"""Tests for the Solcast Solar automated dampening."""

import asyncio
import copy
import datetime
from datetime import datetime as dt, timedelta
import json
import logging
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar.const import (
    AUTO_DAMPEN,
    AUTO_UPDATE,
    CONFIG_DISCRETE_NAME,
    CONFIG_FOLDER_DISCRETE,
    DOMAIN,
    EXCLUDE_SITES,
    GENERATION_ENTITIES,
    GET_ACTUALS,
    PRESUMED_DEAD,
    SERVICE_SET_DAMPENING,
    SITE_EXPORT_ENTITY,
    SITE_EXPORT_LIMIT,
    USE_ACTUALS,
)
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.solcastapi import SolcastApi
from homeassistant.components.solcast_solar.util import (
    DateTimeEncoder,
    JSONDecoder,
    SolcastApiStatus,
    percentile,
)
from homeassistant.config_entries import ConfigEntry
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
    session_clear,
    session_set,
)

ZONE = ZoneInfo(ZONE_RAW)
NOW = dt.now(ZONE)

_LOGGER = logging.getLogger(__name__)


def _no_exception(caplog: pytest.LogCaptureFixture):
    assert "Exception" not in caplog.text


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> tuple[SolcastUpdateCoordinator | None, SolcastApi | None]:
    """Reload the integration."""

    _LOGGER.warning("Reloading integration")
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    if hass.data[DOMAIN].get(entry.entry_id):
        try:
            return entry.runtime_data.coordinator, entry.runtime_data.coordinator.solcast
        except:  # noqa: E722
            _LOGGER.error("Failed to load coordinator (or solcast), which may be expected given test conditions")
    return None, None


async def _exec_update_actuals(
    hass: HomeAssistant,
    coordinator: SolcastUpdateCoordinator,
    solcast: SolcastApi,
    caplog: pytest.LogCaptureFixture,
    freezer: FrozenDateTimeFactory,
    action: str,
    last_update_delta: int = 0,
    wait: bool = True,
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
    if wait:
        await _wait_for_update(hass, caplog, freezer)
        await solcast.tasks_cancel()
        async with asyncio.timeout(1):
            while "Task model_automated_dampening took" not in caplog.text:
                await hass.async_block_till_done()
    await hass.async_block_till_done()


async def _wait_for_update(hass: HomeAssistant, caplog: pytest.LogCaptureFixture, freezer: FrozenDateTimeFactory) -> None:
    """Wait for forecast update completion."""

    async with asyncio.timeout(10):
        while (
            "Forecast update completed successfully" not in caplog.text
            and "Saved estimated actual cache" not in caplog.text
            and "Not requesting a solar forecast" not in caplog.text
            and "aborting forecast update" not in caplog.text
            and "update already in progress" not in caplog.text
            and "pausing" not in caplog.text
            and "Completed task update" not in caplog.text
            and "Completed task force_update" not in caplog.text
            and "ConfigEntryAuthFailed" not in caplog.text
        ):  # Wait for task to complete
            freezer.tick(0.1)
            await hass.async_block_till_done()


async def _wait_for_it(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture, freezer: FrozenDateTimeFactory, wait_for: str, long_time: bool = False
) -> None:
    """Wait for forecast update completion."""

    async with asyncio.timeout(300 if not long_time else 3000):
        while wait_for not in caplog.text:  # Wait for task to complete
            freezer.tick(0.1)
            await hass.async_block_till_done()


async def test_auto_dampen(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test automated dampening."""

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
                    "automated_dampening_insignificant_factor_adjusted": 0.988,
                    "automated_dampening_shift_fifteen": True,
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
        coordinator, solcast = await _reload(hass, entry)
        if coordinator is None or solcast is None:
            pytest.fail("Reload failed")

        # Assert good start, that actuals and generation are enabled, and that the caches are saved
        _LOGGER.debug("Testing good start happened")
        for _ in range(30):  # Extra time needed for reload to complete
            await hass.async_block_till_done()
            freezer.tick(0.1)
        assert hass.data[DOMAIN].get(PRESUMED_DEAD, True) is False
        _no_exception(caplog)

        assert "Auto-dampening suppressed: Excluded site for 3333-3333-3333-3333" in caplog.text
        assert "Interval 08:30 has peak estimated actual 0.936" in caplog.text
        assert "Interval 08:30 max generation: 0.923" in caplog.text
        assert "Auto-dampen factor for 08:30 is 0.986" in caplog.text
        # assert "Auto-dampen factor for 11:00" not in caplog.text
        assert "Ignoring insignificant factor for 08:00" in caplog.text
        assert re.search(r"Ignoring insignificant adjusted granular dampening factor.+08:30:00.+0\.988.+0\.986", caplog.text)
        assert "Ignoring excessive PV generation" not in caplog.text

        # Reload to load saved generation data
        caplog.clear()
        coordinator, solcast = await _reload(hass, entry)
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
        await _exec_update_actuals(hass, coordinator, solcast, caplog, freezer, "force_update_estimates")
        await _wait_for_it(hass, caplog, freezer, "Estimated actual mean APE", long_time=True)
        assert "Estimated actuals dictionary for site 1111-1111-1111-1111" in caplog.text
        assert "Estimated actuals dictionary for site 2222-2222-2222-2222" in caplog.text
        assert "Estimated actuals dictionary for site 3333-3333-3333-3333" in caplog.text
        assert "Task model_automated_dampening took" in caplog.text
        assert "Apply dampening to previous day estimated actuals" not in caplog.text

        # Roll over to tomorrow.
        _LOGGER.debug("Rolling over to tomorrow")
        caplog.clear()
        removed = -5
        value_removed = solcast._data_actuals["siteinfo"]["1111-1111-1111-1111"]["forecasts"].pop(removed)  # pyright: ignore[reportPrivateUsage]
        freezer.move_to((dt.now(solcast._tz) + timedelta(hours=12)).replace(minute=0, second=0, microsecond=0))  # pyright: ignore[reportPrivateUsage]
        await hass.async_block_till_done()
        await _wait_for_it(hass, caplog, freezer, "Update generation data", long_time=True)
        await _wait_for_it(hass, caplog, freezer, "Estimated actual mean APE", long_time=True)
        _no_exception(caplog)
        assert "Advanced option set automated_dampening_ignore_intervals: ['17:00']" in caplog.text
        assert "Calculating dampened estimated actual MAPE" in caplog.text
        assert "Calculating undampened estimated actual MAPE" in caplog.text
        assert "APE calculation for day" in caplog.text
        assert "Estimated actual mean APE" in caplog.text
        assert "Getting estimated actuals update for site" in caplog.text
        assert "Apply dampening to previous day estimated actuals" in caplog.text
        assert "Task model_automated_dampening took" in caplog.text
        assert (
            solcast._data_actuals["siteinfo"]["1111-1111-1111-1111"]["forecasts"][removed - 24]["period_start"]  # pyright: ignore[reportPrivateUsage,reportOptionalMemberAccess]
            == value_removed["period_start"]
        )  # pyright: ignore[reportPrivateUsage]
        assert "Auto-dampen factor for 08:30 is 0.986" in caplog.text

        ADVANCED_CHECKS = {
            0: {"base": 0.986, "adjusted": [0.988, 0.986]},
            1: {"base": 0.986, "adjusted": [0.988, 0.986]},
            2: {"base": 0.772, "adjusted": [0.809, 0.777]},
            3: {"base": 0.345, "adjusted": [0.451, 0.360]},
        }
        for preseve in (False, True):
            solcast.advanced_options["automated_dampening_preserve_unmatched_factors"] = preseve
            for model in (0, 1, 2, 3):
                caplog.clear()
                solcast.advanced_options["automated_dampening_model"] = model
                await solcast.model_automated_dampening()
                assert "Auto-dampen factor for 08:30 is {:.3f}".format(ADVANCED_CHECKS[model]["base"]) in caplog.text

                for adjustment_model in (0, 1):
                    caplog.clear()
                    solcast.advanced_options["automated_dampening_delta_adjustment_model"] = adjustment_model
                    await solcast.apply_forward_dampening()
                    # _LOGGER.critical("Model %d/%d tested", model, adjustment_model)
                    assert (
                        re.search(
                            r"08:30:00, {:.3f}".format(ADVANCED_CHECKS[model]["adjusted"][adjustment_model]),
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
        freezer.move_to((dt.now(solcast._tz) + timedelta(days=1)).replace(minute=0, second=0, microsecond=0))  # pyright: ignore[reportPrivateUsage,reportOptionalMemberAccess]
        await _wait_for_it(hass, caplog, freezer, "Update estimated actuals failed: No valid json returned", long_time=True)
        session_clear(MOCK_CORRUPT_ACTUALS)
        for _ in range(300):  # Extra time needed for get_generation to complete
            freezer.tick(0.1)
            await hass.async_block_till_done()

        # Cause an actual build exception
        _LOGGER.debug("Causing an actual build exception")
        caplog.clear()
        old_data = copy.deepcopy(solcast._data_actuals)  # pyright: ignore[reportPrivateUsage,reportOptionalMemberAccess]
        solcast._data_actuals["siteinfo"]["1111-1111-1111-1111"] = None  # pyright: ignore[reportPrivateUsage,reportOptionalMemberAccess]
        with pytest.raises(ConfigEntryNotReady):
            await solcast.build_forecast_and_actuals(raise_exc=True)  # pyright: ignore[reportOptionalMemberAccess]
        assert solcast.status == SolcastApiStatus.BUILD_FAILED_ACTUALS
        await solcast.model_automated_dampening()  # pyright: ignore[reportOptionalMemberAccess] # Hit an actuals missing deal-breaker
        assert "Auto-dampening suppressed: No estimated actuals yet for 1111-1111-1111-1111" in caplog.text
        solcast._data_actuals = old_data  # pyright: ignore[reportPrivateUsage,reportOptionalMemberAccess]
        solcast.status = SolcastApiStatus.OK

        # Cause a forecast build exception
        _LOGGER.debug("Causing a forecast build exception")
        caplog.clear()
        old_data = copy.deepcopy(solcast._data)  # pyright: ignore[reportPrivateUsage,reportOptionalMemberAccess]
        solcast._data["siteinfo"]["1111-1111-1111-1111"] = None  # pyright: ignore[reportPrivateUsage,reportOptionalMemberAccess,reportOptionalMemberAccess]
        with pytest.raises(ConfigEntryNotReady):
            await solcast.build_forecast_and_actuals(raise_exc=True)  # pyright: ignore[reportOptionalMemberAccess]
        assert solcast.status == SolcastApiStatus.BUILD_FAILED_FORECASTS
        solcast._data = old_data  # pyright: ignore[reportPrivateUsage,reportOptionalMemberAccess]

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
        config_dir = f"{hass.config.config_dir}/{CONFIG_DISCRETE_NAME}" if CONFIG_FOLDER_DISCRETE else hass.config.config_dir
        if CONFIG_FOLDER_DISCRETE:
            Path(config_dir).mkdir(parents=False, exist_ok=True)
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
            Path(f"{config_dir}/solcast-advanced.json").write_text(
                json.dumps(
                    {
                        "automated_dampening_no_limiting_consistency": False,
                        "automated_dampening_shift_fifteen": True,
                    }
                ),
                encoding="utf-8",
            )
        if extra_sensors == ExtraSensors.DODGY:
            options[SITE_EXPORT_ENTITY] = "sensor.not_valid"
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
        coordinator, solcast = await _reload(hass, entry)
        if coordinator is None or solcast is None:
            pytest.fail("Reload failed")

        # Assert good start, that actuals and generation are enabled, and that the caches are saved
        _LOGGER.debug("Testing good start happened")
        for _ in range(30):  # Extra time needed for reload to complete
            freezer.tick(0.1)
            await hass.async_block_till_done()
        assert hass.data[DOMAIN].get(PRESUMED_DEAD, True) is False
        _no_exception(caplog)
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
                assert "Interval 13:00 max generation: 0.000, []" in caplog.text  # Dodgy generation should prevent interval consideration
                assert "Auto-dampen factor for 10:00 is 0.940" in caplog.text  # A valid interval still considered
                assert "Ignoring excessive PV generation jump of 6.000 kWh" in caplog.text  # Dodgy generation should be logged
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
