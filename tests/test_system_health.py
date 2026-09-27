"""Tests for the Solcast Solar diagnostics and system health."""

import logging

from freezegun.api import FrozenDateTimeFactory

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from . import DEFAULT_INPUT1, async_cleanup_integration_tests, async_init_integration

from tests.common import get_system_health_info

_LOGGER = logging.getLogger(__name__)

SYSTEM_HEALTH_DOMAIN = DOMAIN


async def test_system_health(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test system health."""

    await async_init_integration(hass, DEFAULT_INPUT1)

    try:
        assert await async_setup_component(hass, "system_health", {}), "system_health component setup failed"
        await hass.async_block_till_done()

        info = await get_system_health_info(hass, SYSTEM_HEALTH_DOMAIN)
        assert await info["can_reach_server"] == "ok"

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"
