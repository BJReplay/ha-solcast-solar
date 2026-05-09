"""Entity classes for Solcast PV SimCity sensors."""

from __future__ import annotations

from collections.abc import Callable
import contextlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.restore_state import RestoreEntity

from .restore_helpers import recorder_sensor_value, select_measurement_restore_value
from .sim_core import (
    SimulationProfile,
    SolcastSimBatteryModel,
    seconds_since_midnight,
    shade_attenuation_factor,
    simulated_power_kw,
)

UPDATE_INTERVAL = timedelta(seconds=5)
DISPLAY_NAME_PREFIX = "Solcast Sim "


def _prefixed_display_name(name: str) -> str:
    """Return a display name with the integration prefix applied once."""
    if name.startswith(DISPLAY_NAME_PREFIX):
        return name
    return f"{DISPLAY_NAME_PREFIX}{name}"


@dataclass
class ModelSensorDesc:
    """Descriptor for a model-backed sensor."""

    unique_id: str
    name: str
    device_class: SensorDeviceClass
    state_class: SensorStateClass | None
    unit: str
    value_fn: Callable[[SolcastSimBatteryModel], float]
    restore_fn: Callable[[SolcastSimBatteryModel, float], None] | None = None
    restore_display: bool = False
    restore_same_day: bool = False
    set_last_t: bool = False


_SENSORS: list[ModelSensorDesc] = [
    ModelSensorDesc(
        unique_id="solcast_sim_site_export_power",
        name="Site Export Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfPower.WATT,
        value_fn=lambda m: round(m.export_power_kw * 1000, 1),
    ),
    ModelSensorDesc(
        unique_id="solcast_sim_export_energy",
        name="Site Export Energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=lambda m: round(m.export_energy_kwh, 6),
        restore_fn=lambda m, v: m.restore_export_energy(v),
        set_last_t=True,
    ),
    ModelSensorDesc(
        unique_id="solcast_sim_battery_soc",
        name="Battery State of Charge",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        unit=PERCENTAGE,
        value_fn=lambda m: round(m.battery_soc, 2),
    ),
    ModelSensorDesc(
        unique_id="solcast_sim_battery_energy",
        name="Battery Stored Energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=None,
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=lambda m: round(m.battery_energy_kwh, 6),
        restore_fn=lambda m, v: m.restore_battery_energy(v),
    ),
    ModelSensorDesc(
        unique_id="solcast_sim_battery_power",
        name="Battery Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfPower.WATT,
        value_fn=lambda m: round(m.battery_power_kw * 1000, 1),
    ),
    ModelSensorDesc(
        unique_id="solcast_sim_battery_charge_energy",
        name="Battery Charge Energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=lambda m: round(m.charge_energy_kwh, 6),
        restore_fn=lambda m, v: m.restore_charge_energy(v),
    ),
    ModelSensorDesc(
        unique_id="solcast_sim_battery_discharge_energy",
        name="Battery Discharge Energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=lambda m: round(m.discharge_energy_kwh, 6),
        restore_fn=lambda m, v: m.restore_discharge_energy(v),
    ),
    ModelSensorDesc(
        unique_id="solcast_sim_grid_consumption_power",
        name="Grid Consumption Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfPower.WATT,
        value_fn=lambda m: round(m.grid_import_power_kw * 1000, 1),
    ),
    ModelSensorDesc(
        unique_id="solcast_sim_grid_consumption_energy",
        name="Grid Consumption Energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=lambda m: round(m.grid_import_energy_kwh, 6),
        restore_fn=lambda m, v: m.restore_grid_import_energy(v),
    ),
    ModelSensorDesc(
        unique_id="solcast_sim_grid_export_today",
        name="Grid Export Today",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=lambda m: round(m.export_today_energy_kwh, 6),
        restore_fn=lambda m, v: m.restore_export_today_energy(v),
        restore_same_day=True,
    ),
    ModelSensorDesc(
        unique_id="solcast_sim_grid_import_today",
        name="Grid Import Today",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=lambda m: round(m.grid_import_today_energy_kwh, 6),
        restore_fn=lambda m, v: m.restore_grid_import_today_energy(v),
        restore_same_day=True,
    ),
    ModelSensorDesc(
        unique_id="solcast_sim_free_charge_power",
        name="Free Charge Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfPower.WATT,
        value_fn=lambda m: round(m.free_grid_charge_power_kw * 1000, 1),
    ),
    ModelSensorDesc(
        unique_id="solcast_sim_free_charge_energy",
        name="Free Charge Energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=lambda m: round(m.free_grid_charge_energy_kwh, 6),
        restore_fn=lambda m, v: m.restore_free_charge_energy(v),
    ),
]


class ModelSensorMixin(SensorEntity):
    """Shared initialiser and interval logic for model-backed sensors."""

    _attr_should_poll = False

    def _init_desc(
        self,
        desc: ModelSensorDesc,
        model: SolcastSimBatteryModel,
        tz: ZoneInfo,
    ) -> None:
        self._desc = desc
        self._model = model
        self._tz = tz
        self._attr_unique_id = desc.unique_id
        self._attr_name = _prefixed_display_name(desc.name)
        self._attr_device_class = desc.device_class
        self._attr_state_class = desc.state_class
        self._attr_native_unit_of_measurement = desc.unit
        if desc.restore_fn is not None or desc.restore_display:
            self._attr_native_value = None
        else:
            self._attr_native_value = desc.value_fn(model)

    @callback
    def _handle_interval(self, _now: datetime) -> None:
        self._model.advance(seconds_since_midnight(self._tz))
        self._attr_native_value = self._desc.value_fn(self._model)
        self.async_write_ha_state()


class ModelSensor(ModelSensorMixin):
    """Model-backed sensor without state restore."""

    def __init__(self, desc: ModelSensorDesc, model: SolcastSimBatteryModel, tz: ZoneInfo) -> None:
        """Initialise the model-backed sensor."""
        self._init_desc(desc, model, tz)

    async def async_added_to_hass(self) -> None:
        """Register periodic updates when added to Home Assistant."""
        if self._desc.set_last_t:
            self._model.last_t = seconds_since_midnight(self._tz)
        self.async_on_remove(async_track_time_interval(self.hass, self._handle_interval, UPDATE_INTERVAL))


class RestoreModelSensor(ModelSensorMixin, RestoreEntity):
    """Model-backed sensor that restores accumulated state on HA restart."""

    def __init__(self, desc: ModelSensorDesc, model: SolcastSimBatteryModel, tz: ZoneInfo) -> None:
        """Initialise the restoring model-backed sensor."""
        self._init_desc(desc, model, tz)

    async def async_added_to_hass(self) -> None:
        """Restore prior state, then register periodic updates."""
        cache_state: tuple[float, datetime] | None = None
        today = datetime.now(self._tz).date()

        if (last_state := await self.async_get_last_state()) is not None:
            with contextlib.suppress(ValueError, TypeError):
                ts = last_state.last_updated or last_state.last_changed
                if ts is not None and (not self._desc.restore_same_day or ts.astimezone(self._tz).date() == today):
                    cache_state = (float(last_state.state), ts)

        recorder_state: tuple[float, datetime] | None = None
        if self.entity_id is not None:
            recorder_state = await recorder_sensor_value(self.hass, self.entity_id)
            if recorder_state is not None and self._desc.restore_same_day and recorder_state[1].astimezone(self._tz).date() != today:
                recorder_state = None

        restored_value: float | None
        if self._desc.state_class is SensorStateClass.TOTAL_INCREASING:
            cache_value = cache_state[0] if cache_state is not None else None
            recorder_value = recorder_state[0] if recorder_state is not None else None
            if cache_value is None and recorder_value is None:
                restored_value = None
            elif cache_value is None:
                restored_value = recorder_value
            elif recorder_value is None:
                restored_value = cache_value
            else:
                restored_value = max(cache_value, recorder_value)
        else:
            restored_value = select_measurement_restore_value(cache_state, recorder_state)

        if restored_value is not None and self._desc.restore_fn is not None:
            self._desc.restore_fn(self._model, restored_value)

        if restored_value is not None:
            self._attr_native_value = restored_value
        else:
            self._attr_native_value = self._desc.value_fn(self._model)
        if self._desc.set_last_t:
            self._model.last_t = seconds_since_midnight(self._tz)
        self.async_on_remove(async_track_time_interval(self.hass, self._handle_interval, UPDATE_INTERVAL))


class ExportEnergySensor(RestoreModelSensor):
    """Site export energy sensor with extra simulation debug attributes."""

    @property
    def extra_state_attributes(self) -> dict[str, float]:
        """Expose battery and export simulation internals for debugging."""
        return {
            "battery_energy_kwh": round(self._model.battery_energy_kwh, 3),
            "battery_capacity_kwh": round(self._model.battery_capacity_kwh, 3),
            "battery_soc": round(self._model.battery_soc, 2),
            "house_load_kw": round(self._model.house_load_kw, 3),
            "export_limit_kw": round(self._model.export_limit_kw, 3),
            "export_power_w": round(self._model.export_power_kw * 1000, 1),
            "grid_consumption_power_w": round(self._model.grid_import_power_kw * 1000, 1),
        }


class SolcastSimPowerSensor(SensorEntity):
    """Instantaneous splined power sensor for a simulated PV site (W)."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_should_poll = False

    def __init__(self, site: dict[str, Any], tz: ZoneInfo, profile: SimulationProfile) -> None:
        """Initialise the power sensor."""
        self._site = site
        self._tz = tz
        self._profile = profile
        self._attr_unique_id = f"solcast_sim_{site['resource_id']}_power"
        self._attr_name = _prefixed_display_name(f"{site['name']} Generation Power")
        self._attr_native_value: float = 0.0

    async def async_added_to_hass(self) -> None:
        """Compute initial state and register for periodic updates."""
        self._refresh()
        self.async_on_remove(async_track_time_interval(self.hass, self._handle_interval, UPDATE_INTERVAL))

    @callback
    def _handle_interval(self, _now: datetime) -> None:
        self._refresh()
        self.async_write_ha_state()

    def _refresh(self) -> None:
        t = seconds_since_midnight(self._tz)
        power_kw = simulated_power_kw(t, self._site["capacity"], self._tz, self._profile)
        self._attr_native_value = round(power_kw * 1000, 1)


class SolcastSimTotalPowerSensor(SensorEntity):
    """Instantaneous total PV generation power across all simulated sites (W)."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_should_poll = False

    def __init__(self, sites: list[dict[str, Any]], tz: ZoneInfo, profile: SimulationProfile) -> None:
        """Initialise the total power sensor."""
        self._sites = sites
        self._tz = tz
        self._profile = profile
        self._attr_unique_id = "solcast_sim_total_generation_power"
        self._attr_name = _prefixed_display_name("Total PV Generation Power")
        self._attr_native_value: float = 0.0
        self._shade_attenuation_factor = 1.0

    async def async_added_to_hass(self) -> None:
        """Compute initial state and register for periodic updates."""
        self._refresh()
        self.async_on_remove(async_track_time_interval(self.hass, self._handle_interval, UPDATE_INTERVAL))

    @callback
    def _handle_interval(self, _now: datetime) -> None:
        self._refresh()
        self.async_write_ha_state()

    def _refresh(self) -> None:
        t = seconds_since_midnight(self._tz)
        now_local = datetime.now(self._tz)
        self._shade_attenuation_factor = shade_attenuation_factor(now_local, self._profile)
        total_power_kw = sum(simulated_power_kw(t, site["capacity"], self._tz, self._profile) for site in self._sites)
        self._attr_native_value = round(total_power_kw * 1000, 1)

    @property
    def extra_state_attributes(self) -> dict[str, float]:
        """Expose current shade attenuation diagnostics."""
        return {
            "shade_attenuation_factor": round(self._shade_attenuation_factor, 4),
            "shade_blocked_fraction": round(1.0 - self._shade_attenuation_factor, 4),
        }


class SolcastSimEnergySensor(RestoreEntity, SensorEntity):
    """Cumulative energy sensor (total_increasing, kWh) for a simulated PV site."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_should_poll = False

    def __init__(self, site: dict[str, Any], tz: ZoneInfo, profile: SimulationProfile) -> None:
        """Initialise the energy sensor."""
        self._site = site
        self._tz = tz
        self._profile = profile
        self._attr_unique_id = f"solcast_sim_{site['resource_id']}_energy"
        self._attr_name = _prefixed_display_name(f"{site['name']} Generation Energy")
        self._attr_native_value: float = 0.0
        self._last_t: float | None = None

    async def async_added_to_hass(self) -> None:
        """Restore last known accumulated value."""
        if (last_state := await self.async_get_last_state()) is not None:
            try:
                self._attr_native_value = float(last_state.state)
            except (ValueError, TypeError):
                self._attr_native_value = 0.0

        self._last_t = seconds_since_midnight(self._tz)
        self.async_on_remove(async_track_time_interval(self.hass, self._handle_interval, UPDATE_INTERVAL))

    @callback
    def _handle_interval(self, _now: datetime) -> None:
        self._accumulate()
        self.async_write_ha_state()

    def _accumulate(self) -> None:
        t = seconds_since_midnight(self._tz)
        if self._last_t is not None:
            dt_s = t - self._last_t
            if dt_s < 0:
                self._last_t = t
                return
            power_start_kw = simulated_power_kw(self._last_t, self._site["capacity"], self._tz, self._profile)
            power_end_kw = simulated_power_kw(t, self._site["capacity"], self._tz, self._profile)
            avg_power_kw = (power_start_kw + power_end_kw) / 2
            delta_kwh = avg_power_kw * (dt_s / 3600)
            self._attr_native_value = round((self._attr_native_value or 0.0) + max(0.0, delta_kwh), 6)
        self._last_t = t


class SolcastSimTotalEnergySensor(RestoreEntity, SensorEntity):
    """Cumulative total PV generation energy across all simulated sites (kWh)."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_should_poll = False

    def __init__(self, sites: list[dict[str, Any]], tz: ZoneInfo, profile: SimulationProfile) -> None:
        """Initialise the total energy sensor."""
        self._sites = sites
        self._tz = tz
        self._profile = profile
        self._attr_unique_id = "solcast_sim_total_generation_energy"
        self._attr_name = _prefixed_display_name("Total PV Generation Energy")
        self._attr_native_value: float = 0.0
        self._last_t: float | None = None

    async def async_added_to_hass(self) -> None:
        """Restore last known accumulated value."""
        if (last_state := await self.async_get_last_state()) is not None:
            try:
                self._attr_native_value = float(last_state.state)
            except (ValueError, TypeError):
                self._attr_native_value = 0.0

        self._last_t = seconds_since_midnight(self._tz)
        self.async_on_remove(async_track_time_interval(self.hass, self._handle_interval, UPDATE_INTERVAL))

    @callback
    def _handle_interval(self, _now: datetime) -> None:
        self._accumulate()
        self.async_write_ha_state()

    def _accumulate(self) -> None:
        t = seconds_since_midnight(self._tz)
        if self._last_t is not None:
            dt_s = t - self._last_t
            if dt_s < 0:
                self._last_t = t
                return
            power_start_kw = sum(simulated_power_kw(self._last_t, site["capacity"], self._tz, self._profile) for site in self._sites)
            power_end_kw = sum(simulated_power_kw(t, site["capacity"], self._tz, self._profile) for site in self._sites)
            avg_power_kw = (power_start_kw + power_end_kw) / 2
            delta_kwh = avg_power_kw * (dt_s / 3600)
            self._attr_native_value = round((self._attr_native_value or 0.0) + max(0.0, delta_kwh), 6)
        self._last_t = t


class SolcastSimTodayEnergySensor(RestoreEntity, SensorEntity):
    """Daily PV generation energy across all simulated sites (kWh)."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_should_poll = False

    def _midnight(self, day: date) -> datetime:
        """Return local midnight for a given day."""
        return datetime.combine(day, datetime.min.time(), self._tz)

    def __init__(self, sites: list[dict[str, Any]], tz: ZoneInfo, profile: SimulationProfile) -> None:
        """Initialise the daily PV energy sensor."""
        self._sites = sites
        self._tz = tz
        self._profile = profile
        self._attr_unique_id = "solcast_sim_today_generation_energy"
        self._attr_name = _prefixed_display_name("PV Today")
        self._attr_native_value: float = 0.0
        self._attr_last_reset: datetime | None = None
        self._last_t: float | None = None
        self._last_day: date | None = None

    async def async_added_to_hass(self) -> None:
        """Restore same-day accumulated value."""
        today = datetime.now(self._tz).date()
        cache_state: tuple[float, datetime] | None = None
        if (last_state := await self.async_get_last_state()) is not None:
            last_updated = last_state.last_updated or last_state.last_changed
            if last_updated is not None and last_updated.astimezone(self._tz).date() == today:
                with contextlib.suppress(ValueError, TypeError):
                    cache_state = (float(last_state.state), last_updated)

        recorder_state: tuple[float, datetime] | None = None
        if self.entity_id is not None:
            recorder_state = await recorder_sensor_value(self.hass, self.entity_id)
            if recorder_state is not None and recorder_state[1].astimezone(self._tz).date() != today:
                recorder_state = None

        if cache_state is not None or recorder_state is not None:
            restored_value = select_measurement_restore_value(cache_state, recorder_state)
            if restored_value is not None:
                self._attr_native_value = restored_value

        self._attr_last_reset = self._midnight(today)
        self._last_day = today
        self._last_t = seconds_since_midnight(self._tz)
        self.async_on_remove(async_track_time_interval(self.hass, self._handle_interval, UPDATE_INTERVAL))

    @callback
    def _handle_interval(self, _now: datetime) -> None:
        self._accumulate()
        self.async_write_ha_state()

    def _accumulate(self) -> None:
        now = datetime.now(self._tz)
        current_day = now.date()
        t = seconds_since_midnight(self._tz)

        if self._last_day != current_day:
            self._attr_native_value = 0.0
            self._attr_last_reset = self._midnight(current_day)
            self._last_day = current_day
            self._last_t = t
            return

        if self._last_t is not None:
            dt_s = t - self._last_t
            if dt_s < 0:
                self._attr_native_value = 0.0
                self._attr_last_reset = self._midnight(current_day)
                self._last_day = current_day
                self._last_t = t
                return
            power_start_kw = sum(simulated_power_kw(self._last_t, site["capacity"], self._tz, self._profile) for site in self._sites)
            power_end_kw = sum(simulated_power_kw(t, site["capacity"], self._tz, self._profile) for site in self._sites)
            avg_power_kw = (power_start_kw + power_end_kw) / 2
            delta_kwh = avg_power_kw * (dt_s / 3600)
            self._attr_native_value = round((self._attr_native_value or 0.0) + max(0.0, delta_kwh), 6)

        self._last_day = current_day
        self._last_t = t


class SolcastSimBatteryCapacitySensor(SensorEntity):
    """Configured battery total capacity (kWh)."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_should_poll = False

    def __init__(self, model: SolcastSimBatteryModel) -> None:
        """Initialise the battery capacity sensor."""
        self._attr_unique_id = "solcast_sim_battery_capacity"
        self._attr_name = _prefixed_display_name("Battery Capacity")
        self._attr_native_value = round(model.battery_capacity_kwh, 3)


def build_entities(
    sites: list[dict[str, Any]],
    tz: ZoneInfo,
    profile: SimulationProfile,
    model: SolcastSimBatteryModel,
) -> list[SensorEntity]:
    """Build all sensor entities."""
    entities: list[SensorEntity] = []
    for site in sites:
        entities.append(SolcastSimPowerSensor(site, tz, profile))
        entities.append(SolcastSimEnergySensor(site, tz, profile))
    entities.append(SolcastSimTotalPowerSensor(sites, tz, profile))
    entities.append(SolcastSimTotalEnergySensor(sites, tz, profile))
    entities.append(SolcastSimTodayEnergySensor(sites, tz, profile))
    entities.append(SolcastSimBatteryCapacitySensor(model))

    for desc in _SENSORS:
        if desc.set_last_t:
            entities.append(ExportEnergySensor(desc, model, tz))
        elif desc.restore_fn is not None or desc.restore_display:
            entities.append(RestoreModelSensor(desc, model, tz))
        else:
            entities.append(ModelSensor(desc, model, tz))

    return entities
