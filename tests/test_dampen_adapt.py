"""Tests for Solcast Solar automated dampening adaptation."""

from collections import defaultdict
import copy
from datetime import datetime as dt, timedelta
import json
import logging
import math
from pathlib import Path
import re
from typing import Any
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar.const import (
    ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_CONFIGURATION,
    ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_EXCLUDE,
    ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_MINIMUM_HISTORY_DAYS,
    ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL,
    ADVANCED_AUTOMATED_DAMPENING_ELEVATION_ADJUSTMENT,
    ADVANCED_AUTOMATED_DAMPENING_GENERATION_FETCH_DELAY,
    ADVANCED_AUTOMATED_DAMPENING_IGNORE_INTERVALS,
    ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR,
    ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR_ADJUSTED,
    ADVANCED_AUTOMATED_DAMPENING_MODEL,
    ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS,
    ADVANCED_AUTOMATED_DAMPENING_NO_DELTA_ADJUSTMENT,
    ADVANCED_AUTOMATED_DAMPENING_NO_LIMITING_CONSISTENCY,
    ADVANCED_ESTIMATED_ACTUALS_FETCH_DELAY,
    ADVANCED_ESTIMATED_ACTUALS_LOG_MAPE_BREAKDOWN,
    ADVANCED_OPTIONS,
    ALL,
    AUTO_DAMPEN,
    AUTO_UPDATE,
    DOMAIN,
    ENTITY_ACCURACY,
    EXCLUDE_SITES,
    EXPORT_LIMITING,
    FORECASTS,
    GENERATION,
    GENERATION_ENTITIES,
    GET_ACTUALS,
    MAXIMUM,
    MINIMUM,
    MINIMUM_EXTENDED,
    PERIOD_START,
    SITE_EXPORT_ENTITY,
    SITE_EXPORT_LIMIT,
    SITE_INFO,
    USE_ACTUALS,
    VALUE_ADAPTIVE_DAMPENING_NO_DELTA,
)
from homeassistant.components.solcast_solar.dampen import Dampening
from homeassistant.components.solcast_solar.dates import DateTimeHelper, NoIndentEncoder
from homeassistant.components.solcast_solar.solcastapi import SolcastApi
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from . import (
    DEFAULT_INPUT2,
    MOCK_CORRUPT_ACTUALS,
    ZONE_RAW,
    ExtraSensors,
    adjust_dampening_test_caches,
    async_cleanup_integration_tests,
    async_init_integration,
    entity_history,
    get_config_dir,
    no_exception,
    reload_integration,
    session_clear,
    wait_for_it,
    write_advanced_options,
)

_LOGGER = logging.getLogger(__name__)


@pytest.mark.timeout(120)
async def test_adaptive_auto_dampen(  # noqa: C901
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test dampening adaptations."""

    entity_history["days_generation"] = 7
    entity_history["days_suppression"] = 7
    entity_history["offset"] = 2

    try:
        config_dir = get_config_dir(hass.config.config_dir, create=True)

        write_advanced_options(
            hass.config.config_dir,
            {
                ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_CONFIGURATION: True,
                ADVANCED_AUTOMATED_DAMPENING_ELEVATION_ADJUSTMENT: False,
                ADVANCED_AUTOMATED_DAMPENING_MODEL: 3,
                ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL: -1,
                ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_EXCLUDE: [{"model": 3, "delta": 0}],
                ADVANCED_AUTOMATED_DAMPENING_IGNORE_INTERVALS: ["17:00"],
                ADVANCED_AUTOMATED_DAMPENING_NO_LIMITING_CONSISTENCY: True,
                ADVANCED_AUTOMATED_DAMPENING_GENERATION_FETCH_DELAY: 5,
                ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR: 0.988,
                ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR_ADJUSTED: 0.989,
                ADVANCED_ESTIMATED_ACTUALS_FETCH_DELAY: 5,
                ADVANCED_ESTIMATED_ACTUALS_LOG_MAPE_BREAKDOWN: True,
            },
        )

        options = copy.deepcopy(DEFAULT_INPUT2)
        options[AUTO_UPDATE] = 0
        options[GET_ACTUALS] = True
        options[USE_ACTUALS] = 1
        options[AUTO_DAMPEN] = True
        options[EXCLUDE_SITES] = ["3333-3333-3333-3333"]
        options[GENERATION_ENTITIES] = [
            "sensor.solar_export_sensor_1111_1111_1111_1111",
            "sensor.solar_export_sensor_2222_2222_2222_2222",
        ]
        options[SITE_EXPORT_ENTITY] = "sensor.site_export_sensor"
        options[SITE_EXPORT_LIMIT] = 5.0
        er.async_get(hass).async_get_or_create("sensor", DOMAIN, ENTITY_ACCURACY)
        entry = await async_init_integration(hass, options, extra_sensors=ExtraSensors.YES)

        adjust_dampening_test_caches(config_dir)

        # Reload to load saved data and prime initial generation
        caplog.clear()
        coordinator, solcast = await reload_integration(hass, entry)
        if coordinator is None or solcast is None:
            pytest.fail("Reload failed")

        # Assert good start, that actuals and generation are enabled, and that the caches are saved
        _LOGGER.debug("Testing good start happened")
        await wait_for_it(hass, caplog, freezer, "Clear presumed dead flag", long_time=False)
        no_exception(caplog)

        assert "Auto-dampening suppressed: Excluded site for 3333-3333-3333-3333" in caplog.text
        assert "Interval 08:30 has peak estimated actual 0.936" in caplog.text
        assert "Auto-dampen factor for 08:30 is 0.296" in caplog.text

        # Roll over to tomorrow three times.
        roll_to = [
            {"days": 0, "hours": 12},
            {"days": 1, "hours": 0},
            {"days": 1, "hours": 0},
            {"days": 1, "hours": 0},
        ]
        for count, roll in enumerate(roll_to):
            _LOGGER.debug("Rolling over to tomorrow")
            caplog.clear()
            removed = -5
            solcast.data_actuals[SITE_INFO]["1111-1111-1111-1111"][FORECASTS].pop(removed)
            freezer.move_to((dt_util.now(solcast.tz) + timedelta(**roll)).replace(minute=0, second=0, microsecond=0))
            await hass.async_block_till_done()
            solcast.suppress_advanced_watchdog_reload = True
            await solcast.advanced_opt.read_advanced_options()
            await wait_for_it(hass, caplog, freezer, "Update generation data", long_time=True)
            await wait_for_it(hass, caplog, freezer, "Estimated actual mean APE", long_time=True)
            no_exception(caplog)
            assert "Updating automated dampening adaptation history" in caplog.text
            assert "Task dampening update_history took" in caplog.text
            match count:
                case 2:
                    assert "Determining best automated dampening settings" in caplog.text
                    assert "Dampening history actuals suppressed site 3333-3333-3333-3333" in caplog.text
                    assert "Skipping model 2 and delta 0 as history of 2 days" in caplog.text
                    assert "Skipping model 2 and delta 1 as history of 1 days" in caplog.text
                    assert f"Advanced option '{ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL}' set to: 1" in caplog.text
                    assert f"Advanced option '{ADVANCED_AUTOMATED_DAMPENING_MODEL}' set to: 0" in caplog.text
                    assert "Task serialise_advanced_options took" in caplog.text
                    assert re.search(r"Advanced options file .+ exists", caplog.text) is None, (
                        "Advanced options file existence log should not appear"
                    )

                    solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_EXCLUDE] = [{"model": 2, "delta": -1}]
                    await solcast.dampening.adaptive.determine_best_settings()
                    assert "Skipping model 2 and delta -1 as in automated_dampening_adaptive_model_exclude" in caplog.text
                    solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_EXCLUDE] = []

                    solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_NO_DELTA_ADJUSTMENT] = True
                    await solcast.dampening.adaptive.determine_best_settings()
                    solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_NO_DELTA_ADJUSTMENT] = False

                    # Remove the 2nd day from all model/deltas
                    now_missing_day_2 = defaultdict(dict)
                    for model in solcast.dampening.auto_factors_history:
                        for delta in solcast.dampening.auto_factors_history[model]:
                            if len(solcast.dampening.auto_factors_history[model][delta]) > 1:
                                now_missing_day_2[model][delta] = copy.deepcopy(solcast.dampening.auto_factors_history[model][delta][1])
                                solcast.dampening.auto_factors_history[model][delta].pop(1)

                case 3:
                    assert "Determining best automated dampening settings" in caplog.text
                    assert "usable days (gaps tolerated)" in caplog.text

                    # Reinstate the 2nd day from all model/deltas
                    for model in solcast.dampening.auto_factors_history:
                        for delta in solcast.dampening.auto_factors_history[model]:
                            if model in now_missing_day_2 and delta in now_missing_day_2[model]:
                                solcast.dampening.auto_factors_history[model][delta].append(now_missing_day_2[model][delta])

                    # Write history to file so it persists through reload
                    Path(f"{config_dir}/solcast-dampening-history.json").write_text(
                        json.dumps(
                            solcast.dampening.auto_factors_history, ensure_ascii=False, indent=2, cls=NoIndentEncoder, above_level=4
                        ),
                        encoding="utf-8",
                    )

                case 1:
                    assert "Insufficient continuous dampening history" in caplog.text
                    # Knobble the history for some combos
                    now_missing_2_1 = copy.deepcopy(solcast.dampening.auto_factors_history[2][1])
                    now_missing_2_0_1 = copy.deepcopy(solcast.dampening.auto_factors_history[2][0][1])
                    now_missing_3_0_1 = copy.deepcopy(solcast.dampening.auto_factors_history[3][0][1])
                    solcast.dampening.auto_factors_history[2][0] = solcast.dampening.auto_factors_history[3][0][:-1]
                    solcast.dampening.auto_factors_history[2][1] = []
                    solcast.dampening.auto_factors_history[3][0] = [solcast.dampening.auto_factors_history[3][0][0]]

                case 0:
                    assert "Insufficient continuous dampening history" in caplog.text

        # Reload to load dampening factor history
        caplog.clear()
        coordinator, solcast = await reload_integration(hass, entry)
        if coordinator is None or solcast is None:
            pytest.fail("Reload failed")
        await wait_for_it(hass, caplog, freezer, "Completed task stale_update", long_time=True)
        await wait_for_it(hass, caplog, freezer, "Task dampening load_history took")

        # Re-add dampening history for today
        caplog.clear()
        _LOGGER.debug("Re-adding dampening history for today")
        await solcast.dampening.adaptive.update_history()

        # Test valid and full history
        solcast.dampening.auto_factors_history[2][1] = solcast.dampening.auto_factors_history[2][1] + list(now_missing_2_1)
        solcast.dampening.auto_factors_history[2][0].append(now_missing_2_0_1)
        solcast.dampening.auto_factors_history[3][0].append(now_missing_3_0_1)
        Path(f"{config_dir}/solcast-dampening-history.json").write_text(
            json.dumps(solcast.dampening.auto_factors_history, ensure_ascii=False, indent=2, cls=NoIndentEncoder, above_level=4),
            encoding="utf-8",
        )
        caplog.clear()
        solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS] = 4
        await solcast.dampening.adaptive.load_history()
        assert "Automated dampening adaptive model configuration may be sub-optimal" not in caplog.text
        solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS] = 14

        # Test load_history() with an interior date gap where the contiguous tail satisfies expected_records.
        # This exercises:
        #   line 256 - contiguous_days = len(dates) - i  (gap detected in loop)
        #   line 257 - break
        #   line 259 - if contiguous_days * records_per_day >= expected_records  (True: debug "Gaps tolerated")
        #
        # Setup: remove the 2nd-oldest day from every model/delta combo so the dates stored in the
        # file are [day0, day2, day3] - a gap of two days between day0 and day2.
        # With model_days=2: expected_records=24, loaded_count=36 (3 days x 12 combos), 36!=24 triggers
        # the gap-detection block. Contiguous tail = {day2, day3}, contiguous_days=2; 2x12=24 >= 24, so debug.
        full_history = copy.deepcopy(solcast.dampening.auto_factors_history)
        gaped_history = {
            model_key: {delta_key: [e for idx, e in enumerate(entries) if idx != 1] for delta_key, entries in deltas.items()}
            for model_key, deltas in full_history.items()
        }
        Path(f"{config_dir}/solcast-dampening-history.json").write_text(
            json.dumps(gaped_history, ensure_ascii=False, indent=2, cls=NoIndentEncoder, above_level=4),
            encoding="utf-8",
        )
        caplog.clear()
        solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS] = 2
        # Clear in-memory history so load_history() starts fresh and reflects only the gaped file content
        solcast.dampening.auto_factors_history = {}
        await solcast.dampening.adaptive.load_history()
        assert "Gaps in older adaptive model history records tolerated" in caplog.text
        assert "Automated dampening adaptive model configuration may be sub-optimal" not in caplog.text
        # Restore original full history and disk file for subsequent tests
        solcast.dampening.auto_factors_history = copy.deepcopy(full_history)
        Path(f"{config_dir}/solcast-dampening-history.json").write_text(
            json.dumps(full_history, ensure_ascii=False, indent=2, cls=NoIndentEncoder, above_level=4),
            encoding="utf-8",
        )
        solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS] = 14

        # Test staggered history start dates (exercises if period_start < earliest_common)
        # Model 0 will have entries from all 4 days (days 0-3)
        # Model 1 will have entries from 3 days (days 1-3, missing day 0)
        # Model 2 will have entries from 2 days (days 2-3, missing days 0-1)
        # Model 3 will have entries from 3 days (days 1-3, missing day 0)
        # This makes earliest_common = day 2 (where all models have continuous history)
        # When processing models 0, 1, 3, entries for day 0-1 should be skipped (period_start < earliest_common)
        caplog.clear()
        _LOGGER.debug("Testing adaptive dampening with staggered history start dates")
        old_data = copy.deepcopy(solcast.dampening.auto_factors_history)
        for delta in range(-1, 2):
            if len(solcast.dampening.auto_factors_history[1][delta]) >= 4:
                solcast.dampening.auto_factors_history[1][delta].pop(0)
        for delta in range(-1, 2):
            if len(solcast.dampening.auto_factors_history[2][delta]) >= 4:
                solcast.dampening.auto_factors_history[2][delta].pop(0)
                solcast.dampening.auto_factors_history[2][delta].pop(0)
        for delta in range(-1, 2):
            if len(solcast.dampening.auto_factors_history[3][delta]) >= 4:
                solcast.dampening.auto_factors_history[3][delta].pop(0)
        await solcast.dampening.adaptive.determine_best_settings()  # Should skip early entries for models 0, 1, 3
        # Should complete successfully despite staggered dates
        assert "Determining best automated dampening settings" in caplog.text
        assert "Earliest date with complete dampening history" in caplog.text
        assert "delta is" in caplog.text and "days" in caplog.text
        assert "Skipping model" in caplog.text or "history of" in caplog.text
        solcast.dampening.auto_factors_history = old_data

        # Test scenario where all generation is zero (all APE values become infinity)
        # This exercises the defensive check: if error_metric == math.inf
        caplog.clear()
        _LOGGER.debug("Testing adaptive dampening with all zero generation (infinity APE)")
        # Store original generation data
        original_generation = copy.deepcopy(solcast.dampening.data_generation)
        # Set all generation to zero to trigger infinity APE
        for gen_entry in solcast.dampening.data_generation[GENERATION]:
            gen_entry[GENERATION] = 0.0
        await solcast.dampening.adaptive.determine_best_settings()
        # Should log the defensive check message for skipping APE calculation
        assert "Determining best automated dampening settings" in caplog.text
        assert "Skipping evaluation for model" in caplog.text
        assert "due to error calculation issue" in caplog.text
        # Restore original generation data
        solcast.dampening.data_generation = original_generation

        # Test scenario where the Borda-selected model is different from current
        # With Borda count, a different best model always triggers an update
        caplog.clear()
        _LOGGER.debug("Testing adaptive dampening with different Borda-selected model")
        original_model = solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL]
        solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL] = 1
        original_delta = solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL]
        solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL] = 1
        await solcast.dampening.adaptive.determine_best_settings()
        assert "Updating automated dampening settings" in caplog.text
        # Restore original values
        solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL] = original_model
        solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL] = original_delta

        # Test scenario where dampening history references days not in actuals
        # This exercises: if day_start not in actuals: valid = False
        # Need to trigger this without breaking the continuity check in _find_earliest_common_history so remove _data_actuals data for a specific day
        caplog.clear()
        _LOGGER.debug("Testing adaptive dampening with missing actuals for dampening history entry")
        # Get one of the days from dampening history that should have actuals
        sample_entry = solcast.dampening.auto_factors_history[0][-1][1]
        problem_day = solcast.dt_helper.day_start(sample_entry[PERIOD_START])
        saved_actuals = {}
        for site_id in solcast.data_actuals[SITE_INFO]:
            if site_id not in saved_actuals:
                saved_actuals[site_id] = []

            remaining_actuals = []
            for actual in solcast.data_actuals[SITE_INFO][site_id][FORECASTS]:
                ts = actual[PERIOD_START].astimezone(solcast.tz)
                day_start = solcast.dt_helper.day_start(ts)
                if day_start == problem_day:
                    saved_actuals[site_id].append(actual)
                else:
                    remaining_actuals.append(actual)

            solcast.data_actuals[SITE_INFO][site_id][FORECASTS] = remaining_actuals
        await solcast.dampening.adaptive.determine_best_settings()
        assert "Determining best automated dampening settings" in caplog.text
        assert "skipping missing actuals for dampening history entry" in caplog.text

        # Restore the actuals data
        for site_id, saved in saved_actuals.items():
            solcast.data_actuals[SITE_INFO][site_id][FORECASTS].extend(saved)

        # Corrupt the history and reload it
        caplog.clear()
        _LOGGER.debug("Corrupting dampening history and reloading it")
        Path(f"{config_dir}/solcast-dampening-history.json").write_text("having a bad day", encoding="utf-8")
        await solcast.dampening.adaptive.load_history()
        assert "Dampening history file is corrupt" in caplog.text

    finally:
        entity_history["days_generation"] = 3
        entity_history["days_suppression"] = 3
        entity_history["offset"] = -1
        session_clear(MOCK_CORRUPT_ACTUALS)
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_update_history_deal_breaker(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test update_history with deal breaker conditions."""

    assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"

    try:
        write_advanced_options(
            hass.config.config_dir,
            {
                ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_CONFIGURATION: True,
            },
        )

        entity_history["days_generation"] = 1
        entity_history["days_suppression"] = 0
        entity_history["offset"] = -1

        options = copy.deepcopy(DEFAULT_INPUT2)
        options[AUTO_UPDATE] = 0
        options[AUTO_DAMPEN] = True
        options[GET_ACTUALS] = True
        options[USE_ACTUALS] = True

        entry = await async_init_integration(hass, options, extra_sensors=ExtraSensors.YES)
        solcast: SolcastApi = entry.runtime_data.coordinator.solcast

        # Test scenario: No generation data (deal breaker)
        caplog.clear()
        _LOGGER.debug("Testing update_history with no generation data")
        # Clear generation data to trigger the "No generation yet" deal breaker
        solcast.dampening.data_generation[GENERATION] = []
        await solcast.dampening.adaptive.update_history()
        assert "Auto-dampening suppressed: No generation yet" in caplog.text

    finally:
        entity_history["days_generation"] = 3
        entity_history["days_suppression"] = 3
        entity_history["offset"] = -1
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


def test_select_comparison_interval_variance() -> None:
    """Test comparison interval selection with variance across models."""

    adaptive, _, _, today = _build_adaptive_under_test(ZoneInfo(ZONE_RAW))
    dampening = adaptive.dampening

    day_start = today - timedelta(days=1)
    ts = day_start
    generation_dampening = defaultdict(dict, {ts: {GENERATION: 1.0, EXPORT_LIMITING: False}})

    factors_a = [1.0] * 48
    factors_b = [1.0] * 48
    factors_a[0] = 0.8
    factors_b[0] = 0.6

    dampening.auto_factors_history = {
        0: {
            VALUE_ADAPTIVE_DAMPENING_NO_DELTA: [
                {PERIOD_START: day_start, "factors": factors_a},
                {PERIOD_START: day_start, "factors": factors_b},
            ]
        },
        1: {
            VALUE_ADAPTIVE_DAMPENING_NO_DELTA: [
                {PERIOD_START: day_start, "factors": factors_b},
                {PERIOD_START: day_start, "factors": factors_a},
            ]
        },
    }

    selected_interval, avg_gen, avg_factor, variance = adaptive._select_comparison_interval(generation_dampening, 1)

    assert selected_interval == 0
    assert avg_gen > 0
    assert avg_factor < 1.0
    assert variance > 0


def test_select_comparison_interval_single_factor() -> None:
    """Test comparison interval selection with single-factor history."""

    adaptive, _, _, today = _build_adaptive_under_test(ZoneInfo(ZONE_RAW))
    dampening = adaptive.dampening

    day_start = today - timedelta(days=1)
    generation_dampening = defaultdict(dict, {day_start: {GENERATION: 1.0, EXPORT_LIMITING: False}})

    factors = [1.0] * 48
    factors[0] = 0.9

    dampening.auto_factors_history = {0: {VALUE_ADAPTIVE_DAMPENING_NO_DELTA: [{PERIOD_START: day_start, "factors": factors}]}}

    selected_interval, avg_gen, avg_factor, variance = adaptive._select_comparison_interval(generation_dampening, 1)

    assert selected_interval == 0
    assert avg_gen > 0
    assert avg_factor < 1.0
    assert variance == 0.0


def test_select_comparison_interval_diluted_variance() -> None:
    """Test that variance is computed over active-only (factor < 1.0) entries.

    When many overcast/undampened days (factor=1.0) exist alongside a handful of
    dampened days, including those 1.0 entries in the variance calculation inflates N
    and pulls the mean toward 1.0, making genuine model disagreement look negligible.
    The fix computes variance only over active entries so the inter-model signal is
    preserved, and the returned variance should match the active-only computation.
    """

    adaptive, _, _, today = _build_adaptive_under_test(ZoneInfo(ZONE_RAW))
    dampening = adaptive.dampening

    day_start = today - timedelta(days=1)
    generation_dampening = defaultdict(dict, {day_start: {GENERATION: 1.0, EXPORT_LIMITING: False}})

    # Build 10-entry histories where interval 0 has 8 undampened days (1.0) and
    # one dampened day per model with strongly differing values (0.9 vs 0.5).
    # Including the eight 1.0s in the variance formula would dilute the signal;
    # active-only variance over [0.9, 0.5] should be 0.04.
    factors_a = [1.0] * 48
    factors_b = [1.0] * 48
    factors_a[0] = 0.9
    factors_b[0] = 0.5

    undampened_entry = {PERIOD_START: day_start, "factors": [1.0] * 48}
    history_a = [undampened_entry] * 8 + [{PERIOD_START: day_start, "factors": factors_a}]
    history_b = [undampened_entry] * 8 + [{PERIOD_START: day_start, "factors": factors_b}]

    dampening.auto_factors_history = {
        0: {VALUE_ADAPTIVE_DAMPENING_NO_DELTA: history_a},
        1: {VALUE_ADAPTIVE_DAMPENING_NO_DELTA: history_b},
    }

    selected_interval, _, avg_factor, variance = adaptive._select_comparison_interval(generation_dampening, 1)

    # Interval 0 should still be selected — it is the only interval with dampening
    assert selected_interval == 0
    assert avg_factor < 1.0
    # Variance must equal the active-only value: variance([0.9, 0.5]) == 0.04
    assert abs(variance - 0.04) < 1e-9


def test_build_interval_error_weights_hourly_factor_mapping() -> None:
    """Test interval error weighting with hourly factor arrays."""

    adaptive, _, _, today = _build_adaptive_under_test(ZoneInfo(ZONE_RAW))
    dampening = adaptive.dampening

    day_start = today - timedelta(days=1)
    interval = 20
    timestamp = day_start + timedelta(minutes=interval * 30)
    generation_dampening = defaultdict(dict, {timestamp: {GENERATION: 0.25, EXPORT_LIMITING: False}})

    actuals = defaultdict(lambda: [0.0] * 48)
    actuals[dampening.api.dt_helper.day_start(timestamp)][interval] = 4.0

    assert adaptive._build_interval_error_weights(defaultdict(dict), 1) == [0.0] * 48

    current_factors = [1.0] * 24
    current_factors[interval // 2] = 0.5
    dampening.factors = {ALL: current_factors}

    weights = adaptive._build_interval_error_weights(generation_dampening, 1, actuals)

    assert weights[interval] == 2.0, f"Error weight at interval {interval} should be 2.0, got {weights[interval]}"
    assert max(weights[:interval] + weights[interval + 1 :]) == 0.0, "Non-target intervals should have zero weight"
    assert adaptive._apply_interval_error_bias([0.0] * 48, weights) == [0.0] * 48, "Bias applied to zeros should remain zeros"

    dampening.factors = {ALL: [1.0] * 10}
    assert adaptive._build_interval_error_weights(generation_dampening, 1, actuals) == [0.0] * 48


def test_select_comparison_interval_prefers_persistent_error() -> None:
    """Test comparison interval selection favours persistently bad current intervals."""

    adaptive, _, _, today = _build_adaptive_under_test(ZoneInfo(ZONE_RAW))
    dampening = adaptive.dampening

    day_start = today - timedelta(days=1)
    ts_10 = day_start + timedelta(minutes=10 * 30)
    ts_20 = day_start + timedelta(minutes=20 * 30)
    generation_dampening = defaultdict(
        dict,
        {
            ts_10: {GENERATION: 1.0, EXPORT_LIMITING: False},
            ts_20: {GENERATION: 0.25, EXPORT_LIMITING: False},
        },
    )

    factors_a = [1.0] * 48
    factors_b = [1.0] * 48
    factors_a[10] = 0.8
    factors_b[10] = 0.6
    factors_a[20] = 0.8
    factors_b[20] = 0.6
    dampening.auto_factors_history = {
        0: {VALUE_ADAPTIVE_DAMPENING_NO_DELTA: [{PERIOD_START: day_start, "factors": factors_a}]},
        1: {VALUE_ADAPTIVE_DAMPENING_NO_DELTA: [{PERIOD_START: day_start, "factors": factors_b}]},
    }

    actuals = defaultdict(lambda: [0.0] * 48)
    actuals[dampening.api.dt_helper.day_start(day_start)][10] = 4.0
    actuals[dampening.api.dt_helper.day_start(day_start)][20] = 4.0

    current_factors = [1.0] * 48
    current_factors[10] = 0.5
    current_factors[20] = 0.5
    dampening.factors = {ALL: current_factors}

    selected_interval, avg_gen, avg_factor, variance = adaptive._select_comparison_interval(
        generation_dampening,
        1,
        actuals,
    )

    assert selected_interval == 20, f"Expected interval 20 (persistent error), got {selected_interval}"
    assert avg_gen > 0, f"Expected avg_gen > 0, got {avg_gen}"
    assert avg_factor < 1.0, f"Expected avg_factor < 1.0, got {avg_factor}"
    assert variance > 0.0, f"Expected variance > 0.0, got {variance}"


def test_select_comparison_interval_current_factors_fallback() -> None:
    """Test that the current-factors fallback selects by max dampening, not by generation.

    When all history entries have factor=1.0 (e.g. a fresh install or a long
    overcast streak), both the primary formula and the breadth-based fallback
    score every interval as zero. The current-factors fallback must then select
    by the heaviest dampening in factors[ALL], filtered to intervals with at least
    10% of peak generation.

    Critically, this must NOT be weighted by generation. A generation-weighted
    formula (normalised_gen x (1 - factor)) biases toward the peak-energy interval
    even when it has weak dampening, producing a poor comparison discriminator.
    The correct choice is the interval where the model applies the most aggressive
    dampening among those with adequate daylight generation.
    """

    adaptive, _, _, today = _build_adaptive_under_test(ZoneInfo(ZONE_RAW))
    dampening = adaptive.dampening

    day_start = today - timedelta(days=1)

    # Interval 15 has modest generation (2 kWh) but heavy dampening (factor 0.55).
    # Interval 21 has much more generation (8 kWh) but weaker dampening (factor 0.80).
    ts_15 = day_start + timedelta(minutes=15 * 30)
    ts_21 = day_start + timedelta(minutes=21 * 30)
    generation_dampening = defaultdict(
        dict,
        {
            ts_15: {GENERATION: 2.0, EXPORT_LIMITING: False},
            ts_21: {GENERATION: 8.0, EXPORT_LIMITING: False},
        },
    )

    # History is entirely undampened — all factors 1.0 — so history-based scoring
    # produces zero for every interval.
    dampening.auto_factors_history = {
        0: {VALUE_ADAPTIVE_DAMPENING_NO_DELTA: [{PERIOD_START: day_start, "factors": [1.0] * 48}]},
    }

    # The running model applies heavy dampening at interval 15 (factor 0.55)
    # and moderate dampening at interval 21 (factor 0.80).
    current_factors = [1.0] * 48
    current_factors[15] = 0.55  # 45% dampening — heavier discriminator
    current_factors[21] = 0.80  # 20% dampening — weaker discriminator
    dampening.factors = {ALL: current_factors}

    selected_interval, _avg_gen, avg_factor, _variance = adaptive._select_comparison_interval(generation_dampening, 1)

    # Interval 15 must win: (1 - 0.55) = 0.45 > (1 - 0.80) = 0.20.
    # A generation-weighted formula would pick interval 21:
    #   21: (8/8 = 1.0) x 0.20 = 0.20 beats 15: (2/8 = 0.25) x 0.45 = 0.11
    # The correct approach ignores generation magnitude and selects maximum
    # dampening among intervals with adequate daylight production.
    assert selected_interval == 15, f"Expected interval 15 (heaviest dampening), got {selected_interval}"
    assert avg_factor == 1.0, (
        f"Expected avg_factor 1.0 (no active history), got {avg_factor}"
    )  # history-based avg_factor — no active history entries


def _build_adaptive_under_test(tz: ZoneInfo) -> tuple[Any, defaultdict[dt, list[float]], defaultdict[dt, dict[str, Any]], dt]:
    """Build a Dampening backed by a stub SolcastApi for tests that don't need HA."""
    api = MagicMock(spec=SolcastApi)
    api.tz = tz
    api.options = MagicMock()
    api.options.tz = tz
    api.dt_helper = DateTimeHelper(tz)
    api.filename_generation = ""
    api.filename_dampening = ""
    api.advanced_options = {ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_EXCLUDE: []}
    api.sites = []  # instance attribute not in spec; empty list skips site iteration
    dampening = Dampening(api)
    dampening.adjusted_interval_dt = lambda ts: ts.astimezone(tz).hour * 2 + ts.astimezone(tz).minute // 30  # type: ignore[method-assign]
    return dampening.adaptive, defaultdict(lambda: [1.0] * 48), defaultdict(dict), api.dt_helper.day_start_utc()


async def test_build_dampened_actuals_gap_tolerance(caplog: pytest.LogCaptureFixture) -> None:
    """Test _build_dampened_actuals_for_model partial / zero match, and _find_earliest_common_history non-uniform / disjoint history."""
    adaptive, _actuals, _gen, _today = _build_adaptive_under_test(ZoneInfo(ZONE_RAW))
    dampening = adaptive.dampening
    api = dampening.api

    day1 = api.dt_helper.day_start_utc() - timedelta(days=2)
    day2 = api.dt_helper.day_start_utc() - timedelta(days=1)

    factors = [1.0] * 48
    factors[0] = 0.9

    dampening.auto_factors_history = {
        0: {
            0: [
                {PERIOD_START: day1, "factors": factors},
                {PERIOD_START: day2, "factors": factors},
            ]
        }
    }

    actuals: defaultdict[dt, list[float]] = defaultdict(lambda: [0.0] * 48)
    actuals[day1] = [1.0] * 48

    caplog.clear()
    result = adaptive._build_dampened_actuals_for_model(0, 0, day1, actuals)
    assert result is not None, "Result should not be None"
    assert day1 in result
    assert day2 not in result, f"{day2} should not be in result"
    assert "skipping missing actuals" in caplog.text

    caplog.clear()
    result = adaptive._build_dampened_actuals_for_model(0, 0, day2 + timedelta(days=1), actuals)
    assert result is None, "Result should be None"
    assert "produced no dampened actuals" in caplog.text

    model_min = ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_MODEL][MINIMUM]
    model_max = ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_MODEL][MAXIMUM]
    delta_min = ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL][MINIMUM_EXTENDED]
    delta_max = ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL][MAXIMUM]
    min_days = 3
    day0 = day1 - timedelta(days=5)

    def _make_full_history(entries_by_model: dict[int, list[dict]]) -> dict:
        """Build auto_factors_history with the same entries for every delta of each model."""
        history = {}
        for model in range(model_min, model_max + 1):
            history[model] = {}
            for delta in range(delta_min, delta_max + 1):
                history[model][delta] = copy.deepcopy(entries_by_model.get(model, []))
        return history

    gap_entries = [
        {PERIOD_START: day0, "factors": [1.0] * 48},
        {PERIOD_START: day0 + timedelta(days=1), "factors": [1.0] * 48},
        {PERIOD_START: day0 + timedelta(days=3), "factors": [1.0] * 48},
    ]
    continuous_entries = [
        {PERIOD_START: day0, "factors": [1.0] * 48},
        {PERIOD_START: day0 + timedelta(days=1), "factors": [1.0] * 48},
        {PERIOD_START: day0 + timedelta(days=2), "factors": [1.0] * 48},
    ]
    dampening.auto_factors_history = _make_full_history(
        {model_min: gap_entries, **dict.fromkeys(range(model_min + 1, model_max + 1), continuous_entries)}
    )
    assert adaptive._find_earliest_common_history(min_days) is None, "Gap history should return None for earliest common history"

    early_entries = [
        {PERIOD_START: day0, "factors": [1.0] * 48},
        {PERIOD_START: day0 + timedelta(days=1), "factors": [1.0] * 48},
        {PERIOD_START: day0 + timedelta(days=2), "factors": [1.0] * 48},
    ]
    late_entries = [
        {PERIOD_START: day0 + timedelta(days=10), "factors": [1.0] * 48},
        {PERIOD_START: day0 + timedelta(days=11), "factors": [1.0] * 48},
        {PERIOD_START: day0 + timedelta(days=12), "factors": [1.0] * 48},
    ]
    dampening.auto_factors_history = _make_full_history(
        {model_min: early_entries, model_min + 1: early_entries, model_max - 1: late_entries, model_max: late_entries}
    )
    assert adaptive._find_earliest_common_history(min_days) is None, "Disjoint history should return None for earliest common history"


async def test_determine_best_settings_all_combos_skip(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test determine_best_settings when all model/delta evaluations produce no dampened actuals.

    Covers:
    - _evaluate_model_combinations: 'if dampened_actuals is None: continue'
    - _log_model_rankings: 'if not model_rank_frequencies: return'
    - _apply_best_settings: 'if not current_valid: return'
    """
    adaptive, _actuals, _gen, _today = _build_adaptive_under_test(ZoneInfo(ZONE_RAW))
    dampening = adaptive.dampening
    api = dampening.api

    day_start = api.dt_helper.day_start_utc() - timedelta(days=1)

    api.advanced_options.update(
        {
            ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_MINIMUM_HISTORY_DAYS: 1,
            ADVANCED_AUTOMATED_DAMPENING_NO_DELTA_ADJUSTMENT: False,
            ADVANCED_AUTOMATED_DAMPENING_MODEL: ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_MODEL][MINIMUM],
            ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL: ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL][
                MINIMUM_EXTENDED
            ],
            ADVANCED_ESTIMATED_ACTUALS_LOG_MAPE_BREAKDOWN: False,
        }
    )

    monkeypatch.setattr(adaptive, "_find_earliest_common_history", lambda _days: day_start)
    monkeypatch.setattr(adaptive, "_build_actuals_from_sites", lambda _start: {day_start: [1.0] * 48})

    async def _fake_prepare_generation_data(_earliest: dt):
        generation_dampening = defaultdict(dict)
        generation_dampening[day_start] = {GENERATION: 1.0, EXPORT_LIMITING: False}
        generation_dampening_day = defaultdict(float)
        generation_dampening_day[api.dt_helper.day_start(day_start)] = 1.0
        return generation_dampening, generation_dampening_day

    monkeypatch.setattr(dampening, "prepare_generation_data", _fake_prepare_generation_data)
    monkeypatch.setattr(adaptive, "_should_skip_model_delta", lambda _m, _d, _n: (False, ""))
    monkeypatch.setattr(adaptive, "_build_dampened_actuals_for_model", lambda *_args: None)

    caplog.clear()
    await adaptive.determine_best_settings()

    assert "Skipping evaluation for model" in caplog.text
    assert "No ranking data available" in caplog.text
    assert "Could not determine best automated dampening settings" in caplog.text


async def test_calculate_single_interval_error_with_generation(caplog: pytest.LogCaptureFixture) -> None:
    """Test calculate_single_interval_error returns a positive APE when generation is present."""
    adaptive, dampened_actuals, generation_dampening, day_start = _build_adaptive_under_test(ZoneInfo(ZONE_RAW))

    dampened_actuals[adaptive.dampening.api.dt_helper.day_start(day_start)] = [4.0] * 48
    generation_dampening[day_start] = {GENERATION: 1.0, EXPORT_LIMITING: False}

    mean_ape, _ = await adaptive.calculate_single_interval_error(
        dampened_actuals,
        generation_dampening,
        0,
        log_breakdown=True,
    )

    assert mean_ape > 0, f"Expected mean_ape > 0, got {mean_ape}"
    assert "Single interval APE for day" in caplog.text


async def test_calculate_single_interval_error_no_generation(caplog: pytest.LogCaptureFixture) -> None:
    """Test calculate_single_interval_error returns inf when no generation factor is active."""
    adaptive, dampened_actuals, generation_dampening, day_start = _build_adaptive_under_test(ZoneInfo(ZONE_RAW))

    dampened_actuals[adaptive.dampening.api.dt_helper.day_start(day_start)] = [1.0] * 48
    generation_dampening[day_start] = {GENERATION: 0.0, EXPORT_LIMITING: False}

    mean_ape, _ = await adaptive.calculate_single_interval_error(
        dampened_actuals,
        generation_dampening,
        0,
        log_breakdown=True,
    )

    assert mean_ape == math.inf, f"Expected mean_ape == inf, got {mean_ape}"
    assert "Single interval APE for day" in caplog.text


async def test_calculate_single_interval_error_skips_missing() -> None:
    """Test days with missing dampened actuals are skipped."""
    adaptive, dampened_actuals, generation_dampening, day_start = _build_adaptive_under_test(ZoneInfo(ZONE_RAW))
    next_day = day_start + timedelta(days=1)

    generation_dampening[day_start] = {GENERATION: 1.0, EXPORT_LIMITING: False}
    generation_dampening[next_day] = {GENERATION: 1.0, EXPORT_LIMITING: False}

    mean_ape, _ = await adaptive.calculate_single_interval_error(
        dampened_actuals,
        generation_dampening,
        0,
    )

    assert mean_ape == math.inf, f"Expected mean_ape == inf, got {mean_ape}"


async def test_determine_best_settings_alternative_issue(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test alternate model issue creation and clearing in adaptive dampening."""
    adaptive, _actuals, _gen, _today = _build_adaptive_under_test(ZoneInfo(ZONE_RAW))
    dampening = adaptive.dampening
    api = dampening.api

    day_start = api.dt_helper.day_start_utc() - timedelta(days=1)
    factors = [1.0] * 48
    factors[0] = 0.9
    history_entry = {PERIOD_START: day_start, "factors": factors}

    min_model = ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_MODEL][MINIMUM]
    max_model = ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_MODEL][MAXIMUM]
    min_delta = ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL][MINIMUM_EXTENDED]
    max_delta = ADVANCED_OPTIONS[ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL][MAXIMUM]

    dampening.auto_factors_history = {
        model: {delta: [copy.deepcopy(history_entry)] for delta in range(min_delta, max_delta + 1)}
        for model in range(min_model, max_model + 1)
    }

    api.advanced_options.update(
        {
            ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_MINIMUM_HISTORY_DAYS: 1,
            ADVANCED_AUTOMATED_DAMPENING_NO_DELTA_ADJUSTMENT: False,
            ADVANCED_AUTOMATED_DAMPENING_MODEL: max_model,
            ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL: max_delta,
            ADVANCED_ESTIMATED_ACTUALS_LOG_MAPE_BREAKDOWN: False,
        }
    )

    monkeypatch.setattr(adaptive, "_find_earliest_common_history", lambda _days: day_start)
    monkeypatch.setattr(adaptive, "_build_actuals_from_sites", lambda _start: {day_start: [1.0] * 48})

    async def _fake_prepare_generation_data(_earliest: dt):
        generation_dampening = defaultdict(dict)
        generation_dampening[day_start] = {GENERATION: 1.0, EXPORT_LIMITING: False}
        generation_dampening_day = defaultdict(float)
        generation_dampening_day[api.dt_helper.day_start(day_start)] = 1.0
        return generation_dampening, generation_dampening_day

    monkeypatch.setattr(dampening, "prepare_generation_data", _fake_prepare_generation_data)

    current = {"model": min_model, "delta": min_delta}

    def _record_should_skip(model: int, delta: int, _min_days: int) -> tuple[bool, str]:
        current["model"] = model
        current["delta"] = delta
        return False, ""

    monkeypatch.setattr(adaptive, "_should_skip_model_delta", _record_should_skip)

    alternate_better = True
    fake_day = api.dt_helper.day_start(day_start)

    async def _fake_calculate_single_interval_error(*_args, **_kwargs):
        if current["delta"] == VALUE_ADAPTIVE_DAMPENING_NO_DELTA:
            error = 5.0 if alternate_better and current["model"] == min_model else 15.0
            return error, {fake_day: error}
        return 10.0, {fake_day: 10.0}

    monkeypatch.setattr(adaptive, "calculate_single_interval_error", _fake_calculate_single_interval_error)

    async def _fake_serialise_advanced_options() -> None:
        return

    monkeypatch.setattr(adaptive, "_serialise_advanced_options", _fake_serialise_advanced_options)

    caplog.clear()
    await adaptive.determine_best_settings()
    assert "but adaptive dampening found that model" in caplog.text

    alternate_better = False
    caplog.clear()
    await adaptive.determine_best_settings()
    assert "but adaptive dampening found that model" not in caplog.text


async def test_dampening_adaptations_development_flag(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test __init__.py lines 409-410: DAMPENING_ADAPTATIONS_DEVELOPMENT branch.

    Verifies that when the flag is True and auto_dampen with adaptive model
    configuration are both enabled, update_history and determine_best_settings
    are called during async_setup_entry.
    """
    import homeassistant.components.solcast_solar as solcast_module  # noqa: PLC0415
    from homeassistant.components.solcast_solar.dampen_adapt import (  # noqa: PLC0415
        DampeningAdaptive,
    )

    monkeypatch.setattr(solcast_module, "DAMPENING_ADAPTATIONS_DEVELOPMENT", True)

    called = {"update_history": False, "determine_best_settings": False}

    async def _fake_update_history(self) -> None:
        called["update_history"] = True

    async def _fake_determine_best_settings(self) -> None:
        called["determine_best_settings"] = True

    monkeypatch.setattr(DampeningAdaptive, "update_history", _fake_update_history)
    monkeypatch.setattr(DampeningAdaptive, "determine_best_settings", _fake_determine_best_settings)

    write_advanced_options(hass.config.config_dir, {ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_CONFIGURATION: True})

    options = copy.deepcopy(DEFAULT_INPUT2)
    options[AUTO_DAMPEN] = True

    try:
        from homeassistant.config_entries import ConfigEntryState  # noqa: PLC0415

        entry = await async_init_integration(hass, options)
        assert entry.state is ConfigEntryState.LOADED, f"Expected entry state ConfigEntryState.LOADED, got {entry.state}"
        assert called["update_history"], "update_history was not called"
        assert called["determine_best_settings"], "determine_best_settings was not called"
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"
