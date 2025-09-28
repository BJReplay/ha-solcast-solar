"""Tests for the Solcast Solar automated dampening."""

import asyncio
import copy
from datetime import datetime as dt, timedelta
import logging
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar.const import (
    AUTO_DAMPEN,
    AUTO_UPDATE,
    EXCLUDE_SITES,
    GENERATION_ENTITIES,
    GET_ACTUALS,
    SITE_EXPORT_ENTITY,
    SITE_EXPORT_LIMIT,
    USE_ACTUALS,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import (
    DEFAULT_INPUT2,
    ZONE_RAW,
    ExtraSensors,
    async_cleanup_integration_tests,
    async_init_integration,
    entity_history,
)

ZONE = ZoneInfo(ZONE_RAW)
NOW = dt.now(ZONE)

_LOGGER = logging.getLogger(__name__)


entity_history["days_export"] = 1
entity_history["days_generation"] = 5
entity_history["offset"] = 2


@pytest.fixture(autouse=True)
def frozen_time() -> None:
    """Override autouse fixture for this module.

    Using other mock times.
    """
    return


async def midnight_utc(hass: HomeAssistant, freezer: FrozenDateTimeFactory, caplog: pytest.LogCaptureFixture, at: str):
    """Set the time to midnight UTC."""
    freezer.move_to(at)
    for _ in range(600):
        freezer.tick(0.1)
        await hass.async_block_till_done()
        if "Updating sensor Third Site" in caplog.text:
            break


async def five_minute_bump(hass: HomeAssistant, freezer: FrozenDateTimeFactory, caplog: pytest.LogCaptureFixture):
    """Set the time to the next five-minute point."""
    freezer.move_to(dt.now().replace(minute=dt.now().minute // 5 * 5, second=0, microsecond=0) + timedelta(minutes=5))
    while "Updating sensor Dampening" not in caplog.text:
        freezer.tick(0.01)
        await hass.async_block_till_done()


async def test_auto_dampen_dst_transition(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test automated dampening."""

    try:
        options = copy.deepcopy(DEFAULT_INPUT2)
        options[AUTO_UPDATE] = 1
        options[GET_ACTUALS] = True
        options[USE_ACTUALS] = 0
        options[AUTO_DAMPEN] = True
        options[EXCLUDE_SITES] = ["3333-3333-3333-3333"]
        options[GENERATION_ENTITIES] = [
            "sensor.solar_export_sensor_1111_1111_1111_1111",
            "sensor.solar_export_sensor_2222_2222_2222_2222",
        ]
        options[SITE_EXPORT_ENTITY] = "sensor.site_export_sensor"
        options[SITE_EXPORT_LIMIT] = 5.0

        # Test transition from standard to summer time.
        freezer.move_to("2025-10-02 18:00:00")

        await async_init_integration(hass, options, timezone="Australia/Sydney", extra_sensors=ExtraSensors.YES_WATT_HOUR)

        # Enable the dampening entity
        dampening_entity = "sensor.solcast_pv_forecast_dampening"
        er.async_get(hass).async_update_entity(dampening_entity, disabled_by=None)
        async with asyncio.timeout(300):
            while "Reloading configuration entries because disabled_by changed" not in caplog.text:
                freezer.tick(0.01)
                await hass.async_block_till_done()

        await midnight_utc(hass, freezer, caplog, "2025-10-03 00:00:00")

        freezer.move_to("2025-10-03 14:00:00")
        caplog.clear()
        for _ in range(60000):
            freezer.tick(0.1)
            await hass.async_block_till_done()
            if "Applying future dampening" in caplog.text:
                break
        assert "Adjusted granular dampening factor for 2025-10-04 09:00:00 is 0.804" in caplog.text
        assert "Auto-dampen factor for 09:00 is 0.804" in caplog.text
        caplog.clear()
        await five_minute_bump(hass, freezer, caplog)
        if (state := hass.states.get(dampening_entity)) is not None:
            assert state.state == "True"
            if (attribute := state.attributes.get("factors")) is not None:
                assert len(attribute) == 48
                assert attribute[18]["factor"] == 0.804
            else:
                pytest.fail("Dampening attribute `factors` is None")
        else:
            pytest.fail("Dampening entity state is None")

        await midnight_utc(hass, freezer, caplog, "2025-10-04 00:00:00")

        freezer.move_to("2025-10-04 14:00:00")
        caplog.clear()
        for _ in range(60000):
            freezer.tick(0.1)
            await hass.async_block_till_done()
            if "Applying future dampening" in caplog.text:
                break
        assert "Auto-dampen factor for 10:00 is 0.804" in caplog.text
        assert "Adjusted granular dampening factor for 2025-10-05 10:00:00 is 0.804" in caplog.text
        caplog.clear()
        await five_minute_bump(hass, freezer, caplog)
        if (state := hass.states.get(dampening_entity)) is not None:
            assert state.state == "True"
            if (attribute := state.attributes.get("factors")) is not None:
                assert len(attribute) == 48
                assert attribute[20]["factor"] == 0.804
            else:
                pytest.fail("Dampening attribute `factors` is None")
        else:
            pytest.fail("Dampening entity state is None")

        freezer.move_to("2025-10-04 16:00:00")
        caplog.clear()
        await hass.async_block_till_done()
        if (state := hass.states.get(dampening_entity)) is not None:
            assert state.state == "True"
            if (attribute := state.attributes.get("factors")) is not None:
                assert len(attribute) == 48
                assert attribute[20]["factor"] == 0.804
            else:
                pytest.fail("Dampening attribute `factors` is None")
        else:
            pytest.fail("Dampening entity state is None")

    finally:
        assert await async_cleanup_integration_tests(hass)


async def test_auto_dampen_dst_transition_back(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test automated dampening."""

    try:
        options = copy.deepcopy(DEFAULT_INPUT2)
        options[AUTO_UPDATE] = 1
        options[GET_ACTUALS] = True
        options[USE_ACTUALS] = 0
        options[AUTO_DAMPEN] = True
        options[EXCLUDE_SITES] = ["3333-3333-3333-3333"]
        options[GENERATION_ENTITIES] = [
            "sensor.solar_export_sensor_1111_1111_1111_1111",
            "sensor.solar_export_sensor_2222_2222_2222_2222",
        ]
        options[SITE_EXPORT_ENTITY] = "sensor.site_export_sensor"
        options[SITE_EXPORT_LIMIT] = 5.0

        # Test transition from summer to standard time.
        freezer.move_to("2026-04-02 18:00:00")

        await async_init_integration(hass, options, timezone="Australia/Sydney", extra_sensors=ExtraSensors.YES_WATT_HOUR)

        # Enable the dampening entity
        dampening_entity = "sensor.solcast_pv_forecast_dampening"
        er.async_get(hass).async_update_entity(dampening_entity, disabled_by=None)
        async with asyncio.timeout(300):
            while "Reloading configuration entries because disabled_by changed" not in caplog.text:
                freezer.tick(0.01)
                await hass.async_block_till_done()

        await midnight_utc(hass, freezer, caplog, "2026-04-03 00:00:00")

        freezer.move_to("2026-04-03 14:00:00")
        caplog.clear()
        for _ in range(60000):
            freezer.tick(0.1)
            await hass.async_block_till_done()
            if "Applying future dampening" in caplog.text:
                break
        assert "Adjusted granular dampening factor for 2026-04-04 10:00:00 is 0.804" in caplog.text
        caplog.clear()
        await five_minute_bump(hass, freezer, caplog)
        if (state := hass.states.get(dampening_entity)) is not None:
            assert state.state == "True"
            if (attribute := state.attributes.get("factors")) is not None:
                assert len(attribute) == 48
                assert attribute[20]["factor"] == 0.804
            else:
                pytest.fail("Dampening attribute `factors` is None")
        else:
            pytest.fail("Dampening entity state is None")

        await midnight_utc(hass, freezer, caplog, "2026-04-04 00:00:00")

        freezer.move_to("2026-04-04 14:00:00")
        caplog.clear()
        for _ in range(60000):
            freezer.tick(0.1)
            await hass.async_block_till_done()
            if "Applying future dampening" in caplog.text:
                break
        assert "Adjusted granular dampening factor for 2026-04-05 09:00:00 is 0.804" in caplog.text
        caplog.clear()
        await five_minute_bump(hass, freezer, caplog)
        if (state := hass.states.get(dampening_entity)) is not None:
            assert state.state == "True"
            if (attribute := state.attributes.get("factors")) is not None:
                assert len(attribute) == 48
                assert attribute[18]["factor"] == 0.804
            else:
                pytest.fail("Dampening attribute `factors` is None")
        else:
            pytest.fail("Dampening entity state is None")

        freezer.move_to("2026-04-04 16:00:00")
        caplog.clear()
        await hass.async_block_till_done()
        if (state := hass.states.get(dampening_entity)) is not None:
            assert state.state == "True"
            if (attribute := state.attributes.get("factors")) is not None:
                assert len(attribute) == 48
                assert attribute[18]["factor"] == 0.804
            else:
                pytest.fail("Dampening attribute `factors` is None")
        else:
            pytest.fail("Dampening entity state is None")

    finally:
        assert await async_cleanup_integration_tests(hass)
