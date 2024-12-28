"""Tests for Solcast Solar integration."""

from contextvars import ContextVar
import copy
import datetime
from datetime import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Any, Final
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

REQUEST_CONTEXT: ContextVar[pytest.FixtureRequest] = ContextVar("request_context", default=None)

ZONE = ZoneInfo(ZONE_RAW)
set_time_zone(ZONE)

_LOGGER = logging.getLogger(__name__)


async def get_sites_api_request(self, url: str, params: dict, headers: dict, ssl: bool) -> Any:
    """Mock get_sites_api_request, returns a valid response."""

    class Response:
        status = 200

        async def json(**kwargs):
            api_key = params["api_key"]
            return raw_get_sites(api_key)

    class BadResponse:
        status = 401

        async def json(**kwargs):
            return {}

    _LOGGER.info("Mock get sites API request: %s", params["api_key"])
    if API_KEY_SITES.get(params["api_key"]) is None:
        return BadResponse

    return Response


async def fetch_data(self, hours: int, path: str = "error", site: str = "", api_key: str = "", force: bool = False) -> dict | None:
    """Mock fetch data call, always returns a valid data structure."""

    if path == "estimated_actuals":
        self._api_used[api_key] += 1
        return raw_get_site_estimated_actuals(site, api_key, 168)
    if path == "forecasts":
        self._api_used[api_key] += 1
        return raw_get_site_forecasts(site, api_key, hours)
    return None


def get_now_utc(self) -> dt:
    """Mock get_now_utc, spoof middle-of-the-day-ish."""

    return dt.now(self._tz).replace(hour=12, minute=27, second=0, microsecond=0).astimezone(datetime.UTC)


def get_real_now_utc(self) -> dt:
    """Mock get_real_now_utc, spoof middle-of-the-day-ish."""

    return dt.now(self._tz).replace(hour=12, minute=27, second=27, microsecond=27272).astimezone(datetime.UTC)


def get_hour_start_utc(self) -> dt:
    """Mock get_hour_start_utc, spoof middle-of-the-day-ish."""

    return dt.now(self._tz).replace(hour=12, minute=0, second=0, microsecond=0).astimezone(datetime.UTC)


SolcastApi.fetch_data = fetch_data
SolcastApi.get_now_utc = get_now_utc
SolcastApi.get_real_now_utc = get_real_now_utc
SolcastApi.get_hour_start_utc = get_hour_start_utc
SolcastApi.get_sites_api_request = get_sites_api_request


class MockedResponse:
    """Mocked response object."""

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.exception = kwargs.get("exception")
        self.keep = kwargs.get("keep", False)

    @property
    def status(self):
        """Return the status code."""
        return self.kwargs.get("status", 200)

    @property
    def url(self):
        """Return the URL."""
        return self.kwargs.get("url", "http://127.0.0.1")

    @property
    def headers(self):
        """Return the headers."""
        return self.kwargs.get("headers", {})

    async def read(self, **kwargs):
        """Return the content."""
        if (content := self.kwargs.get("content")) is not None:
            return content
        return await self.kwargs.get("read", AsyncMock())()

    async def json(self, **kwargs):
        """Return the content as JSON."""
        if (content := self.kwargs.get("content")) is not None:
            return content
        return await self.kwargs.get("json", AsyncMock())()

    async def text(self, **kwargs):
        """Return the content as text."""
        if (content := self.kwargs.get("content")) is not None:
            return content
        return await self.kwargs.get("text", AsyncMock())()

    def raise_for_status(self) -> None:
        """Raise an exception if the status is not 2xx."""
        if self.status >= 300:
            raise ClientError(self.status)


class ResponseMocker:
    """Mocker for responses."""

    calls: list[dict[str, Any]] = []
    responses: dict[str, MockedResponse] = {}

    def add(self, url: str, response: MockedResponse) -> None:
        """Add a response."""
        self.responses[url] = response

    def get(self, url: str, *args, **kwargs) -> MockedResponse:
        """Get a response."""
        data = {"url": url, "args": list(args), "kwargs": kwargs}
        if (request := REQUEST_CONTEXT.get()) is not None:
            data["_test_caller"] = f"{
                request.node.location[0]}::{request.node.name}"
            data["_uses_setup_integration"] = request.node.name != "test_integration_setup" and (
                "setup_integration" in request.fixturenames or "hacs" in request.fixturenames
            )
        self.calls.append(data)
        response = self.responses.get(url, None)
        if response is not None and response.keep:
            return response
        return self.responses.pop(url, None)


async def client_session_proxy(hass: HomeAssistant) -> ClientSession:
    """Create a mocked client session."""
    base = async_get_clientsession(hass)
    base_request = base._request
    response_mocker = ResponseMocker()

    async def _request(method: str, str_or_url: StrOrURL, *args, **kwargs):
        if str_or_url.startswith("ws://"):
            return await base_request(method, str_or_url, *args, **kwargs)

        if (resp := response_mocker.get(str_or_url, args, kwargs)) is not None:
            _LOGGER.info("Using mocked response for %s", str_or_url)
            if resp.exception:
                raise resp.exception
            return resp

        url = URL(str_or_url)
        fixture_file = f"fixtures/proxy/{url.host}{url.path}{'.json' if url.host in (
            'api.github.com', 'data-v2.hacs.xyz') and not url.path.endswith('.json') else ''}"
        fp = os.path.join(
            os.path.dirname(__file__),
            fixture_file,
        )

        if not os.path.exists(fp):
            raise Exception(f"Missing fixture for proxy/{url.host}{url.path}")  # noqa: TRY002

        async def read(**kwargs):
            if url.path.endswith(".zip"):
                with open(fp, mode="rb") as fptr:  # noqa: ASYNC230
                    return fptr.read()
            with open(fp, encoding="utf-8") as fptr:  # noqa: ASYNC230
                return fptr.read().encode("utf-8")

        async def _json(**kwargs):
            with open(fp, encoding="utf-8") as fptr:  # noqa: ASYNC230
                return json.loads(fptr.read())

        return MockedResponse(
            url=url,
            read=read,
            json=_json,
            headers={
                "X-RateLimit-Limit": "999",
                "X-RateLimit-Remaining": "999",
                "X-RateLimit-Reset": "999",
                "Content-Type": "application/json",
            },
        )

    base._request = _request

    return base


async def async_init_integration(
    hass: HomeAssistant, options: dict, version: int = CONFIG_VERSION, mock_api: bool = False
) -> MockConfigEntry:
    """Set up the Solcast Solar integration in HomeAssistant."""

    hass.config.time_zone = ZONE_RAW
    const.SENSOR_UPDATE_LOGGING = True

    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="solcast_pv_solar", title="Solcast PV Forecast", data={}, options=options, version=version
    )
    if mock_api:
        mock_session = await client_session_proxy(hass)
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
