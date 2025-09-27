"""Tests for the Solcast Solar automated dampening."""

import copy
from datetime import datetime as dt
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

        async def midnight_utc(at: str):
            freezer.move_to(at)
            caplog.clear()
            for _ in range(600):
                freezer.tick(0.1)
                await hass.async_block_till_done()
                if "Updating sensor Third Site" in caplog.text:
                    break

        await midnight_utc("2025-10-03 00:00:00")

        freezer.move_to("2025-10-03 14:00:00")
        caplog.clear()
        for _ in range(24000):
            freezer.tick(0.1)
            await hass.async_block_till_done()
            if "Applying future dampening" in caplog.text:
                break
        assert "Adjusted granular dampening factor for 2025-10-04 09:00:00 is 0.804" in caplog.text

        await midnight_utc("2025-10-04 00:00:00")

        freezer.move_to("2025-10-04 14:00:00")
        caplog.clear()
        for _ in range(24000):
            freezer.tick(0.1)
            await hass.async_block_till_done()
            if "Applying future dampening" in caplog.text:
                break
        assert "Adjusted granular dampening factor for 2025-10-05 10:00:00 is 0.804" in caplog.text

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

        async def midnight_utc(at: str):
            freezer.move_to(at)
            caplog.clear()
            for _ in range(600):
                freezer.tick(0.1)
                await hass.async_block_till_done()
                if "Updating sensor Third Site" in caplog.text:
                    break

        await midnight_utc("2026-04-03 00:00:00")

        freezer.move_to("2026-04-03 14:00:00")
        caplog.clear()
        for _ in range(24000):
            freezer.tick(0.1)
            await hass.async_block_till_done()
            if "Applying future dampening" in caplog.text:
                break
        # assert "Adjusted granular dampening factor for 2026-04-04 10:00:00 is 0.804" in caplog.text

        await midnight_utc("2026-04-04 00:00:00")

        freezer.move_to("2026-04-04 14:00:00")
        caplog.clear()
        for _ in range(24000):
            freezer.tick(0.1)
            await hass.async_block_till_done()
            if "Applying future dampening" in caplog.text:
                break
        assert "Adjusted granular dampening factor for 2026-04-05 09:00:00 is 0.804" in caplog.text

    finally:
        assert await async_cleanup_integration_tests(hass)
