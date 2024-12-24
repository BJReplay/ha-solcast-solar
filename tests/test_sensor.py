"""Tests for the Solcast Solar sensors."""

from datetime import datetime as dt
import logging

import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.components.sensor import SensorStateClass
from homeassistant.components.solcast_solar.const import DOMAIN
from homeassistant.const import STATE_UNAVAILABLE, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import (
    DEFAULT_INPUT1,
    DEFAULT_INPUT2,
    async_cleanup_integration_tests,
    async_init_integration,
)

_LOGGER = logging.getLogger(__name__)


SENSORS: dict[str, dict] = {
    "forecast_today": {
        "state": {"1": "42.552", "2": "58.509"},
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "state_class": SensorStateClass.TOTAL,
    },
    "peak_forecast_today": {
        "state": {"1": "7200", "2": "9900"},
        "unit_of_measurement": UnitOfPower.WATT,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "peak_time_today": {"state": {"1": "2024-01-01T02:00:00+00:00", "2": "2024-01-01T02:00:00+00:00"}},
    "forecast_this_hour": {
        "state": {"1": "7200", "2": "9900"},
        "unit_of_measurement": UnitOfEnergy.WATT_HOUR,
    },
    "forecast_remaining_today": {
        "state": {"1": "23.6817", "2": "32.5624"},
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
    },
    "forecast_next_hour": {
        "state": {"1": "6732", "2": "9256"},
        "unit_of_measurement": UnitOfEnergy.WATT_HOUR,
    },
    "forecast_next_x_hours": {
        "state": {"1": "13748", "2": "18904"},
        "unit_of_measurement": UnitOfEnergy.WATT_HOUR,
    },
    "forecast_tomorrow": {
        "state": {"1": "42.552", "2": "58.509"},
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "state_class": SensorStateClass.TOTAL,
    },
    "peak_forecast_tomorrow": {
        "state": {"1": "7200", "2": "9900"},
        "unit_of_measurement": UnitOfPower.WATT,
    },
    "peak_time_tomorrow": {"state": {"1": "2024-01-01T02:00:00+00:00", "2": "2024-01-01T02:00:00+00:00"}},
    "api_used": {"state": {"1": "4", "2": "4"}},
    "api_limit": {"state": {"1": "10", "2": "10"}},
    "api_last_polled": {},
    "forecast_day_3": {
        "state": {"1": "42.552", "2": "58.509"},
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "state_class": SensorStateClass.TOTAL,
    },
    "forecast_day_4": {
        "state": {"1": "42.552", "2": "58.509"},
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "state_class": SensorStateClass.TOTAL,
    },
    "forecast_day_5": {
        "state": {"1": "42.552", "2": "58.509"},
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "state_class": SensorStateClass.TOTAL,
    },
    "forecast_day_6": {
        "state": {"1": "42.552", "2": "58.509"},
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "state_class": SensorStateClass.TOTAL,
    },
    "forecast_day_7": {
        "state": {"1": "42.552", "2": "58.509"},
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "state_class": SensorStateClass.TOTAL,
    },
    "power_now": {
        "state": {"1": "7221", "2": "9928"},
        "unit_of_measurement": UnitOfPower.WATT,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "power_in_30_minutes": {
        "state": {"1": "7158", "2": "9842"},
        "unit_of_measurement": UnitOfPower.WATT,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "power_in_1_hour": {
        "state": {"1": "6842", "2": "9408"},
        "unit_of_measurement": UnitOfPower.WATT,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    # "weather_description": {},
}


@pytest.mark.parametrize(
    ("key", "settings"),
    [
        ("1", DEFAULT_INPUT1),
        ("2", DEFAULT_INPUT2),
    ],
)
async def test_sensor_states(
    recorder_mock: Recorder, hass: HomeAssistant, key: str, settings: dict, entity_registry: er.EntityRegistry
) -> None:
    """Test states of sensors including expected state class and unit of measurement."""

    entry = await async_init_integration(hass, settings)

    assert len(hass.states.async_all("sensor")) == len(SENSORS) + (3 if key == "1" else 4)

    for sensor, attrs in SENSORS.items():
        state = hass.states.get(f"sensor.solcast_pv_forecast_{sensor}")
        assert state
        assert state.state != STATE_UNAVAILABLE
        if "state" in attrs:
            test = state.state
            try:
                test = dt.fromisoformat(test)
                test = test.replace(year=2024, month=1, day=1).isoformat()
            except:  # noqa: E722
                pass
            assert test == attrs["state"][key]
        if "unit_of_measurement" in attrs:
            assert state.attributes["unit_of_measurement"] == attrs["unit_of_measurement"]
        if "state_class" in attrs:
            assert state.attributes["state_class"] == attrs["state_class"]

    assert await async_cleanup_integration_tests(hass, hass.data[DOMAIN][entry.entry_id].solcast._config_dir)
