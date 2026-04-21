"""Solcast diagnostics."""

from __future__ import annotations

from typing import Any, Final

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from .actions import build_health_check_report
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
    energy_data = coordinator.solcast.query.get_energy_data()
    health_check = build_health_check_report(hass, coordinator, coordinator.solcast)

    return {
        "tz_conversion": coordinator.solcast.options.tz,
        "rooftop_site_count": len(coordinator.solcast.sites),
        "health_check": async_redact_data(health_check, TO_REDACT),
        "data": async_redact_data(coordinator.data, TO_REDACT),
        "energy_forecasts_graph": energy_data["wh_hours"] if energy_data is not None else {},
    }
