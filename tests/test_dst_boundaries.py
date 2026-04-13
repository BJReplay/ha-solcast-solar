"""Tests for DST boundary and interval-index edge cases.

Fast mock-based unit tests for pure-function interval calculations,
plus integration tests for apply_forward, updater scheduling, and
transition detection on DST transition days.
"""

import copy
from datetime import datetime as dt
import json
from pathlib import Path
import tempfile
from typing import Any
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar.const import (
    ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR,
    ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_GENERATION,
    ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_INTERVALS,
    ADVANCED_AUTOMATED_DAMPENING_PRESERVE_UNMATCHED_FACTORS,
    AUTO_DAMPEN,
    AUTO_UPDATE,
    CONFIG_DISCRETE_NAME,
    CONFIG_FOLDER_DISCRETE,
    EXCLUDE_SITES,
    GENERATION_ENTITIES,
    GET_ACTUALS,
    PERIOD_START,
    SITE_EXPORT_ENTITY,
    SITE_EXPORT_LIMIT,
    USE_ACTUALS,
)
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.dampen import Dampening
from homeassistant.components.solcast_solar.util import DateTimeHelper
from homeassistant.core import HomeAssistant

from . import (
    DEFAULT_INPUT1,
    DEFAULT_INPUT2,
    ExtraSensors,
    async_cleanup_integration_tests,
    async_init_integration,
)


@pytest.fixture(autouse=True)
def frozen_time() -> None:
    """Override autouse frozen_time fixture for this module."""
    return


def _make_mock_api(tz: ZoneInfo) -> MagicMock:
    """Build a minimal mock SolcastApi with only what interval methods need."""
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
    api.filename_generation = tempfile.NamedTemporaryFile(delete=False).name
    api.filename_dampening = tempfile.NamedTemporaryFile(delete=False).name
    return api


def _dampening(tz_name: str) -> Dampening:
    """Return a Dampening instance wired to a lightweight mock API."""
    return Dampening(_make_mock_api(ZoneInfo(tz_name)))


def _dt_helper(tz_name: str) -> DateTimeHelper:
    """Return a DateTimeHelper for the given timezone."""
    return DateTimeHelper(ZoneInfo(tz_name))


@pytest.mark.parametrize(
    ("timezone", "local_iso", "expected_interval", "description"),
    [
        # -- Australia/Sydney (UTC+11 AEDT / UTC+10 AEST) --
        # During AEDT (DST active), offset = 1
        ("Australia/Sydney", "2025-11-15T00:00:00+11:00", 0, "Sydney DST midnight clamps to interval 0"),
        ("Australia/Sydney", "2025-11-15T00:30:00+11:00", 0, "Sydney DST 00:30 clamps to interval 0"),
        ("Australia/Sydney", "2025-11-15T01:00:00+11:00", 0, "Sydney DST 01:00 maps to interval 0 (standard 00:00)"),
        ("Australia/Sydney", "2025-11-15T01:30:00+11:00", 1, "Sydney DST 01:30 maps to interval 1 (standard 00:30)"),
        ("Australia/Sydney", "2025-11-15T12:00:00+11:00", 22, "Sydney DST noon maps to interval 22 (standard 11:00)"),
        ("Australia/Sydney", "2025-11-15T23:00:00+11:00", 44, "Sydney DST 23:00 maps to interval 44 (standard 22:00)"),
        ("Australia/Sydney", "2025-11-15T23:30:00+11:00", 45, "Sydney DST 23:30 maps to interval 45 (standard 22:30)"),
        # During AEST (non-DST), offset = 0
        ("Australia/Sydney", "2025-07-15T00:00:00+10:00", 0, "Sydney standard midnight maps to interval 0"),
        ("Australia/Sydney", "2025-07-15T12:00:00+10:00", 24, "Sydney standard noon maps to interval 24"),
        ("Australia/Sydney", "2025-07-15T23:30:00+10:00", 47, "Sydney standard 23:30 maps to interval 47"),
        # -- Europe/Dublin (UTC+1 IST / UTC+0 GMT) --
        # Winter (GMT): offset = 0
        ("Europe/Dublin", "2025-12-15T00:00:00+00:00", 0, "Dublin winter midnight maps to interval 0"),
        ("Europe/Dublin", "2025-12-15T00:30:00+00:00", 1, "Dublin winter 00:30 maps to interval 1"),
        ("Europe/Dublin", "2025-12-15T01:00:00+00:00", 2, "Dublin winter 01:00 maps to interval 2"),
        ("Europe/Dublin", "2025-12-15T12:00:00+00:00", 24, "Dublin winter noon maps to interval 24"),
        ("Europe/Dublin", "2025-12-15T23:30:00+00:00", 47, "Dublin winter 23:30 maps to interval 47"),
        # Summer (IST): offset = 1
        ("Europe/Dublin", "2025-07-15T00:00:00+01:00", 0, "Dublin summer midnight clamps to interval 0"),
        ("Europe/Dublin", "2025-07-15T00:30:00+01:00", 0, "Dublin summer 00:30 clamps to interval 0"),
        ("Europe/Dublin", "2025-07-15T01:00:00+01:00", 0, "Dublin summer 01:00 maps to interval 0 (GMT 00:00)"),
        ("Europe/Dublin", "2025-07-15T12:00:00+01:00", 22, "Dublin summer noon maps to interval 22 (GMT 11:00)"),
        ("Europe/Dublin", "2025-07-15T23:30:00+01:00", 45, "Dublin summer 23:30 maps to interval 45 (GMT 22:30)"),
        # -- Non-DST zone (Australia/Brisbane) --
        ("Australia/Brisbane", "2025-07-15T00:00:00+10:00", 0, "Brisbane midnight maps to interval 0 (never DST)"),
        ("Australia/Brisbane", "2025-07-15T23:30:00+10:00", 47, "Brisbane 23:30 maps to interval 47 (never DST)"),
    ],
)
def test_adjusted_interval_dt_boundaries(
    timezone: str,
    local_iso: str,
    expected_interval: int,
    description: str,
) -> None:
    """Test adjusted_interval_dt returns correct interval index at DST boundaries."""
    dampening = _dampening(timezone)
    result = dampening.adjusted_interval_dt(dt.fromisoformat(local_iso))
    assert result == expected_interval, f"{description}: expected {expected_interval}, got {result}"


@pytest.mark.parametrize(
    ("timezone", "local_iso", "expected_interval", "description"),
    [
        ("Australia/Sydney", "2025-11-15T00:00:00+11:00", 0, "Dict: Sydney DST midnight clamps to 0"),
        ("Australia/Sydney", "2025-11-15T01:00:00+11:00", 0, "Dict: Sydney DST 01:00 maps to 0"),
        ("Australia/Sydney", "2025-07-15T00:00:00+10:00", 0, "Dict: Sydney standard midnight maps to 0"),
        ("Europe/Dublin", "2025-07-15T00:00:00+01:00", 0, "Dict: Dublin summer midnight clamps to 0"),
        ("Europe/Dublin", "2025-07-15T12:00:00+01:00", 22, "Dict: Dublin summer noon maps to 22"),
        ("Europe/Dublin", "2025-12-15T12:00:00+00:00", 24, "Dict: Dublin winter noon maps to 24"),
    ],
)
def test_adjusted_interval_dict_boundaries(
    timezone: str,
    local_iso: str,
    expected_interval: int,
    description: str,
) -> None:
    """Test _adjusted_interval (dict-based) returns correct interval at DST boundaries."""
    dampening = _dampening(timezone)
    forecast_dict: dict[str, Any] = {PERIOD_START: dt.fromisoformat(local_iso)}
    result = dampening._adjusted_interval(forecast_dict)
    assert result == expected_interval, f"{description}: expected {expected_interval}, got {result}"


def test_hour0_dst_clamp_merges_with_hour1() -> None:
    """Test that hour 0 and hour 1 during DST both map to interval 0."""
    dampening = _dampening("Australia/Sydney")
    tz = ZoneInfo("Australia/Sydney")

    midnight_aedt = dt(2025, 11, 15, 0, 0, tzinfo=tz)
    one_am_aedt = dt(2025, 11, 15, 1, 0, tzinfo=tz)

    idx_midnight = dampening.adjusted_interval_dt(midnight_aedt)
    idx_one_am = dampening.adjusted_interval_dt(one_am_aedt)

    assert idx_midnight == 0
    assert idx_one_am == 0
    assert idx_midnight == idx_one_am, "Hour-0 and hour-1 during DST should merge to same interval"


@pytest.mark.parametrize(
    ("timezone", "date_str", "utc_offset", "is_shifted", "expected_unique"),
    [
        # Sydney AEDT (DST): 48 half-hours → 46 unique indices
        ("Australia/Sydney", "2025-11-15", "+11:00", True, 46),
        # Sydney AEST (no DST): 48 half-hours → 48 unique indices
        ("Australia/Sydney", "2025-07-15", "+10:00", False, 48),
        # Brisbane (never DST): 48 → 48 unique
        ("Australia/Brisbane", "2025-07-15", "+10:00", False, 48),
        # Dublin summer (IST, offset=1): 48 → 46 unique
        ("Europe/Dublin", "2025-07-15", "+01:00", True, 46),
        # Dublin winter (GMT, offset=0): 48 → 48 unique
        ("Europe/Dublin", "2025-12-15", "+00:00", False, 48),
    ],
)
def test_interval_range_coverage(
    timezone: str,
    date_str: str,
    utc_offset: str,
    is_shifted: bool,
    expected_unique: int,
) -> None:
    """Test that all expected interval indices are produced over a full day."""
    dampening = _dampening(timezone)
    tz = ZoneInfo(timezone)

    indices = set()
    for half_hour in range(48):
        hour = half_hour // 2
        minute = (half_hour % 2) * 30
        local_time = dt(
            int(date_str[:4]),
            int(date_str[5:7]),
            int(date_str[8:10]),
            hour,
            minute,
            tzinfo=tz,
        )
        idx = dampening.adjusted_interval_dt(local_time)
        indices.add(idx)
        assert 0 <= idx <= 47, f"Interval {idx} out of range for {local_time}"

    assert len(indices) == expected_unique, (
        f"Expected {expected_unique} unique intervals for {timezone} on {date_str}, got {len(indices)}: {sorted(indices)}"
    )

    if is_shifted:
        assert 46 not in indices, "During shifted period, interval 46 should be unreachable"
        assert 47 not in indices, "During shifted period, interval 47 should be unreachable"
    else:
        assert 46 in indices, "Without shift, interval 46 should be reachable"
        assert 47 in indices, "Without shift, interval 47 should be reachable"


@pytest.mark.parametrize(
    ("timezone", "local_iso", "expected_dst"),
    [
        ("Australia/Sydney", "2025-01-15T12:00:00+11:00", True),
        ("Australia/Sydney", "2025-07-15T12:00:00+10:00", False),
        ("Europe/Dublin", "2025-07-15T12:00:00+01:00", True),
        ("Europe/Dublin", "2025-12-15T12:00:00+00:00", False),
        ("Australia/Brisbane", "2025-07-15T12:00:00+10:00", False),
        ("Australia/Brisbane", "2025-01-15T12:00:00+10:00", False),
    ],
)
def test_dst_helper_consistency(
    timezone: str,
    local_iso: str,
    expected_dst: bool,
) -> None:
    """Test that dst() and is_interval_dst() return consistent results."""
    helper = _dt_helper(timezone)
    test_dt = dt.fromisoformat(local_iso)

    dst_result = helper.dst(test_dt)
    assert dst_result == expected_dst, f"dst() for {timezone} at {local_iso}: expected {expected_dst}, got {dst_result}"

    is_interval_result = helper.is_interval_dst({PERIOD_START: test_dt})
    assert is_interval_result == expected_dst, (
        f"is_interval_dst() for {timezone} at {local_iso}: expected {expected_dst}, got {is_interval_result}"
    )

    assert dst_result == is_interval_result


@pytest.mark.parametrize(
    ("timezone", "freeze_at"),
    [
        ("Australia/Sydney", "2025-11-15T12:00:00+11:00"),
        ("Australia/Sydney", "2025-07-15T12:00:00+10:00"),
        ("Europe/Dublin", "2025-07-15T12:00:00+01:00"),
        ("Europe/Dublin", "2025-12-15T12:00:00+00:00"),
    ],
)
def test_adjusted_interval_always_in_range(
    timezone: str,
    freeze_at: str,
) -> None:
    """Test that _adjusted_interval never returns an index outside 0-47."""
    dampening = _dampening(timezone)
    tz = ZoneInfo(timezone)
    date = dt.fromisoformat(freeze_at).date()

    for half_hour in range(48):
        hour = half_hour // 2
        minute = (half_hour % 2) * 30
        local_time = dt(date.year, date.month, date.day, hour, minute, tzinfo=tz)

        idx_dt = dampening.adjusted_interval_dt(local_time)
        assert 0 <= idx_dt <= 47, f"adjusted_interval_dt returned {idx_dt} for {local_time}"

        forecast: dict[str, Any] = {PERIOD_START: local_time}
        idx_dict = dampening._adjusted_interval(forecast)
        assert 0 <= idx_dict <= 47, f"_adjusted_interval returned {idx_dict} for {local_time}"

        assert idx_dt == idx_dict, f"Methods disagree at {local_time}: dt={idx_dt}, dict={idx_dict}"


@pytest.mark.parametrize(
    ("timezone", "freeze_date", "expected_transition", "expected_msg"),
    [
        # Australia/Sydney: standard→summer on first Sunday of October
        # 2025-10-05 is the day clocks spring forward (lose an hour)
        ("Australia/Sydney", "2025-10-04T12:00:00+10:00", True, "standard to summer"),
        # Australia/Sydney: summer→standard on first Sunday of April
        # 2025-04-06 is the day clocks fall back (gain an hour)
        ("Australia/Sydney", "2025-04-05T12:00:00+11:00", True, "summer to standard"),
        # Europe/Dublin: standard→summer on last Sunday of March
        # 2025-03-30 is the day clocks spring forward
        ("Europe/Dublin", "2025-03-29T12:00:00+00:00", True, "winter to summer"),
        # Europe/Dublin: summer→standard on last Sunday of October
        # 2025-10-26 is the day clocks fall back
        ("Europe/Dublin", "2025-10-25T12:00:00+01:00", True, "summer to winter"),
        # No transition: mid-summer Sydney
        ("Australia/Sydney", "2025-01-15T12:00:00+11:00", False, ""),
    ],
)
async def test_transition_detection(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
    timezone: str,
    freeze_date: str,
    expected_transition: bool,
    expected_msg: str,
) -> None:
    """Test that DST transitions are detected in the interval assessment."""

    try:
        freezer.move_to(freeze_date)
        await async_init_integration(hass, DEFAULT_INPUT1, timezone=timezone)

        if expected_transition:
            assert f"Transitioning from {expected_msg} time" in caplog.text, f"Expected transition message for {timezone} on {freeze_date}"
        else:
            assert "Transitioning from" not in caplog.text, f"Unexpected transition detected for {timezone} on {freeze_date}"

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


@pytest.mark.parametrize(
    ("timezone", "freeze_at", "description"),
    [
        # Sydney on the spring-forward day itself
        (
            "Australia/Sydney",
            "2025-10-05T08:00:00+11:00",
            "Sydney spring-forward day",
        ),
        # Dublin on the spring-forward day itself
        (
            "Europe/Dublin",
            "2025-03-30T10:00:00+01:00",
            "Dublin spring-forward day",
        ),
        # Sydney on the fall-back day itself
        (
            "Australia/Sydney",
            "2025-04-06T08:00:00+10:00",
            "Sydney fall-back day",
        ),
    ],
)
async def test_updater_scheduling_across_dst(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
    timezone: str,
    freeze_at: str,
    description: str,
) -> None:
    """Test that auto-update scheduling produces valid intervals on DST transition days."""

    try:
        freezer.move_to(freeze_at)

        options = copy.deepcopy(DEFAULT_INPUT1)
        options[AUTO_UPDATE] = 1  # DAYLIGHT mode
        entry = await async_init_integration(hass, options, timezone=timezone)
        coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator

        updater = coordinator._updater  # pyright: ignore[reportPrivateUsage]
        intervals = list(updater._intervals)  # pyright: ignore[reportPrivateUsage]

        for interval in intervals:
            assert interval.tzinfo is not None, f"Interval {interval} is not tz-aware"
        assert updater.divisions > 0, f"Auto-update divisions should be positive for {description}"
        assert "Sun rise / set today" in caplog.text, f"Missing sunrise/sunset log for {description}"

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_apply_forward_on_spring_forward_day(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test apply_forward on a spring-forward (46 interval) day doesn't error."""

    try:
        # Sydney clocks spring forward on 2025-10-05 at 02:00 AEST → 03:00 AEDT
        # Initialize a day before and run through
        freezer.move_to("2025-10-04T14:00:00+10:00")

        options = copy.deepcopy(DEFAULT_INPUT2)
        options[AUTO_UPDATE] = 1
        options[GET_ACTUALS] = True
        options[USE_ACTUALS] = 0
        options[AUTO_DAMPEN] = True
        options[EXCLUDE_SITES] = ["3333-3333-3333-3333"]
        options[GENERATION_ENTITIES] = [
            "sensor.solar_export_sensor_1111_1111_1111_1111",
            "sensor.solar_export_sensor_2222_2222_2222_2222",
        ]
        options[SITE_EXPORT_ENTITY] = "sensor.site_export_sensor"
        options[SITE_EXPORT_LIMIT] = 5.0

        config_dir = f"{hass.config.config_dir}/{CONFIG_DISCRETE_NAME}" if CONFIG_FOLDER_DISCRETE else hass.config.config_dir
        if CONFIG_FOLDER_DISCRETE:
            Path(config_dir).mkdir(parents=False, exist_ok=True)
        Path(f"{config_dir}/solcast-advanced.json").write_text(json.dumps({"entity_logging": True}), encoding="utf-8")

        entry = await async_init_integration(hass, options, timezone="Australia/Sydney", extra_sensors=ExtraSensors.YES_WATT_HOUR)
        solcast = entry.runtime_data.coordinator.solcast

        # Should not raise any exceptions.
        caplog.clear()
        await solcast.dampening.apply_forward()
        assert "Applying future dampening" in caplog.text
        assert "Exception" not in caplog.text

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_apply_forward_on_fall_back_day(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test apply_forward on a fall-back (50 interval) day doesn't error."""

    try:
        # Sydney clocks fall back on 2025-04-06 at 03:00 AEDT → 02:00 AEST
        freezer.move_to("2025-04-05T14:00:00+11:00")

        options = copy.deepcopy(DEFAULT_INPUT2)
        options[AUTO_UPDATE] = 1
        options[GET_ACTUALS] = True
        options[USE_ACTUALS] = 0
        options[AUTO_DAMPEN] = True
        options[EXCLUDE_SITES] = ["3333-3333-3333-3333"]
        options[GENERATION_ENTITIES] = [
            "sensor.solar_export_sensor_1111_1111_1111_1111",
            "sensor.solar_export_sensor_2222_2222_2222_2222",
        ]
        options[SITE_EXPORT_ENTITY] = "sensor.site_export_sensor"
        options[SITE_EXPORT_LIMIT] = 5.0

        config_dir = f"{hass.config.config_dir}/{CONFIG_DISCRETE_NAME}" if CONFIG_FOLDER_DISCRETE else hass.config.config_dir
        if CONFIG_FOLDER_DISCRETE:
            Path(config_dir).mkdir(parents=False, exist_ok=True)
        Path(f"{config_dir}/solcast-advanced.json").write_text(json.dumps({"entity_logging": True}), encoding="utf-8")

        entry = await async_init_integration(hass, options, timezone="Australia/Sydney", extra_sensors=ExtraSensors.YES_WATT_HOUR)
        solcast = entry.runtime_data.coordinator.solcast

        caplog.clear()
        await solcast.dampening.apply_forward()
        assert "Applying future dampening" in caplog.text
        assert "Exception" not in caplog.text

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_updater_details_empty_intervals_on_dst_day(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test get_auto_update_details with empty intervals on a DST transition day."""

    try:
        freezer.move_to("2025-10-05T22:00:00+11:00")  # Late evening AEDT

        options = copy.deepcopy(DEFAULT_INPUT1)
        options[AUTO_UPDATE] = 1  # DAYLIGHT mode
        entry = await async_init_integration(hass, options, timezone="Australia/Sydney")
        coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator

        updater = coordinator._updater  # pyright: ignore[reportPrivateUsage]

        updater._intervals = []  # pyright: ignore[reportPrivateUsage]

        # Should not raise IndexError
        details = updater.get_auto_update_details()
        assert details["next_auto_update"] is None, "Expected next_auto_update to be None"
        assert "auto_update_divisions" in details
        assert details["auto_update_queue"] == []

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"
