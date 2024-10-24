"""Provide info to system health."""

# pylint: disable=C0304, E0401, W0212, W0613

from __future__ import annotations

#import logging
#import traceback
from typing import Any

from homeassistant.components import system_health # type: ignore
from homeassistant.core import HomeAssistant, callback # type: ignore

from .const import SOLCAST_URL # , DOMAIN
#from .coordinator import SolcastUpdateCoordinator

#_LOGGER = logging.getLogger(__name__)

@callback
def async_register(
    hass: HomeAssistant, register: system_health.SystemHealthRegistration
) -> None:
    """Register system health callbacks."""
    register.async_register_info(system_health_info)


async def system_health_info(hass: HomeAssistant) -> dict[str, Any]:
    """Get info for the info page."""
    #for v in hass.data[DOMAIN].values():
    #    if isinstance(v, SolcastUpdateCoordinator):
    #        coordinator: SolcastUpdateCoordinator = v

    return {
        "can_reach_server": system_health.async_check_can_reach_url(hass, SOLCAST_URL),
    }