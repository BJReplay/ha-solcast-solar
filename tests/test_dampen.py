"""Tests for the Solcast Solar automated dampening."""

import asyncio
from collections import OrderedDict
import copy
import datetime
from datetime import datetime as dt, timedelta
import json
import logging
import math
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.solcast_solar.config_flow import (
    SolcastSolarOptionFlowHandler,
)
from homeassistant.components.solcast_solar.const import (
    ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL,
    ADVANCED_AUTOMATED_DAMPENING_ELEVATION_ADJUSTMENT,
    ADVANCED_AUTOMATED_DAMPENING_GENERATION_FETCH_DELAY,
    ADVANCED_AUTOMATED_DAMPENING_IGNORE_INTERVALS,
    ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR,
    ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR_ADJUSTED,
    ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_GENERATION,
    ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_INTERVALS,
    ADVANCED_AUTOMATED_DAMPENING_MODEL,
    ADVANCED_AUTOMATED_DAMPENING_NO_LIMITING_CONSISTENCY,
    ADVANCED_AUTOMATED_DAMPENING_PRESERVE_UNMATCHED_FACTORS,
    ADVANCED_ESTIMATED_ACTUALS_FETCH_DELAY,
    ADVANCED_ESTIMATED_ACTUALS_LOG_MAPE_BREAKDOWN,
    ADVANCED_HISTORY_MAX_DAYS,
    AUTO_DAMPEN,
    AUTO_UPDATE,
    DAMP_FACTOR,
    DOMAIN,
    ENTITY_ACCURACY,
    ESTIMATE,
    EXCEPTION_GENERATION_MIXED_TYPES,
    EXCLUDE_SITES,
    FORECASTS,
    GENERATION_ENTITIES,
    GET_ACTUALS,
    INTEGRATION,
    PERIOD_START,
    PRESUMED_DEAD,
    RESOURCE_ID,
    SERVICE_FORCE_UPDATE_ESTIMATES,
    SERVICE_SET_DAMPENING,
    SITE_ATTRIBUTE_AZIMUTH,
    SITE_ATTRIBUTE_TILT,
    SITE_EXPORT_ENTITY,
    SITE_EXPORT_LIMIT,
    SITE_INFO,
    USE_ACTUALS,
)
from homeassistant.components.solcast_solar.dampen import Dampening
from homeassistant.components.solcast_solar.util import (
    DateTimeEncoder,
    DateTimeHelper,
    JSONDecoder,
    SolcastApiStatus,
    compute_energy_intervals,
    compute_power_intervals,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import RegistryEntryDisabler

from . import (
    DEFAULT_INPUT2,
    MOCK_CORRUPT_ACTUALS,
    ZONE_RAW,
    ExtraSensors,
    async_cleanup_integration_tests,
    async_init_integration,
    exec_update_actuals,
    get_config_dir,
    no_exception,
    reload_integration,
    session_clear,
    session_set,
    wait_for_it,
    write_advanced_options,
)

from tests.common import MockConfigEntry

ZONE = ZoneInfo(ZONE_RAW)
NOW = dt.now(ZONE)

_LOGGER = logging.getLogger(__name__)


async def test_auto_dampen(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test automated dampening."""

    assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"

    try:
        config_dir = get_config_dir(hass.config.config_dir, create=True)

        write_advanced_options(
            config_dir,
            {
                ADVANCED_AUTOMATED_DAMPENING_ELEVATION_ADJUSTMENT: False,
                ADVANCED_AUTOMATED_DAMPENING_IGNORE_INTERVALS: ["17:00"],
                ADVANCED_AUTOMATED_DAMPENING_NO_LIMITING_CONSISTENCY: True,
                ADVANCED_AUTOMATED_DAMPENING_GENERATION_FETCH_DELAY: 5,
                ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR: 0.988,
                ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR_ADJUSTED: 0.989,
                ADVANCED_ESTIMATED_ACTUALS_FETCH_DELAY: 5,
                ADVANCED_ESTIMATED_ACTUALS_LOG_MAPE_BREAKDOWN: True,
            },
        )

        options = copy.deepcopy(DEFAULT_INPUT2)
        options[AUTO_UPDATE] = 0
        options[GET_ACTUALS] = True
        options[USE_ACTUALS] = 1
        options[AUTO_DAMPEN] = True
        options[EXCLUDE_SITES] = ["3333-3333-3333-3333"]
        options[GENERATION_ENTITIES] = [
            "sensor.solar_export_sensor_1111_1111_1111_1111",
            "sensor.solar_export_sensor_2222_2222_2222_2222",
        ]
        options[SITE_EXPORT_ENTITY] = "sensor.site_export_sensor"
        options[SITE_EXPORT_LIMIT] = 5.0
        er.async_get(hass).async_get_or_create("sensor", DOMAIN, ENTITY_ACCURACY)
        entry = await async_init_integration(hass, options, extra_sensors=ExtraSensors.YES_WATT_HOUR)

        # Fiddle with undampened data cache
        undampened = json.loads(Path(f"{config_dir}/solcast-undampened.json").read_text(encoding="utf-8"), cls=JSONDecoder)
        for site in undampened[SITE_INFO].values():
            for forecast in site[FORECASTS]:
                forecast[ESTIMATE] *= 0.85
        Path(f"{config_dir}/solcast-undampened.json").write_text(json.dumps(undampened, cls=DateTimeEncoder), encoding="utf-8")

        # Fiddle with estimated actual data cache
        actuals = json.loads(Path(f"{config_dir}/solcast-actuals.json").read_text(encoding="utf-8"), cls=JSONDecoder)
        for site in actuals[SITE_INFO].values():
            for forecast in site[FORECASTS]:
                if (
                    forecast[PERIOD_START].astimezone(ZoneInfo(ZONE_RAW)).hour == 10
                    and forecast[PERIOD_START].astimezone(ZoneInfo(ZONE_RAW)).minute == 30
                ):
                    forecast[ESTIMATE] *= 0.91
        Path(f"{config_dir}/solcast-actuals.json").write_text(json.dumps(actuals, cls=DateTimeEncoder), encoding="utf-8")

        # Reload to load saved data and prime initial generation
        caplog.clear()
        coordinator, solcast = await reload_integration(hass, entry)
        if coordinator is None or solcast is None:
            pytest.fail("Reload failed")

        # Assert good start, that actuals and generation are enabled, and that the caches are saved
        _LOGGER.debug("Testing good start happened")
        for _ in range(30):  # Extra time needed for reload to complete
            await hass.async_block_till_done()
            freezer.tick(0.1)
        assert hass.data[DOMAIN].get(PRESUMED_DEAD, True) is False, "Integration presumed dead after setup"
        no_exception(caplog)

        assert "Auto-dampening suppressed: Excluded site for 3333-3333-3333-3333" in caplog.text
        assert "Interval 08:30 has peak estimated actual 0.936" in caplog.text
        assert "Interval 08:30 max generation: 0.777" in caplog.text
        assert "Auto-dampen factor for 08:30 is 0.830" in caplog.text
        # assert "Auto-dampen factor for 11:00" not in caplog.text
        assert "Ignoring insignificant factor for 11:00 of 0.993" in caplog.text
        assert "Ignoring excessive PV generation" not in caplog.text

        # Reload to load saved generation data
        caplog.clear()
        coordinator, solcast = await reload_integration(hass, entry)
        if coordinator is None or solcast is None:
            pytest.fail("Reload failed")
        assert Path(f"{config_dir}/solcast-actuals.json").is_file(), f"File {Path(f'{config_dir}/solcast-actuals.json')} should exist"
        assert Path(f"{config_dir}/solcast-generation.json").is_file(), f"File {Path(f'{config_dir}/solcast-generation.json')} should exist"
        assert "Generation data loaded" in caplog.text

        # Test service action to update dampening manually refused
        caplog.clear()
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, SERVICE_SET_DAMPENING, {DAMP_FACTOR: ("1.0," * 24)[:-1]}, blocking=True)

        # Test service action to force update actuals
        caplog.clear()
        _LOGGER.debug("Testing force update actuals with dampening enabled")
        await exec_update_actuals(hass, coordinator, solcast, caplog, freezer, SERVICE_FORCE_UPDATE_ESTIMATES)
        await wait_for_it(hass, caplog, freezer, "Estimated actual mean APE", long_time=True)
        assert "Estimated actuals dictionary for site 1111-1111-1111-1111" in caplog.text
        assert "Estimated actuals dictionary for site 2222-2222-2222-2222" in caplog.text
        assert "Estimated actuals dictionary for site 3333-3333-3333-3333" in caplog.text
        assert "Task dampening model_automated took" in caplog.text
        assert "Apply dampening to previous day estimated actuals" not in caplog.text

        # Roll over to tomorrow.
        _LOGGER.debug("Rolling over to tomorrow")
        caplog.clear()
        removed = -5
        value_removed = solcast.data_actuals[SITE_INFO]["1111-1111-1111-1111"][FORECASTS].pop(removed)
        freezer.move_to((dt.now(solcast.tz) + timedelta(hours=12)).replace(minute=0, second=0, microsecond=0))
        await hass.async_block_till_done()
        await wait_for_it(hass, caplog, freezer, "Update generation data", long_time=True)
        await wait_for_it(hass, caplog, freezer, "Estimated actual mean APE", long_time=True)
        no_exception(caplog)
        assert "Advanced option set automated_dampening_ignore_intervals: ['17:00']" in caplog.text
        assert "Calculating dampened estimated actual MAPE" in caplog.text
        assert "Calculating undampened estimated actual MAPE" in caplog.text
        assert "Dampened APE calculation for day" in caplog.text
        assert "Undampened APE calculation for day" in caplog.text
        assert "Estimated actual mean APE" in caplog.text
        assert "Getting estimated actuals update for site" in caplog.text
        assert "Apply dampening to previous day estimated actuals" in caplog.text
        assert "Task dampening model_automated took" in caplog.text
        assert (
            solcast.data_actuals[SITE_INFO]["1111-1111-1111-1111"][FORECASTS][removed - 24][PERIOD_START]  # pyright: ignore[reportOptionalMemberAccess]
            == value_removed[PERIOD_START]
        )
        assert "Auto-dampen factor for 08:30 is 0.830" in caplog.text

        ADVANCED_CHECKS = {
            0: {"base": 0.830, "adjusted": [0.858, 0.834]},
            1: {"base": 0.830, "adjusted": [0.858, 0.834]},
            2: {"base": 0.652, "adjusted": [0.709, 0.660]},
            3: {"base": 0.296, "adjusted": [0.410, 0.312]},
        }
        for preseve in (False, True):
            solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_PRESERVE_UNMATCHED_FACTORS] = preseve
            for model in (0, 1, 2, 3):
                caplog.clear()
                solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL] = model
                await solcast.dampening.model_automated()
                assert "Auto-dampen factor for 08:30 is {:.3f}".format(ADVANCED_CHECKS[model]["base"]) in caplog.text

                for adjustment_model in (0, 1):
                    caplog.clear()
                    solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL] = adjustment_model
                    await solcast.dampening.apply_forward()
                    _LOGGER.critical("Model %d/%d tested", model, adjustment_model)
                    assert (
                        re.search(
                            r"Adjusted granular dampening factor for .+ 08:30:00, {:.3f}".format(
                                ADVANCED_CHECKS[model]["adjusted"][adjustment_model]
                            ),
                            caplog.text,
                        )
                        is not None
                    ), f"Expected adjusted dampening factor log for model {model}, adjustment {adjustment_model}"

        # Verify that the dampening entity that should be disabled by default is, then enable it.
        entity = "sensor.solcast_pv_forecast_dampening"
        assert hass.states.get(entity) is None, f"State for {entity} should not exist"
        er.async_get(hass).async_update_entity(entity, disabled_by=None)
        async with asyncio.timeout(300):
            while "Reloading configuration entries because disabled_by changed" not in caplog.text:
                freezer.tick(0.01)
                await hass.async_block_till_done()

        # Roll over to another tomorrow.
        _LOGGER.debug("Rolling over to another tomorrow")
        caplog.clear()
        session_set(MOCK_CORRUPT_ACTUALS)
        freezer.move_to((dt.now(solcast.tz) + timedelta(days=1)).replace(minute=0, second=0, microsecond=0))  # pyright: ignore[reportOptionalMemberAccess]
        await wait_for_it(hass, caplog, freezer, "Update estimated actuals failed: No valid json returned", long_time=True)
        session_clear(MOCK_CORRUPT_ACTUALS)
        for _ in range(300):  # Extra time needed for get_generation to complete
            freezer.tick(0.1)
            await hass.async_block_till_done()

        # Cause an actual build exception
        _LOGGER.debug("Causing an actual build exception")
        caplog.clear()
        old_data = copy.deepcopy(solcast.data_actuals)  # pyright: ignore[reportOptionalMemberAccess]
        solcast.data_actuals[SITE_INFO]["1111-1111-1111-1111"] = None  # pyright: ignore[reportOptionalMemberAccess]
        with pytest.raises(ConfigEntryNotReady):
            await solcast.fetcher.build_forecast_and_actuals(raise_exc=True)  # pyright: ignore[reportOptionalMemberAccess]
        assert solcast.status == SolcastApiStatus.BUILD_FAILED_ACTUALS
        await solcast.dampening.model_automated()  # pyright: ignore[reportOptionalMemberAccess] # Hit an actuals missing deal-breaker
        assert "Auto-dampening suppressed: No estimated actuals yet for 1111-1111-1111-1111" in caplog.text
        solcast.data_actuals = old_data  # pyright: ignore[reportOptionalMemberAccess]
        solcast.status = SolcastApiStatus.OK

        # Cause a forecast build exception
        _LOGGER.debug("Causing a forecast build exception")
        caplog.clear()
        old_data = copy.deepcopy(solcast.data)  # pyright: ignore[reportOptionalMemberAccess]
        solcast.data[SITE_INFO]["1111-1111-1111-1111"] = None  # pyright: ignore[reportOptionalMemberAccess]
        with pytest.raises(ConfigEntryNotReady):
            await solcast.fetcher.build_forecast_and_actuals(raise_exc=True)  # pyright: ignore[reportOptionalMemberAccess]
        assert solcast.status == SolcastApiStatus.BUILD_FAILED_FORECASTS
        solcast.data = old_data  # pyright: ignore[reportOptionalMemberAccess]

        # Turn off auto-dampen.
        caplog.clear()
        opt = {**entry.options}
        opt[AUTO_DAMPEN] = False
        hass.config_entries.async_update_entry(entry, options=opt)
        await hass.async_block_till_done()
        assert "Options updated, action: The integration will reload" in caplog.text
        for _ in range(300):  # Extra time needed for reload to complete
            freezer.tick(0.1)
            await hass.async_block_till_done()

    finally:
        session_clear(MOCK_CORRUPT_ACTUALS)
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


@pytest.mark.parametrize(
    "extra_sensors",
    [
        ExtraSensors.YES_WITH_SUPPRESSION,
        ExtraSensors.YES_UNIT_NOT_IN_HISTORY,
        ExtraSensors.YES_NO_UNIT,
        ExtraSensors.DODGY,
        ExtraSensors.YES_POWER,
    ],
)
async def test_auto_dampen_issues(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    freezer: FrozenDateTimeFactory,
    extra_sensors: ExtraSensors,
) -> None:
    """Test automated dampening."""

    try:
        options = copy.deepcopy(DEFAULT_INPUT2)
        options[GET_ACTUALS] = True
        options[USE_ACTUALS] = 2
        options[AUTO_DAMPEN] = True
        options[EXCLUDE_SITES] = ["3333-3333-3333-3333"]
        options[GENERATION_ENTITIES] = [
            "sensor.solar_export_sensor_1111_1111_1111_1111",
            "sensor.solar_export_sensor_2222_2222_2222_2222",
        ]
        if extra_sensors != ExtraSensors.YES_WITH_SUPPRESSION:
            options[SITE_EXPORT_ENTITY] = "sensor.site_export_sensor"
            options[SITE_EXPORT_LIMIT] = 5.0
        if extra_sensors == ExtraSensors.YES_UNIT_NOT_IN_HISTORY:
            options[GENERATION_ENTITIES][0] = "sensor.not_valid"
        if extra_sensors == ExtraSensors.DODGY:
            options[SITE_EXPORT_ENTITY] = "sensor.not_valid"
            write_advanced_options(hass.config.config_dir, {ADVANCED_AUTOMATED_DAMPENING_ELEVATION_ADJUSTMENT: False})
        er.async_get(hass).async_get_or_create("sensor", DOMAIN, ENTITY_ACCURACY)
        entry = await async_init_integration(hass, options, extra_sensors=extra_sensors)

        # An orphaned forecast day sensor is created along with the extra sensors
        assert "Cleaning up orphaned sensor.solcast_solar_forecast_day_20" in caplog.text

        entity_registry = er.async_get(hass)
        if extra_sensors == ExtraSensors.YES_NO_UNIT:
            e = entity_registry.async_get(options[GENERATION_ENTITIES][0])
            if e is not None:
                entity_registry.async_update_entity(e.entity_id, disabled_by=RegistryEntryDisabler.USER)
            else:
                pytest.fail("Failed to get generation entity to disable")
            await hass.async_block_till_done()
        if extra_sensors == ExtraSensors.YES_UNIT_NOT_IN_HISTORY:
            e = entity_registry.async_get(options[SITE_EXPORT_ENTITY])
            if e is not None:
                entity_registry.async_update_entity(e.entity_id, disabled_by=RegistryEntryDisabler.USER)
            else:
                pytest.fail("Failed to get site export entity to disable")
            await hass.async_block_till_done()

        # Reload to load saved data and prime initial generation
        caplog.clear()
        coordinator, solcast = await reload_integration(hass, entry)
        if coordinator is None or solcast is None:
            pytest.fail("Reload failed")

        # Assert good start, that actuals and generation are enabled, and that the caches are saved
        _LOGGER.debug("Testing good start happened")
        for _ in range(30):  # Extra time needed for reload to complete
            freezer.tick(0.1)
            await hass.async_block_till_done()
        assert hass.data[DOMAIN].get(PRESUMED_DEAD, True) is False, "Integration presumed dead after setup"
        no_exception(caplog)
        assert "Calculating dampened estimated actual MAPE" not in caplog.text
        assert "Estimated actual mean APE" in caplog.text
        if extra_sensors not in [ExtraSensors.YES_UNIT_NOT_IN_HISTORY, ExtraSensors.YES_NO_UNIT]:
            assert "Retrieved day -1 PV generation data from entity: sensor.solar_export_sensor_1111_1111_1111_1111" in caplog.text
            assert "No day -2 PV generation data (or barely any) from entity: sensor.solar_export_sensor_1111_1111_1111_1111" in caplog.text
            # assert "Retrieved day -3 PV generation data from entity: sensor.solar_export_sensor_1111_1111_1111_1111" in caplog.text

        match extra_sensors:
            case ExtraSensors.YES_WITH_SUPPRESSION:
                for interval in ("12:00", "12:30", "13:00", "13:30", "14:00"):
                    assert re.search(r"Auto-dampen suppressed for interval.+" + interval, caplog.text) is not None, (
                        f"Expected auto-dampen suppression log for interval {interval}"
                    )
                    assert f"Interval {interval} max generation: 0.000, []" in caplog.text
            case ExtraSensors.YES_UNIT_NOT_IN_HISTORY:
                assert "has no unit_of_measurement, assuming kWh" not in caplog.text
                assert f"Generation entity {options[GENERATION_ENTITIES][0]} is not a valid entity" in caplog.text
                assert f"Site export entity {options[SITE_EXPORT_ENTITY]} is disabled, please enable it" in caplog.text
            case ExtraSensors.YES_NO_UNIT:
                assert "has no unit_of_measurement, assuming kWh" in caplog.text
                assert f"Generation entity {options[GENERATION_ENTITIES][0]} is disabled, please enable it" in caplog.text
            case ExtraSensors.DODGY:
                assert "has an unsupported unit_of_measurement 'MJ'" in caplog.text  # A dodgy unit should be logged
                assert f"Site export entity {options[SITE_EXPORT_ENTITY]} is not a valid entity" in caplog.text
                assert "Interval 11:00 max generation: 0.000, []" in caplog.text  # A jump in generation should not be seen as a peak
                assert "Interval 12:30 max generation: 3.900" in caplog.text  # Dodgy generation filtered but some valid data remains
                assert "Auto-dampen factor for 10:00 is 0.940" in caplog.text  # A valid interval still considered
                assert "Ignoring excessive PV generation jump at" in caplog.text  # Dodgy generation should be logged
            case ExtraSensors.YES_POWER:
                # Power entity path: site 1111 has insufficient readings, site 2222 has full history.
                assert "Insufficient power readings for entity: sensor.solar_export_sensor_1111_1111_1111_1111" in caplog.text
                assert "Retrieved day -1 PV generation data from entity: sensor.solar_export_sensor_2222_2222_2222_2222" in caplog.text
            case _:
                pytest.fail("Assertions missing for extra_sensors value")

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_apply_recovered_history_backfills_missing_actuals(caplog: pytest.LogCaptureFixture) -> None:
    """Test recovered historical actuals are dampened with delta-adjusted factors."""

    period_start = dt(2026, 3, 21, 22, 30, tzinfo=datetime.UTC)
    next_period_start = dt(2026, 3, 22, 22, 30, tzinfo=datetime.UTC)
    site_id = "1111-1111-1111-1111"

    async def sort_and_prune(site: str | None, data: dict[str, Any], _past_days: int, forecasts: dict[object, Any]) -> None:
        data[SITE_INFO][site] = {FORECASTS: list(forecasts.values())}

    dampening = Dampening.__new__(Dampening)
    dampening.api = SimpleNamespace(  # pyright: ignore[reportAttributeAccessIssue]
        sites=[{RESOURCE_ID: site_id}],
        options=SimpleNamespace(exclude_sites=[]),
        tz=ZoneInfo(ZONE_RAW),
        data_actuals={
            SITE_INFO: {
                site_id: {
                    FORECASTS: [
                        {PERIOD_START: period_start, ESTIMATE: 2.0},
                        {PERIOD_START: next_period_start, ESTIMATE: 2.0},
                    ]
                }
            }
        },
        data_actuals_dampened={SITE_INFO: {site_id: {FORECASTS: []}}},
        advanced_options={ADVANCED_HISTORY_MAX_DAYS: 30},
        fetcher=SimpleNamespace(sort_and_prune=sort_and_prune),
    )
    dampening.get_factor = lambda _site, _period_start, _interval_pv50: 0.6 if _interval_pv50 == 1.0 else 0.8  # pyright: ignore[reportAttributeAccessIssue]

    caplog.clear()
    await dampening.apply_recovered_history({site_id: {period_start.timestamp(), next_period_start.timestamp()}})

    assert "Apply dampening to recovered historical estimated actuals for 1111-1111-1111-1111: 2026-03-22 to 2026-03-23" in caplog.text
    assert dampening.api.data_actuals_dampened[SITE_INFO][site_id][FORECASTS] == [
        {PERIOD_START: period_start, ESTIMATE: 1.2},
        {PERIOD_START: next_period_start, ESTIMATE: 1.2},
    ]


async def test_apply_recovered_history_logs_nonconsecutive_date_spans(caplog: pytest.LogCaptureFixture) -> None:
    """Test recovered history logging preserves gaps between local dates."""

    site_id = "1111-1111-1111-1111"
    period_start = dt(2026, 3, 21, 22, 30, tzinfo=datetime.UTC)
    gap_period_start = dt(2026, 3, 24, 22, 30, tzinfo=datetime.UTC)

    async def sort_and_prune(site: str | None, data: dict[str, Any], _past_days: int, forecasts: dict[object, Any]) -> None:
        data[SITE_INFO][site] = {FORECASTS: list(forecasts.values())}

    dampening = Dampening.__new__(Dampening)
    dampening.api = SimpleNamespace(  # pyright: ignore[reportAttributeAccessIssue]
        sites=[{RESOURCE_ID: site_id}],
        options=SimpleNamespace(exclude_sites=[]),
        tz=ZoneInfo(ZONE_RAW),
        data_actuals={
            SITE_INFO: {
                site_id: {
                    FORECASTS: [
                        {PERIOD_START: period_start, ESTIMATE: 2.0},
                        {PERIOD_START: gap_period_start, ESTIMATE: 2.0},
                    ]
                }
            }
        },
        data_actuals_dampened={SITE_INFO: {site_id: {FORECASTS: []}}},
        advanced_options={ADVANCED_HISTORY_MAX_DAYS: 30},
        fetcher=SimpleNamespace(sort_and_prune=sort_and_prune),
    )
    dampening.get_factor = lambda _site, _period_start, _interval_pv50: 0.6 if _interval_pv50 == 1.0 else 0.8  # pyright: ignore[reportAttributeAccessIssue]

    caplog.clear()
    await dampening.apply_recovered_history({site_id: {period_start.timestamp(), gap_period_start.timestamp()}})

    assert "Apply dampening to recovered historical estimated actuals for 1111-1111-1111-1111: 2026-03-22, 2026-03-25" in caplog.text


def test_format_recovered_periods_empty_set_returns_empty_string() -> None:
    """Test that _format_recovered_periods returns an empty string for an empty set."""
    dampening = Dampening.__new__(Dampening)
    dampening.api = SimpleNamespace(tz=ZoneInfo(ZONE_RAW))  # pyright: ignore[reportAttributeAccessIssue]
    assert dampening._format_recovered_periods(set()) == ""


async def test_apply_recovered_history_no_actuals_match() -> None:
    """Test that apply_recovered_history skips a site when no actuals match the recovered timestamps."""

    site_id = "1111-1111-1111-1111"
    actual_period = dt(2026, 3, 21, 22, 30, tzinfo=datetime.UTC)
    recovered_period = dt(2026, 3, 20, 10, 0, tzinfo=datetime.UTC)  # Different timestamp — no match.

    dampening = Dampening.__new__(Dampening)
    dampening.api = SimpleNamespace(  # pyright: ignore[reportAttributeAccessIssue]
        sites=[{RESOURCE_ID: site_id}],
        options=SimpleNamespace(exclude_sites=[]),
        tz=ZoneInfo(ZONE_RAW),
        data_actuals={SITE_INFO: {site_id: {FORECASTS: [{PERIOD_START: actual_period, ESTIMATE: 2.0}]}}},
        data_actuals_dampened={SITE_INFO: {}},
        advanced_options={ADVANCED_HISTORY_MAX_DAYS: 30},
        fetcher=SimpleNamespace(sort_and_prune=None),  # Must not be called.
    )
    dampening.get_factor = lambda _site, _period_start, _interval_pv50: 0.8  # pyright: ignore[reportAttributeAccessIssue]

    # Recovered timestamp doesn't match any actual in data_actuals → actuals_undampened is empty → continue.
    await dampening.apply_recovered_history({site_id: {recovered_period.timestamp()}})

    assert dampening.api.data_actuals_dampened[SITE_INFO] == {}


async def test_apply_actuals_range_early_return_and_no_actuals() -> None:
    """Test _apply_actuals_range early return when start >= end, and continue when no actuals fall in range."""

    site_id = "1111-1111-1111-1111"
    base = dt(2026, 3, 21, 0, 0, tzinfo=datetime.UTC)

    dampening = Dampening.__new__(Dampening)
    dampening.api = SimpleNamespace(  # pyright: ignore[reportAttributeAccessIssue]
        sites=[{RESOURCE_ID: site_id}],
        options=SimpleNamespace(exclude_sites=[]),
        tz=ZoneInfo(ZONE_RAW),
        data_actuals={SITE_INFO: {site_id: {FORECASTS: [{PERIOD_START: base, ESTIMATE: 1.0}]}}},
        data_actuals_dampened={SITE_INFO: {}},
        advanced_options={ADVANCED_HISTORY_MAX_DAYS: 30},
        fetcher=SimpleNamespace(sort_and_prune=None),  # Must not be called.
    )
    dampening.get_factor = lambda _site, _period_start, _interval_pv50: 0.8  # pyright: ignore[reportAttributeAccessIssue]

    # start == end → early return.
    await dampening._apply_actuals_range(base, base)

    # start > end → early return.
    await dampening._apply_actuals_range(base + timedelta(hours=1), base)

    # start < end but the only actual (at base) falls outside [base+1h, base+2h) → continue.
    await dampening._apply_actuals_range(base + timedelta(hours=1), base + timedelta(hours=2))

    # sort_and_prune was None and never called — confirms no dampening was written.
    assert dampening.api.data_actuals_dampened[SITE_INFO] == {}


# --- Unit tests for compute_power_intervals and compute_energy_intervals ---


def _make_intervals(period_start: dt) -> dict[dt, float]:
    """Build empty 30-minute generation interval dict for one day."""
    return {period_start + timedelta(minutes=m): 0.0 for m in range(0, 1440, 30)}


def test_compute_power_intervals_time_weighted_averaging() -> None:
    """Test time-weighted average power per 30-min interval converts to kWh."""

    period_start = dt(2026, 2, 8, 0, 0, tzinfo=datetime.UTC)
    intervals = _make_intervals(period_start)

    # Interval 1 (00:00-00:30): 4.0 kW for 15 min, then 0.0 kW for 15 min.
    #   weighted avg = (4.0*900 + 0.0*900) / 1800 = 2.0 kW → 2.0 * 0.5 = 1.0 kWh
    # Interval 2 (00:30-01:00): constant 6.0 kW.
    #   weighted avg = 6.0 kW → 6.0 * 0.5 = 3.0 kWh
    power_readings: list[tuple[dt, float]] = [
        (period_start, 4.0),
        (period_start + timedelta(minutes=15), 0.0),
        (period_start + timedelta(minutes=30), 6.0),
        (period_start + timedelta(minutes=45), 6.0),
        (period_start + timedelta(minutes=60), 0.0),
        (period_start + timedelta(days=1), 0.0),
    ]

    result = compute_power_intervals(power_readings, intervals)

    assert result is True, "Time-weighted averaging should return True"
    assert abs(intervals[period_start] - 1.0) < 0.01, f"Interval 1 (half-power): expected ~1.0 kWh, got {intervals[period_start]}"
    assert abs(intervals[period_start + timedelta(minutes=30)] - 3.0) < 0.01, (
        f"Interval 2 (constant 6kW): expected ~3.0 kWh, got {intervals[period_start + timedelta(minutes=30)]}"
    )


def test_compute_power_intervals_watt_conversion() -> None:
    """Test power intervals with pre-converted W→kW values (factor 0.001)."""

    period_start = dt(2026, 2, 8, 0, 0, tzinfo=datetime.UTC)
    intervals = _make_intervals(period_start)

    # 2000 W * 0.001 = 2.0 kW constant for 30 min → 2.0 * 0.5 = 1.0 kWh
    conversion_factor = 0.001
    power_readings: list[tuple[dt, float]] = [
        (period_start, 2000.0 * conversion_factor),
        (period_start + timedelta(minutes=10), 2000.0 * conversion_factor),
        (period_start + timedelta(minutes=20), 2000.0 * conversion_factor),
        (period_start + timedelta(minutes=30), 0.0),
        (period_start + timedelta(days=1), 0.0),
    ]

    result = compute_power_intervals(power_readings, intervals)

    assert result is True, "W→kW conversion should return True"
    assert abs(intervals[period_start] - 1.0) < 0.01, f"W→kW interval: expected ~1.0 kWh, got {intervals[period_start]}"


def test_compute_power_intervals_insufficient_readings() -> None:
    """Test that ≤1 power reading returns False."""

    period_start = dt(2026, 2, 8, 0, 0, tzinfo=datetime.UTC)
    intervals = _make_intervals(period_start)

    # Single reading
    assert compute_power_intervals([(period_start, 2.0)], intervals) is False, "Single reading should return False"
    # Empty
    assert compute_power_intervals([], intervals) is False, "Empty readings should return False"
    # All intervals should remain zero
    assert all(v == 0.0 for v in intervals.values()), "All intervals should remain 0.0 after insufficient readings"


def test_compute_energy_intervals_period_edges_and_gaps() -> None:
    """Test energy distribution with period start/end boundaries and long gaps."""

    period_start = dt(2026, 2, 8, 0, 0, tzinfo=datetime.UTC)
    period_end = dt(2026, 2, 9, 0, 0, tzinfo=datetime.UTC)
    intervals = _make_intervals(period_start)

    # Simulate 7 states: regular 5-min increments then a 2h gap, then period end.
    times = [
        period_start,
        period_start + timedelta(minutes=5),
        period_start + timedelta(minutes=10),
        period_start + timedelta(minutes=15),
        period_start + timedelta(minutes=20),
        period_start + timedelta(hours=2),
        period_end,
    ]
    values = [0.0, 0.1, 0.2, 0.3, 0.4, 0.6, 0.7]

    sample_time = [t.replace(minute=t.minute // 30 * 30, second=0, microsecond=0) for t in times]
    sample_generation = [0.0] + [max(0, values[i + 1] - values[i]) for i in range(len(values) - 1)]
    sample_generation_time = list(times)
    sample_timedelta = [0] + [
        max(0, int((times[i + 1] - period_start).total_seconds() - (times[i] - period_start).total_seconds()))
        for i in range(len(times) - 1)
    ]
    # Reset first sample if at period_start.
    sample_generation[0] = 0.0
    sample_timedelta[0] = 0

    result = compute_energy_intervals(
        sample_time,
        sample_generation,
        sample_generation_time,
        sample_timedelta,
        intervals,
        period_start,
        period_end,
    )

    assert result.uniform_increment is True, "Period edges/gaps: expected uniform_increment True"
    day_total = sum(intervals.values())
    assert day_total > 0, "Period edges/gaps: day total should be > 0"


def test_compute_energy_intervals_uniform_increment() -> None:
    """Test uniform increment detection with equal-step generation deltas."""

    period_start = dt(2026, 2, 8, 0, 0, tzinfo=datetime.UTC)
    period_end = dt(2026, 2, 9, 0, 0, tzinfo=datetime.UTC)
    intervals = _make_intervals(period_start)

    # 11 states with perfectly uniform 0.1 kWh increments every 5 minutes.
    times = [period_start + timedelta(minutes=5 * i) for i in range(11)]
    times[-1] = period_end  # Last state at period end.
    values = [0.1 * i for i in range(11)]

    sample_time = [t.replace(minute=t.minute // 30 * 30, second=0, microsecond=0) for t in times]
    sample_generation = [0.0] + [max(0, values[i + 1] - values[i]) for i in range(len(values) - 1)]
    sample_generation_time = list(times)
    sample_timedelta = [0] + [
        max(0, int((times[i + 1] - period_start).total_seconds() - (times[i] - period_start).total_seconds()))
        for i in range(len(times) - 1)
    ]
    sample_generation[0] = 0.0
    sample_timedelta[0] = 0

    result = compute_energy_intervals(
        sample_time,
        sample_generation,
        sample_generation_time,
        sample_timedelta,
        intervals,
        period_start,
        period_end,
    )

    assert result.uniform_increment is True, "Uniform increment: expected uniform_increment True"
    assert result.upper > 0, f"Uniform increment: expected upper > 0, got {result.upper}"


def test_compute_energy_intervals_zero_timedelta() -> None:
    """Test energy intervals when all samples share the same timestamp."""

    period_start = dt(2026, 2, 8, 0, 0, tzinfo=datetime.UTC)
    period_end = dt(2026, 2, 9, 0, 0, tzinfo=datetime.UTC)
    intervals = _make_intervals(period_start)

    # 6 states all at period_start (zero time deltas).
    times = [period_start] * 6
    values = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]

    sample_time = [t.replace(minute=t.minute // 30 * 30, second=0, microsecond=0) for t in times]
    sample_generation = [0.0] + [max(0, values[i + 1] - values[i]) for i in range(len(values) - 1)]
    sample_generation_time = list(times)
    sample_timedelta = [0] + [
        max(0, int((times[i + 1] - period_start).total_seconds() - (times[i] - period_start).total_seconds()))
        for i in range(len(times) - 1)
    ]
    sample_generation[0] = 0.0
    sample_timedelta[0] = 0

    result = compute_energy_intervals(
        sample_time,
        sample_generation,
        sample_generation_time,
        sample_timedelta,
        intervals,
        period_start,
        period_end,
    )

    # With all zero time deltas, time_upper will be 0 (no non-zero samples).
    assert result.uniform_increment is True, "Zero timedelta: expected uniform_increment True"


async def test_config_flow_mixed_generation_entity_types(
    hass: HomeAssistant,
) -> None:
    """Test config flow rejects mixed energy and power generation entities."""

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="solcast_pv_solar",
        title=INTEGRATION,
        data=copy.deepcopy(DEFAULT_INPUT2),
        options=copy.deepcopy(DEFAULT_INPUT2),
    )
    entry.add_to_hass(hass)

    # Register one ENERGY and one POWER entity.
    entity_registry = er.async_get(hass)
    entity_registry.async_get_or_create(
        "sensor",
        "pytest",
        "energy_sensor",
        config_entry=entry,
        suggested_object_id="energy_sensor",
        unit_of_measurement="kWh",
        original_device_class=SensorDeviceClass.ENERGY,
    )
    entity_registry.async_get_or_create(
        "sensor",
        "pytest",
        "power_sensor",
        config_entry=entry,
        suggested_object_id="power_sensor",
        unit_of_measurement="kW",
        original_device_class=SensorDeviceClass.POWER,
    )

    flow = SolcastSolarOptionFlowHandler(entry)
    flow.hass = hass
    user_input = copy.deepcopy(DEFAULT_INPUT2)
    user_input[GENERATION_ENTITIES] = ["sensor.energy_sensor", "sensor.power_sensor"]
    user_input[SITE_EXPORT_ENTITY] = []
    result = await flow.async_step_init(user_input)
    assert result["errors"]["base"] == EXCEPTION_GENERATION_MIXED_TYPES  # type: ignore[index]


def test_target_timestamp_shifts_to_target_day() -> None:
    """_target_timestamp should preserve the UTC time-of-day on the target day."""
    dampening = Dampening.__new__(Dampening)
    past_ts = dt(2025, 1, 10, 13, 30, tzinfo=datetime.UTC)
    target_day = dt(2025, 1, 25, 0, 0, tzinfo=datetime.UTC)
    result = dampening._target_timestamp(past_ts, target_day)  # type: ignore[attr-defined]
    assert result == dt(2025, 1, 25, 13, 30, tzinfo=datetime.UTC)


def test_elevation_adjustment_ratio_near_horizon_returns_1(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ratio returns 1.0 when either sun elevation is below 5 degrees."""

    class _Loc:
        def __init__(self, elev_seq: list[float]) -> None:
            self._elev_seq = list(elev_seq)

        def solar_elevation(self, _when: dt) -> float:
            return self._elev_seq.pop(0)

    dampening = Dampening.__new__(Dampening)
    dampening.api = SimpleNamespace(hass=SimpleNamespace())  # type: ignore[attr-defined]

    # Past below horizon, target above
    monkeypatch.setattr(
        "homeassistant.components.solcast_solar.dampen.get_astral_location",
        lambda _hass: (_Loc([2.0, 40.0]), 0),
    )
    assert dampening.elevation_adjustment_ratio(NOW, NOW) == 1.0

    # Past above, target below horizon
    monkeypatch.setattr(
        "homeassistant.components.solcast_solar.dampen.get_astral_location",
        lambda _hass: (_Loc([40.0, 2.0]), 0),
    )
    assert dampening.elevation_adjustment_ratio(NOW, NOW) == 1.0


def test_elevation_adjustment_ratio_clamping_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ratio is clamped to [0.5, 2.0]."""

    class _Loc:
        def __init__(self, elev_past: float, elev_target: float) -> None:
            self.elev_past = elev_past
            self.elev_target = elev_target
            self._call = 0

        def solar_elevation(self, _when: dt) -> float:
            self._call += 1
            return self.elev_past if self._call == 1 else self.elev_target

        def solar_azimuth(self, _when: dt) -> float:
            return 180.0

    dampening = Dampening.__new__(Dampening)
    # No tilt/azimuth metadata on sites, so geometry is skipped and clamp is pure elevation. Simple.
    dampening.api = SimpleNamespace(  # pyright: ignore[reportAttributeAccessIssue]
        hass=SimpleNamespace(),
        options=SimpleNamespace(exclude_sites=[]),
        sites=[],
    )  # type: ignore[attr-defined]

    # High target vs low past would give a large ratio -> clamped to 2.0
    monkeypatch.setattr(
        "homeassistant.components.solcast_solar.dampen.get_astral_location",
        lambda _hass: (_Loc(10.0, 80.0), 0),
    )
    assert dampening.elevation_adjustment_ratio(NOW, NOW) == 2.0

    # Low target vs high past would give a tiny ratio -> clamped to 0.5
    monkeypatch.setattr(
        "homeassistant.components.solcast_solar.dampen.get_astral_location",
        lambda _hass: (_Loc(80.0, 10.0), 0),
    )
    assert dampening.elevation_adjustment_ratio(NOW, NOW) == 0.5


def test_elevation_adjustment_ratio_uses_site_geometry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tilt and azimuth metadata drive the ratio, diverging from the elevation-only baseline."""

    class _Loc:
        def solar_elevation(self, when: dt) -> float:
            return 35.0 if when.day == 1 else 55.0

        def solar_azimuth(self, when: dt) -> float:
            return 90.0 if when.day == 1 else 240.0

    past_ts = dt(2025, 6, 1, 12, 0, tzinfo=datetime.UTC)
    target_ts = dt(2025, 6, 2, 12, 0, tzinfo=datetime.UTC)

    dampening = Dampening.__new__(Dampening)
    dampening.api = SimpleNamespace(  # pyright: ignore[reportAttributeAccessIssue]
        hass=SimpleNamespace(),
        options=SimpleNamespace(exclude_sites=[]),
        sites=[
            {RESOURCE_ID: "east", SITE_ATTRIBUTE_TILT: 30.0, SITE_ATTRIBUTE_AZIMUTH: 90.0},
            {RESOURCE_ID: "west", SITE_ATTRIBUTE_TILT: 30.0, SITE_ATTRIBUTE_AZIMUTH: 270.0},
        ],
    )  # type: ignore[attr-defined]

    monkeypatch.setattr(
        "homeassistant.components.solcast_solar.dampen.get_astral_location",
        lambda _hass: (_Loc(), 0),
    )

    base_ratio = math.sin(math.radians(55.0)) / math.sin(
        math.radians(35.0)
    )  # About 1.428, which is the elevation-only ratio we expect to be adjusted by geometry.
    ratio = dampening.elevation_adjustment_ratio(past_ts, target_ts)

    # Computed geometry ratios per site:
    #   east (panel_azimuth=90):
    #     past_gain  = sin(35) x cos(30) + cos(35) x sin(30) x cos(90-90)   ≈ 0.9063
    #     target_gain= sin(55) x cos(30) + cos(55) x sin(30) x cos(240-90)  ≈ 0.4610
    #     ratio_east ≈ 0.509
    #   west (panel_azimuth=270):
    #     past_gain  = sin(35) x cos(30) + cos(35) x sin(30) x cos(90-270)  ≈ 0.0872
    #     target_gain= sin(55) x cos(30) + cos(55) x sin(30) x cos(240-270) ≈ 0.9578
    #     ratio_west ≈ 10.99
    #   average ≈ 5.75 → clamped to 2.0
    assert ratio == pytest.approx(2.0)
    assert ratio > base_ratio


def test_elevation_adjustment_ratio_falls_back_when_all_sites_face_away(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ratio falls back to elevation-only when every site's panel faces away (zero gain)."""

    class _Loc:
        def solar_elevation(self, when: dt) -> float:
            return 35.0 if when.day == 1 else 55.0

        def solar_azimuth(self, _when: dt) -> float:
            return 90.0

    past_ts = dt(2025, 6, 1, 12, 0, tzinfo=datetime.UTC)
    target_ts = dt(2025, 6, 2, 12, 0, tzinfo=datetime.UTC)

    dampening = Dampening.__new__(Dampening)
    # Tilt=90, panel faces directly away from sun (azimuth delta=180°), so gain <= 0 for both timestamps.
    dampening.api = SimpleNamespace(  # pyright: ignore[reportAttributeAccessIssue]
        hass=SimpleNamespace(),
        options=SimpleNamespace(exclude_sites=[]),
        sites=[{RESOURCE_ID: "a", SITE_ATTRIBUTE_TILT: 90, SITE_ATTRIBUTE_AZIMUTH: 270}],
    )  # type: ignore[attr-defined]

    monkeypatch.setattr(
        "homeassistant.components.solcast_solar.dampen.get_astral_location",
        lambda _hass: (_Loc(), 0),
    )

    base_ratio = math.sin(math.radians(55.0)) / math.sin(
        math.radians(35.0)
    )  # About 1.428, we want it to approximately match this time for the "impossible fallback".
    ratio = dampening.elevation_adjustment_ratio(past_ts, target_ts)
    assert ratio == pytest.approx(base_ratio)


def test_elevation_adjustment_ratio_unclamped_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """Geometry ratio is returned unchanged when it falls within [0.5, 2.0]."""

    class _Loc:
        def solar_elevation(self, when: dt) -> float:
            return 35.0 if when.day == 1 else 55.0

        def solar_azimuth(self, _when: dt) -> float:
            return 180.0  # Sun due south at both timestamps.

    past_ts = dt(2025, 6, 1, 12, 0, tzinfo=datetime.UTC)
    target_ts = dt(2025, 6, 2, 12, 0, tzinfo=datetime.UTC)

    dampening = Dampening.__new__(Dampening)
    dampening.api = SimpleNamespace(  # pyright: ignore[reportAttributeAccessIssue]
        hass=SimpleNamespace(),
        options=SimpleNamespace(exclude_sites=[]),
        sites=[{RESOURCE_ID: "south", SITE_ATTRIBUTE_TILT: 30.0, SITE_ATTRIBUTE_AZIMUTH: 180.0}],
    )  # type: ignore[attr-defined]

    monkeypatch.setattr(
        "homeassistant.components.solcast_solar.dampen.get_astral_location",
        lambda _hass: (_Loc(), 0),
    )

    # Single south-facing site, sun due south at both timestamps
    past_gain = math.sin(math.radians(35.0)) * math.cos(math.radians(30.0)) + math.cos(math.radians(35.0)) * math.sin(math.radians(30.0))
    target_gain = math.sin(math.radians(55.0)) * math.cos(math.radians(30.0)) + math.cos(math.radians(55.0)) * math.sin(math.radians(30.0))
    expected = target_gain / past_gain

    ratio = dampening.elevation_adjustment_ratio(past_ts, target_ts)  # 1.099 expected
    assert ratio == pytest.approx(expected)
    assert 0.5 < ratio < 2.0  # Confirm no clamping occurred.


async def test_calculate_elevation_adjustment_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise calculate() with elevation adjustment enabled."""

    tz = ZoneInfo("Australia/Sydney")
    api = MagicMock()
    api.tz = tz
    api.hass = SimpleNamespace()
    api.dt_helper = DateTimeHelper(tz)
    api.peak_intervals = [1.0] * 48
    api.advanced_options = {
        ADVANCED_AUTOMATED_DAMPENING_PRESERVE_UNMATCHED_FACTORS: False,
        ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_INTERVALS: 2,
        ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_GENERATION: 2,
        ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR: 0.95,
        ADVANCED_AUTOMATED_DAMPENING_ELEVATION_ADJUSTMENT: True,
    }
    api.filename_generation = tempfile.NamedTemporaryFile(delete=False).name
    api.filename_dampening = tempfile.NamedTemporaryFile(delete=False).name

    dampening = Dampening(api)

    # Stub astral so the ratio is deterministic and non-unity.
    class _Loc:
        def solar_elevation(self, _when: dt) -> float:
            return 60.0 if _when.day % 2 == 0 else 30.0

        def solar_azimuth(self, _when: dt) -> float:
            return 180.0

    monkeypatch.setattr(
        "homeassistant.components.solcast_solar.dampen.get_astral_location",
        lambda _hass: (_Loc(), 0),
    )

    interval = 20
    timestamps = [
        dt(2025, 10, 1, 0, 0, tzinfo=tz),  # elev 30
        dt(2025, 10, 2, 0, 0, tzinfo=tz),  # elev 60
        dt(2025, 10, 3, 0, 0, tzinfo=tz),  # elev 30
    ]
    # Third sample has act==0.0 -> hits the `act <= 0` short-circuit branch.
    gen_values = [0.8, 0.7, 0.5]
    act_values = [1.0, 1.0, 0.0]

    matching_intervals: dict[int, list[dt]] = {interval: timestamps}
    generation = dict(zip(timestamps, gen_values, strict=True))
    actuals = OrderedDict(zip(timestamps, act_values, strict=True))

    result = await dampening.calculate(matching_intervals, generation, actuals, [], 1)

    assert len(result) == 48
    assert result[interval] <= 1.0
