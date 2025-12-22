"""Support for Solcast PV forecast sensors."""

from __future__ import annotations

from datetime import datetime as dt
from enum import Enum
import logging
import traceback
from typing import Any, Final

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
    API_KEY,
    ATTRIBUTION,
    AUTO_UPDATE_DIVISIONS,
    AUTO_UPDATE_NEXT,
    AUTO_UPDATE_QUEUE,
    DESCRIPTION,
    DETAILED_FORECAST,
    DETAILED_HOURLY,
    DOMAIN,
    ENABLED_BY_DEFAULT,
    ENTITY_API_COUNTER,
    ENTITY_API_LIMIT,
    ENTITY_DAMPEN,
    ENTITY_FORECAST_CUSTOM_HOURS,
    ENTITY_FORECAST_NEXT_HOUR,
    ENTITY_FORECAST_REMAINING_TODAY,
    ENTITY_FORECAST_REMAINING_TODAY_OLD,
    ENTITY_FORECAST_THIS_HOUR,
    ENTITY_LAST_UPDATED,
    ENTITY_LAST_UPDATED_OLD,
    ENTITY_PEAK_W_TIME_TODAY,
    ENTITY_PEAK_W_TIME_TOMORROW,
    ENTITY_PEAK_W_TODAY,
    ENTITY_PEAK_W_TOMORROW,
    ENTITY_POWER_NOW,
    ENTITY_POWER_NOW_1HR,
    ENTITY_POWER_NOW_30M,
    ENTITY_TOTAL_KWH_FORECAST,
    ENTITY_TOTAL_KWH_FORECAST_TODAY,
    ENTITY_TOTAL_KWH_FORECAST_TOMORROW,
    FACTORS,
    HARD_LIMIT,
    HARD_LIMIT_API,
    INTEGRATION,
    MANUFACTURER,
    NAME,
    RESOURCE_ID,
    SITES_DATA,
    UNRECORDED_ATTRIBUTES,
)
from .coordinator import SolcastUpdateCoordinator
from .util import api_key_last_six, redact_api_key

_LOGGER = logging.getLogger(__name__)

NAMES: Final[dict[str, str]] = {
    ENTITY_API_COUNTER: "API Used",
    ENTITY_API_LIMIT: "API Limit",
    ENTITY_DAMPEN: "Dampening",
    ENTITY_FORECAST_CUSTOM_HOURS: "Forecast Custom Hours",
    ENTITY_FORECAST_NEXT_HOUR: "Forecast Next Hour",
    ENTITY_FORECAST_THIS_HOUR: "Forecast This Hour",
    ENTITY_FORECAST_REMAINING_TODAY: "Forecast Remaining Today",
    ENTITY_FORECAST_REMAINING_TODAY_OLD: "Forecast Remaining Today",
    ENTITY_LAST_UPDATED: "API Last Polled",
    ENTITY_LAST_UPDATED_OLD: "API Last Polled",
    ENTITY_PEAK_W_TIME_TODAY: "Peak Time Today",
    ENTITY_PEAK_W_TIME_TOMORROW: "Peak Time Tomorrow",
    ENTITY_PEAK_W_TODAY: "Peak Forecast Today",
    ENTITY_PEAK_W_TOMORROW: "Peak Forecast Tomorrow",
    ENTITY_POWER_NOW: "Power Now",
    ENTITY_POWER_NOW_1HR: "Power in 1 Hour",
    ENTITY_POWER_NOW_30M: "Power in 30 Minutes",
    ENTITY_TOTAL_KWH_FORECAST_TODAY: "Forecast Today",
    ENTITY_TOTAL_KWH_FORECAST_TOMORROW: "Forecast Tomorrow",
}

SENSORS: Final[dict[str, dict[str, Any]]] = {
    ENTITY_API_COUNTER: {
        DESCRIPTION: SensorEntityDescription(
            key=ENTITY_API_COUNTER,
            translation_key=ENTITY_API_COUNTER,
            name=NAMES[ENTITY_API_COUNTER],
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        ATTRIBUTION: False,
    },
    ENTITY_API_LIMIT: {
        DESCRIPTION: SensorEntityDescription(
            key=ENTITY_API_LIMIT,
            translation_key=ENTITY_API_LIMIT,
            name=NAMES[ENTITY_API_LIMIT],
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        ATTRIBUTION: False,
    },
    ENTITY_DAMPEN: {
        DESCRIPTION: SensorEntityDescription(
            key=ENTITY_DAMPEN,
            translation_key=ENTITY_DAMPEN,
            name=NAMES[ENTITY_DAMPEN],
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        ATTRIBUTION: False,
        ENABLED_BY_DEFAULT: False,
    },
    ENTITY_FORECAST_THIS_HOUR: {
        DESCRIPTION: SensorEntityDescription(
            key=ENTITY_FORECAST_THIS_HOUR,
            translation_key=ENTITY_FORECAST_THIS_HOUR,
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
            name=NAMES[ENTITY_FORECAST_THIS_HOUR],
            suggested_display_precision=0,
        )
    },
    ENTITY_FORECAST_CUSTOM_HOURS: {
        DESCRIPTION: SensorEntityDescription(
            key=ENTITY_FORECAST_CUSTOM_HOURS,
            translation_key=ENTITY_FORECAST_CUSTOM_HOURS,
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
            name=NAMES[ENTITY_FORECAST_CUSTOM_HOURS],
            suggested_display_precision=0,
        ),
        ENABLED_BY_DEFAULT: False,
    },
    ENTITY_FORECAST_NEXT_HOUR: {
        DESCRIPTION: SensorEntityDescription(
            key=ENTITY_FORECAST_NEXT_HOUR,
            translation_key=ENTITY_FORECAST_NEXT_HOUR,
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
            name=NAMES[ENTITY_FORECAST_NEXT_HOUR],
            suggested_display_precision=0,
        )
    },
    ENTITY_FORECAST_REMAINING_TODAY_OLD: {
        DESCRIPTION: SensorEntityDescription(
            key=ENTITY_FORECAST_REMAINING_TODAY_OLD,
            translation_key=ENTITY_FORECAST_REMAINING_TODAY,
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            name=NAMES[ENTITY_FORECAST_REMAINING_TODAY],
            suggested_display_precision=2,
        )
    },
    ENTITY_LAST_UPDATED_OLD: {
        DESCRIPTION: SensorEntityDescription(
            key=ENTITY_LAST_UPDATED_OLD,
            translation_key=ENTITY_LAST_UPDATED,
            device_class=SensorDeviceClass.TIMESTAMP,
            name=NAMES[ENTITY_LAST_UPDATED],
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        ATTRIBUTION: False,
    },
    ENTITY_PEAK_W_TIME_TODAY: {
        DESCRIPTION: SensorEntityDescription(
            key=ENTITY_PEAK_W_TIME_TODAY,
            translation_key=ENTITY_PEAK_W_TIME_TODAY,
            name=NAMES[ENTITY_PEAK_W_TIME_TODAY],
            device_class=SensorDeviceClass.TIMESTAMP,
        )
    },
    ENTITY_PEAK_W_TIME_TOMORROW: {
        DESCRIPTION: SensorEntityDescription(
            key=ENTITY_PEAK_W_TIME_TOMORROW,
            translation_key=ENTITY_PEAK_W_TIME_TOMORROW,
            name=NAMES[ENTITY_PEAK_W_TIME_TOMORROW],
            device_class=SensorDeviceClass.TIMESTAMP,
        )
    },
    ENTITY_PEAK_W_TODAY: {
        DESCRIPTION: SensorEntityDescription(
            key=ENTITY_PEAK_W_TODAY,
            translation_key=ENTITY_PEAK_W_TODAY,
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.WATT,
            name=NAMES[ENTITY_PEAK_W_TODAY],
            suggested_display_precision=0,
            state_class=SensorStateClass.MEASUREMENT,
        )
    },
    ENTITY_PEAK_W_TOMORROW: {
        DESCRIPTION: SensorEntityDescription(
            key=ENTITY_PEAK_W_TOMORROW,
            translation_key=ENTITY_PEAK_W_TOMORROW,
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.WATT,
            name=NAMES[ENTITY_PEAK_W_TOMORROW],
            suggested_display_precision=0,
        )
    },
    ENTITY_POWER_NOW: {
        DESCRIPTION: SensorEntityDescription(
            key=ENTITY_POWER_NOW,
            translation_key=ENTITY_POWER_NOW,
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.WATT,
            name=NAMES[ENTITY_POWER_NOW],
            suggested_display_precision=0,
            state_class=SensorStateClass.MEASUREMENT,
        )
    },
    ENTITY_POWER_NOW_1HR: {
        DESCRIPTION: SensorEntityDescription(
            key=ENTITY_POWER_NOW_1HR,
            translation_key=ENTITY_POWER_NOW_1HR,
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.WATT,
            name=NAMES[ENTITY_POWER_NOW_1HR],
            suggested_display_precision=0,
            state_class=SensorStateClass.MEASUREMENT,
        )
    },
    ENTITY_POWER_NOW_30M: {
        DESCRIPTION: SensorEntityDescription(
            key=ENTITY_POWER_NOW_30M,
            translation_key=ENTITY_POWER_NOW_30M,
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.WATT,
            name=NAMES[ENTITY_POWER_NOW_30M],
            suggested_display_precision=0,
            state_class=SensorStateClass.MEASUREMENT,
        )
    },
    ENTITY_TOTAL_KWH_FORECAST_TODAY: {
        DESCRIPTION: SensorEntityDescription(
            key=ENTITY_TOTAL_KWH_FORECAST_TODAY,
            translation_key=ENTITY_TOTAL_KWH_FORECAST_TODAY,
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            name=NAMES[ENTITY_TOTAL_KWH_FORECAST_TODAY],
            suggested_display_precision=2,
            state_class=SensorStateClass.TOTAL,
        )
    },
    ENTITY_TOTAL_KWH_FORECAST_TOMORROW: {
        DESCRIPTION: SensorEntityDescription(
            key=ENTITY_TOTAL_KWH_FORECAST_TOMORROW,
            translation_key=ENTITY_TOTAL_KWH_FORECAST_TOMORROW,
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            name=NAMES[ENTITY_TOTAL_KWH_FORECAST_TOMORROW],
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
        ENTITY_DAMPEN,
        ENTITY_FORECAST_THIS_HOUR,
        ENTITY_FORECAST_NEXT_HOUR,
        ENTITY_FORECAST_CUSTOM_HOURS,
        ENTITY_FORECAST_REMAINING_TODAY,
        ENTITY_FORECAST_REMAINING_TODAY_OLD,
        ENTITY_POWER_NOW,
        ENTITY_POWER_NOW_30M,
        ENTITY_POWER_NOW_1HR,
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
    for forecast_day in range(3, coordinator.advanced_day_entities):
        sen = SolcastSensor(
            coordinator,
            entry,
            {
                DESCRIPTION: SensorEntityDescription(
                    key=f"{ENTITY_TOTAL_KWH_FORECAST}_d{forecast_day}",
                    device_class=SensorDeviceClass.ENERGY,
                    native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                    translation_key=f"{ENTITY_TOTAL_KWH_FORECAST}_d{forecast_day}",
                    name=f"Forecast D{forecast_day}",
                    suggested_display_precision=2,
                    state_class=SensorStateClass.TOTAL,
                ),
                ENABLED_BY_DEFAULT: False,
            },
        )
        entities.append(sen)

    hard_limits = coordinator.solcast.options.hard_limit.split(",")
    if len(hard_limits) == 1:
        k = {
            DESCRIPTION: SensorEntityDescription(
                key=HARD_LIMIT,
                translation_key=HARD_LIMIT,
                name="Hard Limit Set",
                entity_category=EntityCategory.DIAGNOSTIC,
            )
        }
        sen = SolcastSensor(coordinator, entry, k)
        entities.append(sen)
        expecting_limits = [HARD_LIMIT]
    else:
        for api_key in coordinator.solcast.options.api_key.split(","):
            k = {
                DESCRIPTION: SensorEntityDescription(
                    key="hard_limit_" + api_key_last_six(api_key),
                    translation_key=HARD_LIMIT_API,
                    translation_placeholders={
                        API_KEY: redact_api_key(api_key),
                    },
                    entity_category=EntityCategory.DIAGNOSTIC,
                )
            }
            sen = SolcastSensor(coordinator, entry, k)
            entities.append(sen)
        expecting_limits = [f"hard_limit_{api_key_last_six(api_key)}" for api_key in coordinator.solcast.options.api_key.split(",")]

    # Clean up.
    entity_registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        # Clean up orphaned hard limit sensors.
        if HARD_LIMIT in entity.unique_id and entity.unique_id not in expecting_limits:
            entity_registry.async_remove(entity.entity_id)
            _LOGGER.warning("Cleaning up orphaned %s", entity.entity_id)

        # Clean up any orphaned day sensors.
        if entity.translation_key is not None:
            if (
                entity.translation_key.startswith(f"{ENTITY_TOTAL_KWH_FORECAST}_d")
                and int(entity.unique_id.split("_")[-1].split("d")[-1]) > coordinator.advanced_day_entities - 1
            ):
                entity_registry.async_remove(entity.entity_id)
                _LOGGER.warning("Cleaning up orphaned %s", entity.entity_id)

    # Site sensors
    for site in coordinator.get_solcast_sites():
        k = {
            DESCRIPTION: SensorEntityDescription(
                key=site[RESOURCE_ID],
                translation_key=SITES_DATA,
                name=site[NAME],
                device_class=SensorDeviceClass.ENERGY,
                native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                suggested_display_precision=2,
            )
        }
        site_sen = RooftopSensor(
            key=SITES_DATA,
            coordinator=coordinator,
            entry=entry,
            sensor=k,
            rooftop_id=site[RESOURCE_ID],
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

        self.entity_description = sensor[DESCRIPTION]
        self._attr_extra_state_attributes = {}
        self._attr_unique_id = f"{self.entity_description.key}"
        self._coordinator = coordinator
        self._attr_entity_registry_enabled_default = sensor.get(ENABLED_BY_DEFAULT, True)
        self._sensor_data = None
        self._update_policy = get_sensor_update_policy(self.entity_description.key)
        if sensor.get(ATTRIBUTION, True):
            self._attr_attribution = ATTRIBUTION

        try:
            self._sensor_data = self._coordinator.get_sensor_value(self.entity_description.key)
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Unable to get sensor value: %s: %s", e, traceback.format_exc())

        self._attr_available = self._sensor_data is not None

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=INTEGRATION,
            manufacturer=MANUFACTURER,
            model=INTEGRATION,
            entry_type=DeviceEntryType.SERVICE,
            sw_version=coordinator.version,
            configuration_url="https://toolkit.solcast.com.au/",
        )

    async def async_added_to_hass(self) -> None:
        """Entity about to be added to hass, so set recorder excluded attributes."""
        await super().async_added_to_hass()

        if self.entity_description.key in (ENTITY_LAST_UPDATED, ENTITY_LAST_UPDATED_OLD):
            self._state_info[UNRECORDED_ATTRIBUTES] = frozenset([AUTO_UPDATE_NEXT, AUTO_UPDATE_DIVISIONS, AUTO_UPDATE_QUEUE])

        elif str(self.entity_description.key).startswith(ENTITY_TOTAL_KWH_FORECAST):
            exclude = [DETAILED_FORECAST, DETAILED_HOURLY]
            if self._coordinator.solcast.options.attr_brk_site_detailed:
                for s in self._coordinator.solcast.sites:
                    exclude.append(f"{DETAILED_FORECAST}_" + s[RESOURCE_ID].replace("-", "_"))
                    exclude.append(f"{DETAILED_HOURLY}_" + s[RESOURCE_ID].replace("-", "_"))
            self._state_info[UNRECORDED_ATTRIBUTES] = self._state_info[UNRECORDED_ATTRIBUTES] | frozenset(exclude)

        elif self.entity_description.key == "dampen":
            exclude = [FACTORS]
            self._state_info[UNRECORDED_ATTRIBUTES] = self._state_info[UNRECORDED_ATTRIBUTES] | frozenset(exclude)

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
            if self._coordinator.advanced_entity_logging:
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

        self.entity_description = sensor[DESCRIPTION]
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
            name=INTEGRATION,
            manufacturer=MANUFACTURER,
            model=INTEGRATION,
            entry_type=DeviceEntryType.SERVICE,
            sw_version=coordinator.version,
            configuration_url="https://toolkit.solcast.com.au/",
        )

        self._unique_id = f"solcast_api_{sensor[DESCRIPTION].name}"

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
            if self._coordinator.advanced_entity_logging:
                _LOGGER.debug("Updating sensor %s to %s", self.entity_description.name, self._sensor_data)

        self._attr_available = self._sensor_data is not None

        self.async_write_ha_state()
