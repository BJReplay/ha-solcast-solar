"""Tests for canopy edge-density behaviour and cloud transit events in Solcast Sim core."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from custom_components.solcast_sim import (  # pyright: ignore[reportMissingImports]
    sim_core,
)  # pyright: ignore[reportMissingImports]
from custom_components.solcast_sim.sim_core import (  # pyright: ignore[reportMissingImports]
    SimulationProfile,
    _apply_cloud_transits,
    _burnoff_probability_for_season,
    canopy_density_ratio,
    normalise_shade_density_profile,
    shade_attenuation_factor,
)
import pytest


def _build_profile(density_profile: tuple[float, float, float]) -> SimulationProfile:
    """Build a minimal profile for canopy attenuation tests."""
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
        shade_opacity=1.0,
        astral_location=SimpleNamespace(),
        astral_elevation=SimpleNamespace(),
        random_seed="seed",
        shade_density_profile=density_profile,
    )


def test_normalise_shade_density_profile_accepts_ascending_values() -> None:
    """Accept a valid canopy edge-density profile."""
    assert normalise_shade_density_profile("0.3, 0.8, 1.0") == "0.3, 0.8, 1.0"


@pytest.mark.parametrize(
    "value",
    ["0.7,0.6,0.9", "-0.1,0.2,0.3", "0.1,0.2", "a,b,c"],
)
def test_normalise_shade_density_profile_rejects_invalid_values(value: str) -> None:
    """Reject malformed canopy edge-density profiles."""
    with pytest.raises(ValueError):
        normalise_shade_density_profile(value)


def test_canopy_density_ratio_increases_with_depth() -> None:
    """Edge-to-core density should increase as path depth increases."""
    profile = (0.3, 0.8, 1.0)
    assert canopy_density_ratio(0.10, profile) < canopy_density_ratio(0.79, profile)
    assert canopy_density_ratio(0.80, profile) == pytest.approx(1.0)
    assert canopy_density_ratio(0.98, profile) == pytest.approx(1.0)


def test_shade_attenuation_factor_responds_to_density_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """Denser canopy profiles should block more power for the same solar geometry."""
    monkeypatch.setattr(sim_core, "solar_position_deg", lambda _now, _loc, _elev: (3.0, 0.0))

    now_local = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
    fluffy_edges = _build_profile((0.20, 0.45, 0.80))
    dense_edges = _build_profile((0.60, 0.85, 1.00))

    fluffy_factor = shade_attenuation_factor(now_local, fluffy_edges)
    dense_factor = shade_attenuation_factor(now_local, dense_edges)

    assert dense_factor < fluffy_factor


def _flat_profile(variability: float, seed: str = "testseed") -> SimulationProfile:
    """Build a minimal SimulationProfile for transit overlay tests."""
    return SimulationProfile(
        season="auto",
        latitude=-33.0,
        longitude=151.0,
        cloudiness_bias=0.0,
        cloud_variability=variability,
        estimated_actuals_uncertainty_pct=0.0,
        shade_height_m=0.0,
        shade_width_m=0.0,
        shade_distance_m=0.0,
        shade_azimuth_deg=0.0,
        shade_opacity=0.0,
        astral_location=SimpleNamespace(),
        astral_elevation=SimpleNamespace(),
        random_seed=seed,
        shade_density_profile=(0.3, 0.8, 1.0),
    )


def _make_midday_smooth(bins: int = 288) -> list[float]:
    """Return a uniform 0.55 attenuation profile (mixed-cloud midday conditions)."""
    return [0.55] * bins


def test_cloud_transits_disabled_at_zero_variability() -> None:
    """Transit overlay must be a no-op when cloud_variability is zero."""
    profile = _flat_profile(variability=0.0)
    day_seed = "test|2026-05-10|seed"
    smoothed = _make_midday_smooth()
    result = _apply_cloud_transits(smoothed, profile, 0.0, day_seed, len(smoothed))
    assert result == smoothed


def test_cloud_transits_produce_dips_at_high_variability() -> None:
    """High variability should cause at least one deep dip in a midday mixed-cloud profile."""
    profile = _flat_profile(variability=2.0, seed="transit_test")
    day_seed = "transit_test|2026-05-10|-33.0000|151.0000|summer"
    smoothed = _make_midday_smooth()
    result = _apply_cloud_transits(smoothed, profile, 0.0, day_seed, len(smoothed))

    # With max variability and mixed-cloud conditions there must be at least one transit dip.
    min_val = min(result)
    assert min_val < 0.40, f"Expected at least one deep transit dip, got minimum {min_val:.3f}"


def test_cloud_transits_produce_lensing_spikes() -> None:
    """Transit overlay should produce values above the flat background (lensing boosts)."""
    profile = _flat_profile(variability=2.0, seed="lensing_test")
    day_seed = "lensing_test|2026-05-10|-33.0000|151.0000|summer"
    smoothed = _make_midday_smooth()
    result = _apply_cloud_transits(smoothed, profile, 0.0, day_seed, len(smoothed))

    max_val = max(result)
    assert max_val > 0.55, f"Expected at least one lensing spike above 0.55, got maximum {max_val:.3f}"


def test_cloud_transits_are_deterministic() -> None:
    """Same seed and profile must always produce identical transit output."""
    profile = _flat_profile(variability=1.5, seed="determ_test")
    day_seed = "determ_test|2026-05-10|-33.0000|151.0000|summer"
    smoothed = _make_midday_smooth()
    result_a = _apply_cloud_transits(smoothed, profile, 0.0, day_seed, len(smoothed))
    result_b = _apply_cloud_transits(smoothed, profile, 0.0, day_seed, len(smoothed))
    assert result_a == result_b


def test_cloud_transits_different_seeds_produce_different_output() -> None:
    """Different random seeds must produce meaningfully different transit patterns."""
    smoothed = _make_midday_smooth()
    bins = len(smoothed)
    day_a = "seed_a|2026-05-10|-33.0000|151.0000|summer"
    day_b = "seed_b|2026-05-10|-33.0000|151.0000|summer"
    profile = _flat_profile(variability=1.5, seed="seed_a")

    result_a = _apply_cloud_transits(smoothed, profile, 0.0, day_a, bins)
    result_b = _apply_cloud_transits(smoothed, _flat_profile(variability=1.5, seed="seed_b"), 0.0, day_b, bins)
    assert result_a != result_b


def test_cloud_transits_on_clear_day_very_rare() -> None:
    """Near-zero cloud fraction (clear sky) should rarely trigger transits."""
    profile = _flat_profile(variability=2.0, seed="clear_test")
    day_seed = "clear_test|2026-05-10|-33.0000|151.0000|summer"
    # Simulate a very clear day: attenuation 1.0 everywhere.
    smoothed = [1.0] * 288
    result = _apply_cloud_transits(smoothed, profile, 0.0, day_seed, len(smoothed))
    # The mixed_weight should be low for background_cloud ≈ 0, so very few dips.
    dipped_bins = sum(1 for v in result if v < 0.5)
    assert dipped_bins <= 5, f"Expected very few dips on a clear day, got {dipped_bins}"


def test_cloud_transits_respect_variability_scaling() -> None:
    """Higher variability should produce more or deeper transits than lower variability."""
    day_seed = "scale_test|2026-05-10|-33.0000|151.0000|summer"
    smoothed = _make_midday_smooth()

    low_profile = _flat_profile(variability=0.3, seed="scale_test")
    high_profile = _flat_profile(variability=2.0, seed="scale_test")

    result_low = _apply_cloud_transits(smoothed, low_profile, 0.0, day_seed, len(smoothed))
    result_high = _apply_cloud_transits(smoothed, high_profile, 0.0, day_seed, len(smoothed))

    dips_low = sum(1 for v in result_low if v < 0.30)
    dips_high = sum(1 for v in result_high if v < 0.30)
    assert dips_high >= dips_low, "Higher variability must not produce fewer deep dips than lower variability"


def test_burnoff_probability_keeps_summer_unchanged() -> None:
    """Summer burn-off probability should remain unchanged after season split."""
    assert _burnoff_probability_for_season("summer") == pytest.approx(0.35)
    assert _burnoff_probability_for_season("winter") < _burnoff_probability_for_season("autumn")
