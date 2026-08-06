"""Tests for the Solcast Solar sensors."""

import asyncio
import contextlib
import copy
from datetime import datetime as dt, timedelta
import logging
from typing import Any
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.components.sensor import SensorStateClass
from homeassistant.components.solcast_solar.const import (
    ADVANCED_ENTITY_LOGGING,
    ANALYSIS,
    API_FORCE_USED,
    API_LIMIT,
    API_USED,
    ATTRIBUTION,
    BRK_ESTIMATE,
    BRK_ESTIMATE10,
    BRK_ESTIMATE90,
    BRK_SITE,
    CUSTOM_HOURS,
    DAILY_TYPICAL_FORECAST_UPDATES,
    DATA_CORRECT,
    DEFAULT_FORECAST_DAY_SENSORS,
    DEFAULT_FORECAST_DAYS,
    DETAILED_FORECAST,
    DETAILED_HOURLY,
    DT_TIME_FORMAT,
    ENTITY_FORECAST_NEXT_HOUR,
    ENTITY_FORECAST_REMAINING_TODAY,
    ENTITY_FORECAST_THIS_HOUR,
    ENTITY_POWER_NOW,
    ESTIMATE,
    ESTIMATE10,
    ESTIMATE90,
    FORECASTS,
    PERIOD_START,
    RESOURCE_ID,
    SITE_ATTRIBUTE_AZIMUTH,
    SITE_ATTRIBUTE_CAPACITY,
    SITE_ATTRIBUTE_CAPACITY_DC,
    SITE_ATTRIBUTE_COMPASS_DEGREES,
    SITE_ATTRIBUTE_COMPASS_DIRECTION,
    SITE_ATTRIBUTE_INSTALL_DATE,
    SITE_ATTRIBUTE_LATITUDE,
    SITE_ATTRIBUTE_LONGITUDE,
    SITE_ATTRIBUTE_LOSS_FACTOR,
    SITE_ATTRIBUTE_TAGS,
    SITE_ATTRIBUTE_TILT,
    SITE_INFO,
    UNDAMPENED_ESTIMATE,
    UNDAMPENED_ESTIMATE10,
    UNDAMPENED_ESTIMATE90,
)
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.forecast import ForecastQuery
from homeassistant.components.solcast_solar.solcastapi import SolcastApi
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util.read_only_dict import ReadOnlyDict

from . import (
    DEFAULT_INPUT1,
    DEFAULT_INPUT2,
    async_cleanup_integration_tests,
    async_init_integration,
    no_error_or_exception,
    write_advanced_options,
)

from tests.common import MockConfigEntry, async_fire_time_changed

_LOGGER = logging.getLogger(__name__)


# Site breakdown for 2222-2222-2222-2222 and 3333-3333-3333-3333 are identical.
SENSORS: dict[str, dict[str, Any]] = {
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
        "state": {"2": "2024-01-01T12:00:00+10:00", "1": "2024-01-01T12:00:00+10:00"},
        "attributes": {
            "2": {
                "estimate": "2024-01-01T12:00:00+10:00",
                "estimate10": "2024-01-01T12:00:00+10:00",
                "estimate90": "2024-01-01T12:00:00+10:00",
            },
            "1": {
                "estimate": "2024-01-01T12:00:00+10:00",
                "estimate10": "2024-01-01T12:00:00+10:00",
                "estimate90": "2024-01-01T12:00:00+10:00",
            },
        },
        "breakdown": {
            "1": {
                "1111_1111_1111_1111": "2024-01-01T12:00:00+10:00",
                "estimate_1111_1111_1111_1111": "2024-01-01T12:00:00+10:00",
                "estimate10_1111_1111_1111_1111": "2024-01-01T12:00:00+10:00",
                "estimate90_1111_1111_1111_1111": "2024-01-01T12:00:00+10:00",
            },
            "2": {
                "2222_2222_2222_2222": "2024-01-01T12:00:00+10:00",
                "estimate_2222_2222_2222_2222": "2024-01-01T12:00:00+10:00",
                "estimate10_2222_2222_2222_2222": "2024-01-01T12:00:00+10:00",
                "estimate90_2222_2222_2222_2222": "2024-01-01T12:00:00+10:00",
            },
        },
        "can_be_unavailable": True,
    },
    ENTITY_FORECAST_THIS_HOUR: {
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
    ENTITY_FORECAST_REMAINING_TODAY: {
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
    ENTITY_FORECAST_NEXT_HOUR: {
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
            "2": {"estimate": 13748, "estimate10": 11457, "estimate90": 15276, CUSTOM_HOURS: 1},
            "1": {"estimate": 18904, "estimate10": 15753, "estimate90": 21004, CUSTOM_HOURS: 1},
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
        "state": {"2": "2024-01-01T12:00:00+10:00", "1": "2024-01-01T12:00:00+10:00"},
        "attributes": {
            "2": {
                "estimate": "2024-01-01T12:00:00+10:00",
                "estimate10": "2024-01-01T12:00:00+10:00",
                "estimate90": "2024-01-01T12:00:00+10:00",
            },
            "1": {
                "estimate": "2024-01-01T12:00:00+10:00",
                "estimate10": "2024-01-01T12:00:00+10:00",
                "estimate90": "2024-01-01T12:00:00+10:00",
            },
        },
        "breakdown": {
            "1": {
                "1111_1111_1111_1111": "2024-01-01T12:00:00+10:00",
                "estimate_1111_1111_1111_1111": "2024-01-01T12:00:00+10:00",
                "estimate10_1111_1111_1111_1111": "2024-01-01T12:00:00+10:00",
                "estimate90_1111_1111_1111_1111": "2024-01-01T12:00:00+10:00",
            },
            "2": {
                "2222_2222_2222_2222": "2024-01-01T12:00:00+10:00",
                "estimate_2222_2222_2222_2222": "2024-01-01T12:00:00+10:00",
                "estimate10_2222_2222_2222_2222": "2024-01-01T12:00:00+10:00",
                "estimate90_2222_2222_2222_2222": "2024-01-01T12:00:00+10:00",
            },
        },
        "can_be_unavailable": True,
    },
    ENTITY_POWER_NOW: {
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
    API_USED: {"state": {"2": "4", "1": "4"}},
    API_LIMIT: {"state": {"2": DEFAULT_INPUT1[API_LIMIT], "1": DEFAULT_INPUT1[API_LIMIT]}},
    "api_last_polled": {"state": {"2": "isodate", "1": "isodate"}},
}

SENSORS["forecast_tomorrow"] = copy.deepcopy(SENSORS["forecast_today"])
for day in range(
    3, DEFAULT_FORECAST_DAY_SENSORS - 1
):  # Do not test the last day, as values will vary based on the time of day the test is run.
    SENSORS[f"forecast_day_{day}"] = copy.deepcopy(SENSORS["forecast_today"])
    SENSORS[f"forecast_day_{day}"]["should_be_disabled"] = True


@pytest.mark.parametrize(
    ("key", "settings"),
    [
        ("2", DEFAULT_INPUT1),
        ("1", DEFAULT_INPUT2),
    ],
)
async def test_sensor_states(  # noqa: C901
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
    key: str,
    settings: dict[str, Any],
) -> None:
    """Test state and attributes of sensors including expected state class and unit of measurement."""

    def get_estimate_set() -> list[str]:
        estimate_set: list[str] = []
        if settings[BRK_ESTIMATE]:
            estimate_set.append("estimate")
        if settings[BRK_ESTIMATE10]:
            estimate_set.append("estimate10")
        if settings[BRK_ESTIMATE90]:
            estimate_set.append("estimate90")
        return estimate_set

    try:
        write_advanced_options(hass.config.config_dir, {ADVANCED_ENTITY_LOGGING: True})

        entry = await async_init_integration(hass, settings)
        freezer.move_to(dt.now() + timedelta(minutes=1))
        async with asyncio.timeout(10):
            while "Start is not stale" not in caplog.text:
                freezer.tick()
                await hass.async_block_till_done()
        coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator
        solcast = coordinator.solcast

        sensors: dict[str, Any] = copy.deepcopy(SENSORS)
        estimate_set = get_estimate_set()
        estimate_set_hyphen = [e + "-" for e in estimate_set]

        # Special case for api_used
        state = hass.states.get("sensor.solcast_pv_forecast_api_used")
        assert state, "api_used sensor state should exist"
        assert state.state != STATE_UNAVAILABLE
        assert state.state == sensors[API_USED]["state"][key]
        assert state.attributes.get(API_FORCE_USED) == 0
        assert state.attributes.get(DAILY_TYPICAL_FORECAST_UPDATES) == solcast.api_typical_forecast_updates_count

        freezer.move_to((dt.now(solcast.tz) + timedelta(hours=24)).replace(minute=27, second=27))
        await hass.async_block_till_done()

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
                case _:
                    pass

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
            entity = f"sensor.solcast_pv_forecast_{sensor}"
            if not attrs.get("should_be_disabled", False):
                assert hass.states.get(entity) is not None, f"State for {entity} should exist"
                continue
            assert hass.states.get(entity) is None, f"State for {entity} should not exist"
            er.async_get(hass).async_update_entity(entity, disabled_by=None)
        async with asyncio.timeout(300):
            while "Reloading configuration entries because disabled_by changed" not in caplog.text:
                freezer.tick(0.01)
                await hass.async_block_till_done()
        now = dt.now()

        # Test number of site sensors that exist.
        assert len(hass.states.async_all("sensor")) == len(sensors) + (3 if key == "2" else 5), (
            f"Settings {key}: expected {len(sensors) + (3 if key == '2' else 5)} sensors, got {len(hass.states.async_all('sensor'))}"
        )
        no_error_or_exception(caplog)
        caplog.clear()

        # Test initial sensor values.
        for sensor, attrs in sensors.items():
            if sensor == API_USED:
                continue
            state = hass.states.get(f"sensor.solcast_pv_forecast_{sensor}")
            assert state, f"Settings {key}: sensor {sensor} not found"
            assert state.state != STATE_UNAVAILABLE, f"Settings {key}: sensor {sensor} is unavailable"
            if "state" in attrs:
                test = state.state
                with contextlib.suppress(AttributeError, ValueError):
                    testd = dt.fromisoformat(test)
                    test = testd.replace(year=2024, month=1, day=1).astimezone(ZoneInfo(hass.config.time_zone)).isoformat()
                if attrs["state"][key] == "isodate":
                    assert dt.fromisoformat(test), f"Settings {key}: sensor {sensor} state is not a valid ISO date"
                else:
                    assert test == attrs["state"][key], (
                        f"Settings {key}: sensor {sensor} state expected {attrs['state'][key]!r}, got {test!r}"
                    )
            state_attributes: ReadOnlyDict[str, Any] = state.attributes  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            if attrs.get("attributes"):
                for attribute in attrs["attributes"][key]:
                    testa = state_attributes.get(attribute)
                    with contextlib.suppress(AttributeError, ValueError):
                        testa = testa.replace(year=2024, month=1, day=1).isoformat()  # type: ignore[union-attr] # This is an assumed datetime, but that may not be
                    assert testa == attrs["attributes"][key][attribute], (
                        f"Settings {key}: sensor {sensor} attr {attribute!r} expected {attrs['attributes'][key][attribute]!r}, got {testa!r}"
                    )
            if "api" not in sensor:
                assert state_attributes["attribution"] == ATTRIBUTION
            if "unit_of_measurement" in attrs:
                assert state_attributes["unit_of_measurement"] == attrs["unit_of_measurement"], (
                    f"Settings {key}: sensor {sensor} unit expected {attrs['unit_of_measurement']!r}, got {state_attributes['unit_of_measurement']!r}"
                )
            if "state_class" in attrs:
                assert state_attributes["state_class"] == attrs["state_class"], (
                    f"Settings {key}: sensor {sensor} state_class expected {attrs['state_class']!r}, got {state_attributes['state_class']!r}"
                )
        no_error_or_exception(caplog)
        caplog.clear()

        if key == "1":
            assert hass.states.get("sensor.solcast_pv_forecast_first_site").state == "26.595"  # type: ignore[union-attr]
            assert hass.states.get("sensor.solcast_pv_forecast_second_site").state == "15.957"  # type: ignore[union-attr]
            assert hass.states.get("sensor.solcast_pv_forecast_third_site").state == "15.957"  # type: ignore[union-attr]
            assert hass.states.get("sensor.solcast_pv_forecast_api_limit").state == "20"  # type: ignore[union-attr]
            assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set_1").state == "12.0 kW"  # type: ignore[union-attr]
            assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set_2").state == "6.0 kW"  # type: ignore[union-attr]
            # The single overall limit sensor should not exist (this always gets created during PyTest entry
            # load, then is cleaned up when all sensors are defined when more than one limit is specified).
            assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set") is None, (
                "Overall hard limit sensor should not exist when per-site limits are specified"
            )

            attribs: ReadOnlyDict[str, Any] = hass.states.get("sensor.solcast_pv_forecast_first_site").attributes  # type: ignore[union-attr]
            assert attribs, "first_site sensor attributes should exist"
            assert attribs.get(RESOURCE_ID)
            assert attribs.get("name")
            assert attribs.get("friendly_name")
            assert attribs.get(SITE_ATTRIBUTE_INSTALL_DATE)
            assert attribs.get(SITE_ATTRIBUTE_LATITUDE) is None, "latitude should be redacted (None)"
            assert attribs.get(SITE_ATTRIBUTE_LONGITUDE) is None, "longitude should be redacted (None)"
            assert attribs.get(SITE_ATTRIBUTE_CAPACITY)
            assert attribs.get(SITE_ATTRIBUTE_CAPACITY_DC)
            assert attribs.get(SITE_ATTRIBUTE_AZIMUTH)
            assert attribs.get(SITE_ATTRIBUTE_COMPASS_DEGREES) is not None
            assert attribs.get(SITE_ATTRIBUTE_COMPASS_DIRECTION)
            assert attribs.get(SITE_ATTRIBUTE_TILT)
            assert attribs.get(SITE_ATTRIBUTE_LOSS_FACTOR)
            assert attribs.get(SITE_ATTRIBUTE_TAGS)

            attribs: ReadOnlyDict[str, Any] = hass.states.get("sensor.solcast_pv_forecast_forecast_today").attributes  # type: ignore[union-attr]
            assert attribs, "forecast_today sensor attributes should exist"
            assert attribs.get(DETAILED_FORECAST)
            assert attribs.get(DETAILED_HOURLY)
            assert isinstance(attribs.get(DETAILED_FORECAST), list)
            assert isinstance(attribs.get(DETAILED_HOURLY), list)

        # Verify analysis attribute on forecast day sensors.
        for sensor_name in ("forecast_today", "forecast_tomorrow"):
            state = hass.states.get(f"sensor.solcast_pv_forecast_{sensor_name}")
            assert state is not None, f"{sensor_name} sensor state should exist"
            ci = state.attributes.get(ANALYSIS)
            assert ci is not None, f"analysis missing from {sensor_name}"
            assert isinstance(ci, dict), f"analysis for {sensor_name} should be a dict"
            assert ci.get("confidence") == 0.75, f"{sensor_name}: expected confidence 0.75, got {ci.get('confidence')}"
            expected_spread = 11.82 if key == "2" else 16.2525
            assert ci.get("spread_kwh") == expected_spread, (
                f"{sensor_name}: expected spread_kwh {expected_spread}, got {ci.get('spread_kwh')}"
            )
            expected_estimate10 = 35.46 if key == "2" else 48.7575
            expected_estimate90 = 47.28 if key == "2" else 65.01
            assert ci.get("estimate10_kwh") == expected_estimate10, (
                f"{sensor_name}: expected estimate10_kwh {expected_estimate10}, got {ci.get('estimate10_kwh')}"
            )
            assert ci.get("estimate90_kwh") == expected_estimate90, (
                f"{sensor_name}: expected estimate90_kwh {expected_estimate90}, got {ci.get('estimate90_kwh')}"
            )
            assert isinstance(ci.get("intervals"), list), f"{sensor_name}: analysis intervals should be a list"
            assert len(ci["intervals"]) > 0, f"{sensor_name}: analysis intervals should not be empty"
            interval_entry = ci["intervals"][0]
            assert PERIOD_START in interval_entry
            assert "spread_kwh" in interval_entry

        # Verify undampened day totals are exposed consistently on all day sensors.
        for sensor_name in sensors:
            if sensor_name not in ("forecast_today", "forecast_tomorrow") and "forecast_day_" not in sensor_name:
                continue
            state = hass.states.get(f"sensor.solcast_pv_forecast_{sensor_name}")
            assert state is not None, f"{sensor_name} sensor state should exist"
            attribs = state.attributes
            if sensor_name == "forecast_today":
                day = 0
            elif sensor_name == "forecast_tomorrow":
                day = 1
            else:
                day = int(sensor_name.replace("forecast_day_", "")) - 1
            if solcast.dampening_enabled:
                assert attribs.get(UNDAMPENED_ESTIMATE) == solcast.query.get_total_energy_forecast_day(
                    day,
                    forecast_confidence=ESTIMATE,
                    undampened=True,
                )
                assert attribs.get(UNDAMPENED_ESTIMATE10) == solcast.query.get_total_energy_forecast_day(
                    day,
                    forecast_confidence=ESTIMATE10,
                    undampened=True,
                )
                assert attribs.get(UNDAMPENED_ESTIMATE90) == solcast.query.get_total_energy_forecast_day(
                    day,
                    forecast_confidence=ESTIMATE90,
                    undampened=True,
                )
            else:
                assert UNDAMPENED_ESTIMATE not in attribs
                assert UNDAMPENED_ESTIMATE10 not in attribs
                assert UNDAMPENED_ESTIMATE90 not in attribs

        # Test last sensor update time.
        freezer.move_to(now.replace(hour=2, minute=30, second=0, microsecond=0))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        coordinator._data_updated = True  # Will trigger all sensor update

        assert "Updating sensor" in caplog.text
        state = hass.states.get("sensor.solcast_pv_forecast_power_now")  # A per-five minute sensor
        assert state.last_updated.strftime(DT_TIME_FORMAT) == "02:30:00"  # type: ignore[union-attr]
        state = hass.states.get("sensor.solcast_pv_forecast_forecast_remaining_today")  # A per-update/midnight sensor
        assert state.last_updated.strftime(DT_TIME_FORMAT) == "02:30:00"  # type: ignore[union-attr]
        no_error_or_exception(caplog)

        # Simulate date change
        caplog.clear()
        coordinator._last_day = (dt.now(solcast.options.tz) - timedelta(days=1)).day
        await coordinator._update_integration_listeners()
        assert "Date has changed, recalculating splines" in caplog.text
        assert "Previous auto update would have been" in caplog.text
        assert "Auto forecast updates for" in caplog.text

        # Test get bad key and site.
        assert coordinator.get_sensor_value("badkey") is None, "Bad sensor key should return None"
        assert coordinator.get_sensor_extra_attributes("badkey") is None, "Bad sensor key extra attributes should return None"
        no_error_or_exception(caplog)

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_sensor_x_hours_long(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test state and of x hours sensor."""

    try:
        options = copy.deepcopy(DEFAULT_INPUT1)
        options[CUSTOM_HOURS] = 48
        entry = await async_init_integration(hass, options)

        er.async_get(hass).async_update_entity("sensor.solcast_pv_forecast_forecast_next_x_hours", disabled_by=None)
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("sensor.solcast_pv_forecast_forecast_next_x_hours")
        assert state, "forecast_next_x_hours sensor state should exist"
        assert state.state == "86910"
        no_error_or_exception(caplog)

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_forecast_day_undampened_attributes_with_manual_dampening(
    recorder_mock: Recorder,
    hass: HomeAssistant,
) -> None:
    """Test day undampened attributes are exposed when manual dampening is active."""

    settings = copy.deepcopy(DEFAULT_INPUT1)
    settings["damp12"] = 0.9

    try:
        entry = await async_init_integration(hass, settings)
        coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator
        solcast = coordinator.solcast

        assert solcast.dampening_enabled

        state = hass.states.get("sensor.solcast_pv_forecast_forecast_today")
        assert state is not None
        attribs = state.attributes

        assert attribs.get(UNDAMPENED_ESTIMATE) == solcast.query.get_total_energy_forecast_day(
            0,
            forecast_confidence=ESTIMATE,
            undampened=True,
        )
        assert attribs.get(UNDAMPENED_ESTIMATE10) == solcast.query.get_total_energy_forecast_day(
            0,
            forecast_confidence=ESTIMATE10,
            undampened=True,
        )
        assert attribs.get(UNDAMPENED_ESTIMATE90) == solcast.query.get_total_energy_forecast_day(
            0,
            forecast_confidence=ESTIMATE90,
            undampened=True,
        )
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_sensor_unavailable(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Verify sensors unavailable when "impossible" eventualities occur."""

    try:
        options = copy.deepcopy(DEFAULT_INPUT1)
        options[CUSTOM_HOURS] = 120
        entry = await async_init_integration(hass, options)
        async with asyncio.timeout(10):
            while "Start is not stale" not in caplog.text:
                freezer.tick()
                await hass.async_block_till_done()
        coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator
        solcast: SolcastApi = coordinator.solcast

        # Turn SolcastApi to custard.
        old_solcast_data = copy.deepcopy(solcast.data)
        old_solcast_data_undampened = copy.deepcopy(solcast.data_undampened)
        solcast.data[SITE_INFO]["1111-1111-1111-1111"][FORECASTS] = ["blah"]
        solcast.data[SITE_INFO]["2222-2222-2222-2222"][FORECASTS] = []
        solcast.data_undampened[SITE_INFO]["1111-1111-1111-1111"][FORECASTS] = []
        solcast.data_undampened[SITE_INFO]["2222-2222-2222-2222"][FORECASTS] = []

        await solcast.build_forecast_data()
        coordinator._data_updated = True
        coordinator.async_update_listeners()

        for sensor, assertions in SENSORS.items():
            if assertions.get("can_be_unavailable", False) and not assertions.get("should_be_disabled", False):
                state = hass.states.get(f"sensor.solcast_pv_forecast_{sensor}")
                assert state, f"Sensor {sensor} state should exist"
                assert state.state == STATE_UNAVAILABLE

        for site in ("solcast_pv_forecast_first_site", "solcast_pv_forecast_second_site"):
            state = hass.states.get(f"sensor.{site}")
            assert state, f"Site sensor {site} state should exist"
            assert state.state == STATE_UNAVAILABLE

        # Exceptions will be in the log
        caplog.clear()

        # Test when some future day data is missing (remove D3 onwards).
        solcast.data_undampened = old_solcast_data_undampened
        for site in ("1111-1111-1111-1111", "2222-2222-2222-2222"):
            solcast.data[SITE_INFO][site][FORECASTS] = old_solcast_data[SITE_INFO][site][FORECASTS][
                : -(269 + (DEFAULT_FORECAST_DAYS - 8) * 48)
            ]
        await solcast.build_forecast_data()
        coordinator._data_updated = True
        coordinator.async_update_listeners()

        for sensor, assertions in SENSORS.items():
            if "forecast_day_" not in sensor and "forecast_next_x_hours" not in sensor:
                continue
            if assertions.get("can_be_unavailable", False) and not assertions.get("should_be_disabled", False):
                state = hass.states.get(f"sensor.solcast_pv_forecast_{sensor}")
                assert state, f"Sensor {sensor} state should exist"
                assert state.state == STATE_UNAVAILABLE

        no_error_or_exception(caplog)
        caplog.clear()

        # Test when 'today' is partial (remove D3 onwards).
        solcast.data_undampened = old_solcast_data_undampened
        for site in ("1111-1111-1111-1111", "2222-2222-2222-2222"):
            solcast.data[SITE_INFO][site][FORECASTS] = old_solcast_data[SITE_INFO][site][FORECASTS][
                : -(325 + (DEFAULT_FORECAST_DAYS - 8) * 48)
            ]
        await solcast.build_forecast_data()
        coordinator._data_updated = True
        coordinator.async_update_listeners()

        state = hass.states.get("sensor.solcast_pv_forecast_forecast_today")
        assert state, "forecast_today sensor state should exist"
        state_attributes: ReadOnlyDict[str, Any] = state.attributes  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        assert state_attributes[DATA_CORRECT] is False, "Expected state attribute dataCorrect to be False"

        no_error_or_exception(caplog)

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


def _raise_zero_division(*_args: Any, **_kwargs: Any):
    """Raise an exception getting the value of a sensor."""
    return 1 / 0


async def test_sensor_unavailable_exception(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test state of sensors when exceptions occur."""

    monkeypatch.setattr(SolcastUpdateCoordinator, "get_sensor_value", _raise_zero_division)
    monkeypatch.setattr(SolcastUpdateCoordinator, "get_sensor_extra_attributes", _raise_zero_division)
    monkeypatch.setattr(ForecastQuery, "get_rooftop_site_total_today", _raise_zero_division)
    monkeypatch.setattr(ForecastQuery, "get_rooftop_site_extra_data", _raise_zero_division)

    try:
        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        async with asyncio.timeout(10):
            while "Start is not stale" not in caplog.text:
                freezer.tick()
                await hass.async_block_till_done()
            coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator

        coordinator._data_updated = True
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        for sensor, attrs in SENSORS.items():
            if attrs.get("should_be_disabled", False):
                continue
            state = hass.states.get(f"sensor.solcast_pv_forecast_{sensor}")
            _ = state.attributes  # type: ignore[union-attr]
            assert state, f"Sensor {sensor} state should exist"
            assert state.state == STATE_UNAVAILABLE

        for site in ("solcast_pv_forecast_first_site", "solcast_pv_forecast_second_site"):
            state = hass.states.get(f"sensor.{site}")
            _ = state.attributes  # type: ignore[union-attr]
            assert state, f"Site sensor {site} state should exist"
            assert state.state == STATE_UNAVAILABLE

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_rooftop_unique_id_mig(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that RooftopSensor unique IDs are migrated to resource ID."""

    entity_registry = er.async_get(hass)
    entity_registry.async_get_or_create(
        "sensor",
        "solcast_solar",
        "solcast_solcast_api_First Site",
        suggested_object_id="first_site_old",
    )
    entity_registry.async_get_or_create(
        "sensor",
        "solcast_solar",
        "solcast_solcast_api_Second Site",
        suggested_object_id="second_site_old",
    )

    try:
        caplog.set_level(logging.DEBUG, logger="homeassistant.components.solcast_solar.sensor")
        await async_init_integration(hass, DEFAULT_INPUT1)
        await hass.async_block_till_done()

        assert "Migrated RooftopSensor unique ID for site 'First Site' to resource ID" in caplog.text, (
            "Expected migration log for 'First Site' not found"
        )
        assert "Migrated RooftopSensor unique ID for site 'Second Site' to resource ID" in caplog.text, (
            "Expected migration log for 'Second Site' not found"
        )

        assert entity_registry.async_get_entity_id("sensor", "solcast_solar", "solcast_solcast_api_First Site") is None
        assert entity_registry.async_get_entity_id("sensor", "solcast_solar", "solcast_solcast_api_Second Site") is None
        assert entity_registry.async_get_entity_id("sensor", "solcast_solar", "solcast_solcast_api_1111-1111-1111-1111") is not None
        assert entity_registry.async_get_entity_id("sensor", "solcast_solar", "solcast_solcast_api_2222-2222-2222-2222") is not None

        no_error_or_exception(caplog)

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_rooftop_unique_id_mig_skips_when_owned_by_other_entry(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test migration is skipped, without raising, when the colliding entity is owned elsewhere.

    Third companion regression test for https://github.com/BJReplay/ha-solcast-solar/discussions/515,
    covering the collision case that is neither this integration's own already-migrated entity
    nor a registry entry with no config entry attached at all: the resource ID unique ID is
    already claimed by an entity belonging to some other config entry. Nothing is deleted or
    renamed in that case, and the platform still must not crash.
    """

    entity_registry = er.async_get(hass)

    other_entry = MockConfigEntry(domain="other_domain")
    other_entry.add_to_hass(hass)

    entity_registry.async_get_or_create(
        "sensor",
        "solcast_solar",
        "solcast_solcast_api_First Site",
        suggested_object_id="first_site_old",
    )
    entity_registry.async_get_or_create(
        "sensor",
        "solcast_solar",
        "solcast_solcast_api_1111-1111-1111-1111",
        suggested_object_id="owned_elsewhere",
        config_entry=other_entry,
    )

    try:
        caplog.set_level(logging.DEBUG, logger="homeassistant.components.solcast_solar.sensor")
        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        await hass.async_block_till_done()

        # Setup must still succeed: no unhandled exception from the collision.
        assert entry.state is ConfigEntryState.LOADED, f"Config entry should load cleanly, got {entry.state}"
        assert (
            "Skipped RooftopSensor unique ID migration for site 'First Site': resource ID unique ID is already in use "
            "by 'sensor.owned_elsewhere', which belongs to a different config entry" in caplog.text
        )

        # Neither the legacy entity nor the colliding, other-entry-owned entity are touched.
        assert entity_registry.async_get_entity_id("sensor", "solcast_solar", "solcast_solcast_api_First Site") is not None
        assert entity_registry.async_get_entity_id("sensor", "solcast_solar", "solcast_solcast_api_1111-1111-1111-1111") is not None

        no_error_or_exception(caplog)

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_rooftop_unique_id_mig_orphan_collision(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that migration survives an orphaned entity already holding the resource ID unique ID.

    Regression test for https://github.com/BJReplay/ha-solcast-solar/discussions/515: a stray
    entity registry entry unrelated to any active config entry (for example, a leftover from a
    different, unrelated integration that historically shared this domain/unique ID
    combination) can already own the resource-ID-based unique ID that migration wants to claim
    for the legacy site entity. Previously this caused `entity_registry.async_update_entity` to
    raise `ValueError: Unique id '...' is already in use by '...'`, which was unhandled and
    caused the entire sensor platform setup to fail, leaving every Solcast sensor unavailable.
    """

    entity_registry = er.async_get(hass)
    # Legacy, not-yet-migrated RooftopSensor entity for "First Site". This is the entity that
    # holds the site's real recorder history and should be preserved.
    entity_registry.async_get_or_create(
        "sensor",
        "solcast_solar",
        "solcast_solcast_api_First Site",
        suggested_object_id="first_site_old",
    )
    # An orphaned registry entry (no config entry attached) that coincidentally already owns
    # the resource-ID unique ID migration wants to claim for "First Site".
    orphan_entity_id = entity_registry.async_get_or_create(
        "sensor",
        "solcast_solar",
        "solcast_solcast_api_1111-1111-1111-1111",
        suggested_object_id="orphan_collision",
    ).entity_id
    # Second site has no collision and should migrate normally, proving the rest of the
    # platform is unaffected by the collision on the first site.
    entity_registry.async_get_or_create(
        "sensor",
        "solcast_solar",
        "solcast_solcast_api_Second Site",
        suggested_object_id="second_site_old",
    )

    try:
        caplog.set_level(logging.DEBUG, logger="homeassistant.components.solcast_solar.sensor")
        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        await hass.async_block_till_done()

        # The platform must set up successfully despite the collision: this is the core of the
        # regression. Before the fix, an unhandled ValueError here aborted sensor platform setup
        # entirely, and every Solcast sensor entity became unavailable.
        assert entry.state is ConfigEntryState.LOADED, f"Config entry should load cleanly, got {entry.state}"

        # The uncontested second site must still migrate normally: a collision on one site must
        # not take down migration (or setup) for any other site.
        assert "Migrated RooftopSensor unique ID for site 'Second Site' to resource ID" in caplog.text
        assert entity_registry.async_get_entity_id("sensor", "solcast_solar", "solcast_solcast_api_Second Site") is None
        assert entity_registry.async_get_entity_id("sensor", "solcast_solar", "solcast_solcast_api_2222-2222-2222-2222") is not None

        # The orphaned entity that caused the collision must be gone: it was demonstrably not
        # attached to any active config entry, so it is safe to discard automatically (this is
        # exactly what maintainers instructed affected users to do by hand: Settings > Entities
        # > select the stray entity > Delete).
        assert entity_registry.async_get(orphan_entity_id) is None

        # The legacy "First Site" entity -- which holds the real, continuous history for the
        # site -- must have been migrated onto the resource ID, exactly as it would be without
        # a collision. Its entity_id, and therefore its recorder history, is fully preserved.
        assert entity_registry.async_get_entity_id("sensor", "solcast_solar", "solcast_solcast_api_First Site") is None
        migrated_entity_id = entity_registry.async_get_entity_id("sensor", "solcast_solar", "solcast_solcast_api_1111-1111-1111-1111")
        assert migrated_entity_id == "sensor.first_site_old"

        # Every sensor entity, including both site sensors, must be available: the whole point
        # of the fix is that a single collision no longer takes the entire platform down.
        state = hass.states.get(migrated_entity_id)
        assert state is not None, "Migrated site sensor should have a state"
        assert state.state != STATE_UNAVAILABLE

        no_error_or_exception(caplog)

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_rooftop_unique_id_mig_stale_duplicate_of_this_entry(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test migration when the colliding entity is this entry's own, already-migrated entity.

    Companion regression test for https://github.com/BJReplay/ha-solcast-solar/discussions/515.
    autoSteve described a second way the same collision can occur: a downgrade to a pre-v4.6
    release re-creates the legacy, display-name-based entity, and a subsequent re-upgrade then
    finds *both* the legacy entity and the already-migrated, resource-ID-based entity (which
    belongs to this config entry and holds the continuous history) present at once. Here the
    correct/safe side to discard is the stale legacy duplicate, not the modern entity, which is
    the opposite priority to the foreign-orphan collision covered above.
    """

    entity_registry = er.async_get(hass)

    try:
        caplog.set_level(logging.DEBUG, logger="homeassistant.components.solcast_solar.sensor")

        # First, a normal, clean setup: RooftopSensor entities are created directly with their
        # resource-ID unique IDs (no legacy entity pre-exists, so nothing is migrated).
        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        await hass.async_block_till_done()

        modern_entity_id = entity_registry.async_get_entity_id("sensor", "solcast_solar", "solcast_solcast_api_1111-1111-1111-1111")
        assert modern_entity_id is not None
        modern_entry = entity_registry.async_get(modern_entity_id)
        assert modern_entry is not None
        assert modern_entry.config_entry_id == entry.entry_id

        # Simulate a downgrade-then-re-upgrade cycle: the legacy, display-name-based entity has
        # reappeared alongside the modern entity above.
        stale_legacy_entity_id = entity_registry.async_get_or_create(
            "sensor",
            "solcast_solar",
            "solcast_solcast_api_First Site",
            suggested_object_id="first_site_stale_legacy",
        ).entity_id

        caplog.clear()
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

        # The reload must succeed: this is the core of the regression here too. Before the fix,
        # renaming the stale legacy entity onto a unique ID already owned by the modern entity
        # raised an unhandled ValueError and aborted sensor platform setup entirely.
        assert entry.state is ConfigEntryState.LOADED, f"Config entry should reload cleanly, got {entry.state}"

        # The stale legacy duplicate is discarded: it has been dead since the original
        # migration/creation and accumulated no history since, so it is safe to drop in favour
        # of the modern entity, which has been live and collecting history the whole time.
        assert entity_registry.async_get(stale_legacy_entity_id) is None
        assert "Removed stale legacy entity" in caplog.text

        # The modern, already-migrated entity -- and its continuous history -- is completely
        # untouched: same entity_id, still tied to this config entry.
        assert entity_registry.async_get_entity_id("sensor", "solcast_solar", "solcast_solcast_api_1111-1111-1111-1111") == modern_entity_id
        state = hass.states.get(modern_entity_id)
        assert state is not None
        assert state.state != STATE_UNAVAILABLE

        no_error_or_exception(caplog)

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"
