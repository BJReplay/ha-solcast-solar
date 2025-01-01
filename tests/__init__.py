"""Tests for Solcast Solar integration."""

from contextvars import ContextVar
import copy
import datetime
from datetime import datetime as dt
import logging
from pathlib import Path
import re
from typing import Final
from zoneinfo import ZoneInfo

from aiohttp import ClientConnectionError
import pytest

from homeassistant.components.solcast_solar import SolcastApi
import homeassistant.components.solcast_solar.const as const  # noqa: PLR0402
from homeassistant.components.solcast_solar.const import (
    API_QUOTA,
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
    HARD_LIMIT_API,
    KEY_ESTIMATE,
    SITE_DAMP,
)
from homeassistant.components.solcast_solar.sim.simulate import (
    API_KEY_SITES,
    raw_get_site_estimated_actuals,
    raw_get_site_forecasts,
    raw_get_sites,
    set_time_zone,
)
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from .aioresponses import CallbackResult, aioresponses

from tests.common import MockConfigEntry

KEY1: Final = "1"
KEY2: Final = "2"
KEY_NO_SITES = "no_sites"
CUSTOM_HOURS: Final = 2
DEFAULT_INPUT1: Final = {
    CONF_API_KEY: KEY1,
    API_QUOTA: "10",
    AUTO_UPDATE: 1,
    CUSTOM_HOUR_SENSOR: CUSTOM_HOURS,
    HARD_LIMIT_API: "100.0",
    KEY_ESTIMATE: "estimate",
    BRK_ESTIMATE: True,
    BRK_ESTIMATE10: True,
    BRK_ESTIMATE90: True,
    BRK_SITE: True,
    BRK_HALFHOURLY: True,
    BRK_HOURLY: True,
    BRK_SITE_DETAILED: False,
    SITE_DAMP: False,
}

BAD_INPUT = copy.deepcopy(DEFAULT_INPUT1)
BAD_INPUT[CONF_API_KEY] = "badkey"

SITE_DAMP: Final = {f"damp{factor:02d}": 1.0 for factor in range(24)}
DEFAULT_INPUT1 |= SITE_DAMP
ZONE_RAW: Final = "Australia/Brisbane"  # Somewhere without daylight saving time

DEFAULT_INPUT2 = copy.deepcopy(DEFAULT_INPUT1)
DEFAULT_INPUT2[CONF_API_KEY] = KEY1 + "," + KEY2
DEFAULT_INPUT2[AUTO_UPDATE] = 2
DEFAULT_INPUT2[BRK_HALFHOURLY] = True
DEFAULT_INPUT2[BRK_SITE_DETAILED] = True

DEFAULT_INPUT_NO_SITES = copy.deepcopy(DEFAULT_INPUT1)
DEFAULT_INPUT_NO_SITES[CONF_API_KEY] = KEY_NO_SITES

MOCK_SESSION_CONFIG = {
    "api_limit": int(min(DEFAULT_INPUT2[API_QUOTA].split(","))),
    "api_used": {api_key: 0 for api_key in DEFAULT_INPUT2[CONF_API_KEY].split(",")},
    "return_429": False,
    "exception": None,
    "aioresponses": None,
}

REQUEST_CONTEXT: ContextVar[pytest.FixtureRequest] = ContextVar("request_context", default=None)

ZONE = ZoneInfo(ZONE_RAW)
set_time_zone(ZONE)

_LOGGER = logging.getLogger(__name__)


def get_now_utc(self) -> dt:
    """Mock get_now_utc, spoof middle-of-the-day-ish."""

    return dt.now(self._tz).replace(hour=12, minute=27, second=0, microsecond=0).astimezone(datetime.UTC)


def get_real_now_utc(self) -> dt:
    """Mock get_real_now_utc, spoof middle-of-the-day-ish."""

    return dt.now(self._tz).replace(hour=12, minute=27, second=27, microsecond=27272).astimezone(datetime.UTC)


def get_hour_start_utc(self) -> dt:
    """Mock get_hour_start_utc, spoof middle-of-the-day-ish."""

    return dt.now(self._tz).replace(hour=12, minute=0, second=0, microsecond=0).astimezone(datetime.UTC)


# Replace the current date/time functions in SolcastApi.

SolcastApi.get_now_utc = get_now_utc
SolcastApi.get_real_now_utc = get_real_now_utc
SolcastApi.get_hour_start_utc = get_hour_start_utc


def mock_session_config_reset() -> None:
    """Reset the mock session config."""
    MOCK_SESSION_CONFIG["api_used"] = {api_key: 0 for api_key in DEFAULT_INPUT2[CONF_API_KEY].split(",")}


def mock_session_set_too_busy() -> None:
    """Set the mock session to return a 429 error."""
    MOCK_SESSION_CONFIG["return_429"] = True


def mock_session_clear_too_busy() -> None:
    """Clear the mock session to return 429."""
    MOCK_SESSION_CONFIG["return_429"] = False


def mock_session_set_exception(exception: Exception) -> None:
    """Set the mock session to return an exception."""
    MOCK_SESSION_CONFIG["exception"] = exception


def mock_session_clear_exception() -> None:
    """Clear the mock session returned exception."""
    MOCK_SESSION_CONFIG["exception"] = None


STATUS_401 = {
    "response_status": {
        "error_code": "InvalidApiKey",
        "message": "The API key is invalid",
        "errors": [],
    }
}
STATUS_429 = {}
STATUS_429_OVER = {
    "response_status": {
        "error_code": "TooManyRequests",
        "message": "You have exceeded your free daily limit.",
        "errors": [],
    }
}


async def _get_solcast_sites(url, **kwargs) -> CallbackResult:
    try:
        params = kwargs.get("params")
        api_key = params["api_key"]
        if MOCK_SESSION_CONFIG["return_429"]:
            return CallbackResult(status=429, payload=STATUS_429)
        if MOCK_SESSION_CONFIG["api_used"].get(api_key, 0) >= MOCK_SESSION_CONFIG["api_limit"]:
            return CallbackResult(status=429, payload=STATUS_429_OVER)
        if API_KEY_SITES.get(api_key) is None:
            return CallbackResult(status=401, payload=STATUS_401)
        return CallbackResult(payload=raw_get_sites(api_key))
    except Exception as e:  # noqa: BLE001
        _LOGGER.error("Error building sites: %s", e)


async def _get_solcast(url, get, **kwargs) -> CallbackResult:
    try:
        params = kwargs.get("params")
        site = str(url).split("_sites/")[1].split("/")[0]
        api_key = params["api_key"]
        hours = params.get("hours", 168)
        if MOCK_SESSION_CONFIG["return_429"]:
            return CallbackResult(status=429, payload=STATUS_429)
        if MOCK_SESSION_CONFIG["api_used"].get(api_key, 0) >= MOCK_SESSION_CONFIG["api_limit"]:
            return CallbackResult(status=429, payload=STATUS_429_OVER)
        if API_KEY_SITES.get(api_key) is None:
            return CallbackResult(status=401, payload=STATUS_401)
        MOCK_SESSION_CONFIG["api_used"][api_key] += 1
        return CallbackResult(payload=get(site, api_key, hours))
    except Exception as e:  # noqa: BLE001
        _LOGGER.error("Error building past actual data: %s", e)


async def _get_solcast_forecasts(url, **kwargs) -> CallbackResult:
    return await _get_solcast(url, raw_get_site_forecasts, **kwargs)


async def _get_solcast_estimated_actuals(url, **kwargs) -> CallbackResult:
    return await _get_solcast(url, raw_get_site_estimated_actuals, **kwargs)


def mock_session_reset() -> None:
    """Reset the mock session."""
    mock_session_config_reset()
    if MOCK_SESSION_CONFIG["aioresponses"] is not None:
        MOCK_SESSION_CONFIG["aioresponses"].stop()
        MOCK_SESSION_CONFIG["aioresponses"] = None


async def async_init_integration(
    hass: HomeAssistant, options: dict, version: int = CONFIG_VERSION, mock_api: bool = True
) -> MockConfigEntry:
    """Set up the Solcast Solar integration in HomeAssistant."""

    hass.config.time_zone = ZONE_RAW
    const.SENSOR_UPDATE_LOGGING = True

    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="solcast_pv_solar", title="Solcast PV Forecast", data={}, options=options, version=version
    )

    entry.add_to_hass(hass)

    if mock_api:
        mock_session_reset()
        aioresp = None
        aioresp = aioresponses(passthrough=["http://127.0.0.1"])

        URLS = [
            r"https://api\.solcast\.com\.au/rooftop_sites\?.*api_key=.*$",
            r"https://api\.solcast\.com\.au/rooftop_sites/.+/forecasts.*$",
            r"https://api\.solcast\.com\.au/rooftop_sites/.+/estimated_actuals.*$",
        ]
        SITES = 0
        FORECASTS = 1
        ESTIMATED_ACTUALS = 2
        exc = MOCK_SESSION_CONFIG["exception"]
        if exc == ClientConnectionError:
            # Modify the URLs to cause a connection error.
            for n, url in enumerate(URLS):
                URLS[n] = url.replace("solcast", "solcastxxxx")
            exc = None

        aioresp.get("https://api.solcast.com.au", status=200)
        aioresp.get(re.compile(URLS[SITES]), status=200, callback=_get_solcast_sites, repeat=99999, exception=exc)
        aioresp.get(re.compile(URLS[FORECASTS]), status=200, callback=_get_solcast_forecasts, repeat=99999, exception=exc)
        aioresp.get(re.compile(URLS[ESTIMATED_ACTUALS]), status=200, callback=_get_solcast_estimated_actuals, repeat=99999, exception=exc)
        MOCK_SESSION_CONFIG["aioresponses"] = aioresp

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    return entry


async def async_cleanup_integration_tests(hass: HomeAssistant, config_dir: str, **kwargs) -> None:
    """Clean up the Solcast Solar integration caches."""

    def list_files() -> list[str]:
        return [str(cache) for cache in Path(config_dir).glob("solcast*.json")]

    try:
        mock_session_reset()

        caches = await hass.async_add_executor_job(list_files)
        for cache in caches:
            if not kwargs.get("solcast_dampening", True) and "solcast-dampening" in cache:
                continue
            if not kwargs.get("solcast_sites", True) and "solcast-sites" in cache:
                continue
            if not kwargs.get("solcast_usage", True) and "solcast-usage" in cache:
                continue
            _LOGGER.debug("Removing cache file: %s", cache)
            Path(cache).unlink()
    except Exception as e:  # noqa: BLE001
        _LOGGER.error("Error cleaning up Solcast Solar caches: %s", e)
        return False
    return True
