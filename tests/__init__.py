"""Tests setup for Solcast Solar integration."""

import copy
from datetime import UTC, datetime as dt, timedelta
from enum import Enum
import logging
from pathlib import Path
import re
from re import Pattern
from typing import Any
from zoneinfo import ZoneInfo

from aiohttp import ClientConnectionError
from freezegun import freeze_time
import pytest
from yarl import URL

from homeassistant.components.solcast_solar.const import (
    API_QUOTA,
    AUTO_DAMPEN,
    AUTO_UPDATE,
    BRK_ESTIMATE,
    BRK_ESTIMATE10,
    BRK_ESTIMATE90,
    BRK_HALFHOURLY,
    BRK_HOURLY,
    BRK_SITE,
    BRK_SITE_DETAILED,
    CONFIG_VERSION,
    CUSTOM_HOUR_SENSOR,
    DOMAIN,
    EXCLUDE_SITES,
    GENERATION_ENTITIES,
    GET_ACTUALS,
    HARD_LIMIT_API,
    KEY_ESTIMATE,
    SITE_DAMP,
    SITE_EXPORT_ENTITY,
    SITE_EXPORT_LIMIT,
    USE_ACTUALS,
)
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .aioresponses import CallbackResult, aioresponses
from .simulator import API_KEY_SITES, GENERATION_FACTOR, SimulatedSolcast

from tests.common import MockConfigEntry

KEY1 = "1"
KEY2 = "2"
KEY_NO_SITES = "no_sites"
CUSTOM_HOURS = 2
DEFAULT_INPUT1_NO_DAMP: dict[str, Any] = {
    CONF_API_KEY: KEY1,
    API_QUOTA: "20",
    AUTO_UPDATE: "1",
    CUSTOM_HOUR_SENSOR: CUSTOM_HOURS,
    HARD_LIMIT_API: "100.0",
    KEY_ESTIMATE: "estimate",
    BRK_ESTIMATE: True,
    BRK_ESTIMATE10: False,
    BRK_ESTIMATE90: False,
    BRK_SITE: False,
    BRK_HALFHOURLY: False,
    BRK_HOURLY: False,
    BRK_SITE_DETAILED: False,
    EXCLUDE_SITES: [],
    AUTO_DAMPEN: False,
    GET_ACTUALS: False,
    USE_ACTUALS: 0,
    GENERATION_ENTITIES: [],
    SITE_EXPORT_ENTITY: "",
    SITE_EXPORT_LIMIT: 0.0,
}

BAD_INPUT = copy.deepcopy(DEFAULT_INPUT1_NO_DAMP)
BAD_INPUT[CONF_API_KEY] = "badkey"

SITE_DAMP_FACTORS: dict[str, float] = {f"damp{factor:02d}": 1.0 for factor in range(24)}
DEFAULT_INPUT1 = DEFAULT_INPUT1_NO_DAMP | SITE_DAMP_FACTORS | {SITE_DAMP: False}
ZONE_RAW = "Australia/Brisbane"  # Somewhere without daylight saving time by default

DEFAULT_INPUT2 = copy.deepcopy(DEFAULT_INPUT1)
DEFAULT_INPUT2[CONF_API_KEY] = KEY1 + "," + KEY2
DEFAULT_INPUT2[AUTO_UPDATE] = 2
DEFAULT_INPUT2[BRK_HOURLY] = True
DEFAULT_INPUT2[BRK_HALFHOURLY] = True
DEFAULT_INPUT2[BRK_ESTIMATE] = False
DEFAULT_INPUT2[BRK_ESTIMATE10] = True
DEFAULT_INPUT2[BRK_ESTIMATE90] = True
DEFAULT_INPUT2[BRK_SITE_DETAILED] = True
DEFAULT_INPUT2[BRK_SITE] = True
DEFAULT_INPUT2[HARD_LIMIT_API] = "12,6"

DEFAULT_INPUT_NO_SITES = copy.deepcopy(DEFAULT_INPUT1)
DEFAULT_INPUT_NO_SITES[CONF_API_KEY] = KEY_NO_SITES

STATUS_401: dict[str, Any] = {
    "response_status": {
        "error_code": "InvalidApiKey",
        "message": "The API key is invalid.",
        "errors": [],
    }
}
STATUS_403: dict[str, Any] = {
    "response_status": {
        "error_code": "Forbidden",
        "message": "The request cannot be made using this API key.",
        "errors": [],
    }
}
STATUS_EMPTY = ""
STATUS_429_OVER: dict[str, Any] = {
    "response_status": {
        "error_code": "TooManyRequests",
        "message": "You have exceeded your free daily limit.",
        "errors": [],
    }
}
STATUS_429_UNEXPECTED: dict[str, Any] = {
    "response_status": {
        "error_code": "NoIdea",
        "message": "I have no idea what you want, but I am busy.",
        "errors": [],
    }
}

MOCK_ALTER_HISTORY = "alter_history"
MOCK_BAD_REQUEST = "return_400"
MOCK_BUSY = "return_429"
MOCK_BUSY_SITE = "return_429_for_site"
MOCK_BUSY_UNEXPECTED = "return_429_unexpected"
MOCK_CORRUPT_SITES = "return_corrupt_sites"
MOCK_CORRUPT_FORECAST = "return_corrupt_forecast"
MOCK_CORRUPT_ACTUALS = "return_corrupt_actuals"
MOCK_EXCEPTION = "exception"
MOCK_FORBIDDEN = "return_403"
MOCK_NOT_FOUND = "return_404"
MOCK_OVER_LIMIT = "return_429_over"

MOCK_SESSION_CONFIG: dict[str, Any] = {
    "aioresponses": None,
    "api_limit": int(min(DEFAULT_INPUT2[API_QUOTA].split(","))),
    "api_used": dict.fromkeys(DEFAULT_INPUT2[CONF_API_KEY].split(","), 0),
    MOCK_ALTER_HISTORY: False,
    MOCK_BAD_REQUEST: False,
    MOCK_BUSY: False,
    MOCK_BUSY_SITE: None,
    MOCK_BUSY_UNEXPECTED: False,
    MOCK_CORRUPT_SITES: False,
    MOCK_CORRUPT_FORECAST: False,
    MOCK_CORRUPT_ACTUALS: False,
    MOCK_EXCEPTION: None,
    MOCK_FORBIDDEN: False,
    MOCK_NOT_FOUND: False,
    MOCK_OVER_LIMIT: False,
}

entity_history = {
    "days_export": 1,
    "days_generation": 7,
    "days_suppression": 7,
    "offset": 3,
}


class ExtraSensors(Enum):
    """The state of the Solcast API."""

    NONE = 0
    YES = 1
    YES_WATT_HOUR = 2
    YES_NO_UNIT = 3
    YES_UNIT_NOT_IN_HISTORY = 4
    YES_WITH_SUPPRESSION = 5
    DODGY = 9


_LOGGER = logging.getLogger(__name__)

simulated: SimulatedSolcast = SimulatedSolcast()


def _check_abend(api_key: str, site: str | None = None) -> CallbackResult | None:
    if MOCK_SESSION_CONFIG[MOCK_BUSY] or (MOCK_SESSION_CONFIG[MOCK_BUSY_SITE] and site == MOCK_SESSION_CONFIG[MOCK_BUSY_SITE]):
        return CallbackResult(status=429, body=STATUS_EMPTY)
    if MOCK_SESSION_CONFIG["api_used"].get(api_key, 0) >= MOCK_SESSION_CONFIG["api_limit"]:
        return CallbackResult(status=429, payload=STATUS_429_OVER)
    if MOCK_SESSION_CONFIG[MOCK_BUSY_UNEXPECTED]:
        return CallbackResult(status=429, payload=STATUS_429_UNEXPECTED)
    if MOCK_SESSION_CONFIG[MOCK_OVER_LIMIT]:
        return CallbackResult(status=429, payload=STATUS_429_OVER)
    if MOCK_SESSION_CONFIG[MOCK_BAD_REQUEST]:
        return CallbackResult(status=400, body=STATUS_EMPTY)
    if API_KEY_SITES.get(api_key) is None:
        return CallbackResult(status=403, payload=STATUS_403)
    if MOCK_SESSION_CONFIG[MOCK_FORBIDDEN]:
        return CallbackResult(status=403, payload=STATUS_403)
    if MOCK_SESSION_CONFIG[MOCK_NOT_FOUND]:
        return CallbackResult(status=404, body=STATUS_EMPTY)
    return None


async def _get_sites(url: str, **kwargs: Any) -> CallbackResult:
    try:
        params: dict[str, Any] | None = kwargs.get("params")
        if params is not None:
            api_key = params["api_key"]
            if (abend := _check_abend(api_key)) is not None:
                return abend
            if MOCK_SESSION_CONFIG[MOCK_CORRUPT_SITES]:
                return CallbackResult(body="Not available, a string response")
            return CallbackResult(payload=simulated.raw_get_sites(api_key))
        return CallbackResult(status=500, body="No params found")
    except Exception as e:  # noqa: BLE001
        _LOGGER.error("Error building sites: %s", e)
        return CallbackResult(status=500, body=str(e))


async def _get_solcast(url: str, get: Any, **kwargs: Any) -> CallbackResult:
    try:
        params: dict[str, Any] | None = kwargs.get("params")
        site = str(url).split("_sites/")[1].split("/")[0]
        if params is not None:
            api_key = params["api_key"]
            hours = params.get("hours", 168)
            if (abend := _check_abend(api_key, site=site)) is not None:
                return abend
            MOCK_SESSION_CONFIG["api_used"][api_key] += 1
            return CallbackResult(payload=get(site, api_key, hours))
        return CallbackResult(status=500, body="No params found")
    except Exception as e:  # noqa: BLE001
        _LOGGER.error("Error building past actual data: %s", e)
        return CallbackResult(status=500, body=str(e))


async def _get_forecasts(url: str, **kwargs: Any) -> CallbackResult:
    if MOCK_SESSION_CONFIG[MOCK_CORRUPT_FORECAST]:
        return CallbackResult(body="Not available, a string response")
    kwargs["params"]["hours"] -= 12  # Intentionally return less hours for testing.
    return await _get_solcast(url, simulated.raw_get_site_forecasts, **kwargs)


async def _get_actuals(url: str, **kwargs: Any) -> CallbackResult:
    if MOCK_SESSION_CONFIG[MOCK_CORRUPT_ACTUALS]:
        return CallbackResult(body="Not available, a string response")
    if kwargs.get("params") is None:
        _LOGGER.error("No params found in kwargs: %s", kwargs)
        return CallbackResult(status=500, body="No params found")
    simulated.modified_actuals = MOCK_SESSION_CONFIG[MOCK_ALTER_HISTORY]
    return await _get_solcast(url, simulated.raw_get_site_estimated_actuals, **kwargs)


def session_reset_usage() -> None:
    """Reset the mock session config."""
    MOCK_SESSION_CONFIG["api_used"] = dict.fromkeys(DEFAULT_INPUT2[CONF_API_KEY].split(","), 0)


def session_set(setting: str, **kwargs: Any) -> None:
    """Set mock session behaviour."""
    if setting == MOCK_BUSY_SITE:
        MOCK_SESSION_CONFIG[setting] = kwargs.get("site")
        return
    MOCK_SESSION_CONFIG[setting] = True if kwargs.get(MOCK_EXCEPTION) is None else kwargs.get(MOCK_EXCEPTION)


def session_clear(setting: str) -> None:
    """Clear mock session behaviour."""
    match setting:
        case "exception":
            MOCK_SESSION_CONFIG[setting] = None
        case "return_429_for_site":
            MOCK_SESSION_CONFIG[setting] = None
        case _:
            MOCK_SESSION_CONFIG[setting] = False


def aioresponses_reset() -> None:
    """Reset the mock session."""
    session_reset_usage()
    if MOCK_SESSION_CONFIG["aioresponses"] is not None:
        MOCK_SESSION_CONFIG["aioresponses"].stop()
        MOCK_SESSION_CONFIG["aioresponses"] = None


def aioresponses_change_url(url: URL | str | Pattern[Any], new_url: URL | str | Pattern[Any]) -> None:
    """Change URL for the mock session."""
    MOCK_SESSION_CONFIG["aioresponses"].change_url(url, new_url)


async def async_setup_aioresponses() -> None:
    """Set up the mock session."""

    aioresponses_reset()
    aioresp = None
    aioresp = aioresponses(passthrough=["http://127.0.0.1"])

    URLS: dict[str, dict[str, Any]] = {
        "sites": {"URL": r"https://api\.solcast\.com\.au/rooftop_sites\?.*api_key=.*$", "callback": _get_sites},
        "forecasts": {"URL": r"https://api\.solcast\.com\.au/rooftop_sites/.+/forecasts.*$", "callback": _get_forecasts},
        "estimated_actuals": {"URL": r"https://api\.solcast\.com\.au/rooftop_sites/.+/estimated_actuals.*$", "callback": _get_actuals},
    }

    exc = MOCK_SESSION_CONFIG["exception"]
    if exc == ClientConnectionError:
        # Modify the URLs to cause a connection error.
        for url in URLS.values():
            url["URL"] = url["URL"].replace("solcast", "solcastxxxx")
        exc = None

    # Set up the mock GET responses.
    aioresp.get("https://api.solcast.com.au", status=200)
    for _get in URLS.values():
        aioresp.get(re.compile(_get["URL"]), status=200, callback=_get["callback"], repeat=99999, exception=exc)

    MOCK_SESSION_CONFIG["aioresponses"] = aioresp


@pytest.mark.asyncio
async def async_setup_extra_sensors(  # noqa: C901
    hass: HomeAssistant, options: dict[str, Any], entry: MockConfigEntry, extra_sensors: ExtraSensors, off: int = 0
) -> None:
    """Set up extra sensors for testing."""

    FASTER = False  # True for fast tests, False for reliable ones.
    BLOCKS = 5  # Number of blocks to wait for async processing when FASTER is True.

    match extra_sensors:
        case ExtraSensors.YES_WATT_HOUR:
            _uom = "Wh"
        case ExtraSensors.YES_UNIT_NOT_IN_HISTORY:
            _uom = "kWh"
        case ExtraSensors.YES_NO_UNIT:
            _uom = ""
        case ExtraSensors.DODGY:
            _uom = "MJ"
        case _:
            _uom = "kWh"

    adjustment = {"kWh": 1.0, "MWh": 1000.0, "Wh": 0.001, "MJ": 1.0, "": 1.0}
    entity_registry = er.async_get(hass)

    power: dict[int, float]
    gen_bumps: dict[int, tuple[list[Any], float]]
    increasing: float

    async def record_history(entity_id: str, new_now: dt, increasing: float, gap: bool) -> None:
        if not FASTER:
            frozen_time.move_to(new_now)
        if not gap:
            if extra_sensors == ExtraSensors.YES_UNIT_NOT_IN_HISTORY:
                if FASTER:
                    hass.states.async_set(
                        entity_id,
                        str(round(increasing / adjustment[_uom], 4)),
                        None,
                        timestamp=dt.timestamp(new_now),
                    )
                    await hass.async_block_till_done()
                    for _ in range(BLOCKS):
                        await hass.async_block_till_done()
                else:
                    await hass.async_add_executor_job(
                        hass.states.set,
                        entity_id,
                        str(round(increasing / adjustment[_uom], 4)),
                        None,
                        True,
                    )
            else:  # noqa: PLR5501
                if FASTER:
                    hass.states.async_set(
                        entity_id,
                        str(round(increasing / adjustment[_uom], 4)),
                        {"unit_of_measurement": _uom},
                        timestamp=dt.timestamp(new_now),
                    )
                    for _ in range(BLOCKS):
                        await hass.async_block_till_done()
                else:
                    await hass.async_add_executor_job(
                        hass.states.set,
                        entity_id,
                        str(round(increasing / adjustment[_uom], 4)),
                        {"unit_of_measurement": _uom},
                        True,
                    )

    # Build entity histories.
    entities: dict[str, float] = {}
    for api_key in options["api_key"].split(","):
        for site in API_KEY_SITES[api_key]["sites"]:
            entities[site["resource_id"]] = site["capacity"]
    entities["site_export_sensor"] = 0.0
    for site, generation in entities.items():
        if site == "3333-3333-3333-3333":
            continue
        power = {}
        if site != "site_export_sensor":
            now = (dt.now(UTC) - timedelta(days=entity_history["days_generation"])).replace(hour=14, minute=0, second=0)
            for interval in range(48):
                power[interval] = (
                    0.5 * generation * GENERATION_FACTOR[interval]
                    if interval < 20
                    else (
                        round(0.7 * 0.5 * generation * GENERATION_FACTOR[interval], 1)
                        if interval > 32
                        else round(0.97 * 0.5 * generation * GENERATION_FACTOR[interval], 1)
                    )
                )
            entity = "solar_export_sensor_" + site.replace("-", "_")
        else:
            now = (dt.now(UTC) - timedelta(days=entity_history["days_export"])).replace(hour=14, minute=0, second=0)
            if extra_sensors == ExtraSensors.DODGY:
                for interval in range(48):
                    power[interval] = 0.0 if (interval < 24 or interval > 34) else (5.0 if interval != 34 else 2.0)
            else:
                for interval in range(48):
                    power[interval] = 0.0 if (interval < 30 or interval > 34) else (5.0 if interval != 34 else 2.0)
            entity = site
        entity_id = "sensor." + entity

        if site != "site_export_sensor" or (extra_sensors != ExtraSensors.YES_NO_UNIT and site == "site_export_sensor"):
            entity_registry.async_get_or_create(
                "sensor",
                "pytest",
                entity,
                config_entry=entry,
                suggested_object_id=entity,
                unit_of_measurement=_uom,
            )

        gap = False
        with freeze_time(
            now + (timedelta(hours=0) if site == "site_export_sensor" else timedelta(days=entity_history["offset"]) - timedelta(hours=off)),
            tz_offset=0,
        ) as frozen_time:
            gen_bumps = {}
            if site in ("1111-1111-1111-1111", "site_export_sensor"):  # 1111 and site export as a generation-consistent profile
                for i, p in power.items():
                    bumps = p / 0.1
                    if bumps > 0:
                        bump_seconds = int(1800 / bumps)  # Use a varying period for each bump to reach interval generation
                        bump_times = list(range(0, 1800, bump_seconds))
                        gen_bumps[i] = (bump_times, 0.1)
            else:  # 2222 as a time-consistent profile
                for i, p in power.items():
                    if p > 0:
                        bump_times = list(range(0, 1800, 303))  # Use a fixed period of 303 seconds for each bump
                        num_bumps = len(bump_times)
                        gen_bumps[i] = (bump_times, p / num_bumps)
            increasing = 0.0
            adjust = 0.0
            increase = True
            intervals: list[int] = []
            for day in range(entity_history["days_generation"] if site != "site_export_sensor" else entity_history["days_export"]):
                intervals = intervals + list(range(day * 48 + 16, day * 48 + 34))  # Focus on middle of day to reduce history build time
            for interval in intervals:
                i = interval % 48
                day = interval // 48
                gap = False
                if day == 1 and site == "1111-1111-1111-1111":
                    continue  # Skip day 1 for first entity to emulate a missing day
                if site == "2222-2222-2222-2222" and i == 0:
                    increasing = 0.0  # Reset for second entity to emulate a resetting daily meter
                if gen_bumps.get(i):
                    bump_t, increment = gen_bumps[i]
                    for sample, b in enumerate(bump_t):
                        if extra_sensors == ExtraSensors.DODGY:
                            if i == 18:
                                if sample in (0, 5, 6, 7, 8, 9):
                                    # Take out samples in interval 19, including the first one
                                    increase = True
                                    gap = True
                                else:
                                    gap = False
                            elif 20 < i < 24:
                                # Introduce flat period, with a catch-up spike to cause odd update by not incrementing
                                adjust += 0.1
                                increase = False
                            elif i == 24:
                                if adjust > 0.0:
                                    increasing += round(adjust, 1)
                                    adjust = 0.0
                                    increase = False
                            elif 25 < i < 29:
                                # Introduce a gap to cause missing data
                                increase = False
                                gap = True
                            elif i == 32:
                                # Introduce a gap with a jump
                                increase = True
                                gap = True
                            if increase:
                                increasing += increment
                            else:
                                increase = True
                        else:
                            increasing += increment
                        new_now = (
                            now
                            + timedelta(days=entity_history["offset"])
                            - timedelta(hours=off)
                            + timedelta(seconds=(day * 86400) + (i * 30 * 60) + b)
                        )
                        await record_history(entity_id, new_now, increasing, gap)

    if extra_sensors == ExtraSensors.YES_WITH_SUPPRESSION:
        entity = "solcast_suppress_auto_dampening"
        entity_registry.async_get_or_create(
            "sensor",
            "pytest",
            entity,
            config_entry=entry,
            suggested_object_id=entity,
            unit_of_measurement=_uom,
        )
        entity_id = "sensor." + entity
        sequence: list[dict[str, Any]] = [
            {"hours": 12, "minutes": 14, "seconds": 5, "value": "on"},
            {"hours": 12, "minutes": 18, "seconds": 5, "value": "off"},
            {"hours": 12, "minutes": 22, "seconds": 5, "value": "1"},
            {"hours": 12, "minutes": 48, "seconds": 5, "value": "0"},
            {"hours": 12, "minutes": 49, "seconds": 5, "value": "true"},
            {"hours": 13, "minutes": 14, "seconds": 5, "value": "false"},
            {"hours": 13, "minutes": 14, "seconds": 50, "value": "yeahnah"},
            {"hours": 13, "minutes": 15, "seconds": 5, "value": "True"},
            {"hours": 13, "minutes": 45, "seconds": 5, "value": "False"},
            {"hours": 13, "minutes": 46, "seconds": 5, "value": "on"},
            {"hours": 14, "minutes": 14, "seconds": 5, "value": "off"},
        ]
        now = (dt.now(UTC) - timedelta(days=entity_history["days_suppression"])).replace(hour=14, minute=0, second=0)
        with freeze_time(
            now,
            tz_offset=0,
        ) as frozen_time:
            for day in range(entity_history["days_suppression"]):
                for s in sequence:
                    frozen_time.move_to(now + timedelta(days=day, hours=s["hours"], minutes=s["minutes"], seconds=s["seconds"]))
                    await hass.async_add_executor_job(
                        hass.states.set,
                        entity_id,
                        s["value"],
                        None,
                        True,
                    )

    # Surplus day energy sensor to be cleaned up.
    entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "solcast_solar_forecast_day_20",
        config_entry=entry,
        translation_key="total_kwh_forecast_d20",
        suggested_object_id="solcast_solar_forecast_day_20",
        unit_of_measurement="kWh",
        original_device_class="energy",
    )


async def async_init_integration(
    hass: HomeAssistant,
    options: dict[str, Any],
    version: int = CONFIG_VERSION,
    mock_api: bool = True,
    timezone: str = ZONE_RAW,
    extra_sensors: ExtraSensors = ExtraSensors.NONE,
) -> MockConfigEntry:
    """Set up the Solcast Solar integration in HomeAssistant."""

    session_reset_usage()

    ZONE = ZoneInfo(timezone)
    simulated.set_time_zone(ZONE)
    simulated.modified_actuals = False

    hass.config.time_zone = timezone

    if options.get(AUTO_UPDATE) is not None:
        options = copy.deepcopy(options)
        options[AUTO_UPDATE] = int(options[AUTO_UPDATE])
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="solcast_pv_solar", title="Solcast PV Forecast", data=options, options=options, version=version
    )

    entry.add_to_hass(hass)

    if extra_sensors is not ExtraSensors.NONE:
        await async_setup_extra_sensors(hass, options, entry, extra_sensors=extra_sensors)

    if mock_api:
        await async_setup_aioresponses()

    # Ensure that a potentially orphaned simple hard limit diagnostic entity is always present.
    entity_registry = er.async_get(hass)
    entity_registry.async_get_or_create("sensor", DOMAIN, unique_id="solcast_pv_forecast_hard_limit_set", config_entry=entry)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    return entry


async def async_cleanup_integration_caches(hass: HomeAssistant, **kwargs: Any) -> bool:
    """Clean up the Solcast Solar integration caches and session."""

    config_dir = hass.config.config_dir

    def list_files() -> list[str]:
        return [str(cache) for cache in Path(config_dir).glob("solcast*.json")]

    try:
        caches = await hass.async_add_executor_job(list_files)
        for cache in caches:
            if not kwargs.get("solcast_dampening", True) and "solcast-dampening" in cache:
                continue
            if not kwargs.get("solcast_sites", True) and "solcast-sites" in cache:
                continue
            _LOGGER.debug("Removing cache file: %s", cache)
            Path(cache).unlink()
    except Exception as e:  # noqa: BLE001
        _LOGGER.error("Error cleaning up Solcast Solar caches: %s", e)
        return False
    return True


async def async_cleanup_integration_tests(hass: HomeAssistant, **kwargs: Any) -> bool:
    """Clean up the Solcast Solar integration caches and session."""

    config_dir = hass.config.config_dir

    def list_files() -> list[str]:
        return [str(cache) for cache in Path(config_dir).glob("solcast*.json")]

    try:
        aioresponses_reset()

        caches = await hass.async_add_executor_job(list_files)
        for cache in caches:
            if not kwargs.get("solcast_dampening", True) and "solcast-dampening" in cache:
                continue
            if not kwargs.get("solcast_sites", True) and "solcast-sites" in cache:
                continue
            _LOGGER.debug("Removing cache file: %s", cache)
            Path(cache).unlink()
    except Exception as e:  # noqa: BLE001
        _LOGGER.error("Error cleaning up Solcast Solar caches: %s", e)
        return False
    return True
