"""The Solcast Solar coordinator."""

# pylint: disable=C0302, C0304, C0321, E0401, R0902, R0914, W0105, W0613, W0702, W0706, W0719

from __future__ import annotations
from datetime import datetime as dt
from datetime import timedelta

from typing import Any, Dict

import logging
import traceback

import asyncio

from homeassistant.core import HomeAssistant # type: ignore
from homeassistant.helpers.event import async_track_utc_time_change # type: ignore
from homeassistant.exceptions import ServiceValidationError # type: ignore
from homeassistant.helpers.sun import get_astral_event_next # type: ignore

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator # type: ignore

from .const import (
    DATE_FORMAT,
    DOMAIN,
    SENSOR_DEBUG_LOGGING,
)

from .solcastapi import SolcastApi

_LOGGER = logging.getLogger(__name__)

class SolcastUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data."""

    def __init__(self, hass: HomeAssistant, solcast: SolcastApi, version: str):
        """Initialisation.

        Public variables at the top, protected variables (those prepended with _ after).

        Arguments:
            hass (HomeAssistant): The Home Assistant instance.
            solcast (SolcastApi): The Solcast API instance.
            version (str): The integration version from manifest.json.
        """
        self.solcast = solcast
        self.tasks = {}

        self._hass: HomeAssistant = hass
        self._version: str = version
        self._last_day: dt = None
        self._date_changed: bool = False
        self._data_updated: bool = False
        self._sunrise: dt = None
        self._sunset: dt = None
        self._sunrise_tomorrow: dt = None
        self._sunset_tomorrow: dt = None
        self._intervals: list[dt] = []

        super().__init__(hass, _LOGGER, name=DOMAIN)


    async def _async_update_data(self):
        """Update data via library.

        Returns:
            list: Dampened forecast detail list of the sum of all site forecasts.
        """
        return self.solcast.get_data()

    async def setup(self):
        """Set up time change tracking."""
        self._last_day = dt.now(self.solcast.options.tz).day
        try:
            self.__auto_update_setup(init=True)
            await self.__check_forecast_fetch()

            self.tasks['listeners'] = async_track_utc_time_change(self._hass, self.update_integration_listeners, minute=range(0, 60, 5), second=0)
            self.tasks['check_fetch'] = async_track_utc_time_change(self._hass, self.__check_forecast_fetch, minute=range(0, 60, 5), second=0)
            self.tasks['midnight_update'] = async_track_utc_time_change(self._hass, self.__update_utcmidnight_usage_sensor_data,  hour=0, minute=0, second=0)
            for timer, _ in self.tasks.items():
                _LOGGER.debug("Started task %s", timer)
        except:
            _LOGGER.error("Exception in setup: %s", traceback.format_exc())

    async def update_integration_listeners(self, *args):
        """Get updated sensor values."""
        try:
            if SENSOR_DEBUG_LOGGING:
                _LOGGER.debug("Update listeners")

            current_day = dt.now(self.solcast.options.tz).day
            self._date_changed = current_day != self._last_day
            if self._date_changed:
                self._last_day = current_day
                await self.__update_midnight_spline_recalc()
                self.__auto_update_setup()

            await self.async_update_listeners()
        except:
            #_LOGGER.error("Exception in update_integration_listeners(): %s", traceback.format_exc())
            pass

    async def __restart_time_track_midnight_update(self):
        """Cancel and restart UTC time change tracker"""
        try:
            _LOGGER.warning("Restarting midnight UTC timer")
            try:
                self.tasks['midnight_update']() # Cancel the tracker
                _LOGGER.debug("Cancelled task midnight_update")
            except:
                pass
            self.tasks['midnight_update'] = async_track_utc_time_change(self._hass, self.__update_utcmidnight_usage_sensor_data,  hour=0, minute=0, second=0)
            _LOGGER.debug("Started task midnight_update")
        except:
            _LOGGER.error("Exception in __restart_time_track_midnight_update(): %s", traceback.format_exc())

    async def __check_forecast_fetch(self, *args):
        """Check for an auto forecast update event."""
        try:
            if self.solcast.options.auto_update:
                if len(self._intervals) > 0 and self._intervals[0] < self.solcast.get_now_utc() + timedelta(minutes=5):
                    update_in = (self._intervals[0] - self.solcast.get_now_utc()).total_seconds()
                    if self.tasks.get('pending_update') is not None:
                        # An update is already tasked
                        _LOGGER.debug("Update already tasked. Updating in %d seconds", update_in)
                        return
                    _LOGGER.debug("Forecast will update in %d seconds", update_in)
                    async def wait_for_fetch():
                        try:
                            await asyncio.sleep(update_in)
                            # Proceed with forecast update if not cancelled
                            self._intervals = self._intervals[1:]
                            await self.__forecast_update()
                            if len(self._intervals) > 0:
                                _LOGGER.debug("Next forecast update scheduled for %s", self._intervals[0].astimezone(self.solcast.options.tz).strftime(DATE_FORMAT))
                        except asyncio.CancelledError:
                            _LOGGER.debug("Cancelled next scheduled update")
                        finally:
                            if self.tasks.get('pending_update') is not None:
                                self.tasks.pop('pending_update')
                    self.tasks['pending_update'] = asyncio.create_task(wait_for_fetch())
        except:
            _LOGGER.error("Exception in __check_forecast_fetch(): %s", traceback.format_exc())

    async def __update_utcmidnight_usage_sensor_data(self, *args):
        """Resets tracked API usage at midnight UTC."""
        try:
            await self.solcast.reset_api_usage()
            self._data_updated = True
            await self.update_integration_listeners()
            self._data_updated = False
        except:
            _LOGGER.error("Exception in __update_utcmidnight_usage_sensor_data(): %s", traceback.format_exc())

    async def __update_midnight_spline_recalc(self, *args):
        """Re-calculates splines at midnight local time."""
        try:
            await self.solcast.recalculate_splines()
        except:
            _LOGGER.error("Exception in __update_midnight_spline_recalc(): %s", traceback.format_exc())

    def __auto_update_setup(self, init=False):
        """Daily set up of auto-updates."""
        try:
            match self.solcast.options.auto_update:
                case 1:
                    self.__get_sun_rise_set()
                    self.__calculate_forecast_updates(init=init)
                case 2:
                    self._sunrise = self.solcast.get_day_start_utc()
                    self._sunset = self._sunrise + timedelta(hours=24)
                    self._sunrise_tomorrow = self._sunset
                    self._sunset_tomorrow = self._sunrise_tomorrow + timedelta(hours=24)
                    self.__calculate_forecast_updates(init=init)
                case _:
                    pass
        except:
            _LOGGER.error("Exception in __auto_update_setup(): %s", traceback.format_exc())

    def __get_sun_rise_set(self):
        """Get the sunrise and sunset times for today and tomorrow."""

        def sun_rise_set(daystart):
            sunrise = get_astral_event_next(self._hass, "sunrise", daystart).replace(microsecond=0)
            sunset = get_astral_event_next(self._hass, "sunset", daystart).replace(microsecond=0)
            return sunrise, sunset

        self._sunrise, self._sunset = sun_rise_set(self.solcast.get_day_start_utc())
        self._sunrise_tomorrow, self._sunset_tomorrow = sun_rise_set(self.solcast.get_day_start_utc() + timedelta(hours=24))
        _LOGGER.debug(
            "Sun rise / set today: %s / %s",
            self._sunrise.astimezone(self.solcast.options.tz).strftime('%H:%M:%S'),
            self._sunset.astimezone(self.solcast.options.tz).strftime('%H:%M:%S')
        )

    def __calculate_forecast_updates(self, init=False):
        """Calculate all automated forecast update UTC events for the day.

        This is an even spread between sunrise and sunset.
        """
        try:
            divisions = int(self.solcast.get_api_limit() / round(len(self.solcast.sites) / len(self.solcast.options.api_key.split(",")), 0))

            def get_intervals(sunrise: dt, sunset: dt, log=True):
                seconds = int((sunset - sunrise).total_seconds())
                interval = int(seconds / divisions)
                intervals = [(sunrise + timedelta(seconds=interval) * i) for i in range(0, divisions)]
                intervals = [i for i in intervals if i > self.solcast.get_now_utc()]
                if log:
                    _LOGGER.debug("Auto update: Total seconds %d, divisions: %d updates, interval: %d seconds", seconds, divisions, interval)
                    if init:
                        _LOGGER.debug("Auto-update will update forecasts %d times %s", divisions, "over 24 hours" if self.solcast.options.auto_update > 1 else "between sunrise and sunset")
                return intervals

            self._intervals = get_intervals(self._sunrise, self._sunset)

            def format_intervals(intervals):
                return [i.astimezone(self.solcast.options.tz).strftime('%H:%M') if len(intervals) > 5 else i.astimezone(self.solcast.options.tz).strftime('%H:%M:%S') for i in intervals]

            intervals_today = format_intervals(self._intervals)
            if len(intervals_today) > 0:
                _LOGGER.info("Auto-scheduled forecast update for today at %s", ', '.join(intervals_today))
            if len(intervals_today) < divisions: # Only log tomorrow if part-way though today, or today has no more updates
                intervals_tomorrow = format_intervals(get_intervals(self._sunrise_tomorrow, self._sunset_tomorrow, log=False))
                _LOGGER.info("Auto-scheduled forecast update for tomorrow at %s", ', '.join(intervals_tomorrow))
        except:
            _LOGGER.error("Exception in __calculate_forecast_updates(): %s", traceback.format_exc())

    async def __forecast_update(self, force=False):
        """Get updated forecast data."""

        _LOGGER.debug("Checking for stale usage cache")
        if self.solcast.is_stale_usage_cache():
            _LOGGER.warning("Usage cache reset time is stale, last reset was more than 24-hours ago, resetting API usage")
            await self.solcast.reset_usage_cache()
            await self.__restart_time_track_midnight_update()

        #await self.solcast.get_weather()
        await self.solcast.get_forecast_update(do_past=False, force=force)
        self._data_updated = True
        await self.update_integration_listeners()
        self._data_updated = False

    async def service_event_update(self, *args):
        """Get updated forecast data when requested by a service call.

        Raises:
            ServiceValidationError: Notify Home Assistant that an error has occurred, with translation.
        """
        if self.solcast.options.auto_update > 0:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="auto_use_force")
        else:
            self.tasks['forecast_update'] = asyncio.create_task(self.__forecast_update())

    async def service_event_force_update(self, *args):
        """Force the update of forecast data when requested by a service call. Ignores API usage/limit counts.

        Raises:
            ServiceValidationError: Notify Home Assistant that an error has occurred, with translation.
        """
        if self.solcast.options.auto_update == 0:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="auto_use_normal")
        else:
            self.tasks['forecast_update'] = asyncio.create_task(self.__forecast_update(force=True))

    async def service_event_delete_old_solcast_json_file(self, *args):
        """Delete the solcast.json file when requested by a service call."""
        await self.solcast.delete_solcast_file()

    async def service_query_forecast_data(self, *args) -> tuple:
        """Return forecast data requested by a service call."""
        return await self.solcast.get_forecast_list(*args)

    def get_solcast_sites(self) -> dict[str, Any]:
        """Return the active solcast sites.

        Returns:
            dict[str, Any]: The presently known solcast.com sites
        """
        return self.solcast.sites

    def get_energy_tab_data(self) -> dict[str, Any]:
        """Return an energy dictionary.

        Returns:
            dict: A Home Assistant energy dashboard compatible data set.
        """
        return self.solcast.get_energy_data()

    def get_data_updated(self) -> bool:
        """Returns True if data has been updated, which will trigger all sensor values to update.

        Returns:
            bool: Whether the forecast data has been updated.
        """
        return self._data_updated

    def set_data_updated(self, updated):
        """Set the state of the data updated flag.

        Arguments:
            updated (bool): The state to set the _data_updated forecast updated flag to.
        """
        self._data_updated = updated

    def get_date_changed(self) -> bool:
        """Returns True if a roll-over to tomorrow has occurred, which will trigger all sensor values to update.

        Returns:
            bool: Whether a date roll-over has occurred.
        """
        return self._date_changed

    def get_sensor_value(self, key="") -> (int | dt | float | Any | str | bool | None):
        """Return the value of a sensor."""
        match key:
            case "peak_w_today":
                return self.solcast.get_peak_w_day(0)
            case "peak_w_time_today":
                return self.solcast.get_peak_w_time_day(0)
            case "forecast_this_hour":
                return self.solcast.get_forecast_n_hour(0)
            case "forecast_next_hour":
                return self.solcast.get_forecast_n_hour(1)
            case "forecast_custom_hours":
                return self.solcast.get_forecast_custom_hours(self.solcast.custom_hour_sensor)
            case "total_kwh_forecast_today":
                return self.solcast.get_total_kwh_forecast_day(0)
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
                if self.solcast.hard_limit == 100:
                    return False
                else:
                    if self.solcast.hard_limit >= 1000000:
                        return f"{round(self.solcast.hard_limit/1000000, 1)} GW"
                    if self.solcast.hard_limit >= 1000:
                        return f"{round(self.solcast.hard_limit/1000, 1)} MW"
                    else:
                        return f"{round(self.solcast.hard_limit, 1)} kW"
            # case "weather_description":
            #     return self.solcast.get_weather_description()
            case _:
                return None

    def get_sensor_extra_attributes(self, key="") -> (Dict[str, Any] | None):
        """Return the attributes for a sensor."""
        match key:
            case "forecast_this_hour":
                return self.solcast.get_forecasts_n_hour(0)
            case "forecast_next_hour":
                return self.solcast.get_forecasts_n_hour(1)
            case "forecast_custom_hours":
                return self.solcast.get_forecasts_custom_hours(self.solcast.custom_hour_sensor)
            case "total_kwh_forecast_today":
                ret = self.solcast.get_forecast_day(0)
                ret = {**ret, **self.solcast.get_sites_total_kwh_forecast_day(0)}
                return ret
            case "total_kwh_forecast_tomorrow":
                ret = self.solcast.get_forecast_day(1)
                ret = {**ret, **self.solcast.get_sites_total_kwh_forecast_day(1)}
                return ret
            case "total_kwh_forecast_d3":
                ret = self.solcast.get_forecast_day(2)
                ret = {**ret, **self.solcast.get_sites_total_kwh_forecast_day(2)}
                return ret
            case "total_kwh_forecast_d4":
                ret = self.solcast.get_forecast_day(3)
                ret = {**ret, **self.solcast.get_sites_total_kwh_forecast_day(3)}
                return ret
            case "total_kwh_forecast_d5":
                ret = self.solcast.get_forecast_day(4)
                ret = {**ret, **self.solcast.get_sites_total_kwh_forecast_day(4)}
                return ret
            case "total_kwh_forecast_d6":
                ret = self.solcast.get_forecast_day(5)
                ret = {**ret, **self.solcast.get_sites_total_kwh_forecast_day(5)}
                return ret
            case "total_kwh_forecast_d7":
                ret = self.solcast.get_forecast_day(6)
                ret = {**ret, **self.solcast.get_sites_total_kwh_forecast_day(6)}
                return ret
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
            case "get_remaining_today":
                return self.solcast.get_forecasts_remaining_today()
            case _:
                return None

    def get_site_sensor_value(self, roof_id, key) -> (float | None):
        """Get the site total for today."""
        match key:
            case "site_data":
                return self.solcast.get_rooftop_site_total_today(roof_id)
            case _:
                return None

    def get_site_sensor_extra_attributes(self, roof_id, key) -> (dict[str, Any] | None):
        """Get the attributes for a sensor."""
        match key:
            case "site_data":
                return self.solcast.get_rooftop_site_extra_data(roof_id)
            case _:
                return None