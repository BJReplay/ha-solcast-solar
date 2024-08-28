"""Solcast API"""

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
from os.path import exists as file_exists
from os.path import dirname
from typing import Any, Dict, cast

import async_timeout
import aiofiles
from aiohttp import ClientConnectionError, ClientSession
from aiohttp.client_reqrep import ClientResponse
from isodate import parse_datetime

from .spline import cubic_interp

# For current func name, specify 0 or no argument
# For name of caller of current func, specify 1
# For name of caller of caller of current func, specify 2, etc.
currentFuncName = lambda n=0: sys._getframe(n + 1).f_code.co_name

_SENSOR_DEBUG_LOGGING = False
_FORECAST_DEBUG_LOGGING = False
_SPLINE_DEBUG_LOGGING = False

_JSON_VERSION = 4
_LOGGER = logging.getLogger(__name__)

class DateTimeEncoder(json.JSONEncoder):
    """Date/time helper"""
    def default(self, o):
        if isinstance(o, dt):
            return o.isoformat()
        else:
            return None

class JSONDecoder(json.JSONDecoder):
    """JSON decoder helper"""
    def __init__(self, *args, **kwargs) -> None:
        json.JSONDecoder.__init__(
            self, object_hook=self.object_hook, *args, **kwargs)

    def object_hook(self, obj) -> dict:
        """Hook"""
        ret = {}
        for key, value in obj.items():
            if key in {'period_start'}:
                ret[key] = dt.fromisoformat(value)
            else:
                ret[key] = value
        return ret

# HTTP status code translation.
# A 418 error is included here for fun. This was included in RFC2324#section-2.3.2 as an April Fools joke in 1998.
statusTranslate = {
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
    """Translate HTTP status code to a human-readable translation"""
    return (f"{str(status)}/{statusTranslate[status]}") if statusTranslate.get(status) else status


@dataclass
class ConnectionOptions:
    """Solcast options for the integration"""

    api_key: str
    api_quota: str
    host: str
    file_path: str
    tz: timezone
    dampening: dict
    customhoursensor: int
    key_estimate: str
    hard_limit: int
    attr_brk_estimate: bool
    attr_brk_estimate10: bool
    attr_brk_estimate90: bool
    attr_brk_site: bool
    attr_brk_halfhourly: bool
    attr_brk_hourly: bool


class SolcastApi:
    """Solcast API"""

    def __init__(
        self,
        aiohttp_session: ClientSession,
        options: ConnectionOptions,
        api_cache_enabled: bool = False
    ):
        """Device init"""
        self.aiohttp_session = aiohttp_session
        self.options = options
        self.api_cache_enabled = api_cache_enabled
        self._sites_loaded = False
        self._sites = []
        self._data = {'siteinfo': {}, 'last_updated': dt.fromtimestamp(0, timezone.utc).isoformat()}
        self._tally = {}
        self._api_used = {}
        self._api_limit = {}
        self._api_used_reset = {}
        self._filename = options.file_path
        self._config_dir = dirname(self._filename)
        self._tz = options.tz
        self._dataenergy = {}
        self._data_forecasts = []
        self._site_data_forecasts = {}
        self._forecasts_start_idx = 0
        self._loaded_data = False
        self._serialize_lock = asyncio.Lock()
        self._damp = options.dampening
        self._customhoursensor = options.customhoursensor
        self._use_data_field = f"pv_{options.key_estimate}"
        self._hardlimit = options.hard_limit
        self._estimen = {'pv_estimate': options.attr_brk_estimate, 'pv_estimate10': options.attr_brk_estimate10, 'pv_estimate90': options.attr_brk_estimate90}
        self._spline_period = list(range(0, 90000, 1800))
        self.fc_moment = {}
        self.fc_remaining = {}
        #self._weather = ""
        _LOGGER.debug("Configuration directory is %s", self._config_dir)

    def get_tz(self) -> str:
        """Return the time zone"""
        return self._tz

    def sites_loaded(self) -> bool:
        """Return the active sites"""
        return self._sites_loaded

    def get_sites(self) -> dict[str, Any]:
        """Return the active sites"""
        return self._sites

    def get_data(self) -> dict[str, Any]:
        """Return the data dictionary"""
        return self._data

    def get_customhoursensor(self) -> int:
        """Return the custom hour sensor"""
        return self._customhoursensor

    def get_hardlimit(self) -> int:
        """Return the hard limit"""
        return self._hardlimit

    def set_damp(self, d) -> None:
        """Set the dampening dictionary"""
        self._damp = d

    async def serialize_data(self):
        """Serialize data to file"""
        try:
            if not self._loaded_data:
                _LOGGER.debug("Not saving forecast cache in serialize_data() as no data has been loaded yet")
                return
            # If the _loaded_data flag is True, yet last_updated is 1/1/1970 then data has not been
            # loaded properly for some reason, or no forecast has been received since startup.
            # Abort the save.
            if self._data['last_updated'] == dt.fromtimestamp(0, timezone.utc).isoformat():
                _LOGGER.error("Internal error: Solcast forecast cache date has not been set, not saving data")
                return

            async with self._serialize_lock:
                async with aiofiles.open(self._filename, "w") as f:
                    await f.write(json.dumps(self._data, ensure_ascii=False, cls=DateTimeEncoder))
                    _LOGGER.debug("Saved forecast cache")
        except Exception as e:
            _LOGGER.error("Exception in serialize_data(): %s", e)
            _LOGGER.error(traceback.format_exc())

    def redact_api_key(self, api_key) -> str:
        """Obfuscate API key"""
        return '*'*6 + api_key[-6:]

    def redact_msg_api_key(self, msg, api_key) -> str:
        """Obfuscate API key in messages"""
        return msg.replace(api_key, self.redact_api_key(api_key))

    async def write_api_usage_cache_file(self, api_key, reset=False):
        """Serialise the usage cache file"""
        try:
            json_file = self.get_api_usage_cache_filename(api_key)
            if reset:
                self._api_used_reset[api_key] = self.get_day_start_utc()
            _LOGGER.debug("Writing API usage cache file: %s", self.redact_msg_api_key(json_file, api_key))
            json_content = {"daily_limit": self._api_limit[api_key], "daily_limit_consumed": self._api_used[api_key], "reset": self._api_used_reset[api_key].strftime("%Y-%m-%dT%H:%M:%S+00:00")}
            async with aiofiles.open(json_file, 'w') as f:
                await f.write(json.dumps(json_content, ensure_ascii=False))
        except Exception as e:
            _LOGGER.error("Exception in write_api_usage_cache_file(): %s", e)
            _LOGGER.error(traceback.format_exc())

    def get_api_usage_cache_filename(self, entry_name):
        """Build a fully qualified API usage cache filename using a simple name or separate files for more than one API key"""
        return '%s/solcast-usage%s.json' % (self._config_dir, "" if len(self.options.api_key.split(",")) < 2 else "-" + entry_name) # pylint: disable=C0209

    def get_api_sites_cache_filename(self, entry_name):
        """Build a fully qualified site details cache filename using a simple name or separate files for more than one API key"""
        return '%s/solcast-sites%s.json' % (self._config_dir, "" if len(self.options.api_key.split(",")) < 2 else "-" + entry_name) # pylint: disable=C0209

    async def reset_api_usage(self):
        """Reset the daily API usage counter"""
        for api_key, _ in self._api_used.items():
            self._api_used[api_key] = 0
            await self.write_api_usage_cache_file(api_key, reset=True)

    async def sites_data(self):
        """Request site details"""
        try:
            def redact(s):
                return re.sub(r'itude\': [0-9\-\.]+', 'itude\': **.******', s)
            sp = self.options.api_key.split(",")
            for spl in sp:
                params = {"format": "json", "api_key": spl.strip()}
                async with async_timeout.timeout(60):
                    api_cache_filename = self.get_api_sites_cache_filename(spl)
                    _LOGGER.debug("%s", 'Sites cache ' + ('exists' if file_exists(api_cache_filename) else 'does not yet exist'))
                    if self.api_cache_enabled and file_exists(api_cache_filename):
                        _LOGGER.debug("Loading cached sites data")
                        status = 404
                        async with aiofiles.open(api_cache_filename) as f:
                            resp_json = json.loads(await f.read())
                            status = 200
                    else:
                        _LOGGER.debug("Connecting to %s/rooftop_sites?format=json&api_key=%s", self.options.host, self.redact_api_key(spl))
                        retries = 3
                        retry = retries
                        success = False
                        use_cache_immediate = False
                        cache_exists = file_exists(api_cache_filename)
                        while retry >= 0:
                            resp: ClientResponse = await self.aiohttp_session.get(
                                url=f"{self.options.host}/rooftop_sites", params=params, ssl=False
                            )

                            status = resp.status
                            _LOGGER.debug("HTTP session returned status %s in sites_data()%s", translate(status), ', trying cache' if status != 200 else '')
                            try:
                                resp_json = await resp.json(content_type=None)
                            except json.decoder.JSONDecodeError:
                                _LOGGER.error("JSONDecodeError in sites_data(): Solcast site could be having problems")
                            except:
                                raise

                            if status == 200:
                                if resp_json['total_records'] > 0:
                                    _LOGGER.debug("Writing sites cache")
                                    async with aiofiles.open(api_cache_filename, 'w') as f:
                                        await f.write(json.dumps(resp_json, ensure_ascii=False))
                                    success = True
                                    break
                                else:
                                    _LOGGER.error('No sites for the API key %s are configured at solcast.com', self.redact_api_key(spl))
                                    return
                            else:
                                if cache_exists:
                                    use_cache_immediate = True
                                    break
                                if retry > 0:
                                    _LOGGER.debug("Will retry get sites, retry %d", (retries - retry) + 1)
                                    await asyncio.sleep(5)
                                retry -= 1
                        if not success:
                            if not use_cache_immediate:
                                _LOGGER.warning("Retries exhausted gathering Solcast sites, last call result: %s, using cached data if it exists", translate(status))
                            status = 404
                            if cache_exists:
                                async with aiofiles.open(api_cache_filename) as f:
                                    resp_json = json.loads(await f.read())
                                    status = 200
                                _LOGGER.info("Sites loaded for %s", self.redact_api_key(spl))
                            else:
                                _LOGGER.error("Cached Solcast sites are not yet available for %s to cope with API call failure", self.redact_api_key(spl))
                                _LOGGER.error("At least one successful API 'get sites' call is needed, so the integration will not function correctly")

                if status == 200:
                    d = cast(dict, resp_json)
                    _LOGGER.debug("Sites data: %s", redact(str(d)))
                    for i in d['sites']:
                        i['apikey'] = spl.strip()
                        #v4.0.14 to stop HA adding a pin to the map
                        i.pop('longitude', None)
                        i.pop('latitude', None)
                    self._sites = self._sites + d['sites']
                    self._sites_loaded = True
                    self._api_used_reset[spl] = None
                    _LOGGER.info("Sites loaded for %s", self.redact_api_key(spl))
                else:
                    _LOGGER.error("%s HTTP status error %s in sites_data() while gathering sites", self.options.host, translate(status))
                    raise Exception("HTTP sites_data error: Solcast Error gathering sites")
        except ConnectionRefusedError as e:
            _LOGGER.error("Connection refused in sites_data(): %s", e)
        except ClientConnectionError as e:
            _LOGGER.error('Connection error in sites_data(): %s', e)
        except asyncio.TimeoutError:
            try:
                _LOGGER.warning("Retrieving Solcast sites timed out, attempting to continue")
                error = False
                for spl in sp:
                    api_cache_filename = self.get_api_sites_cache_filename(spl)
                    cache_exists = file_exists(api_cache_filename)
                    if cache_exists:
                        _LOGGER.info("Loading cached Solcast sites for %s", self.redact_api_key(spl))
                        async with aiofiles.open(api_cache_filename) as f:
                            resp_json = json.loads(await f.read())
                            d = cast(dict, resp_json)
                            _LOGGER.debug("Sites data: %s", redact(str(d)))
                            for i in d['sites']:
                                i['apikey'] = spl.strip()
                                #v4.0.14 to stop HA adding a pin to the map
                                i.pop('longitude', None)
                                i.pop('latitude', None)
                            self._sites = self._sites + d['sites']
                            self._sites_loaded = True
                            self._api_used_reset[spl] = None
                            _LOGGER.info("Sites loaded for %s", self.redact_api_key(spl))
                    else:
                        error = True
                        _LOGGER.error("Cached sites are not yet available for %s to cope with Solcast API call failure", self.redact_api_key(spl))
                        _LOGGER.error("At least one successful API 'get sites' call is needed, so the integration cannot function yet")
                if error:
                    _LOGGER.error("Timed out getting Solcast sites, and one or more site caches failed to load")
                    _LOGGER.error("This is critical, and the integration cannot function reliably yet")
                    _LOGGER.error("Suggestion: Double check your overall HA configuration, specifically networking related")
            except:
                pass
        except Exception as e:
            _LOGGER.error("Exception in sites_data(): %s: %s", e, traceback.format_exc())

    async def sites_usage(self):
        """Load api usage cache"""

        try:
            if not self._sites_loaded:
                _LOGGER.error("Internal error. Sites must be loaded before sites_usage() is called")

            sp = self.options.api_key.split(",")
            qt = self.options.api_quota.split(",")
            try:
                for i in range(len(sp)): # If only one quota value is present, yet there are multiple sites then use the same quota
                    if len(qt) < i+1:
                        qt.append(qt[i-1])
                quota = { sp[i].strip(): int(qt[i].strip()) for i in range(len(qt)) }
            except Exception as e:
                _LOGGER.error("Exception: %s", e)
                _LOGGER.warning("Could not interpret API quota configuration string, using default of 10")
                quota = {s: 10 for s in sp}

            for spl in sp:
                api_key = spl.strip()
                api_cache_filename = self.get_api_usage_cache_filename(api_key)
                _LOGGER.debug("%s for %s", 'Usage cache ' + ('exists' if file_exists(api_cache_filename) else 'does not yet exist'), self.redact_api_key(api_key))
                cache = True
                if file_exists(api_cache_filename):
                    async with aiofiles.open(api_cache_filename) as f:
                        try:
                            usage = json.loads(await f.read(), cls=JSONDecoder)
                        except:
                            cache = False
                    if cache:
                        self._api_limit[api_key] = usage.get("daily_limit", None)
                        self._api_used[api_key] = usage.get("daily_limit_consumed", None)
                        self._api_used_reset[api_key] = usage.get("reset", None)
                        try:
                            self._api_used_reset[api_key] = parse_datetime(self._api_used_reset[api_key]).astimezone(timezone.utc)
                        except:
                            _LOGGER.error("Internal error parsing datetime from usage cache, continuing")
                            _LOGGER.error(traceback.format_exc())
                        if usage['daily_limit'] != quota[spl]: # Limit has been adjusted, so rewrite the cache
                            self._api_limit[api_key] = quota[spl]
                            await self.write_api_usage_cache_file(api_key)
                            _LOGGER.info("Usage loaded and cache updated with new quota")
                        else:
                            _LOGGER.info("Usage loaded for %s", self.redact_api_key(api_key))
                        if self._api_used_reset[api_key] is not None and self.get_real_now_utc() > self._api_used_reset[api_key] + timedelta(hours=24):
                            _LOGGER.warning("Resetting usage for %s, last reset was more than 24-hours ago", self.redact_api_key(api_key))
                            self._api_used[api_key] = 0
                            await self.write_api_usage_cache_file(api_key, reset=True)
                else:
                    cache = False
                if not cache:
                    _LOGGER.warning("No usage cache found (or corrupt) for %s, creating one and assuming zero API used", self.redact_api_key(api_key))
                    self._api_limit[api_key] = quota[spl]
                    self._api_used[api_key] = 0
                    await self.write_api_usage_cache_file(api_key, reset=True)
                _LOGGER.debug("API counter for %s is %d/%d", self.redact_api_key(api_key), self._api_used[api_key], self._api_limit[api_key])
        except Exception as e:
            _LOGGER.error("Exception in sites_usage(): %s: %s", e, traceback.format_exc())

    '''
    async def sites_usage(self):
        """Load api usage"""

        try:
            sp = self.options.api_key.split(",")

            for spl in sp:
                api_key = spl.strip()
                params = {"api_key": api_key}
                _LOGGER.debug("Getting API limit and usage from solcast for %s", self.redact_api_key(api_key))
                async with async_timeout.timeout(60):
                    api_cache_filename = self.get_api_usage_cache_filename(api_key)
                    _LOGGER.debug("%s", 'API usage cache ' + ('exists' if file_exists(api_cache_filename) else 'does not yet exist'))
                    retries = 3
                    retry = retries
                    success = False
                    use_cache_immediate = False
                    cache_exists = file_exists(api_cache_filename)
                    while retry > 0:
                        resp: ClientResponse = await self.aiohttp_session.get(
                            url=f"{self.options.host}/json/reply/GetUserUsageAllowance", params=params, ssl=False
                        )
                        status = resp.status
                        try:
                            resp_json = await resp.json(content_type=None)
                        except json.decoder.JSONDecodeError:
                            _LOGGER.error("JSONDecodeError in sites_usage() - Solcast site could be having problems")
                        except: raise
                        _LOGGER.debug("HTTP session returned status %s in sites_usage()", translate(status))
                        if status == 200:
                            d = cast(dict, resp_json)
                            self._api_limit[api_key] = d.get("daily_limit", None)
                            self._api_used[api_key] = d.get("daily_limit_consumed", None)
                            await self.write_api_usage_cache_file(api_key)
                            retry = 0
                            success = True
                        else:
                            if cache_exists:
                                use_cache_immediate = True
                                break
                            _LOGGER.debug("Will retry GetUserUsageAllowance, retry %d", (retries - retry) + 1)
                            await asyncio.sleep(5)
                            retry -= 1
                    if not success:
                        if not use_cache_immediate:
                            _LOGGER.warning("Timeout getting Solcast API usage allowance, last call result: %s, using cached data if it exists", translate(status))
                        status = 404
                        if cache_exists:
                            async with aiofiles.open(api_cache_filename) as f:
                                resp_json = json.loads(await f.read())
                                status = 200
                            d = cast(dict, resp_json)
                            self._api_limit[api_key] = d.get("daily_limit", None)
                            self._api_used[api_key] = d.get("daily_limit_consumed", None)
                            _LOGGER.info("Loaded API usage cache")
                        else:
                            _LOGGER.warning("No Solcast API usage cache found")

                if status == 200:
                    _LOGGER.debug("API counter for %s is %d/%d", self.redact_api_key(api_key), self._api_used[api_key], self._api_limit[api_key])
                else:
                    self._api_limit[api_key] = 10
                    self._api_used[api_key] = 0
                    await self.write_api_usage_cache_file(api_key)
                    raise Exception(f"Gathering site usage failed in sites_usage(). Request returned Status code: {translate(status)} - Response: {resp_json}.")

        except json.decoder.JSONDecodeError:
            _LOGGER.error("JSONDecodeError in sites_usage(): Solcast site could be having problems")
        except ConnectionRefusedError as e:
            _LOGGER.error("Error in sites_usage(): %s", e)
        except ClientConnectionError as e:
            _LOGGER.error('Connection error in sites_usage(): %s', e)
        except asyncio.TimeoutError:
            _LOGGER.error("Connection error in sites_usage(): Timed out connecting to solcast server")
        except Exception as e:
            _LOGGER.error("Exception in sites_usage(): %s", traceback.format_exc())
    '''

    '''
    async def sites_weather(self):
        """Request site weather byline"""

        try:
            if len(self._sites) > 0:
                sp = self.options.api_key.split(",")
                rid = self._sites[0].get("resource_id", None)

                params = {"resourceId": rid, "api_key": sp[0]}
                _LOGGER.debug("Get weather byline")
                async with async_timeout.timeout(60):
                    resp: ClientResponse = await self.aiohttp_session.get(
                        url=f"https://api.solcast.com.au/json/reply/GetRooftopSiteSparklines", params=params, ssl=False
                    )
                    resp_json = await resp.json(content_type=None)
                    status = resp.status

                if status == 200:
                    d = cast(dict, resp_json)
                    _LOGGER.debug("Returned data in sites_weather(): %s", str(d))
                    self._weather = d.get("forecast_descriptor", None).get("description", None)
                    _LOGGER.debug("Weather description: %s", self._weather)
                else:
                    raise Exception(f"Gathering weather description failed. request returned Status code: {translate(status)} - Response: {resp_json}.")

        except json.decoder.JSONDecodeError:
            _LOGGER.error("JSONDecodeError in sites_weather(): Solcast site could be having problems")
        except ConnectionRefusedError as e:
            _LOGGER.error("Error in sites_weather(): %s", e)
        except ClientConnectionError as e:
            _LOGGER.error("Connection error in sites_weather(): %s", e)
        except asyncio.TimeoutError:
            _LOGGER.error("Connection Error in sites_weather(): Timed out connection to solcast server")
        except Exception as e:
            _LOGGER.error("Error in sites_weather(): %s", traceback.format_exc())
    '''

    async def load_saved_data(self):
        """Load the saved solcast.json data, also checking for new API keys and site removal"""
        try:
            status = ''
            if len(self._sites) > 0:
                if file_exists(self._filename):
                    async with aiofiles.open(self._filename) as data_file:
                        json_data = json.loads(await data_file.read(), cls=JSONDecoder)
                        json_version = json_data.get("version", 1)
                        #self._weather = json_data.get("weather", "unknown")
                        _LOGGER.debug("Data cache exists, file type is %s", type(json_data))
                        if json_version == _JSON_VERSION:
                            self._data = json_data
                            self._loaded_data = True

                            # Check for any new API keys so no sites data yet for those
                            ks = {}
                            for d in self._sites:
                                if not any(s == d.get('resource_id', '') for s in json_data['siteinfo']):
                                    ks[d.get('resource_id')] = d.get('apikey')

                            if len(ks.keys()) > 0:
                                # Some site data does not exist yet so get it
                                _LOGGER.info("New site(s) have been added, so getting forecast data for just those site(s)")
                                for a, _api_key in ks:
                                    await self.http_data_call(r_id=a, api=_api_key, dopast=True)
                                await self.serialize_data()

                            # Check for sites that need to be removed
                            l = []
                            for s in json_data['siteinfo']:
                                if not any(d.get('resource_id', '') == s for d in self._sites):
                                    _LOGGER.info("Solcast site resource id %s is no longer configured, removing saved data from cached file", s)
                                    l.append(s)

                            for ll in l:
                                del json_data['siteinfo'][ll]

                            # Create an up to date forecast
                            await self.buildforecastdata()
                            _LOGGER.info("Data loaded")

                if not self._loaded_data:
                    # No file to load
                    _LOGGER.warning("There is no solcast.json to load, so fetching solar forecast, including past forecasts")
                    # Could be a brand new install of the integation, or the file has been removed. Poll once now...
                    status = await self.http_data(dopast=True)
            else:
                _LOGGER.error("Solcast site count is zero in load_saved_data(); the get sites must have failed, and there is no sites cache")
                status = 'Solcast sites count is zero, add sites'
        except json.decoder.JSONDecodeError:
            _LOGGER.error("The cached data in solcast.json is corrupt in load_saved_data()")
            status = 'The cached data in /config/solcast.json is corrupted, suggest removing or repairing it'
        except Exception as e:
            _LOGGER.error("Exception in load_saved_data(): %s", traceback.format_exc())
            status = f"Exception in load_saved_data(): {e}"
        return status

    async def delete_solcast_file(self, *args): # pylint: disable=W0613
        """Service event to delete old solcast.json file"""
        _LOGGER.debug("Service event to delete old solcast.json file")
        try:
            if file_exists(self._filename):
                os.remove(self._filename)
                await self.sites_data()
                await self.sites_usage()
                await self.load_saved_data()
            else:
                _LOGGER.warning("There is no solcast.json to delete")
        except Exception:
            _LOGGER.error("Service event to delete old solcast.json file failed")

    async def get_forecast_list(self, *args):
        """Service event to get list of forecasts"""
        try:
            st_time = time.time()

            st_i, end_i = self.get_forecast_list_slice(self._data_forecasts, args[0], args[1], search_past=True)
            h = self._data_forecasts[st_i:end_i]

            if _SENSOR_DEBUG_LOGGING: _LOGGER.debug(
                "Get forecast list: (%ss) st %s end %s st_i %d end_i %d h.len %d",
                round(time.time()-st_time,4), args[0], args[1], st_i, end_i, len(h)
            )

            return tuple( {**d, "period_start": d["period_start"].astimezone(self._tz)} for d in h )

        except Exception:
            _LOGGER.error("Service event to get list of forecasts failed")
            return None

    def get_api_used_count(self):
        """Return total API polling count for this UTC 24hr period (all accounts combined)"""
        used = 0
        for _, v in self._api_used.items():
            used += v
        return used

    def get_api_limit(self):
        """Return API polling limit (all accounts combined)"""
        limit = 0
        for _, v in self._api_limit.items():
            limit += v
        return limit

    # def get_weather(self):
    #     """Return weather description"""
    #     return self._weather

    def get_last_updated_datetime(self) -> dt:
        """Return when the data was last updated"""
        return dt.fromisoformat(self._data["last_updated"])

    def get_rooftop_site_total_today(self, site) -> float:
        """Return total kW for today for a site"""
        if self._tally.get(site) is None:
            _LOGGER.warning("Site total kW forecast today is currently unavailable for %s", site)
        return self._tally.get(site)

    def get_rooftop_site_extra_data(self, site = ""):
        """Return information about a site"""
        g = tuple(d for d in self._sites if d["resource_id"] == site)
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

    def get_now_utc(self):
        """Datetime helper"""
        return dt.now(self._tz).replace(second=0, microsecond=0).astimezone(timezone.utc)

    def get_real_now_utc(self):
        """Datetime helper"""
        return dt.now(self._tz).astimezone(timezone.utc)

    def get_interval_start_utc(self, moment):
        """Datetime helper"""
        n = moment.replace(second=0, microsecond=0)
        return n.replace(minute=0 if n.minute < 30 else 30).astimezone(timezone.utc)

    def get_hour_start_utc(self):
        """Datetime helper"""
        return dt.now(self._tz).replace(minute=0, second=0, microsecond=0).astimezone(timezone.utc)

    def get_day_start_utc(self):
        """Datetime helper"""
        return dt.now(self._tz).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)

    def get_forecast_day(self, futureday) -> Dict[str, Any]:
        """Return forecast data for the Nth day ahead"""
        no_data_error = True

        start_utc = self.get_day_start_utc() + timedelta(days=futureday)
        end_utc = start_utc + timedelta(days=1)
        st_i, end_i = self.get_forecast_list_slice(self._data_forecasts, start_utc, end_utc)
        h = self._data_forecasts[st_i:end_i]

        if _SENSOR_DEBUG_LOGGING: _LOGGER.debug(
            "Get forecast day: %d st %s end %s st_i %d end_i %d h.len %d",
            futureday,
            start_utc.strftime('%Y-%m-%d %H:%M:%S'), end_utc.strftime('%Y-%m-%d %H:%M:%S'),
            st_i, end_i, len(h)
        )

        tup = tuple( {**d, "period_start": d["period_start"].astimezone(self._tz)} for d in h )

        if len(tup) < 48:
            no_data_error = False

        hourlytup = []
        for index in range(0,len(tup),2):
            if len(tup) > 0:
                try:
                    x1 = round((tup[index]["pv_estimate"] + tup[index+1]["pv_estimate"]) /2, 4)
                    x2 = round((tup[index]["pv_estimate10"] + tup[index+1]["pv_estimate10"]) /2, 4)
                    x3 = round((tup[index]["pv_estimate90"] + tup[index+1]["pv_estimate90"]) /2, 4)
                    hourlytup.append({"period_start":tup[index]["period_start"], "pv_estimate":x1, "pv_estimate10":x2, "pv_estimate90":x3})
                except IndexError:
                    x1 = round((tup[index]["pv_estimate"]), 4)
                    x2 = round((tup[index]["pv_estimate10"]), 4)
                    x3 = round((tup[index]["pv_estimate90"]), 4)
                    hourlytup.append({"period_start":tup[index]["period_start"], "pv_estimate":x1, "pv_estimate10":x2, "pv_estimate90":x3})
                except Exception as e:
                    _LOGGER.error("Exception in get_forecast_day(): %s", e)
                    _LOGGER.error(traceback.format_exc())

        res = {
            "dayname": start_utc.astimezone(self._tz).strftime("%A"),
            "dataCorrect": no_data_error,
        }
        if self.options.attr_brk_halfhourly:
            res["detailedForecast"] = tup
        if self.options.attr_brk_hourly:
            res["detailedHourly"] = hourlytup
        return res

    def get_forecast_n_hour(self, n_hour, site=None, _use_data_field=None) -> int:
        """Return forecast for the Nth hour"""
        start_utc = self.get_hour_start_utc() + timedelta(hours=n_hour)
        end_utc = start_utc + timedelta(hours=1)
        res = round(500 * self.get_forecast_pv_estimates(start_utc, end_utc, site=site, _use_data_field=_use_data_field))
        return res

    def get_forecasts_n_hour(self, n_hour) -> Dict[str, Any]:
        """Return forecast for the Nth hour for all sites and individual sites"""
        res = {}
        if self.options.attr_brk_site:
            for site in self._sites:
                res[site['resource_id']] = self.get_forecast_n_hour(n_hour, site=site['resource_id'])
                for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
                    if self._estimen.get(_data_field):
                        res[_data_field.replace('pv_','')+'-'+site['resource_id']] = self.get_forecast_n_hour(n_hour, site=site['resource_id'], _use_data_field=_data_field)
        for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
            if self._estimen.get(_data_field):
                res[_data_field.replace('pv_','')] = self.get_forecast_n_hour(n_hour, _use_data_field=_data_field)
        return res

    def get_forecast_custom_hours(self, n_hours, site=None, _use_data_field=None) -> int:
        """Return forecast for the next N hours"""
        start_utc = self.get_now_utc()
        end_utc = start_utc + timedelta(hours=n_hours)
        res = round(1000 * self.get_forecast_pv_remaining(start_utc, end_utc=end_utc, site=site, _use_data_field=_use_data_field))
        return res

    def get_forecasts_custom_hours(self, n_hour) -> Dict[str, Any]:
        """Return forecast for the next N hours for all sites and individual sites"""
        res = {}
        if self.options.attr_brk_site:
            for site in self._sites:
                res[site['resource_id']] = self.get_forecast_custom_hours(n_hour, site=site['resource_id'])
                for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
                    if self._estimen.get(_data_field):
                        res[_data_field.replace('pv_','')+'-'+site['resource_id']] = self.get_forecast_custom_hours(n_hour, site=site['resource_id'], _use_data_field=_data_field)
        for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
            if self._estimen.get(_data_field):
                res[_data_field.replace('pv_','')] = self.get_forecast_custom_hours(n_hour, _use_data_field=_data_field)
        return res

    def get_power_n_mins(self, n_mins, site=None, _use_data_field=None) -> int:
        """Return expected power generation in the next N minutes"""
        time_utc = self.get_now_utc() + timedelta(minutes=n_mins)
        return round(1000 * self.get_forecast_pv_moment(time_utc, site=site, _use_data_field=_use_data_field))

    def get_sites_power_n_mins(self, n_mins) -> Dict[str, Any]:
        """Return expected power generation in the next N minutes for all sites and individual sites"""
        res = {}
        if self.options.attr_brk_site:
            for site in self._sites:
                res[site['resource_id']] = self.get_power_n_mins(n_mins, site=site['resource_id'])
                for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
                    if self._estimen.get(_data_field):
                        res[_data_field.replace('pv_','')+'-'+site['resource_id']] = self.get_power_n_mins(n_mins, site=site['resource_id'], _use_data_field=_data_field)
        for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
            if self._estimen.get(_data_field):
                res[_data_field.replace('pv_','')] = self.get_power_n_mins(n_mins, site=None, _use_data_field=_data_field)
        return res

    def get_peak_w_day(self, n_day, site=None, _use_data_field=None) -> int:
        """Return max kW for site N days ahead"""
        _data_field = self._use_data_field if _use_data_field is None else _use_data_field
        start_utc = self.get_day_start_utc() + timedelta(days=n_day)
        end_utc = start_utc + timedelta(days=1)
        res = self.get_max_forecast_pv_estimate(start_utc, end_utc, site=site, _use_data_field=_data_field)
        return 0 if res is None else round(1000 * res[_data_field])

    def get_sites_peak_w_day(self, n_day) -> Dict[str, Any]:
        """Return max kW for site N days ahead for all sites and individual sites"""
        res = {}
        if self.options.attr_brk_site:
            for site in self._sites:
                res[site['resource_id']] = self.get_peak_w_day(n_day, site=site['resource_id'])
                for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
                    if self._estimen.get(_data_field):
                        res[_data_field.replace('pv_','')+'-'+site['resource_id']] = self.get_peak_w_day(n_day, site=site['resource_id'], _use_data_field=_data_field)
        for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
            if self._estimen.get(_data_field):
                res[_data_field.replace('pv_','')] = self.get_peak_w_day(n_day, site=None, _use_data_field=_data_field)
        return res

    def get_peak_w_time_day(self, n_day, site=None, _use_data_field=None) -> dt:
        """Return hour of max kW for site N days ahead"""
        start_utc = self.get_day_start_utc() + timedelta(days=n_day)
        end_utc = start_utc + timedelta(days=1)
        res = self.get_max_forecast_pv_estimate(start_utc, end_utc, site=site, _use_data_field=_use_data_field)
        return res if res is None else res["period_start"]

    def get_sites_peak_w_time_day(self, n_day) -> Dict[str, Any]:
        """Return hour of max kW for site N days ahead for all sites and individual sites"""
        res = {}
        if self.options.attr_brk_site:
            for site in self._sites:
                res[site['resource_id']] = self.get_peak_w_time_day(n_day, site=site['resource_id'])
                for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
                    if self._estimen.get(_data_field):
                        res[_data_field.replace('pv_','')+'-'+site['resource_id']] = self.get_peak_w_time_day(n_day, site=site['resource_id'], _use_data_field=_data_field)
        for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
            if self._estimen.get(_data_field):
                res[_data_field.replace('pv_','')] = self.get_peak_w_time_day(n_day, site=None, _use_data_field=_data_field)
        return res

    def get_forecast_remaining_today(self, site=None, _use_data_field=None) -> float:
        """Return remaining forecasted production for today"""
        # time remaining today
        start_utc = self.get_now_utc()
        end_utc = self.get_day_start_utc() + timedelta(days=1)
        res = round(self.get_forecast_pv_remaining(start_utc, end_utc=end_utc, site=site, _use_data_field=_use_data_field), 4)
        return res

    def get_forecasts_remaining_today(self) -> Dict[str, Any]:
        """Return remaining forecasted production for today for all sites and individual sites"""
        res = {}
        if self.options.attr_brk_site:
            for site in self._sites:
                res[site['resource_id']] = self.get_forecast_remaining_today(site=site['resource_id'])
                for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
                    if self._estimen.get(_data_field):
                        res[_data_field.replace('pv_','')+'-'+site['resource_id']] = self.get_forecast_remaining_today(site=site['resource_id'], _use_data_field=_data_field)
        for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
            if self._estimen.get(_data_field):
                res[_data_field.replace('pv_','')] = self.get_forecast_remaining_today(_use_data_field=_data_field)
        return res

    def get_total_kwh_forecast_day(self, n_day, site=None, _use_data_field=None) -> float:
        """Return forecast kWh total for site N days ahead"""
        start_utc = self.get_day_start_utc() + timedelta(days=n_day)
        end_utc = start_utc + timedelta(days=1)
        res = round(0.5 * self.get_forecast_pv_estimates(start_utc, end_utc, site=site, _use_data_field=_use_data_field), 4)
        return res

    def get_sites_total_kwh_forecast_day(self, n_day) -> Dict[str, Any]:
        """Return forecast kWh total for site N days ahead for all sites and individual sites"""
        res = {}
        if self.options.attr_brk_site:
            for site in self._sites:
                res[site['resource_id']] = self.get_total_kwh_forecast_day(n_day, site=site['resource_id'])
                for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
                    if self._estimen.get(_data_field):
                        res[_data_field.replace('pv_','')+'-'+site['resource_id']] = self.get_total_kwh_forecast_day(n_day, site=site['resource_id'], _use_data_field=_data_field)
        for _data_field in ('pv_estimate', 'pv_estimate10', 'pv_estimate90'):
            if self._estimen.get(_data_field):
                res[_data_field.replace('pv_','')] = self.get_total_kwh_forecast_day(n_day, site=None, _use_data_field=_data_field)
        return res

    def get_forecast_list_slice(self, _data, start_utc, end_utc=None, search_past=False) -> tuple[int, int]:
        """Return pv_estimates list slice (st_i, end_i) for interval"""
        if end_utc is None:
            end_utc = start_utc + timedelta(seconds=1800)
        crt_i = -1
        st_i = -1
        end_i = len(_data)
        for crt_i in range(0 if search_past else self._forecasts_start_idx, end_i):
            d = _data[crt_i]
            d1 = d['period_start']
            d2 = d1 + timedelta(seconds=1800)
            # after the last segment
            if end_utc <= d1:
                end_i = crt_i
                break
            # first segment
            if start_utc < d2 and st_i == -1:
                st_i = crt_i
        # never found
        if st_i == -1:
            st_i = 0
            end_i = 0
        return st_i, end_i

    def get_spline(self, spline, st, xx, _data, df, reducing=False) -> None:
        """Build an individual site/forecast confidence spline"""
        for _data_field in df:
            if st > 0:
                y = [_data[st+i][_data_field] for i in range(0, len(self._spline_period))]
                if reducing:
                    # Build a decreasing set of forecasted values instead
                    y = [0.5 * sum(y[i:]) for i in range(0, len(self._spline_period))]
                spline[_data_field] = cubic_interp(xx, self._spline_period, y)
                self.sanitise_spline(spline, _data_field, xx, y, reducing=reducing)
            else: # The list slice was not found, so zero all values in the spline
                spline[_data_field] = [0] * (len(self._spline_period) * 6)
        if _SPLINE_DEBUG_LOGGING:
            _LOGGER.debug(str(spline))

    def sanitise_spline(self, spline, _data_field, xx, y, reducing=False) -> None:
        """Ensures that no negative values are returned, and also shifts the spline to account for half-hour average input values"""
        for j in xx:
            i = int(j/300)
            # Suppress negative values
            if math.copysign(1.0, spline[_data_field][i]) < 0:
                spline[_data_field][i] = 0.0
            # Suppress spline bounce
            if reducing:
                if i+1 <= len(xx)-1 and spline[_data_field][i+1] > spline[_data_field][i]:
                    spline[_data_field][i+1] = spline[_data_field][i]
            else:
                k = int(math.floor(j/1800))
                if k+1 <= len(y)-1 and y[k] == 0 and y[k+1] == 0:
                    spline[_data_field][i] = 0.0
        # Shift right by fifteen minutes because 30-minute averages, padding as appropriate
        if reducing:
            spline[_data_field] = ([spline[_data_field][0]]*3) + spline[_data_field]
        else:
            spline[_data_field] = ([0]*3) + spline[_data_field]

    def build_splines(self, variant, reducing=False) -> None:
        """Build cubic splines for interpolated inter-interval momentary or reducing estimates"""
        df = ['pv_estimate'] + (['pv_estimate10'] if self.options.attr_brk_estimate10 else []) + (['pv_estimate90'] if self.options.attr_brk_estimate90 else [])
        xx = [ i for i in range(0, 1800*len(self._spline_period), 300) ]
        st, _ = self.get_forecast_list_slice(self._data_forecasts, self.get_day_start_utc()) # Get start of day index

        variant['all'] = {}
        self.get_spline(variant['all'], st, xx, self._data_forecasts, df, reducing=reducing)
        if self.options.attr_brk_site:
            for site in self._sites:
                variant[site['resource_id']] = {}
                self.get_spline(variant[site['resource_id']], st, xx, self._data_forecasts, df, reducing=reducing)

    async def spline_moments(self) -> None:
        """Build the moments splines"""
        try:
            self.build_splines(self.fc_moment)
        except Exception as e:
            _LOGGER.debug('Exception in spline_moments(): %s', e)

    def get_moment(self, site, _data_field, t) -> float:
        """Get a time value from a moment spline, with times needing to be for today, and also on five-minute boundaries"""
        try:
            return self.fc_moment['all' if site is None else site][self._use_data_field if _data_field is None else _data_field][int(t / 300)]
        except Exception as e:
            _LOGGER.debug('Exception in get_moment(): %s', e)
            return 0

    async def spline_remaining(self) -> None:
        """Build the descending splines"""
        try:
            self.build_splines(self.fc_remaining, reducing=True)
        except Exception as e:
            _LOGGER.debug('Exception in spline_remaining(): %s', e)

    def get_remaining(self, site, _data_field, t) -> float:
        """Get a time value from a reducing spline, with times needing to be for today, and also on five-minute boundaries"""
        try:
            return self.fc_remaining['all' if site is None else site][self._use_data_field if _data_field is None else _data_field][int(t / 300)]
        except Exception as e:
            _LOGGER.debug('Exception in get_remaining(): %s', e)
            return 0

    def get_forecast_pv_remaining(self, start_utc, end_utc=None, site=None, _use_data_field=None) -> float:
        """Return pv_estimates remaining for period"""
        try:
            _data = self._data_forecasts if site is None else self._site_data_forecasts[site]
            _data_field = self._use_data_field if _use_data_field is None else _use_data_field
            start_utc = start_utc.replace(minute = math.floor(start_utc.minute / 5) * 5)
            st_i, end_i = self.get_forecast_list_slice(_data, start_utc, end_utc) # Get start and end indexes for the requested range
            day_start = self.get_day_start_utc()
            res = self.get_remaining(site, _data_field, (start_utc - day_start).total_seconds())
            if end_utc is not None:
                end_utc = end_utc.replace(minute = math.floor(end_utc.minute / 5) * 5)
                if end_utc < day_start + timedelta(seconds=1800*len(self._spline_period)):
                    # End is within today so use spline data
                    res -= self.get_remaining(site, _data_field, (end_utc - day_start).total_seconds())
                else:
                    # End is beyond today, so revert to simple linear interpolation
                    st_i2, _ = self.get_forecast_list_slice(_data, day_start + timedelta(seconds=1800*len(self._spline_period))) # Get post-spline day onwards start index
                    for d in _data[st_i2:end_i]:
                        d2 = d['period_start'] + timedelta(seconds=1800)
                        s = 1800
                        f = 0.5 * d[_data_field]
                        if end_utc < d2:
                            s -= (d2 - end_utc).total_seconds()
                            res += f * s / 1800
                        else:
                            res += f
            if _SENSOR_DEBUG_LOGGING: _LOGGER.debug(
                "Get estimate: %s()%s %s st %s end %s st_i %d end_i %d res %s",
                currentFuncName(1), '' if site is None else ' '+site, _data_field,
                start_utc.strftime('%Y-%m-%d %H:%M:%S'),
                end_utc.strftime('%Y-%m-%d %H:%M:%S') if end_utc is not None else None,
                st_i, end_i, round(res,4)
            )
            return res if res > 0 else 0
        except Exception as e:
            _LOGGER.error("Exception in get_forecast_pv_remaining(): %s", e)
            _LOGGER.error(traceback.format_exc())
            return 0

    def get_forecast_pv_estimates(self, start_utc, end_utc, site=None, _use_data_field=None) -> float:
        """Return pv_estimates total for period"""
        try:
            _data = self._data_forecasts if site is None else self._site_data_forecasts[site]
            _data_field = self._use_data_field if _use_data_field is None else _use_data_field
            res = 0
            start_utc = start_utc.replace(minute = math.floor(start_utc.minute / 5) * 5)
            end_utc = end_utc.replace(minute = math.floor(end_utc.minute / 5) * 5)
            st_i, end_i = self.get_forecast_list_slice(_data, start_utc, end_utc) # Get start and end indexes for the requested range
            for d in _data[st_i:end_i]:
                res += d[_data_field]
            if _SENSOR_DEBUG_LOGGING: _LOGGER.debug(
                "Get estimate: %s()%s %s st %s end %s st_i %d end_i %d res %s",
                currentFuncName(1), '' if site is None else ' '+site, _data_field,
                start_utc.strftime('%Y-%m-%d %H:%M:%S'),
                end_utc.strftime('%Y-%m-%d %H:%M:%S'),
                st_i, end_i, round(res,4)
            )
            return res
        except Exception as e:
            _LOGGER.error("Exception in get_forecast_pv_estimates(): %s", e)
            _LOGGER.error(traceback.format_exc())
            return 0

    def get_forecast_pv_moment(self, time_utc, site=None, _use_data_field=None) -> float:
        """Return interpolated pv_estimates power for a point in time"""
        try:
            _data_field = self._use_data_field if _use_data_field is None else _use_data_field
            day_start = self.get_day_start_utc()
            time_utc = time_utc.replace(minute = math.floor(time_utc.minute / 5) * 5)
            res = self.get_moment(site, _data_field, (time_utc - day_start).total_seconds())
            if _SENSOR_DEBUG_LOGGING: _LOGGER.debug(
                "Get estimate moment: %s()%s %s t %s sec %d res %s",
                currentFuncName(1), '' if site is None else ' '+site, _data_field,
                time_utc.strftime('%Y-%m-%d %H:%M:%S'), (time_utc - day_start).total_seconds(), round(res, 4)
            )
            return res
        except Exception as e:
            _LOGGER.error("Exception in get_forecast_pv_moment(): %s", e)
            _LOGGER.error(traceback.format_exc())
            return 0

    def get_max_forecast_pv_estimate(self, start_utc, end_utc, site=None, _use_data_field=None):
        """Return max pv_estimate for the interval"""
        try:
            _data = self._data_forecasts if site is None else self._site_data_forecasts[site]
            _data_field = self._use_data_field if _use_data_field is None else _use_data_field
            st_i, end_i = self.get_forecast_list_slice(_data, start_utc, end_utc)
            res = _data[st_i]
            for d in _data[st_i:end_i]:
                if  res[_data_field] < d[_data_field]:
                    res = d
            if _SENSOR_DEBUG_LOGGING: _LOGGER.debug(
                "Get max estimate: %s()%s %s st %s end %s st_i %d end_i %d res %s",
                currentFuncName(1), '' if site is None else ' '+site, _data_field,
                start_utc.strftime('%Y-%m-%d %H:%M:%S'),
                end_utc.strftime('%Y-%m-%d %H:%M:%S'),
                st_i, end_i, res
            )
            return res
        except Exception as e:
            _LOGGER.error("Exception in get_max_forecast_pv_estimate(): %s", e)
            _LOGGER.error(traceback.format_exc())
            return None

    def get_energy_data(self) -> dict[str, Any]:
        """Get energy data"""
        try:
            return self._dataenergy
        except Exception as e:
            _LOGGER.error("Exception in get_energy_data(): %s", e)
            _LOGGER.error(traceback.format_exc())
            return None

    async def http_data(self, dopast = False):
        """Request forecast data for all sites"""
        try:
            status = ''
            if self.get_last_updated_datetime() + timedelta(minutes=1) > dt.now(timezone.utc):
                status = f"Not requesting a forecast from Solcast because time is within one minute of last update ({self.get_last_updated_datetime().astimezone(self._tz)})"
                _LOGGER.warning(status)
                return status

            failure = False
            sites_attempted = 0
            for site in self._sites:
                sites_attempted += 1
                _LOGGER.info("Getting forecast update for Solcast site %s", site['resource_id'])
                result = await self.http_data_call(site['resource_id'], site['apikey'], dopast)
                if not result:
                    failure = True
                    if len(self._sites) > 1:
                        if sites_attempted < len(self._sites):
                            _LOGGER.warning('Forecast update for site %s failed so not getting remaining sites%s', site['resource_id'], ' - API use count may look odd' if len(self._sites) > 2 else '')
                        else:
                            _LOGGER.warning('Forecast update for the last site queued failed (%s) so not getting remaining sites - API use count may look odd', site['resource_id'])
                    else:
                        _LOGGER.warning('Forecast update for site %s failed', site['resource_id'])
                    status = 'At least one site forecast get failed'
                    break

            if sites_attempted > 0 and not failure:
                self._data["last_updated"] = dt.now(timezone.utc).isoformat()
                #self._data["weather"] = self._weather

                await self.buildforecastdata()
                self._data["version"] = _JSON_VERSION
                self._loaded_data = True

                await self.serialize_data()
            else:
                if sites_attempted > 0:
                    _LOGGER.error("At least one Solcast site forecast failed to fetch, so forecast data has not been built")
                else:
                    _LOGGER.error("No Solcast sites were attempted, so forecast data has not been built - check for earlier failure to retrieve sites")
                status = 'At least one site forecast get failed'
        except Exception as e:
            status = f"Exception in http_data(): {e} - Forecast data has not been built"
            _LOGGER.error(status)
            _LOGGER.error(traceback.format_exc())
        return status

    async def http_data_call(self, r_id = None, api = None, dopast = False):
        """Request forecast data via the Solcast API"""
        try:
            lastday = self.get_day_start_utc() + timedelta(days=8)
            numhours = math.ceil((lastday - self.get_now_utc()).total_seconds() / 3600)
            _LOGGER.debug('Polling API for site %s lastday %s numhours %d', r_id, lastday.strftime('%Y-%m-%d'), numhours)

            _data = []
            _data2 = []

            if dopast:
                # Run once, for a new install or if the solcast.json file is deleted. This will use up api call quota.
                ae = None
                resp_dict = await self.fetch_data("estimated_actuals", 168, site=r_id, apikey=api, cachedname="actuals")
                if not isinstance(resp_dict, dict):
                    _LOGGER.error('No data was returned for Solcast estimated_actuals so this WILL cause errors...')
                    _LOGGER.error('Either your API limit is exhaused, Internet down, or networking is misconfigured...')
                    _LOGGER.error('This almost certainly not a problem with the integration, and sensor values will be wrong')
                    raise TypeError(f"Solcast API did not return a json object. Returned {resp_dict}")

                ae = resp_dict.get("estimated_actuals", None)

                if not isinstance(ae, list):
                    raise TypeError(f"Estimated actuals must be a list, not {type(ae)}")

                oldest = dt.now(self._tz).replace(hour=0,minute=0,second=0,microsecond=0) - timedelta(days=6)
                oldest = oldest.astimezone(timezone.utc)

                for x in ae:
                    z = parse_datetime(x["period_end"]).astimezone(timezone.utc)
                    z = z.replace(second=0, microsecond=0) - timedelta(minutes=30)
                    if z.minute not in {0, 30}:
                        raise ValueError(
                            f"Solcast period_start minute is not 0 or 30. {z.minute}"
                        )
                    if z > oldest:
                        _data2.append(
                            {
                                "period_start": z,
                                "pv_estimate": x["pv_estimate"],
                                "pv_estimate10": 0,
                                "pv_estimate90": 0,
                            }
                        )

            resp_dict = await self.fetch_data("forecasts", numhours, site=r_id, apikey=api, cachedname="forecasts")
            if resp_dict is None:
                return False

            if not isinstance(resp_dict, dict):
                raise TypeError(f"Solcast API did not return a json object. Returned {resp_dict}")

            af = resp_dict.get("forecasts", None)
            if not isinstance(af, list):
                raise TypeError(f"forecasts must be a list, not {type(af)}")

            _LOGGER.debug("Solcast returned %d records", len(af))

            st_time = time.time()
            for x in af:
                z = parse_datetime(x["period_end"]).astimezone(timezone.utc)
                z = z.replace(second=0, microsecond=0) - timedelta(minutes=30)
                if z.minute not in {0, 30}:
                    raise ValueError(
                        f"Solcast period_start minute is not 0 or 30. {z.minute}"
                    )
                if z < lastday:
                    _data2.append(
                        {
                            "period_start": z,
                            "pv_estimate": x["pv_estimate"],
                            "pv_estimate10": x["pv_estimate10"],
                            "pv_estimate90": x["pv_estimate90"],
                        }
                    )

            _data = sorted(_data2, key=itemgetter("period_start"))
            _fcasts_dict = {}

            try:
                for x in self._data['siteinfo'][r_id]['forecasts']:
                    _fcasts_dict[x["period_start"]] = x
            except:
                pass

            _LOGGER.debug("Forecasts dictionary length %s", len(_fcasts_dict))

            for x in _data:
                #loop each site and its forecasts

                itm = _fcasts_dict.get(x["period_start"])
                if itm:
                    itm["pv_estimate"] = x["pv_estimate"]
                    itm["pv_estimate10"] = x["pv_estimate10"]
                    itm["pv_estimate90"] = x["pv_estimate90"]
                else:
                    _fcasts_dict[x["period_start"]] = {"period_start": x["period_start"],
                                                            "pv_estimate": x["pv_estimate"],
                                                            "pv_estimate10": x["pv_estimate10"],
                                                            "pv_estimate90": x["pv_estimate90"]}

            # _fcasts_dict contains all data for the site up to 730 days worth
            # Delete data that is older than two years
            pastdays = dt.now(timezone.utc).date() + timedelta(days=-730)
            _forecasts = list(filter(lambda x: x["period_start"].date() >= pastdays, _fcasts_dict.values()))

            _forecasts = sorted(_forecasts, key=itemgetter("period_start"))

            self._data['siteinfo'].update({r_id:{'forecasts': copy.deepcopy(_forecasts)}})

            _LOGGER.debug("HTTP data call processing took %.3f seconds", round(time.time() - st_time, 4))
            return True
        except Exception as e:
            _LOGGER.error("Exception in http_data_call(): %s", e)
            _LOGGER.error(traceback.format_exc())
        return False


    async def fetch_data(self, path="error", hours=168, site="", apikey="", cachedname="forcasts") -> dict[str, Any]:
        """Fetch forecast data"""
        try:
            params = {"format": "json", "api_key": apikey, "hours": hours}
            url=f"{self.options.host}/rooftop_sites/{site}/{path}"
            _LOGGER.debug("Fetch data url: %s", url)

            async with async_timeout.timeout(900):
                api_cache_filename = self._config_dir + '/' + cachedname + "_" + site + ".json"
                if self.api_cache_enabled and file_exists(api_cache_filename):
                    status = 404
                    async with aiofiles.open(api_cache_filename) as f:
                        resp_json = json.loads(await f.read())
                        status = 200
                        _LOGGER.debug("Offline cached mode enabled, loaded data for site %s", site)
                else:
                    if self._api_used[apikey] < self._api_limit[apikey]:
                        tries = 10
                        counter = 0
                        backoff = 15 # On every retry the back-off increases by (at least) fifteen seconds more than the previous back-off
                        while True:
                            _LOGGER.debug("Fetching forecast")
                            counter += 1
                            resp: ClientResponse = await self.aiohttp_session.get(
                                url=url, params=params, ssl=False
                            )
                            status = resp.status
                            if status == 200:
                                break
                            elif status == 429:
                                try:
                                    # Test for API limit exceeded {"response_status":{"error_code":"TooManyRequests","message":"You have exceeded your free daily limit.","errors":[]}}
                                    resp_json = await resp.json(content_type=None)
                                    rs = resp_json.get('response_status')
                                    if rs is not None:
                                        if rs.get('error_code') == 'TooManyRequests':
                                            status = 998
                                            self._api_used[apikey] = self._api_limit[apikey]
                                            await self.write_api_usage_cache_file(apikey)
                                            break
                                        else:
                                            status = 1000
                                            _LOGGER.warning("An unexpected error occurred: %s", rs.get('message'))
                                            break
                                except:
                                    pass
                                if counter >= tries:
                                    status = 999 # All retries have been exhausted
                                    break
                                # Solcast is busy, so delay (15 seconds * counter), plus a random number of seconds between zero and 15
                                delay = (counter * backoff) + random.randrange(0,15)
                                _LOGGER.warning("The Solcast API is busy, pausing %d seconds before retry", delay)
                                await asyncio.sleep(delay)
                            else:
                                break

                        if status == 200:
                            _LOGGER.debug("Fetch successful")

                            _LOGGER.debug("API returned data, API counter incremented from %d to %d", self._api_used[apikey], self._api_used[apikey] + 1)
                            self._api_used[apikey] += 1
                            await self.write_api_usage_cache_file(apikey)

                            resp_json = await resp.json(content_type=None)

                            if self.api_cache_enabled:
                                async with aiofiles.open(api_cache_filename, 'w') as f:
                                    await f.write(json.dumps(resp_json, ensure_ascii=False))
                        elif status == 998: # Exceeded API limit
                            _LOGGER.error("API allowed polling limit has been exceeded, API counter set to %d/%d", self._api_used[apikey], self._api_limit[apikey])
                            return None
                        elif status == 999: # Attempts exhausted
                            _LOGGER.error("API was tried %d times, but all attempts failed", tries)
                            return None
                        elif status == 1000: # An unexpected response
                            return None
                        else:
                            _LOGGER.error("API returned status %s, API used is %d/%d", translate(status), self._api_used[apikey], self._api_limit[apikey])
                            return None
                    else:
                        _LOGGER.warning("API polling limit exhausted, not getting forecast, API used is %d/%d", self._api_used[apikey], self._api_limit[apikey])
                        return None

                _LOGGER.debug("HTTP session returned data type %s", type(resp_json))
                _LOGGER.debug("HTTP session status %s", translate(status))

            if status == 429:
                _LOGGER.warning("Solcast is too busy, try again later")
            elif status == 400:
                _LOGGER.warning("Status %s: The Solcast site is likely missing capacity, please specify capacity or provide historic data for tuning", translate(status))
            elif status == 404:
                _LOGGER.error("The Solcast site cannot be found, status %s returned", translate(status))
            elif status == 200:
                d = cast(dict, resp_json)
                if _FORECAST_DEBUG_LOGGING:
                    _LOGGER.debug("HTTP session returned: %s", str(d))
                return d
                #await self.format_json_data(d)
        except ConnectionRefusedError as e:
            _LOGGER.error("Connection error in fetch_data(), connection refused: %s", e)
        except ClientConnectionError as e:
            _LOGGER.error("Connection error in fetch_data(): %s", e)
        except asyncio.TimeoutError:
            _LOGGER.error("Connection error in fetch_data(): Timed out connecting to Solcast API server")
        except:
            _LOGGER.error("Exception in fetch_data(): %s", traceback.format_exc())

        return None

    def makeenergydict(self) -> dict:
        """Make an energy-compatible dictionary"""
        wh_hours = {}
        try:
            lastv = -1
            lastk = -1
            for v in self._data_forecasts:
                d = v['period_start'].isoformat()
                if v[self._use_data_field] == 0.0:
                    if lastv > 0.0:
                        wh_hours[d] = round(v[self._use_data_field] * 500,0)
                        wh_hours[lastk] = 0.0
                    lastk = d
                    lastv = v[self._use_data_field]
                else:
                    if lastv == 0.0:
                        #add the last one
                        wh_hours[lastk] = round(lastv * 500,0)

                    wh_hours[d] = round(v[self._use_data_field] * 500,0)

                    lastk = d
                    lastv = v[self._use_data_field]
        except:
            _LOGGER.error("Exception in makeenergydict(): %s", traceback.format_exc())

        return wh_hours

    async def buildforecastdata(self):
        """Build data structures needed, adjusting if dampening or setting a hard limit"""
        try:
            today = dt.now(self._tz).date()
            yesterday = dt.now(self._tz).date() + timedelta(days=-730)
            lastday = dt.now(self._tz).date() + timedelta(days=8)

            _fcasts_dict = {}

            st_time = time.time()
            for site, siteinfo in self._data['siteinfo'].items():
                tally = 0
                _site_fcasts_dict = {}

                for x in siteinfo['forecasts']:
                    z = x["period_start"]
                    zz = z.astimezone(self._tz) #- timedelta(minutes=30)

                    # v4.0.8 added code to dampen the forecast data: (* self._damp[h])

                    if yesterday < zz.date() < lastday:
                        h = f"{zz.hour}"
                        if zz.date() == today:
                            tally += min(x[self._use_data_field] * 0.5 * self._damp[h], self._hardlimit)

                        # Add the forecast for this site to the total
                        itm = _fcasts_dict.get(z)
                        if itm:
                            itm["pv_estimate"] = min(round(itm["pv_estimate"] + (x["pv_estimate"] * self._damp[h]),4), self._hardlimit)
                            itm["pv_estimate10"] = min(round(itm["pv_estimate10"] + (x["pv_estimate10"] * self._damp[h]),4), self._hardlimit)
                            itm["pv_estimate90"] = min(round(itm["pv_estimate90"] + (x["pv_estimate90"] * self._damp[h]),4), self._hardlimit)
                        else:
                            _fcasts_dict[z] = {"period_start": z,
                                                "pv_estimate": min(round((x["pv_estimate"] * self._damp[h]),4), self._hardlimit),
                                                "pv_estimate10": min(round((x["pv_estimate10"] * self._damp[h]),4), self._hardlimit),
                                                "pv_estimate90": min(round((x["pv_estimate90"] * self._damp[h]),4), self._hardlimit)}

                        # Record the individual site forecast
                        _site_fcasts_dict[z] = {
                            "period_start": z,
                            "pv_estimate": round((x["pv_estimate"]),4),
                            "pv_estimate10": round((x["pv_estimate10"]),4),
                            "pv_estimate90": round((x["pv_estimate90"]),4),
                        }

                self._site_data_forecasts[site] = sorted(_site_fcasts_dict.values(), key=itemgetter("period_start"))

                siteinfo['tally'] = round(tally, 4)
                self._tally[site] = siteinfo['tally']

            self._data_forecasts = sorted(_fcasts_dict.values(), key=itemgetter("period_start"))

            self._forecasts_start_idx = self.calc_forecast_start_index()

            self._dataenergy = {"wh_hours": self.makeenergydict()}

            await self.check_data_records()

            _LOGGER.debug("Calculating splines")
            await self.spline_moments()
            await self.spline_remaining()

            _LOGGER.debug("Build forecast processing took %.3f seconds", round(time.time() - st_time, 4))

        except:
            _LOGGER.error("Exception in http_data(): %s", traceback.format_exc())


    def calc_forecast_start_index(self):
        """Get the start of forecasts as-at just before midnight (Doesn't stop at midnight because some sensors may need the previous interval)"""
        midnight_utc = self.get_day_start_utc()
        for idx in range(len(self._data_forecasts)-1, -1, -1): # Search in reverse (less to iterate)
            if self._data_forecasts[idx]["period_start"] < midnight_utc:
                break
        _LOGGER.debug("Calc forecast start index midnight: %s UTC, idx %d, len %d", midnight_utc.strftime('%Y-%m-%d %H:%M:%S'), idx, len(self._data_forecasts))
        return idx


    async def check_data_records(self):
        """Verify that all records are present for each day"""
        for i in range(0, 8):
            start_utc = self.get_day_start_utc() + timedelta(days=i)
            end_utc = start_utc + timedelta(days=1)
            st_i, end_i = self.get_forecast_list_slice(self._data_forecasts, start_utc, end_utc)
            num_rec = end_i - st_i

            da = dt.now(self._tz).date() + timedelta(days=i)
            if num_rec == 48:
                _LOGGER.debug("Data for %s contains all 48 records", da.strftime('%Y-%m-%d'))
            else:
                _LOGGER.debug("Data for %s contains only %d of 48 records and may produce inaccurate forecast data", da.strftime('%Y-%m-%d'), num_rec)