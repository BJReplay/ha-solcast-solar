"""Support for the Solcast diagnostics."""

# pylint: disable=C0304, E0401

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import SolcastUpdateCoordinator

TO_REDACT = [
    CONF_API_KEY,
]


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: SolcastUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    return {
        "tz_conversion": coordinator.solcast.options.tz,
        "used_api_requests": coordinator.solcast.get_api_used_count(),
        "api_request_limit": coordinator.solcast.get_api_limit(),
        "rooftop_site_count": len(coordinator.solcast.sites),
        "forecast_hard_limit_set": coordinator.solcast.hard_limit < 100,
        "data": (coordinator.data, TO_REDACT),
        "energy_history_graph": coordinator.get_previousenergy(),
        "energy_forecasts_graph": coordinator.solcast.get_energy_data()["wh_hours"],
    }