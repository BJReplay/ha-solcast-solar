"""Tests for Solcast Sim guidance generation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from custom_components.solcast_sim import (  # pyright: ignore[reportMissingImports]
    guidance,
)
from custom_components.solcast_sim.guidance import (  # pyright: ignore[reportMissingImports]
    PV_TODAY_ENERGY_UNIQUE_ID,
    GuidanceCloudWindowMode,
    _apply_estimated_actuals_jitter,
    _cloud_windows_for_day,
    _compute_actuals_jitter,
    _estimated_actuals_from_recorder,
    _period_cloudiness,
    build_storage_path,
    load_climate_cache,
    save_climate_cache,
    write_guidance_payload_to_file,
)
from custom_components.solcast_sim.sim_core import (  # pyright: ignore[reportMissingImports]
    SimulationProfile,
)
import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er


def _make_profile(shade_opacity: float = 0.0) -> SimulationProfile:
    """Return a SimulationProfile suitable for guidance tests."""
    return SimulationProfile(
        season="auto",
        latitude=-33.0,
        longitude=151.0,
        cloudiness_bias=0.0,
        cloud_variability=0.7,
        estimated_actuals_uncertainty_pct=2.2,
        shade_height_m=12.0,
        shade_width_m=8.0,
        shade_distance_m=15.0,
        shade_azimuth_deg=0.0,
        shade_opacity=shade_opacity,
        astral_location=SimpleNamespace(),
        astral_elevation=SimpleNamespace(),
        random_seed="seed",
    )


def test_build_guidance_payload_includes_seven_day_lookback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guidance includes seven days of lookback for estimated actuals."""

    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 5, 10, 12, 0, tzinfo=tz or UTC)

    monkeypatch.setattr(guidance, "datetime", FakeDateTime)

    profile = _make_profile()
    payload = guidance.build_guidance_payload(profile, ZoneInfo("UTC"), days=2)

    assert payload["estimated_actuals_uncertainty_pct"] == 2.2
    assert "2026-05-03" in payload["days"]
    assert "2026-05-04" in payload["days"]
    assert "2026-05-05" in payload["days"]
    assert "2026-05-06" in payload["days"]
    assert "2026-05-07" in payload["days"]
    assert "2026-05-08" in payload["days"]
    assert "2026-05-09" in payload["days"]
    assert "2026-05-10" in payload["days"]
    assert "2026-05-11" in payload["days"]
    assert "2026-05-02" not in payload["days"]
    assert "2026-05-01" not in payload["days"]


def test_build_guidance_payload_intervals_ignore_shade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Historical estimated-actuals guidance should not reflect local shade."""

    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 5, 10, 12, 0, tzinfo=tz or UTC)

    monkeypatch.setattr(guidance, "datetime", FakeDateTime)

    no_shade = _make_profile(shade_opacity=0.0)
    full_shade = _make_profile(shade_opacity=1.0)

    no_shade_payload = guidance.build_guidance_payload(no_shade, ZoneInfo("UTC"), days=2)
    full_shade_payload = guidance.build_guidance_payload(full_shade, ZoneInfo("UTC"), days=2)

    assert no_shade_payload["days"]["2026-05-09"]["intervals"] == full_shade_payload["days"]["2026-05-09"]["intervals"]


def test_period_cloudiness_averages_window() -> None:
    """_period_cloudiness returns 1-mean for the specified hour window."""
    # 12 bins per hour: hours 6-8 = indices 72..95
    factors = [1.0] * 144  # 12 hours worth
    cloudiness = _period_cloudiness(factors, 0.5, start_hour=0.0, end_hour=12.0)
    assert cloudiness == pytest.approx(0.0, abs=1e-9)


def test_period_cloudiness_empty_window_returns_default() -> None:
    """When the window is empty, the default_cloudiness is returned."""
    result = _period_cloudiness([], 0.6, start_hour=6.0, end_hour=6.0)
    assert result == pytest.approx(0.6)


def test_period_cloudiness_clamps_to_zero_one() -> None:
    """Result is clamped to [0, 1]."""
    factors = [2.0] * 144  # impossible high value
    result = _period_cloudiness(factors, 0.5, start_hour=0.0, end_hour=12.0)
    assert 0.0 <= result <= 1.0


def test_cloud_windows_clock_mode() -> None:
    """CLOCK mode returns fixed hour windows."""
    morning, afternoon = _cloud_windows_for_day(GuidanceCloudWindowMode.CLOCK, 21600.0, 72000.0)
    assert morning == (6.0, 12.0)
    assert afternoon == (12.0, 18.0)


def test_cloud_windows_daylight_mode() -> None:
    """DAYLIGHT mode splits on midday between sunrise and sunset."""
    sunrise_s = 6.0 * 3600.0
    sunset_s = 18.0 * 3600.0
    morning, afternoon = _cloud_windows_for_day(GuidanceCloudWindowMode.DAYLIGHT, sunrise_s, sunset_s)
    split = (6.0 + 18.0) / 2.0
    assert morning == (6.0, split)
    assert afternoon == (split, 18.0)


def test_save_and_load_climate_cache_roundtrip() -> None:
    """Saving and loading climate cache returns matching months."""
    months = [{"mean": 0.4 + i * 0.01, "std": 0.1} for i in range(12)]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cache.json"
        save_climate_cache(path, -33.0, 151.0, months)
        loaded = load_climate_cache(path, -33.0, 151.0)
    assert loaded is not None
    assert len(loaded) == 12
    assert loaded[0]["mean"] == pytest.approx(0.4, abs=0.001)


def test_load_climate_cache_returns_none_for_missing_file() -> None:
    """load_climate_cache returns None when file does not exist."""
    result = load_climate_cache(Path("/nonexistent/path/cache.json"), -33.0, 151.0)
    assert result is None


def test_load_climate_cache_returns_none_for_coordinate_mismatch() -> None:
    """load_climate_cache returns None when coordinates do not match."""
    months = [{"mean": 0.4, "std": 0.1}] * 12
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cache.json"
        save_climate_cache(path, -33.0, 151.0, months)
        loaded = load_climate_cache(path, 51.5, -0.1)
    assert loaded is None


def test_load_climate_cache_returns_none_for_corrupt_json() -> None:
    """load_climate_cache returns None for unreadable JSON."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cache.json"
        path.write_text("not json", encoding="utf-8")
        result = load_climate_cache(path, -33.0, 151.0)
    assert result is None


def test_compute_actuals_jitter_zero_uncertainty() -> None:
    """Zero uncertainty always produces zero jitter."""
    assert _compute_actuals_jitter("2026-05-10", 0, 0.0) == pytest.approx(0.0)


def test_compute_actuals_jitter_is_deterministic() -> None:
    """Same inputs always produce the same jitter."""
    j1 = _compute_actuals_jitter("2026-05-10", 3, 15.0)
    j2 = _compute_actuals_jitter("2026-05-10", 3, 15.0)
    assert j1 == j2


def test_compute_actuals_jitter_nonzero_with_uncertainty() -> None:
    """Positive uncertainty can produce nonzero jitter."""
    found_nonzero = any(_compute_actuals_jitter("2026-05-10", slot, 20.0) != 0.0 for slot in range(48))
    assert found_nonzero


def test_apply_estimated_actuals_jitter_zero_value() -> None:
    """Zero base value is never changed by jitter."""
    assert _apply_estimated_actuals_jitter(0.0, "2026-05-10", 0, 15.0) == pytest.approx(0.0)


def test_apply_estimated_actuals_jitter_scales_value() -> None:
    """Jitter changes a nonzero value by a bounded fraction."""
    original = 0.5
    jittered = _apply_estimated_actuals_jitter(original, "2026-05-10", 1, 15.0)
    # Result must still be in [0, BASE_FORECAST_SCALE]
    assert 0.0 <= jittered <= 0.95


def test_estimated_actuals_from_recorder_handles_none_values() -> None:
    """None recorder values produce 0.0 in output."""
    result = _estimated_actuals_from_recorder("2026-05-10", 0.0, [None, 0.5, None])
    assert result[0] == pytest.approx(0.0)


def test_estimated_actuals_from_recorder_applies_jitter() -> None:
    """Nonzero slots have jitter applied (may differ from original value)."""
    result = _estimated_actuals_from_recorder("2026-05-10", 20.0, [0.5] * 5)
    assert len(result) == 5
    assert all(0.0 <= v <= 0.95 for v in result)


def test_write_guidance_payload_creates_json_file() -> None:
    """write_guidance_payload_to_file writes parseable JSON."""
    payload = {"key": "value", "number": 42}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "guidance.json"
        write_guidance_payload_to_file(path, payload)
        assert path.exists()
        loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == payload


def test_write_guidance_payload_creates_parent_dirs() -> None:
    """write_guidance_payload_to_file creates intermediate directories."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sub" / "dir" / "guidance.json"
        write_guidance_payload_to_file(path, {"x": 1})
        assert path.exists()


def test_build_storage_path() -> None:
    """build_storage_path returns config_dir/solcast_sim/filename."""
    result = build_storage_path(Path("/some/config"), "guidance.json")
    assert result == Path("/some/config/solcast_sim/guidance.json")


def test_load_climate_cache_returns_none_when_expired() -> None:
    """load_climate_cache returns None when cache age exceeds 30 days."""
    old_time = datetime.now().astimezone() - timedelta(days=400)
    data = {
        "latitude": -33.0,
        "longitude": 151.0,
        "fetched_at": old_time.isoformat(),
        "months": [{"mean": 0.4, "std": 0.1}] * 12,
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cache.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        result = load_climate_cache(path, -33.0, 151.0)
    assert result is None


def test_load_climate_cache_returns_none_for_wrong_month_count() -> None:
    """load_climate_cache returns None when months list length != 12."""
    recent = datetime.now().astimezone()
    data = {
        "latitude": -33.0,
        "longitude": 151.0,
        "fetched_at": recent.isoformat(),
        "months": [{"mean": 0.4, "std": 0.1}] * 11,
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cache.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        result = load_climate_cache(path, -33.0, 151.0)
    assert result is None


def test_build_guidance_payload_high_variability_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    """High-variability locale uses its own season-gain map."""

    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 7, 1, 12, 0, tzinfo=tz or UTC)

    monkeypatch.setattr(guidance, "datetime", FakeDateTime)
    profile = SimulationProfile(
        season="auto",
        latitude=52.0,
        longitude=-1.0,
        cloudiness_bias=0.0,
        cloud_variability=0.5,
        estimated_actuals_uncertainty_pct=0.0,
        shade_height_m=0.0,
        shade_width_m=0.0,
        shade_distance_m=0.0,
        shade_azimuth_deg=0.0,
        shade_opacity=0.0,
        astral_location=SimpleNamespace(),
        astral_elevation=SimpleNamespace(),
        random_seed="seed",
    )
    payload = guidance.build_guidance_payload(profile, ZoneInfo("UTC"), days=1)
    # High-variability summer gain is 0.88
    assert payload["days"]["2026-07-01"]["season_gain"] == pytest.approx(0.88)


async def test_async_fetch_climate_normals_exception(hass: HomeAssistant) -> None:
    """Network exception returns None."""
    with patch("custom_components.solcast_sim.guidance.async_get_clientsession") as mock_cs:
        mock_cs.return_value.get.side_effect = Exception("network error")
        result = await guidance.async_fetch_climate_normals(hass, -33.0, 151.0)
    assert result is None


async def test_async_fetch_climate_normals_non_200(hass: HomeAssistant) -> None:
    """Non-200 HTTP response returns None."""
    mock_resp = MagicMock()
    mock_resp.status = 503
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    with patch("custom_components.solcast_sim.guidance.async_get_clientsession") as mock_cs:
        mock_cs.return_value.get.return_value = mock_cm
        result = await guidance.async_fetch_climate_normals(hass, -33.0, 151.0)
    assert result is None


async def test_async_fetch_climate_normals_insufficient_data(hass: HomeAssistant) -> None:
    """Returns None when monthly samples are below threshold."""
    dates = [f"2020-{m:02d}-01" for m in range(1, 13)]
    data = {"daily": {"time": dates, "cloud_cover_mean": [50.0] * 12}}
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=data)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    with patch("custom_components.solcast_sim.guidance.async_get_clientsession") as mock_cs:
        mock_cs.return_value.get.return_value = mock_cm
        result = await guidance.async_fetch_climate_normals(hass, -33.0, 151.0)
    assert result is None


async def test_async_fetch_climate_normals_success(hass: HomeAssistant) -> None:
    """Returns 12-month stats when data is sufficient."""
    dates = []
    values = []
    for year in range(2020, 2025):
        for month in range(1, 13):
            for day in range(1, 4):
                dates.append(f"{year}-{month:02d}-{day:02d}")
                values.append(50.0)
    data = {"daily": {"time": dates, "cloud_cover_mean": values}}
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=data)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    with patch("custom_components.solcast_sim.guidance.async_get_clientsession") as mock_cs:
        mock_cs.return_value.get.return_value = mock_cm
        result = await guidance.async_fetch_climate_normals(hass, -33.0, 151.0)
    assert result is not None
    assert len(result) == 12
    assert all("mean" in m and "std" in m for m in result)


async def test_async_recorder_historic_zero_capacity(hass: HomeAssistant) -> None:
    """Returns empty dict when capacity is zero."""
    result = await guidance._async_recorder_historic_estimated_actuals(hass, ZoneInfo("UTC"), 0.0)
    assert result == {}


async def test_async_recorder_historic_no_entity(hass: HomeAssistant) -> None:
    """Returns empty dict when entity is not registered."""
    hass.config.components.add("recorder")
    result = await guidance._async_recorder_historic_estimated_actuals(hass, ZoneInfo("UTC"), 5.0)
    assert result == {}


async def test_async_recorder_historic_no_rows(hass: HomeAssistant) -> None:
    """Returns empty dict when history has no rows."""
    hass.config.components.add("recorder")
    registry = er.async_get(hass)
    registry.async_get_or_create("sensor", "solcast_sim", PV_TODAY_ENERGY_UNIQUE_ID)
    mock_instance = MagicMock()
    mock_instance.async_add_executor_job = AsyncMock(return_value={})
    with patch("custom_components.solcast_sim.guidance.get_instance", return_value=mock_instance):
        result = await guidance._async_recorder_historic_estimated_actuals(hass, ZoneInfo("UTC"), 5.0)
    assert result == {}


async def test_async_write_guidance_file(hass: HomeAssistant) -> None:
    """Writes guidance JSON to config storage."""
    profile = SimulationProfile(
        season="auto",
        latitude=-33.0,
        longitude=151.0,
        cloudiness_bias=0.0,
        cloud_variability=0.5,
        estimated_actuals_uncertainty_pct=0.0,
        shade_height_m=0.0,
        shade_width_m=0.0,
        shade_distance_m=0.0,
        shade_azimuth_deg=0.0,
        shade_opacity=0.0,
        astral_location=SimpleNamespace(),
        astral_elevation=SimpleNamespace(),
        random_seed="seed",
    )
    with patch(
        "custom_components.solcast_sim.guidance._async_recorder_historic_estimated_actuals",
        AsyncMock(return_value={}),
    ):
        await guidance.async_write_guidance_file(hass, profile, ZoneInfo("UTC"))
    path = guidance.build_storage_path(Path(hass.config.config_dir), guidance.GUIDANCE_FILENAME)
    assert path.exists()


async def test_async_recorder_historic_rows_normal_and_reset(hass: HomeAssistant) -> None:
    """Row loop builds slot fractions from normal delta and daily-reset rows."""
    hass.config.components.add("recorder")
    registry = er.async_get(hass)
    registry.async_get_or_create("sensor", "solcast_sim", PV_TODAY_ENERGY_UNIQUE_ID)
    entity_id = registry.async_get_entity_id("sensor", "solcast_sim", PV_TODAY_ENERGY_UNIQUE_ID)
    tz = ZoneInfo("UTC")
    t0 = datetime(2026, 5, 18, 12, 0, tzinfo=UTC)
    rows = [
        SimpleNamespace(state="0.5", last_updated=t0),  # anchor
        SimpleNamespace(state="1.5", last_updated=t0 + timedelta(minutes=30)),  # +1.0 kWh -> slot 25
        SimpleNamespace(state="0.3", last_updated=t0 + timedelta(hours=1)),  # reset -> 0.3 kWh -> slot 26
    ]
    mock_instance = MagicMock()
    mock_instance.async_add_executor_job = AsyncMock(return_value={entity_id: rows})
    with patch("custom_components.solcast_sim.guidance.get_instance", return_value=mock_instance):
        result = await guidance._async_recorder_historic_estimated_actuals(hass, tz, 5.0)
    slots = result["2026-05-18"]
    assert len(slots) == 48
    assert slots[0] is None
    assert slots[25] == pytest.approx(0.4)
    assert slots[26] == pytest.approx(0.12)


async def test_async_recorder_historic_rows_edge_cases(hass: HomeAssistant) -> None:
    """Row loop skips bad state, None timestamp, zero delta; accumulates same-slot readings."""
    hass.config.components.add("recorder")
    registry = er.async_get(hass)
    registry.async_get_or_create("sensor", "solcast_sim", PV_TODAY_ENERGY_UNIQUE_ID)
    entity_id = registry.async_get_entity_id("sensor", "solcast_sim", PV_TODAY_ENERGY_UNIQUE_ID)
    tz = ZoneInfo("UTC")
    t0 = datetime(2026, 5, 18, 12, 0, tzinfo=UTC)
    rows = [
        SimpleNamespace(state="unavailable", last_updated=t0),  # ValueError -> skip
        SimpleNamespace(state="1.0", last_updated=None),  # None time -> skip
        SimpleNamespace(state="1.0", last_updated=t0),  # anchor
        SimpleNamespace(state="1.0", last_updated=t0 + timedelta(minutes=30)),  # delta=0 -> skip
        SimpleNamespace(state="2.0", last_updated=t0 + timedelta(hours=1)),  # delta=1.0 -> slot 26
        SimpleNamespace(state="3.5", last_updated=t0 + timedelta(hours=1, minutes=14)),  # delta=1.5 -> slot 26 accumulate
    ]
    mock_instance = MagicMock()
    mock_instance.async_add_executor_job = AsyncMock(return_value={entity_id: rows})
    with patch("custom_components.solcast_sim.guidance.get_instance", return_value=mock_instance):
        result = await guidance._async_recorder_historic_estimated_actuals(hass, tz, 5.0)
    # accumulated 2.5 kWh -> 2.5 * 2 / 5.0 = 1.0, clipped to BASE_FORECAST_SCALE (0.9)
    assert result["2026-05-18"][26] == pytest.approx(0.9)


async def test_async_recorder_historic_rows_with_shade_profile(hass: HomeAssistant) -> None:
    """With a profile, shade un-attenuation divides delta by the mocked shade factor."""
    hass.config.components.add("recorder")
    registry = er.async_get(hass)
    registry.async_get_or_create("sensor", "solcast_sim", PV_TODAY_ENERGY_UNIQUE_ID)
    entity_id = registry.async_get_entity_id("sensor", "solcast_sim", PV_TODAY_ENERGY_UNIQUE_ID)
    tz = ZoneInfo("UTC")
    t0 = datetime(2026, 5, 18, 12, 0, tzinfo=UTC)
    rows = [
        SimpleNamespace(state="0.5", last_updated=t0),
        SimpleNamespace(state="1.5", last_updated=t0 + timedelta(minutes=30)),  # delta=1.0 kWh
    ]
    mock_instance = MagicMock()
    mock_instance.async_add_executor_job = AsyncMock(return_value={entity_id: rows})
    with (
        patch("custom_components.solcast_sim.guidance.get_instance", return_value=mock_instance),
        patch("custom_components.solcast_sim.guidance.shade_attenuation_factor", return_value=0.5),
    ):
        result = await guidance._async_recorder_historic_estimated_actuals(hass, tz, 5.0, profile=_make_profile())
    # shade_factor=0.5 -> delta_kwh = 1.0 / 0.5 = 2.0 -> fraction = 2.0 * 2 / 5.0 = 0.8
    assert result["2026-05-18"][25] == pytest.approx(0.8)


async def test_async_fetch_climate_normals_skips_none_values(hass: HomeAssistant) -> None:
    """None entries in cloud_cover_mean are silently skipped."""
    dates = []
    values: list[float | None] = []
    for year in range(2020, 2025):
        for month in range(1, 13):
            for day in range(1, 4):
                dates.append(f"{year}-{month:02d}-{day:02d}")
                values.append(None if day == 1 else 50.0)
    data = {"daily": {"time": dates, "cloud_cover_mean": values}}
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=data)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    with patch("custom_components.solcast_sim.guidance.async_get_clientsession") as mock_cs:
        mock_cs.return_value.get.return_value = mock_cm
        result = await guidance.async_fetch_climate_normals(hass, -33.0, 151.0)
    assert result is not None
    assert len(result) == 12
