"""Support for Solcast PV forecast sensors."""

from __future__ import annotations

from datetime import datetime as dt
from enum import Enum
import logging
import traceback
from typing import Any

from propcache.api import cached_property

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTRIBUTION,
    DOMAIN,
    FORECAST_DAY_SENSORS,
    MANUFACTURER,
    SENSOR_UPDATE_LOGGING,
)
from .coordinator import SolcastUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

SENSORS: dict[str, dict[str, Any]] = {
    "api_counter": {
        "description": SensorEntityDescription(
            key="api_counter",
            translation_key="api_counter",
            name="API Used",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        "attribution": False,
    },
    "api_limit": {
        "description": SensorEntityDescription(
            key="api_limit",
            translation_key="api_limit",
            name="API Limit",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        "attribution": False,
    },
    "dampen": {
        "description": SensorEntityDescription(
            key="dampen",
            translation_key="dampen",
            name="Dampening",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        "attribution": False,
        "enabled_by_default": False,
    },
    "forecast_this_hour": {
        "description": SensorEntityDescription(
            key="forecast_this_hour",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
            translation_key="forecast_this_hour",
            name="Forecast This Hour",
            suggested_display_precision=0,
        )
    },
    "forecast_custom_hours": {
        "description": SensorEntityDescription(
            key="forecast_custom_hours",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
            translation_key="forecast_custom_hours",
            name="Forecast Custom Hours",
            suggested_display_precision=0,
        ),
        "enabled_by_default": False,
    },
    "forecast_next_hour": {
        "description": SensorEntityDescription(
            key="forecast_next_hour",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
            translation_key="forecast_next_hour",
            name="Forecast Next Hour",
            suggested_display_precision=0,
        )
    },
    "forecast_remaining_today": {
        "description": SensorEntityDescription(
            key="get_remaining_today",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            translation_key="get_remaining_today",
            name="Forecast Remaining Today",
            suggested_display_precision=2,
        )
    },
    "lastupdated": {
        "description": SensorEntityDescription(
            key="lastupdated",
            device_class=SensorDeviceClass.TIMESTAMP,
            translation_key="lastupdated",
            name="API Last Polled",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        "attribution": False,
    },
    "peak_w_time_today": {
        "description": SensorEntityDescription(
            key="peak_w_time_today",
            translation_key="peak_w_time_today",
            name="Peak Time Today",
            device_class=SensorDeviceClass.TIMESTAMP,
        )
    },
    "peak_w_time_tomorrow": {
        "description": SensorEntityDescription(
            key="peak_w_time_tomorrow",
            translation_key="peak_w_time_tomorrow",
            name="Peak Time Tomorrow",
            device_class=SensorDeviceClass.TIMESTAMP,
        )
    },
    "peak_w_today": {
        "description": SensorEntityDescription(
            key="peak_w_today",
            translation_key="peak_w_today",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.WATT,
            name="Peak Forecast Today",
            suggested_display_precision=0,
            state_class=SensorStateClass.MEASUREMENT,
        )
    },
    "peak_w_tomorrow": {
        "description": SensorEntityDescription(
            key="peak_w_tomorrow",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.WATT,
            translation_key="peak_w_tomorrow",
            name="Peak Forecast Tomorrow",
            suggested_display_precision=0,
        )
    },
    "power_now": {
        "description": SensorEntityDescription(
            key="power_now",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.WATT,
            translation_key="power_now",
            name="Power Now",
            suggested_display_precision=0,
            state_class=SensorStateClass.MEASUREMENT,
        )
    },
    "power_now_1hr": {
        "description": SensorEntityDescription(
            key="power_now_1hr",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.WATT,
            translation_key="power_now_1hr",
            name="Power in 1 Hour",
            suggested_display_precision=0,
            state_class=SensorStateClass.MEASUREMENT,
        )
    },
    "power_now_30m": {
        "description": SensorEntityDescription(
            key="power_now_30m",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.WATT,
            translation_key="power_now_30m",
            name="Power in 30 Minutes",
            suggested_display_precision=0,
            state_class=SensorStateClass.MEASUREMENT,
        )
    },
    "total_kwh_forecast_today": {
        "description": SensorEntityDescription(
            key="total_kwh_forecast_today",
            translation_key="total_kwh_forecast_today",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            name="Forecast Today",
            suggested_display_precision=2,
            state_class=SensorStateClass.TOTAL,
        )
    },
    "total_kwh_forecast_tomorrow": {
        "description": SensorEntityDescription(
            key="total_kwh_forecast_tomorrow",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            translation_key="total_kwh_forecast_tomorrow",
            name="Forecast Tomorrow",
            suggested_display_precision=2,
            state_class=SensorStateClass.TOTAL,
        )
    },
}


class SensorUpdatePolicy(Enum):
    """Sensor update policy."""

    DEFAULT = 0
    EVERY_TIME_INTERVAL = 1


def get_sensor_update_policy(key: str) -> SensorUpdatePolicy:
    """Get the sensor update policy.

    Some sensors update every five minutes (EVERY_TIME_INTERVAL), while others only update on startup or forecast fetch.

    Arguments:
        key (str): The sensor key.

    Returns:
        SensorUpdatePolicy: The update policy.

    """
    if key in (
        "dampen",
        "forecast_this_hour",
        "forecast_next_hour",
        "forecast_custom_hours",
        "forecast_remaining_today",
        "get_remaining_today",
        "power_now",
        "power_now_30m",
        "power_now_1hr",
    ):
        return SensorUpdatePolicy.EVERY_TIME_INTERVAL
    return SensorUpdatePolicy.DEFAULT


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a Solcast sensor.

    Arguments:
        hass (HomeAssistant): The Home Assistant instance.
        entry (ConfigEntry): The integration entry instance, contains the configuration.
        async_add_entities (AddEntitiesCallback): The Home Assistant callback to add entities.

    """

    coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator
    entities: list[RooftopSensor | SolcastSensor] = []

    for sensor in SENSORS.values():
        sen = SolcastSensor(
            coordinator,
            entry,
            sensor,
        )
        entities.append(sen)
    for forecast_day in range(3, FORECAST_DAY_SENSORS):
        sen = SolcastSensor(
            coordinator,
            entry,
            {
                "description": SensorEntityDescription(
                    key=f"total_kwh_forecast_d{forecast_day}",
                    device_class=SensorDeviceClass.ENERGY,
                    native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                    translation_key=f"total_kwh_forecast_d{forecast_day}",
                    name=f"Forecast D{forecast_day}",
                    suggested_display_precision=2,
                    state_class=SensorStateClass.TOTAL,
                ),
                "enabled_by_default": False,
            },
        )
        entities.append(sen)

    hard_limits = coordinator.solcast.options.hard_limit.split(",")
    if len(hard_limits) == 1:
        k = {
            "description": SensorEntityDescription(
                key="hard_limit",
                translation_key="hard_limit",
                name="Hard Limit Set",
                entity_category=EntityCategory.DIAGNOSTIC,
            )
        }
        sen = SolcastSensor(coordinator, entry, k)
        entities.append(sen)
        expecting_limits = ["hard_limit"]
    else:
        for api_key in coordinator.solcast.options.api_key.split(","):
            k = {
                "description": SensorEntityDescription(
                    key="hard_limit_" + api_key[-6:],
                    translation_key="hard_limit_api",
                    translation_placeholders={
                        "api_key": "*" * 6 + api_key[-6:],
                    },
                    entity_category=EntityCategory.DIAGNOSTIC,
                )
            }
            sen = SolcastSensor(coordinator, entry, k)
            entities.append(sen)
        expecting_limits = [f"hard_limit_{api_key[-6:]}" for api_key in coordinator.solcast.options.api_key.split(",")]

    # Clean up.
    entity_registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        # Clean up orphaned hard limit sensors.
        if "hard_limit" in entity.unique_id and entity.unique_id not in expecting_limits:
            entity_registry.async_remove(entity.entity_id)
            _LOGGER.warning("Cleaning up orphaned %s", entity.entity_id)

        # Clean up any orphaned day sensors.
        if entity.translation_key is not None:
            if (
                entity.translation_key.startswith("total_kwh_forecast_d")
                and int(entity.unique_id.split("_")[-1].split("d")[-1]) > FORECAST_DAY_SENSORS - 1
            ):
                entity_registry.async_remove(entity.entity_id)
                _LOGGER.warning("Cleaning up orphaned %s", entity.entity_id)

    # Site sensors
    for site in coordinator.get_solcast_sites():
        k = {
            "description": SensorEntityDescription(
                key=site["resource_id"],
                translation_key="site_data",
                name=site["name"],
                device_class=SensorDeviceClass.ENERGY,
                native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                suggested_display_precision=2,
            )
        }
        site_sen = RooftopSensor(
            key="site_data",
            coordinator=coordinator,
            entry=entry,
            sensor=k,
            rooftop_id=site["resource_id"],
        )
        entities.append(site_sen)

    async_add_entities(entities)


class SolcastSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Solcast sensor device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SolcastUpdateCoordinator,
        entry: ConfigEntry,
        sensor: dict[str, Any],
    ) -> None:
        """Initialise the sensor.

        Arguments:
            coordinator (SolcastUpdateCoordinator): The integration coordinator instance.
            entry (ConfigEntry): The integration entry instance, contains the configuration.
            sensor (dict[str, Any]): The details of the entity.

        """
        super().__init__(coordinator)

        self.entity_description = sensor["description"]
        self._attr_extra_state_attributes = {}
        self._attr_unique_id = f"{self.entity_description.key}"
        self._coordinator = coordinator
        self._attr_entity_registry_enabled_default = sensor.get("enabled_by_default", True)
        self._sensor_data = None
        self._update_policy = get_sensor_update_policy(self.entity_description.key)
        if sensor.get("attribution", True):
            self._attr_attribution = ATTRIBUTION

        try:
            self._sensor_data = self._coordinator.get_sensor_value(self.entity_description.key)
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Unable to get sensor value: %s: %s", e, traceback.format_exc())

        self._attr_available = self._sensor_data is not None

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Solcast PV Forecast",
            manufacturer=MANUFACTURER,
            model="Solcast PV Forecast",
            entry_type=DeviceEntryType.SERVICE,
            sw_version=coordinator.version,
            configuration_url="https://toolkit.solcast.com.au/",
        )

    async def async_added_to_hass(self) -> None:
        """Entity about to be added to hass, so set recorder excluded attributes."""
        await super().async_added_to_hass()

        if self.entity_description.key == "lastupdated":
            self._state_info["unrecorded_attributes"] = frozenset(["next_auto_update", "auto_update_divisions", "auto_update_queue"])

        elif str(self.entity_description.key).startswith("total_kwh_forecast"):
            exclude = ["detailedForecast", "detailedHourly"]
            if self._coordinator.solcast.options.attr_brk_site_detailed:
                for s in self._coordinator.solcast.sites:
                    exclude.append("detailedForecast_" + s["resource_id"].replace("-", "_"))
                    exclude.append("detailedHourly_" + s["resource_id"].replace("-", "_"))
            self._state_info["unrecorded_attributes"] = self._state_info["unrecorded_attributes"] | frozenset(exclude)

        elif self.entity_description.key == "dampen":
            exclude = ["factors"]
            self._state_info["unrecorded_attributes"] = self._state_info["unrecorded_attributes"] | frozenset(exclude)

    @property
    def available(self) -> bool:  # type: ignore[explicit-override]  # Explicitly overridden because parent is a cached property
        """Return the availability of the sensor linked to the source sensor."""
        return self._attr_available

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:  # type: ignore[explicit-override]
        """Return the state extra attributes of the sensor.

        Returns:
            dict[str, Any] | None: The current attributes of a sensor.

        """
        return self._coordinator.get_sensor_extra_attributes(self.entity_description.key)

    @property
    def native_value(self) -> int | dt | float | str | bool | None:  # type: ignore[explicit-override]
        """Return the current value of the sensor.

        Returns:
            int | dt | float | str | bool | None: The current value of a sensor.

        """
        return self._sensor_data

    @cached_property
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
        if self._update_policy == SensorUpdatePolicy.DEFAULT and not (
            self._coordinator.get_date_changed() or self._coordinator.get_data_updated()
        ):
            return

        try:
            self._sensor_data = self._coordinator.get_sensor_value(self.entity_description.key)
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Unable to get sensor value: %s: %s", e, traceback.format_exc())
            self._sensor_data = None
        finally:
            if SENSOR_UPDATE_LOGGING:
                _LOGGER.debug("Updating sensor %s to %s", self.entity_description.name, self._sensor_data)

        self._attr_available = self._sensor_data is not None

        self.async_write_ha_state()


class RooftopSensor(CoordinatorEntity, SensorEntity):
    """Representation of a rooftop sensor device."""

    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        *,
        key: str,
        coordinator: SolcastUpdateCoordinator,
        entry: ConfigEntry,
        sensor: dict[str, SensorEntityDescription],
        rooftop_id: str,
    ) -> None:
        """Initialise the sensor.

        Arguments:
            key (str): The sensor name.
            coordinator (SolcastUpdateCoordinator): The integration coordinator instance.
            entry (ConfigEntry): The integration entry instance, contains the configuration.
            sensor (dict[str, SensorEntityDescription]): The details of the entity.
            rooftop_id (str): The site name to use as the senor name.

        """
        super().__init__(coordinator)

        self.entity_description = sensor["description"]
        self._key = key
        self._coordinator = coordinator
        self._rooftop_id = rooftop_id  # entity_description.
        self._attr_extra_state_attributes = {}
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._sensor_data = None

        try:
            self._sensor_data = coordinator.get_site_sensor_value(self._rooftop_id, key)
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Unable to get sensor value: %s", e)

        self._attr_available = self._sensor_data is not None

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Solcast PV Forecast",
            manufacturer=MANUFACTURER,
            model="Solcast PV Forecast",
            entry_type=DeviceEntryType.SERVICE,
            sw_version=coordinator.version,
            configuration_url="https://toolkit.solcast.com.au/",
        )

        self._unique_id = f"solcast_api_{sensor['description'].name}"

    @property
    def available(self) -> bool:  # type: ignore[explicit-override]  # Explicitly overridden because parent is a cached property
        """Return the availability of the sensor linked to the source sensor."""
        return self._attr_available

    @cached_property
    def name(self) -> str:
        """Return the name of the device.

        Returns:
            str: The device name.

        """
        return f"{self.entity_description.name}"

    @property
    def unique_id(self) -> str | None:  # type: ignore[explicit-override]
        """Return the unique ID of the sensor.

        Returns:
            str: Unique ID.

        """
        return f"solcast_{self._unique_id}"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:  # type: ignore[explicit-override]
        """Return the state extra attributes of the sensor.

        Returns:
            dict[str, Any] | None: The current attributes of a sensor.

        """
        return self._coordinator.get_site_sensor_extra_attributes(self._rooftop_id, self._key)

    @property
    def native_value(self) -> int | dt | float | str | bool | None:  # type: ignore[explicit-override]
        """Return the current value of the sensor.

        Returns:
            int | dt | float | str | bool | None: The current value of a sensor.

        """
        return self._sensor_data

    @cached_property
    def should_poll(self) -> bool:
        """Return whether the sensor should poll.

        Returns:
            bool: Always returns False, as sensors are not polled.

        """
        return False

    async def async_added_to_hass(self) -> None:
        """Entity is added to Home Assistant."""
        await super().async_added_to_hass()

    @callback
    def _handle_coordinator_update(self):
        """Handle updated data from the coordinator."""
        if not (self._coordinator.get_date_changed() or self._coordinator.get_data_updated()):
            return
        try:
            self._sensor_data = self._coordinator.get_site_sensor_value(self._rooftop_id, self._key)
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Unable to get sensor value: %s: %s", e, traceback.format_exc())
            self._sensor_data = None
        finally:
            if SENSOR_UPDATE_LOGGING:
                _LOGGER.debug("Updating sensor %s to %s", self.entity_description.name, self._sensor_data)

        self._attr_available = self._sensor_data is not None

        self.async_write_ha_state()
