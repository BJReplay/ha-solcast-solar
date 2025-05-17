"""Provide info to system health."""

from __future__ import annotations

from typing import Any

from homeassistant.components import system_health
from homeassistant.core import HomeAssistant, callback

from .const import SOLCAST_URL


@callback
def async_register(hass: HomeAssistant, register: system_health.SystemHealthRegistration) -> None:
    """Register system health callbacks."""
    register.domain = "Solcast Solar"
    register.async_register_info(system_health_info)  # pyright: ignore[reportUnknownMemberType]


async def system_health_info(hass: HomeAssistant) -> dict[str, Any]:
    """Get info for the info page."""

    return {
        "can_reach_server": system_health.async_check_can_reach_url(hass, SOLCAST_URL),
    }
