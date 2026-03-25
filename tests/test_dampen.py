"""Tests for the Solcast Solar automated dampening."""

import asyncio
import copy
import datetime
from datetime import datetime as dt, timedelta
import json
import logging
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.solcast_solar.config_flow import (
    SolcastSolarOptionFlowHandler,
)
from homeassistant.components.solcast_solar.const import (
    AUTO_DAMPEN,
    AUTO_UPDATE,
    CONFIG_DISCRETE_NAME,
    CONFIG_FOLDER_DISCRETE,
    DOMAIN,
    ENTITY_ACCURACY,
    ESTIMATE,
    EXCLUDE_SITES,
    FORECASTS,
    GENERATION_ENTITIES,
    GET_ACTUALS,
    PERIOD_START,
    PRESUMED_DEAD,
    RESOURCE_ID,
    SERVICE_SET_DAMPENING,
    SITE_EXPORT_ENTITY,
    SITE_EXPORT_LIMIT,
    SITE_INFO,
    USE_ACTUALS,
)
from homeassistant.components.solcast_solar.dampen import Dampening
from homeassistant.components.solcast_solar.util import (
    DateTimeEncoder,
    JSONDecoder,
    SolcastApiStatus,
    compute_energy_intervals,
    compute_power_intervals,
    percentile,
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
    no_exception,
    reload_integration,
    session_clear,
    session_set,
    wait_for_it,
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

    assert await async_cleanup_integration_tests(hass)

    try:
        config_dir = f"{hass.config.config_dir}/{CONFIG_DISCRETE_NAME}" if CONFIG_FOLDER_DISCRETE else hass.config.config_dir
        if CONFIG_FOLDER_DISCRETE:
            Path(config_dir).mkdir(parents=False, exist_ok=True)

        Path(f"{config_dir}/solcast-advanced.json").write_text(
            json.dumps(
                {
                    "automated_dampening_ignore_intervals": ["17:00"],
                    "automated_dampening_no_limiting_consistency": True,
                    "automated_dampening_generation_fetch_delay": 5,
                    "automated_dampening_insignificant_factor": 0.988,
                    "automated_dampening_insignificant_factor_adjusted": 0.989,
                    "estimated_actuals_fetch_delay": 5,
                    "estimated_actuals_log_mape_breakdown": True,
                }
            ),
            encoding="utf-8",
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
        for site in undampened["siteinfo"].values():
            for forecast in site["forecasts"]:
                forecast["pv_estimate"] *= 0.85
        Path(f"{config_dir}/solcast-undampened.json").write_text(json.dumps(undampened, cls=DateTimeEncoder), encoding="utf-8")

        # Fiddle with estimated actual data cache
        actuals = json.loads(Path(f"{config_dir}/solcast-actuals.json").read_text(encoding="utf-8"), cls=JSONDecoder)
        for site in actuals["siteinfo"].values():
            for forecast in site["forecasts"]:
                if (
                    forecast["period_start"].astimezone(ZoneInfo(ZONE_RAW)).hour == 10
                    and forecast["period_start"].astimezone(ZoneInfo(ZONE_RAW)).minute == 30
                ):
                    forecast["pv_estimate"] *= 0.91
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
        assert hass.data[DOMAIN].get(PRESUMED_DEAD, True) is False
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
        assert Path(f"{config_dir}/solcast-actuals.json").is_file()
        assert Path(f"{config_dir}/solcast-generation.json").is_file()
        assert "Generation data loaded" in caplog.text

        # Test service action to update dampening manually refused
        caplog.clear()
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, SERVICE_SET_DAMPENING, {"damp_factor": ("1.0," * 24)[:-1]}, blocking=True)

        # Test service action to force update actuals
        caplog.clear()
        _LOGGER.debug("Testing force update actuals with dampening enabled")
        await exec_update_actuals(hass, coordinator, solcast, caplog, freezer, "force_update_estimates")
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
        value_removed = solcast.data_actuals["siteinfo"]["1111-1111-1111-1111"]["forecasts"].pop(removed)
        freezer.move_to((dt.now(solcast.tz) + timedelta(hours=12)).replace(minute=0, second=0, microsecond=0))
        await hass.async_block_till_done()
        await wait_for_it(hass, caplog, freezer, "Update generation data", long_time=True)
        await wait_for_it(hass, caplog, freezer, "Estimated actual mean APE", long_time=True)
        no_exception(caplog)
        assert "Advanced option set automated_dampening_ignore_intervals: ['17:00']" in caplog.text
        assert "Calculating dampened estimated actual MAPE" in caplog.text
        assert "Calculating undampened estimated actual MAPE" in caplog.text
        assert "APE calculation for day" in caplog.text
        assert "Estimated actual mean APE" in caplog.text
        assert "Getting estimated actuals update for site" in caplog.text
        assert "Apply dampening to previous day estimated actuals" in caplog.text
        assert "Task dampening model_automated took" in caplog.text
        assert (
            solcast.data_actuals["siteinfo"]["1111-1111-1111-1111"]["forecasts"][removed - 24]["period_start"]  # pyright: ignore[reportOptionalMemberAccess]
            == value_removed["period_start"]
        )
        assert "Auto-dampen factor for 08:30 is 0.830" in caplog.text

        ADVANCED_CHECKS = {
            0: {"base": 0.830, "adjusted": [0.858, 0.834]},
            1: {"base": 0.830, "adjusted": [0.858, 0.834]},
            2: {"base": 0.652, "adjusted": [0.709, 0.660]},
            3: {"base": 0.296, "adjusted": [0.410, 0.312]},
        }
        for preseve in (False, True):
            solcast.advanced_options["automated_dampening_preserve_unmatched_factors"] = preseve
            for model in (0, 1, 2, 3):
                caplog.clear()
                solcast.advanced_options["automated_dampening_model"] = model
                await solcast.dampening.model_automated()
                assert "Auto-dampen factor for 08:30 is {:.3f}".format(ADVANCED_CHECKS[model]["base"]) in caplog.text

                for adjustment_model in (0, 1):
                    caplog.clear()
                    solcast.advanced_options["automated_dampening_delta_adjustment_model"] = adjustment_model
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
                    )

        # Verify that the dampening entity that should be disabled by default is, then enable it.
        entity = "sensor.solcast_pv_forecast_dampening"
        assert hass.states.get(entity) is None
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
        solcast.data_actuals["siteinfo"]["1111-1111-1111-1111"] = None  # pyright: ignore[reportOptionalMemberAccess]
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
        solcast.data["siteinfo"]["1111-1111-1111-1111"] = None  # pyright: ignore[reportOptionalMemberAccess]
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
        assert await async_cleanup_integration_tests(hass)


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
        assert hass.data[DOMAIN].get(PRESUMED_DEAD, True) is False
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
                    assert re.search(r"Auto-dampen suppressed for interval.+" + interval, caplog.text) is not None
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
        assert await async_cleanup_integration_tests(hass)


async def test_percentile() -> None:
    """Test percentile function."""

    data: list[float]

    data = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile(data, 0) == 1.0
    assert percentile(data, 25) == 2.0
    assert percentile(data, 50) == 3.0
    assert percentile(data, 75) == 4.0
    assert percentile(data, 100) == 5.0

    data = [5.0]
    assert percentile(data, 0) == 5.0
    assert percentile(data, 25) == 5.0
    assert percentile(data, 50) == 5.0
    assert percentile(data, 75) == 5.0
    assert percentile(data, 100) == 5.0

    data = [0.1] * 10 + [0.5]
    assert percentile(data, 90) == 0.1

    data = [0.1] * 8 + [0.5]
    assert round(percentile(data, 90), 2) == 0.18

    data = []
    assert percentile(data, 50) == 0.0


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
        advanced_options={"history_max_days": 30},
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
        advanced_options={"history_max_days": 30},
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
        advanced_options={"history_max_days": 30},
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
        advanced_options={"history_max_days": 30},
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

    assert result is True
    assert abs(intervals[period_start] - 1.0) < 0.01
    assert abs(intervals[period_start + timedelta(minutes=30)] - 3.0) < 0.01


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

    assert result is True
    assert abs(intervals[period_start] - 1.0) < 0.01


def test_compute_power_intervals_insufficient_readings() -> None:
    """Test that ≤1 power reading returns False."""

    period_start = dt(2026, 2, 8, 0, 0, tzinfo=datetime.UTC)
    intervals = _make_intervals(period_start)

    # Single reading
    assert compute_power_intervals([(period_start, 2.0)], intervals) is False
    # Empty
    assert compute_power_intervals([], intervals) is False
    # All intervals should remain zero
    assert all(v == 0.0 for v in intervals.values())


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

    assert result.uniform_increment is True
    day_total = sum(intervals.values())
    assert day_total > 0


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

    assert result.uniform_increment is True
    assert result.upper > 0


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
    assert result.uniform_increment is True


async def test_config_flow_mixed_generation_entity_types(
    hass: HomeAssistant,
) -> None:
    """Test config flow rejects mixed energy and power generation entities."""

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="solcast_pv_solar",
        title="Solcast PV Forecast",
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
    assert result["errors"]["base"] == "generation_mixed_types"  # type: ignore[index]
