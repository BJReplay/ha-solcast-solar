"""Unit tests for Solcast Solar DST-related dampening behaviour.

These tests verify:
1. _calculate() produces correct factors and DST-shifted log labels.
2. The coordinator attribute builder generates 48 sorted factors with
   DST-shifted interval labels.
3. Factor storage index does not change across DST transitions; only
   the display label shifts.
"""

from collections import OrderedDict
from datetime import datetime as dt
import tempfile
from typing import Any
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from freezegun import freeze_time
import pytest

from homeassistant.components.solcast_solar.const import (
    ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR,
    ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_GENERATION,
    ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_INTERVALS,
    ADVANCED_AUTOMATED_DAMPENING_PRESERVE_UNMATCHED_FACTORS,
    ALL,
    ENTITY_DAMPEN,
    FACTOR,
    FACTORS,
    INTERVAL,
    METHOD,
    SITE_DAMP,
)
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.dampen import Dampening
from homeassistant.components.solcast_solar.util import DateTimeHelper


@pytest.fixture(autouse=True)
def frozen_time() -> None:
    """Override autouse frozen_time fixture for this module."""
    return


def _make_mock_api(tz: ZoneInfo) -> MagicMock:
    """Build a mock SolcastApi with the minimum attributes _calculate needs."""
    api = MagicMock()
    api.tz = tz
    api.dt_helper = DateTimeHelper(tz)
    api.peak_intervals = [1.0] * 48
    api.advanced_options = {
        ADVANCED_AUTOMATED_DAMPENING_PRESERVE_UNMATCHED_FACTORS: False,
        ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_INTERVALS: 2,
        ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_GENERATION: 2,
        ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR: 0.95,
    }
    # Use temporary files for test file paths
    api.filename_generation = tempfile.NamedTemporaryFile(delete=False).name
    api.filename_dampening = tempfile.NamedTemporaryFile(delete=False).name
    return api


def _make_mock_coordinator(
    factors_list: list[float],
    tz: ZoneInfo,
    auto_dampen: bool = True,
) -> SolcastUpdateCoordinator:
    """Build a mock coordinator with enough internals for get_sensor_extra_attributes."""
    coord = object.__new__(SolcastUpdateCoordinator)
    solcast = MagicMock()
    solcast.entry_options = {SITE_DAMP: True}
    solcast.options.auto_dampen = auto_dampen
    solcast.options.tz = tz
    solcast.dampening.factors = {ALL: factors_list}
    solcast.dampening.factors_mtime = 0
    solcast.advanced_options = {}
    coord.solcast = solcast
    coord._SolcastUpdateCoordinator__get_value = {  # pyright: ignore[reportAttributeAccessIssue]
        ENTITY_DAMPEN: [{METHOD: lambda: True}],
    }
    return coord


def _build_matching_data(
    interval: int,
    timestamps: list[dt],
    gen_values: list[float],
    act_values: list[float],
) -> tuple[dict[int, list[dt]], dict[dt, float], dict[dt, float]]:
    """Build matching_intervals, generation, and actuals dicts for one interval."""
    matching_intervals: dict[int, list[dt]] = {interval: timestamps}
    generation = dict(zip(timestamps, gen_values, strict=True))
    actuals = OrderedDict(zip(timestamps, act_values, strict=True))
    return matching_intervals, generation, actuals


def _get_attribute_factors(
    factors_list: list[float],
    tz: ZoneInfo,
    auto_dampen: bool = True,
) -> list[dict[str, Any]]:
    """Return dampening factor attributes using the coordinator method directly."""
    coord = _make_mock_coordinator(factors_list, tz, auto_dampen)
    result = coord.get_sensor_extra_attributes(ENTITY_DAMPEN)

    assert result is not None, "Result should not be None"
    return result[FACTORS]


class TestCalculateFactorComputation:
    """Test _calculate produces correct factor values."""

    @pytest.mark.parametrize(
        ("dampening_model", "gen_values", "act_values", "expected_factor"),
        [
            # Default model (0): peak-based, factor = max(gen) / peak
            (0, [0.819, 0.800], [1.0, 1.0], 0.819),
            # Model 1 (max): max of gen/act ratios
            (1, [0.819, 0.700], [1.0, 1.0], 0.819),
            # Model 2 (avg): average of gen/act ratios
            (2, [0.819, 0.819], [1.0, 1.0], 0.819),
            # Model 3 (min): min of gen/act ratios
            (3, [0.900, 0.819], [1.0, 1.0], 0.819),
        ],
    )
    @freeze_time("2025-10-03T14:00:00+11:00")
    async def test_factor_value(
        self,
        dampening_model: int,
        gen_values: list[float],
        act_values: list[float],
        expected_factor: float,
    ) -> None:
        """Test _calculate produces the correct factor value for different models."""
        tz = ZoneInfo("Australia/Sydney")
        api = _make_mock_api(tz)
        dampening = Dampening(api)

        interval = 20  # 10:00 local standard time
        timestamps = [
            dt(2025, 10, 1, 0, 0, tzinfo=tz),
            dt(2025, 10, 2, 0, 0, tzinfo=tz),
        ]

        matching_intervals, generation, actuals = _build_matching_data(interval, timestamps, gen_values, act_values)

        result = await dampening.calculate(matching_intervals, generation, actuals, [], dampening_model)

        assert len(result) == 48, f"Model {dampening_model}: expected 48 intervals, got {len(result)}"
        assert result[interval] == expected_factor, (
            f"Model {dampening_model}: interval {interval} expected {expected_factor}, got {result[interval]}"
        )

    @freeze_time("2025-10-03T14:00:00+11:00")
    async def test_unmatched_intervals_remain_one(self) -> None:
        """Test that intervals without matching data stay at 1.0."""
        tz = ZoneInfo("Australia/Sydney")
        api = _make_mock_api(tz)
        dampening = Dampening(api)

        interval = 20
        timestamps = [
            dt(2025, 10, 1, 0, 0, tzinfo=tz),
            dt(2025, 10, 2, 0, 0, tzinfo=tz),
        ]
        matching_intervals, generation, actuals = _build_matching_data(interval, timestamps, [0.819, 0.819], [1.0, 1.0])

        result = await dampening.calculate(matching_intervals, generation, actuals, [], 0)

        # All intervals except 20 should remain 1.0
        for i in range(48):
            if i != interval:
                assert result[i] == 1.0, f"interval {i} should be 1.0"

    @freeze_time("2025-10-03T14:00:00+11:00")
    async def test_ignored_interval_skipped(self) -> None:
        """Test that an ignored interval is skipped and stays at 1.0."""
        tz = ZoneInfo("Australia/Sydney")
        api = _make_mock_api(tz)
        dampening = Dampening(api)

        interval = 20
        timestamps = [
            dt(2025, 10, 1, 0, 0, tzinfo=tz),
            dt(2025, 10, 2, 0, 0, tzinfo=tz),
        ]
        matching_intervals, generation, actuals = _build_matching_data(interval, timestamps, [0.5, 0.5], [1.0, 1.0])

        result = await dampening.calculate(matching_intervals, generation, actuals, [interval], 0)

        assert result[interval] == 1.0, f"Ignored interval {interval} should remain 1.0, got {result[interval]}"


class TestCalculateDSTLabels:
    """Test _calculate produces DST-shifted labels in log messages."""

    @freeze_time("2025-10-06T14:00:00+11:00")  # AEDT (summer time, after Oct 5 transition)
    async def test_summer_time_label_shift(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test label shows +1 hour during AEDT (summer time).

        Interval 20 = 10:00 standard. During AEDT, dst_offset=1 → label "11:00".
        """
        tz = ZoneInfo("Australia/Sydney")
        api = _make_mock_api(tz)
        dampening = Dampening(api)

        interval = 20
        timestamps = [
            dt(2025, 10, 1, 0, 0, tzinfo=tz),
            dt(2025, 10, 2, 0, 0, tzinfo=tz),
        ]
        matching_intervals, generation, actuals = _build_matching_data(interval, timestamps, [0.819, 0.819], [1.0, 1.0])

        with caplog.at_level("DEBUG"):
            await dampening.calculate(matching_intervals, generation, actuals, [], 0)

        assert "Auto-dampen factor for 11:00 is 0.819" in caplog.text

    @freeze_time("2025-06-15T14:00:00+10:00")  # AEST (standard time)
    async def test_standard_time_label_no_shift(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test label shows no shift during AEST (standard time).

        Interval 20 = 10:00 standard. During AEST, dst_offset=0 → label "10:00".
        """
        tz = ZoneInfo("Australia/Sydney")
        api = _make_mock_api(tz)
        dampening = Dampening(api)

        interval = 20
        timestamps = [
            dt(2025, 6, 1, 0, 0, tzinfo=tz),
            dt(2025, 6, 2, 0, 0, tzinfo=tz),
        ]
        matching_intervals, generation, actuals = _build_matching_data(interval, timestamps, [0.819, 0.819], [1.0, 1.0])

        with caplog.at_level("DEBUG"):
            await dampening.calculate(matching_intervals, generation, actuals, [], 0)

        assert "Auto-dampen factor for 10:00 is 0.819" in caplog.text

    @freeze_time("2025-10-02T14:00:00+10:00")  # Day before spring-forward
    async def test_label_before_spring_forward(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test label before Sydney spring-forward (first Sunday in October).

        Oct 2 is still AEST → dst_offset=0, interval 20 → "10:00".
        """
        tz = ZoneInfo("Australia/Sydney")
        api = _make_mock_api(tz)
        dampening = Dampening(api)

        interval = 20
        timestamps = [
            dt(2025, 9, 28, 0, 0, tzinfo=tz),
            dt(2025, 9, 29, 0, 0, tzinfo=tz),
        ]
        matching_intervals, generation, actuals = _build_matching_data(interval, timestamps, [0.819, 0.819], [1.0, 1.0])

        with caplog.at_level("DEBUG"):
            await dampening.calculate(matching_intervals, generation, actuals, [], 0)

        assert "Auto-dampen factor for 10:00 is 0.819" in caplog.text

    @freeze_time("2025-10-05T14:00:00+11:00")  # Day after spring-forward
    async def test_label_after_spring_forward(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test label after Sydney spring-forward.

        Oct 5 is AEDT → dst_offset=1, interval 20 → "11:00".
        """
        tz = ZoneInfo("Australia/Sydney")
        api = _make_mock_api(tz)
        dampening = Dampening(api)

        interval = 20
        timestamps = [
            dt(2025, 10, 3, 0, 0, tzinfo=tz),
            dt(2025, 10, 4, 0, 0, tzinfo=tz),
        ]
        matching_intervals, generation, actuals = _build_matching_data(interval, timestamps, [0.819, 0.819], [1.0, 1.0])

        with caplog.at_level("DEBUG"):
            await dampening.calculate(matching_intervals, generation, actuals, [], 0)

        assert "Auto-dampen factor for 11:00 is 0.819" in caplog.text


class TestAttributeBuilderDSTLabels:
    """Test the coordinator attribute builder labels shift with DST."""

    @freeze_time("2025-10-02T14:00:00+10:00")  # AEST (before spring-forward)
    def test_standard_time_labels(self) -> None:
        """Test attribute labels during standard time (AEST).

        Interval 20 → hour 10, no DST offset → label "10:00".
        """
        tz = ZoneInfo("Australia/Sydney")
        factors_list = [1.0] * 48
        factors_list[20] = 0.819

        result = _get_attribute_factors(factors_list, tz)

        assert len(result) == 48, f"Expected 48 attribute entries during AEST, got {len(result)}"
        # Find the entry with factor 0.819
        matching = [e for e in result if e[FACTOR] == 0.819]
        assert len(matching) == 1, f"Expected exactly 1 entry with factor 0.819 during AEST, got {len(matching)}"
        assert matching[0][INTERVAL] == "10:00", f"AEST: factor 0.819 should be at 10:00, got {matching[0][INTERVAL]}"

    @freeze_time("2025-10-05T14:00:00+11:00")  # AEDT (after spring-forward)
    def test_summer_time_labels(self) -> None:
        """Test attribute labels during summer time (AEDT).

        Interval 20 → hour 10 + 1 DST offset → label "11:00".
        """
        tz = ZoneInfo("Australia/Sydney")
        factors_list = [1.0] * 48
        factors_list[20] = 0.819

        result = _get_attribute_factors(factors_list, tz)

        assert len(result) == 48, f"Expected 48 attribute entries during AEDT, got {len(result)}"
        matching = [e for e in result if e[FACTOR] == 0.819]
        assert len(matching) == 1, f"Expected exactly 1 entry with factor 0.819 during AEDT, got {len(matching)}"
        assert matching[0][INTERVAL] == "11:00", f"AEDT: factor 0.819 should be at 11:00, got {matching[0][INTERVAL]}"

    @freeze_time("2025-10-05T14:00:00+11:00")  # AEDT
    def test_factor_at_original_index_maps_to_shifted_label(self) -> None:
        """Test factor stored at raw index 20 appears at label "11:00" during AEDT.

        This is the core of the DST test: the underlying storage index
        stays at 20, but the display label shifts from "10:00" → "11:00".
        """
        tz = ZoneInfo("Australia/Sydney")
        factors_list = [1.0] * 48
        factors_list[20] = 0.819

        result = _get_attribute_factors(factors_list, tz)

        # In the sorted result, find entry at label "11:00"
        entry_11 = next(e for e in result if e[INTERVAL] == "11:00")
        assert entry_11[FACTOR] == 0.819, f"AEDT: label 11:00 should have factor 0.819, got {entry_11[FACTOR]}"

        # Label "10:00" should be 1.0 (it maps to raw index 18 during AEDT)
        entry_10 = next(e for e in result if e[INTERVAL] == "10:00")
        assert entry_10[FACTOR] == 1.0, f"AEDT: label 10:00 should have factor 1.0, got {entry_10[FACTOR]}"

    @freeze_time("2025-10-02T14:00:00+10:00")  # AEST
    def test_factor_at_original_index_no_shift_during_standard(self) -> None:
        """Test factor stored at raw index 20 appears at label "10:00" during AEST."""
        tz = ZoneInfo("Australia/Sydney")
        factors_list = [1.0] * 48
        factors_list[20] = 0.819

        result = _get_attribute_factors(factors_list, tz)

        entry_10 = next(e for e in result if e[INTERVAL] == "10:00")
        assert entry_10[FACTOR] == 0.819, f"AEST: label 10:00 should have factor 0.819, got {entry_10[FACTOR]}"


class TestDSTTransitionScenarios:
    """Test the complete DST transition scenarios.

    These replicate what the original integration tests verified:
    - Spring-forward: factor label shifts from "10:00" to "11:00" for index 20
    - Fall-back: factor label shifts from "11:00" to "10:00" for index 20
    """

    @pytest.mark.parametrize(
        ("frozen_before", "frozen_after", "interval", "label_before", "label_after"),
        [
            # Spring-forward (Oct 5 2025): AEST→AEDT
            (
                "2025-10-02T14:00:00+10:00",
                "2025-10-05T14:00:00+11:00",
                20,
                "10:00",
                "11:00",
            ),
            # Fall-back (Apr 6 2026): AEDT→AEST
            (
                "2026-04-02T14:00:00+11:00",
                "2026-04-06T14:00:00+10:00",
                20,
                "11:00",
                "10:00",
            ),
        ],
    )
    def test_label_shifts_across_transition(
        self,
        frozen_before: str,
        frozen_after: str,
        interval: int,
        label_before: str,
        label_after: str,
    ) -> None:
        """Test that the attribute label shifts across a DST transition.

        The factor stays at the same raw index in the underlying list,
        but the label changes because the attribute builder uses dt.now()
        to determine DST state.
        """
        tz = ZoneInfo("Australia/Sydney")
        factors_list = [1.0] * 48
        factors_list[interval] = 0.819

        # Before transition
        with freeze_time(frozen_before):
            result_before = _get_attribute_factors(factors_list, tz)
        matching_before = [e for e in result_before if e[FACTOR] == 0.819]
        assert len(matching_before) == 1, (
            f"Before transition ({frozen_before}): expected 1 entry with factor 0.819, got {len(matching_before)}"
        )
        assert matching_before[0][INTERVAL] == label_before, (
            f"Before transition: expected label {label_before}, got {matching_before[0][INTERVAL]}"
        )

        # After transition
        with freeze_time(frozen_after):
            result_after = _get_attribute_factors(factors_list, tz)
        matching_after = [e for e in result_after if e[FACTOR] == 0.819]
        assert len(matching_after) == 1, f"After transition ({frozen_after}): expected 1 entry with factor 0.819, got {len(matching_after)}"
        assert matching_after[0][INTERVAL] == label_after, (
            f"After transition: expected label {label_after}, got {matching_after[0][INTERVAL]}"
        )

    @pytest.mark.parametrize(
        ("frozen_before", "frozen_after", "interval", "dampening_model", "label_before", "label_after"),
        [
            # Spring-forward: _calculate log label shifts 10:00 → 11:00
            (
                "2025-10-02T14:00:00+10:00",
                "2025-10-05T14:00:00+11:00",
                20,
                0,
                "10:00",
                "11:00",
            ),
            # Fall-back: _calculate log label shifts 11:00 → 10:00
            (
                "2026-04-02T14:00:00+11:00",
                "2026-04-06T14:00:00+10:00",
                20,
                0,
                "11:00",
                "10:00",
            ),
        ],
    )
    async def test_calculate_log_label_shifts_across_transition(
        self,
        caplog: pytest.LogCaptureFixture,
        frozen_before: str,
        frozen_after: str,
        interval: int,
        dampening_model: int,
        label_before: str,
        label_after: str,
    ) -> None:
        """Test _calculate log labels shift across DST transition.

        The factor value stays the same, but the label in the log
        message changes with DST.
        """
        tz = ZoneInfo("Australia/Sydney")
        gen_values = [0.819, 0.819]
        act_values = [1.0, 1.0]

        # Before transition
        with freeze_time(frozen_before):
            api = _make_mock_api(tz)
            dampening_obj = Dampening(api)
            timestamps = [
                dt(2025, 9, 28, 0, 0, tzinfo=tz),
                dt(2025, 9, 29, 0, 0, tzinfo=tz),
            ]
            matching_intervals, generation, actuals = _build_matching_data(interval, timestamps, gen_values, act_values)
            with caplog.at_level("DEBUG"):
                result = await dampening_obj.calculate(matching_intervals, generation, actuals, [], dampening_model)
            assert result[interval] == 0.819, f"Before transition: interval {interval} expected 0.819, got {result[interval]}"
            assert f"Auto-dampen factor for {label_before} is 0.819" in caplog.text, f"Before transition: expected log label {label_before}"
            caplog.clear()

        # After transition
        with freeze_time(frozen_after):
            api = _make_mock_api(tz)
            dampening_obj = Dampening(api)
            with caplog.at_level("DEBUG"):
                result = await dampening_obj.calculate(matching_intervals, generation, actuals, [], dampening_model)
            assert result[interval] == 0.819, f"After transition: interval {interval} expected 0.819, got {result[interval]}"
            assert f"Auto-dampen factor for {label_after} is 0.819" in caplog.text, f"After transition: expected log label {label_after}"

    @pytest.mark.parametrize(
        ("dampening_model", "gen_values", "act_values", "expected_factor"),
        [
            (0, [0.819, 0.800], [1.0, 1.0], 0.819),
            (1, [0.819, 0.700], [1.0, 1.0], 0.819),
            (2, [0.819, 0.819], [1.0, 1.0], 0.819),
            (3, [0.900, 0.819], [1.0, 1.0], 0.819),
        ],
    )
    @freeze_time("2025-10-05T14:00:00+11:00")
    async def test_factor_persists_at_index_across_models(
        self,
        dampening_model: int,
        gen_values: list[float],
        act_values: list[float],
        expected_factor: float,
    ) -> None:
        """Test the factor value is consistent at the raw index regardless of DST display."""
        tz = ZoneInfo("Australia/Sydney")
        api = _make_mock_api(tz)
        dampening_obj = Dampening(api)

        interval = 20
        timestamps = [
            dt(2025, 10, 1, 0, 0, tzinfo=tz),
            dt(2025, 10, 2, 0, 0, tzinfo=tz),
        ]
        matching_intervals, generation, actuals = _build_matching_data(interval, timestamps, gen_values, act_values)

        result = await dampening_obj.calculate(matching_intervals, generation, actuals, [], dampening_model)

        assert result[interval] == expected_factor, (
            f"Model {dampening_model}: interval {interval} expected {expected_factor}, got {result[interval]}"
        )
        # Display label is shifted but factor is at raw index
        attrs = _get_attribute_factors(result, tz)
        matching = [e for e in attrs if e[FACTOR] == expected_factor]
        assert len(matching) == 1, f"Model {dampening_model}: expected 1 attribute entry with factor {expected_factor}, got {len(matching)}"
        assert matching[0][INTERVAL] == "11:00", (
            f"Model {dampening_model}: AEDT label should be 11:00, got {matching[0][INTERVAL]}"
        )  # AEDT: 10:00+1


class TestAttributeBuilderEdgeCases:
    """Test attribute builder edge cases around DST boundaries."""

    @freeze_time("2025-10-05T14:00:00+11:00")  # AEDT
    def test_48_entries_after_dst_shift(self) -> None:
        """Test attribute builder always produces exactly 48 entries during DST."""
        tz = ZoneInfo("Australia/Sydney")
        factors_list = [1.0] * 48

        result = _get_attribute_factors(factors_list, tz)

        assert len(result) == 48, f"AEDT: expected 48 entries, got {len(result)}"
        # Verify sorted order
        intervals = [e[INTERVAL] for e in result]
        assert intervals == sorted(intervals), "AEDT: attribute entries are not sorted"

    @freeze_time("2025-10-05T14:00:00+11:00")  # AEDT
    def test_fill_in_entries_during_dst(self) -> None:
        """Test 00:00/00:30 and 03:00/03:30 are filled in if missing during DST.

        During AEDT, index 0 maps to label "01:00" and index 1 to "01:30",
        so "00:00" and "00:30" would be missing without fill-in logic.
        """
        tz = ZoneInfo("Australia/Sydney")
        factors_list = [0.5] * 48

        result = _get_attribute_factors(factors_list, tz)

        assert len(result) == 48, f"AEDT fill-in: expected 48 entries, got {len(result)}"
        labels = {e[INTERVAL] for e in result}
        assert "00:00" in labels, "AEDT: missing 00:00 fill-in entry"
        assert "00:30" in labels, "AEDT: missing 00:30 fill-in entry"

    @freeze_time("2025-10-02T14:00:00+10:00")  # AEST
    def test_no_extra_entries_during_standard_time(self) -> None:
        """Test attribute builder produces exactly 48 entries during standard time."""
        tz = ZoneInfo("Australia/Sydney")
        factors_list = [1.0] * 48

        result = _get_attribute_factors(factors_list, tz)

        assert len(result) == 48, f"AEST: expected 48 entries, got {len(result)}"
        intervals = [e[INTERVAL] for e in result]
        assert intervals == sorted(intervals), "AEST: attribute entries are not sorted"
        # During standard time, no 24:00/24:30 should exist
        assert "24:00" not in intervals, "AEST: unexpected 24:00 entry"
        assert "24:30" not in intervals, "AEST: unexpected 24:30 entry"


class TestWinterTimeDSTLabels:
    """Test DST label behaviour for winter time zones like Europe/Dublin.

    Dublin uses "Winter time" where dst() returns timedelta(-1h) in winter
    and timedelta(0) in summer (IST). The util.dst() helper accounts for
    this by checking against timedelta(0) instead of timedelta(1h) for
    WINTER_TIME zones.
    """

    @freeze_time("2025-06-15T14:00:00+01:00")  # IST (summer)
    async def test_dublin_summer_label(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test Dublin summer (IST) produces shifted labels."""
        tz = ZoneInfo("Europe/Dublin")
        api = _make_mock_api(tz)
        dampening_obj = Dampening(api)

        interval = 20
        timestamps = [
            dt(2025, 6, 1, 10, 0, tzinfo=tz),
            dt(2025, 6, 2, 10, 0, tzinfo=tz),
        ]
        matching_intervals, generation, actuals = _build_matching_data(interval, timestamps, [0.819, 0.819], [1.0, 1.0])

        with caplog.at_level("DEBUG"):
            await dampening_obj.calculate(matching_intervals, generation, actuals, [], 0)

        # Dublin summer: IST, dst() helper returns True → offset 1 → label "11:00"
        assert "Auto-dampen factor for 11:00 is 0.819" in caplog.text

    @freeze_time("2025-01-15T14:00:00+00:00")  # GMT (winter)
    async def test_dublin_winter_label(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test Dublin winter (GMT) produces unshifted labels."""
        tz = ZoneInfo("Europe/Dublin")
        api = _make_mock_api(tz)
        dampening_obj = Dampening(api)

        interval = 20
        timestamps = [
            dt(2025, 1, 1, 10, 0, tzinfo=tz),
            dt(2025, 1, 2, 10, 0, tzinfo=tz),
        ]
        matching_intervals, generation, actuals = _build_matching_data(interval, timestamps, [0.819, 0.819], [1.0, 1.0])

        with caplog.at_level("DEBUG"):
            await dampening_obj.calculate(matching_intervals, generation, actuals, [], 0)

        # Dublin winter: GMT, dst() helper returns False → offset 0 → label "10:00"
        assert "Auto-dampen factor for 10:00 is 0.819" in caplog.text


class TestCoordinatorAttributeBuilder:
    """Test the real coordinator get_sensor_extra_attributes method.

    These tests exercise the DST fill-in and removal branches in coordinator.py.
    """

    @freeze_time("2025-10-06T14:00:00+11:00")  # Fully AEDT (day after transition)
    def test_fill_in_00_entries_during_full_dst(self) -> None:
        """Test that 00:00/00:30 entries are filled in during full DST.

        On a fully-AEDT day (Oct 6), index 0 maps to label "01:00"
        (hour 0 + DST offset 1), so "00:00" and "00:30" are missing.
        The coordinator fills these with factor 1.
        """
        tz = ZoneInfo("Australia/Sydney")
        factors_list = [0.5] * 48
        coord = _make_mock_coordinator(factors_list, tz)

        result = coord.get_sensor_extra_attributes(ENTITY_DAMPEN)

        assert result is not None, "Full DST: get_sensor_extra_attributes returned None"
        factors = result[FACTORS]
        assert len(factors) == 48, f"Full DST: expected 48 entries, got {len(factors)}"
        labels = {e[INTERVAL] for e in factors}
        assert "00:00" in labels, "Full DST: missing 00:00 fill-in entry"
        assert "00:30" in labels, "Full DST: missing 00:30 fill-in entry"
        # The filled entries have factor 1 (not 0.5)
        entry_00 = next(e for e in factors if e[INTERVAL] == "00:00")
        assert entry_00[FACTOR] == 1, f"Full DST: 00:00 fill-in should have factor 1, got {entry_00[FACTOR]}"
        entry_0030 = next(e for e in factors if e[INTERVAL] == "00:30")
        assert entry_0030[FACTOR] == 1, f"Full DST: 00:30 fill-in should have factor 1, got {entry_0030[FACTOR]}"

    @freeze_time("2025-10-05T14:00:00+11:00")  # Transition day (AEST→AEDT)
    def test_fill_in_03_entries_on_transition_day(self) -> None:
        """Test that 03:00/03:30 entries are filled in on the transition day.

        On the transition day (Oct 5), hours 0-2 are still AEST (no shift),
        but hour 3 jumps to AEDT (shift +1 → "04:00"). So "03:00"/"03:30"
        are missing and need fill-in.
        """
        tz = ZoneInfo("Australia/Sydney")
        factors_list = [0.5] * 48
        coord = _make_mock_coordinator(factors_list, tz)

        result = coord.get_sensor_extra_attributes(ENTITY_DAMPEN)

        assert result is not None, "Transition day: get_sensor_extra_attributes returned None"
        factors = result[FACTORS]
        assert len(factors) == 48, f"Transition day: expected 48 entries, got {len(factors)}"
        labels = {e[INTERVAL] for e in factors}
        assert "03:00" in labels, "Transition day: missing 03:00 fill-in entry"
        assert "03:30" in labels, "Transition day: missing 03:30 fill-in entry"
        entry_03 = next(e for e in factors if e[INTERVAL] == "03:00")
        assert entry_03[FACTOR] == 1, f"Transition day: 03:00 fill-in should have factor 1, got {entry_03[FACTOR]}"
        entry_0330 = next(e for e in factors if e[INTERVAL] == "03:30")
        assert entry_0330[FACTOR] == 1, f"Transition day: 03:30 fill-in should have factor 1, got {entry_0330[FACTOR]}"

    @freeze_time("2025-10-06T14:00:00+11:00")  # Fully AEDT
    def test_remove_24h_entries_during_dst(self) -> None:
        """Test that 24:00/24:30 entries are removed during DST.

        During AEDT, index 46 maps to hour 23 + 1 = "24:00" and
        index 47 maps to "24:30". These are removed by the coordinator.
        """
        tz = ZoneInfo("Australia/Sydney")
        factors_list = [1.0] * 48
        factors_list[46] = 0.7
        factors_list[47] = 0.8
        coord = _make_mock_coordinator(factors_list, tz)

        result = coord.get_sensor_extra_attributes(ENTITY_DAMPEN)

        assert result is not None, "DST 24h removal: get_sensor_extra_attributes returned None"
        factors = result[FACTORS]
        assert len(factors) == 48, f"DST 24h removal: expected 48 entries, got {len(factors)}"
        labels = {e[INTERVAL] for e in factors}
        assert "24:00" not in labels, "DST: 24:00 should be removed"
        assert "24:30" not in labels, "DST: 24:30 should be removed"

    @freeze_time("2025-10-02T14:00:00+10:00")  # AEST (no DST)
    def test_no_fill_in_during_standard_time(self) -> None:
        """Test no fill-in or removal needed during standard time."""
        tz = ZoneInfo("Australia/Sydney")
        factors_list = [1.0] * 48
        factors_list[20] = 0.819
        coord = _make_mock_coordinator(factors_list, tz)

        result = coord.get_sensor_extra_attributes(ENTITY_DAMPEN)

        assert result is not None, "AEST standard: get_sensor_extra_attributes returned None"
        factors = result[FACTORS]
        assert len(factors) == 48, f"AEST standard: expected 48 entries, got {len(factors)}"
        labels = [e[INTERVAL] for e in factors]
        assert labels == sorted(labels), "AEST standard: attribute entries are not sorted"
        assert "24:00" not in labels, "AEST standard: unexpected 24:00 entry"
        # Factor at index 20 maps to "10:00" during AEST
        entry_10 = next(e for e in factors if e[INTERVAL] == "10:00")
        assert entry_10[FACTOR] == 0.819, f"AEST standard: 10:00 should have factor 0.819, got {entry_10[FACTOR]}"

    @freeze_time("2025-10-05T14:00:00+11:00")  # AEDT
    def test_factor_at_index_20_maps_to_shifted_label(self) -> None:
        """Test factor at raw index 20 shows at label "11:00" during AEDT."""
        tz = ZoneInfo("Australia/Sydney")
        factors_list = [1.0] * 48
        factors_list[20] = 0.819
        coord = _make_mock_coordinator(factors_list, tz)

        result = coord.get_sensor_extra_attributes(ENTITY_DAMPEN)

        assert result is not None, "AEDT index-20: get_sensor_extra_attributes returned None"
        factors = result[FACTORS]
        entry_11 = next(e for e in factors if e[INTERVAL] == "11:00")
        assert entry_11[FACTOR] == 0.819, f"AEDT: label 11:00 should have factor 0.819, got {entry_11[FACTOR]}"

    @freeze_time("2025-10-05T14:00:00+11:00")  # AEDT
    def test_all_48_entries_sorted_during_dst(self) -> None:
        """Test that the result is exactly 48 sorted entries during DST."""
        tz = ZoneInfo("Australia/Sydney")
        factors_list = [1.0] * 48
        coord = _make_mock_coordinator(factors_list, tz)

        result = coord.get_sensor_extra_attributes(ENTITY_DAMPEN)

        assert result is not None, "AEDT sorted: get_sensor_extra_attributes returned None"
        factors = result[FACTORS]
        assert len(factors) == 48, f"AEDT sorted: expected 48 entries, got {len(factors)}"
        intervals = [e[INTERVAL] for e in factors]
        assert intervals == sorted(intervals), "AEDT sorted: attribute entries are not sorted"
