"""Solcast adaptive dampening model evaluation and history management."""

from __future__ import annotations

import asyncio
from collections import defaultdict
import copy
from datetime import datetime as dt, timedelta
from itertools import pairwise
import json
import logging
import math
from pathlib import Path
from statistics import median
import time
from typing import TYPE_CHECKING, Any, Final, NamedTuple

import aiofiles

from .const import (
    ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_CONFIGURATION,
    ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_EXCLUDE,
    ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_MINIMUM_HISTORY_DAYS,
    ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL,
    ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR,
    ADVANCED_AUTOMATED_DAMPENING_MODEL,
    ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS,
    ADVANCED_AUTOMATED_DAMPENING_NO_DELTA_ADJUSTMENT,
    ADVANCED_ESTIMATED_ACTUALS_LOG_MAPE_BREAKDOWN,
    ADVANCED_OPTIONS,
    ALL,
    AMENDABLE,
    DEFAULT_DAMPENING_DELTA_ADJUSTMENT_MODEL,
    DT_DATE_FORMAT,
    DT_DATE_FORMAT_UTC,
    DT_DATE_ONLY_FORMAT,
    ESTIMATE,
    EXPORT_LIMITING,
    FORECASTS,
    GENERATION,
    MAXIMUM,
    MINIMUM,
    MINIMUM_EXTENDED,
    PERIOD_START,
    RESOURCE_ID,
    SITE_INFO,
    VALUE_ADAPTIVE_DAMPENING_CONFIG_UNCHANGED,
    VALUE_ADAPTIVE_DAMPENING_NO_DELTA,
)
from .util import NoIndentEncoder, ordinal

if TYPE_CHECKING:
    from .dampen import Dampening

_LOGGER = logging.getLogger(__name__)

_MODEL_EVAL_RESULT: Final = "_ModelEvalResult"


class _ModelEvalResult(NamedTuple):
    """Result of evaluating all model/delta combinations for adaptive dampening."""

    daily_model_errors: dict[dt, dict[tuple[int, int], float]]
    daily_ranks: dict[dt, dict[tuple[int, int], int]]
    borda_scores: dict[tuple[int, int], float]
    best_model_adjusted: int
    best_model_no_delta: int
    best_delta_adjusted: int


class DampeningAdaptive:
    """Manages adaptive dampening model evaluation and history for Solcast forecasts."""

    def __init__(self, dampening: Dampening) -> None:
        """Initialise the adaptive dampening manager.

        Arguments:
            dampening: The parent Dampening instance.
        """
        self.dampening = dampening

    async def calculate_single_interval_error(
        self,
        dampened_actuals: defaultdict[dt, list[float]],
        generation_dampening: defaultdict[dt, dict[str, Any]],
        peak_interval: int,
        log_breakdown: bool = False,
    ) -> tuple[float, dict[dt, float]]:
        """Calculate error for a single common peak interval across all days.

        Compares actual generation vs dampened estimated actual for one specific interval
        (e.g., 12:00-12:30) across all available days. This prevents compensating errors
        and focuses model selection on performance at the most critical time of day.

        Only compares timestamps that actually exist in generation_dampening (i.e., not
        filtered out due to export limiting or other exclusions).

        Returns:
            Tuple of (mean_ape, daily_errors).
        """
        interval_errors: list[float] = []
        daily_errors: dict[dt, float] = {}

        # Iterate through actual generation timestamps that exist (not filtered out)
        for timestamp, gen_data in generation_dampening.items():
            # Calculate which interval this timestamp represents
            interval_idx = self.dampening.adjusted_interval_dt(timestamp)

            if interval_idx != peak_interval:
                continue
            day_start = self.dampening.api.dt_helper.day_start(timestamp)

            if day_start not in dampened_actuals:
                continue

            actual_gen = gen_data[GENERATION]
            dampened_estimate = dampened_actuals[day_start][peak_interval] * 0.5  # Convert to 30-min kWh

            if actual_gen > 0:
                interval_ape = abs(actual_gen - dampened_estimate) / actual_gen * 100.0
                interval_errors.append(interval_ape)
            else:
                interval_ape = math.inf

            daily_errors[day_start] = interval_ape

            if log_breakdown:
                _LOGGER.debug(
                    "Single interval APE for day %s, Actual %.2f kWh, Estimate %.2f kWh, Error %.2f%s",
                    day_start.astimezone(self.dampening.api.options.tz).strftime(DT_DATE_ONLY_FORMAT),
                    actual_gen,
                    dampened_estimate,
                    interval_ape,
                    "%" if interval_ape != math.inf else "",
                )

        if len(interval_errors) == 0:
            return (math.inf, daily_errors)

        return (
            sum(interval_errors) / len(interval_errors),
            daily_errors,
        )

    async def determine_best_settings(self) -> None:
        """Determine which dampening settings result in the lowest error rate.

        Finds earliest common history start date for all models with > minimum dampening history.
        Builds actuals for dates since that earliest start date, then applies dampening history
        for all model/delta combinations to those actuals & calculates error rate.  Selects settings
        with lowest error rate and serialises to solcast-advanced.json.
        """

        _LOGGER.debug("Determining best automated dampening settings")
        start_time = time.time()

        min_history_days = self.dampening.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_MINIMUM_HISTORY_DAYS]
        earliest_common = self._find_earliest_common_history(min_history_days)

        if earliest_common is None or earliest_common > self.dampening.api.dt_helper.day_start_utc() - timedelta(days=min_history_days):
            _LOGGER.info("Insufficient continuous dampening history to determine best automated dampening settings")
            return

        _LOGGER.debug(
            "Earliest date with complete dampening history is %s, delta is %d days",
            earliest_common.astimezone(self.dampening.api.tz).strftime(DT_DATE_ONLY_FORMAT),
            (self.dampening.api.dt_helper.day_start_utc() - earliest_common).days,
        )

        actuals = self._build_actuals_from_sites(earliest_common)
        generation_dampening, _ = await self.dampening.prepare_generation_data(earliest_common)

        common_peak_interval, avg_gen, avg_factor, variance = self._select_comparison_interval(
            generation_dampening,
            min_history_days,
            earliest_common,
        )
        _LOGGER.debug(
            "Selected interval %d (%02d:%02d) for adaptive comparison: %.3f kWh, factor %.3f, variance %.4f",
            common_peak_interval,
            common_peak_interval // 2,
            (common_peak_interval % 2) * 30,
            avg_gen,
            avg_factor,
            variance,
        )

        result = await self._evaluate_model_combinations(earliest_common, actuals, generation_dampening, common_peak_interval)

        self._log_model_rankings(result)
        await self._apply_best_settings(result, common_peak_interval)

        _LOGGER.debug("Task dampening determine_best_settings took %.3f seconds", time.time() - start_time)

    async def load_history(self) -> bool:
        """Load dampening history from JSON, validate, and repopulate."""

        start_time = time.time()
        _LOGGER.debug("Loading dampening history from file: %s", self.dampening.api.filename_dampening_history)

        valid = True
        loaded_count = 0

        expected_records = (
            (ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL][MAXIMUM] + 2)
            * (ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_MODEL][MAXIMUM] + 1)
            * self.dampening.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS]
        )

        # --- Initialise structure if needed ---
        if not self.dampening.auto_factors_history:
            self.dampening.auto_factors_history = {
                m: {
                    d: []
                    for d in range(
                        ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL][MINIMUM_EXTENDED],
                        ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL][MAXIMUM] + 1,
                    )
                }
                for m in range(
                    ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_MODEL][MINIMUM],
                    ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_MODEL][MAXIMUM] + 1,
                )
            }

        if Path(self.dampening.api.filename_dampening_history).is_file():
            async with aiofiles.open(self.dampening.api.filename_dampening_history) as file:
                try:
                    raw = json.loads(await file.read(), cls=_JSONDecoder)
                except json.decoder.JSONDecodeError:
                    _LOGGER.warning(
                        "Dampening history file is corrupt - could not decode JSON - adaptive dampening model configuration failed"
                    )
                    valid = False
        else:
            valid = False
            _LOGGER.warning("No dampening history file found, adaptive dampening configuration has not yet been built")
        if valid:
            # --- Parse and add history ---
            for model_str, deltas in raw.items():
                model = int(model_str)
                for delta_str, entries in deltas.items():
                    delta = int(delta_str)
                    for entry in entries:
                        await self._add_history(period_start=entry["period_start"], model=model, delta=delta, factors=entry["factors"])
                        loaded_count += 1

            msg = f"Load dampening history loaded {loaded_count} of a maximum of {expected_records} records"

            if loaded_count != expected_records:
                # Distinguish between gaps in history (benign, caused by missed actuals
                # fetches) and genuinely insufficient contiguous history (sub-optimal).
                model_days = self.dampening.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS]
                records_per_day = expected_records // model_days
                first_model = ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_MODEL][MINIMUM]
                first_delta = ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL][MINIMUM_EXTENDED]
                dates = sorted(e["period_start"] for e in self.dampening.auto_factors_history[first_model][first_delta])
                contiguous_days = len(dates)
                for i in range(len(dates) - 1, 0, -1):
                    if (dates[i] - dates[i - 1]).days != 1:
                        contiguous_days = len(dates) - i
                        break
                if contiguous_days * records_per_day >= expected_records:
                    _LOGGER.debug(
                        "%s: Gaps in older adaptive model history records tolerated as sometimes expected due to missing actuals fetches",
                        msg,
                    )
                else:
                    _LOGGER.warning(
                        "%s: Automated dampening adaptive model configuration may be sub-optimal until maximum history of %d days is built",
                        msg,
                        model_days,
                    )
            else:
                _LOGGER.debug(msg)

        _LOGGER.debug("Task dampening load_history took %.3f seconds", time.time() - start_time)

        return valid

    async def update_history(self) -> None:
        """Generate history of dampening factors for all models."""

        if (
            self.dampening.api.options.auto_dampen
            and self.dampening.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_CONFIGURATION]
        ):
            start_time = time.time()
            _LOGGER.debug("Updating automated dampening adaptation history")

            if await self.dampening.check_deal_breaker_automated():
                return

            actuals, ignored_intervals, generation, matching_intervals = await self.dampening.prepare_data()

            # Build undampened pv50 estimates for the previous day

            undampened_interval_pv50: dict[dt, float] = {}
            for site in self.dampening.api.sites:
                if site[RESOURCE_ID] in self.dampening.api.options.exclude_sites:
                    continue
                for forecast in self.dampening.api.data_undampened[SITE_INFO][site[RESOURCE_ID]][FORECASTS]:
                    period_start = forecast[PERIOD_START]
                    if (
                        period_start >= self.dampening.api.dt_helper.day_start_utc(future=-1)
                        and period_start < self.dampening.api.dt_helper.day_start_utc()
                    ):
                        if period_start not in undampened_interval_pv50:
                            undampened_interval_pv50[period_start] = forecast[ESTIMATE] * 0.5
                        else:
                            undampened_interval_pv50[period_start] += forecast[ESTIMATE] * 0.5

            for dampening_model in range(
                ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_MODEL][MINIMUM],
                ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_MODEL][MAXIMUM] + 1,
            ):
                dampening = await self.dampening.calculate(
                    matching_intervals, generation, actuals, ignored_intervals, dampening_model, False
                )

                await self._add_history(  # Add entry for no delta adjustment
                    period_start=self.dampening.api.dt_helper.day_start_utc(future=-1),
                    model=dampening_model,
                    delta=VALUE_ADAPTIVE_DAMPENING_NO_DELTA,
                    factors=dampening,
                )

                _LOGGER.debug(
                    "Dampening factors on %s for model %d and delta adjustment %d: %s",
                    self.dampening.api.dt_helper.day_start_utc(future=-1).strftime(DT_DATE_FORMAT_UTC),
                    dampening_model,
                    VALUE_ADAPTIVE_DAMPENING_NO_DELTA,
                    ",".join(f"{factor:.3f}" for factor in dampening),
                )

                for delta_adjustment in range(
                    ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL][MINIMUM],
                    ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL][MAXIMUM] + 1,
                ):
                    adjusted_dampening = copy.deepcopy(dampening)
                    for period_start, period_value in undampened_interval_pv50.items():
                        interval = self.dampening.adjusted_interval_dt(period_start)
                        if (
                            self.dampening.api.peak_intervals[interval] > 0
                            and period_value > 0
                            and dampening[interval] < 1.0
                            and period_start in actuals
                        ):
                            adjusted_dampening[interval] = self.dampening.apply_adjustment(
                                actuals[period_start], dampening[interval], interval, delta_adjustment
                            )  # Adjust based on actual vs peak rather than forecast vs peak
                            adjusted_dampening[interval] = (
                                1.0
                                if (
                                    self.dampening.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR]
                                    <= adjusted_dampening[interval]
                                    < 1.0
                                )
                                else adjusted_dampening[interval]
                            )

                    await self._add_history(
                        period_start=self.dampening.api.dt_helper.day_start_utc(future=-1),  # Adding history for the previous day
                        model=dampening_model,
                        delta=delta_adjustment,
                        factors=adjusted_dampening,
                    )
                    _LOGGER.debug(
                        "Dampening factors on %s for model %d and delta adjustment %d: %s",
                        self.dampening.api.dt_helper.day_start_utc(future=-1).strftime(DT_DATE_FORMAT_UTC),
                        dampening_model,
                        delta_adjustment,
                        ",".join(f"{factor:.3f}" for factor in adjusted_dampening),
                    )

            # Trim, sort and serialise.

            cutoff = self.dampening.api.dt_helper.day_start_utc(
                future=-self.dampening.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS]
            )

            serialisable = {}

            for model, deltas in self.dampening.auto_factors_history.items():
                serialisable[model] = {}

                for delta, entries in deltas.items():
                    # Filter entries newer than cutoff
                    recent_entries = [entry for entry in entries if entry["period_start"] >= cutoff]

                    # Sort by period_start
                    recent_entries.sort(key=lambda e: e["period_start"])

                    # Update in-memory structure
                    self.dampening.auto_factors_history[model][delta] = recent_entries

                    # Build serialisable version
                    serialisable[model][delta] = [
                        {"period_start": entry["period_start"], "factors": entry["factors"]} for entry in recent_entries
                    ]

            payload = json.dumps(serialisable, ensure_ascii=False, indent=2, cls=NoIndentEncoder, above_level=4)
            async with self.dampening.api.serialise_lock, aiofiles.open(self.dampening.api.filename_dampening_history, "w") as file:
                await file.write(payload)

            _LOGGER.debug("Task dampening update_history took %.3f seconds", time.time() - start_time)

    async def _add_history(self, period_start: dt, model: int, delta: int, factors: list[float]) -> None:
        """Adds a dampening history record to auto_factors_history."""

        # Update or add the entry
        entries = self.dampening.auto_factors_history[model][delta]
        new_entry = {"period_start": period_start, "factors": factors}

        # Try to update existing entry
        for i, entry in enumerate(entries):
            if entry["period_start"] == period_start:
                entries[i] = new_entry
                return

        # Add new entry if not found
        entries.append(new_entry)

    async def _apply_best_settings(
        self,
        result: _ModelEvalResult,
        common_peak_interval: int,
    ) -> None:
        """Log and conditionally serialise the best adaptive dampening configuration."""
        use_delta_mode = not self.dampening.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_NO_DELTA_ADJUSTMENT]

        if use_delta_mode:
            selected_model = result.best_model_adjusted
            selected_delta: int | None = result.best_delta_adjusted
            current_valid = {selected_model, selected_delta} != {VALUE_ADAPTIVE_DAMPENING_CONFIG_UNCHANGED}
            is_different = {selected_model, selected_delta} != {
                self.dampening.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL],
                self.dampening.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL],
            }
            alternative_model = result.best_model_no_delta
        else:
            selected_model = result.best_model_no_delta
            selected_delta = None
            current_valid = selected_model != VALUE_ADAPTIVE_DAMPENING_CONFIG_UNCHANGED
            is_different = selected_model != self.dampening.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL]
            alternative_model = result.best_model_adjusted

        if not current_valid:
            _LOGGER.info("Could not determine best automated dampening settings - values unmodified")
            return

        if use_delta_mode:
            selected_md = (result.best_model_adjusted, result.best_delta_adjusted)
            alternate_md = (result.best_model_no_delta, VALUE_ADAPTIVE_DAMPENING_NO_DELTA)
        else:
            selected_md = (result.best_model_no_delta, VALUE_ADAPTIVE_DAMPENING_NO_DELTA)
            alternate_md = (result.best_model_adjusted, result.best_delta_adjusted)
        selected_error = result.borda_scores[selected_md]
        alternative_error = result.borda_scores[alternate_md]

        _LOGGER.log(
            logging.DEBUG if _LOGGER.isEnabledFor(logging.DEBUG) else logging.INFO,
            "Best automated dampening settings: model %d%s%s",
            selected_model,
            f" and delta {selected_delta}" if use_delta_mode else "",
            f" with Borda score of {selected_error:.3f} (interval {common_peak_interval}: {common_peak_interval // 2:02d}:{(common_peak_interval % 2) * 30:02d})"
            if _LOGGER.isEnabledFor(logging.DEBUG)
            else "",
        )
        if is_different:
            _LOGGER.info("Updating automated dampening settings")
            self.dampening.api.advanced_options.update(
                {
                    ADVANCED_AUTOMATED_DAMPENING_MODEL: selected_model,
                    ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL: selected_delta
                    if use_delta_mode
                    else DEFAULT_DAMPENING_DELTA_ADJUSTMENT_MODEL,
                }
            )
            await self._serialise_advanced_options()
        else:
            _LOGGER.debug("Adaptive dampening configuration unchanged")

        if alternative_model != VALUE_ADAPTIVE_DAMPENING_CONFIG_UNCHANGED and alternative_error < selected_error:
            _LOGGER.debug(
                "%s is set %s but adaptive dampening found that model %d%s had a lower Borda score of %.3f vs the selected %.3f",
                ADVANCED_AUTOMATED_DAMPENING_NO_DELTA_ADJUSTMENT,
                "false" if use_delta_mode else "true",
                alternative_model,
                " with no delta adjustment" if use_delta_mode else f" and delta {result.best_delta_adjusted}",
                alternative_error,
                selected_error,
            )

    def _build_actuals_from_sites(self, earliest_common: dt) -> defaultdict[dt, list[float]]:
        """Build actuals dictionary from site data.

        Args:
            earliest_common: Start date for collecting actuals data.

        Returns:
            Dictionary mapping day_start to 48 interval values.
        """
        _LOGGER.debug(
            "Getting undampened actuals from %s to %s",
            earliest_common.strftime(DT_DATE_FORMAT_UTC),
            self.dampening.api.dt_helper.day_start_utc().strftime(DT_DATE_FORMAT_UTC),
        )
        actuals: defaultdict[dt, list[float]] = defaultdict(lambda: [0.0] * 48)
        for site in self.dampening.api.sites:
            if site[RESOURCE_ID] in self.dampening.api.options.exclude_sites:
                _LOGGER.debug("Dampening history actuals suppressed site %s", site[RESOURCE_ID])
                continue

            start, end = self.dampening.api.query.get_list_slice(
                self.dampening.api.data_actuals[SITE_INFO][site[RESOURCE_ID]][FORECASTS],
                earliest_common,
                self.dampening.api.dt_helper.day_start_utc() - timedelta(minutes=30),
                search_past=True,
            )
            for actual in self.dampening.api.data_actuals[SITE_INFO][site[RESOURCE_ID]][FORECASTS][start:end]:
                ts: dt = actual[PERIOD_START].astimezone(self.dampening.api.tz)
                day_start = self.dampening.api.dt_helper.day_start(ts)

                if day_start not in actuals:
                    _LOGGER.debug("Adding actuals entry for %s", day_start.strftime(DT_DATE_ONLY_FORMAT))

                actuals[day_start][self.dampening.adjusted_interval_dt(ts)] += actual[ESTIMATE]

        return actuals

    def _build_dampened_actuals_for_model(
        self,
        model: int,
        delta: int,
        earliest_common: dt,
        actuals: defaultdict[dt, list[float]],
    ) -> defaultdict[dt, list[float]] | None:
        """Build dampened actuals for a single model/delta combination.

        Applies the model's historical dampening factors to undampened actuals from the
        common start date forward.  Days where actuals are missing (e.g., estimated actuals
        were unavailable that midnight) are skipped.
        Returns None if no dampened days could be produced at all.
        """
        model_entries = self.dampening.auto_factors_history[model][delta]
        dampened_actuals: defaultdict[dt, list[float]] = defaultdict(lambda: [0.0] * 48)

        for model_entry in model_entries:
            period_start = model_entry["period_start"]
            if period_start < earliest_common:
                continue
            day_start = self.dampening.api.dt_helper.day_start(period_start)
            if day_start not in actuals:
                _LOGGER.debug(
                    "Model %d and delta %d skipping missing actuals for dampening history entry %s",
                    model,
                    delta,
                    day_start.strftime(DT_DATE_FORMAT),
                )
                continue
            factors = model_entry["factors"]
            dampened_actuals[day_start] = [actuals[day_start][i] * factors[i] for i in range(48)]

        if not dampened_actuals:
            _LOGGER.debug("Model %d and delta %d produced no dampened actuals", model, delta)
            return None

        return dampened_actuals

    async def _evaluate_model_combinations(
        self,
        earliest_common: dt,
        actuals: defaultdict[dt, list[float]],
        generation_dampening: defaultdict[dt, dict[str, Any]],
        common_peak_interval: int,
    ) -> _ModelEvalResult:
        """Evaluate all model/delta combinations and return the best-performing settings.

        For each model/delta combination applies its historical dampening factors to the
        undampened actuals, then computes single-interval error at the selected comparison
        interval. Returns per-day error rankings and the best model/delta for each mode.
        """
        daily_model_errors: dict[dt, dict[tuple[int, int], float]] = defaultdict(dict)
        best_model_adjusted = VALUE_ADAPTIVE_DAMPENING_CONFIG_UNCHANGED
        best_model_no_delta = VALUE_ADAPTIVE_DAMPENING_CONFIG_UNCHANGED
        best_delta_adjusted = VALUE_ADAPTIVE_DAMPENING_CONFIG_UNCHANGED

        for model in range(
            ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_MODEL][MINIMUM],
            ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_MODEL][MAXIMUM] + 1,
        ):
            for delta in range(
                ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL][MINIMUM_EXTENDED],
                ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL][MAXIMUM] + 1,
            ):
                should_skip, reason = self._should_skip_model_delta(
                    model, delta, self.dampening.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_MINIMUM_HISTORY_DAYS]
                )
                if should_skip:
                    _LOGGER.debug("Skipping model %d and delta %d as %s", model, delta, reason)
                    continue

                await asyncio.sleep(0)  # Be nice to HA
                _LOGGER.debug("Evaluating model %d and delta %d", model, delta)

                dampened_actuals = self._build_dampened_actuals_for_model(model, delta, earliest_common, actuals)
                if dampened_actuals is None:
                    _LOGGER.debug("Skipping evaluation for model %d and delta %d", model, delta)
                    continue

                error_single_interval, daily_errors = await self.calculate_single_interval_error(
                    dampened_actuals,
                    generation_dampening,
                    common_peak_interval,
                    log_breakdown=self.dampening.api.advanced_options[ADVANCED_ESTIMATED_ACTUALS_LOG_MAPE_BREAKDOWN],
                )

                for day, error in daily_errors.items():
                    daily_model_errors[day][(model, delta)] = error

                if error_single_interval == math.inf:
                    _LOGGER.debug("Skipping evaluation for model %d and delta %d due to error calculation issue", model, delta)
                    continue

        daily_ranks = self._get_daily_ranks(daily_model_errors)

        # Compute Borda scores (mean rank position, lower = better).
        rank_sums: defaultdict[tuple[int, int], float] = defaultdict(float)
        rank_counts: defaultdict[tuple[int, int], int] = defaultdict(int)

        for ranks in daily_ranks.values():
            for md, rank in ranks.items():
                rank_sums[md] += rank
                rank_counts[md] += 1

        borda_scores = {md: rank_sums[md] / rank_counts[md] for md in rank_sums}

        # Select Borda winners.
        no_delta_candidates = {md: s for md, s in borda_scores.items() if md[1] == VALUE_ADAPTIVE_DAMPENING_NO_DELTA}
        adjusted_candidates = {md: s for md, s in borda_scores.items() if md[1] != VALUE_ADAPTIVE_DAMPENING_NO_DELTA}

        if no_delta_candidates:
            best_nd = min(no_delta_candidates, key=lambda md: (no_delta_candidates[md], md[0]))
            best_model_no_delta = best_nd[0]

        if adjusted_candidates:
            best_adj = min(
                adjusted_candidates,
                key=lambda md: (adjusted_candidates[md], md[0], md[1] if md[1] >= 0 else float("inf")),
            )
            best_model_adjusted = best_adj[0]
            best_delta_adjusted = best_adj[1]

        return _ModelEvalResult(
            daily_model_errors=daily_model_errors,
            daily_ranks=daily_ranks,
            borda_scores=borda_scores,
            best_model_adjusted=best_model_adjusted,
            best_model_no_delta=best_model_no_delta,
            best_delta_adjusted=best_delta_adjusted,
        )

    def _find_earliest_common_history(self, min_days: int) -> dt | None:
        """Find earliest date where continuous dampening history is available for all models and deltas.

        When all model/delta combinations share the same history dates (i.e., no new strategy was
        added mid-way through), symmetric gaps caused by missed actuals are tolerated: the date
        set is the intersection of all period lists and gaps are skipped rather than treated as
        a continuity break (provided enough usable days still remain).

        Returns:
            Earliest common date with sufficient usable history, or None if insufficient history exists.
        """
        period_lists = []
        for model in range(
            ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_MODEL][MINIMUM],
            ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_MODEL][MAXIMUM] + 1,
        ):
            for delta in range(
                ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL][MINIMUM_EXTENDED],
                ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL][MAXIMUM] + 1,
            ):
                if self._should_skip_model_delta(model, delta, min_days)[0]:
                    continue

                period_lists.append(sorted(entry["period_start"] for entry in self.dampening.auto_factors_history[model][delta]))

        if len(period_lists) == 0:
            return None

        # Dates present in every model/delta combination.
        common_periods = sorted(set.intersection(*(set(pl) for pl in period_lists)))
        if not common_periods:
            return None

        # Determine whether all lists are uniform (same dates, no new strategy was introduced).
        all_equal = all(pl == period_lists[0] for pl in period_lists)

        if not all_equal:
            # Non-uniform: search for the earliest common date from which all lists are strictly continuous.
            for candidate in common_periods:
                if all(
                    all(curr == prev + timedelta(days=1) for prev, curr in pairwise(sorted(p for p in periods if p >= candidate)))
                    for periods in period_lists
                ):
                    _LOGGER.debug(
                        "Earliest common dampening history (non-uniform) is %s",
                        candidate.strftime(DT_DATE_FORMAT_UTC),
                    )
                    return candidate
            return None

        earliest_common = common_periods[0]
        _LOGGER.debug(
            "Earliest common dampening history is %s with %d usable days (gaps tolerated)",
            earliest_common.strftime(DT_DATE_FORMAT_UTC),
            len(common_periods),
        )
        return earliest_common

    def _get_daily_ranks(self, daily_model_errors: dict[dt, dict[tuple[int, int], float]]) -> dict[dt, dict[tuple[int, int], int]]:
        """Helper to calculate error rankings for each day."""
        daily_ranks = {}
        for day, errors in daily_model_errors.items():
            sorted_items = sorted(errors.items(), key=lambda x: x[1])  # sort only on errors
            day_rank_map = {}
            current_rank = 1
            for i, (md, error) in enumerate(sorted_items):
                if i > 0 and error > sorted_items[i - 1][1]:
                    current_rank = i + 1  # new rank is current index+1
                day_rank_map[md] = current_rank
            daily_ranks[day] = day_rank_map
        return daily_ranks

    def _log_model_rankings(self, result: _ModelEvalResult) -> None:
        """Log a per-day rank distribution table for all evaluated model/delta combinations."""
        model_rank_frequencies: defaultdict[tuple[int, int], defaultdict[int, int]] = defaultdict(lambda: defaultdict(int))
        model_chronological_logs: defaultdict[tuple[int, int], list[str]] = defaultdict(list)
        max_rank_observed = 0

        daily_model_errors = result.daily_model_errors
        daily_ranks = result.daily_ranks
        borda_scores = result.borda_scores

        for day, ranks in daily_ranks.items():
            for md, rank in ranks.items():
                model_rank_frequencies[md][rank] += 1
                max_rank_observed = max(max_rank_observed, rank)
                err = daily_model_errors[day][md]
                model_chronological_logs[md].append(f"{err:.2f}% ({ordinal(rank)})")

        if not model_rank_frequencies:
            _LOGGER.debug("No ranking data available (insufficient history or all-infinity errors)")
            return

        # Use existing borda_scores for sorting
        sorted_by_borda = sorted(
            borda_scores.keys(),
            key=lambda md: (borda_scores[md], md[0], md[1] if md[1] >= 0 else float("inf")),
        )

        model_rank_profiles = {md: [freqs[r] for r in range(1, max_rank_observed + 1)] for md, freqs in model_rank_frequencies.items()}

        _LOGGER.debug("Ranking:")
        for i, md in enumerate(sorted_by_borda, 1):
            _LOGGER.debug(
                "  #%d: Model %d Delta %d : Borda %.3f : Distribution: [%s]",
                i,
                md[0],
                md[1],
                borda_scores[md],
                ", ".join([f"{ordinal(r)}:{count}" for r, count in enumerate(model_rank_profiles[md], 1)]),
            )
            _LOGGER.debug("      History: [%s]", ", ".join(model_chronological_logs[md]))

        no_delta_winner = next((md for md in sorted_by_borda if md[1] == VALUE_ADAPTIVE_DAMPENING_NO_DELTA), None)
        adjusted_winner = next((md for md in sorted_by_borda if md[1] != VALUE_ADAPTIVE_DAMPENING_NO_DELTA), None)
        if no_delta_winner:
            _LOGGER.debug("Ranking winner (no delta): Model %d (Borda %.3f)", no_delta_winner[0], borda_scores[no_delta_winner])
        if adjusted_winner:
            _LOGGER.debug(
                "Ranking winner (adjusted): Model %d Delta %d (Borda %.3f)",
                adjusted_winner[0],
                adjusted_winner[1],
                borda_scores[adjusted_winner],
            )

    def _build_interval_error_weights(
        self,
        generation_dampening: defaultdict[dt, dict[str, Any]],
        min_history_days: int,
        earliest_common: dt | None = None,
    ) -> list[float]:
        """Build interval weights from persistent current dampened forecast error.

        Uses the current active dampening factors applied to historical estimated actuals
        and compares those dampened estimates against recorder generation. Intervals with
        repeatedly large errors receive higher weights, but only when enough valid days
        contribute to make the errors credible.
        """
        if not generation_dampening:
            return [0.0] * 48

        current_all_factors: list[float] = self.dampening.factors.get(ALL, [])
        if not current_all_factors:
            return [0.0] * 48

        actuals = self._build_actuals_from_sites(earliest_common or min(generation_dampening))
        interval_error_samples: list[list[float]] = [[] for _ in range(48)]

        for timestamp, gen_data in generation_dampening.items():
            if gen_data.get(EXPORT_LIMITING, False):
                continue

            actual_generation = gen_data[GENERATION]
            if actual_generation <= 0:
                continue

            interval = self.dampening.adjusted_interval_dt(timestamp)
            factor_index = interval if len(current_all_factors) == 48 else interval // 2
            if factor_index >= len(current_all_factors):
                continue

            day_start = self.dampening.api.dt_helper.day_start(timestamp)
            if day_start not in actuals:
                continue

            dampened_estimate = actuals[day_start][interval] * current_all_factors[factor_index] * 0.5
            interval_error_samples[interval].append(abs(actual_generation - dampened_estimate) / actual_generation)

        error_weights = [0.0] * 48
        for interval, samples in enumerate(interval_error_samples):
            if not samples:
                continue

            confidence = min(1.0, len(samples) / max(min_history_days, 1))
            error_weights[interval] = min(median(samples), 2.0) * confidence

        return error_weights

    def _apply_interval_error_bias(self, scores: list[float], error_weights: list[float]) -> list[float]:
        """Bias interval scores toward persistent error when there is usable residual data."""
        if not scores or not error_weights or max(scores) == 0.0 or max(error_weights) == 0.0:
            return scores

        biased_scores = [score * error_weights[index] for index, score in enumerate(scores)]
        return biased_scores if max(biased_scores) > 0.0 else scores

    def _select_comparison_interval(
        self,
        generation_dampening: defaultdict[dt, dict[str, Any]],
        min_history_days: int,
        earliest_common: dt | None = None,
    ) -> tuple[int, float, float, float]:
        """Select the best interval for single-interval adaptive comparison.

        Identifies the interval with highest dampening impact by balancing:
        - Substantial generation (not dawn/dusk)
        - Dampening actually being applied (factor < 1.0)
        - Model disagreement (variance in factors)
        - Breadth of dampening across model/delta configurations
        - Persistent current dampened forecast error

        Args:
            generation_dampening: Generation data for calculating interval totals.
            min_history_days: Minimum number of history days required for a model.
            earliest_common: Optional common history start for building residuals.

        Returns:
            Tuple of (interval_index, avg_generation, avg_dampen_factor, variance).
        """
        interval_totals = [0.0] * 48
        interval_counts = [0] * 48
        interval_dampen_sum = [0.0] * 48
        interval_dampen_count = [0] * 48
        interval_has_zero_generation = [False] * 48

        for ts, gen_data in generation_dampening.items():
            if not gen_data.get(EXPORT_LIMITING, False):
                interval = self.dampening.adjusted_interval_dt(ts)
                if gen_data[GENERATION] > 0:
                    interval_totals[interval] += gen_data[GENERATION]
                    interval_counts[interval] += 1
                else:
                    interval_has_zero_generation[interval] = True

        # Analyse dampening factors using only the no-delta (raw) history entries.
        # Delta-adjusted entries (delta 0, 1, 2 …) have been pushed toward 1.0 by the
        # adjustment algorithm, which artificially deflates both variance and breadth.
        # The raw no-delta factors represent what each dampening model strength genuinely
        # computed, without post-processing bias — giving cleaner discrimination.
        interval_active_factors: list[list[float]] = [[] for _ in range(48)]
        total_models = 0
        combo_dampens: list[set[int]] = [set() for _ in range(48)]

        for model_key, model_data in self.dampening.auto_factors_history.items():
            no_delta_entries = model_data.get(VALUE_ADAPTIVE_DAMPENING_NO_DELTA, [])
            if len(no_delta_entries) >= min_history_days:
                total_models += 1
                for entry in no_delta_entries:
                    for i, factor in enumerate(entry["factors"]):
                        if factor < 1.0:  # Only count where dampening is applied
                            interval_dampen_sum[i] += factor
                            interval_dampen_count[i] += 1
                            combo_dampens[i].add(model_key)
                            interval_active_factors[i].append(factor)

        # Calculate averages and normalise generation to peak interval (0-1 range)
        avg_generation = [interval_totals[i] / interval_counts[i] if interval_counts[i] > 0 else 0.0 for i in range(48)]
        max_generation = max(avg_generation) if any(g > 0 for g in avg_generation) else 1.0
        normalised_generation = [g / max_generation for g in avg_generation]
        avg_dampen_factor = [interval_dampen_sum[i] / interval_dampen_count[i] if interval_dampen_count[i] > 0 else 1.0 for i in range(48)]

        # Calculate variance of dampening factors across models for each interval,
        # using only entries where dampening was actually applied (factor < 1.0).
        dampen_variance = []
        for i in range(48):
            if len(interval_active_factors[i]) > 1:
                active = interval_active_factors[i]
                mean = sum(active) / len(active)
                variance = sum((f - mean) ** 2 for f in active) / len(active)
                dampen_variance.append(variance)
            else:
                dampen_variance.append(0.0)

        # Calculate breadth of dampening: fraction of dampening models that apply dampening
        # Intervals where more model strengths agree dampening is needed are better for comparison
        dampening_breadth = [len(combo_dampens[i]) / total_models if total_models > 0 else 0.0 for i in range(48)]
        interval_error_weights = self._build_interval_error_weights(generation_dampening, min_history_days, earliest_common)

        # Score = (1 - avg_factor) × sqrt(variance) × dampening_breadth, for intervals
        # with adequate generation only (≥ 10% of peak to exclude pre-dawn/post-dusk).
        # The goal here is dampening quality, not energy magnitude. Where possible,
        # bias this toward intervals where the current dampened forecast is also
        # persistently wrong.
        min_gen_fraction = 0.10
        dampening_impact = [
            (1.0 - avg_dampen_factor[i]) * (dampen_variance[i] ** 0.5) * dampening_breadth[i]
            if normalised_generation[i] >= min_gen_fraction and not interval_has_zero_generation[i]
            else 0.0
            for i in range(48)
        ]
        dampening_impact = self._apply_interval_error_bias(dampening_impact, interval_error_weights)

        # Fall back progressively when history-based scoring cannot discriminate.
        if not dampening_impact or max(dampening_impact) == 0.0:
            # First fallback: drop the variance term — (1 - dampening) × breadth, still generation-gated
            dampening_impact = [
                (1.0 - avg_dampen_factor[i]) * dampening_breadth[i]
                if normalised_generation[i] >= min_gen_fraction and not interval_has_zero_generation[i]
                else 0.0
                for i in range(48)
            ]
            dampening_impact = self._apply_interval_error_bias(dampening_impact, interval_error_weights)
        if max(dampening_impact) == 0.0:
            # Second fallback: use the current model factors as a proxy for where dampening
            # matters. This handles the case where the history contains only 1.0 entries
            # (fresh install, overcast streak, etc.).
            current_all_factors: list[float] = self.dampening.factors.get(ALL, [])
            if current_all_factors and any(f < 1.0 for f in current_all_factors):
                min_gen_fraction = 0.10  # Require at least 10% of peak to exclude pre-dawn/dusk
                dampening_impact = [
                    (1.0 - current_all_factors[i])
                    if normalised_generation[i] >= min_gen_fraction and not interval_has_zero_generation[i]
                    else 0.0
                    for i in range(48)
                ]
        if max(dampening_impact) == 0.0:
            # Final fallback: pure generation — ensures a daytime interval is always chosen
            dampening_impact = list(normalised_generation)
        # Select interval with highest weighted score
        selected_interval = dampening_impact.index(max(dampening_impact)) if dampening_impact else 0

        return (
            selected_interval,
            avg_generation[selected_interval],
            avg_dampen_factor[selected_interval],
            dampen_variance[selected_interval],
        )

    async def _serialise_advanced_options(self) -> None:
        """Serialise advanced options to JSON."""
        start_time = time.time()
        _LOGGER.debug("Serialising advanced options to file: %s", self.dampening.api.filename_advanced)

        data = {}

        for option, value in self.dampening.api.advanced_options.items():
            adv_cfg = ADVANCED_OPTIONS.get(option)

            if adv_cfg and adv_cfg.get(AMENDABLE, False):  # Always update amendable options from memory
                data[option] = value
                _LOGGER.debug("Advanced option '%s' set to: %s", option, data[option])
            elif option in self.dampening.api.extant_advanced_options:
                data[option] = self.dampening.api.extant_advanced_options[option]  # write back non-amendable options unchanged

        payload = json.dumps(data, ensure_ascii=False, cls=NoIndentEncoder, indent=2, above_level=2)
        self.dampening.api.suppress_advanced_watchdog_reload = True  # Turn off watchdog for this change

        async with self.dampening.api.serialise_lock, aiofiles.open(self.dampening.api.filename_advanced, "w") as file:
            await file.write(payload)

        _LOGGER.debug("Task serialise_advanced_options took %.3f seconds", time.time() - start_time)

    def _should_skip_model_delta(self, model: int, delta: int, min_days: int) -> tuple[bool, str | None]:
        """Check if a model/delta combination should be skipped.

        Returns:
            tuple of (should_skip, reason)
        """
        if self.dampening.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_EXCLUDE] and any(
            entry["model"] == model and entry["delta"] == delta
            for entry in self.dampening.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_EXCLUDE]
        ):
            return True, f"in {ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_EXCLUDE}"

        entries = self.dampening.auto_factors_history[model][delta]
        if len(entries) < min_days:
            return True, f"history of {len(entries)} days is less than minimum {min_days} days"

        return False, None


# Local import alias to avoid circular import at module level
from .util import JSONDecoder as _JSONDecoder  # noqa: E402
