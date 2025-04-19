"""Support for the Solcast diagnostics."""

from __future__ import annotations

from typing import Any, Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from .coordinator import SolcastUpdateCoordinator

TO_REDACT: Final = [
    CONF_API_KEY,
]


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    Args:
        hass (HomeAssistant): The Home Assistant instance.
        entry (ConfigEntry): The integration entry instance, provides access to the coordinator.

    Returns:
        dict[str, Any]: Diagnostic details to include in a download file.

    """
    coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator

    def hard_limit_set():
        hard_set = False
        for hard_limit in coordinator.solcast.hard_limit.split(","):
            if hard_limit != "100.0":
                hard_set = True
        return hard_set

    energy_data = coordinator.solcast.get_energy_data()

    return {
        "tz_conversion": coordinator.solcast.options.tz,
        "used_api_requests": coordinator.solcast.get_api_used_count(),
        "api_request_limit": coordinator.solcast.get_api_limit(),
        "rooftop_site_count": len(coordinator.solcast.sites),
        "forecast_hard_limit_set": hard_limit_set(),
        "data": (coordinator.data, TO_REDACT),
        "energy_forecasts_graph": energy_data["wh_hours"] if energy_data is not None else {},
    }
