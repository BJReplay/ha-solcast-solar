"""Tests for the Solcast Solar sensors."""

import contextlib
import copy
from datetime import datetime as dt, timedelta
import logging

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.components.sensor import SensorStateClass
from homeassistant.components.solcast_solar.const import API_QUOTA, CUSTOM_HOUR_SENSOR
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.solcastapi import SolcastApi
from homeassistant.const import (
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfEnergy,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant

from . import (
    DEFAULT_INPUT1,
    DEFAULT_INPUT2,
    async_cleanup_integration_tests,
    async_init_integration,
)

_LOGGER = logging.getLogger(__name__)


# Site breakdown for 2222-2222-2222-2222 and 3333-3333-3333-3333 are identical.
SENSORS: dict[str, dict] = {
    "forecast_today": {
        "state": {"1": "42.552", "2": "58.509"},
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "state_class": SensorStateClass.TOTAL,
        "attributes": {
            "1": {"estimate": 42.552, "estimate10": 35.46, "estimate90": 47.28},
            "2": {"estimate": 58.509, "estimate10": 48.7575, "estimate90": 65.01},
        },
        "breakdown": {
            "1": {
                "1111-1111-1111-1111": 26.595,
                "estimate-1111-1111-1111-1111": 26.595,
                "estimate10-1111-1111-1111-1111": 22.1625,
                "estimate90-1111-1111-1111-1111": 29.55,
            },
            "2": {
                "2222-2222-2222-2222": 15.957,
                "estimate-2222-2222-2222-2222": 15.957,
                "estimate10-2222-2222-2222-2222": 13.2975,
                "estimate90-2222-2222-2222-2222": 17.73,
            },
        },
        "can_be_unavailable": True,
    },
    "peak_forecast_today": {
        "state": {"1": "7200", "2": "9900"},
        "unit_of_measurement": UnitOfPower.WATT,
        "state_class": SensorStateClass.MEASUREMENT,
        "attributes": {
            "1": {"estimate": 7200, "estimate10": 6000, "estimate90": 8000},
            "2": {"estimate": 9900, "estimate10": 8250, "estimate90": 11000},
        },
        "breakdown": {
            "1": {
                "1111-1111-1111-1111": 4500,
                "estimate-1111-1111-1111-1111": 4500,
                "estimate10-1111-1111-1111-1111": 3750,
                "estimate90-1111-1111-1111-1111": 5000,
            },
            "2": {
                "2222-2222-2222-2222": 2700,
                "estimate-2222-2222-2222-2222": 2700,
                "estimate10-2222-2222-2222-2222": 2250,
                "estimate90-2222-2222-2222-2222": 3000,
            },
        },
        "can_be_unavailable": True,
    },
    "peak_time_today": {
        "state": {"1": "2024-01-01T02:00:00+00:00", "2": "2024-01-01T02:00:00+00:00"},
        "attributes": {
            "1": {
                "estimate": "2024-01-01T02:00:00+00:00",
                "estimate10": "2024-01-01T02:00:00+00:00",
                "estimate90": "2024-01-01T02:00:00+00:00",
            },
            "2": {
                "estimate": "2024-01-01T02:00:00+00:00",
                "estimate10": "2024-01-01T02:00:00+00:00",
                "estimate90": "2024-01-01T02:00:00+00:00",
            },
        },
        "breakdown": {
            "1": {
                "1111-1111-1111-1111": "2024-01-01T02:00:00+00:00",
                "estimate-1111-1111-1111-1111": "2024-01-01T02:00:00+00:00",
                "estimate10-1111-1111-1111-1111": "2024-01-01T02:00:00+00:00",
                "estimate90-1111-1111-1111-1111": "2024-01-01T02:00:00+00:00",
            },
            "2": {
                "2222-2222-2222-2222": "2024-01-01T02:00:00+00:00",
                "estimate-2222-2222-2222-2222": "2024-01-01T02:00:00+00:00",
                "estimate10-2222-2222-2222-2222": "2024-01-01T02:00:00+00:00",
                "estimate90-2222-2222-2222-2222": "2024-01-01T02:00:00+00:00",
            },
        },
        "can_be_unavailable": True,
    },
    "forecast_this_hour": {
        "state": {"1": "7200", "2": "9900"},
        "unit_of_measurement": UnitOfEnergy.WATT_HOUR,
        "attributes": {
            "1": {"estimate": 7200, "estimate10": 6000, "estimate90": 8000},
            "2": {"estimate": 9900, "estimate10": 8250, "estimate90": 11000},
        },
        "breakdown": {
            "1": {
                "1111-1111-1111-1111": 4500,
                "estimate-1111-1111-1111-1111": 4500,
                "estimate10-1111-1111-1111-1111": 3750,
                "estimate90-1111-1111-1111-1111": 5000,
            },
            "2": {
                "2222-2222-2222-2222": 2700,
                "estimate-2222-2222-2222-2222": 2700,
                "estimate10-2222-2222-2222-2222": 2250,
                "estimate90-2222-2222-2222-2222": 3000,
            },
        },
        "can_be_unavailable": True,
    },
    "forecast_remaining_today": {
        "state": {"1": "23.6817", "2": "32.5624"},
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "attributes": {
            "1": {"estimate": 23.6817, "estimate10": 19.7348, "estimate90": 26.313},
            "2": {"estimate": 32.5624, "estimate10": 27.1353, "estimate90": 36.1804},
        },
        "breakdown": {
            "1": {
                "1111-1111-1111-1111": 14.8011,
                "estimate-1111-1111-1111-1111": 14.8011,
                "estimate10-1111-1111-1111-1111": 12.3342,
                "estimate90-1111-1111-1111-1111": 16.4456,
            },
            "2": {
                "2222-2222-2222-2222": 8.8807,
                "estimate-2222-2222-2222-2222": 8.8807,
                "estimate10-2222-2222-2222-2222": 7.4005,
                "estimate90-2222-2222-2222-2222": 9.8674,
            },
        },
        "can_be_unavailable": True,
    },
    "forecast_next_hour": {
        "state": {"1": "6732", "2": "9256"},
        "unit_of_measurement": UnitOfEnergy.WATT_HOUR,
        "attributes": {
            "1": {"estimate": 6732, "estimate10": 5610, "estimate90": 7480},
            "2": {"estimate": 9256, "estimate10": 7714, "estimate90": 10285},
        },
        "breakdown": {
            "1": {
                "1111-1111-1111-1111": 4208,
                "estimate-1111-1111-1111-1111": 4208,
                "estimate10-1111-1111-1111-1111": 3506,
                "estimate90-1111-1111-1111-1111": 4675,
            },
            "2": {
                "2222-2222-2222-2222": 2524,
                "estimate-2222-2222-2222-2222": 2524,
                "estimate10-2222-2222-2222-2222": 2104,
                "estimate90-2222-2222-2222-2222": 2805,
            },
        },
        "can_be_unavailable": True,
    },
    "forecast_next_x_hours": {
        "state": {"1": "13748", "2": "18904"},
        "unit_of_measurement": UnitOfEnergy.WATT_HOUR,
        "attributes": {
            "1": {"estimate": 13748, "estimate10": 11457, "estimate90": 15276},
            "2": {"estimate": 18904, "estimate10": 15753, "estimate90": 21004},
        },
        "breakdown": {
            "1": {
                "1111-1111-1111-1111": 8593,
                "estimate-1111-1111-1111-1111": 8593,
                "estimate10-1111-1111-1111-1111": 7160,
                "estimate90-1111-1111-1111-1111": 9547,
            },
            "2": {
                "2222-2222-2222-2222": 5156,
                "estimate-2222-2222-2222-2222": 5156,
                "estimate10-2222-2222-2222-2222": 4296,
                "estimate90-2222-2222-2222-2222": 5728,
            },
        },
        "can_be_unavailable": True,
    },
    "peak_forecast_tomorrow": {
        "state": {"1": "7200", "2": "9900"},
        "unit_of_measurement": UnitOfPower.WATT,
        "attributes": {
            "1": {"estimate": 7200, "estimate10": 6000, "estimate90": 8000},
            "2": {"estimate": 9900, "estimate10": 8250, "estimate90": 11000},
        },
        "breakdown": {
            "1": {
                "1111-1111-1111-1111": 4500,
                "estimate-1111-1111-1111-1111": 4500,
                "estimate10-1111-1111-1111-1111": 3750,
                "estimate90-1111-1111-1111-1111": 5000,
            },
            "2": {
                "2222-2222-2222-2222": 2700,
                "estimate-2222-2222-2222-2222": 2700,
                "estimate10-2222-2222-2222-2222": 2250,
                "estimate90-2222-2222-2222-2222": 3000,
            },
        },
        "can_be_unavailable": True,
    },
    "peak_time_tomorrow": {
        "state": {"1": "2024-01-01T02:00:00+00:00", "2": "2024-01-01T02:00:00+00:00"},
        "attributes": {
            "1": {
                "estimate": "2024-01-01T02:00:00+00:00",
                "estimate10": "2024-01-01T02:00:00+00:00",
                "estimate90": "2024-01-01T02:00:00+00:00",
            },
            "2": {
                "estimate": "2024-01-01T02:00:00+00:00",
                "estimate10": "2024-01-01T02:00:00+00:00",
                "estimate90": "2024-01-01T02:00:00+00:00",
            },
        },
        "breakdown": {
            "1": {
                "1111-1111-1111-1111": "2024-01-01T02:00:00+00:00",
                "estimate-1111-1111-1111-1111": "2024-01-01T02:00:00+00:00",
                "estimate10-1111-1111-1111-1111": "2024-01-01T02:00:00+00:00",
                "estimate90-1111-1111-1111-1111": "2024-01-01T02:00:00+00:00",
            },
            "2": {
                "2222-2222-2222-2222": "2024-01-01T02:00:00+00:00",
                "estimate-2222-2222-2222-2222": "2024-01-01T02:00:00+00:00",
                "estimate10-2222-2222-2222-2222": "2024-01-01T02:00:00+00:00",
                "estimate90-2222-2222-2222-2222": "2024-01-01T02:00:00+00:00",
            },
        },
        "can_be_unavailable": True,
    },
    "power_now": {
        "state": {"1": "7221", "2": "9928"},
        "unit_of_measurement": UnitOfPower.WATT,
        "state_class": SensorStateClass.MEASUREMENT,
        "attributes": {
            "1": {"estimate": 7221, "estimate10": 6017, "estimate90": 8023},
            "2": {"estimate": 9928, "estimate10": 8274, "estimate90": 11032},
        },
        "breakdown": {
            "1": {
                "1111-1111-1111-1111": 4513,
                "estimate-1111-1111-1111-1111": 4513,
                "estimate10-1111-1111-1111-1111": 3761,
                "estimate90-1111-1111-1111-1111": 5014,
            },
            "2": {
                "2222-2222-2222-2222": 2708,
                "estimate-2222-2222-2222-2222": 2708,
                "estimate10-2222-2222-2222-2222": 2256,
                "estimate90-2222-2222-2222-2222": 3009,
            },
        },
        "can_be_unavailable": True,
    },
    "power_in_30_minutes": {
        "state": {"1": "7158", "2": "9842"},
        "unit_of_measurement": UnitOfPower.WATT,
        "state_class": SensorStateClass.MEASUREMENT,
        "attributes": {
            "1": {"estimate": 7158, "estimate10": 5965, "estimate90": 7953},
            "2": {"estimate": 9842, "estimate10": 8201, "estimate90": 10935},
        },
        "breakdown": {
            "1": {
                "1111-1111-1111-1111": 4474,
                "estimate-1111-1111-1111-1111": 4474,
                "estimate10-1111-1111-1111-1111": 3728,
                "estimate90-1111-1111-1111-1111": 4971,
            },
            "2": {
                "2222-2222-2222-2222": 2684,
                "estimate-2222-2222-2222-2222": 2684,
                "estimate10-2222-2222-2222-2222": 2237,
                "estimate90-2222-2222-2222-2222": 2982,
            },
        },
        "can_be_unavailable": True,
    },
    "power_in_1_hour": {
        "state": {"1": "6842", "2": "9408"},
        "unit_of_measurement": UnitOfPower.WATT,
        "state_class": SensorStateClass.MEASUREMENT,
        "attributes": {
            "1": {"estimate": 6842, "estimate10": 5702, "estimate90": 7603},
            "2": {"estimate": 9408, "estimate10": 7840, "estimate90": 10454},
        },
        "breakdown": {
            "1": {
                "1111-1111-1111-1111": 4276,
                "estimate-1111-1111-1111-1111": 4276,
                "estimate10-1111-1111-1111-1111": 3564,
                "estimate90-1111-1111-1111-1111": 4752,
            },
            "2": {
                "2222-2222-2222-2222": 2566,
                "estimate-2222-2222-2222-2222": 2566,
                "estimate10-2222-2222-2222-2222": 2138,
                "estimate90-2222-2222-2222-2222": 2851,
            },
        },
        "can_be_unavailable": True,
    },
    "api_used": {"state": {"1": "4", "2": "4"}},
    "api_limit": {"state": {"1": DEFAULT_INPUT1[API_QUOTA], "2": DEFAULT_INPUT1[API_QUOTA]}},
    "api_last_polled": {"state": {"1": "isodate", "2": "isodate"}},
    # "weather_description": {},
}

for attrs in SENSORS.values():
    if "attributes" in attrs:
        attrs["breakdown"]["3"] = {}
        for breakdown, value in attrs["breakdown"]["2"].items():
            attrs["breakdown"]["3"][breakdown.replace("2", "3")] = value
        attrs["attributes"]["1"] |= attrs["breakdown"]["1"] | attrs["breakdown"]["2"]
        attrs["attributes"]["2"] |= attrs["breakdown"]["1"] | attrs["breakdown"]["2"] | attrs["breakdown"]["3"]
        del attrs["breakdown"]

SENSORS["forecast_tomorrow"] = SENSORS["forecast_today"]
SENSORS["forecast_day_3"] = SENSORS["forecast_today"]
SENSORS["forecast_day_4"] = SENSORS["forecast_today"]
SENSORS["forecast_day_5"] = SENSORS["forecast_today"]
SENSORS["forecast_day_6"] = SENSORS["forecast_today"]
SENSORS["forecast_day_7"] = SENSORS["forecast_today"]


@pytest.mark.parametrize(
    ("key", "settings"),
    [
        ("1", DEFAULT_INPUT1),
        ("2", DEFAULT_INPUT2),
    ],
)
async def test_sensor_states(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    key: str,
    settings: dict,
) -> None:
    """Test state and attributes of sensors including expected state class and unit of measurement."""

    entry = await async_init_integration(hass, settings)
    coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator
    solcast = coordinator.solcast

    try:
        assert len(hass.states.async_all("sensor")) == len(SENSORS) + (3 if key == "1" else 4)

        for sensor, attrs in SENSORS.items():
            state = hass.states.get(f"sensor.solcast_pv_forecast_{sensor}")
            assert state
            assert state.state != STATE_UNAVAILABLE
            if "state" in attrs:
                test = state.state
                with contextlib.suppress(AttributeError, ValueError):
                    test = dt.fromisoformat(test)
                    test = test.replace(year=2024, month=1, day=1).isoformat()
                if attrs["state"][key] == "isodate":
                    assert dt.fromisoformat(test)
                else:
                    assert test == attrs["state"][key]
            if "attributes" in attrs:
                if attrs["attributes"][key].get("bob"):
                    _LOGGER.critical(state.attributes)
                for attribute in attrs["attributes"][key]:
                    test = state.attributes[attribute]
                    with contextlib.suppress(AttributeError, ValueError):
                        test = test.replace(year=2024, month=1, day=1).isoformat()
                    assert test == attrs["attributes"][key][attribute]
            assert state.attributes["attribution"] == "Data retrieved from Solcast"
            if "unit_of_measurement" in attrs:
                assert state.attributes["unit_of_measurement"] == attrs["unit_of_measurement"]
            if "state_class" in attrs:
                assert state.attributes["state_class"] == attrs["state_class"]

        coordinator._data_updated = False
        await coordinator.update_integration_listeners()
        coordinator._data_updated = True
        await coordinator.update_integration_listeners()
        coordinator._last_day = (dt.now(solcast.options.tz) - timedelta(days=1)).day
        await coordinator.update_integration_listeners()

        assert coordinator.get_sensor_value("badkey") is None
        assert coordinator.get_sensor_extra_attributes("badkey") is None
        assert coordinator.get_site_sensor_value("badroof", "badkey") is None
        assert coordinator.get_site_sensor_extra_attributes("badroof", "badkey") is None

    finally:
        assert await async_cleanup_integration_tests(hass)


async def test_sensor_x_hours_long(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test state and of x hours sensor."""

    options = copy.deepcopy(DEFAULT_INPUT1)
    options[CUSTOM_HOUR_SENSOR] = 48
    await async_init_integration(hass, options)

    try:
        state = hass.states.get("sensor.solcast_pv_forecast_forecast_next_x_hours")
        assert state
        assert int(state.state) == 86910
    finally:
        assert await async_cleanup_integration_tests(hass)


async def test_sensor_unavailable(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Verify sensors unavailable when "impossible" eventualities occur."""

    options = copy.deepcopy(DEFAULT_INPUT1)
    options[CUSTOM_HOUR_SENSOR] = 120
    entry = await async_init_integration(hass, options)
    coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator
    solcast: SolcastApi = coordinator.solcast

    try:
        # Turn SolcastApi to custard.
        old_solcast_data = copy.deepcopy(solcast._data)
        old_solcast_data_undampened = copy.deepcopy(solcast._data_undampened)
        solcast._data["siteinfo"]["1111-1111-1111-1111"]["forecasts"] = ["blah"]
        solcast._data["siteinfo"]["2222-2222-2222-2222"]["forecasts"] = []
        solcast._data_undampened["siteinfo"]["1111-1111-1111-1111"]["forecasts"] = []
        solcast._data_undampened["siteinfo"]["2222-2222-2222-2222"]["forecasts"] = []

        await solcast.build_forecast_data()
        coordinator._data_updated = True
        coordinator.async_update_listeners()

        for sensor, assertions in SENSORS.items():
            if assertions.get("can_be_unavailable", False):
                state = hass.states.get(f"sensor.solcast_pv_forecast_{sensor}")
                assert state
                assert state.state == STATE_UNAVAILABLE

        for site in ("first_site", "second_site"):
            state = hass.states.get(f"sensor.{site}")
            assert state
            assert state.state == STATE_UNAVAILABLE

        # Test when some future day data is missing (remove D3 onwards).
        solcast._data_undampened = old_solcast_data_undampened
        for site in ("1111-1111-1111-1111", "2222-2222-2222-2222"):
            solcast._data["siteinfo"][site]["forecasts"] = old_solcast_data["siteinfo"][site]["forecasts"][:-269]
        await solcast.build_forecast_data()
        coordinator._data_updated = True
        coordinator.async_update_listeners()

        for sensor, assertions in SENSORS.items():
            if "forecast_day_" not in sensor and "forecast_next_x_hours" not in sensor:
                continue
            if assertions.get("can_be_unavailable", False):
                state = hass.states.get(f"sensor.solcast_pv_forecast_{sensor}")
                assert state
                assert state.state == STATE_UNAVAILABLE

        # Test when 'today' is partial (remove D3 onwards).
        solcast._data_undampened = old_solcast_data_undampened
        for site in ("1111-1111-1111-1111", "2222-2222-2222-2222"):
            solcast._data["siteinfo"][site]["forecasts"] = old_solcast_data["siteinfo"][site]["forecasts"][:-325]
        await solcast.build_forecast_data()
        coordinator._data_updated = True
        coordinator.async_update_listeners()

        state = hass.states.get("sensor.solcast_pv_forecast_forecast_today")
        assert state
        assert state.attributes["dataCorrect"] is False

    finally:
        assert await async_cleanup_integration_tests(hass)


def get_sensor_value(self, key: str):
    """Raise an exception getting the value of a sensor."""
    return 1 / 0


def get_site_sensor_value(self, rooftop: str, key: str):
    """Raise an exception getting the value of a sensor."""
    return 1 / 0


def get_sensor_extra_attributes(self, key: str):
    """Raise an exception getting the value of a sensor."""
    return 1 / 0


def get_site_sensor_extra_attributes(self, rooftop: str, key: str):
    """Raise an exception getting the value of a sensor."""
    return 1 / 0


async def test_sensor_unavailble_exception(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test state and attributes of sensors including expected state class and unit of measurement."""

    SolcastUpdateCoordinator.get_sensor_value = get_sensor_value
    SolcastUpdateCoordinator.get_sensor_extra_attributes = get_sensor_extra_attributes
    SolcastUpdateCoordinator.get_site_sensor_value = get_site_sensor_value
    SolcastUpdateCoordinator.get_site_sensor_extra_attributes = get_site_sensor_extra_attributes
    entry = await async_init_integration(hass, DEFAULT_INPUT1)
    coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator

    try:
        coordinator._data_updated = True
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        for sensor in SENSORS:
            state = hass.states.get(f"sensor.solcast_pv_forecast_{sensor}")
            _ = state.attributes
            assert state
            assert state.state == STATE_UNAVAILABLE

        for site in ("first_site", "second_site"):
            state = hass.states.get(f"sensor.{site}")
            _ = state.attributes
            assert state
            assert state.state == STATE_UNAVAILABLE

    finally:
        assert await async_cleanup_integration_tests(hass)
