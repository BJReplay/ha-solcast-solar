"""Solcast update scheduling and execution."""

from __future__ import annotations  # Remains for compatibility with Python < 3.14+  # noqa: TID251

import asyncio
import contextlib
from datetime import date, datetime as dt, timedelta
import logging
import math
from random import randint
from typing import TYPE_CHECKING, Any

from cronsim import CronSim, CronSimError

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_utc_time_change,
)
from homeassistant.helpers.sun import get_astral_event_next
from homeassistant.util import dt as dt_util

from .const import (
    ADVANCED_ALLOW_EXCEED_API_LIMIT_MAXIMUM,
    ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_CONFIGURATION,
    ADVANCED_AUTOMATED_DAMPENING_GENERATION_FETCH_DELAY,
    ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS,
    ADVANCED_ESTIMATED_ACTUALS_FETCH_DELAY,
    ADVANCED_ESTIMATED_ACTUALS_LOG_APE_PERCENTILES,
    ADVANCED_ESTIMATED_ACTUALS_LOG_MAPE_BREAKDOWN,
    ALL,
    DOMAIN,
    DT_DATE_FORMAT,
    DT_DATE_ONLY_FORMAT,
    DT_TIME_FORMAT,
    DT_TIME_FORMAT_SHORT,
    ENTITY_ACCURACY,
    SENSOR,
    TASK_ACTUALS_FETCH,
    TASK_CHECK_FETCH,
    TASK_FORECASTS_FETCH,
    TASK_FORECASTS_FETCH_IMMEDIATE,
    TASK_NEW_DAY_ACTUALS,
    TASK_NEW_DAY_GENERATION,
)
from .enums import AutoUpdate
from .issues import sync_actuals_quota_risk_issue
from .util import ordinal

if TYPE_CHECKING:
    from .coordinator import SolcastUpdateCoordinator

from .log import get_logger

_LOGGER = get_logger(__name__)
TASK_PROXY_UPDATE = "pending_proxy_update"
# Max estimated_actuals_fetch_delay (120) plus one hour latitude for UTC/local and DST variation.
_LATEST_PROXY_ACTUALS_MINUTE = 180


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
        self._proxy_scheduled_for: dt | None = None
        self._proxy_actuals_cron_checked: str | None = None

    async def setup(self) -> None:
        """Set up auto-update scheduling."""

        self._coordinator.solcast.proxy_follow_reschedule = self._check_proxy_forecast_fetch
        self.update_setup(init=True)
        await self.check_forecast_fetch()

        self._coordinator.tasks[TASK_CHECK_FETCH] = async_track_utc_time_change(
            self._coordinator.hass, self.check_forecast_fetch, minute=range(0, 60, 5), second=0
        )

    def update_setup(self, init: bool = False) -> None:
        """Set up of auto-updates."""

        if self._coordinator.solcast.proxy_mode:
            if self._intervals:
                self._intervals = []
            _LOGGER.debug("Auto update interval generation skipped: proxy mode active")
            return

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
        self.divisions = int(self._coordinator.solcast.api_limit / self._coordinator.solcast.api_maximum_sites)

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
        if self._coordinator.solcast.proxy_mode and self._coordinator.solcast.proxy_next_attempt_at is not None:
            tz = self._coordinator.solcast.options.tz
            follow_at = self._coordinator.solcast.proxy_next_attempt_at + timedelta(
                seconds=self._coordinator.solcast.proxy_poll_delay_seconds
            )
            next_update = follow_at.astimezone(tz)
            self._coordinator.solcast.fetcher.set_next_update(
                next_update.strftime(DT_TIME_FORMAT)
                if next_update.date() == dt_util.now(tz).date()
                else next_update.strftime(DT_DATE_FORMAT)
            )
            return
        if len(self._intervals) > 0:
            tz = self._coordinator.solcast.options.tz
            next_update = self._intervals[0].astimezone(tz)
            self._coordinator.solcast.fetcher.set_next_update(
                next_update.strftime(DT_TIME_FORMAT)
                if next_update.date() == dt_util.now(tz).date()
                else next_update.strftime(DT_DATE_FORMAT)
            )

    def get_auto_update_details(self) -> dict[str, Any]:
        """Return attributes for the last updated sensor."""

        tz = self._coordinator.solcast.options.tz
        base: dict[str, int | dt] = {
            "last_attempt": self._coordinator.solcast.last_attempt.astimezone(tz),
            "failure_count_today": self._coordinator.solcast.failures_last_24h,
            "failure_count_7_day": self._coordinator.solcast.failures_last_7d,
            "failure_count_14_day": self._coordinator.solcast.failures_last_14d,
        }
        if self._coordinator.solcast.proxy_mode:
            next_update = None
            queue: list[dt] = []
            if self._coordinator.solcast.proxy_next_attempt_at is not None:
                next_update = (
                    self._coordinator.solcast.proxy_next_attempt_at + timedelta(seconds=self._coordinator.solcast.proxy_poll_delay_seconds)
                ).astimezone(tz)
                queue = [next_update]
            return base | {
                "next_auto_update": next_update,
                "auto_update_divisions": self.divisions,
                "auto_update_queue": queue,
            }
        if self._coordinator.solcast.options.auto_update != AutoUpdate.NONE:
            return base | {
                "next_auto_update": self._intervals[0].astimezone(tz) if self._intervals else None,
                "auto_update_divisions": self.divisions,
                "auto_update_queue": [i.astimezone(tz) for i in self._intervals[:48]],
            }
        return base

    def _next_from_proxy_cron(self, base_time: dt, cron_expression: str) -> dt | None:
        """Return the next UTC occurrence for the proxy's cron expression."""
        if len(cron_expression.split()) != 5:
            return None
        try:
            return next(CronSim(cron_expression, base_time.astimezone(dt_util.UTC)))
        except (CronSimError, StopIteration):
            return None

    @staticmethod
    def _next_from_proxy_schedule(base_time: dt, schedule_day_utc: str | None, slots_utc: tuple[str, ...]) -> dt | None:
        """Return next UTC occurrence from proxy schedule-day and HH:MM slots."""
        if not schedule_day_utc or not slots_utc:
            return None
        base_utc = base_time.astimezone(dt_util.UTC)
        for slot in slots_utc:
            with contextlib.suppress(ValueError, TypeError):
                slot_dt = dt.fromisoformat(f"{schedule_day_utc}T{slot}:00+00:00").astimezone(dt_util.UTC)
                if slot_dt > base_utc:
                    return slot_dt
        return None

    @staticmethod
    def _attempt_to_follow_from_proxy_schedule(
        base_time: dt,
        schedule_day_utc: str | None,
        slots_utc: tuple[str, ...],
        poll_delay_seconds: int,
    ) -> dt | None:
        """Return the proxy attempt to follow: latest slot still inside delay window, else next slot."""
        if not schedule_day_utc or not slots_utc:
            return None
        base_utc = base_time.astimezone(dt_util.UTC)
        latest_slot: dt | None = None
        next_slot: dt | None = None
        for slot in slots_utc:
            with contextlib.suppress(ValueError, TypeError):
                slot_dt = dt.fromisoformat(f"{schedule_day_utc}T{slot}:00+00:00").astimezone(dt_util.UTC)
                if slot_dt <= base_utc:
                    latest_slot = slot_dt
                    continue
                next_slot = slot_dt
                break

        if latest_slot is not None and latest_slot + timedelta(seconds=max(1, poll_delay_seconds)) > base_utc:
            return latest_slot
        return next_slot

    async def _check_proxy_forecast_fetch(self) -> None:
        """Check for and schedule a proxy-follow forecast update event."""
        if self._coordinator.solcast.proxy_halted:
            if cancel := self._coordinator.tasks.pop(TASK_PROXY_UPDATE, None):
                cancel()
            self._proxy_scheduled_for = None
            self._coordinator.solcast.fetcher.set_next_update(None)
            return
        if self._coordinator.solcast.tasks.get(TASK_FORECASTS_FETCH) is not None:
            return

        next_attempt = self._coordinator.solcast.proxy_next_attempt_at
        if next_attempt is None:
            derived_next = self._attempt_to_follow_from_proxy_schedule(
                self._coordinator.solcast.dt_helper.real_now_utc(),
                self._coordinator.solcast.proxy_schedule_day_utc,
                self._coordinator.solcast.proxy_forecast_times_utc,
                self._coordinator.solcast.proxy_poll_delay_seconds,
            )
            if derived_next is not None:
                self._coordinator.solcast.proxy_next_attempt_at = derived_next
                next_attempt = derived_next
                _LOGGER.debug(
                    "Derived next proxy forecast collection from schedule %s: %s",
                    self._coordinator.solcast.proxy_schedule_day_utc,
                    derived_next.strftime(DT_DATE_FORMAT),
                )
        if next_attempt is None and self._coordinator.solcast.proxy_forecast_cron is not None:
            derived_next = self._next_from_proxy_cron(
                self._coordinator.solcast.dt_helper.real_now_utc(),
                self._coordinator.solcast.proxy_forecast_cron,
            )
            if derived_next is not None:
                self._coordinator.solcast.proxy_next_attempt_at = derived_next
                next_attempt = derived_next
                _LOGGER.debug(
                    "Derived next proxy forecast collection from cron %s: %s",
                    self._coordinator.solcast.proxy_forecast_cron,
                    derived_next.strftime(DT_DATE_FORMAT),
                )
        if next_attempt is None:
            return

        _now = self._coordinator.solcast.dt_helper.real_now_utc().replace(microsecond=0)
        follow_at = next_attempt + timedelta(seconds=self._coordinator.solcast.proxy_poll_delay_seconds)
        if follow_at <= _now:
            follow_at = _now + timedelta(seconds=max(1, self._coordinator.solcast.proxy_poll_delay_seconds))

        existing = self._coordinator.tasks.get(TASK_PROXY_UPDATE)
        if self._proxy_scheduled_for != follow_at and existing is not None:
            existing()
            self._coordinator.tasks.pop(TASK_PROXY_UPDATE, None)
            self._proxy_scheduled_for = None

        if self._coordinator.tasks.get(TASK_PROXY_UPDATE) is None:
            _LOGGER.debug(
                "Create task %s to fire at %02d:%02d:%02d UTC",
                TASK_PROXY_UPDATE,
                follow_at.hour,
                follow_at.minute,
                follow_at.second,
            )
            self._coordinator.tasks[TASK_PROXY_UPDATE] = async_track_point_in_utc_time(
                self._coordinator.hass,
                self._fetch_proxy,
                follow_at,
            )
            self._proxy_scheduled_for = follow_at

        self.set_next_update()

    async def check_forecast_fetch(self, _called_at: dt | None = None) -> None:
        """Check for an auto forecast update event."""

        if self._coordinator.solcast.proxy_mode:
            await self._check_proxy_forecast_fetch()
            return

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

    async def _fetch_proxy(self, _called_at: dt | None = None) -> None:
        """Handle a scheduled proxy-follow forecast update."""

        _LOGGER.info("Auto update forecast (proxy-follow)")
        self._coordinator.tasks.pop(TASK_PROXY_UPDATE, None)
        self._proxy_scheduled_for = None
        if self._coordinator.solcast.tasks.get(TASK_FORECASTS_FETCH) is not None:
            return
        self.set_next_update()
        await self.forecast_update(completion=f"Completed task {TASK_PROXY_UPDATE}")

    async def _fetch(self, _called_at: dt | None = None) -> None:
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

            await self._coordinator.solcast.fetcher.get_forecast_update(
                do_past_hours=need_history_hours,
                force=force,
            )

            await self._coordinator.update_integration_listeners()
            await self._coordinator.async_request_refresh()
            if self._coordinator.solcast.proxy_mode:
                await self._check_proxy_forecast_fetch()

            _LOGGER.debug(completion)
        finally:
            with contextlib.suppress(Exception):
                # Clean up a task created by a service call action
                self._coordinator.tasks.pop(TASK_FORECASTS_FETCH_IMMEDIATE, None)

    def _get_minute_of_day(self, time_point: dt) -> int:
        """Get the minute of the day for a given time point."""

        return time_point.hour * 60 + time_point.minute

    async def check_generation_fetch(self) -> bool:
        """Check if generation fetch was missed and schedule it."""

        scheduled = False
        if (
            self._coordinator.solcast.options.get_actuals
            and self._coordinator.solcast.options.auto_dampen
            and bool(self._coordinator.solcast.options.generation_entities)
        ):
            if not self._coordinator.solcast.estimated_actuals_updated_today:
                if TASK_NEW_DAY_GENERATION in self._coordinator.tasks:
                    return True

                tz = self._coordinator.solcast.options.tz
                now_minute = self._get_minute_of_day(dt_util.now(tz))
                generation_fetch_delay = self._coordinator.solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_GENERATION_FETCH_DELAY]

                if now_minute <= generation_fetch_delay:
                    update_at = (
                        dt_util.now(tz).replace(
                            hour=0,
                            minute=0,
                            second=5 if generation_fetch_delay == 0 else 0,
                            microsecond=0,
                        )  # i.e. just past midnight local
                        + timedelta(minutes=generation_fetch_delay)
                    )
                    _LOGGER.debug(
                        "Scheduling generation update at %s",
                        update_at.astimezone(tz).strftime(DT_TIME_FORMAT),
                    )
                else:
                    # If startup/reload happened after the scheduled window then the timer was likely cancelled and not recreated. Schedule it again.
                    update_at = dt_util.now(tz).replace(microsecond=0) + timedelta(seconds=30 + randint(0, 29))
                    _LOGGER.info(
                        "Generation update window was missed, scheduling at %s",
                        update_at.astimezone(tz).strftime(DT_TIME_FORMAT),
                    )

                self._coordinator.tasks[TASK_NEW_DAY_GENERATION] = async_track_point_in_utc_time(
                    self._coordinator.hass,
                    self._generation,
                    update_at,
                )
                scheduled = True

        return scheduled

    async def check_estimated_actuals_fetch(self) -> bool:
        """Schedule estimated actuals fetch if needed."""

        get_actuals = self._coordinator.solcast.options.get_actuals

        sync_actuals_quota_risk_issue(
            self._coordinator.hass,
            self._coordinator.solcast.sites,
            self._coordinator.solcast.api_typical,
            self._coordinator.solcast.api_used,
            self._coordinator.solcast.api_forced,
            self._coordinator.solcast.api_limit,
            get_actuals,
            proxy_mode=self._coordinator.solcast.proxy_mode,
            allow_exceed_api_limit_maximum=self._coordinator.solcast.advanced_options.get(ADVANCED_ALLOW_EXCEED_API_LIMIT_MAXIMUM, False),
        )

        scheduled = False
        if get_actuals:
            self._validate_proxy_actuals_cron()
            actuals_updated_today = self._coordinator.solcast.estimated_actuals_updated_today
            if not actuals_updated_today:
                if TASK_NEW_DAY_ACTUALS in self._coordinator.tasks:
                    return True

                update_at = self._proxy_actuals_update_at() or self._local_actuals_update_at()
                self._coordinator.tasks[TASK_NEW_DAY_ACTUALS] = async_track_point_in_utc_time(
                    self._coordinator.hass,
                    self._actuals,
                    update_at,
                )
                scheduled = True
        return scheduled

    def _local_actuals_update_at(self) -> dt:
        """Return when to collect estimated actuals directly from Solcast."""

        tz = self._coordinator.solcast.options.tz
        now_minute = self._get_minute_of_day(dt_util.now(tz))
        estimated_actuals_fetch_delay = self._coordinator.solcast.advanced_options[ADVANCED_ESTIMATED_ACTUALS_FETCH_DELAY]

        if now_minute <= estimated_actuals_fetch_delay:
            update_at = (
                dt_util.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)  # i.e. midnight local
                + timedelta(minutes=max(now_minute, estimated_actuals_fetch_delay))
                + timedelta(minutes=randint(1, 14), seconds=randint(0, 59))
            )
            _LOGGER.debug(
                "Scheduling estimated actuals update at %s",
                update_at.astimezone(tz).strftime(DT_TIME_FORMAT),
            )
        else:
            # If startup/reload happened after the scheduled window then the timer was likely cancelled and not recreated. Schedule it again.
            update_at = dt_util.now(tz).replace(microsecond=0) + timedelta(seconds=30 + randint(0, 29))
            _LOGGER.info(
                "Estimated actuals update window was missed, scheduling at %s",
                update_at.astimezone(tz).strftime(DT_TIME_FORMAT),
            )
        return update_at

    def _first_unsuitable_actuals_day(self, cron_expression: str, earliest_minute: int, latest_minute: int | None = None) -> date | None:
        """Return the first local day in the next year whose first proxy collection is missing or outside the acceptable local minute window."""

        solcast = self._coordinator.solcast
        tz = solcast.options.tz
        today = solcast.dt_helper.real_now_utc().astimezone(tz).date()
        for offset in range(366):
            day = today + timedelta(days=offset)
            day_start = dt.combine(day, dt.min.time(), tzinfo=tz)
            first = self._next_from_proxy_cron(day_start - timedelta(seconds=1), cron_expression)
            local = first.astimezone(tz) if first is not None else None
            local_minute = local.hour * 60 + local.minute if local is not None else -1
            if (
                local is None
                or local.date() != day
                or local_minute < earliest_minute
                or (latest_minute is not None and local_minute > latest_minute)
            ):
                return day
        return None

    def _proxy_actuals_update_at(self) -> dt | None:
        """Return when to collect estimated actuals from the proxy, or None when it advertises no usable cron."""

        solcast = self._coordinator.solcast
        if not solcast.proxy_mode or solcast.proxy_actuals_cron is None:
            return None
        # The proxy collects once per cron occurrence, so the first occurrence of the local day is the one to follow.
        collected_at = self._next_from_proxy_cron(solcast.dt_helper.day_start_utc() - timedelta(seconds=1), solcast.proxy_actuals_cron)
        if collected_at is None:
            return None

        self._validate_proxy_actuals_cron()

        tz = solcast.options.tz
        now = solcast.dt_helper.real_now_utc().replace(microsecond=0)
        update_at = collected_at + timedelta(seconds=solcast.proxy_poll_delay_seconds)
        if update_at <= now:
            update_at = now + timedelta(seconds=30 + randint(0, 29))
            _LOGGER.info(
                "Proxy estimated actuals collection was missed, scheduling at %s",
                update_at.astimezone(tz).strftime(DT_TIME_FORMAT),
            )
        else:
            _LOGGER.debug(
                "Scheduling estimated actuals update at %s (proxy-follow)",
                update_at.astimezone(tz).strftime(DT_TIME_FORMAT),
            )
        return update_at

    def _validate_proxy_actuals_cron(self) -> None:
        """Validate proxy actuals cron suitability and log startup-visible errors once per cron value."""

        solcast = self._coordinator.solcast
        if not solcast.proxy_mode or solcast.proxy_actuals_cron is None:
            return
        if solcast.proxy_actuals_times_utc:
            _LOGGER.debug(
                "Skipping proxy actuals cron validation; proxy provides explicit schedule slots (%s)",
                ", ".join(solcast.proxy_actuals_times_utc),
            )
            return
        if self._proxy_actuals_cron_checked == solcast.proxy_actuals_cron:
            return

        self._proxy_actuals_cron_checked = solcast.proxy_actuals_cron

        if (day := self._first_unsuitable_actuals_day(solcast.proxy_actuals_cron, 0, _LATEST_PROXY_ACTUALS_MINUTE)) is not None:
            _LOGGER.error(
                "Proxy estimated actuals schedule '%s' (UTC) does not first fire between 00:00 and %02d:%02d local time on %s, so a day's estimated actuals may be skipped. The proxy should collect in that local-time window on every day of the year",
                solcast.proxy_actuals_cron,
                *divmod(_LATEST_PROXY_ACTUALS_MINUTE, 60),
                day.strftime(DT_DATE_ONLY_FORMAT),
            )

        if solcast.options.auto_dampen and solcast.options.generation_entities:
            generation_delay = solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_GENERATION_FETCH_DELAY]
            if (day := self._first_unsuitable_actuals_day(solcast.proxy_actuals_cron, generation_delay + 1)) is not None:
                _LOGGER.error(
                    "Proxy estimated actuals schedule '%s' (UTC) does not first fire after the generation data fetch at %02d:%02d local time on %s, so automated dampening may model with stale generation data. The proxy should collect after that time on every day of the year",
                    solcast.proxy_actuals_cron,
                    *divmod(generation_delay, 60),
                    day.strftime(DT_DATE_ONLY_FORMAT),
                )

    async def _actuals(self, _called_at: dt | None = None) -> None:
        _LOGGER.info("Update estimated actuals")
        await self.update_estimated_actuals_history(new_day=True, dampen_yesterday=True)

    async def _generation(self, _called_at: dt | None = None) -> None:
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
            entity_registry = er.async_get(self._coordinator.hass)
            entity_id = entity_registry.async_get_entity_id(SENSOR, DOMAIN, ENTITY_ACCURACY)
            if entity_id is not None:
                entity = entity_registry.async_get(entity_id)
                if entity is not None and not entity.disabled_by:
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
        log_mape_breakdown = self._coordinator.solcast.advanced_options[ADVANCED_ESTIMATED_ACTUALS_LOG_MAPE_BREAKDOWN]
        day_start_minus_30 = self._coordinator.solcast.dt_helper.day_start_utc() - timedelta(minutes=30)
        if self._coordinator.solcast.options.auto_dampen and earliest_dampened_start is not None:
            if log_mape_breakdown:
                _LOGGER.debug(
                    "Calculating dampened estimated actual MAPE from %s to %s",
                    earliest_dampened_start.astimezone(self._coordinator.solcast.options.tz).strftime(DT_DATE_ONLY_FORMAT),
                    day_start_minus_30.astimezone(self._coordinator.solcast.options.tz).strftime(DT_DATE_ONLY_FORMAT),
                )
            if log_mape_breakdown:
                _LOGGER.debug(
                    "Calculating undampened estimated actual MAPE from %s to %s",
                    earliest_undampened_start.astimezone(self._coordinator.solcast.options.tz).strftime(DT_DATE_ONLY_FORMAT),
                    day_start_minus_30.astimezone(self._coordinator.solcast.options.tz).strftime(DT_DATE_ONLY_FORMAT),
                )
            dampened_estimates, undampened_estimates = await asyncio.gather(
                self._coordinator.solcast.query.get_estimate_list(
                    earliest_dampened_start,
                    day_start_minus_30,
                    ALL,
                    False,  # Undampened = False
                ),
                self._coordinator.solcast.query.get_estimate_list(
                    earliest_undampened_start,
                    day_start_minus_30,
                    ALL,
                    True,  # Undampened = True
                ),
            )
            (
                (inf_d, error_dampened, error_dampened_percentiles, inf_d_daily),
                (inf_u, error_undampened, error_undampened_percentiles, inf_u_daily),
            ) = await asyncio.gather(
                self._coordinator.solcast.dampening.calculate_error(
                    generation_dampening_day,
                    generation_dampening,
                    dampened_estimates,
                    percentiles_to_calculate,
                    log_mape_breakdown,
                    "Dampened",
                ),
                self._coordinator.solcast.dampening.calculate_error(
                    generation_dampening_day,
                    generation_dampening,
                    undampened_estimates,
                    percentiles_to_calculate,
                    log_mape_breakdown,
                    "Undampened",
                ),
            )
        else:
            error_dampened = -1.0  # Not applicable
            error_dampened_percentiles = [-1.0] * len(percentiles_to_calculate)  # Not applicable
            if log_mape_breakdown:
                _LOGGER.debug(
                    "Calculating undampened estimated actual MAPE from %s to %s",
                    earliest_undampened_start.astimezone(self._coordinator.solcast.options.tz).strftime(DT_DATE_ONLY_FORMAT),
                    day_start_minus_30.astimezone(self._coordinator.solcast.options.tz).strftime(DT_DATE_ONLY_FORMAT),
                )
            inf_u, error_undampened, error_undampened_percentiles, inf_u_daily = await self._coordinator.solcast.dampening.calculate_error(
                generation_dampening_day,
                generation_dampening,
                await self._coordinator.solcast.query.get_estimate_list(
                    earliest_undampened_start,
                    day_start_minus_30,
                    ALL,
                    True,  # Undampened = True
                ),
                percentiles_to_calculate,
                log_mape_breakdown,
                "Undampened",
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
