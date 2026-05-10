"""Core simulation primitives for Solcast PV SimCity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import hashlib
import math
import random
from typing import Any
from zoneinfo import ZoneInfo

API_KEY_SITES: dict[str, Any] = {
    "1": {
        "sites": [
            {"resource_id": "1111-1111-1111-1111", "name": "First Site", "capacity": 5.0},
            {"resource_id": "2222-2222-2222-2222", "name": "Second Site", "capacity": 3.0},
        ]
    },
    "2": {
        "sites": [
            {"resource_id": "3333-3333-3333-3333", "name": "Third Site", "capacity": 3.0},
        ]
    },
    "3": {
        "sites": [
            {"resource_id": "4444-4444-4444-4444", "name": "Fourth Site", "capacity": 4.5},
            {"resource_id": "5555-5555-5555-5555", "name": "Fifth Site", "capacity": 3.2},
            {"resource_id": "6666-6666-6666-6666", "name": "Sixth Site", "capacity": 4.2},
        ]
    },
}


def parse_api_keys(value: str) -> list[str]:
    """Parse comma-separated API keys into a de-duplicated list."""
    return list(dict.fromkeys(part.strip() for part in str(value).split(",") if part.strip()))


def canonicalise_api_keys(value: str) -> str:
    """Return canonical comma-separated API keys for stable config identity."""
    api_keys = parse_api_keys(value)
    sorted_keys = sorted(
        api_keys,
        key=lambda key: (not key.isdigit(), int(key) if key.isdigit() else key),
    )
    return ",".join(sorted_keys)


BASE_FORECAST_SCALE = 0.9
BATTERY_ENERGY_UNIQUE_ID = "solcast_sim_battery_energy"
BATTERY_INITIAL_SOC = 50.0

SECONDS_PER_MINUTE = 60
MINUTES_PER_HOUR = 60
HOURS_PER_DAY = 24
SECONDS_PER_HOUR = SECONDS_PER_MINUTE * MINUTES_PER_HOUR
SECONDS_PER_DAY = HOURS_PER_DAY * SECONDS_PER_HOUR
SECONDS_PER_5_MINUTES = 5 * SECONDS_PER_MINUTE
FIVE_MINUTE_INTERVALS_PER_HOUR = 12
APPROX_SEASON_SPAN_DAYS = 92

LATITUDE_DAYLIGHT_MIN_DEG = -66.0
LATITUDE_DAYLIGHT_MAX_DEG = 66.0
EARTH_AXIAL_TILT_DEG = 23.44
DAYS_PER_YEAR = 365.0
SOLAR_DECLINATION_DAY_OFFSET = 10
DAYLIGHT_MIN_HOURS = 4.0
DAYLIGHT_MAX_HOURS = 20.0

SHA256_SEED_BYTES = 8

DAILY_CLOUD_MAX = 0.95
DAY_CLOUD_GAUSS_STD_FACTOR = 0.5
DAY_CLOUD_GAUSS_STD_MIN = 0.01
CLOUD_STD_REFERENCE = 0.18
CLOUD_VARIABILITY_BASE_SCALE = 0.50
PROFILE_CLOUD_VARIABILITY_MAX = 2.0
LOCAL_CLOUD_VARIATION_CENTRE = 0.5
INTRADAY_VARIABILITY_MIXED_PEAK = 0.5
INTRADAY_VARIABILITY_MIXED_SPAN = 0.35
INTRADAY_VARIABILITY_FLOOR = 0.28
INTRADAY_VARIABILITY_GAIN = 1.0
CLOUD_TREND_PERSISTENCE = 0.88
CLOUD_TREND_INNOVATION_SCALE = 0.45
CLOUD_ATTENUATION_EXPONENT = 1.2
CLOUD_ATTENUATION_SCALE = 0.90
CLOUD_ATTENUATION_MIN = 0.05
CLOUD_ATTENUATION_MAX = 1.35
CLOUD_SMOOTHING_CENTRE_WEIGHT = 2.0
CLEAR_SKY_SHAPE_EXPONENT = 1.7

BURN_OFF_PATTERN_PROB_COOL_SEASONS = 0.75
BURN_OFF_PATTERN_PROB_WARM_SEASONS = 0.35
BURN_OFF_CLOUD_BIAS_MAX = 0.35
BURN_OFF_CLEARING_WEIGHT = 0.65

CLOUD_EDGE_MIXED_PEAK = 0.55
CLOUD_EDGE_MIXED_SPAN = 0.30
CLOUD_EDGE_SPIKE_DECAY = 0.56
CLOUD_EDGE_SPIKE_PROB_BASE = 0.008
CLOUD_EDGE_SPIKE_PROB_GAIN = 0.16
CLOUD_EDGE_SPIKE_MAX = 0.45

SIMULATED_POWER_CAP_FACTOR = 1.12

COOL_SEASONS = {"winter", "autumn", "spring"}
SPELL_CLEAR_TARGET_COOL = 0.08
SPELL_CLOUDY_TARGET_COOL = 0.88
SPELL_CLEAR_TARGET_SUMMER = 0.12
SPELL_CLOUDY_TARGET_SUMMER = 0.82
SPELL_CLEAR_TARGET_DEFAULT = 0.15
SPELL_CLOUDY_TARGET_DEFAULT = 0.90
SPELL_CLOUDY_THRESHOLD_COOL = 0.24
SPELL_CLEAR_THRESHOLD_COOL = 0.15
SPELL_CLOUDY_THRESHOLD_DEFAULT = 0.22
SPELL_CLEAR_THRESHOLD_DEFAULT = 0.18
SPELL_CLEAR_CAP_BASE_COOL = 0.28
SPELL_CLEAR_CAP_REDUCTION_COOL = 0.20

SPELL_SIGNAL_WAVE_WEIGHT_PRIMARY = 0.75
SPELL_SIGNAL_WAVE_WEIGHT_SECONDARY = 0.45
SPELL_SIGNAL_WAVE_WEIGHT_TERTIARY = 0.25
SPELL_SIGNAL_WAVE_PERIOD_PRIMARY_DAYS = 9.0
SPELL_SIGNAL_WAVE_PERIOD_SECONDARY_DAYS = 17.0
SPELL_SIGNAL_WAVE_PERIOD_TERTIARY_DAYS = 31.0
SPELL_SIGNAL_NORMALISATION_FACTOR = 1.45
SPELL_CLEAR_STRENGTH_EXPONENT = 0.65

SOLAR_ANGLE_EPSILON = 1e-6
BATTERY_FULL_EPSILON_KWH = 1e-6
SECOND_OF_DAY_MAX = 86399.0

FREE_CHARGE_DEFAULT_START_S = 11 * SECONDS_PER_HOUR
FREE_CHARGE_DEFAULT_END_S = 14 * SECONDS_PER_HOUR

# Monthly cloud cover normals for particularly variable North Atlantic locales (Jan-Dec). I've got you covered, Geoff.
_VARIABLE_LOCALE_MONTHLY_CLOUD_MEAN: tuple[float, ...] = (
    0.80,
    0.76,
    0.68,
    0.62,
    0.60,
    0.58,
    0.56,
    0.58,
    0.64,
    0.72,
    0.78,
    0.81,
)
_VARIABLE_LOCALE_MONTHLY_CLOUD_STD: tuple[float, ...] = (
    0.14,
    0.16,
    0.26,
    0.28,
    0.28,
    0.27,
    0.26,
    0.27,
    0.28,
    0.23,
    0.17,
    0.13,
)


@dataclass(frozen=True)
class SimulationProfile:
    """Inputs controlling seasonal and pseudo-random generation behaviour."""

    season: str
    latitude: float
    longitude: float
    cloudiness_bias: float
    cloud_variability: float
    estimated_actuals_uncertainty_pct: float
    shade_height_m: float
    shade_width_m: float
    shade_distance_m: float
    shade_azimuth_deg: float
    shade_opacity: float
    astral_location: Any
    astral_elevation: Any
    random_seed: str
    climate_monthly_cloud: tuple[float, ...] | None = None
    climate_monthly_cloud_std: tuple[float, ...] | None = None


def time_str_to_seconds(t: str) -> int:
    """Convert a 'HH:MM:SS' or 'HH:MM' string to seconds since midnight."""
    parts = t.split(":")
    h, m, s = int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0
    return h * SECONDS_PER_HOUR + m * SECONDS_PER_MINUTE + s


def derived_random_seed(api_key: str, latitude: float, longitude: float) -> str:
    """Return a stable internal seed derived from simulation identity."""
    return f"simcity|{api_key}|{latitude:.6f}|{longitude:.6f}"


def is_high_variability_locale(latitude: float, longitude: float) -> bool:
    """Return True for locales with persistently bad winters and highly variable transitional seasons."""
    return 49.5 <= latitude <= 60.9 and -8.2 <= longitude <= 1.8


def clip(value: float, lower: float, upper: float) -> float:
    """Clamp *value* between *lower* and *upper*."""
    return max(lower, min(upper, value))


def season_starts_for_year(year: int, latitude: float) -> dict[str, date]:
    """Return meteorological season start dates for a year and hemisphere."""
    if latitude >= 0:
        return {
            "spring": date(year, 3, 1),
            "summer": date(year, 6, 1),
            "autumn": date(year, 9, 1),
            "winter": date(year, 12, 1),
        }
    return {
        "autumn": date(year, 3, 1),
        "winter": date(year, 6, 1),
        "spring": date(year, 9, 1),
        "summer": date(year, 12, 1),
    }


def season_span_for_date(day: date, latitude: float) -> tuple[str, date, date]:
    """Return (season, season_start, next_season_start) containing *day*."""
    boundaries: list[tuple[date, str]] = []
    for year in (day.year - 1, day.year, day.year + 1):
        starts = season_starts_for_year(year, latitude)
        boundaries.extend((start, season) for season, start in starts.items())
    boundaries.sort(key=lambda item: item[0])

    for idx, (start, season) in enumerate(boundaries[:-1]):
        next_start = boundaries[idx + 1][0]
        if start <= day < next_start:
            return season, start, next_start

    season, start = boundaries[-1][1], boundaries[-1][0]
    return season, start, start + timedelta(days=APPROX_SEASON_SPAN_DAYS)


def effective_season_day(day: date, configured_season: str, latitude: float) -> tuple[date, str]:
    """Map real *day* to effective day/season used for simulation."""
    current_season, current_start, _current_next = season_span_for_date(day, latitude)
    if configured_season == "auto":
        return day, current_season

    day_index = max(0, (day - current_start).days)

    season_starts: list[date] = [
        season_starts_for_year(year, latitude)[configured_season] for year in (day.year - 1, day.year, day.year + 1)
    ]
    season_starts.sort()

    target_start = max((start for start in season_starts if start <= day), default=season_starts[0])
    all_boundaries: list[date] = []
    for year in (target_start.year - 1, target_start.year, target_start.year + 1):
        all_boundaries.extend(season_starts_for_year(year, latitude).values())
    all_boundaries = sorted(set(all_boundaries))
    next_target_start = next(
        (start for start in all_boundaries if start > target_start),
        target_start + timedelta(days=APPROX_SEASON_SPAN_DAYS),
    )

    target_len = max(1, (next_target_start - target_start).days)
    mapped_index = min(day_index, target_len - 1)
    mapped_day = target_start + timedelta(days=mapped_index)
    return mapped_day, configured_season


def daylight_seconds(day: date, latitude: float, season: str) -> float:
    """Estimate daylight duration from latitude/day-of-year and season profile."""
    del season
    doy = day.timetuple().tm_yday
    phi = math.radians(clip(latitude, LATITUDE_DAYLIGHT_MIN_DEG, LATITUDE_DAYLIGHT_MAX_DEG))
    decl = math.radians(-EARTH_AXIAL_TILT_DEG * math.cos((2 * math.pi / DAYS_PER_YEAR) * (doy + SOLAR_DECLINATION_DAY_OFFSET)))
    cos_ha = clip(-math.tan(phi) * math.tan(decl), -1.0, 1.0)
    hour_angle = math.acos(cos_ha)
    daylight = HOURS_PER_DAY * hour_angle / math.pi
    return clip(daylight * SECONDS_PER_HOUR, DAYLIGHT_MIN_HOURS * SECONDS_PER_HOUR, DAYLIGHT_MAX_HOURS * SECONDS_PER_HOUR)


def seed_to_int(seed_material: str) -> int:
    """Build deterministic seed integer from text."""
    digest = hashlib.sha256(seed_material.encode("utf-8")).digest()
    return int.from_bytes(digest[:SHA256_SEED_BYTES], "big", signed=False)


def solar_position_deg(now_local: datetime, astral_location: Any, astral_elevation: Any) -> tuple[float, float]:
    """Return (elevation_deg, azimuth_deg) for local time using Astral."""
    now_utc = now_local.astimezone(UTC)
    elevation_deg = float(astral_location.solar_elevation(now_utc, astral_elevation))
    azimuth_deg = float(astral_location.solar_azimuth(now_utc, astral_elevation))
    return elevation_deg, azimuth_deg


def azimuth_delta_deg(a: float, b: float) -> float:
    """Return minimal absolute azimuth separation in degrees."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


def solcast_azimuth_to_compass_deg(solcast_azimuth_deg: float) -> float:
    """Convert Solcast azimuth to compass azimuth in degrees."""
    az = float(solcast_azimuth_deg)
    if az in (180.0, -180.0):
        return 180.0
    if az >= 0.0:
        return (360.0 - az) % 360.0
    return -az


def parse_shade_azimuth_to_compass(raw_azimuth: float) -> float:
    """Parse configured shade azimuth and return compass azimuth."""
    if not -180.0 <= raw_azimuth <= 180.0:
        raise ValueError("shade_azimuth_deg must be in Solcast range [-180, 180]")
    return solcast_azimuth_to_compass_deg(raw_azimuth)


def shade_attenuation_factor(now_local: datetime, profile: SimulationProfile) -> float:
    """Return multiplicative generation factor from tree shading."""
    shade_opacity = clip(profile.shade_opacity, 0.0, 1.0)
    shade_height_m = max(0.0, profile.shade_height_m)
    shade_width_m = max(0.0, profile.shade_width_m)
    shade_distance_m = max(0.0, profile.shade_distance_m)
    if shade_opacity <= 0.0 or shade_height_m <= 0.0 or shade_width_m <= 0.0 or shade_distance_m <= 0.0:
        return 1.0

    elevation_deg, azimuth_deg = solar_position_deg(
        now_local,
        profile.astral_location,
        profile.astral_elevation,
    )
    if elevation_deg <= 0.0:
        return 1.0

    tree_top_angle_deg = math.degrees(math.atan2(shade_height_m, shade_distance_m))
    if elevation_deg >= tree_top_angle_deg:
        return 1.0

    # Angular half-width is derived from actual physical width and distance.
    shade_half_width_deg = math.degrees(math.atan2(shade_width_m / 2.0, shade_distance_m))
    az_delta = azimuth_delta_deg(azimuth_deg, profile.shade_azimuth_deg % 360.0)
    if az_delta >= shade_half_width_deg:
        return 1.0

    az_factor = (1.0 - az_delta / max(shade_half_width_deg, 0.01)) ** 2
    elev_factor = clip(1.0 - (elevation_deg / max(tree_top_angle_deg, 0.1)), 0.0, 1.0)
    blocked_fraction = clip(shade_opacity * az_factor * elev_factor, 0.0, 1.0)
    return 1.0 - blocked_fraction


def base_cloudiness_for_day(day: date, season: str, profile: SimulationProfile) -> tuple[float, float]:
    """Return (base_cloudiness, day_std) from climate normals or seasonal fallback."""
    if profile.climate_monthly_cloud is not None and profile.climate_monthly_cloud_std is not None:
        idx = day.month - 1
        return profile.climate_monthly_cloud[idx], profile.climate_monthly_cloud_std[idx]
    if is_high_variability_locale(profile.latitude, profile.longitude):
        idx = day.month - 1
        return _VARIABLE_LOCALE_MONTHLY_CLOUD_MEAN[idx], _VARIABLE_LOCALE_MONTHLY_CLOUD_STD[idx]
    base = {
        "spring": 0.30,
        "summer": 0.20,
        "autumn": 0.35,
        "winter": 0.55,
    }.get(season, 0.35)
    return base, 0.18


def _intraday_cloud_bias(
    day_phase: float,
    burnoff_enabled: bool,
    burnoff_amplitude: float,
    mixed_shape_gain: float,
) -> float:
    """Return deterministic intraday cloudiness bias.

    Produces realistic day-shape weather patterns, including burn-off days where
    overcast mornings clear toward a hazy or partly cloudy afternoon.
    """
    if burnoff_enabled:
        # Morning overcast/drizzle loading tapers through the day.
        morning_overcast = clip((0.62 - day_phase) / 0.62, 0.0, 1.0)
        afternoon_clearing = clip((day_phase - 0.52) / 0.48, 0.0, 1.0)
        return burnoff_amplitude * (morning_overcast - BURN_OFF_CLEARING_WEIGHT * afternoon_clearing)

    # Mixed/partly-cloudy fallback keeps some shape without strongly biasing the day.
    noon_dip = -0.06 * math.exp(-((day_phase - 0.50) ** 2) / 0.02)
    afternoon_variability = 0.05 * math.exp(-((day_phase - 0.72) ** 2) / 0.03)
    return mixed_shape_gain * (noon_dip + afternoon_variability)


def cloud_profile(profile: SimulationProfile, day: date, season: str) -> list[float]:
    """Return deterministic 5-minute cloud attenuation factors for one day."""
    base_cloudiness, cloud_std = base_cloudiness_for_day(day, season, profile)
    day_seed = f"{profile.random_seed}|{day.isoformat()}|{profile.latitude:.4f}|{profile.longitude:.4f}|{season}"
    day_rng = random.Random(seed_to_int(day_seed))
    daily_cloud = clip(
        base_cloudiness
        + profile.cloudiness_bias
        + day_rng.gauss(0.0, max(cloud_std * DAY_CLOUD_GAUSS_STD_FACTOR, DAY_CLOUD_GAUSS_STD_MIN)),
        0.0,
        DAILY_CLOUD_MAX,
    )

    bins = HOURS_PER_DAY * FIVE_MINUTE_INTERVALS_PER_HOUR
    mixed_distance = abs(daily_cloud - INTRADAY_VARIABILITY_MIXED_PEAK)
    mixed_weight = clip(1.0 - (mixed_distance / INTRADAY_VARIABILITY_MIXED_SPAN), 0.0, 1.0)
    intraday_variability_weight = INTRADAY_VARIABILITY_FLOOR + INTRADAY_VARIABILITY_GAIN * mixed_weight

    variability_scale = (
        CLOUD_VARIABILITY_BASE_SCALE
        * (cloud_std / CLOUD_STD_REFERENCE)
        * clip(
            profile.cloud_variability,
            0.0,
            PROFILE_CLOUD_VARIABILITY_MAX,
        )
        * intraday_variability_weight
    )

    in_cool_season = season in COOL_SEASONS
    burnoff_prob = BURN_OFF_PATTERN_PROB_COOL_SEASONS if in_cool_season else BURN_OFF_PATTERN_PROB_WARM_SEASONS
    cloudiness_gate = clip((daily_cloud - 0.30) / 0.60, 0.0, 1.0)
    burnoff_enabled = day_rng.random() < burnoff_prob * cloudiness_gate
    burnoff_amplitude = BURN_OFF_CLOUD_BIAS_MAX * clip(0.45 + daily_cloud, 0.0, 1.0) * day_rng.uniform(0.85, 1.15)
    mixed_shape_gain = day_rng.uniform(0.85, 1.20)

    # Use a correlated cloud anomaly so adjacent intervals trend smoothly.
    trend_anomaly = 0.0
    cloud_edge_spike = 0.0
    raw: list[float] = []
    for idx in range(bins):
        bin_rng = random.Random(seed_to_int(f"{day_seed}|bin:{idx}"))
        day_phase = (idx + 0.5) / bins
        innovation = (bin_rng.random() - LOCAL_CLOUD_VARIATION_CENTRE) * variability_scale
        trend_anomaly = trend_anomaly * CLOUD_TREND_PERSISTENCE + innovation * CLOUD_TREND_INNOVATION_SCALE
        local_day_bias = _intraday_cloud_bias(day_phase, burnoff_enabled, burnoff_amplitude, mixed_shape_gain)
        local_cloud = clip(
            daily_cloud + trend_anomaly + local_day_bias,
            0.0,
            1.0,
        )

        attenuation = clip(
            1.0 - (local_cloud**CLOUD_ATTENUATION_EXPONENT) * CLOUD_ATTENUATION_SCALE,
            CLOUD_ATTENUATION_MIN,
            1.0,
        )

        # Cloud-edge enhancement: brief irradiance spikes on mixed-cloud days,
        # strongest near solar peak and in convective/partly-cloudy conditions.
        mixed_distance = abs(local_cloud - CLOUD_EDGE_MIXED_PEAK)
        mixed_weight = clip(1.0 - (mixed_distance / CLOUD_EDGE_MIXED_SPAN), 0.0, 1.0)
        daytime_weight = math.sin(math.pi * day_phase) ** 1.8
        variability_weight = clip(profile.cloud_variability / PROFILE_CLOUD_VARIABILITY_MAX, 0.0, 1.0)
        spike_prob = CLOUD_EDGE_SPIKE_PROB_BASE + CLOUD_EDGE_SPIKE_PROB_GAIN * mixed_weight * daytime_weight * variability_weight

        if bin_rng.random() < spike_prob:
            pulse = CLOUD_EDGE_SPIKE_MAX * (0.35 + 0.65 * bin_rng.random()) * mixed_weight * daytime_weight
            cloud_edge_spike = max(cloud_edge_spike, pulse)
        else:
            cloud_edge_spike *= CLOUD_EDGE_SPIKE_DECAY

        attenuation = clip(
            attenuation * (1.0 + cloud_edge_spike),
            CLOUD_ATTENUATION_MIN,
            CLOUD_ATTENUATION_MAX,
        )
        raw.append(attenuation)

    smoothed: list[float] = []
    for idx in range(bins):
        prev_val = raw[idx - 1] if idx > 0 else raw[idx]
        next_val = raw[idx + 1] if idx < bins - 1 else raw[idx]
        smoothed.append((prev_val + CLOUD_SMOOTHING_CENTRE_WEIGHT * raw[idx] + next_val) / (2.0 + CLOUD_SMOOTHING_CENTRE_WEIGHT))
    return smoothed


def daily_cloudiness(profile: SimulationProfile, day: date, season: str) -> float:
    """Return deterministic cloudiness metric for a given day."""
    base_cloudiness, cloud_std = base_cloudiness_for_day(day, season, profile)
    day_seed = f"{profile.random_seed}|{day.isoformat()}|{profile.latitude:.4f}|{profile.longitude:.4f}|{season}"
    day_rng = random.Random(seed_to_int(day_seed))
    return clip(
        base_cloudiness
        + profile.cloudiness_bias
        + day_rng.gauss(0.0, max(cloud_std * DAY_CLOUD_GAUSS_STD_FACTOR, DAY_CLOUD_GAUSS_STD_MIN)),
        0.0,
        DAILY_CLOUD_MAX,
    )


def persistent_spell_adjustment(
    profile: SimulationProfile,
    day: date,
    season: str,
    base_cloudiness: float = 0.5,
) -> tuple[float, str]:
    """Return deterministic multi-day cloudiness adjustment and spell label."""
    seed_base = f"{profile.random_seed}|{profile.latitude:.4f}|{profile.longitude:.4f}|spell"
    phase_rng = random.Random(seed_to_int(seed_base))
    phase_1 = phase_rng.uniform(0.0, 2.0 * math.pi)
    phase_2 = phase_rng.uniform(0.0, 2.0 * math.pi)
    phase_3 = phase_rng.uniform(0.0, 2.0 * math.pi)

    day_idx = day.toordinal()
    low_frequency_signal = (
        SPELL_SIGNAL_WAVE_WEIGHT_PRIMARY * math.sin((2.0 * math.pi * day_idx / SPELL_SIGNAL_WAVE_PERIOD_PRIMARY_DAYS) + phase_1)
        + SPELL_SIGNAL_WAVE_WEIGHT_SECONDARY * math.sin((2.0 * math.pi * day_idx / SPELL_SIGNAL_WAVE_PERIOD_SECONDARY_DAYS) + phase_2)
        + SPELL_SIGNAL_WAVE_WEIGHT_TERTIARY * math.sin((2.0 * math.pi * day_idx / SPELL_SIGNAL_WAVE_PERIOD_TERTIARY_DAYS) + phase_3)
    )
    spell_signal = clip(low_frequency_signal / SPELL_SIGNAL_NORMALISATION_FACTOR, -1.0, 1.0)

    southern_hemisphere = profile.latitude < 0

    if southern_hemisphere and season in COOL_SEASONS:
        clear_target = SPELL_CLEAR_TARGET_COOL
        cloudy_target = SPELL_CLOUDY_TARGET_COOL
    elif season == "summer":
        clear_target = SPELL_CLEAR_TARGET_SUMMER
        cloudy_target = SPELL_CLOUDY_TARGET_SUMMER
    else:
        clear_target = SPELL_CLEAR_TARGET_DEFAULT
        cloudy_target = SPELL_CLOUDY_TARGET_DEFAULT

    if southern_hemisphere and season in COOL_SEASONS:
        cloudy_threshold = SPELL_CLOUDY_THRESHOLD_COOL
        clear_threshold = SPELL_CLEAR_THRESHOLD_COOL
    else:
        cloudy_threshold = SPELL_CLOUDY_THRESHOLD_DEFAULT
        clear_threshold = SPELL_CLEAR_THRESHOLD_DEFAULT

    if spell_signal >= cloudy_threshold:
        strength = (spell_signal - cloudy_threshold) / (1.0 - cloudy_threshold)
        target_cloud = base_cloudiness + (cloudy_target - base_cloudiness) * strength
        return target_cloud - base_cloudiness, "cloudy_spell"

    if spell_signal <= -clear_threshold:
        strength = (-spell_signal - clear_threshold) / (1.0 - clear_threshold)
        clear_strength = strength**SPELL_CLEAR_STRENGTH_EXPONENT
        target_cloud = base_cloudiness + (clear_target - base_cloudiness) * clear_strength
        if southern_hemisphere and season in COOL_SEASONS:
            target_cloud = min(
                target_cloud,
                SPELL_CLEAR_CAP_BASE_COOL - SPELL_CLEAR_CAP_REDUCTION_COOL * clear_strength,
            )
        return target_cloud - base_cloudiness, "clear_spell"

    return 0.0, "mixed"


def simulated_power_kw(second_of_day: float, capacity_kw: float, tz: ZoneInfo, profile: SimulationProfile) -> float:
    """Return synthetic PV generation in kW using seasonal daylight + clouds."""
    now_local = datetime.now(tz)
    local_day = now_local.date()
    effective_day, season = effective_season_day(local_day, profile.season, profile.latitude)

    t = clip(second_of_day, 0.0, SECOND_OF_DAY_MAX)
    daylight_s = daylight_seconds(effective_day, profile.latitude, season)
    sunrise_s = (SECONDS_PER_DAY - daylight_s) / 2
    sunset_s = sunrise_s + daylight_s
    if t <= sunrise_s or t >= sunset_s:
        return 0.0

    phase = (t - sunrise_s) / max(1.0, daylight_s)
    clear_sky_shape = math.sin(math.pi * phase) ** CLEAR_SKY_SHAPE_EXPONENT

    cloud_factors = cloud_profile(profile, effective_day, season)
    cloud_idx = int(t // SECONDS_PER_5_MINUTES)
    cloud_idx = int(clip(float(cloud_idx), 0.0, float(len(cloud_factors) - 1)))
    cloud_factor = cloud_factors[cloud_idx]

    season_gain = {
        "spring": 0.95,
        "summer": 1.00,
        "autumn": 0.85,
        "winter": 0.70,
    }.get(season, 0.90)

    shade_factor = shade_attenuation_factor(now_local, profile)
    power_kw = capacity_kw * BASE_FORECAST_SCALE * season_gain * clear_sky_shape * cloud_factor * shade_factor
    return clip(power_kw, 0.0, capacity_kw * SIMULATED_POWER_CAP_FACTOR)


def seconds_since_midnight(tz: ZoneInfo) -> float:
    """Return elapsed seconds since local midnight."""
    now = datetime.now(tz)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return (now - midnight).total_seconds()


class SolcastSimBatteryModel:
    """Shared state model for battery/export simulation."""

    _CHARGE_TAPER_START_SOC = 0.85
    _CHARGE_TAPER_MIN_KW = 2.0
    _CHARGE_TAPER_MIN_FACTOR = 0.4

    def __init__(
        self,
        sites: list[dict[str, Any]],
        tz: ZoneInfo,
        profile: SimulationProfile,
        export_factor: float,
        export_limit_kw: float,
        battery_capacity_kwh: float,
        battery_max_charge_kw: float,
        battery_max_discharge_kw: float,
        house_load_kw: float,
        free_charge_start_s: int = FREE_CHARGE_DEFAULT_START_S,
        free_charge_end_s: int = FREE_CHARGE_DEFAULT_END_S,
    ) -> None:
        """Initialise model state."""
        self.sites = sites
        self._tz = tz
        self._profile = profile
        self.export_factor = export_factor
        self.export_limit_kw = max(0.0, export_limit_kw)
        self.battery_capacity_kwh = max(0.0, battery_capacity_kwh)
        self.battery_max_charge_kw = max(0.0, battery_max_charge_kw)
        self.battery_max_discharge_kw = max(0.0, battery_max_discharge_kw)
        self.house_load_kw = max(0.0, house_load_kw)
        self.free_charge_start_s = free_charge_start_s
        self.free_charge_end_s = free_charge_end_s

        self.battery_energy_kwh = min(
            self.battery_capacity_kwh,
            max(0.0, self.battery_capacity_kwh * (BATTERY_INITIAL_SOC / 100.0)),
        )
        self.export_power_kw = 0.0
        self.charge_power_kw = 0.0
        self.discharge_power_kw = 0.0
        self.battery_power_kw = 0.0
        self.grid_import_power_kw = 0.0

        self.export_energy_kwh = 0.0
        self.export_today_energy_kwh = 0.0
        self.charge_energy_kwh = 0.0
        self.discharge_energy_kwh = 0.0
        self.grid_import_energy_kwh = 0.0
        self.grid_import_today_energy_kwh = 0.0
        self.free_grid_charge_power_kw = 0.0
        self.free_grid_charge_energy_kwh = 0.0
        self.last_day: date | None = None
        self.last_t: float | None = None

    def _charge_power_limit_kw(self) -> float:
        """Return max charge power after SOC taper near full."""
        if self.battery_capacity_kwh <= 0:
            return 0.0

        soc = self.battery_energy_kwh / self.battery_capacity_kwh
        taper_min_kw = min(
            self.battery_max_charge_kw,
            max(
                self._CHARGE_TAPER_MIN_KW,
                self.battery_max_charge_kw * self._CHARGE_TAPER_MIN_FACTOR,
            ),
        )

        if soc <= self._CHARGE_TAPER_START_SOC:
            return self.battery_max_charge_kw
        if soc >= 1.0:
            return taper_min_kw

        taper_window = 1.0 - self._CHARGE_TAPER_START_SOC
        taper_factor = (1.0 - soc) / taper_window
        taper_factor = max(0.0, min(1.0, taper_factor))
        return taper_min_kw + (self.battery_max_charge_kw - taper_min_kw) * taper_factor

    def prime_power_state(self, t: float) -> None:
        """Populate instantaneous power flows without advancing energy totals."""
        total_power_kw = sum(simulated_power_kw(t, site["capacity"], self._tz, self._profile) for site in self.sites)

        surplus_kw = max(0.0, total_power_kw - self.house_load_kw)
        deficit_kw = max(0.0, self.house_load_kw - total_power_kw)

        charge_kw = 0.0
        discharge_kw = 0.0
        free_charge_kw = 0.0

        if self.battery_capacity_kwh > 0 and self.battery_energy_kwh < self.battery_capacity_kwh and surplus_kw > 0:
            charge_kw = min(surplus_kw, self._charge_power_limit_kw())
            surplus_kw -= charge_kw

        if (
            self.free_charge_start_s <= t < self.free_charge_end_s
            and self.battery_capacity_kwh > 0
            and self.battery_energy_kwh < self.battery_capacity_kwh
        ):
            available_charge_kw = max(0.0, self._charge_power_limit_kw() - charge_kw)
            free_charge_kw = available_charge_kw

        if self.battery_capacity_kwh > 0 and self.battery_energy_kwh > 0 and deficit_kw > 0:
            discharge_kw = min(deficit_kw, self.battery_max_discharge_kw)

        battery_full = self.battery_capacity_kwh <= 0 or self.battery_energy_kwh >= self.battery_capacity_kwh - BATTERY_FULL_EPSILON_KWH
        export_kw = 0.0
        if battery_full and surplus_kw > 0:
            export_kw = min(surplus_kw * self.export_factor, self.export_limit_kw)

        self.export_power_kw = export_kw
        self.charge_power_kw = charge_kw
        self.discharge_power_kw = discharge_kw
        self.free_grid_charge_power_kw = free_charge_kw
        self.battery_power_kw = max(0.0, discharge_kw - charge_kw - free_charge_kw)
        self.grid_import_power_kw = max(0.0, deficit_kw - discharge_kw)

    def restore_export_energy(self, value: float) -> None:
        """Restore total exported energy."""
        self.export_energy_kwh = max(self.export_energy_kwh, 0.0, value)

    def restore_export_today_energy(self, value: float) -> None:
        """Restore today's exported energy."""
        self.export_today_energy_kwh = max(self.export_today_energy_kwh, 0.0, value)

    def restore_charge_energy(self, value: float) -> None:
        """Restore total charged energy."""
        self.charge_energy_kwh = max(self.charge_energy_kwh, 0.0, value)

    def restore_discharge_energy(self, value: float) -> None:
        """Restore total discharged energy."""
        self.discharge_energy_kwh = max(self.discharge_energy_kwh, 0.0, value)

    def restore_battery_energy(self, value: float) -> None:
        """Restore battery stored energy."""
        self.battery_energy_kwh = min(self.battery_capacity_kwh, max(0.0, value))

    def restore_battery_soc(self, value: float) -> None:
        """Restore battery state of charge."""
        self.restore_battery_energy(self.battery_capacity_kwh * (value / 100.0))

    def restore_grid_import_energy(self, value: float) -> None:
        """Restore total grid import energy."""
        self.grid_import_energy_kwh = max(self.grid_import_energy_kwh, 0.0, value)

    def restore_grid_import_today_energy(self, value: float) -> None:
        """Restore today's grid import energy."""
        self.grid_import_today_energy_kwh = max(self.grid_import_today_energy_kwh, 0.0, value)

    def restore_free_charge_energy(self, value: float) -> None:
        """Restore total free-period grid charge energy."""
        self.free_grid_charge_energy_kwh = max(self.free_grid_charge_energy_kwh, 0.0, value)

    @property
    def battery_soc(self) -> float:
        """Return battery state of charge (%)."""
        if self.battery_capacity_kwh <= 0:
            return 100.0
        return min(100.0, max(0.0, (self.battery_energy_kwh / self.battery_capacity_kwh) * 100))

    def advance(self, t: float) -> None:
        """Advance simulation state to second-of-day *t*."""
        current_day = datetime.now(self._tz).date()
        if self.last_day != current_day:
            if self.last_day is not None:
                self.export_today_energy_kwh = 0.0
                self.grid_import_today_energy_kwh = 0.0
            self.last_day = current_day

        if self.last_t is None:
            self.last_t = t
            return

        dt_s = t - self.last_t
        if dt_s <= 0:
            self.last_t = t
            return

        dt_h = dt_s / SECONDS_PER_HOUR
        total_power_kw = sum(simulated_power_kw(t, site["capacity"], self._tz, self._profile) for site in self.sites)

        surplus_kw = max(0.0, total_power_kw - self.house_load_kw)
        deficit_kw = max(0.0, self.house_load_kw - total_power_kw)

        charge_kw = 0.0
        discharge_kw = 0.0

        if self.battery_capacity_kwh > 0 and surplus_kw > 0:
            remaining_kwh = max(0.0, self.battery_capacity_kwh - self.battery_energy_kwh)
            max_charge_by_capacity_kw = remaining_kwh / dt_h if dt_h > 0 else 0.0
            charge_kw = min(surplus_kw, self._charge_power_limit_kw(), max_charge_by_capacity_kw)
            self.battery_energy_kwh += charge_kw * dt_h
            surplus_kw -= charge_kw

        free_charge_kw = 0.0
        if self.free_charge_start_s <= t < self.free_charge_end_s and self.battery_capacity_kwh > 0:
            remaining_kwh = max(0.0, self.battery_capacity_kwh - self.battery_energy_kwh)
            max_charge_by_capacity_kw = remaining_kwh / dt_h if dt_h > 0 else 0.0
            available_charge_kw = max(0.0, self._charge_power_limit_kw() - charge_kw)
            free_charge_kw = min(available_charge_kw, max_charge_by_capacity_kw)
            self.battery_energy_kwh += free_charge_kw * dt_h

        if self.battery_capacity_kwh > 0 and deficit_kw > 0:
            max_discharge_by_energy_kw = self.battery_energy_kwh / dt_h if dt_h > 0 else 0.0
            discharge_kw = min(deficit_kw, self.battery_max_discharge_kw, max_discharge_by_energy_kw)
            self.battery_energy_kwh -= discharge_kw * dt_h

        self.battery_energy_kwh = min(
            self.battery_capacity_kwh,
            max(0.0, self.battery_energy_kwh),
        )
        battery_full = self.battery_capacity_kwh <= 0 or self.battery_energy_kwh >= self.battery_capacity_kwh - BATTERY_FULL_EPSILON_KWH

        export_kw = 0.0
        if battery_full and surplus_kw > 0:
            export_kw = min(surplus_kw * self.export_factor, self.export_limit_kw)

        self.export_power_kw = export_kw
        self.charge_power_kw = charge_kw
        self.discharge_power_kw = discharge_kw
        self.free_grid_charge_power_kw = free_charge_kw
        self.battery_power_kw = max(0.0, discharge_kw - charge_kw - free_charge_kw)
        self.grid_import_power_kw = max(0.0, deficit_kw - discharge_kw)

        self.export_energy_kwh += export_kw * dt_h
        self.export_today_energy_kwh += export_kw * dt_h
        self.charge_energy_kwh += charge_kw * dt_h
        self.discharge_energy_kwh += discharge_kw * dt_h
        self.grid_import_energy_kwh += self.grid_import_power_kw * dt_h
        self.grid_import_today_energy_kwh += self.grid_import_power_kw * dt_h
        self.free_grid_charge_energy_kwh += free_charge_kw * dt_h
        self.last_t = t
