"""Support for Solcast PV forecast sensors."""

from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass
from enum import Enum

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_CONFIGURATION_URL,
    ATTR_IDENTIFIERS,
    ATTR_MANUFACTURER,
    ATTR_MODEL,
    ATTR_NAME,
    ATTR_SW_VERSION,
    UnitOfEnergy,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ATTR_ENTRY_TYPE, ATTRIBUTION
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
        state_class= SensorStateClass.TOTAL,
    ),
    "peak_w_today": SensorEntityDescription(
        key="peak_w_today",
        translation_key="peak_w_today",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        name="Peak Forecast Today",
        icon="mdi:solar-power",
        suggested_display_precision=0,
        state_class= SensorStateClass.MEASUREMENT,
    ),
    "peak_w_time_today": SensorEntityDescription(
        key="peak_w_time_today",
        translation_key="peak_w_time_today",
        name="Peak Time Today",
        icon="mdi:clock",
        device_class=SensorDeviceClass.TIMESTAMP,
        #suggested_display_precision=0,
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
    "forecast_custom_hour": SensorEntityDescription(
        key="forecast_custom_hour",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        translation_key="forecast_custom_hour",
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
        # suggested_display_precision=0,
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
    ),
    "total_kwh_forecast_d4": SensorEntityDescription(
        key="total_kwh_forecast_d4",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        translation_key="total_kwh_forecast_d4",
        name="Forecast D4",
        icon="mdi:solar-power",
        suggested_display_precision=2,
    ),
    "total_kwh_forecast_d5": SensorEntityDescription(
        key="total_kwh_forecast_d5",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        translation_key="total_kwh_forecast_d5",
        name="Forecast D5",
        icon="mdi:solar-power",
        suggested_display_precision=2,
    ),
    "total_kwh_forecast_d6": SensorEntityDescription(
        key="total_kwh_forecast_d6",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        translation_key="total_kwh_forecast_d6",
        name="Forecast D6",
        icon="mdi:solar-power",
        suggested_display_precision=2,
    ),
    "total_kwh_forecast_d7": SensorEntityDescription(
        key="total_kwh_forecast_d7",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        translation_key="total_kwh_forecast_d7",
        name="Forecast D7",
        icon="mdi:solar-power",
        suggested_display_precision=2,
    ),
    "power_now": SensorEntityDescription(
        key="power_now",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        translation_key="power_now",
        name="Power Now",
        suggested_display_precision=0,
        state_class= SensorStateClass.MEASUREMENT,
    ),
    "power_now_30m": SensorEntityDescription(
        key="power_now_30m",
        translation_key="power_now_30m",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        #name="Power Next 30 Mins",
        suggested_display_precision=0,
    ),
    "power_now_1hr": SensorEntityDescription(
        key="power_now_1hr",
        translation_key="power_now_1hr",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        #name="Power Next Hour",
        suggested_display_precision=0,
    ),
    #"weather_description": SensorEntityDescription(
        #key="weather_description",
        #translation_key="weather_description",
        #icon="mdi:weather-partly-snowy-rainy",
    #),
}

class SensorUpdatePolicy(Enum):
    DEFAULT = 0
    EVERY_TIME_INTERVAL = 1

def getSensorUpdatePolicy(key) -> SensorUpdatePolicy:
    match key:
        case (
            "forecast_this_hour" |
            "forecast_next_hour" |
            "forecast_custom_hour" |
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
) -> None:
    """Set up the Solcast sensor."""

    coordinator: SolcastUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    for sensor_types in SENSORS:
        sen = SolcastSensor(coordinator, SENSORS[sensor_types], entry)
        entities.append(sen)

    for site in coordinator.solcast._sites:
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
    """Representation of a Solcast Sensor device."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SolcastUpdateCoordinator,
        entity_description: SensorEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)

        #doesnt work :()
        if entity_description.key == "forecast_custom_hour":
            self._attr_translation_placeholders = {"forecast_custom_hour": f"{coordinator.solcast._customhoursensor}"}

        self.entity_description = entity_description
        self.coordinator = coordinator
        self.update_policy = getSensorUpdatePolicy(entity_description.key)
        self._attr_unique_id = f"{entity_description.key}"

        self._attributes = {}
        self._attr_extra_state_attributes = {}

        try:
            self._sensor_data = coordinator.get_sensor_value(entity_description.key)
        except Exception as ex:
            _LOGGER.error(
                f"Unable to get sensor value {ex} %s", traceback.format_exc()
            )
            self._sensor_data = None

        if self._sensor_data is None:
            self._attr_available = False
        else:
            self._attr_available = True

        self._attr_device_info = {
            ATTR_IDENTIFIERS: {(DOMAIN, entry.entry_id)},
            ATTR_NAME: "Solcast PV Forecast", #entry.title,
            ATTR_MANUFACTURER: "BJReplay",
            ATTR_MODEL: "Solcast PV Forecast",
            ATTR_ENTRY_TYPE: DeviceEntryType.SERVICE,
            ATTR_SW_VERSION: coordinator._version,
            ATTR_CONFIGURATION_URL: "https://toolkit.solcast.com.au/",
        }


    @property
    def extra_state_attributes(self):
        """Return the state extra attributes of the sensor."""
        try:
            return self.coordinator.get_sensor_extra_attributes(
                self.entity_description.key
            )
        except Exception as ex:
            _LOGGER.error(
                f"Unable to get sensor value {ex} %s", traceback.format_exc()
            )
            return None

    @property
    def native_value(self):
        """Return the value reported by the sensor."""
        return self._sensor_data

    @property
    def should_poll(self) -> bool:
        """Return if the sensor should poll."""
        return False

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""

        # these sensors will pick-up the change on the next interval update (5mins)
        if self.update_policy == SensorUpdatePolicy.EVERY_TIME_INTERVAL and self.coordinator._dataUpdated:
            return

        # these sensors update when the date changed or when there is new data
        if self.update_policy == SensorUpdatePolicy.DEFAULT and not (self.coordinator._dateChanged or self.coordinator._dataUpdated) :
           return

        try:
            self._sensor_data = self.coordinator.get_sensor_value(
                self.entity_description.key
            )
        except Exception as ex:
            _LOGGER.error(
                f"Unable to get sensor value {ex} %s", traceback.format_exc()
            )
            self._sensor_data = None

        if self._sensor_data is None:
            self._attr_available = False
        else:
            self._attr_available = True

        self.async_write_ha_state()

@dataclass
class RooftopSensorEntityDescription(SensorEntityDescription):
    rooftop_id: str | None = None

class RooftopSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Solcast Sensor device."""

    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        *,
        key: str,
        coordinator: SolcastUpdateCoordinator,
        entity_description: SensorEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)

        self.key = key
        self.coordinator = coordinator
        self.entity_description = entity_description
        self.rooftop_id = entity_description.rooftop_id

        self._attributes = {}
        self._attr_extra_state_attributes = {}
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

        try:
            self._sensor_data = coordinator.get_site_sensor_value(self.rooftop_id, key)
        except Exception as ex:
            _LOGGER.error(
                f"Unable to get sensor value {ex} %s", traceback.format_exc()
            )
            self._sensor_data = None

        self._attr_device_info = {
            ATTR_IDENTIFIERS: {(DOMAIN, entry.entry_id)},
            ATTR_NAME: "Solcast PV Forecast", #entry.title,
            ATTR_MANUFACTURER: "BJReplay",
            ATTR_MODEL: "Solcast PV Forecast",
            ATTR_ENTRY_TYPE: DeviceEntryType.SERVICE,
            ATTR_SW_VERSION: coordinator._version,
            ATTR_CONFIGURATION_URL: "https://toolkit.solcast.com.au/",
        }

        self._unique_id = f"solcast_api_{entity_description.name}"

    @property
    def name(self):
        """Return the name of the device."""
        return f"{self.entity_description.name}"

    @property
    def friendly_name(self):
        """Return the name of the device."""
        return self.entity_description.name

    @property
    def unique_id(self):
        """Return the unique ID of the sensor."""
        return f"solcast_{self._unique_id}"

    @property
    def extra_state_attributes(self):
        """Return the state extra attributes of the sensor."""
        try:
            return self.coordinator.get_site_sensor_extra_attributes(
                self.rooftop_id,
                self.key,
            )
        except Exception as ex:
            _LOGGER.error(
                f"Unable to get sensor value {ex} %s", traceback.format_exc()
            )
            return None

    @property
    def native_value(self):
        """Return the value reported by the sensor."""
        return self._sensor_data

    @property
    def should_poll(self) -> bool:
        """Return if the sensor should poll."""
        return False

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        try:
            self._sensor_data = self.coordinator.get_site_sensor_value(
                self.rooftop_id,
                self.key,
            )
        except Exception as ex:
            _LOGGER.error(
                f"Unable to get sensor value {ex} %s", traceback.format_exc()
            )
            self._sensor_data = None
        self.async_write_ha_state()