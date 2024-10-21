"""Solcast API."""

# pylint: disable=C0302, C0304, C0321, E0401, R0902, R0914, W0105, W0702, W0706, W0718, W0719

from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
import os
import sys
import time
import traceback
import random
import re
from dataclasses import dataclass
from datetime import datetime as dt
from datetime import timedelta, timezone
from operator import itemgetter
from pathlib import Path
from os.path import exists as file_exists
from os.path import dirname
from typing import Optional, Any, Dict, Tuple, cast
from collections import OrderedDict

import async_timeout # type: ignore
import aiofiles # type: ignore
from aiohttp import ClientConnectionError, ClientSession # type: ignore
from aiohttp.client_reqrep import ClientResponse # type: ignore
from isodate import parse_datetime # type: ignore

from homeassistant.exceptions import ServiceValidationError # type: ignore
from homeassistant.const import CONF_API_KEY # type: ignore

from .spline import cubic_interp
from .const import (
    BRK_ESTIMATE,
    BRK_ESTIMATE10,
    BRK_ESTIMATE90,
    BRK_SITE,
    BRK_HALFHOURLY,
    BRK_HOURLY,
    BRK_SITE_DETAILED,
    CUSTOM_HOUR_SENSOR,
    DATE_FORMAT,
    DATE_FORMAT_UTC,
    DOMAIN,
    FORECAST_DEBUG_LOGGING,
    HARD_LIMIT,
    KEY_ESTIMATE,
    SENSOR_DEBUG_LOGGING,
    SITE_DAMP,
    SPLINE_DEBUG_LOGGING,
)

"""Return the function name at a specified caller depth.

* For current function name, specify 0 or no argument
* For name of caller of current function, specify 1
* For name of caller of caller of current function, specify 2, etc.
"""
currentFuncName = lambda n=0: sys._getframe(n + 1).f_code.co_name # pylint: disable=C3001, W0212

GRANULAR_DAMPENING_OFF = False
GRANULAR_DAMPENING_ON = True
JSON_VERSION = 4
SET_ALLOW_RESET = True

_LOGGER = logging.getLogger(__name__)

class DateTimeEncoder(json.JSONEncoder):
    """Helper to convert datetime dict values to ISO format."""
    def default(self, o) -> Optional[str]:
        if isinstance(o, dt):
            return o.isoformat()
        else:
            return None

class NoIndentEncoder(json.JSONEncoder):
    """Helper to output semi-indented json."""
    def iterencode(self, o, _one_shot=False):
        list_lvl = 0
        for s in super(NoIndentEncoder, self).iterencode(o, _one_shot=_one_shot):
            if s.startswith('['):
                list_lvl += 1
                s = s.replace(' ','').replace('\n', '').rstrip()
            elif list_lvl > 0:
                s = s.replace(' ','').replace('\n', '').rstrip()
                if s and s[-1] == ',':
                    s = s[:-1] + self.item_separator
                elif s and s[-1] == ':':
                    s = s[:-1] + self.key_separator
            if s.endswith(']'):
                list_lvl -= 1
            yield s

class JSONDecoder(json.JSONDecoder):
    """Helper to convert ISO format dict values to datetime."""
    def __init__(self, *args, **kwargs):
        json.JSONDecoder.__init__(
            self, object_hook=self.object_hook, *args, **kwargs)

    def object_hook(self, obj) -> dict: # pylint: disable=E0202
        """Required hook."""
        ret = {}
        for key, value in obj.items():
            if key in {'period_start', 'reset'}:
                ret[key] = dt.fromisoformat(value)
            else:
                ret[key] = value
        return ret

# HTTP status code translation.
# A 418 error is included here for fun. This introduced in RFC2324#section-2.3.2 as an April Fools joke in 1998.
__status_translate = {
    200: 'Success',
    401: 'Unauthorized',
    403: 'Forbidden',
    404: 'Not found',
    418: 'I\'m a teapot',
    429: 'Try again later',
    500: 'Internal web server error',
    501: 'Not implemented',
    502: 'Bad gateway',
    503: 'Service unavailable',
    504: 'Gateway timeout',
}

def translate(status) -> str | Any:
    """Translate HTTP status code to a human-readable translation.

    Arguments:
        status (int): A HTTP status code.

    Returns:
        str: Human readable HTTP status.
    """
    return (f"{str(status)}/{__status_translate[status]}") if __status_translate.get(status) else status


@dataclass
class ConnectionOptions:
    """Solcast options for the integration."""

    api_key: str
    api_quota: str
    host: str
    file_path: str
    tz: timezone
    auto_update: int
    dampening: dict
    custom_hour_sensor: int
    key_estimate: str
    hard_limit: int
    attr_brk_estimate: bool
    attr_brk_estimate10: bool
    attr_brk_estimate90: bool
    attr_brk_site: bool
    attr_brk_halfhourly: bool
    attr_brk_hourly: bool
    attr_brk_site_detailed: bool


class SolcastApi: # pylint: disable=R0904
    """The Solcast API.

    Functions:
        get_forecast_update: Request forecast data for all sites.
        get_data: Reurn the data dictionary.
        build_forecast_data: Build the forecast, adjusting if dampening or setting a hard limit.

        get_forecast_list: Service event to get list of forecasts.
        delete_solcast_file: Service event to delete the solcast.json file.
        get_sites_and_usage: Get the sites and usage, and validate API key changes against the cache files in use.
        reset_api_usage: Reset the daily API usage counter.
        load_saved_data: Load the saved solcast.json data.
        serialise_granular_dampening: Serialise the granular dampening file.
        granular_dampening_data: Read the current granular dampening file.
        get_dampening: Return the currently set dampening factors for a service call.

        get_last_updated_datetime: Return when the data was last updated.
        is_stale_data: Return whether the forecast was last updated some time ago (i.e. is stale).
        get_api_limit: Return API polling limit for this UTC 24hr period (minimum of all API keys).
        get_api_used_count: Return API polling count for this UTC 24hr period (minimum of all API keys).

        get_rooftop_site_total_today: Return total kW for today for a site.
        get_rooftop_site_extra_data: Return information about a site.
        get_forecast_day: Return forecast data for the Nth day ahead.
        get_forecast_n_hour: Return forecast for the Nth hour. Based from prior hour point.
        get_forecasts_n_hour: Return forecast for the Nth hour for all sites and individual sites.
        get_forecast_custom_hours: Return forecast for the next N hours. Interpolated, based from prior 5-minute point.
        get_forecasts_custom_hours: Return forecast for the next N hours for all sites and individual sites.
        get_power_n_mins: Return expected power generation in the next N minutes. Based from prior half-hour point.
        get_sites_power_n_mins: Return expected power generation in the next N minutes for all sites and individual sites.
        get_peak_w_day: Return max kW for site N days ahead.
        get_sites_peak_w_day: Return max kW for site N days ahead for all sites and individual sites.
        get_peak_w_time_day: Return hour of max kW for site N days ahead.
        get_sites_peak_w_time_day: Return hour of max kW for site N days ahead for all sites and individual sites.
        get_forecast_remaining_today: Return remaining forecasted production for today. Interpolated, based from prior 5-minute point.
        get_forecasts_remaining_today: Return remaining forecasted production for today for all sites and individual sites.
        get_total_kwh_forecast_day: Return forecast kWh total for site N days ahead.
        get_sites_total_kwh_forecast_day: Return forecast kWh total for site N days ahead for all sites and individual sites.
    """

    def __init__(
        self,
        aiohttp_session: ClientSession,
        options: ConnectionOptions,
        api_cache_enabled: bool = False
    ):
        """Initialisation.

        Public variables at the top, protected variables following.

        Arguments:
            aiohttp_session (ClientSession): The aiohttp client session provided by Home Assistant
            options (ConnectionOptions): The integration stored configuration options.
            api_cache_enabled (bool): Utilise cached data instead of getting updates from Solcast (default: {False}).
        """

        self.custom_hour_sensor = options.custom_hour_sensor
        self.damp = options.dampening # Re-set on recalc in __init__
        self.entry = None
        self.entry_options = {}
        self.estimate_set = {'pv_estimate': options.attr_brk_estimate, 'pv_estimate10': options.attr_brk_estimate10, 'pv_estimate90': options.attr_brk_estimate90}
        self.granular_dampening = {}
        self.hard_limit = options.hard_limit
        self.hass = None
        self.headers = {}
        self.options = options
        self.previously_loaded = False
        self.sites = []
        self.sites_loaded = False
        self.tasks = {}

        self._aiohttp_session = aiohttp_session
        self._api_cache_enabled = api_cache_enabled # For offline development.
        self._api_limit = {}
        self._api_used = {}
        self._api_used_reset = {}
        self._data = {'siteinfo': {}, 'last_updated': dt.fromtimestamp(0, timezone.utc).isoformat(), 'version': JSON_VERSION}
        self._data_energy = {}
        self._data_forecasts = []
        self._data_forecasts_undampened = []
        self._data_undampened = copy.deepcopy(self._data)
        self._filename = options.file_path
        file_name, extension = os.path.splitext(options.file_path)
        self._filename_undampened = f"{file_name}-undampened{extension}"
        self._forecasts_moment = {}
        self._forecasts_remaining = {}
        self._granular_allow_reset = True
        self._granular_dampening_mtime = 0
        self._loaded_data = False
        self._site_data_forecasts = {}
        self._site_data_forecasts_undampened = {}
        self._spline_period = list(range(0, 90000, 1800))
        self._serialise_lock = asyncio.Lock()
        self._tally = {}
        self._tz = options.tz
        self._use_data_field = f"pv_{options.key_estimate}"
        #self._weather = ""

        self._config_dir = dirname(self._filename)
        _LOGGER.debug("Configuration directory is %s", self._config_dir)

    async def set_options(self, options: dict):
        """Set the class option variables (used by __init__ to avoid an integration reload).

        Arguments:
            options (dict): The data field to use for sensor values
        """
        self.damp = {str(i): options[f"damp{i:02}"] for i in range(0,24)}
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
            options.get(HARD_LIMIT, 100000) / 1000,
            options[BRK_ESTIMATE],
            options[BRK_ESTIMATE10],
            options[BRK_ESTIMATE90],
            options[BRK_SITE],
            options[BRK_HALFHOURLY],
            options[BRK_HOURLY],
            options[BRK_SITE_DETAILED],
        )
        self.hard_limit = self.options.hard_limit
        self._use_data_field = f"pv_{self.options.key_estimate}"
        self.estimate_set = {
            'pv_estimate': options[BRK_ESTIMATE],
            'pv_estimate10': options[BRK_ESTIMATE10],
            'pv_estimate90': options[BRK_ESTIMATE90],
        }

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
        return self.get_last_updated_datetime() < self.get_day_start_utc() - timedelta(days=1)

    def is_stale_usage_cache(self) -> bool:
        """Return whether the usage cache was last reset over 24-hours ago (i.e. is stale).

        Returns:
            bool: True for stale, False if reset recently.
        """
        sp = self.options.api_key.split(",")
        for spl in sp:
            api_key = spl.strip()
            if self._api_used_reset[api_key] < self.__get_utc_previous_midnight():
                return True
        return False

    def __redact_api_key(self, api_key) -> str:
        """Obfuscate API key.

        Arguments:
            api_key (str): An individual Solcast account API key.

        Returns:
            str: The last six characters of the key, prepended by six asterisks.
        """
        return '*'*6 + api_key[-6:]

    def __redact_msg_api_key(self, msg, api_key) -> str:
        """Obfuscate API key in messages.

        Arguments:
            msg (str): Typically a message to be logged.
            api_key (str): An individual Solcast account API key.

        Returns:
            str: The message, with API key obfuscated.
        """
        return msg.replace(api_key, self.__redact_api_key(api_key))

    def __is_multi_key(self) -> bool:
        """Test whether multiple API keys are in use.

        Returns:
            bool: True for multiple API Solcast accounts configured. If configured then separate files will be used for caches.
        """
        return len(self.options.api_key.split(",")) > 1

    def __get_usage_cache_filename(self, api_key) -> str:
        """Build an API cache filename.

        Arguments:
            api_key (str): An individual Solcast account API key.

        Returns:
            str: A fully qualified cache filename using a simple name or separate files for more than one API key.
        """
        return f"{self._config_dir}/solcast-usage{'' if not self.__is_multi_key() else '-' + api_key}.json"

    def __get_sites_cache_filename(self, api_key) -> str:
        """Build a site details cache filename.

        Arguments:
            api_key (str): An individual Solcast account API key.

        Returns:
            str: A fully qualified cache filename using a simple name or separate files for more than one API key.
        """
        return f"{self._config_dir}/solcast-sites{'' if not self.__is_multi_key() else '-' + api_key}.json"

    def __get_granular_dampening_filename(self, legacy=False) -> str:
        """Build a fully qualified site dampening filename.

        Arguments:
            legacy (bool): Return the name of the legacy per-site dampening file.

        Returns:
            str: A fully qualified cache filename.
        """
        if legacy:
            return f"{self._config_dir}/solcast-site-dampening.json"
        else:
            return f"{self._config_dir}/solcast-dampening.json"

    async def __serialise_data(self, data, filename) -> bool:
        """Serialize data to file.

        Arguments:
            data (dict): The data to serialise.
            filename (str): The name of the file

        Returns:
            bool: Success or failure.
        """
        serialise = True
        # The twin try/except blocks here are significant. If the two were combined with
        # `await f.write(json.dumps(self._data, ensure_ascii=False, cls=DateTimeEncoder))`
        # then should an exception occur during conversion from dict to JSON string it
        # would result in an empty file.
        try:
            if not self._loaded_data:
                _LOGGER.debug("Not saving forecast cache in __serialise_data() as no data has been loaded yet")
                return False
            """
            If the _loaded_data flag is True, yet last_updated is 1/1/1970 then data has not been loaded
            properly for some reason, or no forecast has been received since startup so abort the save.
            """
            if data['last_updated'] == dt.fromtimestamp(0, timezone.utc).isoformat():
                _LOGGER.error("Internal error: Forecast cache %s last updated date has not been set, not saving data", filename)
                return False
            payload = json.dumps(data, ensure_ascii=False, cls=DateTimeEncoder)
        except Exception as e:
            _LOGGER.error("Exception in __serialise_data(): %s: %s", e, traceback.format_exc())
            serialise = False
        if serialise:
            try:
                async with self._serialise_lock:
                    async with aiofiles.open(filename, 'w') as f:
                        await f.write(payload)
                _LOGGER.debug("Saved %s forecast cache", "dampened" if filename == self._filename else "undampened")
                return True
            except Exception as e:
                _LOGGER.error("Exception writing forecast data: %s", e)
        return False

    async def __sites_data(self):
        """Request site details.

        The Solcast API is called here with a simple five-second retry mechanism. If
        the sites cannot be loaded then the integration cannot function, and this will
        result in Home Assistant repeatedly trying to initialise.
        """
        try:
            def redact_lat_lon(s) -> str:
                return re.sub(r'itude\': [0-9\-\.]+', 'itude\': **.******', s)
            sp = self.options.api_key.split(",")
            for spl in sp:
                api_key = spl.strip()
                async with async_timeout.timeout(60):
                    cache_filename = self.__get_sites_cache_filename(api_key)
                    _LOGGER.debug("%s", "Sites cache " + ("exists" if file_exists(cache_filename) else "does not yet exist"))
                    if self._api_cache_enabled and file_exists(cache_filename):
                        _LOGGER.debug("Loading cached sites data")
                        status = 404
                        async with aiofiles.open(cache_filename) as f:
                            resp_json = json.loads(await f.read())
                            status = 200
                    else:
                        url = f"{self.options.host}/rooftop_sites"
                        params = {"format": "json", "api_key": api_key}
                        _LOGGER.debug("Connecting to %s?format=json&api_key=%s", url, self.__redact_api_key(api_key))
                        retries = 3
                        retry = retries
                        success = False
                        use_cache_immediate = False
                        cache_exists = file_exists(cache_filename)
                        while retry >= 0:
                            resp: ClientResponse = await self._aiohttp_session.get(url=url, params=params, headers=self.headers, ssl=False)

                            status = resp.status
                            (_LOGGER.info if status == 200 else _LOGGER.warning)("HTTP session returned status %s in __sites_data()%s", translate(status), ", trying cache" if status != 200 else "")
                            try:
                                resp_json = await resp.json(content_type=None)
                            except json.decoder.JSONDecodeError:
                                _LOGGER.error("JSONDecodeError in __sites_data(): Solcast could be having problems")
                            except:
                                raise

                            if status == 200:
                                for i in resp_json['sites']:
                                    i['api_key'] = api_key
                                if resp_json['total_records'] > 0:
                                    _LOGGER.debug("Writing sites cache")
                                    async with self._serialise_lock:
                                        async with aiofiles.open(cache_filename, 'w') as f:
                                            await f.write(json.dumps(resp_json, ensure_ascii=False))
                                    success = True
                                    break
                                else:
                                    _LOGGER.error("No sites for the API key %s are configured at solcast.com", self.__redact_api_key(api_key))
                                    break
                            else:
                                if cache_exists:
                                    use_cache_immediate = True
                                    break
                                if status == 404:
                                    _LOGGER.error("Error getting sites for the API key %s, is the key correct?", self.__redact_api_key(api_key))
                                    break
                                if retry > 0:
                                    _LOGGER.debug("Will retry get sites, retry %d", (retries - retry) + 1)
                                    await asyncio.sleep(5)
                                retry -= 1
                        if status == 404 and not use_cache_immediate:
                            continue
                        if not success:
                            if not use_cache_immediate:
                                _LOGGER.warning("Retries exhausted gathering sites, last call result: %s, using cached data if it exists", translate(status))
                            status = 404
                            if cache_exists:
                                async with aiofiles.open(cache_filename) as f:
                                    resp_json = json.loads(await f.read())
                                    status = 200
                                    for i in resp_json['sites']:
                                        if i.get('api_key') is None:
                                            continue
                                        if i.get('api_key') not in sp:
                                            status = 429
                                            _LOGGER.debug("API key has changed so sites cache is invalid, not loading cached data")
                                            break
                            else:
                                _LOGGER.error("Cached sites are not yet available for %s to cope with API call failure", self.__redact_api_key(api_key))
                                _LOGGER.error("At least one successful API 'get sites' call is needed, so the integration will not function correctly")

                if status == 200:
                    d = cast(dict, resp_json)
                    _LOGGER.debug("Sites data: %s", self.__redact_msg_api_key(redact_lat_lon(str(d)), api_key))
                    for i in d['sites']:
                        i['apikey'] = api_key
                        i.pop('longitude', None)
                        i.pop('latitude', None)
                    self.sites = self.sites + d['sites']
                    self.sites_loaded = True
                    self._api_used_reset[api_key] = None
                    if not self.previously_loaded:
                        _LOGGER.info("Sites loaded%s", (" for " + self.__redact_api_key(api_key)) if self.__is_multi_key() else "")
                else:
                    _LOGGER.error("%s HTTP status error %s in __sites_data() while gathering sites", self.options.host, translate(status))
                    raise Exception("HTTP __sites_data() error: gathering sites")
        except ConnectionRefusedError as e:
            _LOGGER.error("Connection refused in __sites_data(): %s", e)
        except ClientConnectionError as e:
            _LOGGER.error("Connection error in __sites_data(): %s", e)
        except asyncio.TimeoutError:
            try:
                _LOGGER.warning("Retrieving sites timed out, attempting to continue")
                error = False
                for spl in sp:
                    api_key = spl.strip()
                    cache_filename = self.__get_sites_cache_filename(api_key)
                    cache_exists = file_exists(cache_filename)
                    if cache_exists:
                        _LOGGER.info("Loading cached sites for %s", self.__redact_api_key(api_key))
                        async with aiofiles.open(cache_filename) as f:
                            resp_json = json.loads(await f.read())
                            d = cast(dict, resp_json)
                            _LOGGER.debug("Sites data: %s", redact_lat_lon(str(d)))
                            for i in d['sites']:
                                i['apikey'] = api_key
                                i.pop('longitude', None)
                                i.pop('latitude', None)
                                i['api_key'] = None
                            self.sites = self.sites + d['sites']
                            self.sites_loaded = True
                            self._api_used_reset[api_key] = None
                            if not self.previously_loaded:
                                _LOGGER.info("Sites loaded%s", (" for " + self.__redact_api_key(api_key)) if self.__is_multi_key() else "")
                    else:
                        error = True
                        _LOGGER.error("Cached sites are not yet available for %s to cope with API call failure", self.__redact_api_key(api_key))
                        _LOGGER.error("At least one successful API 'get sites' call is needed, so the integration will not function correctly")
                if error:
                    _LOGGER.error("Suggestion: Check your overall HA configuration, specifically networking related (Is IPV6 an issue for you? DNS? Proxy?)")
            except:
                pass
        except Exception as e:
            _LOGGER.error("Exception in __sites_data(): %s: %s", e, traceback.format_exc())

    async def __serialise_usage(self, api_key, reset=False):
        """Serialise the usage cache file.

        Arguments:
            api_key (str): An individual Solcast account API key.
            reset (bool): Whether to reset API key usage to zero.
        """
        serialise = True
        try:
            json_file = self.__get_usage_cache_filename(api_key)
            if reset:
                self._api_used_reset[api_key] = self.__get_utc_previous_midnight()
            _LOGGER.debug("Writing API usage cache file: %s", self.__redact_msg_api_key(json_file, api_key))
            json_content = {"daily_limit": self._api_limit[api_key], "daily_limit_consumed": self._api_used[api_key], "reset": self._api_used_reset[api_key]}
            payload = json.dumps(json_content, ensure_ascii=False, cls=DateTimeEncoder)
        except Exception as e:
            _LOGGER.error("Exception in __serialise_usage(): %s: %s", e, traceback.format_exc())
            serialise = False
        if serialise:
            try:
                async with self._serialise_lock:
                    async with aiofiles.open(json_file, 'w') as f:
                        await f.write(payload)
            except Exception as e:
                _LOGGER.error("Exception writing usage cache for %s: %s", self.__redact_msg_api_key(json_file, api_key), e)

    async def __sites_usage(self):
        """Load api usage cache.

        The Solcast API for hobbyists is limited in the number of API calls that are
        allowed, and usage of this quota is tracked by the integration. There is not
        currently an API call to determine limit and usage, hence this tracking.

        The limit is specified by the user in integration configuration.
        """
        try:
            if not self.sites_loaded:
                _LOGGER.error("Internal error. Sites must be loaded before __sites_usage() is called")
                return

            sp = self.options.api_key.split(",")
            qt = self.options.api_quota.split(",")
            try:
                for i in range(len(sp)): # If only one quota value is present, yet there are multiple sites then use the same quota.
                    if len(qt) < i+1:
                        qt.append(qt[i-1])
                quota = { sp[i].strip(): int(qt[i].strip()) for i in range(len(qt)) }
            except Exception as e:
                _LOGGER.error("Exception in __sites_usage(): %s", e)
                _LOGGER.warning("Could not interpret API limit configuration string (%s), using default of 10", self.options.api_quota)
                quota = {s: 10 for s in sp}

            earliest_reset = self.__get_utc_previous_midnight()
            for spl in sp:
                api_key = spl.strip()
                cache_filename = self.__get_usage_cache_filename(api_key)
                _LOGGER.debug("%s for %s", "Usage cache " + ("exists" if file_exists(cache_filename) else "does not yet exist"), self.__redact_api_key(api_key))
                cache = True
                if file_exists(cache_filename):
                    async with aiofiles.open(cache_filename) as f:
                        try:
                            usage = json.loads(await f.read(), cls=JSONDecoder)
                        except json.decoder.JSONDecodeError:
                            _LOGGER.error("The usage cache for %s is corrupt, re-creating cache with zero usage", self.__redact_api_key(api_key))
                            cache = False
                        except Exception as e:
                            _LOGGER.error("Load usage cache exception %s for %s, re-creating cache with zero usage", e, self.__redact_api_key(api_key))
                            cache = False
                    if cache:
                        self._api_limit[api_key] = usage.get("daily_limit", 10)
                        self._api_used[api_key] = usage.get("daily_limit_consumed", 0)
                        self._api_used_reset[api_key] = usage.get("reset", self.__get_utc_previous_midnight())
                        _LOGGER.debug("Usage cache for %s last reset %s", self.__redact_api_key(api_key), self._api_used_reset[api_key].astimezone(self._tz).strftime(DATE_FORMAT))
                        if self._api_used_reset[api_key] < earliest_reset:
                            earliest_reset = self._api_used_reset[api_key]
                        if usage['daily_limit'] != quota[api_key]: # Limit has been adjusted, so rewrite the cache.
                            self._api_limit[api_key] = quota[api_key]
                            await self.__serialise_usage(api_key)
                            _LOGGER.info("Usage loaded and cache updated with new limit")
                        else:
                            if not self.previously_loaded:
                                _LOGGER.info("Usage loaded%s", (" for " + self.__redact_api_key(api_key)) if self.__is_multi_key() else "")
                        if self._api_used_reset[api_key] is not None and self.__get_real_now_utc() > self._api_used_reset[api_key] + timedelta(hours=24):
                            _LOGGER.warning("Resetting usage for %s, last reset was more than 24-hours ago", self.__redact_api_key(api_key))
                            self._api_used[api_key] = 0
                            await self.__serialise_usage(api_key, reset=True)
                else:
                    cache = False
                if not cache:
                    _LOGGER.warning("Creating usage cache for %s, assuming zero API used", self.__redact_api_key(api_key))
                    self._api_limit[api_key] = quota[api_key]
                    self._api_used[api_key] = 0
                    await self.__serialise_usage(api_key, reset=True)
                _LOGGER.debug("API counter for %s is %d/%d", self.__redact_api_key(api_key), self._api_used[api_key], self._api_limit[api_key])
            # Check for last reset disagreement
            for spl in sp:
                api_key = spl.strip()
                if self._api_used_reset[api_key] > earliest_reset:
                    _LOGGER.warning("Disagreement in earliest reset time for API keys, so aligning")
                    self._api_used_reset[api_key] = earliest_reset
                    await self.__serialise_usage(api_key)

        except Exception as e:
            _LOGGER.error("Exception in __sites_usage(): %s: %s", e, traceback.format_exc())

    async def reset_usage_cache(self):
        """Reset all usage caches"""
        sp = self.options.api_key.split(",")
        for spl in sp:
            api_key = spl.strip()
            self._api_used[api_key] = 0
            await self.__serialise_usage(api_key, reset=True)

    async def get_sites_and_usage(self):
        """Get the sites and usage, and validate API key changes against the cache files in use.

        Both the sites and usage are gathered here.
        
        Additionally, transitions from a multi-API key set up to a single API key are
        tracked at startup, and necessary adjustments are made to file naming.

        Single key installations have cache files named like `solcast-sites.json`, while
        multi-key installations have caches named `solcast-sites-thepiakeyappended.json`

        The reason is that sites are loaded in groups of API key, and similarly for API
        usage, so these must be cached separately.
        """

        def cleanup(file1, file2):
            """Rename files and remove orphans as required when transitioning.

            Arguments:
                file1, file2 (str): Two files to be checked for existence. The order is significant,
                with file1 either being renamed, should file2 not exist), or otherwise be removed.
            """
            if file_exists(file1) and not file_exists(file2):
                _LOGGER.info("Renaming %s to %s", self.__redact_msg_api_key(file1, sp[0]), self.__redact_msg_api_key(file2, sp[0]))
                os.rename(file1, file2)
            if file_exists(file1) and file_exists(file2):
                _LOGGER.warning("Removing orphaned %s", self.__redact_msg_api_key(file1, sp[0]))
                os.remove(file1)

        def remove_orphans(all_a, multi_a):
            """Remove entirely orphaned cache files for API keys.

            If a cache filename present in all_a does not exist in multi_a then it is considered
            orphaned, and will be cleaned up.

            Arguments:
                all_a (list): All cache files that exist.
                multi_a (list): The currently configured caches.
            """
            for s in all_a:
                if s not in multi_a:
                    red = re.match('(.+-)(.+)([0-9a-zA-Z]{6}.json)', s)
                    _LOGGER.warning("Removing orphaned %s", red.group(1)+"******"+red.group(3))
                    os.remove(s)

        try:
            sp = [s.strip() for s in self.options.api_key.split(",")]
            simple_sites = f"{self._config_dir}/solcast-sites.json"
            simple_usage = f"{self._config_dir}/solcast-usage.json"
            multi_sites = [f"{self._config_dir}/solcast-sites-{s}.json" for s in sp]
            multi_usage = [f"{self._config_dir}/solcast-usage-{s}.json" for s in sp]
            if self.__is_multi_key():
                cleanup(simple_sites, multi_sites[0])
                cleanup(simple_usage, multi_usage[0])
            else:
                cleanup(multi_sites[0], simple_sites)
                cleanup(multi_usage[0], simple_usage)
            def list_files() -> Tuple[list[str], list[str]]:
                all_sites = [str(s) for s in Path("/config").glob("solcast-sites-*.json")]
                all_usage = [str(s) for s in Path("/config").glob("solcast-usage-*.json")]
                return all_sites, all_usage
            all_sites, all_usage = await self.hass.async_add_executor_job(list_files)
            remove_orphans(all_sites, multi_sites)
            remove_orphans(all_usage, multi_usage)
        except:
            _LOGGER.debug(traceback.format_exc())

        self.tasks['sites_load'] = asyncio.create_task(self.__sites_data())
        await self.tasks['sites_load']
        if self.tasks.get('sites_load') is not None:
            self.tasks.pop('sites_load')
        if self.sites_loaded:
            await self.__sites_usage()

    async def reset_api_usage(self):
        """Reset the daily API usage counter."""
        _LOGGER.debug("Reset API usage")
        for api_key, _ in self._api_used.items():
            self._api_used[api_key] = 0
            await self.__serialise_usage(api_key, reset=True)

    def __valid_granular_dampening(self) -> bool:
        """Verify that the in-memory granular dampening is going to work (already checked elsewhere for 24/48 length).

        Returns:
            bool: True for a valid configuration.
        """
        if self.granular_dampening:
            first_site_len = 0
            for _, damp_list in self.granular_dampening.items():
                if first_site_len == 0:
                    first_site_len = len(damp_list)
                else:
                    if len(damp_list) != first_site_len:
                        _LOGGER.warning("Number of dampening factors for all sites must be the same, dampening will be ignored until this is resolved")
                        return False
            return True
        else:
            return True

    async def serialise_granular_dampening(self):
        """Serialise the site dampening file.

        See comment in __serialise_data.
        """
        serialise = True
        try:
            json_file = self.__get_granular_dampening_filename()
            if self.__valid_granular_dampening():
                _LOGGER.debug("Writing granular dampening file: %s", json_file)
                payload = json.dumps(self.granular_dampening, ensure_ascii=False, cls=NoIndentEncoder, indent=2)
            else:
                _LOGGER.warning("Not writing granular dampening file: %s", json_file)
                serialise = False
        except Exception as e:
            _LOGGER.error("Exception in serialise_granular_dampening(): %s: %s", e, traceback.format_exc())
            serialise = False
        if serialise:
            try:
                async with self._serialise_lock:
                    async with aiofiles.open(json_file, 'w') as f:
                        await f.write(payload)
                self._granular_dampening_mtime = os.path.getmtime(json_file)
            except Exception as e:
                _LOGGER.error("Exception writing site dampening for %s: %s", json_file, e)
            finally:
                _LOGGER.debug("Granular dampening file mtime: %s", dt.fromtimestamp(self._granular_dampening_mtime, self._tz).strftime(DATE_FORMAT))

    async def __migrate_granular_dampening(self) -> bool:
        """Migrate from legacy per-site dampening to granular dampening.

        Returns:
            bool: Per-site dampening legacy file upgraded.
        """
        try:
            legacy_file = self.__get_granular_dampening_filename(legacy=True)
            if file_exists(legacy_file):
                ex = False
                try:
                    _LOGGER.info("Migrating legacy per-site dampening to granular")
                    async with aiofiles.open(legacy_file) as f:
                        resp_json = json.loads(await f.read())
                        self.granular_dampening = cast(dict, resp_json)
                    for site, damp_dict in self.granular_dampening.items():
                        self.granular_dampening[site] = [damp_dict[f"{hour}"] for hour in range(0,24)]
                    if self.granular_dampening:
                        _LOGGER.debug("Granular dampening: %s", str(self.granular_dampening))
                    os.remove(legacy_file)
                except Exception as e:
                    _LOGGER.error("Exception in __migrate_granular_dampening(): %s: %s", e, traceback.format_exc())
                    ex = True
                if not ex:
                    await self.serialise_granular_dampening()
                    return True
        except Exception as e:
            _LOGGER.error("Exception in __migrate_granular_dampening(): %s: %s", e, traceback.format_exc())
            ex = True
        return False

    async def granular_dampening_data(self, info_suppression=False) -> bool:
        """Read the current granular dampening file.

        Arguments:
            info_suppression (bool): Suppress the output of INFO level log messages

        Returns:
            bool: Granular dampening in use.
        """
        if await self.__migrate_granular_dampening():
            return True

        def option(enable: bool, set_allow_reset: bool = False):
            site_damp = self.entry_options.get(SITE_DAMP, False) if self.entry_options.get(SITE_DAMP) is not None else False
            if enable ^ site_damp:
                self.entry_options[SITE_DAMP] = enable
                if set_allow_reset:
                    self._granular_allow_reset = enable
                self.hass.config_entries.async_update_entry(self.entry, options=self.entry_options)
            return enable

        ex = False
        try:
            json_file = self.__get_granular_dampening_filename()
            if not file_exists(json_file):
                self.granular_dampening = {}
                self._granular_dampening_mtime = 0
                return option(GRANULAR_DAMPENING_OFF)
            else:
                try:
                    async with aiofiles.open(json_file) as f:
                        resp_json = json.loads(await f.read())
                        self.granular_dampening = cast(dict, resp_json)
                        if self.granular_dampening:
                            err = False
                            first_site_len = 0
                            for site, damp_list in self.granular_dampening.items():
                                if first_site_len == 0:
                                    first_site_len = len(damp_list)
                                else:
                                    if len(damp_list) != first_site_len:
                                        _LOGGER.error("Number of dampening factors for all sites must be the same in %s, dampening ignored", json_file)
                                        self.granular_dampening = {}
                                        return option(GRANULAR_DAMPENING_OFF, SET_ALLOW_RESET)
                                if len(damp_list) not in (24, 48):
                                    _LOGGER.error("Number of dampening factors for site %s must be 24 or 48 in %s, dampening ignored", site, json_file)
                                    err = True
                            if err:
                                self.granular_dampening = {}
                                return option(GRANULAR_DAMPENING_OFF, SET_ALLOW_RESET)
                            _LOGGER.debug("Granular dampening: %s", str(self.granular_dampening))
                            _LOGGER.debug("Valid granular dampening: %s", self.__valid_granular_dampening())
                            return option(GRANULAR_DAMPENING_ON, SET_ALLOW_RESET)
                        else:
                            _LOGGER.debug("Using legacy hourly dampening")
                            return option(GRANULAR_DAMPENING_OFF, SET_ALLOW_RESET)
                except:
                    raise
                finally:
                    self._granular_dampening_mtime = os.path.getmtime(json_file)
        except Exception as e:
            _LOGGER.error("Exception in granular_dampening_data(): %s: %s", e, traceback.format_exc())
            ex = True
            return option(GRANULAR_DAMPENING_OFF)
        finally:
            if not self.previously_loaded and not ex:
                if len(self.granular_dampening) > 0 and not info_suppression:
                    _LOGGER.info("Granular dampening loaded")
                    _LOGGER.debug("Granular dampening file mtime: %s", dt.fromtimestamp(self._granular_dampening_mtime, self._tz).strftime(DATE_FORMAT))

    async def refresh_granular_dampening_data(self):
        """Loads granular dampening data if the file has changed."""
        try:
            if file_exists(self.__get_granular_dampening_filename()):
                mtime = os.path.getmtime(self.__get_granular_dampening_filename())
                if mtime != self._granular_dampening_mtime:
                    await self.granular_dampening_data(info_suppression=True)
                    _LOGGER.info("Granular dampening reloaded")
                    _LOGGER.debug("Granular dampening file mtime: %s", dt.fromtimestamp(mtime, self._tz).strftime(DATE_FORMAT))
        except Exception as e:
            _LOGGER.error("Exception in refresh_granular_dampening_data(): %s: %s", e, traceback.format_exc())

    def allow_granular_dampening_reset(self):
        """Allow options change to reset the granular dampening file to an empty dictionary."""
        return self._granular_allow_reset

    async def get_dampening(self, site: str) -> list:
        """Retrieve the currently set dampening factors.

        Arguments:
            site (str): An optional site.

        Returns:
            (list): The service call response for the presently set dampening factors.
        """
        try:
            if self.entry_options.get(SITE_DAMP):
                if not site:
                    sites = [s['resource_id'] for s in self.sites]
                else:
                    sites = [site]
                all_set = self.granular_dampening.get('all') is not None
                if site:
                    if not all_set:
                        if site in self.granular_dampening.keys():
                            return [{'site': s, 'damp_factor': ','.join(str(f) for f in self.granular_dampening[s])} for s in sites if self.granular_dampening.get(s)]
                        else:
                            raise ServiceValidationError(
                                translation_domain=DOMAIN,
                                translation_key="damp_not_for_site",
                                translation_placeholders={"site": site}
                            )
                    else:
                        if site != 'all':
                            if site in self.granular_dampening.keys():
                                _LOGGER.warning("There is dampening for site %s, but it is being overriden by an all sites entry, returning the 'all' entries instead", site)
                            else:
                                _LOGGER.warning("There is no dampening set for site %s, but it is being overriden by an all sites entry, returning the 'all' entries instead", site)
                        return [{'site': 'all', 'damp_factor': ','.join(str(f) for f in self.granular_dampening['all'])}]
                else:
                    if all_set:
                        return [{'site': 'all', 'damp_factor': ','.join(str(f) for f in self.granular_dampening['all'])}]
                    else:
                        return [{'site': s, 'damp_factor': ','.join(str(f) for f in self.granular_dampening[s])} for s in sites if self.granular_dampening.get(s)]
            else:
                if not site or site == 'all':
                    return [{'site': 'all', 'damp_factor': ','.join(str(f) for _, f in self.damp.items())}]
                else:
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key="damp_use_all",
                        translation_placeholders={"site": site}
                    )
        except Exception as e:
            if not isinstance(e, ServiceValidationError):
                _LOGGER.error("Exception in get_dampening(): %s: %s", e, traceback.format_exc())
            else:
                raise e

    '''
    async def get_weather(self):
        """Request site weather byline."""

        try:
            if len(self.sites) > 0:
                sp = self.options.api_key.split(",")
                rid = self.sites[0].get("resource_id", None)
                url=f"{self.options.host}/json/reply/GetRooftopSiteSparklines"
                params = {"resourceId": rid, "api_key": sp[0]}
                _LOGGER.debug("Get weather byline")
                async with async_timeout.timeout(60):
                    resp: ClientResponse = await self._aiohttp_session.get(url=url, params=params, headers=self.headers, ssl=False)
                    resp_json = await resp.json(content_type=None)
                    status = resp.status

                if status == 200:
                    d = cast(dict, resp_json)
                    _LOGGER.debug("Returned data in get_weather(): %s", str(d))
                    self._weather = d.get("forecast_descriptor", None).get("description", None)
                    _LOGGER.debug("Weather description: %s", self._weather)
                else:
                    raise Exception(f"Gathering weather description failed. request returned: {translate(status)} - Response: {resp_json}.")

        except json.decoder.JSONDecodeError:
            _LOGGER.error("JSONDecodeError in get_weather(): Solcast could be having problems")
        except ConnectionRefusedError as e:
            _LOGGER.error("Error in get_weather(): %s", e)
        except ClientConnectionError as e:
            _LOGGER.error("Connection error in get_weather(): %s", e)
        except asyncio.TimeoutError:
            _LOGGER.error("Connection error in get_weather(): Timed out connecting to solcast")
        except Exception as e:
            _LOGGER.error("Error in get_weather(): %s", traceback.format_exc())
    '''

    async def load_saved_data(self) -> str:
        """Load the saved solcast.json data.

        This also checks for new API keys and site removal.

        Returns:
            str: A failure status message, or an empty string.
        """
        try:
            status = ''
            if len(self.sites) > 0:

                async def load_data(filename, set_loaded=True) -> dict:
                    if file_exists(filename):
                        async with aiofiles.open(filename) as data_file:
                            json_data = json.loads(await data_file.read(), cls=JSONDecoder)
                            json_version = json_data.get("version", 1)
                            #self._weather = json_data.get("weather", "unknown")
                            _LOGGER.debug("Data cache %s exists, file type is %s", filename, type(json_data))
                            data = json_data
                            if json_version != JSON_VERSION:
                                _LOGGER.warning("%s version is not latest (%d vs. %d), upgrading", filename, json_version, JSON_VERSION)
                                # Future: If the file structure changes then upgrade it
                                if json_version < 4:
                                    data['version'] = 4
                                    json_version = 4
                                    await self.__serialise_data(data, filename)
                                #if json_version < 5:
                                #    upgrade in future...
                                #    data['version'] = 5
                                #    json_version = 5
                                #    await self.__serialise_data(data, filename)
                            if set_loaded:
                                self._loaded_data = True
                        if not self.previously_loaded:
                            _LOGGER.info("%s data loaded", "Dampened" if filename == self._filename else "Undampened")
                        return data
                    else:
                        return None

                async def adds_moves_changes():
                    # Check for any new API keys so no sites data yet for those, and for API key change.
                    # Users having multiple API keys where one key changes will have all usage reset.
                    serialise = False
                    reset_usage = False
                    new_sites = {}
                    try:
                        cache_sites = list(self._data['siteinfo'].keys())
                        old_api_keys = self.hass.data[DOMAIN].get('old_api_key', self.hass.data[DOMAIN]['entry_options'].get(CONF_API_KEY, '')).split(',')
                        for d in self.sites:
                            site = d['resource_id']
                            api_key = d['apikey']
                            if site not in cache_sites:
                                new_sites[site] = api_key
                            else:
                                if len(self._data['siteinfo'][site].get('forecasts', [])) == 0: # Empty forecast data.
                                    new_sites[site] = api_key
                            if api_key not in old_api_keys: # If a new site is seen in conjunction with an API key change then reset the usage.
                                reset_usage = True
                    except Exception  as e:
                        raise f"Exception while adding new sites: {e}"
                    try:
                        del self.hass.data[DOMAIN]['old_api_key']
                    except:
                        pass

                    if reset_usage:
                        _LOGGER.info("An API key has changed, resetting usage")
                        await self.reset_api_usage()

                    if len(new_sites.keys()) > 0:
                        # Some site data does not exist yet so get it.
                        _LOGGER.info("New site(s) have been added, so getting forecast data for them")
                        for site, api_key in new_sites.items():
                            await self.__http_data_call(site=site, api_key=api_key, do_past=True)

                        self._data["last_updated"] = dt.now(timezone.utc).isoformat()
                        self._data_undampened["last_updated"] = dt.now(timezone.utc).isoformat()
                        self._data["version"] = JSON_VERSION
                        self._data_undampened["version"] = JSON_VERSION
                        serialise = True

                        self._loaded_data = True

                    # Check for sites that need to be removed.
                    remove_sites = []
                    try:
                        configured_sites = [s['resource_id'] for s in self.sites]
                        for s in cache_sites:
                            if s not in configured_sites:
                                _LOGGER.warning("Site resource id %s is no longer configured, will remove saved data from cached files %s, %s", s, self._filename, self._filename_undampened)
                                remove_sites.append(s)
                    except Exception  as e:
                        raise f"Exception while determining stale sites for {self._filename}, {self._filename_undampened}: {e}"

                    for site in remove_sites:
                        try:
                            del self._data['siteinfo'][site]
                            del self._data_undampened['siteinfo'][site] # May not yet exist.
                        except:
                            pass
                    if len(remove_sites) > 0:
                        serialise = True

                    if serialise:
                        await self.__serialise_data(self._data, self._filename)
                        await self.__serialise_data(self._data_undampened, self._filename_undampened)

                dampened_data = await load_data(self._filename)
                if dampened_data:
                    self._data = dampened_data
                    # Load the undampened history
                    undampened_data = await load_data(self._filename_undampened, set_loaded=False)
                    if undampened_data:
                        self._data_undampened = undampened_data
                    # Migrate undampened history data to the undampened cache if needed.
                    await self.__migrate_undampened_history()
                    # Check for sites changes.
                    await adds_moves_changes()

                if not self._loaded_data:
                    # No file to load.
                    _LOGGER.warning("There is no solcast.json to load, so fetching solar forecast, including past forecasts")
                    # Could be a brand new install of the integation, or the file has been removed. Poll once now...
                    status = await self.get_forecast_update(do_past=True)
                else:
                    # Create an up to date forecast.
                    await self.build_forecast_data()
            else:
                _LOGGER.error("Site count is zero in load_saved_data(); the get sites must have failed, and there is no sites cache")
                status = 'Site count is zero, add sites'
        except json.decoder.JSONDecodeError:
            _LOGGER.error("The cached data in solcast.json is corrupt in load_saved_data()")
            status = 'The cached data in /config/solcast.json is corrupted, suggest removing or repairing it'
        except Exception as e:
            _LOGGER.error("Exception in load_saved_data(): %s", traceback.format_exc())
            status = f"Exception in load_saved_data(): {e}"
        return status

    async def delete_solcast_file(self, *args): # pylint: disable=W0613
        """Service event to delete the solcast.json file.

        Note: This will immediately trigger a forecast get with history, so this should
        really be called an integration reset.

        Arguments:
            args (tuple): Not used.
        """
        _LOGGER.debug("Service event to delete old solcast.json file")
        try:
            if file_exists(self._filename_undampened):
                os.remove(self._filename_undampened)
            else:
                _LOGGER.warning("There is no solcast-undampened.json to delete")
            if file_exists(self._filename):
                os.remove(self._filename)
            else:
                _LOGGER.warning("There is no solcast.json to delete")
                return
            await self.get_sites_and_usage()
            await self.load_saved_data()
        except Exception:
            _LOGGER.error("Service event to delete old solcast.json file failed")

    async def get_forecast_list(self, *args) -> Optional[Tuple[Dict[Any], ...]]:
        """Service event to get forecasts.

        Arguments:
            args (tuple): [0] (dt) = from timestamp, [1] (dt) = to timestamp, [2] = site, [3] (bool) = dampened or undampened.

        Returns:
            tuple(dict, ...): Forecasts representing the range specified.
        """
        try:
            st_time = time.time()

            if args[2] == 'all':
                data_forecasts = self._data_forecasts if not args[3] else self._data_forecasts_undampened
            else:
                data_forecasts = self._site_data_forecasts[args[2]] if not args[3] else self._site_data_forecasts_undampened[args[2]]
            st_i, end_i = self.__get_forecast_list_slice(data_forecasts, args[0], args[1], search_past=True)
            h = data_forecasts[st_i:end_i]

            if SENSOR_DEBUG_LOGGING: _LOGGER.debug(
                "Get forecast list: (%ss) st %s end %s st_i %d end_i %d h.len %d site %s undamp %s",
                round(time.time()-st_time,4), args[0].strftime(DATE_FORMAT_UTC), args[1].strftime(DATE_FORMAT_UTC), st_i, end_i, len(h), args[2], args[3]
            )

            return tuple( {**d, "period_start": d["period_start"].astimezone(self._tz)} for d in h )

        except Exception:
            _LOGGER.error("Service event to get list of forecasts failed")
            return None

    def get_api_used_count(self) -> int:
        """Return API polling count for this UTC 24hr period (minimum of all API keys).

        A minimum is used because forecasts are polled at the same time for each configured API key. Should
        one API key fail but the other succeed then usage will be misaligned, so the lowest usage of all
        API keys will apply.

        Returns:
            int: The tracked API usage count.
        """
        return min(list(self._api_used.values()))

    def get_api_limit(self) -> int:
        """Return API polling limit for this UTC 24hr period (minimum of all API keys).

        A minimum is used because forecasts are polled at the same time, so even if one API key has a
        higher limit that limit will never be reached.

        Returns:
            int: The lowest API limit of all configured API keys.
        """
        return min(list(self._api_limit.values()))

    # def get_weather_description(self):
    #     """Return weather description."""
    #     return self._weather

    def get_last_updated_datetime(self) -> dt:
        """Return when the data was last updated.

        Returns:
            datetime: The last successful forecast fetch.
        """
        return dt.fromisoformat(self._data["last_updated"])

    def get_rooftop_site_total_today(self, site) -> float:
        """Return total kW for today for a site.

        Arguments:
            site (str): A Solcast site ID.

        Returns:
            float: Total site kW forecast today.
        """
        if self._tally.get(site) is None:
            _LOGGER.warning("Site total kW forecast today is currently unavailable for %s", site)
        return self._tally.get(site)

    def get_rooftop_site_extra_data(self, site="") -> Dict[str, Any]:
        """Return information about a site.

        Arguments:
            site (str): An Optional Solcast site ID.

        Returns:
            dict: Site attributes that have been configured at solcast.com.
        """
        g = tuple(d for d in self.sites if d["resource_id"] == site)
        if len(g) != 1:
            raise ValueError(f"Unable to find site {site}")
        site: Dict[str, Any] = g[0]
        ret = {
            "name": site.get("name", None),
            "resource_id": site.get("resource_id", None),
            "capacity": site.get("capacity", None),
            "capacity_dc": site.get("capacity_dc", None),
            "longitude": site.get("longitude", None),
            "latitude": site.get("latitude", None),
            "azimuth": site.get("azimuth", None),
            "tilt": site.get("tilt", None),
            "install_date": site.get("install_date", None),
            "loss_factor": site.get("loss_factor", None)
        }
        for key in tuple(ret.keys()):
            if ret[key] is None: ret.pop(key, None)
        return ret

    def get_day_start_utc(self) -> dt:
        """Datetime helper.

        Returns:
            datetime: The UTC date and time representing midnight local time.
        """
        return dt.now(self._tz).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)

    def __get_utc_previous_midnight(self) -> dt:
        """Datetime helper.

        Returns:
            datetime: The UTC date and time representing midnight UTC of the current day.
        """
        return dt.now().astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    def get_now_utc(self) -> dt:
        """Datetime helper.

        Returns:
            datetime: The UTC date and time representing now as at the previous minute boundary.
        """
        return dt.now(self._tz).replace(second=0, microsecond=0).astimezone(timezone.utc)

    def __get_real_now_utc(self) -> dt:
        """Datetime helper.

        Returns:
            datetime: The UTC date and time representing now including seconds/microseconds.
        """
        return dt.now(self._tz).astimezone(timezone.utc)

    def __get_hour_start_utc(self) -> dt:
        """Datetime helper.

        Returns:
            datetime: The UTC date and time representing the start of the current hour.
        """
        return dt.now(self._tz).replace(minute=0, second=0, microsecond=0).astimezone(timezone.utc)

    def get_forecast_day(self, futureday) -> Dict[str, Any]:
        """Return forecast data for the Nth day ahead.

        Arguments:
            futureday (int): A day (0 = today, 1 = tomorrow, etc., with a maxiumum of day 7).

        Returns:
            dict: Includes the day name, whether there are issues with the data in terms of completeless,
            and detailed half-hourly forecast (and site breakdown if that option is configured), and a
            detailed hourly forecast (and site breakdown if that option is configured).
        """
        no_data_error = True

        def build_hourly(t) -> list[Dict[str, Any]]:
            ht = []
            for index in range(0,len(t),2):
                if len(t) > 0:
                    try:
                        x1 = round((t[index]["pv_estimate"] + t[index+1]["pv_estimate"]) / 2, 4)
                        x2 = round((t[index]["pv_estimate10"] + t[index+1]["pv_estimate10"]) / 2, 4)
                        x3 = round((t[index]["pv_estimate90"] + t[index+1]["pv_estimate90"]) / 2, 4)
                        ht.append({"period_start":t[index]["period_start"], "pv_estimate":x1, "pv_estimate10":x2, "pv_estimate90":x3})
                    except IndexError:
                        x1 = round((t[index]["pv_estimate"]), 4)
                        x2 = round((t[index]["pv_estimate10"]), 4)
                        x3 = round((t[index]["pv_estimate90"]), 4)
                        ht.append({"period_start":t[index]["period_start"], "pv_estimate":x1, "pv_estimate10":x2, "pv_estimate90":x3})
                    except Exception as e:
                        _LOGGER.error("Exception in get_forecast_day(): %s: %s", e, traceback.format_exc())
            return ht

        start_utc = self.get_day_start_utc() + timedelta(days=futureday)
        end_utc = start_utc + timedelta(days=1)
        st_i, end_i = self.__get_forecast_list_slice(self._data_forecasts, start_utc, end_utc)
        h = self._data_forecasts[st_i:end_i]
        if self.options.attr_brk_halfhourly:
            if self.options.attr_brk_site_detailed:
                hs = {}
                for site in self.sites:
                    hs[site['resource_id']] = self._site_data_forecasts[site['resource_id']][st_i:end_i]

        if SENSOR_DEBUG_LOGGING: _LOGGER.debug(
            "Get forecast day: %d st %s end %s st_i %d end_i %d h.len %d",
            futureday,
            start_utc.strftime(DATE_FORMAT_UTC), end_utc.strftime(DATE_FORMAT_UTC),
            st_i, end_i, len(h)
        )

        tup = tuple( {**d, "period_start": d["period_start"].astimezone(self._tz)} for d in h )
        if self.options.attr_brk_halfhourly:
            if self.options.attr_brk_site_detailed:
                tups = {}
                for site in self.sites:
                    tups[site['resource_id']] = tuple( {**d, "period_start": d["period_start"].astimezone(self._tz)} for d in hs[site['resource_id']] )

        if len(tup) < 48:
            no_data_error = False

        if self.options.attr_brk_hourly:
            hourlytup = build_hourly(tup)
            if self.options.attr_brk_site_detailed:
                hourlytups = {}
                for site in self.sites:
                    hourlytups[site['resource_id']] = build_hourly(tups[site['resource_id']])

        res = {
            "dayname": start_utc.astimezone(self._tz).strftime("%A"),
            "dataCorrect": no_data_error,
        }
        if self.options.attr_brk_halfhourly:
            res["detailedForecast"] = tup
            if self.options.attr_brk_site_detailed:
                for site in self.sites:
                    res[f"detailedForecast-{site['resource_id']}"] = tups[site['resource_id']]
        if self.options.attr_brk_hourly:
            res["detailedHourly"] = hourlytup
            if self.options.attr_brk_site_detailed:
                for site in self.sites:
                    res[f"detailedHourly-{site['resource_id']}"] = hourlytups[site['resource_id']]
        return res

    def get_forecast_n_hour(self, n_hour, site=None, _use_data_field=None) -> int:
        """Return forecast for the Nth hour.

        Arguments:
            n_hour (int): An hour into the future, or the current hour (0 = current and 1 = next hour are used).
            site (str): An optional Solcast site ID, used to build site breakdown attributes (used).
            _used_data_field (str): An optional forecast type, used to select the pv_forecast, pv_forecast10 or pv_forecast90 returned.

        Returns:
            int - A forecast for an hour period as Wh (either used for a sensor or its attributes).
        """
        start_utc = self.__get_hour_start_utc() + timedelta(hours=n_hour)
        end_utc = start_utc + timedelta(hours=1)
        res = round(500 * self.__get_forecast_pv_estimates(start_utc, end_utc, site=site, _use_data_field=_use_data_field))
        return res

    def get_forecasts_n_hour(self, n_hour) -> Dict[str, Any]:
        """Return forecast for the Nth hour for all sites and individual sites.

        Arguments:
            n_hour (int): An hour into the future, or the current hour (0 = current and 1 = next hour are used).

        Returns:
            dict: Sensor attributes for an hour period, depending on the configured options.
        """
        res = {}
        if self.options.attr_brk_site:
            for site in self.sites:
                res[site['resource_id']] = self.get_forecast_n_hour(n_hour, site=site['resource_id'])
                for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
                    if self.estimate_set.get(_data_field):
                        res[_data_field.replace('pv_','')+'-'+site['resource_id']] = self.get_forecast_n_hour(n_hour, site=site['resource_id'], _use_data_field=_data_field)
        for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
            if self.estimate_set.get(_data_field):
                res[_data_field.replace('pv_','')] = self.get_forecast_n_hour(n_hour, _use_data_field=_data_field)
        return res

    def get_forecast_custom_hours(self, n_hours, site=None, _use_data_field=None) -> int:
        """Return forecast for the next N hours.

        Arguments:
            n_hours (int): A number of hours into the future.
            site (str): An optional Solcast site ID, used to build site breakdown attributes.
            _used_data_field (str): A optional forecast type, used to select the pv_forecast, pv_forecast10 or pv_forecast90 returned.

        Returns:
            int - A forecast for a multiple hour period as Wh (either used for a sensor or its attributes).
        """
        start_utc = self.get_now_utc()
        end_utc = start_utc + timedelta(hours=n_hours)
        res = round(1000 * self.__get_forecast_pv_remaining(start_utc, end_utc=end_utc, site=site, _use_data_field=_use_data_field))
        return res

    def get_forecasts_custom_hours(self, n_hours) -> Dict[str, Any]:
        """Return forecast for the next N hours for all sites and individual sites.

        Arguments:
            n_hours (int): A configured number of hours into the future.

        Returns:
            dict: Sensor attributes for a multiple hour period, depending on the configured options.
        """
        res = {}
        if self.options.attr_brk_site:
            for site in self.sites:
                res[site['resource_id']] = self.get_forecast_custom_hours(n_hours, site=site['resource_id'])
                for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
                    if self.estimate_set.get(_data_field):
                        res[_data_field.replace('pv_','')+'-'+site['resource_id']] = self.get_forecast_custom_hours(n_hours, site=site['resource_id'], _use_data_field=_data_field)
        for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
            if self.estimate_set.get(_data_field):
                res[_data_field.replace('pv_','')] = self.get_forecast_custom_hours(n_hours, _use_data_field=_data_field)
        return res

    def get_power_n_mins(self, n_mins, site=None, _use_data_field=None) -> int:
        """Return expected power generation in the next N minutes.

        Arguments:
            n_mins (int): A number of minutes into the future.
            site (str): An optional Solcast site ID, used to build site breakdown attributes.
            _used_data_field (str): A optional forecast type, used to select the pv_forecast, pv_forecast10 or pv_forecast90 returned.

        Returns:
            int: A power forecast in N minutes as W (either used for a sensor or its attributes).
        """
        time_utc = self.get_now_utc() + timedelta(minutes=n_mins)
        return round(1000 * self.__get_forecast_pv_moment(time_utc, site=site, _use_data_field=_use_data_field))

    def get_sites_power_n_mins(self, n_mins) -> Dict[str, Any]:
        """Return expected power generation in the next N minutes for all sites and individual sites.

        Arguments:
            n_mins (int): A number of minutes into the future.

        Returns:
            dict: Sensor attributes containing a forecast in N minutes, depending on the configured options.
        """
        res = {}
        if self.options.attr_brk_site:
            for site in self.sites:
                res[site['resource_id']] = self.get_power_n_mins(n_mins, site=site['resource_id'])
                for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
                    if self.estimate_set.get(_data_field):
                        res[_data_field.replace('pv_','')+'-'+site['resource_id']] = self.get_power_n_mins(n_mins, site=site['resource_id'], _use_data_field=_data_field)
        for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
            if self.estimate_set.get(_data_field):
                res[_data_field.replace('pv_','')] = self.get_power_n_mins(n_mins, site=None, _use_data_field=_data_field)
        return res

    def get_peak_w_day(self, n_day, site=None, _use_data_field=None) -> int:
        """Return maximum forecast Watts for N days ahead.

        Arguments:
            n_day (int): A number representing a day (0 = today, 1 = tomorrow, etc., with a maxiumum of day 7).
            site (str): An optional Solcast site ID, used to build site breakdown attributes (used).
            _used_data_field (str): A optional forecast type, used to select the pv_forecast, pv_forecast10 or pv_forecast90 returned.

        Returns:
            int: An expected peak generation for a given day as Watts.
        """
        _data_field = self._use_data_field if _use_data_field is None else _use_data_field
        start_utc = self.get_day_start_utc() + timedelta(days=n_day)
        end_utc = start_utc + timedelta(days=1)
        res = self.__get_max_forecast_pv_estimate(start_utc, end_utc, site=site, _use_data_field=_data_field)
        return 0 if res is None else round(1000 * res[_data_field])

    def get_sites_peak_w_day(self, n_day) -> Dict[str, Any]:
        """Return maximum forecast Watts for N days ahead for all sites and individual sites.

        Arguments:
            n_day (int): A number representing a day (0 = today, 1 = tomorrow, etc., with a maxiumum of day 7).

        Returns:
            dict: Sensor attributes of expected peak generation values for a given day, depending on the configured options.
        """
        res = {}
        if self.options.attr_brk_site:
            for site in self.sites:
                res[site['resource_id']] = self.get_peak_w_day(n_day, site=site['resource_id'])
                for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
                    if self.estimate_set.get(_data_field):
                        res[_data_field.replace('pv_','')+'-'+site['resource_id']] = self.get_peak_w_day(n_day, site=site['resource_id'], _use_data_field=_data_field)
        for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
            if self.estimate_set.get(_data_field):
                res[_data_field.replace('pv_','')] = self.get_peak_w_day(n_day, site=None, _use_data_field=_data_field)
        return res

    def get_peak_w_time_day(self, n_day, site=None, _use_data_field=None) -> dt:
        """Return hour of max generation for site N days ahead.

        Arguments:
            n_day (int): A number representing a day (0 = today, 1 = tomorrow, etc., with a maxiumum of day 7).
            site (str): An optional Solcast site ID, used to build site breakdown attributes (used).
            _used_data_field (str): A optional forecast type, used to select the pv_forecast, pv_forecast10 or pv_forecast90 returned.

        Returns:
            datetime: The date and time of expected peak generation for a given day.
        """
        start_utc = self.get_day_start_utc() + timedelta(days=n_day)
        end_utc = start_utc + timedelta(days=1)
        res = self.__get_max_forecast_pv_estimate(start_utc, end_utc, site=site, _use_data_field=_use_data_field)
        return res if res is None else res["period_start"]

    def get_sites_peak_w_time_day(self, n_day) -> Dict[str, Any]:
        """Return hour of max generation for site N days ahead for all sites and individual sites.

        Arguments:
            n_day (int): A day (0 = today, 1 = tomorrow, etc., with a maxiumum of day 7).

        Returns:
            dict: Sensor attributes of the date and time of expected peak generation for a given day, depending on the configured options.
        """
        res = {}
        if self.options.attr_brk_site:
            for site in self.sites:
                res[site['resource_id']] = self.get_peak_w_time_day(n_day, site=site['resource_id'])
                for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
                    if self.estimate_set.get(_data_field):
                        res[_data_field.replace('pv_','')+'-'+site['resource_id']] = self.get_peak_w_time_day(n_day, site=site['resource_id'], _use_data_field=_data_field)
        for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
            if self.estimate_set.get(_data_field):
                res[_data_field.replace('pv_','')] = self.get_peak_w_time_day(n_day, site=None, _use_data_field=_data_field)
        return res

    def get_forecast_remaining_today(self, site=None, _use_data_field=None) -> float:
        """Return remaining forecasted production for today.

        Arguments:
            site (str): An optional Solcast site ID, used to build site breakdown attributes (used).
            _used_data_field (str): A optional forecast type, used to select the pv_forecast, pv_forecast10 or pv_forecast90 returned.

        Returns:
            float: The expected remaining solar generation for the current day as kWh.
        """
        start_utc = self.get_now_utc()
        end_utc = self.get_day_start_utc() + timedelta(days=1)
        res = round(self.__get_forecast_pv_remaining(start_utc, end_utc=end_utc, site=site, _use_data_field=_use_data_field), 4)
        return res

    def get_forecasts_remaining_today(self) -> Dict[str, Any]:
        """Return remaining forecasted production for today for all sites and individual sites.

        Returns:
            dict: Sensor attributes containing the expected remaining solar generation for the current day, depending on the configured options.
        """
        res = {}
        if self.options.attr_brk_site:
            for site in self.sites:
                res[site['resource_id']] = self.get_forecast_remaining_today(site=site['resource_id'])
                for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
                    if self.estimate_set.get(_data_field):
                        res[_data_field.replace('pv_','')+'-'+site['resource_id']] = self.get_forecast_remaining_today(site=site['resource_id'], _use_data_field=_data_field)
        for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
            if self.estimate_set.get(_data_field):
                res[_data_field.replace('pv_','')] = self.get_forecast_remaining_today(_use_data_field=_data_field)
        return res

    def get_total_kwh_forecast_day(self, n_day, site=None, _use_data_field=None) -> float:
        """Return forecast production total for N days ahead.

        Arguments:
            n_day (int): A day (0 = today, 1 = tomorrow, etc., with a maxiumum of day 7).
            site (str): An optional Solcast site ID, used to build site breakdown attributes (used).
            _used_data_field (str): A optional forecast type, used to select the pv_forecast, pv_forecast10 or pv_forecast90 returned.

        Returns:
            float: The forecast total solar generation for a given day as kWh.
        """
        start_utc = self.get_day_start_utc() + timedelta(days=n_day)
        end_utc = start_utc + timedelta(days=1)
        res = round(0.5 * self.__get_forecast_pv_estimates(start_utc, end_utc, site=site, _use_data_field=_use_data_field), 4)
        return res

    def get_sites_total_kwh_forecast_day(self, n_day) -> Dict[str, Any]:
        """Return forecast production total for N days ahead for all sites and individual sites.

        Arguments:
            n_day (int): A day (0 = today, 1 = tomorrow, etc., with a maxiumum of day 7).

        Returns:
            dict: Sensor attributes containing the forecast total solar generation for a given day, depending on the configured options.
        """
        res = {}
        if self.options.attr_brk_site:
            for site in self.sites:
                res[site['resource_id']] = self.get_total_kwh_forecast_day(n_day, site=site['resource_id'])
                for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
                    if self.estimate_set.get(_data_field):
                        res[_data_field.replace('pv_','')+'-'+site['resource_id']] = self.get_total_kwh_forecast_day(n_day, site=site['resource_id'], _use_data_field=_data_field)
        for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
            if self.estimate_set.get(_data_field):
                res[_data_field.replace('pv_','')] = self.get_total_kwh_forecast_day(n_day, site=None, _use_data_field=_data_field)
        return res

    def __get_forecast_list_slice(self, _data, start_utc, end_utc=None, search_past=False) -> tuple[int, int]:
        """Return forecast data list slice start and end indexes for interval.

        Arguments:
            _data (list): The detailed forecast data to search, either total data or site breakdown data.
            start_utc (datetime): Start of time period requested in UTC.
            end_utc (datetime): Optional end of time period requested in UTC (if omitted, thirty minutes beyond start).
            search_past (bool): Optional flag to indicate that past periods should be searched.

        Returns:
            tuple(int, int): List index of start of period, list index of end of period.
        """
        if end_utc is None:
            end_utc = start_utc + timedelta(seconds=1800)
        crt_i = -1
        st_i = -1
        end_i = len(_data)
        _forecasts_start_idx = self.__calc_forecast_start_index(_data)
        for crt_i in range(0 if search_past else _forecasts_start_idx, end_i):
            d = _data[crt_i]
            d1 = d['period_start']
            d2 = d1 + timedelta(seconds=1800)
            # After the last segment.
            if end_utc <= d1:
                end_i = crt_i
                break
            # First segment.
            if start_utc < d2 and st_i == -1:
                st_i = crt_i
        # Never found.
        if st_i == -1:
            st_i = 0
            end_i = 0
        return st_i, end_i

    def __get_spline(self, spline, st, xx, _data, data_fields, reducing=False):
        """Build a forecast spline, momentary or day reducing.

        Arguments:
            spline (dict): The data structure to populate.
            st (int): The starting index of the data slice.
            xx (list): Seconds intervals of the day, one for each 5-minute interval (plus another hours worth).
            _data (list): The data structure used to build the spline, either total data or site breakdown data.
            data_fields (list): The forecast types to build, pv_forecast, pv_forecast10 or pv_forecast90.
            reducing (bool): A flag to indicate whether a momentary power spline should be built, or a reducing energy spline, default momentary.
        """
        for _data_field in data_fields:
            if st > 0:
                y = [_data[st+i][_data_field] for i in range(0, len(self._spline_period))]
                if reducing:
                    # Build a decreasing set of forecasted values instead.
                    y = [0.5 * sum(y[i:]) for i in range(0, len(self._spline_period))]
                spline[_data_field] = cubic_interp(xx, self._spline_period, y)
                self.__sanitise_spline(spline, _data_field, xx, y, reducing=reducing)
            else: # The list slice was not found, so zero all values in the spline.
                spline[_data_field] = [0] * (len(self._spline_period) * 6)
        if SPLINE_DEBUG_LOGGING:
            _LOGGER.debug(str(spline))

    def __sanitise_spline(self, spline, _data_field, xx, y, reducing=False):
        """Ensures that no negative values are returned, and also shifts the spline to account for half-hour average input values.

        Arguments:
            spline (dict): The data structure to sanitise.
            _data_field (str): The forecast type to sanitise, pv_forecast, pv_forecast10 or pv_forecast90.
            xx (list): Seconds intervals of the day, one for each 5-minute interval (plus another hours worth).
            y (list): The period momentary or reducing input data used for the spline calculation.
            reducing (bool): A flag to indicate whether the spline is momentary power, or reducing energy, default momentary.
        """
        for j in xx:
            i = int(j/300)
            # Suppress negative values.
            if math.copysign(1.0, spline[_data_field][i]) < 0:
                spline[_data_field][i] = 0.0
            # Suppress spline bounce.
            if reducing:
                if i+1 <= len(xx)-1 and spline[_data_field][i+1] > spline[_data_field][i]:
                    spline[_data_field][i+1] = spline[_data_field][i]
            else:
                k = int(math.floor(j/1800))
                if k+1 <= len(y)-1 and y[k] == 0 and y[k+1] == 0:
                    spline[_data_field][i] = 0.0
        # Shift right by fifteen minutes because 30-minute averages, padding as appropriate.
        if reducing:
            spline[_data_field] = ([spline[_data_field][0]]*3) + spline[_data_field]
        else:
            spline[_data_field] = ([0]*3) + spline[_data_field]

    def __build_splines(self, variant, reducing=False):
        """Build cubic splines for interpolated inter-interval momentary or reducing estimates.

        Arguments:
            variant (list): The variant variable to populate, _forecasts_moment or _forecasts_reducing.
            reducing (bool): A flag to indicate whether the spline is momentary power, or reducing energy, default momentary.
        """
        df = [self._use_data_field]
        if self._use_data_field != self.options.attr_brk_estimate:
            df.append('pv_estimate')
        if self._use_data_field != self.options.attr_brk_estimate10:
            df.append('pv_estimate10')
        if self._use_data_field != self.options.attr_brk_estimate90:
            df.append('pv_estimate90')
        xx = list(range(0, 1800*len(self._spline_period), 300))

        variant['all'] = {}
        st, _ = self.__get_forecast_list_slice(self._data_forecasts, self.get_day_start_utc()) # Get start of day index.
        self.__get_spline(variant['all'], st, xx, self._data_forecasts, df, reducing=reducing)
        if self.options.attr_brk_site:
            for site in self.sites:
                variant[site['resource_id']] = {}
                st, _ = self.__get_forecast_list_slice(self._site_data_forecasts[site['resource_id']], self.get_day_start_utc()) # Get start of day index.
                self.__get_spline(variant[site['resource_id']], st, xx, self._site_data_forecasts[site['resource_id']], df, reducing=reducing)

    async def __spline_moments(self):
        """Build the moments splines."""
        try:
            self.__build_splines(self._forecasts_moment)
        except:
            _LOGGER.error("Exception in __spline_moments(): %s", traceback.format_exc())

    async def __spline_remaining(self):
        """Build the descending splines."""
        try:
            self.__build_splines(self._forecasts_remaining, reducing=True)
        except:
            _LOGGER.error("Exception in __spline_remaining(): %s", traceback.format_exc())

    async def recalculate_splines(self):
        """Recalculate both the moment and remaining splines"""
        _LOGGER.debug("Calculating splines")
        await self.__spline_moments()
        await self.__spline_remaining()

    def __get_moment(self, site, _data_field, n_min) -> float:
        """Get a time value from a moment spline.

        n_min (int): Minute of the day.
        """
        return self._forecasts_moment['all' if site is None else site][self._use_data_field if _data_field is None else _data_field][int(n_min / 300)]

    def __get_remaining(self, site, _data_field, n_min) -> float:
        """Get a remaining value at a given five-minute point from a reducing spline.

        Arguments:
            site (str): A Solcast site ID.
            _data_field (str): The forecast type, pv_forecast, pv_forecast10 or pv_forecast90.
            n_min (int): The minute of the day.

        Returns:
            float: A splined forecasted remaining value as kWh.
        """
        return self._forecasts_remaining['all' if site is None else site][self._use_data_field if _data_field is None else _data_field][int(n_min / 300)]

    def __get_forecast_pv_remaining(self, start_utc, end_utc=None, site=None, _use_data_field=None) -> float:
        """Return estimate remaining for a period.

        The start_utc and end_utc will be adjusted to the most recent five-minute period start. Where
        end_utc is present the forecasted remining energy between the two datetime values is calculated.

        Arguments:
            start_utc (datetime): Start of time period in UTC.
            end_utc (datetime): Optional end of time period in UTC. If omitted then a result for the start_utc only is returned.
            site (str): Optional Solcast site ID, used to provide site breakdown.
            _used_data_field (str): A optional forecast type, used to select the pv_forecast, pv_forecast10 or pv_forecast90 returned.

        Returns:
            float: Energy forecast to be remaining for a period as kWh.
        """
        try:
            _data = self._data_forecasts if site is None else self._site_data_forecasts[site]
            _data_field = self._use_data_field if _use_data_field is None else _use_data_field
            start_utc = start_utc.replace(minute = math.floor(start_utc.minute / 5) * 5)
            st_i, end_i = self.__get_forecast_list_slice(_data, start_utc, end_utc) # Get start and end indexes for the requested range.
            day_start = self.get_day_start_utc()
            res = self.__get_remaining(site, _data_field, (start_utc - day_start).total_seconds())
            if end_utc is not None:
                end_utc = end_utc.replace(minute = math.floor(end_utc.minute / 5) * 5)
                if end_utc < day_start + timedelta(seconds=1800*len(self._spline_period)):
                    # End is within today so use spline data.
                    res -= self.__get_remaining(site, _data_field, (end_utc - day_start).total_seconds())
                else:
                    # End is beyond today, so revert to simple linear interpolation.
                    st_i2, _ = self.__get_forecast_list_slice(_data, day_start + timedelta(seconds=1800*len(self._spline_period))) # Get post-spline day onwards start index.
                    for d in _data[st_i2:end_i]:
                        d2 = d['period_start'] + timedelta(seconds=1800)
                        s = 1800
                        f = 0.5 * d[_data_field]
                        if end_utc < d2:
                            s -= (d2 - end_utc).total_seconds()
                            res += f * s / 1800
                        else:
                            res += f
            if SENSOR_DEBUG_LOGGING: _LOGGER.debug(
                "Get estimate: %s()%s %s st %s end %s st_i %d end_i %d res %s",
                currentFuncName(1), '' if site is None else ' '+site, _data_field,
                start_utc.strftime(DATE_FORMAT_UTC),
                end_utc.strftime(DATE_FORMAT_UTC) if end_utc is not None else None,
                st_i, end_i, round(res,4)
            )
            return res if res > 0 else 0
        except Exception as e:
            _LOGGER.error("Exception in __get_forecast_pv_remaining(): %s: %s", e, traceback.format_exc())
            raise
            #return 0

    def __get_forecast_pv_estimates(self, start_utc, end_utc, site=None, _use_data_field=None) -> float:
        """Return energy total for a period.

        Arguments:
            start_utc (datetime): Start of time period datetime in UTC.
            end_utc (datetime): End of time period datetime in UTC.
            site (str): Optional Solcast site ID, used to provide site breakdown.
            _used_data_field (str): A optional forecast type, used to select the pv_forecast, pv_forecast10 or pv_forecast90 returned.
 
        Returns:
            float: Energy forecast total for a period as kWh.
       """
        try:
            _data = self._data_forecasts if site is None else self._site_data_forecasts[site]
            _data_field = self._use_data_field if _use_data_field is None else _use_data_field
            res = 0
            st_i, end_i = self.__get_forecast_list_slice(_data, start_utc, end_utc) # Get start and end indexes for the requested range.
            if _data[st_i:end_i] != []:
                for d in _data[st_i:end_i]:
                    res += d[_data_field]
                if SENSOR_DEBUG_LOGGING: _LOGGER.debug(
                    "Get estimate: %s()%s%s st %s end %s st_i %d end_i %d res %s",
                    currentFuncName(1), '' if site is None else ' '+site, '' if _data_field is None else ' '+_data_field,
                    start_utc.strftime(DATE_FORMAT_UTC),
                    end_utc.strftime(DATE_FORMAT_UTC),
                    st_i, end_i, round(res,4)
                )
            else:
                _LOGGER.error(
                    "No forecast data available for %s()%s%s: %s to %s",
                    currentFuncName(1), '' if site is None else ' '+site, '' if _data_field is None else ' '+_data_field,
                    start_utc.strftime(DATE_FORMAT_UTC),
                    end_utc.strftime(DATE_FORMAT_UTC)
                )
            return res
        except Exception as e:
            _LOGGER.error("Exception in __get_forecast_pv_estimates(): %s: %s", e, traceback.format_exc())
            return 0

    def __get_forecast_pv_moment(self, time_utc, site=None, _use_data_field=None) -> float:
        """Return forecast power for a point in time.

        Arguments:
            time_utc (datetime): A moment in UTC to return.
            site (str): Optional Solcast site ID, used to provide site breakdown.
            _used_data_field (str): A optional forecast type, used to select the pv_forecast, pv_forecast10 or pv_forecast90 returned.
 
        Returns:
            float: Forecast power for a point in time as kW (from splined data).
        """
        try:
            _data_field = self._use_data_field if _use_data_field is None else _use_data_field
            day_start = self.get_day_start_utc()
            time_utc = time_utc.replace(minute = math.floor(time_utc.minute / 5) * 5)
            res = self.__get_moment(site, _data_field, (time_utc - day_start).total_seconds())
            if SENSOR_DEBUG_LOGGING: _LOGGER.debug(
                "Get estimate moment: %s()%s %s t %s sec %d res %s",
                currentFuncName(1), '' if site is None else ' '+site, _data_field,
                time_utc.strftime(DATE_FORMAT_UTC), (time_utc - day_start).total_seconds(), round(res, 4)
            )
            return res
        except Exception as e:
            _LOGGER.error("Exception in __get_forecast_pv_moment(): %s: %s", e, traceback.format_exc())
            raise
            #return 0

    def __get_max_forecast_pv_estimate(self, start_utc, end_utc, site=None, _use_data_field=None) -> float:
        """Return forecast maximum for a period.

        Arguments:
            start_utc (datetime): Start of time period datetime in UTC.
            end_utc (datetime): End of time period datetime in UTC.
            site (str): Optional Solcast site ID, used to provide site breakdown.
            _used_data_field (str): A optional forecast type, used to select the pv_forecast, pv_forecast10 or pv_forecast90 returned.
 
        Returns:
            float: The maximum forecast power for a period as kW.
        """
        try:
            _data = self._data_forecasts if site is None else self._site_data_forecasts[site]
            _data_field = self._use_data_field if _use_data_field is None else _use_data_field
            res = 0
            st_i, end_i = self.__get_forecast_list_slice(_data, start_utc, end_utc)
            if _data[st_i:end_i] != []:
                res = _data[st_i]
                for d in _data[st_i:end_i]:
                    if  res[_data_field] < d[_data_field]:
                        res = d
                if SENSOR_DEBUG_LOGGING: _LOGGER.debug(
                    "Get max estimate: %s()%s %s st %s end %s st_i %d end_i %d res %s",
                    currentFuncName(1), '' if site is None else ' '+site, _data_field,
                    start_utc.strftime(DATE_FORMAT_UTC),
                    end_utc.strftime(DATE_FORMAT_UTC),
                    st_i, end_i, res
                )
            else:
                _LOGGER.error(
                    "No forecast data available for %s()%s%s: %s to %s",
                    currentFuncName(1), '' if site is None else ' '+site, '' if _data_field is None else ' '+_data_field,
                    start_utc.strftime(DATE_FORMAT_UTC),
                    end_utc.strftime(DATE_FORMAT_UTC)
                )
            return res
        except Exception as e:
            _LOGGER.error("Exception in __get_max_forecast_pv_estimate(): %s: %s", e, traceback.format_exc())
            return 0

    def get_energy_data(self) -> Optional[dict[str, Any]]:
        """Get energy data.
 
        Returns:
            dict: A Home Assistant energy dashboard compatible data set.
        """
        try:
            return self._data_energy
        except Exception as e:
            _LOGGER.error("Exception in get_energy_data(): %s: %s", e, traceback.format_exc())
            return None

    async def get_forecast_update(self, do_past=False, force=False) -> str:
        """Request forecast data for all sites.

        Arguments:
            do_past (bool): A optional flag to indicate that past actual forecasts should be retrieved.
 
        Returns:
            str: An error message, or an empty string for no error.
        """
        try:
            status = ''
            if self.get_last_updated_datetime() + timedelta(minutes=1) > dt.now(timezone.utc):
                status = f"Not requesting a solar forecast because time is within one minute of last update ({self.get_last_updated_datetime().astimezone(self._tz)})"
                _LOGGER.warning(status)
                return status

            await self.refresh_granular_dampening_data()

            failure = False
            sites_attempted = 0
            for site in self.sites:
                sites_attempted += 1
                _LOGGER.info("Getting forecast update for site %s", site['resource_id'])
                result = await self.__http_data_call(site=site['resource_id'], api_key=site['apikey'], do_past=do_past, force=force)
                if not result:
                    failure = True
                    if len(self.sites) > 1:
                        if sites_attempted < len(self.sites):
                            _LOGGER.warning(
                                "Forecast update for site %s failed so not getting remaining sites%s", site['resource_id'],
                                " - API use count may be odd" if len(self.sites) > 2 and not force else ""
                            )
                        else:
                            _LOGGER.warning(
                                "Forecast update for the last site queued failed (%s)%s", site['resource_id'],
                                " - API use count may be odd" if not force else ""
                            )
                    else:
                        _LOGGER.warning("Forecast update for site %s failed", site['resource_id'])
                    status = 'At least one site forecast get failed'
                    break

            if sites_attempted > 0 and not failure:
                self._data["last_updated"] = dt.now(timezone.utc).isoformat()
                self._data_undampened["last_updated"] = dt.now(timezone.utc).isoformat()
                #self._data["weather"] = self._weather

                b_status = await self.build_forecast_data()
                self._data["version"] = JSON_VERSION
                self._data_undampened["version"] = JSON_VERSION
                self._loaded_data = True

                s_status = await self.__serialise_data(self._data, self._filename)
                await self.__serialise_data(self._data_undampened, self._filename_undampened)
                if b_status and s_status:
                    _LOGGER.info("Forecast update completed successfully")
            else:
                if sites_attempted > 0:
                    _LOGGER.error("At least one site forecast failed to fetch, so forecast has not been built")
                else:
                    _LOGGER.error("Internal error, there is no sites data so forecast has not been built")
                status = 'At least one site forecast get failed'
        except Exception as e:
            status = f"Exception in get_forecast_update(): {e} - Forecast has not been built"
            _LOGGER.error(status)
            _LOGGER.error(traceback.format_exc())
        return status

    async def __migrate_undampened_history(self):
        """Migrate undampened forecasts if undampened data for a site does not exist."""
        apply_dampening = []
        try:
            forecasts = {}
            pastdays = self.get_day_start_utc() - timedelta(days=14)
            for s in self.sites:
                site = s['resource_id']
                if not self._data_undampened['siteinfo'].get(site) or len(self._data_undampened['siteinfo'][site].get('forecasts', [])) == 0:
                    _LOGGER.info("Migrating undampened history to %s for %s", self._filename_undampened, site)
                    apply_dampening.append(site)
                else:
                    continue
                # Load the forecast history.
                try:
                    forecasts[site] = {forecast["period_start"]: forecast for forecast in self._data['siteinfo'][site]['forecasts']}
                except:
                    forecasts[site] = {}
                forecasts_undampened = {}
                try:
                    # Migrate forecast history if undampened data does not yet exist.
                    if len(forecasts[site]) > 0:
                        forecasts_undampened = sorted(list({
                            forecast["period_start"]: forecast for forecast in self._data['siteinfo'][site]['forecasts'] if forecast["period_start"] >= pastdays
                        }.values()), key=itemgetter("period_start"))
                        _LOGGER.debug("Migrating %d forecast entries to undampened forecasts for site %s", len(forecasts_undampened), site)
                except:
                    _LOGGER.debug(traceback.format_exc())
                    raise
                self._data_undampened['siteinfo'].update({site:{'forecasts': copy.deepcopy(forecasts_undampened)}})

            if len(apply_dampening) > 0:
                self._data_undampened["last_updated"] = dt.now(timezone.utc).isoformat()
                await self.__serialise_data(self._data_undampened, self._filename_undampened)

            valid_granular_dampening = self.__valid_granular_dampening()
            for s in self.sites:
                site = s['resource_id']
                if site in apply_dampening:
                    _LOGGER.info("Dampening forecasts for today onwards for site %s", site)
                else:
                    continue
                day_start = self.get_day_start_utc()
                for interval, forecast in forecasts[site].items():
                    if interval >= day_start:
                        # Apply dampening to the existing data (today onwards only).
                        period_start = forecast["period_start"]
                        dampening_factor = self.__get_dampening_factor(site, period_start.astimezone(self._tz), valid_granular_dampening)
                        self.__forecast_entry_update(
                            forecasts[site],
                            period_start,
                            round(round(forecast["pv_estimate"], 4) * dampening_factor, 4),
                            round(round(forecast["pv_estimate10"], 4) * dampening_factor, 4),
                            round(round(forecast["pv_estimate90"], 4) * dampening_factor, 4)
                        )
                forecasts[site] = sorted(list(forecasts[site].values()), key=itemgetter("period_start"))
                self._data['siteinfo'].update({site:{'forecasts': copy.deepcopy(forecasts[site])}})

            if len(apply_dampening) > 0:
                await self.__serialise_data(self._data, self._filename)
        except Exception as e:
            _LOGGER.error("Exception in __migrate_undampened_history(): %s: %s", e, traceback.format_exc())

    def __forecast_entry_update(self, forecasts: dict, period_start: dt, pv: float, pv10: float, pv90: float):
        """Update an individual forecast entry."""
        extant = forecasts.get(period_start)
        if extant: # Update existing.
            extant["pv_estimate"] = pv
            extant["pv_estimate10"] = pv10
            extant["pv_estimate90"] = pv90
        else: # New forecast.
            forecasts[period_start] = {"period_start": period_start, "pv_estimate": pv, "pv_estimate10": pv10, "pv_estimate90": pv90}

    def __get_dampening_granular_factor(self, site: str, z: dt):
        """Retrieve a granular dampening factor."""
        return self.granular_dampening[site][
            z.hour if len(self.granular_dampening[site]) == 24 else ((z.hour*2) + (1 if z.minute > 0 else 0))
        ]

    def __get_dampening_factor(self, site: str, z: int, valid_granular_dampening: bool) -> float:
        """Retrieve either a traditional or granular dampening factor."""
        if self.entry_options.get(SITE_DAMP):
            if self.granular_dampening.get('all') and valid_granular_dampening:
                return self.__get_dampening_granular_factor('all', z)
            elif self.granular_dampening.get(site) and valid_granular_dampening:
                return self.__get_dampening_granular_factor(site, z)
            else:
                return 1.0
        else:
            return self.damp.get(f"{z.hour}", 1.0)

    async def __http_data_call(self, site=None, api_key=None, do_past=False, force=False) -> bool:
        """Request forecast data via the Solcast API.

        Arguments:
            site (str): A Solcast site ID
            api_key (str): A Solcast API key appropriate to use for the site
            do_past (bool): A optional flag to indicate that past actual forecasts should be retrieved.

        Returns:
            bool: A flag indicating success or failure
        """
        try:
            lastday = self.get_day_start_utc() + timedelta(days=8)
            numhours = math.ceil((lastday - self.get_now_utc()).total_seconds() / 3600)
            _LOGGER.debug("Polling API for site %s lastday %s numhours %d", site, lastday.strftime('%Y-%m-%d'), numhours)

            new_data = []

            """
            Fetch past data. (Run once, for a new install or if the solcast.json file is deleted. This will use up api call quota.)
            """
            if do_past:
                self.tasks['fetch'] = asyncio.create_task(self.__fetch_data(168, path="estimated_actuals", site=site, api_key=api_key, cachedname="actuals", force=force))
                await self.tasks['fetch']
                resp_dict = self.tasks['fetch'].result()
                if self.tasks.get('fetch') is not None:
                    self.tasks.pop('fetch')
                if not isinstance(resp_dict, dict):
                    _LOGGER.error("No data was returned for estimated_actuals so this WILL cause issues. Your API limit may be exhaused, or Solcast has a problem...")
                    raise TypeError(f"API did not return a json object. Returned {resp_dict}")

                estimate_actuals = resp_dict.get("estimated_actuals", None)

                if not isinstance(estimate_actuals, list):
                    raise TypeError(f"Estimated actuals must be a list, not {type(estimate_actuals)}")

                oldest = (dt.now(self._tz).replace(hour=0,minute=0,second=0,microsecond=0) - timedelta(days=6)).astimezone(timezone.utc)

                for estimate_actual in estimate_actuals:
                    z = parse_datetime(estimate_actual["period_end"]).astimezone(timezone.utc)
                    z = z.replace(second=0, microsecond=0) - timedelta(minutes=30)
                    if z.minute not in {0, 30}:
                        raise ValueError(
                            f"period_start minute is not 0 or 30. {z.minute}"
                        )
                    if z > oldest:
                        new_data.append(
                            {
                                "period_start": z,
                                "pv_estimate": estimate_actual["pv_estimate"],
                                "pv_estimate10": 0,
                                "pv_estimate90": 0,
                            }
                        )

            """
            Fetch latest data.
            """
            self.tasks['fetch'] = asyncio.create_task(self.__fetch_data(numhours, path="forecasts", site=site, api_key=api_key, cachedname="forecasts", force=force))
            await self.tasks['fetch']
            resp_dict = self.tasks['fetch'].result()
            if self.tasks.get('fetch') is not None:
                self.tasks.pop('fetch')
            if resp_dict is None:
                return False

            if not isinstance(resp_dict, dict):
                raise TypeError(f"API did not return a json object. Returned {resp_dict}")

            latest_forecasts = resp_dict.get("forecasts", None)
            if not isinstance(latest_forecasts, list):
                raise TypeError(f"forecasts must be a list, not {type(latest_forecasts)}")

            _LOGGER.debug("%d records returned", len(latest_forecasts))

            st_time = time.time()
            for forecast in latest_forecasts:
                z = parse_datetime(forecast["period_end"]).astimezone(timezone.utc)
                z = z.replace(second=0, microsecond=0) - timedelta(minutes=30)
                if z.minute not in {0, 30}:
                    raise ValueError(
                        f"period_start minute is not 0 or 30. {z.minute}"
                    )
                if z < lastday:
                    new_data.append(
                        {
                            "period_start": z,
                            "pv_estimate": forecast["pv_estimate"],
                            "pv_estimate10": forecast["pv_estimate10"],
                            "pv_estimate90": forecast["pv_estimate90"],
                        }
                    )

            """
            Add or update forecasts with the latest data.
            """
            # Load the forecast history.
            try:
                forecasts = {forecast["period_start"]: forecast for forecast in self._data['siteinfo'][site]['forecasts']}
            except:
                forecasts = {}
            try:
                forecasts_undampened = {forecast["period_start"]: forecast for forecast in self._data_undampened['siteinfo'][site]['forecasts']}
            except:
                forecasts_undampened = {}

            # Apply dampening to the new data
            valid_granular_dampening = self.__valid_granular_dampening()
            for forecast in sorted(new_data, key=itemgetter("period_start")):
                period_start = forecast["period_start"]
                pv = round(forecast["pv_estimate"], 4)
                pv10 = round(forecast["pv_estimate10"], 4)
                pv90 = round(forecast["pv_estimate90"], 4)

                # Retrieve the dampening factor for the period, and dampen the estimates.
                dampening_factor = self.__get_dampening_factor(site, period_start.astimezone(self._tz), valid_granular_dampening)
                pv_dampened = round(pv * dampening_factor, 4)
                pv10_dampened = round(pv10 * dampening_factor, 4)
                pv90_dampened = round(pv90 * dampening_factor, 4)

                # Add or update the new entries.
                self.__forecast_entry_update(forecasts, period_start, pv_dampened, pv10_dampened, pv90_dampened)
                self.__forecast_entry_update(forecasts_undampened, period_start, pv, pv10, pv90)

            # Forecasts contains up to 730 days of period history data for each site. Convert dictionary to list, retain the past two years, sort by period start.
            pastdays = self.get_day_start_utc() - timedelta(days=730)
            forecasts = sorted(list(filter(lambda forecast: forecast["period_start"] >= pastdays, forecasts.values())), key=itemgetter("period_start"))
            self._data['siteinfo'].update({site:{'forecasts': copy.deepcopy(forecasts)}})

            # Undampened forecasts contains up to 14 days of period history data for each site.
            pastdays = self.get_day_start_utc() - timedelta(days=14)
            forecasts_undampened = sorted(list(filter(lambda forecast: forecast["period_start"] >= pastdays, forecasts_undampened.values())), key=itemgetter("period_start"))
            self._data_undampened['siteinfo'].update({site:{'forecasts': copy.deepcopy(forecasts_undampened)}})

            _LOGGER.debug("Forecasts dictionary length %s", len(forecasts))
            _LOGGER.debug("Undampened forecasts dictionary length %s", len(forecasts_undampened))
            _LOGGER.debug("HTTP data call processing took %.3f seconds", round(time.time() - st_time, 4))
            return True
        except Exception as e:
            _LOGGER.error("Exception in __http_data_call(): %s: %s", e, traceback.format_exc())
        return False


    async def __fetch_data(self, hours, path="error", site="", api_key="", cachedname="forecasts", force=False) -> Optional[dict[str, Any]]:
        """Fetch forecast data.
        
        Arguments:
            hours (int): Number of hours to fetch, normally 168, or seven days.
            path (str): The path to follow. "forecast" or "estimated actuals". Omitting this parameter will result in an error.
            site (str): A Solcast site ID.
            api_key (str): A Solcast API key appropriate to use for the site.
            cachedname (str): "forecasts" or "actuals".

        Returns:
            dict: Raw forecast data points, or None if unsuccessful.
        """
        try:
            """
            One site is fetched, and retries ensure that the site is actually fetched.
            Occasionally the Solcast API is busy, and returns a 429 status, which is a
            request to try again later. (It could also indicate that the API limit for
            the day has been exceeded, and this is catered for by examining additional
            status.)

            The retry mechanism is a "back-off", where the interval between attempted
            fetches is increased each time. All attempts possible span a maximum of
            fifteen minutes, and this is also the timeout limit set for the entire
            async operation.
            """
            async with async_timeout.timeout(900):
                if self._api_cache_enabled:
                    api_cache_filename = self._config_dir + '/' + cachedname + "_" + site + ".json"
                    if file_exists(api_cache_filename):
                        status = 404
                        async with aiofiles.open(api_cache_filename) as f:
                            resp_json = json.loads(await f.read())
                            status = 200
                            _LOGGER.debug("Offline cached mode enabled, loaded data for site %s", site)
                else:
                    if self._api_used[api_key] < self._api_limit[api_key] or force:
                        url = f"{self.options.host}/rooftop_sites/{site}/{path}"
                        params = {"format": "json", "api_key": api_key, "hours": hours}
                        _LOGGER.debug("Fetch data url: %s", url)
                        tries = 10
                        counter = 0
                        backoff = 15 # On every retry the back-off increases by (at least) fifteen seconds more than the previous back-off.
                        while True:
                            _LOGGER.debug("Fetching forecast")
                            counter += 1
                            resp: ClientResponse = await self._aiohttp_session.get(url=url, params=params, headers=self.headers, ssl=False)
                            status = resp.status
                            if status == 200:
                                break
                            elif status == 429:
                                try:
                                    # Test for API limit exceeded {"response_status":{"error_code":"TooManyRequests","message":"You have exceeded your free daily limit.","errors":[]}}.
                                    resp_json = await resp.json(content_type=None)
                                    rs = resp_json.get('response_status')
                                    if rs is not None:
                                        if rs.get('error_code') == 'TooManyRequests':
                                            status = 998
                                            self._api_used[api_key] = self._api_limit[api_key]
                                            await self.__serialise_usage(api_key)
                                            break
                                        else:
                                            status = 1000
                                            _LOGGER.warning("An unexpected error occurred: %s", rs.get('message'))
                                            break
                                except:
                                    pass
                                if counter >= tries:
                                    status = 999 # All retries have been exhausted.
                                    break
                                # Solcast is busy, so delay (15 seconds * counter), plus a random number of seconds between zero and 15.
                                delay = (counter * backoff) + random.randrange(0,15)
                                _LOGGER.warning("API returned 'try later' (status 429), pausing %d seconds before retry", delay)
                                await asyncio.sleep(delay)
                            else:
                                break

                        if status == 200:
                            _LOGGER.debug("Fetch successful")

                            if not force:
                                _LOGGER.debug("API returned data, API counter incremented from %d to %d", self._api_used[api_key], self._api_used[api_key] + 1)
                                self._api_used[api_key] += 1
                                await self.__serialise_usage(api_key)
                            else:
                                _LOGGER.debug("API returned data, using force fetch so not incrementing API counter")
                            resp_json = await resp.json(content_type=None)

                            if self._api_cache_enabled:
                                async with self._serialise_lock:
                                    async with aiofiles.open(api_cache_filename, 'w') as f:
                                        await f.write(json.dumps(resp_json, ensure_ascii=False))
                        elif status == 998: # Exceeded API limit.
                            _LOGGER.error("API allowed polling limit has been exceeded, API counter set to %d/%d", self._api_used[api_key], self._api_limit[api_key])
                            return None
                        elif status == 999: # Attempts exhausted.
                            _LOGGER.error("API was tried %d times, but all attempts failed", tries)
                            return None
                        elif status == 1000: # An unexpected response.
                            return None
                        else:
                            _LOGGER.error("API returned status %s, API used is %d/%d", translate(status), self._api_used[api_key], self._api_limit[api_key])
                            return None
                    else:
                        _LOGGER.warning("API polling limit exhausted, not getting forecast for site %s, API used is %d/%d", site, self._api_used[api_key], self._api_limit[api_key])
                        return None

                _LOGGER.debug("HTTP session returned data type %s", type(resp_json))
                _LOGGER.debug("HTTP session status %s", translate(status))

            if status == 429:
                _LOGGER.warning("API is too busy, try again later")
            elif status == 400:
                _LOGGER.warning("Status %s: The site is likely missing capacity, please specify capacity or provide historic data for tuning", translate(status))
            elif status == 404:
                _LOGGER.error("The site cannot be found, status %s returned", translate(status))
            elif status == 200:
                d = cast(dict, resp_json)
                if FORECAST_DEBUG_LOGGING:
                    _LOGGER.debug("HTTP session returned: %s", str(d))
                return d
        except asyncio.exceptions.CancelledError:
            _LOGGER.debug('Fetch cancelled')
        except ConnectionRefusedError as e:
            _LOGGER.error("Connection error in __fetch_data(), connection refused: %s", e)
        except ClientConnectionError as e:
            _LOGGER.error("Connection error in __fetch_data(): %s", e)
        except asyncio.TimeoutError:
            _LOGGER.error("Connection error in __fetch_data(): Timed out connecting to server")
        except:
            _LOGGER.error("Exception in __fetch_data(): %s", traceback.format_exc())

        return None

    def __make_energy_dict(self) -> dict:
        """Make a Home Assistant energy dashboard compatible dictionary.

        Returns:
            dict: An energy dashboard compatible data structure.
        """
        wh_hours = {}
        try:
            lastv = -1
            lastk = -1
            for v in self._data_forecasts:
                d = v['period_start'].isoformat()
                value = v[self._use_data_field]
                if value == 0.0:
                    if lastv > 0.0:
                        wh_hours[d] = 0.0
                        wh_hours[lastk] = 0.0
                else:
                    if lastv == 0.0:
                        wh_hours[lastk] = 0.0
                    wh_hours[d] = round(value * 500,0)

                lastk = d
                lastv = value
        except:
            _LOGGER.error("Exception in __make_energy_dict(): %s", traceback.format_exc())

        return wh_hours

    async def build_forecast_data(self) -> bool:
        """Build data structures needed, adjusting if dampening or setting a hard limit.

        Returns:
            bool: A flag indicating success or failure.
        """
        try:
            st_time = time.time()

            today = dt.now(self._tz).date()
            commencing = dt.now(self._tz).date() - timedelta(days=730)
            commencing_undampened = dt.now(self._tz).date() - timedelta(days=14)
            lastday = dt.now(self._tz).date() + timedelta(days=8)

            forecasts = {}
            forecasts_undampened = {}

            def build_data(data: list, commencing: dt, forecasts: dict, site_data_forecasts: list, update_tally: bool=False):
                for site, siteinfo in data['siteinfo'].items():
                    if update_tally:
                        tally = 0
                    site_forecasts = {}

                    for forecast in siteinfo['forecasts']:
                        z = forecast["period_start"]
                        zz = z.astimezone(self._tz)

                        if commencing < zz.date() < lastday:

                            # Record the individual site forecast.
                            site_forecasts[z] = {
                                "period_start": z,
                                "pv_estimate": min(forecast["pv_estimate"], self.hard_limit),
                                "pv_estimate10": min(forecast["pv_estimate10"], self.hard_limit),
                                "pv_estimate90": min(forecast["pv_estimate90"], self.hard_limit),
                            }

                            if update_tally and zz.date() == today:
                                tally += min(forecast[self._use_data_field] * 0.5, self.hard_limit)

                            # Add the forecast for this site to the total.
                            extant = forecasts.get(z)
                            if extant:
                                extant["pv_estimate"] = min(round(extant["pv_estimate"] + site_forecasts[z]["pv_estimate"], 4), self.hard_limit)
                                extant["pv_estimate10"] = min(round(extant["pv_estimate10"] + site_forecasts[z]["pv_estimate10"], 4), self.hard_limit)
                                extant["pv_estimate90"] = min(round(extant["pv_estimate90"] + site_forecasts[z]["pv_estimate90"], 4), self.hard_limit)
                            else:
                                forecasts[z] = {
                                    "period_start": z,
                                    "pv_estimate": min(site_forecasts[z]["pv_estimate"], self.hard_limit),
                                    "pv_estimate10": min(site_forecasts[z]["pv_estimate10"], self.hard_limit),
                                    "pv_estimate90": min(site_forecasts[z]["pv_estimate90"], self.hard_limit),
                                }

                    site_data_forecasts[site] = sorted(site_forecasts.values(), key=itemgetter("period_start"))
                    if update_tally:
                        siteinfo['tally'] = round(tally, 4)
                        self._tally[site] = siteinfo['tally']

            build_data(self._data, commencing, forecasts, self._site_data_forecasts, update_tally=True)
            self._data_forecasts = sorted(forecasts.values(), key=itemgetter("period_start"))
            self._data_energy = {"wh_hours": self.__make_energy_dict()}

            build_data(self._data_undampened, commencing_undampened, forecasts_undampened, self._site_data_forecasts_undampened)
            self._data_forecasts_undampened = sorted(forecasts_undampened.values(), key=itemgetter("period_start"))

            await self.__check_data_records()
            await self.recalculate_splines()

            _LOGGER.debug("Build forecast processing took %.3f seconds", round(time.time() - st_time, 4))
            return True

        except:
            _LOGGER.error("Exception in get_forecast_update(): %s", traceback.format_exc())
            return False


    def __calc_forecast_start_index(self, _data) -> int:
        """Get the start of forecasts as-at just before midnight.

        Doesn't stop at midnight because some sensors may need the previous interval,
        and searches in reverse because less to iterate.

        Arguments:
            _data (list): The data structure to search, either total data or site breakdown data.

        Returns:
            int: The starting index of the data structure just prior to midnight local time.
        """
        midnight_utc = self.get_day_start_utc()
        for idx in range(len(_data)-1, -1, -1):
            if _data[idx]["period_start"] < midnight_utc:
                break
        #if SENSOR_DEBUG_LOGGING:
        #    _LOGGER.debug("Calc forecast start index midnight: %s, idx %d, len %d", midnight_utc.strftime(DATE_FORMAT_UTC), idx, len(_data))
        return idx


    async def __check_data_records(self):
        """Log whether all records are present for each day."""
        try:
            contiguous_start_date = None
            contiguous_end_date = None
            all_records = True
            interval_assessment = {}

            for future in range(0, 8):
                start_utc = self.get_day_start_utc() + timedelta(days=future)
                end_utc = start_utc + timedelta(days=1)
                st_i, end_i = self.__get_forecast_list_slice(self._data_forecasts, start_utc, end_utc)
                intervals = end_i - st_i

                interval_date = dt.now(self._tz).date() + timedelta(days=future)
                if future == 0 and intervals == 48:
                    contiguous_start_date = interval_date
                if intervals == 48:
                    if all_records:
                        contiguous_end_date = interval_date
                    else:
                        interval_assessment[interval_date] = 48
                else:
                    all_records = False
                    interval_assessment[interval_date] = intervals
            if contiguous_start_date and contiguous_end_date:
                _LOGGER.debug("Forecast data from %s to %s contains all 48 intervals", contiguous_start_date.strftime('%Y-%m-%d'), contiguous_end_date.strftime('%Y-%m-%d'))
            if len(interval_assessment.keys()) > 0:
                for day, intervals in OrderedDict(sorted(interval_assessment.items(), key=lambda k:k[0])).items():
                    if intervals == 48:
                        _LOGGER.debug("Forecast data for %s contains all 48 intervals", day.strftime('%Y-%m-%d'))
                    else:
                        _LOGGER.debug("Forecast data for %s contains only %d of 48 intervals and may produce inaccurate forecast data", day.strftime('%Y-%m-%d'), intervals)
        except Exception as e:
            _LOGGER.error("Exception in __check_data_records(): %s: %s", e, traceback.format_exc())
