"""Unit tests for forecast.py."""

import math

from custom_components.solcast_solar.forecast import ForecastQuery

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
