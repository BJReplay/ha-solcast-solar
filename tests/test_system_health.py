"""Tests for the Solcast Solar diagnostics and system health."""

import logging
from typing import Any

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar.const import DOMAIN
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.solcastapi import SolcastApi
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from . import DEFAULT_INPUT1, async_cleanup_integration_tests, async_init_integration

_LOGGER = logging.getLogger(__name__)

SYSTEM_HEALTH_DOMAIN = "Solcast Solar"


async def get_system_health_info(hass: HomeAssistant, domain: str) -> dict[str, Any]:
    """Get system health info."""
    return await hass.data["system_health"][domain].info_callback(hass)


async def test_system_health(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    # response_mocker: ResponseMocker,
) -> None:
    """Test system health."""

    entry = await async_init_integration(hass, DEFAULT_INPUT1)
    coordinator: SolcastUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    solcast: SolcastApi = coordinator.solcast

    try:
        assert await async_setup_component(hass, "system_health", {})
        await hass.async_block_till_done()

        info = await get_system_health_info(hass, SYSTEM_HEALTH_DOMAIN)
        assert await info["can_reach_server"] == "ok"

    finally:
        assert await async_cleanup_integration_tests(hass, solcast._config_dir)
