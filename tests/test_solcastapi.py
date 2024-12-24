"""Test the Solcast API."""

# pylint: disable=global-statement

import copy
from datetime import datetime as dt
import logging
from zoneinfo import ZoneInfo

import pytest

from homeassistant.components.solcast_solar.__init__ import (
    __get_options,
    __get_session_headers,
    __get_version,
    __setup_storage,
)
from homeassistant.components.solcast_solar.const import DOMAIN
from homeassistant.components.solcast_solar.sim.simulate import (
    raw_get_sites,
    set_time_zone,
)
from homeassistant.components.solcast_solar.solcastapi import FRESH_DATA, SolcastApi
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client

from . import (
    CUSTOM_HOURS,
    DEFAULT_INPUT1,
    DEFAULT_INPUT2,
    ZONE_RAW,
    async_cleanup_integration_tests,
)

from tests.common import MockConfigEntry

_LOGGER = logging.getLogger(__name__)

MOCK_ENTRY1 = MockConfigEntry(domain=DOMAIN, data={}, options=DEFAULT_INPUT1)
MOCK_ENTRY2 = MockConfigEntry(domain=DOMAIN, data={}, options=DEFAULT_INPUT2)

ZONE = ZoneInfo(ZONE_RAW)
set_time_zone(ZONE)


async def __get_solcast(hass: HomeAssistant, entry: MockConfigEntry) -> SolcastApi:
    version = await __get_version(hass)
    options = await __get_options(hass, entry)
    __setup_storage(hass)
    solcast = SolcastApi(aiohttp_client.async_get_clientsession(hass), options, hass, entry)
    solcast.headers = __get_session_headers(version)
    for api_key in options.api_key.split(","):
        _sites = raw_get_sites(api_key)
        solcast.sites += [site | {"apikey": api_key} for site in _sites["sites"]]
    solcast._api_used = {api_key: 0 for api_key in options.api_key.split(",")}
    solcast._api_limit = {api_key: 10 for api_key in options.api_key.split(",")}
    solcast._tz = ZONE
    hass.config.time_zone = ZONE_RAW
    return solcast


MOCK = {}


async def test_forecast_update(hass: HomeAssistant) -> None:
    """Test fetch forecast including past actuals."""

    global MOCK  # noqa: PLW0603 A global is used to store the SolcastApi instances for later performant testing.

    # Forecast fetch with past actuals, one API key, two sites.
    solcast = await __get_solcast(hass, MOCK_ENTRY1)
    assert solcast._data == FRESH_DATA
    assert solcast._data_undampened == FRESH_DATA
    assert await solcast.get_forecast_update(do_past=True, force=False) == ""

    await solcast.recalculate_splines()
    mock_solcast1 = solcast

    # Check rapid update refused, and that auto_updated is set, one API key, two sites.
    assert (await solcast.get_forecast_update(do_past=False, force=True)).startswith("Not requesting a solar forecast because time") is True
    assert solcast._data["auto_updated"] is True

    # Check update when auto_update is disabled, one API key, two sites.
    user_input = copy.deepcopy(DEFAULT_INPUT1)
    user_input["auto_update"] = 0
    solcast = None
    solcast = await __get_solcast(hass, MockConfigEntry(domain=DOMAIN, data={}, options=user_input))
    assert await solcast.get_forecast_update(do_past=False, force=False) == ""
    assert solcast._data["auto_updated"] is False

    # Check update when auto_update is enabled, two API keys, three sites.
    solcast = await __get_solcast(hass, MOCK_ENTRY2)
    assert await solcast.get_forecast_update(do_past=True, force=False) == ""

    await solcast.recalculate_splines()

    MOCK = {
        "mock1": mock_solcast1,
        "mock2": solcast,
    }


def __available_estimates(solcast):
    df = [solcast._use_forecast_confidence]
    if solcast.options.attr_brk_estimate and "pv_estimate" not in df:
        df.append("pv_estimate")
    if solcast.options.attr_brk_estimate10 and "pv_estimate10" not in df:
        df.append("pv_estimate10")
    if solcast.options.attr_brk_estimate90 and "pv_estimate90" not in df:
        df.append("pv_estimate90")
    return df


async def test_build_splines(hass: HomeAssistant) -> None:
    """Test building splines."""

    for solcast in MOCK.values():
        # Check building splines, one API key, two sites.
        await solcast.recalculate_splines()
        day_length = len(solcast._spline_period) * 6 + 3  # Three extra intervals are spline padding

        df = __available_estimates(solcast)

        for estimate in ["pv_estimate", "pv_estimate10", "pv_estimate90"]:
            if estimate in df:
                assert len(solcast._forecasts_moment["all"][estimate]) == day_length
                assert len(solcast._forecasts_remaining["all"][estimate]) == day_length
                for site in solcast.sites:
                    if estimate in df:
                        assert len(solcast._forecasts_moment[site["resource_id"]][estimate]) == day_length
                        assert sum(solcast._forecasts_moment[site["resource_id"]][estimate]) > 0
                for site in solcast.sites:
                    assert len(solcast._forecasts_remaining[site["resource_id"]][estimate]) == day_length
                    assert sum(solcast._forecasts_remaining[site["resource_id"]][estimate]) > 0
            else:
                with pytest.raises(KeyError):
                    len(solcast._forecasts_moment["all"][estimate])
                with pytest.raises(KeyError):
                    len(solcast._forecasts_remaining["all"][estimate])
                for site in solcast.sites:
                    with pytest.raises(KeyError):
                        len(solcast._forecasts_moment[site["resource_id"]][estimate])
                    with pytest.raises(KeyError):
                        sum(solcast._forecasts_moment[site["resource_id"]][estimate])
                    with pytest.raises(KeyError):
                        len(solcast._forecasts_remaining[site["resource_id"]][estimate])
                    with pytest.raises(KeyError):
                        sum(solcast._forecasts_remaining[site["resource_id"]][estimate])


async def test_get_total_energy_forecast(hass: HomeAssistant) -> None:
    """Test total energy forecast for the day."""

    build = False
    expect = {
        "mock1": {"pv_estimate": 42.552, "pv_estimate10": 35.46, "pv_estimate90": 47.28},
        "mock2": {"pv_estimate": 58.509, "pv_estimate10": 48.7575, "pv_estimate90": 65.01},
    }

    if build:
        expect = {mock: {"pv_estimate": 0.0, "pv_estimate10": 0.0, "pv_estimate90": 0.0} for mock in MOCK}
    for mock, solcast in MOCK.items():
        for day in range(7):
            if not build:
                assert solcast.get_total_energy_forecast_day(day) == expect[mock]["pv_" + solcast.options.key_estimate]
                for estimate in ["pv_estimate", "pv_estimate10", "pv_estimate90"]:
                    assert solcast.get_total_energy_forecast_day(day, forecast_confidence=estimate) == expect[mock][estimate]
            else:
                if day > 0:
                    break
                for estimate in ["pv_estimate", "pv_estimate10", "pv_estimate90"]:
                    expect[mock][estimate] = solcast.get_total_energy_forecast_day(day, forecast_confidence=estimate)
        assert solcast.get_total_energy_forecast_day(9) == 0.0
    if build:
        _LOGGER.info(expect)


async def test_get_peaks(hass: HomeAssistant) -> None:
    """Test peak time forecast for the day."""

    build = False
    expect = {
        "mock1": {
            "pv_estimate": {"peak_time": "2024-01-01T02:00:00+00:00", "peak_power": 7200},
            "pv_estimate10": {"peak_time": "2024-01-01T02:00:00+00:00", "peak_power": 6000},
            "pv_estimate90": {"peak_time": "2024-01-01T02:00:00+00:00", "peak_power": 8000},
        },
        "mock2": {
            "pv_estimate": {"peak_time": "2024-01-01T02:00:00+00:00", "peak_power": 9900},
            "pv_estimate10": {"peak_time": "2024-01-01T02:00:00+00:00", "peak_power": 8250},
            "pv_estimate90": {"peak_time": "2024-01-01T02:00:00+00:00", "peak_power": 11000},
        },
    }

    if build:
        expect = {mock: {"pv_estimate": {}, "pv_estimate10": {}, "pv_estimate90": {}} for mock in MOCK}
    for mock, solcast in MOCK.items():
        for day in range(7):
            if not build:
                assert solcast.get_peak_time_day(day).replace(year=2024, month=1, day=1) == dt.fromisoformat(
                    expect[mock]["pv_estimate"]["peak_time"]
                )
                assert solcast.get_peak_power_day(day) == expect[mock]["pv_estimate"]["peak_power"]
            for estimate in ["pv_estimate", "pv_estimate10", "pv_estimate90"]:
                if not build:
                    assert solcast.get_peak_time_day(day, forecast_confidence=estimate).replace(
                        year=2024, month=1, day=1
                    ) == dt.fromisoformat(expect[mock][estimate]["peak_time"])
                    assert solcast.get_peak_power_day(day, forecast_confidence=estimate) == expect[mock][estimate]["peak_power"]
                else:
                    if day > 0:
                        break
                    expect[mock][estimate] = {
                        "peak_time": solcast.get_peak_time_day(day, forecast_confidence=estimate)
                        .replace(year=2024, month=1, day=1)
                        .isoformat(),
                        "peak_power": solcast.get_peak_power_day(day, forecast_confidence=estimate),
                    }
    if build:
        _LOGGER.info(expect)


async def test_get_power_n_minutes(hass: HomeAssistant) -> None:
    """Test get_power_n_minutes."""

    build = False
    expect = {
        "mock1": {
            "pv_estimate": {0: 7221, 30: 7158, 60: 6842},
            "pv_estimate10": {0: 6017, 30: 5965, 60: 5702},
            "pv_estimate90": {0: 8023, 30: 7953, 60: 7603},
        },
        "mock2": {"pv_estimate": {0: 9928, 30: 9842, 60: 9408}, "pv_estimate10": {0: 8274, 30: 8201, 60: 7840}, "pv_estimate90": {}},
    }
    expect_site = {
        "mock1": {
            "1111-1111-1111-1111": {
                "pv_estimate": {0: 4513, 30: 4474, 60: 4276},
                "pv_estimate10": {0: 3761, 30: 3728, 60: 3564},
                "pv_estimate90": {0: 5014, 30: 4971, 60: 4752},
            },
            "2222-2222-2222-2222": {
                "pv_estimate": {0: 2708, 30: 2684, 60: 2566},
                "pv_estimate10": {0: 2256, 30: 2237, 60: 2138},
                "pv_estimate90": {0: 3009, 30: 2982, 60: 2851},
            },
        },
        "mock2": {
            "1111-1111-1111-1111": {
                "pv_estimate": {0: 4513, 30: 4474, 60: 4276},
                "pv_estimate10": {0: 3761, 30: 3728, 60: 3564},
                "pv_estimate90": {},
            },
            "2222-2222-2222-2222": {
                "pv_estimate": {0: 2708, 30: 2684, 60: 2566},
                "pv_estimate10": {0: 2256, 30: 2237, 60: 2138},
                "pv_estimate90": {},
            },
            "3333-3333-3333-3333": {
                "pv_estimate": {0: 2708, 30: 2684, 60: 2566},
                "pv_estimate10": {0: 2256, 30: 2237, 60: 2138},
                "pv_estimate90": {},
            },
        },
    }

    if build:
        expect = {mock: {} for mock in MOCK}
        expect_site = {mock: {} for mock in MOCK}
    for mock, solcast in MOCK.items():
        df = __available_estimates(solcast)

        if not build:
            for minute in range(0, 61, 30):
                assert solcast.get_power_n_minutes(minute) == expect[mock]["pv_" + solcast.options.key_estimate][minute]
        for estimate in ["pv_estimate", "pv_estimate10", "pv_estimate90"]:
            if build:
                expect[mock][estimate] = {}
            for minute in range(0, 61, 30):
                if not build:
                    if estimate in df:
                        assert solcast.get_power_n_minutes(minute, forecast_confidence=estimate) == expect[mock][estimate][minute]
                    else:
                        with pytest.raises(KeyError):
                            solcast.get_power_n_minutes(minute, forecast_confidence=estimate)
                elif estimate in df:
                    expect[mock][estimate][minute] = solcast.get_power_n_minutes(minute, forecast_confidence=estimate)
        for site in solcast.sites:
            if build:
                expect_site[mock][site["resource_id"]] = {"pv_estimate": {}, "pv_estimate10": {}, "pv_estimate90": {}}
            for estimate in ["pv_estimate", "pv_estimate10", "pv_estimate90"]:
                for minute in range(0, 61, 30):
                    if not build:
                        if estimate in df:
                            assert (
                                solcast.get_power_n_minutes(minute, forecast_confidence=estimate, site=site["resource_id"])
                                == expect_site[mock][site["resource_id"]][estimate][minute]
                            )
                        else:
                            with pytest.raises(KeyError):
                                solcast.get_power_n_minutes(minute, forecast_confidence=estimate, site=site["resource_id"])
                    elif estimate in df:
                        expect_site[mock][site["resource_id"]][estimate][minute] = solcast.get_power_n_minutes(
                            minute, forecast_confidence=estimate, site=site["resource_id"]
                        )
    if build:
        _LOGGER.info(expect)
        _LOGGER.info(expect_site)


async def test_get_forecast_n_hour(hass: HomeAssistant) -> None:
    """Test get_forecast_n_hours."""

    build = False
    expect = {
        "mock1": {"pv_estimate": {0: 7200, 1: 6732}, "pv_estimate10": {0: 6000, 1: 5610}, "pv_estimate90": {0: 8000, 1: 7480}},
        "mock2": {"pv_estimate": {0: 9900, 1: 9256}, "pv_estimate10": {0: 8250, 1: 7714}, "pv_estimate90": {}},
    }
    expect_site = {
        "mock1": {
            "1111-1111-1111-1111": {
                "pv_estimate": {0: 4500, 1: 4208},
                "pv_estimate10": {0: 3750, 1: 3506},
                "pv_estimate90": {0: 5000, 1: 4675},
            },
            "2222-2222-2222-2222": {
                "pv_estimate": {0: 2700, 1: 2524},
                "pv_estimate10": {0: 2250, 1: 2104},
                "pv_estimate90": {0: 3000, 1: 2805},
            },
        },
        "mock2": {
            "1111-1111-1111-1111": {"pv_estimate": {0: 4500, 1: 4208}, "pv_estimate10": {0: 3750, 1: 3506}, "pv_estimate90": {}},
            "2222-2222-2222-2222": {"pv_estimate": {0: 2700, 1: 2524}, "pv_estimate10": {0: 2250, 1: 2104}, "pv_estimate90": {}},
            "3333-3333-3333-3333": {"pv_estimate": {0: 2700, 1: 2524}, "pv_estimate10": {0: 2250, 1: 2104}, "pv_estimate90": {}},
        },
    }

    if build:
        expect = {mock: {} for mock in MOCK}
        expect_site = {mock: {} for mock in MOCK}
    for mock, solcast in MOCK.items():
        df = __available_estimates(solcast)

        if not build:
            for hour in range(2):
                assert solcast.get_forecast_n_hour(hour) == expect[mock]["pv_" + solcast.options.key_estimate][hour]
        for estimate in ["pv_estimate", "pv_estimate10", "pv_estimate90"]:
            if build:
                expect[mock][estimate] = {}
            for hour in range(2):
                if not build:
                    if estimate in df:
                        assert solcast.get_forecast_n_hour(hour, forecast_confidence=estimate) == expect[mock][estimate][hour]
                elif estimate in df:
                    expect[mock][estimate][hour] = solcast.get_forecast_n_hour(hour, forecast_confidence=estimate)
        for site in solcast.sites:
            if build:
                expect_site[mock][site["resource_id"]] = {"pv_estimate": {}, "pv_estimate10": {}, "pv_estimate90": {}}
            for estimate in ["pv_estimate", "pv_estimate10", "pv_estimate90"]:
                for hour in range(2):
                    if not build:
                        if estimate in df:
                            assert (
                                solcast.get_forecast_n_hour(hour, forecast_confidence=estimate, site=site["resource_id"])
                                == expect_site[mock][site["resource_id"]][estimate][hour]
                            )
                    elif estimate in df:
                        expect_site[mock][site["resource_id"]][estimate][hour] = solcast.get_forecast_n_hour(
                            hour, forecast_confidence=estimate, site=site["resource_id"]
                        )
    if build:
        _LOGGER.info(expect)
        _LOGGER.info(expect_site)


async def test_get_forecast_custom_hours(hass: HomeAssistant) -> None:
    """Test get_forecast_custom_hours."""

    build = False
    expect = {
        "mock1": {"pv_estimate": 13748, "pv_estimate10": 11457, "pv_estimate90": 15276},
        "mock2": {"pv_estimate": 18904, "pv_estimate10": 15753},
    }
    expect_site = {
        "mock1": {
            "1111-1111-1111-1111": {"pv_estimate": 8593, "pv_estimate10": 7160, "pv_estimate90": 9547},
            "2222-2222-2222-2222": {"pv_estimate": 5156, "pv_estimate10": 4296, "pv_estimate90": 5728},
        },
        "mock2": {
            "1111-1111-1111-1111": {"pv_estimate": 8593, "pv_estimate10": 7160},
            "2222-2222-2222-2222": {"pv_estimate": 5156, "pv_estimate10": 4296},
            "3333-3333-3333-3333": {"pv_estimate": 5156, "pv_estimate10": 4296},
        },
    }
    expect_long = {
        "mock1": {"pv_estimate": 151449, "pv_estimate10": 126207, "pv_estimate90": 168276},
        "mock2": {"pv_estimate": 208242, "pv_estimate10": 173535},
    }

    if build:
        expect = {mock: {} for mock in MOCK}
        expect_site = {mock: {} for mock in MOCK}
        expect_long = {mock: {} for mock in MOCK}
    for mock, solcast in MOCK.items():
        df = __available_estimates(solcast)
        if not build:
            assert solcast.get_forecast_custom_hours(CUSTOM_HOURS) == expect[mock]["pv_" + solcast.options.key_estimate]
        for estimate in ["pv_estimate", "pv_estimate10", "pv_estimate90"]:
            if not build:
                if estimate in df:
                    assert solcast.get_forecast_custom_hours(CUSTOM_HOURS, forecast_confidence=estimate) == expect[mock][estimate]
                    assert solcast.get_forecast_custom_hours(90, forecast_confidence=estimate) == expect_long[mock][estimate]
                else:
                    with pytest.raises(KeyError):
                        solcast.get_forecast_custom_hours(CUSTOM_HOURS, forecast_confidence=estimate)
                    with pytest.raises(KeyError):
                        solcast.get_forecast_custom_hours(90, forecast_confidence=estimate)
            elif estimate in df:
                expect[mock][estimate] = solcast.get_forecast_custom_hours(CUSTOM_HOURS, forecast_confidence=estimate)
                expect_long[mock][estimate] = solcast.get_forecast_custom_hours(90, forecast_confidence=estimate)
        for site in solcast.sites:
            if build:
                expect_site[mock][site["resource_id"]] = {}
            for estimate in ["pv_estimate", "pv_estimate10", "pv_estimate90"]:
                if not build:
                    if estimate in df:
                        assert (
                            solcast.get_forecast_custom_hours(CUSTOM_HOURS, forecast_confidence=estimate, site=site["resource_id"])
                            == expect_site[mock][site["resource_id"]][estimate]
                        )
                    else:
                        with pytest.raises(KeyError):
                            solcast.get_forecast_custom_hours(CUSTOM_HOURS, forecast_confidence=estimate, site=site["resource_id"])
                elif estimate in df:
                    expect_site[mock][site["resource_id"]][estimate] = solcast.get_forecast_custom_hours(
                        CUSTOM_HOURS, forecast_confidence=estimate, site=site["resource_id"]
                    )
    if build:
        _LOGGER.info(expect)
        _LOGGER.info(expect_site)
        _LOGGER.info(expect_long)


async def test_get_forecast_remaining_today(hass: HomeAssistant) -> None:
    """Test get_forecast_remaining_today."""

    build = False
    expect = {
        "mock1": {"pv_estimate": 23.6817, "pv_estimate10": 19.7348, "pv_estimate90": 26.313},
        "mock2": {"pv_estimate": 32.5624, "pv_estimate10": 27.1353},
    }
    expect_site = {
        "mock1": {
            "1111-1111-1111-1111": {"pv_estimate": 14.8011, "pv_estimate10": 12.3342, "pv_estimate90": 16.4456},
            "2222-2222-2222-2222": {"pv_estimate": 8.8807, "pv_estimate10": 7.4005, "pv_estimate90": 9.8674},
        },
        "mock2": {
            "1111-1111-1111-1111": {"pv_estimate": 14.8011, "pv_estimate10": 12.3342},
            "2222-2222-2222-2222": {"pv_estimate": 8.8807, "pv_estimate10": 7.4005},
            "3333-3333-3333-3333": {"pv_estimate": 8.8807, "pv_estimate10": 7.4005},
        },
    }

    if build:
        expect = {mock: {} for mock in MOCK}
        expect_site = {mock: {} for mock in MOCK}
    for mock, solcast in MOCK.items():
        df = __available_estimates(solcast)
        if not build:
            assert solcast.get_forecast_remaining_today() == expect[mock]["pv_" + solcast.options.key_estimate]
        for estimate in ["pv_estimate", "pv_estimate10", "pv_estimate90"]:
            if not build:
                if estimate in df:
                    assert solcast.get_forecast_remaining_today(forecast_confidence=estimate) == expect[mock][estimate]
                else:
                    with pytest.raises(KeyError):
                        solcast.get_forecast_remaining_today(forecast_confidence=estimate)
            elif estimate in df:
                expect[mock][estimate] = solcast.get_forecast_remaining_today(forecast_confidence=estimate)
        for site in solcast.sites:
            if build:
                expect_site[mock][site["resource_id"]] = {}
            for estimate in ["pv_estimate", "pv_estimate10", "pv_estimate90"]:
                if not build:
                    if estimate in df:
                        assert (
                            solcast.get_forecast_remaining_today(forecast_confidence=estimate, site=site["resource_id"])
                            == expect_site[mock][site["resource_id"]][estimate]
                        )
                    else:
                        with pytest.raises(KeyError):
                            solcast.get_forecast_remaining_today(forecast_confidence=estimate, site=site["resource_id"])
                elif estimate in df:
                    expect_site[mock][site["resource_id"]][estimate] = solcast.get_forecast_remaining_today(
                        forecast_confidence=estimate, site=site["resource_id"]
                    )
    if build:
        _LOGGER.info(expect)
        _LOGGER.info(expect_site)


async def test_get_forecast_day(hass: HomeAssistant) -> None:
    """Test get_forecast_day."""

    for solcast in MOCK.values():
        for day in range(7):  # Range of seven because the eighth day can be partially unavailable
            data = solcast.get_forecast_day(day)
            assert data.get("dataCorrect", False) is True
            if solcast.options.attr_brk_halfhourly:
                assert len(data.get("detailedForecast", {})) == 48
                for f in data["detailedForecast"]:
                    assert f.get("period_start") is not None
                    for estimate in ["pv_estimate", "pv_estimate10", "pv_estimate90"]:
                        assert type(f.get(estimate)) is float
            if solcast.options.attr_brk_hourly:
                assert len(data.get("detailedHourly", {})) == 24
                for f in data["detailedHourly"]:
                    assert f.get("period_start") is not None
                    for estimate in ["pv_estimate", "pv_estimate10", "pv_estimate90"]:
                        assert type(f.get(estimate)) is float


async def test_cleanup(hass: HomeAssistant) -> None:
    """Clean up."""
    assert await async_cleanup_integration_tests(hass, MOCK["mock1"]._config_dir)
