"""Support for the Solcast diagnostics."""

# pylint: disable=C0304, E0401, W0212

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
        "tz_conversion": coordinator.solcast._tz,
        "used_api_requests": coordinator.solcast.get_api_used_count(),
        "api_request_limit": coordinator.solcast.get_api_limit(),
        "rooftop_site_count": len(coordinator.solcast._sites),
        "forecast_hard_limit_set": coordinator.solcast._hardlimit < 100,
        "data": (coordinator.data, TO_REDACT),
        "energy_history_graph": coordinator._previousenergy,
        "energy_forecasts_graph": coordinator.solcast._dataenergy["wh_hours"],
    }