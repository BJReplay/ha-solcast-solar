"""Climate normals and guidance payload generation for Solcast PV SimCity."""

import asyncio
from datetime import UTC, date, datetime, time, timedelta
from enum import IntEnum
from functools import partial
import json
import logging
import math
from pathlib import Path
import random
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.components.recorder import get_instance, history
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .sim_core import (
    API_KEY_SITES,
    BASE_FORECAST_SCALE,
    SimulationProfile,
    clip,
    cloud_profile,
    daily_cloudiness,
    daylight_seconds,
    effective_season_day,
    is_high_variability_locale,
    persistent_spell_adjustment,
    seed_to_int,
    shade_attenuation_factor,
)

_LOGGER = logging.getLogger(__name__)


class GuidanceCloudWindowMode(IntEnum):
    """Cloud-window calculation modes."""

    CLOCK = 0
    DAYLIGHT = 1


GUIDANCE_UPDATE_INTERVAL = timedelta(hours=1)
GUIDANCE_DAYS = 14
GUIDANCE_LOOKBACK_DAYS = 7
STORAGE_DIRNAME = "solcast_sim"
GUIDANCE_FILENAME = "guidance.json"
CLIMATE_CACHE_FILENAME = "climate_cache.json"
CLIMATE_CACHE_MAX_AGE_DAYS = 30

COORDINATE_MISS = 999.0
COORDINATE_MATCH_TOLERANCE_DEG = 0.01
SECONDS_PER_DAY = 86400
MONTHS_PER_YEAR = 12
MIN_MONTHLY_SAMPLES = 10
PERCENT_TO_RATIO = 100.0
CLIMATE_FETCH_TIMEOUT = 30

GUIDANCE_CLOUD_WINDOW_MODE = GuidanceCloudWindowMode.DAYLIGHT

MORNING_START_HOUR = 6
MORNING_END_HOUR = 12
AFTERNOON_START_HOUR = 12
AFTERNOON_END_HOUR = 18
HOUR_TO_CLOUD_FACTOR_INDEX = 12

SPELL_ADJUSTMENT_WEIGHT = 0.85
MIXED_CLOUDINESS_CAP_COOL_SEASON = 0.78
MIXED_CLOUDINESS_CAP_WARM_SEASON = 0.84
COOL_SEASONS = {"winter", "autumn", "spring"}

REGIME_ROLL_MORNING_WORSE_MAX = 0.22
REGIME_ROLL_AFTERNOON_WORSE_MAX = 0.44
REGIME_ROLL_BOTH_WORSE_MAX = 0.58
REGIME_ROLL_BOTH_BETTER_MAX = 0.72
REGIME_SHIFT_STRONG_MIN = 0.18
REGIME_SHIFT_STRONG_MAX = 0.38
REGIME_SHIFT_SOFT_MIN = 0.12
REGIME_SHIFT_SOFT_MAX = 0.28

CURVEBALL_BASE_PROBABILITY = 0.28
CURVEBALL_CLOUDINESS_PROBABILITY_WEIGHT = 0.20
CURVEBALL_STRENGTH_MIN = 0.08
CURVEBALL_STRENGTH_MAX = 0.30
CURVEBALL_CENTRE_HOUR_MIN = 8.0
CURVEBALL_CENTRE_HOUR_MAX = 16.5
CURVEBALL_WIDTH_HOURS_MIN = 1.4
CURVEBALL_WIDTH_HOURS_MAX = 4.2
CURVEBALL_POSITIVE_SIGN_PROBABILITY = 0.75

DEFAULT_SEASON_GAIN = 0.90
FORECAST_CONFIDENCE_CLOUDINESS_WEIGHT = 0.55
FORECAST_CONFIDENCE_INTRADAY_CONTRAST_WEIGHT = 0.35
FORECAST_CONFIDENCE_CURVEBALL_WEIGHT = 0.40
FORECAST_CONFIDENCE_VARIABILITY_WEIGHT = 0.15
FORECAST_CONFIDENCE_BADNESS_PENALTY_WEIGHT = 0.10
FORECAST_CONFIDENCE_MIXEDNESS_PENALTY_WEIGHT = 0.06
FORECAST_CONFIDENCE_MIN = 0.2
FORECAST_CONFIDENCE_MAX = 0.90

GUIDANCE_INTERVALS_PER_DAY = 48
GUIDANCE_INTERVAL_SECONDS = 1800
GUIDANCE_INTERVAL_MIDPOINT_SECONDS = 900
CLOUD_FACTOR_BUCKET_SECONDS = 60
GUIDANCE_SUBSAMPLES_PER_INTERVAL = 6
CLEAR_SKY_SHAPE_EXPONENT = 1.7

BIAS_TOWARDS_P10_SCALE = 1.05
SPREAD_SCALE_MIXEDNESS_WEIGHT = 1.2
SPREAD_SCALE_DIFFICULTY_WEIGHT = 0.35
SPREAD_SCALE_BASE = 0.75
SPREAD_SCALE_MIN = 0.6
SPREAD_SCALE_MAX = 2.3
ESTIMATE_SCALE_CLOUDINESS_WEIGHT = 0.45
ESTIMATE_SCALE_MIN = 0.25
ESTIMATE_SCALE_MAX = 1.1
BAD_WEATHER_P10_BIAS_WEIGHT = 0.85
BAD_WEATHER_ESTIMATE_TRIM_WEIGHT = 0.14
PV_TODAY_ENERGY_UNIQUE_ID = "solcast_sim_today_generation_energy"


def _period_cloudiness(cloud_factors: list[float], default_cloudiness: float, start_hour: float, end_hour: float) -> float:
    """Return average cloudiness for a local-hour window."""
    start_idx = max(0, int(start_hour * HOUR_TO_CLOUD_FACTOR_INDEX))
    end_idx = min(len(cloud_factors), int(end_hour * HOUR_TO_CLOUD_FACTOR_INDEX))
    window = cloud_factors[start_idx:end_idx]
    if not window:
        return default_cloudiness
    return clip(1.0 - (sum(window) / len(window)), 0.0, 1.0)


def _cloud_windows_for_day(
    mode: GuidanceCloudWindowMode,
    sunrise_s: float,
    sunset_s: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return (morning_window, afternoon_window) as (start_hour, end_hour)."""
    if mode is GuidanceCloudWindowMode.CLOCK:
        return (
            (float(MORNING_START_HOUR), float(MORNING_END_HOUR)),
            (float(AFTERNOON_START_HOUR), float(AFTERNOON_END_HOUR)),
        )

    sunrise_h = sunrise_s / 3600.0
    sunset_h = sunset_s / 3600.0
    split_h = (sunrise_h + sunset_h) / 2.0
    return ((sunrise_h, split_h), (split_h, sunset_h))


def load_climate_cache(path: Path, lat: float, lon: float) -> list[dict[str, float]] | None:
    """Load cached monthly climate normals if present, current, and matching location."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (
            abs(data.get("latitude", COORDINATE_MISS) - lat) > COORDINATE_MATCH_TOLERANCE_DEG
            or abs(data.get("longitude", COORDINATE_MISS) - lon) > COORDINATE_MATCH_TOLERANCE_DEG
        ):
            return None
        fetched = datetime.fromisoformat(data["fetched_at"])
        age_seconds = (datetime.now().astimezone() - fetched).total_seconds()
        if age_seconds > CLIMATE_CACHE_MAX_AGE_DAYS * SECONDS_PER_DAY:
            return None
        months: list[dict[str, float]] = data.get("months", [])
        if len(months) != MONTHS_PER_YEAR:
            return None
    except Exception:  # noqa: BLE001
        return None
    else:
        return months


def save_climate_cache(path: Path, lat: float, lon: float, months: list[dict[str, float]]) -> None:
    """Persist monthly climate normals to cache file atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "fetched_at": datetime.now().astimezone().isoformat(),
        "months": [{"mean": round(m["mean"], 4), "std": round(m["std"], 4)} for m in months],
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


async def async_fetch_climate_normals(hass: HomeAssistant, lat: float, lon: float) -> list[dict[str, float]] | None:
    """Fetch 5-year daily cloud cover from Open-Meteo archive and compute monthly stats."""
    now_year = datetime.now().year
    end_year = now_year - 1
    start_year = end_year - 4
    url = (
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat:.4f}&longitude={lon:.4f}"
        f"&start_date={start_year}-01-01&end_date={end_year}-12-31"
        "&daily=cloud_cover_mean&timezone=UTC"
    )
    try:
        session = async_get_clientsession(hass)
        async with asyncio.timeout(CLIMATE_FETCH_TIMEOUT):
            async with session.get(url) as resp:
                if resp.status != 200:
                    _LOGGER.debug(
                        "Climate normals fetch returned HTTP %s for configured location",
                        resp.status,
                    )
                    return None
                data = await resp.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("Climate normals fetch failed for configured location: %s", exc)
        return None

    daily = data.get("daily", {})
    dates: list[str] = daily.get("time", [])
    values: list[float | None] = daily.get("cloud_cover_mean", [])

    monthly_buckets: list[list[float]] = [[] for _ in range(12)]
    for date_str, val in zip(dates, values, strict=True):
        if val is None:
            continue
        idx = int(date_str[5:7]) - 1
        monthly_buckets[idx].append(float(val) / PERCENT_TO_RATIO)

    if any(len(bucket) < MIN_MONTHLY_SAMPLES for bucket in monthly_buckets):
        _LOGGER.debug("Climate normals: insufficient data for configured location")
        return None

    result: list[dict[str, float]] = []
    for bucket in monthly_buckets:
        mean = sum(bucket) / len(bucket)
        variance = sum((x - mean) ** 2 for x in bucket) / len(bucket)
        result.append({"mean": mean, "std": variance**0.5})
    return result


def _interval_generation_fraction(
    profile: SimulationProfile,
    day: date,
    minute: int,
    season_gain: float,
) -> float:
    """Return a Solcast-style estimated-actuals fraction for a 30-minute interval."""
    effective_day, season = effective_season_day(day, profile.season, profile.latitude)
    cloud_factors = cloud_profile(profile, effective_day, season)
    daylight_s = daylight_seconds(effective_day, profile.latitude, season)
    sunrise_s = (24 * 3600 - daylight_s) / 2
    sunset_s = sunrise_s + daylight_s
    interval_start_sod = minute * GUIDANCE_INTERVAL_SECONDS
    samples: list[float] = []
    for idx in range(GUIDANCE_SUBSAMPLES_PER_INTERVAL):
        sample_sod = interval_start_sod + (idx + 0.5) * (GUIDANCE_INTERVAL_SECONDS / GUIDANCE_SUBSAMPLES_PER_INTERVAL)
        if sample_sod <= sunrise_s or sample_sod >= sunset_s:
            samples.append(0.0)
            continue

        phase = (sample_sod - sunrise_s) / max(1.0, daylight_s)
        clear_sky = math.sin(math.pi * phase) ** CLEAR_SKY_SHAPE_EXPONENT
        ci = int(clip(float(sample_sod // CLOUD_FACTOR_BUCKET_SECONDS), 0.0, float(len(cloud_factors) - 1)))
        samples.append(BASE_FORECAST_SCALE * season_gain * clear_sky * cloud_factors[ci])

    if not samples:
        return 0.0
    return clip(sum(samples) / len(samples), 0.0, BASE_FORECAST_SCALE)


def _compute_actuals_jitter(day_str: str, slot: int, uncertainty_pct: float) -> float:
    """Return deterministic, unbiased jitter for estimated actuals."""
    if uncertainty_pct <= 0.0:
        return 0.0
    seed = (sum(ord(c) for c in day_str) * 31 + slot * 7919) & 0xFFFFFFFF
    rng = random.Random(seed)
    u1 = max(1e-9, rng.random())
    u2 = rng.random()
    z = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
    return z * (uncertainty_pct / 100.0)


def _apply_estimated_actuals_jitter(value: float, day_str: str, slot: int, uncertainty_pct: float) -> float:
    """Apply jitter to a generation fraction."""
    if value <= 0.0:
        return 0.0
    jitter = _compute_actuals_jitter(day_str, slot, uncertainty_pct)
    return clip(value * (1.0 + jitter), 0.0, BASE_FORECAST_SCALE)


def _estimated_actuals_from_recorder(
    day_str: str,
    uncertainty_pct: float,
    recorder_values: list[float | None],
) -> list[float]:
    """Build estimated actuals from recorder values with jitter."""
    result: list[float] = []
    for slot, recorder_value in enumerate(recorder_values):
        if recorder_value is None or recorder_value <= 0.0:
            result.append(0.0)
            continue
        jittered = _apply_estimated_actuals_jitter(recorder_value, day_str, slot, uncertainty_pct)
        result.append(round(jittered, 5))
    return result


async def _async_recorder_historic_estimated_actuals(
    hass: HomeAssistant,
    tz: ZoneInfo,
    total_site_capacity_kw: float,
    profile: SimulationProfile | None = None,
) -> dict[str, list[float | None]]:
    """Build historic 30-minute estimated actuals from recorder energy statistics."""
    if total_site_capacity_kw <= 0.0 or "recorder" not in hass.config.components:
        return {}

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", "solcast_sim", PV_TODAY_ENERGY_UNIQUE_ID)
    if entity_id is None:
        return {}

    local_today = datetime.now(tz).date()
    start_local = datetime.combine(local_today - timedelta(days=GUIDANCE_LOOKBACK_DAYS), time.min, tzinfo=tz)
    end_local = datetime.combine(local_today + timedelta(days=1), time.min, tzinfo=tz)
    start_utc = start_local.astimezone(UTC)
    end_utc = end_local.astimezone(UTC)

    history_rows_map = await get_instance(hass).async_add_executor_job(
        partial(
            history.state_changes_during_period,
            hass,
            start_utc,
            end_utc,
            entity_id,
            True,
            False,
            None,
            True,
        )
    )

    rows = history_rows_map.get(entity_id)
    if not rows:
        return {}

    slot_energy_by_day: dict[str, list[float | None]] = {}
    previous_value: float | None = None
    previous_ts: float | None = None
    for row in rows:
        try:
            row_value = float(row.state)
        except (ValueError, TypeError):
            continue
        row_time = row.last_updated
        if row_time is None:
            continue
        row_ts = row_time.timestamp()

        if previous_value is None:
            previous_value = row_value
            previous_ts = row_ts
            continue

        if row_value < previous_value:
            # Daily total sensor reset; treat new value as post-reset accumulation.
            delta_kwh = row_value
        else:
            delta_kwh = row_value - previous_value
        previous_value = row_value

        if delta_kwh <= 0.0:
            previous_ts = row_ts
            continue

        # Un-shade: Reverse the local shade attenuation.
        if profile is not None:
            delta_mid_ts = (previous_ts + row_ts) / 2.0 if previous_ts is not None else row_ts
            mid_local = datetime.fromtimestamp(delta_mid_ts, tz=tz)
            shade_factor = shade_attenuation_factor(mid_local, profile)
            # Clamp to a minimum to prevent division issues at very low sun angles.
            shade_factor = max(shade_factor, 0.05)
            if shade_factor < 1.0:
                delta_kwh = delta_kwh / shade_factor
        previous_ts = row_ts

        local_time = row_time.astimezone(tz)
        day_key = local_time.date().isoformat()
        slot = int((local_time.hour * 60 + local_time.minute) / 30)
        if slot < 0 or slot >= GUIDANCE_INTERVALS_PER_DAY:
            continue

        day_slots = slot_energy_by_day.setdefault(day_key, [None] * GUIDANCE_INTERVALS_PER_DAY)
        existing = day_slots[slot]
        day_slots[slot] = delta_kwh if existing is None else (existing + delta_kwh)

    recorder_actuals: dict[str, list[float | None]] = {}
    for day_key, slot_energies in slot_energy_by_day.items():
        slot_values: list[float | None] = []
        for slot_energy in slot_energies:
            if slot_energy is None:
                slot_values.append(None)
                continue
            # 30-minute slot energy to average kW.
            avg_power_kw = slot_energy * 2.0
            fraction = clip(avg_power_kw / total_site_capacity_kw, 0.0, BASE_FORECAST_SCALE)
            slot_values.append(round(fraction, 5))
        recorder_actuals[day_key] = slot_values

    return recorder_actuals


def build_guidance_payload(
    profile: SimulationProfile,
    tz: ZoneInfo,
    days: int = GUIDANCE_DAYS,
    recorder_historic_actuals: dict[str, list[float | None]] | None = None,
) -> dict[str, Any]:
    """Build a rolling day-level guidance payload used by the WSGI simulator."""
    mode = GUIDANCE_CLOUD_WINDOW_MODE
    local_today = datetime.now(tz).date()
    payload_days: dict[str, dict[str, Any]] = {}

    if is_high_variability_locale(profile.latitude, profile.longitude):
        season_gain_map = {
            "spring": 0.75,
            "summer": 0.88,
            "autumn": 0.58,
            "winter": 0.42,
        }
    else:
        season_gain_map = {
            "spring": 0.95,
            "summer": 1.00,
            "autumn": 0.85,
            "winter": 0.70,
        }

    for idx in range(-GUIDANCE_LOOKBACK_DAYS, days):
        day = local_today + timedelta(days=idx)
        effective_day, season = effective_season_day(day, profile.season, profile.latitude)
        base_cloudiness = daily_cloudiness(profile, effective_day, season)
        spell_adjustment, spell_regime = persistent_spell_adjustment(profile, effective_day, season, base_cloudiness)
        cloudiness = clip(base_cloudiness + spell_adjustment, 0.0, 0.95)
        if spell_regime == "mixed":
            mixed_cap = MIXED_CLOUDINESS_CAP_COOL_SEASON if season in COOL_SEASONS else MIXED_CLOUDINESS_CAP_WARM_SEASON
            cloudiness = min(cloudiness, mixed_cap)

        daylight_s = daylight_seconds(effective_day, profile.latitude, season)
        sunrise_s = (24 * 3600 - daylight_s) / 2
        sunset_s = sunrise_s + daylight_s
        (morning_window, afternoon_window) = _cloud_windows_for_day(mode, sunrise_s, sunset_s)

        cloud_factors = cloud_profile(profile, effective_day, season)
        day_seed = f"{profile.random_seed}|{effective_day.isoformat()}|{profile.latitude:.4f}|{profile.longitude:.4f}|{season}|guidance"
        day_rng = random.Random(seed_to_int(day_seed))

        morning_cloudiness = clip(
            _period_cloudiness(cloud_factors, cloudiness, morning_window[0], morning_window[1])
            + spell_adjustment * SPELL_ADJUSTMENT_WEIGHT,
            0.0,
            1.0,
        )
        afternoon_cloudiness = clip(
            _period_cloudiness(cloud_factors, cloudiness, afternoon_window[0], afternoon_window[1])
            + spell_adjustment * SPELL_ADJUSTMENT_WEIGHT,
            0.0,
            1.0,
        )

        regime_roll = day_rng.random()
        if regime_roll < REGIME_ROLL_MORNING_WORSE_MAX:
            morning_cloudiness = clip(
                morning_cloudiness + day_rng.uniform(REGIME_SHIFT_STRONG_MIN, REGIME_SHIFT_STRONG_MAX),
                0.0,
                1.0,
            )
            afternoon_cloudiness = clip(
                afternoon_cloudiness - day_rng.uniform(REGIME_SHIFT_SOFT_MIN, REGIME_SHIFT_SOFT_MAX),
                0.0,
                1.0,
            )
        elif regime_roll < REGIME_ROLL_AFTERNOON_WORSE_MAX:
            morning_cloudiness = clip(
                morning_cloudiness - day_rng.uniform(REGIME_SHIFT_SOFT_MIN, REGIME_SHIFT_SOFT_MAX),
                0.0,
                1.0,
            )
            afternoon_cloudiness = clip(
                afternoon_cloudiness + day_rng.uniform(REGIME_SHIFT_STRONG_MIN, REGIME_SHIFT_STRONG_MAX),
                0.0,
                1.0,
            )
        elif regime_roll < REGIME_ROLL_BOTH_WORSE_MAX:
            boost = day_rng.uniform(REGIME_SHIFT_SOFT_MIN, REGIME_SHIFT_SOFT_MAX)
            morning_cloudiness = clip(morning_cloudiness + boost, 0.0, 1.0)
            afternoon_cloudiness = clip(afternoon_cloudiness + boost, 0.0, 1.0)
        elif regime_roll < REGIME_ROLL_BOTH_BETTER_MAX:
            drop = day_rng.uniform(REGIME_SHIFT_SOFT_MIN, REGIME_SHIFT_SOFT_MAX)
            morning_cloudiness = clip(morning_cloudiness - drop, 0.0, 1.0)
            afternoon_cloudiness = clip(afternoon_cloudiness - drop, 0.0, 1.0)

        has_curveball = day_rng.random() < (CURVEBALL_BASE_PROBABILITY + cloudiness * CURVEBALL_CLOUDINESS_PROBABILITY_WEIGHT)
        curveball_strength = day_rng.uniform(CURVEBALL_STRENGTH_MIN, CURVEBALL_STRENGTH_MAX) if has_curveball else 0.0
        curveball_centre_hour = day_rng.uniform(CURVEBALL_CENTRE_HOUR_MIN, CURVEBALL_CENTRE_HOUR_MAX)
        curveball_width_hours = day_rng.uniform(CURVEBALL_WIDTH_HOURS_MIN, CURVEBALL_WIDTH_HOURS_MAX)
        curveball_sign = 1.0 if day_rng.random() < CURVEBALL_POSITIVE_SIGN_PROBABILITY else -1.0
        season_gain = season_gain_map.get(season, DEFAULT_SEASON_GAIN)
        intraday_contrast = abs(morning_cloudiness - afternoon_cloudiness)
        weather_mixedness = clip(1.0 - abs(cloudiness - 0.5) / 0.5, 0.0, 1.0)
        forecast_confidence = clip(
            1.0
            - (
                cloudiness * FORECAST_CONFIDENCE_CLOUDINESS_WEIGHT
                + intraday_contrast * FORECAST_CONFIDENCE_INTRADAY_CONTRAST_WEIGHT
                + curveball_strength * FORECAST_CONFIDENCE_CURVEBALL_WEIGHT
                + profile.cloud_variability * FORECAST_CONFIDENCE_VARIABILITY_WEIGHT
                + cloudiness * FORECAST_CONFIDENCE_BADNESS_PENALTY_WEIGHT
                + weather_mixedness * FORECAST_CONFIDENCE_MIXEDNESS_PENALTY_WEIGHT
            ),
            FORECAST_CONFIDENCE_MIN,
            FORECAST_CONFIDENCE_MAX,
        )
        weather_difficulty = clip((cloudiness + (1.0 - forecast_confidence)) / 2.0, 0.0, 1.0)
        weather_badness = clip(cloudiness * 0.65 + (1.0 - forecast_confidence) * 0.35, 0.0, 1.0)

        intervals: list[float] = [
            round(_interval_generation_fraction(profile, day, slot, season_gain), 5) for slot in range(GUIDANCE_INTERVALS_PER_DAY)
        ]

        recorder_day_values = recorder_historic_actuals.get(day.isoformat()) if recorder_historic_actuals else None
        estimated_actuals = (
            _estimated_actuals_from_recorder(day.isoformat(), profile.estimated_actuals_uncertainty_pct, recorder_day_values)
            if recorder_day_values is not None
            else []
        )

        payload_days[day.isoformat()] = {
            "cloudiness": round(cloudiness, 4),
            "spell_regime": spell_regime,
            "spell_adjustment": round(spell_adjustment, 4),
            "morning_cloudiness": round(morning_cloudiness, 4),
            "afternoon_cloudiness": round(afternoon_cloudiness, 4),
            "bias_towards_p10": round(
                clip(weather_badness * BAD_WEATHER_P10_BIAS_WEIGHT * BIAS_TOWARDS_P10_SCALE, 0.0, 1.0),
                4,
            ),
            "spread_scale": round(
                clip(
                    SPREAD_SCALE_BASE
                    + weather_mixedness * SPREAD_SCALE_MIXEDNESS_WEIGHT
                    + weather_difficulty * SPREAD_SCALE_DIFFICULTY_WEIGHT,
                    SPREAD_SCALE_MIN,
                    SPREAD_SCALE_MAX,
                ),
                4,
            ),
            "estimate_scale": round(
                clip(
                    (1.0 - cloudiness * ESTIMATE_SCALE_CLOUDINESS_WEIGHT)
                    * season_gain
                    * (1.0 - weather_badness * BAD_WEATHER_ESTIMATE_TRIM_WEIGHT),
                    ESTIMATE_SCALE_MIN,
                    ESTIMATE_SCALE_MAX,
                ),
                4,
            ),
            "season_gain": round(season_gain, 4),
            "daylight_seconds": round(daylight_s, 1),
            "sunrise_seconds": round(sunrise_s, 1),
            "sunset_seconds": round(sunset_s, 1),
            "curveball_strength": round(curveball_strength, 4),
            "curveball_centre_hour": round(curveball_centre_hour, 2),
            "curveball_width_hours": round(curveball_width_hours, 2),
            "curveball_sign": round(curveball_sign, 1),
            "forecast_confidence": round(forecast_confidence, 4),
            "effective_day": effective_day.isoformat(),
            "effective_season": season,
            "intervals": intervals,
            "estimated_actuals": estimated_actuals,
            "recorder_backed": recorder_day_values is not None,
        }

    return {
        "generated_at": datetime.now(tz).isoformat(),
        "timezone": str(tz),
        "season_mode": profile.season,
        "cloud_window_mode": mode.name.lower(),
        "estimated_actuals_uncertainty_pct": round(profile.estimated_actuals_uncertainty_pct, 4),
        "latitude": round(profile.latitude, 6),
        "longitude": round(profile.longitude, 6),
        "days": payload_days,
    }


def write_guidance_payload_to_file(path: Path, payload: dict[str, Any]) -> None:
    """Write guidance payload atomically to JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def build_storage_path(config_dir: Path, filename: str) -> Path:
    """Return a SimCity storage path under config/solcast_sim/."""
    return config_dir / STORAGE_DIRNAME / filename


async def async_write_guidance_file(
    hass: HomeAssistant,
    profile: SimulationProfile,
    tz: ZoneInfo,
    sites: list[dict[str, Any]] | None = None,
) -> None:
    """Generate and persist rolling guidance JSON for the WSGI simulator."""
    sites_in_use = sites if sites is not None else [site for api_data in API_KEY_SITES.values() for site in api_data["sites"]]
    total_site_capacity_kw = sum(float(site.get("capacity", 0.0)) for site in sites_in_use)
    recorder_historic_actuals = await _async_recorder_historic_estimated_actuals(
        hass,
        tz,
        total_site_capacity_kw,
        profile,
    )
    payload = await hass.async_add_executor_job(
        partial(build_guidance_payload, profile, tz, recorder_historic_actuals=recorder_historic_actuals)
    )
    guidance_path = build_storage_path(Path(hass.config.config_dir), GUIDANCE_FILENAME)
    await hass.async_add_executor_job(write_guidance_payload_to_file, guidance_path, payload)
