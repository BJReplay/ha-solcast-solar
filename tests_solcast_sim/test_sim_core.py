"""Tests for canopy edge-density behaviour and cloud transit events in Solcast Sim core."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from custom_components.solcast_sim import (  # pyright: ignore[reportMissingImports]
    sim_core,
)  # pyright: ignore[reportMissingImports]
from custom_components.solcast_sim.sim_core import (  # pyright: ignore[reportMissingImports]
    API_KEY_SITES,
    SimulationProfile,
    SolcastSimBatteryModel,
    _apply_cloud_transits,
    _burnoff_probability_for_season,
    _interpolate_piecewise,
    _intraday_cloud_bias,
    _spell_targets_for_season,
    _spell_thresholds_for_season,
    base_cloudiness_for_day,
    canopy_density_ratio,
    effective_season_day,
    normalise_shade_density_profile,
    parse_shade_azimuth_to_compass,
    season_span_for_date,
    season_starts_for_year,
    seasonal_blend_weights,
    shade_attenuation_factor,
    solar_position_deg,
    solcast_azimuth_to_compass_deg,
    time_str_to_seconds,
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


def test_time_str_to_seconds_hh_mm() -> None:
    """HH:MM format is parsed correctly."""
    assert time_str_to_seconds("11:00") == 39600


def test_time_str_to_seconds_hh_mm_ss() -> None:
    """HH:MM:SS format adds the seconds component."""
    assert time_str_to_seconds("11:00:30") == 39630


def test_season_starts_northern_hemisphere() -> None:
    """Northern hemisphere spring starts in March."""
    starts = season_starts_for_year(2026, latitude=45.0)
    assert starts["spring"] == date(2026, 3, 1)
    assert starts["summer"] == date(2026, 6, 1)


def test_season_starts_southern_hemisphere() -> None:
    """Southern hemisphere seasons are flipped: autumn in March, summer in December."""
    starts = season_starts_for_year(2026, latitude=-33.0)
    assert starts["autumn"] == date(2026, 3, 1)
    assert starts["winter"] == date(2026, 6, 1)
    assert starts["spring"] == date(2026, 9, 1)
    assert starts["summer"] == date(2026, 12, 1)


def test_effective_season_day_auto_returns_real_day() -> None:
    """Season 'auto' returns the real date and current season."""
    day = date(2026, 7, 15)
    mapped, season = effective_season_day(day, "auto", latitude=-33.0)
    assert mapped == day
    assert season == "winter"  # southern hemisphere winter


def test_effective_season_day_configured_season() -> None:
    """A configured season maps the day index into the target season."""
    day = date(2026, 7, 15)
    mapped, season = effective_season_day(day, "summer", latitude=-33.0)
    assert season == "summer"
    # The mapped day should fall within the southern summer (Dec-Feb region).
    assert mapped.month in (12, 1, 2)


def test_seasonal_blend_weights_temperate_sums_to_one() -> None:
    """Weights for a temperate latitude always sum to 1."""
    weights = seasonal_blend_weights(date(2026, 6, 15), latitude=45.0)
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-9)


def test_seasonal_blend_weights_equatorial_blends_all_seasons() -> None:
    """At equatorial latitude all four seasons receive nonzero weight."""
    weights = seasonal_blend_weights(date(2026, 6, 15), latitude=5.0)
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-9)
    assert len(weights) == 4
    assert all(v > 0.0 for v in weights.values())


def test_seasonal_blend_weights_high_lat_returns_base_weights() -> None:
    """High-latitude early return (seasonality_factor >= 1) gives non-blended weights."""
    # Mid-season: should return pure single-season weight.
    weights = seasonal_blend_weights(date(2026, 7, 15), latitude=45.0)
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-9)
    # Dominant season has most of the weight.
    assert max(weights.values()) >= 0.5


def _profile_with_climate_normals() -> SimulationProfile:
    means = tuple(0.3 + i * 0.01 for i in range(12))
    stds = tuple(0.1 for _ in range(12))
    return SimulationProfile(
        season="auto",
        latitude=-33.0,
        longitude=151.0,
        cloudiness_bias=0.0,
        cloud_variability=0.7,
        estimated_actuals_uncertainty_pct=2.2,
        shade_height_m=0.0,
        shade_width_m=0.0,
        shade_distance_m=0.0,
        shade_azimuth_deg=0.0,
        shade_opacity=0.0,
        astral_location=SimpleNamespace(),
        astral_elevation=SimpleNamespace(),
        random_seed="seed",
        climate_monthly_cloud=means,
        climate_monthly_cloud_std=stds,
    )


def test_base_cloudiness_uses_climate_normals() -> None:
    """Climate normals path returns the monthly mean and std directly."""
    profile = _profile_with_climate_normals()
    mean, std = base_cloudiness_for_day(date(2026, 1, 15), "summer", profile)
    # Month index 0 → means[0] = 0.30
    assert mean == pytest.approx(0.30, abs=0.001)
    assert std == pytest.approx(0.1, abs=0.001)


def test_base_cloudiness_high_variability_locale() -> None:
    """High-variability UK locale returns values from the variable table."""
    profile = SimulationProfile(
        season="auto",
        latitude=55.0,
        longitude=0.0,
        cloudiness_bias=0.0,
        cloud_variability=0.7,
        estimated_actuals_uncertainty_pct=2.2,
        shade_height_m=0.0,
        shade_width_m=0.0,
        shade_distance_m=0.0,
        shade_azimuth_deg=0.0,
        shade_opacity=0.0,
        astral_location=SimpleNamespace(),
        astral_elevation=SimpleNamespace(),
        random_seed="seed",
    )
    mean, std = base_cloudiness_for_day(date(2026, 1, 15), "winter", profile)
    assert 0.0 < mean <= 1.0
    assert std > 0.0


def test_base_cloudiness_seasonal_fallback() -> None:
    """Default seasonal fallback returns a fixed base and 0.18 std."""
    profile = SimulationProfile(
        season="auto",
        latitude=-33.0,
        longitude=151.0,
        cloudiness_bias=0.0,
        cloud_variability=0.7,
        estimated_actuals_uncertainty_pct=2.2,
        shade_height_m=0.0,
        shade_width_m=0.0,
        shade_distance_m=0.0,
        shade_azimuth_deg=0.0,
        shade_opacity=0.0,
        astral_location=SimpleNamespace(),
        astral_elevation=SimpleNamespace(),
        random_seed="seed",
    )
    mean, std = base_cloudiness_for_day(date(2026, 6, 15), "winter", profile)
    assert mean == pytest.approx(0.55)
    assert std == pytest.approx(0.18)


def test_intraday_cloud_bias_burnoff_morning() -> None:
    """Burnoff mode produces a positive bias in the morning phase."""
    result = _intraday_cloud_bias(0.0, burnoff_enabled=True, burnoff_amplitude=0.35, mixed_shape_gain=0.0)
    assert result > 0.0


def test_intraday_cloud_bias_burnoff_afternoon() -> None:
    """Burnoff mode clears toward afternoon (bias decreases or turns negative)."""
    morning = _intraday_cloud_bias(0.1, burnoff_enabled=True, burnoff_amplitude=0.35, mixed_shape_gain=0.0)
    afternoon = _intraday_cloud_bias(0.9, burnoff_enabled=True, burnoff_amplitude=0.35, mixed_shape_gain=0.0)
    assert morning > afternoon


def test_intraday_cloud_bias_mixed_shape() -> None:
    """Mixed mode returns a small nonzero bias at midday."""
    result = _intraday_cloud_bias(0.5, burnoff_enabled=False, burnoff_amplitude=0.0, mixed_shape_gain=1.0)
    # Gaussian noon-dip → small negative value around phase=0.5
    assert result != 0.0


@pytest.mark.parametrize(
    "season",
    ["winter", "autumn", "spring", "summer", "unknown"],
    ids=["winter", "autumn", "spring", "summer", "default"],
)
def test_spell_targets_all_seasons(season: str) -> None:
    """_spell_targets_for_season returns a valid (clear, cloudy) pair for every season."""
    clear, cloudy = _spell_targets_for_season(season)
    assert 0.0 < clear < 1.0
    assert 0.0 < cloudy < 1.0


@pytest.mark.parametrize(
    "season",
    ["winter", "autumn", "spring", "summer", "unknown"],
    ids=["winter", "autumn", "spring", "summer", "default"],
)
def test_spell_thresholds_all_seasons(season: str) -> None:
    """_spell_thresholds_for_season returns a valid (cloudy_thresh, clear_thresh) pair."""
    cloudy_thresh, clear_thresh = _spell_thresholds_for_season(season)
    assert 0.0 < cloudy_thresh < 1.0
    assert 0.0 < clear_thresh < 1.0


def _make_profile_for_battery() -> SimulationProfile:
    return SimulationProfile(
        season="auto",
        latitude=-33.0,
        longitude=151.0,
        cloudiness_bias=0.0,
        cloud_variability=0.7,
        estimated_actuals_uncertainty_pct=0.0,
        shade_height_m=0.0,
        shade_width_m=0.0,
        shade_distance_m=0.0,
        shade_azimuth_deg=0.0,
        shade_opacity=0.0,
        astral_location=SimpleNamespace(),
        astral_elevation=SimpleNamespace(),
        random_seed="batttest",
    )


def _make_battery(monkeypatch: pytest.MonkeyPatch, power_per_site_kw: float = 2.0) -> SolcastSimBatteryModel:
    """Return a battery model with simulated_power_kw patched to a constant value."""
    monkeypatch.setattr(sim_core, "simulated_power_kw", lambda *_a: power_per_site_kw)
    return SolcastSimBatteryModel(
        sites=API_KEY_SITES["1"]["sites"],
        tz=ZoneInfo("UTC"),
        profile=_make_profile_for_battery(),
        export_factor=1.0,
        export_limit_kw=10.0,
        battery_capacity_kwh=10.0,
        battery_max_charge_kw=5.0,
        battery_max_discharge_kw=5.0,
        house_load_kw=1.0,
    )


def test_battery_init_starts_at_half_soc(monkeypatch: pytest.MonkeyPatch) -> None:
    """Battery initialises at BATTERY_INITIAL_SOC (50%) of capacity."""
    model = _make_battery(monkeypatch)
    assert model.battery_soc == pytest.approx(50.0)
    assert model.battery_energy_kwh == pytest.approx(5.0)


def test_battery_soc_zero_capacity() -> None:
    """battery_soc returns 100.0 when capacity is zero (no battery)."""
    model = SolcastSimBatteryModel(
        sites=API_KEY_SITES["1"]["sites"],
        tz=ZoneInfo("UTC"),
        profile=_make_profile_for_battery(),
        export_factor=1.0,
        export_limit_kw=5.0,
        battery_capacity_kwh=0.0,
        battery_max_charge_kw=5.0,
        battery_max_discharge_kw=5.0,
        house_load_kw=1.0,
    )
    assert model.battery_soc == pytest.approx(100.0)


def test_battery_advance_first_call_sets_last_t(monkeypatch: pytest.MonkeyPatch) -> None:
    """First advance call stores last_t and returns without changing energy."""
    model = _make_battery(monkeypatch)
    initial_energy = model.battery_energy_kwh
    model.advance(43200.0)
    assert model.last_t == pytest.approx(43200.0)
    assert model.battery_energy_kwh == pytest.approx(initial_energy)


def test_battery_advance_charges_with_surplus(monkeypatch: pytest.MonkeyPatch) -> None:
    """Surplus PV (generation > load) charges the battery on the second advance call."""
    # 2 sites × 2.0 kW = 4.0 kW total, house_load = 1.0, surplus = 3.0 kW
    # Use 8 AM - outside the default 11 AM-2 PM free-charge window.
    model = _make_battery(monkeypatch, power_per_site_kw=2.0)
    initial_energy = model.battery_energy_kwh
    model.advance(28800.0)  # 08:00
    model.advance(28800.0 + 3600.0)  # 09:00
    assert model.battery_energy_kwh > initial_energy
    assert model.charge_power_kw > 0.0


def test_battery_advance_discharges_with_deficit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deficit (load > generation) discharges the battery."""
    # 0 PV, house_load = 1.0 → full deficit. Use 8 AM outside the free-charge window.
    model = _make_battery(monkeypatch, power_per_site_kw=0.0)
    initial_energy = model.battery_energy_kwh
    model.advance(28800.0)  # 08:00
    model.advance(28800.0 + 3600.0)  # 09:00
    assert model.battery_energy_kwh < initial_energy
    assert model.discharge_power_kw > 0.0


def test_battery_advance_exports_when_full(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fully charged battery causes surplus power to be exported."""
    model = _make_battery(monkeypatch, power_per_site_kw=3.0)
    # Pre-fill the battery to capacity and use 8 AM outside the free-charge window.
    model.battery_energy_kwh = model.battery_capacity_kwh
    model.advance(28800.0)  # 08:00
    model.advance(28800.0 + 3600.0)  # 09:00
    assert model.export_power_kw > 0.0


def test_battery_prime_power_state_sets_flows(monkeypatch: pytest.MonkeyPatch) -> None:
    """prime_power_state populates power flow fields without changing energy."""
    # 2 sites × 2.0 kW = 4.0 kW, surplus of 3.0 kW → charge
    model = _make_battery(monkeypatch, power_per_site_kw=2.0)
    initial_energy = model.battery_energy_kwh
    model.prime_power_state(43200.0)
    assert model.charge_power_kw > 0.0
    # Energy must not change - prime_power_state is instantaneous only
    assert model.battery_energy_kwh == pytest.approx(initial_energy)


def test_battery_restore_soc(monkeypatch: pytest.MonkeyPatch) -> None:
    """restore_battery_soc sets energy proportional to capacity."""
    model = _make_battery(monkeypatch)
    model.restore_battery_soc(80.0)
    assert model.battery_energy_kwh == pytest.approx(8.0)
    assert model.battery_soc == pytest.approx(80.0)


def test_battery_restore_energy(monkeypatch: pytest.MonkeyPatch) -> None:
    """restore_battery_energy clamps to capacity."""
    model = _make_battery(monkeypatch)
    model.restore_battery_energy(999.0)
    assert model.battery_energy_kwh == pytest.approx(model.battery_capacity_kwh)


def test_battery_restore_export_energy(monkeypatch: pytest.MonkeyPatch) -> None:
    """restore_export_energy stores the value."""
    model = _make_battery(monkeypatch)
    model.restore_export_energy(42.5)
    assert model.export_energy_kwh == pytest.approx(42.5)


def test_battery_restore_charge_energy(monkeypatch: pytest.MonkeyPatch) -> None:
    """restore_charge_energy stores the value."""
    model = _make_battery(monkeypatch)
    model.restore_charge_energy(7.3)
    assert model.charge_energy_kwh == pytest.approx(7.3)


def test_battery_restore_discharge_energy(monkeypatch: pytest.MonkeyPatch) -> None:
    """restore_discharge_energy stores the value."""
    model = _make_battery(monkeypatch)
    model.restore_discharge_energy(2.1)
    assert model.discharge_energy_kwh == pytest.approx(2.1)


def test_battery_restore_grid_import_energy(monkeypatch: pytest.MonkeyPatch) -> None:
    """restore_grid_import_energy stores the value."""
    model = _make_battery(monkeypatch)
    model.restore_grid_import_energy(5.0)
    assert model.grid_import_energy_kwh == pytest.approx(5.0)


def test_battery_advance_resets_daily_totals_on_new_day(monkeypatch: pytest.MonkeyPatch) -> None:
    """Advance resets today's export and import totals when the date changes."""
    model = _make_battery(monkeypatch, power_per_site_kw=3.0)
    model.export_today_energy_kwh = 5.0
    model.grid_import_today_energy_kwh = 3.0
    # Simulate last_day being yesterday so the day-change branch triggers.
    model.last_day = date(2000, 1, 1)
    model.advance(43200.0)
    assert model.export_today_energy_kwh == pytest.approx(0.0)
    assert model.grid_import_today_energy_kwh == pytest.approx(0.0)


def test_battery_charge_power_limit_tapers_near_full(monkeypatch: pytest.MonkeyPatch) -> None:
    """Charge limit tapers when SOC is between 85% and 100%."""
    model = _make_battery(monkeypatch)
    full_limit = model._charge_power_limit_kw()
    # Set battery to 90% SOC (within taper zone)
    model.battery_energy_kwh = model.battery_capacity_kwh * 0.90
    tapered_limit = model._charge_power_limit_kw()
    assert tapered_limit < full_limit


def test_battery_charge_power_limit_at_full(monkeypatch: pytest.MonkeyPatch) -> None:
    """At 100% SOC the charge limit returns the minimum taper value."""
    model = _make_battery(monkeypatch)
    model.battery_energy_kwh = model.battery_capacity_kwh
    limit = model._charge_power_limit_kw()
    assert limit > 0.0
    assert limit <= model.battery_max_charge_kw


def test_interpolate_piecewise_degenerate_knots() -> None:
    """Degenerate knot pair (x0 == x1) returns y1 directly."""
    result = _interpolate_piecewise(((0.5, 0.3), (0.5, 0.7)), 0.5)
    assert result == pytest.approx(0.7)


def test_interpolate_piecewise_single_point() -> None:
    """Loop-exhaustion guard for a single-point input returns the only y value."""
    result = _interpolate_piecewise(((0.0, 1.0),), 0.0)
    assert result == pytest.approx(1.0)


def test_solar_position_deg_calls_astral() -> None:
    """solar_position_deg delegates to astral_location methods."""
    mock_loc = SimpleNamespace(
        solar_elevation=lambda utc, elev: 30.0,
        solar_azimuth=lambda utc, elev: 180.0,
    )
    mock_elev = SimpleNamespace()
    now_local = datetime(2026, 6, 1, 12, 0, tzinfo=ZoneInfo("UTC"))
    elev, az = solar_position_deg(now_local, mock_loc, mock_elev)
    assert elev == pytest.approx(30.0)
    assert az == pytest.approx(180.0)


def test_solcast_azimuth_180_returns_180() -> None:
    """Azimuth 180 (due south in Solcast) maps to 180 compass."""
    assert solcast_azimuth_to_compass_deg(180.0) == pytest.approx(180.0)


def test_solcast_azimuth_negative_returns_positive() -> None:
    """Negative Solcast azimuth maps to its absolute value."""
    assert solcast_azimuth_to_compass_deg(-45.0) == pytest.approx(45.0)


def test_parse_shade_azimuth_out_of_range_raises() -> None:
    """parse_shade_azimuth_to_compass raises ValueError for |az| > 180."""
    with pytest.raises(ValueError, match="shade_azimuth_deg"):
        parse_shade_azimuth_to_compass(200.0)


def test_shade_attenuation_night_elevation_returns_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns 1.0 when sun is below horizon (elevation <= 0)."""
    profile = _build_profile((0.3, 0.8, 1.0))
    monkeypatch.setattr(sim_core, "solar_position_deg", lambda *_: (-5.0, 0.0))
    result = shade_attenuation_factor(datetime(2026, 6, 1, 0, 0, tzinfo=ZoneInfo("UTC")), profile)
    assert result == pytest.approx(1.0)


def test_shade_attenuation_high_elevation_returns_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns 1.0 when sun is higher than the tree top angle."""
    profile = _build_profile((0.3, 0.8, 1.0))
    monkeypatch.setattr(sim_core, "solar_position_deg", lambda *_: (85.0, 0.0))
    result = shade_attenuation_factor(datetime(2026, 6, 1, 12, 0, tzinfo=ZoneInfo("UTC")), profile)
    assert result == pytest.approx(1.0)


def test_shade_attenuation_off_azimuth_returns_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns 1.0 when sun azimuth is outside the shade half-width."""
    profile = _build_profile((0.3, 0.8, 1.0))
    # Sun at elevation 3° (below tree top), azimuth 180° away from shade at 0°.
    monkeypatch.setattr(sim_core, "solar_position_deg", lambda *_: (3.0, 180.0))
    result = shade_attenuation_factor(datetime(2026, 6, 1, 12, 0, tzinfo=ZoneInfo("UTC")), profile)
    assert result == pytest.approx(1.0)


def test_simulated_power_kw_shade_softening(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shade factor < 1 triggers the overcast-softening block."""
    profile = _build_profile((0.3, 0.8, 1.0))
    monkeypatch.setattr(sim_core, "shade_attenuation_factor", lambda *_: 0.5)
    # Noon UTC, summer southern hemisphere: daylight guaranteed.
    result = sim_core.simulated_power_kw(43200.0, 5.0, ZoneInfo("UTC"), profile)
    # Softening only reduces shade, so result must be >= 0.
    assert result >= 0.0


def test_season_span_for_date_fallback() -> None:
    """A late-year southern-hemisphere date resolves to summer."""
    day = date(2028, 12, 1)
    season, start, _next_start = season_span_for_date(day, latitude=-33.0)
    assert season == "summer"
    assert start <= day


def test_battery_charge_power_limit_zero_capacity() -> None:
    """_charge_power_limit_kw returns 0.0 when battery_capacity_kwh is 0."""
    model = SolcastSimBatteryModel(
        sites=API_KEY_SITES["1"]["sites"],
        tz=ZoneInfo("UTC"),
        profile=_make_profile_for_battery(),
        export_factor=1.0,
        export_limit_kw=10.0,
        battery_capacity_kwh=0.0,
        battery_max_charge_kw=5.0,
        battery_max_discharge_kw=5.0,
        house_load_kw=1.0,
    )
    assert model._charge_power_limit_kw() == pytest.approx(0.0)


def test_battery_prime_full_exports(monkeypatch: pytest.MonkeyPatch) -> None:
    """prime_power_state exports surplus when battery is full."""
    model = _make_battery(monkeypatch, power_per_site_kw=3.0)
    model.battery_energy_kwh = model.battery_capacity_kwh
    model.prime_power_state(43200.0)
    assert model.export_power_kw > 0.0


def test_battery_restore_export_today_energy(monkeypatch: pytest.MonkeyPatch) -> None:
    """restore_export_today_energy stores the value."""
    model = _make_battery(monkeypatch)
    model.restore_export_today_energy(5.0)
    assert model.export_today_energy_kwh == pytest.approx(5.0)


def test_battery_restore_grid_import_today_energy(monkeypatch: pytest.MonkeyPatch) -> None:
    """restore_grid_import_today_energy stores the value."""
    model = _make_battery(monkeypatch)
    model.restore_grid_import_today_energy(3.0)
    assert model.grid_import_today_energy_kwh == pytest.approx(3.0)


def test_battery_restore_free_charge_energy(monkeypatch: pytest.MonkeyPatch) -> None:
    """restore_free_charge_energy stores the value."""
    model = _make_battery(monkeypatch)
    model.restore_free_charge_energy(2.0)
    assert model.free_grid_charge_energy_kwh == pytest.approx(2.0)


def test_battery_advance_free_charge_period(monkeypatch: pytest.MonkeyPatch) -> None:
    """Advance charges from grid during the free-charge window."""
    # power_per_site_kw=0 → no PV, battery starts at 50% (5/10 kWh).
    model = _make_battery(monkeypatch, power_per_site_kw=0.0)
    initial_energy = model.battery_energy_kwh
    # FREE_CHARGE_DEFAULT_START_S = 39600 (11 AM).
    model.advance(39600.0)  # sets last_t, no energy change
    model.advance(39600.0 + 3600.0)  # 1 h inside free-charge window
    assert model.battery_energy_kwh > initial_energy
    assert model.free_grid_charge_energy_kwh > 0.0


def test_battery_advance_same_timestamp_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Advance with a repeated timestamp skips energy calculations."""
    model = _make_battery(monkeypatch)
    model.advance(43200.0)
    initial_energy = model.battery_energy_kwh
    model.advance(43200.0)  # repeated timestamp - dt_s == 0
    assert model.battery_energy_kwh == pytest.approx(initial_energy)
