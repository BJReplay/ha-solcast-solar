"""Tests for the Solcast Solar integration startup, options and scenarios."""

import asyncio
from collections.abc import Callable
import contextlib
import copy
import datetime
from datetime import datetime as dt, timedelta
import json
import logging
import os
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp
from aiohttp import ClientConnectionError
import pytest
from voluptuous.error import MultipleInvalid

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar.const import (
    API_QUOTA,
    AUTO_DAMPEN,
    AUTO_UPDATE,
    BRK_ESTIMATE,
    BRK_ESTIMATE10,
    BRK_ESTIMATE90,
    BRK_HALFHOURLY,
    BRK_HOURLY,
    BRK_SITE,
    BRK_SITE_DETAILED,
    CONFIG_DISCRETE_NAME,
    CONFIG_FOLDER_DISCRETE,
    CUSTOM_HOUR_SENSOR,
    DEFAULT_FORECAST_DAYS,
    DELAYED_RESTART_ON_CRASH,
    DOMAIN,
    EVENT_END_DATETIME,
    EVENT_START_DATETIME,
    EXCLUDE_SITES,
    GENERATION_ENTITIES,
    GET_ACTUALS,
    HARD_LIMIT_API,
    KEY_ESTIMATE,
    PRESUMED_DEAD,
    PRIOR_CRASH_TIME,
    SITE,
    SITE_EXPORT_ENTITY,
    SITE_EXPORT_LIMIT,
    UNDAMPENED,
    USE_ACTUALS,
)
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.solcastapi import (
    ConnectionOptions,
    SitesStatus,
    SolcastApi,
)
from homeassistant.components.solcast_solar.util import AutoUpdate
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from . import (
    BAD_INPUT,
    DEFAULT_INPUT1,
    DEFAULT_INPUT2,
    DEFAULT_INPUT_NO_SITES,
    MOCK_ALTER_HISTORY,
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
    verify_data_schema,
)

_LOGGER = logging.getLogger(__name__)

ACTIONS = [
    "clear_all_solcast_data",
    "force_update_estimates",
    "force_update_forecasts",
    "get_dampening",
    "query_estimate_data",
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


def patch_solcast_api(solcast: SolcastApi) -> SolcastApi:
    """Patch SolcastApi to return a fixed time.

    Cannot use freezegun with these tests because time must tick (the tick= option won't work).
    """
    solcast.get_now_utc = get_now_utc  # type: ignore[method-assign]
    solcast.get_real_now_utc = get_real_now_utc  # type: ignore[method-assign]
    solcast.get_hour_start_utc = get_hour_start_utc  # type: ignore[method-assign]
    return solcast


async def _exec_update(
    hass: HomeAssistant,
    solcast: SolcastApi,
    caplog: pytest.LogCaptureFixture,
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
        last_updated = solcast._data["last_updated"] - timedelta(seconds=last_update_delta)  # pyright: ignore[reportPrivateUsage]
        _LOGGER.info("Mock last updated: %s", last_updated)
    solcast._data["last_updated"] = last_updated  # pyright: ignore[reportPrivateUsage]
    await hass.services.async_call(DOMAIN, action, {}, blocking=True)
    if wait_exception:
        await _wait_for_raise(hass, wait_exception)
    elif wait:
        await _wait_for_update(hass, caplog)
        await solcast.tasks_cancel()
    await hass.async_block_till_done()


async def _exec_update_actuals(
    hass: HomeAssistant,
    coordinator: SolcastUpdateCoordinator,
    solcast: SolcastApi,
    caplog: pytest.LogCaptureFixture,
    action: str,
    last_update_delta: int = 0,
    wait: bool = True,
    wait_exception: Exception | None = None,
) -> None:
    """Execute an estimated actuals action and wait for completion."""

    caplog.clear()
    if last_update_delta == 0:
        last_updated = dt(year=2020, month=1, day=1, hour=1, minute=1, second=1, tzinfo=datetime.UTC)
    else:
        last_updated = solcast._data_actuals["last_updated"] - timedelta(seconds=last_update_delta)  # pyright: ignore[reportPrivateUsage]
        _LOGGER.info("Mock last updated: %s", last_updated)
    solcast._data_actuals["last_updated"] = last_updated  # pyright: ignore[reportPrivateUsage]
    await hass.services.async_call(DOMAIN, action, {}, blocking=True)
    if wait_exception:
        await _wait_for_raise(hass, wait_exception)
    elif wait:
        await _wait_for_update(hass, caplog)
        await solcast.tasks_cancel()
        async with asyncio.timeout(1):
            while coordinator.tasks.get("actuals"):
                await hass.async_block_till_done()
    await hass.async_block_till_done()


async def _wait_for_update(hass: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """Wait for forecast update completion."""

    async with asyncio.timeout(10):
        while (
            "Forecast update completed successfully" not in caplog.text
            and "Not requesting a solar forecast" not in caplog.text
            and "aborting forecast update" not in caplog.text
            and "update already in progress" not in caplog.text
            and "pausing" not in caplog.text
            and "Completed task update" not in caplog.text
            and "Completed task force_update" not in caplog.text
            and "Completed task actuals" not in caplog.text
            and "Completed task force_actuals" not in caplog.text
            and "ConfigEntryAuthFailed" not in caplog.text
        ):  # Wait for task to complete
            await asyncio.sleep(0.01)
            await hass.async_block_till_done()


async def _wait_for_abort(caplog: pytest.LogCaptureFixture) -> None:
    """Wait for forecast update completion."""

    async with asyncio.timeout(10):
        while (
            "Forecast update aborted" not in caplog.text and "Forecast update already in progress, ignoring" not in caplog.text
        ):  # Wait for task to abort
            await asyncio.sleep(0.01)


async def _wait_for(caplog: pytest.LogCaptureFixture, wait_text: str) -> None:
    """Wait for forecast update completion."""

    async with asyncio.timeout(10):
        while wait_text not in caplog.text:  # Wait for task to abort
            await asyncio.sleep(0.01)


async def _wait_for_raise(hass: HomeAssistant, exception: Exception) -> None:
    """Wait for exception."""

    async def wait_for_exception():
        async with asyncio.timeout(10):
            while True:
                await hass.async_block_till_done()
                await asyncio.sleep(0.01)

    with pytest.raises(exception):  # type: ignore[call-overload]
        await wait_for_exception()


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> tuple[SolcastUpdateCoordinator | None, SolcastApi | None]:
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


async def five_minute_bump(hass: HomeAssistant, caplog: pytest.LogCaptureFixture):
    """Move to a sensor update done."""
    async with asyncio.timeout(1):
        while "Updating sensor Dampening" not in caplog.text:
            await asyncio.sleep(0.1)
            await hass.async_block_till_done()
    assert "Updating sensor Dampening" in caplog.text


async def test_api_failure(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test API failure."""

    await async_cleanup_integration_tests(hass)
    try:

        def assertions1_busy(entry: ConfigEntry):
            assert entry.state is ConfigEntryState.SETUP_RETRY
            assert "Get sites failed, last call result: 429/Try again later" in caplog.text
            assert "Cached sites are not yet available" in caplog.text
            caplog.clear()

        def assertions1_bad_data(entry: ConfigEntry):
            assert "API did not return a json object, returned" in caplog.text

        def assertions1_except(entry: ConfigEntry):
            assert entry.state is ConfigEntryState.SETUP_ERROR
            assert "Error retrieving sites" in caplog.text
            assert "Attempting to continue" in caplog.text
            assert "Cached sites are not yet available" in caplog.text
            caplog.clear()

        def assertions2_busy(entry: ConfigEntry):
            assert "Get sites failed, last call result: 429/Try again later, using cached data" in caplog.text
            assert "Sites loaded for ******1" in caplog.text
            assert "Sites loaded for ******2" in caplog.text
            caplog.clear()

        def assertions2_except(entry: ConfigEntry):
            assert "Error retrieving sites" in caplog.text
            assert "Attempting to continue" in caplog.text
            assert "Sites loaded for ******1" in caplog.text
            assert "Sites loaded for ******2" in caplog.text
            caplog.clear()

        async def too_busy(assertions: Callable[[ConfigEntry], None]):
            session_set(MOCK_BUSY)
            entry = await async_init_integration(hass, DEFAULT_INPUT2)
            assertions(entry)
            session_clear(MOCK_BUSY)
            hass.data[DOMAIN][PRESUMED_DEAD] = False

        async def bad_response(assertions: Callable[[ConfigEntry], None]):
            for returned in [MOCK_CORRUPT_SITES, MOCK_CORRUPT_ACTUALS, MOCK_CORRUPT_FORECAST]:
                session_set(returned)
                entry = await async_init_integration(hass, DEFAULT_INPUT2)
                assertions(entry)
                session_clear(returned)
                hass.data[DOMAIN][PRESUMED_DEAD] = False

        async def exceptions(assertions: Callable[[ConfigEntry], None]):
            session_set(MOCK_EXCEPTION, exception=ConnectionRefusedError)
            entry = await async_init_integration(hass, DEFAULT_INPUT2)
            assertions(entry)
            hass.data[DOMAIN][PRESUMED_DEAD] = False
            session_set(MOCK_EXCEPTION, exception=TimeoutError)
            entry = await async_init_integration(hass, DEFAULT_INPUT2)
            assertions(entry)
            hass.data[DOMAIN][PRESUMED_DEAD] = False
            session_set(MOCK_EXCEPTION, exception=ClientConnectionError)
            entry = await async_init_integration(hass, DEFAULT_INPUT2)
            assertions(entry)
            session_clear(MOCK_EXCEPTION)
            hass.data[DOMAIN][PRESUMED_DEAD] = False

        async def exceptions_update():
            tests: list[dict[str, Any]] = [
                {"exception": TimeoutError, "assertion": "Connection error: Timed out", "fatal": True},
                {"exception": ClientConnectionError, "assertion": "Client error", "fatal": True},
                {"exception": ConnectionRefusedError, "assertion": "Connection error, connection refused", "fatal": True},
                {"exception": MOCK_BAD_REQUEST, "assertion": "400/Bad request", "fatal": True},
                {"exception": MOCK_NOT_FOUND, "assertion": "404/Not found", "fatal": True},
                {"exception": MOCK_BUSY, "assertion": "429/Try again later", "fatal": False},
                {"exception": MOCK_BUSY_UNEXPECTED, "assertion": "Unexpected response received", "fatal": True},
                # Forbidden must be last
                {"exception": MOCK_FORBIDDEN, "assertion": "ConfigEntryAuthFailed: API key is invalid", "fatal": True},
            ]
            for test in tests:
                if not isinstance(test["exception"], str):
                    session_set(MOCK_EXCEPTION, exception=test["exception"])

                entry: ConfigEntry = await async_init_integration(hass, DEFAULT_INPUT2)
                coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator
                solcast: SolcastApi = patch_solcast_api(coordinator.solcast)
                solcast.options.auto_update = AutoUpdate.NONE
                hass.data[DOMAIN][PRESUMED_DEAD] = False
                await hass.async_block_till_done()
                caplog.clear()

                if isinstance(test["exception"], str):
                    session_set(test["exception"])
                if test["exception"] == MOCK_FORBIDDEN:
                    await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=20)
                    assert "re-authentication required" in caplog.text
                    with pytest.raises(ConfigEntryAuthFailed):
                        await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=20)
                    solcast.options.auto_update = AutoUpdate.DAYLIGHT
                    with pytest.raises(ConfigEntryAuthFailed):
                        await _exec_update(hass, solcast, caplog, "force_update_forecasts", last_update_delta=20)
                    solcast.options.auto_update = AutoUpdate.NONE
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
        entry: ConfigEntry = await async_init_integration(hass, DEFAULT_INPUT2)
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
    """Test schema upgrade."""

    config_dir = f"{hass.config.config_dir}/{CONFIG_DISCRETE_NAME}" if CONFIG_FOLDER_DISCRETE else hass.config.config_dir

    options = copy.deepcopy(DEFAULT_INPUT1)
    options[CONF_API_KEY] = "2"
    entry: ConfigEntry = await async_init_integration(hass, options)
    coordinator = entry.runtime_data.coordinator
    solcast = patch_solcast_api(coordinator.solcast)
    try:
        data_file = Path(f"{config_dir}/solcast.json")
        undampened_file = Path(f"{config_dir}/solcast-undampened.json")
        original_data = json.loads(data_file.read_text(encoding="utf-8"))

        def set_old_solcast_schema(data_file: Path):
            data = copy.deepcopy(original_data)
            data["version"] = 4
            data.pop("last_attempt")
            data.pop("auto_updated")
            data_file.write_text(json.dumps(data), encoding="utf-8")

        def set_ancient_solcast_schema(data_file: Path):
            data = copy.deepcopy(original_data)
            data.pop("version")
            data.pop("last_attempt")
            data.pop("auto_updated")
            data["forecasts"] = data["siteinfo"]["3333-3333-3333-3333"]["forecasts"].copy()
            data.pop("siteinfo")
            data_file.write_text(json.dumps(data), encoding="utf-8")

        def set_incompatible_schema1(data_file: Path):
            data = copy.deepcopy(original_data)
            data.pop("version")
            data.pop("siteinfo")
            data.pop("last_attempt")
            data.pop("auto_updated")
            data["some_stuff"] = {"fraggle": "rock"}
            data_file.write_text(json.dumps(data), encoding="utf-8")

        def set_incompatible_schema2(data_file: Path):
            data = copy.deepcopy(original_data)
            data.pop("version")
            data["siteinfo"] = {"weird": "stuff"}
            data["forecasts"] = "favourable"
            data.pop("last_attempt")
            data.pop("auto_updated")
            data_file.write_text(json.dumps(data), encoding="utf-8")

        def verify_new_solcast_schema(data_file: Path):
            data = json.loads(data_file.read_text(encoding="utf-8"))
            assert data["version"] == 8
            assert "last_attempt" in data
            assert "auto_updated" in data

        def kill_undampened_cache():
            with contextlib.suppress(FileNotFoundError):
                undampened_file.unlink()

        # Test upgrade schema version
        kill_undampened_cache()
        set_old_solcast_schema(data_file)
        coordinator, solcast = await _reload(hass, entry)
        assert "version from v4 to v8" in caplog.text
        assert "Migrating un-dampened history" in caplog.text
        verify_new_solcast_schema(data_file)
        verify_new_solcast_schema(undampened_file)
        caplog.clear()

        # Test upgrade from v3 schema
        kill_undampened_cache()
        set_ancient_solcast_schema(data_file)
        coordinator, solcast = await _reload(hass, entry)
        assert "version from v1 to v8" in caplog.text
        assert "Migrating un-dampened history" in caplog.text
        verify_new_solcast_schema(data_file)
        verify_new_solcast_schema(undampened_file)
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
    options: dict[str, Any],
) -> None:
    """Test integration init."""

    try:
        config_dir = f"{hass.config.config_dir}/{CONFIG_DISCRETE_NAME}" if CONFIG_FOLDER_DISCRETE else hass.config.config_dir
        if CONFIG_FOLDER_DISCRETE:
            Path(config_dir).mkdir(parents=False, exist_ok=True)
        Path(f"{config_dir}/solcast-advanced.json").write_text(json.dumps({"entity_logging": True}), encoding="utf-8")

        # Test startup
        entry: ConfigEntry = await async_init_integration(hass, options)

        if options == BAD_INPUT:
            assert entry.state is ConfigEntryState.SETUP_ERROR
            assert hass.data[DOMAIN].get(PRESUMED_DEAD, True) is True
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
        assert hass.data[DOMAIN].get(PRESUMED_DEAD, True) is False

        # Enable the dampening entity
        dampening_entity = "sensor.solcast_pv_forecast_dampening"
        er.async_get(hass).async_update_entity(dampening_entity, disabled_by=None)
        await hass.async_block_till_done()

        coordinator: SolcastUpdateCoordinator | None
        if (coordinator := entry.runtime_data.coordinator) is None:
            pytest.fail("No coordinator")
        solcast: SolcastApi | None = patch_solcast_api(coordinator.solcast)
        granular_dampening_file = Path(f"{config_dir}/solcast-dampening.json")
        assert granular_dampening_file.is_file() is False

        coordinator, solcast = await _reload(hass, entry)
        if coordinator is None or solcast is None:
            pytest.fail("No coordinator or solcast")

        coordinator.set_next_update()

        assert solcast.sites_status is SitesStatus.OK
        assert solcast._loaded_data is True  # pyright: ignore[reportPrivateUsage]
        assert "Dampening factors corrupt or not found, setting to 1.0" not in caplog.text
        assert solcast._tz == ZONE  # pyright: ignore[reportPrivateUsage]

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
        solcast.options.auto_update = AutoUpdate.NONE
        await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=5)
        assert "Not requesting a solar forecast because time is within ten seconds of last update" in caplog.text
        assert "ERROR" not in caplog.text

        _no_exception(caplog)

        # Test API too busy encountered for first site
        caplog.clear()
        session_set(MOCK_BUSY)
        solcast.options.auto_update = AutoUpdate.NONE
        await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=20)
        assert "seconds before retry" in caplog.text
        assert "ERROR" not in caplog.text
        await hass.async_block_till_done()
        await _wait_for(caplog, "Forecast has not been updated")
        session_clear(MOCK_BUSY)

        # Simulate exceed API limit and beyond
        caplog.clear()
        _LOGGER.info("Simulating API limit exceeded")
        session_set(MOCK_OVER_LIMIT)
        await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=20)
        await _wait_for(caplog, "Forecast has not been updated")
        assert "API allowed polling limit has been exceeded" in caplog.text
        assert "No data was returned for forecasts" in caplog.text
        caplog.clear()
        _no_exception(caplog)
        await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=20)
        assert "API polling limit exhausted, not getting forecast" in caplog.text
        assert "No data was returned for forecasts" in caplog.text
        caplog.clear()
        _no_exception(caplog)
        session_clear(MOCK_OVER_LIMIT)

        # Create a granular dampening file to be read
        granular_dampening = (
            {
                "1111-1111-1111-1111": [0.8] * 48,
                "2222-2222-2222-2222": [0.9] * 48,
            }
            if options == DEFAULT_INPUT1
            else {
                "1111-1111-1111-1111": [0.7] * 24,  # Intentionally dodgy
                "2222-2222-2222-2222": [0.8] * 42,  # Intentionally dodgy
                "3333-3333-3333-3333": [0.9] * 48,
            }
        )
        # Create in the legacy location for auto-move test if CONFIG_FOLDER_DISCRETE is True and it is before June 2026
        if options == DEFAULT_INPUT1 and dt.now(solcast.options.tz) < dt(2026, 6, 1, tzinfo=solcast.options.tz) and CONFIG_FOLDER_DISCRETE:
            legacy_dampening_file = Path(f"{config_dir.replace(f'/{CONFIG_DISCRETE_NAME}', '')}/{granular_dampening_file.name}")
            legacy_dampening_file.write_text(json.dumps(granular_dampening), encoding="utf-8")
            _LOGGER.debug("Write legacy dampening file %s for auto-move test", legacy_dampening_file)
        else:
            granular_dampening_file.write_text(json.dumps(granular_dampening), encoding="utf-8")
            _LOGGER.debug("Write dampening file %s for test", granular_dampening_file)
        await _wait_for(caplog, "Running task watchdog_dampening")
        assert granular_dampening_file.is_file()
        if CONFIG_FOLDER_DISCRETE:
            if options == DEFAULT_INPUT1 and dt.now(solcast.options.tz) < dt(2026, 6, 1, tzinfo=solcast.options.tz):
                assert "auto-moving will cease 1st June 2026" in caplog.text
            else:
                assert "auto-moving will cease 1st June 2026" not in caplog.text

        # Test update beyond ten seconds of prior update, also with stale usage cache and dodgy dampening file
        session_reset_usage()
        for api_key in options["api_key"].split(","):
            solcast._api_used_reset[api_key] = dt.now(datetime.UTC) - timedelta(days=5)  # pyright: ignore[reportPrivateUsage]
        solcast.options.auto_update = AutoUpdate.NONE
        await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=20)
        assert "Not requesting a solar forecast because time is within ten seconds of last update" not in caplog.text
        assert "resetting API usage" in caplog.text
        assert "Writing API usage cache" in caplog.text
        assert "Started task midnight_update" in caplog.text
        if options == DEFAULT_INPUT2:
            assert "Number of dampening factors for all sites must be the same" in caplog.text
            assert "must be 24 or 48 in" in caplog.text
            assert "Forecast update completed successfully" in caplog.text
        else:
            await five_minute_bump(hass, caplog)
            assert "Granular dampening loaded" in caplog.text
            assert "Forecast update completed successfully" in caplog.text
            assert "contains all intervals" in caplog.text
        _no_exception(caplog)

        caplog.clear()

        if options == DEFAULT_INPUT1:
            sensor = hass.states.get("sensor.solcast_pv_forecast_forecast_tomorrow")
            if sensor is not None:
                assert sensor.state == "35.6374"
            else:
                pytest.fail("Test undampened: State of forecast_tomorrow is None")

            # Modify the granular dampening file directly
            granular_dampening = {"1111-1111-1111-1111": [0.7] * 48, "2222-2222-2222-2222": [0.8] * 48}
            granular_dampening_file.write_text(json.dumps(granular_dampening), encoding="utf-8")
            await _wait_for(caplog, "Updating sensor Forecast Tomorrow")
            assert "Granular dampening mtime changed" in caplog.text
            assert "Granular dampening loaded" in caplog.text
            sensor = hass.states.get("sensor.solcast_pv_forecast_forecast_tomorrow")
            if sensor is not None:
                assert sensor.state == "31.3821"
            else:
                pytest.fail("Test dampened: State of forecast_tomorrow is None")

            # Remove the granular dampening file
            granular_dampening_file.unlink()
            await _wait_for(caplog, "Granular dampening file deleted, no longer monitoring")

        # Verify data schema
        verify_data_schema(solcast._data)  # pyright: ignore[reportPrivateUsage]
        verify_data_schema(solcast._data_undampened)  # pyright: ignore[reportPrivateUsage]
        verify_data_schema(solcast._data_actuals)  # pyright: ignore[reportPrivateUsage]
        verify_data_schema(solcast._data_actuals_dampened)  # pyright: ignore[reportPrivateUsage]

        caplog.clear()

        def set_file_last_modified(file_path: str, dtm: dt):
            dt_epoch = dtm.timestamp()
            os.utime(file_path, (dt_epoch, dt_epoch))

        granular_dampening_file.write_text("really dodgy", encoding="utf-8")
        set_file_last_modified(str(granular_dampening_file), dt.now(datetime.UTC) - timedelta(minutes=5))
        await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=20)
        assert "JSONDecodeError, dampening ignored" in caplog.text
        granular_dampening_file.unlink()
        caplog.clear()

        # Test reset usage cache when fresh
        for api_key in options["api_key"].split(","):
            solcast._api_used_reset[api_key] = solcast._api_used_reset[api_key] - timedelta(hours=24)  # type: ignore[assignment, operator]
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


async def test_remaining_actions(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test remaining actions."""

    try:
        config_dir = f"{hass.config.config_dir}/{CONFIG_DISCRETE_NAME}" if CONFIG_FOLDER_DISCRETE else hass.config.config_dir
        if CONFIG_FOLDER_DISCRETE:
            Path(config_dir).mkdir(parents=False, exist_ok=True)
        Path(f"{config_dir}/solcast-advanced.json").write_text(
            json.dumps({"entity_logging": True, "forecast_day_entities": 10}), encoding="utf-8"
        )

        # Start with two API keys and three sites
        entry = await async_init_integration(hass, DEFAULT_INPUT2)
        assert hass.data[DOMAIN].get(PRESUMED_DEAD, True) is False
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        _no_exception(caplog)

        # Test for creation of additional forecast day entities
        assert "Registered new sensor.solcast_solar entity: sensor.solcast_pv_forecast_forecast_day_8" in caplog.text
        assert "Registered new sensor.solcast_solar entity: sensor.solcast_pv_forecast_forecast_day_9" in caplog.text

        caplog.clear()

        # Switch to one API key and two sites to assert the initial clean-up
        _LOGGER.debug("Swithching to one API key and two sites")
        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        solcast: SolcastApi = patch_solcast_api(entry.runtime_data.coordinator.solcast)
        assert hass.data[DOMAIN].get(PRESUMED_DEAD, True) is False

        def occurs_in_log(text: str, occurrences: int) -> None:
            occurs = 0
            for entry in caplog.messages:
                if text in entry:
                    occurs += 1
            assert occurrences == occurs

        # Test logs for cache load
        assert "Sites cache exists" in caplog.text
        assert f"Data cache {config_dir}/solcast.json exists, file type is <class 'dict'>" in caplog.text
        assert f"Data cache {config_dir}/solcast-undampened.json exists, file type is <class 'dict'>" in caplog.text
        occurs_in_log("Renaming", 2)
        occurs_in_log("Removing orphaned", 2)

        # Forced update when auto-update is disabled
        _LOGGER.debug("Test forced update when auto-update is disabled")
        solcast.options.auto_update = AutoUpdate.NONE
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, "force_update_forecasts", {}, blocking=True)

        # Test set/get dampening factors
        async def _clear_granular_dampening():
            # Clear granular dampening
            await hass.services.async_call(DOMAIN, "set_dampening", {"damp_factor": ("1.0," * 24)[:-1]}, blocking=True)
            await hass.async_block_till_done()  # Because options change
            dampening = await hass.services.async_call(DOMAIN, "get_dampening", {}, blocking=True, return_response=True)
            if dampening is not None:
                assert (
                    dampening.get("data", [{}])[0]  # pyright: ignore[reportArgumentType, reportIndexIssue, reportOptionalSubscript] # Response is always a list
                    == {
                        "site": "all",
                        "damp_factor": ("1.0," * 24)[:-1],
                    }
                )
            else:
                pytest.fail("Dampening is None")

        dampening = await hass.services.async_call(DOMAIN, "get_dampening", {}, blocking=True, return_response=True)
        if dampening is not None:
            if isinstance(dampening.get("data", [{}]), list):
                assert (
                    dampening.get("data", [{}])[0]  # type: ignore[index]
                    == {
                        "site": "all",
                        "damp_factor": ("1.0," * 24)[:-1],
                    }
                )
                odd_factors: list[dict[str, Any]] = [
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
            else:
                pytest.fail("Dampening data is not a list")
        else:
            pytest.fail("Dampening is None")

        _LOGGER.debug("Test set various dampening factors")
        await hass.services.async_call(DOMAIN, "set_dampening", {"damp_factor": ("0.5," * 24)[:-1]}, blocking=True)
        await hass.async_block_till_done()  # Because options change
        dampening = await hass.services.async_call(DOMAIN, "get_dampening", {}, blocking=True, return_response=True)
        assert dampening.get("data", [{}])[0] == {"site": "all", "damp_factor": ("0.5," * 24)[:-1]}  # type: ignore[union-attr, index]
        # Granular dampening
        await hass.services.async_call(DOMAIN, "set_dampening", {"damp_factor": ("0.5," * 48)[:-1]}, blocking=True)
        await hass.async_block_till_done()  # Because options change
        assert Path(f"{config_dir}/solcast-dampening.json").is_file()
        dampening = await hass.services.async_call(DOMAIN, "get_dampening", {}, blocking=True, return_response=True)
        assert dampening.get("data", [{}])[0] == {"site": "all", "damp_factor": ("0.5," * 48)[:-1]}  # type: ignore[union-attr, index]
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
            DOMAIN, "set_dampening", {"site": "1111_1111_1111_1111", "damp_factor": ("0.5," * 48)[:-1]}, blocking=True
        )
        await hass.async_block_till_done()  # Because options change
        dampening = await hass.services.async_call(DOMAIN, "get_dampening", {}, blocking=True, return_response=True)
        assert dampening.get("data", [{}])[0] == {"site": "1111-1111-1111-1111", "damp_factor": ("0.5," * 48)[:-1]}  # type: ignore[union-attr, index]
        dampening = await hass.services.async_call(
            DOMAIN, "get_dampening", {"site": "1111_1111_1111_1111"}, blocking=True, return_response=True
        )
        assert dampening.get("data", [{}])[0] == {"site": "1111_1111_1111_1111", "damp_factor": ("0.5," * 48)[:-1]}  # type: ignore[union-attr, index]
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
        odd_limits: list[dict[str, Any]] = [
            {"set": {}, "expect": MultipleInvalid},  # No hard limit
            {"set": {"hard_limit": "zzzzzz"}, "expect": ServiceValidationError},  # Silly hard limit
            {"set": {"hard_limit": "-5"}, "expect": ServiceValidationError},  # Negative hard limit
            {"set": {"hard_limit": "5.0,5.0,5.0"}, "expect": ServiceValidationError},  # Too many hard limits
        ]
        for limits in odd_limits:
            _LOGGER.debug("Test set odd hard limit: %s", limits)
            with pytest.raises(limits["expect"]):
                await hass.services.async_call(DOMAIN, "set_hard_limit", limits["set"], blocking=True)

        async def _set_hard_limit(hard_limit: str) -> SolcastApi:
            await hass.services.async_call(DOMAIN, "set_hard_limit", {"hard_limit": hard_limit}, blocking=True)
            await hass.async_block_till_done()
            return patch_solcast_api(entry.runtime_data.coordinator.solcast)  # Because integration reloads

        async def _remove_hard_limit() -> SolcastApi:
            await hass.services.async_call(DOMAIN, "remove_hard_limit", {}, blocking=True)
            await hass.async_block_till_done()
            return patch_solcast_api(entry.runtime_data.coordinator.solcast)  # Because integration reloads

        _LOGGER.debug("Test set reasonable hard limit")
        solcast = await _set_hard_limit("5.0")
        assert solcast.hard_limit == "5.0"
        assert "Build hard limit period values from scratch for forecast" in caplog.text
        assert "Build hard limit period values from scratch for undampened forecast" in caplog.text
        for estimate in ["pv_estimate", "pv_estimate10", "pv_estimate90"]:
            assert len(solcast._sites_hard_limit["all"][estimate]) > 0  # pyright: ignore[reportPrivateUsage]
            assert len(solcast._sites_hard_limit_undampened["all"][estimate]) > 0  # pyright: ignore[reportPrivateUsage]
        assert re.search("Build hard limit processing took.+seconds for forecast", caplog.text)
        assert re.search("Build hard limit processing took.+seconds for undampened forecast", caplog.text)

        _LOGGER.debug("Test set large hard limit")
        solcast = await _set_hard_limit("5000")
        assert solcast.hard_limit == "5000.0"
        assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set").state == "5.0 MW"  # type: ignore[union-attr]

        _LOGGER.debug("Test set huge hard limit")
        solcast = await _set_hard_limit("5000000")
        assert solcast.hard_limit == "5000000.0"
        assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set").state == "5.0 GW"  # type: ignore[union-attr]

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
        assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set_1").state == "False"  # type: ignore[union-attr]
        assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set_2").state == "False"  # type: ignore[union-attr]

        _LOGGER.debug("Test set hard limit for both API keys")
        solcast = await _set_hard_limit("5.0,5.0")
        assert solcast.hard_limit == "5.0,5.0"
        assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set_1").state == "5.0 kW"  # type: ignore[union-attr]
        assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set_2").state == "5.0 kW"  # type: ignore[union-attr]
        assert "Build hard limit period values from scratch for forecast" in caplog.text
        assert "Build hard limit period values from scratch for undampened forecast" in caplog.text
        for api_key in entry.options["api_key"].split(","):
            for estimate in ["pv_estimate", "pv_estimate10", "pv_estimate90"]:
                assert len(solcast._sites_hard_limit[api_key][estimate]) > 0  # pyright: ignore[reportPrivateUsage]
                assert len(solcast._sites_hard_limit_undampened[api_key][estimate]) > 0  # pyright: ignore[reportPrivateUsage]
        assert re.search("Build hard limit processing took.+seconds for forecast", caplog.text)
        assert re.search("Build hard limit processing took.+seconds for undampened forecast", caplog.text)

        caplog.clear()
        _LOGGER.debug("Test set single hard limit value for both API keys")
        solcast = await _remove_hard_limit()
        assert solcast.hard_limit == "100.0"
        for estimate in ["pv_estimate", "pv_estimate10", "pv_estimate90"]:
            assert len(solcast._sites_hard_limit["all"][estimate]) == 0  # pyright: ignore[reportPrivateUsage]
            assert len(solcast._sites_hard_limit_undampened["all"][estimate]) == 0  # pyright: ignore[reportPrivateUsage]
        assert re.search("Build hard limit processing took.+seconds for forecast", caplog.text) is None
        assert re.search("Build hard limit processing took.+seconds for undampened forecast", caplog.text) is None

        # Test query forecast data
        queries: list[dict[str, Any]] = [
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
                    SITE: "2222_2222_2222_2222",
                    UNDAMPENED: True,
                },
                "expect": 96,
            },
        ]
        for query in queries:
            _LOGGER.debug("Testing query forecast data: %s", query["query"])
            forecast_data = await hass.services.async_call(
                DOMAIN,
                "query_forecast_data",
                query["query"],
                blocking=True,
                return_response=True,
            )
            assert len(forecast_data.get("data", [])) == query["expect"]  # type: ignore[arg-type, union-attr]

        assert "ERROR" not in caplog.text

        # Test invalid query range
        _LOGGER.debug("Testing invalid query range")
        with pytest.raises(ServiceValidationError):
            forecast_data = await hass.services.async_call(
                DOMAIN,
                "query_forecast_data",
                {
                    EVENT_START_DATETIME: solcast.get_day_start_utc(future=DEFAULT_FORECAST_DAYS + 2).isoformat(),
                    EVENT_END_DATETIME: solcast.get_day_start_utc(future=DEFAULT_FORECAST_DAYS + 6).isoformat(),
                },
                blocking=True,
                return_response=True,
            )

        # Verify data schema
        verify_data_schema(solcast._data)  # pyright: ignore[reportPrivateUsage]
        verify_data_schema(solcast._data_undampened)  # pyright: ignore[reportPrivateUsage]
        verify_data_schema(solcast._data_actuals)  # pyright: ignore[reportPrivateUsage]
        verify_data_schema(solcast._data_actuals_dampened)  # pyright: ignore[reportPrivateUsage]

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

        # Test call an action with no entry loaded
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, "update_forecasts", {}, blocking=True)
        assert "Integration not loaded" in caplog.text

        _no_exception(caplog)

    finally:
        assert await async_cleanup_integration_tests(hass)


async def test_scenarios(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test various integration scenarios."""

    try:
        config_dir = f"{hass.config.config_dir}/{CONFIG_DISCRETE_NAME}" if CONFIG_FOLDER_DISCRETE else hass.config.config_dir
        if CONFIG_FOLDER_DISCRETE:
            Path(config_dir).mkdir(parents=False, exist_ok=True)

        options = copy.deepcopy(DEFAULT_INPUT1)
        options[HARD_LIMIT_API] = "6.0"
        entry = await async_init_integration(hass, options)
        coordinator = entry.runtime_data.coordinator
        solcast = patch_solcast_api(coordinator.solcast)

        # Test bad serialise data while an entry exists
        _LOGGER.debug("Testing bad serialise data")
        async with aiohttp.ClientSession() as session:
            connection_options = ConnectionOptions(
                DEFAULT_INPUT1[CONF_API_KEY],
                DEFAULT_INPUT1[API_QUOTA],
                "api.whatever.com",
                config_dir,
                ZoneInfo(ZONE_RAW),
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
                DEFAULT_INPUT1[EXCLUDE_SITES],
                DEFAULT_INPUT1[GET_ACTUALS],
                DEFAULT_INPUT1[USE_ACTUALS],
                DEFAULT_INPUT1[GENERATION_ENTITIES],
                DEFAULT_INPUT1[SITE_EXPORT_ENTITY],
                DEFAULT_INPUT1[SITE_EXPORT_LIMIT],
                DEFAULT_INPUT1[AUTO_DAMPEN],
            )
            solcast_bad: SolcastApi = SolcastApi(session, connection_options, hass, entry)
            await solcast_bad.serialise_data(solcast_bad._data, str(Path(f"{config_dir}/solcast.json")))  # pyright: ignore[reportPrivateUsage]
            assert "Not serialising empty data" in caplog.text

        # Assert good start
        _LOGGER.debug("Testing good start happened")
        assert hass.data[DOMAIN].get(PRESUMED_DEAD, True) is False
        assert "Hard limit is set to limit peak forecast values" in caplog.text
        _no_exception(caplog)
        caplog.clear()

        # Test start with stale data
        data_file = Path(f"{config_dir}/solcast.json")
        data_file_undampened = Path(f"{config_dir}/solcast-undampened.json")
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

        def alter_last_updated_as_very_stale():
            for d_file in [data_file, data_file_undampened]:
                data = json.loads(d_file.read_text(encoding="utf-8"))
                data["last_updated"] = (dt.now(datetime.UTC) - timedelta(days=DEFAULT_FORECAST_DAYS + 1)).isoformat()
                data["last_attempt"] = data["last_updated"]
                data["auto_updated"] = 10
                # Shift all forecast intervals back nine days
                for site in data["siteinfo"].values():
                    site["forecasts"] = [
                        {
                            "period_start": (dt.fromisoformat(f["period_start"]) - timedelta(days=DEFAULT_FORECAST_DAYS + 1)).isoformat(),
                            "pv_estimate": f["pv_estimate"],
                            "pv_estimate10": f["pv_estimate10"],
                            "pv_estimate90": f["pv_estimate90"],
                        }
                        for f in site["forecasts"]
                    ]
                d_file.write_text(json.dumps(data), encoding="utf-8")
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
        if coordinator is None or solcast is None:
            pytest.fail("Reload failed")
        await _wait_for_update(hass, caplog)
        assert "is older than expected, should be" in caplog.text
        assert solcast._data["last_updated"] > dt.now(datetime.UTC) - timedelta(minutes=10)  # pyright: ignore[reportPrivateUsage]
        assert "ERROR" not in caplog.text
        _no_exception(caplog)

        # Get last auto-update time for a subsequent test
        last_update = ""
        for line in caplog.messages:
            if line.startswith("Previous auto update UTC "):
                last_update = line[-25:]
                break

        caplog.clear()
        restore_data()

        # Test very stale start with auto update enabled
        _LOGGER.debug("Testing very stale start with auto update enabled")
        alter_last_updated_as_very_stale()
        coordinator, solcast = await _reload(hass, entry)
        if coordinator is None or solcast is None:
            pytest.fail("Reload failed")
        await _wait_for_update(hass, caplog)
        assert "is older than expected, should be" in caplog.text
        assert solcast._data["last_updated"] > dt.now(datetime.UTC) - timedelta(minutes=10)  # pyright: ignore[reportPrivateUsage]
        assert "hours of past data" in caplog.text
        assert "ERROR" not in caplog.text
        _no_exception(caplog)

        caplog.clear()
        restore_data()

        # Test stale start with auto update disabled
        _LOGGER.debug("Testing stale start with auto update disabled")
        opt = {**entry.options}
        opt[AUTO_UPDATE] = 0
        hass.config_entries.async_update_entry(entry, options=opt)
        await hass.async_block_till_done()
        alter_last_updated_as_stale()
        coordinator, solcast = await _reload(hass, entry)
        if coordinator is None or solcast is None:
            pytest.fail("Reload failed")
        await _wait_for_update(hass, caplog)
        assert "The update automation has not been running" in caplog.text
        _no_exception(caplog)

        caplog.clear()
        restore_data()

        # Test very stale start with auto update disabled
        _LOGGER.debug("Testing very stale start with auto update disabled")
        alter_last_updated_as_very_stale()
        coordinator, solcast = await _reload(hass, entry)
        if coordinator is None or solcast is None:
            pytest.fail("Reload failed")
        await _wait_for_update(hass, caplog)
        assert "The update automation has not been running" in caplog.text
        assert solcast._data["last_updated"] > dt.now(datetime.UTC) - timedelta(minutes=10)  # pyright: ignore[reportPrivateUsage]
        assert "hours of past data" in caplog.text
        assert "ERROR" not in caplog.text
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

        # Excluding site
        caplog.clear()
        _LOGGER.debug("Testing site exclusion")
        assert hass.states.get("sensor.solcast_pv_forecast_forecast_today").state == "39.888"  # type: ignore[union-attr]
        opt = {**entry.options}
        opt[EXCLUDE_SITES] = ["2222-2222-2222-2222"]
        hass.config_entries.async_update_entry(entry, options=opt)
        await hass.async_block_till_done()
        assert "Recalculate forecasts and refresh sensors" in caplog.text
        assert hass.states.get("sensor.solcast_pv_forecast_forecast_today").state == "24.93"  # type: ignore[union-attr]

        # Test simple API key change
        caplog.clear()
        _LOGGER.debug("Testing API key change")
        opt = {**entry.options}
        opt[CONF_API_KEY] = "10"
        hass.config_entries.async_update_entry(entry, options=opt)
        await hass.async_block_till_done()
        assert "API key ******10 has changed" in caplog.text
        assert "resetting usage" not in caplog.text

        # Test API key change, start with an API failure and invalid sites cache
        # Verify API key change removes sites, and migrates undampened history for new site
        caplog.clear()
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
        hass.data[DOMAIN][PRESUMED_DEAD] = False  # Clear presumption of death
        coordinator, solcast = await _reload(hass, entry)
        if coordinator is None or solcast is None:
            pytest.fail("Reload failed")
        assert "An API key has changed with a new site added" in caplog.text
        assert "Reset API usage" in caplog.text
        assert "New site(s) have been added" in caplog.text
        assert "Site resource id 1111-1111-1111-1111 is no longer configured" in caplog.text
        assert "Site resource id 2222-2222-2222-2222 is no longer configured" in caplog.text
        _no_exception(caplog)
        caplog.clear()

        sites_file = Path(f"{config_dir}/solcast-sites.json")
        sites = json.loads(sites_file.read_text(encoding="utf-8"))

        # Test no sites call on start when in a presumed dead state, then an allowed call after sixty minutes.
        session_set(MOCK_BUSY)

        hass.data[DOMAIN][PRESUMED_DEAD] = True  # Set presumption of death
        coordinator, solcast = await _reload(hass, entry)
        if coordinator is None or solcast is None:
            pytest.fail("Reload failed")
        assert "Get sites failed, last call result: 999/Prior crash" in caplog.text
        assert "Connecting to https://api.solcast.com.au/rooftop_sites" not in caplog.text
        caplog.clear()
        hass.data[DOMAIN][PRESUMED_DEAD] = True  # Set presumption of death
        hass.data[DOMAIN][PRIOR_CRASH_TIME] = dt_util.now(dt_util.UTC) - timedelta(
            minutes=DELAYED_RESTART_ON_CRASH - DELAYED_RESTART_ON_CRASH / 2
        )
        coordinator, solcast = await _reload(hass, entry)
        assert re.search(r"Prior crash detected.+, skipping load for \d+ minutes", caplog.text)
        assert "Integration failed to load previously" in caplog.text
        assert "Connecting to https://api.solcast.com.au/rooftop_sites" not in caplog.text
        hass.data[DOMAIN][PRIOR_CRASH_TIME] = dt_util.now(dt_util.UTC) - timedelta(minutes=DELAYED_RESTART_ON_CRASH + 1)
        coordinator, solcast = await _reload(hass, entry)
        assert "Prior crash detected" in caplog.text
        assert f"Prior crash was more than {DELAYED_RESTART_ON_CRASH} minutes ago" in caplog.text
        assert "Connecting to https://api.solcast.com.au/rooftop_sites" in caplog.text
        hass.data[DOMAIN].pop(PRESUMED_DEAD, None)
        hass.data[DOMAIN].pop(PRIOR_CRASH_TIME, None)

        caplog.clear()
        _LOGGER.debug("Unlinking sites cache files")
        for f in ["solcast-sites.json", "solcast-sites-1.json", "solcast-sites-2.json"]:
            Path(f"{config_dir}/{f}").unlink(missing_ok=True)  # Remove sites cache file
        hass.data[DOMAIN]["prior_crash_allow_sites"] = dt_util.now(dt_util.UTC) - timedelta(
            minutes=DELAYED_RESTART_ON_CRASH - DELAYED_RESTART_ON_CRASH / 2
        )
        coordinator, solcast = await _reload(hass, entry)
        assert "Sites data could not be retrieved" in caplog.text
        assert hass.data[DOMAIN].get("prior_crash_allow_sites")
        assert "Connecting to https://api.solcast.com.au/rooftop_sites" in caplog.text
        assert "HTTP session returned status 429/Try again later" in caplog.text
        assert "At least one successful API 'get sites' call is needed" in caplog.text
        caplog.clear()

        hass.data[DOMAIN][PRESUMED_DEAD] = False  # Clear presumption of death
        session_clear(MOCK_BUSY)

        # Test corrupt cache start, integration will mostly not load, and will not attempt reload
        # Must be the final test because it will leave the integration in a bad state

        corrupt = "Purple monkey dishwasher 🤣🤣🤣"
        usage_file = Path(f"{config_dir}/solcast-usage.json")
        usage = json.loads(usage_file.read_text(encoding="utf-8"))

        def _really_corrupt_data():
            data_file.write_text(corrupt, encoding="utf-8")

        def _really_corrupt_data_2():
            data_file.write_text(json.dumps([corrupt]), encoding="utf-8")

        def _corrupt_data():
            data = json.loads(data_file.read_text(encoding="utf-8"))
            data["siteinfo"]["3333-3333-3333-3333"]["forecasts"] = [{"bob": 0}]
            data_file.write_text(json.dumps(data), encoding="utf-8")

        def _corrupt_with_zero_length():
            data_file.write_text("", encoding="utf-8")

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
        hass.data[DOMAIN].pop(PRESUMED_DEAD, None)
        hass.data[DOMAIN].pop("prior_crash_allow_sites", None)
        usage_corruption: list[dict[str, Any]] = [
            {"daily_limit": "10", "daily_limit_consumed": 8, "reset": "2025-01-05T00:00:00+00:00"},
            {"daily_limit": 10, "daily_limit_consumed": "8", "reset": "2025-01-05T00:00:00+00:00"},
            {"daily_limit": 10, "daily_limit_consumed": 8, "reset": "notadate"},
        ]
        for test in usage_corruption:
            _LOGGER.debug("Testing usage corruption: %s", test)
            usage_file.write_text(json.dumps(test), encoding="utf-8")
            await _reload(hass, entry)
            assert entry.state is ConfigEntryState.SETUP_ERROR
            assert hass.data[DOMAIN].get(PRESUMED_DEAD) is True
            assert hass.data[DOMAIN].get("prior_crash_allow_sites") is None
            hass.data[DOMAIN].pop(PRESUMED_DEAD, None)  # Clear presumption of death
            hass.data[DOMAIN].pop("prior_crash_allow_sites", None)
        usage_file.write_text(corrupt, encoding="utf-8")
        await _reload(hass, entry)
        assert "corrupt, re-creating cache with zero usage" in caplog.text
        usage_file.write_text(json.dumps(usage), encoding="utf-8")
        caplog.clear()

        # Corrupt solcast.json as zero length
        _LOGGER.debug("Testing corruption: solcast.json")
        _corrupt_with_zero_length()
        await _reload(hass, entry)
        assert re.search(rf"CRITICAL.+Removing zero-length file.+{data_file}", caplog.text) is not None
        caplog.clear()

        # Corrupt solcast.json
        _LOGGER.debug("Testing corruption: solcast.json")
        _corrupt_data()
        await _reload(hass, entry)
        assert hass.data[DOMAIN].get(PRESUMED_DEAD, True) is True
        caplog.clear()

        _LOGGER.debug("Testing extreme corruption: solcast.json")
        _really_corrupt_data()
        await _reload(hass, entry)
        assert "is corrupt in load_saved_data" in caplog.text
        assert "integration not ready yet" in caplog.text
        assert hass.data[DOMAIN].get(PRESUMED_DEAD, True) is True

        _LOGGER.debug("Testing extreme corruption as acceptable (but unacceptable) JSON list: solcast.json")
        hass.data[DOMAIN].pop(PRESUMED_DEAD)
        _really_corrupt_data_2()
        await _reload(hass, entry)
        assert "cache appears corrupt" in caplog.text
        assert "is corrupt in load_saved_data" in caplog.text
        assert "integration not ready yet" in caplog.text
        assert hass.data[DOMAIN].get(PRESUMED_DEAD, True) is True

    finally:
        assert await async_cleanup_integration_tests(hass)


async def test_estimated_actuals(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test various integration scenarios."""

    try:
        config_dir = f"{hass.config.config_dir}/{CONFIG_DISCRETE_NAME}" if CONFIG_FOLDER_DISCRETE else hass.config.config_dir
        if CONFIG_FOLDER_DISCRETE:
            Path(config_dir).mkdir(parents=False, exist_ok=True)
        options = copy.deepcopy(DEFAULT_INPUT1)
        options[GET_ACTUALS] = True
        options[USE_ACTUALS] = 1
        entry = await async_init_integration(hass, options)
        coordinator = entry.runtime_data.coordinator
        solcast = patch_solcast_api(coordinator.solcast)

        # Assert good start, that actuals are enabled, and that the cache is saved
        _LOGGER.debug("Testing good start happened")
        assert hass.data[DOMAIN].get(PRESUMED_DEAD, True) is False
        _no_exception(caplog)
        assert Path(f"{config_dir}/solcast-actuals.json").is_file()
        caplog.clear()

        # Kill the cache, then re-create with a forced update
        _LOGGER.debug("Testing force update actuals")
        Path(f"{config_dir}/solcast-dampening.json").unlink(missing_ok=True)  # Remove dampening file
        await _exec_update_actuals(hass, coordinator, solcast, caplog, "force_update_estimates", wait=True)
        assert Path(f"{config_dir}/solcast-actuals.json").is_file()
        assert "Estimated actuals dictionary for site 1111-1111-1111-1111" in caplog.text
        assert "Estimated actuals dictionary for site 2222-2222-2222-2222" in caplog.text
        assert "Auto-dampening suppressed" not in caplog.text
        assert "Task model_automated_dampening took" not in caplog.text
        assert "Apply dampening to previous day estimated actuals" not in caplog.text

        # Retrieve actuals data
        queries: list[dict[str, Any]] = [
            {
                "query": {
                    EVENT_START_DATETIME: solcast.get_day_start_utc(future=-1).isoformat(),
                    EVENT_END_DATETIME: solcast.get_day_start_utc().isoformat(),
                },
                "expect": 48,
            },
            {
                "query": {},
                "expect": 48,
            },
        ]
        for query in queries:
            _LOGGER.debug("Testing query estimated data: %s", query["query"])
            estimate_data = await hass.services.async_call(
                DOMAIN,
                "query_estimate_data",
                query["query"],
                blocking=True,
                return_response=True,
            )
            assert len(estimate_data.get("data", [])) == query["expect"]  # type: ignore[arg-type, union-attr]

        # Test invalid query range
        _LOGGER.debug("Testing invalid estimated actual query range")
        with pytest.raises(ServiceValidationError):
            estimate_data = await hass.services.async_call(
                DOMAIN,
                "query_estimate_data",
                {
                    EVENT_START_DATETIME: solcast.get_day_start_utc(future=-50).isoformat(),
                    EVENT_END_DATETIME: solcast.get_day_start_utc(future=-40).isoformat(),
                },
                blocking=True,
                return_response=True,
            )

        # Switch between not using estimated actuals and using
        _LOGGER.debug("Testing switch between using and not using estimated actuals")
        caplog.clear()
        opt = {**entry.options}
        opt[USE_ACTUALS] = 0
        hass.config_entries.async_update_entry(entry, options=opt)
        await hass.async_block_till_done()
        assert "Recalculate forecasts and refresh sensors" in caplog.text
        energy_dashboard = solcast.get_energy_data()
        if energy_dashboard is None:
            pytest.fail("Energy dashboard data is None")
        else:
            assert energy_dashboard["wh_hours"].get((solcast.get_day_start_utc() - timedelta(hours=8)).isoformat()) == 936.0

        session_set(MOCK_ALTER_HISTORY)
        await _exec_update_actuals(hass, coordinator, solcast, caplog, "force_update_estimates")
        caplog.clear()
        opt = {**entry.options}
        opt[USE_ACTUALS] = 1
        hass.config_entries.async_update_entry(entry, options=opt)
        await hass.async_block_till_done()
        assert "Recalculate forecasts and refresh sensors" in caplog.text
        energy_dashboard = solcast.get_energy_data()
        session_clear(MOCK_ALTER_HISTORY)
        if energy_dashboard is None:
            pytest.fail("Energy dashboard data is None")
        else:
            assert energy_dashboard["wh_hours"].get((solcast.get_day_start_utc() - timedelta(hours=8)).isoformat()) == 374.0

        _LOGGER.debug("Testing get actuals abort if already in progress")
        caplog.clear()
        await _exec_update_actuals(hass, coordinator, solcast, caplog, "force_update_estimates", wait=False)
        await _exec_update_actuals(hass, coordinator, solcast, caplog, "force_update_estimates", wait=False)
        await _wait_for_update(hass, caplog)
        assert "update already in progress" in caplog.text
        caplog.clear()
        await _wait_for_update(hass, caplog)

        _LOGGER.debug("Testing get actuals when not using actuals")
        caplog.clear()
        opt = {**entry.options}
        opt[GET_ACTUALS] = False
        opt[USE_ACTUALS] = False
        hass.config_entries.async_update_entry(entry, options=opt)
        await hass.async_block_till_done()
        caplog.clear()
        with pytest.raises(ServiceValidationError):
            await _exec_update_actuals(hass, coordinator, solcast, caplog, "force_update_estimates")
        assert "Estimated actuals not enabled" in caplog.text

    finally:
        assert await async_cleanup_integration_tests(hass)


async def test_config_folder_migration(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test migration of config to a discrete folder."""

    try:
        Path(f"{hass.config.config_dir}/solcast-test.json").write_text(  # Create old config file
            json.dumps({"last_updated": dt.now(datetime.UTC).isoformat(), "siteinfo": {}}), encoding="utf-8"
        )
        options = copy.deepcopy(DEFAULT_INPUT1)
        entry = await async_init_integration(hass, options)  # This will trigger migration
        config_file_old = Path(f"{hass.config.config_dir}/solcast-test.json")
        config_file_new = Path(f"{hass.config.config_dir}/{CONFIG_DISCRETE_NAME}/solcast-test.json")
        assert not config_file_old.is_file()
        assert config_file_new.is_file()
        assert entry.state is ConfigEntryState.LOADED
        assert re.search(
            r"INFO.+Migrating config directory file.+config/solcast-test.json to .+config/solcast_solar/solcast-test.json", caplog.text
        )
        _no_exception(caplog)
    finally:
        assert await async_cleanup_integration_tests(hass)
