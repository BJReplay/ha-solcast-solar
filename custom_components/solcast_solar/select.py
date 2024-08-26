"""Selector to allow users to select the pv_ data field to use for calcualtions."""

# pylint: disable=C0304, E0401, W0212

import logging

from enum import IntEnum

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.const import (
    EntityCategory,
    ATTR_CONFIGURATION_URL,
    ATTR_IDENTIFIERS,
    ATTR_MANUFACTURER,
    ATTR_MODEL,
    ATTR_NAME,
    ATTR_SW_VERSION,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ATTRIBUTION, DOMAIN, KEY_ESTIMATE, ATTR_ENTRY_TYPE
from .coordinator import SolcastUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class PVEstimateMode(IntEnum):
    """
    Enumeration of pv forecasts kinds.

    Possible values are:
    ESTIMATE - Default forecasts
    ESTIMATE10 = Forecasts 10 - cloudier than expected scenario
    ESTIMATE90 = Forecasts 90 - less cloudy than expected scenario
    """

    ESTIMATE = 0
    ESTIMATE10 = 1
    ESTIMATE90 = 2


_MODE_TO_OPTION: dict[PVEstimateMode, str] = {
    PVEstimateMode.ESTIMATE: "estimate",
    PVEstimateMode.ESTIMATE10: "estimate10",
    PVEstimateMode.ESTIMATE90: "estimate90",
}

# _OPTION_TO_MODE: dict[str, PVEstimateMode] = {
#     value: key for key, value in _MODE_TO_OPTION.items()
# }

ESTIMATE_MODE = SelectEntityDescription(
    key="estimate_mode",
    icon="mdi:sun-angle",
    entity_category=EntityCategory.CONFIG,
    translation_key="estimate_mode",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Setup entry"""
    coordinator: SolcastUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    try:
        est_mode = coordinator.solcast.options.key_estimate
    except ValueError:
        _LOGGER.debug("Could not read estimate mode", exc_info=True)
    else:
        entity = EstimateModeEntity(
            coordinator,
            ESTIMATE_MODE,
            [v for k, v in _MODE_TO_OPTION.items()],
            est_mode,
            entry,
        )
        async_add_entities([entity])


class EstimateModeEntity(SelectEntity):
    """Entity representing the solcast estimate field to use for calculations."""

    _attr_attribution = ATTRIBUTION
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SolcastUpdateCoordinator,
        entity_description: SelectEntityDescription,
        supported_options: list[str],
        current_option: str,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""

        self.coordinator = coordinator
        self._entry = entry

        self.entity_description = entity_description
        self._attr_unique_id = f"{entity_description.key}"

        self._attr_options = supported_options
        self._attr_current_option = current_option

        self._attr_entity_category = EntityCategory.CONFIG

        self._attributes = {}
        self._attr_extra_state_attributes = {}

        self._attr_device_info = {
            ATTR_IDENTIFIERS: {(DOMAIN, entry.entry_id)},
            ATTR_NAME: "Solcast PV Forecast",
            ATTR_MANUFACTURER: "BJReplay",
            ATTR_MODEL: "Solcast PV Forecast",
            ATTR_ENTRY_TYPE: DeviceEntryType.SERVICE,
            ATTR_SW_VERSION: coordinator._version,
            ATTR_CONFIGURATION_URL: "https://toolkit.solcast.com.au/",
        }

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self._attr_current_option = option
        self.async_write_ha_state()

        new = {**self._entry.options}
        new[KEY_ESTIMATE] = option

        self.coordinator._hass.config_entries.async_update_entry(self._entry, options=new)