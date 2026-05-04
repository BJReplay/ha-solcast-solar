"""Solcast PV SimCity - synthetic PV generation and battery simulation sensors.

Uses the same natural cubic spline as the Solcast Solar integration
(mirroring solcast_solar/util.py cubic_interp) to produce smooth power and
total_increasing energy sensors.  Includes a battery charge/discharge model,
site export, and grid consumption sensors.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import contextlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
import importlib.util
import math
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.components.recorder import get_instance, history
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.restore_state import (
    RestoreEntity,
    async_get as async_get_restore_state,
)

# ---------------------------------------------------------------------------
# Load simulator data from the integration test fixtures at import time.
# ---------------------------------------------------------------------------

_SIM_PATH = Path(__file__).parent.parent.parent.parent / "tests/components/solcast_solar/simulator/simulate.py"
_spec = importlib.util.spec_from_file_location("solcast_simulate", _SIM_PATH)
_sim_module = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_sim_module)  # type: ignore[union-attr]

API_KEY_SITES: dict[str, Any] = _sim_module.API_KEY_SITES
GENERATION_FACTOR: list[float] = _sim_module.GENERATION_FACTOR

# Half-hourly x-axis for the spline: seconds from midnight, one per
# GENERATION_FACTOR entry (48 entries → 0 … 47 × 1800).
_SPLINE_X: list[int] = [i * 1800 for i in range(len(GENERATION_FACTOR))]

# ---------------------------------------------------------------------------
# Platform constants
# ---------------------------------------------------------------------------

UPDATE_INTERVAL = timedelta(seconds=5)
BATTERY_ENERGY_UNIQUE_ID = "solcast_sim_battery_energy"


def _time_str_to_seconds(t: str) -> int:
    """Convert a 'HH:MM:SS' or 'HH:MM' string to seconds since midnight."""
    parts = t.split(":")
    h, m, s = int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0
    return h * 3600 + m * 60 + s


def _restored_sensor_value(
    hass: HomeAssistant,
    integration_domain: str,
    unique_id: str,
) -> tuple[float, datetime] | None:
    """Return restored value and timestamp for a sensor by unique_id."""
    entity_id = er.async_get(hass).async_get_entity_id("sensor", integration_domain, unique_id)
    if entity_id is None:
        return None

    if (stored := async_get_restore_state(hass).last_states.get(entity_id)) is None:
        return None

    with contextlib.suppress(ValueError, TypeError):
        ts = stored.state.last_updated or stored.state.last_changed or stored.last_seen
        return float(stored.state.state), ts
    return None


async def _recorder_sensor_value(
    hass: HomeAssistant,
    entity_id: str,
) -> tuple[float, datetime] | None:
    """Return most recent recorder value and timestamp for an entity."""
    if "recorder" not in hass.config.components:
        return None

    recorder_states = await get_instance(hass).async_add_executor_job(partial(history.get_last_state_changes, hass, 1, entity_id=entity_id))
    if not (states := recorder_states.get(entity_id)):
        return None

    with contextlib.suppress(ValueError, TypeError):
        state = states[-1]
        ts = state.last_updated or state.last_changed
        if ts is None:
            return None
        return float(state.state), ts
    return None


def _select_measurement_restore_value(
    cache_state: tuple[float, datetime] | None,
    recorder_state: tuple[float, datetime] | None,
) -> float | None:
    """Select restore value for measurement sensors using newest timestamp."""
    if cache_state is None:
        return recorder_state[0] if recorder_state is not None else None
    if recorder_state is None:
        return cache_state[0]
    return cache_state[0] if cache_state[1] >= recorder_state[1] else recorder_state[0]


async def _prime_model_from_restore_state(
    hass: HomeAssistant,
    integration_domain: str,
    model: SolcastSimBatteryModel,
) -> None:
    """Prime model battery state from freshest startup state source."""
    cache_state = _restored_sensor_value(hass, integration_domain, BATTERY_ENERGY_UNIQUE_ID)

    recorder_state: tuple[float, datetime] | None = None
    if (
        energy_entity_id := er.async_get(hass).async_get_entity_id(
            "sensor",
            integration_domain,
            BATTERY_ENERGY_UNIQUE_ID,
        )
    ) is not None:
        recorder_state = await _recorder_sensor_value(hass, energy_entity_id)

    if (battery_energy := _select_measurement_restore_value(cache_state, recorder_state)) is not None:
        model.restore_battery_energy(battery_energy)


# ---------------------------------------------------------------------------
# Cubic spline helpers
# ---------------------------------------------------------------------------


def _diff(lst: Sequence[float]) -> list[float]:
    """Return successive differences (numpy-like diff, no non-negative clamp)."""
    return [lst[i + 1] - lst[i] for i in range(len(lst) - 1)]


def _cubic_interp(x0: list[float], x: Sequence[float], y: list[float]) -> list[float]:
    """Evaluate a natural cubic spline defined by (x, y) at each point in x0."""
    size = len(x)
    x_diff = _diff(x)
    y_diff = _diff(y)

    li: list[float] = [0.0] * size
    li_1: list[float] = [0.0] * (size - 1)
    z: list[float] = [0.0] * size

    li[0] = math.sqrt(2 * x_diff[0])
    li_1[0] = 0.0
    z[0] = 0.0

    for i in range(1, size - 1):
        li_1[i] = x_diff[i - 1] / li[i - 1]
        li[i] = math.sqrt(2 * (x_diff[i - 1] + x_diff[i]) - li_1[i - 1] * li_1[i - 1])
        bi = 6 * (y_diff[i] / x_diff[i] - y_diff[i - 1] / x_diff[i - 1])
        z[i] = (bi - li_1[i - 1] * z[i - 1]) / li[i]

    i = size - 1
    li_1[i - 1] = x_diff[-1] / li[i - 1]
    li[i] = math.sqrt(2 * x_diff[-1] - li_1[i - 1] * li_1[i - 1])
    z[i] = -li_1[i - 1] * z[i - 1] / li[i]

    z[-1] /= li[-1]
    for i in range(size - 2, -1, -1):
        z[i] = (z[i] - li_1[i] * z[i + 1]) / li[i]

    results: list[float] = []
    for x_ in x0:
        n = max(
            1,
            min(
                next(
                    (idx for idx, val in enumerate(x) if x_ <= val),
                    len(x),
                ),
                size - 1,
            ),
        )
        h = x[n] - x[n - 1]
        val = (
            z[n - 1] / (6 * h) * (x[n] - x_) ** 3
            + z[n] / (6 * h) * (x_ - x[n - 1]) ** 3
            + (y[n] / h - z[n] * h / 6) * (x_ - x[n - 1])
            + (y[n - 1] / h - z[n - 1] * h / 6) * (x[n] - x_)
        )
        results.append(round(val, 4))
    return results


def _splined_power_kw(second_of_day: float, capacity_kw: float) -> float:
    """Return instantaneous splined power in kW for *second_of_day*.

    Clamps to [0, capacity_kw] to avoid cubic overshoot at tails.
    """
    t = min(second_of_day, float(_SPLINE_X[-1]))
    y = [gf * capacity_kw for gf in GENERATION_FACTOR]
    return max(0.0, min(capacity_kw, _cubic_interp([t], _SPLINE_X, y)[0]))


def _seconds_since_midnight(tz: ZoneInfo) -> float:
    """Return elapsed seconds since local midnight."""
    now = datetime.now(tz)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return (now - midnight).total_seconds()


class SolcastSimBatteryModel:
    """Shared state model for battery/export simulation."""

    def __init__(
        self,
        sites: list[dict[str, Any]],
        export_factor: float,
        export_limit_kw: float,
        battery_capacity_kwh: float,
        battery_initial_soc: float,
        battery_max_charge_kw: float,
        battery_max_discharge_kw: float,
        house_load_kw: float,
        free_charge_kw: float = 0.0,
        free_charge_start_s: int = 11 * 3600,
        free_charge_end_s: int = 14 * 3600,
    ) -> None:
        """Initialize model state."""
        self.sites = sites
        self.export_factor = export_factor
        self.export_limit_kw = max(0.0, export_limit_kw)
        self.battery_capacity_kwh = max(0.0, battery_capacity_kwh)
        self.battery_max_charge_kw = max(0.0, battery_max_charge_kw)
        self.battery_max_discharge_kw = max(0.0, battery_max_discharge_kw)
        self.house_load_kw = max(0.0, house_load_kw)
        self.free_charge_kw = max(0.0, free_charge_kw)
        self.free_charge_start_s = free_charge_start_s
        self.free_charge_end_s = free_charge_end_s

        self.battery_energy_kwh = min(
            self.battery_capacity_kwh,
            max(0.0, self.battery_capacity_kwh * (battery_initial_soc / 100.0)),
        )
        self.export_power_kw = 0.0
        self.charge_power_kw = 0.0
        self.discharge_power_kw = 0.0
        self.battery_power_kw = 0.0
        self.grid_import_power_kw = 0.0

        self.export_energy_kwh = 0.0
        self.charge_energy_kwh = 0.0
        self.discharge_energy_kwh = 0.0
        self.grid_import_energy_kwh = 0.0
        self.free_grid_charge_power_kw = 0.0
        self.free_grid_charge_energy_kwh = 0.0
        self.last_t: float | None = None

    def prime_power_state(self, t: float) -> None:
        """Populate instantaneous power flows without advancing energy totals."""
        total_power_kw = sum(_splined_power_kw(t, site["capacity"]) for site in self.sites)

        surplus_kw = max(0.0, total_power_kw - self.house_load_kw)
        deficit_kw = max(0.0, self.house_load_kw - total_power_kw)

        charge_kw = 0.0
        discharge_kw = 0.0
        free_charge_kw = 0.0

        if self.battery_capacity_kwh > 0 and self.battery_energy_kwh < self.battery_capacity_kwh and surplus_kw > 0:
            charge_kw = min(surplus_kw, self.battery_max_charge_kw)
            surplus_kw -= charge_kw

        if (
            self.free_charge_start_s <= t < self.free_charge_end_s
            and self.battery_capacity_kwh > 0
            and self.battery_energy_kwh < self.battery_capacity_kwh
            and self.free_charge_kw > 0
        ):
            available_charge_kw = max(0.0, self.battery_max_charge_kw - charge_kw)
            free_charge_kw = min(available_charge_kw, self.free_charge_kw)

        if self.battery_capacity_kwh > 0 and self.battery_energy_kwh > 0 and deficit_kw > 0:
            discharge_kw = min(deficit_kw, self.battery_max_discharge_kw)

        battery_full = self.battery_capacity_kwh <= 0 or self.battery_energy_kwh >= self.battery_capacity_kwh - 1e-6
        export_kw = 0.0
        if battery_full and surplus_kw > 0:
            export_kw = min(surplus_kw * self.export_factor, self.export_limit_kw)

        self.export_power_kw = export_kw
        self.charge_power_kw = charge_kw
        self.discharge_power_kw = discharge_kw
        self.free_grid_charge_power_kw = free_charge_kw
        self.battery_power_kw = discharge_kw - charge_kw - free_charge_kw
        self.grid_import_power_kw = max(0.0, deficit_kw - discharge_kw)

    def restore_export_energy(self, value: float) -> None:
        """Restore total exported energy."""
        self.export_energy_kwh = max(self.export_energy_kwh, 0.0, value)

    def restore_charge_energy(self, value: float) -> None:
        """Restore total charged energy."""
        self.charge_energy_kwh = max(self.charge_energy_kwh, 0.0, value)

    def restore_discharge_energy(self, value: float) -> None:
        """Restore total discharged energy."""
        self.discharge_energy_kwh = max(self.discharge_energy_kwh, 0.0, value)

    def restore_battery_energy(self, value: float) -> None:
        """Restore battery stored energy."""
        self.battery_energy_kwh = min(self.battery_capacity_kwh, max(0.0, value))

    def restore_battery_soc(self, value: float) -> None:
        """Restore battery state of charge."""
        self.restore_battery_energy(self.battery_capacity_kwh * (value / 100.0))

    def restore_grid_import_energy(self, value: float) -> None:
        """Restore total grid import energy."""
        self.grid_import_energy_kwh = max(self.grid_import_energy_kwh, 0.0, value)

    def restore_free_charge_energy(self, value: float) -> None:
        """Restore total free-period grid charge energy."""
        self.free_grid_charge_energy_kwh = max(self.free_grid_charge_energy_kwh, 0.0, value)

    @property
    def battery_soc(self) -> float:
        """Return battery state of charge (%)."""
        if self.battery_capacity_kwh <= 0:
            return 100.0
        return min(100.0, max(0.0, (self.battery_energy_kwh / self.battery_capacity_kwh) * 100))

    def advance(self, t: float) -> None:
        """Advance simulation state to second-of-day *t*."""
        if self.last_t is None:
            self.last_t = t
            return

        dt_s = t - self.last_t
        if dt_s <= 0:
            self.last_t = t
            return

        dt_h = dt_s / 3600
        total_power_kw = sum(_splined_power_kw(t, site["capacity"]) for site in self.sites)

        surplus_kw = max(0.0, total_power_kw - self.house_load_kw)
        deficit_kw = max(0.0, self.house_load_kw - total_power_kw)

        charge_kw = 0.0
        discharge_kw = 0.0

        if self.battery_capacity_kwh > 0 and surplus_kw > 0:
            remaining_kwh = max(0.0, self.battery_capacity_kwh - self.battery_energy_kwh)
            max_charge_by_capacity_kw = remaining_kwh / dt_h if dt_h > 0 else 0.0
            charge_kw = min(surplus_kw, self.battery_max_charge_kw, max_charge_by_capacity_kw)
            self.battery_energy_kwh += charge_kw * dt_h
            surplus_kw -= charge_kw

        # Free-power window (configurable, local time): top up battery from grid at no cost.
        free_charge_kw = 0.0
        if self.free_charge_start_s <= t < self.free_charge_end_s and self.battery_capacity_kwh > 0 and self.free_charge_kw > 0:
            remaining_kwh = max(0.0, self.battery_capacity_kwh - self.battery_energy_kwh)
            max_charge_by_capacity_kw = remaining_kwh / dt_h if dt_h > 0 else 0.0
            available_charge_kw = max(0.0, self.battery_max_charge_kw - charge_kw)
            free_charge_kw = min(available_charge_kw, self.free_charge_kw, max_charge_by_capacity_kw)
            self.battery_energy_kwh += free_charge_kw * dt_h

        if self.battery_capacity_kwh > 0 and deficit_kw > 0:
            max_discharge_by_energy_kw = self.battery_energy_kwh / dt_h if dt_h > 0 else 0.0
            discharge_kw = min(deficit_kw, self.battery_max_discharge_kw, max_discharge_by_energy_kw)
            self.battery_energy_kwh -= discharge_kw * dt_h

        self.battery_energy_kwh = min(
            self.battery_capacity_kwh,
            max(0.0, self.battery_energy_kwh),
        )
        battery_full = self.battery_capacity_kwh <= 0 or self.battery_energy_kwh >= self.battery_capacity_kwh - 1e-6

        export_kw = 0.0
        if battery_full and surplus_kw > 0:
            export_kw = min(surplus_kw * self.export_factor, self.export_limit_kw)

        self.export_power_kw = export_kw
        self.charge_power_kw = charge_kw
        self.discharge_power_kw = discharge_kw
        self.free_grid_charge_power_kw = free_charge_kw
        self.battery_power_kw = discharge_kw - charge_kw - free_charge_kw
        self.grid_import_power_kw = max(0.0, deficit_kw - discharge_kw)

        self.export_energy_kwh += export_kw * dt_h
        self.charge_energy_kwh += charge_kw * dt_h
        self.discharge_energy_kwh += discharge_kw * dt_h
        self.grid_import_energy_kwh += self.grid_import_power_kw * dt_h
        self.free_grid_charge_energy_kwh += free_charge_kw * dt_h
        self.last_t = t


# ---------------------------------------------------------------------------
# Sensor descriptors for model-backed entities
# ---------------------------------------------------------------------------


@dataclass
class _ModelSensorDesc:
    """Descriptor for a model-backed sensor."""

    unique_id: str
    name: str
    device_class: SensorDeviceClass
    state_class: SensorStateClass
    unit: str
    value_fn: Callable[[SolcastSimBatteryModel], float]
    restore_fn: Callable[[SolcastSimBatteryModel, float], None] | None = None
    # restore_display=True: use RestoreEntity to show the last known value on
    # restart even though the model state is managed by a different sensor.
    restore_display: bool = False
    # When True the sensor sets model.last_t on first add to kick off the sim.
    set_last_t: bool = False


_MODEL_SENSOR_DESCS: list[_ModelSensorDesc] = [
    _ModelSensorDesc(
        unique_id="solcast_sim_site_export_power",
        name="Site Export Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfPower.WATT,
        value_fn=lambda m: round(m.export_power_kw * 1000, 1),
    ),
    _ModelSensorDesc(
        unique_id="solcast_sim_export_energy",
        name="Site Export Energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=lambda m: round(m.export_energy_kwh, 6),
        restore_fn=lambda m, v: m.restore_export_energy(v),
        set_last_t=True,
    ),
    _ModelSensorDesc(
        unique_id="solcast_sim_battery_soc",
        name="Battery State of Charge",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        unit=PERCENTAGE,
        value_fn=lambda m: round(m.battery_soc, 2),
    ),
    _ModelSensorDesc(
        unique_id="solcast_sim_battery_energy",
        name="Battery Stored Energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=lambda m: round(m.battery_energy_kwh, 6),
        restore_fn=lambda m, v: m.restore_battery_energy(v),
    ),
    _ModelSensorDesc(
        unique_id="solcast_sim_battery_power",
        name="Battery Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfPower.WATT,
        value_fn=lambda m: round(m.battery_power_kw * 1000, 1),
    ),
    _ModelSensorDesc(
        unique_id="solcast_sim_battery_charge_energy",
        name="Battery Charge Energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=lambda m: round(m.charge_energy_kwh, 6),
        restore_fn=lambda m, v: m.restore_charge_energy(v),
    ),
    _ModelSensorDesc(
        unique_id="solcast_sim_battery_discharge_energy",
        name="Battery Discharge Energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=lambda m: round(m.discharge_energy_kwh, 6),
        restore_fn=lambda m, v: m.restore_discharge_energy(v),
    ),
    _ModelSensorDesc(
        unique_id="solcast_sim_grid_consumption_power",
        name="Grid Consumption Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfPower.WATT,
        value_fn=lambda m: round(m.grid_import_power_kw * 1000, 1),
    ),
    _ModelSensorDesc(
        unique_id="solcast_sim_grid_consumption_energy",
        name="Grid Consumption Energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=lambda m: round(m.grid_import_energy_kwh, 6),
        restore_fn=lambda m, v: m.restore_grid_import_energy(v),
    ),
    _ModelSensorDesc(
        unique_id="solcast_sim_free_charge_power",
        name="Free Charge Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfPower.WATT,
        value_fn=lambda m: round(m.free_grid_charge_power_kw * 1000, 1),
    ),
    _ModelSensorDesc(
        unique_id="solcast_sim_free_charge_energy",
        name="Free Charge Energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=lambda m: round(m.free_grid_charge_energy_kwh, 6),
        restore_fn=lambda m, v: m.restore_free_charge_energy(v),
    ),
]


# ---------------------------------------------------------------------------
# Model sensor base classes
# ---------------------------------------------------------------------------


class _ModelSensorMixin(SensorEntity):
    """Shared initialiser and interval logic for model-backed sensors."""

    _attr_should_poll = False

    def _init_desc(
        self,
        desc: _ModelSensorDesc,
        model: SolcastSimBatteryModel,
        tz: ZoneInfo,
    ) -> None:
        """Populate sensor attributes from the descriptor."""
        self._desc = desc
        self._model = model
        self._tz = tz
        self._attr_unique_id = desc.unique_id
        self._attr_name = desc.name
        self._attr_device_class = desc.device_class
        self._attr_state_class = desc.state_class
        self._attr_native_unit_of_measurement = desc.unit
        # Avoid flashing synthetic initialization values at startup for
        # sensors that restore state.
        if desc.restore_fn is not None or desc.restore_display:
            self._attr_native_value = None
        else:
            self._attr_native_value = desc.value_fn(model)

    @callback
    def _handle_interval(self, _now: datetime) -> None:
        """Advance model and push new state."""
        self._model.advance(_seconds_since_midnight(self._tz))
        self._attr_native_value = self._desc.value_fn(self._model)
        self.async_write_ha_state()


class _ModelSensor(_ModelSensorMixin):
    """Model-backed sensor without state restore."""

    def __init__(self, desc: _ModelSensorDesc, model: SolcastSimBatteryModel, tz: ZoneInfo) -> None:
        """Initialize."""
        self._init_desc(desc, model, tz)

    async def async_added_to_hass(self) -> None:
        """Register periodic update."""
        if self._desc.set_last_t:
            self._model.last_t = _seconds_since_midnight(self._tz)
        self.async_on_remove(async_track_time_interval(self.hass, self._handle_interval, UPDATE_INTERVAL))


class _RestoreModelSensor(_ModelSensorMixin, RestoreEntity):
    """Model-backed sensor that restores accumulated state on HA restart."""

    def __init__(self, desc: _ModelSensorDesc, model: SolcastSimBatteryModel, tz: ZoneInfo) -> None:
        """Initialize."""
        self._init_desc(desc, model, tz)

    async def async_added_to_hass(self) -> None:
        """Restore previous state then register periodic update."""
        cache_state: tuple[float, datetime] | None = None

        if (last_state := await self.async_get_last_state()) is not None:
            with contextlib.suppress(ValueError, TypeError):
                ts = last_state.last_updated or last_state.last_changed
                if ts is not None:
                    cache_state = (float(last_state.state), ts)

        recorder_state: tuple[float, datetime] | None = None
        if self.entity_id is not None:
            recorder_state = await _recorder_sensor_value(self.hass, self.entity_id)

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
            restored_value = _select_measurement_restore_value(cache_state, recorder_state)

        if restored_value is not None and self._desc.restore_fn is not None:
            self._desc.restore_fn(self._model, restored_value)

        if restored_value is not None:
            self._attr_native_value = restored_value
        else:
            self._attr_native_value = self._desc.value_fn(self._model)
        if self._desc.set_last_t:
            self._model.last_t = _seconds_since_midnight(self._tz)
        self.async_on_remove(async_track_time_interval(self.hass, self._handle_interval, UPDATE_INTERVAL))


class _ExportEnergySensor(_RestoreModelSensor):
    """Site export energy sensor - adds extra debug attributes."""

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


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Solcast PV SimCity sensors from a config entry."""
    config = {**entry.data, **entry.options}
    api_key: str = config.get("api_key", "1")
    export_factor: float = float(config.get("export_factor", 1.0))
    export_limit_kw: float = float(config.get("export_limit_kw", 5.0))
    battery_capacity_kwh: float = float(config.get("battery_capacity_kwh", 13.5))
    battery_initial_soc: float = float(config.get("battery_initial_soc", 50.0))
    battery_max_charge_kw: float = float(config.get("battery_max_charge_kw", 5.0))
    battery_max_discharge_kw: float = float(config.get("battery_max_discharge_kw", 5.0))
    house_load_kw: float = float(config.get("house_load_kw", 1.0))
    free_charge_kw: float = float(config.get("free_charge_kw", battery_max_charge_kw))
    free_charge_start_s: int = _time_str_to_seconds(config.get("free_charge_start", "11:00:00"))
    free_charge_end_s: int = _time_str_to_seconds(config.get("free_charge_end", "14:00:00"))
    tz = ZoneInfo(config.get("timezone", "Australia/Melbourne"))

    if api_key not in API_KEY_SITES:
        raise ValueError(f"solcast_sim: api_key '{api_key}' not found in SimCity data. Available keys: {list(API_KEY_SITES)}")

    sites: list[dict[str, Any]] = API_KEY_SITES[api_key]["sites"]
    model = SolcastSimBatteryModel(
        sites,
        export_factor,
        export_limit_kw,
        battery_capacity_kwh,
        battery_initial_soc,
        battery_max_charge_kw,
        battery_max_discharge_kw,
        house_load_kw,
        free_charge_kw,
        free_charge_start_s,
        free_charge_end_s,
    )
    await _prime_model_from_restore_state(hass, entry.domain, model)
    model.prime_power_state(_seconds_since_midnight(tz))

    entities: list[SensorEntity] = []
    for site in sites:
        entities.append(SolcastSimPowerSensor(site, tz))
        entities.append(SolcastSimEnergySensor(site, tz))
    entities.append(SolcastSimTotalPowerSensor(sites, tz))
    entities.append(SolcastSimTotalEnergySensor(sites, tz))
    entities.append(SolcastSimBatteryCapacitySensor(model))

    for desc in _MODEL_SENSOR_DESCS:
        if desc.set_last_t:
            entities.append(_ExportEnergySensor(desc, model, tz))
        elif desc.restore_fn is not None or desc.restore_display:
            entities.append(_RestoreModelSensor(desc, model, tz))
        else:
            entities.append(_ModelSensor(desc, model, tz))

    async_add_entities(entities)


# ---------------------------------------------------------------------------
# Per-site sensors
# ---------------------------------------------------------------------------


class SolcastSimPowerSensor(SensorEntity):
    """Instantaneous splined power sensor for a simulated PV site (W)."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_should_poll = False

    def __init__(self, site: dict[str, Any], tz: ZoneInfo) -> None:
        """Initialize the power sensor."""
        self._site = site
        self._tz = tz
        self._attr_unique_id = f"solcast_sim_{site['resource_id']}_power"
        self._attr_name = f"{site['name']} Generation Power"
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
        t = _seconds_since_midnight(self._tz)
        power_kw = _splined_power_kw(t, self._site["capacity"])
        self._attr_native_value = round(power_kw * 1000, 1)


class SolcastSimTotalPowerSensor(SensorEntity):
    """Instantaneous total PV generation power across all simulated sites (W)."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_should_poll = False

    def __init__(self, sites: list[dict[str, Any]], tz: ZoneInfo) -> None:
        """Initialize the total power sensor."""
        self._sites = sites
        self._tz = tz
        self._attr_unique_id = "solcast_sim_total_generation_power"
        self._attr_name = "Total PV Generation Power"
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
        t = _seconds_since_midnight(self._tz)
        total_power_kw = sum(_splined_power_kw(t, site["capacity"]) for site in self._sites)
        self._attr_native_value = round(total_power_kw * 1000, 1)


class SolcastSimEnergySensor(RestoreEntity, SensorEntity):
    """Cumulative energy sensor (total_increasing, kWh) for a simulated PV site."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_should_poll = False

    def __init__(self, site: dict[str, Any], tz: ZoneInfo) -> None:
        """Initialize the energy sensor."""
        self._site = site
        self._tz = tz
        self._attr_unique_id = f"solcast_sim_{site['resource_id']}_energy"
        self._attr_name = f"{site['name']} Generation Energy"
        self._attr_native_value: float = 0.0
        self._last_t: float | None = None

    async def async_added_to_hass(self) -> None:
        """Restore last known accumulated value then start ticking."""
        if (last_state := await self.async_get_last_state()) is not None:
            try:
                self._attr_native_value = float(last_state.state)
            except (ValueError, TypeError):
                self._attr_native_value = 0.0

        self._last_t = _seconds_since_midnight(self._tz)
        self.async_on_remove(async_track_time_interval(self.hass, self._handle_interval, UPDATE_INTERVAL))

    @callback
    def _handle_interval(self, _now: datetime) -> None:
        self._accumulate()
        self.async_write_ha_state()

    def _accumulate(self) -> None:
        """Add delta energy for the elapsed interval."""
        t = _seconds_since_midnight(self._tz)
        if self._last_t is not None:
            dt_s = t - self._last_t
            if dt_s < 0:
                # Midnight rollover - skip this tick to avoid a backward jump.
                self._last_t = t
                return
            power_kw = _splined_power_kw(t, self._site["capacity"])
            delta_kwh = power_kw * (dt_s / 3600)
            self._attr_native_value = round((self._attr_native_value or 0.0) + max(0.0, delta_kwh), 6)
        self._last_t = t


class SolcastSimTotalEnergySensor(RestoreEntity, SensorEntity):
    """Cumulative total PV generation energy across all simulated sites (kWh)."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_should_poll = False

    def __init__(self, sites: list[dict[str, Any]], tz: ZoneInfo) -> None:
        """Initialize the total energy sensor."""
        self._sites = sites
        self._tz = tz
        self._attr_unique_id = "solcast_sim_total_generation_energy"
        self._attr_name = "Total PV Generation Energy"
        self._attr_native_value: float = 0.0
        self._last_t: float | None = None

    async def async_added_to_hass(self) -> None:
        """Restore last known accumulated value then start ticking."""
        if (last_state := await self.async_get_last_state()) is not None:
            try:
                self._attr_native_value = float(last_state.state)
            except (ValueError, TypeError):
                self._attr_native_value = 0.0

        self._last_t = _seconds_since_midnight(self._tz)
        self.async_on_remove(async_track_time_interval(self.hass, self._handle_interval, UPDATE_INTERVAL))

    @callback
    def _handle_interval(self, _now: datetime) -> None:
        self._accumulate()
        self.async_write_ha_state()

    def _accumulate(self) -> None:
        """Add delta total energy for the elapsed interval."""
        t = _seconds_since_midnight(self._tz)
        if self._last_t is not None:
            dt_s = t - self._last_t
            if dt_s < 0:
                self._last_t = t
                return
            total_power_kw = sum(_splined_power_kw(t, site["capacity"]) for site in self._sites)
            delta_kwh = total_power_kw * (dt_s / 3600)
            self._attr_native_value = round((self._attr_native_value or 0.0) + max(0.0, delta_kwh), 6)
        self._last_t = t


class SolcastSimBatteryCapacitySensor(SensorEntity):
    """Configured battery total capacity (kWh)."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_should_poll = False

    def __init__(self, model: SolcastSimBatteryModel) -> None:
        """Initialize the battery capacity sensor."""
        self._attr_unique_id = "solcast_sim_battery_capacity"
        self._attr_name = "Battery Capacity"
        self._attr_native_value = round(model.battery_capacity_kwh, 3)
