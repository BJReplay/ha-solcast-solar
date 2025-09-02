"""Tests for the Solcast Solar automated dampening."""

import asyncio
import copy
import datetime
from datetime import datetime as dt, timedelta
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar.const import (
    AUTO_DAMPEN,
    DOMAIN,
    EXCLUDE_SITES,
    GENERATION_ENTITIES,
    GET_ACTUALS,
    SERVICE_SET_DAMPENING,
    SITE_EXPORT_ENTITY,
    SITE_EXPORT_LIMIT,
    USE_ACTUALS,
)
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.solcastapi import SolcastApi
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from . import (
    DEFAULT_INPUT2,
    MOCK_BUSY,
    MOCK_CORRUPT_ACTUALS,
    ZONE_RAW,
    async_cleanup_integration_tests,
    async_init_integration,
    session_clear,
    session_set,
)

ZONE = ZoneInfo(ZONE_RAW)
NOW = dt.now(ZONE)

_LOGGER = logging.getLogger(__name__)


def get_now_utc() -> dt:
    """Mock get_now_utc, spoof middle-of-the-day-ish."""

    return NOW.replace(hour=12, minute=27, second=0, microsecond=0).astimezone(datetime.UTC)


def get_real_now_utc() -> dt:
    """Mock get_real_now_utc, spoof middle-of-the-day-ish."""

    return NOW.replace(hour=12, minute=27, second=27, microsecond=27272).astimezone(datetime.UTC)


def get_hour_start_utc() -> dt:
    """Mock get_hour_start_utc, spoof middle-of-the-day-ish."""

    return NOW.replace(hour=12, minute=0, second=0, microsecond=0).astimezone(datetime.UTC)


def patch_solcast_api(solcast: SolcastApi):
    """Patch SolcastApi to return a fixed time.

    Cannot use freezegun with these tests because time must tick (the tick= option won't work).
    """
    solcast.get_now_utc = get_now_utc  # type: ignore[method-assign]
    solcast.get_real_now_utc = get_real_now_utc  # type: ignore[method-assign]
    solcast.get_hour_start_utc = get_hour_start_utc  # type: ignore[method-assign]
    return solcast


def _no_exception(caplog: pytest.LogCaptureFixture):
    assert "Error" not in caplog.text
    assert "Exception" not in caplog.text


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
        config_dir = hass.config.config_dir

        options = copy.deepcopy(DEFAULT_INPUT2)
        options[GET_ACTUALS] = True
        options[USE_ACTUALS] = True
        options[AUTO_DAMPEN] = True
        options[EXCLUDE_SITES] = ["3333-3333-3333-3333"]
        options[GENERATION_ENTITIES] = ["sensor.solar_export_sensor_1111_1111_1111_1111", "sensor.solar_export_sensor_2222_2222_2222_2222"]
        options[SITE_EXPORT_ENTITY] = "sensor.site_export_sensor"
        options[SITE_EXPORT_LIMIT] = 5.0
        entry = await async_init_integration(hass, options, extra_sensors=True)
        coordinator = entry.runtime_data.coordinator
        solcast = patch_solcast_api(coordinator.solcast)

        # Reload to load saved data and prime initial generation
        caplog.clear()
        coordinator, solcast = await _reload(hass, entry)
        if coordinator is None or solcast is None:
            pytest.fail("Reload failed")

        # Assert good start, that actuals and generation are enabled, and that the caches are saved
        _LOGGER.debug("Testing good start happened")
        assert hass.data[DOMAIN].get("presumed_dead", True) is False
        _no_exception(caplog)

        assert "Auto-dampening suppressed: Excluded site for 3333-3333-3333-3333" in caplog.text
        assert "Interval 08:30 has peak estimated actual 0.936" in caplog.text
        assert "Max generation: 0.800" in caplog.text
        assert "Auto-dampen factor for 08:30 is 0.855" in caplog.text
        assert "Auto-dampen factor for 11:00" not in caplog.text
        assert "Ignoring insignificant factor for 11:00 of 0.988" in caplog.text

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

        # Verify that the dampening entity that should be disabled by default is, then enable it.
        entity = "sensor.solcast_pv_forecast_dampening"
        assert hass.states.get(entity) is None
        er.async_get(hass).async_update_entity(entity, disabled_by=None)
        async with asyncio.timeout(300):
            while "Reloading configuration entries because disabled_by changed" not in caplog.text:
                freezer.tick(0.01)
                await hass.async_block_till_done()

        # Roll over to tomorrow.
        _LOGGER.debug("Rolling over to tomorrow")
        caplog.clear()
        freezer.move_to((dt.now(solcast._tz) + timedelta(hours=12)).replace(minute=20, second=0, microsecond=0))  # pyright: ignore[reportPrivateUsage]
        await hass.async_block_till_done()
        await _wait_for_it(hass, caplog, freezer, "Task build_data_actuals took")
        await hass.async_block_till_done()
        assert "Getting estimated actuals update for site" in caplog.text
        assert "Apply dampening to previous day estimated actuals" in caplog.text
        caplog.clear()
        freezer.move_to(dt.now(solcast._tz).replace(minute=50, second=0, microsecond=0))  # pyright: ignore[reportPrivateUsage]
        await hass.async_block_till_done()
        await _wait_for_it(hass, caplog, freezer, "Task model_automated_dampening took")
        await hass.async_block_till_done()
        assert "Auto-dampen factor for 08:30 is 0.855" in caplog.text

        # Roll over to another tomorrow.
        _LOGGER.debug("Rolling over to another tomorrow")
        caplog.clear()
        session_set(MOCK_CORRUPT_ACTUALS)
        freezer.move_to((dt.now(solcast._tz) + timedelta(days=1)).replace(minute=20, second=0, microsecond=0))  # pyright: ignore[reportPrivateUsage]
        await hass.async_block_till_done()
        await _wait_for_it(hass, caplog, freezer, "Update estimated actuals failed: No valid json returned")
        session_clear(MOCK_CORRUPT_ACTUALS)
        for _ in range(300):  # Extra time needed for get_generation to complete
            await hass.async_block_till_done()
            freezer.tick(0.1)

        # Roll over to yet another tomorrow to test get actuals failure due to Solcast busy.
        _LOGGER.debug("Rolling over to yet another tomorrow")
        caplog.clear()
        session_set(MOCK_BUSY)
        freezer.move_to((dt.now(solcast._tz) + timedelta(days=1)).replace(minute=20, second=0, microsecond=0))  # pyright: ignore[reportPrivateUsage]
        await hass.async_block_till_done()
        await _wait_for_it(hass, caplog, freezer, "HTTP session status 429/Try again later", long_time=True)
        session_clear(MOCK_BUSY)

        # Cause an actual build exception
        _LOGGER.debug("Causing an actual build exception")
        caplog.clear()
        old_data = copy.deepcopy(solcast._data_actuals)  # pyright: ignore[reportPrivateUsage]
        solcast._data_actuals["siteinfo"]["1111-1111-1111-1111"] = None  # pyright: ignore[reportPrivateUsage]
        status = await solcast.build_forecast_and_actuals()
        assert "Failed to build estimated actual data" in status
        await solcast.model_automated_dampening()  # Hit an actuals missing deal-breaker
        assert "Auto-dampening suppressed: No estimated actuals yet for 1111-1111-1111-1111" in caplog.text
        solcast._data_actuals = old_data  # pyright: ignore[reportPrivateUsage]

        # Cause a forecast build exception
        _LOGGER.debug("Causing a forecast build exception")
        caplog.clear()
        old_data = copy.deepcopy(solcast._data)  # pyright: ignore[reportPrivateUsage]
        solcast._data["siteinfo"]["1111-1111-1111-1111"] = None  # pyright: ignore[reportPrivateUsage]
        status = await solcast.build_forecast_and_actuals()
        assert "Failed to build forecast data" in status
        solcast._data = old_data  # pyright: ignore[reportPrivateUsage]

        # Turn off auto-dampen.
        caplog.clear()
        opt = {**entry.options}
        opt[AUTO_DAMPEN] = False
        hass.config_entries.async_update_entry(entry, options=opt)
        await hass.async_block_till_done()
        assert "Options updated, action: The integration will reload" in caplog.text
        for _ in range(300):  # Extra time needed for reload to complete
            await hass.async_block_till_done()
            freezer.tick(0.1)

    finally:
        assert await async_cleanup_integration_tests(hass)
