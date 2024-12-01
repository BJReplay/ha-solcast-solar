"""The Solcast Solar coordinator."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime as dt, timedelta
import logging
import time
import traceback
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.event import async_track_utc_time_change
from homeassistant.helpers.sun import get_astral_event_next
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    DATE_FORMAT,
    DOMAIN,
    SENSOR_DEBUG_LOGGING,
    SENSOR_UPDATE_LOGGING,
    TIME_FORMAT,
)
from .solcastapi import SolcastApi

_LOGGER = logging.getLogger(__name__)

DAYS = [
    "total_kwh_forecast_today",
    "total_kwh_forecast_tomorrow",
    "total_kwh_forecast_d3",
    "total_kwh_forecast_d4",
    "total_kwh_forecast_d5",
    "total_kwh_forecast_d6",
    "total_kwh_forecast_d7",
]
NO_ATTRIBUTES = ["api_counter", "api_limit", "lastupdated"]


class SolcastUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data."""

    def __init__(self, hass: HomeAssistant, solcast: SolcastApi, version: str) -> None:
        """Initialise the coordinator.

        Public variables at the top, protected variables (those prepended with _ after).

        Arguments:
            hass (HomeAssistant): The Home Assistant instance.
            solcast (SolcastApi): The Solcast API instance.
            version (str): The integration version from manifest.json.

        """
        self.hass: HomeAssistant = hass
        self.interval_just_passed: dt = None
        self.solcast: SolcastApi = solcast
        self.tasks: dict[str, Any] = {}
        self.version: str = version

        self._date_changed: bool = False
        self._data_updated: bool = False
        self._intervals: list[dt] = []
        self._last_day: dt = None
        self._sunrise: dt = None
        self._sunrise_tomorrow: dt = None
        self._sunrise_yesterday: dt = None
        self._sunset: dt = None
        self._sunset_tomorrow: dt = None
        self._sunset_yesterday: dt = None

        # First list item is the sensor value method, additional items are only used for sensor attributes.
        self.__get_value = {
            "forecast_this_hour": [{"method": self.solcast.get_forecast_n_hour, "value": 0}],
            "forecast_next_hour": [{"method": self.solcast.get_forecast_n_hour, "value": 1}],
            "forecast_custom_hours": [{"method": self.solcast.get_forecast_custom_hours, "value": self.solcast.custom_hour_sensor}],
            "get_remaining_today": [{"method": self.solcast.get_forecast_remaining_today}],
            "power_now": [{"method": self.solcast.get_power_n_minutes, "value": 0}],
            "power_now_30m": [{"method": self.solcast.get_power_n_minutes, "value": 30}],
            "power_now_1hr": [{"method": self.solcast.get_power_n_minutes, "value": 60}],
            "peak_w_time_today": [{"method": self.solcast.get_peak_time_day, "value": 0}],
            "peak_w_time_tomorrow": [{"method": self.solcast.get_peak_time_day, "value": 1}],
            "peak_w_today": [{"method": self.solcast.get_peak_power_day, "value": 0}],
            "peak_w_tomorrow": [{"method": self.solcast.get_peak_power_day, "value": 1}],
            "api_counter": [{"method": self.solcast.get_api_used_count}],
            "api_limit": [{"method": self.solcast.get_api_limit}],
            "lastupdated": [{"method": self.solcast.get_last_updated}],
        }
        self.__get_value |= {
            day: [
                {"method": self.solcast.get_total_energy_forecast_day, "value": ahead},
                {"method": self.solcast.get_forecast_day, "value": ahead},
            ]
            for ahead, day in enumerate(DAYS)
        }

        super().__init__(hass, _LOGGER, name=DOMAIN)

    async def _async_update_data(self):
        """Update data via library.

        Returns:
            list: Dampened forecast detail list of the sum of all site forecasts.

        """
        return self.solcast.get_data()

    async def setup(self) -> bool:
        """Set up time change tracking."""
        self._last_day = dt.now(self.solcast.options.tz).day
        try:
            self.__auto_update_setup(init=True)
            await self.__check_forecast_fetch()

            self.tasks["listeners"] = async_track_utc_time_change(
                self.hass, self.update_integration_listeners, minute=range(0, 60, 5), second=0
            )
            self.tasks["check_fetch"] = async_track_utc_time_change(
                self.hass, self.__check_forecast_fetch, minute=range(0, 60, 5), second=0
            )
            self.tasks["midnight_update"] = async_track_utc_time_change(
                self.hass, self.__update_utc_midnight_usage_sensor_data, hour=0, minute=0, second=0
            )
            for timer in sorted(self.tasks):
                _LOGGER.debug("Running task %s", timer)
        except:  # noqa: E722
            _LOGGER.error("Exception in setup: %s", traceback.format_exc())
            return False
        return True

    async def update_integration_listeners(self, *args):
        """Get updated sensor values."""
        if SENSOR_UPDATE_LOGGING:
            start_time = time.time()
        try:
            if SENSOR_DEBUG_LOGGING:
                _LOGGER.debug("Update listeners")

            current_day = dt.now(self.solcast.options.tz).day
            self._date_changed = current_day != self._last_day
            if self._date_changed:
                _LOGGER.debug("Date has changed, recalculate splines and set up auto-updates")
                self._last_day = current_day
                await self.__update_midnight_spline_recalculate()
                self.__auto_update_setup()

            await self.async_update_listeners()
        except:  # noqa: E722
            # _LOGGER.error("Exception in update_integration_listeners(): %s", traceback.format_exc())
            pass
        if SENSOR_UPDATE_LOGGING:
            _LOGGER.debug("Update listeners took %.3f seconds", time.time() - start_time)

    async def __restart_time_track_midnight_update(self):
        """Cancel and restart UTC time change tracker."""
        try:
            _LOGGER.warning("Restarting midnight UTC timer")
            try:
                self.tasks["midnight_update"]()  # Cancel the tracker
                _LOGGER.debug("Cancelled task midnight_update")
            except:  # noqa: E722
                pass
            self.tasks["midnight_update"] = async_track_utc_time_change(
                self.hass, self.__update_utc_midnight_usage_sensor_data, hour=0, minute=0, second=0
            )
            _LOGGER.debug("Started task midnight_update")
        except:  # noqa: E722
            _LOGGER.error("Exception in __restart_time_track_midnight_update(): %s", traceback.format_exc())

    async def __check_forecast_fetch(self, *args):
        """Check for an auto forecast update event."""
        try:
            if self.solcast.options.auto_update:

                def set_next_update():
                    if len(self._intervals) > 0:
                        next_update = self._intervals[0].astimezone(self.solcast.options.tz)
                        self.solcast.set_next_update(
                            next_update.strftime(TIME_FORMAT)
                            if next_update.date() == dt.now().date()
                            else next_update.strftime(DATE_FORMAT)
                        )
                    else:
                        self.solcast.set_next_update(None)

                async def wait_for_fetch(update_in: int):
                    try:
                        task_name = f"pending_update_{update_in:03}"
                        await asyncio.sleep(update_in)
                        _LOGGER.info("Auto update forecast")
                        self._intervals = self._intervals[1:]
                        set_next_update()
                        await self.__forecast_update(completion=f"Completed task {task_name}")
                    except asyncio.CancelledError:
                        _LOGGER.info("Auto update scheduled update cancelled")
                    finally:
                        with contextlib.suppress(Exception):
                            self.tasks.pop(task_name)

                if len(self._intervals) > 0:
                    _now = self.solcast.get_real_now_utc().replace(microsecond=0)
                    _from = _now.replace(minute=int(_now.minute / 5) * 5, second=0)

                    pop_expired = []
                    for index, interval in enumerate(self._intervals):
                        if _from <= interval <= _from + timedelta(seconds=299):
                            update_in = int((interval - _now).total_seconds())
                            task_name = f"pending_update_{update_in:03}"
                            if update_in >= 0:
                                if self.tasks.get(task_name) is not None:
                                    # The interval update is already tasked
                                    _LOGGER.debug("Task %s already exists, ignoring", task_name)
                                    continue
                                _LOGGER.debug("Create task %s", task_name)
                                self.tasks[task_name] = asyncio.create_task(wait_for_fetch(update_in))
                            else:
                                _LOGGER.debug("Not tasking %s", task_name)
                        if interval < _from:
                            pop_expired.append(index)
                    # Remove expired intervals if any have been missed
                    if len(pop_expired) > 0:
                        _LOGGER.debug("Removing expired auto update intervals")
                        self._intervals = [interval for i, interval in enumerate(self._intervals) if i not in pop_expired]
                        set_next_update()

        except:  # noqa: E722
            _LOGGER.error("Exception in __check_forecast_fetch(): %s", traceback.format_exc())

    async def __update_utc_midnight_usage_sensor_data(self, *args):
        """Reset tracked API usage at midnight UTC."""
        try:
            await self.solcast.reset_api_usage()
            self._data_updated = True
            await self.update_integration_listeners()
            self._data_updated = False
        except:  # noqa: E722
            _LOGGER.error("Exception in __update_utc_midnight_usage_sensor_data(): %s", traceback.format_exc())

    async def __update_midnight_spline_recalculate(self):
        """Re-calculates splines at midnight local time."""
        try:
            await self.solcast.check_data_records()
            await self.solcast.recalculate_splines()
        except:  # noqa: E722
            _LOGGER.error("Exception in __update_midnight_spline_recalculate(): %s", traceback.format_exc())

    def __auto_update_setup(self, init: bool = False):
        """Set up of auto-updates."""
        try:
            match self.solcast.options.auto_update:
                case 1:
                    self.__get_sun_rise_set()
                    self.__calculate_forecast_updates(init=init)
                case 2:
                    self._sunrise_yesterday = self.solcast.get_day_start_utc(future=-1)
                    self._sunset_yesterday = self.solcast.get_day_start_utc()
                    self._sunrise = self._sunset_yesterday
                    self._sunset = self.solcast.get_day_start_utc(future=1)
                    self._sunrise_tomorrow = self._sunset
                    self._sunset_tomorrow = self.solcast.get_day_start_utc(future=2)
                    self.__calculate_forecast_updates(init=init)
                case _:
                    pass
        except:  # noqa: E722
            _LOGGER.error("Exception in __auto_update_setup(): %s", traceback.format_exc())

    def __get_sun_rise_set(self):
        """Get the sunrise and sunset times for today and tomorrow."""

        def sun_rise_set(day_start):
            sunrise = get_astral_event_next(self.hass, "sunrise", day_start).replace(microsecond=0)
            sunset = get_astral_event_next(self.hass, "sunset", day_start).replace(microsecond=0)
            return sunrise, sunset

        self._sunrise_yesterday, self._sunset_yesterday = sun_rise_set(self.solcast.get_day_start_utc(future=-1))
        self._sunrise, self._sunset = sun_rise_set(self.solcast.get_day_start_utc())
        self._sunrise_tomorrow, self._sunset_tomorrow = sun_rise_set(self.solcast.get_day_start_utc(future=1))
        _LOGGER.debug(
            "Sun rise / set today: %s / %s",
            self._sunrise.astimezone(self.solcast.options.tz).strftime("%H:%M:%S"),
            self._sunset.astimezone(self.solcast.options.tz).strftime("%H:%M:%S"),
        )

    def __calculate_forecast_updates(self, init: bool = False):
        """Calculate all automated forecast update UTC events for the day.

        This is an even spread between sunrise and sunset.
        """
        try:
            divisions = int(self.solcast.get_api_limit() / min(len(self.solcast.sites), 2))

            def get_intervals(sunrise: dt, sunset: dt, log=True):
                intervals_yesterday = []
                if sunrise == self._sunrise:
                    seconds = int((self._sunset_yesterday - self._sunrise_yesterday).total_seconds())
                    intervals_yesterday = [
                        (self._sunrise_yesterday + timedelta(seconds=int(seconds / divisions * i))).replace(microsecond=0)
                        for i in range(divisions)
                    ]
                seconds = (sunset - sunrise).total_seconds()
                interval = seconds / divisions
                intervals = intervals_yesterday + [
                    (sunrise + timedelta(seconds=interval * i)).replace(microsecond=0) for i in range(divisions)
                ]
                _now = self.solcast.get_real_now_utc()
                for i in intervals:
                    if i < _now:
                        self.interval_just_passed = i
                    else:
                        break
                intervals = [i for i in intervals if i > _now]
                if log:
                    _LOGGER.debug("Auto update total seconds: %d, divisions: %d, interval: %d seconds", seconds, divisions, interval)
                    if init:
                        _LOGGER.debug(
                            "Auto update forecasts %s",
                            "over 24 hours" if self.solcast.options.auto_update > 1 else "between sunrise and sunset",
                        )
                if sunrise == self._sunrise:
                    if self.interval_just_passed in intervals_yesterday:
                        just_passed = self.interval_just_passed.astimezone(self.solcast.options.tz).strftime(DATE_FORMAT)
                    else:
                        just_passed = self.interval_just_passed.astimezone(self.solcast.options.tz).strftime("%H:%M:%S")
                    _LOGGER.debug("Previous auto update would have been at %s", just_passed)
                return intervals

            def format_intervals(intervals):
                return [
                    i.astimezone(self.solcast.options.tz).strftime("%H:%M")
                    if len(intervals) > 10
                    else i.astimezone(self.solcast.options.tz).strftime("%H:%M:%S")
                    for i in intervals
                ]

            intervals_today = get_intervals(self._sunrise, self._sunset)
            intervals_tomorrow = get_intervals(self._sunrise_tomorrow, self._sunset_tomorrow, log=False)
            self._intervals = intervals_today + intervals_tomorrow

            if len(intervals_today) > 0:
                _LOGGER.info(
                    "Auto forecast update%s for today at %s",
                    "s" if len(intervals_today) > 1 else "",
                    ", ".join(format_intervals(intervals_today)),
                )
            if len(intervals_today) < divisions:  # Only log tomorrow if part-way though today, or today has no more updates
                _LOGGER.info(
                    "Auto forecast update%s for tomorrow at %s",
                    "s" if len(intervals_tomorrow) > 1 else "",
                    ", ".join(format_intervals(intervals_tomorrow)),
                )
        except:  # noqa: E722
            _LOGGER.error("Exception in __calculate_forecast_updates(): %s", traceback.format_exc())

    async def __forecast_update(self, force: bool = False, completion: str = ""):
        """Get updated forecast data."""

        try:
            _LOGGER.debug("Started task %s", "update" if completion == "" else completion.replace("Completed task ", ""))
            _LOGGER.debug("Checking for stale usage cache")
            if self.solcast.is_stale_usage_cache():
                _LOGGER.warning("Usage cache reset time is stale, last reset was more than 24-hours ago, resetting API usage")
                await self.solcast.reset_usage_cache()
                await self.__restart_time_track_midnight_update()

            # await self.solcast.get_weather()
            await self.solcast.get_forecast_update(do_past=False, force=force)
            self._data_updated = True
            await self.update_integration_listeners()
            self._data_updated = False
            _LOGGER.debug(completion)
        finally:
            with contextlib.suppress(Exception):
                # Clean up a task created by a service call action
                self.tasks.pop("forecast_update")

    async def service_event_update(self, **kwargs):
        """Get updated forecast data when requested by a service call.

        Arguments:
            kwargs (dict): If a key of "ignore_auto_enabled" exists (regardless of the value), then the API counter will be incremented.

        Raises:
            ServiceValidationError: Notify Home Assistant that an error has occurred, with translation.

        """
        if self.solcast.options.auto_update > 0 and "ignore_auto_enabled" not in kwargs:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="auto_use_force")
        self.tasks["forecast_update"] = asyncio.create_task(
            self.__forecast_update(completion="Completed task update" if not kwargs.get("completion") else kwargs["completion"])
        )

    async def service_event_force_update(self):
        """Force the update of forecast data when requested by a service call. Ignores API usage/limit counts.

        Raises:
            ServiceValidationError: Notify Home Assistant that an error has occurred, with translation.

        """
        if self.solcast.options.auto_update == 0:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="auto_use_normal")
        self.tasks["forecast_update"] = asyncio.create_task(self.__forecast_update(force=True, completion="Completed task force_update"))

    async def service_event_delete_old_solcast_json_file(self):
        """Delete the solcast.json file when requested by a service call."""
        for task, cancel in self.solcast.tasks.items():
            _LOGGER.debug("Cancelling solcastapi task %s", task)
            cancel.cancel()
        self.solcast.tasks = {}
        if not await self.solcast.delete_solcast_file():
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="remove_cache_failed")
        self._data_updated = True
        await self.update_integration_listeners()
        self._data_updated = False

    async def service_query_forecast_data(self, *args) -> tuple:
        """Return forecast data requested by a service call."""
        return await self.solcast.get_forecast_list(*args)

    def get_solcast_sites(self) -> dict[str, Any]:
        """Return the active solcast sites.

        Returns:
            dict[str, Any]: The presently known solcast.com sites.

        """
        return self.solcast.sites

    def get_energy_tab_data(self) -> dict[str, Any]:
        """Return an energy dictionary.

        Returns:
            dict: A Home Assistant energy dashboard compatible data set.

        """
        return self.solcast.get_energy_data()

    def get_data_updated(self) -> bool:
        """Whether data has been updated, which will trigger all sensor values to update.

        Returns:
            bool: Whether the forecast data has been updated.

        """
        return self._data_updated

    def set_data_updated(self, updated: bool):
        """Set the state of the data updated flag.

        Arguments:
            updated (bool): The state to set the _data_updated forecast updated flag to.

        """
        self._data_updated = updated

    def get_date_changed(self) -> bool:
        """Whether a roll-over to tomorrow has occurred, which will trigger all sensor values to update.

        Returns:
            bool: Whether a date roll-over has occurred.

        """
        return self._date_changed

    def get_sensor_value(self, key: str = "") -> int | dt | float | str | bool | None:  # noqa: C901
        """Return the value of a sensor."""

        def unit_adjusted(hard_limit):
            if hard_limit >= 1000000:
                return f"{round(hard_limit/1000000, 1)} GW"
            if hard_limit >= 1000:
                return f"{round(hard_limit/1000, 1)} MW"
            return f"{round(hard_limit, 1)} kW"

        # Most sensors
        if self.__get_value.get(key) is not None:
            if self.__get_value[key][0].get("value") is not None:
                return self.__get_value[key][0]["method"](self.__get_value[key][0].get("value", 0))
            return self.__get_value[key][0]["method"]()

        # Hard limit
        if key == "hard_limit":
            hard_limit = float(self.solcast.hard_limit.split(",")[0])
            if hard_limit == 100:
                return False
            return unit_adjusted(hard_limit)

        # Hard limits
        api_keys = self.solcast.options.api_key
        i = 0
        for api_key in api_keys.split(","):
            if key == "hard_limit_" + api_key[-6:]:
                hard_limit = float(self.solcast.hard_limit.split(",")[i])
                if hard_limit == 100:
                    return False
                return unit_adjusted(hard_limit)
        return None

    def get_sensor_extra_attributes(self, key: str = "") -> dict[str, Any] | None:
        """Return the attributes for a sensor."""

        if self.__get_value.get(key) is None:
            return None
        ret = {}
        for fetch in self.__get_value[key] if key not in NO_ATTRIBUTES else []:
            ret |= (
                self.solcast.get_forecast_attributes(fetch["method"], fetch.get("value", 0))
                if fetch["method"] != self.solcast.get_forecast_day
                else fetch["method"](fetch["value"])
            )
        return ret

    def get_site_sensor_value(self, roof_id: str, key: str) -> float | None:
        """Get the site total for today."""
        match key:
            case "site_data":
                return self.solcast.get_rooftop_site_total_today(roof_id)
            case _:
                return None

    def get_site_sensor_extra_attributes(self, roof_id: str, key: str) -> dict[str, Any] | None:
        """Get the attributes for a sensor."""
        match key:
            case "site_data":
                return self.solcast.get_rooftop_site_extra_data(roof_id)
            case _:
                return None
