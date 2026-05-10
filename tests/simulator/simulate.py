"""Simulated data for Solcast Solar integration."""

import contextlib
import datetime
from datetime import datetime as dt, timedelta
import json
import math
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

API_KEY_SITES: dict[str, Any] = {
    "1": {
        "sites": [
            {
                "resource_id": "1111-1111-1111-1111",
                "name": "First Site",
                "latitude": -11.11111,
                "longitude": 111.1111,
                "install_date": "2024-01-01T00:00:00+00:00",
                "loss_factor": 0.99,
                "capacity": 5.0,
                "capacity_dc": 6.2,
                "azimuth": 66,
                "tilt": 30,
                "tags": ["tag1", "tag2"],
            },
            {
                "resource_id": "2222-2222-2222-2222",
                "name": "Second Site",
                "latitude": -11.11111,
                "longitude": 111.1111,
                "install_date": "2024-01-01T00:00:00+00:00",
                "loss_factor": 0.99,
                "capacity": 3.0,
                "capacity_dc": 4.2,
                "azimuth": 66,
                "tilt": 30,
                "tags": ["tag1", "tag3"],
            },
        ],
        "counter": 0,
    },
    "10": {
        "sites": [
            {
                "resource_id": "1111-1111-1111-1111",
                "name": "First Site",
                "latitude": -11.11111,
                "longitude": 111.1111,
                "install_date": "2024-01-01T00:00:00+00:00",
                "loss_factor": 0.99,
                "capacity": 5.0,
                "capacity_dc": 6.2,
                "azimuth": 66,
                "tilt": 30,
                "tags": ["tag1", "tag2"],
            },
            {
                "resource_id": "2222-2222-2222-2222",
                "name": "Second Site",
                "latitude": -11.11111,
                "longitude": 111.1111,
                "install_date": "2024-01-01T00:00:00+00:00",
                "loss_factor": 0.99,
                "capacity": 3.0,
                "capacity_dc": 4.2,
                "azimuth": 66,
                "tilt": 30,
                "tags": ["tag1", "tag3"],
            },
        ],
        "counter": 0,
    },
    "2": {
        "sites": [
            {
                "resource_id": "3333-3333-3333-3333",
                "name": "Third Site",
                "latitude": -11.11111,
                "longitude": 111.1111,
                "install_date": "2024-01-01T00:00:00+00:00",
                "loss_factor": 0.99,
                "capacity": 3.0,
                "capacity_dc": 3.5,
                "azimuth": 66,
                "tilt": 30,
                "tags": ["tag1", "tag4"],
            },
        ],
        "counter": 0,
    },
    "3": {
        "sites": [
            {
                "resource_id": "4444-4444-4444-4444",
                "name": "Fourth Site",
                "latitude": -11.11111,
                "longitude": 111.1111,
                "install_date": "2024-01-01T00:00:00+00:00",
                "loss_factor": 0.99,
                "capacity": 4.5,
                "capacity_dc": 5.0,
                "azimuth": 66,
                "tilt": 30,
                "tags": ["tag1", "tag5"],
            },
            {
                "resource_id": "5555-5555-5555-5555",
                "name": "Fifth Site",
                "latitude": -11.11111,
                "longitude": 111.1111,
                "install_date": "2024-01-01T00:00:00+00:00",
                "loss_factor": 0.99,
                "capacity": 3.2,
                "capacity_dc": 3.7,
                "azimuth": 66,
                "tilt": 30,
                "tags": ["tag1", "tag6"],
            },
            {
                "resource_id": "6666-6666-6666-6666",
                "name": "Sixth Site",
                "latitude": -11.11111,
                "longitude": 111.1111,
                "install_date": "2024-01-01T00:00:00+00:00",
                "loss_factor": 0.99,
                "capacity": 4.2,
                "capacity_dc": 4.8,
                "azimuth": 66,
                "tilt": 30,
                "tags": ["tag1", "tag7"],
            },
        ],
        "counter": 0,
    },
    "aaaa-aaaa": {
        "sites": [
            {
                "resource_id": "7777-7777-7777-7777",
                "name": "Seventh Site",
                "latitude": -11.11111,
                "longitude": 111.1111,
                "install_date": "2024-01-01T00:00:00+00:00",
                "loss_factor": 0.99,
                "capacity": 3.0,
                "capacity_dc": 3.5,
                "azimuth": 66,
                "tilt": 30,
                "tags": ["tag1", "tag2"],
            },
        ],
        "counter": 0,
    },
    "no_sites": {
        "sites": [],
        "counter": 0,
    },
}
FORECAST = 0.9
FORECAST_10 = 0.75
FORECAST_90 = 1.0
GENERATION_FACTOR: list[float] = [
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0.01,
    0.025,
    0.04,
    0.075,
    0.11,
    0.17,
    0.26,
    0.38,
    0.52,
    0.65,
    0.8,
    0.9,
    0.97,
    1,
    1,
    0.97,
    0.9,
    0.8,
    0.65,
    0.52,
    0.38,
    0.26,
    0.17,
    0.11,
    0.075,
    0.04,
    0.025,
    0.01,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
]
TIMEZONE = ZoneInfo("Australia/Melbourne")

INTERVAL_MINUTES = 30
HALF_HOURS_PER_HOUR = 2
INTERVALS_PER_DAY = 48
INTERVAL_ISO_PERIOD = "PT30M"
SECONDS_PER_HOUR = 3600.0
SECONDS_PER_DAY = 86400.0
SECONDS_PER_DAY_LAST = 86399.0
HALF_INTERVAL_MINUTES = INTERVAL_MINUTES // 2

MIDPOINT_BLEND_START_HOUR = 11.0
MIDPOINT_BLEND_END_HOUR = 13.0
MODIFIED_OUTPUT_START_HOUR = 16
MODIFIED_LATE_DAY_MULTIPLIER = 0.4
GENERATION_FACTOR_TAPER_START_INTERVAL = 32
DST_INTERVAL_SHIFT = 2
DST_COMPARISON_HOURS = 1
DST_FIRST_SHIFTED_INTERVAL = 1

# Guidance defaults and bounds for non-deterministic forecast shaping.
GUIDANCE_CLOUDINESS_DEFAULT = 0.0
GUIDANCE_CLOUDINESS_MIN = 0.0
GUIDANCE_CLOUDINESS_MAX = 1.0
GUIDANCE_FORECAST_CONFIDENCE_MIN = 0.2
GUIDANCE_FORECAST_CONFIDENCE_MAX = 0.98
GUIDANCE_FORECAST_CONFIDENCE_CLOUDINESS_FACTOR = 0.6
GUIDANCE_CURVEBALL_STRENGTH_DEFAULT = 0.0
GUIDANCE_CURVEBALL_STRENGTH_MIN = 0.0
GUIDANCE_CURVEBALL_STRENGTH_MAX = 0.6
GUIDANCE_CURVEBALL_CENTRE_DEFAULT_HOUR = 12.0
GUIDANCE_CURVEBALL_CENTRE_MIN_HOUR = 0.0
GUIDANCE_CURVEBALL_CENTRE_MAX_HOUR = 24.0
GUIDANCE_CURVEBALL_WIDTH_DEFAULT_HOURS = 2.0
GUIDANCE_CURVEBALL_WIDTH_MIN_HOURS = 0.5
GUIDANCE_CURVEBALL_WIDTH_MAX_HOURS = 6.0
GUIDANCE_CURVEBALL_SIGN_DEFAULT_P50 = 1.0
GUIDANCE_CURVEBALL_SIGN_DEFAULT_FALLBACK = -1.0
GUIDANCE_CURVEBALL_SIGN_MIN = -1.0
GUIDANCE_CURVEBALL_SIGN_MAX = 1.0
GUIDANCE_SPREAD_SCALE_DEFAULT = 1.0
GUIDANCE_SPREAD_SCALE_CLOUDINESS_FACTOR = 0.6
GUIDANCE_SPREAD_SCALE_MIN = 0.5
GUIDANCE_SPREAD_SCALE_MAX = 2.5
GUIDANCE_ESTIMATE_SCALE_DEFAULT = 1.0
GUIDANCE_ESTIMATE_SCALE_CLOUDINESS_FACTOR = 0.25
GUIDANCE_ESTIMATE_SCALE_MIN = 0.2
GUIDANCE_ESTIMATE_SCALE_MAX = 1.1

# Skill-wave and deterministic day-hash model constants.
DAY_HASH_MODULUS = 113
SKILL_AMPLITUDE_BASE = 0.06
SKILL_AMPLITUDE_CLOUDINESS_FACTOR = 0.14
SKILL_WAVE_PRIMARY_SLOT_FREQ = 0.63
SKILL_WAVE_PRIMARY_DAY_CYCLES = 2.0
SKILL_WAVE_SECONDARY_WEIGHT = 0.6
SKILL_WAVE_SECONDARY_SLOT_FREQ = 0.19
SKILL_WAVE_SECONDARY_PHASE_SHIFT = 1.3
SKILL_WAVE_SECONDARY_DAY_SCALE = 3.0
SKILL_WAVE_NORMALISER = 1.6
OPTIMISM_BIAS_CLOUDINESS_FACTOR = 0.08

# Surprise-event profile and intraday correction tuning.
GAUSSIAN_EXP_SCALE = -0.5
SURPRISE_BASE_FACTOR = 0.16
SURPRISE_CLOUDINESS_FACTOR = 0.24
INTRADAY_CORRECTION_START_HOUR = 9.0
INTRADAY_CORRECTION_WINDOW_HOURS = 7.0
SKILL_CORRECTION_MAX_FACTOR = 0.45
SURPRISE_CORRECTION_MAX_FACTOR = 0.18

# Bias and spread shaping bounds for p10/p50/p90 synthesis.
P50_BIAS_MIN = 0.55
P50_BIAS_MAX = 1.75
WEATHER_MIXEDNESS_CENTER = 0.5
WEATHER_MIXEDNESS_HALF_RANGE = 0.5
WEATHER_BADNESS_CLOUDINESS_WEIGHT = 0.65
WEATHER_BADNESS_UNCERTAINTY_WEIGHT = 0.35
BAND_WIDTH_BASE = 0.03
BAND_WIDTH_UNCERTAINTY_FACTOR = 0.44
BAND_WIDTH_MIXEDNESS_FACTOR = 0.09
BAND_WIDTH_SURPRISE_FACTOR = 0.18
BAND_WIDTH_MIN = 0.025
BAND_WIDTH_MAX = 0.68
DOWN_SPAN_SKEW_BASE = 0.92
DOWN_SPAN_SKEW_WEATHER_FACTOR = 0.42
DOWN_SPAN_SKEW_SURPRISE_FACTOR = 0.28
DOWN_SPAN_SKEW_MIN = 0.55
DOWN_SPAN_SKEW_MAX = 1.75
UP_SPAN_SKEW_BASE = 0.74
UP_SPAN_SKEW_GOOD_WEATHER_FACTOR = 0.30
UP_SPAN_SKEW_SURPRISE_FACTOR = 0.24
UP_SPAN_SKEW_MIN = 0.45
UP_SPAN_SKEW_MAX = 1.55
MIN_TOTAL_SPAN_BASE = 0.02
MIN_TOTAL_SPAN_UNCERTAINTY_FACTOR = 0.20
NUMERIC_EPSILON = 1e-9

# Fallback daylight model constants.
BAD_WEATHER_P50_TO_P10_SHIFT_FACTOR = 0.75
DAYLIGHT_CURVE_EXPONENT = 1.7
WEATHER_CURVE_CLOUDINESS_FACTOR = 0.65
WEATHER_CURVE_MIN = 0.25
WEATHER_CURVE_MAX = 1.05
INTERVAL_UNCERTAINTY_BASE = 0.70
INTERVAL_UNCERTAINTY_SPREAD_FACTOR = 0.45
INTERVAL_UNCERTAINTY_CLOUDINESS_FACTOR = 0.16
INTERVAL_UNCERTAINTY_CURVEBALL_FACTOR = 0.20
INTERVAL_UNCERTAINTY_MIN = 0.03
INTERVAL_UNCERTAINTY_MAX = 0.98
BAND_RATIO_BASE = 0.035
BAND_RATIO_UNCERTAINTY_FACTOR = 0.62
BAND_RATIO_MIN = 0.03
BAND_RATIO_MAX = 0.78
FALLBACK_DOWN_SKEW_BASE = 0.92
FALLBACK_DOWN_SKEW_P10_BIAS_FACTOR = 0.38
FALLBACK_DOWN_SKEW_CLOUDINESS_FACTOR = 0.12
FALLBACK_DOWN_SKEW_CURVEBALL_FACTOR = 0.28
FALLBACK_DOWN_SKEW_MIN = 0.55
FALLBACK_DOWN_SKEW_MAX = 1.80
FALLBACK_UP_SKEW_BASE = 0.72
FALLBACK_UP_SKEW_P10_BIAS_FACTOR = 0.24
FALLBACK_UP_SKEW_GOOD_WEATHER_FACTOR = 0.10
FALLBACK_UP_SKEW_CURVEBALL_FACTOR = 0.22
FALLBACK_UP_SKEW_MIN = 0.45
FALLBACK_UP_SKEW_MAX = 1.55
MIN_DOWN_SEPARATION_BASE = 0.015
MIN_DOWN_SEPARATION_UNCERTAINTY_FACTOR = 0.18
SUNRISE_DEFAULT_HOUR = 6.0
SUNSET_DEFAULT_HOUR = 18.0
DEFAULT_ACTUALS_UNCERTAINTY_PCT = 2.2


class SimulatedSolcast:
    """Simulated Solcast API."""

    modified_actuals: bool = False

    def __init__(self) -> None:
        """Initialise the API."""
        self.timezone: ZoneInfo = TIMEZONE
        self.cached_forecasts: dict[str, Any] = {}
        self.forecast_guidance: dict[str, dict[str, float]] = {}
        self.interval_guidance: dict[str, list[float]] = {}
        self.actuals_uncertainty_pct: float = DEFAULT_ACTUALS_UNCERTAINTY_PCT

    def set_actuals_uncertainty(self, uncertainty_pct: float) -> None:
        """Set the estimated actuals jitter percentage."""
        self.actuals_uncertainty_pct = max(0.0, float(uncertainty_pct))

    def set_forecast_guidance(self, guidance: dict[str, dict[str, float]]) -> None:
        """Set in-memory forecast guidance keyed by local date (YYYY-MM-DD)."""
        self.forecast_guidance = guidance
        self.cached_forecasts.clear()

    def load_forecast_guidance_file(self, file_path: str) -> None:
        """Load forecast guidance from JSON and clear cached forecast responses."""
        with Path(file_path).open(encoding="utf-8") as fp:
            payload = json.load(fp)

        if not isinstance(payload, dict):
            self.interval_guidance = {}
            self.set_actuals_uncertainty(DEFAULT_ACTUALS_UNCERTAINTY_PCT)
            self.set_forecast_guidance({})
            return

        uncertainty_pct = payload.get("estimated_actuals_uncertainty_pct", DEFAULT_ACTUALS_UNCERTAINTY_PCT)
        if isinstance(uncertainty_pct, (float, int)):
            self.set_actuals_uncertainty(float(uncertainty_pct))
        else:
            self.set_actuals_uncertainty(DEFAULT_ACTUALS_UNCERTAINTY_PCT)

        timezone_name = payload.get("timezone")
        if isinstance(timezone_name, str) and timezone_name:
            with contextlib.suppress(Exception):
                self.set_time_zone(ZoneInfo(timezone_name))

        days = payload.get("days", {})
        if isinstance(days, dict):
            normalised: dict[str, dict[str, float]] = {}
            intervals: dict[str, list[float]] = {}
            for day, values in days.items():
                if not isinstance(day, str) or not isinstance(values, dict):
                    continue
                normalised[day] = {str(k): float(v) for k, v in values.items() if isinstance(k, str) and isinstance(v, (float, int))}
                raw_ivs = values.get("intervals")
                if isinstance(raw_ivs, list) and len(raw_ivs) == INTERVALS_PER_DAY:
                    intervals[day] = [float(v) for v in raw_ivs]
            self.interval_guidance = intervals
            self.set_forecast_guidance(normalised)
            return

        self.interval_guidance = {}
        self.set_actuals_uncertainty(DEFAULT_ACTUALS_UNCERTAINTY_PCT)
        self.set_forecast_guidance({})

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        """Clamp a value between lower and upper bounds."""
        return max(lower, min(upper, value))

    def _interval_slot(self, period_end: dt, minute: int) -> tuple[str, int, float]:
        """Return local day key, 30-minute slot index, and midpoint hour."""
        local_dt = (period_end + timedelta(minutes=minute * INTERVAL_MINUTES)).astimezone(self.timezone)
        midpoint = local_dt - timedelta(minutes=HALF_INTERVAL_MINUTES)
        local_day = local_dt.date().isoformat()
        slot = midpoint.hour * HALF_HOURS_PER_HOUR + midpoint.minute // INTERVAL_MINUTES
        midpoint_hour = midpoint.hour + midpoint.minute / 60.0 + midpoint.second / 3600.0
        return local_day, slot, midpoint_hour

    def _interval_truth_value(self, site_capacity: float, local_day: str, slot: int) -> float | None:
        """Return the exact SimCity generation fraction for an interval, if available."""
        ivs = self.interval_guidance.get(local_day)
        if not ivs or slot < 0 or slot >= len(ivs):
            return None
        return round(site_capacity * ivs[slot], 4)

    def _forecast_values(self, site_capacity: float, period_end: dt, minute: int) -> tuple[float, float, float]:
        """Return (p10, p50, p90) forecasts shaped by guidance when available."""
        local_day, slot, midpoint_hour = self._interval_slot(period_end, minute)
        guidance = self.forecast_guidance.get(local_day)
        if not guidance:
            raw_50 = self.__pv_interval(site_capacity, FORECAST, period_end, minute)
            raw_10 = self.__pv_interval(site_capacity, FORECAST_10, period_end, minute)
            raw_90 = self.__pv_interval(site_capacity, FORECAST_90, period_end, minute)
            return raw_10, raw_50, raw_90

        cloudiness = self._clamp(
            float(guidance.get("cloudiness", GUIDANCE_CLOUDINESS_DEFAULT)),
            GUIDANCE_CLOUDINESS_MIN,
            GUIDANCE_CLOUDINESS_MAX,
        )
        forecast_confidence = self._clamp(
            float(
                guidance.get(
                    "forecast_confidence",
                    1.0 - cloudiness * GUIDANCE_FORECAST_CONFIDENCE_CLOUDINESS_FACTOR,
                )
            ),
            GUIDANCE_FORECAST_CONFIDENCE_MIN,
            GUIDANCE_FORECAST_CONFIDENCE_MAX,
        )

        truth = self._interval_truth_value(site_capacity, local_day, slot)
        if truth is not None:
            if truth == 0.0:
                return 0.0, 0.0, 0.0

            curveball_strength = self._clamp(
                float(guidance.get("curveball_strength", GUIDANCE_CURVEBALL_STRENGTH_DEFAULT)),
                GUIDANCE_CURVEBALL_STRENGTH_MIN,
                GUIDANCE_CURVEBALL_STRENGTH_MAX,
            )
            curveball_centre_hour = self._clamp(
                float(guidance.get("curveball_centre_hour", GUIDANCE_CURVEBALL_CENTRE_DEFAULT_HOUR)),
                GUIDANCE_CURVEBALL_CENTRE_MIN_HOUR,
                GUIDANCE_CURVEBALL_CENTRE_MAX_HOUR,
            )
            curveball_width_hours = self._clamp(
                float(guidance.get("curveball_width_hours", GUIDANCE_CURVEBALL_WIDTH_DEFAULT_HOURS)),
                GUIDANCE_CURVEBALL_WIDTH_MIN_HOURS,
                GUIDANCE_CURVEBALL_WIDTH_MAX_HOURS,
            )
            curveball_sign = self._clamp(
                float(guidance.get("curveball_sign", GUIDANCE_CURVEBALL_SIGN_DEFAULT_P50)),
                GUIDANCE_CURVEBALL_SIGN_MIN,
                GUIDANCE_CURVEBALL_SIGN_MAX,
            )

            # Skill error: smooth, day-specific, scales with forecast difficulty.
            day_hash = (sum(ord(ch) for ch in local_day) % DAY_HASH_MODULUS) / float(DAY_HASH_MODULUS)
            skill_amp = (1.0 - forecast_confidence) * (SKILL_AMPLITUDE_BASE + cloudiness * SKILL_AMPLITUDE_CLOUDINESS_FACTOR)
            skill_wave = (
                math.sin(slot * SKILL_WAVE_PRIMARY_SLOT_FREQ + day_hash * math.pi * SKILL_WAVE_PRIMARY_DAY_CYCLES)
                + SKILL_WAVE_SECONDARY_WEIGHT
                * math.sin(
                    slot * SKILL_WAVE_SECONDARY_SLOT_FREQ + SKILL_WAVE_SECONDARY_PHASE_SHIFT + day_hash * SKILL_WAVE_SECONDARY_DAY_SCALE
                )
            ) / SKILL_WAVE_NORMALISER
            skill_error = skill_amp * skill_wave

            # Forecasters tend to overestimate on cloudy/uncertain days.
            optimism_bias = cloudiness * (1.0 - forecast_confidence) * OPTIMISM_BIAS_CLOUDINESS_FACTOR

            # Surprise error: nature-driven, time-local, one event per day.
            surprise_shape = math.exp(GAUSSIAN_EXP_SCALE * ((midpoint_hour - curveball_centre_hour) / curveball_width_hours) ** 2)
            surprise_error = (
                curveball_sign * curveball_strength * surprise_shape * (SURPRISE_BASE_FACTOR + cloudiness * SURPRISE_CLOUDINESS_FACTOR)
            )

            # Partial intraday correction — forecasts improve as day unfolds but
            # persistent surprises remain partially unresolved.
            correction = self._clamp(
                (midpoint_hour - INTRADAY_CORRECTION_START_HOUR) / INTRADAY_CORRECTION_WINDOW_HOURS,
                0.0,
                1.0,
            )
            corrected_skill = skill_error * (1.0 - SKILL_CORRECTION_MAX_FACTOR * correction)
            corrected_surprise = surprise_error * (1.0 - SURPRISE_CORRECTION_MAX_FACTOR * correction)

            bias = 1.0 + optimism_bias + corrected_skill + corrected_surprise
            p50_raw = truth * self._clamp(bias, P50_BIAS_MIN, P50_BIAS_MAX)

            weather_mixedness = self._clamp(
                1.0 - abs(cloudiness - WEATHER_MIXEDNESS_CENTER) / WEATHER_MIXEDNESS_HALF_RANGE,
                0.0,
                1.0,
            )
            weather_badness = self._clamp(
                cloudiness * WEATHER_BADNESS_CLOUDINESS_WEIGHT + (1.0 - forecast_confidence) * WEATHER_BADNESS_UNCERTAINTY_WEIGHT,
                0.0,
                1.0,
            )
            uncertainty = 1.0 - forecast_confidence
            # Forecast uncertainty drives quantile spread: tighter when confidence
            # is high, broader when confidence is low.
            band_width = self._clamp(
                BAND_WIDTH_BASE
                + uncertainty * BAND_WIDTH_UNCERTAINTY_FACTOR
                + weather_mixedness * BAND_WIDTH_MIXEDNESS_FACTOR
                + abs(corrected_surprise) * BAND_WIDTH_SURPRISE_FACTOR,
                BAND_WIDTH_MIN,
                BAND_WIDTH_MAX,
            )

            down_span = (
                p50_raw
                * band_width
                * self._clamp(
                    DOWN_SPAN_SKEW_BASE
                    + weather_badness * DOWN_SPAN_SKEW_WEATHER_FACTOR
                    + max(0.0, corrected_surprise) * DOWN_SPAN_SKEW_SURPRISE_FACTOR,
                    DOWN_SPAN_SKEW_MIN,
                    DOWN_SPAN_SKEW_MAX,
                )
            )
            up_span = (
                p50_raw
                * band_width
                * self._clamp(
                    UP_SPAN_SKEW_BASE
                    + (1.0 - weather_badness) * UP_SPAN_SKEW_GOOD_WEATHER_FACTOR
                    + max(0.0, -corrected_surprise) * UP_SPAN_SKEW_SURPRISE_FACTOR,
                    UP_SPAN_SKEW_MIN,
                    UP_SPAN_SKEW_MAX,
                )
            )

            min_total_span = p50_raw * (MIN_TOTAL_SPAN_BASE + uncertainty * MIN_TOTAL_SPAN_UNCERTAINTY_FACTOR)
            if down_span + up_span < min_total_span:
                scale = min_total_span / max(NUMERIC_EPSILON, down_span + up_span)
                down_span *= scale
                up_span *= scale

            p10 = self._clamp(p50_raw - down_span, 0.0, p50_raw)
            p90 = self._clamp(p50_raw + up_span, p50_raw, site_capacity * FORECAST_90)
            p50 = self._clamp(p50_raw, p10, p90)

            return round(p10, 4), round(p50, 4), round(p90, 4)

        # Fallback when no per-interval data: analytical daylight + weather shaping.
        raw_50 = site_capacity * FORECAST
        raw_10 = site_capacity * FORECAST_10
        raw_90 = site_capacity * FORECAST_90

        p10_bias = self._clamp(
            float(guidance.get("bias_towards_p10", cloudiness)),
            0.0,
            1.0,
        )
        spread_scale = self._clamp(
            float(
                guidance.get(
                    "spread_scale",
                    GUIDANCE_SPREAD_SCALE_DEFAULT + cloudiness * GUIDANCE_SPREAD_SCALE_CLOUDINESS_FACTOR,
                )
            ),
            GUIDANCE_SPREAD_SCALE_MIN,
            GUIDANCE_SPREAD_SCALE_MAX,
        )
        estimate_scale = self._clamp(
            float(
                guidance.get(
                    "estimate_scale",
                    GUIDANCE_ESTIMATE_SCALE_DEFAULT - cloudiness * GUIDANCE_ESTIMATE_SCALE_CLOUDINESS_FACTOR,
                )
            ),
            GUIDANCE_ESTIMATE_SCALE_MIN,
            GUIDANCE_ESTIMATE_SCALE_MAX,
        )
        morning_cloudiness = self._clamp(float(guidance.get("morning_cloudiness", cloudiness)), 0.0, 1.0)
        afternoon_cloudiness = self._clamp(float(guidance.get("afternoon_cloudiness", cloudiness)), 0.0, 1.0)
        curveball_strength = self._clamp(
            float(guidance.get("curveball_strength", GUIDANCE_CURVEBALL_STRENGTH_DEFAULT)),
            GUIDANCE_CURVEBALL_STRENGTH_MIN,
            GUIDANCE_CURVEBALL_STRENGTH_MAX,
        )
        curveball_centre_hour = self._clamp(
            float(guidance.get("curveball_centre_hour", GUIDANCE_CURVEBALL_CENTRE_DEFAULT_HOUR)),
            GUIDANCE_CURVEBALL_CENTRE_MIN_HOUR,
            GUIDANCE_CURVEBALL_CENTRE_MAX_HOUR,
        )
        curveball_width_hours = self._clamp(
            float(guidance.get("curveball_width_hours", GUIDANCE_CURVEBALL_WIDTH_DEFAULT_HOURS)),
            GUIDANCE_CURVEBALL_WIDTH_MIN_HOURS,
            GUIDANCE_CURVEBALL_WIDTH_MAX_HOURS,
        )
        curveball_sign = self._clamp(
            float(guidance.get("curveball_sign", GUIDANCE_CURVEBALL_SIGN_DEFAULT_FALLBACK)),
            GUIDANCE_CURVEBALL_SIGN_MIN,
            GUIDANCE_CURVEBALL_SIGN_MAX,
        )
        sunrise_seconds = self._clamp(
            float(guidance.get("sunrise_seconds", SUNRISE_DEFAULT_HOUR * SECONDS_PER_HOUR)),
            0.0,
            SECONDS_PER_DAY_LAST,
        )
        sunset_seconds = self._clamp(
            float(guidance.get("sunset_seconds", SUNSET_DEFAULT_HOUR * SECONDS_PER_HOUR)),
            0.0,
            SECONDS_PER_DAY,
        )

        shaped_50 = raw_50 * estimate_scale
        # On bad-weather days, shift central forecast materially toward p10.
        shaped_50 = shaped_50 - (shaped_50 - raw_10) * BAD_WEATHER_P50_TO_P10_SHIFT_FACTOR * p10_bias

        shaped_10 = max(0.0, min(shaped_50, raw_10))
        shaped_90 = max(shaped_50, raw_90)

        second_of_day = midpoint_hour * SECONDS_PER_HOUR

        if midpoint_hour <= MIDPOINT_BLEND_START_HOUR:
            period_cloudiness = morning_cloudiness
        elif midpoint_hour >= MIDPOINT_BLEND_END_HOUR:
            period_cloudiness = afternoon_cloudiness
        else:
            blend = (midpoint_hour - MIDPOINT_BLEND_START_HOUR) / (MIDPOINT_BLEND_END_HOUR - MIDPOINT_BLEND_START_HOUR)
            period_cloudiness = morning_cloudiness * (1.0 - blend) + afternoon_cloudiness * blend

        curveball = (
            curveball_sign
            * curveball_strength
            * math.exp(GAUSSIAN_EXP_SCALE * ((midpoint_hour - curveball_centre_hour) / curveball_width_hours) ** 2)
        )
        effective_cloudiness = self._clamp(period_cloudiness + curveball, 0.0, 1.0)

        if second_of_day <= sunrise_seconds or second_of_day >= sunset_seconds:
            shaped_10 = shaped_50 = shaped_90 = 0.0
        else:
            daylight_seconds = max(1.0, sunset_seconds - sunrise_seconds)
            phase = (second_of_day - sunrise_seconds) / daylight_seconds
            daylight_curve = math.sin(math.pi * phase) ** DAYLIGHT_CURVE_EXPONENT
            weather_curve = self._clamp(
                1.0 - effective_cloudiness * WEATHER_CURVE_CLOUDINESS_FACTOR,
                WEATHER_CURVE_MIN,
                WEATHER_CURVE_MAX,
            )
            shaped_50 *= daylight_curve * weather_curve

            uncertainty = 1.0 - forecast_confidence
            interval_uncertainty = self._clamp(
                uncertainty * (INTERVAL_UNCERTAINTY_BASE + INTERVAL_UNCERTAINTY_SPREAD_FACTOR * spread_scale)
                + effective_cloudiness * INTERVAL_UNCERTAINTY_CLOUDINESS_FACTOR
                + abs(curveball) * INTERVAL_UNCERTAINTY_CURVEBALL_FACTOR,
                INTERVAL_UNCERTAINTY_MIN,
                INTERVAL_UNCERTAINTY_MAX,
            )
            band_ratio = self._clamp(
                BAND_RATIO_BASE + interval_uncertainty * BAND_RATIO_UNCERTAINTY_FACTOR,
                BAND_RATIO_MIN,
                BAND_RATIO_MAX,
            )

            down_skew = self._clamp(
                FALLBACK_DOWN_SKEW_BASE
                + p10_bias * FALLBACK_DOWN_SKEW_P10_BIAS_FACTOR
                + effective_cloudiness * FALLBACK_DOWN_SKEW_CLOUDINESS_FACTOR
                + max(0.0, curveball) * FALLBACK_DOWN_SKEW_CURVEBALL_FACTOR,
                FALLBACK_DOWN_SKEW_MIN,
                FALLBACK_DOWN_SKEW_MAX,
            )
            up_skew = self._clamp(
                FALLBACK_UP_SKEW_BASE
                + (1.0 - p10_bias) * FALLBACK_UP_SKEW_P10_BIAS_FACTOR
                + (1.0 - effective_cloudiness) * FALLBACK_UP_SKEW_GOOD_WEATHER_FACTOR
                + max(0.0, -curveball) * FALLBACK_UP_SKEW_CURVEBALL_FACTOR,
                FALLBACK_UP_SKEW_MIN,
                FALLBACK_UP_SKEW_MAX,
            )

            down_span = shaped_50 * band_ratio * down_skew
            up_span = shaped_50 * band_ratio * up_skew
            min_down_sep = shaped_50 * (MIN_DOWN_SEPARATION_BASE + uncertainty * MIN_DOWN_SEPARATION_UNCERTAINTY_FACTOR)
            down_span = max(down_span, min_down_sep)

            shaped_10 = max(0.0, shaped_50 - down_span)
            shaped_90 = max(shaped_50, shaped_50 + up_span)

        cap_90 = site_capacity * FORECAST_90
        shaped_10 = self._clamp(shaped_10, 0.0, cap_90)
        shaped_50 = self._clamp(shaped_50, shaped_10, cap_90)
        shaped_90 = self._clamp(shaped_90, shaped_50, cap_90)
        return round(shaped_10, 4), round(shaped_50, 4), round(shaped_90, 4)

    def raw_get_sites(self, api_key: str) -> dict[str, Any] | None:
        """Return sites for an API key."""
        sites = API_KEY_SITES.get(api_key)
        meta = {
            "page_count": 1,
            "current_page": 1,
            "total_records": len(API_KEY_SITES.get(api_key, {}).get("sites", [])),
        }
        return sites | meta if sites is not None else None

    def raw_get_site_estimated_actuals(
        self,
        site_id: str,
        api_key: str,
        hours: int,
        prefix: str = "pv_estimate",
        period_end: dt | None = None,
        key: str | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Return simulated estimated actuals for a site."""
        sites: list[dict[str, Any]] | int | None = API_KEY_SITES.get(api_key, {}).get("sites", [])
        site: dict[str, Any] | None = next((s for s in sites if s["resource_id"] == site_id), None) if isinstance(sites, list) else None
        if not site:
            return {}
        period_end = self.get_period(dt.now(datetime.UTC), timedelta(hours=hours) * -1) if period_end is None else period_end

        output_key = key or prefix
        return {
            "estimated_actuals": [
                {
                    "period_end": (period_end + timedelta(minutes=minute * INTERVAL_MINUTES)).isoformat(),
                    "period": INTERVAL_ISO_PERIOD,
                    output_key: self._estimated_actual_value(site["capacity"], period_end, minute),
                }
                for minute in range((hours + 1) * HALF_HOURS_PER_HOUR)
            ],
        }

    def _actuals_jitter(self, local_day: str, slot: int) -> float:
        """Return deterministic gaussian jitter for estimated actuals.

        Keyed on day+slot so the same interval always returns the same noise,
        simulating satellite-derived estimation error that is consistent within
        a polling cycle but varies across intervals. The 1σ scale is
        ``actuals_uncertainty_pct / 100`` and is loaded from guidance.
        """
        if self.actuals_uncertainty_pct <= 0.0:
            return 0.0
        seed = (sum(ord(c) for c in local_day) * 31 + slot * 7919) & 0xFFFFFF
        # Box-Muller using two cheap pseudo-random values derived from the seed.
        u1 = ((seed * 1664525 + 1013904223) & 0xFFFFFF) / 0xFFFFFF
        u2 = ((seed * 22695477 + 1) & 0xFFFFFF) / 0xFFFFFF
        u1 = max(1e-9, u1)
        z = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
        return z * (self.actuals_uncertainty_pct / 100.0)

    def _estimated_actual_value(self, site_capacity: float, period_end: dt, minute: int) -> float:
        """Return estimated actual value for a site interval."""
        local_day, slot, midpoint_hour = self._interval_slot(period_end, minute)
        truth = self._interval_truth_value(site_capacity, local_day, slot)
        apply_jitter = truth is not None or local_day in self.forecast_guidance
        if truth is not None:
            if truth > 0.0 and apply_jitter:
                truth = self._clamp(truth * (1.0 + self._actuals_jitter(local_day, slot)), 0.0, site_capacity)
            if not self.modified_actuals:
                return round(truth, 4)
            multiplier = MODIFIED_LATE_DAY_MULTIPLIER if midpoint_hour >= MODIFIED_OUTPUT_START_HOUR else 1.0
            return round(truth * multiplier, 4)

        _p10, p50, _p90 = self._forecast_values(site_capacity, period_end, minute)
        if p50 > 0.0 and apply_jitter:
            p50 = self._clamp(p50 * (1.0 + self._actuals_jitter(local_day, slot)), 0.0, site_capacity)
        if not self.modified_actuals:
            return round(p50, 4)
        multiplier = MODIFIED_LATE_DAY_MULTIPLIER if midpoint_hour >= MODIFIED_OUTPUT_START_HOUR else 1.0
        return round(p50 * multiplier, 4)

    def raw_get_site_forecasts(
        self,
        site_id: str,
        api_key: str,
        hours: int,
        prefix: str = "pv_estimate",
        key: str | None = None,
        period_end: dt | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Return simulated forecasts for a site."""
        sites: list[dict[str, Any]] | int | None = API_KEY_SITES.get(api_key, {}).get("sites")
        site: dict[str, Any] | None = next((s for s in sites if s["resource_id"] == site_id), None) if isinstance(sites, list) else None
        if not site:
            return {}
        output_key = key or prefix
        period_end = self.get_period(dt.now(datetime.UTC), timedelta(minutes=INTERVAL_MINUTES)) if period_end is None else period_end

        lookup = f"{api_key} {site_id} {hours} {period_end}"
        if cached := self.cached_forecasts.get(lookup):
            return cached

        forecasts: list[dict[str, Any]] = []
        for minute in range(hours * HALF_HOURS_PER_HOUR + 1):  # Solcast returns one extra interval beyond even count
            p10, p50, p90 = self._forecast_values(site["capacity"], period_end, minute)
            forecasts.append(
                {
                    "period_end": (period_end + timedelta(minutes=minute * INTERVAL_MINUTES)).isoformat(),
                    "period": INTERVAL_ISO_PERIOD,
                    output_key: p50,
                    output_key + "10": p10,
                    output_key + "90": p90,
                }
            )

        self.cached_forecasts[lookup] = {"forecasts": forecasts}
        return self.cached_forecasts[lookup]

    def set_time_zone(self, timezone: ZoneInfo) -> None:
        """Set the time zone."""
        self.timezone = timezone

    def get_period(self, period: dt, delta: timedelta) -> dt:
        """Return the start period and factors for the current time."""
        return (
            period.replace(
                minute=(int(period.minute / INTERVAL_MINUTES) * INTERVAL_MINUTES),
                second=0,
                microsecond=0,
            )
            + delta
        )

    def __pv_interval(self, site_capacity: float, estimate: float, period_end: dt, minute: int, modified: bool = False) -> float:
        """Calculate value for a single interval."""
        interval = int(
            (period_end + timedelta(minutes=minute * INTERVAL_MINUTES)).astimezone(self.timezone).hour * HALF_HOURS_PER_HOUR
            + (period_end + timedelta(minutes=minute * INTERVAL_MINUTES)).astimezone(self.timezone).minute / INTERVAL_MINUTES
        )
        interval -= (
            DST_INTERVAL_SHIFT
            if (
                (period_end + timedelta(minutes=minute * INTERVAL_MINUTES)).astimezone(self.timezone).dst()
                == timedelta(hours=DST_COMPARISON_HOURS)
                and interval > DST_FIRST_SHIFTED_INTERVAL
            )
            else 0
        )

        return round(
            site_capacity
            * estimate
            * (
                GENERATION_FACTOR[interval] * MODIFIED_LATE_DAY_MULTIPLIER
                if modified and interval > GENERATION_FACTOR_TAPER_START_INTERVAL
                else GENERATION_FACTOR[interval]
            ),
            4,
        )
