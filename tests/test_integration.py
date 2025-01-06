"""Tests for the Solcast Solar initialisation."""

import asyncio
import copy
import datetime
from datetime import datetime as dt, timedelta
import json
import logging
import os
from pathlib import Path

from aiohttp import ClientConnectionError
import pytest
from voluptuous.error import MultipleInvalid

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar.const import (
    API_QUOTA,
    AUTO_UPDATE,
    DOMAIN,
    EVENT_END_DATETIME,
    EVENT_START_DATETIME,
    HARD_LIMIT_API,
    SITE,
    UNDAMPENED,
)
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.solcastapi import SitesStatus, SolcastApi
from homeassistant.components.solcast_solar.util import SolcastConfigEntry
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from . import (
    BAD_INPUT,
    DEFAULT_INPUT1,
    DEFAULT_INPUT2,
    DEFAULT_INPUT_NO_SITES,
    ZONE,
    async_cleanup_integration_tests,
    async_init_integration,
    mock_session_clear_exception,
    mock_session_clear_over_limit,
    mock_session_clear_too_busy,
    mock_session_config_reset,
    mock_session_set_exception,
    mock_session_set_over_limit,
    mock_session_set_too_busy,
)

_LOGGER = logging.getLogger(__name__)

SERVICES = [
    "clear_all_solcast_data",
    "force_update_forecasts",
    "get_dampening",
    "query_forecast_data",
    "remove_hard_limit",
    "set_dampening",
    "set_hard_limit",
    "update_forecasts",
]

NOW = dt.now(ZONE)


@pytest.fixture(autouse=True)
def frozen_time() -> None:
    """Override autouse fixture for this module.

    Time must pass, so use method replacement instead.
    """
    return


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


async def test_api_failure(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test API failure."""

    try:

        def assertions1_busy(entry: SolcastConfigEntry):
            assert entry.state is ConfigEntryState.SETUP_RETRY
            assert "Get sites failed, last call result: 429/Try again later" in caplog.text
            assert "Cached sites are not yet available" in caplog.text
            caplog.clear()

        def assertions1_except(entry: SolcastConfigEntry):
            assert entry.state is ConfigEntryState.SETUP_RETRY
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
            mock_session_set_too_busy()
            entry = await async_init_integration(hass, DEFAULT_INPUT1)
            assertions(entry)
            mock_session_clear_too_busy()

        async def exceptions(assertions: callable):
            mock_session_set_exception(ConnectionRefusedError)
            entry = await async_init_integration(hass, DEFAULT_INPUT1)
            assertions(entry)
            mock_session_set_exception(TimeoutError)
            entry = await async_init_integration(hass, DEFAULT_INPUT1)
            assertions(entry)
            mock_session_set_exception(ClientConnectionError)
            entry = await async_init_integration(hass, DEFAULT_INPUT1)
            assertions(entry)
            mock_session_clear_exception()

        # Test API too busy during get sites without cache
        await too_busy(assertions1_busy)
        # Test exceptions during get sites without cache
        await exceptions(assertions1_except)

        # Normal start and teardown to create caches
        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        assert hass.data[DOMAIN].get("presumed_dead", True) is False
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

        # Test API too busy during get sites with the cache present
        await too_busy(assertions2_busy)
        # Test exceptions during get sites with the cache present
        await exceptions(assertions2_except)

    finally:
        mock_session_clear_too_busy()
        mock_session_clear_exception()
        assert await async_cleanup_integration_tests(hass)


async def _exec_update(
    hass: HomeAssistant,
    solcast: SolcastApi,
    caplog: any,
    action: str,
    last_update_delta: int = 0,
    wait: bool = True,
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
    await hass.async_block_till_done()
    if wait:
        await _wait_for_update(caplog)


async def _wait_for_update(caplog: any) -> None:
    """Wait for forecast update completion."""
    async with asyncio.timeout(5):
        while (
            "Forecast update completed successfully" not in caplog.text
            and "Not requesting a solar forecast" not in caplog.text
            and "seconds before retry" not in caplog.text
            and "ERROR" not in caplog.text
        ):  # Wait for task to complete
            await asyncio.sleep(0.01)


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
        assert "Get sites failed, last call result: 401/Unauthorized" in caplog.text
        assert "API key is invalid" in caplog.text
        return

    if options == DEFAULT_INPUT_NO_SITES:
        assert entry.state is ConfigEntryState.SETUP_ERROR
        assert "No sites for the API key ******_sites are configured at solcast.com" in caplog.text
        assert "Get sites failed, last call result: 200/Success" in caplog.text
        return

    assert entry.state is ConfigEntryState.LOADED
    assert hass.data[DOMAIN].get("presumed_dead", True) is False

    coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator
    solcast: SolcastApi = patch_solcast_api(coordinator.solcast)
    granular_dampening_file = Path(f"{config_dir}/solcast-dampening.json")
    if options == DEFAULT_INPUT2:
        assert granular_dampening_file.is_file()

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
        assert len(hass.services.async_services_for_domain(DOMAIN).keys()) == len(SERVICES)
        for service in SERVICES:
            assert hass.services.has_service(DOMAIN, service) is True

        # Test refused update without forcing
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, "update_forecasts", {}, blocking=True)

        # Test forced update and clear data actions
        await _exec_update(hass, solcast, caplog, "force_update_forecasts")
        await _exec_update(hass, solcast, caplog, "force_update_forecasts", wait=False)
        await _exec_update(hass, solcast, caplog, "clear_all_solcast_data")

        # Test for API key redaction
        for api_key in options["api_key"].split(","):
            assert "key=" + api_key not in caplog.text
            assert "key: " + api_key not in caplog.text
            assert "sites-" + api_key not in caplog.text
            assert "usage-" + api_key not in caplog.text

        # Test update within ten seconds of prior update
        solcast.options.auto_update = 0
        await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=5)
        assert "Not requesting a solar forecast because time is within ten seconds of last update" in caplog.text
        assert "ERROR" not in caplog.text
        caplog.clear()

        # Test API too busy
        mock_session_set_too_busy()
        solcast.options.auto_update = 0
        await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=20)
        assert "seconds before retry" in caplog.text
        await solcast.tasks_cancel()
        await hass.async_block_till_done()
        assert "ERROR" not in caplog.text
        caplog.clear()
        mock_session_clear_too_busy()
        await hass.async_block_till_done()

        # Simulate exceed API limit and beyond
        mock_session_set_over_limit()
        await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=20)
        assert "API allowed polling limit has been exceeded" in caplog.text
        assert "No data was returned for forecasts" in caplog.text
        caplog.clear()
        await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=20)
        assert "API polling limit exhausted, not getting forecast" in caplog.text
        caplog.clear()
        mock_session_clear_over_limit()

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
        mock_session_config_reset()
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
        else:
            assert "Granular dampening reloaded" in caplog.text
            assert "Forecast update completed successfully" in caplog.text
            assert "contains all intervals" in caplog.text
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

        mock_session_config_reset()

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

    caplog.clear()

    # Switch to one API key and two sites to assert the initial clean-up
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
            with pytest.raises(factors["expect"]):
                await hass.services.async_call(DOMAIN, "set_dampening", factors["set"], blocking=True)

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

        solcast = await _set_hard_limit("5.0")
        assert solcast.hard_limit == "5.0"
        assert "Build hard limit period values from scratch for dampened" in caplog.text
        assert "Build hard limit period values from scratch for un-dampened" in caplog.text
        for estimate in ["pv_estimate", "pv_estimate10", "pv_estimate90"]:
            assert len(solcast._sites_hard_limit["all"][estimate]) > 0
            assert len(solcast._sites_hard_limit_undampened["all"][estimate]) > 0

        solcast = await _set_hard_limit("5000")
        assert solcast.hard_limit == "5000.0"
        assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set").state == "5.0 MW"

        solcast = await _set_hard_limit("5000000")
        assert solcast.hard_limit == "5000000.0"
        assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set").state == "5.0 GW"

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

        assert "ERROR" not in caplog.text
        caplog.clear()

        # Switch to using two API keys, three sites, start with an out-of-date usage cache
        usage_file = Path(f"{config_dir}/solcast-usage.json")
        data = json.loads(usage_file.read_text(encoding="utf-8"))
        data["reset"] = (dt.now(datetime.UTC) - timedelta(days=5)).isoformat()
        usage_file.write_text(json.dumps(data), encoding="utf-8")
        config = copy.deepcopy(DEFAULT_INPUT2)
        config[API_QUOTA] = "8,8"
        mock_session_config_reset()
        entry = await async_init_integration(hass, config)

        solcast = await _set_hard_limit("100.0,100.0")
        assert solcast.hard_limit == "100.0,100.0"
        assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set_1").state == "False"
        assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set_2").state == "False"

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
            forecast_data = await hass.services.async_call(
                DOMAIN, "query_forecast_data", query["query"], blocking=True, return_response=True
            )
            assert len(forecast_data.get("data", [])) == query["expect"]

        assert "ERROR" not in caplog.text

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
        assert hass.data[DOMAIN].get("presumed_dead", True) is False
        assert "Hard limit is set to limit peak forecast values" in caplog.text
        caplog.clear()

        # Test start with stale data
        data_file = Path(f"{config_dir}/solcast.json")

        def alter_last_updated():
            data = json.loads(data_file.read_text(encoding="utf-8"))
            data["last_updated"] = (dt.now(datetime.UTC) - timedelta(days=5)).isoformat()
            data["last_attempt"] = data["last_updated"]
            data["auto_updated"] = True
            data_file.write_text(json.dumps(data), encoding="utf-8")
            mock_session_config_reset()

        def set_old_solcast_schema():
            data = json.loads(data_file.read_text(encoding="utf-8"))
            data["version"] = 3
            data.pop("last_attempt")
            data.pop("auto_updated")
            data_file.write_text(json.dumps(data), encoding="utf-8")

        def verify_new_solcast_schema():
            data = json.loads(data_file.read_text(encoding="utf-8"))
            assert data["version"] == 5
            assert "last_attempt" in data
            assert "auto_updated" in data

        async def reload():
            _LOGGER.warning("Reloading integration")
            await hass.config_entries.async_reload(entry.entry_id)
            await hass.async_block_till_done()
            if hass.data[DOMAIN].get(entry.entry_id):
                try:
                    return entry.runtime_data.coordinator, patch_solcast_api(coordinator.solcast)
                except:  # noqa: E722
                    _LOGGER.error("Failed to load coordinator (or solcast), which may be expected given test conditions")
            return None, None

        # Test stale start with auto update enabled
        alter_last_updated()
        coordinator, solcast = await reload()
        await _wait_for_update(caplog)
        assert "is older than expected, should be" in caplog.text
        assert solcast._data["last_updated"] > dt.now(datetime.UTC) - timedelta(minutes=10)
        caplog.clear()

        # Test stale start with auto update disabled
        opt = {**entry.options}
        opt[AUTO_UPDATE] = 0
        hass.config_entries.async_update_entry(entry, options=opt)
        await hass.async_block_till_done()
        alter_last_updated()
        coordinator, solcast = await reload()
        # Sneak in an extra update that will be cancelled because update already in progress
        await hass.services.async_call(DOMAIN, "update_forecasts", {}, blocking=True)
        await _wait_for_update(caplog)
        assert "The update automation has not been running, updating forecast" in caplog.text
        assert solcast._data["last_updated"] > dt.now(datetime.UTC) - timedelta(minutes=10)
        caplog.clear()

        # Test API key change, start with an API failure and invalid sites cache
        mock_session_set_too_busy()
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
        assert "sites cache is invalid" in caplog.text
        mock_session_clear_too_busy()
        caplog.clear()

        # Test upgrade schema version
        set_old_solcast_schema()
        coordinator, solcast = await reload()
        assert "version from v3 to v5" in caplog.text
        verify_new_solcast_schema()

        # Test API key change removes sites, and migrates undampened history for new site
        assert "An API key has changed, resetting usage" in caplog.text
        assert "Reset API usage" in caplog.text
        assert "New site(s) have been added" in caplog.text
        assert "Site resource id 1111-1111-1111-1111 is no longer configured" in caplog.text
        assert "Site resource id 2222-2222-2222-2222 is no longer configured" in caplog.text
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
        mock_session_set_too_busy()
        sites_file.write_text(corrupt, encoding="utf-8")
        await reload()
        assert "Exception in __sites_data(): Expecting value:" in caplog.text
        sites_file.write_text(json.dumps(sites), encoding="utf-8")
        mock_session_clear_too_busy()
        caplog.clear()

        # Corrupt usage.json
        usage_corruption = [
            {"daily_limit": "10", "daily_limit_consumed": 8, "reset": "2025-01-05T00:00:00+00:00"},
            {"daily_limit": 10, "daily_limit_consumed": "8", "reset": "2025-01-05T00:00:00+00:00"},
            {"daily_limit": 10, "daily_limit_consumed": 8, "reset": "notadate"},
        ]
        for test in usage_corruption:
            _LOGGER.critical(test)
            usage_file.write_text(json.dumps(test), encoding="utf-8")
            await reload()
            assert entry.state is ConfigEntryState.SETUP_ERROR
        usage_file.write_text(corrupt, encoding="utf-8")
        await reload()
        assert "corrupt, re-creating cache with zero usage" in caplog.text
        usage_file.write_text(json.dumps(usage), encoding="utf-8")
        caplog.clear()

        # Corrupt solcast.json
        _corrupt_data()
        await reload()
        assert "Failed to build forecast data" in caplog.text
        assert "Exception in build_data(): 'period_start'" in caplog.text
        assert "UnboundLocalError in check_data_records()" in caplog.text
        assert hass.data[DOMAIN].get("presumed_dead", True) is True
        caplog.clear()

        _really_corrupt_data()
        await reload()
        assert "The cached data in solcast.json is corrupt" in caplog.text
        assert "integration not ready yet" in caplog.text
        assert hass.data[DOMAIN].get("presumed_dead", True) is True

    finally:
        assert await async_cleanup_integration_tests(hass)
