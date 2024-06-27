"""Solcast API."""
from __future__ import annotations

import asyncio
import aiofiles
import copy
import json
import logging
import math
import os
import sys
import time
import traceback
import random
from dataclasses import dataclass
from datetime import datetime as dt
from datetime import timedelta, timezone
from operator import itemgetter
from os.path import exists as file_exists
from typing import Any, Dict, cast

import async_timeout
from aiohttp import ClientConnectionError, ClientSession
from aiohttp.client_reqrep import ClientResponse
from isodate import parse_datetime

# for current func name, specify 0 or no argument.
# for name of caller of current func, specify 1.
# for name of caller of caller of current func, specify 2. etc.
currentFuncName = lambda n=0: sys._getframe(n + 1).f_code.co_name

_JSON_VERSION = 4
_LOGGER = logging.getLogger(__name__)

class DateTimeEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, dt):
            return o.isoformat()

class JSONDecoder(json.JSONDecoder):
    def __init__(self, *args, **kwargs):
        json.JSONDecoder.__init__(
            self, object_hook=self.object_hook, *args, **kwargs)

    def object_hook(self, obj):
        ret = {}
        for key, value in obj.items():
            if key in {'period_start'}:
                ret[key] = dt.fromisoformat(value)
            else:
                ret[key] = value
        return ret

statusTranslate = {
    329: 'Solcast too busy',
}

@dataclass
class ConnectionOptions:
    """Solcast API options for connection."""

    api_key: str
    host: str
    file_path: str
    tz: timezone
    dampening: dict
    customhoursensor: int
    key_estimate: str
    hard_limit: int


class SolcastApi:
    """Solcast API rooftop."""

    def __init__(
        self,
        aiohttp_session: ClientSession,
        options: ConnectionOptions,
        apiCacheEnabled: bool = False
    ):
        """Device init."""
        self.aiohttp_session = aiohttp_session
        self.options = options
        self.apiCacheEnabled = apiCacheEnabled
        self._sites = []
        self._data = {'siteinfo': {}, 'last_updated': dt.fromtimestamp(0, timezone.utc).isoformat()}
        self._api_used = {}
        self._api_limit = {}
        self._filename = options.file_path
        self._tz = options.tz
        self._dataenergy = {}
        self._data_forecasts = []
        self._forecasts_start_idx = 0
        self._detailedForecasts = []
        self._loaded_data = False
        self._serialize_lock = asyncio.Lock()
        self._damp =options.dampening
        self._customhoursensor = options.customhoursensor
        self._use_data_field = f"pv_{options.key_estimate}"
        self._hardlimit = options.hard_limit
        #self._weather = ""

    async def serialize_data(self):
        """Serialize data to file."""
        if not self._loaded_data:
            _LOGGER.debug(
                f"SOLCAST - serialize_data not saving data as it has not been loaded yet"
            )
            return

        async with self._serialize_lock:
            async with aiofiles.open(self._filename, "w") as f:
                 await f.write(json.dumps(self._data, ensure_ascii=False, cls=DateTimeEncoder))

    def redact_api_key(self, api_key):
        return '*'*6 + api_key[-6:]

    def redact_msg_api_key(self, msg, api_key):
        return msg.replace(api_key, self.redact_api_key(api_key))

    async def write_api_usage_cache_file(self, json_file, json_content, api_key):
        _LOGGER.debug(f"SOLCAST - writing API usage cache file: {self.redact_msg_api_key(json_file, api_key)}")
        async with aiofiles.open(json_file, 'w') as f:
            await f.write(json.dumps(json_content, ensure_ascii=False))

    def get_api_usage_cache_filename(self, num_entries, entry_name):
        return "/config/solcast-usage%s.json" % ("" if num_entries <= 1 else "-" + entry_name)

    async def reset_api_usage(self):
        for api_key in self._api_used.keys():
            self._api_used[api_key] = 0
            await self.write_api_usage_cache_file(
                self.get_api_usage_cache_filename(len(self._api_used), api_key),
                {"daily_limit": self._api_limit[api_key], "daily_limit_consumed": self._api_used[api_key]},
                api_key)

    async def sites_data(self):
        """Request data via the Solcast API."""

        try:
            sp = self.options.api_key.split(",")
            for spl in sp:
                #params = {"format": "json", "api_key": self.options.api_key}
                params = {"format": "json", "api_key": spl.strip()}
                async with async_timeout.timeout(60):
                    if len(sp) == 1:
                        apiCacheFileName = "/config/solcast-sites.json"
                    else:
                        apiCacheFileName = "/config/solcast-sites-%s.json" % (spl,)
                    _LOGGER.debug(f"SOLCAST apiCacheEnabled={str(self.apiCacheEnabled)}, {apiCacheFileName}={str(file_exists(apiCacheFileName))}")
                    if self.apiCacheEnabled and file_exists(apiCacheFileName):
                        _LOGGER.debug(f"SOLCAST - loading cached sites data")
                        status = 404
                        async with aiofiles.open(apiCacheFileName) as f:
                            resp_json = json.loads(await f.read())
                            status = 200
                    else:
                        _LOGGER.debug(f"SOLCAST - connecting to - {self.options.host}/rooftop_sites?format=json&api_key={self.redact_api_key(spl)}")
                        retries = 3
                        retry = retries
                        success = False
                        while retry >= 0:
                            resp: ClientResponse = await self.aiohttp_session.get(
                                url=f"{self.options.host}/rooftop_sites", params=params, ssl=False
                            )

                            status = resp.status
                            try:
                                resp_json = await resp.json(content_type=None)
                                _LOGGER.debug(f"SOLCAST - sites_data code http_session returned data type is {type(resp_json)}")
                                if statusTranslate.get(status): status = str(status) + statusTranslate[status]
                                _LOGGER.debug(f"SOLCAST - sites_data code http_session returned status {status}")
                            except json.decoder.JSONDecodeError:
                                _LOGGER.error("SOLCAST - sites_data JSONDecodeError.. The data returned from Solcast is unknown, Solcast site could be having problems")
                            except: raise

                            if status == 200:
                                _LOGGER.debug(f"SOLCAST - writing sites data cache")
                                async with aiofiles.open(apiCacheFileName, 'w') as f:
                                    await f.write(json.dumps(resp_json, ensure_ascii=False))
                                retry = -1
                                success = True
                            else:
                                if retry > 0:
                                    _LOGGER.debug(f"SOLCAST - will retry GET rooftop_sites, retry {(retries - retry) + 1}")
                                    await asyncio.sleep(5)
                                retry -= 1
                        if not success:
                            if statusTranslate.get(status): status = str(status) + statusTranslate[status]
                            _LOGGER.warning(f"SOLCAST - Retries exhausted gathering rooftop sites data, last call result: {status}, using cached data if it exists")
                            status = 404
                            if file_exists(apiCacheFileName):
                                _LOGGER.debug(f"SOLCAST - loading cached sites data")
                                async with aiofiles.open(apiCacheFileName) as f:
                                    resp_json = json.loads(await f.read())
                                    status = 200
                            else:
                                _LOGGER.error(f"SOLCAST - cached sites data is not yet available to cope with Solcast API being too busy - at least one successful API call is needed")

                if status == 200:
                    d = cast(dict, resp_json)
                    _LOGGER.debug(f"SOLCAST - sites_data: {d}")
                    for i in d['sites']:
                        i['apikey'] = spl.strip()
                        #v4.0.14 to stop HA adding a pin to the map
                        i.pop('longitude', None)
                        i.pop('latitude', None)

                    self._sites = self._sites + d['sites']
                else:
                    _LOGGER.error(
                        f"SOLCAST - sites_data Solcast.com http status Error {status} - Gathering rooftop sites data"
                    )
                    _LOGGER.error(f"SOLCAST - Solcast integration did not start correctly, as rooftop sites data is needed. Suggestion: Restart the integration")
                    raise Exception(f"SOLCAST - HTTP sites_data error: Solcast Error gathering rooftop sites data")
        except ConnectionRefusedError as err:
            _LOGGER.error("SOLCAST - sites_data ConnectionRefusedError Error.. %s",err)
        except ClientConnectionError as e:
            _LOGGER.error('SOLCAST - sites_data Connection Error', str(e))
        except asyncio.TimeoutError:
            _LOGGER.error("SOLCAST - sites_data TimeoutError Error - Timed out connection to solcast server")
        except Exception as e:
            _LOGGER.error("SOLCAST - sites_data Exception error: %s", traceback.format_exc())

    async def sites_usage(self):
        """Request api usage via the Solcast API."""

        try:
            sp = self.options.api_key.split(",")

            for spl in sp:
                sitekey = spl.strip()
                #params = {"format": "json", "api_key": self.options.api_key}
                params = {"api_key": sitekey}
                _LOGGER.debug(f"SOLCAST - getting API limit and usage from solcast for {self.redact_api_key(sitekey)}")
                async with async_timeout.timeout(60):
                    apiCacheFileName = self.get_api_usage_cache_filename(len(sp), sitekey)
                    resp: ClientResponse = await self.aiohttp_session.get(
                        url=f"https://api.solcast.com.au/json/reply/GetUserUsageAllowance", params=params, ssl=False
                    )
                    retries = 3
                    retry = retries
                    success = False
                    while retry > 0:
                        resp_json = await resp.json(content_type=None)
                        status = resp.status
                        if status == 200:
                            await self.write_api_usage_cache_file(apiCacheFileName, resp_json, sitekey)
                            retry = 0
                            success = True
                        else:
                            _LOGGER.debug(f"SOLCAST - will retry GET GetUserUsageAllowance, retry {(retries - retry) + 1}")
                            await asyncio.sleep(5)
                            retry -= 1
                    if not success:
                        if statusTranslate.get(status): status = str(status) + statusTranslate[status]
                        _LOGGER.warning(f"SOLCAST - Timeout getting usage allowance, last call result: {status}, using cached data if it exists")
                        status = 404
                        if file_exists(apiCacheFileName):
                            _LOGGER.debug(f"SOLCAST - loading cached usage")
                            async with aiofiles.open(apiCacheFileName) as f:
                                resp_json = json.loads(await f.read())
                                status = 200

                if status == 200:
                    d = cast(dict, resp_json)
                    self._api_limit[sitekey] = d.get("daily_limit", None)
                    self._api_used[sitekey] = d.get("daily_limit_consumed", None)
                    _LOGGER.debug(f"SOLCAST - API counter for {self.redact_api_key(sitekey)} is {self._api_used[sitekey]}/{self._api_limit[sitekey]}")
                else:
                    self._api_limit[sitekey] = 10
                    self._api_used[sitekey] = 0
                    raise Exception(f"SOLCAST - sites_usage: gathering site usage failed. Request returned Status code: {status} - Response: {resp_json}.")

        except json.decoder.JSONDecodeError:
            _LOGGER.error("SOLCAST - sites_usage JSONDecodeError.. The data returned from Solcast is unknown, Solcast site could be having problems")
        except ConnectionRefusedError as err:
            _LOGGER.error("SOLCAST - sites_usage Error.. %s",err)
        except ClientConnectionError as e:
            _LOGGER.error('SOLCAST - sites_usage Connection Error', str(e))
        except asyncio.TimeoutError:
            _LOGGER.error("SOLCAST - sites_usage Connection Error - Timed out connection to solcast server")
        except Exception as e:
            _LOGGER.error("SOLCAST - sites_usage error: %s", traceback.format_exc())

    # async def sites_weather(self):
    #     """Request rooftop site weather byline via the Solcast API."""

    #     try:
    #         if len(self._sites) > 0:
    #             sp = self.options.api_key.split(",")
    #             rid = self._sites[0].get("resource_id", None)

    #             params = {"resourceId": rid, "api_key": sp[0]}
    #             _LOGGER.debug(f"SOLCAST - get rooftop weather byline from solcast")
    #             async with async_timeout.timeout(60):
    #                 resp: ClientResponse = await self.aiohttp_session.get(
    #                     url=f"https://api.solcast.com.au/json/reply/GetRooftopSiteSparklines", params=params, ssl=False
    #                 )
    #                 resp_json = await resp.json(content_type=None)
    #                 status = resp.status

    #             if status == 200:
    #                 d = cast(dict, resp_json)
    #                 _LOGGER.debug(f"SOLCAST - sites_weather returned data: {d}")
    #                 self._weather = d.get("forecast_descriptor", None).get("description", None)
    #                 _LOGGER.debug(f"SOLCAST - rooftop weather description: {self._weather}")
    #             else:
    #                 raise Exception(f"SOLCAST - sites_weather: gathering rooftop weather description failed. request returned Status code: {status} - Response: {resp_json}.")

    #     except json.decoder.JSONDecodeError:
    #         _LOGGER.error("SOLCAST - sites_weather JSONDecodeError.. The rooftop weather description from Solcast is unknown, Solcast site could be having problems")
    #     except ConnectionRefusedError as err:
    #         _LOGGER.error("SOLCAST - sites_weather Error.. %s",err)
    #     except ClientConnectionError as e:
    #         _LOGGER.error('SOLCAST - sites_weather Connection Error', str(e))
    #     except asyncio.TimeoutError:
    #         _LOGGER.error("SOLCAST - sites_weather Connection Error - Timed out connection to solcast server")
    #     except Exception as e:
    #         _LOGGER.error("SOLCAST - sites_weather error: %s", traceback.format_exc())

    async def load_saved_data(self):
        try:
            if len(self._sites) > 0:
                if file_exists(self._filename):
                    async with aiofiles.open(self._filename) as data_file:
                        jsonData = json.loads(await data_file.read(), cls=JSONDecoder)
                        json_version = jsonData.get("version", 1)
                        #self._weather = jsonData.get("weather", "unknown")
                        _LOGGER.debug(f"SOLCAST - load_saved_data file exists.. file type is {type(jsonData)}")
                        if json_version == _JSON_VERSION:
                            self._loaded_data = True
                            self._data = jsonData

                            #any new API keys so no sites data yet for those
                            ks = {}
                            for d in self._sites:
                                if not any(s == d.get('resource_id', '') for s in jsonData['siteinfo']):
                                    ks[d.get('resource_id')] = d.get('apikey')

                            if len(ks.keys()) > 0:
                                #some api keys rooftop data does not exist yet so go and get it
                                _LOGGER.debug("SOLCAST - Must be new API jey added so go and get the data for it")
                                for a in ks:
                                    await self.http_data_call(r_id=a, api=ks[a], dopast=True)
                                await self.serialize_data()

                            #any site changes that need to be removed
                            l = []
                            for s in jsonData['siteinfo']:
                                if not any(d.get('resource_id', '') == s for d in self._sites):
                                    _LOGGER.info(f"Solcast rooftop resource id {s} no longer part of your system.. removing saved data from cached file")
                                    l.append(s)

                            for ll in l:
                                del jsonData['siteinfo'][ll]

                            #create an up to date forecast and make sure the TZ fits just in case its changed
                            await self.buildforecastdata()

                if not self._loaded_data:
                    #no file to load
                    _LOGGER.debug(f"SOLCAST - load_saved_data there is no existing file with saved data to load")
                    #could be a brand new install of the integation so this is poll once now automatically
                    await self.http_data(dopast=True)
            else:
                _LOGGER.debug(f"SOLCAST - load_saved_data site count is zero! ")
        except json.decoder.JSONDecodeError:
            _LOGGER.error("SOLCAST - load_saved_data error: The cached data is corrupt")
        except Exception as e:
            _LOGGER.error("SOLCAST - load_saved_data error: %s", traceback.format_exc())

    async def delete_solcast_file(self, *args):
        _LOGGER.debug(f"SOLCAST - service event to delete old solcast.json file")
        try:
            if file_exists(self._filename):
                os.remove(self._filename)
                await self.sites_data()
                await self.load_saved_data()
        except Exception:
            _LOGGER.error(f"SOLCAST - service event to delete old solcast.json file failed")

    async def get_forecast_list(self, *args):
        try:
            st_time = time.time()

            st_i, end_i = self.get_forecast_list_slice(args[0], args[1], search_past=True)
            h = self._data_forecasts[st_i:end_i]

            _LOGGER.debug("SOLCAST - get_forecast_list (%ss) st %s end %s st_i %d end_i %d h.len %d",
                            round(time.time()-st_time,4), args[0], args[1], st_i, end_i, len(h))

            return tuple(
                    {**d, "period_start": d["period_start"].astimezone(self._tz)} for d in h
                )

        except Exception:
            _LOGGER.error(f"SOLCAST - service event to get list of forecasts failed")
            return None

    def get_api_used_count(self):
        """Return API polling count for this UTC 24hr period"""
        used = 0
        for k, v in self._api_used.items(): used += v
        return used

    def get_api_limit(self):
        """Return API polling limit for this account"""
        try:
            limit = 0
            for k, v in self._api_limit.items(): limit += v
            return limit
        except Exception:
            return None

    # def get_weather(self):
    #     """Return weather description"""
    #     return self._weather

    def get_last_updated_datetime(self) -> dt:
        """Return date time with the data was last updated"""
        return dt.fromisoformat(self._data["last_updated"])

    def get_rooftop_site_total_today(self, rooftopid) -> float:
        """Return a rooftop sites total kw for today"""
        if self._data["siteinfo"][rooftopid].get("tally") == None: _LOGGER.warning(f"SOLCAST - 'Tally' is currently unavailable for rooftop {rooftopid}")
        return self._data["siteinfo"][rooftopid].get("tally")

    def get_rooftop_site_extra_data(self, rooftopid = ""):
        """Return a rooftop sites information"""
        g = tuple(d for d in self._sites if d["resource_id"] == rooftopid)
        if len(g) != 1:
            raise ValueError(f"Unable to find rooftop site {rooftopid}")
        site: Dict[str, Any] = g[0]
        ret = {}

        ret["name"] = site.get("name", None)
        ret["resource_id"] = site.get("resource_id", None)
        ret["capacity"] = site.get("capacity", None)
        ret["capacity_dc"] = site.get("capacity_dc", None)
        ret["longitude"] = site.get("longitude", None)
        ret["latitude"] = site.get("latitude", None)
        ret["azimuth"] = site.get("azimuth", None)
        ret["tilt"] = site.get("tilt", None)
        ret["install_date"] = site.get("install_date", None)
        ret["loss_factor"] = site.get("loss_factor", None)
        for key in tuple(ret.keys()):
            if ret[key] is None:
                ret.pop(key, None)

        return ret

    def get_now_utc(self):
        return dt.now(self._tz).astimezone(timezone.utc)

    def get_hour_start_utc(self):
        return dt.now(self._tz).replace(minute=0, second=0, microsecond=0).astimezone(timezone.utc)

    def get_day_start_utc(self):
        return dt.now(self._tz).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)

    def get_forecast_day(self, futureday) -> Dict[str, Any]:
        """Return Solcast Forecasts data for the Nth day ahead"""
        noDataError = True

        start_utc = self.get_day_start_utc() + timedelta(days=futureday)
        end_utc = start_utc + timedelta(days=1)
        st_i, end_i = self.get_forecast_list_slice(start_utc, end_utc)
        h = self._data_forecasts[st_i:end_i]

        _LOGGER.debug("SOLCAST - get_forecast_day %d st %s end %s st_i %d end_i %d h.len %d",
                        futureday,
                        start_utc.strftime('%Y-%m-%d %H:%M:%S'),
                        end_utc.strftime('%Y-%m-%d %H:%M:%S'),
                        st_i, end_i, len(h))

        tup = tuple(
                {**d, "period_start": d["period_start"].astimezone(self._tz)} for d in h
            )

        if len(tup) < 48:
            noDataError = False

        hourlyturp = []
        for index in range(0,len(tup),2):
            if len(tup)>0:
                try:
                    x1 = round((tup[index]["pv_estimate"] + tup[index+1]["pv_estimate"]) /2, 4)
                    x2 = round((tup[index]["pv_estimate10"] + tup[index+1]["pv_estimate10"]) /2, 4)
                    x3 = round((tup[index]["pv_estimate90"] + tup[index+1]["pv_estimate90"]) /2, 4)
                    hourlyturp.append({"period_start":tup[index]["period_start"], "pv_estimate":x1, "pv_estimate10":x2, "pv_estimate90":x3})
                except IndexError:
                    x1 = round((tup[index]["pv_estimate"]), 4)
                    x2 = round((tup[index]["pv_estimate10"]), 4)
                    x3 = round((tup[index]["pv_estimate90"]), 4)
                    hourlyturp.append({"period_start":tup[index]["period_start"], "pv_estimate":x1, "pv_estimate10":x2, "pv_estimate90":x3})

        return {
            "detailedForecast": tup,
            "detailedHourly": hourlyturp,
            "dayname": start_utc.astimezone(self._tz).strftime("%A"),
            "dataCorrect": noDataError,
        }

    def get_forecast_n_hour(self, n_hour) -> int:
        """Return Solcast Forecast for the Nth hour"""
        start_utc = self.get_hour_start_utc() + timedelta(hours=n_hour)
        end_utc = start_utc + timedelta(hours=1)
        res = round(500 * self.get_forecast_pv_estimates(start_utc, end_utc))
        return res

    def get_forecast_custom_hours(self, n_hours) -> int:
        """Return Solcast Forecast for the next N hours"""
        start_utc = self.get_now_utc()
        end_utc = start_utc + timedelta(hours=n_hours)
        res = round(500 * self.get_forecast_pv_estimates(start_utc, end_utc))
        return res

    def get_power_n_mins(self, n_mins) -> int:
        """Return Solcast Power for the next N minutes"""
        # uses a rolling 20mins interval (arbitrary decision) to smooth out the transitions between the 30mins intervals
        start_utc = self.get_now_utc() + timedelta(minutes=n_mins-10)
        end_utc = start_utc + timedelta(minutes=20)
        # multiply with 1.5 as the power reported is only for a 20mins interval (out of 30mins)
        res = round(1000 * 1.5 * self.get_forecast_pv_estimates(start_utc, end_utc))
        return res

    def get_peak_w_day(self, n_day) -> int:
        """Return max kw for rooftop site N days ahead"""
        start_utc = self.get_day_start_utc() + timedelta(days=n_day)
        end_utc = start_utc + timedelta(days=1)
        res = self.get_max_forecast_pv_estimate(start_utc, end_utc)
        return 0 if res is None else round(1000 * res[self._use_data_field])

    def get_peak_w_time_day(self, n_day) -> dt:
        """Return hour of max kw for rooftop site N days ahead"""
        start_utc = self.get_day_start_utc() + timedelta(days=n_day)
        end_utc = start_utc + timedelta(days=1)
        res = self.get_max_forecast_pv_estimate(start_utc, end_utc)
        return res if res is None else res["period_start"]

    def get_forecast_remaining_today(self) -> float:
        """Return remaining Forecasts data for today"""
        # time remaining today
        start_utc = self.get_now_utc()
        end_utc = self.get_day_start_utc() + timedelta(days=1)
        res = 0.5 * self.get_forecast_pv_estimates(start_utc, end_utc)
        return res

    def get_total_kwh_forecast_day(self, n_day) -> float:
        """Return total kwh total for rooftop site N days ahead"""
        start_utc = self.get_day_start_utc() + timedelta(days=n_day)
        end_utc = start_utc + timedelta(days=1)
        res = 0.5 * self.get_forecast_pv_estimates(start_utc, end_utc)
        return res

    def get_forecast_list_slice(self, start_utc, end_utc, search_past=False):
        """Return Solcast pv_estimates list slice [st_i, end_i) for interval [start_utc, end_utc)"""
        crt_i = -1
        st_i = -1
        end_i = len(self._data_forecasts)
        for crt_i in range(0 if search_past else self._forecasts_start_idx, end_i):
            d = self._data_forecasts[crt_i]
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

    def get_forecast_pv_estimates(self, start_utc, end_utc) -> float:
        """Return Solcast pv_estimates for interval [start_utc, end_utc)"""
        try:
            res = 0
            st_i, end_i = self.get_forecast_list_slice(start_utc, end_utc)
            for d in self._data_forecasts[st_i:end_i]:
                d1 = d['period_start']
                d2 = d1 + timedelta(seconds=1800)
                s = 1800
                f = d[self._use_data_field]
                if start_utc > d1:
                    s -= (start_utc - d1).total_seconds()
                if end_utc < d2:
                    s -= (d2 - end_utc).total_seconds()
                if s < 1800:
                    f *= s / 1800
                res += f
            _LOGGER.debug("SOLCAST - %s st %s end %s st_i %d end_i %d res %s",
                          currentFuncName(1),
                          start_utc.strftime('%Y-%m-%d %H:%M:%S'),
                          end_utc.strftime('%Y-%m-%d %H:%M:%S'),
                          st_i, end_i, round(res,3))
            return res
        except Exception as ex:
            _LOGGER.error(f"SOLCAST - get_forecast_pv_estimates: {ex}")
            return 0

    def get_max_forecast_pv_estimate(self, start_utc, end_utc):
        """Return max Solcast pv_estimate for the interval [start_utc, end_utc)"""
        try:
            res = None
            st_i, end_i = self.get_forecast_list_slice(start_utc, end_utc)
            for d in self._data_forecasts[st_i:end_i]:
                if res is None or res[self._use_data_field] < d[self._use_data_field]:
                    res = d
            _LOGGER.debug("SOLCAST - %s st %s end %s st_i %d end_i %d res %s",
                          currentFuncName(1),
                          start_utc.strftime('%Y-%m-%d %H:%M:%S'),
                          end_utc.strftime('%Y-%m-%d %H:%M:%S'),
                          st_i, end_i, res)
            return res
        except Exception as ex:
            _LOGGER.error(f"SOLCAST - get_max_forecast_pv_estimate: {ex}")
            return None

    def get_energy_data(self) -> dict[str, Any]:
        try:
            return self._dataenergy
        except Exception as e:
            _LOGGER.error(f"SOLCAST - get_energy_data: {e}")
            return None

    async def http_data(self, dopast = False):
        """Request forecast data via the Solcast API."""
        if self.get_last_updated_datetime() + timedelta(minutes=15) > dt.now(timezone.utc):
            _LOGGER.warning(f"SOLCAST - not requesting forecast because time is within fifteen minutes of last update ({self.get_last_updated_datetime().astimezone(self._tz)})")
            return

        failure = False
        for site in self._sites:
            _LOGGER.debug(f"SOLCAST - API polling for rooftop {site['resource_id']}")
            #site=site['resource_id'], apikey=site['apikey'],
            usageCacheFileName = self.get_api_usage_cache_filename(len(self._sites), site['apikey'])
            result = await self.http_data_call(usageCacheFileName, site['resource_id'], site['apikey'], dopast)
            if not result:
                failure = True

        self._data["version"] = _JSON_VERSION
        if not failure:
            self._data["last_updated"] = dt.now(timezone.utc).isoformat()
            #await self.sites_usage()
            #self._data["weather"] = self._weather
            self._loaded_data = True

        await self.buildforecastdata()
        await self.serialize_data()

    async def http_data_call(self, usageCacheFileName, r_id = None, api = None, dopast = False):
        """Request forecast data via the Solcast API."""
        lastday = self.get_day_start_utc() + timedelta(days=8)
        numhours = math.ceil((lastday - self.get_now_utc()).total_seconds() / 3600)
        _LOGGER.debug(f"SOLCAST - Polling API for rooftop_id {r_id} lastday {lastday} numhours {numhours}")

        _data = []
        _data2 = []

        # This is run once, for a new install or if the solcast.json file is deleted
        # This does use up an api call count too
        if dopast:
            ae = None
            resp_dict = await self.fetch_data(usageCacheFileName, "estimated_actuals", 168, site=r_id, apikey=api, cachedname="actuals")
            if not isinstance(resp_dict, dict):
                _LOGGER.error(
                    f"SOLCAST - No data was returned for estimated_actuals so this WILL cause errors... "
                    f"Either your limit is exhaused, internet down, what ever the case is it is "
                    f"NOT a problem with the integration, and all other problems of sensor values being wrong will be seen"
                )
                raise TypeError(f"Solcast API did not return a json object. Returned {resp_dict}")

            ae = resp_dict.get("estimated_actuals", None)

            if not isinstance(ae, list):
                raise TypeError(f"estimated actuals must be a list, not {type(ae)}")

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

        resp_dict = await self.fetch_data(usageCacheFileName, "forecasts", numhours, site=r_id, apikey=api, cachedname="forecasts")
        if resp_dict is None:
            return False

        if not isinstance(resp_dict, dict):
            raise TypeError(f"Solcast API did not return a json object. Returned {resp_dict}")

        af = resp_dict.get("forecasts", None)
        if not isinstance(af, list):
            raise TypeError(f"forecasts must be a list, not {type(af)}")

        _LOGGER.debug(f"SOLCAST - Solcast returned {len(af)} records")

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

        _LOGGER.debug("SOLCAST - http_data_call _fcasts_dict len %s", len(_fcasts_dict))

        for x in _data:
            #loop each rooftop site and its forecasts
            
            itm = _fcasts_dict.get(x["period_start"])
            if itm:
                itm["pv_estimate"] = x["pv_estimate"]
                itm["pv_estimate10"] = x["pv_estimate10"]
                itm["pv_estimate90"] = x["pv_estimate90"]
            else:
                # _LOGGER.debug("adding itm")
                _fcasts_dict[x["period_start"]] = {"period_start": x["period_start"],
                                                        "pv_estimate": x["pv_estimate"],
                                                        "pv_estimate10": x["pv_estimate10"],
                                                        "pv_estimate90": x["pv_estimate90"]}
        
        #_fcasts_dict now contains all data for the rooftop site up to 730 days worth
        #this deletes data that is older than 730 days (2 years)   
        pastdays = dt.now(timezone.utc).date() + timedelta(days=-730)
        _forecasts = list(filter(lambda x: x["period_start"].date() >= pastdays, _fcasts_dict.values()))
    
        _forecasts = sorted(_forecasts, key=itemgetter("period_start"))

        self._data['siteinfo'].update({r_id:{'forecasts': copy.deepcopy(_forecasts)}})

        _LOGGER.info(f"SOLCAST - http_data_call processing took {round(time.time()-st_time,4)}s")
        return True


    async def fetch_data(self, usageCacheFileName, path= "error", hours=168, site="", apikey="", cachedname="forcasts") -> dict[str, Any]:
        """fetch data via the Solcast API."""

        try:
            params = {"format": "json", "api_key": apikey, "hours": hours}
            url=f"{self.options.host}/rooftop_sites/{site}/{path}"
            _LOGGER.debug(f"SOLCAST - fetch_data code url - {url}")

            async with async_timeout.timeout(480):
                apiCacheFileName = '/config/' + cachedname + "_" + site + ".json"
                if self.apiCacheEnabled and file_exists(apiCacheFileName):
                    _LOGGER.debug(f"SOLCAST - Getting cached testing data for site {site}")
                    status = 404
                    async with aiofiles.open(apiCacheFileName) as f:
                        resp_json = json.loads(await f.read())
                        status = 200
                        _LOGGER.debug(f"SOLCAST - Got cached file data for site {site}")
                else:
                    if self._api_used[apikey] < self._api_limit[apikey]:
                        tries = 5
                        counter = 1
                        backoff = 30
                        while counter <= 5:
                            _LOGGER.info(f"SOLCAST - Fetching forecast")
                            resp: ClientResponse = await self.aiohttp_session.get(
                                url=url, params=params, ssl=False
                            )
                            status = resp.status
                            if status == 200: break
                            if status == 429:
                                # Solcast is busy, so delay (30 seconds * counter), plus a random number of seconds between zero and 30
                                delay = (counter * backoff) + random.randrange(0,30)
                                _LOGGER.warning(f"SOLCAST - Solcast API is busy, pausing {delay} seconds before retry")
                                await asyncio.sleep(delay)
                                counter += 1

                        if status == 200:
                            _LOGGER.info(f"SOLCAST - Fetch successful")

                            _LOGGER.debug(f"SOLCAST - API returned data. API Counter incremented from {self._api_used[apikey]} to {self._api_used[apikey] + 1}")
                            self._api_used[apikey] = self._api_used[apikey] + 1
                            await self.write_api_usage_cache_file(usageCacheFileName,
                                {"daily_limit": self._api_limit[apikey], "daily_limit_consumed": self._api_used[apikey]},
                                apikey)

                            resp_json = await resp.json(content_type=None)

                            if self.apiCacheEnabled:
                                async with aiofiles.open(apiCacheFileName, 'w') as f:
                                    await f.write(json.dumps(resp_json, ensure_ascii=False))
                        else:
                            _LOGGER.warning(f"SOLCAST - API returned status {status}. API used {self._api_used[apikey]} to {self._api_used[apikey] + 1}")
                            _LOGGER.warning("This is an error with the data returned from Solcast, not the integration")
                    else:
                        _LOGGER.warning(f"SOLCAST - API limit exceeded, not getting forecast")
                        return None

                _LOGGER.debug(f"SOLCAST - fetch_data code http_session returned data type is {type(resp_json)}")
                _LOGGER.debug(f"SOLCAST - fetch_data code http_session status is {status}")

            if status == 429:
                _LOGGER.warning("SOLCAST - Exceeded Solcast API allowed polling limit, or Solcast is too busy - API used is {self._api_used[apikey]}/{self._api_limit[apikey]}")
            elif status == 400:
                _LOGGER.warning(
                    "SOLCAST - The rooftop site missing capacity, please specify capacity or provide historic data for tuning."
                )
            elif status == 404:
                _LOGGER.warning("SOLCAST - Error 404. The rooftop site cannot be found or is not accessible.")
            elif status == 200:
                d = cast(dict, resp_json)
                _LOGGER.debug(f"SOLCAST - fetch_data Returned: {d}")
                return d
                #await self.format_json_data(d)
        except ConnectionRefusedError as err:
            _LOGGER.error("SOLCAST - Error. Connection Refused. %s",err)
        except ClientConnectionError as e:
            _LOGGER.error('SOLCAST - Connection Error', str(e))
        except asyncio.TimeoutError:
            _LOGGER.error("SOLCAST - Connection Timeout Error - Timed out connectng to Solcast API server")
        except Exception as e:
            _LOGGER.error("SOLCAST - fetch_data error: %s", traceback.format_exc())

        return None

    def makeenergydict(self) -> dict:
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
        except Exception as e:
            _LOGGER.error("SOLCAST - makeenergydict: %s", traceback.format_exc())

        return wh_hours

    async def buildforecastdata(self):
        """build the data needed and convert where needed"""
        try:
            today = dt.now(self._tz).date()
            yesterday = dt.now(self._tz).date() + timedelta(days=-730)
            lastday = dt.now(self._tz).date() + timedelta(days=8)

            _fcasts_dict = {}

            st_time = time.time()
            for s, siteinfo in self._data['siteinfo'].items():
                tally = 0
                for x in siteinfo['forecasts']:
                    #loop each rooftop site and its forecasts
                    z = x["period_start"]
                    zz = z.astimezone(self._tz) #- timedelta(minutes=30)

                    #v4.0.8 added code to dampen the forecast data.. (* self._damp[h])

                    if yesterday < zz.date() < lastday:
                        h = f"{zz.hour}"
                        if zz.date() == today:
                            tally += min(x[self._use_data_field] * 0.5 * self._damp[h], self._hardlimit)

                        itm = _fcasts_dict.get(z)
                        if itm:
                            itm["pv_estimate"] = min(round(itm["pv_estimate"] + (x["pv_estimate"] * self._damp[h]),4), self._hardlimit)
                            itm["pv_estimate10"] = min(round(itm["pv_estimate10"] + (x["pv_estimate10"] * self._damp[h]),4), self._hardlimit)
                            itm["pv_estimate90"] = min(round(itm["pv_estimate90"] + (x["pv_estimate90"] * self._damp[h]),4), self._hardlimit)
                        else:
                            _fcasts_dict[z] = {"period_start": z,
                                                "pv_estimate": min(round((x["pv_estimate"]* self._damp[h]),4), self._hardlimit),
                                                "pv_estimate10": min(round((x["pv_estimate10"]* self._damp[h]),4), self._hardlimit),
                                                "pv_estimate90": min(round((x["pv_estimate90"]* self._damp[h]),4), self._hardlimit)}

                siteinfo['tally'] = round(tally, 4)

            self._data_forecasts = sorted(_fcasts_dict.values(), key=itemgetter("period_start"))

            self._forecasts_start_idx = self.calcForecastStartIndex()

            self._dataenergy = {"wh_hours": self.makeenergydict()}

            await self.checkDataRecords()

            _LOGGER.info(f"SOLCAST - buildforecastdata processing took {round(time.time()-st_time,4)}s")

        except Exception as e:
            _LOGGER.error("SOLCAST - http_data error: %s", traceback.format_exc())


    def calcForecastStartIndex(self):
        midnight_utc = self.get_day_start_utc()
        # search in reverse (less to iterate) and find the interval just before midnight
        # we could stop at midnight but some sensors might need the previous interval
        for idx in range(len(self._data_forecasts)-1, -1, -1):
            if self._data_forecasts[idx]["period_start"] < midnight_utc: break
        _LOGGER.debug("SOLCAST - calcForecastStartIndex midnight_utc %s, idx %s, len %s", midnight_utc, idx, len(self._data_forecasts))
        return idx


    async def checkDataRecords(self):
        for i in range(0,8):
            start_utc = self.get_day_start_utc() + timedelta(days=i)
            end_utc = start_utc + timedelta(days=1)
            st_i, end_i = self.get_forecast_list_slice(start_utc, end_utc)
            num_rec = end_i - st_i

            da = dt.now(self._tz).date() + timedelta(days=i)
            if num_rec == 48:
                _LOGGER.debug(f"SOLCAST - Data for {da} contains all 48 records")
            else:
                _LOGGER.debug(f"SOLCAST - Data for {da} contains only {num_rec} of 48 records and may produce inaccurate forecast data")
