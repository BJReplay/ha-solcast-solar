"""Solcast automated dampening."""

from __future__ import annotations

import asyncio
from collections import OrderedDict, defaultdict
import copy
from datetime import UTC, date, datetime as dt, timedelta
import json
import logging
import math
from operator import itemgetter
from pathlib import Path
from statistics import mean
import time
from typing import TYPE_CHECKING, Any, Final, cast

import aiofiles

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import state_changes_during_period
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT
from homeassistant.core import State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.sun import get_astral_location

from .const import (
    ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL,
    ADVANCED_AUTOMATED_DAMPENING_ELEVATION_ADJUSTMENT,
    ADVANCED_AUTOMATED_DAMPENING_GENERATION_HISTORY_LOAD_DAYS,
    ADVANCED_AUTOMATED_DAMPENING_IGNORE_INTERVALS,
    ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR,
    ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR_ADJUSTED,
    ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_GENERATION,
    ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_INTERVALS,
    ADVANCED_AUTOMATED_DAMPENING_MODEL,
    ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS,
    ADVANCED_AUTOMATED_DAMPENING_NO_DELTA_ADJUSTMENT,
    ADVANCED_AUTOMATED_DAMPENING_NO_LIMITING_CONSISTENCY,
    ADVANCED_AUTOMATED_DAMPENING_PRESERVE_UNMATCHED_FACTORS,
    ADVANCED_AUTOMATED_DAMPENING_SIMILAR_PEAK,
    ADVANCED_AUTOMATED_DAMPENING_SUPPRESSION_ENTITY,
    ADVANCED_GRANULAR_DAMPENING_DELTA_ADJUSTMENT,
    ADVANCED_HISTORY_MAX_DAYS,
    ALL,
    DOMAIN,
    DT_DATE_FORMAT,
    DT_DATE_FORMAT_SHORT,
    DT_DATE_MONTH_DAY,
    DT_DATE_ONLY_FORMAT,
    ESTIMATE,
    ESTIMATE10,
    ESTIMATE90,
    EXCEPTION_DAMP_NOT_FOR_SITE,
    EXCEPTION_DAMP_USE_ALL,
    EXCEPTION_NOT_A_SITE,
    EXPORT_LIMITING,
    FORECASTS,
    GENERATION,
    GENERATION_VERSION,
    HALF_HOUR_MINUTES,
    INTERVALS_PER_DAY,
    LAST_UPDATED,
    PERIOD_START,
    PLATFORM_BINARY_SENSOR,
    PLATFORM_SENSOR,
    PLATFORM_SWITCH,
    RESOURCE_ID,
    SITE,
    SITE_ATTRIBUTE_AZIMUTH,
    SITE_ATTRIBUTE_TILT,
    SITE_DAMP,
    SITE_INFO,
    VERSION,
)
from .dampen_adapt import DampeningAdaptive
from .util import (
    JSONDecoder,
    NoIndentEncoder,
    compute_energy_intervals,
    compute_power_intervals,
    diff,
    forecast_entry_update,
    format_site_key,
    percentile,
)

if TYPE_CHECKING:
    from .solcastapi import SolcastApi

GRANULAR_DAMPENING_OFF: Final[bool] = False
GRANULAR_DAMPENING_ON: Final[bool] = True
SET_ALLOW_RESET: Final[bool] = True

_POWER_UNIT_FACTORS: Final[dict[str, float]] = {"mW": 1e-6, "W": 0.001, "kW": 1.0, "MW": 1000.0}
_ENERGY_UNIT_FACTORS: Final[dict[str, float]] = {"mWh": 1e-6, "Wh": 0.001, "kWh": 1.0, "MWh": 1000.0}
_SUPPRESSION_ENTITY_ON_STATES: Final[tuple[str, ...]] = ("on", "1", "true", "True")
_SUPPRESSION_ENTITY_STATES: Final[tuple[str, ...]] = ("on", "off", "1", "0", "true", "false", "True", "False")
_SITE_EXPORT_INTERVAL_MINUTES: Final[int] = 5

_LOGGER = logging.getLogger(__name__)


class Dampening:
    """Manages all dampening-related operations for Solcast forecasts."""

    def __init__(self, api: SolcastApi) -> None:
        """Initialise the dampening manager.

        Arguments:
            api: The parent SolcastApi instance.
        """
        self.api = api
        self.adaptive = DampeningAdaptive(self)
        self.auto_factors: dict[dt, float] = {}
        self.auto_factors_history: dict[int, dict[int, list[dict[str, Any]]]] = {}
        self.data_generation: dict[str, list[dict[str, Any]] | Any] = {
            LAST_UPDATED: dt.fromtimestamp(0, UTC),
            GENERATION: [],
            VERSION: GENERATION_VERSION,
        }
        self.filename_generation = api.filename_generation
        self.granular_allow_reset = True
        self.factors: dict[str, list[float]] = {}
        self.factors_mtime: float = 0

    def allow_granular_reset(self) -> bool:
        """Allow options change to reset the granular dampening file to an empty dictionary."""
        return self.granular_allow_reset

    def get_filename(self) -> str:
        """Return the dampening configuration filename."""
        return self.api.filename_dampening

    def set_allow_granular_reset(self, enable: bool) -> None:
        """Set/clear allow reset granular dampening file to an empty dictionary by options change."""
        self.granular_allow_reset = enable

    def adjusted_interval_dt(self, interval: dt) -> int:
        """Adjust a datetime as standard time."""
        interval_tz = interval.astimezone(self.api.tz)
        offset = 1 if self.api.dt_helper.dst(interval_tz) else 0
        return self._interval_index_from_tz_dt(interval_tz, offset)

    @staticmethod
    def _interval_index_from_tz_dt(period_start_tz: dt, offset: int) -> int:
        """Return the interval index (0-47) from a timezone-aware datetime and DST offset."""
        return ((period_start_tz.hour - offset) * 2 + period_start_tz.minute // 30) if period_start_tz.hour - offset >= 0 else 0

    @staticmethod
    def _tilt_incidence_gain(elevation: float, solar_azimuth: float, tilt: float, panel_azimuth: float) -> float:
        """Return a simple tilt-aware irradiance gain for one site."""
        elevation_rad = math.radians(elevation)
        tilt_rad = math.radians(tilt)
        azimuth_delta_rad = math.radians(solar_azimuth - panel_azimuth)

        gain = math.sin(elevation_rad) * math.cos(tilt_rad) + math.cos(elevation_rad) * math.sin(tilt_rad) * math.cos(azimuth_delta_rad)
        return max(gain, 0.0)

    def elevation_adjustment_ratio(self, past_ts: dt, target_ts: dt) -> float:
        """Return a geometry-normalisation ratio between past and target timestamps.

        Used to normalise historical PV generation samples from a prior day to the expected
        solar contribution on a target day, compensating for solar-geometry drift.

        For each site, the cos-incidence gain is computed at both timestamps; the site ratios
        are averaged across all sites.

        Arguments:
            past_ts: Timestamp of the past half-hour sample.
            target_ts: Timestamp representing the same wall-clock moment on the target day.

        Returns:
            (float) A clamped multiplier to apply to the past value.
        """
        location, _ = get_astral_location(self.api.hass)
        elev_past = location.solar_elevation(past_ts)
        elev_target = location.solar_elevation(target_ts)

        # Skip adjustment near the horizon where tiny sin values blow up the ratio
        # and where shading models break down anyway.
        if elev_past < 5.0 or elev_target < 5.0:
            return 1.0

        azimuth_past = location.solar_azimuth(past_ts)
        azimuth_target = location.solar_azimuth(target_ts)

        ratio_sum = 0.0
        count = 0

        exclude_sites = set(self.api.options.exclude_sites)

        for site in self.api.sites:
            if site[RESOURCE_ID] in exclude_sites:
                continue

            tilt = float(site[SITE_ATTRIBUTE_TILT])
            panel_azimuth = float(site[SITE_ATTRIBUTE_AZIMUTH])

            past_gain = self._tilt_incidence_gain(elev_past, azimuth_past, tilt, panel_azimuth)
            target_gain = self._tilt_incidence_gain(elev_target, azimuth_target, tilt, panel_azimuth)
            if past_gain <= 0.0 or target_gain <= 0.0:
                continue

            ratio_sum += target_gain / past_gain
            count += 1

        if count == 0:
            # No site sees the sun at both timestamps. Impossible fallback really. This used to be the non-azimuth/tilt adjusted return, included for posterity.
            return max(0.5, min(2.0, math.sin(math.radians(elev_target)) / math.sin(math.radians(elev_past))))

        # Clamp to avoid extreme swings from numerical edge-cases.
        return max(0.5, min(2.0, ratio_sum / count))

    @staticmethod
    def _target_timestamp(past_ts: dt, target_day: dt) -> dt:
        """Build a timestamp on target_day at the same UTC time-of-day as past_ts."""
        past_midnight_utc = past_ts.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        target_midnight_utc = target_day.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        return past_ts + (target_midnight_utc - past_midnight_utc)

    async def apply_forward(self, applicable_sites: list[str] | None = None, do_past_hours: int = 0) -> None:
        """Apply dampening to forward forecasts."""
        if self.api.data_undampened[SITE_INFO]:
            _LOGGER.debug("Applying future dampening")

            self.auto_factors = {
                period_start: factor
                for period_start, factor in self.auto_factors.items()
                if period_start >= self.api.dt_helper.day_start_utc()
            }

            undampened_interval_pv50: defaultdict[dt, float] = defaultdict(float)
            for site in self.api.sites:
                if self._should_exclude_site(site[RESOURCE_ID]):
                    continue
                for forecast in self.api.data_undampened[SITE_INFO][site[RESOURCE_ID]][FORECASTS]:
                    period_start = forecast[PERIOD_START]
                    if period_start >= self.api.dt_helper.day_start_utc():
                        undampened_interval_pv50[period_start] += forecast[ESTIMATE] * 0.5

            record_adjustment = True
            for site in self.api.sites:
                site_id = site[RESOURCE_ID]
                # Load all forecasts.
                forecasts_undampened_future = [
                    forecast
                    for forecast in self.api.data_undampened[SITE_INFO][site_id][FORECASTS]
                    if forecast[PERIOD_START]
                    >= (
                        self.api.dt_helper.day_start_utc()
                        if self.api.data[SITE_INFO].get(site_id)
                        else self.api.dt_helper.day_start_utc() - timedelta(hours=do_past_hours)
                    )
                ]
                forecasts = (
                    {forecast[PERIOD_START]: forecast for forecast in self.api.data[SITE_INFO][site_id][FORECASTS]}
                    if self.api.data[SITE_INFO].get(site_id)
                    else {}
                )
                sorted_forecasts_undampened_future = sorted(forecasts_undampened_future, key=itemgetter(PERIOD_START))
                apply_dampening_to_site = not self._should_exclude_site(site_id) and (
                    (site_id in applicable_sites) if applicable_sites else True
                )

                await asyncio.sleep(0)  # Yield to event loop to avoid blocking

                for forecast in sorted_forecasts_undampened_future:
                    period_start = forecast[PERIOD_START]
                    if apply_dampening_to_site:
                        period_start = forecast[PERIOD_START]
                        pv = round(forecast[ESTIMATE], 4)
                        pv10 = round(forecast[ESTIMATE10], 4)
                        pv90 = round(forecast[ESTIMATE90], 4)

                        # Retrieve the dampening factor for the period, and dampen the estimates.
                        dampening_factor = self.get_factor(
                            site_id,
                            period_start.astimezone(self.api.tz),
                            undampened_interval_pv50.get(period_start, -1),
                            record_adjustment=record_adjustment,
                        )
                        if record_adjustment:
                            self.auto_factors[period_start] = dampening_factor
                        pv_dampened = round(pv * dampening_factor, 4)
                        pv10_dampened = round(pv10 * dampening_factor, 4)
                        pv90_dampened = round(pv90 * dampening_factor, 4)

                        # Add or update the new entries.
                        forecast_entry_update(forecasts, period_start, pv_dampened, pv10_dampened, pv90_dampened)
                    else:
                        forecast_entry_update(
                            forecasts,
                            period_start,
                            round(forecast[ESTIMATE], 4),
                            round(forecast[ESTIMATE10], 4),
                            round(forecast[ESTIMATE90], 4),
                        )

                if apply_dampening_to_site:
                    record_adjustment = False

                await self.api.fetcher.sort_and_prune(
                    site_id, self.api.data, self.api.advanced_options[ADVANCED_HISTORY_MAX_DAYS], forecasts
                )

    async def apply_yesterday(self) -> None:
        """Apply dampening to yesterday's estimated actuals."""
        await self._apply_actuals_range(
            start=self.api.dt_helper.day_start_utc(future=-1),
            end=self.api.dt_helper.day_start_utc(),
        )

    async def apply_recovered_history(self, recovered_periods_by_site: dict[str, set[float]]) -> None:
        """Apply dampening to recovered historical estimated actuals."""
        if not recovered_periods_by_site:
            return

        recovered_periods = {
            dt.fromtimestamp(period_start, UTC) for periods in recovered_periods_by_site.values() for period_start in periods
        }
        undampened_interval_pv50 = self._build_actuals_interval_pv50(recovered_periods)

        for site in self.api.sites:
            if self._should_exclude_site(site[RESOURCE_ID]):
                continue

            periods = recovered_periods_by_site.get(site[RESOURCE_ID])
            if not periods:
                continue

            _LOGGER.debug(
                "Apply dampening to recovered historical estimated actuals for %s: %s",
                site[RESOURCE_ID],
                self._format_recovered_periods(periods),
            )

            actuals_undampened = [
                actual
                for actual in self.api.data_actuals[SITE_INFO][site[RESOURCE_ID]][FORECASTS]
                if actual[PERIOD_START].timestamp() in periods
            ]
            if not actuals_undampened:
                continue

            extant_actuals = (
                {actual[PERIOD_START]: actual for actual in self.api.data_actuals_dampened[SITE_INFO][site[RESOURCE_ID]][FORECASTS]}
                if self.api.data_actuals_dampened[SITE_INFO].get(site[RESOURCE_ID])
                else {}
            )

            for actual in actuals_undampened:
                period_start = actual[PERIOD_START]
                dampened = round(
                    actual[ESTIMATE]
                    * self.get_factor(
                        site[RESOURCE_ID],
                        period_start.astimezone(self.api.tz),
                        undampened_interval_pv50.get(period_start, -1.0),
                    ),
                    4,
                )
                forecast_entry_update(extant_actuals, period_start, dampened)

            await self.api.fetcher.sort_and_prune(
                site[RESOURCE_ID],
                self.api.data_actuals_dampened,
                self.api.advanced_options[ADVANCED_HISTORY_MAX_DAYS],
                extant_actuals,
            )

    def _format_recovered_periods(self, periods: set[float]) -> str:
        """Return local date spans for recovered periods."""
        days = sorted({dt.fromtimestamp(period_start, UTC).astimezone(self.api.tz).date() for period_start in periods})
        if not days:
            return ""

        spans: list[str] = []
        span_start = days[0]
        span_end = days[0]

        for day in days[1:]:
            if day == span_end + timedelta(days=1):
                span_end = day
                continue

            spans.append(self._format_date_range(span_start, span_end))
            span_start = day
            span_end = day

        spans.append(self._format_date_range(span_start, span_end))
        return ", ".join(spans)

    @staticmethod
    def _format_date_range(start: date, end: date) -> str:
        """Return a formatted date range string."""
        start_str = start.strftime(DT_DATE_ONLY_FORMAT)
        return start_str if start == end else f"{start_str} to {end.strftime(DT_DATE_ONLY_FORMAT)}"

    def _should_exclude_site(self, site_id: str) -> bool:
        """Return True if the site should be excluded from processing."""
        return site_id in self.api.options.exclude_sites

    def _build_actuals_interval_pv50(self, applicable_periods: set[dt]) -> defaultdict[dt, float]:
        """Build combined pv50 values for estimated actual timestamps."""
        undampened_interval_pv50: defaultdict[dt, float] = defaultdict(float)

        for site in self.api.sites:
            if self._should_exclude_site(site[RESOURCE_ID]):
                continue
            for forecast in self.api.data_actuals[SITE_INFO][site[RESOURCE_ID]][FORECASTS]:
                period_start = forecast[PERIOD_START]
                if period_start in applicable_periods:
                    undampened_interval_pv50[period_start] += forecast[ESTIMATE] * 0.5

        return undampened_interval_pv50

    async def _apply_actuals_range(self, start: dt, end: dt) -> None:
        """Apply dampening to estimated actuals in a time range."""
        if start >= end:
            return

        undampened_interval_pv50 = self._build_actuals_interval_pv50(
            {
                forecast[PERIOD_START]
                for site in self.api.sites
                if not self._should_exclude_site(site[RESOURCE_ID])
                for forecast in self.api.data_actuals[SITE_INFO][site[RESOURCE_ID]][FORECASTS]
                if start <= forecast[PERIOD_START] < end
            }
        )

        for site in self.api.sites:
            if self._should_exclude_site(site[RESOURCE_ID]):
                continue

            _LOGGER.debug(
                "Apply dampening to previous day estimated actuals for %s from %s to %s",
                site[RESOURCE_ID],
                start.strftime(DT_DATE_FORMAT),
                end.strftime(DT_DATE_FORMAT),
            )

            actuals_undampened = [
                actual for actual in self.api.data_actuals[SITE_INFO][site[RESOURCE_ID]][FORECASTS] if start <= actual[PERIOD_START] < end
            ]
            if not actuals_undampened:
                continue

            extant_actuals = (
                {actual[PERIOD_START]: actual for actual in self.api.data_actuals_dampened[SITE_INFO][site[RESOURCE_ID]][FORECASTS]}
                if self.api.data_actuals_dampened[SITE_INFO].get(site[RESOURCE_ID])
                else {}
            )

            for actual in actuals_undampened:
                period_start = actual[PERIOD_START]
                undampened = actual[ESTIMATE]
                factor = self.get_factor(
                    site[RESOURCE_ID],
                    period_start.astimezone(self.api.tz),
                    undampened_interval_pv50.get(period_start, -1.0),
                )
                dampened = round(undampened * factor, 4)
                forecast_entry_update(extant_actuals, period_start, dampened)

            await self.api.fetcher.sort_and_prune(
                site[RESOURCE_ID],
                self.api.data_actuals_dampened,
                self.api.advanced_options[ADVANCED_HISTORY_MAX_DAYS],
                extant_actuals,
            )

    async def get(self, site: str | None, site_underscores: bool) -> list[dict[str, Any]]:
        """Retrieve the currently set dampening factors.

        Arguments:
            site (str): An optional site.
            site_underscores (bool): Whether to replace dashes with underscores in returned site names.

        Returns:
            (list[dict[str, Any]]): The action response for the presently set dampening factors.
        """
        if self.api.entry_options.get(SITE_DAMP):
            if not site:
                sites = [_site[RESOURCE_ID] for _site in self.api.sites]
            else:
                sites = [site]
            all_set = self.factors.get(ALL) is not None
            if site:
                available_sites = {item[RESOURCE_ID] for item in self.api.sites}
                if site != ALL and site not in available_sites:
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key=EXCEPTION_NOT_A_SITE,
                    )
                if not all_set:
                    if site in self.factors:
                        return [
                            {
                                SITE: _site if not site_underscores else format_site_key(_site),
                                "damp_factor": ",".join(str(factor) for factor in self.factors[_site]),
                            }
                            for _site in sites
                            if self.factors.get(_site)
                        ]
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key=EXCEPTION_DAMP_NOT_FOR_SITE,
                        translation_placeholders={SITE: site},
                    )
                if site != ALL:
                    if site in self.factors:
                        _LOGGER.warning(
                            "There is dampening for site %s, but it is being overridden by an all sites entry, returning the 'all' entries instead",
                            site,
                        )
                    else:
                        _LOGGER.warning(
                            "There is no dampening set for site %s, but it is being overridden by an all sites entry, returning the 'all' entries instead",
                            site,
                        )
                return [
                    {
                        SITE: ALL,
                        "damp_factor": ",".join(str(factor) for factor in self.factors[ALL]),
                    }
                ]
            if all_set:
                return [
                    {
                        SITE: ALL,
                        "damp_factor": ",".join(str(factor) for factor in self.factors[ALL]),
                    }
                ]
            return [
                {
                    SITE: _site if not site_underscores else format_site_key(_site),
                    "damp_factor": ",".join(str(factor) for factor in self.factors[_site]),
                }
                for _site in sites
                if self.factors.get(_site)
            ]
        if not site or site == ALL:
            return [
                {
                    SITE: ALL,
                    "damp_factor": ",".join(str(factor) for _, factor in self.api.damp.items()),
                }
            ]
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key=EXCEPTION_DAMP_USE_ALL,
            translation_placeholders={SITE: site},
        )

    def get_earliest_estimate_after_dampened(self, after: dt) -> dt | None:
        """Get the earliest contiguous dampened estimated actual datetime.

        Returns:
            dt | None: The earliest dampened estimated actual datetime, or None if no data.
        """
        return self._get_earliest_estimate_after(self.api.data_estimated_actuals_dampened, after=after, dampened=True)

    def get_earliest_estimate_after_undampened(self, after: dt) -> dt | None:
        """Get the earliest contiguous undampened estimated actual datetime.

        Returns:
            dt | None: The earliest undampened estimated actual datetime, or None if no data.
        """
        return self._get_earliest_estimate_after(self.api.data_estimated_actuals, after=after)

    def get_factor(self, site: str | None, period_start: dt, interval_pv50: float, record_adjustment: bool = False) -> float:
        """Retrieve either a traditional or granular dampening factor."""
        if site is not None:
            if self.api.entry_options.get(SITE_DAMP):
                if self.factors.get(ALL):
                    return self._get_granular_factor(ALL, period_start, interval_pv50, record_adjustment=record_adjustment)
                if self.factors.get(site):
                    return self._get_granular_factor(site, period_start)
                return 1.0
        return self.api.damp.get(f"{period_start.hour}", 1.0)

    @staticmethod
    def _bucket_interval_start(timestamp: dt, interval_minutes: int = HALF_HOUR_MINUTES) -> dt:
        """Return timestamp rounded down to the nearest interval boundary."""
        return timestamp.replace(
            minute=timestamp.minute // interval_minutes * interval_minutes,
            second=0,
            microsecond=0,
        )

    @staticmethod
    def _build_float_intervals(start: dt, interval_minutes: int, initial_value: float = 0.0) -> dict[dt, float]:
        """Build a fixed one-day float map for the given interval size."""
        return {
            start + timedelta(minutes=minute): initial_value for minute in range(0, INTERVALS_PER_DAY * HALF_HOUR_MINUTES, interval_minutes)
        }

    @staticmethod
    def _build_half_hour_bool_intervals(start: dt) -> dict[dt, bool]:
        """Build a fixed one-day half-hour bool map."""
        return {start + timedelta(minutes=minute): False for minute in range(0, INTERVALS_PER_DAY * HALF_HOUR_MINUTES, HALF_HOUR_MINUTES)}

    async def _get_entity_history(
        self,
        recorder_instance: Any,
        start: dt,
        end: dt,
        entity: str,
        *state_changes_args: Any,
    ) -> dict[str, list[State]]:
        """Fetch recorder state history for one entity in a time window."""
        return await recorder_instance.async_add_executor_job(
            state_changes_during_period,
            self.api.hass,
            start,
            end,
            entity,
            *state_changes_args,
        )

    async def _collect_generation_intervals_for_day(
        self,
        prev_start: dt,
        day_start: dt,
        day: int,
        entity_registry: er.EntityRegistry,
        recorder_instance: Any,
    ) -> dict[dt, float]:
        """Collect one day of PV generation intervals from configured entities."""
        generation_intervals = self._build_float_intervals(prev_start, HALF_HOUR_MINUTES)

        for entity in self.api.options.generation_entities:
            r_entity = entity_registry.async_get(entity)
            if r_entity is None:
                _LOGGER.error("Generation entity %s is not a valid entity", entity)
                continue
            if r_entity.disabled_by is not None:
                _LOGGER.error("Generation entity %s is disabled, please enable it", entity)
                continue

            entity_history = await self._get_entity_history(recorder_instance, prev_start, day_start, entity)
            if entity_history.get(entity) and len(entity_history[entity]) > 4:
                _LOGGER.debug("Retrieved day %d PV generation data from entity: %s", -1 + day * -1, entity)

                if self._is_power_entity(entity):
                    # Power entity: compute time-weighted average kW per interval, then convert to kWh (* 0.5).
                    conversion_factor = self._get_conversion_factor(entity, entity_history[entity], is_power=True)
                    power_readings: list[tuple[dt, float]] = [
                        (e.last_updated.astimezone(UTC), float(e.state) * conversion_factor)
                        for e in entity_history[entity]
                        if e.state.replace(".", "").isnumeric()
                    ]

                    if not compute_power_intervals(power_readings, generation_intervals):
                        _LOGGER.debug("Insufficient power readings for entity: %s", entity)
                    continue

                # Energy entity: compute deltas and distribute across intervals.
                conversion_factor = self._get_conversion_factor(entity, entity_history[entity])
                numeric_entries = [
                    (e.last_updated.astimezone(UTC), float(e.state) * conversion_factor)
                    for e in entity_history[entity]
                    if e.state.replace(".", "").isnumeric()
                ]
                sample_time: list[dt] = [self._bucket_interval_start(ts) for ts, _ in numeric_entries]
                sample_generation: list[float] = [0.0, *diff([v for _, v in numeric_entries])]
                sample_generation_time: list[dt] = [ts for ts, _ in numeric_entries]
                sample_timedelta: list[int] = [
                    0,
                    *diff([(ts - prev_start).total_seconds() for ts, _ in numeric_entries]),
                ]

                if sample_generation_time and sample_generation_time[0] == prev_start:
                    sample_generation[0] = 0.0
                    sample_timedelta[0] = 0

                result = compute_energy_intervals(
                    sample_time,
                    sample_generation,
                    sample_generation_time,
                    sample_timedelta,
                    generation_intervals,
                    prev_start,
                    day_start,
                )
                _LOGGER.debug(
                    f"%s increments detected for entity: %s, outlier upper bound: {'%.3f kWh' if result.uniform_increment else '%d seconds'}",  # noqa: G004
                    "Generation-consistent" if result.uniform_increment else "Time-consistent",
                    entity,
                    result.upper,
                )
                for interval in result.ignored:
                    _LOGGER.debug(
                        "Ignoring excessive PV generation jump at %s from entity: %s",
                        interval.astimezone(self.api.tz).strftime(DT_DATE_FORMAT),
                        entity,
                    )
            else:
                _LOGGER.debug(
                    "No day %d PV generation data (or barely any) from entity: %s (%s)",
                    -1 + day * -1,
                    entity,
                    entity_history.get(entity),
                )

        for interval_start, generation in generation_intervals.items():
            generation_intervals[interval_start] = round(generation, 3)

        return generation_intervals

    async def _apply_suppression_entity_limits(
        self,
        export_limiting: dict[dt, bool],
        prev_start: dt,
        day_start: dt,
        entity_registry: er.EntityRegistry,
        recorder_instance: Any,
    ) -> None:
        """Apply suppression-entity state history to export-limiting intervals."""
        platforms = [PLATFORM_BINARY_SENSOR, PLATFORM_SENSOR, PLATFORM_SWITCH]
        find_entity = self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_SUPPRESSION_ENTITY]
        entity = ""
        found = False
        for platform in platforms:
            entity = f"{platform}.{find_entity}"
            r_entity = entity_registry.async_get(entity)
            if r_entity is not None and r_entity.disabled_by is None:
                found = True
                break
        if not found:
            return

        _LOGGER.debug("Suppression entity %s exists", entity)
        entity_history = await self._get_entity_history(
            recorder_instance,
            prev_start,
            day_start,
            entity,
            True,  # No attributes
            False,  # Descending order
            None,  # Limit
            True,  # Include start time state
        )

        if not entity_history.get(entity) or len(entity_history[entity]) == 0:
            return

        entity_state: dict[dt, bool] = {}
        state = False
        for e in entity_history[entity]:
            if e.state not in _SUPPRESSION_ENTITY_STATES:
                continue

            interval = self._bucket_interval_start(e.last_updated.astimezone(UTC))
            if e.state in _SUPPRESSION_ENTITY_ON_STATES:
                state = True
                if not entity_state.get(interval):
                    entity_state[interval] = state
                    interval_plus_half_hour = interval + timedelta(minutes=HALF_HOUR_MINUTES)
                    if state and entity_state.get(interval_plus_half_hour) is not None:
                        entity_state.pop(interval_plus_half_hour)
                _LOGGER.debug(
                    "Interval %s state change %s at %s",
                    interval.astimezone(self.api.tz).strftime(DT_DATE_FORMAT_SHORT),
                    entity_state[interval],
                    e.last_updated.astimezone(self.api.tz).strftime(DT_DATE_FORMAT_SHORT),
                )
            elif state:
                state = False
                interval_plus_half_hour = interval + timedelta(minutes=HALF_HOUR_MINUTES)
                entity_state[interval_plus_half_hour] = False
                _LOGGER.debug(
                    "Interval %s state change %s at %s",
                    interval_plus_half_hour.astimezone(self.api.tz).strftime(DT_DATE_FORMAT_SHORT),
                    entity_state[interval_plus_half_hour],
                    e.last_updated.astimezone(self.api.tz).strftime(DT_DATE_FORMAT_SHORT),
                )

        state = False
        for interval in export_limiting:
            if entity_state.get(interval) is not None:
                state = entity_state[interval]
            export_limiting[interval] = state
            if state:
                _LOGGER.debug("Auto-dampen suppressed for interval %s", interval.astimezone(self.api.tz).strftime(DT_DATE_FORMAT_SHORT))

    async def _apply_site_export_limits(
        self,
        export_limiting: dict[dt, bool],
        prev_start: dt,
        day_start: dt,
        entity_registry: er.EntityRegistry,
        recorder_instance: Any,
    ) -> None:
        """Apply site export-limit detection to half-hour intervals."""
        if self.api.options.site_export_limit <= 0 or self.api.options.site_export_entity == "":
            return

        entity = self.api.options.site_export_entity
        r_entity = entity_registry.async_get(entity)
        if r_entity is None:
            _LOGGER.error("Site export entity %s is not a valid entity", entity)
            return
        if r_entity.disabled_by is not None:
            _LOGGER.error("Site export entity %s is disabled, please enable it", entity)
            return

        export_intervals = self._build_float_intervals(prev_start, _SITE_EXPORT_INTERVAL_MINUTES)
        entity_history = await self._get_entity_history(recorder_instance, prev_start, day_start, entity)
        if not entity_history.get(entity) or len(entity_history[entity]) == 0:
            _LOGGER.debug("No site export history found for %s", entity)
            return

        conversion_factor = self._get_conversion_factor(entity, entity_history[entity])
        sample_time: list[dt] = [
            self._bucket_interval_start(e.last_updated.astimezone(UTC), _SITE_EXPORT_INTERVAL_MINUTES)
            for e in entity_history[entity]
            if e.state.replace(".", "").isnumeric()
        ]
        sample_export: list[float] = [
            0.0,
            *diff([float(e.state) * conversion_factor for e in entity_history[entity] if e.state.replace(".", "").isnumeric()]),
        ]

        for interval, kwh in zip(sample_time, sample_export, strict=True):
            export_intervals[interval] += kwh

        for interval, export in export_intervals.items():
            export_intervals[interval] = round(export * (60 / _SITE_EXPORT_INTERVAL_MINUTES), 3)

        for interval, export in export_intervals.items():
            export_interval = self._bucket_interval_start(interval)
            if export >= self.api.options.site_export_limit:
                export_limiting[export_interval] = True

    async def get_pv_generation(self) -> None:
        """Get PV generation from external entity/entities.

        Supports two entity types:
        - Energy entities (Wh/kWh/MWh, total increasing): Computes energy deltas and distributes across intervals.
        - Power entities (W/kW/MW, instantaneous): Computes time-weighted average power per interval, then converts to kWh.

        The entities must have state history. Very large units are not supported (e.g. GWh, TWh) because of precision loss.
        """

        start_time = time.time()

        # Load the generation history.
        generation: dict[dt, dict[str, Any]] = {generated[PERIOD_START]: generated for generated in self.data_generation[GENERATION]}
        days = 1 if generation else self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_GENERATION_HISTORY_LOAD_DAYS]

        entity_registry = er.async_get(self.api.hass)
        recorder_instance = get_instance(self.api.hass)

        for day in range(days):
            # PV generation
            day_start = self.api.dt_helper.day_start_utc(future=(-1 * day))
            prev_start = day_start - timedelta(days=1)
            generation_intervals = await self._collect_generation_intervals_for_day(
                prev_start,
                day_start,
                day,
                entity_registry,
                recorder_instance,
            )

            export_limiting = self._build_half_hour_bool_intervals(prev_start)
            await self._apply_suppression_entity_limits(
                export_limiting,
                prev_start,
                day_start,
                entity_registry,
                recorder_instance,
            )
            await self._apply_site_export_limits(
                export_limiting,
                prev_start,
                day_start,
                entity_registry,
                recorder_instance,
            )

            # Add recent generation intervals to the history.
            generation.update(
                {
                    i: {PERIOD_START: i, GENERATION: generated, EXPORT_LIMITING: export_limiting[i]}
                    for i, generated in generation_intervals.items()
                }
            )

        # Trim, sort and serialise.
        self.data_generation = {
            LAST_UPDATED: dt.now(UTC).replace(microsecond=0),
            GENERATION: sorted(
                filter(
                    lambda generated: generated[PERIOD_START] >= self.api.dt_helper.day_start_utc(future=-22),
                    generation.values(),
                ),
                key=itemgetter(PERIOD_START),
            ),
        }
        await self.api.sites_cache.serialise_data(self.data_generation, self.filename_generation)
        _LOGGER.debug("Task get_pv_generation took %.3f seconds", time.time() - start_time)

    async def granular_data(self) -> bool:
        """Read the current granular dampening file.

        Returns:
            bool: Granular dampening in use.
        """

        def option(enable: bool, set_allow_reset: bool = False):
            site_damp = self.api.entry_options.get(SITE_DAMP, False) if self.api.entry_options.get(SITE_DAMP) is not None else False
            if enable ^ site_damp:
                options = {**self.api.entry_options}
                options[SITE_DAMP] = enable
                self.api.entry_options[SITE_DAMP] = enable
                if set_allow_reset:
                    self.granular_allow_reset = enable
                if self.api.entry is not None:
                    self.api.hass.config_entries.async_update_entry(self.api.entry, options=options)
            return enable

        error = False
        return_value = False
        mtime = True
        filename = self.get_filename()
        try:
            if not Path(filename).is_file():
                self.factors = {}
                self.factors_mtime = 0
                mtime = False
                return option(GRANULAR_DAMPENING_OFF)
            async with aiofiles.open(filename) as file:
                content = await file.read()
                try:
                    response_json = json.loads(content)
                except json.decoder.JSONDecodeError:
                    _LOGGER.error("JSONDecodeError, dampening ignored: %s", filename)
                    error = True
                    return option(GRANULAR_DAMPENING_OFF, SET_ALLOW_RESET)
                self.factors = cast(dict[str, Any], response_json)
                if content.replace("\n", "").replace("\r", "").strip() != "" and isinstance(response_json, dict) and self.factors:
                    first_site_len = 0
                    for site, damp_list in self.factors.items():
                        if first_site_len == 0:
                            first_site_len = len(damp_list)
                        elif len(damp_list) != first_site_len:
                            _LOGGER.error(
                                "Number of dampening factors for all sites must be the same in %s, dampening ignored",
                                filename,
                            )
                            self.factors = {}
                            error = True
                        if len(damp_list) not in (24, 48):
                            _LOGGER.error(
                                "Number of dampening factors for site %s must be 24 or 48 in %s, dampening ignored",
                                site,
                                filename,
                            )
                            self.factors = {}
                            error = True
                    if error:
                        return_value = option(GRANULAR_DAMPENING_OFF, SET_ALLOW_RESET)
                    else:
                        _LOGGER.debug("Granular dampening %s", str(self.factors))
                        return_value = option(GRANULAR_DAMPENING_ON, SET_ALLOW_RESET)
            return return_value
        finally:
            if mtime:
                self.factors_mtime = Path(filename).stat().st_mtime if Path(filename).exists() else 0
            if error:
                self.factors = {}

    async def load_generation_data(self) -> dict[str, Any] | None:
        """Load generation data from cache file.

        Returns:
            dict[str, Any] | None: The loaded generation data, or None if not found.
        """
        data = None
        if Path(self.filename_generation).is_file():
            async with aiofiles.open(self.filename_generation) as data_file:
                json_data: dict[str, Any] = json.loads(await data_file.read(), cls=JSONDecoder)
                # Note that the generation data cache does not have a version number
                # Future changes to the structure, if any, will need to be handled here by checking current version by allowing for None
                _LOGGER.debug(
                    "Data cache %s exists, file type is %s",
                    self.filename_generation,
                    type(json_data),
                )
                if isinstance(json_data, dict):
                    data = json_data
                    _LOGGER.debug("Generation data loaded")
        return data

    async def migrate_undampened_history(self) -> None:
        """Migrate un-dampened forecasts if un-dampened data for a site does not exist."""
        apply_dampening: list[str] = []
        forecasts: dict[str, dict[dt, Any]] = {}
        past_days = self.api.dt_helper.day_start_utc(future=-14)
        for site in self.api.sites:
            site = site[RESOURCE_ID]
            if not self.api.data_undampened[SITE_INFO].get(site) or len(self.api.data_undampened[SITE_INFO][site].get(FORECASTS, [])) == 0:
                _LOGGER.info(
                    "Migrating un-dampened history to %s for %s",
                    self.api.filename_undampened,
                    site,
                )
                apply_dampening.append(site)
            else:
                continue
            # Load the forecast history.
            forecasts[site] = {forecast[PERIOD_START]: forecast for forecast in self.api.data[SITE_INFO][site][FORECASTS]}
            forecasts_undampened: list[dict[str, Any]] = []
            # Migrate forecast history if un-dampened data does not yet exist.
            if forecasts[site]:
                forecasts_undampened = sorted(
                    {
                        forecast[PERIOD_START]: forecast
                        for forecast in self.api.data[SITE_INFO][site][FORECASTS]
                        if forecast[PERIOD_START] >= past_days
                    }.values(),
                    key=itemgetter(PERIOD_START),
                )
                _LOGGER.debug(
                    "Migrating %d forecast entries to un-dampened forecasts for site %s",
                    len(forecasts_undampened),
                    site,
                )
            self.api.data_undampened[SITE_INFO].update({site: {FORECASTS: copy.deepcopy(forecasts_undampened)}})

        if apply_dampening:
            self.api.data_undampened[LAST_UPDATED] = dt.now(UTC).replace(microsecond=0)
            await self.api.sites_cache.serialise_data(self.api.data_undampened, self.api.filename_undampened)

        if apply_dampening:
            await self.apply_forward(applicable_sites=apply_dampening)
            await self.api.sites_cache.serialise_data(self.api.data, self.api.filename)

    async def calculate_error(
        self,
        generation_day: defaultdict[dt, float],
        generation: defaultdict[dt, dict[str, Any]],
        values: tuple[dict[str, Any], ...],
        percentiles: tuple[int, ...] = (50,),
        log_breakdown: bool = False,
        breakdown_label: str = "",
    ) -> tuple[bool, float, list[float], dict[str, float]]:
        """Calculate mean and percentile absolute percentage error."""
        value_day: defaultdict[dt, float] = defaultdict(float)
        error: defaultdict[dt, float] = defaultdict(float)
        last_day: dt | None = None

        for interval in values:
            i = interval[PERIOD_START].astimezone(self.api.options.tz).replace(hour=0, minute=0, second=0, microsecond=0)
            if i != last_day:
                value_day[i] = 0.0
                last_day = i
            if generation.get(interval[PERIOD_START]) is not None and not generation[interval[PERIOD_START]][EXPORT_LIMITING]:
                value_day[i] += interval[ESTIMATE] / 2  # 30 minute intervals

        for day, value in value_day.items():
            error[day] = abs(generation_day[day] - value) / generation_day[day] * 100.0 if generation_day[day] > 0 else math.inf

            if log_breakdown:
                label_prefix = f"{breakdown_label} " if breakdown_label else ""
                _LOGGER.debug(
                    "%sAPE calculation for day %s, Actual %.2f kWh, Estimate %.2f kWh, Error %.2f%s",
                    label_prefix,
                    day.strftime(DT_DATE_ONLY_FORMAT),
                    generation_day[day],
                    value,
                    error[day],
                    "%" if error[day] != math.inf else "",
                )

        non_inf_error: dict[dt, float] = {k: v for k, v in error.items() if v != math.inf}
        daily: dict[str, float] = {k.strftime(DT_DATE_ONLY_FORMAT): round(v, 2) for k, v in non_inf_error.items()}
        return (
            (
                (len(error) != len(non_inf_error)),
                mean(non_inf_error.values()),
                [percentile(sorted(error.values()), p) for p in percentiles],
                daily,
            )
            if non_inf_error
            else (False, math.inf, [math.inf] * len(percentiles), {})
        )

    async def check_deal_breaker_automated(self) -> bool:
        """Check for deal breakers that would prevent automated dampening from running.

        Returns:
            bool: True if a deal breaker is found, False otherwise.
        """
        deal_breaker = ""
        deal_breaker_site = ""
        if not self.data_generation[GENERATION]:
            deal_breaker = "No generation yet"
        else:
            for site in self.api.sites:
                if self.api.data_actuals[SITE_INFO].get(site[RESOURCE_ID]) is None:
                    deal_breaker = "No estimated actuals yet"
                    deal_breaker_site = site[RESOURCE_ID]
                    break
        if deal_breaker:
            _LOGGER.info("Auto-dampening suppressed: %s%s", deal_breaker, f" for {deal_breaker_site}" if deal_breaker_site else "")
            return True
        return False

    async def model_automated(self, force: bool = False) -> None:
        """Model the automated dampening of the forecast data.

        Look for consistently low PV generation in consistently high estimated actual intervals.
        Dampening factors are always referenced using standard time (not daylight savings time).
        """
        start_time = time.time()

        if not self.api.options.auto_dampen and not force:
            _LOGGER.debug("Automated dampening is not enabled, skipping dampening model_automated()")
            await self.prepare_data(only_peaks=True)
            return

        if await self.check_deal_breaker_automated():
            return

        actuals, ignored_intervals, generation, matching_intervals = await self.prepare_data()

        _LOGGER.debug("Modelling automated dampening factors")

        dampening = await self.calculate(
            matching_intervals, generation, actuals, ignored_intervals, self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL]
        )

        if dampening != self.factors.get(ALL):
            self.factors[ALL] = dampening
            await self.serialise_granular()
            await self.granular_data()
        _LOGGER.debug("Task dampening model_automated took %.3f seconds", time.time() - start_time)

    async def prepare_generation_data(self, earliest_start: dt) -> tuple[defaultdict[dt, dict[str, Any]], defaultdict[dt, float]]:
        """Prepare generation data for accuracy metrics calculation.

        ignore_unmatched excludes intervals below minimum peak in
        determine_best_settings.
        """
        ignored_intervals: list[int] = []  # Intervals to ignore in standard time

        for time_string in self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_IGNORE_INTERVALS]:
            hour, minute = map(int, time_string.split(":"))
            interval = hour * 2 + minute // 30
            ignored_intervals.append(interval)

        model_intervals = self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS] * INTERVALS_PER_DAY
        export_limited_intervals = dict.fromkeys(range(INTERVALS_PER_DAY), False)
        if not self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_NO_LIMITING_CONSISTENCY]:
            for gen in self.data_generation[GENERATION][-model_intervals:]:
                if gen[EXPORT_LIMITING]:
                    export_limited_intervals[self._adjusted_interval(gen)] = True

        data_generation = copy.deepcopy(self.data_generation)
        generation_dampening: defaultdict[dt, dict[str, Any]] = defaultdict(dict[str, Any])
        generation_dampening_day: defaultdict[dt, float] = defaultdict(float)
        for record in data_generation.get(GENERATION, [])[-model_intervals:]:
            if record[PERIOD_START] < earliest_start:
                continue

            interval = self.adjusted_interval_dt(record[PERIOD_START])
            if interval in ignored_intervals or export_limited_intervals[interval]:
                record[EXPORT_LIMITING] = True
                continue

            generation_dampening[record[PERIOD_START]] = {
                GENERATION: record[GENERATION],
                EXPORT_LIMITING: record[EXPORT_LIMITING],
            }
            if not record[EXPORT_LIMITING]:
                generation_dampening_day[
                    record[PERIOD_START].astimezone(self.api.options.tz).replace(hour=0, minute=0, second=0, microsecond=0)
                ] += record[GENERATION]

        return generation_dampening, generation_dampening_day

    async def refresh_granular_data(self) -> None:
        """Load granular dampening data if the file has changed."""
        if Path(self.get_filename()).is_file():
            mtime = Path(self.get_filename()).stat().st_mtime
            if mtime != self.factors_mtime:
                await self.granular_data()
                _LOGGER.info("Granular dampening loaded")
                _LOGGER.debug(
                    "Granular dampening file mtime %s",
                    dt.fromtimestamp(mtime, self.api.tz).strftime(DT_DATE_FORMAT),
                )

    async def serialise_granular(self) -> None:
        """Serialise the site dampening file."""
        filename = self.get_filename()
        _LOGGER.debug("Writing granular dampening to %s", filename)
        payload = json.dumps(
            self.factors,
            ensure_ascii=False,
            cls=NoIndentEncoder,
            indent=2,
        )
        async with self.api.serialise_lock, aiofiles.open(filename, "w") as file:
            await file.write(payload)
        self.factors_mtime = Path(filename).stat().st_mtime
        _LOGGER.debug(
            "Granular dampening file mtime %s",
            dt.fromtimestamp(self.factors_mtime, self.api.tz).strftime(DT_DATE_FORMAT),
        )

    def _adjusted_interval(self, interval: dict[str, Any]) -> int:
        """Adjust a forecast/actual interval as standard time."""
        period_start_tz = interval[PERIOD_START].astimezone(self.api.tz)
        offset = 1 if self.api.dt_helper.is_interval_dst(interval) else 0
        return self._interval_index_from_tz_dt(period_start_tz, offset)

    def apply_adjustment(self, interval_pv50, factor, interval, delta_adjustment_model) -> float:
        """Applies selected delta_adjustment_model to past dampening factor."""
        match delta_adjustment_model:
            case 1:
                # Adjust the factor based on forecast vs. peak interval using squared ratio
                factor = max(factor, factor + ((1.0 - factor) * ((1.0 - (interval_pv50 / self.api.peak_intervals[interval])) ** 2)))
            case _:
                # Adjust the factor based on forecast vs. peak interval delta-logarithmically.
                factor = max(
                    factor,
                    min(
                        1.0,
                        factor + ((1.0 - factor) * (math.log(self.api.peak_intervals[interval]) - math.log(interval_pv50))),
                    ),
                )

        return round(factor, 3)

    def _get_conversion_factor(self, entity: str, entity_history: list[State] | None = None, is_power: bool = False) -> float:
        """Get the conversion factor for an entity to convert to kWh (energy) or kW (power)."""

        if is_power:
            unit_factors = _POWER_UNIT_FACTORS
            default_unit = "kW"
        else:
            unit_factors = _ENERGY_UNIT_FACTORS
            default_unit = "kWh"

        entity_unit = None

        if entity_history:
            latest_state = entity_history[-1]
            if hasattr(latest_state, "attributes") and latest_state.attributes:
                entity_unit = latest_state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)

        if not entity_unit:
            entity_registry = er.async_get(self.api.hass)
            entity_entry = entity_registry.async_get(entity)
            if entity_entry and entity_entry.unit_of_measurement:
                entity_unit = entity_entry.unit_of_measurement

        if not entity_unit:
            _LOGGER.warning("Entity %s has no %s, assuming %s", entity, ATTR_UNIT_OF_MEASUREMENT, default_unit)
            return 1.0

        conversion_factor = unit_factors.get(entity_unit)
        if conversion_factor is None:
            _LOGGER.error("Entity %s has an unsupported %s '%s', assuming %s", entity, ATTR_UNIT_OF_MEASUREMENT, entity_unit, default_unit)
            return 1.0

        if conversion_factor != 1.0:
            _LOGGER.debug("Entity %s uses %s, applying conversion factor %s", entity, entity_unit, conversion_factor)

        return conversion_factor

    def _is_power_entity(self, entity: str) -> bool:
        """Determine whether a generation entity is a power (W/kW) entity rather than energy (Wh/kWh)."""

        entity_registry = er.async_get(self.api.hass)
        r_entity = entity_registry.async_get(entity)
        if r_entity is not None:
            dc = r_entity.device_class or r_entity.original_device_class
            if dc == SensorDeviceClass.POWER:
                return True
        return False

    async def calculate(  # noqa: C901
        self,
        matching_intervals: dict[int, list[dt]],
        generation: dict[dt, float],
        actuals: dict[dt, float],
        ignored_intervals: list[int],
        dampening_model: int,
        verbose_log: bool = True,
        target_day: dt | None = None,
    ) -> list[float]:
        """Applies selected dampening_model to passed data to calculate list of dampening factors."""

        dampening = [1.0] * INTERVALS_PER_DAY  # Initialize dampening factors

        apply_elevation_adjustment = bool(self.api.advanced_options.get(ADVANCED_AUTOMATED_DAMPENING_ELEVATION_ADJUSTMENT, False))
        if apply_elevation_adjustment and target_day is None:
            target_day = self.api.dt_helper.day_start_utc()

        # For the default model, ceiling comes from self.api.peak_intervals, which is the un-normalised max of past estimated
        # actuals across MODEL_DAYS. It is normalised here (when elevation adjustment is enabled) to target_day's sun elevation.
        peak_intervals: dict[int, float] = self.api.peak_intervals
        if apply_elevation_adjustment and target_day is not None:
            normalised_peaks: dict[int, float] = dict.fromkeys(range(INTERVALS_PER_DAY), 0.0)
            for period_start, actual in actuals.items():
                ratio = self.elevation_adjustment_ratio(period_start, self._target_timestamp(period_start, target_day))
                adjusted = actual * ratio
                idx = self.adjusted_interval_dt(period_start)
                if normalised_peaks[idx] < adjusted:
                    normalised_peaks[idx] = round(adjusted, 3)
            peak_intervals = normalised_peaks

        # Check the generation for each interval and determine if it is consistently lower than the peak.
        for interval, matching in matching_intervals.items():
            # Get current factor if required
            if self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_PRESERVE_UNMATCHED_FACTORS]:
                prior_factor = self.factors[ALL][interval] if self.factors.get(ALL) is not None else 1.0

            dst_offset = (
                1
                if self.api.dt_helper.dst(
                    dt.now(self.api.tz).replace(hour=interval // 2, minute=30 * (interval % 2), second=0, microsecond=0)
                )
                else 0
            )
            interval_time = f"{interval // 2 + (dst_offset):02}:{30 * (interval % 2):02}"
            if interval in ignored_intervals:
                if verbose_log:
                    _LOGGER.debug("Interval %s is intentionally ignored, skipping", interval_time)
                continue
            # Build (timestamp, gen, elevation_ratio) triplets for matching intervals
            # that have non-zero generation. The ratio is retained so that per-pair
            # raw dampening factors (gen/act) can be normalised to target_day's sun
            # geometry in the 1/2/3 models below.
            sample_triplets: list[tuple[dt, float, float]] = []
            for timestamp in matching:
                raw_gen = round(generation.get(timestamp, 0.0), 3)
                if raw_gen == 0.0:
                    continue
                if apply_elevation_adjustment and target_day is not None:
                    ratio = self.elevation_adjustment_ratio(timestamp, self._target_timestamp(timestamp, target_day))
                else:
                    ratio = 1.0
                sample_triplets.append((timestamp, raw_gen, ratio))
            generation_samples: list[float] = [gen for _, gen, _ in sample_triplets]
            preserve_this_interval = False
            if matching:
                msg = ""
                log_msg = True
                if verbose_log:
                    _LOGGER.debug(
                        "Interval %s has peak estimated actual %.3f and %d matching intervals: %s",
                        interval_time,
                        peak_intervals[interval],
                        len(matching),
                        ", ".join([date.astimezone(self.api.tz).strftime(DT_DATE_MONTH_DAY) for date in matching]),
                    )
                match dampening_model:
                    case 1 | 2 | 3:
                        if len(matching) >= self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_INTERVALS]:
                            actual_samples: list[float] = [actuals.get(timestamp, 0.0) for timestamp, _, _ in sample_triplets]
                            ratio_samples: list[float] = [ratio for _, _, ratio in sample_triplets]
                            if verbose_log:
                                _LOGGER.debug(
                                    "Selected %d estimated actuals for %s: %s",
                                    len(actual_samples),
                                    interval_time,
                                    ", ".join(f"{act:.3f}" for act in actual_samples),
                                )
                                _LOGGER.debug(
                                    "Selected %d generation records for %s: %s",
                                    len(generation_samples),
                                    interval_time,
                                    generation_samples,
                                )
                            if (
                                len(generation_samples)
                                >= self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_GENERATION]
                            ):
                                if len(actual_samples) == len(generation_samples):
                                    raw_factors: list[float] = []
                                    for act, gen, ratio in zip(actual_samples, generation_samples, ratio_samples, strict=True):
                                        if act <= 0:
                                            raw_factors.append(1.0)
                                            continue
                                        # Normalise each historical pair's factor to target_day's sun geometry.
                                        # Cap at 1.0 since dampening cannot amplify.
                                        raw_factors.append(min((gen / act) * ratio, 1.0))
                                    if verbose_log:
                                        if apply_elevation_adjustment and any(r != 1.0 for r in ratio_samples):
                                            _LOGGER.debug(
                                                "Elevation ratios applied for %s: %s",
                                                interval_time,
                                                ", ".join(f"{r:.3f}" for r in ratio_samples),
                                            )
                                        _LOGGER.debug(
                                            "Candidate factors for %s: %s",
                                            interval_time,
                                            ", ".join(f"{fact:.3f}" for fact in raw_factors),
                                        )
                                    match dampening_model:
                                        case 1:  # max factor from matched pairs
                                            factor = max(raw_factors)
                                        case 2:  # average factor from matched pairs
                                            factor = mean(raw_factors)
                                        case 3:  # min factor from matched pairs
                                            factor = min(raw_factors)
                                    factor = round(factor, 3) if factor > 0 else 1.0
                                    if self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR] <= factor < 1.0:
                                        msg = f"Ignoring insignificant factor for {interval_time} of {factor:.3f}"
                                        factor = 1.0
                                    else:
                                        msg = f"Auto-dampen factor for {interval_time} is {factor:.3f}"
                                    dampening[interval] = factor
                                msg = (
                                    f"Mismatched sample lengths for {interval_time}: {len(actual_samples)} actuals vs {len(generation_samples)} generations"
                                    if len(actual_samples) != len(generation_samples)
                                    else msg
                                )
                            else:
                                msg = f"Not enough reliable generation samples for {interval_time} to determine dampening ({len(generation_samples)})"
                                preserve_this_interval = self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_PRESERVE_UNMATCHED_FACTORS]
                    case _:
                        # Normalise the numerator. Historical generation samples are scaled to what they would have been on target_day
                        # given that interval's sun elevation. Pair the denominator (peak_intervals, already normalised above).
                        normalised_generation = [round(gen * ratio, 3) for _, gen, ratio in sample_triplets]
                        peak = max(normalised_generation) if normalised_generation else 0.0
                        if verbose_log:
                            _LOGGER.debug("Interval %s max generation: %.3f, %s", interval_time, peak, normalised_generation)
                        if len(matching) >= self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_INTERVALS]:
                            if peak < peak_intervals[interval]:
                                if (
                                    len(generation_samples)
                                    >= self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_GENERATION]
                                ):
                                    factor = (peak / peak_intervals[interval]) if peak_intervals[interval] != 0 else 1.0
                                    if self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR] <= factor < 1.0:
                                        msg = f"Ignoring insignificant factor for {interval_time} of {factor:.3f}"
                                        factor = 1.0
                                    else:
                                        msg = f"Auto-dampen factor for {interval_time} is {factor:.3f}"
                                    dampening[interval] = round(factor, 3)
                                else:
                                    msg = f"Not enough reliable generation samples for {interval_time} to determine dampening ({len(generation_samples)})"
                                    preserve_this_interval = self.api.advanced_options[
                                        ADVANCED_AUTOMATED_DAMPENING_PRESERVE_UNMATCHED_FACTORS
                                    ]
                            else:
                                log_msg = False

                if not preserve_this_interval:
                    msg = (
                        f"Not enough matching intervals for {interval_time} to determine dampening"
                        if len(matching) < self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_INTERVALS]
                        else msg
                    )
                    preserve_this_interval = (
                        self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_PRESERVE_UNMATCHED_FACTORS]
                        and len(matching) < self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_INTERVALS]
                    )

                if preserve_this_interval:
                    dampening[interval] = prior_factor
                    msg = msg + f", preserving prior factor {prior_factor:.3f}" if prior_factor != 1.0 else msg

                if log_msg and msg != "" and verbose_log:
                    _LOGGER.debug(msg)

        return dampening

    @staticmethod
    def _get_earliest_estimate_after(data: list[dict[str, Any]], after: dt, dampened: bool = False) -> dt | None:
        """Get the earliest estimated actual datetime after a specified datetime."""
        earliest = None
        if data:
            # Find all actuals with period_start >= after, then get the earliest one
            in_scope_actuals = [actual[PERIOD_START] for actual in data if actual[PERIOD_START] >= after]
            earliest = min(in_scope_actuals) if in_scope_actuals else None
            _LOGGER.debug(
                "Earliest applicable %s estimated actual datetime is %s",
                "dampened" if dampened else "undampened",
                earliest,
            )
        return earliest

    def _get_granular_factor(self, site: str, period_start: dt, interval_pv50: float = -1.0, record_adjustment: bool = False) -> float:
        """Retrieve a granular dampening factor."""
        factor = self.factors[site][
            period_start.hour if len(self.factors[site]) == 24 else ((period_start.hour * 2) + (1 if period_start.minute > 0 else 0))
        ]
        if (
            site == ALL
            and (self.api.options.auto_dampen or self.api.advanced_options[ADVANCED_GRANULAR_DAMPENING_DELTA_ADJUSTMENT])
            and self.factors.get(ALL)
        ):
            interval = self.adjusted_interval_dt(period_start)
            factor = min(1.0, self.factors[ALL][interval])
            if (
                not self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_NO_DELTA_ADJUSTMENT]
                and self.api.peak_intervals[interval] > 0
                and interval_pv50 > 0
                and factor < 1.0
            ):
                interval_time = period_start.astimezone(self.api.tz).strftime(DT_DATE_FORMAT)
                factor_pre_adjustment = factor

                factor = self.apply_adjustment(
                    interval_pv50, factor, interval, self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL]
                )

                if (
                    record_adjustment
                    and period_start.astimezone(self.api.tz).date() == dt.now(self.api.tz).date()
                    and round(factor, 3) != round(factor_pre_adjustment, 3)
                ):
                    _LOGGER.debug(
                        "%sdjusted granular dampening factor for %s, %.3f (was %.3f, peak %.3f, interval pv50 %.3f)",
                        "Ignoring insignificant a"
                        if self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR_ADJUSTED] <= factor < 1.0
                        else "A",
                        interval_time,
                        factor,
                        factor_pre_adjustment,
                        self.api.peak_intervals[interval],
                        interval_pv50,
                    )
                factor = 1.0 if factor >= self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR_ADJUSTED] else factor

        return min(1.0, factor)

    async def prepare_data(
        self, only_peaks: bool = False
    ) -> tuple[OrderedDict[dt, float], list[int], dict[dt, float], dict[int, list[dt]]]:
        """Builds data required for dampening calculations."""
        actuals: OrderedDict[dt, float] = OrderedDict()
        model_days: int = self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS]

        _LOGGER.debug("Determining peak estimated actual intervals%s", " and dampening data" if not only_peaks else "")
        if (
            self.api.options.auto_dampen or self.api.advanced_options[ADVANCED_GRANULAR_DAMPENING_DELTA_ADJUSTMENT]
        ) and self.api.options.get_actuals:
            for site in self.api.sites:
                if self._should_exclude_site(site[RESOURCE_ID]):
                    _LOGGER.debug("Auto-dampening suppressed: Excluded site for %s", site[RESOURCE_ID])
                    continue
                start, end = self.api.query.get_list_slice(
                    self.api.data_actuals[SITE_INFO][site[RESOURCE_ID]][FORECASTS],
                    self.api.dt_helper.day_start_utc() - timedelta(days=model_days),
                    self.api.dt_helper.day_start_utc(),
                    search_past=True,
                )
                site_actuals = {
                    actual[PERIOD_START]: actual for actual in self.api.data_actuals[SITE_INFO][site[RESOURCE_ID]][FORECASTS][start:end]
                }
                for period_start, actual in site_actuals.items():
                    extant: float | None = actuals.get(period_start)
                    if extant is not None:
                        actuals[period_start] += actual[ESTIMATE] * 0.5
                    else:
                        actuals[period_start] = actual[ESTIMATE] * 0.5

            # Collect top intervals from the past MODEL_DAYS days.
            self.api.peak_intervals = dict.fromkeys(range(INTERVALS_PER_DAY), 0.0)
            for period_start, actual in actuals.items():
                interval = self.adjusted_interval_dt(period_start)
                if self.api.peak_intervals[interval] < actual:
                    self.api.peak_intervals[interval] = round(actual, 3)

        if only_peaks:
            return actuals, [], {}, {}

        ignore_intervals_cfg: list[str] = self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_IGNORE_INTERVALS]
        no_limiting: bool = self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_NO_LIMITING_CONSISTENCY]
        similar_peak: float = self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_SIMILAR_PEAK]

        ignored_intervals: list[int] = []  # Intervals to ignore in local time zone
        for time_string in ignore_intervals_cfg:
            hour, minute = map(int, time_string.split(":"))
            interval = hour * 2 + minute // 30
            ignored_intervals.append(interval)

        model_intervals = model_days * INTERVALS_PER_DAY
        export_limited_intervals = dict.fromkeys(range(INTERVALS_PER_DAY), False)
        if not no_limiting:
            for gen in self.data_generation[GENERATION][-model_intervals:]:
                if gen[EXPORT_LIMITING]:
                    export_limited_intervals[self._adjusted_interval(gen)] = True

        generation: dict[dt, float] = {}
        for gen in self.data_generation[GENERATION][-model_intervals:]:
            if not no_limiting:
                if not export_limited_intervals[self._adjusted_interval(gen)]:
                    generation[gen[PERIOD_START]] = gen[GENERATION]
            elif not gen[EXPORT_LIMITING]:
                generation[gen[PERIOD_START]] = gen[GENERATION]

        # Collect intervals that are close to the peak.
        matching_intervals: dict[int, list[dt]] = {i: [] for i in range(INTERVALS_PER_DAY)}
        for period_start, actual in actuals.items():
            interval = self.adjusted_interval_dt(period_start)
            if actual > similar_peak * self.api.peak_intervals[interval]:
                matching_intervals[interval].append(period_start)
        return actuals, ignored_intervals, generation, matching_intervals
