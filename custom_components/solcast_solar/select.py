"""Selector to allow users to select the pv_ data field to use for calculations."""

from enum import IntEnum
import logging
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, KEY_ESTIMATE, MANUFACTURER
from .coordinator import SolcastUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class PVEstimateMode(IntEnum):
    """Enumeration of pv forecast estimates.

    ESTIMATE: Use default forecasts
    ESTIMATE10: Use forecasts 10 - cloudier than expected scenario
    ESTIMATE90: Use forecasts 90 - less cloudy than expected scenario
    """

    ESTIMATE = 0
    ESTIMATE10 = 1
    ESTIMATE90 = 2


_MODE_TO_OPTION: dict[PVEstimateMode, str] = {
    PVEstimateMode.ESTIMATE: "estimate",
    PVEstimateMode.ESTIMATE10: "estimate10",
    PVEstimateMode.ESTIMATE90: "estimate90",
}

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
    """Set up a Solcast select.

    Arguments:
        hass (HomeAssistant): The Home Assistant instance.
        entry (ConfigEntry): The integration entry instance, contains the configuration.
        async_add_entities (AddEntitiesCallback): The Home Assistant callback to add entities.

    """
    coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator

    entity = EstimateModeEntity(
        coordinator,
        ESTIMATE_MODE,
        list(_MODE_TO_OPTION.values()),
        coordinator.solcast.options.key_estimate,
        entry,
    )
    async_add_entities([entity])


class EstimateModeEntity(SelectEntity):
    """Entity representing the solcast estimate field to use for calculations."""

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
        """Initialise the sensor.

        Arguments:
            coordinator (SolcastUpdateCoordinator): The integration coordinator instance.
            entity_description (SensorEntityDescription): The details of the entity.
            supported_options (list[str]): All select options available.
            current_option (str): The currently selected option.
            entry (ConfigEntry): The integration entry instance, contains the configuration.

        """

        self.coordinator = coordinator
        self.entity_description = entity_description

        self._entry = entry
        self._attr_unique_id = f"{entity_description.key}"
        self._attr_options = supported_options
        self._attr_current_option = current_option
        self._attr_entity_category = EntityCategory.CONFIG
        self._attributes: dict[str, Any] = {}
        self._attr_extra_state_attributes: dict[str, Any] = {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Solcast PV Forecast",
            manufacturer=MANUFACTURER,
            model="Solcast PV Forecast",
            entry_type=DeviceEntryType.SERVICE,
            sw_version=coordinator.version,
            configuration_url="https://toolkit.solcast.com.au/",
        )

    async def async_select_option(self, option: str) -> None:
        """Change the selected option.

        Arguments:
            option (str): The preferred forecast to use. estimate, estimate10 or estimate90

        """
        self._attr_current_option = option
        self.async_write_ha_state()

        new = {**self._entry.options}
        new[KEY_ESTIMATE] = option

        self.coordinator.hass.config_entries.async_update_entry(self._entry, options=new)
