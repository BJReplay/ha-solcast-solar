"""Support for Solcast PV forecast sensors."""

# pylint: disable=C0304, E0401, W0718

from __future__ import annotations

from typing import Any, Dict
from datetime import datetime as dt

import logging
import traceback
from dataclasses import dataclass
from enum import Enum

from homeassistant.components.sensor import ( # type: ignore
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry # type: ignore
from homeassistant.const import ( # type: ignore
    ATTR_CONFIGURATION_URL,
    ATTR_IDENTIFIERS,
    ATTR_MANUFACTURER,
    ATTR_MODEL,
    ATTR_NAME,
    ATTR_SW_VERSION,
    #MATCH_ALL,
    UnitOfEnergy,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant, callback # type: ignore
from homeassistant.helpers.device_registry import DeviceEntryType # type: ignore
from homeassistant.helpers.entity import EntityCategory # type: ignore
from homeassistant.helpers.entity_platform import AddEntitiesCallback # type: ignore
from homeassistant.helpers.update_coordinator import CoordinatorEntity # type: ignore

from .const import (
    ATTR_ENTRY_TYPE,
    ATTRIBUTION,
    DOMAIN,
    MANUFACTURER,
)
from .coordinator import SolcastUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

SENSORS: dict[str, SensorEntityDescription] = {
    "total_kwh_forecast_today": SensorEntityDescription(
        key="total_kwh_forecast_today",
        translation_key="total_kwh_forecast_today",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        name="Forecast Today",
        icon="mdi:solar-power",
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL,
    ),
    "peak_w_today": SensorEntityDescription(
        key="peak_w_today",
        translation_key="peak_w_today",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        name="Peak Forecast Today",
        icon="mdi:solar-power",
        suggested_display_precision=0,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "peak_w_time_today": SensorEntityDescription(
        key="peak_w_time_today",
        translation_key="peak_w_time_today",
        name="Peak Time Today",
        icon="mdi:clock",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    "forecast_this_hour": SensorEntityDescription(
        key="forecast_this_hour",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        translation_key="forecast_this_hour",
        name="Forecast This Hour",
        icon="mdi:solar-power",
        suggested_display_precision=0,
    ),
    "forecast_remaining_today": SensorEntityDescription(
        key="get_remaining_today",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        translation_key="get_remaining_today",
        name="Forecast Remaining Today",
        icon="mdi:solar-power",
        suggested_display_precision=2,
    ),
    "forecast_next_hour": SensorEntityDescription(
        key="forecast_next_hour",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        translation_key="forecast_next_hour",
        name="Forecast Next Hour",
        icon="mdi:solar-power",
        suggested_display_precision=0,
    ),
    "forecast_custom_hours": SensorEntityDescription(
        key="forecast_custom_hours",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        translation_key="forecast_custom_hours",
        name="Forecast Custom Hours",
        icon="mdi:solar-power",
        suggested_display_precision=0,
    ),
    "total_kwh_forecast_tomorrow": SensorEntityDescription(
        key="total_kwh_forecast_tomorrow",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        translation_key="total_kwh_forecast_tomorrow",
        name="Forecast Tomorrow",
        icon="mdi:solar-power",
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL,
    ),
    "peak_w_tomorrow": SensorEntityDescription(
        key="peak_w_tomorrow",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        translation_key="peak_w_tomorrow",
        name="Peak Forecast Tomorrow",
        icon="mdi:solar-power",
        suggested_display_precision=0,
    ),
    "peak_w_time_tomorrow": SensorEntityDescription(
        key="peak_w_time_tomorrow",
        translation_key="peak_w_time_tomorrow",
        name="Peak Time Tomorrow",
        icon="mdi:clock",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    "api_counter": SensorEntityDescription(
        key="api_counter",
        translation_key="api_counter",
        name="API Used",
        icon="mdi:web-check",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "api_limit": SensorEntityDescription(
        key="api_limit",
        translation_key="api_limit",
        name="API Limit",
        icon="mdi:web-check",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "lastupdated": SensorEntityDescription(
        key="lastupdated",
        device_class=SensorDeviceClass.TIMESTAMP,
        translation_key="lastupdated",
        name="API Last Polled",
        icon="mdi:clock",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "hard_limit": SensorEntityDescription(
        key="hard_limit",
        translation_key="hard_limit",
        name="Hard Limit Set",
        icon="mdi:speedometer",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "total_kwh_forecast_d3": SensorEntityDescription(
        key="total_kwh_forecast_d3",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        translation_key="total_kwh_forecast_d3",
        name="Forecast D3",
        icon="mdi:solar-power",
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL,
    ),
    "total_kwh_forecast_d4": SensorEntityDescription(
        key="total_kwh_forecast_d4",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        translation_key="total_kwh_forecast_d4",
        name="Forecast D4",
        icon="mdi:solar-power",
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL,
    ),
    "total_kwh_forecast_d5": SensorEntityDescription(
        key="total_kwh_forecast_d5",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        translation_key="total_kwh_forecast_d5",
        name="Forecast D5",
        icon="mdi:solar-power",
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL,
    ),
    "total_kwh_forecast_d6": SensorEntityDescription(
        key="total_kwh_forecast_d6",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        translation_key="total_kwh_forecast_d6",
        name="Forecast D6",
        icon="mdi:solar-power",
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL,
    ),
    "total_kwh_forecast_d7": SensorEntityDescription(
        key="total_kwh_forecast_d7",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        translation_key="total_kwh_forecast_d7",
        name="Forecast D7",
        icon="mdi:solar-power",
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL,
    ),
    "power_now": SensorEntityDescription(
        key="power_now",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        translation_key="power_now",
        name="Power Now",
        suggested_display_precision=0,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "power_now_30m": SensorEntityDescription(
        key="power_now_30m",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        translation_key="power_now_30m",
        #name="Power in 30 Minutes",
        suggested_display_precision=0,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "power_now_1hr": SensorEntityDescription(
        key="power_now_1hr",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        translation_key="power_now_1hr",
        #name="Power in 1 Hour",
        suggested_display_precision=0,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    #"weather_description": SensorEntityDescription(
        #key="weather_description",
        #translation_key="weather_description",
        #icon="mdi:weather-partly-snowy-rainy",
    #),
}

class SensorUpdatePolicy(Enum):
    """Sensor update policy"""
    DEFAULT = 0
    EVERY_TIME_INTERVAL = 1

def get_sensor_update_policy(key: str) -> SensorUpdatePolicy:
    """Get the sensor update policy.

    Many sensors update every five minutes (EVERY_TIME_INTERVAL), while others only update on startup or forecast fetch.

    Arguments:
        key (str): The sensor name.

    Returns:
        SensorUpdatePolicy: The update policy.
    """
    match key:
        case (
            "forecast_this_hour" |
            "forecast_next_hour" |
            "forecast_custom_hours" |
            "forecast_remaining_today" |
            "get_remaining_today" |
            "power_now" |
            "power_now_30m" |
            "power_now_1hr"
            ):
            return SensorUpdatePolicy.EVERY_TIME_INTERVAL
        case _:
            return SensorUpdatePolicy.DEFAULT

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up a Solcast sensor.

    Arguments:
        hass (HomeAssistant): The Home Assistant instance.
        entry (ConfigEntry): The integration entry instance, contains the configuration.
        async_add_entities (AddEntitiesCallback): The Home Assistant callback to add entities.
    """

    coordinator: SolcastUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    for sensor_types, _ in SENSORS.items():
        sen = SolcastSensor(coordinator, SENSORS[sensor_types], entry)
        entities.append(sen)

    for site in coordinator.get_solcast_sites():
        k = RooftopSensorEntityDescription(
                key=site["resource_id"],
                name=site["name"],
                icon="mdi:home",
                device_class=SensorDeviceClass.ENERGY,
                native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                suggested_display_precision=2,
                rooftop_id=site["resource_id"],
            )
        sen = RooftopSensor(
            key="site_data",
            coordinator=coordinator,
            entity_description=k,
            entry=entry,
        )

        entities.append(sen)

    async_add_entities(entities)

class SolcastSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Solcast sensor device."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    #_unrecorded_attributes = frozenset({MATCH_ALL}) # Large attributes now excluded dynamically in async_added_to_hass()

    def __init__(
        self,
        coordinator: SolcastUpdateCoordinator,
        entity_description: SensorEntityDescription,
        entry: ConfigEntry,
    ):
        """Initialise the sensor.

        Arguments:
            coordinator (SolcastUpdateCoordinator): The integration coordinator instance.
            entity_description (SensorEntityDescription): The details of the entity.
            entry (ConfigEntry): The integration entry instance, contains the configuration.
        """
        super().__init__(coordinator)

        # No longer used. Was used to alter the custom X hour sensor friendly name.
        #if entity_description.key == "forecast_custom_hours":
        #    self._attr_translation_placeholders = {"forecast_custom_hours": f"{coordinator.solcast.custom_hour_sensor}"}

        self.entity_description = entity_description
        self._coordinator = coordinator
        self._update_policy = get_sensor_update_policy(entity_description.key)
        self._attr_unique_id = f"{entity_description.key}"
        self._attributes = {}
        self._attr_extra_state_attributes = {}

        try:
            self._sensor_data = self._coordinator.get_sensor_value(entity_description.key)
        except Exception as e:
            _LOGGER.error("Unable to get sensor value: %s: %s", e, traceback.format_exc())
            self._sensor_data = None

        if self._sensor_data is None:
            self._attr_available = False
        else:
            self._attr_available = True

        self._attr_device_info = {
            ATTR_IDENTIFIERS: {(DOMAIN, entry.entry_id)},
            ATTR_NAME: "Solcast PV Forecast", #entry.title,
            ATTR_MANUFACTURER: MANUFACTURER,
            ATTR_MODEL: "Solcast PV Forecast",
            ATTR_ENTRY_TYPE: DeviceEntryType.SERVICE,
            ATTR_SW_VERSION: coordinator._version,
            ATTR_CONFIGURATION_URL: "https://toolkit.solcast.com.au/",
        }

    async def async_added_to_hass(self):
        """Entity about to be added to hass, so set recorder excluded attributes."""
        await super().async_added_to_hass()
        try:
            if (
                self.entity_id.startswith('sensor.solcast_pv_forecast_forecast_today') or
                self.entity_id.startswith('sensor.solcast_pv_forecast_forecast_tomorrow') or
                self.entity_id.startswith('sensor.solcast_pv_forecast_forecast_day')
            ):
                exclude = ['detailedForecast', 'detailedHourly']
                if self._coordinator.solcast.options.attr_brk_site_detailed:
                    for s in self._coordinator.solcast.sites:
                        exclude.append('detailedForecast-' + s['resource_id'])
                        exclude.append('detailedHourly-' + s['resource_id'])
                self._state_info["unrecorded_attributes"] = self._state_info["unrecorded_attributes"] | frozenset(exclude)
        except Exception as e:
            _LOGGER.error("Exception setting excluded attributes: %s", e)
            _LOGGER.error(traceback.format_exc())

    @property
    def extra_state_attributes(self) -> (Dict[str, Any] | None):
        """Return the state extra attributes of the sensor.

        Returns:
            Dict[str, Any] | None: The current attributes of a sensor.
        """
        try:
            return self._coordinator.get_sensor_extra_attributes(self.entity_description.key)
        except Exception as e:
            _LOGGER.error("Unable to get sensor value: %s: %s", e, traceback.format_exc())
            return None

    @property
    def native_value(self) -> (int | dt | float | Any | str | bool | None):
        """Return the current value of the sensor.

        Returns:
            int | dt | float | Any | str | bool | None: The current value of a sensor.
        """
        return self._sensor_data

    @property
    def should_poll(self) -> bool:
        """Return whether the sensor should poll.

        Returns:
            bool: Always returns False, as sensors are not polled.
        """
        return False

    @callback
    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator.

        Some sensors are updated periodically every five minutes (those with an update policy of
        SensorUpdatePolicy.EVERY_TIME_INTERVAL), while the remaining sensors update after each
        forecast update or when the date changes.
        """

        if self._update_policy == SensorUpdatePolicy.DEFAULT and not (self._coordinator.get_date_changed() or self._coordinator.get_data_updated()) :
            return

        try:
            self._sensor_data = self._coordinator.get_sensor_value(self.entity_description.key)
        except Exception as e:
            _LOGGER.error("Unable to get sensor value: %s: %s", e, traceback.format_exc())
            self._sensor_data = None

        if self._sensor_data is None:
            self._attr_available = False
        else:
            self._attr_available = True

        self.async_write_ha_state()

@dataclass
class RooftopSensorEntityDescription(SensorEntityDescription):
    """Representation of a rooftop entity description."""
    key: str | None = None
    name: str | None = None
    icon: str | None = None
    device_class: SensorDeviceClass = SensorDeviceClass.ENERGY
    native_unit_of_measurement: UnitOfEnergy = UnitOfEnergy.KILO_WATT_HOUR
    suggested_display_precision: int = 2
    rooftop_id: str | None = None

class RooftopSensor(CoordinatorEntity, SensorEntity):
    """Representation of a rooftop sensor device."""

    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        *,
        key: str,
        coordinator: SolcastUpdateCoordinator,
        entity_description: SensorEntityDescription,
        entry: ConfigEntry,
    ):
        """Initialise the sensor.

        Arguments:
            key (str): The sensor name.
            coordinator (SolcastUpdateCoordinator): The integration coordinator instance.
            entity_description (SensorEntityDescription): The details of the entity.
            entry (ConfigEntry): The integration entry instance, contains the configuration.
        """
        super().__init__(coordinator)

        self.entity_description = entity_description
        self._key = key
        self._coordinator = coordinator
        self._rooftop_id = entity_description.rooftop_id
        self._attributes = {}
        self._attr_extra_state_attributes = {}
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

        try:
            self._sensor_data = coordinator.get_site_sensor_value(self._rooftop_id, key)
        except Exception as e:
            _LOGGER.error("Unable to get sensor value: %s: %s", e, traceback.format_exc())
            self._sensor_data = None

        self._attr_device_info = {
            ATTR_IDENTIFIERS: {(DOMAIN, entry.entry_id)},
            ATTR_NAME: "Solcast PV Forecast",
            ATTR_MANUFACTURER: MANUFACTURER,
            ATTR_MODEL: "Solcast PV Forecast",
            ATTR_ENTRY_TYPE: DeviceEntryType.SERVICE,
            ATTR_SW_VERSION: coordinator._version,
            ATTR_CONFIGURATION_URL: "https://toolkit.solcast.com.au/",
        }

        self._unique_id = f"solcast_api_{entity_description.name}"

    @property
    def name(self):
        """Return the name of the device.

        Returns:
            str: The device name.
        """
        return f"{self.entity_description.name}"

    @property
    def friendly_name(self):
        """Return the friendly name of the device.

        Returns:
            str: The device friendly name, which is the same as device name.
        """
        return self.entity_description.name

    @property
    def unique_id(self):
        """Return the unique ID of the sensor.

        Returns:
            str: Unique ID.
        """
        return f"solcast_{self._unique_id}"

    @property
    def extra_state_attributes(self):
        """Return the state extra attributes of the sensor.
        """
        try:
            return self._coordinator.get_site_sensor_extra_attributes(self._rooftop_id, self._key )
        except Exception as e:
            _LOGGER.error("Unable to get sensor attributes: %s: %s", e, traceback.format_exc())
            return None

    @property
    def native_value(self) -> (int | dt | float | Any | str | bool | None):
        """Return the current value of the sensor.

        Returns:
            int | dt | float | Any | str | bool | None: The current value of a sensor.
        """
        return self._sensor_data

    @property
    def should_poll(self) -> bool:
        """Return whether the sensor should poll.

        Returns:
            bool: Always returns False, as sensors are not polled.
        """
        return False

    async def async_added_to_hass(self):
        """Called when an entity is added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(self._coordinator.async_add_listener(self._handle_coordinator_update))

    @callback
    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        try:
            self._sensor_data = self._coordinator.get_site_sensor_value(self._rooftop_id, self._key)
        except Exception as e:
            _LOGGER.error("Unable to get sensor value: %s: %s", e, traceback.format_exc())
            self._sensor_data = None
        self.async_write_ha_state()