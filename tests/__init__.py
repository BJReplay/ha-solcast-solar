"""Tests for Solcast Solar integration."""

from contextvars import ContextVar
import copy
import datetime
from datetime import datetime as dt
import json
import logging
from pathlib import Path
from typing import Final
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from aiohttp import ClientError, ClientSession
from aiohttp.typedefs import StrOrURL
import pytest
from yarl import URL

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
from homeassistant.helpers.aiohttp_client import async_get_clientsession

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


# Monkey patch the current date/time.

SolcastApi.get_now_utc = get_now_utc
SolcastApi.get_real_now_utc = get_real_now_utc
SolcastApi.get_hour_start_utc = get_hour_start_utc


class MockedResponse:
    """Mocked response object."""

    def __init__(self, **kwargs) -> None:
        """Initialize the object."""
        self.kwargs = kwargs
        self.exception = None
        self.keep = kwargs.get("keep", False)
        self.built_response = ""
        self.built_status = 0

    @property
    def status(self):
        """Return the status code."""
        return self.kwargs.get("status", self.built_status if self.built_status > 0 else 200)

    @property
    def url(self):
        """Return the URL."""
        return self.kwargs.get("url", "http://127.0.0.1")

    async def build_response(self, params: dict):
        """Build the response."""
        build = self.kwargs.get("build")
        if build is not None:
            try:
                self.built_status, self.built_response = await build(params=params, **self.kwargs)
            except Exception as e:  # noqa: BLE001
                _LOGGER.error("Error building response: %s", e)
                self.built_status = 500
                self.built_response = json.dumps({"error": str(e)})

    @property
    def headers(self):
        """Return the headers."""
        return self.kwargs.get("headers", {})

    async def read(self, **kwargs):
        """Return the content."""
        if self.built_response != "":
            return self.built_response
        if (content := self.kwargs.get("content")) is not None:
            return content
        return await self.kwargs.get("read", AsyncMock())()

    async def json(self, **kwargs):
        """Return the content as JSON."""
        if self.built_response != "":
            return json.loads(self.built_response)
        if (content := self.kwargs.get("content")) is not None:
            return json.loads(content)
        return await self.kwargs.get("json", AsyncMock())()

    async def text(self, **kwargs):
        """Return the content as text."""
        if self.built_response != "":
            return self.built_response
        if (content := self.kwargs.get("content")) is not None:
            return content
        return await self.kwargs.get("text", AsyncMock())()

    def raise_for_status(self) -> None:
        """Raise an exception if the status is not 2xx."""
        if self.status >= 300:
            raise ClientError(self.status)


class ResponseMocker:
    """Mocker for responses."""

    responders: dict[str, MockedResponse] = {}

    def add(self, url: str, response: MockedResponse) -> None:
        """Add a response."""
        response.kwargs["url"] = url
        url = URL(url)
        self.responders[url.scheme + "://" + url.host + url.path] = response

    async def get(self, url: URL, params: dict, *args, **kwargs) -> MockedResponse:
        """Get a response."""
        response = self.responders.get(url.scheme + "://" + url.host + url.path, None)
        if response is not None:
            response.exception = MOCK_SESSION_CONFIG["exception"]
            if response.exception is None:
                await response.build_response(params)
        return response


async def client_session_proxy(hass: HomeAssistant, config) -> ClientSession:
    """Create a mocked client session."""
    base = async_get_clientsession(hass)
    response_mocker = ResponseMocker()

    async def _empty(**kwargs):
        return 200, "{}"

    status_401 = {
        "response_status": {
            "error_code": "InvalidApiKey",
            "message": "The API key is invalid",
            "errors": [],
        }
    }
    status_429 = {}
    status_429_over = {
        "response_status": {
            "error_code": "TooManyRequests",
            "message": "You have exceeded your free daily limit.",
            "errors": [],
        }
    }

    async def _get_solcast_sites(**kwargs):
        try:
            params = kwargs.get("params")
            api_key = params["api_key"]
            if config["return_429"]:
                return 429, json.dumps(status_429)
            if config["api_used"].get(api_key, 0) >= config["api_limit"]:
                return 429, json.dumps(status_429_over)
            if API_KEY_SITES.get(api_key) is None:
                return 401, json.dumps(status_401)
            return 200, json.dumps(raw_get_sites(api_key))
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Error building sites: %s", e)
            return 500, json.dumps({"error building sites": str(e)})

    async def _get_solcast(**kwargs):
        try:
            params = kwargs.get("params")
            url = kwargs.get("url")
            site = url.split("_sites/")[1].split("/")[0]
            api_key = params["api_key"]
            hours = params.get("hours", 168)
            if config["return_429"]:
                return 429, json.dumps(status_429)
            if config["api_used"].get(api_key, 0) >= config["api_limit"]:
                return 429, json.dumps(status_429_over)
            if API_KEY_SITES.get(api_key) is None:
                return 401, json.dumps(status_401)
            config["api_used"][api_key] += 1
            return 200, json.dumps(kwargs.get("function")(site, api_key, hours))
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Error building forecast/actual data: %s", e)
            return 500, json.dumps({"Error building forecast/actual data": str(e)})

    response_mocker.add(
        url="https://api.solcast.com.au",
        response=MockedResponse(
            build=_empty,
            headers={"Content-Type": "application/json"},
        ),
    )

    response_mocker.add(
        url="https://api.solcast.com.au/rooftop_sites",
        response=MockedResponse(
            build=_get_solcast_sites,
            headers={"Content-Type": "application/json"},
        ),
    )

    for data in API_KEY_SITES.values():
        for site in data["sites"]:
            try:
                response_mocker.add(
                    url=f"https://api.solcast.com.au/rooftop_sites/{site['resource_id']}/forecasts",
                    response=MockedResponse(
                        build=_get_solcast,
                        function=raw_get_site_forecasts,
                        headers={"Content-Type": "application/json"},
                    ),
                )
                response_mocker.add(
                    url=f"https://api.solcast.com.au/rooftop_sites/{site['resource_id']}/estimated_actuals",
                    response=MockedResponse(
                        build=_get_solcast,
                        function=raw_get_site_estimated_actuals,
                        headers={"Content-Type": "application/json"},
                    ),
                )
            except Exception as e:  # noqa: BLE001
                _LOGGER.error("Error adding estimated_actuals: %s", e)

    async def _request(method: str, str_or_url: StrOrURL, *args, **kwargs):
        if (resp := await response_mocker.get(URL(str_or_url), kwargs.get("params", {}), args, kwargs)) is not None:
            _LOGGER.info("Using mocked response for %s", str_or_url)
            if resp.exception:
                raise resp.exception
            return resp

        return MockedResponse(
            url=URL(str_or_url),
            build=_empty,
            headers={
                "Content-Type": "application/json",
            },
        )

    base._request = _request  # Will generate a deprecation warning

    return base


def mock_session_config_reset():
    """Reset the mock session config."""
    MOCK_SESSION_CONFIG["api_used"] = {api_key: 0 for api_key in DEFAULT_INPUT2[CONF_API_KEY].split(",")}


def mock_session_set_too_busy():
    """Set the mock session to return 429 errors."""
    MOCK_SESSION_CONFIG["return_429"] = True


def mock_session_clear_too_busy():
    """Clear the mock session to return 429 errors."""
    MOCK_SESSION_CONFIG["return_429"] = False


def mock_session_set_exception(exception: Exception):
    """Set the mock session to return exceptions."""
    MOCK_SESSION_CONFIG["exception"] = exception


def mock_session_clear_exception():
    """Clear the mock session to return exceptions."""
    MOCK_SESSION_CONFIG["exception"] = None


async def async_init_integration(
    hass: HomeAssistant, options: dict, version: int = CONFIG_VERSION, mock_api: bool = True
) -> MockConfigEntry:
    """Set up the Solcast Solar integration in HomeAssistant."""

    hass.config.time_zone = ZONE_RAW
    const.SENSOR_UPDATE_LOGGING = True

    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="solcast_pv_solar", title="Solcast PV Forecast", data={}, options=options, version=version
    )
    if mock_api:
        mock_session_config_reset()
        mock_session = await client_session_proxy(hass, MOCK_SESSION_CONFIG)
        with patch(
            "homeassistant.helpers.aiohttp_client.async_get_clientsession",
            return_value=mock_session,
        ):
            entry.add_to_hass(hass)
    else:
        entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    return entry


async def async_cleanup_integration_tests(hass: HomeAssistant, config_dir: str, **kwargs) -> None:
    """Clean up the Solcast Solar integration caches."""

    def list_files() -> list[str]:
        return [str(cache) for cache in Path(config_dir).glob("solcast*.json")]

    try:
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
