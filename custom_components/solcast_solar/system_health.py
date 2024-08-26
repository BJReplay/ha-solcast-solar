"""Provide info to system health."""

# pylint: disable=C0304, E0401, W0212, W0613

from __future__ import annotations

from typing import Any

from homeassistant.components import system_health
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, SOLCAST_URL
from .coordinator import SolcastUpdateCoordinator


@callback
def async_register(
    hass: HomeAssistant, register: system_health.SystemHealthRegistration
) -> None:
    """Register system health callbacks."""
    register.async_register_info(system_health_info)


async def system_health_info(hass: HomeAssistant) -> dict[str, Any]:
    """Get info for the info page."""
    coordinator: SolcastUpdateCoordinator =list(hass.data[DOMAIN].values())[0]
    used_requests = coordinator.solcast.get_api_used_count()

    return {
        "can_reach_server": system_health.async_check_can_reach_url(hass, SOLCAST_URL),
        "used_requests": used_requests,
        "rooftop_site_count": len(coordinator.solcast._sites),
    }