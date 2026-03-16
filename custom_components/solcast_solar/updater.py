"""Solcast PV forecast, update scheduling and execution."""

from __future__ import annotations

import contextlib
from datetime import datetime as dt, timedelta
import logging
import math
from random import randint
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_utc_time_change,
)
from homeassistant.helpers.sun import get_astral_event_next

from .const import (
    ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_CONFIGURATION,
    ADVANCED_AUTOMATED_DAMPENING_GENERATION_FETCH_DELAY,
    ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS,
    ADVANCED_ESTIMATED_ACTUALS_FETCH_DELAY,
    ADVANCED_ESTIMATED_ACTUALS_LOG_APE_PERCENTILES,
    ADVANCED_ESTIMATED_ACTUALS_LOG_MAPE_BREAKDOWN,
    DT_DATE_FORMAT,
    DT_DATE_ONLY_FORMAT,
    DT_TIME_FORMAT,
    DT_TIME_FORMAT_SHORT,
    TASK_ACTUALS_FETCH,
    TASK_CHECK_FETCH,
    TASK_FORECASTS_FETCH_IMMEDIATE,
    TASK_NEW_DAY_ACTUALS,
    TASK_NEW_DAY_GENERATION,
)
from .util import AutoUpdate, ordinal

if TYPE_CHECKING:
    from .coordinator import SolcastUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class Updater:
    """Auto-update scheduling and execution for the Solcast Solar integration."""

    def __init__(self, coordinator: SolcastUpdateCoordinator) -> None:
        """Initialise the updater.

        Arguments:
            coordinator: The update coordinator.

        """
        self._coordinator = coordinator
        self.divisions: int = 0
        self.interval_just_passed: dt | None = None
        self.accuracy_data: dict[str, Any] = {}
        self._intervals: list[dt] = []
        self._update_sequence: list[int] = []
        self._sunrise: dt
        self._sunrise_tomorrow: dt
        self._sunrise_yesterday: dt
        self._sunset: dt
        self._sunset_tomorrow: dt
        self._sunset_yesterday: dt

    async def setup(self) -> None:
        """Set up auto-update scheduling."""

        self.update_setup(init=True)
        await self.check_forecast_fetch()

        self._coordinator.tasks[TASK_CHECK_FETCH] = async_track_utc_time_change(
            self._coordinator.hass, self.check_forecast_fetch, minute=range(0, 60, 5), second=0
        )

    def update_setup(self, init: bool = False) -> None:
        """Set up of auto-updates."""

        match self._coordinator.solcast.options.auto_update:
            case AutoUpdate.DAYLIGHT:
                self._get_sun_rise_set()
                self._calculate_forecast_updates(init=init)
            case AutoUpdate.ALL_DAY:
                self._sunrise_yesterday = self._coordinator.solcast.dt_helper.day_start_utc(future=-1)
                self._sunset_yesterday = self._coordinator.solcast.dt_helper.day_start_utc()
                self._sunrise = self._sunset_yesterday
                self._sunset = self._coordinator.solcast.dt_helper.day_start_utc(future=1)
                self._sunrise_tomorrow = self._sunset
                self._sunset_tomorrow = self._coordinator.solcast.dt_helper.day_start_utc(future=2)
                self._calculate_forecast_updates(init=init)
            case _:
                pass

    def _get_sun_rise_set(self) -> None:
        """Get the sunrise and sunset times for today and tomorrow."""

        def sun_rise_set(day_start: dt) -> tuple[dt, dt]:
            sunrise = get_astral_event_next(self._coordinator.hass, "sunrise", day_start).replace(microsecond=0)
            sunset = get_astral_event_next(self._coordinator.hass, "sunset", day_start).replace(microsecond=0)
            return sunrise, sunset

        self._sunrise_yesterday, self._sunset_yesterday = sun_rise_set(self._coordinator.solcast.dt_helper.day_start_utc(future=-1))
        self._sunrise, self._sunset = sun_rise_set(self._coordinator.solcast.dt_helper.day_start_utc())
        self._sunrise_tomorrow, self._sunset_tomorrow = sun_rise_set(self._coordinator.solcast.dt_helper.day_start_utc(future=1))
        _LOGGER.debug(
            "Sun rise / set today at %s / %s",
            self._sunrise.astimezone(self._coordinator.solcast.options.tz).strftime(DT_TIME_FORMAT),
            self._sunset.astimezone(self._coordinator.solcast.options.tz).strftime(DT_TIME_FORMAT),
        )

    def _calculate_forecast_updates(self, init: bool = False) -> None:
        """Calculate all automated forecast update UTC events for the day.

        This is an even spread between sunrise and sunset.
        """
        self.divisions = int(self._coordinator.solcast.api_limit / min(len(self._coordinator.solcast.sites), 2))

        def get_intervals(sunrise: dt, sunset: dt, log: bool = True):
            intervals_yesterday = []
            if sunrise == self._sunrise:
                seconds = int((self._sunset_yesterday - self._sunrise_yesterday).total_seconds())
                intervals_yesterday = [
                    (self._sunrise_yesterday + timedelta(seconds=int(seconds / self.divisions * i))).replace(microsecond=0)
                    for i in range(self.divisions)
                ]
            seconds = int((sunset - sunrise).total_seconds())
            interval = seconds / self.divisions
            intervals = intervals_yesterday + [
                (sunrise + timedelta(seconds=interval * i)).replace(microsecond=0) for i in range(self.divisions)
            ]
            _now = self._coordinator.solcast.dt_helper.real_now_utc()
            for i in intervals:
                if i < _now:
                    self.interval_just_passed = i
                else:
                    break
            intervals = [i for i in intervals if i > _now]
            if _LOGGER.isEnabledFor(logging.DEBUG):
                if log:
                    _LOGGER.debug("Auto update total seconds %d, divisions %d, interval %d seconds", seconds, self.divisions, interval)
                    if init:
                        _LOGGER.debug(
                            "Auto update forecasts %s",
                            "over 24 hours"
                            if self._coordinator.solcast.options.auto_update == AutoUpdate.ALL_DAY
                            else "between sunrise and sunset",
                        )
                if sunrise == self._sunrise:
                    just_passed = "Unknown"
                    if self.interval_just_passed is not None:
                        if self.interval_just_passed in intervals_yesterday:
                            just_passed = self.interval_just_passed.astimezone(self._coordinator.solcast.options.tz).strftime(
                                DT_DATE_FORMAT
                            )
                        else:
                            just_passed = self.interval_just_passed.astimezone(self._coordinator.solcast.options.tz).strftime(
                                DT_TIME_FORMAT
                            )
                        _LOGGER.debug("Previous auto update UTC %s", self.interval_just_passed.isoformat())
                    _LOGGER.debug("Previous auto update would have been at %s", just_passed)
            return intervals

        def format_intervals(intervals: list[dt]) -> list[str]:
            return [
                i.astimezone(self._coordinator.solcast.options.tz).strftime(DT_TIME_FORMAT_SHORT)
                if len(intervals) > 10
                else i.astimezone(self._coordinator.solcast.options.tz).strftime(DT_TIME_FORMAT)
                for i in intervals
            ]

        intervals_today = get_intervals(self._sunrise, self._sunset)
        intervals_tomorrow = get_intervals(self._sunrise_tomorrow, self._sunset_tomorrow, log=False)
        self._intervals = intervals_today + intervals_tomorrow
        self._coordinator.solcast.auto_update_divisions = self.divisions

        if len(intervals_today) > 0:
            _LOGGER.info(
                "Auto forecast update%s for today at %s",
                "s" if len(intervals_today) > 1 else "",
                ", ".join(format_intervals(intervals_today)),
            )
        if len(intervals_today) < self.divisions:
            _LOGGER.info(
                "Auto forecast update%s for tomorrow at %s",
                "s" if len(intervals_tomorrow) > 1 else "",
                ", ".join(format_intervals(intervals_tomorrow)),
            )

    def set_next_update(self) -> None:
        """Set the next forecast update message time."""
        self._coordinator.solcast.fetcher.set_next_update(None)
        if len(self._intervals) > 0:
            next_update = self._intervals[0].astimezone(self._coordinator.solcast.options.tz)
            self._coordinator.solcast.fetcher.set_next_update(
                next_update.strftime(DT_TIME_FORMAT)
                if next_update.date() == dt.now(self._coordinator.solcast.options.tz).date()
                else next_update.strftime(DT_DATE_FORMAT)
            )

    def get_auto_update_details(self) -> dict[str, Any]:
        """Return attributes for the last updated sensor."""

        base: dict[str, int | dt] = {
            "last_attempt": self._coordinator.solcast.last_attempt.astimezone(self._coordinator.solcast.options.tz),
            "failure_count_today": self._coordinator.solcast.failures_last_24h,
            "failure_count_7_day": self._coordinator.solcast.failures_last_7d,
            "failure_count_14_day": self._coordinator.solcast.failures_last_14d,
        }
        if self._coordinator.solcast.options.auto_update != AutoUpdate.NONE:
            return base | {
                "next_auto_update": self._intervals[0].astimezone(self._coordinator.solcast.options.tz) if self._intervals else None,
                "auto_update_divisions": self.divisions,
                "auto_update_queue": [i.astimezone(self._coordinator.solcast.options.tz) for i in self._intervals[:48]],
            }
        return base

    async def check_forecast_fetch(self, _: dt | None = None) -> None:
        """Check for an auto forecast update event."""

        if self._coordinator.solcast.options.auto_update != AutoUpdate.NONE:
            if len(self._intervals) > 0:
                _now = self._coordinator.solcast.dt_helper.real_now_utc().replace(microsecond=0)
                _from = _now.replace(minute=int(_now.minute / 5) * 5, second=0)

                pop_expired: list[int] = []
                for index, interval in enumerate(self._intervals):
                    if _from <= interval < _from + timedelta(minutes=5):
                        update_in = int((interval - _now).total_seconds())
                        if update_in >= 0:
                            task_name = f"pending_update_{update_in:03}"
                            _LOGGER.debug(
                                "Create task %s to fire at %02d:%02d:%02d UTC", task_name, interval.hour, interval.minute, interval.second
                            )
                            self._update_sequence.append(update_in)
                            self._coordinator.tasks[task_name] = async_track_point_in_utc_time(
                                self._coordinator.hass,
                                self._fetch,
                                interval,
                            )
                    if interval < _from:
                        pop_expired.append(index)
                # Remove expired intervals if any have been missed
                if len(pop_expired) > 0:
                    _LOGGER.debug("Removing expired auto update intervals")
                    self._intervals = [interval for i, interval in enumerate(self._intervals) if i not in pop_expired]
                    self.set_next_update()

    async def _fetch(self, _: dt | None = None) -> None:
        """Handle a scheduled auto forecast update."""

        if len(self._update_sequence) > 0:
            task_name = f"pending_update_{self._update_sequence.pop(0):03}"
            _LOGGER.info("Auto update forecast")
            self._intervals.pop(0)
            self.set_next_update()
            await self.forecast_update(completion=f"Completed task {task_name}")
            if task_name in self._coordinator.tasks:
                self._coordinator.tasks.pop(task_name)

    async def forecast_update(self, force: bool = False, completion: str = "", need_history_hours: int = 0) -> None:
        """Get updated forecast data."""

        try:
            _LOGGER.debug("Started task %s", "update" if completion == "" else completion.replace("Completed task ", ""))
            _LOGGER.debug("Checking for stale usage cache")
            if self._coordinator.solcast.sites_cache.stale_usage_cache:
                _LOGGER.warning("Usage cache reset time is stale, last reset was more than 24-hours ago, resetting API usage")
                await self._coordinator.solcast.sites_cache.reset_usage_cache()
                await self._coordinator.restart_time_track_midnight_update()

            await self._coordinator.solcast.fetcher.get_forecast_update(do_past_hours=need_history_hours, force=force)

            self._coordinator.set_data_updated(True)
            await self._coordinator.update_integration_listeners()
            self._coordinator.set_data_updated(False)
            await self._coordinator.async_request_refresh()

            _LOGGER.debug(completion)
        finally:
            with contextlib.suppress(Exception):
                # Clean up a task created by a service call action
                self._coordinator.tasks.pop(TASK_FORECASTS_FETCH_IMMEDIATE, None)
                await self._coordinator.solcast.build_actual_data()

    def _get_minute_of_day(self, time_point: dt) -> int:
        """Get the minute of the day for a given time point."""

        return time_point.hour * 60 + time_point.minute

    async def check_generation_fetch(self) -> None:
        """Check if generation fetch was missed and schedule it."""

        if self._coordinator.solcast.options.get_actuals:
            if not self._coordinator.solcast.estimated_actuals_updated_today:
                now_minute = self._get_minute_of_day(dt.now(self._coordinator.solcast.options.tz))
                if now_minute <= self._coordinator.solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_GENERATION_FETCH_DELAY]:
                    update_at = (
                        dt.now(self._coordinator.solcast.options.tz).replace(
                            hour=0,
                            minute=0,
                            second=5
                            if self._coordinator.solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_GENERATION_FETCH_DELAY] == 0
                            else 0,
                            microsecond=0,
                        )  # i.e. just past midnight local
                        + timedelta(minutes=self._coordinator.solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_GENERATION_FETCH_DELAY])
                    )
                    _LOGGER.debug(
                        "Scheduling generation update at %s",
                        update_at.astimezone(self._coordinator.solcast.options.tz).strftime(DT_TIME_FORMAT),
                    )
                    self._coordinator.tasks[TASK_NEW_DAY_GENERATION] = async_track_point_in_utc_time(
                        self._coordinator.hass,
                        self._generation,
                        update_at,
                    )

    async def check_estimated_actuals_fetch(self) -> bool:
        """Check if estimated actuals fetch was missed and schedule it."""

        scheduled = False
        if self._coordinator.solcast.options.get_actuals:
            if not self._coordinator.solcast.estimated_actuals_updated_today:
                now_minute = self._get_minute_of_day(dt.now(self._coordinator.solcast.options.tz))
                if now_minute <= self._coordinator.solcast.advanced_options[ADVANCED_ESTIMATED_ACTUALS_FETCH_DELAY]:
                    update_at = (
                        dt.now(self._coordinator.solcast.options.tz).replace(
                            hour=0, minute=0, second=0, microsecond=0
                        )  # i.e. midnight local
                        + timedelta(
                            minutes=max(now_minute, self._coordinator.solcast.advanced_options[ADVANCED_ESTIMATED_ACTUALS_FETCH_DELAY])
                        )
                        + timedelta(minutes=randint(1, 14), seconds=randint(0, 59))
                    )
                    _LOGGER.debug(
                        "Scheduling estimated actuals update at %s",
                        update_at.astimezone(self._coordinator.solcast.options.tz).strftime(DT_TIME_FORMAT),
                    )
                    self._coordinator.tasks[TASK_NEW_DAY_ACTUALS] = async_track_point_in_utc_time(
                        self._coordinator.hass,
                        self._actuals,
                        update_at,
                    )
                    scheduled = True
        return scheduled

    async def _actuals(self, _: dt | None = None) -> None:
        _LOGGER.info("Update estimated actuals")
        await self.update_estimated_actuals_history(new_day=True, dampen_yesterday=True)

    async def _generation(self, _: dt | None = None) -> None:
        _LOGGER.info("Update generation data")
        await self._update_generation_history()

    async def _update_generation_history(self, new_day: bool = False, dampen_yesterday: bool = False) -> None:
        """Update generation using the API."""

        await self._coordinator.solcast.dampening.get_pv_generation()
        if TASK_NEW_DAY_GENERATION in self._coordinator.tasks:
            self._coordinator.tasks.pop(TASK_NEW_DAY_GENERATION, None)

    async def update_estimated_actuals_history(self, new_day: bool = False, dampen_yesterday: bool = False) -> None:
        """Update estimated actuals using the API."""

        _LOGGER.debug("Started task actuals")
        await self._coordinator.solcast.fetcher.update_estimated_actuals(dampen_yesterday=dampen_yesterday)
        await self._coordinator.solcast.build_actual_data()
        _LOGGER.debug("Completed task actuals")
        task = TASK_ACTUALS_FETCH if not new_day else TASK_NEW_DAY_ACTUALS
        if task in self._coordinator.tasks:
            self._coordinator.tasks.pop(task, None)

        if (
            self._coordinator.solcast.options.auto_dampen
            and self._coordinator.solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_CONFIGURATION]
        ):
            await self._coordinator.solcast.dampening.adaptive.update_history()
            await self._coordinator.solcast.dampening.adaptive.determine_best_settings()

        await self._coordinator.solcast.dampening.model_automated()
        if self._coordinator.solcast.options.auto_dampen:
            await self._coordinator.solcast.dampening.apply_forward()
            await self._coordinator.solcast.build_forecast_data()

        if self._coordinator.solcast.options.get_actuals:
            await self.calculate_accuracy_metrics()

    async def calculate_accuracy_metrics(self) -> None:
        """Calculate accuracy metrics for generation vs. undampened/dampened actuals."""

        percentiles_to_calculate = tuple(self._coordinator.solcast.advanced_options[ADVANCED_ESTIMATED_ACTUALS_LOG_APE_PERCENTILES])

        earliest_undampened_start = self._coordinator.solcast.dampening.get_earliest_estimate_after_undampened(
            self._coordinator.solcast.dt_helper.day_start_utc()
            - timedelta(days=self._coordinator.solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS])
        )
        if not self._coordinator.solcast.options.get_actuals or earliest_undampened_start is None:
            return
        if self._coordinator.solcast.options.auto_dampen:
            earliest_dampened_start = self._coordinator.solcast.dampening.get_earliest_estimate_after_dampened(
                self._coordinator.solcast.dt_helper.day_start_utc()
                - timedelta(days=self._coordinator.solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS])
            )

        generation_dampening, generation_dampening_day = await self._coordinator.solcast.dampening.prepare_generation_data(
            earliest_undampened_start
        )

        inf_u = False
        inf_d = False
        inf_d_daily: dict[str, float] = {}
        if self._coordinator.solcast.options.auto_dampen and earliest_dampened_start is not None:
            if self._coordinator.solcast.advanced_options[ADVANCED_ESTIMATED_ACTUALS_LOG_MAPE_BREAKDOWN]:
                _LOGGER.debug(
                    "Calculating dampened estimated actual MAPE from %s to %s",
                    earliest_dampened_start.astimezone(self._coordinator.solcast.options.tz).strftime(DT_DATE_ONLY_FORMAT),
                    (self._coordinator.solcast.dt_helper.day_start_utc() - timedelta(minutes=30))
                    .astimezone(self._coordinator.solcast.options.tz)
                    .strftime(DT_DATE_ONLY_FORMAT),
                )

            inf_d, error_dampened, error_dampened_percentiles, inf_d_daily = await self._coordinator.solcast.dampening.calculate_error(
                generation_dampening_day,
                generation_dampening,
                await self._coordinator.solcast.query.get_estimate_list(
                    earliest_dampened_start,
                    self._coordinator.solcast.dt_helper.day_start_utc() - timedelta(minutes=30),
                    False,  # Undampened = False
                ),
                percentiles_to_calculate,
                self._coordinator.solcast.advanced_options[ADVANCED_ESTIMATED_ACTUALS_LOG_MAPE_BREAKDOWN],
            )
        else:
            error_dampened = -1.0  # Not applicable
            error_dampened_percentiles = [-1.0] * len(percentiles_to_calculate)  # Not applicable
        if self._coordinator.solcast.advanced_options[ADVANCED_ESTIMATED_ACTUALS_LOG_MAPE_BREAKDOWN]:
            _LOGGER.debug(
                "Calculating undampened estimated actual MAPE from %s to %s",
                earliest_undampened_start.astimezone(self._coordinator.solcast.options.tz).strftime(DT_DATE_ONLY_FORMAT),
                (self._coordinator.solcast.dt_helper.day_start_utc() - timedelta(minutes=30))
                .astimezone(self._coordinator.solcast.options.tz)
                .strftime(DT_DATE_ONLY_FORMAT),
            )
        inf_u, error_undampened, error_undampened_percentiles, inf_u_daily = await self._coordinator.solcast.dampening.calculate_error(
            generation_dampening_day,
            generation_dampening,
            await self._coordinator.solcast.query.get_estimate_list(
                earliest_undampened_start,
                self._coordinator.solcast.dt_helper.day_start_utc() - timedelta(minutes=30),
                True,  # Undampened = True
            ),
            percentiles_to_calculate,
            self._coordinator.solcast.advanced_options[ADVANCED_ESTIMATED_ACTUALS_LOG_MAPE_BREAKDOWN],
        )
        if inf_u or inf_d:
            _LOGGER.debug("Excluding %s values", math.inf)
        _LOGGER.debug(
            "Estimated actual mean APE: %.2f%%%s", error_undampened, f", ({error_dampened:.2f}% dampened)" if error_dampened != -1.0 else ""
        )
        for i, p in enumerate(percentiles_to_calculate):
            _LOGGER.debug(
                "Estimated actual %s percentile APE: %.2f%%%s",
                ordinal(p),
                error_undampened_percentiles[i],
                f", ({error_dampened_percentiles[i]:.2f}% dampened)" if error_dampened_percentiles[i] != -1.0 else "",
            )

        model_days = self._coordinator.solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS]
        self.accuracy_data = {
            "dampened_mape": round(error_dampened, 2) if error_dampened not in (-1.0, math.inf) else None,
            "undampened_mape": round(error_undampened, 2) if error_undampened != math.inf else None,
            "model_period_days": model_days,
            "infinity_excluded": inf_u or inf_d,
            "dampened_daily": inf_d_daily,
            "undampened_daily": inf_u_daily,
            "dampened_percentiles": (
                {p: round(error_dampened_percentiles[i], 2) for i, p in enumerate(percentiles_to_calculate)}
                if error_dampened != -1.0
                else {}
            ),
            "undampened_percentiles": {p: round(error_undampened_percentiles[i], 2) for i, p in enumerate(percentiles_to_calculate)},
        }
