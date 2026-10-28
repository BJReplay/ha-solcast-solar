"""Post-scenarios integration tests for Solcast Solar."""

import asyncio
import copy
import datetime
from datetime import datetime as dt, timedelta
import json
import logging
from pathlib import Path
from typing import Any
import unittest.mock

from custom_components.solcast_solar.config_flow import validate_sites
from custom_components.solcast_solar.const import (
    ADVANCED_AUTOMATED_DAMPENING_GENERATION_FETCH_DELAY,
    ADVANCED_ESTIMATED_ACTUALS_FETCH_DELAY,
    ADVANCED_ESTIMATED_ACTUALS_LOG_APE_PERCENTILES,
    ADVANCED_ESTIMATED_ACTUALS_LOG_MAPE_BREAKDOWN,
    ADVANCED_SOLCAST_PORT,
    ADVANCED_SSL_VERIFY,
    API_KEY,
    CONFIG_DISCRETE_NAME,
    CONFIG_FOLDER_DISCRETE,
    DAMPENED,
    DAMPENED_MAPE,
    DAMPENED_PERCENTILES,
    DAMPENING_FACTOR,
    DOMAIN,
    EVENT_END_DATETIME,
    EVENT_START_DATETIME,
    FORECASTS,
    GET_ACTUALS,
    LAST_UPDATED,
    RESOURCE_ID,
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
    SITE_INFO,
    TASK_NEW_DAY_ACTUALS,
    TASK_NEW_DAY_GENERATION,
    UNDAMPENED_MAPE,
    UNDAMPENED_PERCENTILES,
    USE_ACTUALS,
)
from custom_components.solcast_solar.coordinator import SolcastUpdateCoordinator
from custom_components.solcast_solar.solcastapi import SolcastApi
import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.exceptions import ServiceValidationError

from . import (
    DEFAULT_INPUT1,
    DEFAULT_INPUT2,
    MOCK_ALTER_HISTORY,
    async_cleanup_integration_tests,
    async_init_integration,
    get_advanced_options_file,
    no_error_or_exception,
    session_clear,
    session_set,
    simulated,
)
from .test_integration import _exec_update_actuals, _wait_for_update, patch_solcast_api

_LOGGER = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def frozen_time() -> None:
    """Disable the global freezer fixture for this module."""


async def test_validate_sites_does_not_mutate_caches_before_reload(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Validation should not mutate caches before runtime migration executes."""

    try:
        config_dir = f"{hass.config.config_dir}/{CONFIG_DISCRETE_NAME}" if CONFIG_FOLDER_DISCRETE else hass.config.config_dir
        if CONFIG_FOLDER_DISCRETE:
            Path(config_dir).mkdir(parents=False, exist_ok=True)

        entry = await async_init_integration(hass, copy.deepcopy(DEFAULT_INPUT2))
        assert entry.state is ConfigEntryState.LOADED

        old_sites_key1 = Path(f"{config_dir}/solcast-sites-1.json")
        new_sites_key11 = Path(f"{config_dir}/solcast-sites-11.json")
        assert old_sites_key1.is_file()

        proposed = {**entry.options}
        proposed[CONF_API_KEY] = "1a,11,2"
        status, message = await validate_sites(hass, proposed)
        assert status == 200, message

        # Validation must not delete old key caches or create new key caches.
        assert old_sites_key1.is_file()
        assert not new_sites_key11.exists()

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_site_transfer_migrates_history_and_backs_up(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test transferring a site to a new API key with a different site ID keeps history."""

    try:
        config_dir = f"{hass.config.config_dir}/{CONFIG_DISCRETE_NAME}" if CONFIG_FOLDER_DISCRETE else hass.config.config_dir
        if CONFIG_FOLDER_DISCRETE:
            Path(config_dir).mkdir(parents=False, exist_ok=True)

        entry = await async_init_integration(hass, copy.deepcopy(DEFAULT_INPUT1))
        assert entry.state is ConfigEntryState.LOADED

        old_site_id = "2222-2222-2222-2222"
        new_site_id = "7777-7777-7777-7777"

        dampening_file = Path(f"{config_dir}/solcast-dampening.json")
        dampening_file.write_text(json.dumps({old_site_id: [0.9] * 24}), encoding="utf-8")

        cache_files = [
            Path(f"{config_dir}/solcast.json"),
            Path(f"{config_dir}/solcast-undampened.json"),
            Path(f"{config_dir}/solcast-actuals.json"),
            Path(f"{config_dir}/solcast-actuals-dampened.json"),
        ]
        cache_files = [cache_file for cache_file in cache_files if cache_file.is_file()]

        old_history_counts: dict[str, int] = {}
        for cache_file in cache_files:
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            old_history_counts[cache_file.name] = len(payload[SITE_INFO][old_site_id][FORECASTS])

        caplog.clear()
        hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_API_KEY: "11"})
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.LOADED
        assert "Site transfer detected for API key ******11" in caplog.text
        assert "Applying cached history transfer for moved site IDs: 2222-2222-2222-2222->7777-7777-7777-7777" in caplog.text
        assert "New site(s) have been added" not in caplog.text

        backup_day = dt.now(datetime.UTC).strftime("%y%m%d")
        for cache_file in cache_files:
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            assert old_site_id not in payload[SITE_INFO]
            assert new_site_id in payload[SITE_INFO]
            assert len(payload[SITE_INFO][new_site_id][FORECASTS]) >= old_history_counts[cache_file.name]

            backup_file = cache_file.with_name(f"{cache_file.stem}-{backup_day}{cache_file.suffix}.bak")
            assert backup_file.is_file(), f"Expected backup file {backup_file}"

        dampening = json.loads(dampening_file.read_text(encoding="utf-8"))
        assert old_site_id not in dampening
        assert new_site_id in dampening

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


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
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"
        no_error_or_exception(caplog)
        assert Path(f"{config_dir}/solcast-actuals.json").is_file(), f"File {Path(f'{config_dir}/solcast-actuals.json')} should exist"
        caplog.clear()

        # Kill the cache, then re-create with a forced update
        _LOGGER.debug("Testing force update actuals")
        Path(f"{config_dir}/solcast-dampening.json").unlink(missing_ok=True)
        await _exec_update_actuals(hass, coordinator, solcast, caplog, SERVICE_FORCE_UPDATE_ESTIMATES, wait=True)
        assert Path(f"{config_dir}/solcast-actuals.json").is_file(), f"File {Path(f'{config_dir}/solcast-actuals.json')} should exist"
        assert "Estimated actuals dictionary for site 1111-1111-1111-1111" in caplog.text
        assert "Estimated actuals dictionary for site 2222-2222-2222-2222" in caplog.text
        assert "Auto-dampening suppressed" not in caplog.text
        assert "Task model_automated_dampening took" not in caplog.text
        assert "Apply dampening to previous day estimated actuals" not in caplog.text

        queries: list[dict[str, Any]] = [
            {
                "query": {
                    EVENT_START_DATETIME: solcast.dt_helper.day_start_utc(future=-1).isoformat(),
                    EVENT_END_DATETIME: solcast.dt_helper.day_start_utc().isoformat(),
                },
                "expect": 48,
            },
            {
                "query": {},
                "expect": 48,
            },
            {
                "query": {
                    SITE: solcast.sites[0][RESOURCE_ID],
                },
                "expect": 48,
            },
        ]
        for query in queries:
            _LOGGER.debug("Testing query estimated data: %s", query["query"])
            estimate_data = await hass.services.async_call(
                DOMAIN,
                SERVICE_QUERY_ESTIMATE_DATA,
                query["query"],
                blocking=True,
                return_response=True,
            )
            assert len(estimate_data.get("data", [])) == query["expect"]  # type: ignore[arg-type, union-attr]

        dampened_estimate_data = await hass.services.async_call(
            DOMAIN,
            SERVICE_QUERY_ESTIMATE_DATA,
            {
                DAMPENED: True,
            },
            blocking=True,
            return_response=True,
        )
        assert dampened_estimate_data is not None
        dampened_estimates = dampened_estimate_data.get("data", [])
        assert isinstance(dampened_estimates, tuple | list)
        dampened_estimate_intervals = [interval for interval in dampened_estimates if isinstance(interval, dict)]
        assert dampened_estimate_intervals
        assert all(DAMPENING_FACTOR in interval for interval in dampened_estimate_intervals)

        dampened_site_estimate_data = await hass.services.async_call(
            DOMAIN,
            SERVICE_QUERY_ESTIMATE_DATA,
            {
                SITE: solcast.sites[0][RESOURCE_ID],
                DAMPENED: True,
            },
            blocking=True,
            return_response=True,
        )
        assert dampened_site_estimate_data is not None
        dampened_site_estimates = dampened_site_estimate_data.get("data", [])
        assert isinstance(dampened_site_estimates, tuple | list)
        dampened_site_estimate_intervals = [interval for interval in dampened_site_estimates if isinstance(interval, dict)]
        assert dampened_site_estimate_intervals
        assert all(DAMPENING_FACTOR not in interval for interval in dampened_site_estimate_intervals)

        _LOGGER.debug("Testing invalid estimated actual query range")
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN,
                SERVICE_QUERY_ESTIMATE_DATA,
                {
                    EVENT_START_DATETIME: solcast.dt_helper.day_start_utc(future=-50).isoformat(),
                    EVENT_END_DATETIME: solcast.dt_helper.day_start_utc(future=-40).isoformat(),
                },
                blocking=True,
                return_response=True,
            )

        _LOGGER.debug("Testing invalid dampened estimated actual query range")
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN,
                SERVICE_QUERY_ESTIMATE_DATA,
                {
                    EVENT_START_DATETIME: solcast.dt_helper.day_start_utc(future=-50).isoformat(),
                    EVENT_END_DATETIME: solcast.dt_helper.day_start_utc(future=-40).isoformat(),
                    DAMPENED: True,
                },
                blocking=True,
                return_response=True,
            )

        _LOGGER.debug("Testing invalid estimated actual query site")
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN,
                SERVICE_QUERY_ESTIMATE_DATA,
                {SITE: "not-a-real-site"},
                blocking=True,
                return_response=True,
            )

        _LOGGER.debug("Testing switch between using and not using estimated actuals")
        caplog.clear()
        opt = {**entry.options}
        opt[USE_ACTUALS] = 0
        hass.config_entries.async_update_entry(entry, options=opt)
        await hass.async_block_till_done()
        assert "Recalculate forecasts and refresh sensors" in caplog.text
        energy_dashboard = solcast.query.get_energy_data()
        if energy_dashboard is None:
            pytest.fail("Energy dashboard data is None")
        else:
            assert energy_dashboard["wh_hours"].get((solcast.dt_helper.day_start_utc() - timedelta(hours=8)).isoformat()) == 936.0

        session_set(MOCK_ALTER_HISTORY)
        await _exec_update_actuals(hass, coordinator, solcast, caplog, SERVICE_FORCE_UPDATE_ESTIMATES)
        caplog.clear()
        opt = {**entry.options}
        opt[USE_ACTUALS] = 1
        hass.config_entries.async_update_entry(entry, options=opt)
        await hass.async_block_till_done()
        assert "Recalculate forecasts and refresh sensors" in caplog.text
        energy_dashboard = solcast.query.get_energy_data()
        session_clear(MOCK_ALTER_HISTORY)
        if energy_dashboard is None:
            pytest.fail("Energy dashboard data is None")
        else:
            assert energy_dashboard["wh_hours"].get((solcast.dt_helper.day_start_utc() - timedelta(hours=8)).isoformat()) == 374.0

        _LOGGER.debug("Testing get actuals abort if already in progress")
        caplog.clear()
        await _exec_update_actuals(hass, coordinator, solcast, caplog, SERVICE_FORCE_UPDATE_ESTIMATES, wait=False)
        await _exec_update_actuals(hass, coordinator, solcast, caplog, SERVICE_FORCE_UPDATE_ESTIMATES, wait=False)
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
        result = await hass.services.async_call(DOMAIN, SERVICE_DIAGNOSTIC, {}, blocking=True, return_response=True)
        data = result["data"]  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["actuals_health"]["status"] == "disabled"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        with pytest.raises(ServiceValidationError):
            await _exec_update_actuals(hass, coordinator, solcast, caplog, SERVICE_FORCE_UPDATE_ESTIMATES)
        assert "Estimated actuals not enabled" in caplog.text

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


@pytest.mark.asyncio
async def test_updater_scheduler_catch_up_and_duplicate_guards(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Cover catch-up scheduling and duplicate-task guards in one setup."""

    try:
        entry = await async_init_integration(hass, copy.deepcopy(DEFAULT_INPUT1))
        coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator
        solcast: SolcastApi = patch_solcast_api(coordinator.solcast)

        solcast.data_actuals[LAST_UPDATED] = dt.now(datetime.UTC) - timedelta(days=1)
        solcast.advanced_options[ADVANCED_ESTIMATED_ACTUALS_FETCH_DELAY] = 0
        solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_GENERATION_FETCH_DELAY] = 0

        now_local = dt.now(solcast.options.tz).replace(minute=1, second=0, microsecond=0)
        with (
            unittest.mock.patch("custom_components.solcast_solar.updater.dt") as dt_mock,
            unittest.mock.patch("custom_components.solcast_solar.updater.randint", return_value=5),
            unittest.mock.patch(
                "custom_components.solcast_solar.updater.async_track_point_in_utc_time",
                return_value=unittest.mock.Mock(),
            ) as mock_track_point,
        ):
            dt_mock.now.return_value = now_local
            generation_scheduled = await coordinator.updater.check_generation_fetch()
            estimated_actuals_scheduled = await coordinator.updater.check_estimated_actuals_fetch()

        assert generation_scheduled
        assert estimated_actuals_scheduled
        assert TASK_NEW_DAY_GENERATION in coordinator.tasks
        assert TASK_NEW_DAY_ACTUALS in coordinator.tasks
        assert mock_track_point.call_count == 2
        assert "Generation update window was missed, scheduling at" in caplog.text
        assert "Estimated actuals update window was missed, scheduling at" in caplog.text

        coordinator.tasks[TASK_NEW_DAY_GENERATION] = unittest.mock.Mock()
        assert await coordinator.updater.check_generation_fetch()

        coordinator.tasks[TASK_NEW_DAY_ACTUALS] = unittest.mock.Mock()
        assert await coordinator.updater.check_estimated_actuals_fetch()

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


@pytest.mark.asyncio
async def test_updater_estimated_actuals_skip_paths_and_undampened_accuracy(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Cover estimated-actuals skip branches and undampened-only accuracy path."""

    try:
        entry = await async_init_integration(hass, copy.deepcopy(DEFAULT_INPUT1))
        coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator
        solcast: SolcastApi = patch_solcast_api(coordinator.solcast)

        solcast.advanced_options[ADVANCED_ESTIMATED_ACTUALS_FETCH_DELAY] = 0
        solcast.data_actuals[LAST_UPDATED] = dt.now(datetime.UTC)
        now_local = dt.now(solcast.options.tz).replace(minute=0, second=0, microsecond=0)

        with unittest.mock.patch("custom_components.solcast_solar.updater.dt") as dt_mock:
            dt_mock.now.return_value = now_local
            scheduled = await coordinator.updater.check_estimated_actuals_fetch()

        assert not scheduled
        assert TASK_NEW_DAY_ACTUALS not in coordinator.tasks

        solcast.data_actuals[LAST_UPDATED] = dt.now(datetime.UTC) - timedelta(days=1)
        caplog.clear()
        with (
            unittest.mock.patch("custom_components.solcast_solar.updater.dt") as dt_mock,
            unittest.mock.patch.object(
                SolcastApi,
                "estimated_actuals_updated_today",
                new_callable=unittest.mock.PropertyMock,
                side_effect=[False, True],
            ),
            unittest.mock.patch.object(
                coordinator.updater,
                "update_estimated_actuals_history",
                new=unittest.mock.AsyncMock(return_value=None),
            ),
            unittest.mock.patch(
                "custom_components.solcast_solar.updater.async_track_point_in_utc_time",
                return_value=unittest.mock.Mock(),
            ),
        ):
            dt_mock.now.return_value = now_local
            scheduled = await coordinator.updater.check_estimated_actuals_fetch()

        assert scheduled
        assert TASK_NEW_DAY_ACTUALS in coordinator.tasks
        coordinator.tasks.pop(TASK_NEW_DAY_ACTUALS, None)

        solcast.options.auto_dampen = False
        solcast.advanced_options[ADVANCED_ESTIMATED_ACTUALS_LOG_MAPE_BREAKDOWN] = True
        solcast.advanced_options[ADVANCED_ESTIMATED_ACTUALS_LOG_APE_PERCENTILES] = [50, 90]

        earliest = solcast.dt_helper.day_start_utc() - timedelta(days=2)
        solcast.dampening.get_earliest_estimate_after_undampened = unittest.mock.Mock(return_value=earliest)
        solcast.dampening.prepare_generation_data = unittest.mock.AsyncMock(return_value=({}, {}))
        solcast.query.get_estimate_list = unittest.mock.AsyncMock(return_value=[])
        solcast.dampening.calculate_error = unittest.mock.AsyncMock(return_value=(False, 12.34, [10.0, 20.0], {"2026-05-01": 12.34}))

        await coordinator.updater.calculate_accuracy_metrics()

        assert solcast.query.get_estimate_list.await_count == 1
        assert solcast.dampening.calculate_error.await_count == 1
        assert coordinator.updater.accuracy_data[DAMPENED_MAPE] is None
        assert coordinator.updater.accuracy_data[UNDAMPENED_MAPE] == 12.34
        assert coordinator.updater.accuracy_data[DAMPENED_PERCENTILES] == {}
        assert coordinator.updater.accuracy_data[UNDAMPENED_PERCENTILES] == {50: 10.0, 90: 20.0}
        no_error_or_exception(caplog)
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


@pytest.mark.asyncio
async def test_advanced_solcast_port_applied_runtime(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Apply an advanced Solcast port override without reloading the integration."""

    try:
        entry = await async_init_integration(hass, copy.deepcopy(DEFAULT_INPUT1))
        coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator
        solcast: SolcastApi = coordinator.solcast

        assert solcast.advanced_options[ADVANCED_SOLCAST_PORT] == 0

        advanced_file = get_advanced_options_file(hass.config.config_dir, create=True)
        caplog.clear()
        advanced_file.write_text(json.dumps({ADVANCED_SOLCAST_PORT: 8443}), encoding="utf-8")
        async with asyncio.timeout(10):
            while solcast.advanced_options[ADVANCED_SOLCAST_PORT] != 8443:
                await hass.async_block_till_done()
                await asyncio.sleep(0.01)

        assert solcast.advanced_options[ADVANCED_SOLCAST_PORT] == 8443

        caplog.clear()
        assert solcast.sites
        site_id = solcast.sites[0][RESOURCE_ID]
        api_key = solcast.sites[0][API_KEY]
        payload = simulated.raw_get_site_forecasts(site_id, api_key, 320)
        response = unittest.mock.MagicMock(status=200, url=f"https://api.solcast.com.au:8443/rooftop_sites/{site_id}/forecasts")
        response.text = unittest.mock.AsyncMock(return_value=json.dumps(payload))
        original_session = solcast.aiohttp_session
        mock_session = unittest.mock.MagicMock()
        mock_session.get = unittest.mock.AsyncMock(return_value=response)
        solcast.aiohttp_session = mock_session
        try:
            await solcast.fetcher.fetch_data(hours=320, path=FORECASTS, site=site_id, api_key=api_key, force=True)
        finally:
            solcast.aiohttp_session = original_session

        mock_session.get.assert_awaited_once()
        assert mock_session.get.await_args.kwargs["url"].startswith("https://api.solcast.com.au:8443/rooftop_sites/")

        no_error_or_exception(caplog)
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_service_supports_response(
    recorder_mock: Recorder,
    hass: HomeAssistant,
) -> None:
    """Test that response-returning service actions are registered with SupportsResponse.ONLY."""

    try:
        await async_init_integration(hass, DEFAULT_INPUT1)

        response_actions = {
            SERVICE_DIAGNOSTIC,
            SERVICE_GET_DAMPENING,
            SERVICE_GET_OPTIONS,
            SERVICE_QUERY_ESTIMATE_DATA,
            SERVICE_QUERY_FORECAST_DATA,
        }
        non_response_actions = {
            SERVICE_CLEAR_DATA,
            SERVICE_FORCE_UPDATE_ESTIMATES,
            SERVICE_FORCE_UPDATE_FORECASTS,
            SERVICE_REMOVE_HARD_LIMIT,
            SERVICE_SET_CUSTOM_HOURS,
            SERVICE_SET_DAMPENING,
            SERVICE_SET_HARD_LIMIT,
            SERVICE_SET_OPTIONS,
            SERVICE_UPDATE,
        }

        registered = hass.services.async_services_for_domain(DOMAIN)

        for action_name in response_actions:
            assert action_name in registered, f"Action '{action_name}' not registered"
            assert registered[action_name].supports_response is SupportsResponse.ONLY, (
                f"Action '{action_name}' should have SupportsResponse.ONLY, got {registered[action_name].supports_response}"
            )

        for action_name in non_response_actions:
            assert action_name in registered, f"Action '{action_name}' not registered"
            assert registered[action_name].supports_response is not SupportsResponse.ONLY, (
                f"Action '{action_name}' should not have SupportsResponse.ONLY, got {registered[action_name].supports_response}"
            )

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


@pytest.mark.parametrize("ssl_verify", [True, False])
async def test_fetch_data_respects_advanced_ssl_verify(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    ssl_verify: bool,
) -> None:
    """Test fetch_data passes ssl_verify to aiohttp."""

    try:
        entry = await async_init_integration(hass, copy.deepcopy(DEFAULT_INPUT1))
        coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator
        solcast: SolcastApi = coordinator.solcast

        assert solcast.sites
        site_id = solcast.sites[0][RESOURCE_ID]
        api_key = solcast.sites[0][API_KEY]
        solcast.advanced_options[ADVANCED_SSL_VERIFY] = ssl_verify

        payload = simulated.raw_get_site_forecasts(site_id, api_key, 320)
        response = unittest.mock.MagicMock(status=200, url=f"https://api.solcast.com.au/rooftop_sites/{site_id}/forecasts")
        response.text = unittest.mock.AsyncMock(return_value=json.dumps(payload))

        original_session = solcast.aiohttp_session
        mock_session = unittest.mock.MagicMock()
        mock_session.get = unittest.mock.AsyncMock(return_value=response)
        solcast.aiohttp_session = mock_session
        try:
            await solcast.fetcher.fetch_data(hours=320, path=FORECASTS, site=site_id, api_key=api_key, force=True)
        finally:
            solcast.aiohttp_session = original_session

        mock_session.get.assert_awaited_once()
        assert mock_session.get.await_args.kwargs["ssl"] is ssl_verify
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


@pytest.mark.parametrize("ssl_verify", [True, False])
async def test_sites_cache_respects_advanced_ssl_verify(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    ssl_verify: bool,
) -> None:
    """Test sites discovery passes ssl_verify to aiohttp."""

    try:
        entry = await async_init_integration(hass, copy.deepcopy(DEFAULT_INPUT1))
        coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator
        solcast: SolcastApi = coordinator.solcast

        solcast.advanced_options[ADVANCED_SSL_VERIFY] = ssl_verify

        api_key = str(entry.options[CONF_API_KEY]).split(",")[0].strip()
        payload = simulated.raw_get_sites(api_key)
        assert payload is not None

        response = unittest.mock.MagicMock(status=200)
        response.text = unittest.mock.AsyncMock(return_value=json.dumps(payload))

        original_session = solcast.aiohttp_session
        mock_session = unittest.mock.MagicMock()
        mock_session.get = unittest.mock.AsyncMock(return_value=response)
        solcast.aiohttp_session = mock_session
        try:
            status, _, _ = await solcast.sites_cache.get_sites_and_usage(prior_crash=False, use_cache=False)
        finally:
            solcast.aiohttp_session = original_session

        assert status == 200
        mock_session.get.assert_awaited_once()
        assert mock_session.get.await_args.kwargs["ssl"] is ssl_verify
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_config_folder_migration(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test migration of config to a discrete folder."""

    try:
        Path(f"{hass.config.config_dir}/solcast-test.json").write_text(
            json.dumps({LAST_UPDATED: dt.now(datetime.UTC).isoformat(), SITE_INFO: {}}), encoding="utf-8"
        )
        options = copy.deepcopy(DEFAULT_INPUT1)
        entry = await async_init_integration(hass, options)
        config_file_old = Path(f"{hass.config.config_dir}/solcast-test.json")
        config_file_new = Path(f"{hass.config.config_dir}/{CONFIG_DISCRETE_NAME}/solcast-test.json")
        assert not config_file_old.is_file(), f"File {config_file_old} should not exist"
        assert config_file_new.is_file(), f"File {config_file_new} should exist"
        assert entry.state is ConfigEntryState.LOADED, f"Expected entry state ConfigEntryState.LOADED, got {entry.state}"
        assert f"Migrating config directory file {config_file_old} to {config_file_new}" in caplog.text
        no_error_or_exception(caplog)
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"
