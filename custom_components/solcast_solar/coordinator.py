"""The Solcast Solar integration."""
from __future__ import annotations
from datetime import datetime as dt

import logging
import traceback

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_utc_time_change

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .solcastapi import SolcastApi

_LOGGER = logging.getLogger(__name__)

class SolcastUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from Solcast Solar API."""

    def __init__(self, hass: HomeAssistant, solcast: SolcastApi, version: str) -> None:
        """Initialize."""
        self.solcast = solcast
        self._hass = hass
        self._previousenergy = None
        self._version = version
        self._lastDay = None
        self._dayChanged = False
        self._dataUpdated = False

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
        )


    async def _async_update_data(self):
        """Update data via library."""
        return self.solcast._data

    async def setup(self):
        d={}
        self._previousenergy = d
        self._lastDay = dt.now(self.solcast._tz).day
        try:
            #4.0.18 - added reset usage call to reset usage sensors at UTC midnight
            async_track_utc_time_change(self._hass, self.update_utcmidnight_usage_sensor_data, hour=0,minute=0,second=0)
            async_track_utc_time_change(self._hass, self.update_integration_listeners, minute=range(0, 60, 5), second=0)
        except Exception as error:
            _LOGGER.error("SOLCAST - Error coordinator setup: %s", traceback.format_exc())


    async def update_integration_listeners(self, *args):
        try:
            crtDay = dt.now(self.solcast._tz).day
            self._dateChanged = (crtDay != self._lastDay)
            if self._dateChanged:
                self._lastDay = crtDay

            self.async_update_listeners()
        except Exception:
            #_LOGGER.error("SOLCAST - update_integration_listeners: %s", traceback.format_exc())
            pass

    async def update_utcmidnight_usage_sensor_data(self, *args):
        try:
            await self.solcast.reset_api_usage()
        except Exception:
            #_LOGGER.error("SOLCAST - update_utcmidnight_usage_sensor_data: %s", traceback.format_exc())
            pass

    async def service_event_update(self, *args):
        #await self.solcast.sites_weather()
        await self.solcast.http_data(dopast=False)
        self._dataUpdated = True
        await self.update_integration_listeners()
        self._dataUpdated = False

    async def service_event_delete_old_solcast_json_file(self, *args):
        await self.solcast.delete_solcast_file()

    async def service_query_forecast_data(self, *args) -> tuple:
        return await self.solcast.get_forecast_list(*args)

    def get_energy_tab_data(self):
        return self.solcast.get_energy_data()

    def get_sensor_value(self, key=""):
        match key:
            case "total_kwh_forecast_today":
                return self.solcast.get_total_kwh_forecast_day(0)
            case "peak_w_today":
                return self.solcast.get_peak_w_day(0)
            case "peak_w_time_today":
                return self.solcast.get_peak_w_time_day(0)
            case "forecast_this_hour":
                return self.solcast.get_forecast_n_hour(0)
            case "forecast_next_hour":
                return self.solcast.get_forecast_n_hour(1)
            case "forecast_custom_hour":
                return self.solcast.get_forecast_custom_hours(self.solcast._customhoursensor)
            case "total_kwh_forecast_tomorrow":
                return self.solcast.get_total_kwh_forecast_day(1)
            case "total_kwh_forecast_d3":
                return self.solcast.get_total_kwh_forecast_day(2)
            case "total_kwh_forecast_d4":
                return self.solcast.get_total_kwh_forecast_day(3)
            case "total_kwh_forecast_d5":
                return self.solcast.get_total_kwh_forecast_day(4)
            case "total_kwh_forecast_d6":
                return self.solcast.get_total_kwh_forecast_day(5)
            case "total_kwh_forecast_d7":
                return self.solcast.get_total_kwh_forecast_day(6)
            case "power_now":
                return self.solcast.get_power_n_mins(0)
            case "power_now_30m":
                return self.solcast.get_power_n_mins(30)
            case "power_now_1hr":
                return self.solcast.get_power_n_mins(60)
            case "peak_w_tomorrow":
                return self.solcast.get_peak_w_day(1)
            case "peak_w_time_tomorrow":
                return self.solcast.get_peak_w_time_day(1)
            case "get_remaining_today":
                return self.solcast.get_forecast_remaining_today()
            case "api_counter":
                return self.solcast.get_api_used_count()
            case "api_limit":
                return self.solcast.get_api_limit()
            case "lastupdated":
                return self.solcast.get_last_updated_datetime()
            case "hard_limit":
                #return self.solcast._hardlimit < 100
                return False if self.solcast._hardlimit == 100 else f"{round(self.solcast._hardlimit * 1000)}w"
            # case "weather_description":
            #     return self.solcast.get_weather()
            case _:
                return None

    def get_sensor_extra_attributes(self, key=""):
        match key:
            case "total_kwh_forecast_today":
                return self.solcast.get_forecast_day(0)
            case "total_kwh_forecast_tomorrow":
                return self.solcast.get_forecast_day(1)
            case "total_kwh_forecast_d3":
                return self.solcast.get_forecast_day(2)
            case "total_kwh_forecast_d4":
                return self.solcast.get_forecast_day(3)
            case "total_kwh_forecast_d5":
                return self.solcast.get_forecast_day(4)
            case "total_kwh_forecast_d6":
                return self.solcast.get_forecast_day(5)
            case "total_kwh_forecast_d7":
                return self.solcast.get_forecast_day(6)
            case "power_now":
                return self.solcast.get_sites_power_n_mins(0)
            case "power_now_30m":
                return self.solcast.get_sites_power_n_mins(30)
            case "power_now_1hr":
                return self.solcast.get_sites_power_n_mins(60)
            case "peak_w_today":
                return self.solcast.get_sites_peak_w_day(0)
            case "peak_w_time_today":
                return self.solcast.get_sites_peak_w_time_day(0)
            case "peak_w_tomorrow":
                return self.solcast.get_sites_peak_w_day(1)
            case "peak_w_time_tomorrow":
                return self.solcast.get_sites_peak_w_time_day(1)
            case _:
                return None

    def get_site_sensor_value(self, roof_id, key):
        match key:
            case "site_data":
                return self.solcast.get_rooftop_site_total_today(roof_id)
            case _:
                return None

    def get_site_sensor_extra_attributes(self, roof_id, key):
        match key:
            case "site_data":
                return self.solcast.get_rooftop_site_extra_data(roof_id)
            case _:
                return None