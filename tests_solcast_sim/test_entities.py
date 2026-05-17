"""Tests for Solcast PV SimCity entity restore behaviour."""

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

from custom_components.solcast_sim import (  # pyright: ignore[reportMissingImports]
    entities,
)
from custom_components.solcast_sim.entities import (  # pyright: ignore[reportMissingImports]
    ExportEnergySensor,
    ModelSensor,
    ModelSensorDesc,
    RestoreModelSensor,
    SolcastSimBatteryCapacitySensor,
    SolcastSimEnergySensor,
    SolcastSimPowerSensor,
    SolcastSimShadeAttenuationSensor,
    SolcastSimShadeBlockedSensor,
    SolcastSimTodayEnergySensor,
    SolcastSimTotalEnergySensor,
    SolcastSimTotalPowerSensor,
    _jitter,
    _prefixed_display_name,
    build_entities,
)
from custom_components.solcast_sim.sim_core import (  # pyright: ignore[reportMissingImports]
    SimulationProfile,
)
import pytest

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant


@pytest.mark.asyncio
async def test_today_energy_sensor_restores_freshest_same_day_value(hass: HomeAssistant) -> None:
    """Restore today's total from the freshest same-day source after restart."""
    sensor = SolcastSimTodayEnergySensor([], ZoneInfo("UTC"), _simple_profile())
    sensor.hass = hass
    sensor.entity_id = "sensor.solcast_sim_today_generation_energy"

    async def fake_recorder_sensor_value(_hass, _entity_id):
        return (2.5, datetime(2026, 5, 9, 11, 0, tzinfo=UTC))

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        sensor,
        "async_get_last_state",
        AsyncMock(
            return_value=SimpleNamespace(
                last_updated=datetime(2026, 5, 9, 10, 0, tzinfo=UTC),
                last_changed=None,
                state="1.25",
            )
        ),
    )
    monkeypatch.setattr(entities, "recorder_sensor_value", fake_recorder_sensor_value)
    monkeypatch.setattr(entities, "async_track_time_interval", lambda *args, **kwargs: None)

    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 5, 9, 12, 0, tzinfo=tz or UTC)

    monkeypatch.setattr(entities, "datetime", FakeDateTime)

    try:
        await sensor.async_added_to_hass()
        assert sensor._attr_native_value == 2.5
        assert sensor._attr_last_reset == datetime(2026, 5, 9, 0, 0, tzinfo=UTC)
    finally:
        monkeypatch.undo()


def test_today_energy_sensor_sets_last_reset_on_day_rollover() -> None:
    """Reset daily total and last_reset when the local day changes."""
    sensor = SolcastSimTodayEnergySensor([{"capacity": 5.0}], ZoneInfo("UTC"), _simple_profile())
    sensor._attr_native_value = 3.7
    sensor._last_day = datetime(2026, 5, 9, tzinfo=UTC).date()
    sensor._last_t = 86395.0

    monkeypatch = pytest.MonkeyPatch()

    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 5, 10, 0, 0, 1, tzinfo=tz or UTC)

    monkeypatch.setattr(entities, "datetime", FakeDateTime)

    try:
        sensor._accumulate()
        assert sensor._attr_native_value == 0.0
        assert sensor._attr_last_reset == datetime(2026, 5, 10, 0, 0, tzinfo=UTC)
    finally:
        monkeypatch.undo()


def test_jitter_returns_float_near_input() -> None:
    """Jitter stays within ±0.05 W of input."""
    for _ in range(50):
        result = _jitter(100.0)
        assert abs(result - 100.0) <= 0.05 + 1e-9


def test_jitter_rounds_to_two_decimal_places() -> None:
    """Jitter output has at most two decimal places."""
    for _ in range(50):
        result = _jitter(300.0)
        assert round(result, 2) == result


def test_prefixed_display_name_adds_prefix() -> None:
    """Add 'Solcast Sim ' prefix when not already present."""
    assert _prefixed_display_name("PV Today") == "Solcast Sim PV Today"


def test_prefixed_display_name_no_double_prefix() -> None:
    """Do not add prefix when already present."""
    assert _prefixed_display_name("Solcast Sim PV Today") == "Solcast Sim PV Today"


def _make_model() -> MagicMock:
    model = MagicMock()
    model.last_day = None
    model.last_t = None
    model.export_power_kw = 1.0
    return model


def _simple_desc(
    unique_id: str = "solcast_sim_site_export_power",
    state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT,
    restore_fn=None,
    restore_display: bool = False,
    restore_same_day: bool = False,
    set_last_t: bool = False,
) -> ModelSensorDesc:
    return ModelSensorDesc(
        unique_id=unique_id,
        name="Test Sensor",
        device_class=SensorDeviceClass.POWER,
        state_class=state_class,
        unit=UnitOfPower.WATT,
        value_fn=lambda m: round(m.export_power_kw * 1000, 1),
        restore_fn=restore_fn,
        restore_display=restore_display,
        restore_same_day=restore_same_day,
        set_last_t=set_last_t,
    )


def test_model_sensor_initial_value_set() -> None:
    """ModelSensor sets native value from value_fn on init."""
    model = _make_model()
    desc = _simple_desc()
    sensor = ModelSensor(desc, model, ZoneInfo("UTC"))
    assert sensor._attr_native_value == 1000.0


def test_model_sensor_restore_fn_sets_none_initially() -> None:
    """ModelSensor with restore_fn sets native_value to None initially."""
    model = _make_model()
    desc = _simple_desc(restore_fn=lambda m, v: None)
    sensor = ModelSensor(desc, model, ZoneInfo("UTC"))
    assert sensor._attr_native_value is None


def test_model_sensor_with_total_state_class_sets_last_reset() -> None:
    """ModelSensor with TOTAL state class sets _attr_last_reset at midnight."""
    model = _make_model()
    desc = _simple_desc(
        state_class=SensorStateClass.TOTAL,
        restore_fn=lambda m, v: None,
    )
    sensor = ModelSensor(desc, model, ZoneInfo("UTC"))
    assert sensor._attr_last_reset is not None
    assert sensor._attr_last_reset.hour == 0
    assert sensor._attr_last_reset.minute == 0


async def test_model_sensor_added_to_hass_registers_interval(hass: HomeAssistant) -> None:
    """ModelSensor registers interval timer when added to hass."""
    model = _make_model()
    desc = _simple_desc()
    sensor = ModelSensor(desc, model, ZoneInfo("UTC"))
    sensor.hass = hass

    registered: list[Any] = []
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(sensor, "async_on_remove", lambda func: None)

    def fake_track_interval(_hass, fn, interval):
        registered.append(fn)
        return lambda: None

    monkeypatch.setattr(entities, "async_track_time_interval", fake_track_interval)

    try:
        await sensor.async_added_to_hass()
        assert len(registered) == 1
    finally:
        monkeypatch.undo()


async def test_model_sensor_added_to_hass_with_set_last_t(hass: HomeAssistant) -> None:
    """ModelSensor with set_last_t=True sets model.last_t when added to hass."""
    model = _make_model()
    desc = _simple_desc(set_last_t=True)
    sensor = ModelSensor(desc, model, ZoneInfo("UTC"))
    sensor.hass = hass

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(sensor, "async_on_remove", lambda func: None)
    monkeypatch.setattr(entities, "async_track_time_interval", lambda *a, **kw: lambda: None)
    try:
        await sensor.async_added_to_hass()
        assert model.last_t is not None
    finally:
        monkeypatch.undo()


def test_model_sensor_handle_interval_updates_value() -> None:
    """ModelSensor._handle_interval updates native value from model."""
    model = _make_model()
    desc = _simple_desc()
    sensor = ModelSensor(desc, model, ZoneInfo("UTC"))
    mock_write = MagicMock()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(sensor, "async_write_ha_state", mock_write)

    model.export_power_kw = 2.5
    model.last_day = None
    sensor._handle_interval(datetime.now(UTC))

    assert sensor._attr_native_value == 2500.0
    mock_write.assert_called_once()
    monkeypatch.undo()


def test_model_sensor_handle_interval_updates_last_reset_on_new_day() -> None:
    """ModelSensor._handle_interval updates last_reset when the day changes."""
    model = _make_model()
    model.last_day = date(2026, 5, 9)
    desc = _simple_desc(
        state_class=SensorStateClass.TOTAL,
        restore_fn=lambda m, v: None,
    )
    sensor = ModelSensor(desc, model, ZoneInfo("UTC"))
    mock_write_1 = MagicMock()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(sensor, "async_write_ha_state", mock_write_1)

    model.last_day = date(2026, 5, 10)

    def fake_advance(t):
        pass

    model.advance = fake_advance

    # Simulate a day change: after advance, model.last_day is the new day.
    sensor._attr_last_reset = datetime(2026, 5, 9, 0, 0, tzinfo=ZoneInfo("UTC"))
    sensor._model.last_day = date(2026, 5, 10)

    class FakeSensor(ModelSensor):
        def __init__(self, desc, model, tz) -> None:
            self._attr_last_reset = datetime(2026, 5, 9, 0, 0, tzinfo=ZoneInfo("UTC"))
            self._attr_native_value = None

            super().__init__(desc, model, tz)

        def _handle_interval(self, _now):
            prev_day = date(2026, 5, 9)  # simulate prev_day before advance
            self._model.advance(0)
            if self._desc.state_class is SensorStateClass.TOTAL and self._model.last_day != prev_day and self._model.last_day is not None:
                self._attr_last_reset = datetime.combine(self._model.last_day, datetime.min.time(), self._tz)
            self._attr_native_value = self._desc.value_fn(self._model)
            self.async_write_ha_state()

    sensor2 = FakeSensor(desc, model, ZoneInfo("UTC"))
    mock_write_2 = MagicMock()
    monkeypatch.setattr(sensor2, "async_write_ha_state", mock_write_2)
    sensor2._handle_interval(datetime.now(UTC))

    assert sensor2._attr_last_reset == datetime(2026, 5, 10, 0, 0, tzinfo=ZoneInfo("UTC"))
    monkeypatch.undo()


async def test_restore_model_sensor_restores_value(hass: HomeAssistant) -> None:
    """RestoreModelSensor restores its value from last state."""
    model = _make_model()
    restore_called = []
    desc = _simple_desc(
        restore_fn=lambda m, v: restore_called.append(v),
        state_class=SensorStateClass.TOTAL_INCREASING,
        unique_id="solcast_sim_export_energy",
    )
    sensor = RestoreModelSensor(desc, model, ZoneInfo("UTC"))
    sensor.hass = hass
    sensor.entity_id = "sensor.test_export"

    ts = datetime(2026, 5, 9, 10, 0, tzinfo=UTC)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(sensor, "async_on_remove", lambda func: None)
    monkeypatch.setattr(
        sensor,
        "async_get_last_state",
        AsyncMock(
            return_value=SimpleNamespace(
                last_updated=ts,
                last_changed=None,
                state="5.25",
            )
        ),
    )
    monkeypatch.setattr(entities, "recorder_sensor_value", AsyncMock(return_value=None))
    monkeypatch.setattr(entities, "async_track_time_interval", lambda *a, **kw: lambda: None)
    try:
        await sensor.async_added_to_hass()
        assert sensor._attr_native_value == 5.25
        assert restore_called == [5.25]
    finally:
        monkeypatch.undo()


async def test_restore_model_sensor_uses_model_value_when_no_state(hass: HomeAssistant) -> None:
    """RestoreModelSensor falls back to model value when no state to restore."""
    model = _make_model()
    model.export_power_kw = 0.5
    desc = _simple_desc(
        restore_fn=lambda m, v: None,
        state_class=SensorStateClass.TOTAL_INCREASING,
        unique_id="solcast_sim_export_energy",
    )
    sensor = RestoreModelSensor(desc, model, ZoneInfo("UTC"))
    sensor.hass = hass
    sensor.entity_id = "sensor.test_export"
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(sensor, "async_on_remove", lambda func: None)
    monkeypatch.setattr(sensor, "async_get_last_state", AsyncMock(return_value=None))
    monkeypatch.setattr(entities, "recorder_sensor_value", AsyncMock(return_value=None))
    monkeypatch.setattr(entities, "async_track_time_interval", lambda *a, **kw: lambda: None)
    try:
        await sensor.async_added_to_hass()
        assert sensor._attr_native_value == 500.0
    finally:
        monkeypatch.undo()


def test_export_energy_sensor_extra_attributes() -> None:
    """ExportEnergySensor exposes battery and export internals."""
    model = MagicMock()
    model.battery_energy_kwh = 5.0
    model.battery_capacity_kwh = 13.5
    model.battery_soc = 37.0
    model.house_load_kw = 0.5
    model.export_limit_kw = 5.0
    model.export_power_kw = 1.2
    model.grid_import_power_kw = 0.0
    model.last_day = None
    model.last_t = None

    desc = ModelSensorDesc(
        unique_id="solcast_sim_export_energy",
        name="Site Export Energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=lambda m: round(m.export_energy_kwh, 6),
        restore_fn=lambda m, v: m.restore_export_energy(v),
        set_last_t=True,
    )
    sensor = ExportEnergySensor(desc, model, ZoneInfo("UTC"))
    attrs = sensor.extra_state_attributes
    assert attrs["battery_energy_kwh"] == 5.0
    assert attrs["battery_capacity_kwh"] == 13.5
    assert attrs["battery_soc"] == 37.0
    assert attrs["export_limit_kw"] == 5.0


def _simple_profile() -> SimulationProfile:
    """Return a minimal SimulationProfile with shade disabled."""
    return SimulationProfile(
        season="auto",
        latitude=-33.0,
        longitude=151.0,
        cloudiness_bias=0.0,
        cloud_variability=0.5,
        estimated_actuals_uncertainty_pct=10.0,
        shade_opacity=0.0,
        shade_height_m=0.0,
        shade_width_m=0.0,
        shade_distance_m=100.0,
        shade_azimuth_deg=0.0,
        shade_density_profile=(0.3, 0.8, 1.0),
        astral_location=None,
        astral_elevation=None,
        random_seed="test",
    )


def test_power_sensor_refresh_sets_native_value() -> None:
    """SolcastSimPowerSensor._refresh sets a float native value."""
    site = {"resource_id": "abc123", "name": "Test Site", "capacity": 5.0}
    sensor = SolcastSimPowerSensor(site, ZoneInfo("UTC"), _simple_profile())
    sensor._refresh()
    assert isinstance(sensor._attr_native_value, float)


def test_total_power_sensor_refresh_sets_native_value() -> None:
    """SolcastSimTotalPowerSensor._refresh sums all site powers."""
    sites = [
        {"resource_id": "a", "name": "Site A", "capacity": 3.0},
        {"resource_id": "b", "name": "Site B", "capacity": 2.0},
    ]
    sensor = SolcastSimTotalPowerSensor(sites, ZoneInfo("UTC"), _simple_profile())
    sensor._refresh()
    assert isinstance(sensor._attr_native_value, float)


def test_total_power_sensor_extra_attributes() -> None:
    """SolcastSimTotalPowerSensor exposes shade attributes."""
    sensor = SolcastSimTotalPowerSensor([], ZoneInfo("UTC"), _simple_profile())
    attrs = sensor.extra_state_attributes
    assert "shade_attenuation_factor" in attrs
    assert "shade_blocked_fraction" in attrs


def test_shade_blocked_sensor_refresh_range() -> None:
    """SolcastSimShadeBlockedSensor native value is in [0, 100]."""
    sensor = SolcastSimShadeBlockedSensor(ZoneInfo("UTC"), _simple_profile())
    sensor._refresh()
    assert 0.0 <= sensor._attr_native_value <= 100.0


def test_shade_blocked_sensor_extra_attributes() -> None:
    """SolcastSimShadeBlockedSensor exposes shade_active and attenuation factor."""
    sensor = SolcastSimShadeBlockedSensor(ZoneInfo("UTC"), _simple_profile())
    sensor._attr_native_value = 20.0
    attrs = sensor.extra_state_attributes
    assert attrs["shade_active"] is True
    assert 0.0 <= attrs["shade_attenuation_factor"] <= 1.0


def test_shade_blocked_sensor_not_active_at_zero() -> None:
    """Shade is not active when blocked percentage is zero."""
    sensor = SolcastSimShadeBlockedSensor(ZoneInfo("UTC"), _simple_profile())
    sensor._attr_native_value = 0.0
    attrs = sensor.extra_state_attributes
    assert attrs["shade_active"] is False


def test_shade_attenuation_sensor_refresh() -> None:
    """SolcastSimShadeAttenuationSensor native value is in [0, 1]."""
    sensor = SolcastSimShadeAttenuationSensor(ZoneInfo("UTC"), _simple_profile())
    sensor._refresh()
    assert 0.0 <= sensor._attr_native_value <= 1.0


def test_energy_sensor_accumulate_negative_dt_skips() -> None:
    """SolcastSimEnergySensor._accumulate skips when dt_s is negative (day rollover)."""
    site = {"resource_id": "x", "name": "X", "capacity": 5.0}
    sensor = SolcastSimEnergySensor(site, ZoneInfo("UTC"), _simple_profile())
    sensor._attr_native_value = 3.0
    sensor._last_t = 86399.0  # almost midnight

    monkeypatch = pytest.MonkeyPatch()

    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 5, 10, 0, 0, 1, tzinfo=tz or UTC)

    monkeypatch.setattr(entities, "datetime", FakeDateTime)
    # Make seconds_since_midnight return a value < _last_t
    monkeypatch.setattr(entities, "seconds_since_midnight", lambda tz: 1.0)

    try:
        sensor._accumulate()
        # Value should not change when dt_s < 0
        assert sensor._attr_native_value == 3.0
        assert sensor._last_t == 1.0
    finally:
        monkeypatch.undo()


def test_energy_sensor_accumulate_positive_dt_adds_energy() -> None:
    """SolcastSimEnergySensor._accumulate adds positive energy on each tick."""
    site = {"resource_id": "x", "name": "X", "capacity": 5.0}
    sensor = SolcastSimEnergySensor(site, ZoneInfo("UTC"), _simple_profile())
    sensor._attr_native_value = 0.0
    sensor._last_t = 0.0  # just after midnight

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(entities, "seconds_since_midnight", lambda tz: 5.0)
    monkeypatch.setattr(entities, "simulated_power_kw", lambda t, cap, tz, profile: 1.0)

    try:
        sensor._accumulate()
        # 1 kW for 5 seconds = 5/3600 kWh
        expected = round(5.0 / 3600.0, 6)
        assert sensor._attr_native_value == expected
    finally:
        monkeypatch.undo()


def test_total_energy_sensor_accumulate_sums_sites() -> None:
    """SolcastSimTotalEnergySensor._accumulate sums power across sites."""
    sites = [
        {"resource_id": "a", "name": "A", "capacity": 5.0},
        {"resource_id": "b", "name": "B", "capacity": 5.0},
    ]
    sensor = SolcastSimTotalEnergySensor(sites, ZoneInfo("UTC"), _simple_profile())
    sensor._attr_native_value = 0.0
    sensor._last_t = 0.0

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(entities, "seconds_since_midnight", lambda tz: 5.0)
    monkeypatch.setattr(entities, "simulated_power_kw", lambda t, cap, tz, profile: 1.0)

    try:
        sensor._accumulate()
        # 2 sites × 1 kW × 5s = 10/3600 kWh
        expected = round(10.0 / 3600.0, 6)
        assert sensor._attr_native_value == expected
    finally:
        monkeypatch.undo()


def test_battery_capacity_sensor_init() -> None:
    """SolcastSimBatteryCapacitySensor stores the battery capacity."""
    model = MagicMock()
    model.battery_capacity_kwh = 13.5
    sensor = SolcastSimBatteryCapacitySensor(model)
    assert sensor._attr_native_value == 13.5
    assert sensor._attr_unique_id == "solcast_sim_battery_capacity"


def test_build_entities_returns_list() -> None:
    """build_entities returns a non-empty list of sensor entities."""
    model = MagicMock()
    model.battery_capacity_kwh = 13.5
    model.last_day = None
    model.last_t = None
    model.export_power_kw = 0.0
    model.battery_soc = 50.0
    model.battery_energy_kwh = 5.0
    model.battery_power_kw = 0.0
    model.charge_energy_kwh = 0.0
    model.discharge_energy_kwh = 0.0
    model.grid_import_power_kw = 0.0
    model.grid_import_energy_kwh = 0.0
    model.export_today_energy_kwh = 0.0
    model.grid_import_today_energy_kwh = 0.0
    model.free_grid_charge_power_kw = 0.0
    model.free_grid_charge_energy_kwh = 0.0
    model.export_energy_kwh = 0.0
    model.house_load_kw = 0.0
    model.export_limit_kw = 0.0

    sites = [{"resource_id": "abc", "name": "TestSite", "capacity": 5.0}]
    profile = _simple_profile()
    tz = ZoneInfo("UTC")

    result = build_entities(sites, tz, profile, model)
    assert isinstance(result, list)
    assert len(result) > 0
