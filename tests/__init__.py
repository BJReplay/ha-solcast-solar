"""Tests for Solcast Solar integration."""

import copy
import datetime
from datetime import datetime as dt
import logging
from pathlib import Path
from typing import Any, Final
from zoneinfo import ZoneInfo

from homeassistant.components.solcast_solar import SolcastApi
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
DEFAULT_INPUT2[API_QUOTA] = "10,10"
DEFAULT_INPUT2[AUTO_UPDATE] = 2
DEFAULT_INPUT2[BRK_HALFHOURLY] = False
DEFAULT_INPUT2[BRK_SITE_DETAILED] = True

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


async def async_init_integration(hass: HomeAssistant, input: dict, version: int = CONFIG_VERSION) -> MockConfigEntry:
    """Set up the Solcast Solar integration in HomeAssistant."""

    hass.config.time_zone = ZONE_RAW

    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="solcast_pv_solar", title="Solcast PV Forecast", data={}, options=input, version=version
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    return entry


async def async_cleanup_integration_tests(hass: HomeAssistant, config_dir: str) -> None:
    """Clean up the Solcast Solar integration caches."""

    def list_files() -> list[str]:
        return [str(cache) for cache in Path(config_dir).glob("solcast*.json")]

    try:
        caches = await hass.async_add_executor_job(list_files)
        for cache in caches:
            _LOGGER.debug("Removing cache file: %s", cache)
            Path(cache).unlink()
    except Exception as e:  # noqa: BLE001
        _LOGGER.error("Error cleaning up Solcast Solar caches: %s", e)
        return False
    return True
