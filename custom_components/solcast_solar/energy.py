"""Energy platform."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import SolcastUpdateCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_get_solar_forecast(hass: HomeAssistant, config_entry_id: str) -> dict[str, Any] | None:
    """Get solar forecast for a config entry ID.

    Arguments:
        hass (HomeAssistant): The Home Assistant instance.
        config_entry_id (str): The integration entry ID.

    Returns:
        dict[str, Any] | None: The Energy Dashboard compatible forecast data

    """

    if not hass.data.get(DOMAIN):
        _LOGGER.warning("Domain %s is not yet available to provide forecast data", DOMAIN)
        return None

    entry: ConfigEntry | None = hass.config_entries.async_get_entry(config_entry_id)
    if (
        entry is None
        or (coordinator := entry.runtime_data.coordinator) is None
        or not isinstance(entry.runtime_data.coordinator, SolcastUpdateCoordinator)
    ):
        return None

    return coordinator.get_energy_tab_data()
