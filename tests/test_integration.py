"""Tests for the Solcast Solar integration startup, options and scenarios."""

import asyncio
import contextlib
import copy
import datetime
from datetime import datetime as dt, timedelta
import json
import logging
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import aiohttp
from aiohttp import ClientConnectionError
import pytest
from voluptuous.error import MultipleInvalid

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar.const import (
    API_QUOTA,
    AUTO_UPDATE,
    BRK_ESTIMATE,
    BRK_ESTIMATE10,
    BRK_ESTIMATE90,
    BRK_HALFHOURLY,
    BRK_HOURLY,
    BRK_SITE,
    BRK_SITE_DETAILED,
    CUSTOM_HOUR_SENSOR,
    DOMAIN,
    EVENT_END_DATETIME,
    EVENT_START_DATETIME,
    HARD_LIMIT_API,
    KEY_ESTIMATE,
    SITE,
    UNDAMPENED,
)
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.solcastapi import (
    ConnectionOptions,
    SitesStatus,
    SolcastApi,
)
from homeassistant.components.solcast_solar.util import SolcastConfigEntry
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ServiceValidationError

from . import (
    BAD_INPUT,
    DEFAULT_INPUT1,
    DEFAULT_INPUT2,
    DEFAULT_INPUT_NO_SITES,
    MOCK_BAD_REQUEST,
    MOCK_BUSY,
    MOCK_BUSY_UNEXPECTED,
    MOCK_CORRUPT_ACTUALS,
    MOCK_CORRUPT_FORECAST,
    MOCK_CORRUPT_SITES,
    MOCK_EXCEPTION,
    MOCK_FORBIDDEN,
    MOCK_NOT_FOUND,
    MOCK_OVER_LIMIT,
    ZONE_RAW,
    async_cleanup_integration_tests,
    async_init_integration,
    session_clear,
    session_reset_usage,
    session_set,
)

_LOGGER = logging.getLogger(__name__)

ACTIONS = [
    "clear_all_solcast_data",
    "force_update_forecasts",
    "get_dampening",
    "query_forecast_data",
    "remove_hard_limit",
    "set_dampening",
    "set_hard_limit",
    "update_forecasts",
]

ZONE = ZoneInfo(ZONE_RAW)
NOW = dt.now(ZONE)


@pytest.fixture(autouse=True)
def frozen_time() -> None:
    """Override autouse fixture for this module, disabling use of the freezer feature.

    Time runs in this test suite in real-time, so method replacement is used
    instead of the regular datetime helpers.

    The date is the real date, but the time is spoofed to always be around midday
    for forecast and sensor updates giving predicable responses. Logged time is realtime,
    allowing analysis of performance and waiting for asyncio tasks to complete normally.
    """


def get_now_utc() -> dt:
    """Mock get_now_utc, spoof middle-of-the-day-ish."""

    return NOW.replace(hour=12, minute=27, second=0, microsecond=0).astimezone(datetime.UTC)


def get_real_now_utc() -> dt:
    """Mock get_real_now_utc, spoof middle-of-the-day-ish."""

    return NOW.replace(hour=12, minute=27, second=27, microsecond=27272).astimezone(datetime.UTC)


def get_hour_start_utc() -> dt:
    """Mock get_hour_start_utc, spoof middle-of-the-day-ish."""

    return NOW.replace(hour=12, minute=0, second=0, microsecond=0).astimezone(datetime.UTC)


def patch_solcast_api(solcast):
    """Patch SolcastApi to return a fixed time.

    Cannot use freezegun with these tests because time must tick (the teck= option won't work).
    """
    solcast.get_now_utc = get_now_utc
    solcast.get_real_now_utc = get_real_now_utc
    solcast.get_hour_start_utc = get_hour_start_utc
    return solcast


async def _exec_update(
    hass: HomeAssistant,
    solcast: SolcastApi,
    caplog: any,
    action: str,
    last_update_delta: int = 0,
    wait: bool = True,
    wait_exception: Exception | None = None,
) -> None:
    """Execute an action and wait for completion."""

    caplog.clear()
    if last_update_delta == 0:
        last_updated = dt(year=2020, month=1, day=1, hour=1, minute=1, second=1, tzinfo=datetime.UTC)
    else:
        last_updated = solcast._data["last_updated"] - timedelta(seconds=last_update_delta)
        _LOGGER.info("Mock last updated: %s", last_updated)
    solcast._data["last_updated"] = last_updated
    await hass.services.async_call(DOMAIN, action, {}, blocking=True)
    if wait_exception:
        await _wait_for_raise(hass, wait_exception)
    elif wait:
        await _wait_for_update(caplog)
        await solcast.tasks_cancel()
    await hass.async_block_till_done()


async def _wait_for_update(caplog: any) -> None:
    """Wait for forecast update completion."""

    async with asyncio.timeout(5):
        while (
            "Forecast update completed successfully" not in caplog.text
            and "Not requesting a solar forecast" not in caplog.text
            and "aborting forecast update" not in caplog.text
            and "pausing" not in caplog.text
            and "Completed task update" not in caplog.text
            and "Completed task force_update" not in caplog.text
            and "ConfigEntryAuthFailed" not in caplog.text
        ):  # Wait for task to complete
            await asyncio.sleep(0.01)


async def _wait_for_abort(caplog: any) -> None:
    """Wait for forecast update completion."""

    async with asyncio.timeout(5):
        while (
            "Forecast update aborted" not in caplog.text and "Forecast update already requested, ignoring" not in caplog.text
        ):  # Wait for task to abort
            await asyncio.sleep(0.01)


async def _wait_for_raise(hass: HomeAssistant, exception: Exception) -> None:
    """Wait for exception."""

    async def wait_for_exception():
        async with asyncio.timeout(5):
            while True:
                await hass.async_block_till_done()
                await asyncio.sleep(0.01)

    with pytest.raises(exception):
        await wait_for_exception()


async def _reload(hass: HomeAssistant, entry: SolcastConfigEntry) -> tuple[SolcastUpdateCoordinator | None, SolcastApi | None]:
    """Reload the integration."""

    _LOGGER.warning("Reloading integration")
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    if hass.data[DOMAIN].get(entry.entry_id):
        try:
            coordinator = entry.runtime_data.coordinator
            return coordinator, patch_solcast_api(coordinator.solcast)
        except:  # noqa: E722
            _LOGGER.error("Failed to load coordinator (or solcast), which may be expected given test conditions")
    return None, None


def _no_exception(caplog: pytest.LogCaptureFixture):
    assert "Error" not in caplog.text
    assert "Exception" not in caplog.text


async def test_api_failure(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test API failure."""

    await async_cleanup_integration_tests(hass)
    try:

        def assertions1_busy(entry: SolcastConfigEntry):
            assert entry.state is ConfigEntryState.SETUP_RETRY
            assert "Get sites failed, last call result: 429/Try again later" in caplog.text
            assert "Cached sites are not yet available" in caplog.text
            caplog.clear()

        def assertions1_bad_data(entry: SolcastConfigEntry):
            assert "API did not return a json object, returned" in caplog.text

        def assertions1_except(entry: SolcastConfigEntry):
            assert entry.state is ConfigEntryState.SETUP_ERROR
            assert "Error retrieving sites, attempting to continue" in caplog.text
            assert "Cached sites are not yet available" in caplog.text
            caplog.clear()

        def assertions2_busy(entry: SolcastConfigEntry):
            assert "Get sites failed, last call result: 429/Try again later, using cached data" in caplog.text
            assert "Sites data:" in caplog.text
            caplog.clear()

        def assertions2_except(entry: SolcastConfigEntry):
            assert "Error retrieving sites, attempting to continue" in caplog.text
            assert "Sites data:" in caplog.text
            caplog.clear()

        async def too_busy(assertions: callable):
            session_set(MOCK_BUSY)
            entry = await async_init_integration(hass, DEFAULT_INPUT1)
            assertions(entry)
            session_clear(MOCK_BUSY)

        async def bad_response(assertions: callable):
            for returned in [MOCK_CORRUPT_SITES, MOCK_CORRUPT_ACTUALS, MOCK_CORRUPT_FORECAST]:
                session_set(returned)
                entry = await async_init_integration(hass, DEFAULT_INPUT1)
                assertions(entry)
                session_clear(returned)

        async def exceptions(assertions: callable):
            session_set(MOCK_EXCEPTION, exception=ConnectionRefusedError)
            entry = await async_init_integration(hass, DEFAULT_INPUT1)
            assertions(entry)
            session_set(MOCK_EXCEPTION, exception=TimeoutError)
            entry = await async_init_integration(hass, DEFAULT_INPUT1)
            assertions(entry)
            session_set(MOCK_EXCEPTION, exception=ClientConnectionError)
            entry = await async_init_integration(hass, DEFAULT_INPUT1)
            assertions(entry)
            session_clear(MOCK_EXCEPTION)

        async def exceptions_update():
            for test in [
                {"exception": TimeoutError, "assertion": "Connection error: Timed out", "fatal": True},
                {"exception": ClientConnectionError, "assertion": "Client error", "fatal": True},
                {"exception": ConnectionRefusedError, "assertion": "Connection error, connection refused", "fatal": True},
                {"exception": MOCK_BAD_REQUEST, "assertion": "400/Bad request", "fatal": True},
                {"exception": MOCK_NOT_FOUND, "assertion": "404/Not found", "fatal": True},
                {"exception": MOCK_BUSY, "assertion": "429/Try again later", "fatal": False},
                {"exception": MOCK_BUSY_UNEXPECTED, "assertion": "Unexpected response received", "fatal": True},
                # Forbidden must be last
                {"exception": MOCK_FORBIDDEN, "assertion": "ConfigEntryAuthFailed: API key is invalid", "fatal": True},
            ]:
                if not isinstance(test["exception"], str):
                    session_set(MOCK_EXCEPTION, exception=test["exception"])

                entry: SolcastConfigEntry = await async_init_integration(hass, DEFAULT_INPUT1)
                coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator
                solcast: SolcastApi = patch_solcast_api(coordinator.solcast)
                solcast.options.auto_update = 0
                assert hass.data[DOMAIN].get("presumed_dead", True) is False
                await hass.async_block_till_done()
                caplog.clear()

                if isinstance(test["exception"], str):
                    session_set(test["exception"])
                if test["exception"] == MOCK_FORBIDDEN:
                    await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=20)
                    assert "re-authentication required" in caplog.text
                    with pytest.raises(ConfigEntryAuthFailed):
                        await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=20)
                    solcast.options.auto_update = 1
                    with pytest.raises(ConfigEntryAuthFailed):
                        await _exec_update(hass, solcast, caplog, "force_update_forecasts", last_update_delta=20)
                    solcast.options.auto_update = 0
                else:
                    await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=20)
                    assert test["assertion"] in caplog.text
                    if test["fatal"]:
                        assert "pausing" not in caplog.text

                assert await hass.config_entries.async_unload(entry.entry_id)
                if isinstance(test["exception"], str):
                    session_clear(test["exception"])
                else:
                    session_clear(MOCK_EXCEPTION)

                await hass.config_entries.async_unload(entry.entry_id)
                await hass.async_block_till_done()
            caplog.clear()

        # Test API too busy during get sites without cache
        await too_busy(assertions1_busy)
        # Test exceptions during get sites without cache
        await exceptions(assertions1_except)
        # Test bad responses without cache
        await bad_response(assertions1_bad_data)

        # Normal start and teardown to create caches
        session_clear(MOCK_BUSY)
        entry: SolcastConfigEntry = await async_init_integration(hass, DEFAULT_INPUT1)
        await hass.async_block_till_done()
        assert await hass.config_entries.async_unload(entry.entry_id)

        # Test API too busy during get sites with the cache present
        await too_busy(assertions2_busy)
        # Test exceptions during get sites with the cache present
        await exceptions(assertions2_except)

        # Test forecast update exceptions
        await exceptions_update()

    finally:
        session_clear(MOCK_BAD_REQUEST)
        session_clear(MOCK_BUSY)
        session_clear(MOCK_BUSY_UNEXPECTED)
        session_clear(MOCK_EXCEPTION)
        session_clear(MOCK_FORBIDDEN)
        session_clear(MOCK_NOT_FOUND)

        assert await async_cleanup_integration_tests(hass)


async def test_schema_upgrade(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test various integration scenarios."""

    config_dir = hass.config.config_dir

    options = copy.deepcopy(DEFAULT_INPUT1)
    options[CONF_API_KEY] = "2"
    entry: SolcastConfigEntry = await async_init_integration(hass, options)
    coordinator = entry.runtime_data.coordinator
    solcast = patch_solcast_api(coordinator.solcast)
    try:
        data_file = Path(f"{config_dir}/solcast.json")
        undampened_file = Path(f"{config_dir}/solcast-undampened.json")
        original_data = json.loads(data_file.read_text(encoding="utf-8"))

        def set_old_solcast_schema(data_file):
            data = copy.deepcopy(original_data)
            data["version"] = 4
            data.pop("last_attempt")
            data.pop("auto_updated")
            data_file.write_text(json.dumps(data), encoding="utf-8")

        def set_ancient_solcast_schema(data_file):
            data = copy.deepcopy(original_data)
            data.pop("version")
            data.pop("last_attempt")
            data.pop("auto_updated")
            data["forecasts"] = data["siteinfo"]["3333-3333-3333-3333"]["forecasts"].copy()
            data.pop("siteinfo")
            data_file.write_text(json.dumps(data), encoding="utf-8")

        def set_incompatible_schema1(data_file):
            data = copy.deepcopy(original_data)
            data.pop("version")
            data.pop("siteinfo")
            data.pop("last_attempt")
            data.pop("auto_updated")
            data["some_stuff"] = {"fraggle": "rock"}
            data_file.write_text(json.dumps(data), encoding="utf-8")

        def set_incompatible_schema2(data_file):
            data = copy.deepcopy(original_data)
            data.pop("version")
            data["siteinfo"] = {"weird": "stuff"}
            data["forecasts"] = "favourable"
            data.pop("last_attempt")
            data.pop("auto_updated")
            data_file.write_text(json.dumps(data), encoding="utf-8")

        def verify_new_solcast_schema(data_file):
            data = json.loads(data_file.read_text(encoding="utf-8"))
            assert data["version"] == 6
            assert "last_attempt" in data
            assert "auto_updated" in data

        def kill_undampened_cache():
            with contextlib.suppress(FileNotFoundError):
                undampened_file.unlink()

        # Test upgrade schema version
        kill_undampened_cache()
        set_old_solcast_schema(data_file)
        coordinator, solcast = await _reload(hass, entry)
        assert "version from v4 to v6" in caplog.text
        assert "Migrating un-dampened history" in caplog.text
        verify_new_solcast_schema(data_file)
        caplog.clear()

        # Test upgrade from v3 schema
        kill_undampened_cache()
        set_ancient_solcast_schema(data_file)
        coordinator, solcast = await _reload(hass, entry)
        assert "version from v1 to v6" in caplog.text
        assert "Migrating un-dampened history" in caplog.text
        verify_new_solcast_schema(data_file)
        caplog.clear()

        # Test upgrade from incompatible schema 1
        kill_undampened_cache()
        set_incompatible_schema1(data_file)
        coordinator, solcast = await _reload(hass, entry)
        assert "CRITICAL" in caplog.text
        assert solcast is None
        caplog.clear()

        # Test upgrade from incompatible schema 2
        kill_undampened_cache()
        set_incompatible_schema2(data_file)
        coordinator, solcast = await _reload(hass, entry)
        assert "CRITICAL" in caplog.text
        assert solcast is None

    finally:
        assert await async_cleanup_integration_tests(hass)


@pytest.mark.parametrize(
    "options",
    [
        BAD_INPUT,
        DEFAULT_INPUT_NO_SITES,
        DEFAULT_INPUT1,
        DEFAULT_INPUT2,
    ],
)
async def test_integration(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    options: dict,
) -> None:
    """Test integration init."""

    config_dir = hass.config.config_dir

    # Test startup
    entry: SolcastConfigEntry = await async_init_integration(hass, options)

    if options == BAD_INPUT:
        assert entry.state is ConfigEntryState.SETUP_ERROR
        assert hass.data[DOMAIN].get("presumed_dead", True) is True
        assert "Dampening factors corrupt or not found, setting to 1.0" in caplog.text
        assert "Get sites failed, last call result: 403/Forbidden" in caplog.text
        assert "API key is invalid" in caplog.text
        return

    if options == DEFAULT_INPUT_NO_SITES:
        assert entry.state is ConfigEntryState.SETUP_ERROR
        assert "HTTP session returned status 200/Success" in caplog.text
        assert "No sites for the API key ******_sites are configured at solcast.com" in caplog.text
        assert "No sites found for API key" in caplog.text
        return

    assert entry.state is ConfigEntryState.LOADED
    assert hass.data[DOMAIN].get("presumed_dead", True) is False

    coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator
    solcast: SolcastApi = patch_solcast_api(coordinator.solcast)
    granular_dampening_file = Path(f"{config_dir}/solcast-dampening.json")
    if options == DEFAULT_INPUT2:
        assert granular_dampening_file.is_file()
    coordinator.set_next_update()

    try:
        assert solcast.sites_status is SitesStatus.OK
        assert solcast._loaded_data is True
        assert "Dampening factors corrupt or not found, setting to 1.0" not in caplog.text
        assert solcast._tz == ZONE

        # Test cache files are as expected
        if len(options["api_key"].split(",")) == 1:
            assert not Path(f"{config_dir}/solcast-sites-1.json").is_file()
            assert not Path(f"{config_dir}/solcast-sites-2.json").is_file()
            assert Path(f"{config_dir}/solcast-sites.json").is_file()
            assert not Path(f"{config_dir}/solcast-usage-1.json").is_file()
            assert not Path(f"{config_dir}/solcast-usage-2.json").is_file()
            assert Path(f"{config_dir}/solcast-usage.json").is_file()
        else:
            assert Path(f"{config_dir}/solcast-sites-1.json").is_file()
            assert Path(f"{config_dir}/solcast-sites-2.json").is_file()
            assert not Path(f"{config_dir}/solcast-sites.json").is_file()
            assert Path(f"{config_dir}/solcast-usage-1.json").is_file()
            assert Path(f"{config_dir}/solcast-usage-2.json").is_file()
            assert not Path(f"{config_dir}/solcast-usage.json").is_file()

        # Test coordinator tasks are created
        assert coordinator.tasks["listeners"]
        assert coordinator.tasks["check_fetch"]
        assert coordinator.tasks["midnight_update"]

        # Test expected services are registered
        assert len(hass.services.async_services_for_domain(DOMAIN).keys()) == len(ACTIONS)
        for service in ACTIONS:
            assert hass.services.has_service(DOMAIN, service) is True

        # Test refused update without forcing
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, "update_forecasts", {}, blocking=True)

        # Test forced update and clear data actions
        await _exec_update(hass, solcast, caplog, "force_update_forecasts")

        # Test for API key redaction
        for api_key in options["api_key"].split(","):
            assert "key=" + api_key not in caplog.text
            assert "key: " + api_key not in caplog.text
            assert "sites-" + api_key not in caplog.text
            assert "usage-" + api_key not in caplog.text

        # Test force, force abort because running and clear data actions
        await _exec_update(hass, solcast, caplog, "force_update_forecasts", wait=False)
        caplog.clear()
        await _exec_update(hass, solcast, caplog, "force_update_forecasts", wait=False)  # Twice to cover abort force
        await _wait_for_abort(caplog)
        await _exec_update(hass, solcast, caplog, "update_forecasts", wait=False)  # Thrice to cover abort normal
        await _wait_for_abort(caplog)
        await hass.async_block_till_done()
        await _exec_update(hass, solcast, caplog, "clear_all_solcast_data")  # Will cancel active fetch

        # Test update within ten seconds of prior update
        solcast.options.auto_update = 0
        await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=5)
        assert "Not requesting a solar forecast because time is within ten seconds of last update" in caplog.text
        assert "ERROR" not in caplog.text

        _no_exception(caplog)

        # Test API too busy encountered for first site
        caplog.clear()
        session_set(MOCK_BUSY)
        solcast.options.auto_update = 0
        await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=20)
        assert "seconds before retry" in caplog.text
        assert "ERROR" not in caplog.text
        await hass.async_block_till_done()
        session_clear(MOCK_BUSY)

        # Simulate exceed API limit and beyond
        caplog.clear()
        session_set(MOCK_OVER_LIMIT)
        await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=20)
        assert "API allowed polling limit has been exceeded" in caplog.text
        assert "No data was returned for forecasts" in caplog.text
        caplog.clear()
        _no_exception(caplog)
        await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=20)
        assert "API polling limit exhausted, not getting forecast" in caplog.text
        caplog.clear()
        _no_exception(caplog)
        session_clear(MOCK_OVER_LIMIT)

        # Create a granular dampening file to be read on next update
        granular_dampening = (
            {"1111-1111-1111-1111": [0.8] * 48, "2222-2222-2222-2222": [0.9] * 48}
            if options == DEFAULT_INPUT1
            else {
                "1111-1111-1111-1111": [0.7] * 24,  # Intentionally dodgy
                "2222-2222-2222-2222": [0.8] * 42,  # Intentionally dodgy
                "3333-3333-3333-3333": [0.9] * 48,
            }
        )
        granular_dampening_file.write_text(json.dumps(granular_dampening), encoding="utf-8")
        assert granular_dampening_file.is_file()

        # Test update beyond ten seconds of prior update, also with stale usage cache and dodgy dampening file
        session_reset_usage()
        for api_key in options["api_key"].split(","):
            solcast._api_used_reset[api_key] = dt.now(datetime.UTC) - timedelta(days=5)
        solcast.options.auto_update = 0
        await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=20)
        assert "Not requesting a solar forecast because time is within ten seconds of last update" not in caplog.text
        assert "resetting API usage" in caplog.text
        assert "Writing API usage cache file" in caplog.text
        assert "Started task midnight_update" in caplog.text
        if options == DEFAULT_INPUT2:
            assert "Number of dampening factors for all sites must be the same" in caplog.text
            assert "must be 24 or 48 in" in caplog.text
            assert "Forecast update completed successfully" in caplog.text
        else:
            assert "Granular dampening reloaded" in caplog.text
            assert "Forecast update completed successfully" in caplog.text
            assert "contains all intervals" in caplog.text
        _no_exception(caplog)
        caplog.clear()

        def set_file_last_modified(file_path, dt):
            dt_epoch = dt.timestamp()
            os.utime(file_path, (dt_epoch, dt_epoch))

        granular_dampening_file.write_text("really dodgy", encoding="utf-8")
        set_file_last_modified(str(granular_dampening_file), dt.now(datetime.UTC) - timedelta(minutes=5))
        await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=20)
        assert "JSONDecodeError, dampening ignored" in caplog.text
        caplog.clear()

        # Test reset usage cache when fresh
        for api_key in options["api_key"].split(","):
            solcast._api_used_reset[api_key] = solcast._api_used_reset[api_key] - timedelta(hours=24)
        await solcast.reset_api_usage()
        assert "Reset API usage" in caplog.text
        await solcast.reset_api_usage()
        assert "Usage cache is fresh, so not resetting" in caplog.text

        # Test clear data action when no solcast.json exists
        if options == DEFAULT_INPUT2:
            Path(f"{config_dir}/solcast.json").unlink()
            Path(f"{config_dir}/solcast-undampened.json").unlink()
            await hass.services.async_call(DOMAIN, "clear_all_solcast_data", {}, blocking=True)
            await hass.async_block_till_done()
            assert "There is no solcast-undampened.json to delete" in caplog.text
            assert "There is no solcast.json to delete" in caplog.text
            assert "There is no solcast.json to load" in caplog.text
            assert "Polling API for site 1111-1111-1111-1111" in caplog.text
            assert "Polling API for site 2222-2222-2222-2222" in caplog.text
            assert "Polling API for site 3333-3333-3333-3333" in caplog.text

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

        session_reset_usage()

    finally:
        assert await async_cleanup_integration_tests(
            hass,
            solcast_dampening=options != DEFAULT_INPUT1,  # Keep dampening file from the DEFAULT_INPUT1 test
            solcast_sites=options != DEFAULT_INPUT1,  # Keep sites cache file from the DEFAULT_INPUT1 test
        )


async def test_integration_remaining_actions(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test remaining actions."""

    config_dir = hass.config.config_dir

    # Start with two API keys and three sites
    entry = await async_init_integration(hass, DEFAULT_INPUT2)
    assert hass.data[DOMAIN].get("presumed_dead", True) is False
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    _no_exception(caplog)
    caplog.clear()

    # Switch to one API key and two sites to assert the initial clean-up
    _LOGGER.debug("Swithching to one API key and two sites")
    entry = await async_init_integration(hass, DEFAULT_INPUT1)
    solcast: SolcastApi = patch_solcast_api(entry.runtime_data.coordinator.solcast)
    assert hass.data[DOMAIN].get("presumed_dead", True) is False

    def occurs_in_log(text: str, occurrences: int) -> int:
        occurs = 0
        for entry in caplog.messages:
            if text in entry:
                occurs += 1
        assert occurrences == occurs

    try:
        # Test logs for cache load
        assert "Sites cache exists" in caplog.text
        assert f"Data cache {config_dir}/solcast.json exists, file type is <class 'dict'>" in caplog.text
        assert f"Data cache {config_dir}/solcast-undampened.json exists, file type is <class 'dict'>" in caplog.text
        occurs_in_log("Renaming", 2)
        occurs_in_log("Removing orphaned", 2)

        # Forced update when auto-update is disabled
        _LOGGER.debug("Test forced update when auto-update is disabled")
        solcast.options.auto_update = 0
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, "force_update_forecasts", {}, blocking=True)

        # Test set/get dampening factors
        async def _clear_granular_dampening():
            # Clear granular dampening
            await hass.services.async_call(DOMAIN, "set_dampening", {"damp_factor": ("1.0," * 24)[:-1]}, blocking=True)
            await hass.async_block_till_done()  # Because options change
            dampening = await hass.services.async_call(DOMAIN, "get_dampening", {}, blocking=True, return_response=True)
            assert dampening.get("data", [{}])[0] == {
                "site": "all",
                "damp_factor": ("1.0," * 24)[:-1],
            }

        dampening = await hass.services.async_call(DOMAIN, "get_dampening", {}, blocking=True, return_response=True)
        assert dampening.get("data", [{}])[0] == {
            "site": "all",
            "damp_factor": ("1.0," * 24)[:-1],
        }
        odd_factors = [
            {"set": {}, "expect": MultipleInvalid},  # No factors
            {"set": {"damp_factor": "  "}, "expect": ServiceValidationError},  # No factors
            {"set": {"damp_factor": ("0.5," * 5)[:-1]}, "expect": ServiceValidationError},  # Insufficient factors
            {"set": {"damp_factor": ("0.5," * 15)[:-1]}, "expect": ServiceValidationError},  # Not 24 or 48 factors
            {"set": {"damp_factor": ("1.5," * 24)[:-1]}, "expect": ServiceValidationError},  # Out of range factors
            {"set": {"damp_factor": ("0.8f," * 24)[:-1]}, "expect": ServiceValidationError},  # Weird factors
            {
                "set": {"site": "all", "damp_factor": ("1.0," * 24)[:-1]},
                "expect": ServiceValidationError,
            },  # Site with 24 dampening factors
        ]
        for factors in odd_factors:
            _LOGGER.debug("Test set odd dampening factors: %s", factors)
            with pytest.raises(factors["expect"]):
                await hass.services.async_call(DOMAIN, "set_dampening", factors["set"], blocking=True)

        _LOGGER.debug("Test set various dampening factors")
        await hass.services.async_call(DOMAIN, "set_dampening", {"damp_factor": ("0.5," * 24)[:-1]}, blocking=True)
        await hass.async_block_till_done()  # Because options change
        dampening = await hass.services.async_call(DOMAIN, "get_dampening", {}, blocking=True, return_response=True)
        assert dampening.get("data", [{}])[0] == {"site": "all", "damp_factor": ("0.5," * 24)[:-1]}
        # Granular dampening
        await hass.services.async_call(DOMAIN, "set_dampening", {"damp_factor": ("0.5," * 48)[:-1]}, blocking=True)
        await hass.async_block_till_done()  # Because options change
        assert Path(f"{config_dir}/solcast-dampening.json").is_file()
        dampening = await hass.services.async_call(DOMAIN, "get_dampening", {}, blocking=True, return_response=True)
        assert dampening.get("data", [{}])[0] == {"site": "all", "damp_factor": ("0.5," * 48)[:-1]}
        # Trigger re-apply forward dampening
        await hass.services.async_call(DOMAIN, "set_dampening", {"damp_factor": ("0.75," * 48)[:-1]}, blocking=True)
        await hass.async_block_till_done()  # Because options change
        await _clear_granular_dampening()

        # Request dampening for a site when using legacy dampening
        with pytest.raises(ServiceValidationError):
            dampening = await hass.services.async_call(
                DOMAIN, "get_dampening", {"site": "1111-1111-1111-1111"}, blocking=True, return_response=True
            )
        # Granular dampening with site
        _LOGGER.debug("Test granular dampening with site")
        await hass.services.async_call(
            DOMAIN, "set_dampening", {"site": "1111-1111-1111-1111", "damp_factor": ("0.5," * 48)[:-1]}, blocking=True
        )
        await hass.async_block_till_done()  # Because options change
        dampening = await hass.services.async_call(DOMAIN, "get_dampening", {}, blocking=True, return_response=True)
        assert dampening.get("data", [{}])[0] == {"site": "1111-1111-1111-1111", "damp_factor": ("0.5," * 48)[:-1]}
        dampening = await hass.services.async_call(
            DOMAIN, "get_dampening", {"site": "1111-1111-1111-1111"}, blocking=True, return_response=True
        )
        assert dampening.get("data", [{}])[0] == {"site": "1111-1111-1111-1111", "damp_factor": ("0.5," * 48)[:-1]}
        with pytest.raises(ServiceValidationError):
            dampening = await hass.services.async_call(
                DOMAIN, "set_dampening", {"site": "9999-9999-9999-9999", "damp_factor": ("0.5," * 48)[:-1]}, blocking=True
            )
        with pytest.raises(ServiceValidationError):
            dampening = await hass.services.async_call(
                DOMAIN, "get_dampening", {"site": "9999-9999-9999-9999"}, blocking=True, return_response=True
            )
        await hass.services.async_call(DOMAIN, "set_dampening", {"site": "all", "damp_factor": ("0.5," * 48)[:-1]}, blocking=True)
        caplog.clear()
        dampening = await hass.services.async_call(
            DOMAIN, "get_dampening", {"site": "1111-1111-1111-1111"}, blocking=True, return_response=True
        )
        assert "being overridden by an all sites entry" in caplog.text
        dampening = await hass.services.async_call(
            DOMAIN, "get_dampening", {"site": "2222-2222-2222-2222"}, blocking=True, return_response=True
        )
        assert "being overridden by an all sites entry" in caplog.text
        await _clear_granular_dampening()

        # Test set/clear hard limit
        odd_limits = [
            {"set": {}, "expect": MultipleInvalid},  # No hard limit
            {"set": {"hard_limit": "zzzzzz"}, "expect": ServiceValidationError},  # Silly hard limit
            {"set": {"hard_limit": "-5"}, "expect": ServiceValidationError},  # Negative hard limit
            {"set": {"hard_limit": "5.0,5.0,5.0"}, "expect": ServiceValidationError},  # Too many hard limits
        ]
        for limits in odd_limits:
            _LOGGER.debug("Test set odd hard limit: %s", limits)
            with pytest.raises(limits["expect"]):
                await hass.services.async_call(DOMAIN, "set_hard_limit", limits["set"], blocking=True)

        async def _set_hard_limit(hard_limit: str) -> None:
            await hass.services.async_call(DOMAIN, "set_hard_limit", {"hard_limit": hard_limit}, blocking=True)
            await hass.async_block_till_done()
            return patch_solcast_api(entry.runtime_data.coordinator.solcast)  # Because integration reloads

        async def _remove_hard_limit() -> None:
            await hass.services.async_call(DOMAIN, "remove_hard_limit", {}, blocking=True)
            await hass.async_block_till_done()
            return patch_solcast_api(entry.runtime_data.coordinator.solcast)  # Because integration reloads

        _LOGGER.debug("Test set reasonable hard limit")
        solcast = await _set_hard_limit("5.0")
        assert solcast.hard_limit == "5.0"
        assert "Build hard limit period values from scratch for dampened" in caplog.text
        assert "Build hard limit period values from scratch for un-dampened" in caplog.text
        for estimate in ["pv_estimate", "pv_estimate10", "pv_estimate90"]:
            assert len(solcast._sites_hard_limit["all"][estimate]) > 0
            assert len(solcast._sites_hard_limit_undampened["all"][estimate]) > 0

        _LOGGER.debug("Test set large hard limit")
        solcast = await _set_hard_limit("5000")
        assert solcast.hard_limit == "5000.0"
        assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set").state == "5.0 MW"

        _LOGGER.debug("Test set huge hard limit")
        solcast = await _set_hard_limit("5000000")
        assert solcast.hard_limit == "5000000.0"
        assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set").state == "5.0 GW"

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

        assert "ERROR" not in caplog.text
        caplog.clear()

        # Switch to using two API keys, three sites, start with an out-of-date usage cache
        _LOGGER.debug("Switch to using two API keys, three sites")
        usage_file = Path(f"{config_dir}/solcast-usage.json")
        data = json.loads(usage_file.read_text(encoding="utf-8"))
        data["reset"] = (dt.now(datetime.UTC) - timedelta(days=5)).isoformat()
        usage_file.write_text(json.dumps(data), encoding="utf-8")
        config = copy.deepcopy(DEFAULT_INPUT2)
        config[API_QUOTA] = "8,8"
        session_reset_usage()
        entry = await async_init_integration(hass, config)

        _LOGGER.debug("Test disable hard limit")
        solcast = await _set_hard_limit("100.0,100.0")
        assert solcast.hard_limit == "100.0,100.0"
        assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set_1").state == "False"
        assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set_2").state == "False"

        _LOGGER.debug("Test set hard limit for both API keys")
        solcast = await _set_hard_limit("5.0,5.0")
        assert solcast.hard_limit == "5.0,5.0"
        assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set_1").state == "5.0 kW"
        assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set_2").state == "5.0 kW"
        assert "Build hard limit period values from scratch for dampened" in caplog.text
        assert "Build hard limit period values from scratch for un-dampened" in caplog.text
        for api_key in entry.options["api_key"].split(","):
            for estimate in ["pv_estimate", "pv_estimate10", "pv_estimate90"]:
                assert len(solcast._sites_hard_limit[api_key][estimate]) > 0
                assert len(solcast._sites_hard_limit_undampened[api_key][estimate]) > 0

        _LOGGER.debug("Test set single hard limit value for both API keys")
        solcast = await _remove_hard_limit()
        assert solcast.hard_limit == "100.0"
        for estimate in ["pv_estimate", "pv_estimate10", "pv_estimate90"]:
            assert len(solcast._sites_hard_limit["all"][estimate]) == 0
            assert len(solcast._sites_hard_limit_undampened["all"][estimate]) == 0

        # Test query forecast data
        queries = [
            {
                "query": {
                    EVENT_START_DATETIME: solcast.get_day_start_utc().isoformat(),
                    EVENT_END_DATETIME: solcast.get_day_start_utc(future=1).isoformat(),
                },
                "expect": 48,
            },
            {
                "query": {
                    EVENT_START_DATETIME: solcast.get_day_start_utc().isoformat(),
                    EVENT_END_DATETIME: solcast.get_day_start_utc(future=1).isoformat(),
                    UNDAMPENED: True,
                },
                "expect": 48,
            },
            {
                "query": {
                    EVENT_START_DATETIME: (solcast.get_day_start_utc(future=-1) + timedelta(hours=3)).isoformat(),
                    EVENT_END_DATETIME: solcast.get_day_start_utc().isoformat(),
                    SITE: "1111-1111-1111-1111",
                },
                "expect": 42,
            },
            {
                "query": {
                    EVENT_START_DATETIME: solcast.get_day_start_utc(future=-3).isoformat(),
                    EVENT_END_DATETIME: solcast.get_day_start_utc(future=-1).isoformat(),
                    SITE: "2222-2222-2222-2222",
                    UNDAMPENED: True,
                },
                "expect": 96,
            },
        ]
        for query in queries:
            _LOGGER.debug("Testing query forecast data: %s", query["query"])
            forecast_data = await hass.services.async_call(
                DOMAIN, "query_forecast_data", query["query"], blocking=True, return_response=True
            )
            assert len(forecast_data.get("data", [])) == query["expect"]

        assert "ERROR" not in caplog.text

        # Test invalid query range
        _LOGGER.debug("Testing invalid query range")
        with pytest.raises(ServiceValidationError):
            forecast_data = await hass.services.async_call(
                DOMAIN,
                "query_forecast_data",
                {
                    EVENT_START_DATETIME: solcast.get_day_start_utc(future=10).isoformat(),
                    EVENT_END_DATETIME: solcast.get_day_start_utc(future=16).isoformat(),
                },
                blocking=True,
                return_response=True,
            )

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

        # Test call an action with no entry loaded
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, "update_forecasts", {}, blocking=True)
        assert "Integration not loaded" in caplog.text

        _no_exception(caplog)

    finally:
        assert await async_cleanup_integration_tests(hass)


async def test_integration_scenarios(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test various integration scenarios."""

    config_dir = hass.config.config_dir

    options = copy.deepcopy(DEFAULT_INPUT1)
    options[HARD_LIMIT_API] = "6.0"
    entry = await async_init_integration(hass, options)
    coordinator = entry.runtime_data.coordinator
    solcast = patch_solcast_api(coordinator.solcast)

    try:
        # Test bad serialise data while an entry exists
        _LOGGER.debug("Testing bad serialise data")
        async with aiohttp.ClientSession() as session:
            connection_options = ConnectionOptions(
                DEFAULT_INPUT1[CONF_API_KEY],
                DEFAULT_INPUT1[API_QUOTA],
                "api.whatever.com",
                config_dir,
                ZONE_RAW,
                DEFAULT_INPUT1[AUTO_UPDATE],
                {str(hour): DEFAULT_INPUT1[f"damp{hour:02}"] for hour in range(24)},
                DEFAULT_INPUT1[CUSTOM_HOUR_SENSOR],
                DEFAULT_INPUT1[KEY_ESTIMATE],
                DEFAULT_INPUT1[HARD_LIMIT_API],
                DEFAULT_INPUT1[BRK_ESTIMATE],
                DEFAULT_INPUT1[BRK_ESTIMATE10],
                DEFAULT_INPUT1[BRK_ESTIMATE90],
                DEFAULT_INPUT1[BRK_SITE],
                DEFAULT_INPUT1[BRK_HALFHOURLY],
                DEFAULT_INPUT1[BRK_HOURLY],
                DEFAULT_INPUT1[BRK_SITE_DETAILED],
            )
            solcast_bad: SolcastApi = SolcastApi(session, connection_options, hass, entry)
            await solcast_bad.serialise_data(solcast_bad._data, Path(f"{config_dir}/solcast.json"))
            assert "Not serialising empty data" in caplog.text

        # Assert good start
        _LOGGER.debug("Testing good start happened")
        assert hass.data[DOMAIN].get("presumed_dead", True) is False
        assert "Hard limit is set to limit peak forecast values" in caplog.text
        _no_exception(caplog)
        caplog.clear()

        # Test start with stale data
        data_file = Path(f"{config_dir}/solcast.json")
        original_data = json.loads(data_file.read_text(encoding="utf-8"))

        def alter_last_updated_as_stale():
            data = json.loads(data_file.read_text(encoding="utf-8"))
            data["last_updated"] = (dt.now(datetime.UTC) - timedelta(days=5)).isoformat()
            data["last_attempt"] = data["last_updated"]
            data["auto_updated"] = 10
            # Remove forecasts today up to "now"
            for site in data["siteinfo"].values():
                site["forecasts"] = [f for f in site["forecasts"] if f["period_start"] > dt.now(datetime.UTC).isoformat()]
            data_file.write_text(json.dumps(data), encoding="utf-8")
            session_reset_usage()

        def alter_last_updated_as_fresh(last_update: str):
            data = json.loads(data_file.read_text(encoding="utf-8"))
            data["last_updated"] = last_update
            data["last_attempt"] = data["last_updated"]
            data["auto_updated"] = 10
            data_file.write_text(json.dumps(data), encoding="utf-8")

        def restore_data():
            data_file.write_text(json.dumps(original_data), encoding="utf-8")

        # Test stale start with auto update enabled
        _LOGGER.debug("Testing stale start with auto update enabled")
        alter_last_updated_as_stale()
        coordinator, solcast = await _reload(hass, entry)
        await _wait_for_update(caplog)
        assert "is older than expected, should be" in caplog.text
        assert solcast._data["last_updated"] > dt.now(datetime.UTC) - timedelta(minutes=10)
        assert "ERROR" not in caplog.text
        _no_exception(caplog)

        # Get last auto-update time for a subsequent test
        last_update = ""
        for line in caplog.messages:
            if line.startswith("Previous auto update UTC "):
                last_update = line[-25:]
                break

        caplog.clear()

        # Test stale start with auto update disabled
        _LOGGER.debug("Testing stale start with auto update disabled")
        opt = {**entry.options}
        opt[AUTO_UPDATE] = 0
        hass.config_entries.async_update_entry(entry, options=opt)
        await hass.async_block_till_done()
        alter_last_updated_as_stale()
        coordinator, solcast = await _reload(hass, entry)
        _no_exception(caplog)
        caplog.clear()

        restore_data()

        # Re-enable auto-update, re-load integration, test forecast is fresh
        _LOGGER.debug("Testing start with fresh auto updated data")
        alter_last_updated_as_fresh(last_update)
        opt = {**entry.options}
        opt[AUTO_UPDATE] = 1
        hass.config_entries.async_update_entry(entry, options=opt)
        await hass.async_block_till_done()
        assert "Auto update forecast is fresh" in caplog.text

        # Test API key change, start with an API failure and invalid sites cache
        # Verify API key change removes sites, and migrates undampened history for new site
        _LOGGER.debug("Testing API key change")
        session_set(MOCK_BUSY)
        sites_file = Path(f"{config_dir}/solcast-sites.json")
        data = json.loads(sites_file.read_text(encoding="utf-8"))
        data["sites"][0].pop("api_key")
        data["sites"][1]["api_key"] = "888"
        sites_file.write_text(json.dumps(data), encoding="utf-8")
        opt = {**entry.options}
        opt[CONF_API_KEY] = "2"
        hass.config_entries.async_update_entry(entry, options=opt)
        await hass.async_block_till_done()
        assert "Options updated, action: The integration will reload" in caplog.text
        assert "has changed and sites are different invalidating the cache" in caplog.text
        session_clear(MOCK_BUSY)
        caplog.clear()
        coordinator, solcast = await _reload(hass, entry)
        assert "An API key has changed, resetting usage" in caplog.text
        assert "Reset API usage" in caplog.text
        assert "New site(s) have been added" in caplog.text
        assert "Site resource id 1111-1111-1111-1111 is no longer configured" in caplog.text
        assert "Site resource id 2222-2222-2222-2222 is no longer configured" in caplog.text
        _no_exception(caplog)
        caplog.clear()

        # Test corrupt cache start, integration will mostly not load, and will not attempt reload
        # Must be the final test because it will leave the integration in a bad state

        corrupt = "Purple monkey dishwasher 🤣🤣🤣"
        sites_file = Path(f"{config_dir}/solcast-sites.json")
        sites = json.loads(sites_file.read_text(encoding="utf-8"))
        usage_file = Path(f"{config_dir}/solcast-usage.json")
        usage = json.loads(usage_file.read_text(encoding="utf-8"))

        def _really_corrupt_data():
            data_file.write_text(corrupt, encoding="utf-8")

        def _corrupt_data():
            data = json.loads(data_file.read_text(encoding="utf-8"))
            data["siteinfo"]["3333-3333-3333-3333"]["forecasts"] = [{"bob": 0}]
            data_file.write_text(json.dumps(data), encoding="utf-8")

        # Corrupt sites.json
        _LOGGER.debug("Testing corruption: sites.json")
        session_set(MOCK_BUSY)
        sites_file.write_text(corrupt, encoding="utf-8")
        await _reload(hass, entry)
        assert "Exception in __sites_data(): Expecting value:" in caplog.text
        sites_file.write_text(json.dumps(sites), encoding="utf-8")
        session_clear(MOCK_BUSY)
        caplog.clear()

        # Corrupt usage.json
        usage_corruption = [
            {"daily_limit": "10", "daily_limit_consumed": 8, "reset": "2025-01-05T00:00:00+00:00"},
            {"daily_limit": 10, "daily_limit_consumed": "8", "reset": "2025-01-05T00:00:00+00:00"},
            {"daily_limit": 10, "daily_limit_consumed": 8, "reset": "notadate"},
        ]
        for test in usage_corruption:
            _LOGGER.debug("Testing usage corruption: %s", test)
            usage_file.write_text(json.dumps(test), encoding="utf-8")
            await _reload(hass, entry)
            assert entry.state is ConfigEntryState.SETUP_ERROR
        usage_file.write_text(corrupt, encoding="utf-8")
        await _reload(hass, entry)
        assert "corrupt, re-creating cache with zero usage" in caplog.text
        usage_file.write_text(json.dumps(usage), encoding="utf-8")
        caplog.clear()

        # Corrupt solcast.json
        _LOGGER.debug("Testing corruption: solcast.json")
        _corrupt_data()
        await _reload(hass, entry)
        assert hass.data[DOMAIN].get("presumed_dead", True) is True
        caplog.clear()

        _LOGGER.debug("Testing extreme corruption: solcast.json")
        _really_corrupt_data()
        await _reload(hass, entry)
        assert "The cached data in solcast.json is corrupt" in caplog.text
        assert "integration not ready yet" in caplog.text
        assert hass.data[DOMAIN].get("presumed_dead", True) is True

    finally:
        assert await async_cleanup_integration_tests(hass)
