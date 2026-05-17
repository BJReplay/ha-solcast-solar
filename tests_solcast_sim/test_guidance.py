"""Tests for Solcast Sim guidance generation."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from custom_components.solcast_sim import (  # pyright: ignore[reportMissingImports]
    guidance,
)
from custom_components.solcast_sim.sim_core import (  # pyright: ignore[reportMissingImports]
    SimulationProfile,
)
import pytest


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
