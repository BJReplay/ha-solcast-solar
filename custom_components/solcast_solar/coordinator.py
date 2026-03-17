"""The Solcast Solar coordinator."""

from __future__ import annotations

import asyncio
from datetime import datetime as dt, timedelta
import logging
from operator import itemgetter
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_utc_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    ADVANCED_ENTITY_LOGGING,
    ADVANCED_FORECAST_DAY_ENTITIES,
    ALL,
    COMPLETION,
    CUSTOM_HOURS,
    DAMPENED_APE_BREAKDOWN,
    DAMPENED_DAILY,
    DAMPENED_MAPE,
    DAMPENED_PERCENTILES,
    DOMAIN,
    ENTITY_ACCURACY,
    ENTITY_API_COUNTER,
    ENTITY_API_LIMIT,
    ENTITY_DAMPEN,
    ENTITY_FORECAST_CUSTOM_HOURS,
    ENTITY_FORECAST_NEXT_HOUR,
    ENTITY_FORECAST_REMAINING_TODAY,
    ENTITY_FORECAST_REMAINING_TODAY_OLD,
    ENTITY_FORECAST_THIS_HOUR,
    ENTITY_LAST_UPDATED,
    ENTITY_LAST_UPDATED_OLD,
    ENTITY_PEAK_W_TIME_TODAY,
    ENTITY_PEAK_W_TIME_TOMORROW,
    ENTITY_PEAK_W_TODAY,
    ENTITY_PEAK_W_TOMORROW,
    ENTITY_POWER_NOW,
    ENTITY_POWER_NOW_1HR,
    ENTITY_POWER_NOW_30M,
    ENTITY_TOTAL_KWH_FORECAST_TODAY,
    ENTITY_TOTAL_KWH_FORECAST_TOMORROW,
    EXCEPTION_AUTO_USE_FORCE,
    EXCEPTION_AUTO_USE_NORMAL,
    EXCEPTION_INIT_KEY_INVALID,
    FACTOR,
    FACTORS,
    GET_ACTUALS,
    INFINITY_EXCLUDED,
    INTEGRATION_AUTOMATED,
    INTERVAL,
    LAST_UPDATED,
    METHOD,
    MODEL_PERIOD_DAYS,
    NEED_HISTORY_HOURS,
    PERIOD_START,
    SENSOR,
    SITE_DAMP,
    TASK_ACTUALS_FETCH,
    TASK_FORECASTS_FETCH,
    TASK_FORECASTS_FETCH_IMMEDIATE,
    TASK_LISTENERS,
    TASK_MIDNIGHT_UPDATE,
    UNDAMPENED_APE_BREAKDOWN,
    UNDAMPENED_DAILY,
    UNDAMPENED_MAPE,
    UNDAMPENED_PERCENTILES,
    VALUE,
)
from .solcastapi import SolcastApi
from .updater import Updater
from .util import AutoUpdate
from .watch import FileWatcher

_LOGGER = logging.getLogger(__name__)

NO_ATTRIBUTES = [ENTITY_API_COUNTER, ENTITY_API_LIMIT, ENTITY_DAMPEN, ENTITY_ACCURACY, ENTITY_LAST_UPDATED_OLD]


class SolcastUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry, solcast: SolcastApi, version: str) -> None:
        """Initialise the coordinator.

        Public variables at the top, protected variables (those prepended with _ after).

        Arguments:
            hass (HomeAssistant): The Home Assistant instance.
            config_entry (ConfigEntry): The configuration entry for the Solcast Solar integration.
            solcast (SolcastApi): The Solcast API instance.
            version (str): The integration version from manifest.json.

        """
        self.entry = config_entry
        self.hass: HomeAssistant = hass
        self.solcast: SolcastApi = solcast
        self.tasks: dict[str, Any] = {}
        self.version: str = version

        self.advanced_entity_logging: bool = solcast.advanced_options[ADVANCED_ENTITY_LOGGING]
        self.advanced_day_entities: int = solcast.advanced_options[ADVANCED_FORECAST_DAY_ENTITIES]
        self.file_dampening = self.solcast.dampening.get_filename()
        self.file_advanced = self.solcast.filename_advanced
        self._updater: Updater = Updater(self)
        self._file_watcher: FileWatcher | None = None
        self._date_changed: bool = False
        self._data_updated: bool = False
        self._last_day: int = dt.now(self.solcast.options.tz).day

        # First list item is the sensor value method, additional items are only used for sensor attributes.
        self.__get_value: dict[str, list[dict[str, Any]]] = {
            ENTITY_FORECAST_THIS_HOUR: [{METHOD: self.solcast.query.get_forecast_n_hour, VALUE: 0}],
            ENTITY_FORECAST_NEXT_HOUR: [{METHOD: self.solcast.query.get_forecast_n_hour, VALUE: 1}],
            ENTITY_FORECAST_CUSTOM_HOURS: [{METHOD: self.solcast.query.get_forecast_custom_hours, VALUE: self.solcast.custom_hour_sensor}],
            ENTITY_FORECAST_REMAINING_TODAY: [{METHOD: self.solcast.query.get_forecast_remaining_today}],
            ENTITY_FORECAST_REMAINING_TODAY_OLD: [{METHOD: self.solcast.query.get_forecast_remaining_today}],
            ENTITY_POWER_NOW: [{METHOD: self.solcast.query.get_power_n_minutes, VALUE: 0}],
            ENTITY_POWER_NOW_30M: [{METHOD: self.solcast.query.get_power_n_minutes, VALUE: 30}],
            ENTITY_POWER_NOW_1HR: [{METHOD: self.solcast.query.get_power_n_minutes, VALUE: 60}],
            ENTITY_PEAK_W_TIME_TODAY: [{METHOD: self.solcast.query.get_peak_time_day, VALUE: 0}],
            ENTITY_PEAK_W_TIME_TOMORROW: [{METHOD: self.solcast.query.get_peak_time_day, VALUE: 1}],
            ENTITY_PEAK_W_TODAY: [{METHOD: self.solcast.query.get_peak_power_day, VALUE: 0}],
            ENTITY_PEAK_W_TOMORROW: [{METHOD: self.solcast.query.get_peak_power_day, VALUE: 1}],
            ENTITY_API_COUNTER: [{METHOD: lambda: self.solcast.api_used_count}],
            ENTITY_API_LIMIT: [{METHOD: lambda: self.solcast.api_limit}],
            ENTITY_LAST_UPDATED: [{METHOD: lambda: self.solcast.last_updated}],
            ENTITY_LAST_UPDATED_OLD: [{METHOD: lambda: self.solcast.last_updated}],
            ENTITY_DAMPEN: [{METHOD: lambda: self.solcast.dampening_enabled}],
            ENTITY_ACCURACY: [{METHOD: lambda: self._updater.accuracy_data.get(DAMPENED_MAPE)}],
        }
        days = [ENTITY_TOTAL_KWH_FORECAST_TODAY, ENTITY_TOTAL_KWH_FORECAST_TOMORROW] + [
            f"total_kwh_forecast_d{r}" for r in range(3, self.advanced_day_entities)
        ]
        self.__get_value |= {
            day: [
                {METHOD: self.solcast.query.get_total_energy_forecast_day, VALUE: ahead},
                {METHOD: self.solcast.query.get_forecast_day, VALUE: ahead},
            ]
            for ahead, day in enumerate(days)
        }

        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
        )

    @property
    def divisions(self) -> int:
        """Return the number of auto-update divisions."""
        return self._updater.divisions

    @property
    def interval_just_passed(self) -> dt | None:
        """Return the most recent auto-update interval that has passed."""
        return self._updater.interval_just_passed

    async def _async_update_data(self) -> dict[str, Any]:
        """Update data via library.

        Returns:
            list: Dampened forecast detail list of the sum of all site forecasts.

        """
        # Check for re-authentication required
        if self.solcast.reauth_required:
            raise ConfigEntryAuthFailed(translation_domain=DOMAIN, translation_key="init_key_invalid")

        return self.solcast.data

    async def setup(self) -> bool:
        """Set up time change tracking and file watchdogs."""

        await self._updater.setup()

        self.tasks[TASK_MIDNIGHT_UPDATE] = async_track_utc_time_change(
            self.hass, self._update_utc_midnight_usage_sensor_data, hour=0, minute=0, second=0
        )
        self.tasks[TASK_LISTENERS] = async_track_utc_time_change(
            self.hass, self.update_integration_listeners, minute=range(0, 60, 5), second=0
        )
        self._file_watcher = FileWatcher(self)
        await self._file_watcher.setup()
        for task in sorted(self.tasks):
            _LOGGER.debug("Running task %s", task)

        await self._updater.check_generation_fetch()
        if not await self._updater.check_estimated_actuals_fetch():
            if self.solcast.options.get_actuals:
                entity_registry = er.async_get(self.hass)
                entity_id = entity_registry.async_get_entity_id(SENSOR, DOMAIN, ENTITY_ACCURACY)
                if entity_id is not None:
                    entity = entity_registry.async_get(entity_id)
                    if entity is not None and not entity.disabled_by:
                        await self._updater.calculate_accuracy_metrics()

        return True

    async def update_integration_listeners(self, called_at: dt | None = None) -> None:
        """Get updated sensor values."""

        current_day = dt.now(self.solcast.options.tz).day
        self._date_changed = current_day != self._last_day
        if self._date_changed:
            _LOGGER.debug(
                "Date has changed, recalculating splines, %ssetting up auto-updates%s%s",
                "not " if self.solcast.options.auto_update == AutoUpdate.NONE else "",
                ", updating estimated actuals" if self.solcast.options.get_actuals else "",
                " and generation data" if self.solcast.options.generation_entities else "",
            )
            self._last_day = current_day

            self.solcast.advanced_opt.log_advanced_options()  # Daily reminder of advanced options in use
            await self._update_midnight_spline_recalculate()
            self._updater.update_setup()

            if self.solcast.options.auto_dampen and self.solcast.options.generation_entities:
                await self._updater.check_generation_fetch()
            await self._updater.check_estimated_actuals_fetch()

        await self.solcast.sites_cache.cleanup_issues()
        self.async_update_listeners()

    async def restart_time_track_midnight_update(self) -> None:
        """Cancel and restart UTC time change tracker."""
        _LOGGER.warning("Restarting midnight UTC timer")
        if self.tasks.get(TASK_MIDNIGHT_UPDATE):
            self.tasks[TASK_MIDNIGHT_UPDATE]()  # Cancel the tracker
        _LOGGER.debug("Cancelled task midnight_update")
        self.tasks[TASK_MIDNIGHT_UPDATE] = async_track_utc_time_change(
            self.hass, self._update_utc_midnight_usage_sensor_data, hour=0, minute=0, second=0
        )
        _LOGGER.debug("Started task midnight_update")

    async def _update_utc_midnight_usage_sensor_data(self, _: dt | None = None) -> None:
        """Reset tracked API usage at midnight UTC."""
        await self.solcast.sites_cache.reset_api_usage()
        await self.solcast.fetcher.reset_failure_stats()
        self._data_updated = True
        await self.update_integration_listeners()
        self._data_updated = False

    async def _update_midnight_spline_recalculate(self) -> None:
        """Re-calculates splines at midnight local time."""
        await self.solcast.check_data_records()
        await self.solcast.query.recalculate_splines()

    async def service_event_update(self, **kwargs: dict[str, Any]) -> None:
        """Get updated forecast data when requested by a service call.

        Arguments:
            kwargs (dict): If a key of "ignore_auto_enabled" exists (regardless of the value), then the API counter will be incremented.

        Raises:
            ServiceValidationError: Notify Home Assistant that an error has occurred.

        """
        if self.tasks.get(TASK_FORECASTS_FETCH_IMMEDIATE) is None and self.solcast.tasks.get(TASK_FORECASTS_FETCH) is None:
            if self.solcast.reauth_required:
                raise ConfigEntryAuthFailed(translation_domain=DOMAIN, translation_key="init_key_invalid")

            if self.solcast.options.auto_update != AutoUpdate.NONE and "ignore_auto_enabled" not in kwargs:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key=EXCEPTION_AUTO_USE_FORCE)
            update_kwargs: dict[str, Any] = {
                COMPLETION: "Completed task update" if not kwargs.get(COMPLETION) else kwargs[COMPLETION],
                NEED_HISTORY_HOURS: kwargs.get(NEED_HISTORY_HOURS, 0),
            }
            task = asyncio.create_task(self._updater.forecast_update(**update_kwargs))
            self.tasks[TASK_FORECASTS_FETCH_IMMEDIATE] = task.cancel
        else:
            _LOGGER.warning("Forecast update already in progress, ignoring")

    async def service_event_force_update(self) -> None:
        """Force the update of forecast data when requested by a service call. Ignores API usage/limit counts.

        Raises:
            ServiceValidationError: Notify Home Assistant that an error has occurred.

        """
        if self.tasks.get(TASK_FORECASTS_FETCH_IMMEDIATE) is None and self.solcast.tasks.get(TASK_FORECASTS_FETCH) is None:
            if self.solcast.reauth_required:
                raise ConfigEntryAuthFailed(translation_domain=DOMAIN, translation_key=EXCEPTION_INIT_KEY_INVALID)

            if self.solcast.options.auto_update == AutoUpdate.NONE:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key=EXCEPTION_AUTO_USE_NORMAL)
            task = asyncio.create_task(self._updater.forecast_update(force=True, completion="Completed task force_update"))
            self.tasks[TASK_FORECASTS_FETCH_IMMEDIATE] = task.cancel
        else:
            _LOGGER.warning("Forecast update already in progress, ignoring service action")

    async def service_event_force_update_estimates(self) -> None:
        """Force the update of estimated actual data when requested by a service call. Ignores API usage/limit counts.

        Raises:
            ServiceValidationError: Notify Home Assistant that an error has occurred.

        """
        if not self.solcast.entry_options[GET_ACTUALS]:
            _LOGGER.debug("Estimated actuals not enabled, ignoring service action")
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="actuals_not_enabled")
        if self.tasks.get(TASK_ACTUALS_FETCH) is None:
            task = asyncio.create_task(self._updater.update_estimated_actuals_history())
            self.tasks[TASK_ACTUALS_FETCH] = task.cancel
        else:
            _LOGGER.warning("Estimated actuals update already in progress, ignoring service action")

    async def service_event_delete_old_solcast_json_file(self) -> None:
        """Delete the solcast.json file when requested by a service call."""
        await self.solcast.tasks_cancel()
        await self.tasks_cancel_specific(TASK_FORECASTS_FETCH_IMMEDIATE)
        await self.hass.async_block_till_done()
        await self.solcast.sites_cache.delete_solcast_file()
        self._data_updated = True
        await self.update_integration_listeners()
        self._data_updated = False

    async def service_query_forecast_data(self, *args: Any) -> tuple[dict[str, Any], ...]:
        """Return forecast data requested by a service call."""
        return await self.solcast.query.get_forecast_list(*args)

    async def service_query_estimate_data(self, *args: Any) -> tuple[dict[str, Any], ...]:
        """Return estimated actual data requested by a service call."""
        return await self.solcast.query.get_estimate_list(*args)

    def get_solcast_sites(self) -> list[Any]:
        """Return the active solcast sites.

        Returns:
            list[Any]: The presently known solcast.com sites.

        """
        return self.solcast.sites

    def get_energy_tab_data(self) -> dict[str, Any] | None:
        """Return an energy dictionary.

        Returns:
            dict: A Home Assistant energy dashboard compatible data set.

        """
        return self.solcast.query.get_energy_data()

    def get_data_updated(self) -> bool:
        """Whether data has been updated, which will trigger all sensor values to update.

        Returns:
            bool: Whether the forecast data has been updated.

        """
        return self._data_updated

    def set_data_updated(self, updated: bool) -> None:
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

    def get_sensor_value(self, key: str = "") -> int | dt | float | str | bool | None:
        """Return the value of a sensor."""

        def unit_adjusted(hard_limit: float) -> str:
            if hard_limit >= 1000000:
                return f"{round(hard_limit / 1000000, 1)} GW"
            if hard_limit >= 1000:
                return f"{round(hard_limit / 1000, 1)} MW"
            return f"{round(hard_limit, 1)} kW"

        # Most sensors
        if self.__get_value.get(key) is not None:
            if self.__get_value[key][0].get(VALUE) is not None:
                return self.__get_value[key][0][METHOD](self.__get_value[key][0].get(VALUE, 0))
            return self.__get_value[key][0][METHOD]()

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
                break
            i += 1
        if key.startswith("hard_limit_"):
            hard_limit = float(self.solcast.hard_limit.split(",")[i])
            if hard_limit == 100:
                return False
            return unit_adjusted(hard_limit)
        return None

    def get_sensor_extra_attributes(self, key: str = "") -> dict[str, Any] | None:
        """Return the attributes for a sensor."""

        if self.__get_value.get(key) is None:
            return None
        ret: dict[str, Any] = {}
        for fetch in self.__get_value[key] if key not in NO_ATTRIBUTES else []:
            ret |= (
                self.solcast.query.get_forecast_attributes(fetch[METHOD], fetch.get(VALUE, 0))
                if fetch[METHOD] != self.solcast.query.get_forecast_day
                else fetch[METHOD](fetch[VALUE])
            )

        if key == "dampen":
            if self.solcast.entry_options.get(SITE_DAMP):
                # Granular dampening
                ret |= {
                    INTEGRATION_AUTOMATED: self.solcast.options.auto_dampen,
                    LAST_UPDATED: (
                        dt.fromtimestamp(self.solcast.dampening.factors_mtime).replace(microsecond=0).astimezone(self.solcast.options.tz)
                        if self.solcast.dampening.factors_mtime
                        else None
                    ),
                }
                if self.solcast.options.auto_dampen:
                    factors: dict[str, dict[str, Any]] = {}
                    dst = False
                    for i, f in enumerate(self.solcast.dampening.factors.get(ALL, [])):
                        dst = dt.now(self.solcast.options.tz).replace(
                            hour=i // 2, minute=i % 2 * 30, second=0, microsecond=0
                        ).dst() == timedelta(hours=1)
                        interval = f"{i // 2 + (1 if dst else 0):02d}:{i % 2 * 30:02d}"
                        factors[interval] = {
                            INTERVAL: interval,
                            FACTOR: f,
                        }
                    for hour in ["00", "03"]:
                        if factors.get(hour + ":00") is None:
                            factors[hour + ":00"] = {INTERVAL: hour + ":00", FACTOR: 1}
                            factors[hour + ":30"] = {INTERVAL: hour + ":30", FACTOR: 1}
                    if factors.get("24:00"):
                        factors.pop("24:00")
                        factors.pop("24:30")
                    ret[FACTORS] = sorted(factors.values(), key=itemgetter(INTERVAL))
                else:
                    ret[FACTORS] = [
                        {
                            INTERVAL: f"{i // 2:02d}:{i % 2 * 30:02d}",
                            FACTOR: f,
                        }
                        for i, f in enumerate(self.solcast.dampening.factors.get(ALL, []))
                    ]
            else:
                ret |= {
                    INTEGRATION_AUTOMATED: False,
                    LAST_UPDATED: None,
                    FACTORS: [
                        {
                            INTERVAL: i,
                            FACTOR: f,
                        }
                        for i, f in self.solcast.options.dampening.items()
                    ],
                }
            # Add advanced options
            ret |= {k: v for k, v in self.solcast.advanced_options.items() if "dampening" in k}

        if key in (ENTITY_LAST_UPDATED, ENTITY_LAST_UPDATED_OLD):
            ret |= self._updater.get_auto_update_details()

        if key == ENTITY_FORECAST_CUSTOM_HOURS:
            ret |= {CUSTOM_HOURS: self.solcast.options.custom_hour_sensor}

        if key == ENTITY_ACCURACY:
            data = self._updater.accuracy_data
            if data:
                ret |= {
                    UNDAMPENED_MAPE: data.get(UNDAMPENED_MAPE),
                    MODEL_PERIOD_DAYS: data.get(MODEL_PERIOD_DAYS),
                    INFINITY_EXCLUDED: data.get(INFINITY_EXCLUDED),
                    DAMPENED_APE_BREAKDOWN: [{PERIOD_START: date, "ape": v} for date, v in data.get(DAMPENED_DAILY, {}).items()],
                    UNDAMPENED_APE_BREAKDOWN: [{PERIOD_START: date, "ape": v} for date, v in data.get(UNDAMPENED_DAILY, {}).items()],
                    **{f"dampened_p{p}_ape": v for p, v in data.get(DAMPENED_PERCENTILES, {}).items()},
                    **{f"undampened_p{p}_ape": v for p, v in data.get(UNDAMPENED_PERCENTILES, {}).items()},
                }

        return ret

    def get_site_sensor_value(self, roof_id: str, key: str) -> float | None:
        """Get the site total for today."""
        match key:
            case "site_data":
                return self.solcast.query.get_rooftop_site_total_today(roof_id)
            case _:
                return None

    def get_site_sensor_extra_attributes(self, roof_id: str, key: str) -> dict[str, Any] | None:
        """Get the attributes for a sensor."""
        match key:
            case "site_data":
                return self.solcast.query.get_rooftop_site_extra_data(roof_id)
            case _:
                return None

    async def tasks_cancel(self) -> None:
        """Cancel all tasks."""
        for task, cancel in self.tasks.items():
            _LOGGER.debug("Cancelling coordinator task %s", task)
            cancel()
        self.tasks = {}

    async def tasks_cancel_specific(self, task: str) -> None:
        """Cancel a specific task."""
        cancel = self.tasks.get(task)
        if cancel is not None:
            _LOGGER.debug("Cancelling coordinator task %s", task)
            cancel()
            self.tasks.pop(task)
