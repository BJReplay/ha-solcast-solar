"""Solcast automated dampening."""

# pylint: disable=pointless-string-statement

from __future__ import annotations

import asyncio
from collections import OrderedDict, defaultdict
import copy
from datetime import UTC, datetime as dt, timedelta
import json
import logging
import math
from operator import itemgetter
from pathlib import Path
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

from .const import (
    ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL,
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
    EXPORT_LIMITING,
    FORECASTS,
    GENERATION,
    GENERATION_VERSION,
    LAST_UPDATED,
    PERIOD_START,
    PLATFORM_BINARY_SENSOR,
    PLATFORM_SENSOR,
    PLATFORM_SWITCH,
    RESOURCE_ID,
    SITE,
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
    percentile,
)

if TYPE_CHECKING:
    from .solcastapi import SolcastApi

GRANULAR_DAMPENING_OFF: Final[bool] = False
GRANULAR_DAMPENING_ON: Final[bool] = True
SET_ALLOW_RESET: Final[bool] = True


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
        offset = 1 if self.api.dt_helper.dst(interval.astimezone(self.api.tz)) else 0
        return (
            ((interval.astimezone(self.api.tz).hour - offset) * 2 + interval.astimezone(self.api.tz).minute // 30)
            if interval.astimezone(self.api.tz).hour - offset >= 0
            else 0
        )

    async def apply_forward(self, applicable_sites: list[str] | None = None, do_past_hours: int = 0) -> None:
        """Apply dampening to forward forecasts."""
        if len(self.api.data_undampened[SITE_INFO]) > 0:
            _LOGGER.debug("Applying future dampening")

            self.auto_factors = {
                period_start: factor
                for period_start, factor in self.auto_factors.items()
                if period_start >= self.api.dt_helper.day_start_utc()
            }

            undampened_interval_pv50: dict[dt, float] = {}
            for site in self.api.sites:
                if site[RESOURCE_ID] in self.api.options.exclude_sites:
                    continue
                for forecast in self.api.data_undampened[SITE_INFO][site[RESOURCE_ID]][FORECASTS]:
                    period_start = forecast[PERIOD_START]
                    if period_start >= self.api.dt_helper.day_start_utc():
                        if period_start not in undampened_interval_pv50:
                            undampened_interval_pv50[period_start] = forecast[ESTIMATE] * 0.5
                        else:
                            undampened_interval_pv50[period_start] += forecast[ESTIMATE] * 0.5

            record_adjustment = True
            for site in self.api.sites:
                # Load all forecasts.
                forecasts_undampened_future = [
                    forecast
                    for forecast in self.api.data_undampened[SITE_INFO][site[RESOURCE_ID]][FORECASTS]
                    if forecast[PERIOD_START]
                    >= (
                        self.api.dt_helper.day_start_utc()
                        if self.api.data[SITE_INFO].get(site[RESOURCE_ID])
                        else self.api.dt_helper.day_start_utc() - timedelta(hours=do_past_hours)
                    )
                ]
                forecasts = (
                    {forecast[PERIOD_START]: forecast for forecast in self.api.data[SITE_INFO][site[RESOURCE_ID]][FORECASTS]}
                    if self.api.data[SITE_INFO].get(site[RESOURCE_ID])
                    else {}
                )

                await asyncio.sleep(0)  # Yield to event loop to avoid blocking

                if site[RESOURCE_ID] not in self.api.options.exclude_sites and (
                    (site[RESOURCE_ID] in applicable_sites) if applicable_sites else True
                ):
                    # Apply dampening to forward data
                    for forecast in sorted(forecasts_undampened_future, key=itemgetter(PERIOD_START)):
                        period_start = forecast[PERIOD_START]
                        pv = round(forecast[ESTIMATE], 4)
                        pv10 = round(forecast[ESTIMATE10], 4)
                        pv90 = round(forecast[ESTIMATE90], 4)

                        # Retrieve the dampening factor for the period, and dampen the estimates.
                        dampening_factor = self.get_factor(
                            site[RESOURCE_ID],
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
                    record_adjustment = False
                else:
                    for forecast in sorted(forecasts_undampened_future, key=itemgetter(PERIOD_START)):
                        period_start = forecast[PERIOD_START]
                        forecast_entry_update(
                            forecasts,
                            period_start,
                            round(forecast[ESTIMATE], 4),
                            round(forecast[ESTIMATE10], 4),
                            round(forecast[ESTIMATE90], 4),
                        )

                await self.api.fetcher.sort_and_prune(
                    site[RESOURCE_ID], self.api.data, self.api.advanced_options[ADVANCED_HISTORY_MAX_DAYS], forecasts
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
            if site[RESOURCE_ID] in self.api.options.exclude_sites:
                continue

            periods = recovered_periods_by_site.get(site[RESOURCE_ID])
            if not periods:
                continue

            _LOGGER.debug(
                "Apply dampening to recovered historical estimated actuals for %s (%d samples)",
                site[RESOURCE_ID],
                len(periods),
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

    def _build_actuals_interval_pv50(self, applicable_periods: set[dt]) -> dict[dt, float]:
        """Build combined pv50 values for estimated actual timestamps."""
        undampened_interval_pv50: dict[dt, float] = {}

        for site in self.api.sites:
            if site[RESOURCE_ID] in self.api.options.exclude_sites:
                continue
            for forecast in self.api.data_actuals[SITE_INFO][site[RESOURCE_ID]][FORECASTS]:
                period_start = forecast[PERIOD_START]
                if period_start in applicable_periods:
                    if period_start not in undampened_interval_pv50:
                        undampened_interval_pv50[period_start] = forecast[ESTIMATE] * 0.5
                    else:
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
                if site[RESOURCE_ID] not in self.api.options.exclude_sites
                for forecast in self.api.data_actuals[SITE_INFO][site[RESOURCE_ID]][FORECASTS]
                if start <= forecast[PERIOD_START] < end
            }
        )

        for site in self.api.sites:
            if site[RESOURCE_ID] in self.api.options.exclude_sites:
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
                if not all_set:
                    if site in self.factors:
                        return [
                            {
                                SITE: _site if not site_underscores else _site.replace("-", "_"),
                                "damp_factor": ",".join(str(factor) for factor in self.factors[_site]),
                            }
                            for _site in sites
                            if self.factors.get(_site)
                        ]
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key="damp_not_for_site",
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
                    SITE: _site if not site_underscores else _site.replace("-", "_"),
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
            translation_key="damp_use_all",
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

    async def get_pv_generation(self) -> None:  # noqa: C901
        """Get PV generation from external entity/entities.

        Supports two entity types:
        - Energy entities (Wh/kWh/MWh, total increasing): Computes energy deltas and distributes across intervals.
        - Power entities (W/kW/MW, instantaneous): Computes time-weighted average power per interval, then converts to kWh.

        The entities must have state history. Very large units are not supported (e.g. GWh, TWh) because of precision loss.
        """

        start_time = time.time()

        _ON = ("on", "1", "true", "True")
        _ALL = ("on", "off", "1", "0", "true", "false", "True", "False")

        # Load the generation history.
        generation: dict[dt, dict[str, Any]] = {generated[PERIOD_START]: generated for generated in self.data_generation[GENERATION]}
        days = 1 if len(generation) > 0 else self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_GENERATION_HISTORY_LOAD_DAYS]

        entity_registry = er.async_get(self.api.hass)

        for day in range(days):
            # PV generation
            generation_intervals: dict[dt, float] = {
                self.api.dt_helper.day_start_utc(future=(-1 * day)) - timedelta(days=1) + timedelta(minutes=minute): 0
                for minute in range(0, 1440, 30)
            }
            for entity in self.api.options.generation_entities:
                r_entity = entity_registry.async_get(entity)
                if r_entity is None:
                    _LOGGER.error("Generation entity %s is not a valid entity", entity)
                    continue
                if r_entity.disabled_by is not None:
                    _LOGGER.error("Generation entity %s is disabled, please enable it", entity)
                    continue
                entity_history = await get_instance(self.api.hass).async_add_executor_job(
                    state_changes_during_period,
                    self.api.hass,
                    self.api.dt_helper.day_start_utc(future=(-1 * day)) - timedelta(days=1),
                    self.api.dt_helper.day_start_utc(future=(-1 * day)),
                    entity,
                )
                if entity_history.get(entity) and len(entity_history[entity]) > 4:
                    _LOGGER.debug("Retrieved day %d PV generation data from entity: %s", -1 + day * -1, entity)

                    if self._is_power_entity(entity):
                        # Power entity: compute time-weighted average kW per interval, then convert to kWh (* 0.5).
                        conversion_factor = self._get_conversion_factor(entity, entity_history[entity], is_power=True)

                        # Build list of (timestamp, power_kW) from state history.
                        power_readings: list[tuple[dt, float]] = [
                            (e.last_updated.astimezone(UTC), float(e.state) * conversion_factor)
                            for e in entity_history[entity]
                            if e.state.replace(".", "").isnumeric()
                        ]

                        if not compute_power_intervals(power_readings, generation_intervals):
                            _LOGGER.debug("Insufficient power readings for entity: %s", entity)

                    else:
                        # Energy entity: compute deltas and distribute across intervals.
                        conversion_factor = self._get_conversion_factor(entity, entity_history[entity])
                        # Arrange the generation samples into half-hour intervals.
                        sample_time: list[dt] = [
                            e.last_updated.astimezone(UTC).replace(
                                minute=e.last_updated.astimezone(UTC).minute // 30 * 30, second=0, microsecond=0
                            )
                            for e in entity_history[entity]
                            if e.state.replace(".", "").isnumeric()
                        ]
                        # Build a list of generation delta values.
                        sample_generation: list[float] = [
                            0.0,
                            *diff(
                                [float(e.state) * conversion_factor for e in entity_history[entity] if e.state.replace(".", "").isnumeric()]
                            ),
                        ]
                        sample_generation_time: list[dt] = [
                            e.last_updated.astimezone(UTC) for e in entity_history[entity] if e.state.replace(".", "").isnumeric()
                        ]
                        sample_timedelta: list[int] = [
                            0,
                            *diff(
                                [
                                    (
                                        e.last_updated.astimezone(UTC)
                                        - (self.api.dt_helper.day_start_utc(future=(-1 * day)) - timedelta(days=1))
                                    ).total_seconds()
                                    for e in entity_history[entity]
                                    if e.state.replace(".", "").isnumeric()
                                ]
                            ),
                        ]

                        period_start = self.api.dt_helper.day_start_utc(future=(-1 * day)) - timedelta(days=1)
                        period_end = self.api.dt_helper.day_start_utc(future=(-1 * day))
                        if sample_generation_time and sample_generation_time[0] == period_start:
                            sample_generation[0] = 0.0
                            sample_timedelta[0] = 0

                        result = compute_energy_intervals(
                            sample_time,
                            sample_generation,
                            sample_generation_time,
                            sample_timedelta,
                            generation_intervals,
                            period_start,
                            period_end,
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
            for i, gen in generation_intervals.items():
                generation_intervals[i] = round(gen, 3)

            export_limiting: dict[dt, bool] = {
                self.api.dt_helper.day_start_utc(future=(-1 * day)) - timedelta(days=1) + timedelta(minutes=minute): False
                for minute in range(0, 1440, 30)
            }

            # Identify intervals intentionally disabled by the user.
            platforms = [PLATFORM_BINARY_SENSOR, PLATFORM_SENSOR, PLATFORM_SWITCH]
            find_entity = self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_SUPPRESSION_ENTITY]
            entity = ""
            found = False
            for p in platforms:
                entity = f"{p}.{find_entity}"
                r_entity = entity_registry.async_get(entity)
                if r_entity is not None and r_entity.disabled_by is None:
                    found = True
                    break
            if found:
                _LOGGER.debug("Suppression entity %s exists", entity)
                query_start_time = self.api.dt_helper.day_start_utc(future=(-1 * day)) - timedelta(days=1)
                query_end_time = self.api.dt_helper.day_start_utc(future=(-1 * day))

                # Get state changes during the period
                entity_history = await get_instance(self.api.hass).async_add_executor_job(
                    state_changes_during_period,
                    self.api.hass,
                    query_start_time,
                    query_end_time,
                    entity,
                    True,  # No attributes
                    False,  # Descending order
                    None,  # Limit
                    True,  # Include start time state
                )

                if entity_history.get(entity) and len(entity_history[entity]):
                    entity_state: dict[dt, bool] = {}
                    state = False

                    for e in entity_history[entity]:
                        if e.state not in _ALL:
                            continue
                        interval = e.last_updated.astimezone(UTC).replace(
                            minute=e.last_updated.astimezone(UTC).minute // 30 * 30, second=0, microsecond=0
                        )
                        if e.state in _ON:
                            state = True
                            if not entity_state.get(interval):
                                entity_state[interval] = state
                                if state and entity_state.get(interval + timedelta(minutes=30)) is not None:
                                    entity_state.pop(interval + timedelta(minutes=30))
                            _LOGGER.debug(
                                "Interval %s state change %s at %s",
                                interval.astimezone(self.api.tz).strftime(DT_DATE_FORMAT_SHORT),
                                entity_state[interval],
                                e.last_updated.astimezone(self.api.tz).strftime(DT_DATE_FORMAT_SHORT),
                            )
                        elif state:
                            state = False
                            entity_state[interval + timedelta(minutes=30)] = False
                            _LOGGER.debug(
                                "Interval %s state change %s at %s",
                                (interval + timedelta(minutes=30)).astimezone(self.api.tz).strftime(DT_DATE_FORMAT_SHORT),
                                entity_state[interval + timedelta(minutes=30)],
                                e.last_updated.astimezone(self.api.tz).strftime(DT_DATE_FORMAT_SHORT),
                            )
                    state = False
                    for interval in export_limiting:
                        if entity_state.get(interval) is not None:
                            state = entity_state[interval]
                        export_limiting[interval] = state
                        if state:
                            _LOGGER.debug(
                                "Auto-dampen suppressed for interval %s", interval.astimezone(self.api.tz).strftime(DT_DATE_FORMAT_SHORT)
                            )

            # Detect site export limiting
            if self.api.options.site_export_limit > 0 and self.api.options.site_export_entity != "":
                _INTERVAL = 5  # The time window in minutes to detect export limiting

                entity = self.api.options.site_export_entity
                r_entity = entity_registry.async_get(entity)
                if r_entity is None:
                    _LOGGER.error("Site export entity %s is not a valid entity", entity)
                    entity = ""
                elif r_entity.disabled_by is not None:
                    _LOGGER.error("Site export entity %s is disabled, please enable it", entity)
                    entity = ""
                export_intervals: dict[dt, float] = {
                    self.api.dt_helper.day_start_utc(future=(-1 * day)) - timedelta(days=1) + timedelta(minutes=minute): 0
                    for minute in range(0, 1440, _INTERVAL)
                }
                if entity:
                    entity_history = await get_instance(self.api.hass).async_add_executor_job(
                        state_changes_during_period,
                        self.api.hass,
                        self.api.dt_helper.day_start_utc(future=(-1 * day)) - timedelta(days=1),
                        self.api.dt_helper.day_start_utc(future=(-1 * day)),
                        entity,
                    )
                    if entity_history.get(entity) and len(entity_history[entity]):
                        # Get the conversion factor for the entity to convert to kWh.
                        conversion_factor = self._get_conversion_factor(entity, entity_history[entity])
                        # Arrange the site export samples into intervals.
                        sample_time: list[dt] = [
                            e.last_updated.astimezone(UTC).replace(
                                minute=e.last_updated.astimezone(UTC).minute // _INTERVAL * _INTERVAL, second=0, microsecond=0
                            )
                            for e in entity_history[entity]
                            if e.state.replace(".", "").isnumeric()
                        ]
                        # Build a list of export delta values.
                        sample_export: list[float] = [
                            0.0,
                            *diff(
                                [float(e.state) * conversion_factor for e in entity_history[entity] if e.state.replace(".", "").isnumeric()]
                            ),
                        ]
                        for interval, kWh in zip(sample_time, sample_export, strict=True):
                            export_intervals[interval] += kWh
                        # Convert to export per interval in kW.
                        for i, export in export_intervals.items():
                            export_intervals[i] = round(export * (60 / _INTERVAL), 3)

                        for i, export in export_intervals.items():
                            export_interval = i.replace(minute=i.minute // 30 * 30)
                            if export >= self.api.options.site_export_limit:
                                export_limiting[export_interval] = True
                    else:
                        _LOGGER.debug("No site export history found for %s", entity)

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
            if len(forecasts[site]) > 0:
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

        if len(apply_dampening) > 0:
            self.api.data_undampened[LAST_UPDATED] = dt.now(UTC).replace(microsecond=0)
            await self.api.sites_cache.serialise_data(self.api.data_undampened, self.api.filename_undampened)

        if len(apply_dampening) > 0:
            await self.apply_forward(applicable_sites=apply_dampening)
            await self.api.sites_cache.serialise_data(self.api.data, self.api.filename)

    async def calculate_error(
        self,
        generation_day: defaultdict[dt, float],
        generation: defaultdict[dt, dict[str, Any]],
        values: tuple[dict[str, Any], ...],
        percentiles: tuple[int, ...] = (50,),
        log_breakdown: bool = False,
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
                _LOGGER.debug(
                    "APE calculation for day %s, Actual %.2f kWh, Estimate %.2f kWh, Error %.2f%s",
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
                sum(non_inf_error.values()) / len(non_inf_error),
                [percentile(sorted(error.values()), p) for p in percentiles],
                daily,
            )
            if len(non_inf_error) > 0
            else (False, math.inf, [math.inf] * len(percentiles), {})
        )

    async def check_deal_breaker_automated(self) -> bool:
        """Check for deal breakers that would prevent automated dampening from running.

        Returns:
            bool: True if a deal breaker is found, False otherwise.
        """
        deal_breaker = ""
        deal_breaker_site = ""
        if len(self.data_generation[GENERATION]) == 0:
            deal_breaker = "No generation yet"
        else:
            for site in self.api.sites:
                if self.api.data_actuals[SITE_INFO].get(site[RESOURCE_ID]) is None:
                    deal_breaker = "No estimated actuals yet"
                    deal_breaker_site = site[RESOURCE_ID]
                    break
        if deal_breaker != "":
            _LOGGER.info("Auto-dampening suppressed: %s%s", deal_breaker, f" for {deal_breaker_site}" if deal_breaker_site != "" else "")
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

        export_limited_intervals = dict.fromkeys(range(48), False)
        if not self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_NO_LIMITING_CONSISTENCY]:
            for gen in self.data_generation[GENERATION][-1 * self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS] * 48 :]:
                if gen[EXPORT_LIMITING]:
                    export_limited_intervals[self._adjusted_interval(gen)] = True

        data_generation = copy.deepcopy(self.data_generation)
        generation_dampening: defaultdict[dt, dict[str, Any]] = defaultdict(dict[str, Any])
        generation_dampening_day: defaultdict[dt, float] = defaultdict(float)
        for record in data_generation.get(GENERATION, [])[-1 * self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS] * 48 :]:
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
        offset = 1 if self.api.dt_helper.is_interval_dst(interval) else 0
        return (
            (
                (interval[PERIOD_START].astimezone(self.api.tz).hour - offset) * 2
                + interval[PERIOD_START].astimezone(self.api.tz).minute // 30
            )
            if interval[PERIOD_START].astimezone(self.api.tz).hour - offset >= 0
            else 0
        )

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
            unit_factors = {"mW": 1e-6, "W": 0.001, "kW": 1.0, "MW": 1000.0}
            default_unit = "kW"
        else:
            unit_factors = {"mWh": 1e-6, "Wh": 0.001, "kWh": 1.0, "MWh": 1000.0}
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
    ) -> list[float]:
        """Applies selected dampening_model to passed data to calculate list of dampening factors."""

        dampening = [1.0] * 48  # Initialize dampening factors

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
            generation_samples: list[float] = [
                round(generation.get(timestamp, 0.0), 3) for timestamp in matching if generation.get(timestamp, 0.0) != 0.0
            ]
            preserve_this_interval = False
            if len(matching) > 0:
                msg = ""
                log_msg = True
                if verbose_log:
                    _LOGGER.debug(
                        "Interval %s has peak estimated actual %.3f and %d matching intervals: %s",
                        interval_time,
                        self.api.peak_intervals[interval],
                        len(matching),
                        ", ".join([date.astimezone(self.api.tz).strftime(DT_DATE_MONTH_DAY) for date in matching]),
                    )
                match dampening_model:
                    case 1 | 2 | 3:
                        if len(matching) >= self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_INTERVALS]:
                            actual_samples: list[float] = [
                                actuals.get(timestamp, 0.0) for timestamp in matching if generation.get(timestamp, 0.0) != 0.0
                            ]
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
                                    for act, gen in zip(actual_samples, generation_samples, strict=True):
                                        raw_factors.append(min(gen / act, 1.0) if act > 0 else 1.0)
                                    if verbose_log:
                                        _LOGGER.debug(
                                            "Candidate factors for %s: %s",
                                            interval_time,
                                            ", ".join(f"{fact:.3f}" for fact in raw_factors),
                                        )
                                    match dampening_model:
                                        case 1:  # max factor from matched pairs
                                            factor = max(raw_factors)
                                        case 2:  # average factor from matched pairs
                                            factor = sum(raw_factors) / len(raw_factors)
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
                        peak = max(generation_samples) if len(generation_samples) > 0 else 0.0
                        if verbose_log:
                            _LOGGER.debug("Interval %s max generation: %.3f, %s", interval_time, peak, generation_samples)
                        if len(matching) >= self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_INTERVALS]:
                            if peak < self.api.peak_intervals[interval]:
                                if (
                                    len(generation_samples)
                                    >= self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_GENERATION]
                                ):
                                    factor = (peak / self.api.peak_intervals[interval]) if self.api.peak_intervals[interval] != 0 else 1.0
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

    def _get_earliest_estimate_after(self, data: list[dict[str, Any]], after: dt, dampened: bool = False) -> dt | None:
        """Get the earliest estimated actual datetime after a specified datetime."""
        earliest = None
        if len(data) > 0:
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

        _LOGGER.debug("Determining peak estimated actual intervals%s", " and dampening data" if not only_peaks else "")
        if (
            self.api.options.auto_dampen or self.api.advanced_options[ADVANCED_GRANULAR_DAMPENING_DELTA_ADJUSTMENT]
        ) and self.api.options.get_actuals:
            for site in self.api.sites:
                if site[RESOURCE_ID] in self.api.options.exclude_sites:
                    _LOGGER.debug("Auto-dampening suppressed: Excluded site for %s", site[RESOURCE_ID])
                    continue
                start, end = self.api.query.get_list_slice(
                    self.api.data_actuals[SITE_INFO][site[RESOURCE_ID]][FORECASTS],
                    self.api.dt_helper.day_start_utc() - timedelta(days=self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS]),
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
            self.api.peak_intervals = dict.fromkeys(range(48), 0.0)
            for period_start, actual in actuals.items():
                interval = self.adjusted_interval_dt(period_start)
                if self.api.peak_intervals[interval] < actual:
                    self.api.peak_intervals[interval] = round(actual, 3)

        if only_peaks:
            return actuals, [], {}, {}

        ignored_intervals: list[int] = []  # Intervals to ignore in local time zone
        for time_string in self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_IGNORE_INTERVALS]:
            hour, minute = map(int, time_string.split(":"))
            interval = hour * 2 + minute // 30
            ignored_intervals.append(interval)

        export_limited_intervals = dict.fromkeys(range(48), False)
        if not self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_NO_LIMITING_CONSISTENCY]:
            for gen in self.data_generation[GENERATION][-1 * self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS] * 48 :]:
                if gen[EXPORT_LIMITING]:
                    export_limited_intervals[self._adjusted_interval(gen)] = True

        generation: dict[dt, float] = {}
        for gen in self.data_generation[GENERATION][-1 * self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS] * 48 :]:
            if not self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_NO_LIMITING_CONSISTENCY]:
                if not export_limited_intervals[self._adjusted_interval(gen)]:
                    generation[gen[PERIOD_START]] = gen[GENERATION]
            elif not gen[EXPORT_LIMITING]:
                generation[gen[PERIOD_START]] = gen[GENERATION]

        # Collect intervals that are close to the peak.
        matching_intervals: dict[int, list[dt]] = {i: [] for i in range(48)}
        for period_start, actual in actuals.items():
            interval = self.adjusted_interval_dt(period_start)
            if actual > self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_SIMILAR_PEAK] * self.api.peak_intervals[interval]:
                matching_intervals[interval].append(period_start)
        return actuals, ignored_intervals, generation, matching_intervals
