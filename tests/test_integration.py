"""Tests for the Solcast Solar integration startup, options and scenarios."""

import asyncio
from collections.abc import Callable
import contextlib
import copy
import datetime
from datetime import datetime as dt, timedelta
import json
import logging
from pathlib import Path
import re
from typing import Any, cast
import unittest.mock
from zoneinfo import ZoneInfo

import aiohttp
from aiohttp import ClientConnectionError
from freezegun.api import FrozenDateTimeFactory
import pytest
from voluptuous.error import MultipleInvalid

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar.const import (
    ADVANCED_ALLOW_EXCEED_API_LIMIT_MAXIMUM,
    ADVANCED_ENTITY_LOGGING,
    ADVANCED_FORECAST_DAY_ENTITIES,
    API_KEY,
    API_LIMIT,
    AUTO_DAMPEN,
    AUTO_UPDATE,
    AUTO_UPDATED,
    BRK_ESTIMATE,
    BRK_ESTIMATE10,
    BRK_ESTIMATE90,
    BRK_HALFHOURLY,
    BRK_HOURLY,
    BRK_SITE,
    BRK_SITE_DETAILED,
    CONFIG_DISCRETE_NAME,
    CONFIG_FOLDER_DISCRETE,
    CUSTOM_HOURS,
    DAILY_ACTUALS_CONSUMED,
    DAILY_FORCED_CONSUMED,
    DAILY_LIMIT,
    DAILY_LIMIT_CONSUMED,
    DAILY_TYPICAL,
    DAILY_TYPICAL_FORECAST_UPDATES,
    DAMP_FACTOR,
    DAMPENED_APE_BREAKDOWN,
    DAMPENED_DAILY,
    DAMPENED_MAPE,
    DAMPENED_PERCENTILES,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_SOLCAST_HTTPS_URL,
    DELAYED_RESTART_ON_CRASH,
    DOMAIN,
    ENTITY_ACCURACY,
    ESTIMATE,
    ESTIMATE10,
    ESTIMATE90,
    EVENT_END_DATETIME,
    EVENT_START_DATETIME,
    EXCEPTION_ACTUALS_WITHOUT_GET,
    EXCEPTION_DAMP_NOT_FOR_SITE,
    EXCEPTION_DAMP_USE_ALL,
    EXCEPTION_DAMPEN_WITHOUT_ACTUALS,
    EXCEPTION_DAMPEN_WITHOUT_GENERATION,
    EXCEPTION_EXPORT_NO_ENTITY,
    EXCEPTION_EXPORT_NO_LIMIT,
    EXCEPTION_NOT_A_SITE,
    EXCEPTION_SET_OPTIONS_EMPTY,
    EXCLUDE_SITES,
    FORECASTS,
    GENERATION_ENTITIES,
    GET_ACTUALS,
    HARD_LIMIT,
    HARD_LIMIT_API,
    INFINITY_EXCLUDED,
    ISSUE_CORRUPT_FILE,
    ISSUE_DEPRECATED_REMOVE_HARD_LIMIT,
    ISSUE_DEPRECATED_SET_CUSTOM_HOURS,
    ISSUE_DEPRECATED_SET_HARD_LIMIT,
    KEY_ESTIMATE,
    LAST_ATTEMPT,
    LAST_UPDATED,
    MODEL_PERIOD_DAYS,
    PERIOD_START,
    SERVICE_CLEAR_DATA,
    SERVICE_DIAGNOSTIC,
    SERVICE_FORCE_UPDATE_ESTIMATES,
    SERVICE_FORCE_UPDATE_FORECASTS,
    SERVICE_GET_DAMPENING,
    SERVICE_GET_OPTIONS,
    SERVICE_QUERY_ESTIMATE_DATA,
    SERVICE_QUERY_FORECAST_DATA,
    SERVICE_REMOVE_HARD_LIMIT,
    SERVICE_SET_CUSTOM_HOURS,
    SERVICE_SET_DAMPENING,
    SERVICE_SET_HARD_LIMIT,
    SERVICE_SET_OPTIONS,
    SERVICE_UPDATE,
    SITE,
    SITE_EXPORT_ENTITY,
    SITE_EXPORT_LIMIT,
    SITE_INFO,
    SITES,
    TASK_CHECK_FETCH,
    TASK_LISTENERS,
    TASK_MIDNIGHT_UPDATE,
    TASK_NEW_DAY_ACTUALS,
    UNDAMPENED,
    UNDAMPENED_APE_BREAKDOWN,
    UNDAMPENED_DAILY,
    UNDAMPENED_MAPE,
    UNDAMPENED_PERCENTILES,
    USE_ACTUALS,
)
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.enums import (
    AutoUpdate,
    HistoryType,
    SitesStatus,
)
from homeassistant.components.solcast_solar.forecast import ForecastQuery
from homeassistant.components.solcast_solar.solcastapi import (
    ConnectionOptions,
    SolcastApi,
)
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ServiceValidationError
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.util import dt as dt_util

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
    ZONE_RAW,
    async_cleanup_integration_tests,
    async_init_integration,
    clear_state,
    get_config_dir,
    no_error_or_exception,
    session_clear,
    session_reset_usage,
    session_set,
    set_crash_time,
    set_presumed_dead,
    verify_data_schema,
    write_advanced_options,
)

_LOGGER = logging.getLogger(__name__)
_TEST_POLL_INTERVAL = 0.005

ACTIONS = [
    SERVICE_CLEAR_DATA,
    SERVICE_DIAGNOSTIC,
    SERVICE_FORCE_UPDATE_ESTIMATES,
    SERVICE_FORCE_UPDATE_FORECASTS,
    SERVICE_GET_DAMPENING,
    SERVICE_GET_OPTIONS,
    SERVICE_QUERY_ESTIMATE_DATA,
    SERVICE_QUERY_FORECAST_DATA,
    SERVICE_REMOVE_HARD_LIMIT,
    SERVICE_SET_DAMPENING,
    SERVICE_SET_CUSTOM_HOURS,
    SERVICE_SET_HARD_LIMIT,
    SERVICE_SET_OPTIONS,
    SERVICE_UPDATE,
]

ZONE = ZoneInfo(ZONE_RAW)
NOW = dt.now(ZONE)


@pytest.fixture(autouse=True)
def frozen_time() -> None:
    """Override autouse fixture for this module, disabling use of the freezer feature.

    Time runs in this test suite in real-time, so method replacement is used
    instead of the regular datetime helpers.

    The date is the real date, but the time is spoofed to always be around midday
    for forecast and sensor updates giving predictable responses. Logged time is real time,
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
    solcast.dt_helper.now_utc = get_now_utc  # type: ignore[method-assign]
    solcast.dt_helper.real_now_utc = get_real_now_utc  # type: ignore[method-assign]
    solcast.dt_helper.hour_start_utc = get_hour_start_utc  # type: ignore[method-assign]
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
        last_updated = dt.now(datetime.UTC) - timedelta(seconds=last_update_delta)
        _LOGGER.info("Mock last updated: %s", last_updated)
    solcast.data[LAST_UPDATED] = last_updated
    await hass.services.async_call(DOMAIN, action, {}, blocking=True)
    if wait_exception:
        await _wait_for_raise(hass, wait_exception)
    elif wait:
        await _wait_for_update(hass, caplog)
        await solcast.tasks_cancel()
        # If _wait_for_update exited on "pausing", the outer _forecast_update task is still
        # running: the inner TASK_FORECASTS_FETCH was cancelled but _forecast_update itself
        # is not HA-tracked, so hass.async_block_till_done() won't wait for it.  Under
        # coverage the task can be slow enough to log "Completed task update" *after* the
        # next iteration's caplog.clear(), making _wait_for_update exit on stale content.
        # Wait here until the outer task logs its completion before proceeding.
        if "pausing" in caplog.text:
            last_record = len(caplog.records)
            async with asyncio.timeout(30):
                while True:
                    records = caplog.records
                    for r in records[last_record:]:
                        msg = r.getMessage()
                        if "Completed task update" in msg or "Completed task force_update" in msg:
                            return
                    last_record = len(records)
                    await asyncio.sleep(_TEST_POLL_INTERVAL)
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
        last_updated = dt.now(datetime.UTC) - timedelta(seconds=last_update_delta)
        _LOGGER.info("Mock last updated: %s", last_updated)
    solcast.data_actuals[LAST_UPDATED] = last_updated
    await hass.services.async_call(DOMAIN, action, {}, blocking=True)
    if wait_exception:
        await _wait_for_raise(hass, wait_exception)
    elif wait:
        await _wait_for_update(hass, caplog)
        await solcast.tasks_cancel()
        async with asyncio.timeout(30):
            while coordinator.tasks.get(TASK_NEW_DAY_ACTUALS):
                await asyncio.sleep(_TEST_POLL_INTERVAL)
    await hass.async_block_till_done()


async def _wait_for_update(hass: HomeAssistant, caplog: pytest.LogCaptureFixture, freezer: FrozenDateTimeFactory | None = None) -> None:
    """Wait for forecast update completion."""

    needles = (
        "Forecast update completed successfully",
        "Not requesting a solar forecast",
        "aborting forecast update",
        "update already in progress",
        "pausing",
        "Completed task update",
        "Completed task force_update",
        "Completed task actuals",
        "Completed task force_actuals",
        "ConfigEntryAuthFailed",
    )
    last_record = 0
    async with asyncio.timeout(500 if freezer else 10):
        while True:
            records = caplog.records
            for r in records[last_record:]:
                if any(n in r.getMessage() for n in needles):
                    return
            last_record = len(records)
            if freezer:
                freezer.tick(0.1)
                await hass.async_block_till_done()
            else:
                await asyncio.sleep(_TEST_POLL_INTERVAL)


async def _wait_for_abort(caplog: pytest.LogCaptureFixture) -> None:
    """Wait for forecast update abort."""

    last_record = 0
    async with asyncio.timeout(10):
        while True:
            records = caplog.records
            for r in records[last_record:]:
                msg = r.getMessage()
                if "Forecast update aborted" in msg or "Forecast update already in progress, ignoring" in msg:
                    return
            last_record = len(records)
            await asyncio.sleep(_TEST_POLL_INTERVAL)


async def _wait_for(caplog: pytest.LogCaptureFixture, wait_text: str) -> None:
    """Wait for a log message to appear."""

    last_record = 0
    async with asyncio.timeout(20):
        while True:
            records = caplog.records
            if any(wait_text in r.getMessage() for r in records[last_record:]):
                return
            last_record = len(records)
            await asyncio.sleep(_TEST_POLL_INTERVAL)


async def _wait_for_startup_tasks(hass: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """Wait for startup-triggered tasks that can race with the next test phase."""

    last_record = 0
    stale_update_started = False
    deadline = asyncio.get_running_loop().time() + 1

    while asyncio.get_running_loop().time() < deadline:
        records = caplog.records
        for r in records[last_record:]:
            msg = r.getMessage()
            if "Completed task stale_update" in msg:
                await hass.async_block_till_done()
                return
            if not stale_update_started and "Started task stale_update" in msg:
                stale_update_started = True
                break
        last_record = len(records)
        if stale_update_started:
            break
        await hass.async_block_till_done()
        await asyncio.sleep(_TEST_POLL_INTERVAL)

    if stale_update_started and not any("Completed task stale_update" in r.getMessage() for r in caplog.records):
        await _wait_for(caplog, "Completed task stale_update")
    await hass.async_block_till_done()


async def _wait_for_raise(hass: HomeAssistant, exception: Exception) -> None:
    """Wait for exception."""

    async def wait_for_exception():
        async with asyncio.timeout(10):
            while True:
                await asyncio.sleep(_TEST_POLL_INTERVAL)

    with pytest.raises(exception):  # type: ignore[call-overload]
        await wait_for_exception()


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> tuple[SolcastUpdateCoordinator | None, SolcastApi | None]:
    """Reload the integration."""

    _LOGGER.warning("Reloading integration")
    await hass.config_entries.async_reload(entry.entry_id)
    min_settle_cycles = 3
    for attempt in range(5):
        await hass.async_block_till_done()
        if attempt + 1 < min_settle_cycles:
            continue
        if entry.state is not ConfigEntryState.LOADED:
            continue
        with contextlib.suppress(AttributeError):
            coordinator = entry.runtime_data.coordinator
            return coordinator, patch_solcast_api(coordinator.solcast)
    if entry.state is ConfigEntryState.LOADED:
        _LOGGER.error("Failed to load coordinator (or solcast), which may be expected given test conditions")
    return None, None


async def five_minute_bump(hass: HomeAssistant, caplog: pytest.LogCaptureFixture):
    """Move to a sensor update done."""
    last_record = 0
    async with asyncio.timeout(1):
        while True:
            records = caplog.records
            if any("Updating sensor Dampening" in r.getMessage() for r in records[last_record:]):
                break
            last_record = len(records)
            await asyncio.sleep(_TEST_POLL_INTERVAL)
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
            assert entry.state is ConfigEntryState.SETUP_RETRY, f"Expected entry state ConfigEntryState.SETUP_RETRY, got {entry.state}"
            assert "Get sites failed, last call result: 429/Try again later" in caplog.text
            assert "Cached sites are not yet available" in caplog.text
            caplog.clear()

        def assertions1_bad_data(entry: ConfigEntry):
            assert "API did not return a json object, returned" in caplog.text

        def assertions1_except(entry: ConfigEntry):
            assert entry.state is ConfigEntryState.SETUP_ERROR, f"Expected entry state ConfigEntryState.SETUP_ERROR, got {entry.state}"
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
            caplog.clear()
            session_set(MOCK_BUSY)
            entry = await async_init_integration(hass, DEFAULT_INPUT2)
            assertions(entry)
            if entry.state in (ConfigEntryState.SETUP_ERROR, ConfigEntryState.SETUP_RETRY):
                await hass.config_entries.async_remove(entry.entry_id)
                await hass.async_block_till_done()
            session_clear(MOCK_BUSY)
            await set_presumed_dead(hass, entry, False)

        async def bad_response(assertions: Callable[[ConfigEntry], None]):
            for returned in [MOCK_CORRUPT_SITES, MOCK_CORRUPT_ACTUALS, MOCK_CORRUPT_FORECAST]:
                session_set(returned)
                entry = await async_init_integration(hass, DEFAULT_INPUT2)
                assertions(entry)
                if entry.state in (ConfigEntryState.SETUP_ERROR, ConfigEntryState.SETUP_RETRY):
                    await hass.config_entries.async_remove(entry.entry_id)
                    await hass.async_block_till_done()
                session_clear(returned)
                await set_presumed_dead(hass, entry, False)

        async def exceptions(assertions: Callable[[ConfigEntry], None]):
            session_set(MOCK_EXCEPTION, exception=ConnectionRefusedError)
            entry = await async_init_integration(hass, DEFAULT_INPUT2)
            assertions(entry)
            if entry.state in (ConfigEntryState.SETUP_ERROR, ConfigEntryState.SETUP_RETRY):
                await hass.config_entries.async_remove(entry.entry_id)
                await hass.async_block_till_done()
            await set_presumed_dead(hass, entry, False)
            session_set(MOCK_EXCEPTION, exception=TimeoutError)
            entry = await async_init_integration(hass, DEFAULT_INPUT2)
            assertions(entry)
            if entry.state in (ConfigEntryState.SETUP_ERROR, ConfigEntryState.SETUP_RETRY):
                await hass.config_entries.async_remove(entry.entry_id)
                await hass.async_block_till_done()
            await set_presumed_dead(hass, entry, False)
            session_set(MOCK_EXCEPTION, exception=ClientConnectionError)
            entry = await async_init_integration(hass, DEFAULT_INPUT2)
            assertions(entry)
            if entry.state in (ConfigEntryState.SETUP_ERROR, ConfigEntryState.SETUP_RETRY):
                await hass.config_entries.async_remove(entry.entry_id)
                await hass.async_block_till_done()
            session_clear(MOCK_EXCEPTION)
            await set_presumed_dead(hass, entry, False)

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
                await set_presumed_dead(hass, entry, False)
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
                        await _exec_update(hass, solcast, caplog, SERVICE_FORCE_UPDATE_FORECASTS, last_update_delta=20)
                    solcast.options.auto_update = AutoUpdate.NONE
                else:
                    await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=20)
                    assert test["assertion"] in caplog.text

                assert await hass.config_entries.async_unload(entry.entry_id), "Config entry unload failed"
                if isinstance(test["exception"], str):
                    session_clear(test["exception"])
                else:
                    session_clear(MOCK_EXCEPTION)

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
        caplog.clear()
        entry: ConfigEntry = await async_init_integration(hass, DEFAULT_INPUT2)
        await _wait_for_startup_tasks(hass, caplog)
        assert await hass.config_entries.async_unload(entry.entry_id), "Config entry unload failed"
        await hass.async_block_till_done()

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

        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_schema_upgrade_caller(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test the schema upgrade calling code and undampened history migration."""

    config_dir = f"{hass.config.config_dir}/{CONFIG_DISCRETE_NAME}" if CONFIG_FOLDER_DISCRETE else hass.config.config_dir

    options = copy.deepcopy(DEFAULT_INPUT1)
    options[CONF_API_KEY] = "2"
    entry: ConfigEntry = await async_init_integration(hass, options)
    try:
        data_file = Path(f"{config_dir}/solcast.json")
        undampened_file = Path(f"{config_dir}/solcast-undampened.json")
        original_data = json.loads(data_file.read_text(encoding="utf-8"))

        # Successful upgrade from v4 (exercises solcastapi.py caller + migrate_undampened_history).
        with contextlib.suppress(FileNotFoundError):
            undampened_file.unlink()
        data = copy.deepcopy(original_data)
        data["version"] = 4
        data.pop(LAST_ATTEMPT)
        data.pop(AUTO_UPDATED)
        data_file.write_text(json.dumps(data), encoding="utf-8")
        await _reload(hass, entry)
        assert "version from v4 to v10" in caplog.text
        assert "Migrating un-dampened history" in caplog.text
        upgraded = json.loads(data_file.read_text(encoding="utf-8"))
        assert upgraded["version"] == 10
        caplog.clear()

        # Incompatible schema (exercises the SchemaIncompatibleError except branch).
        with contextlib.suppress(FileNotFoundError):
            undampened_file.unlink()
        data = copy.deepcopy(original_data)
        data.pop("version")
        data.pop(SITE_INFO)
        data.pop(LAST_ATTEMPT)
        data.pop(AUTO_UPDATED)
        data["some_stuff"] = {"fraggle": "rock"}
        data_file.write_text(json.dumps(data), encoding="utf-8")
        _coordinator, solcast = await _reload(hass, entry)
        assert "CRITICAL" in caplog.text
        assert solcast is None, "Solcast API should be None after critical corruption"

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


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
        config_dir = str(get_config_dir(hass.config.config_dir, create=True))
        write_advanced_options(config_dir, {ADVANCED_ENTITY_LOGGING: True})

        # Test startup
        entry: ConfigEntry = await async_init_integration(hass, options | ({GET_ACTUALS: True} if options == DEFAULT_INPUT1 else {}))

        if options == BAD_INPUT:
            assert entry.state is ConfigEntryState.SETUP_ERROR, f"Expected entry state ConfigEntryState.SETUP_ERROR, got {entry.state}"
            assert entry.state is not ConfigEntryState.LOADED, "Integration should be presumed dead"
            assert "Dampening factors corrupt or not found, setting to 1.0" in caplog.text
            assert "Get sites failed, last call result: 403/Forbidden" in caplog.text
            assert "API key is invalid" in caplog.text
            return

        if options == DEFAULT_INPUT_NO_SITES:
            assert entry.state is ConfigEntryState.SETUP_ERROR, f"Expected entry state ConfigEntryState.SETUP_ERROR, got {entry.state}"
            assert "HTTP session returned status 200/Success" in caplog.text
            assert "No sites for the API key ******_sites are configured at solcast.com" in caplog.text
            assert "No sites found for API key" in caplog.text
            return

        assert entry.state is ConfigEntryState.LOADED, f"Expected entry state ConfigEntryState.LOADED, got {entry.state}"
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"

        # Enable the dampening entity
        dampening_entity = "sensor.solcast_pv_forecast_dampening"
        er.async_get(hass).async_update_entity(dampening_entity, disabled_by=None)
        await hass.async_block_till_done()

        coordinator: SolcastUpdateCoordinator | None
        if (coordinator := entry.runtime_data.coordinator) is None:
            pytest.fail("No coordinator")
        solcast: SolcastApi | None = patch_solcast_api(coordinator.solcast)
        granular_dampening_file = Path(f"{config_dir}/solcast-dampening.json")
        assert granular_dampening_file.is_file() is False, f"File {granular_dampening_file} should not exist"

        coordinator, solcast = await _reload(hass, entry)
        if coordinator is None or solcast is None:
            pytest.fail("No coordinator or solcast")

        coordinator._updater.set_next_update()

        assert solcast.sites_status is SitesStatus.OK, f"Expected sites status SitesStatus.OK, got {solcast.sites_status}"
        assert solcast.loaded_data is True, "Solcast data should be loaded"
        assert "Dampening factors corrupt or not found, setting to 1.0" not in caplog.text
        assert solcast.tz == ZONE

        # Test cache files are as expected
        if len(options[API_KEY].split(",")) == 1:
            assert not Path(f"{config_dir}/solcast-sites-1.json").is_file(), (
                f"File {Path(f'{config_dir}/solcast-sites-1.json')} should not exist"
            )
            assert not Path(f"{config_dir}/solcast-sites-2.json").is_file(), (
                f"File {Path(f'{config_dir}/solcast-sites-2.json')} should not exist"
            )
            assert Path(f"{config_dir}/solcast-sites.json").is_file(), f"File {Path(f'{config_dir}/solcast-sites.json')} should exist"
            assert not Path(f"{config_dir}/solcast-usage-1.json").is_file(), (
                f"File {Path(f'{config_dir}/solcast-usage-1.json')} should not exist"
            )
            assert not Path(f"{config_dir}/solcast-usage-2.json").is_file(), (
                f"File {Path(f'{config_dir}/solcast-usage-2.json')} should not exist"
            )
            assert Path(f"{config_dir}/solcast-usage.json").is_file(), f"File {Path(f'{config_dir}/solcast-usage.json')} should exist"
        else:
            assert Path(f"{config_dir}/solcast-sites-1.json").is_file(), f"File {Path(f'{config_dir}/solcast-sites-1.json')} should exist"
            assert Path(f"{config_dir}/solcast-sites-2.json").is_file(), f"File {Path(f'{config_dir}/solcast-sites-2.json')} should exist"
            assert not Path(f"{config_dir}/solcast-sites.json").is_file(), (
                f"File {Path(f'{config_dir}/solcast-sites.json')} should not exist"
            )
            assert Path(f"{config_dir}/solcast-usage-1.json").is_file(), f"File {Path(f'{config_dir}/solcast-usage-1.json')} should exist"
            assert Path(f"{config_dir}/solcast-usage-2.json").is_file(), f"File {Path(f'{config_dir}/solcast-usage-2.json')} should exist"
            assert not Path(f"{config_dir}/solcast-usage.json").is_file(), (
                f"File {Path(f'{config_dir}/solcast-usage.json')} should not exist"
            )

        # Test coordinator tasks are created
        assert coordinator.tasks[TASK_LISTENERS]
        assert coordinator.tasks[TASK_CHECK_FETCH]
        assert coordinator.tasks[TASK_MIDNIGHT_UPDATE]

        # Test expected services are registered
        assert len(hass.services.async_services_for_domain(DOMAIN).keys()) == len(ACTIONS)
        for service in ACTIONS:
            assert hass.services.has_service(DOMAIN, service) is True, f"Service {service} should be registered"

        # Test refused update without forcing
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, "update_forecasts", {}, blocking=True)

        # Test forced update and clear data actions
        caplog.clear()
        _watchfiles_logger = logging.getLogger("watchfiles")
        _watchfiles_level = _watchfiles_logger.level
        _watchfiles_logger.setLevel(logging.WARNING)
        try:
            await _exec_update(hass, solcast, caplog, SERVICE_FORCE_UPDATE_FORECASTS)
        finally:
            _watchfiles_logger.setLevel(_watchfiles_level)

        # Test for API key redaction
        for api_key in options[API_KEY].split(","):
            assert "key=" + api_key not in caplog.text
            assert "key: " + api_key not in caplog.text
            assert "sites-" + api_key not in caplog.text
            assert "usage-" + api_key not in caplog.text

        # Test force, force abort because running and clear data actions
        await _exec_update(hass, solcast, caplog, SERVICE_FORCE_UPDATE_FORECASTS, wait=False)
        caplog.clear()
        await _exec_update(hass, solcast, caplog, SERVICE_FORCE_UPDATE_FORECASTS, wait=False)  # Twice to cover abort force
        await _wait_for_abort(caplog)
        await _exec_update(hass, solcast, caplog, "update_forecasts", wait=False)  # Thrice to cover abort normal
        await _wait_for_abort(caplog)
        await hass.async_block_till_done()
        await _exec_update(hass, solcast, caplog, SERVICE_CLEAR_DATA)  # Will cancel active fetch

        # Test update within ten seconds of prior update
        solcast.options.auto_update = AutoUpdate.NONE
        await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=5)
        assert "Not requesting a solar forecast because time is within ten seconds of last update" in caplog.text
        assert "ERROR" not in caplog.text

        no_error_or_exception(caplog)

        assert await hass.config_entries.async_unload(entry.entry_id), "Config entry unload failed"
        await hass.async_block_till_done()

        session_reset_usage()

    finally:
        assert await async_cleanup_integration_tests(
            hass,
            solcast_dampening=options != DEFAULT_INPUT1,  # Keep dampening file from the DEFAULT_INPUT1 test
            solcast_sites=options != DEFAULT_INPUT1,  # Keep sites cache file from the DEFAULT_INPUT1 test
        ), "Integration test cleanup failed"


async def test_remaining_actions(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Test remaining actions."""

    try:
        config_dir = str(get_config_dir(hass.config.config_dir, create=True))
        write_advanced_options(config_dir, {ADVANCED_ENTITY_LOGGING: True, ADVANCED_FORECAST_DAY_ENTITIES: 10})

        # Start with two API keys and three sites
        entry = await async_init_integration(hass, DEFAULT_INPUT2)
        await _wait_for_startup_tasks(hass, caplog)
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"
        assert await hass.config_entries.async_unload(entry.entry_id), "Config entry unload failed"
        await hass.async_block_till_done()
        no_error_or_exception(caplog)

        # Test for creation of additional forecast day entities
        assert "Registered new sensor.solcast_solar entity: sensor.solcast_pv_forecast_forecast_day_8" in caplog.text
        assert "Registered new sensor.solcast_solar entity: sensor.solcast_pv_forecast_forecast_day_9" in caplog.text

        caplog.clear()

        # Switch to one API key and two sites to assert the initial clean-up
        _LOGGER.debug("Switching to one API key and two sites")
        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        solcast: SolcastApi = patch_solcast_api(entry.runtime_data.coordinator.solcast)
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"

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
            await hass.services.async_call(DOMAIN, SERVICE_FORCE_UPDATE_FORECASTS, {}, blocking=True)

        # Test set/get dampening factors
        async def _clear_granular_dampening():
            # Clear granular dampening
            await hass.services.async_call(DOMAIN, SERVICE_SET_DAMPENING, {DAMP_FACTOR: ("1.0," * 24)[:-1]}, blocking=True)
            expected = {
                "site": "all",
                DAMP_FACTOR: ("1.0," * 24)[:-1],
            }
            for _ in range(50):
                await hass.async_block_till_done()  # Because options change
                dampening = await hass.services.async_call(DOMAIN, SERVICE_GET_DAMPENING, {}, blocking=True, return_response=True)
                if dampening is None:
                    continue
                data = dampening.get("data", [])
                if isinstance(data, list) and data and data[0] == expected:
                    return
            pytest.fail("Dampening did not settle to the expected legacy factors")

        dampening = await hass.services.async_call(DOMAIN, SERVICE_GET_DAMPENING, {}, blocking=True, return_response=True)
        if dampening is not None:
            if isinstance(dampening.get("data", [{}]), list):
                assert (
                    dampening.get("data", [{}])[0]  # type: ignore[index]
                    == {
                        "site": "all",
                        DAMP_FACTOR: ("1.0," * 24)[:-1],
                    }
                )
                odd_factors: list[dict[str, Any]] = [
                    {"set": {}, "expect": MultipleInvalid},  # No factors
                    {"set": {DAMP_FACTOR: "  "}, "expect": ServiceValidationError},  # No factors
                    {"set": {DAMP_FACTOR: ("0.5," * 5)[:-1]}, "expect": ServiceValidationError},  # Insufficient factors
                    {"set": {DAMP_FACTOR: ("0.5," * 15)[:-1]}, "expect": ServiceValidationError},  # Not 24 or 48 factors
                    {"set": {DAMP_FACTOR: ("1.5," * 24)[:-1]}, "expect": ServiceValidationError},  # Out of range factors
                    {"set": {DAMP_FACTOR: ("0.8f," * 24)[:-1]}, "expect": ServiceValidationError},  # Weird factors
                    {
                        "set": {"site": "all", DAMP_FACTOR: ("1.0," * 24)[:-1]},
                        "expect": ServiceValidationError,
                    },  # Site with 24 dampening factors
                ]
                for factors in odd_factors:
                    _LOGGER.debug("Test set odd dampening factors: %s", factors)
                    with pytest.raises(factors["expect"]):
                        await hass.services.async_call(DOMAIN, SERVICE_SET_DAMPENING, factors["set"], blocking=True)
            else:
                pytest.fail("Dampening data is not a list")
        else:
            pytest.fail("Dampening is None")

        _LOGGER.debug("Test set various dampening factors")
        await hass.services.async_call(DOMAIN, SERVICE_SET_DAMPENING, {DAMP_FACTOR: ("0.5," * 24)[:-1]}, blocking=True)
        await hass.async_block_till_done()  # Because options change
        dampening = await hass.services.async_call(DOMAIN, SERVICE_GET_DAMPENING, {}, blocking=True, return_response=True)
        assert dampening.get("data", [{}])[0] == {"site": "all", DAMP_FACTOR: ("0.5," * 24)[:-1]}  # type: ignore[union-attr, index]
        # Granular dampening
        await hass.services.async_call(DOMAIN, SERVICE_SET_DAMPENING, {DAMP_FACTOR: ("0.5," * 48)[:-1]}, blocking=True)
        await hass.async_block_till_done()  # Because options change
        assert Path(f"{config_dir}/solcast-dampening.json").is_file(), f"File {Path(f'{config_dir}/solcast-dampening.json')} should exist"
        dampening = await hass.services.async_call(DOMAIN, SERVICE_GET_DAMPENING, {}, blocking=True, return_response=True)
        assert dampening.get("data", [{}])[0] == {"site": "all", DAMP_FACTOR: ("0.5," * 48)[:-1]}  # type: ignore[union-attr, index]
        # Trigger re-apply forward dampening
        await hass.services.async_call(DOMAIN, SERVICE_SET_DAMPENING, {DAMP_FACTOR: ("0.75," * 48)[:-1]}, blocking=True)
        await hass.async_block_till_done()  # Because options change
        await _clear_granular_dampening()

        # Request dampening for a site when using legacy dampening
        with pytest.raises(ServiceValidationError) as exc_info:
            dampening = await hass.services.async_call(
                DOMAIN, SERVICE_GET_DAMPENING, {"site": "1111-1111-1111-1111"}, blocking=True, return_response=True
            )
        assert exc_info.value.translation_key == EXCEPTION_DAMP_USE_ALL
        # Granular dampening with site
        _LOGGER.debug("Test granular dampening with site")
        await hass.services.async_call(
            DOMAIN, SERVICE_SET_DAMPENING, {"site": "1111_1111_1111_1111", DAMP_FACTOR: ("0.5," * 48)[:-1]}, blocking=True
        )
        await hass.async_block_till_done()  # Because options change
        dampening = await hass.services.async_call(DOMAIN, SERVICE_GET_DAMPENING, {}, blocking=True, return_response=True)
        assert dampening.get("data", [{}])[0] == {"site": "1111-1111-1111-1111", DAMP_FACTOR: ("0.5," * 48)[:-1]}  # type: ignore[union-attr, index]
        dampening = await hass.services.async_call(
            DOMAIN, SERVICE_GET_DAMPENING, {"site": "1111_1111_1111_1111"}, blocking=True, return_response=True
        )
        assert dampening.get("data", [{}])[0] == {"site": "1111_1111_1111_1111", DAMP_FACTOR: ("0.5," * 48)[:-1]}  # type: ignore[union-attr, index]
        with pytest.raises(ServiceValidationError) as exc_info:
            await hass.services.async_call(
                DOMAIN, SERVICE_GET_DAMPENING, {"site": "2222-2222-2222-2222"}, blocking=True, return_response=True
            )
        assert exc_info.value.translation_key == EXCEPTION_DAMP_NOT_FOR_SITE
        with pytest.raises(ServiceValidationError) as exc_info:
            dampening = await hass.services.async_call(
                DOMAIN, SERVICE_SET_DAMPENING, {"site": "9999-9999-9999-9999", DAMP_FACTOR: ("0.5," * 48)[:-1]}, blocking=True
            )
        assert exc_info.value.translation_key == EXCEPTION_NOT_A_SITE
        with pytest.raises(ServiceValidationError) as exc_info:
            dampening = await hass.services.async_call(
                DOMAIN, SERVICE_GET_DAMPENING, {"site": "9999-9999-9999-9999"}, blocking=True, return_response=True
            )
        assert exc_info.value.translation_key == EXCEPTION_NOT_A_SITE
        await hass.services.async_call(DOMAIN, SERVICE_SET_DAMPENING, {"site": "all", DAMP_FACTOR: ("0.5," * 48)[:-1]}, blocking=True)
        caplog.clear()
        dampening = await hass.services.async_call(
            DOMAIN, SERVICE_GET_DAMPENING, {"site": "1111-1111-1111-1111"}, blocking=True, return_response=True
        )
        assert "being overridden by an all sites entry" in caplog.text
        dampening = await hass.services.async_call(
            DOMAIN, SERVICE_GET_DAMPENING, {"site": "2222-2222-2222-2222"}, blocking=True, return_response=True
        )
        assert "being overridden by an all sites entry" in caplog.text
        await _clear_granular_dampening()

        # Test set/clear hard limit
        odd_limits: list[dict[str, Any]] = [
            {"set": {}, "expect": MultipleInvalid},  # No hard limit
            {"set": {HARD_LIMIT: "zzzzzz"}, "expect": ServiceValidationError},  # Silly hard limit
            {"set": {HARD_LIMIT: "-5"}, "expect": ServiceValidationError},  # Negative hard limit
            {"set": {HARD_LIMIT: "5.0,5.0,5.0"}, "expect": ServiceValidationError},  # Too many hard limits
        ]
        for limits in odd_limits:
            _LOGGER.debug("Test set odd hard limit: %s", limits)
            with pytest.raises(limits["expect"]):
                await hass.services.async_call(DOMAIN, SERVICE_SET_HARD_LIMIT, limits["set"], blocking=True)

        async def _set_hard_limit(hard_limit: str) -> SolcastApi:
            await hass.services.async_call(DOMAIN, SERVICE_SET_HARD_LIMIT, {HARD_LIMIT: hard_limit}, blocking=True)
            await hass.async_block_till_done()
            return patch_solcast_api(entry.runtime_data.coordinator.solcast)  # Because integration reloads

        async def _remove_hard_limit() -> SolcastApi:
            await hass.services.async_call(DOMAIN, SERVICE_REMOVE_HARD_LIMIT, {}, blocking=True)
            await hass.async_block_till_done()
            return patch_solcast_api(entry.runtime_data.coordinator.solcast)  # Because integration reloads

        _LOGGER.debug("Test set reasonable hard limit")
        solcast = await _set_hard_limit("5.0")
        assert solcast.hard_limit == "5.0"
        issue = issue_registry.async_get_issue(DOMAIN, ISSUE_DEPRECATED_SET_HARD_LIMIT)
        assert issue is not None, "Issue ISSUE_DEPRECATED_SET_HARD_LIMIT should exist"
        assert issue.translation_placeholders is not None
        assert issue.translation_placeholders.get("deprecated_action") == SERVICE_SET_HARD_LIMIT
        assert "Build hard limit period values from scratch for forecast" in caplog.text
        assert "Build hard limit period values from scratch for undampened forecast" in caplog.text
        for estimate in [ESTIMATE, ESTIMATE10, ESTIMATE90]:
            assert len(solcast._sites_hard_limit["all"][estimate]) > 0
            assert len(solcast._sites_hard_limit_undampened["all"][estimate]) > 0
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

        assert await hass.config_entries.async_unload(entry.entry_id), "Config entry unload failed"
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
        config[API_LIMIT] = "8,8"
        session_reset_usage()
        entry = await async_init_integration(hass, config)

        _LOGGER.debug("Test disable hard limit")
        solcast = await _set_hard_limit("100.0,100.0")
        assert solcast.hard_limit == "100.0,100.0"
        assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set_1").state == "False"  # type: ignore[union-attr]
        assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set_2").state == "False"  # type: ignore[union-attr]

        _LOGGER.debug("Test disable hard limit via zero for both API keys")
        solcast = await _set_hard_limit("0,0")
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
        for api_key in entry.options[API_KEY].split(","):
            for estimate in [ESTIMATE, ESTIMATE10, ESTIMATE90]:
                assert len(solcast._sites_hard_limit[api_key][estimate]) > 0
                assert len(solcast._sites_hard_limit_undampened[api_key][estimate]) > 0
        assert re.search("Build hard limit processing took.+seconds for forecast", caplog.text)
        assert re.search("Build hard limit processing took.+seconds for undampened forecast", caplog.text)

        caplog.clear()
        _LOGGER.debug("Test set single hard limit value for both API keys")
        solcast = await _remove_hard_limit()
        assert solcast.hard_limit == "100.0"
        issue = issue_registry.async_get_issue(DOMAIN, ISSUE_DEPRECATED_REMOVE_HARD_LIMIT)
        assert issue is not None, "Issue ISSUE_DEPRECATED_REMOVE_HARD_LIMIT should exist"
        assert issue.translation_placeholders is not None
        assert issue.translation_placeholders.get("deprecated_action") == SERVICE_REMOVE_HARD_LIMIT
        for estimate in [ESTIMATE, ESTIMATE10, ESTIMATE90]:
            assert len(solcast._sites_hard_limit["all"][estimate]) == 0
            assert len(solcast._sites_hard_limit_undampened["all"][estimate]) == 0
        assert re.search("Build hard limit processing took.+seconds for forecast", caplog.text) is None, (
            "Hard limit processing log should not appear for forecast"
        )
        assert re.search("Build hard limit processing took.+seconds for undampened forecast", caplog.text) is None, (
            "Hard limit processing log should not appear for undampened forecast"
        )

        caplog.clear()
        _LOGGER.debug("Test set hard limit back to multi after single (single to multi transition)")
        solcast = await _set_hard_limit("5.0,5.0")
        assert solcast.hard_limit == "5.0,5.0"
        assert "Hard limit changed from single to multi" in caplog.text

        # Test set custom hours sensor
        _LOGGER.debug("Test set custom hours sensor with invalid inputs")
        invalid_hours = [
            {"set": {"hours": "gah!"}, "expect": ServiceValidationError},
            {"set": {"hours": "3.5"}, "expect": ServiceValidationError},
            {"set": {"hours": "0"}, "expect": ServiceValidationError},
            {"set": {"hours": "-5"}, "expect": ServiceValidationError},
            {"set": {"hours": "145"}, "expect": ServiceValidationError},
        ]
        for hours_test in invalid_hours:
            _LOGGER.debug("Test set invalid custom hours: %s", hours_test)
            with pytest.raises(hours_test["expect"]):
                await hass.services.async_call(DOMAIN, SERVICE_SET_CUSTOM_HOURS, hours_test["set"], blocking=True)

        async def _set_custom_hours(hours: str) -> SolcastApi:
            await hass.services.async_call(DOMAIN, SERVICE_SET_CUSTOM_HOURS, {"hours": hours}, blocking=True)
            await hass.async_block_till_done()
            return patch_solcast_api(entry.runtime_data.coordinator.solcast)  # Because integration reloads

        _LOGGER.debug("Test set custom hours valid inputs")
        solcast = await _set_custom_hours("1")
        assert solcast.custom_hour_sensor == 1
        assert entry.options[CUSTOM_HOURS] == 1
        issue = issue_registry.async_get_issue(DOMAIN, ISSUE_DEPRECATED_SET_CUSTOM_HOURS)
        assert issue is not None, "Issue ISSUE_DEPRECATED_SET_CUSTOM_HOURS should exist"
        assert issue.translation_placeholders is not None
        assert issue.translation_placeholders.get("deprecated_action") == SERVICE_SET_CUSTOM_HOURS
        solcast = await _set_custom_hours("144")
        assert solcast.custom_hour_sensor == 144
        assert entry.options[CUSTOM_HOURS] == 144
        solcast = await _set_custom_hours("  24  ")
        assert solcast.custom_hour_sensor == 24
        assert entry.options[CUSTOM_HOURS] == 24

        caplog.clear()

        # Test set_options action
        _LOGGER.debug("Test set_options with no data")
        with pytest.raises(ServiceValidationError) as exc_info:
            await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {}, blocking=True)
        assert exc_info.value.translation_key == EXCEPTION_SET_OPTIONS_EMPTY

        _LOGGER.debug("Test set_options with invalid hard limit")
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {HARD_LIMIT: "zzzz"}, blocking=True)

        _LOGGER.debug("Test set_options with invalid custom hours")
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {CUSTOM_HOURS: "0"}, blocking=True)

        _LOGGER.debug("Test set_options with invalid auto update (boolean coerced to string)")
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {AUTO_UPDATE: "True"}, blocking=True)

        _LOGGER.debug("Test set_options with invalid key estimate")
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {KEY_ESTIMATE: "bad"}, blocking=True)

        _LOGGER.debug("Test set_options with invalid use actuals")
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {USE_ACTUALS: "5"}, blocking=True)

        _LOGGER.debug("Test set_options with invalid export limit")
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {SITE_EXPORT_LIMIT: "abc"}, blocking=True)

        _LOGGER.debug("Test set_options with out of range export limit")
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {SITE_EXPORT_LIMIT: "101"}, blocking=True)

        _LOGGER.debug("Test set_options with invalid api_limit")
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {API_LIMIT: "abc"}, blocking=True)

        _LOGGER.debug("Test set_options with api_limit exceeding default maximum")
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {API_LIMIT: "51"}, blocking=True)

        _LOGGER.debug("Test set_options with api_limit exceeding maximum when advanced override is enabled")
        base_config_dir = Path(hass.config.config_dir)
        write_advanced_options(base_config_dir, {ADVANCED_ALLOW_EXCEED_API_LIMIT_MAXIMUM: True})
        await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {API_LIMIT: "51"}, blocking=True)
        await hass.async_block_till_done()
        assert entry.options[API_LIMIT] == "51"

        _LOGGER.debug("Test set_options with invalid use_actuals (boolean coerced to string)")
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {USE_ACTUALS: "True"}, blocking=True)

        _LOGGER.debug("Test set_options with invalid use_actuals (out of range)")
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {USE_ACTUALS: "3"}, blocking=True)

        _LOGGER.debug("Test set_options with empty api_key")
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {API_KEY: ""}, blocking=True)

        _LOGGER.debug("Test set_options with duplicate api_key")
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {API_KEY: "abc123,abc123"}, blocking=True)

        _LOGGER.debug("Test set_options with valid api_key (same key, no reload)")
        original_key = entry.options[CONF_API_KEY]
        await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {API_KEY: original_key}, blocking=True)
        await hass.async_block_till_done()
        assert entry.options[CONF_API_KEY] == original_key

        # Cross-validation errors
        _LOGGER.debug("Test set_options use_actuals without get_actuals")
        with pytest.raises(ServiceValidationError) as exc_info:
            await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {USE_ACTUALS: "1", GET_ACTUALS: False}, blocking=True)
        assert exc_info.value.translation_key == EXCEPTION_ACTUALS_WITHOUT_GET

        _LOGGER.debug("Test set_options auto_dampen without get_actuals")
        with pytest.raises(ServiceValidationError) as exc_info:
            await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {AUTO_DAMPEN: True, GET_ACTUALS: False}, blocking=True)
        assert exc_info.value.translation_key == EXCEPTION_DAMPEN_WITHOUT_ACTUALS

        _LOGGER.debug("Test set_options auto_dampen without generation entities")
        with pytest.raises(ServiceValidationError) as exc_info:
            await hass.services.async_call(
                DOMAIN, SERVICE_SET_OPTIONS, {AUTO_DAMPEN: True, GET_ACTUALS: True, GENERATION_ENTITIES: ""}, blocking=True
            )
        assert exc_info.value.translation_key == EXCEPTION_DAMPEN_WITHOUT_GENERATION

        _LOGGER.debug("Test set_options export limit without entity")
        with pytest.raises(ServiceValidationError) as exc_info:
            await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {SITE_EXPORT_LIMIT: "5.0", SITE_EXPORT_ENTITY: ""}, blocking=True)
        assert exc_info.value.translation_key == EXCEPTION_EXPORT_NO_ENTITY

        _LOGGER.debug("Test set_options export entity without limit")
        with pytest.raises(ServiceValidationError) as exc_info:
            await hass.services.async_call(
                DOMAIN, SERVICE_SET_OPTIONS, {SITE_EXPORT_ENTITY: "sensor.grid_export", SITE_EXPORT_LIMIT: "0.0"}, blocking=True
            )
        assert exc_info.value.translation_key == EXCEPTION_EXPORT_NO_LIMIT

        # Valid set_options calls
        _LOGGER.debug("Test set_options custom hours only")
        await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {CUSTOM_HOURS: "12"}, blocking=True)
        await hass.async_block_till_done()
        assert entry.options[CUSTOM_HOURS] == 12

        _LOGGER.debug("Test set_options hard limit only")
        await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {HARD_LIMIT: "5000"}, blocking=True)
        await hass.async_block_till_done()
        assert entry.options[HARD_LIMIT_API] == "5000.0"

        _LOGGER.debug("Test set_options auto update")
        await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {AUTO_UPDATE: "2"}, blocking=True)
        await hass.async_block_till_done()
        assert entry.options[AUTO_UPDATE] == 2

        _LOGGER.debug("Test set_options key estimate")
        await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {KEY_ESTIMATE: "estimate10"}, blocking=True)
        await hass.async_block_till_done()
        assert entry.options[KEY_ESTIMATE] == "estimate10"

        _LOGGER.debug("Test set_options boolean breakdowns")
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_OPTIONS,
            {
                BRK_ESTIMATE: False,
                BRK_ESTIMATE10: False,
                BRK_ESTIMATE90: False,
                BRK_SITE: False,
                BRK_HALFHOURLY: False,
                BRK_HOURLY: False,
                BRK_SITE_DETAILED: True,
            },
            blocking=True,
        )
        await hass.async_block_till_done()
        assert entry.options[BRK_ESTIMATE] is False, "Expected option BRK_ESTIMATE to be False"
        assert entry.options[BRK_ESTIMATE10] is False, "Expected option BRK_ESTIMATE10 to be False"
        assert entry.options[BRK_ESTIMATE90] is False, "Expected option BRK_ESTIMATE90 to be False"
        assert entry.options[BRK_SITE] is False, "Expected option BRK_SITE to be False"
        assert entry.options[BRK_HALFHOURLY] is False, "Expected option BRK_HALFHOURLY to be False"
        assert entry.options[BRK_HOURLY] is False, "Expected option BRK_HOURLY to be False"
        assert entry.options[BRK_SITE_DETAILED] is True, "Expected option BRK_SITE_DETAILED to be True"

        _LOGGER.debug("Test set_options get actuals and use actuals")
        await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {GET_ACTUALS: True, USE_ACTUALS: "1"}, blocking=True)
        await hass.async_block_till_done()
        assert entry.options[GET_ACTUALS] is True, "Expected option GET_ACTUALS to be True"
        assert entry.options[USE_ACTUALS] == 1

        _LOGGER.debug("Test set_options generation entities and exclude sites")
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_OPTIONS,
            {GENERATION_ENTITIES: "sensor.pv1, sensor.pv2", EXCLUDE_SITES: "1111-1111-1111-1111"},
            blocking=True,
        )
        await hass.async_block_till_done()
        assert entry.options[GENERATION_ENTITIES] == ["sensor.pv1", "sensor.pv2"]
        assert entry.options[EXCLUDE_SITES] == ["1111-1111-1111-1111"]

        _LOGGER.debug("Test set_options site export")
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_OPTIONS,
            {SITE_EXPORT_ENTITY: "sensor.grid_export", SITE_EXPORT_LIMIT: "5.0"},
            blocking=True,
        )
        await hass.async_block_till_done()
        assert entry.options[SITE_EXPORT_ENTITY] == "sensor.grid_export"
        assert entry.options[SITE_EXPORT_LIMIT] == 5.0

        _LOGGER.debug("Test set_options api_limit valid")
        await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {API_LIMIT: "15"}, blocking=True)
        await hass.async_block_till_done()
        assert entry.options[API_LIMIT] == "15"

        _LOGGER.debug("Test set_options auto_dampen")
        await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {AUTO_DAMPEN: True}, blocking=True)
        await hass.async_block_till_done()
        assert entry.options[AUTO_DAMPEN] is True, "Expected option AUTO_DAMPEN to be True"

        # Reset breakdowns to True for later tests
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_OPTIONS,
            {
                BRK_ESTIMATE: True,
                BRK_ESTIMATE10: True,
                BRK_ESTIMATE90: True,
                BRK_SITE: True,
                BRK_HALFHOURLY: True,
                BRK_HOURLY: True,
                BRK_SITE_DETAILED: False,
                HARD_LIMIT: "100",
                CUSTOM_HOURS: "24",
                AUTO_UPDATE: "0",
                KEY_ESTIMATE: "estimate",
                GET_ACTUALS: False,
                USE_ACTUALS: "0",
                AUTO_DAMPEN: False,
                GENERATION_ENTITIES: "",
                EXCLUDE_SITES: "",
                SITE_EXPORT_ENTITY: "",
                SITE_EXPORT_LIMIT: "0",
            },
            blocking=True,
        )
        await hass.async_block_till_done()

        caplog.clear()

        # Test get_options action
        _LOGGER.debug("Test get_options returns current configuration")
        expect = {
            CONF_API_KEY: entry.options[CONF_API_KEY],
            API_LIMIT: entry.options[API_LIMIT],
            AUTO_UPDATE: entry.options[AUTO_UPDATE],
            KEY_ESTIMATE: entry.options[KEY_ESTIMATE],
            CUSTOM_HOURS: entry.options[CUSTOM_HOURS],
            HARD_LIMIT: entry.options[HARD_LIMIT_API],
            BRK_ESTIMATE: entry.options[BRK_ESTIMATE],
            BRK_ESTIMATE10: entry.options[BRK_ESTIMATE10],
            BRK_ESTIMATE90: entry.options[BRK_ESTIMATE90],
            BRK_SITE: entry.options[BRK_SITE],
            BRK_HALFHOURLY: entry.options[BRK_HALFHOURLY],
            BRK_HOURLY: entry.options[BRK_HOURLY],
            BRK_SITE_DETAILED: entry.options[BRK_SITE_DETAILED],
            GET_ACTUALS: entry.options[GET_ACTUALS],
            USE_ACTUALS: entry.options[USE_ACTUALS],
            AUTO_DAMPEN: entry.options[AUTO_DAMPEN],
            GENERATION_ENTITIES: ",".join(entry.options[GENERATION_ENTITIES]),
            EXCLUDE_SITES: ",".join(entry.options[EXCLUDE_SITES]),
            SITE_EXPORT_ENTITY: entry.options[SITE_EXPORT_ENTITY],
            SITE_EXPORT_LIMIT: entry.options[SITE_EXPORT_LIMIT],
        }
        result = await hass.services.async_call(DOMAIN, SERVICE_GET_OPTIONS, {}, blocking=True, return_response=True)
        assert result is not None, "get_options result is None"
        data = result.get("data")
        assert data is not None, "get_options data is None"
        for key, value in expect.items():
            assert data[key] == value  # type: ignore[union-attr]
        unexpected = set(data.keys()) - set(expect.keys())  # pyright: ignore[reportAttributeAccessIssue]
        assert not unexpected, f"get_options returned unexpected keys: {unexpected}"

        _LOGGER.debug("Test get_options after modifying options")
        await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {CUSTOM_HOURS: "48", AUTO_UPDATE: "2"}, blocking=True)
        await hass.async_block_till_done()
        result = await hass.services.async_call(DOMAIN, SERVICE_GET_OPTIONS, {}, blocking=True, return_response=True)
        assert result is not None, "get_options result is None"
        assert result["data"][CUSTOM_HOURS] is not None and result["data"][CUSTOM_HOURS] == 48  # type: ignore[union-attr]
        assert result["data"][AUTO_UPDATE] is not None and result["data"][AUTO_UPDATE] == 2  # type: ignore[union-attr]

        # Reset changes
        await hass.services.async_call(DOMAIN, SERVICE_SET_OPTIONS, {CUSTOM_HOURS: "24", AUTO_UPDATE: "0"}, blocking=True)
        await hass.async_block_till_done()

        caplog.clear()

        # Test query forecast data
        queries: list[dict[str, Any]] = [
            {
                "query": {
                    EVENT_START_DATETIME: solcast.dt_helper.day_start_utc().isoformat(),
                    EVENT_END_DATETIME: solcast.dt_helper.day_start_utc(future=1).isoformat(),
                },
                "expect": 48,
            },
            {
                "query": {
                    EVENT_START_DATETIME: solcast.dt_helper.day_start_utc().isoformat(),
                    EVENT_END_DATETIME: solcast.dt_helper.day_start_utc(future=1).isoformat(),
                    UNDAMPENED: True,
                },
                "expect": 48,
            },
            {
                "query": {
                    EVENT_START_DATETIME: (solcast.dt_helper.day_start_utc(future=-1) + timedelta(hours=3)).isoformat(),
                    EVENT_END_DATETIME: solcast.dt_helper.day_start_utc().isoformat(),
                    SITE: "1111-1111-1111-1111",
                },
                "expect": 42,
            },
            {
                "query": {
                    EVENT_START_DATETIME: solcast.dt_helper.day_start_utc(future=-3).isoformat(),
                    EVENT_END_DATETIME: solcast.dt_helper.day_start_utc(future=-1).isoformat(),
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
                SERVICE_QUERY_FORECAST_DATA,
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
                SERVICE_QUERY_FORECAST_DATA,
                {
                    EVENT_START_DATETIME: solcast.dt_helper.day_start_utc(future=DEFAULT_FORECAST_DAYS + 2).isoformat(),
                    EVENT_END_DATETIME: solcast.dt_helper.day_start_utc(future=DEFAULT_FORECAST_DAYS + 6).isoformat(),
                },
                blocking=True,
                return_response=True,
            )

        # Test invalid site
        _LOGGER.debug("Testing invalid site for query forecast data")
        with pytest.raises(ServiceValidationError) as exc_info:
            await hass.services.async_call(
                DOMAIN,
                SERVICE_QUERY_FORECAST_DATA,
                {
                    EVENT_START_DATETIME: solcast.dt_helper.day_start_utc().isoformat(),
                    EVENT_END_DATETIME: solcast.dt_helper.day_start_utc(future=1).isoformat(),
                    SITE: "9999-9999-9999-9999",
                },
                blocking=True,
                return_response=True,
            )
        assert exc_info.value.translation_key == EXCEPTION_NOT_A_SITE

        # Verify data schema
        verify_data_schema(solcast.data)
        verify_data_schema(solcast.data_undampened)
        verify_data_schema(solcast.data_actuals)
        verify_data_schema(solcast.data_actuals_dampened)

        assert await hass.config_entries.async_unload(entry.entry_id), "Config entry unload failed"
        await hass.async_block_till_done()

        # Test call an action with no entry loaded
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, "update_forecasts", {}, blocking=True)
        assert "Integration not loaded" in caplog.text

        no_error_or_exception(caplog)

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


@pytest.mark.parametrize(
    "options",
    [
        DEFAULT_INPUT1,
        DEFAULT_INPUT2,
    ],
)
async def test_usage_cache_persists_usage_counters(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    options: dict[str, Any],
) -> None:
    """Test usage cache persists estimated-actuals and forced counters across reloads."""

    try:
        config_dir = str(get_config_dir(hass.config.config_dir, create=True))
        entry: ConfigEntry = await async_init_integration(hass, options | ({GET_ACTUALS: True} if options == DEFAULT_INPUT1 else {}))
        assert entry.state is ConfigEntryState.LOADED, f"Expected entry state ConfigEntryState.LOADED, got {entry.state}"

        actuals_seed = 3
        forced_seed = 2
        multi_key = len(options[API_KEY].split(",")) > 1
        for api_key in options[API_KEY].split(","):
            api_key = api_key.strip()
            usage_file = Path(f"{config_dir}/solcast-usage{'' if not multi_key else '-' + api_key}.json")
            usage = json.loads(usage_file.read_text(encoding="utf-8"))
            usage[DAILY_ACTUALS_CONSUMED] = actuals_seed
            usage[DAILY_FORCED_CONSUMED] = forced_seed
            usage_file.write_text(json.dumps(usage), encoding="utf-8")

        _coordinator, solcast = await _reload(hass, entry)
        if solcast is None:
            pytest.fail("No solcast")

        for api_key in options[API_KEY].split(","):
            api_key = api_key.strip()
            assert solcast.api_actuals.get(api_key) == actuals_seed, (
                f"Expected persisted daily actuals usage {actuals_seed} for {api_key}, got {solcast.api_actuals.get(api_key)}"
            )
            assert solcast.api_forced.get(api_key) == forced_seed, (
                f"Expected persisted daily forced usage {forced_seed} for {api_key}, got {solcast.api_forced.get(api_key)}"
            )

        no_error_or_exception(caplog)

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_usage_typical_forecast_updates_default(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test backfill of daily_typical_forecast_updates when missing."""

    api_key = "unit_test_api_key"
    typical_seed = 6
    forced_seed = 2

    async with aiohttp.ClientSession() as session:
        connection_options = ConnectionOptions(
            api_key,
            cast(str, DEFAULT_INPUT1[API_LIMIT]),
            DEFAULT_SOLCAST_HTTPS_URL,
            "solcast.json",
            ZoneInfo(ZONE_RAW),
            AutoUpdate(int(DEFAULT_INPUT1[AUTO_UPDATE])),
            {str(hour): cast(float, DEFAULT_INPUT1[f"damp{hour:02}"]) for hour in range(24)},
            cast(int, DEFAULT_INPUT1[CUSTOM_HOURS]),
            cast(str, DEFAULT_INPUT1[KEY_ESTIMATE]),
            cast(str, DEFAULT_INPUT1[HARD_LIMIT_API]),
            cast(bool, DEFAULT_INPUT1[BRK_ESTIMATE]),
            cast(bool, DEFAULT_INPUT1[BRK_ESTIMATE10]),
            cast(bool, DEFAULT_INPUT1[BRK_ESTIMATE90]),
            cast(bool, DEFAULT_INPUT1[BRK_SITE]),
            cast(bool, DEFAULT_INPUT1[BRK_HALFHOURLY]),
            cast(bool, DEFAULT_INPUT1[BRK_HOURLY]),
            cast(bool, DEFAULT_INPUT1[BRK_SITE_DETAILED]),
            cast(list[str], DEFAULT_INPUT1[EXCLUDE_SITES]),
            cast(bool, DEFAULT_INPUT1[GET_ACTUALS]),
            cast(HistoryType, DEFAULT_INPUT1[USE_ACTUALS]),
            cast(list[str], DEFAULT_INPUT1[GENERATION_ENTITIES]),
            cast(str, DEFAULT_INPUT1[SITE_EXPORT_ENTITY]),
            cast(float, DEFAULT_INPUT1[SITE_EXPORT_LIMIT]),
            cast(bool, DEFAULT_INPUT1[AUTO_DAMPEN]),
        )
        solcast = SolcastApi(session, connection_options, hass)
        usage_file = Path(solcast.sites_cache._get_usage_cache_filename(api_key))
        usage_file.write_text(
            json.dumps(
                {
                    DAILY_LIMIT: int(DEFAULT_INPUT1[API_LIMIT]),
                    DAILY_LIMIT_CONSUMED: 0,
                    DAILY_FORCED_CONSUMED: forced_seed,
                    DAILY_ACTUALS_CONSUMED: 0,
                    DAILY_TYPICAL: typical_seed,
                    "reset": dt.now(datetime.UTC).isoformat(),
                }
            ),
            encoding="utf-8",
        )

        await solcast.sites_cache._sites_usage()

        assert solcast.api_typical.get(api_key) == typical_seed
        assert solcast.api_forced.get(api_key) == forced_seed
        assert solcast.api_typical_forecast_updates.get(api_key) == typical_seed + forced_seed, (
            "Expected backfilled daily_typical_forecast_updates to equal daily_typical + daily_forced_consumed"
        )

        usage = json.loads(usage_file.read_text(encoding="utf-8"))
        assert usage[DAILY_TYPICAL_FORECAST_UPDATES] == typical_seed + forced_seed

    assert "Usage loaded and cache updated with typical forecast updates" in caplog.text
    no_error_or_exception(caplog)


async def test_scenarios(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    issue_registry: ir.IssueRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test various integration scenarios."""

    try:
        config_dir = str(get_config_dir(hass.config.config_dir, create=True))
        write_advanced_options(config_dir, {ADVANCED_ENTITY_LOGGING: True})

        freezer.move_to(dt.now(tz=ZoneInfo(ZONE_RAW)).replace(hour=12, minute=0, second=0, microsecond=0))

        options = copy.deepcopy(DEFAULT_INPUT1)
        options[HARD_LIMIT_API] = "6.0"
        entry = await async_init_integration(hass, options, timezone=ZONE_RAW)
        coordinator = entry.runtime_data.coordinator
        solcast = patch_solcast_api(coordinator.solcast)

        # Test bad serialise data while an entry exists
        _LOGGER.debug("Testing bad serialise data")
        async with aiohttp.ClientSession() as session:
            connection_options = ConnectionOptions(
                cast(str, DEFAULT_INPUT1[CONF_API_KEY]),
                cast(str, DEFAULT_INPUT1[API_LIMIT]),
                "api.whatever.com",
                config_dir,
                ZoneInfo(ZONE_RAW),
                AutoUpdate(int(DEFAULT_INPUT1[AUTO_UPDATE])),
                {str(hour): cast(float, DEFAULT_INPUT1[f"damp{hour:02}"]) for hour in range(24)},
                cast(int, DEFAULT_INPUT1[CUSTOM_HOURS]),
                cast(str, DEFAULT_INPUT1[KEY_ESTIMATE]),
                cast(str, DEFAULT_INPUT1[HARD_LIMIT_API]),
                cast(bool, DEFAULT_INPUT1[BRK_ESTIMATE]),
                cast(bool, DEFAULT_INPUT1[BRK_ESTIMATE10]),
                cast(bool, DEFAULT_INPUT1[BRK_ESTIMATE90]),
                cast(bool, DEFAULT_INPUT1[BRK_SITE]),
                cast(bool, DEFAULT_INPUT1[BRK_HALFHOURLY]),
                cast(bool, DEFAULT_INPUT1[BRK_HOURLY]),
                cast(bool, DEFAULT_INPUT1[BRK_SITE_DETAILED]),
                cast(list[str], DEFAULT_INPUT1[EXCLUDE_SITES]),
                cast(bool, DEFAULT_INPUT1[GET_ACTUALS]),
                cast(HistoryType, DEFAULT_INPUT1[USE_ACTUALS]),
                cast(list[str], DEFAULT_INPUT1[GENERATION_ENTITIES]),
                cast(str, DEFAULT_INPUT1[SITE_EXPORT_ENTITY]),
                cast(float, DEFAULT_INPUT1[SITE_EXPORT_LIMIT]),
                cast(bool, DEFAULT_INPUT1[AUTO_DAMPEN]),
            )
            solcast_bad: SolcastApi = SolcastApi(session, connection_options, hass, entry)
            await solcast_bad.sites_cache.serialise_data(solcast_bad.data, str(Path(f"{config_dir}/solcast.json")))
            assert "Not serialising empty data" in caplog.text

        # Assert good start
        _LOGGER.debug("Testing good start happened")
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"
        assert "Hard limit is set to limit peak forecast values" in caplog.text
        no_error_or_exception(caplog)
        caplog.clear()

        # Test start with stale data
        data_file = Path(f"{config_dir}/solcast.json")
        data_file_undampened = Path(f"{config_dir}/solcast-undampened.json")
        original_data = json.loads(data_file.read_text(encoding="utf-8"))

        def alter_in_memory_as_stale():
            extant_data = copy.deepcopy(solcast.data_forecasts)  # pyright: ignore[reportOptionalMemberAccess]
            solcast.data_forecasts = [f for f in extant_data if f[PERIOD_START] >= dt.now(datetime.UTC).replace(second=0, microsecond=0)]  # pyright: ignore[reportOptionalMemberAccess]

        def alter_last_updated_as_stale():
            data = json.loads(data_file.read_text(encoding="utf-8"))
            data[LAST_UPDATED] = (dt.now(datetime.UTC) - timedelta(days=5)).isoformat()
            data[LAST_ATTEMPT] = data[LAST_UPDATED]
            data[AUTO_UPDATED] = 10
            # Remove forecasts today up to "now"
            for site in data[SITE_INFO].values():
                site[FORECASTS] = [f for f in site[FORECASTS] if f[PERIOD_START] > dt.now(datetime.UTC).isoformat()]
            data_file.write_text(json.dumps(data), encoding="utf-8")
            session_reset_usage()

        def alter_last_updated_as_very_stale():
            for d_file in [data_file, data_file_undampened]:
                data = json.loads(d_file.read_text(encoding="utf-8"))
                data[LAST_UPDATED] = (dt.now(datetime.UTC) - timedelta(days=DEFAULT_FORECAST_DAYS + 1)).isoformat()
                data[LAST_ATTEMPT] = data[LAST_UPDATED]
                data[AUTO_UPDATED] = 10
                # Shift all forecast intervals back nine days
                for site in data[SITE_INFO].values():
                    site[FORECASTS] = [
                        {
                            PERIOD_START: (dt.fromisoformat(f[PERIOD_START]) - timedelta(days=DEFAULT_FORECAST_DAYS + 1)).isoformat(),
                            ESTIMATE: f[ESTIMATE],
                            ESTIMATE10: f[ESTIMATE10],
                            ESTIMATE90: f[ESTIMATE90],
                        }
                        for f in site[FORECASTS]
                    ]
                d_file.write_text(json.dumps(data), encoding="utf-8")
            session_reset_usage()

        def alter_last_updated_as_fresh(last_update: str):
            data = json.loads(data_file.read_text(encoding="utf-8"))
            data[LAST_UPDATED] = last_update
            data[LAST_ATTEMPT] = data[LAST_UPDATED]
            data[AUTO_UPDATED] = 10
            data_file.write_text(json.dumps(data), encoding="utf-8")

        def restore_data():
            data_file.write_text(json.dumps(original_data), encoding="utf-8")

        # Test missing data at beginning of forecast data set
        _LOGGER.debug("Testing remaining and moment with missing prior data")
        await coordinator._update_integration_listeners()
        state_assertions = {
            "sensor.solcast_pv_forecast_power_in_30_minutes": 6000,
            "sensor.solcast_pv_forecast_forecast_remaining_today": 21.944,
        }

        def assert_state_assertions(pre_post: str):
            for entity_id, expected_state in state_assertions.items():
                _LOGGER.debug("Asserting %s state for %s is %s", pre_post, entity_id, expected_state)
                state = hass.states.get(entity_id)
                assert state is not None, f"State for {entity_id} should exist"
                assert float(state.state) == expected_state

        assert_state_assertions("pre-update")
        alter_in_memory_as_stale()
        await solcast.query.recalculate_splines()
        await coordinator._update_integration_listeners()
        assert_state_assertions("post-update")

        # Diagnostic should report a missed auto-update interval in this scenario
        interval_just_passed = dt.now(datetime.UTC).replace(second=0, microsecond=0) - timedelta(minutes=10)
        coordinator._updater.interval_just_passed = interval_just_passed
        solcast.data[LAST_UPDATED] = interval_just_passed + timedelta(minutes=1)
        solcast.data[LAST_ATTEMPT] = interval_just_passed - timedelta(minutes=1)
        solcast.data[AUTO_UPDATED] = coordinator.divisions
        result = await hass.services.async_call(DOMAIN, SERVICE_DIAGNOSTIC, {}, blocking=True, return_response=True)
        data = result["data"]  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["forecast_health"]["status"] == "missed_interval"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert any("missed the expected auto-update interval" in issue for issue in data["issues"])  # pyright: ignore[reportGeneralTypeIssues, reportOptionalIterable, reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        # Test stale start with auto update enabled
        _LOGGER.debug("Testing stale start with auto update enabled")
        alter_last_updated_as_stale()

        coordinator, solcast = await _reload(hass, entry)
        if coordinator is None or solcast is None:
            pytest.fail("Reload failed")
        await _wait_for_update(hass, caplog, freezer)
        assert "is older than expected, should be" in caplog.text
        assert solcast.data[LAST_UPDATED] > dt.now(datetime.UTC) - timedelta(minutes=10)
        assert "ERROR" not in caplog.text
        no_error_or_exception(caplog)

        # Get last auto-update time for a subsequent test
        assert coordinator.interval_just_passed is not None
        last_update = coordinator.interval_just_passed.isoformat()

        caplog.clear()
        restore_data()

        # Test very stale start with auto update enabled
        _LOGGER.debug("Testing very stale start with auto update enabled")
        alter_last_updated_as_very_stale()
        coordinator, solcast = await _reload(hass, entry)
        if coordinator is None or solcast is None:
            pytest.fail("Reload failed")
        await _wait_for_update(hass, caplog, freezer)
        assert "is older than expected, should be" in caplog.text
        assert solcast.data[LAST_UPDATED] > dt.now(datetime.UTC) - timedelta(minutes=10)
        assert "hours of past data" in caplog.text
        assert "ERROR" not in caplog.text
        no_error_or_exception(caplog)

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
        await _wait_for_update(hass, caplog, freezer)
        assert "The update automation has not been running" in caplog.text
        no_error_or_exception(caplog)

        caplog.clear()
        restore_data()

        # Test very stale start with auto update disabled
        _LOGGER.debug("Testing very stale start with auto update disabled")
        alter_last_updated_as_very_stale()
        coordinator, solcast = await _reload(hass, entry)
        if coordinator is None or solcast is None:
            pytest.fail("Reload failed")
        await _wait_for_update(hass, caplog, freezer)
        assert "The update automation has not been running" in caplog.text
        assert solcast.data[LAST_UPDATED] > dt.now(datetime.UTC) - timedelta(minutes=10)
        assert "hours of past data" in caplog.text
        assert "ERROR" not in caplog.text
        no_error_or_exception(caplog)

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
        result = await hass.services.async_call(DOMAIN, SERVICE_DIAGNOSTIC, {}, blocking=True, return_response=True)
        data = result["data"]  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["forecast_health"]["status"] == "fresh"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

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
        data[SITES][0].pop(API_KEY)
        data[SITES][1][API_KEY] = "888"
        sites_file.write_text(json.dumps(data), encoding="utf-8")
        opt = {**entry.options}
        opt[CONF_API_KEY] = "2"
        hass.config_entries.async_update_entry(entry, options=opt)
        await hass.async_block_till_done()
        assert "Options updated, action: The integration will reload" in caplog.text
        assert "has changed and sites are different invalidating the cache" in caplog.text
        session_clear(MOCK_BUSY)
        caplog.clear()
        await set_presumed_dead(hass, entry, False)  # Clear presumption of death
        coordinator, solcast = await _reload(hass, entry)
        if coordinator is None or solcast is None:
            pytest.fail("Reload failed")
        assert "An API key has changed with a new site added" in caplog.text
        assert "Reset API usage" in caplog.text
        assert "New site(s) have been added" in caplog.text
        assert "Site resource id 1111-1111-1111-1111 is no longer configured" in caplog.text
        assert "Site resource id 2222-2222-2222-2222 is no longer configured" in caplog.text
        no_error_or_exception(caplog)
        caplog.clear()

        sites_file = Path(f"{config_dir}/solcast-sites.json")
        sites = json.loads(sites_file.read_text(encoding="utf-8"))

        # Test no sites call on start when in a presumed dead state, then an allowed call after sixty minutes
        session_set(MOCK_BUSY)

        await set_presumed_dead(hass, entry, True)  # Set presumption of death
        coordinator, solcast = await _reload(hass, entry)
        if coordinator is None or solcast is None:
            pytest.fail("Reload failed")
        assert "Get sites failed, last call result: 999/Prior crash" in caplog.text
        assert "Connecting to https://api.solcast.com.au/rooftop_sites" not in caplog.text
        caplog.clear()
        await set_presumed_dead(hass, entry, True)  # Set presumption of death
        await set_crash_time(
            hass,
            entry,
            dt_util.now(dt_util.UTC) - timedelta(minutes=DELAYED_RESTART_ON_CRASH - DELAYED_RESTART_ON_CRASH / 2),
        )
        coordinator, solcast = await _reload(hass, entry)
        assert re.search(r"Prior crash detected.+, skipping load for \d+ minutes", caplog.text)
        assert "Integration failed to load previously" in caplog.text
        assert "Connecting to https://api.solcast.com.au/rooftop_sites" not in caplog.text
        await set_crash_time(hass, entry, dt_util.now(dt_util.UTC) - timedelta(minutes=DELAYED_RESTART_ON_CRASH + 1))
        coordinator, solcast = await _reload(hass, entry)
        assert "Prior crash detected" in caplog.text
        assert f"Prior crash was more than {DELAYED_RESTART_ON_CRASH} minutes ago" in caplog.text
        assert "Connecting to https://api.solcast.com.au/rooftop_sites" in caplog.text
        await clear_state(hass, entry)

        caplog.clear()
        _LOGGER.debug("Unlinking sites cache files")
        for f in ["solcast-sites.json", "solcast-sites-1.json", "solcast-sites-2.json"]:
            Path(f"{config_dir}/{f}").unlink(missing_ok=True)  # Remove sites cache file
        coordinator, solcast = await _reload(hass, entry)
        assert "Sites data could not be retrieved" in caplog.text
        assert "Connecting to https://api.solcast.com.au/rooftop_sites" in caplog.text
        assert "HTTP session returned status 429/Try again later" in caplog.text
        assert "At least one successful API 'get sites' call is needed" in caplog.text
        caplog.clear()

        await set_presumed_dead(hass, entry, False)  # Clear presumption of death
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
            data[SITE_INFO]["3333-3333-3333-3333"][FORECASTS] = [{"bob": 0}]
            data_file.write_text(json.dumps(data), encoding="utf-8")

        def _corrupt_with_zero_length():
            data_file.write_text("", encoding="utf-8")

        # Corrupt sites.json
        _LOGGER.debug("Testing corruption: sites.json")
        session_set(MOCK_BUSY)
        sites_file.write_text(corrupt, encoding="utf-8")
        await _reload(hass, entry)
        assert "Exception in _sites_data()" in caplog.text
        assert "JSONDecodeError: Expecting value:" in caplog.text
        sites_file.write_text(json.dumps(sites), encoding="utf-8")
        session_clear(MOCK_BUSY)
        caplog.clear()

        # Corrupt usage.json
        await clear_state(hass, entry)
        usage_corruption: list[dict[str, Any]] = [
            {DAILY_LIMIT: "10", DAILY_LIMIT_CONSUMED: 8, "reset": "2025-01-05T00:00:00+00:00"},
            {DAILY_LIMIT: 10, DAILY_LIMIT_CONSUMED: "8", "reset": "2025-01-05T00:00:00+00:00"},
            {DAILY_LIMIT: 10, DAILY_LIMIT_CONSUMED: 8, "reset": "notadate"},
        ]
        for test in usage_corruption:
            _LOGGER.debug("Testing usage corruption: %s", test)
            usage_file.write_text(json.dumps(test), encoding="utf-8")
            await _reload(hass, entry)
            assert entry.state is ConfigEntryState.SETUP_ERROR, f"Expected entry state ConfigEntryState.SETUP_ERROR, got {entry.state}"
            assert entry.state is not ConfigEntryState.LOADED, "Integration should be presumed dead after corruption"
            await clear_state(hass, entry)  # Clear presumption of death
        usage_file.write_text(corrupt, encoding="utf-8")
        await _reload(hass, entry)
        assert "corrupt, re-creating cache with zero usage" in caplog.text
        usage_file.write_text(json.dumps(usage), encoding="utf-8")
        caplog.clear()

        # Corrupt solcast.json as zero length
        _LOGGER.debug("Testing zero-length corruption: solcast.json")
        _corrupt_with_zero_length()
        await _reload(hass, entry)
        assert re.search(rf"CRITICAL.+Removing zero-length file.+{data_file}", caplog.text) is not None, (
            "Expected CRITICAL log for zero-length file removal"
        )
        issue = issue_registry.async_get_issue(DOMAIN, ISSUE_CORRUPT_FILE)
        assert issue is not None, "Issue ISSUE_CORRUPT_FILE should exist after zero-length file removal"
        assert issue.is_persistent is False, "Issue should not be persistent"
        assert f"Raise issue `{issue.issue_id}`" in caplog.text
        caplog.clear()

        # Corrupt solcast.json with a non-convertible ISO datetime string (e.g. year out of Python range)
        _LOGGER.debug("Testing non-convertible period_start: solcast.json")
        nc_data = json.loads(data_file.read_text(encoding="utf-8"))
        first_site = next(iter(nc_data[SITE_INFO]))
        nc_data[SITE_INFO][first_site][FORECASTS].insert(
            0, {PERIOD_START: "18409-09-29T02:00:00+00:00", ESTIMATE: 0.0, ESTIMATE10: 0.0, ESTIMATE90: 0.0}
        )
        data_file.write_text(json.dumps(nc_data), encoding="utf-8")
        await _reload(hass, entry)
        assert "Dropping 1 entry(s) with non-datetime period_start" in caplog.text
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"
        caplog.clear()

        # Corrupt solcast.json
        _LOGGER.debug("Testing corruption: solcast.json")
        _corrupt_data()
        await _reload(hass, entry)
        assert entry.state is not ConfigEntryState.LOADED, "Integration should be presumed dead"
        caplog.clear()

        _LOGGER.debug("Testing extreme corruption: solcast.json")
        _really_corrupt_data()
        await _reload(hass, entry)
        assert "is corrupt in load_saved_data" in caplog.text
        assert "integration not ready yet" in caplog.text
        assert entry.state is not ConfigEntryState.LOADED, "Integration should be presumed dead"

        _LOGGER.debug("Testing extreme corruption as acceptable (but unacceptable) JSON list: solcast.json")
        await clear_state(hass, entry)
        _really_corrupt_data_2()
        await _reload(hass, entry)
        assert "cache appears corrupt" in caplog.text
        assert "is corrupt in load_saved_data" in caplog.text
        assert "integration not ready yet" in caplog.text
        assert entry.state is not ConfigEntryState.LOADED, "Integration should be presumed dead"

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_forecast_update_no_sites(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that a forecast update with no sites logs the appropriate warning."""

    try:
        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        solcast: SolcastApi = patch_solcast_api(entry.runtime_data.coordinator.solcast)
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"

        entity_registry = er.async_get(hass)
        for entity_id in ("sensor.solcast_pv_forecast_first_site", "sensor.solcast_pv_forecast_second_site"):
            if entity_registry.async_get(entity_id):
                entity_registry.async_remove(entity_id)
        await hass.async_block_till_done()

        original_sites = solcast.sites
        try:
            solcast.sites = []
            solcast.options.auto_update = AutoUpdate.NONE

            await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=20, wait=False)
            await _wait_for(caplog, "Forecast has not been updated")
            assert "Forecast has not been updated: Unknown" in caplog.text
        finally:
            solcast.sites = original_sites
            await hass.async_block_till_done()

        no_error_or_exception(caplog)

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_forecast_accuracy_sensor_states(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test forecast accuracy sensor across populated, undampened-only, and empty states."""

    try:
        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        patch_solcast_api(entry.runtime_data.coordinator.solcast)
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"

        coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator

        # Populated dampened and undampened data.
        coordinator._updater.accuracy_data = {  # pyright: ignore[reportPrivateUsage]
            DAMPENED_MAPE: 5.25,
            UNDAMPENED_MAPE: 8.75,
            MODEL_PERIOD_DAYS: 14,
            INFINITY_EXCLUDED: True,
            DAMPENED_DAILY: {"2026-03-01": 4.1, "2026-03-02": 6.3},
            UNDAMPENED_DAILY: {"2026-03-01": 7.8, "2026-03-02": 9.7},
            DAMPENED_PERCENTILES: {50: 4.5, 90: 9.1},
            UNDAMPENED_PERCENTILES: {50: 7.2, 90: 14.3},
        }
        value = coordinator.get_sensor_value(ENTITY_ACCURACY)
        assert value == 5.25
        attrs = coordinator.get_sensor_extra_attributes(ENTITY_ACCURACY)
        assert attrs is not None, "Accuracy sensor attributes should not be None"
        assert attrs[UNDAMPENED_MAPE] == 8.75
        assert attrs[MODEL_PERIOD_DAYS] == 14
        assert attrs[INFINITY_EXCLUDED] is True, "Expected attribute infinity_excluded to be True"
        assert attrs[DAMPENED_APE_BREAKDOWN] == [
            {PERIOD_START: "2026-03-01", "ape": 4.1},
            {PERIOD_START: "2026-03-02", "ape": 6.3},
        ]
        assert attrs[UNDAMPENED_APE_BREAKDOWN] == [
            {PERIOD_START: "2026-03-01", "ape": 7.8},
            {PERIOD_START: "2026-03-02", "ape": 9.7},
        ]
        assert attrs["dampened_p50_ape"] == 4.5
        assert attrs["dampened_p90_ape"] == 9.1
        assert attrs["undampened_p50_ape"] == 7.2
        assert attrs["undampened_p90_ape"] == 14.3

        # Undampened-only state.
        coordinator._updater.accuracy_data = {  # pyright: ignore[reportPrivateUsage]
            DAMPENED_MAPE: None,
            UNDAMPENED_MAPE: 12.5,
            MODEL_PERIOD_DAYS: 14,
            INFINITY_EXCLUDED: False,
            DAMPENED_DAILY: {},
            UNDAMPENED_DAILY: {"2026-03-01": 11.0},
            DAMPENED_PERCENTILES: {},
            UNDAMPENED_PERCENTILES: {50: 11.0},
        }
        value = coordinator.get_sensor_value(ENTITY_ACCURACY)
        assert value is None, "Accuracy value should be None without dampened MAPE"
        attrs = coordinator.get_sensor_extra_attributes(ENTITY_ACCURACY)
        assert attrs is not None, "Accuracy sensor attributes should not be None"
        assert attrs[UNDAMPENED_MAPE] == 12.5
        assert attrs[MODEL_PERIOD_DAYS] == 14
        assert attrs[INFINITY_EXCLUDED] is False, "Expected attribute infinity_excluded to be False"
        assert attrs[UNDAMPENED_APE_BREAKDOWN] == [{PERIOD_START: "2026-03-01", "ape": 11.0}]
        assert attrs[DAMPENED_APE_BREAKDOWN] == []
        assert attrs["undampened_p50_ape"] == 11.0
        assert "dampened_p50_ape" not in attrs

        # Empty state.
        coordinator._updater.accuracy_data = {}  # pyright: ignore[reportPrivateUsage]
        value = coordinator.get_sensor_value(ENTITY_ACCURACY)
        assert value is None, "Accuracy value should be None with empty data"
        attrs = coordinator.get_sensor_extra_attributes(ENTITY_ACCURACY)
        assert attrs is not None, "Accuracy sensor attributes should not be None"
        assert attrs == {}

        no_error_or_exception(caplog)

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


@pytest.mark.parametrize(
    ("url", "port", "expected"),
    [
        # port <= 0: URL returned unchanged (trailing slash stripped)
        pytest.param(DEFAULT_SOLCAST_HTTPS_URL, 0, DEFAULT_SOLCAST_HTTPS_URL, id="port=0 no-op"),
        pytest.param("https://api.solcast.com.au/", -1, DEFAULT_SOLCAST_HTTPS_URL, id="port=-1 no-op trailing slash"),
        # Normal host with positive port
        pytest.param(DEFAULT_SOLCAST_HTTPS_URL, 8443, "https://api.solcast.com.au:8443", id="normal host port override"),
        # URL with a path component
        pytest.param("https://api.solcast.com.au/v1", 9000, "https://api.solcast.com.au:9000/v1", id="host with path"),
        # No netloc (bare path): returned as-is even with positive port
        pytest.param("/just/a/path", 8443, "/just/a/path", id="bare path no netloc"),
        # IPv6 host: urlsplit strips brackets from hostname, code re-wraps them
        pytest.param("https://[2001:db8::1]", 8443, "https://[2001:db8::1]:8443", id="IPv6 host re-wrapped"),
        # URL with username only
        pytest.param("https://user@api.solcast.com.au", 8443, "https://user@api.solcast.com.au:8443", id="username only"),
        # URL with username and password
        pytest.param("https://user:pass@api.solcast.com.au", 8443, "https://user:pass@api.solcast.com.au:8443", id="username and password"),
    ],
)
def test_get_solcast_base_url(url: str, port: int, expected: str) -> None:
    """Test get_solcast_base_url covers all branches."""
    assert SolcastApi.get_solcast_base_url(url, port) == expected


def test_get_rooftop_site_extra_data_unknown_site() -> None:
    """Return None when the requested site ID is not in the sites list."""

    api = unittest.mock.MagicMock()
    api.sites = []
    query = ForecastQuery(api)
    assert query.get_rooftop_site_extra_data("unknown-site-id") is None
