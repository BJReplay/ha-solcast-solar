"""Solcast energy platform."""

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import SolcastUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_get_solar_forecast(hass: HomeAssistant, config_entry_id: str) -> dict[str, Any] | None:
    """Get solar forecast for a config entry ID.

    Arguments:
        hass (HomeAssistant): The Home Assistant instance.
        config_entry_id (str): The integration entry ID.

    Returns:
        dict[str, Any] | None: The Energy Dashboard compatible forecast data

    """

    entry: ConfigEntry | None = hass.config_entries.async_get_entry(config_entry_id)
    runtime_data = getattr(entry, "runtime_data", None) if entry is not None else None
    coordinator = getattr(runtime_data, "coordinator", None)
    if entry is None or coordinator is None or not isinstance(coordinator, SolcastUpdateCoordinator):
        return None

    return coordinator.solcast.query.get_energy_data()
