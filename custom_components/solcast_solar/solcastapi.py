"""Solcast API."""

# pylint: disable=pointless-string-statement

from __future__ import annotations

import asyncio
from collections import OrderedDict, defaultdict
import contextlib
import copy
from dataclasses import dataclass
import datetime
from datetime import date, datetime as dt, timedelta, tzinfo
import json
import logging
import math
from operator import itemgetter
from pathlib import Path
import random
import re
import sys
import time
import traceback
from types import MappingProxyType
from typing import Any, Final, cast

import aiofiles
from aiohttp import ClientConnectionError, ClientResponseError, ClientSession
from aiohttp.client_reqrep import ClientResponse

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import state_changes_during_period
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, CONF_API_KEY
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from .const import (
    AUTO_DAMPEN,
    BRK_ESTIMATE,
    BRK_ESTIMATE10,
    BRK_ESTIMATE90,
    BRK_HALFHOURLY,
    BRK_HOURLY,
    BRK_SITE,
    BRK_SITE_DETAILED,
    CUSTOM_HOUR_SENSOR,
    DATE_FORMAT,
    DATE_MONTH_DAY,
    DOMAIN,
    EXCLUDE_SITES,
    FORECAST_DAYS,
    GENERATION_ENTITIES,
    GENERATION_VERSION,
    GET_ACTUALS,
    HARD_LIMIT_API,
    KEY_ESTIMATE,
    SITE_DAMP,
    SITE_EXPORT_ENTITY,
    SITE_EXPORT_LIMIT,
    USE_ACTUALS,
)
from .util import (
    Api,
    AutoUpdate,
    DataCallStatus,
    DateTimeEncoder,
    HistoryType,
    JSONDecoder,
    NoIndentEncoder,
    SitesStatus,
    SolcastApiStatus,
    UsageStatus,
    cubic_interp,
    diff,
    find_percentile,
)

API: Final = Api.HOBBYIST  # The API to use. Presently only the hobbyist API is allowed for hobbyist accounts.

# if API == Api.HOBBYIST:
FORECAST: Final = "pv_estimate"
FORECAST10: Final = "pv_estimate10"
FORECAST90: Final = "pv_estimate90"

GRANULAR_DAMPENING_OFF: Final = False
GRANULAR_DAMPENING_ON: Final = True
JSON_VERSION: Final = 7
SET_ALLOW_RESET: Final = True

# Status code translation, HTTP and more.
# A HTTP 418 error is included here for fun. This was introduced in RFC2324#section-2.3.2 as an April Fools joke in 1998.
# 400 >= HTTP error <= 599
# 900 >= Exceptions < 1000, to be potentially handled with retries.
STATUS_TRANSLATE: Final = {
    200: "Success",
    400: "Bad request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not found",
    418: "I'm a teapot",
    420: "Enhance your calm (rate limited)",
    429: "Try again later",
    500: "Internal web server error",
    501: "Not implemented",
    502: "Bad gateway",
    503: "Service unavailable",
    504: "Gateway timeout",
    996: "Connection refused",
    997: "Connect call failed",
    999: "Prior crash",
}

FRESH_DATA: dict[str, Any] = {
    "siteinfo": {},
    "last_updated": dt.fromtimestamp(0, datetime.UTC),
    "last_attempt": dt.fromtimestamp(0, datetime.UTC),
    "auto_updated": 0,
    "failure": {"last_24h": 0, "last_7d": [0] * 7},
    "version": JSON_VERSION,
}

_LOGGER = logging.getLogger(__name__)

# Return the function name at a specified caller depth. 0=current, 1=caller, 2=caller of caller, etc.
FunctionName = lambda n=0: sys._getframe(n + 1).f_code.co_name  # noqa: E731, SLF001 # type: ignore[no-redef]


@dataclass
class ConnectionOptions:
    """Solcast options for the integration."""

    api_key: str
    api_quota: str
    host: str
    file_path: str
    tz: tzinfo
    auto_update: AutoUpdate
    dampening: dict[str, float]
    custom_hour_sensor: int
    key_estimate: str
    hard_limit: str
    attr_brk_estimate: bool
    attr_brk_estimate10: bool
    attr_brk_estimate90: bool
    attr_brk_site: bool
    attr_brk_halfhourly: bool
    attr_brk_hourly: bool
    attr_brk_site_detailed: bool
    exclude_sites: list[str]
    get_actuals: bool
    use_actuals: HistoryType
    generation_entities: list[str]
    site_export_entity: str
    site_export_limit: float
    auto_dampen: bool


class SolcastApi:  # pylint: disable=too-many-public-methods
    """The Solcast API."""

    def __init__(
        self,
        aiohttp_session: ClientSession,
        options: ConnectionOptions,
        hass: HomeAssistant,
        entry: ConfigEntry | None = None,
    ) -> None:
        """Initialise the API interface.

        Arguments:
            aiohttp_session (ClientSession): The aiohttp client session provided by Home Assistant
            options (ConnectionOptions): The integration stored configuration options.
            hass (HomeAssistant): The Home Assistant instance.
            entry (ConfigEntry): The entry options.

        """

        self.auto_update_divisions: int = 0
        self.custom_hour_sensor: int = options.custom_hour_sensor
        self.damp: dict[str, float] = options.dampening
        self.entry = entry
        self.entry_options: dict[str, Any] = {}
        if self.entry is not None:
            self.entry_options = {**self.entry.options}
        self.estimate_set: list[str] = self.__get_estimate_set(options)
        self.granular_dampening: dict[str, list[float]] = {}
        self.granular_dampening_mtime: float = 0
        self.hard_limit: str = options.hard_limit
        self.hass: HomeAssistant = hass
        self.headers: dict[str, str] = {}
        self.latest_period: dt | None = None
        self.options: ConnectionOptions = options
        self.reauth_required: bool = False
        self.sites: list[dict[str, Any]] = []
        self.sites_status: SitesStatus = SitesStatus.UNKNOWN
        self.status: SolcastApiStatus = SolcastApiStatus.OK
        self.tasks: dict[str, Any] = {}
        self.usage_status: UsageStatus = UsageStatus.UNKNOWN

        file_path = Path(options.file_path)

        self._aiohttp_session = aiohttp_session
        self._api_limit: dict[str, int] = {}
        self._api_used: dict[str, int] = {}
        self._api_used_reset: dict[str, dt | None] = {}
        self._auto_dampening_factors: dict[dt, float] = {}
        self._data: dict[str, Any] = copy.deepcopy(FRESH_DATA)
        self._data_actuals: dict[str, Any] = copy.deepcopy(FRESH_DATA)
        self._data_actuals_dampened: dict[str, Any] = copy.deepcopy(FRESH_DATA)
        self._data_energy_dashboard: dict[str, Any] = {}
        self._data_estimated_actuals: list[dict[str, Any]] = []
        self._data_estimated_actuals_dampened: list[dict[str, Any]] = []
        self._data_forecasts: list[dict[str, Any]] = []
        self._data_forecasts_undampened: list[dict[str, Any]] = []
        self._data_generation: dict[str, list[dict[str, Any]] | Any] = {
            "last_updated": dt.fromtimestamp(0, datetime.UTC),
            "generation": [],
            "version": GENERATION_VERSION,
        }
        self._data_undampened: dict[str, Any] = copy.deepcopy(FRESH_DATA)
        self._extant_sites: defaultdict[str, list[dict[str, Any]]] = defaultdict(list[dict[str, Any]])
        self._extant_usage: defaultdict[str, dict[str, Any]] = defaultdict(dict[str, Any])
        self._filename = options.file_path
        self._filename_actuals = f"{file_path.parent / file_path.stem}-actuals{file_path.suffix}"
        self._filename_actuals_dampened = f"{file_path.parent / file_path.stem}-actuals-dampened{file_path.suffix}"
        self._filename_generation = f"{file_path.parent / file_path.stem}-generation{file_path.suffix}"
        self._filename_undampened = f"{file_path.parent / file_path.stem}-undampened{file_path.suffix}"
        self._forecasts_moment: dict[str, dict[str, list[float]]] = {}
        self._forecasts_remaining: dict[str, dict[str, list[float]]] = {}
        self._granular_allow_reset = True
        self._loaded_data = False
        self._next_update: str | None = None
        self._rekey: dict[str, Any] = {}
        self._peak_intervals: dict[int, float] = dict.fromkeys(range(48), -1.0)
        self._site_data_forecasts: dict[str, list[dict[str, Any]]] = {}
        self._site_data_forecasts_undampened: dict[str, list[dict[str, Any]]] = {}
        self._site_latitude: defaultdict[str, dict[str, bool | float | int | None]] = defaultdict(dict[str, bool | float | int | None])
        self._sites_hard_limit: defaultdict[str, Any] = defaultdict(dict)
        self._sites_hard_limit_undampened: defaultdict[str, Any] = defaultdict(dict)
        self._spline_period = list(range(0, 90000, 1800))
        self._serialise_lock = asyncio.Lock()
        self._tally: dict[str, float | None] = {}
        self._tz = options.tz
        self._use_forecast_confidence = f"pv_{options.key_estimate}"

        self._config_dir = hass.config.config_dir
        _LOGGER.debug("Configuration directory is %s", self._config_dir)

    async def tasks_cancel(self):
        """Cancel all tasks."""

        for task, cancel in self.tasks.items():
            _LOGGER.debug("Cancelling solcastapi task %s", task)
            cancel.cancel()

    async def set_options(self, options: MappingProxyType[str, Any]):
        """Set the class option variables (called by __init__ to avoid an integration reload).

        Arguments:
            options (dict): The integration entry options.

        """
        self.damp = {str(hour): options[f"damp{hour:02}"] for hour in range(24)}
        self.options = ConnectionOptions(
            # All these options require a reload, and can not be dynamically set, hence retrieval from self.options...
            self.options.api_key,
            self.options.api_quota,
            self.options.host,
            self.options.file_path,
            self.options.tz,
            self.options.auto_update,
            # Options that can be dynamically set...
            self.damp,
            options[CUSTOM_HOUR_SENSOR],
            options.get(KEY_ESTIMATE, self.options.key_estimate),
            options.get(HARD_LIMIT_API, "100.0"),
            options[BRK_ESTIMATE],
            options[BRK_ESTIMATE10],
            options[BRK_ESTIMATE90],
            options[BRK_SITE],
            options[BRK_HALFHOURLY],
            options[BRK_HOURLY],
            options[BRK_SITE_DETAILED],
            options[EXCLUDE_SITES],
            options[GET_ACTUALS],
            options[USE_ACTUALS],
            options[GENERATION_ENTITIES],
            options[SITE_EXPORT_ENTITY],
            options[SITE_EXPORT_LIMIT],
            options[AUTO_DAMPEN],
        )
        self.hard_limit = self.options.hard_limit
        self._use_forecast_confidence = f"pv_{self.options.key_estimate}"
        self.estimate_set = self.__get_estimate_set(self.options)

    def __get_estimate_set(self, options: ConnectionOptions) -> list[str]:
        estimate_set: list[str] = []
        if options.attr_brk_estimate:
            estimate_set.append("pv_estimate")
        if options.attr_brk_estimate10:
            estimate_set.append("pv_estimate10")
        if options.attr_brk_estimate90:
            estimate_set.append("pv_estimate90")
        return estimate_set

    def get_data(self) -> dict[str, Any]:
        """Return the data dictionary.

        Returns:
            list: Dampened forecast detail list of the sum of all site forecasts.

        """
        return self._data

    def is_stale_data(self) -> bool:
        """Return whether the forecast was last updated some time ago (i.e. is stale).

        Returns:
            bool: True for stale, False if updated recently.

        """
        last_updated = self.get_last_updated()
        return last_updated is not None and last_updated < self.get_day_start_utc(future=-1)

    def is_stale_usage_cache(self) -> bool:
        """Return whether the usage cache was last reset over 24-hours ago (i.e. is stale).

        Returns:
            bool: True for stale, False if reset recently.

        """
        api_keys = self.options.api_key.split(",")
        for api_key in api_keys:
            api_key = api_key.strip()
            api_used_reset = self._api_used_reset.get(api_key)
            if api_used_reset is not None and api_used_reset < self.__get_utc_previous_midnight():
                return True
        return False

    def __translate(self, status: int) -> str | Any:
        """Translate HTTP status code to a human-readable translation.

        Arguments:
            status (int): A HTTP status code.

        Returns:
            str: Human readable HTTP status.

        """
        return (f"{status}/{STATUS_TRANSLATE[status]}") if STATUS_TRANSLATE.get(status) else status

    def __redact_api_key(self, api_key: str) -> str:
        """Obfuscate API key.

        Arguments:
            api_key (str): An individual Solcast account API key.

        Returns:
            str: The last six characters of the key, prepended by six asterisks.

        """
        return "*" * 6 + api_key[-6:]

    def __redact_msg_api_key(self, msg: str, api_key: str) -> str:
        """Obfuscate API key in messages.

        Arguments:
            msg (str): Typically a message to be logged.
            api_key (str): An individual Solcast account API key.

        Returns:
            str: The message, with API key obfuscated.

        """
        return (
            msg.replace("key=" + api_key, "key=" + self.__redact_api_key(api_key))
            .replace("key': '" + api_key, "key': '" + self.__redact_api_key(api_key))
            .replace("sites-" + api_key, "sites-" + self.__redact_api_key(api_key))
            .replace("usage-" + api_key, "usage-" + self.__redact_api_key(api_key))
        )

    def __is_multi_key(self) -> bool:
        """Test whether multiple API keys are in use.

        Returns:
            bool: True for multiple API Solcast accounts configured. If configured then separate files will be used for caches.

        """
        return len(self.options.api_key.split(",")) > 1

    def __get_usage_cache_filename(self, api_key: str) -> str:
        """Build an API cache filename.

        Arguments:
            api_key (str): An individual Solcast account API key.

        Returns:
            str: A fully qualified cache filename using a simple name or separate files for more than one API key.

        """
        return f"{self._config_dir}/solcast-usage{'' if not self.__is_multi_key() else '-' + api_key}.json"

    def __get_sites_cache_filename(self, api_key: str) -> str:
        """Build a site details cache filename.

        Arguments:
            api_key (str): An individual Solcast account API key.

        Returns:
            str: A fully qualified cache filename using a simple name or separate files for more than one API key.

        """
        return f"{self._config_dir}/solcast-sites{'' if not self.__is_multi_key() else '-' + api_key}.json"

    def get_granular_dampening_filename(self) -> str:
        """Build a fully qualified site dampening filename.

        Arguments:
            legacy (bool): Return the name of the legacy per-site dampening file.

        Returns:
            str: A fully qualified cache filename.

        """
        return f"{self._config_dir}/solcast-dampening.json"

    async def serialise_data(self, data: dict[str, Any], filename: str) -> bool:
        """Serialize data to file.

        Arguments:
            data (dict): The data to serialise.
            filename (str): The name of the file

        Returns:
            bool: Success or failure.

        """
        if self._loaded_data and data["last_updated"] != dt.fromtimestamp(0, datetime.UTC):
            payload = json.dumps(data, ensure_ascii=False, cls=DateTimeEncoder)
            async with self._serialise_lock, aiofiles.open(filename, "w") as file:
                await file.write(payload)
            log_file = {
                self._filename: "dampened",
                self._filename_undampened: "undampened",
                self._filename_actuals: "estimated actual",
                self._filename_actuals_dampened: "dampened estimated actual",
                self._filename_generation: "generation",
            }
            _LOGGER.debug(
                "Saved %s cache",
                log_file.get(filename, "unknown"),
            )
            return True
        _LOGGER.error("Not serialising empty data for %s", filename)
        return False

    def __redact_lat_lon_simple(self, s: str) -> str:
        return re.sub(r"\.[0-9]+", ".******", s)

    def __redact_lat_lon(self, s: str) -> str:
        return re.sub(r"itude\': [0-9\-\.]+", "itude': **.******", s)

    async def __sites_data(self, prior_crash: bool = False, use_cache: bool = True) -> tuple[int, str, str]:  # noqa: C901
        """Request site details.

        If the sites cannot be loaded then the integration cannot function, and this will
        result in Home Assistant repeatedly trying to initialise.

        If the sites cache exists and is valid then it is loaded on API error.

        Arguments:
            prior_crash (bool): When a prior crash during init has occurred use cached sites, and do not call Solcast.
            use_cache (bool): When True, use the cache if it exists and is valid.

        Returns:
            tuple[int, str, str]: The status code, message and relevant API key.

        """
        one_only = False
        status = 999

        async def load_cache(cache_filename: str) -> dict[str, Any]:
            _LOGGER.info("Loading cached sites for %s", self.__redact_api_key(api_key))
            async with aiofiles.open(cache_filename) as file:
                return json.loads(await file.read())

        async def save_cache(cache_filename: str, response_data: dict[str, Any]):
            _LOGGER.debug("Writing sites cache for %s", self.__redact_api_key(api_key))
            async with self._serialise_lock, aiofiles.open(cache_filename, "w") as file:
                await file.write(json.dumps(response_json, ensure_ascii=False))

        def cached_sites_unavailable(at_least_one_only: bool = False) -> None:
            nonlocal one_only

            if not at_least_one_only:
                _LOGGER.error(
                    "Cached sites are not yet available for %s to cope with API call failure",
                    self.__redact_api_key(api_key),
                )
                _LOGGER.error("At least one successful API 'get sites' call is needed, so the integration will not function correctly")
                one_only = True

        def set_sites(response_json: dict[str, Any], api_key: str) -> None:
            sites_data = response_json
            _LOGGER.debug(
                "Sites data received %s",
                self.__redact_msg_api_key(self.__redact_lat_lon(str(sites_data)), api_key),
            )
            for site in sites_data["sites"]:
                site["api_key"] = api_key
                site.pop("longitude", None)
                self._site_latitude[site["resource_id"]]["latitude"] = site.pop("latitude", None)
                self._site_latitude[site["resource_id"]]["azimuth"] = site["azimuth"]
            self.sites = self.sites + sites_data["sites"]
            self._api_used_reset[api_key] = None
            _LOGGER.debug(
                "Sites loaded%s",
                (" for " + self.__redact_api_key(api_key)) if self.__is_multi_key() else "",
            )

        def check_rekey(response_json: dict[str, Any], api_key: str) -> bool:
            _LOGGER.debug("Checking rekey for %s", self.__redact_api_key(api_key))

            cache_status = False
            all_sites = sorted([site["resource_id"] for site in response_json["sites"]])
            self._rekey[api_key] = None
            for key in self._extant_sites:
                extant_sites = sorted([site["resource_id"] for site in self._extant_sites[key]])
                if all_sites == extant_sites:
                    if api_key != key:
                        # Re-keyed API key...
                        # * Update the sites cache to the new key (an API failure may have occurred on load).
                        # Note that if an API failure had occurred then the sites are not really known, so this key change is a guess at best.
                        _LOGGER.info("API key %s has changed", self.__redact_api_key(api_key))
                        self._rekey[api_key] = key
                        for site in response_json["sites"]:
                            site["api_key"] = api_key
                    cache_status = True
            return cache_status

        self.sites = []
        api_key_in_error = ""
        api_keys = self.options.api_key.split(",")

        try:
            for api_key in api_keys:
                response_json: dict[str, Any] = {}
                api_key = api_key.strip()
                cache_filename = self.__get_sites_cache_filename(api_key)
                cache_exists = Path(cache_filename).is_file()
                if not cache_exists:
                    prior_crash = False
                _LOGGER.debug(
                    "%s",
                    f"Sites cache {'exists' if cache_exists else 'does not yet exist'} for {self.__redact_api_key(api_key)}",
                )
                success = False

                if not prior_crash:
                    url = f"{self.options.host}/rooftop_sites"
                    params = {"format": "json", "api_key": api_key}
                    _LOGGER.debug("Connecting to %s?format=json&api_key=%s", url, self.__redact_api_key(api_key))
                    response: ClientResponse = await self._aiohttp_session.get(url=url, params=params, headers=self.headers, ssl=False)
                    status = response.status
                    (_LOGGER.debug if status == 200 else _LOGGER.warning)(
                        "HTTP session returned status %s%s",
                        self.__translate(status),
                        ", trying cache" if status not in (200, 403) and cache_exists and use_cache else "",
                    )
                    text_response = ""
                    try:
                        text_response = await response.text()
                        if text_response != "":
                            response_json = json.loads(text_response)
                    except json.decoder.JSONDecodeError:
                        _LOGGER.error("API did not return a json object, returned `%s`", text_response)
                        status = 500
                else:
                    status = 999  # Force a cache load instead of using the API

                if status == 200:
                    for site in response_json.get("sites", []):
                        site["api_key"] = api_key
                    if response_json["total_records"] > 0:
                        set_sites(response_json, api_key)
                        _ = check_rekey(response_json, api_key)
                        await save_cache(cache_filename, response_json)
                        success = True
                        self.sites_status = SitesStatus.OK
                    else:
                        _LOGGER.error(
                            "No sites for the API key %s are configured at solcast.com",
                            self.__redact_api_key(api_key),
                        )
                        cache_exists = False  # Prevent cache load if no sites
                        self.sites_status = SitesStatus.NO_SITES
                        api_key_in_error = self.__redact_api_key(api_key)
                        break

                if not success:
                    if cache_exists and use_cache:
                        _LOGGER.warning(
                            "Get sites failed, last call result: %s, using cached data",
                            self.__translate(status),
                        )
                    else:
                        _LOGGER.error(
                            "Get sites failed, last call result: %s",
                            self.__translate(status),
                        )
                    if status != 200:
                        api_key_in_error = self.__redact_api_key(api_key)
                    if status != 200 and cache_exists and use_cache:
                        response_json = await load_cache(cache_filename)
                        success = True
                        self.sites_status = SitesStatus.OK
                        if status == 403:
                            self.sites_status = SitesStatus.BAD_KEY
                            break
                        status = 200
                        if not check_rekey(response_json, api_key):
                            self.sites_status = SitesStatus.CACHE_INVALID
                            _LOGGER.info(
                                "API key %s has changed and sites are different invalidating the cache, not using cached data",
                                self.__redact_api_key(api_key),
                            )
                            success = False
                        if success:
                            set_sites(response_json, api_key)
                    elif not cache_exists:
                        cached_sites_unavailable()
                        if status in (401, 403):
                            self.sites_status = SitesStatus.BAD_KEY
                            break
                        if status in (429, 420):
                            self.sites_status = SitesStatus.API_BUSY
                            break
                        self.sites_status = SitesStatus.ERROR
                        api_key_in_error = self.__redact_api_key(api_key)
                        break

                if status == 200 and success:
                    pass
                else:
                    cached_sites_unavailable(at_least_one_only=True)
        except (ClientConnectionError, ClientResponseError, ConnectionRefusedError, TimeoutError) as e:
            _LOGGER.error("Connection error: %s", e)
            self.sites_status = SitesStatus.ERROR
            api_key_in_error = ""
            _LOGGER.error("Error retrieving sites: %s", e)
            if use_cache:
                _LOGGER.info("Attempting to continue with cached sites")
                error = False
                self.sites = []
                for api_key in api_keys:
                    api_key = api_key.strip()
                    cache_filename = self.__get_sites_cache_filename(api_key)
                    if Path(cache_filename).is_file():  # Cache exists, so load it
                        response_json = await load_cache(cache_filename)
                        set_sites(response_json, api_key)
                        _ = check_rekey(response_json, api_key)
                        self.sites_status = SitesStatus.OK
                    else:
                        self.sites_status = SitesStatus.ERROR
                        error = True
                        cached_sites_unavailable()
                        api_key_in_error = self.__redact_api_key(api_key)
                        break
                if error:
                    _LOGGER.error(
                        "Suggestion: Check your overall HA configuration, specifically networking related (Is IPV6 an issue for you? DNS? Proxy?)"
                    )
            return (
                200 if self.sites_status == SitesStatus.OK else 999,
                "Cached sites loaded" if self.sites_status == SitesStatus.OK else "Cached sites not loaded",
                api_key_in_error,
            )
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Exception in __sites_data(): %s: %s", e, traceback.format_exc())
            return 999, f"Exception in __sites_data(): {e}", ""

        return status, self.__translate(status), api_key_in_error

    async def __serialise_usage(self, api_key: str, reset: bool = False):
        """Serialise the usage cache file.

        Arguments:
            api_key (str): An individual Solcast account API key.
            reset (bool): Whether to reset API key usage to zero.

        """
        filename = self.__get_usage_cache_filename(api_key)
        if reset:
            self._api_used_reset[api_key] = self.__get_utc_previous_midnight()
        _LOGGER.debug(
            "Writing API usage cache %s",
            self.__redact_msg_api_key(filename, api_key),
        )
        json_content: dict[str, Any] = {
            "daily_limit": self._api_limit[api_key],
            "daily_limit_consumed": self._api_used[api_key],
            "reset": self._api_used_reset[api_key],
        }
        payload = json.dumps(json_content, ensure_ascii=False, cls=DateTimeEncoder)
        async with self._serialise_lock, aiofiles.open(filename, "w") as file:
            await file.write(payload)

    async def __sites_usage(self):
        """Load api usage cache.

        The Solcast API for hobbyists is limited in the number of API calls that are
        allowed, and usage of this quota is tracked by the integration. There is not
        currently an API call to determine limit and usage, hence this tracking.

        The limit is specified by the user in integration configuration.
        """
        try:

            async def sanitise_and_set_usage(api_key: str, usage: dict[str, Any]):
                self._api_limit[api_key] = usage.get("daily_limit", 10)
                assert isinstance(self._api_limit[api_key], int), "daily_limit is not an integer"
                self._api_used[api_key] = usage.get("daily_limit_consumed", 0)
                assert isinstance(self._api_used[api_key], int), "daily_limit_consumed is not an integer"
                self._api_used_reset[api_key] = usage.get("reset", self.__get_utc_previous_midnight())
                assert isinstance(self._api_used_reset[api_key], dt), "reset is not a datetime"
                if (used_reset := self._api_used_reset[api_key]) is not None:
                    _LOGGER.debug(
                        "Usage cache for %s last reset %s",
                        self.__redact_api_key(api_key),
                        used_reset.astimezone(self._tz).strftime(DATE_FORMAT),
                    )
                if usage["daily_limit"] != quota[api_key]:  # Limit has been adjusted, so rewrite the cache.
                    self._api_limit[api_key] = quota[api_key]
                    await self.__serialise_usage(api_key)
                    _LOGGER.info("Usage loaded and cache updated with new limit")
                else:
                    _LOGGER.debug(
                        "Usage loaded%s",
                        (" for " + self.__redact_api_key(api_key)) if self.__is_multi_key() else "",
                    )
                if used_reset is not None:
                    if self.get_real_now_utc() > used_reset + timedelta(hours=24):
                        _LOGGER.warning(
                            "Resetting usage for %s, last reset was more than 24-hours ago",
                            self.__redact_api_key(api_key),
                        )
                        self._api_used[api_key] = 0
                        await self.__serialise_usage(api_key, reset=True)

            self.usage_status = UsageStatus.OK
            api_keys = self.options.api_key.split(",")
            api_quota = self.options.api_quota.split(",")
            for index in range(len(api_keys)):  # If only one quota value is present, yet there are multiple sites then use the same quota.
                if len(api_quota) < index + 1:
                    api_quota.append(api_quota[index - 1])
            quota = {api_keys[index].strip(): int(api_quota[index].strip()) for index in range(len(api_quota))}

            for api_key in api_keys:
                api_key = api_key.strip()
                old_api_key = self._rekey.get(api_key)  # For a re-keyed API key.
                cache_filename = self.__get_usage_cache_filename(api_key)
                _LOGGER.debug(
                    "%s for %s",
                    "Usage cache " + ("exists" if Path(cache_filename).is_file() else "does not yet exist"),
                    self.__redact_api_key(api_key),
                )
                cache = True
                usage: dict[str, Any] = {}
                if Path(cache_filename).is_file():
                    usage = self._extant_usage.get(old_api_key, {}) if old_api_key is not None else {}
                    if not old_api_key:
                        async with aiofiles.open(cache_filename) as file:
                            try:
                                usage = json.loads(await file.read(), cls=JSONDecoder)
                            except json.decoder.JSONDecodeError:
                                _LOGGER.error(
                                    "The usage cache for %s is corrupt, re-creating cache with zero usage",
                                    self.__redact_api_key(api_key),
                                )
                                cache = False
                    if cache and usage:
                        await sanitise_and_set_usage(api_key, usage)
                else:
                    cache = False
                if not cache:
                    if old_api_key:
                        # Multi-key, so the old cache has been removed
                        _LOGGER.debug("Using extant cache data for API key %s", self.__redact_api_key(api_key))
                        usage = self._extant_usage.get(old_api_key, {}) if old_api_key is not None else {}
                        await sanitise_and_set_usage(api_key, usage)
                    else:
                        _LOGGER.warning("Creating usage cache for %s, assuming zero API used", self.__redact_api_key(api_key))
                        self._api_limit[api_key] = quota[api_key]
                        self._api_used[api_key] = 0
                        self._api_used_reset[api_key] = self.__get_utc_previous_midnight()
                    await self.__serialise_usage(api_key, reset=True)
                _LOGGER.debug(
                    "API counter for %s is %d/%d",
                    self.__redact_api_key(api_key),
                    self._api_used[api_key],
                    self._api_limit[api_key],
                )

        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Exception in __sites_usage(): %s: %s", e, traceback.format_exc())
            self.usage_status = UsageStatus.ERROR

    async def reset_usage_cache(self):
        """Reset all usage caches."""
        api_keys = self.options.api_key.split(",")
        for api_key in api_keys:
            api_key = api_key.strip()
            self._api_used[api_key] = 0
            await self.__serialise_usage(api_key, reset=True)

    async def get_sites_and_usage(self, prior_crash: bool = False, use_cache: bool = True) -> tuple[int, str, str]:  # noqa: C901
        """Get the sites and usage, and validate API key changes against the cache files in use.

        Both the sites and usage are gathered here.

        Additionally, transitions from a multi-API key set up to a single API key are
        tracked at startup, and necessary adjustments are made to file naming.

        Single key installations have cache files named like `solcast-sites.json`, while
        multi-key installations have caches named `solcast-sites-api_key.json`

        The reason is that sites are loaded in groups of API key, and similarly for API
        usage, so these must be cached separately.

        Arguments:
            prior_crash (bool): When a prior crash during init has occurred use cached sites, and do not call Solcast.
            use_cache (bool): When True, use the cache if it exists and is valid.

        Returns:
            tuple[int, str, str]: The status code, message and relevant API key from load sites.

        """
        issue_registry = ir.async_get(self.hass)

        def rename(file1: str, file2: str, api_key: str):
            if Path(file1).is_file():
                _LOGGER.info("Renaming %s to %s", self.__redact_msg_api_key(file1, api_key), self.__redact_msg_api_key(file2, api_key))
                Path(file1).rename(Path(file2))

        async def test_unusual_azimuth() -> None:
            """Test for unusual azimuth values."""
            _LOGGER.debug("Testing for unusual azimuth values")
            any_unusual = False
            raise_issue = ""
            for site, v in self._site_latitude.items():
                unusual = False
                proposal = 0
                if v["latitude"] is None:
                    # Using cached data, so latitude is not known
                    continue
                if "latitude" in v and "azimuth" in v:
                    azimuth = v["azimuth"]
                    if azimuth is not None:
                        if v["latitude"] > 0:
                            # Northern hemisphere, so azimuth should be 90 to 180, or -90 to -180
                            raise_issue = "unusual_azimuth_northern"
                            if azimuth > 0 and not (90 <= azimuth <= 180):
                                unusual = True
                                proposal = 180 - int(azimuth)
                            if azimuth < 0 and not (-180 <= azimuth <= -90):
                                unusual = True
                                proposal = -180 - int(azimuth)
                        else:
                            # Southern hemisphere, so azimuth should be 0 to 90, or -90 to 0
                            raise_issue = "unusual_azimuth_southern"
                            if azimuth > 0 and not (0 <= azimuth <= 90):
                                unusual = True
                                proposal = 180 - int(azimuth)
                            if azimuth < 0 and not (-90 <= azimuth <= 0):
                                unusual = True
                                proposal = -180 - int(azimuth)
                    if unusual:
                        any_unusual = True
                        log = (
                            _LOGGER.warning
                            if issue_registry.async_get_issue(DOMAIN, "unusual_azimuth_northern") is None
                            and issue_registry.async_get_issue(DOMAIN, "unusual_azimuth_southern") is None
                            else _LOGGER.debug
                        )
                        log(self.__redact_lat_lon_simple(f"Unusual azimuth {azimuth} for site {site}, latitude {v['latitude']}"))

                if unusual:
                    # If azimuth is unusual then raise an issue.
                    _LOGGER.debug("Raise issue `%s` for site %s", raise_issue, site)
                    ir.async_create_issue(
                        self.hass,
                        DOMAIN,
                        raise_issue,
                        is_fixable=False,
                        is_persistent=True,
                        severity=ir.IssueSeverity.WARNING,
                        translation_key=raise_issue,
                        translation_placeholders={
                            "site": site,
                            "latitude": str(v["latitude"]),
                            "proposal": str(proposal),
                            "extant": str(v["azimuth"]),
                            "learn_more": "",
                        },
                        learn_more_url="https://github.com/BJReplay/ha-solcast-solar?tab=readme-ov-file#solcast-requirements",
                    )
                    break
            if not any_unusual and issue_registry.async_get_issue(DOMAIN, "unusual_azimuth_northern") is not None:
                _LOGGER.debug("Remove issue for %s", "unusual_azimuth_northern")
                ir.async_delete_issue(self.hass, DOMAIN, "unusual_azimuth_northern")
            if not any_unusual and issue_registry.async_get_issue(DOMAIN, "unusual_azimuth_southern") is not None:
                _LOGGER.debug("Remove issue for %s", "unusual_azimuth_southern")
                ir.async_delete_issue(self.hass, DOMAIN, "unusual_azimuth_southern")

        async def from_single_site_to_multi(api_keys: list[str]):
            """Transition from a single API key to multiple API keys."""
            single_sites = f"{self._config_dir}/solcast-sites.json"
            single_usage = f"{self._config_dir}/solcast-usage.json"
            if Path(single_sites).is_file():
                async with aiofiles.open(single_sites) as file:
                    single_api_key = json.loads(await file.read(), cls=JSONDecoder)["sites"][0].get("api_key", api_keys[0])
                multi_sites = f"{self._config_dir}/solcast-sites-{single_api_key}.json"
                if not Path(multi_sites).is_file() and Path(single_sites).is_file():
                    multi_usage = f"{self._config_dir}/solcast-usage-{single_api_key}.json"
                    rename(single_sites, multi_sites, single_api_key)
                    rename(single_usage, multi_usage, single_api_key)

        async def from_multi_site_to_single(api_keys: list[str]):
            """Transition from multiple API keys to a single API key."""
            single_sites = f"{self._config_dir}/solcast-sites.json"
            if not Path(single_sites).is_file():
                rename(f"{self._config_dir}/solcast-sites-{api_keys[0]}.json", single_sites, api_keys[0])
                rename(f"{self._config_dir}/solcast-usage-{api_keys[0]}.json", f"{self._config_dir}/solcast-usage.json", api_keys[0])

        def remove_orphans(all_cached: list[str], multi_cached: list[str]):
            """Remove orphaned cache files."""
            for file in all_cached:
                if file not in multi_cached:
                    component_parts = re.search(r"(.+solcast-(sites-|usage-))(.+)(\.json)", file)
                    if component_parts is not None:
                        _LOGGER.warning(
                            "Removing orphaned %s",
                            component_parts.group(1) + "******" + component_parts.group(3)[-6:] + component_parts.group(4),
                        )
                        Path(file).unlink()

        def list_all_files() -> tuple[list[str], list[str]]:
            sites = [str(sites) for sites in Path(self._config_dir).glob("solcast-sites*.json")]
            usage = [str(usage) for usage in Path(self._config_dir).glob("solcast-usage*.json")]
            return sorted(sites), sorted(usage)

        def list_multi_key_files() -> tuple[list[str], list[str]]:
            sites = [str(sites) for sites in Path(self._config_dir).glob("solcast-sites-*.json")]
            usage = [str(usage) for usage in Path(self._config_dir).glob("solcast-usage-*.json")]
            return sorted(sites), sorted(usage)

        async def load_extant_sites_and_usage(sites: list[str], usages: list[str]):
            extant_sites: dict[str, list[dict[str, Any]]] = defaultdict(list)  # Existing sites in caches
            extant_usage: dict[str, dict[str, Any]] = defaultdict(dict)  # Existing usage in caches, separated by API key
            single_key = None
            for site in sites:
                async with aiofiles.open(site) as file:
                    try:
                        response_json = json.loads(await file.read(), cls=JSONDecoder)
                    except json.decoder.JSONDecodeError:
                        _LOGGER.error("JSONDecodeError, sites ignored: %s", site)
                        continue
                    for _site in response_json.get("sites", []):
                        if _site.get("api_key"):
                            extant_sites[_site["api_key"]].append(_site)
                            if not self.__is_multi_key():
                                single_key = _site["api_key"]
                        elif not self.__is_multi_key():  # The key is unknown because old schema version
                            extant_sites["unknown"].append(_site)
            for usage in usages:
                async with aiofiles.open(usage) as file:
                    try:
                        response_json = json.loads(await file.read(), cls=JSONDecoder)
                    except json.decoder.JSONDecodeError:
                        _LOGGER.error("JSONDecodeError, usage ignored: %s", usage)
                        continue
                    match = re.search(r"solcast-usage-(.+)\.json", usage)
                    if match:
                        extant_usage[match.group(1)] = response_json
                    elif not self.__is_multi_key() and single_key:
                        extant_usage[single_key] = response_json
                    else:  # The key is unknown because old schema version
                        extant_usage["unknown"] = response_json
            return extant_sites, extant_usage

        api_keys = [api_key.strip() for api_key in self.options.api_key.split(",")]
        if self.__is_multi_key():
            await from_single_site_to_multi(api_keys)
        else:
            await from_multi_site_to_single(api_keys)
        multi_sites = [f"{self._config_dir}/solcast-sites-{api_key}.json" for api_key in api_keys]
        multi_usage = [f"{self._config_dir}/solcast-usage-{api_key}.json" for api_key in api_keys]

        all_sites, all_usage = await self.hass.async_add_executor_job(list_all_files)
        multi_key_sites, multi_key_usage = await self.hass.async_add_executor_job(list_multi_key_files)
        self._extant_sites, self._extant_usage = await load_extant_sites_and_usage(all_sites, all_usage)
        remove_orphans(multi_key_sites, multi_sites)
        remove_orphans(multi_key_usage, multi_usage)

        status, message, api_key_in_error = await self.__sites_data(prior_crash=prior_crash, use_cache=use_cache)
        if self.sites_status == SitesStatus.OK:
            await test_unusual_azimuth()
            await self.__sites_usage()

        return status, message, api_key_in_error

    async def reset_api_usage(self, force: bool = False):
        """Reset the daily API usage counter.

        Arguments:
            force (bool): Force the reset even if the cache is not stale.

        """
        if force or self.is_stale_usage_cache():
            _LOGGER.debug("Reset API usage")
            for api_key in self._api_used:
                self._api_used[api_key] = 0
                await self.__serialise_usage(api_key, reset=True)
        else:
            _LOGGER.debug("Usage cache is fresh, so not resetting")

    async def serialise_granular_dampening(self):
        """Serialise the site dampening file."""
        filename = self.get_granular_dampening_filename()
        _LOGGER.debug("Writing granular dampening to %s", filename)
        payload = json.dumps(
            self.granular_dampening,
            ensure_ascii=False,
            cls=NoIndentEncoder,
            indent=2,
        )
        async with self._serialise_lock, aiofiles.open(filename, "w") as file:
            await file.write(payload)
        self.granular_dampening_mtime = Path(filename).stat().st_mtime
        _LOGGER.debug(
            "Granular dampening file mtime %s",
            dt.fromtimestamp(self.granular_dampening_mtime, self._tz).strftime(DATE_FORMAT),
        )

    async def granular_dampening_data(self) -> bool:
        """Read the current granular dampening file.

        Returns:
            bool: Granular dampening in use.

        """

        def option(enable: bool, set_allow_reset: bool = False):
            site_damp = self.entry_options.get(SITE_DAMP, False) if self.entry_options.get(SITE_DAMP) is not None else False
            if enable ^ site_damp:
                options = {**self.entry_options}
                options[SITE_DAMP] = enable
                self.entry_options[SITE_DAMP] = enable
                if set_allow_reset:
                    self._granular_allow_reset = enable
                if self.entry is not None:
                    self.hass.config_entries.async_update_entry(self.entry, options=options)
            return enable

        error = False
        return_value = False
        mtime = True
        filename = self.get_granular_dampening_filename()
        try:
            if not Path(filename).is_file():
                self.granular_dampening = {}
                self.granular_dampening_mtime = 0
                mtime = False
                return option(GRANULAR_DAMPENING_OFF)
            async with aiofiles.open(filename) as file:
                try:
                    response_json = json.loads(await file.read())
                except json.decoder.JSONDecodeError:
                    _LOGGER.error("JSONDecodeError, dampening ignored: %s", filename)
                    error = True
                    return option(GRANULAR_DAMPENING_OFF, SET_ALLOW_RESET)
                self.granular_dampening = cast(dict[str, Any], response_json)
                if self.granular_dampening:
                    first_site_len = 0
                    for site, damp_list in self.granular_dampening.items():
                        if first_site_len == 0:
                            first_site_len = len(damp_list)
                        elif len(damp_list) != first_site_len:
                            _LOGGER.error(
                                "Number of dampening factors for all sites must be the same in %s, dampening ignored",
                                filename,
                            )
                            self.granular_dampening = {}
                            error = True
                        if len(damp_list) not in (24, 48):
                            _LOGGER.error(
                                "Number of dampening factors for site %s must be 24 or 48 in %s, dampening ignored",
                                site,
                                filename,
                            )
                            self.granular_dampening = {}
                            error = True
                    if error:
                        return_value = option(GRANULAR_DAMPENING_OFF, SET_ALLOW_RESET)
                    else:
                        _LOGGER.debug("Granular dampening %s", str(self.granular_dampening))
                        return_value = option(GRANULAR_DAMPENING_ON, SET_ALLOW_RESET)
            return return_value
        finally:
            if mtime:
                self.granular_dampening_mtime = Path(filename).stat().st_mtime if Path(filename).exists() else 0
            if error:
                self.granular_dampening = {}

    async def refresh_granular_dampening_data(self) -> None:
        """Load granular dampening data if the file has changed."""
        if Path(self.get_granular_dampening_filename()).is_file():
            mtime = Path(self.get_granular_dampening_filename()).stat().st_mtime
            if mtime != self.granular_dampening_mtime:
                await self.granular_dampening_data()
                _LOGGER.info("Granular dampening loaded")
                _LOGGER.debug(
                    "Granular dampening file mtime %s",
                    dt.fromtimestamp(mtime, self._tz).strftime(DATE_FORMAT),
                )

    def allow_granular_dampening_reset(self) -> bool:
        """Allow options change to reset the granular dampening file to an empty dictionary."""
        return self._granular_allow_reset

    def set_allow_granular_dampening_reset(self, enable: bool) -> None:
        """Set/clear allow reset granular dampening file to an empty dictionary by options change."""
        self._granular_allow_reset = enable

    async def get_dampening(self, site: str | None, site_underscores: bool) -> list[dict[str, Any]]:
        """Retrieve the currently set dampening factors.

        Arguments:
            site (str): An optional site.
            site_underscores (bool): Whether to replace dashes with underscores in returned site names.

        Returns:
            (list): The action response for the presently set dampening factors.

        """
        if self.entry_options.get(SITE_DAMP):
            if not site:
                sites = [_site["resource_id"] for _site in self.sites]
            else:
                sites = [site]
            all_set = self.granular_dampening.get("all") is not None
            if site:
                if not all_set:
                    if site in self.granular_dampening:
                        return [
                            {
                                "site": _site if not site_underscores else _site.replace("-", "_"),
                                "damp_factor": ",".join(str(factor) for factor in self.granular_dampening[_site]),
                            }
                            for _site in sites
                            if self.granular_dampening.get(_site)
                        ]
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key="damp_not_for_site",
                        translation_placeholders={"site": site},
                    )
                if site != "all":
                    if site in self.granular_dampening:
                        _LOGGER.warning(
                            "There is dampening for site %s, but it is being overridden by an all sites entry, returning the 'all' entries instead",
                            site,
                        )
                    else:
                        _LOGGER.warning(
                            "There is no dampening set for site %s, but it is being overridden by an all sites entry, returning the 'all' entries instead",
                            site,
                        )
                return [
                    {
                        "site": "all",
                        "damp_factor": ",".join(str(factor) for factor in self.granular_dampening["all"]),
                    }
                ]
            if all_set:
                return [
                    {
                        "site": "all",
                        "damp_factor": ",".join(str(factor) for factor in self.granular_dampening["all"]),
                    }
                ]
            return [
                {
                    "site": _site if not site_underscores else _site.replace("-", "_"),
                    "damp_factor": ",".join(str(factor) for factor in self.granular_dampening[_site]),
                }
                for _site in sites
                if self.granular_dampening.get(_site)
            ]
        if not site or site == "all":
            return [
                {
                    "site": "all",
                    "damp_factor": ",".join(str(factor) for _, factor in self.damp.items()),
                }
            ]
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="damp_use_all",
            translation_placeholders={"site": site},
        )

    async def load_saved_data(self) -> str:  # noqa: C901
        """Load the saved solcast.json data.

        This also checks for new API keys and site removal.

        Returns:
            str: A failure status message, or an empty string.

        """
        file = ""
        try:
            status = ""
            if len(self.sites) > 0:

                async def load_data(filename: str, set_loaded: bool = True) -> dict[str, Any] | None:
                    nonlocal file

                    if Path(filename).is_file():
                        file = filename
                        async with aiofiles.open(filename) as data_file:
                            json_data: dict[str, Any] = json.loads(await data_file.read(), cls=JSONDecoder)
                            json_version = json_data.get("version", 1)
                            _LOGGER.debug(
                                "Data cache %s exists, file type is %s",
                                filename,
                                type(json_data),
                            )
                            data = json_data
                            if set_loaded:
                                self._loaded_data = True
                            log_file = {
                                self._filename: "Dampened",
                                self._filename_undampened: "Undampened",
                                self._filename_actuals: "Estimated actual",
                                self._filename_actuals_dampened: "Dampened estimated actual",
                            }
                            _LOGGER.debug("%s data loaded", log_file.get(filename, "Unknown"))
                            if json_version != JSON_VERSION:
                                _LOGGER.info(
                                    "Upgrading %s cache version from v%d to v%d",
                                    filename.lower(),
                                    json_version,
                                    JSON_VERSION,
                                )
                                # If the file structure must change then upgrade it
                                on_version = json_version

                                # Test for incompatible data
                                incompatible = "The solcast.json appears incompatible, so cannot upgrade it"
                                if data.get("siteinfo") is None and data.get("forecasts") is None:
                                    # Need one or the other to be able to upgrade.
                                    _LOGGER.critical(incompatible)
                                    self.status = SolcastApiStatus.DATA_INCOMPATIBLE
                                if data.get("siteinfo") is not None:
                                    if not isinstance(
                                        data.get("siteinfo", {}).get(self.sites[0]["resource_id"], {}).get("forecasts"), list
                                    ):
                                        self.status = SolcastApiStatus.DATA_INCOMPATIBLE
                                if data.get("forecasts") is not None:
                                    if not isinstance(data.get("forecasts"), list):
                                        self.status = SolcastApiStatus.DATA_INCOMPATIBLE
                                if self.status == SolcastApiStatus.DATA_INCOMPATIBLE:
                                    _LOGGER.critical(incompatible)
                                    return None

                                # What happened before v4 stays before v4. BJReplay has no visibility of ancient.
                                # V3 and prior versions of the solcast.json file did not have a version key.
                                if json_version < 4:
                                    data["version"] = 4
                                    json_version = 4
                                # Add "last_attempt" and "auto_updated" to cache structure as of v5, introduced v4.2.5.
                                # Ancient v3 versions of this code did not have the "siteinfo" key to contain forecasts, so fix that.
                                if json_version < 5:
                                    data["version"] = 5
                                    data["last_attempt"] = data["last_updated"]
                                    data["auto_updated"] = self.options.auto_update != AutoUpdate.NONE
                                    if data.get("siteinfo") is None:
                                        if (
                                            data.get("forecasts") is not None
                                            and len(self.sites) > 0
                                            and self.sites[0].get("resource_id") is not None
                                        ):
                                            data["siteinfo"] = {self.sites[0]["resource_id"]: {"forecasts": data.get("forecasts")}}
                                            data.pop("forecasts", None)
                                            data.pop("energy", None)
                                    json_version = 5
                                # Alter "auto_updated" boolean flag to be the integer number of auto-update divisions, introduced v4.3.0.
                                if json_version < 6:
                                    data["version"] = 6
                                    data["auto_updated"] = 99999 if self.options.auto_update != AutoUpdate.NONE else 0
                                    json_version = 6
                                # Add "failure" statistics to cache structure, introduced v4.3.5.
                                if json_version < 7:
                                    data["version"] = 7
                                    data["failure"] = {"last_24h": 0, "last_7d": [0] * 7}
                                    json_version = 7

                                if json_version > on_version:
                                    await self.serialise_data(data, filename)
                        return data
                    return None

                async def load_generation_data() -> dict[str, Any] | None:
                    nonlocal file

                    if Path(self._filename_generation).is_file():
                        file = self._filename_generation
                        async with aiofiles.open(self._filename_generation) as data_file:
                            json_data: dict[str, Any] = json.loads(await data_file.read(), cls=JSONDecoder)
                            _LOGGER.debug(
                                "Data cache %s exists, file type is %s",
                                self._filename_generation,
                                type(json_data),
                            )
                            data = json_data
                            _LOGGER.debug("Generation data loaded")
                        return data
                    return None

                async def adds_moves_changes():
                    # Check for any new API keys so no sites data yet for those, and also for API key change.
                    serialise = False
                    reset_usage = False
                    new_sites: dict[str, str] = {}
                    cache_sites = list(self._data["siteinfo"].keys())
                    old_api_keys = (
                        self.hass.data[DOMAIN].get("old_api_key", self.hass.data[DOMAIN]["entry_options"].get(CONF_API_KEY, "")).split(",")
                    )
                    for site in self.sites:
                        api_key = site["api_key"]
                        site = site["resource_id"]
                        if site not in cache_sites or len(self._data["siteinfo"][site].get("forecasts", [])) == 0:
                            new_sites[site] = api_key
                            if (
                                api_key not in old_api_keys
                            ):  # If a new site is seen in conjunction with an API key change then reset the usage.
                                reset_usage = True
                    with contextlib.suppress(Exception):
                        del self.hass.data[DOMAIN]["old_api_key"]

                    if reset_usage:
                        _LOGGER.info("An API key has changed with a new site added, resetting usage")
                        await self.reset_api_usage(force=True)

                    if len(new_sites.keys()) > 0:
                        # Some site data does not exist yet so get it.
                        # Do not alter self._data['last_attempt'], as this is not a scheduled thing
                        _LOGGER.info("New site(s) have been added, so getting forecast data for them")
                        for site, api_key in new_sites.items():
                            await self.__http_data_call(site=site, api_key=api_key, do_past_hours=168)

                        _now = dt.now(datetime.UTC).replace(microsecond=0)
                        update: dict[str, Any] = {"last_updated": _now, "last_attempt": _now, "version": JSON_VERSION}
                        self._data |= update
                        self._data_undampened |= update
                        self._data_actuals |= update
                        serialise = True

                        self._loaded_data = True

                    # Check for sites that need to be removed.
                    remove_sites: list[str] = []
                    configured_sites = [site["resource_id"] for site in self.sites]
                    for site in cache_sites:
                        if site not in configured_sites:
                            _LOGGER.warning(
                                "Site resource id %s is no longer configured, will remove saved data from %s, %s, %s, %s",
                                site,
                                self._filename,
                                self._filename_undampened,
                                self._filename_actuals,
                                self._filename_actuals_dampened,
                            )
                            remove_sites.append(site)

                    for site in remove_sites:
                        for data in [self._data, self._data_undampened, self._data_actuals]:
                            with contextlib.suppress(Exception):
                                del data["siteinfo"][site]
                    if len(remove_sites) > 0:
                        serialise = True

                    if serialise:
                        await self.apply_forward_dampening()
                        for filename, data in {
                            self._filename: self._data,
                            self._filename_undampened: self._data_undampened,
                            self._filename_actuals: self._data_actuals,
                            self._filename_actuals_dampened: self._data_actuals,
                        }.items():
                            await self.serialise_data(data, filename)

                dampened_data = await load_data(self._filename)
                if dampened_data:
                    self._data = dampened_data
                    # Load the un-dampened history
                    undampened_data = await load_data(self._filename_undampened, set_loaded=False)
                    if undampened_data:
                        self._data_undampened = undampened_data
                    # Load the estimated actuals history
                    actuals_data = await load_data(self._filename_actuals, set_loaded=False)
                    if actuals_data:
                        self._data_actuals = actuals_data
                    # Load the dampened estimated actuals history
                    actuals_dampened_data = await load_data(self._filename_actuals_dampened, set_loaded=False)
                    if actuals_dampened_data:
                        self._data_actuals_dampened = actuals_dampened_data
                    elif actuals_data:
                        self._data_actuals_dampened = actuals_data
                    # Load the generation history
                    generation_data = await load_generation_data()
                    if generation_data:
                        self._data_generation = generation_data
                    # If configured to get generation but there is no cached data, then get it.
                    if self.options.auto_dampen and self.options.generation_entities and len(self._data_generation["generation"]) == 0:
                        await self.get_pv_generation()
                    # Check for sites changes.
                    await adds_moves_changes()
                    # Migrate un-dampened history data to the un-dampened cache if needed.
                    await self.__migrate_undampened_history()
                else:
                    if self.status != SolcastApiStatus.OK:
                        return ""
                    # There is no cached data, so start fresh.
                    self._data = copy.deepcopy(FRESH_DATA)
                    self._data_undampened = copy.deepcopy(FRESH_DATA)
                    self._data_actuals = copy.deepcopy(FRESH_DATA)
                    self._data_actuals_dampened = copy.deepcopy(FRESH_DATA)
                    self._loaded_data = False

                if not self._loaded_data:
                    # No file to load.
                    _LOGGER.warning("There is no solcast.json to load, so fetching solar forecast, including past forecasts")
                    # Could be a brand new install of the integration, or the file has been removed. Get the forecast and past actuals.
                    status = await self.get_forecast_update(do_past_hours=168)
                    self._loaded_data = True
                    for filename, data in {
                        self._filename: self._data,
                        self._filename_undampened: self._data_undampened,
                        self._filename_actuals: self._data_actuals,
                        self._filename_actuals_dampened: self._data_actuals_dampened,
                    }.items():
                        await self.serialise_data(data, filename)
        except json.decoder.JSONDecodeError:
            _LOGGER.error("The cached data in %s is corrupt in load_saved_data()", file)
            status = f"The cached data in {file} is corrupted, suggest removing or repairing it"
        return status

    async def build_forecast_and_actuals(self) -> str:
        """Build the forecast and estimated actual data."""

        status = ""
        if self._loaded_data:
            # Create an up-to-date forecast.
            if not await self.build_forecast_data():
                status = "Failed to build forecast data (corrupt config/solcast.json?)"
            elif self.options.get_actuals:
                if not await self.build_actual_data():
                    status = "Failed to build estimated actual data (corrupt config/solcast-actuals.json?)"
        return status

    async def reset_failure_stats(self) -> None:
        """Reset the failure statistics."""

        _LOGGER.debug("Resetting failure statistics")
        self._data["failure"]["last_24h"] = 0
        self._data["failure"]["last_7d"] = [0, *self._data["failure"]["last_7d"][:-1]]
        await self.serialise_data(self._data, self._filename)

    def get_last_attempt(self) -> dt:
        """Get the date/time of last attempted forecast update.

        Returns:
            dt: The date/time of last attempt.

        """
        return self._data["last_attempt"].replace(microsecond=0)

    def get_failures_last_24h(self) -> int:
        """Get the number of failures in the last 24 hours.

        Returns:
            int: The number of failures in the last 24 hours.

        """
        return self._data["failure"]["last_24h"]

    def get_failures_last_7d(self) -> int:
        """Get the number of failures in the last 7 days.

        Returns:
            list[int]: The number of failures in the last 7 days.

        """
        return sum(self._data["failure"]["last_7d"])

    async def delete_solcast_file(self, *args: tuple[Any]) -> None:
        """Delete the solcast json files.

        Note: This will immediately trigger a forecast get with estimated actual history, so this
        is an integration reset.

        Arguments:
            args (tuple): Not used.

        """
        _LOGGER.debug("Action to delete old solcast json files")
        for filename in [self._filename, self._filename_undampened, self._filename_actuals, self._filename_actuals_dampened]:
            if Path(filename).is_file():
                Path(filename).unlink()
            else:
                _LOGGER.warning("There is no %s to delete", filename.split("/")[-1])
        self._loaded_data = False
        await self.load_saved_data()

    async def get_forecast_list(self, *args: Any) -> tuple[dict[str, Any], ...]:
        """Get forecasts.

        Arguments:
            args (tuple): [0] (dt) = from timestamp, [1] (dt) = to timestamp, [2] = site, [3] (bool) = dampened or un-dampened.

        Returns:
            tuple(dict[str, Any], ...): Forecasts representing the range specified.

        """

        if args[2] == "all":
            data_forecasts = self._data_forecasts if not args[3] else self._data_forecasts_undampened
        else:
            data_forecasts = self._site_data_forecasts[args[2]] if not args[3] else self._site_data_forecasts_undampened[args[2]]
        start_index, end_index = self.__get_list_slice(data_forecasts, args[0], args[1], search_past=True)
        if start_index == 0 and end_index == 0:
            # Range could not be found
            raise ValueError("Range is invalid")
        forecast_slice = data_forecasts[start_index:end_index]

        return tuple({**data, "period_start": data["period_start"].astimezone(self._tz)} for data in forecast_slice)

    async def get_estimate_list(self, *args: Any) -> tuple[dict[str, Any], ...]:
        """Get estimated actuals.

        Arguments:
            args (tuple): [0] (dt) = from timestamp, [1] (dt) = to timestamp.

        Returns:
            tuple(dict[str, Any], ...): Estimated actuals representing the range specified.

        """

        start_index, end_index = self.__get_list_slice(self._data_estimated_actuals, args[0], args[1], search_past=True)
        if start_index == 0 and end_index == 0:
            # Range could not be found
            raise ValueError("Range is invalid")
        estimate_slice = self._data_estimated_actuals[start_index:end_index]

        return tuple({**data, "period_start": data["period_start"].astimezone(self._tz)} for data in estimate_slice)

    def get_api_used_count(self) -> int:
        """Return API polling count for this UTC 24hr period (minimum of all API keys).

        A maximum is used because forecasts are polled at the same time for each configured API key. Should
        one API key fail but the other succeed then usage will be misaligned, so the highest usage of all
        API keys will apply.

        Returns:
            int: The tracked API usage count.

        """
        return max(list(self._api_used.values()))

    def get_api_limit(self) -> int:
        """Return API polling limit for this UTC 24hr period (minimum of all API keys).

        A minimum is used because forecasts are polled at the same time, so even if one API key has a
        higher limit that limit will never be reached.

        Returns:
            int: The lowest API limit of all configured API keys.

        """
        return min(list(self._api_limit.values()))

    def get_last_updated(self) -> dt | None:
        """Return when the data was last updated.

        Returns:
            dt | None: The last successful forecast fetch.

        """
        return self._data.get("last_updated")

    def get_dampen(self) -> bool:
        """Return whether dampening is enabled.

        Returns:
            bool: Whether dampening is enabled.

        """
        return (
            self.options.auto_dampen
            or self.granular_dampening != {}
            or (not self.options.auto_dampen and self.granular_dampening == {} and sum(self.options.dampening.values()) != 24)
        )

    def get_rooftop_site_total_today(self, site: str) -> float | None:
        """Return total kW for today for a site.

        Arguments:
            site (str): A Solcast site ID.

        Returns:
            float | None: Total site kW forecast today.

        """
        if self._tally.get(site) is None:
            _LOGGER.warning("Site total kW forecast today is currently unavailable for %s", site)
        return self._tally.get(site)

    def get_rooftop_site_extra_data(self, site: str = "") -> dict[str, Any]:
        """Return information about a site.

        Arguments:
            site (str): An optional Solcast site ID.

        Returns:
            dict: Site attributes that have been configured at solcast.com.

        """
        target_site = tuple(_site for _site in self.sites if _site["resource_id"] == site)
        _site: dict[str, Any] = target_site[0]
        result = {
            "name": _site.get("name"),
            "resource_id": _site.get("resource_id"),
            "capacity": _site.get("capacity"),
            "capacity_dc": _site.get("capacity_dc"),
            "longitude": _site.get("longitude"),
            "latitude": _site.get("latitude"),
            "azimuth": _site.get("azimuth"),
            "tilt": _site.get("tilt"),
            "install_date": _site.get("install_date"),
            "loss_factor": _site.get("loss_factor"),
            "tags": _site.get("tags"),
        }
        return {k: v for k, v in result.items() if v is not None}

    def is_dst(self, interval: dict[str, Any]) -> bool | None:
        """Return whether an interval is daylight savings time."""
        return (interval["period_start"].astimezone(self._tz).dst() == timedelta(hours=1)) if interval["period_start"] is not None else None

    def get_day_start_utc(self, future: int = 0) -> dt:
        """Datetime helper.

        Returns:
            datetime: The UTC date and time representing midnight local time.

        Arguments:
            future(int): An optional number of days into the future (or negative number for into the past)

        """
        for_when = (dt.now(self._tz) + timedelta(days=future)).astimezone(self._tz)
        return for_when.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(datetime.UTC)

    def __get_utc_previous_midnight(self) -> dt:
        """Datetime helper.

        Returns:
            datetime: The UTC date and time representing midnight UTC of the current day.

        """
        return dt.now().astimezone(datetime.UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    def get_now_utc(self) -> dt:
        """Datetime helper.

        Returns:
            datetime: The UTC date and time representing now as at the previous minute boundary.

        """
        return dt.now(self._tz).replace(second=0, microsecond=0).astimezone(datetime.UTC)

    def get_real_now_utc(self) -> dt:
        """Datetime helper.

        Returns:
            datetime: The UTC date and time representing now including seconds/microseconds.

        """
        return dt.now(self._tz).astimezone(datetime.UTC)

    def get_hour_start_utc(self) -> dt:
        """Datetime helper.

        Returns:
            datetime: The UTC date and time representing the start of the current hour.

        """
        return dt.now(self._tz).replace(minute=0, second=0, microsecond=0).astimezone(datetime.UTC)

    def get_forecast_day(self, future_day: int) -> dict[str, Any] | None:
        """Return forecast data for the Nth day ahead.

        Arguments:
            future_day (int): A day (0 = today, 1 = tomorrow, etc., with a maximum of day FORECAST_DAYS - 1).

        Returns:
            dict: Includes the day name, whether there are issues with the data in terms of completeness,
            and detailed half-hourly forecast (and site breakdown if that option is configured), and a
            detailed hourly forecast (and site breakdown if that option is configured).

        """
        no_data_error = True

        def build_hourly(forecast: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [
                {
                    "period_start": forecast[index]["period_start"],
                    "pv_estimate": round(
                        (forecast[index]["pv_estimate"] + forecast[index + 1]["pv_estimate"]) / 2,
                        4,
                    ),
                    "pv_estimate10": round(
                        (forecast[index]["pv_estimate10"] + forecast[index + 1]["pv_estimate10"]) / 2,
                        4,
                    ),
                    "pv_estimate90": round(
                        (forecast[index]["pv_estimate90"] + forecast[index + 1]["pv_estimate90"]) / 2,
                        4,
                    ),
                }
                for index in range(1 if len(forecast) % 2 == 1 else 0, len(forecast), 2)
                if len(forecast) > 0
            ]

        def get_start_and_end(forecasts: list[dict[str, Any]]) -> tuple[int, int, dt, dt]:
            start_utc = self.get_day_start_utc(future=future_day)
            start, _ = self.__get_list_slice(forecasts, start_utc)
            end_utc = min(self.get_day_start_utc(future=future_day + 1), forecasts[-1]["period_start"])  # Don't go past the last forecast.
            end, _ = self.__get_list_slice(forecasts, end_utc)
            if not start:
                # Data is missing, so adjust the start time to the first available forecast.
                start, _ = self.__get_list_slice(forecasts, forecasts[0]["period_start"])
                start_utc = forecasts[0]["period_start"]
            return start, end, start_utc, end_utc

        # site_start_index = {site["resource_id"]: 0 for site in self.sites}
        # site_end_index = {site["resource_id"]: 0 for site in self.sites}

        start_index, end_index, start_utc, _ = get_start_and_end(self._data_forecasts)

        site_data_forecast: dict[str, list[dict[str, Any]]] = {}
        forecast_slice = self._data_forecasts[start_index:end_index]
        if self.options.attr_brk_site_detailed:
            for site in self.sites:
                site_start_index, site_end_index, _, _ = get_start_and_end(self._site_data_forecasts[site["resource_id"]])
                site_data_forecast[site["resource_id"]] = self._site_data_forecasts[site["resource_id"]][site_start_index:site_end_index]

        _tuple = [{**forecast, "period_start": forecast["period_start"].astimezone(self._tz)} for forecast in forecast_slice]
        tuples: dict[str, list[dict[str, Any]]] = {}
        if self.options.attr_brk_site_detailed:
            for site in self.sites:
                tuples[site["resource_id"]] = [
                    {
                        **forecast,
                        "period_start": forecast["period_start"].astimezone(self._tz),
                    }
                    for forecast in site_data_forecast[site["resource_id"]]
                ]

        if len(_tuple) < 48:
            no_data_error = False

        hourly_tuple: list[dict[str, Any]] = []
        hourly_tuples: dict[str, list[dict[str, Any]]] = {}
        if self.options.attr_brk_hourly:
            hourly_tuple = build_hourly(_tuple)
            if self.options.attr_brk_site_detailed:
                hourly_tuples = {}
                for site in self.sites:
                    hourly_tuples[site["resource_id"]] = build_hourly(tuples[site["resource_id"]])

        result: dict[str, Any] = {
            "dayname": start_utc.astimezone(self._tz).strftime("%A"),
            "dataCorrect": no_data_error,
        }
        if self.options.attr_brk_halfhourly:
            result["detailedForecast"] = _tuple
            if self.options.attr_brk_site_detailed:
                for site in self.sites:
                    result[f"detailedForecast_{site['resource_id'].replace('-', '_')}"] = tuples[site["resource_id"]]
        if self.options.attr_brk_hourly:
            result["detailedHourly"] = hourly_tuple
            if self.options.attr_brk_site_detailed:
                for site in self.sites:
                    result[f"detailedHourly_{site['resource_id'].replace('-', '_')}"] = hourly_tuples[site["resource_id"]]
        return result

    def get_forecast_n_hour(
        self,
        n_hour: int,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> int | None:
        """Return forecast for the Nth hour.

        Arguments:
            n_hour (int): An hour into the future, or the current hour (0 = current and 1 = next hour are used).
            site (str): An optional Solcast site ID, used to build site breakdown attributes.
            forecast_confidence (str): An optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            int | None - A forecast for an hour period as Wh (either used for a sensor or its attributes).

        """
        start_utc = self.get_hour_start_utc() + timedelta(hours=n_hour)
        end_utc = start_utc + timedelta(hours=1)
        estimate = self.__get_forecast_pv_estimates(start_utc, end_utc, site=site, forecast_confidence=forecast_confidence)
        return round(500 * estimate) if estimate is not None else None

    def get_forecast_custom_hours(
        self,
        n_hours: int,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> int | None:
        """Return forecast for the next N hours.

        Arguments:
            n_hours (int): A number of hours into the future.
            site (str): An optional Solcast site ID, used to build site breakdown attributes.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            int | None - A forecast for a multiple hour period as Wh (either used for a sensor or its attributes).

        """
        start_utc = self.get_now_utc()
        end_utc = start_utc + timedelta(hours=n_hours)
        remaining = self.__get_forecast_pv_remaining(
            start_utc,
            end_utc=end_utc,
            site=site,
            forecast_confidence=forecast_confidence,
        )
        return round(1000 * remaining) if remaining is not None else None

    def get_power_n_minutes(
        self,
        n_mins: int,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> int | None:
        """Return expected power generation in the next N minutes.

        Arguments:
            n_mins (int): A number of minutes into the future.
            site (str): An optional Solcast site ID, used to build site breakdown attributes.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            int | None: A power forecast in N minutes as W (either used for a sensor or its attributes).

        """
        time_utc = self.get_now_utc() + timedelta(minutes=n_mins)
        forecast = self.__get_forecast_pv_moment(time_utc, site=site, forecast_confidence=forecast_confidence)
        return round(1000 * forecast) if forecast is not None else None

    def get_peak_power_day(
        self,
        n_day: int,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> int | None:
        """Return maximum forecast Watts for N days ahead.

        Arguments:
            n_day (int): A number representing a day (0 = today, 1 = tomorrow, etc., with a maximum of day FORECAST_DAYS - 1).
            site (str): An optional Solcast site ID, used to build site breakdown attributes.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            int | None: An expected peak generation for a given day as Watts.

        """
        forecast_confidence = self._use_forecast_confidence if forecast_confidence is None else forecast_confidence
        start_utc = self.get_day_start_utc(future=n_day)
        end_utc = self.get_day_start_utc(future=n_day + 1)
        result = self.__get_max_forecast_pv_estimate(start_utc, end_utc, site=site, forecast_confidence=forecast_confidence)
        return int(round(1000 * result[forecast_confidence])) if result is not None else None

    def get_peak_time_day(
        self,
        n_day: int,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> dt | None:
        """Return hour of max generation for site N days ahead.

        Arguments:
            n_day (int): A number representing a day (0 = today, 1 = tomorrow, etc., with a maximum of day FORECAST_DAYS - 1).
            site (str): An optional Solcast site ID, used to build site breakdown attributes.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            dt | None: The date and time of expected peak generation for a given day.

        """
        start_utc = self.get_day_start_utc(future=n_day)
        end_utc = self.get_day_start_utc(future=n_day + 1)
        result = self.__get_max_forecast_pv_estimate(start_utc, end_utc, site=site, forecast_confidence=forecast_confidence)
        return result["period_start"] if result is not None else None

    def get_forecast_remaining_today(self, n: int = 0, site: str | None = None, forecast_confidence: str | None = None) -> float | None:
        """Return remaining forecasted production for today.

        Arguments:
            n (int): Not used.
            site (str): An optional Solcast site ID, used to build site breakdown attributes.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            float | None: The expected remaining solar generation for the current day as kWh.

        """
        start_utc = self.get_now_utc()
        end_utc = self.get_day_start_utc(future=1)
        remaining = self.__get_forecast_pv_remaining(
            start_utc,
            end_utc=end_utc,
            site=site,
            forecast_confidence=forecast_confidence,
        )
        return round(remaining, 4) if remaining is not None else None

    def get_total_energy_forecast_day(
        self,
        n_day: int,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> float | None:
        """Return forecast production total for N days ahead.

        Arguments:
            n_day (int): A day (0 = today, 1 = tomorrow, etc., with a maximum of day FORECAST_DAYS - 1).
            site (str): An optional Solcast site ID, used to build site breakdown attributes.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            float | None: The forecast total solar generation for a given day as kWh.

        """
        start_utc = self.get_day_start_utc(future=n_day)
        end_utc = self.get_day_start_utc(future=n_day + 1)
        estimate = self.__get_forecast_pv_estimates(start_utc, end_utc, site=site, forecast_confidence=forecast_confidence)
        return round(0.5 * estimate, 4) if estimate is not None else None

    def get_forecast_attributes(self, get_forecast_value: Any, n: int = 0) -> dict[str, Any]:
        """Return forecast attributes for the 'n' forecast value for all sites and individual sites.

        Arguments:
            get_forecast_value (function): A function to get the forecast value.
            n (int): A minute, hour or day into the future.

        Returns:
            dict: Sensor attributes for the period, depending on the configured options.

        """
        result: dict[str, Any] = {}
        if self.options.attr_brk_site:
            for site in self.sites:
                result[site["resource_id"].replace("-", "_")] = get_forecast_value(n, site=site["resource_id"])
                for forecast_confidence in self.estimate_set:
                    result[forecast_confidence.replace("pv_", "") + "_" + site["resource_id"].replace("-", "_")] = get_forecast_value(
                        n,
                        site=site["resource_id"],
                        forecast_confidence=forecast_confidence,
                    )
        for forecast_confidence in self.estimate_set:
            result[forecast_confidence.replace("pv_", "")] = get_forecast_value(n, forecast_confidence=forecast_confidence)
        return result

    def __get_list_slice(
        self,
        data: list[dict[str, Any]],
        start_utc: dt,
        end_utc: dt | None = None,
        search_past: bool = False,
    ) -> tuple[int, int]:
        """Return forecast data list slice start and end indexes for interval.

        Arguments:
            data (list): The data to search, either actual or forecast total data or site breakdown data.
            start_utc (datetime): Start of time period requested in UTC.
            end_utc (datetime): Optional end of time period requested in UTC (if omitted, thirty minutes beyond start).
            search_past (bool): Optional flag to indicate that past periods should be searched.

        Returns:
            tuple(int, int): List index of start of period, list index of end of period.

        """
        if end_utc is None:
            end_utc = start_utc + timedelta(seconds=1800)
        start_index = -1
        end_index = len(data)
        for test_index in range(0 if search_past else self.__calc_forecast_start_index(data), end_index):
            forecast_period = data[test_index]["period_start"]
            # After the last segment.
            if end_utc <= forecast_period:
                end_index = test_index
                break
            # First segment.
            if start_utc < forecast_period + timedelta(seconds=1800) and start_index == -1:
                start_index = test_index
        # Never found.
        if start_index == -1:
            start_index = 0
            end_index = 0
        return start_index, end_index

    def __get_spline(
        self,
        spline: dict[str, list[float]],
        start: int,
        xx: list[int],
        data: list[dict[str, Any]],
        confidences: list[str],
        reducing: bool = False,
    ):
        """Build a forecast spline, momentary or day reducing.

        Arguments:
            spline (dict): The data structure to populate.
            start (int): The starting index of the data slice.
            xx (list): Seconds intervals of the day, one for each 5-minute interval (plus another hours worth).
            data (list): The data structure used to build the spline, either total data or site breakdown data.
            confidences (list): The forecast types to build, pv_estimate, pv_estimate10 or pv_estimate90.
            reducing (bool): A flag to indicate whether a momentary power spline should be built, or a reducing energy spline, default momentary.

        """
        for forecast_confidence in confidences:
            try:
                y = [data[start + index][forecast_confidence] for index in range(len(self._spline_period))]
                if reducing:
                    # Build a decreasing set of forecasted values instead.
                    y = [0.5 * sum(y[index:]) for index in range(len(self._spline_period))]
                spline[forecast_confidence] = cubic_interp(xx, self._spline_period, y)
                self.__sanitise_spline(spline, forecast_confidence, xx, y, reducing=reducing)
                continue
            except IndexError:
                pass
            spline[forecast_confidence] = [0] * (len(self._spline_period) * 6)

    def __sanitise_spline(
        self,
        spline: dict[str, list[float]],
        forecast_confidence: str,
        xx: list[int],
        y: list[float],
        reducing: bool = False,
    ):
        """Ensure that no negative values are returned, and also shifts the spline to account for half-hour average input values.

        Arguments:
            spline (dict): The data structure to sanitise.
            forecast_confidence (str): The forecast type to sanitise, pv_estimate, pv_estimate10 or pv_estimate90.
            xx (list): Seconds intervals of the day, one for each 5-minute interval (plus another hours worth).
            y (list): The period momentary or reducing input data used for the spline calculation.
            reducing (bool): A flag to indicate whether the spline is momentary power, or reducing energy, default momentary.

        """
        offset = int(xx[0] / 300)  # To cater for less intervals than the spline period
        for interval in xx:
            spline_index = int(interval / 300) - offset  # Every five minutes
            # Suppress negative values.
            if math.copysign(1.0, spline[forecast_confidence][spline_index]) < 0:
                spline[forecast_confidence][spline_index] = 0.0
            # Suppress spline bounce.
            if reducing:
                if (
                    spline_index + 1 <= len(xx) - 1
                    and spline[forecast_confidence][spline_index + 1] > spline[forecast_confidence][spline_index]
                ):
                    spline[forecast_confidence][spline_index + 1] = spline[forecast_confidence][spline_index]
            else:
                y_index = int(math.floor(interval / 1800))  # Every half hour
                if y_index + 1 <= len(y) - 1 and y[y_index] == 0 and y[y_index + 1] == 0:
                    spline[forecast_confidence][spline_index] = 0.0
        # Shift right by fifteen minutes because 30-minute averages, padding as appropriate.
        if reducing:
            spline[forecast_confidence] = ([spline[forecast_confidence][0]] * 3) + spline[forecast_confidence]
        else:
            spline[forecast_confidence] = ([0] * 3) + spline[forecast_confidence]

    def __build_spline(self, variant: dict[str, dict[str, list[float]]], reducing: bool = False):
        """Build cubic splines for interpolated inter-interval momentary or reducing estimates.

        Arguments:
            variant (dict[str, list[float]): The variant variable to populate, _forecasts_moment or _forecasts_reducing.
            reducing (bool): A flag to indicate whether the spline is momentary power, or reducing energy, default momentary.

        """
        df = [self._use_forecast_confidence]
        for enabled, estimate in (
            (self.options.attr_brk_estimate, "pv_estimate"),
            (self.options.attr_brk_estimate10, "pv_estimate10"),
            (self.options.attr_brk_estimate90, "pv_estimate90"),
        ):
            if enabled and estimate not in df:
                df.append(estimate)

        start: int = 0
        end: int = 0
        xx: list[int] = []

        def get_start_and_end(forecasts: list[dict[str, Any]]) -> tuple[int, int, list[int]]:
            try:
                start, end = self.__get_list_slice(forecasts, self.get_day_start_utc())  # Get start of day index.
                if start:
                    xx = list(range(0, 1800 * len(self._spline_period), 300))
                else:
                    # Data is missing at the start of the set, so adjust the start time to the first available forecast.
                    start, end = self.__get_list_slice(forecasts, forecasts[0]["period_start"], self.get_day_start_utc(future=1))
                    xx = list(range((48 - start) * 300, 1800 * len(self._spline_period), 300))
            except IndexError:
                start = 0
                end = 0
                xx = []
            return start, end, xx

        variant["all"] = {}
        start, end, xx = get_start_and_end(self._data_forecasts)
        if end:
            self.__get_spline(variant["all"], start, xx, self._data_forecasts, df, reducing=reducing)
        if self.options.attr_brk_site:
            for site in self.sites:
                variant[site["resource_id"]] = {}
                if self._site_data_forecasts.get(site["resource_id"]):
                    start, end, xx = get_start_and_end(self._site_data_forecasts[site["resource_id"]])
                    if end:
                        self.__get_spline(
                            variant[site["resource_id"]],
                            start,
                            xx,
                            self._site_data_forecasts[site["resource_id"]],
                            df,
                            reducing=reducing,
                        )

    async def __spline_moments(self):
        """Build the moments splines."""
        self.__build_spline(self._forecasts_moment)

    async def __spline_remaining(self):
        """Build the descending splines."""
        self.__build_spline(self._forecasts_remaining, reducing=True)

    async def recalculate_splines(self):
        """Recalculate both the moment and remaining splines."""
        start_time = time.time()
        await self.__spline_moments()
        await self.__spline_remaining()
        _LOGGER.debug("Task recalculate_splines took %.3f seconds", time.time() - start_time)

    def __get_moment(self, site: str | None, forecast_confidence: str | None, n_min: float) -> float | None:
        """Get a time value from a moment spline.

        Arguments:
            site (str | None): A Solcast site ID.
            forecast_confidence (str): The forecast type, pv_estimate, pv_estimate10 or pv_estimate90.
            n_min (float): Minute of the day.

        Returns:
            float: A splined forecasted value as kW.

        """
        variant: list[float] | None = self._forecasts_moment["all" if site is None else site].get(
            self._use_forecast_confidence if forecast_confidence is None else forecast_confidence
        )
        offset = (
            (len(self._spline_period) * 6 - len(variant)) + 3 if variant is not None else 0
        )  # To cater for less intervals than the spline period
        return variant[int(n_min / 300) - offset] if variant and len(variant) > 0 else None

    def __get_remaining(self, site: str | None, forecast_confidence: str | None, n_min: float) -> float | None:
        """Get a remaining value at a given five-minute point from a reducing spline.

        Arguments:
            site (str | None): A Solcast site ID.
            forecast_confidence (str): The forecast type, pv_estimate, pv_estimate10 or pv_estimate90.
            n_min (float): The minute of the day.

        Returns:
            float: A splined forecasted remaining value as kWh.

        """
        variant: list[float] | None = self._forecasts_remaining["all" if site is None else site].get(
            self._use_forecast_confidence if forecast_confidence is None else forecast_confidence
        )
        offset = (
            (len(self._spline_period) * 6 - len(variant)) + 3 if variant is not None else 0
        )  # To cater for less intervals than the spline period
        return variant[int(n_min / 300) - offset] if variant and len(variant) > 0 else None

    def __get_forecast_pv_remaining(
        self,
        start_utc: dt,
        end_utc: dt | None = None,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> float | None:
        """Return estimate remaining for a period.

        The start_utc and end_utc will be adjusted to the most recent five-minute period start. Where
        end_utc is present the forecasted remaining energy between the two datetime values is calculated.

        Arguments:
            start_utc (datetime): Start of time period in UTC.
            end_utc (datetime): Optional end of time period in UTC. If omitted then a result for the start_utc only is returned.
            site (str): Optional Solcast site ID, used to provide site breakdown.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            float: Energy forecast to be remaining for a period as kWh.

        """
        data = self._data_forecasts if site is None else self._site_data_forecasts[site]
        forecast_confidence = self._use_forecast_confidence if forecast_confidence is None else forecast_confidence
        start_utc = start_utc.replace(minute=math.floor(start_utc.minute / 5) * 5)
        start_index, end_index = self.__get_list_slice(  # Get start and end indexes for the requested range.
            data, start_utc, end_utc
        )
        if (start_index == 0 and end_index == 0) or data[len(data) - 1]["period_start"] < end_utc:
            return None  # Set sensor to unavailable
        day_start = self.get_day_start_utc()
        result = self.__get_remaining(site, forecast_confidence, (start_utc - day_start).total_seconds())
        if end_utc is not None:
            end_utc = end_utc.replace(minute=math.floor(end_utc.minute / 5) * 5)
            if end_utc < day_start + timedelta(seconds=1800 * len(self._spline_period)) and result is not None:
                # End is within today so use spline data.
                if (val := self.__get_remaining(site, forecast_confidence, (end_utc - day_start).total_seconds())) is not None:
                    result -= val
            elif result is not None:
                # End is beyond today, so revert to simple linear interpolation.
                start_index_post_spline, _ = self.__get_list_slice(  # Get post-spline day onwards start index.
                    data,
                    day_start + timedelta(seconds=1800 * len(self._spline_period)),
                )
                for forecast in data[start_index_post_spline:end_index]:
                    forecast_period_next = forecast["period_start"] + timedelta(seconds=1800)
                    seconds = 1800
                    interval = 0.5 * forecast[forecast_confidence]
                    if end_utc < forecast_period_next:
                        seconds -= (forecast_period_next - end_utc).total_seconds()
                        result += interval * seconds / 1800
                    else:
                        result += interval
        return max(0, result) if result is not None else None

    def __get_forecast_pv_estimates(
        self,
        start_utc: dt,
        end_utc: dt,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> float | None:
        """Return energy total for a period.

        Arguments:
            start_utc (datetime): Start of time period datetime in UTC.
            end_utc (datetime): End of time period datetime in UTC.
            site (str): Optional Solcast site ID, used to provide site breakdown.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            float: Energy forecast total for a period as kWh.

        """
        data = self._data_forecasts if site is None else self._site_data_forecasts[site]
        forecast_confidence = self._use_forecast_confidence if forecast_confidence is None else forecast_confidence
        result = 0
        start_index, end_index = self.__get_list_slice(  # Get start and end indexes for the requested range.
            data, start_utc, end_utc
        )
        if start_index == 0 and end_index == 0:
            return None
        for forecast_slice in data[start_index:end_index]:
            result += forecast_slice[forecast_confidence]
        return result

    def __get_forecast_pv_moment(
        self,
        time_utc: dt,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> float | None:
        """Return forecast power for a point in time.

        Arguments:
            time_utc (datetime): A moment in UTC to return.
            site (str): Optional Solcast site ID, used to provide site breakdown.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            float: Forecast power for a point in time as kW (from splined data).

        """
        forecast_confidence = self._use_forecast_confidence if forecast_confidence is None else forecast_confidence
        day_start = self.get_day_start_utc()
        time_utc = time_utc.replace(minute=math.floor(time_utc.minute / 5) * 5)
        return self.__get_moment(site, forecast_confidence, (time_utc - day_start).total_seconds())

    def __get_max_forecast_pv_estimate(
        self,
        start_utc: dt,
        end_utc: dt,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> dict[str, Any] | None:
        """Return forecast maximum interval for a period.

        Arguments:
            start_utc (datetime): Start of time period datetime in UTC.
            end_utc (datetime): End of time period datetime in UTC.
            site (str): Optional Solcast site ID, used to provide site breakdown.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            dict[str, Any]: The interval data with largest generation for a period.

        """
        result: dict[str, Any] | None = None
        data = self._data_forecasts if site is None else self._site_data_forecasts[site]
        forecast_confidence = self._use_forecast_confidence if forecast_confidence is None else forecast_confidence
        start_index, end_index = self.__get_list_slice(data, start_utc, end_utc)
        if start_index == 0 and end_index == 0:
            return None  # Set sensor to unavailable
        result = data[start_index]
        for forecast_slice in data[start_index:end_index]:
            if result[forecast_confidence] < forecast_slice[forecast_confidence]:
                result = forecast_slice
        return result

    def get_energy_data(self) -> dict[str, Any] | None:
        """Get energy data.

        Returns:
            dict: A Home Assistant energy dashboard compatible data set.

        """
        return self._data_energy_dashboard

    def __get_conversion_factor(self, entity: str, entity_history: list[State] | None = None, is_export: bool = False) -> float:
        """Get the conversion factor for an electricity energy entity to convert to kWh."""

        energy_unit_factors = {
            "mWh": 1e-6,
            "Wh": 0.001,
            "kWh": 1.0,
            "MWh": 1000.0,
        }
        entity_type = "Export entity" if is_export else "Entity"
        entity_unit = None

        if entity_history:
            # Check the entity history for the unit of measurement.
            latest_state = entity_history[-1]
            if hasattr(latest_state, "attributes") and latest_state.attributes:
                entity_unit = latest_state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)

        if not entity_unit:
            # If not found, get the unit of measurement from the entity registry.
            entity_registry = er.async_get(self.hass)
            entity_entry = entity_registry.async_get(entity)
            if entity_entry and entity_entry.unit_of_measurement:
                entity_unit = entity_entry.unit_of_measurement

        if not entity_unit:
            _LOGGER.warning("%s %s has no %s, assuming kWh", entity_type, entity, ATTR_UNIT_OF_MEASUREMENT)
            return 1.0

        conversion_factor = energy_unit_factors.get(entity_unit)
        if conversion_factor is None:
            _LOGGER.error("%s %s has an unsupported %s '%s', assuming kWh", entity_type, entity, ATTR_UNIT_OF_MEASUREMENT, entity_unit)
            return 1.0

        if conversion_factor != 1.0:
            _LOGGER.debug("%s %s uses %s, applying conversion factor %s", entity_type, entity, entity_unit, conversion_factor)

        return conversion_factor

    async def get_pv_generation(self) -> None:
        """Get PV generation from external entity/entities.

        Sensors must be increasing energy values (may reset at midnight), and the entities must have state history.
        Supports both kWh and other (e.g. Wh) sane electricity energy units with automatic conversion.
        Very large units of measurement are not supported (e.g. GWh, TWh) because of precision loss.
        """

        _EXCESSIVE_FACTOR = 3
        start_time = time.time()

        # Load the generation history.
        generation: dict[dt, dict[str, Any]] = {generated["period_start"]: generated for generated in self._data_generation["generation"]}
        days = 1 if len(generation) > 0 else 7

        entity_registry = er.async_get(self.hass)

        for day in range(days):
            # PV generation
            generation_intervals: dict[dt, float] = {
                self.get_day_start_utc(future=(-1 * day)) - timedelta(days=1) + timedelta(minutes=minute): 0
                for minute in range(0, 1440, 30)
            }
            for entity in self.options.generation_entities:
                r_entity = entity_registry.async_get(entity)
                if r_entity is None:
                    _LOGGER.error("Generation entity %s is not a valid entity", entity)
                    continue
                if r_entity.disabled_by is not None:
                    _LOGGER.error("Generation entity %s is disabled, please enable it", entity)
                    continue
                entity_history = await get_instance(self.hass).async_add_executor_job(
                    state_changes_during_period,
                    self.hass,
                    self.get_day_start_utc(future=(-1 * day)) - timedelta(days=1),
                    self.get_day_start_utc(future=(-1 * day)),
                    entity,
                )
                if entity_history.get(entity) and len(entity_history[entity]):
                    _LOGGER.debug("Retrieved day %d PV generation data from entity: %s", -1 + day * -1, entity)

                    # Get the conversion factor for the entity to convert to kWh.
                    conversion_factor = self.__get_conversion_factor(entity, entity_history[entity], is_export=False)
                    # Arrange the generation samples into half-hour intervals.
                    sample_time: list[dt] = [
                        e.last_updated.astimezone(datetime.UTC).replace(
                            minute=e.last_updated.astimezone(datetime.UTC).minute // 30 * 30, second=0, microsecond=0
                        )
                        for e in entity_history[entity]
                        if e.state.replace(".", "").isnumeric()
                    ]
                    # Build a list of generation delta values.
                    sample_generation: list[float] = [
                        0.0,
                        *diff([float(e.state) * conversion_factor for e in entity_history[entity] if e.state.replace(".", "").isnumeric()]),
                    ]
                    # Build generation values for each interval, ignoring any excessive jumps.
                    non_zero_generation = sorted([kWh for kWh in sample_generation if kWh > 0])
                    typical_gen = find_percentile(non_zero_generation, 90)
                    _LOGGER.debug("Typical generation jump: %.3f kWh", typical_gen)
                    for interval, kWh in zip(sample_time, sample_generation, strict=True):
                        if kWh <= typical_gen * _EXCESSIVE_FACTOR:  # Ignore excessive jumps.
                            generation_intervals[interval] += kWh
                        else:
                            _LOGGER.debug(
                                "Ignoring excessive PV generation jump of %.3f kWh in interval %s from entity: %s",
                                kWh,
                                interval.astimezone(self.options.tz).strftime("%Y-%m-%d %H:%M"),
                                entity,
                            )
                else:
                    _LOGGER.debug("No day %d PV generation data from entity: %s (%s)", -1 + day * -1, entity, entity_history.get(entity))
            for i, gen in generation_intervals.items():
                generation_intervals[i] = round(gen, 3)

            # Detect site export limiting
            export_limiting: dict[dt, bool] = {
                self.get_day_start_utc(future=(-1 * day)) - timedelta(days=1) + timedelta(minutes=minute): False
                for minute in range(0, 1440, 30)
            }

            if self.options.site_export_limit > 0 and self.options.site_export_entity != "":
                _INTERVAL = 5

                entity = self.options.site_export_entity
                r_entity = entity_registry.async_get(entity)
                if r_entity is None:
                    _LOGGER.error("Site export entity %s is not a valid entity", entity)
                    entity = ""
                elif r_entity.disabled_by is not None:
                    _LOGGER.error("Site export entity %s is disabled, please enable it", entity)
                    entity = ""
                export_intervals: dict[dt, float] = {
                    self.get_day_start_utc(future=(-1 * day)) - timedelta(days=1) + timedelta(minutes=minute): 0
                    for minute in range(0, 1440, _INTERVAL)
                }
                if entity:
                    entity_history = await get_instance(self.hass).async_add_executor_job(
                        state_changes_during_period,
                        self.hass,
                        self.get_day_start_utc(future=(-1 * day)) - timedelta(days=1),
                        self.get_day_start_utc(future=(-1 * day)),
                        entity,
                    )
                    if entity_history.get(entity) and len(entity_history[entity]):
                        # Get the conversion factor for the entity to convert to kWh.
                        conversion_factor = self.__get_conversion_factor(entity, entity_history[entity], is_export=False)
                        # Arrange the site export samples into intervals.
                        sample_time: list[dt] = [
                            e.last_updated.astimezone(datetime.UTC).replace(
                                minute=e.last_updated.astimezone(datetime.UTC).minute // _INTERVAL * _INTERVAL, second=0, microsecond=0
                            )
                            for e in entity_history[entity]
                            if e.state.replace(".", "").isnumeric()
                        ]
                        # Build a list of export delta values.
                        sample_export: list[float] = [
                            0.0,
                            *diff(
                                [float(e.state) * conversion_factor for e in entity_history[entity] if e.state.replace(".", "").isnumeric()]
                            ),
                        ]
                        for interval, kWh in zip(sample_time, sample_export, strict=True):
                            export_intervals[interval] += kWh
                        # Convert to export per interval in kW.
                        for i, export in export_intervals.items():
                            export_intervals[i] = round(export * (60 / _INTERVAL), 3)

                        for i, export in export_intervals.items():
                            export_interval = i.replace(minute=i.minute // 30 * 30)
                            if export >= self.options.site_export_limit and generation_intervals[export_interval] > 0:
                                export_limiting[export_interval] = True
                    else:
                        _LOGGER.debug("No site export history found for %s", entity)

            # Add recent generation intervals to the history.
            generation |= {
                i: {"period_start": i, "generation": generation, "export_limiting": export_limiting[i]}
                for i, generation in generation_intervals.items()
            }

        # Trim, sort and serialise.
        self._data_generation = {
            "last_updated": dt.now(datetime.UTC).replace(microsecond=0),
            "generation": sorted(
                filter(
                    lambda generated: generated["period_start"] >= self.get_day_start_utc(future=-22),
                    generation.values(),
                ),
                key=itemgetter("period_start"),
            ),
        }
        await self.serialise_data(self._data_generation, self._filename_generation)
        _LOGGER.debug("Task get_pv_generation took %.3f seconds", time.time() - start_time)

    def adjusted_interval(self, interval: dict[str, Any]) -> int:
        """Adjust a forecast/actual interval as standard time."""
        offset = 1 if self.is_dst(interval) else 0
        return (
            ((interval["period_start"].astimezone(self._tz).hour - offset) * 2 + interval["period_start"].astimezone(self._tz).minute // 30)
            if interval["period_start"].astimezone(self._tz).hour - offset >= 0
            else 0
        )

    def adjusted_interval_dt(self, interval: dt) -> int:
        """Adjust a datetime as standard time."""
        offset = 1 if interval.dst() == timedelta(hours=1) else 0
        return (
            ((interval.astimezone(self._tz).hour - offset) * 2 + interval.astimezone(self._tz).minute // 30)
            if interval.astimezone(self._tz).hour - offset >= 0
            else 0
        )

    async def model_automated_dampening(self, force: bool = False) -> None:
        """Model the automated dampening of the forecast data.

        Look for consistently low PV generation in consistently high estimated actual intervals.
        Dampening factors are always referenced using standard time (not daylight savings time).
        """
        if not self.options.auto_dampen and not force:
            _LOGGER.debug("Automated dampening is not enabled, skipping model_automated_dampening()")
            return

        start_time = time.time()

        export_limited_intervals = dict.fromkeys(range(48), False)
        for gen in self._data_generation["generation"]:
            if gen["export_limiting"]:
                export_limited_intervals[self.adjusted_interval(gen)] = True
        generation: dict[dt, float] = {}
        for gen in self._data_generation["generation"]:
            if not export_limited_intervals[self.adjusted_interval(gen)]:
                generation[gen["period_start"]] = gen["generation"]

        actuals: OrderedDict[dt, float] = OrderedDict()
        for site in self.sites:
            deal_breaker = ""
            if site["resource_id"] in self.options.exclude_sites:
                deal_breaker = "Excluded site"
            if self._data_actuals["siteinfo"].get(site["resource_id"]) is None:
                deal_breaker = "No estimated actuals yet"
            if len(self._data_generation["generation"]) == 0:
                deal_breaker = "No generation yet"
            if deal_breaker != "":
                if deal_breaker == "Excluded site":
                    _LOGGER.debug("Auto-dampening suppressed: %s for %s", deal_breaker, site["resource_id"])
                    continue
                _LOGGER.info("Auto-dampening suppressed: %s for %s", deal_breaker, site["resource_id"])
                return
            start, end = self.__get_list_slice(
                self._data_actuals["siteinfo"][site["resource_id"]]["forecasts"],
                self._data_generation["generation"][0]["period_start"],
                self.get_day_start_utc(),
                search_past=True,
            )
            site_actuals = {
                actual["period_start"]: actual for actual in self._data_actuals["siteinfo"][site["resource_id"]]["forecasts"][start:end]
            }
            for period_start, actual in site_actuals.items():
                extant: float | None = actuals.get(period_start)
                if extant is not None:
                    actuals[period_start] += actual["pv_estimate"] * 0.5
                else:
                    actuals[period_start] = actual["pv_estimate"] * 0.5

        # Collect top intervals from the past fourteen days.
        self._peak_intervals = dict.fromkeys(range(48), 0.0)
        for period_start, actual in actuals.items():
            interval = self.adjusted_interval_dt(period_start)
            if self._peak_intervals[interval] < actual:
                self._peak_intervals[interval] = round(actual, 3)

        # Collect intervals that are close to the peak.
        matching_intervals: dict[int, list[dt]] = {i: [] for i in range(48)}
        for period_start, actual in actuals.items():
            interval = self.adjusted_interval_dt(period_start)
            if actual > 0.90 * self._peak_intervals[interval]:
                matching_intervals[interval].append(period_start)

        # Defaults.
        dampening: list[float] = [1.0] * 48
        noise = 0.95

        # Check the generation for each interval and determine if it is consistently lower than the peak.
        for interval, matching in matching_intervals.items():
            generation_samples: list[float] = [
                generation.get(timestamp, 0.0) for timestamp in matching if generation.get(timestamp, 0.0) != 0.0
            ]
            if len(matching) > 0 and len(generation_samples) > 0:  # and len(generation_samples) > len(matching) / 2:
                peak = max(generation_samples)

                interval_time = f"{
                    interval // 2
                    + (
                        1
                        if dt.now(self._tz).replace(hour=interval // 2, minute=30 * (interval % 2), second=0, microsecond=0).dst()
                        == timedelta(hours=1)
                        else 0
                    ):02}:{30 * (interval % 2):02}"
                _LOGGER.debug(
                    "Interval %s has peak estimated actual %.3f and %d matching intervals: %s",
                    interval_time,
                    self._peak_intervals[interval],
                    len(matching),
                    ", ".join([date.astimezone(self._tz).strftime(DATE_MONTH_DAY) for date in matching]),
                )
                _LOGGER.debug("Interval %s max generation: %.3f, %s", interval_time, peak, generation_samples)
                if peak < self._peak_intervals[interval]:
                    factor = (peak / self._peak_intervals[interval]) if self._peak_intervals[interval] != 0 else 0.0
                    if factor < noise:
                        _LOGGER.debug("Auto-dampen factor for %s is %.3f", interval_time, factor)
                        dampening[interval] = round(factor, 3)
                    else:
                        _LOGGER.debug("Ignoring insignificant factor for %s of %.3f", interval_time, factor)

        if dampening != self.granular_dampening.get("all"):
            self.granular_dampening["all"] = dampening
            await self.serialise_granular_dampening()
            await self.granular_dampening_data()
        _LOGGER.debug("Task model_automated_dampening took %.3f seconds", time.time() - start_time)

    async def update_estimated_actuals(self, dampen_yesterday: bool = False) -> None:
        """Update estimated actuals."""

        status: DataCallStatus = DataCallStatus.SUCCESS
        reason: str = ""

        start_time = time.time()

        for site in self.sites:
            _LOGGER.info("Getting estimated actuals update for site %s", site["resource_id"])
            api_key = site["api_key"]

            new_data: list[dict[str, Any]] = []

            act_response: dict[str, Any] | None
            try:
                self.tasks["actuals"] = asyncio.create_task(
                    self.fetch_data(
                        hours=168,
                        path="estimated_actuals",
                        site=site["resource_id"],
                        api_key=api_key,
                        force=True,
                    )
                )
                await self.tasks["actuals"]
            finally:
                act_response = self.tasks.pop("actuals").result() if self.tasks.get("actuals") is not None else None
            if not isinstance(act_response, dict):
                _LOGGER.error("No valid data was returned for estimated_actuals so this may cause issues")
                _LOGGER.error("API did not return a json object, returned `%s`", act_response)
                status = DataCallStatus.FAIL
                reason = "No valid json returned"
                break

            estimate_actuals: list[dict[str, Any]] = act_response.get("estimated_actuals", [])

            oldest = (dt.now(self._tz).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6)).astimezone(datetime.UTC)

            for estimate_actual in estimate_actuals:
                period_start = dt.fromisoformat(estimate_actual["period_end"]).astimezone(datetime.UTC).replace(
                    second=0, microsecond=0
                ) - timedelta(minutes=30)
                if period_start > oldest:
                    new_data.append(
                        {
                            "period_start": period_start,
                            "pv_estimate": estimate_actual[FORECAST],
                        }
                    )

            # Load the actuals history and add or update the new entries.
            actuals = (
                {actual["period_start"]: actual for actual in self._data_actuals["siteinfo"][site["resource_id"]]["forecasts"]}
                if self._data_actuals["siteinfo"].get(site["resource_id"])
                else {}
            )
            for actual in new_data:
                self.__forecast_entry_update(
                    actuals,
                    actual["period_start"],
                    round(actual["pv_estimate"], 4),
                )

            await self.sort_and_prune(site["resource_id"], self._data_actuals, 730, actuals)
            _LOGGER.debug("Estimated actuals dictionary for site %s length %s", site["resource_id"], len(actuals))

        if status == DataCallStatus.SUCCESS and dampen_yesterday:
            # Apply dampening to yesterday actuals, but only if the new factors for the day have not been modelled.

            undampened_interval_pv50: dict[dt, float] = {}
            for site in self.sites:
                for forecast in self._data_actuals["siteinfo"][site["resource_id"]]["forecasts"]:
                    period_start = forecast["period_start"]
                    if period_start >= self.get_day_start_utc(future=-1) and period_start < self.get_day_start_utc():
                        if period_start not in undampened_interval_pv50:
                            undampened_interval_pv50[period_start] = forecast["pv_estimate"] * 0.5
                        else:
                            undampened_interval_pv50[period_start] += forecast["pv_estimate"] * 0.5

            for site in self.sites:
                if site["resource_id"] not in self.options.exclude_sites:
                    _LOGGER.debug("Apply dampening to previous day estimated actuals for %s", site["resource_id"])
                    # Load the undampened estimated actual day yesterday.
                    actuals_undampened_day = [
                        actual
                        for actual in self._data_actuals["siteinfo"][site["resource_id"]]["forecasts"]
                        if actual["period_start"] >= self.get_day_start_utc(future=-1) and actual["period_start"] < self.get_day_start_utc()
                    ]
                    extant_actuals = (
                        {
                            actual["period_start"]: actual
                            for actual in self._data_actuals_dampened["siteinfo"][site["resource_id"]]["forecasts"]
                        }
                        if self._data_actuals_dampened["siteinfo"].get(site["resource_id"])
                        else {}
                    )

                    for actual in actuals_undampened_day:
                        period_start = actual["period_start"]
                        self.__forecast_entry_update(
                            extant_actuals,
                            period_start,
                            round(
                                actual["pv_estimate"]
                                * self.__get_dampening_factor(
                                    site["resource_id"], period_start.astimezone(self._tz), undampened_interval_pv50.get(period_start, -1.0)
                                ),
                                4,
                            ),
                        )

                    await self.sort_and_prune(site["resource_id"], self._data_actuals_dampened, 730, extant_actuals)

        if status != DataCallStatus.SUCCESS:
            _LOGGER.error("Update estimated actuals failed: %s", reason)
        else:
            self._data_actuals["last_updated"] = dt.now(datetime.UTC).replace(microsecond=0)
            self._data_actuals["last_attempt"] = dt.now(datetime.UTC).replace(microsecond=0)
            await self.serialise_data(self._data_actuals, self._filename_actuals)
            self._data_actuals_dampened["last_updated"] = dt.now(datetime.UTC).replace(microsecond=0)
            self._data_actuals_dampened["last_attempt"] = dt.now(datetime.UTC).replace(microsecond=0)
            await self.serialise_data(self._data_actuals_dampened, self._filename_actuals_dampened)

        _LOGGER.debug("Task update_estimated_actuals took %.3f seconds", time.time() - start_time)

    async def get_forecast_update(self, do_past_hours: int = 0, force: bool = False) -> str:
        """Request forecast data for all sites.

        Arguments:
            do_past_hours (int): A optional number of past actual forecast hours that should be retrieved.
            force (bool): A forced update, which does not update the internal API use counter.

        Returns:
            str: An error message, or an empty string for no error.

        """
        last_attempt = dt.now(datetime.UTC)
        status = ""

        def next_update():
            if self._next_update is not None:
                return f", next auto update at {self._next_update}"
            return ""

        if last_updated := self.get_last_updated():
            if last_updated + timedelta(seconds=10) > dt.now(datetime.UTC):
                status = f"Not requesting a solar forecast because time is within ten seconds of last update ({last_updated.astimezone(self._tz)})"
                _LOGGER.warning(status)
                if self._next_update is not None:
                    _LOGGER.info("Forecast update suppressed%s", next_update())
                return status

        await self.refresh_granular_dampening_data()

        failure = False
        sites_attempted = 0
        sites_succeeded = 0
        reason = "Unknown"
        for site in self.sites:
            sites_attempted += 1
            _LOGGER.info(
                "Getting forecast update for site %s%s",
                site["resource_id"],
                f", including {do_past_hours} hours of past data" if do_past_hours > 0 else "",
            )
            result, reason = await self.__http_data_call(
                site=site["resource_id"],
                api_key=site["api_key"],
                do_past_hours=do_past_hours,
                force=force,
            )
            if result == DataCallStatus.FAIL:
                failure = True
                _LOGGER.warning(
                    "Forecast update for site %s failed%s%s",
                    site["resource_id"],
                    " so not getting remaining sites" if sites_attempted < len(self.sites) else "",
                    " - API use count may be odd" if len(self.sites) > 1 and sites_succeeded and not force else "",
                )
                status = "At least one site forecast get failed" if len(self.sites) > 1 else "Forecast get failed"
                break
            if result == DataCallStatus.ABORT:
                _LOGGER.info("Forecast update aborted%s", next_update())
                return ""
            if result == DataCallStatus.SUCCESS:
                sites_succeeded += 1

        if sites_attempted > 0 and not failure:
            await self.apply_forward_dampening(do_past_hours=do_past_hours)

            b_status = await self.build_forecast_data()
            self._loaded_data = True

            async def set_metadata_and_serialise(data: dict[str, Any]):
                data["last_updated"] = dt.now(datetime.UTC).replace(microsecond=0)
                data["last_attempt"] = last_attempt
                # Set to divisions if auto update is enabled, but not forced, in which case set to 99999 (otherwise zero).
                data["auto_updated"] = (
                    self.auto_update_divisions if self.options.auto_update != AutoUpdate.NONE and not force else 0 if not force else 99999
                )
                return await self.serialise_data(data, self._filename if data == self._data else self._filename_undampened)

            s_status = await set_metadata_and_serialise(self._data)
            await set_metadata_and_serialise(self._data_undampened)
            self._loaded_data = True

            if b_status and s_status:
                _LOGGER.info("Forecast update completed successfully%s", next_update())
        else:
            await self.serialise_data(self._data, self._filename)
            _LOGGER.warning("Forecast has not been updated%s", next_update())
            status = f"At least one site forecast get failed: {reason}"
        return status

    def set_next_update(self, next_update: str | None) -> None:
        """Set the next update time.

        Arguments:
            next_update (str): A string containing the time that the next auto update will occur.

        """
        self._next_update = next_update

    async def __migrate_undampened_history(self):
        """Migrate un-dampened forecasts if un-dampened data for a site does not exist."""
        apply_dampening: list[str] = []
        forecasts: dict[str, dict[dt, Any]] = {}
        past_days = self.get_day_start_utc(future=-14)
        for site in self.sites:
            site = site["resource_id"]
            if not self._data_undampened["siteinfo"].get(site) or len(self._data_undampened["siteinfo"][site].get("forecasts", [])) == 0:
                _LOGGER.info(
                    "Migrating un-dampened history to %s for %s",
                    self._filename_undampened,
                    site,
                )
                apply_dampening.append(site)
            else:
                continue
            # Load the forecast history.
            forecasts[site] = {forecast["period_start"]: forecast for forecast in self._data["siteinfo"][site]["forecasts"]}
            forecasts_undampened: list[dict[str, Any]] = []
            # Migrate forecast history if un-dampened data does not yet exist.
            if len(forecasts[site]) > 0:
                forecasts_undampened = sorted(
                    {
                        forecast["period_start"]: forecast
                        for forecast in self._data["siteinfo"][site]["forecasts"]
                        if forecast["period_start"] >= past_days
                    }.values(),
                    key=itemgetter("period_start"),
                )
                _LOGGER.debug(
                    "Migrating %d forecast entries to un-dampened forecasts for site %s",
                    len(forecasts_undampened),
                    site,
                )
            self._data_undampened["siteinfo"].update({site: {"forecasts": copy.deepcopy(forecasts_undampened)}})

        if len(apply_dampening) > 0:
            self._data_undampened["last_updated"] = dt.now(datetime.UTC).replace(microsecond=0)
            await self.serialise_data(self._data_undampened, self._filename_undampened)

        if len(apply_dampening) > 0:
            await self.apply_forward_dampening(applicable_sites=apply_dampening)
            await self.serialise_data(self._data, self._filename)

    def __forecast_entry_update(
        self, forecasts: dict[dt, Any], period_start: dt, pv: float, pv10: float | None = None, pv90: float | None = None
    ):
        """Update an individual forecast entry."""
        extant = forecasts.get(period_start)
        if extant:  # Update existing.
            forecasts[period_start]["pv_estimate"] = pv
            if pv10 is not None:
                forecasts[period_start]["pv_estimate10"] = pv10
            if pv90 is not None:
                forecasts[period_start]["pv_estimate90"] = pv90
        elif pv10 is not None:
            forecasts[period_start] = {
                "period_start": period_start,
                "pv_estimate": pv,
                "pv_estimate10": pv10,
                "pv_estimate90": pv90,
            }
        else:
            forecasts[period_start] = {
                "period_start": period_start,
                "pv_estimate": pv,
            }

    def __get_dampening_granular_factor(
        self, site: str, period_start: dt, interval_pv50: float = -1.0, record_adjustment: bool = False
    ) -> float:
        """Retrieve a granular dampening factor."""
        factor = self.granular_dampening[site][
            period_start.hour
            if len(self.granular_dampening[site]) == 24
            else ((period_start.hour * 2) + (1 if period_start.minute > 0 else 0))
        ]
        if site == "all" and self.options.auto_dampen and self.granular_dampening.get("all"):
            interval = self.adjusted_interval_dt(period_start)
            factor = self.granular_dampening["all"][interval]
            if self._peak_intervals[interval] > 0 and interval_pv50 > 0 and factor < 1.0:
                # Adjust the factor based on forecast vs. peak interval logarithmically.
                factor_pre_adjustment = factor
                factor = max(factor, min(1, factor + ((1 - factor) * (math.log(self._peak_intervals[interval]) - math.log(interval_pv50)))))
                if record_adjustment and period_start.astimezone(self._tz).date() == dt.now(self._tz).date():
                    _LOGGER.debug(
                        "Adjusted granular dampening factor for %s is %.3f (was %.3f, peak %.3f, interval pv50 %.3f)",
                        period_start.astimezone(self._tz).strftime(DATE_FORMAT),
                        factor,
                        factor_pre_adjustment,
                        self._peak_intervals[interval],
                        interval_pv50,
                    )
        return factor

    def __get_dampening_factor(self, site: str | None, period_start: dt, interval_pv50: float, record_adjustment: bool = False) -> float:
        """Retrieve either a traditional or granular dampening factor."""
        if site is not None:
            if self.entry_options.get(SITE_DAMP):
                if self.granular_dampening.get("all"):
                    return self.__get_dampening_granular_factor("all", period_start, interval_pv50, record_adjustment=record_adjustment)
                if self.granular_dampening.get(site):
                    return self.__get_dampening_granular_factor(site, period_start)
                return 1.0
        return self.damp.get(f"{period_start.hour}", 1.0)

    async def apply_forward_dampening(self, applicable_sites: list[str] | None = None, do_past_hours: int = 0) -> None:
        """Apply dampening to forward forecasts."""
        if len(self._data_undampened["siteinfo"]) == 0:
            return
        _LOGGER.debug("Applying future dampening")

        self._auto_dampening_factors = {
            period_start: factor
            for period_start, factor in self._auto_dampening_factors.items()
            if period_start >= self.get_day_start_utc()
        }

        undampened_interval_pv50: dict[dt, float] = {}
        for site in self.sites:
            for forecast in self._data_undampened["siteinfo"][site["resource_id"]]["forecasts"]:
                period_start = forecast["period_start"]
                if period_start >= self.get_day_start_utc():
                    if period_start not in undampened_interval_pv50:
                        undampened_interval_pv50[period_start] = forecast["pv_estimate"] * 0.5
                    else:
                        undampened_interval_pv50[period_start] += forecast["pv_estimate"] * 0.5

        record_adjustment = True
        for site in self.sites:
            # Load all forecasts.
            forecasts_undampened_future = [
                forecast
                for forecast in self._data_undampened["siteinfo"][site["resource_id"]]["forecasts"]
                if forecast["period_start"]
                >= (
                    self.get_day_start_utc()
                    if self._data["siteinfo"].get(site["resource_id"])
                    else self.get_day_start_utc() - timedelta(hours=do_past_hours)
                )  # Was >= dt.now(datetime.UTC)
            ]
            forecasts = (
                {forecast["period_start"]: forecast for forecast in self._data["siteinfo"][site["resource_id"]]["forecasts"]}
                if self._data["siteinfo"].get(site["resource_id"])
                else {}
            )

            if site["resource_id"] not in self.options.exclude_sites and (
                (site["resource_id"] in applicable_sites) if applicable_sites else True
            ):
                # Apply dampening to forward data
                for forecast in sorted(forecasts_undampened_future, key=itemgetter("period_start")):
                    period_start = forecast["period_start"]
                    pv = round(forecast["pv_estimate"], 4)
                    pv10 = round(forecast["pv_estimate10"], 4)
                    pv90 = round(forecast["pv_estimate90"], 4)

                    # Retrieve the dampening factor for the period, and dampen the estimates.
                    dampening_factor = self.__get_dampening_factor(
                        site["resource_id"],
                        period_start.astimezone(self._tz),
                        undampened_interval_pv50.get(period_start, -1),
                        record_adjustment=record_adjustment,
                    )
                    if record_adjustment:
                        self._auto_dampening_factors[period_start] = dampening_factor
                    pv_dampened = round(pv * dampening_factor, 4)
                    pv10_dampened = round(pv10 * dampening_factor, 4)
                    pv90_dampened = round(pv90 * dampening_factor, 4)

                    # Add or update the new entries.
                    self.__forecast_entry_update(forecasts, period_start, pv_dampened, pv10_dampened, pv90_dampened)
                record_adjustment = False
            else:
                for forecast in sorted(forecasts_undampened_future, key=itemgetter("period_start")):
                    period_start = forecast["period_start"]
                    self.__forecast_entry_update(
                        forecasts,
                        period_start,
                        round(forecast["pv_estimate"], 4),
                        round(forecast["pv_estimate10"], 4),
                        round(forecast["pv_estimate90"], 4),
                    )

            await self.sort_and_prune(site["resource_id"], self._data, 730, forecasts)
            _LOGGER.debug(
                "Forecasts dictionary length for %s is %s (%s un-dampened)",
                site["resource_id"],
                len(forecasts),
                len(self._data_undampened["siteinfo"][site["resource_id"]]["forecasts"]),
            )

    async def sort_and_prune(self, site: str | None, data: dict[str, Any], past_days: int, forecasts: dict[Any, Any]) -> None:
        """Sort and prune a forecast list."""

        _past_days = self.get_day_start_utc(future=past_days * -1)
        _forecasts: list[dict[str, Any]] = sorted(
            filter(
                lambda forecast: forecast["period_start"] >= _past_days,
                forecasts.values(),
            ),
            key=itemgetter("period_start"),
        )
        data["siteinfo"].update({site: {"forecasts": copy.deepcopy(_forecasts)}})

    async def __http_data_call(
        self,
        site: str | None = None,
        api_key: str | None = None,
        do_past_hours: int = 0,
        force: bool = False,
    ) -> tuple[DataCallStatus, str]:
        """Request forecast data via the Solcast API.

        Arguments:
            site (str): A Solcast site ID
            api_key (str): A Solcast API key appropriate to use for the site
            do_past_hours (int): A optional number of past actual forecast hours that should be retrieved.
            force (bool): A forced update, which does not update the internal API use counter.

        Returns:
            tuple[DataCallStatus, str]: A flag indicating success, failure or abort, and a reason for failure.

        """
        last_day = self.get_day_start_utc(future=FORECAST_DAYS)
        hours = math.ceil((last_day - self.get_now_utc()).total_seconds() / 3600)
        _LOGGER.debug(
            "Polling API for site %s, last day %s, %d hours",
            site,
            last_day.strftime("%Y-%m-%d"),
            hours,
        )

        new_data: list[dict[str, Any]] = []

        # Fetch past data. (Run once, for a new install or if the solcast.json file is deleted. This will use up api call quota.)

        if do_past_hours > 0:
            act_response: dict[str, Any] | None
            try:
                self.tasks["fetch"] = asyncio.create_task(
                    self.fetch_data(
                        hours=do_past_hours,
                        path="estimated_actuals",
                        site=site,
                        api_key=api_key,
                        force=force,
                    )
                )
                await self.tasks["fetch"]
            finally:
                act_response = self.tasks.pop("fetch").result() if self.tasks.get("fetch") is not None else None
            if not isinstance(act_response, dict):
                _LOGGER.error(
                    "No valid data was returned for estimated_actuals so this will cause issues (API limit may be exhausted, or Solcast might have a problem)"
                )
                _LOGGER.error("API did not return a json object, returned `%s`", act_response)
                return DataCallStatus.FAIL, "No valid json returned"

            estimate_actuals: list[dict[str, Any]] = act_response.get("estimated_actuals", [])

            oldest = (dt.now(self._tz).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6)).astimezone(datetime.UTC)

            actuals: dict[dt, Any] = {}
            for estimate_actual in estimate_actuals:
                period_start = dt.fromisoformat(estimate_actual["period_end"]).astimezone(datetime.UTC).replace(
                    second=0, microsecond=0
                ) - timedelta(minutes=30)
                if period_start > oldest:
                    new_data.append(
                        {
                            "period_start": period_start,
                            "pv_estimate": estimate_actual[FORECAST],
                            "pv_estimate10": 0,
                            "pv_estimate90": 0,
                        }
                    )
            for actual in new_data:
                period_start = actual["period_start"]

                # Add or update the new entries.
                self.__forecast_entry_update(
                    actuals,
                    period_start,
                    round(actual["pv_estimate"], 4),
                )

            await self.sort_and_prune(site, self._data_actuals, 730, actuals)

            self._data_actuals["last_updated"] = dt.now(datetime.UTC).replace(microsecond=0)
            self._data_actuals["last_attempt"] = dt.now(datetime.UTC).replace(microsecond=0)

        # Fetch latest data.

        response: dict[str, Any] | None = None
        if self.tasks.get("fetch") is not None:
            _LOGGER.warning("A fetch task is already running, so aborting forecast update")
            return DataCallStatus.ABORT, "Fetch already running"
        try:
            self.tasks["fetch"] = asyncio.create_task(
                self.fetch_data(
                    hours=hours,
                    path="forecasts",
                    site=site,
                    api_key=api_key,
                    force=force,
                )
            )
            await self.tasks["fetch"]
        finally:
            response = self.tasks.pop("fetch").result() if self.tasks.get("fetch") is not None else None
        if response is None:
            _LOGGER.error("No data was returned for forecasts")

        if not isinstance(response, dict):
            _LOGGER.error("API did not return a json object. Returned %s", response)
            return DataCallStatus.FAIL, "No valid json returned"

        latest_forecasts = response.get("forecasts", [])

        _LOGGER.debug("%d records returned", len(latest_forecasts))

        start_time = time.time()
        for forecast in latest_forecasts:
            period_start = dt.fromisoformat(forecast["period_end"]).astimezone(datetime.UTC).replace(second=0, microsecond=0) - timedelta(
                minutes=30
            )
            if period_start < last_day:
                new_data.append(
                    {
                        "period_start": period_start,
                        "pv_estimate": forecast[FORECAST],
                        "pv_estimate10": forecast[FORECAST10],
                        "pv_estimate90": forecast[FORECAST90],
                    }
                )

        # Add or update forecasts with the latest data.

        # Load the forecast history.
        try:
            forecasts_undampened = {forecast["period_start"]: forecast for forecast in self._data_undampened["siteinfo"][site]["forecasts"]}
        except:  # noqa: E722
            forecasts_undampened = {}

        _LOGGER.debug("Task load_new_data took %.3f seconds", time.time() - start_time)

        # Add new data to the undampened forecasts.
        start_time = time.time()
        for forecast in new_data:
            period_start = forecast["period_start"]
            self.__forecast_entry_update(
                forecasts_undampened,
                period_start,
                round(forecast["pv_estimate"], 4),
                round(forecast["pv_estimate10"], 4),
                round(forecast["pv_estimate90"], 4),
            )

        await self.sort_and_prune(site, self._data_undampened, 14, forecasts_undampened)

        return DataCallStatus.SUCCESS, ""

    async def _sleep(self, delay: float):
        """Sleep for a specified number of seconds."""
        await asyncio.sleep(delay)

    async def fetch_data(
        self,
        hours: int = 0,
        path: str = "error",
        site: str | None = None,
        api_key: str | None = None,
        force: bool = False,
    ) -> dict[str, Any] | str | None:
        """Fetch forecast data.

        Arguments:
            hours (int): Number of hours to fetch, normally 168, or seven days.
            path (str): The path to follow. "forecasts" or "estimated_actuals". Omitting this parameter will result in an error.
            site (str): A Solcast site ID.
            api_key (str): A Solcast API key appropriate to use for the site.
            force (bool): A forced update, which does not update the internal API use counter.

        Returns:
            dict: Raw forecast data points, or None if unsuccessful.

        """
        response_text = ""
        try:

            def increment_failure_count():
                self._data["failure"]["last_24h"] += 1
                self._data["failure"]["last_7d"][0] += 1

            if api_key is not None and site is not None:
                # One site is fetched, and retries ensure that the site is actually fetched.
                # Occasionally the Solcast API is busy, and returns a 429 status, which is a
                # request to try again later. (It could also indicate that the API limit for
                # the day has been exceeded, and this is catered for by examining additional
                # status.)

                # The retry mechanism is a "back-off", where the interval between attempted
                # fetches is increased each time. All attempts possible span a maximum of
                # fifteen minutes, and this is also the timeout limit set for the entire
                # async operation.

                start_time = time.time()

                async with asyncio.timeout(900):
                    if self._api_used[api_key] < self._api_limit[api_key] or force:
                        # if API == Api.HOBBYIST:
                        url = f"{self.options.host}/rooftop_sites/{site}/{path}"
                        params: dict[str, str | int] = {"format": "json", "api_key": api_key, "hours": hours}

                        tries = 10
                        counter = 0
                        backoff = 15  # On every retry the back-off increases by (at least) fifteen seconds more than the previous back-off.
                        while True:
                            _LOGGER.debug("Fetching path %s", path)
                            counter += 1
                            response_text = ""
                            try:
                                response: ClientResponse = await self._aiohttp_session.get(
                                    url=url, params=params, headers=self.headers, ssl=False
                                )
                                _LOGGER.debug("Fetch data url %s", self.__redact_msg_api_key(str(response.url), api_key))
                                status = response.status
                                if status == 200:
                                    response_text = await response.text()
                            except TimeoutError:
                                _LOGGER.error("Connection error: Timed out connecting to server")
                                status = 1000
                                increment_failure_count()
                                break
                            except ConnectionRefusedError as e:
                                _LOGGER.error("Connection error, connection refused: %s", e)
                                status = 1000
                                increment_failure_count()
                                break
                            except (ClientConnectionError, ClientResponseError) as e:
                                _LOGGER.error("Client error: %s", e)
                                status = 1000
                                increment_failure_count()
                                break
                            if status in (200, 400, 401, 403, 404, 500):  # Do not retry for these statuses.
                                if status != 200:
                                    increment_failure_count()
                                break
                            if status == 429:
                                increment_failure_count()
                                # Test for API limit exceeded.
                                # {"response_status":{"error_code":"TooManyRequests","message":"You have exceeded your free daily limit.","errors":[]}}
                                response_json = await response.json(content_type=None)
                                if response_json is not None:
                                    response_status = response_json.get("response_status")
                                    if response_status is not None:
                                        if response_status.get("error_code") == "TooManyRequests":
                                            _LOGGER.debug("Set status to 998, API limit exceeded")
                                            status = 998
                                            self._api_used[api_key] = self._api_limit[api_key]
                                            await self.__serialise_usage(api_key)
                                            break
                                        status = 1000
                                        _LOGGER.warning("An unexpected error occurred: %s", response_status.get("message"))
                                        break
                            if counter >= tries:
                                _LOGGER.error("API was tried %d times, but all attempts failed", tries)
                                break
                            # Integration fetch is in a possibly recoverable state, so delay (15 seconds * counter),
                            # plus a random number of seconds between zero and 15.
                            delay = (counter * backoff) + random.randrange(0, 15)
                            _LOGGER.warning(
                                "Call status %s, pausing %d seconds before retry",
                                self.__translate(status),
                                delay,
                            )
                            await self._sleep(delay)

                        if status == 200:
                            if not force:
                                _LOGGER.debug(
                                    "API returned data, API counter incremented from %d to %d",
                                    self._api_used[api_key],
                                    self._api_used[api_key] + 1,
                                )
                                self._api_used[api_key] += 1
                                await self.__serialise_usage(api_key)
                            else:
                                _LOGGER.debug("API returned data, using force fetch so not incrementing API counter")
                            response_json = response_text
                            response_json = json.loads(response_json)
                            _LOGGER.debug(
                                "Task fetch_data took %.3f seconds",
                                time.time() - start_time,
                            )
                            return response_json
                        elif status in (400, 404):  # noqa: RET505
                            _LOGGER.error("Unexpected error getting sites, status %s returned", self.__translate(status))
                        elif status == 403:  # Forbidden.
                            _LOGGER.error("API key %s is forbidden, re-authentication required", self.__redact_api_key(api_key))
                            self.reauth_required = True
                        elif status == 998:  # Exceeded API limit.
                            _LOGGER.error(
                                "API allowed polling limit has been exceeded, API counter set to %d/%d",
                                self._api_used[api_key],
                                self._api_limit[api_key],
                            )
                        elif status == 1000:  # Unexpected response.
                            _LOGGER.error("Unexpected response received")
                        else:  # Other, or unknown status.
                            _LOGGER.error(
                                "Call status %s, API used is %d/%d",
                                self.__translate(status),
                                self._api_used[api_key],
                                self._api_limit[api_key],
                            )
                            _LOGGER.debug("HTTP session status %s", self.__translate(status))
                    else:
                        _LOGGER.warning(
                            "API polling limit exhausted, not getting forecast for site %s, API used is %d/%d",
                            site,
                            self._api_used[api_key],
                            self._api_limit[api_key],
                        )
                        return None

        except asyncio.exceptions.CancelledError:
            _LOGGER.info("Fetch cancelled")
        except json.decoder.JSONDecodeError:
            return response_text

        return None

    def __make_energy_dict(self) -> dict[str, dict[str, float]]:
        """Make a Home Assistant Energy dashboard compatible dictionary.

        Returns:
            dict: An Energy dashboard compatible data structure.

        """
        if self.options.use_actuals == HistoryType.FORECASTS:
            return {
                "wh_hours": OrderedDict(
                    sorted(
                        {
                            forecast["period_start"].isoformat(): round(forecast[self._use_forecast_confidence] * 500, 0)
                            for index, forecast in enumerate(self._data_forecasts)
                            if index > 1
                            and index < len(self._data_forecasts) - 2
                            and (
                                forecast[self._use_forecast_confidence] > 0
                                or self._data_forecasts[index - 1][self._use_forecast_confidence] > 0
                                or self._data_forecasts[index + 1][self._use_forecast_confidence] > 0
                                or (
                                    forecast["period_start"].minute == 30
                                    and self._data_forecasts[index - 2][self._use_forecast_confidence] > 0.2
                                )
                                or (
                                    forecast["period_start"].minute == 30
                                    and self._data_forecasts[index + 2][self._use_forecast_confidence] > 0.2
                                )
                            )
                        }.items()
                    )
                )
            }

        # Show estimated actuals on Energy dashboard, so combine past estimated actuals with forecast start of today onwards
        _data = (
            self._data_estimated_actuals
            if self.options.use_actuals == HistoryType.ESTIMATED_ACTUALS
            else self._data_estimated_actuals_dampened
        )
        forecasts_start, _ = self.__get_list_slice(self._data_forecasts, self.get_day_start_utc(), search_past=True)
        actuals_start, actuals_end = self.__get_list_slice(
            _data, self.get_day_start_utc() - timedelta(days=730), self.get_day_start_utc(), search_past=True
        )
        return {
            "wh_hours": OrderedDict(
                sorted(
                    (
                        {
                            actual["period_start"].isoformat(): round(actual["pv_estimate"] * 500, 0)
                            for index, actual in enumerate(_data)
                            if index > actuals_start + 1
                            and index < actuals_end - 2
                            and (
                                actual["pv_estimate"] > 0
                                or _data[index - 1]["pv_estimate"] > 0
                                or _data[index + 1]["pv_estimate"] > 0
                                or (actual["period_start"].minute == 30 and _data[index - 2]["pv_estimate"] > 0.2)
                                or (actual["period_start"].minute == 30 and _data[index + 2]["pv_estimate"] > 0.2)
                            )
                        }
                        | {
                            forecast["period_start"].isoformat(): round(forecast[self._use_forecast_confidence] * 500, 0)
                            for index, forecast in enumerate(self._data_forecasts)
                            if index >= forecasts_start
                            and index < len(self._data_forecasts) - 2
                            and (
                                forecast["pv_estimate"] > 0
                                or self._data_forecasts[index - 1]["pv_estimate"] > 0
                                or self._data_forecasts[index + 1]["pv_estimate"] > 0
                                or (forecast["period_start"].minute == 30 and self._data_forecasts[index - 2]["pv_estimate"] > 0.2)
                                or (forecast["period_start"].minute == 30 and self._data_forecasts[index + 2]["pv_estimate"] > 0.2)
                            )
                        }
                    ).items()
                )
            )
        }

    def __site_api_key(self, site: str) -> str | None:
        api_key: str | None = None
        for _site in self.sites:
            if _site["resource_id"] == site:
                api_key = _site["api_key"]
                break
        return api_key

    def hard_limit_set(self) -> tuple[bool, bool]:
        """Determine whether a hard limit is set.

        Returns:
            tuple: A flag indicating whether a hard limit is set, and whether multiple keys are in use.

        """
        limit_set = False
        hard_limit = self.hard_limit.split(",")
        multi_key = len(hard_limit) > 1
        for limit in hard_limit:
            if limit != "100.0":
                limit_set = True
                break
        return limit_set, multi_key

    def __hard_limit_for_key(self, api_key: str) -> float:
        hard_limit = self.hard_limit.split(",")
        limit = 100.0
        if len(hard_limit) == 1:
            limit = float(hard_limit[0])
        else:
            for index, key in enumerate(self.options.api_key.split(",")):
                if key == api_key:
                    limit = float(hard_limit[index])
                    break
        return limit

    async def build_actual_data(self) -> bool:
        """Build data structures needed, adjusting if setting a hard limit.

        Returns:
            bool: A flag indicating success or failure.

        """
        commencing: datetime.date = dt.now(self._tz).date() - timedelta(days=730)
        last_day: datetime.date = dt.now(self._tz).date()

        actuals: dict[dt, dict[str, dt | float]] = {}
        actuals_dampened: dict[dt, dict[str, dt | float]] = {}

        self._data_estimated_actuals = []
        self._data_estimated_actuals_dampened = []

        build_success = True

        async def build_data_actuals(
            data: dict[str, Any],
            commencing: datetime.date,
            actuals: dict[dt, dict[str, dt | float]],
            sites_hard_limit: defaultdict[str, dict[str, dict[dt, Any]]],
        ) -> list[Any]:
            nonlocal build_success

            api_key: str | None = None

            try:
                _, multi_key = self.hard_limit_set()

                # Build per-site actuals with hard limit applied.
                for resource_id, siteinfo in data.get("siteinfo", {}).items():
                    api_key = self.__site_api_key(resource_id) if multi_key else "all"
                    site_actuals: dict[dt, dict[str, dt | float]] = {}

                    if api_key is not None:
                        for actual in siteinfo["forecasts"]:
                            period_start = actual["period_start"]
                            period_start_local = period_start.astimezone(self._tz)

                            if commencing < period_start_local.date() < last_day:
                                # Record the individual site actual.
                                site_actuals[period_start] = {
                                    "period_start": period_start,
                                    "pv_estimate": round(
                                        min(
                                            actual["pv_estimate"],
                                            sites_hard_limit[api_key]["pv_estimate"].get(period_start, {}).get(resource_id, 100),
                                        ),
                                        4,
                                    ),
                                }

                                # If the site is not excluded, add to the total.
                                if resource_id not in self.options.exclude_sites:
                                    extant: dict[str, Any] | None = actuals.get(period_start)
                                    if extant is not None:
                                        extant["pv_estimate"] = round(
                                            extant["pv_estimate"] + site_actuals[period_start]["pv_estimate"],
                                            4,
                                        )
                                    else:
                                        actuals[period_start] = {
                                            "period_start": period_start,
                                            "pv_estimate": site_actuals[period_start]["pv_estimate"],
                                        }
                        # site_data_forecasts[resource_id] = sorted(site_actuals.values(), key=itemgetter("period_start"))
                return sorted(actuals.values(), key=itemgetter("period_start"))
            except Exception as e:  # noqa: BLE001
                _LOGGER.error("Exception in build_data_actuals(): %s: %s", e, traceback.format_exc())
                build_success = False
                return []

        start_time = time.time()
        self._data_estimated_actuals = await build_data_actuals(
            self._data_actuals,
            commencing,
            actuals,
            self._sites_hard_limit,
        )
        self._data_estimated_actuals_dampened = await build_data_actuals(
            self._data_actuals_dampened,
            commencing,
            actuals_dampened,
            self._sites_hard_limit,
        )
        _LOGGER.debug("Task build_data_actuals took %.3f seconds", time.time() - start_time)
        self._data_energy_dashboard = self.__make_energy_dict()

        return build_success

    async def build_forecast_data(self) -> bool:  # noqa: C901
        """Build data structures needed, adjusting if setting a hard limit.

        Returns:
            bool: A flag indicating success or failure.

        """
        today: datetime.date = dt.now(self._tz).date()
        commencing: datetime.date = dt.now(self._tz).date() - timedelta(days=730)
        commencing_undampened: datetime.date = dt.now(self._tz).date() - timedelta(days=14)
        last_day: datetime.date = dt.now(self._tz).date() + timedelta(days=FORECAST_DAYS)
        logged_hard_limit: list[str] = []

        forecasts: dict[dt, dict[str, dt | float]] = {}
        forecasts_undampened: dict[dt, dict[str, dt | float]] = {}

        self._data_forecasts = []
        self._data_forecasts_undampened = []

        build_success = True

        async def build_data(  # noqa: C901
            data: dict[str, Any],
            commencing: datetime.date,
            forecasts: dict[dt, dict[str, dt | float]],
            site_data_forecasts: dict[str, list[dict[str, dt | float]]],
            sites_hard_limit: defaultdict[str, dict[str, dict[dt, Any]]],
            update_tally: bool = False,
        ):
            nonlocal build_success

            site = None
            tally: Any = None
            api_key: str | None = None

            try:
                # Build per-site hard limit.
                # The API key hard limit for each site is calculated as proportion of the site contribution for the account.
                start_time = time.time()
                hard_limit_set, multi_key = self.hard_limit_set()
                if hard_limit_set:
                    api_key_sites: dict[str, Any] = defaultdict(dict)
                    for site in self.sites:
                        api_key_sites[site["api_key"] if multi_key else "all"][site["resource_id"]] = {
                            "earliest_period": data["siteinfo"][site["resource_id"]]["forecasts"][0]["period_start"],
                            "last_period": data["siteinfo"][site["resource_id"]]["forecasts"][-1]["period_start"],
                        }
                    if update_tally:
                        _LOGGER.debug("Hard limit for individual API keys %s", multi_key)
                    for api_key, sites in api_key_sites.items():
                        hard_limit = self.__hard_limit_for_key(api_key)
                        _api_key = self.__redact_api_key(api_key) if multi_key else "all"
                        if _api_key not in logged_hard_limit:
                            logged_hard_limit.append(_api_key)
                            _LOGGER.debug(
                                "Hard limit for API key %s is %s",
                                _api_key,
                                hard_limit,
                            )
                        siteinfo = {
                            site: {forecast["period_start"]: forecast for forecast in data["siteinfo"][site]["forecasts"]} for site in sites
                        }
                        earliest: dt = dt.now(self._tz)
                        latest: dt = earliest
                        for limits in sites.values():
                            if len(sites_hard_limit[api_key]) == 0:
                                _LOGGER.debug(
                                    "Build hard limit period values from scratch for %s",
                                    "dampened" if update_tally else "un-dampened",
                                )
                                earliest = min(earliest, limits["earliest_period"])
                            else:
                                earliest = self.get_day_start_utc()  # Past hard limits done, so re-calculate from today onwards
                            latest = limits["last_period"]
                        _LOGGER.debug(
                            "Earliest period %s, latest period %s",
                            dt.strftime(earliest.astimezone(self._tz), DATE_FORMAT),
                            dt.strftime(latest.astimezone(self._tz), DATE_FORMAT),
                        )
                        periods: list[dt] = [
                            earliest + timedelta(minutes=30 * x) for x in range(int((latest - earliest).total_seconds() / 1800))
                        ]
                        for pv_estimate in [
                            "pv_estimate",
                            "pv_estimate10",
                            "pv_estimate90",
                        ]:
                            sites_hard_limit[api_key][pv_estimate] = {}
                        for period in periods:
                            for pv_estimate in [
                                "pv_estimate",
                                "pv_estimate10",
                                "pv_estimate90",
                            ]:
                                estimate = {site: siteinfo[site].get(period, {}).get(pv_estimate) for site in sites}
                                total_estimate = sum(estimate[site] for site in sites if estimate[site] is not None)
                                if total_estimate == 0:
                                    continue
                                sites_hard_limit[api_key][pv_estimate][period] = {
                                    site: estimate[site] / total_estimate * hard_limit for site in sites if estimate[site] is not None
                                }
                    _LOGGER.debug(
                        "Build hard limit processing took %.3f seconds for %s",
                        time.time() - start_time,
                        "dampened" if update_tally else "un-dampened",
                    )
                elif multi_key:
                    for api_key in self.options.api_key.split(","):
                        for pv_estimate in [
                            "pv_estimate",
                            "pv_estimate10",
                            "pv_estimate90",
                        ]:
                            sites_hard_limit[api_key][pv_estimate] = {}
                else:
                    for pv_estimate in [
                        "pv_estimate",
                        "pv_estimate10",
                        "pv_estimate90",
                    ]:
                        sites_hard_limit["all"][pv_estimate] = {}

                # Build per-site and total forecasts with proportionate hard limit applied.
                for resource_id, siteinfo in data.get("siteinfo", {}).items():
                    api_key = self.__site_api_key(resource_id) if multi_key else "all"
                    if update_tally:
                        tally = None
                    site_forecasts: dict[dt, dict[str, dt | float]] = {}

                    if api_key is not None:
                        for forecast in siteinfo["forecasts"]:
                            period_start = forecast["period_start"]
                            period_start_local = period_start.astimezone(self._tz)

                            if commencing < period_start_local.date() < last_day:
                                # Record the individual site forecast.
                                site_forecasts[period_start] = {
                                    "period_start": period_start,
                                    "pv_estimate": round(
                                        min(
                                            forecast["pv_estimate"],
                                            sites_hard_limit[api_key]["pv_estimate"].get(period_start, {}).get(resource_id, 100),
                                        ),
                                        4,
                                    ),
                                    "pv_estimate10": round(
                                        min(
                                            forecast["pv_estimate10"],
                                            sites_hard_limit[api_key]["pv_estimate10"].get(period_start, {}).get(resource_id, 100),
                                        ),
                                        4,
                                    ),
                                    "pv_estimate90": round(
                                        min(
                                            forecast["pv_estimate90"],
                                            sites_hard_limit[api_key]["pv_estimate90"].get(period_start, {}).get(resource_id, 100),
                                        ),
                                        4,
                                    ),
                                }

                                if update_tally and period_start_local.date() == today:
                                    if tally is None:
                                        tally = 0.0
                                    tally += (
                                        min(
                                            forecast[self._use_forecast_confidence],
                                            sites_hard_limit[api_key][self._use_forecast_confidence]
                                            .get(period_start, {})
                                            .get(resource_id, 100),
                                        )
                                        * 0.5
                                    )

                                # If the forecast is for today, and the site is not excluded, add to the total.
                                if resource_id not in self.options.exclude_sites:
                                    extant: dict[str, Any] | None = forecasts.get(period_start)
                                    if extant is not None:
                                        extant["pv_estimate"] = round(
                                            extant["pv_estimate"] + site_forecasts[period_start]["pv_estimate"],
                                            4,
                                        )
                                        extant["pv_estimate10"] = round(
                                            extant["pv_estimate10"] + site_forecasts[period_start]["pv_estimate10"],
                                            4,
                                        )
                                        extant["pv_estimate90"] = round(
                                            extant["pv_estimate90"] + site_forecasts[period_start]["pv_estimate90"],
                                            4,
                                        )
                                    else:
                                        forecasts[period_start] = {
                                            "period_start": period_start,
                                            "pv_estimate": site_forecasts[period_start]["pv_estimate"],
                                            "pv_estimate10": site_forecasts[period_start]["pv_estimate10"],
                                            "pv_estimate90": site_forecasts[period_start]["pv_estimate90"],
                                        }
                                        if update_tally and self.options.auto_dampen and period_start >= self.get_day_start_utc():
                                            forecasts[period_start]["dampening_factor"] = round(
                                                self._auto_dampening_factors[period_start], 4
                                            )
                        site_data_forecasts[resource_id] = sorted(site_forecasts.values(), key=itemgetter("period_start"))
                        if update_tally:
                            rounded_tally: Any = round(tally, 4) if tally is not None else 0.0
                            if tally is not None:
                                siteinfo["tally"] = rounded_tally
                            self._tally[resource_id] = rounded_tally
                if update_tally:
                    self._data_forecasts = sorted(forecasts.values(), key=itemgetter("period_start"))
                else:
                    self._data_forecasts_undampened = sorted(forecasts.values(), key=itemgetter("period_start"))
            except Exception as e:  # noqa: BLE001, handle all exceptions
                _LOGGER.error("Exception in build_data(): %s: %s", e, traceback.format_exc())
                self._data_forecasts = []
                self._data_forecasts_undampened = []
                if update_tally:
                    for site in self.sites:
                        self._tally[site["resource_id"]] = None
                build_success = False

        start_time = time.time()
        await build_data(
            self._data,
            commencing,
            forecasts,
            self._site_data_forecasts,
            self._sites_hard_limit,
            update_tally=True,
        )
        if build_success:
            await build_data(
                self._data_undampened,
                commencing_undampened,
                forecasts_undampened,
                self._site_data_forecasts_undampened,
                self._sites_hard_limit_undampened,
            )
        _LOGGER.debug("Task build_data took %.3f seconds", time.time() - start_time)
        self._data_energy_dashboard = self.__make_energy_dict()

        await self.check_data_records()
        await self.recalculate_splines()
        return build_success

    def __calc_forecast_start_index(self, data: list[dict[str, Any]]) -> int:
        """Get the start of forecasts as-at just before midnight.

        Doesn't stop at midnight because some sensors may need the previous interval,
        and searches in reverse because less to iterate.

        Arguments:
            data (list): The data structure to search, either total data or site breakdown data.

        Returns:
            int: The starting index of the data structure just prior to midnight local time.

        """
        index = 0
        midnight_utc = self.get_day_start_utc()
        for index in range(len(data) - 1, -1, -1):
            if data[index]["period_start"] < midnight_utc:
                break
        return index

    async def check_data_records(self) -> None:
        """Log whether all records are present for each day.

        Returns:
            bool: A flag indicating success or failure.

        """
        contiguous: int = 0
        contiguous_start_date: Any = None
        contiguous_end_date: Any = None
        all_records_good = True
        summer_time_transitioning = False
        interval_assessment: dict[datetime.date, Any] = {}

        # The latest period is used to determine whether any history should be updated on stale start.
        self.latest_period = self._data_forecasts[-1]["period_start"] if len(self._data_forecasts) > 0 else None

        for future_day in range(FORECAST_DAYS):
            start_utc = self.get_day_start_utc(future=future_day)
            end_utc = self.get_day_start_utc(future=future_day + 1)
            start_index, end_index = self.__get_list_slice(self._data_forecasts, start_utc, end_utc)

            expected_intervals = 48
            _is_dst: bool | None = None
            for interval in range(start_index, end_index):
                if interval == start_index:
                    _is_dst = self.is_dst(self._data_forecasts[interval])
                else:
                    is_daylight = self.is_dst(self._data_forecasts[interval])
                    if is_daylight is not None and is_daylight != _is_dst:
                        summer_time_transitioning = True
                        expected_intervals = 50 if _is_dst else 46
            intervals = end_index - start_index
            forecasts_date = dt.now(self._tz).date() + timedelta(days=future_day)

            def set_assessment(forecasts_date: date, expected_intervals: int, intervals: int, contiguous: int, is_correct: bool) -> int:
                nonlocal all_records_good, contiguous_end_date
                interval_assessment[forecasts_date] = {
                    "expected_intervals": expected_intervals,
                    "intervals": intervals,
                    "correct": is_correct,
                }
                if is_correct:
                    if all_records_good:
                        contiguous += 1
                        contiguous_end_date = forecasts_date
                else:
                    all_records_good = False
                return contiguous

            if intervals == expected_intervals:
                contiguous = set_assessment(forecasts_date, expected_intervals, intervals, contiguous, True)
            else:
                contiguous = set_assessment(forecasts_date, expected_intervals, intervals, contiguous, False)
            if future_day == 0 and interval_assessment[forecasts_date]["correct"]:
                contiguous_start_date = forecasts_date
        if summer_time_transitioning:
            _LOGGER.debug("Transitioning between summer/standard time")
        if contiguous > 1:
            _LOGGER.debug(
                "Forecast data from %s to %s contains all intervals",
                contiguous_start_date.strftime("%Y-%m-%d"),
                contiguous_end_date.strftime("%Y-%m-%d"),
            )
        else:
            contiguous_end_date = None
        if contiguous < FORECAST_DAYS:
            for day, assessment in OrderedDict(sorted(interval_assessment.items(), key=lambda k: k[0])).items():
                if contiguous_end_date is not None and day <= contiguous_end_date:
                    continue
                match assessment["correct"]:
                    case True:
                        _LOGGER.debug(
                            "Forecast data for %s contains all intervals",
                            day.strftime("%Y-%m-%d"),
                        )
                    case _:
                        (_LOGGER.debug if contiguous == FORECAST_DAYS - 1 else _LOGGER.warning)(
                            "Forecast data for %s contains %d of %d intervals%s",
                            day.strftime("%Y-%m-%d"),
                            assessment["intervals"],
                            assessment["expected_intervals"],
                            ", which may be expected" if contiguous == FORECAST_DAYS - 1 else ", so is missing forecast data",
                        )
        issue_registry = ir.async_get(self.hass)

        def _remove_issues():
            # Remove any relevant issues that may exist.
            for check_issue in ("records_missing", "records_missing_fixable"):
                if issue_registry.async_get_issue(DOMAIN, check_issue) is not None:
                    _LOGGER.debug("Remove issue for %s", check_issue)
                    ir.async_delete_issue(self.hass, DOMAIN, check_issue)

        if 0 < contiguous < FORECAST_DAYS - 1:
            if self.entry is not None:
                # If auto-update is enabled then raise an un-fixable issue, otherwise raise a fixable issue.
                raise_issue: str | None
                raise_issue = "records_missing_fixable" if self.entry.options["auto_update"] == AutoUpdate.NONE else "records_missing"
                # If auto-update is enabled yet the prior forecast update was manual then do not raise an issue.
                raise_issue = None if self._data["auto_updated"] == 0 and self.entry.options["auto_update"] != 0 else raise_issue
                if raise_issue is not None and issue_registry.async_get_issue(DOMAIN, raise_issue) is None:
                    _LOGGER.warning("Raise issue `%s` for missing forecast data", raise_issue)
                    ir.async_create_issue(
                        self.hass,
                        DOMAIN,
                        raise_issue,
                        is_fixable=self.entry.options["auto_update"] == AutoUpdate.NONE,
                        data={
                            "contiguous": contiguous,
                        },
                        severity=ir.IssueSeverity.WARNING,
                        translation_key=raise_issue,
                        learn_more_url="https://github.com/BJReplay/ha-solcast-solar?tab=readme-ov-file#updating-forecasts",
                    )
                if not raise_issue:
                    _remove_issues()
        if contiguous >= FORECAST_DAYS - 1:
            # If data is all (or mostly) present then remove any relevant issues.
            _remove_issues()
