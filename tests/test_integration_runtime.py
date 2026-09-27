"""Tests for Solcast Solar runtime retries and dampening flow."""

import datetime
from datetime import datetime as dt, timedelta
import json
import logging
import os
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar.const import (
    ADVANCED_ENTITY_LOGGING,
    ADVANCED_GRANULAR_DAMPENING_DELTA_ADJUSTMENT,
    API_KEY,
    CONFIG_DISCRETE_NAME,
    CONFIG_FOLDER_DISCRETE,
    DOMAIN,
    ESTIMATE,
    FORECASTS,
    GET_ACTUALS,
    PERIOD_START,
    SERVICE_CLEAR_DATA,
    SERVICE_FORCE_UPDATE_ESTIMATES,
    SITE_INFO,
)
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.dates import DateTimeEncoder, JSONDecoder
from homeassistant.components.solcast_solar.enums import AutoUpdate
from homeassistant.components.solcast_solar.solcastapi import SolcastApi
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from . import (
    DEFAULT_INPUT1,
    DEFAULT_INPUT2,
    MOCK_BUSY,
    MOCK_OVER_LIMIT,
    ZONE_RAW,
    async_cleanup_integration_tests,
    async_init_integration,
    get_config_dir,
    no_error_or_exception,
    session_clear,
    session_reset_usage,
    session_set,
    verify_data_schema,
    write_advanced_options,
)
from .test_integration import (
    _exec_update,
    _exec_update_actuals,
    _reload,
    _wait_for,
    five_minute_bump,
    patch_solcast_api,
)

_LOGGER = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def frozen_time() -> None:
    """Disable the global freezer fixture for runtime timing tests."""


@pytest.mark.parametrize(
    "options",
    [
        DEFAULT_INPUT1,
        DEFAULT_INPUT2,
    ],
)
async def test_integration_runtime_and_dampening_flow(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    options: dict[str, Any],
) -> None:
    """Test runtime retries, dampening file handling and cache reset behaviors."""

    default_advanced_options = {ADVANCED_ENTITY_LOGGING: True}

    try:
        config_dir = str(get_config_dir(hass.config.config_dir, create=True))
        write_advanced_options(config_dir, default_advanced_options)

        entry: ConfigEntry = await async_init_integration(hass, options | ({GET_ACTUALS: True} if options == DEFAULT_INPUT1 else {}))
        assert entry.state is ConfigEntryState.LOADED, f"Expected entry state ConfigEntryState.LOADED, got {entry.state}"

        er.async_get(hass).async_update_entity("sensor.solcast_pv_forecast_dampening", disabled_by=None)
        await hass.async_block_till_done()

        coordinator: SolcastUpdateCoordinator | None
        if (coordinator := entry.runtime_data.coordinator) is None:
            pytest.fail("No coordinator")
        solcast: SolcastApi | None = patch_solcast_api(coordinator.solcast)
        granular_dampening_file = Path(f"{config_dir}/solcast-dampening.json")

        coordinator, solcast = await _reload(hass, entry)
        if coordinator is None or solcast is None:
            pytest.fail("No coordinator or solcast")

        coordinator._updater.set_next_update()

        # Test API too busy encountered for first site
        caplog.clear()
        session_set(MOCK_BUSY)
        solcast.options.auto_update = AutoUpdate.NONE
        await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=20)
        assert "seconds before retry" in caplog.text
        await _wait_for(caplog, "Forecast has not been updated")
        session_clear(MOCK_BUSY)

        # Simulate exceed API limit and beyond
        caplog.clear()
        _LOGGER.info("Simulating API limit exceeded")
        session_set(MOCK_OVER_LIMIT)
        await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=20)
        await _wait_for(caplog, "Forecast has not been updated")
        assert "API allowed polling limit has been exceeded" in caplog.text
        caplog.clear()
        no_error_or_exception(caplog)
        await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=20)
        assert "API polling limit exhausted, not getting forecast" in caplog.text
        caplog.clear()
        no_error_or_exception(caplog)
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
        if (
            options == DEFAULT_INPUT1
            and dt_util.now(solcast.options.tz) < dt(2026, 6, 1, tzinfo=solcast.options.tz)
            and CONFIG_FOLDER_DISCRETE
        ):
            legacy_dampening_file = Path(f"{config_dir.replace(f'/{CONFIG_DISCRETE_NAME}', '')}/{granular_dampening_file.name}")
            legacy_dampening_file.write_text(json.dumps(granular_dampening), encoding="utf-8")
            _LOGGER.debug("Write legacy dampening file %s for auto-move test", legacy_dampening_file)
        else:
            granular_dampening_file.write_text(json.dumps(granular_dampening), encoding="utf-8")
            _LOGGER.debug("Write dampening file %s for test", granular_dampening_file)
        await _wait_for(caplog, "Running task watch_dampening")
        assert granular_dampening_file.is_file(), f"File {granular_dampening_file} should exist"
        if CONFIG_FOLDER_DISCRETE:
            if options == DEFAULT_INPUT1 and dt_util.now(solcast.options.tz) < dt(2026, 6, 1, tzinfo=solcast.options.tz):
                assert "auto-moving will cease 1st June 2026" in caplog.text
            else:
                assert "auto-moving will cease 1st June 2026" not in caplog.text

        # Test update beyond ten seconds of prior update, also with stale usage cache and dodgy dampening file
        session_reset_usage()
        for api_key in options[API_KEY].split(","):
            solcast.sites_cache._api_used_reset[api_key] = dt_util.now(datetime.UTC) - timedelta(days=5)
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
        no_error_or_exception(caplog)

        caplog.clear()

        if options == DEFAULT_INPUT1:
            sensor = hass.states.get("sensor.solcast_pv_forecast_forecast_tomorrow")
            if sensor is not None:
                assert sensor.state == "35.6374"
            else:
                pytest.fail("Test undampened: State of forecast_tomorrow is None")

            write_advanced_options(config_dir, default_advanced_options | {ADVANCED_GRANULAR_DAMPENING_DELTA_ADJUSTMENT: True})
            await _wait_for(caplog, "Advanced option set granular_dampening_delta_adjustment: True")

            await _exec_update_actuals(hass, coordinator, solcast, caplog, SERVICE_FORCE_UPDATE_ESTIMATES, wait=True)
            assert "Automated dampening is not enabled" in caplog.text

            scenario: list[dict[str, Any]] = [
                {"factors": {"1111-1111-1111-1111": [0.7] * 48, "2222-2222-2222-2222": [0.8] * 48}, "result": "31.3821"},
                {"factors": {"1111-1111-1111-1111": [0.85] * 48, "2222-2222-2222-2222": [0.85] * 48}, "result": "36.1691"},
                {"factors": {"all": [0.55] * 48}, "result": "24.3749"},
            ]
            first = True
            for test in scenario:
                if first:
                    first = False
                    actuals = json.loads(Path(f"{config_dir}/solcast-actuals.json").read_text(encoding="utf-8"), cls=JSONDecoder)
                    for site in actuals[SITE_INFO].values():
                        for forecast in site[FORECASTS]:
                            if (
                                forecast[PERIOD_START].astimezone(ZoneInfo(ZONE_RAW)).hour > 10
                                and forecast[PERIOD_START].astimezone(ZoneInfo(ZONE_RAW)).hour < 14
                            ):
                                forecast[ESTIMATE] *= 1.11
                    Path(f"{config_dir}/solcast-actuals.json").write_text(json.dumps(actuals, cls=DateTimeEncoder), encoding="utf-8")

                    caplog.clear()
                    coordinator, solcast = await _reload(hass, entry)
                    if coordinator is None or solcast is None:
                        pytest.fail("Reload failed")
                    await _wait_for(caplog, "Running task watch_advanced")
                    caplog.clear()
                    await solcast.dampening.model_automated()
                granular_dampening_file.write_text(json.dumps(test["factors"]), encoding="utf-8")
                await _wait_for(caplog, "Updating sensor Forecast Tomorrow")
                assert "Granular dampening mtime changed" in caplog.text
                assert "Granular dampening loaded" in caplog.text
                sensor = hass.states.get("sensor.solcast_pv_forecast_forecast_tomorrow")
                if sensor is not None:
                    assert sensor.state == test["result"], (
                        f"peak_intervals[24]={solcast.peak_intervals.get(24)}, "
                        f"DELTA_ADJUSTMENT={solcast.advanced_options.get('granular_dampening_delta_adjustment')}, "
                        f"get_actuals={solcast.options.get_actuals}"
                    )
                else:
                    pytest.fail("Test dampened: State of forecast_tomorrow is None")
                caplog.clear()

        if options == DEFAULT_INPUT1:
            write_advanced_options(config_dir, default_advanced_options)
            await _wait_for(caplog, "Advanced option set entity_logging: True")

            granular_dampening_file.unlink()
            await _wait_for(caplog, "Granular dampening file deleted, no longer monitoring")

        solcast.options.auto_update = AutoUpdate.NONE

        verify_data_schema(solcast.data)
        verify_data_schema(solcast.data_undampened)
        verify_data_schema(solcast.data_actuals)
        verify_data_schema(solcast.data_actuals_dampened)

        caplog.clear()

        def set_file_last_modified(file_path: str, dtm: dt) -> None:
            dt_epoch = dtm.timestamp()
            os.utime(file_path, (dt_epoch, dt_epoch))

        granular_dampening_file.write_text("really dodgy", encoding="utf-8")
        set_file_last_modified(str(granular_dampening_file), dt_util.now(datetime.UTC) - timedelta(minutes=5))
        await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=20)
        assert "JSONDecodeError, dampening ignored" in caplog.text
        granular_dampening_file.unlink()
        caplog.clear()

        for api_key in options[API_KEY].split(","):
            solcast.sites_cache._api_used_reset[api_key] = solcast.sites_cache._api_used_reset[api_key] - timedelta(hours=24)  # type: ignore[assignment, operator]
        await solcast.sites_cache.reset_api_usage()
        assert "Reset API usage" in caplog.text
        await solcast.sites_cache.reset_api_usage()
        assert "Usage cache is fresh, so not resetting" in caplog.text

        if options == DEFAULT_INPUT2:
            Path(f"{config_dir}/solcast.json").unlink()
            Path(f"{config_dir}/solcast-undampened.json").unlink()
            await hass.services.async_call(DOMAIN, SERVICE_CLEAR_DATA, {}, blocking=True)
            await hass.async_block_till_done()
            assert "There is no solcast-undampened.json to delete" in caplog.text
            assert "There is no solcast.json to delete" in caplog.text
            assert "There is no solcast.json to load" in caplog.text
            assert "Polling API for site 1111-1111-1111-1111" in caplog.text
            assert "Polling API for site 2222-2222-2222-2222" in caplog.text
            assert "Polling API for site 3333-3333-3333-3333" in caplog.text

        assert await hass.config_entries.async_unload(entry.entry_id), "Config entry unload failed"
        await hass.async_block_till_done()

        session_reset_usage()

    finally:
        assert await async_cleanup_integration_tests(
            hass,
            solcast_dampening=options != DEFAULT_INPUT1,
            solcast_sites=options != DEFAULT_INPUT1,
        ), "Integration test cleanup failed"
