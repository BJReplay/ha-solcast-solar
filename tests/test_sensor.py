"""Tests for the Solcast Solar sensors."""

import asyncio
import contextlib
import copy
from datetime import datetime as dt, timedelta
import logging

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.components.sensor import SensorStateClass
from homeassistant.components.solcast_solar.const import (
    API_QUOTA,
    BRK_ESTIMATE,
    BRK_ESTIMATE10,
    BRK_ESTIMATE90,
    BRK_SITE,
    CUSTOM_HOUR_SENSOR,
)
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.solcastapi import SolcastApi
from homeassistant.const import STATE_UNAVAILABLE, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import (
    DEFAULT_INPUT1,
    DEFAULT_INPUT2,
    async_cleanup_integration_tests,
    async_init_integration,
)

from tests.common import async_fire_time_changed

_LOGGER = logging.getLogger(__name__)


# Site breakdown for 2222-2222-2222-2222 and 3333-3333-3333-3333 are identical.
SENSORS: dict[str, dict] = {
    "forecast_today": {
        "state": {"2": "42.552", "1": "58.509"},
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "state_class": SensorStateClass.TOTAL,
        "attributes": {
            "2": {"estimate": 42.552, "estimate10": 35.46, "estimate90": 47.28},
            "1": {"estimate": 58.509, "estimate10": 48.7575, "estimate90": 65.01},
        },
        "breakdown": {
            "1": {
                "1111_1111_1111_1111": 26.595,
                "estimate_1111_1111_1111_1111": 26.595,
                "estimate10_1111_1111_1111_1111": 22.1625,
                "estimate90_1111_1111_1111_1111": 29.55,
            },
            "2": {
                "2222_2222_2222_2222": 15.957,
                "estimate_2222_2222_2222_2222": 15.957,
                "estimate10_2222_2222_2222_2222": 13.2975,
                "estimate90_2222_2222_2222_2222": 17.73,
            },
        },
        "can_be_unavailable": True,
    },
    "peak_forecast_today": {
        "state": {"2": "7200", "1": "9900"},
        "unit_of_measurement": UnitOfPower.WATT,
        "state_class": SensorStateClass.MEASUREMENT,
        "attributes": {
            "2": {"estimate": 7200, "estimate10": 6000, "estimate90": 8000},
            "1": {"estimate": 9900, "estimate10": 8250, "estimate90": 11000},
        },
        "breakdown": {
            "1": {
                "1111_1111_1111_1111": 4500,
                "estimate_1111_1111_1111_1111": 4500,
                "estimate10_1111_1111_1111_1111": 3750,
                "estimate90_1111_1111_1111_1111": 5000,
            },
            "2": {
                "2222_2222_2222_2222": 2700,
                "estimate_2222_2222_2222_2222": 2700,
                "estimate10_2222_2222_2222_2222": 2250,
                "estimate90_2222_2222_2222_2222": 3000,
            },
        },
        "can_be_unavailable": True,
    },
    "peak_time_today": {
        "state": {"2": "2024-01-01T02:00:00+00:00", "1": "2024-01-01T02:00:00+00:00"},
        "attributes": {
            "2": {
                "estimate": "2024-01-01T02:00:00+00:00",
                "estimate10": "2024-01-01T02:00:00+00:00",
                "estimate90": "2024-01-01T02:00:00+00:00",
            },
            "1": {
                "estimate": "2024-01-01T02:00:00+00:00",
                "estimate10": "2024-01-01T02:00:00+00:00",
                "estimate90": "2024-01-01T02:00:00+00:00",
            },
        },
        "breakdown": {
            "1": {
                "1111_1111_1111_1111": "2024-01-01T02:00:00+00:00",
                "estimate_1111_1111_1111_1111": "2024-01-01T02:00:00+00:00",
                "estimate10_1111_1111_1111_1111": "2024-01-01T02:00:00+00:00",
                "estimate90_1111_1111_1111_1111": "2024-01-01T02:00:00+00:00",
            },
            "2": {
                "2222_2222_2222_2222": "2024-01-01T02:00:00+00:00",
                "estimate_2222_2222_2222_2222": "2024-01-01T02:00:00+00:00",
                "estimate10_2222_2222_2222_2222": "2024-01-01T02:00:00+00:00",
                "estimate90_2222_2222_2222_2222": "2024-01-01T02:00:00+00:00",
            },
        },
        "can_be_unavailable": True,
    },
    "forecast_this_hour": {
        "state": {"2": "7200", "1": "9900"},
        "unit_of_measurement": UnitOfEnergy.WATT_HOUR,
        "attributes": {
            "2": {"estimate": 7200, "estimate10": 6000, "estimate90": 8000},
            "1": {"estimate": 9900, "estimate10": 8250, "estimate90": 11000},
        },
        "breakdown": {
            "1": {
                "1111_1111_1111_1111": 4500,
                "estimate_1111_1111_1111_1111": 4500,
                "estimate10_1111_1111_1111_1111": 3750,
                "estimate90_1111_1111_1111_1111": 5000,
            },
            "2": {
                "2222_2222_2222_2222": 2700,
                "estimate_2222_2222_2222_2222": 2700,
                "estimate10_2222_2222_2222_2222": 2250,
                "estimate90_2222_2222_2222_2222": 3000,
            },
        },
        "can_be_unavailable": True,
    },
    "forecast_remaining_today": {
        "state": {"2": "23.6817", "1": "32.5624"},
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "attributes": {
            "2": {"estimate": 23.6817, "estimate10": 19.7348, "estimate90": 26.313},
            "1": {"estimate": 32.5624, "estimate10": 27.1353, "estimate90": 36.1804},
        },
        "breakdown": {
            "1": {
                "1111_1111_1111_1111": 14.8011,
                "estimate_1111_1111_1111_1111": 14.8011,
                "estimate10_1111_1111_1111_1111": 12.3342,
                "estimate90_1111_1111_1111_1111": 16.4456,
            },
            "2": {
                "2222_2222_2222_2222": 8.8807,
                "estimate_2222_2222_2222_2222": 8.8807,
                "estimate10_2222_2222_2222_2222": 7.4005,
                "estimate90_2222_2222_2222_2222": 9.8674,
            },
        },
        "can_be_unavailable": True,
    },
    "forecast_next_hour": {
        "state": {"2": "6732", "1": "9256"},
        "unit_of_measurement": UnitOfEnergy.WATT_HOUR,
        "attributes": {
            "2": {"estimate": 6732, "estimate10": 5610, "estimate90": 7480},
            "1": {"estimate": 9256, "estimate10": 7714, "estimate90": 10285},
        },
        "breakdown": {
            "1": {
                "1111_1111_1111_1111": 4208,
                "estimate_1111_1111_1111_1111": 4208,
                "estimate10_1111_1111_1111_1111": 3506,
                "estimate90_1111_1111_1111_1111": 4675,
            },
            "2": {
                "2222_2222_2222_2222": 2524,
                "estimate_2222_2222_2222_2222": 2524,
                "estimate10_2222_2222_2222_2222": 2104,
                "estimate90_2222_2222_2222_2222": 2805,
            },
        },
        "can_be_unavailable": True,
    },
    "forecast_next_x_hours": {
        "state": {"2": "13748", "1": "18904"},
        "unit_of_measurement": UnitOfEnergy.WATT_HOUR,
        "attributes": {
            "2": {"estimate": 13748, "estimate10": 11457, "estimate90": 15276},
            "1": {"estimate": 18904, "estimate10": 15753, "estimate90": 21004},
        },
        "breakdown": {
            "1": {
                "1111_1111_1111_1111": 8593,
                "estimate_1111_1111_1111_1111": 8593,
                "estimate10_1111_1111_1111_1111": 7160,
                "estimate90_1111_1111_1111_1111": 9547,
            },
            "2": {
                "2222_2222_2222_2222": 5156,
                "estimate_2222_2222_2222_2222": 5156,
                "estimate10_2222_2222_2222_2222": 4296,
                "estimate90_2222_2222_2222_2222": 5728,
            },
        },
        "can_be_unavailable": True,
        "should_be_disabled": True,
    },
    "peak_forecast_tomorrow": {
        "state": {"2": "7200", "1": "9900"},
        "unit_of_measurement": UnitOfPower.WATT,
        "attributes": {
            "2": {"estimate": 7200, "estimate10": 6000, "estimate90": 8000},
            "1": {"estimate": 9900, "estimate10": 8250, "estimate90": 11000},
        },
        "breakdown": {
            "1": {
                "1111_1111_1111_1111": 4500,
                "estimate_1111_1111_1111_1111": 4500,
                "estimate10_1111_1111_1111_1111": 3750,
                "estimate90_1111_1111_1111_1111": 5000,
            },
            "2": {
                "2222_2222_2222_2222": 2700,
                "estimate_2222_2222_2222_2222": 2700,
                "estimate10_2222_2222_2222_2222": 2250,
                "estimate90_2222_2222_2222_2222": 3000,
            },
        },
        "can_be_unavailable": True,
    },
    "peak_time_tomorrow": {
        "state": {"2": "2024-01-01T02:00:00+00:00", "1": "2024-01-01T02:00:00+00:00"},
        "attributes": {
            "2": {
                "estimate": "2024-01-01T02:00:00+00:00",
                "estimate10": "2024-01-01T02:00:00+00:00",
                "estimate90": "2024-01-01T02:00:00+00:00",
            },
            "1": {
                "estimate": "2024-01-01T02:00:00+00:00",
                "estimate10": "2024-01-01T02:00:00+00:00",
                "estimate90": "2024-01-01T02:00:00+00:00",
            },
        },
        "breakdown": {
            "1": {
                "1111_1111_1111_1111": "2024-01-01T02:00:00+00:00",
                "estimate_1111_1111_1111_1111": "2024-01-01T02:00:00+00:00",
                "estimate10_1111_1111_1111_1111": "2024-01-01T02:00:00+00:00",
                "estimate90_1111_1111_1111_1111": "2024-01-01T02:00:00+00:00",
            },
            "2": {
                "2222_2222_2222_2222": "2024-01-01T02:00:00+00:00",
                "estimate_2222_2222_2222_2222": "2024-01-01T02:00:00+00:00",
                "estimate10_2222_2222_2222_2222": "2024-01-01T02:00:00+00:00",
                "estimate90_2222_2222_2222_2222": "2024-01-01T02:00:00+00:00",
            },
        },
        "can_be_unavailable": True,
    },
    "power_now": {
        "state": {"2": "7221", "1": "9928"},
        "unit_of_measurement": UnitOfPower.WATT,
        "state_class": SensorStateClass.MEASUREMENT,
        "attributes": {
            "2": {"estimate": 7221, "estimate10": 6017, "estimate90": 8023},
            "1": {"estimate": 9928, "estimate10": 8274, "estimate90": 11032},
        },
        "breakdown": {
            "1": {
                "1111_1111_1111_1111": 4513,
                "estimate_1111_1111_1111_1111": 4513,
                "estimate10_1111_1111_1111_1111": 3761,
                "estimate90_1111_1111_1111_1111": 5014,
            },
            "2": {
                "2222_2222_2222_2222": 2708,
                "estimate_2222_2222_2222_2222": 2708,
                "estimate10_2222_2222_2222_2222": 2256,
                "estimate90_2222_2222_2222_2222": 3009,
            },
        },
        "can_be_unavailable": True,
    },
    "power_in_30_minutes": {
        "state": {"2": "7158", "1": "9842"},
        "unit_of_measurement": UnitOfPower.WATT,
        "state_class": SensorStateClass.MEASUREMENT,
        "attributes": {
            "2": {"estimate": 7158, "estimate10": 5965, "estimate90": 7953},
            "1": {"estimate": 9842, "estimate10": 8201, "estimate90": 10935},
        },
        "breakdown": {
            "1": {
                "1111_1111_1111_1111": 4474,
                "estimate_1111_1111_1111_1111": 4474,
                "estimate10_1111_1111_1111_1111": 3728,
                "estimate90_1111_1111_1111_1111": 4971,
            },
            "2": {
                "2222_2222_2222_2222": 2684,
                "estimate_2222_2222_2222_2222": 2684,
                "estimate10_2222_2222_2222_2222": 2237,
                "estimate90_2222_2222_2222_2222": 2982,
            },
        },
        "can_be_unavailable": True,
    },
    "power_in_1_hour": {
        "state": {"2": "6842", "1": "9408"},
        "unit_of_measurement": UnitOfPower.WATT,
        "state_class": SensorStateClass.MEASUREMENT,
        "attributes": {
            "2": {"estimate": 6842, "estimate10": 5702, "estimate90": 7603},
            "1": {"estimate": 9408, "estimate10": 7840, "estimate90": 10454},
        },
        "breakdown": {
            "1": {
                "1111_1111_1111_1111": 4276,
                "estimate_1111_1111_1111_1111": 4276,
                "estimate10_1111_1111_1111_1111": 3564,
                "estimate90_1111_1111_1111_1111": 4752,
            },
            "2": {
                "2222_2222_2222_2222": 2566,
                "estimate_2222_2222_2222_2222": 2566,
                "estimate10_2222_2222_2222_2222": 2138,
                "estimate90_2222_2222_2222_2222": 2851,
            },
        },
        "can_be_unavailable": True,
    },
    "api_used": {"state": {"2": "4", "1": "4"}},
    "api_limit": {"state": {"2": DEFAULT_INPUT1[API_QUOTA], "1": DEFAULT_INPUT1[API_QUOTA]}},
    "api_last_polled": {"state": {"2": "isodate", "1": "isodate"}},
}

SENSORS["forecast_tomorrow"] = copy.deepcopy(SENSORS["forecast_today"])
for day in range(3, 7):  # Do not test day 7, as values will vary based on the time of day the test is run.
    SENSORS[f"forecast_day_{day}"] = copy.deepcopy(SENSORS["forecast_today"])
    SENSORS[f"forecast_day_{day}"]["should_be_disabled"] = True


def _no_exception(caplog: pytest.LogCaptureFixture):
    assert "Error" not in caplog.text
    assert "Exception" not in caplog.text


@pytest.mark.parametrize(
    ("key", "settings"),
    [
        ("2", DEFAULT_INPUT1),
        ("1", DEFAULT_INPUT2),
    ],
)
async def test_sensor_states(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
    key: str,
    settings: dict,
) -> None:
    """Test state and attributes of sensors including expected state class and unit of measurement."""

    entry = await async_init_integration(hass, settings)
    coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator
    solcast = coordinator.solcast

    def get_estimate_set() -> list[str]:
        estimate_set = []
        if settings[BRK_ESTIMATE]:
            estimate_set.append("estimate")
        if settings[BRK_ESTIMATE10]:
            estimate_set.append("estimate10")
        if settings[BRK_ESTIMATE90]:
            estimate_set.append("estimate90")
        return estimate_set

    try:
        sensors = copy.deepcopy(SENSORS)
        estimate_set = get_estimate_set()
        estimate_set_hyphen = [e + "-" for e in estimate_set]

        # Consolidate breakdowns for the key scenarios
        if settings[BRK_SITE]:
            match key:
                case "1":
                    for values in sensors.values():
                        if values.get("breakdown"):
                            values["breakdown"]["3"] = {}
                            for breakdown, value in values["breakdown"]["2"].items():
                                values["breakdown"]["3"][breakdown.replace("2", "3")] = value
                            values["attributes"]["1"] |= values["breakdown"]["1"] | values["breakdown"]["2"] | values["breakdown"]["3"]
                case "2":
                    for values in sensors.values():
                        if values.get("breakdown"):
                            values["attributes"]["2"] |= values["breakdown"]["1"] | values["breakdown"]["2"]

        # Remove unused options for the key scenarios based on settings.
        for values in sensors.values():
            to_pop = [
                attr
                for attr in values.get("attributes", {}).get(key, {})
                if (attr not in estimate_set and "-" not in attr)
                or (attr[4:5] == "-" and not settings[BRK_SITE])
                or ("estimate" in attr and "-" in attr and attr[: attr.find("-") + 1] not in estimate_set_hyphen)
            ]
            for attr in to_pop:
                values["attributes"][key].pop(attr)

        # Verify that the entities that should be disabled by default are, then enable them.
        for sensor, attrs in sensors.items():
            entry_id = f"sensor.solcast_pv_forecast_{sensor}"
            if not attrs.get("should_be_disabled", False):
                continue
            assert hass.states.get(entry_id) is None
            er.async_get(hass).async_update_entity(entry_id, disabled_by=None)
        # await hass.config_entries.async_reload(entry.entry_id)
        async with asyncio.timeout(300):
            while "Reloading configuration entries because disabled_by changed" not in caplog.text:
                freezer.tick(0.01)
                await hass.async_block_till_done()
        now = dt.now()

        # Test number of site sensors that exist.
        assert len(hass.states.async_all("sensor")) == len(sensors) + (3 if key == "2" else 5)
        _no_exception(caplog)
        caplog.clear()

        # Test initial sensor values.
        for sensor, attrs in sensors.items():
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
            if attrs.get("attributes"):
                for attribute in attrs["attributes"][key]:
                    test = state.attributes.get(attribute)
                    with contextlib.suppress(AttributeError, ValueError):
                        test = test.replace(year=2024, month=1, day=1).isoformat()
                    assert test == attrs["attributes"][key][attribute]
            assert state.attributes["attribution"] == "Data retrieved from Solcast"
            if "unit_of_measurement" in attrs:
                assert state.attributes["unit_of_measurement"] == attrs["unit_of_measurement"]
            if "state_class" in attrs:
                assert state.attributes["state_class"] == attrs["state_class"]
        _no_exception(caplog)
        caplog.clear()

        if key == "1":
            assert hass.states.get("sensor.first_site").state == "26.595"
            assert hass.states.get("sensor.second_site").state == "15.957"
            assert hass.states.get("sensor.third_site").state == "15.957"
            assert hass.states.get("sensor.solcast_pv_forecast_api_limit").state == "20"
            assert hass.states.get("sensor.solcast_pv_forecast_api_used").state == "4"
            assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set_1").state == "12.0 kW"
            assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set_2").state == "6.0 kW"

        # Test last sensor update time.
        freezer.move_to(now.replace(hour=2, minute=30, second=0, microsecond=0))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        coordinator._data_updated = True  # Will trigger all sensor update

        assert "Updating sensor" in caplog.text
        state = hass.states.get("sensor.solcast_pv_forecast_power_now")  # A per-five minute sensor
        assert state.last_updated.strftime("%H:%M:%S") == "02:30:00"
        state = hass.states.get("sensor.solcast_pv_forecast_forecast_remaining_today")  # A per-update/midnight sensor
        assert state.last_updated.strftime("%H:%M:%S") == "02:30:00"
        _no_exception(caplog)

        # Simulate date change
        caplog.clear()
        coordinator._last_day = (dt.now(solcast.options.tz) - timedelta(days=1)).day
        await coordinator.update_integration_listeners()
        assert "Date has changed, recalculate splines and set up auto-updates" in caplog.text
        assert "Previous auto update would have been" in caplog.text
        assert "Auto forecast updates for" in caplog.text

        # Test get bad key and site.
        assert coordinator.get_sensor_value("badkey") is None
        assert coordinator.get_sensor_extra_attributes("badkey") is None
        assert coordinator.get_site_sensor_value("badroof", "badkey") is None
        assert coordinator.get_site_sensor_extra_attributes("badroof", "badkey") is None
        _no_exception(caplog)

    finally:
        assert await async_cleanup_integration_tests(hass)


async def test_sensor_x_hours_long(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test state and of x hours sensor."""

    options = copy.deepcopy(DEFAULT_INPUT1)
    options[CUSTOM_HOUR_SENSOR] = 48
    entry = await async_init_integration(hass, options)

    try:
        er.async_get(hass).async_update_entity("sensor.solcast_pv_forecast_forecast_next_x_hours", disabled_by=None)
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("sensor.solcast_pv_forecast_forecast_next_x_hours")
        assert state
        assert state.state == "86910"
        _no_exception(caplog)

    finally:
        assert await async_cleanup_integration_tests(hass)


async def test_sensor_unavailable(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
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
            if assertions.get("can_be_unavailable", False) and not assertions.get("should_be_disabled", False):
                state = hass.states.get(f"sensor.solcast_pv_forecast_{sensor}")
                assert state
                assert state.state == STATE_UNAVAILABLE

        for site in ("first_site", "second_site"):
            state = hass.states.get(f"sensor.{site}")
            assert state
            assert state.state == STATE_UNAVAILABLE

        # Exceptions will be in the log
        caplog.clear()

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
            if assertions.get("can_be_unavailable", False) and not assertions.get("should_be_disabled", False):
                state = hass.states.get(f"sensor.solcast_pv_forecast_{sensor}")
                assert state
                assert state.state == STATE_UNAVAILABLE

        _no_exception(caplog)
        caplog.clear()

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

        _no_exception(caplog)

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
    """Test state of sensors when exceptions occur."""

    old_get_sensor_value = SolcastUpdateCoordinator.get_sensor_value
    old_get_sensor_extra_attributes = SolcastUpdateCoordinator.get_sensor_extra_attributes
    old_get_site_sensor_value = SolcastUpdateCoordinator.get_site_sensor_value
    old_get_site_sensor_extra_attributes = SolcastUpdateCoordinator.get_site_sensor_extra_attributes

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

        for sensor, attrs in SENSORS.items():
            if attrs.get("should_be_disabled", False):
                continue
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
        SolcastUpdateCoordinator.get_sensor_value = old_get_sensor_value
        SolcastUpdateCoordinator.get_sensor_extra_attributes = old_get_sensor_extra_attributes
        SolcastUpdateCoordinator.get_site_sensor_value = old_get_site_sensor_value
        SolcastUpdateCoordinator.get_site_sensor_extra_attributes = old_get_site_sensor_extra_attributes
