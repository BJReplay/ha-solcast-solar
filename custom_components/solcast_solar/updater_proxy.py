"""Proxy schedule handling for Solcast updates."""

# Remains for compatibility with Python < 3.14+.
from __future__ import annotations  # noqa: TID251

import contextlib
from datetime import date, datetime as dt, timedelta
from random import randint
from typing import TYPE_CHECKING

from cronsim import CronSim, CronSimError

from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .const import (
    ADVANCED_AUTOMATED_DAMPENING_GENERATION_FETCH_DELAY,
    DT_DATE_FORMAT,
    DT_DATE_ONLY_FORMAT,
    DT_TIME_FORMAT,
    TASK_FORECASTS_FETCH,
)

if TYPE_CHECKING:
    from .coordinator import SolcastUpdateCoordinator
    from .updater import Updater

from .log import get_logger

_LOGGER = get_logger(__name__)
TASK_PROXY_UPDATE = "pending_proxy_update"
TASK_PROXY_SCHEDULE_REFRESH_BEFORE_UPDATE = "pending_proxy_schedule_refresh_before_update"
_PROXY_SCHEDULE_REFRESH_LEAD = timedelta(seconds=5)
# Max estimated_actuals_fetch_delay (120) plus one hour latitude for UTC/local and DST variation.
_LATEST_PROXY_ACTUALS_MINUTE = 180


class ProxyUpdater:
    """Manage integration scheduling that follows a Solcast proxy."""

    def __init__(self, coordinator: SolcastUpdateCoordinator, updater: Updater) -> None:
        """Initialise the proxy updater."""
        self._coordinator = coordinator
        self._updater = updater
        self.scheduled_for: dt | None = None
        self.schedule_refresh_scheduled_for: dt | None = None
        self._actuals_cron_checked: str | None = None

    def next_from_cron(self, base_time: dt, cron_expression: str) -> dt | None:
        """Return the next UTC occurrence for the proxy's cron expression."""
        if len(cron_expression.split()) != 5:
            return None
        try:
            return next(CronSim(cron_expression, base_time.astimezone(dt_util.UTC)))
        except (CronSimError, StopIteration):
            return None

    @staticmethod
    def next_from_schedule(base_time: dt, schedule_day_utc: str | None, slots_utc: tuple[str, ...]) -> dt | None:
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
    def attempt_to_follow_schedule(
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

    async def refresh_schedule_before_update(self, _called_at: dt | None = None) -> None:
        """Refresh proxy timing shortly before its next collection."""
        self._coordinator.tasks.pop(TASK_PROXY_SCHEDULE_REFRESH_BEFORE_UPDATE, None)
        self.schedule_refresh_scheduled_for = None

        if not self._coordinator.solcast.proxy_mode:
            return

        retrying = self._coordinator.solcast.proxy_last_fetch_status == "retrying"
        if not await self._coordinator.solcast.sites_cache.refresh_proxy_schedule(require_daylight_proxy_mode=True, concise_log=True):
            return

        if not retrying and not self._coordinator.solcast.proxy_fetch_in_progress:
            self._coordinator.solcast.proxy_next_attempt_at = None
        await self.check_forecast_fetch(quiet=True)

    async def check_forecast_fetch(self, quiet: bool = False) -> None:
        """Check for and schedule a proxy-follow forecast update event."""
        if self._coordinator.solcast.proxy_halted:
            if cancel := self._coordinator.tasks.pop(TASK_PROXY_UPDATE, None):
                cancel()
            if cancel := self._coordinator.tasks.pop(TASK_PROXY_SCHEDULE_REFRESH_BEFORE_UPDATE, None):
                cancel()
            self.scheduled_for = None
            self.schedule_refresh_scheduled_for = None
            self._coordinator.solcast.fetcher.set_next_update(None)
            return
        if self._coordinator.solcast.tasks.get(TASK_FORECASTS_FETCH) is not None:
            return

        next_attempt = self._coordinator.solcast.proxy_next_attempt_at
        if next_attempt is None:
            derived_next = self.attempt_to_follow_schedule(
                self._coordinator.solcast.dt_helper.real_now_utc(),
                self._coordinator.solcast.proxy_schedule_day_utc,
                self._coordinator.solcast.proxy_forecast_times_utc,
                self._coordinator.solcast.proxy_poll_delay_seconds,
            )
            if derived_next is not None:
                self._coordinator.solcast.proxy_next_attempt_at = derived_next
                next_attempt = derived_next
                if not quiet:
                    _LOGGER.debug(
                        "Derived next proxy forecast collection from schedule %s: %s",
                        self._coordinator.solcast.proxy_schedule_day_utc,
                        derived_next.strftime(DT_DATE_FORMAT),
                    )
        if next_attempt is None and self._coordinator.solcast.proxy_forecast_cron is not None:
            derived_next = self.next_from_cron(
                self._coordinator.solcast.dt_helper.real_now_utc(),
                self._coordinator.solcast.proxy_forecast_cron,
            )
            if derived_next is not None:
                self._coordinator.solcast.proxy_next_attempt_at = derived_next
                next_attempt = derived_next
                if not quiet:
                    _LOGGER.debug(
                        "Derived next proxy forecast collection from cron %s: %s",
                        self._coordinator.solcast.proxy_forecast_cron,
                        derived_next.strftime(DT_DATE_FORMAT),
                    )
        if next_attempt is None:
            return

        now = self._coordinator.solcast.dt_helper.real_now_utc()
        follow_at = next_attempt + timedelta(seconds=self._coordinator.solcast.proxy_poll_delay_seconds)
        if follow_at <= now:
            follow_at = now + timedelta(seconds=max(1, self._coordinator.solcast.proxy_poll_delay_seconds))

        existing = self._coordinator.tasks.get(TASK_PROXY_UPDATE)
        if self.scheduled_for != follow_at and existing is not None:
            existing()
            self._coordinator.tasks.pop(TASK_PROXY_UPDATE, None)
            self.scheduled_for = None
            if cancel := self._coordinator.tasks.pop(TASK_PROXY_SCHEDULE_REFRESH_BEFORE_UPDATE, None):
                cancel()
            self.schedule_refresh_scheduled_for = None

        if self._coordinator.tasks.get(TASK_PROXY_UPDATE) is None:
            if not quiet:
                _LOGGER.debug(
                    "Create task %s to fire at %02d:%02d:%02d UTC",
                    TASK_PROXY_UPDATE,
                    follow_at.hour,
                    follow_at.minute,
                    follow_at.second,
                )
            self._coordinator.tasks[TASK_PROXY_UPDATE] = async_track_point_in_utc_time(
                self._coordinator.hass,
                self.fetch,
                follow_at,
            )
            self.scheduled_for = follow_at

        refresh_at = next_attempt - _PROXY_SCHEDULE_REFRESH_LEAD
        existing_refresh = self._coordinator.tasks.get(TASK_PROXY_SCHEDULE_REFRESH_BEFORE_UPDATE)
        if existing_refresh is not None and (refresh_at <= now or self.schedule_refresh_scheduled_for != refresh_at):
            existing_refresh()
            self._coordinator.tasks.pop(TASK_PROXY_SCHEDULE_REFRESH_BEFORE_UPDATE, None)
            self.schedule_refresh_scheduled_for = None

        if refresh_at > now and self._coordinator.tasks.get(TASK_PROXY_SCHEDULE_REFRESH_BEFORE_UPDATE) is None:
            self._coordinator.tasks[TASK_PROXY_SCHEDULE_REFRESH_BEFORE_UPDATE] = async_track_point_in_utc_time(
                self._coordinator.hass,
                self.refresh_schedule_before_update,
                refresh_at,
            )
            self.schedule_refresh_scheduled_for = refresh_at

        self._updater.set_next_update()

    async def fetch(self, _called_at: dt | None = None) -> None:
        """Handle a scheduled proxy-follow forecast update."""
        _LOGGER.info("Auto update forecast (proxy-follow)")
        self._coordinator.tasks.pop(TASK_PROXY_UPDATE, None)
        self.scheduled_for = None
        if self._coordinator.solcast.tasks.get(TASK_FORECASTS_FETCH) is not None:
            return
        self._updater.set_next_update()
        await self._updater.forecast_update(completion=f"Completed task {TASK_PROXY_UPDATE}")

    def actuals_update_at(self) -> dt | None:
        """Return when to collect estimated actuals from the proxy."""
        solcast = self._coordinator.solcast
        if not solcast.proxy_mode:
            return None

        timezone = solcast.options.tz
        now = solcast.dt_helper.real_now_utc().replace(microsecond=0)

        if solcast.proxy_actuals_times_utc:
            collected_at = self.attempt_to_follow_schedule(
                now,
                solcast.proxy_schedule_day_utc,
                solcast.proxy_actuals_times_utc,
                solcast.proxy_poll_delay_seconds,
            )
            if collected_at is None:
                return None
            update_at = collected_at + timedelta(seconds=solcast.proxy_poll_delay_seconds)
            if update_at <= now:
                update_at = now + timedelta(seconds=30 + randint(0, 29))
                _LOGGER.info(
                    "Proxy estimated actuals collection was missed, scheduling at %s",
                    update_at.astimezone(timezone).strftime(DT_TIME_FORMAT),
                )
            else:
                _LOGGER.debug(
                    "Scheduling estimated actuals update at %s (proxy slot-follow)",
                    update_at.astimezone(timezone).strftime(DT_TIME_FORMAT),
                )
            return update_at

        if solcast.proxy_actuals_cron is None:
            return None
        collected_at = self.next_from_cron(solcast.dt_helper.day_start_utc() - timedelta(seconds=1), solcast.proxy_actuals_cron)
        if collected_at is None:
            return None

        self.validate_actuals_cron()

        update_at = collected_at + timedelta(seconds=solcast.proxy_poll_delay_seconds)
        if update_at <= now:
            update_at = now + timedelta(seconds=30 + randint(0, 29))
            _LOGGER.info(
                "Proxy estimated actuals collection was missed, scheduling at %s",
                update_at.astimezone(timezone).strftime(DT_TIME_FORMAT),
            )
        else:
            _LOGGER.debug(
                "Scheduling estimated actuals update at %s (proxy-follow)",
                update_at.astimezone(timezone).strftime(DT_TIME_FORMAT),
            )
        return update_at

    def _first_unsuitable_actuals_day(self, cron_expression: str, earliest_minute: int, latest_minute: int | None = None) -> date | None:
        """Return the first local day where the proxy actuals collection is unsuitable."""
        solcast = self._coordinator.solcast
        timezone = solcast.options.tz
        today = solcast.dt_helper.real_now_utc().astimezone(timezone).date()
        for offset in range(366):
            day = today + timedelta(days=offset)
            day_start = dt.combine(day, dt.min.time(), tzinfo=timezone)
            first = self.next_from_cron(day_start - timedelta(seconds=1), cron_expression)
            local = first.astimezone(timezone) if first is not None else None
            local_minute = local.hour * 60 + local.minute if local is not None else -1
            if (
                local is None
                or local.date() != day
                or local_minute < earliest_minute
                or (latest_minute is not None and local_minute > latest_minute)
            ):
                return day
        return None

    def validate_actuals_cron(self) -> None:
        """Validate proxy actuals cron suitability and log errors once per cron value."""
        solcast = self._coordinator.solcast
        if not solcast.proxy_mode or solcast.proxy_actuals_cron is None:
            return
        if solcast.proxy_actuals_times_utc:
            _LOGGER.debug(
                "Skipping proxy actuals cron validation; proxy provides explicit schedule slots (%s)",
                ", ".join(solcast.proxy_actuals_times_utc),
            )
            return
        if self._actuals_cron_checked == solcast.proxy_actuals_cron:
            return

        self._actuals_cron_checked = solcast.proxy_actuals_cron

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
