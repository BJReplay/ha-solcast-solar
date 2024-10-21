"""Support for the Solcast diagnostics."""

# pylint: disable=C0304, E0401

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry # type: ignore
from homeassistant.const import CONF_API_KEY # type: ignore
from homeassistant.core import HomeAssistant # type: ignore

from .const import DOMAIN
from .coordinator import SolcastUpdateCoordinator

TO_REDACT = [
    CONF_API_KEY,
]


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    Args:
        hass (HomeAssistant): The Home Assistant instance.
        entry (ConfigEntry): The integration entry instance, provides access to the coordinator.

    Returns:
        dict[str, Any]: Diagnostic details to include in a download file.
    """
    coordinator: SolcastUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    def hard_limit_set():
        hard_set = False
        for hard_limit in coordinator.solcast.hard_limit.split(','):
            if hard_limit != '100.0':
                hard_set = True
        return hard_set

    return {
        "tz_conversion": coordinator.solcast.options.tz,
        "used_api_requests": coordinator.solcast.get_api_used_count(),
        "api_request_limit": coordinator.solcast.get_api_limit(),
        "rooftop_site_count": len(coordinator.solcast.sites),
        "forecast_hard_limit_set": hard_limit_set(),
        "data": (coordinator.data, TO_REDACT),
        "energy_forecasts_graph": coordinator.solcast.get_energy_data()["wh_hours"],
    }