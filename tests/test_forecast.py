"""Unit tests for forecast.py."""

import math

from homeassistant.components.solcast_solar.forecast import ForecastQuery

cubic_interp = ForecastQuery._cubic_interp


class TestCubicInterp:
    """Tests for the cubic_interp spline function."""

    def test_interpolates_exact_knot_points(self) -> None:
        """Interpolating at knot x-values must return the corresponding y-values."""
        x = [0.0, 1.0, 2.0, 3.0]
        y = [0.0, 1.0, 4.0, 9.0]
        result = cubic_interp(x, x, y)
        assert len(result) == len(x)
        for got, expected in zip(result, y, strict=True):
            assert math.isclose(got, expected, abs_tol=1e-3), f"At knot: got {got}, expected {expected}"

    def test_interpolates_midpoints_linearly_for_straight_line(self) -> None:
        """For y = x the spline must be exact at all queried points."""
        x = [0.0, 1.0, 2.0, 3.0, 4.0]
        y = [0.0, 1.0, 2.0, 3.0, 4.0]
        x0 = [0.5, 1.5, 2.5, 3.5]
        result = cubic_interp(x0, x, y)
        for got, xq in zip(result, x0, strict=True):
            assert math.isclose(got, xq, abs_tol=1e-3), f"Linear interp: got {got}, expected {xq}"

    def test_interpolates_quadratic(self) -> None:
        """Spline of y = x² should recover quadratic values closely away from boundaries."""
        # Natural spline boundary conditions cause larger error near the ends;
        # use interior query points (away from x[0] and x[-1]) only.
        x = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
        y = [xi**2 for xi in x]
        x0 = [1.5, 2.5, 3.5]
        result = cubic_interp(x0, x, y)
        for got, xq in zip(result, x0, strict=True):
            expected = round(xq**2, 4)
            assert math.isclose(got, expected, abs_tol=0.05), f"Quadratic interp at {xq}: got {got}, expected {expected}"

    def test_single_query_point(self) -> None:
        """A single query point must produce a list with one element."""
        x = [0.0, 1.0, 2.0, 3.0]
        y = [0.0, 1.0, 0.0, 1.0]
        result = cubic_interp([1.5], x, y)
        assert len(result) == 1, f"Single query point should yield a 1-element list, got {len(result)}"
        assert isinstance(result[0], float), f"Interpolated value should be a float, got {type(result[0])}"

    def test_query_below_range_clamps_to_first_interval(self) -> None:
        """Query points below x[0] should be clamped into the first spline interval."""
        x = [1.0, 2.0, 3.0, 4.0]
        y = [1.0, 4.0, 9.0, 16.0]
        # x0 value below the knot range — must not raise
        result = cubic_interp([0.0], x, y)
        assert len(result) == 1, "Out-of-range query below x[0] must still produce exactly one result"

    def test_query_above_range_clamps_to_last_interval(self) -> None:
        """Query points above x[-1] should be clamped into the last spline interval."""
        x = [0.0, 1.0, 2.0, 3.0]
        y = [0.0, 1.0, 4.0, 9.0]
        result = cubic_interp([10.0], x, y)
        assert len(result) == 1, "Out-of-range query above x[-1] must still produce exactly one result"

    def test_output_length_matches_query_length(self) -> None:
        """Output list must have the same length as x0."""
        x = [0.0, 1.0, 2.0, 3.0, 4.0]
        y = [0.0, 1.0, 8.0, 27.0, 64.0]
        x0 = [0.25, 0.5, 0.75, 1.25, 1.75, 2.5, 3.5]
        result = cubic_interp(x0, x, y)
        assert len(result) == len(x0), f"Output should have {len(x0)} elements but got {len(result)}"

    def test_output_values_are_rounded_to_4dp(self) -> None:
        """All output values must be rounded to exactly 4 decimal places."""
        x = [0.0, 1.0, 2.0, 3.0]
        y = [0.0, 1.0, 0.5, 1.5]
        x0 = [0.3, 0.7, 1.3, 2.6]
        result = cubic_interp(x0, x, y)
        for val in result:
            assert val == round(val, 4), f"{val} is not rounded to 4 dp"

    def test_solar_generation_profile(self) -> None:
        """Realistic PV half-hourly profile: bell-shaped generation curve."""
        # Hours 6..18, generation peaks at noon
        hours = [6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0]
        gen = [0.0, 0.5, 2.0, 3.0, 2.0, 0.5, 0.0]
        query = [7.0, 9.0, 11.0, 13.0, 15.0, 17.0]
        result = cubic_interp(query, hours, gen)
        # Result should be non-negative and peak near midday
        assert all(isinstance(v, float) for v in result), f"All interpolated values should be floats, got {[type(v) for v in result]}"
        # The value at 11h should be higher than at 7h (rising side)
        assert result[2] > result[0], f"11h value {result[2]} should exceed 7h value {result[0]} on the rising side"
        # The value at 13h should be higher than at 17h (falling side)
        assert result[3] > result[5], f"13h value {result[3]} should exceed 17h value {result[5]} on the falling side"


class TestSanitiseSpline:
    """Tests for zeroing the momentary spline where two half hours in a row are zero."""

    def test_missing_morning_does_not_zero_the_afternoon(self) -> None:
        """A day that starts after midnight must not wipe the afternoon with night zeros."""
        query = ForecastQuery.__new__(ForecastQuery)
        gap = 15  # First forecast at 07:30
        xx = list(range(1800 * gap, 1800 * 50, 300))
        y = [3.0 if 8 <= 7.5 + i * 0.5 <= 18 else 0.0 for i in range(len(xx) // 6)]
        confidence = "pv_estimate"
        spline = {confidence: [1.0] * len(xx)}
        query._sanitise_spline(spline, confidence, xx, y)

        def index(seconds: int) -> int:
            # Three leading samples are the half-hour average shift.
            return int(seconds / 300) - int(xx[0] / 300) + 3

        assert spline[confidence][index(15 * 3600)] == 1.0, "Afternoon must keep its value"
        assert spline[confidence][index(22 * 3600 + 30 * 60)] == 0.0, "Night must still be zeroed"

    def test_real_day_starting_at_0730_keeps_the_afternoon(self) -> None:
        """Real forecast of a site added during the day, so its first half hour is 07:30 local.

        pv_estimate in kW for each half hour from 07:30, taken from the detailedForecast attribute of a
        rooftop on 7 October 2026 (Europe/Berlin). Before the fix the momentary spline was 0 from 11:30 on.
        """
        query = ForecastQuery.__new__(ForecastQuery)
        query._spline_period = list(range(0, 90000, 1800))
        today = [
            0.0695, 0.3961, 0.9175, 1.4272, 1.909, 2.3363, 2.7661, 3.0155, 3.211, 2.8405, 3.0162,
            1.9623, 1.5817, 1.0721, 0.5086, 0.4775, 0.5228, 0.5704, 0.3915, 0.2477, 0.1891, 0.0691,
            0.0198, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        ]  # fmt: skip
        confidence = "pv_estimate"
        data = [{confidence: value} for value in [*today, 0.0, 0.0]]  # Plus the first hour of tomorrow
        xx = list(range(1800 * (48 - len(today)), 1800 * len(query._spline_period), 300))
        spline: dict[str, list[float]] = {}
        query._get_spline(spline, 0, xx, data, [confidence])
        moment = spline[confidence]
        offset = len(query._spline_period) * 6 - len(moment) + 3  # As in _get_moment()

        def at(hour: int, minute: int = 0) -> float:
            return moment[int((hour * 3600 + minute * 60) / 300) - offset]

        for hour, minute in ((11, 30), (12, 0), (13, 0), (15, 0), (17, 0)):
            assert at(hour, minute) > 0.1, f"{hour:02d}:{minute:02d} must not be zeroed"
        assert at(21) == 0.0, "21:00 is night"
