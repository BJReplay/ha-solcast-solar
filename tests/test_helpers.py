"""Unit tests for Solcast helper functions and methods."""

from datetime import UTC, datetime as dt

import pytest

from homeassistant.components.solcast_solar.const import (
    DEFAULT_SOLCAST_HTTPS_URL,
    ESTIMATE,
    ESTIMATE10,
    ESTIMATE90,
    PERIOD_START,
)
from homeassistant.components.solcast_solar.solcastapi import SolcastApi
from homeassistant.components.solcast_solar.util import (
    azimuth_to_compass_degrees,
    azimuth_to_compass_direction,
    diff,
    interquartile_bounds,
    ordinal,
    percentile,
    split_and_strip,
)


class TestGetSolcastBaseUrl:
    """Tests for get_solcast_base_url."""

    def test_no_port_returns_url_unchanged(self) -> None:
        """Port <= 0 must return the URL with no modification."""
        assert SolcastApi.get_solcast_base_url(DEFAULT_SOLCAST_HTTPS_URL, 0) == DEFAULT_SOLCAST_HTTPS_URL, (
            "Port 0 should leave the URL unchanged"
        )
        assert SolcastApi.get_solcast_base_url(DEFAULT_SOLCAST_HTTPS_URL, -1) == DEFAULT_SOLCAST_HTTPS_URL, (
            "Negative port should leave the URL unchanged"
        )

    def test_trailing_slash_stripped(self) -> None:
        """Trailing slashes on the base URL should be removed."""
        assert SolcastApi.get_solcast_base_url("https://api.solcast.com.au/", 0) == DEFAULT_SOLCAST_HTTPS_URL, (
            "Trailing slash must be stripped from the base URL"
        )

    def test_port_injected_into_netloc(self) -> None:
        """A positive port should appear in the returned URL."""
        result = SolcastApi.get_solcast_base_url(DEFAULT_SOLCAST_HTTPS_URL, 8080)
        assert ":8080" in result, f"Port 8080 should appear in the netloc of {result!r}"
        assert result.startswith("https://"), f"Scheme must be preserved as https://, got {result!r}"

    def test_path_preserved_with_port(self) -> None:
        """Any path component must be preserved when a port is injected."""
        result = SolcastApi.get_solcast_base_url("https://api.solcast.com.au/v2", 9000)
        assert "/v2" in result, f"Path '/v2' must be preserved in {result!r}"
        assert ":9000" in result, f"Port 9000 must appear in {result!r}"

    def test_ipv6_address_bracketed(self) -> None:
        """IPv6 addresses must be wrapped in brackets when a port is added."""
        result = SolcastApi.get_solcast_base_url("https://[::1]", 8080)
        assert "[::1]:8080" in result, f"IPv6 address with port should appear as '[::1]:8080' in {result!r}"


class TestHttpStatusTranslate:
    """Tests for http_status_translate."""

    def test_known_code_returns_string(self) -> None:
        """Known HTTP status codes should return a slash-delimited description string."""
        assert SolcastApi.http_status_translate(200) == "200/Success", "HTTP 200 should map to '200/Success'"
        assert SolcastApi.http_status_translate(429) == "429/Try again later", "HTTP 429 should map to '429/Try again later'"
        assert SolcastApi.http_status_translate(418) == "418/I'm a teapot", "HTTP 418 should map to the teapot status string"

    def test_unknown_code_returns_int(self) -> None:
        """HTTP 999 is a sentinel for a prior crash and should contain that text."""
        result = SolcastApi.http_status_translate(999)
        assert "Prior crash" in str(result), f"HTTP 999 result {result!r} should contain 'Prior crash'"

    def test_completely_unknown_code_returns_int(self) -> None:
        """A status code with no translation entry should be returned as-is."""
        result = SolcastApi.http_status_translate(599)
        assert result == 599, f"Unknown status 599 should be returned unchanged, got {result!r}"


class TestForecastEntryUpdate:
    """Tests for forecast_entry_update."""

    def test_creates_new_entry_without_p10_p90(self) -> None:
        """A new entry with only p50 should contain pv_estimate but no p10/p90 keys."""
        forecasts: dict = {}
        ts = dt(2025, 6, 1, 0, 0, tzinfo=UTC)
        SolcastApi.forecast_entry_update(forecasts, ts, 1.5)
        assert forecasts[ts][ESTIMATE] == 1.5, "pv_estimate must be stored with the provided value"
        assert ESTIMATE10 not in forecasts[ts], "pv_estimate10 must not be present when p10 was not supplied"

    def test_creates_new_entry_with_p10_p90(self) -> None:
        """A new entry created with all three estimates should store each under its constant key."""
        forecasts: dict = {}
        ts = dt(2025, 6, 1, 0, 30, tzinfo=UTC)
        SolcastApi.forecast_entry_update(forecasts, ts, 1.5, pv10=1.0, pv90=2.0)
        assert forecasts[ts][ESTIMATE] == 1.5, "p50 estimate must be stored under ESTIMATE"
        assert forecasts[ts][ESTIMATE10] == 1.0, "p10 estimate must be stored under ESTIMATE10"
        assert forecasts[ts][ESTIMATE90] == 2.0, "p90 estimate must be stored under ESTIMATE90"

    def test_updates_existing_entry_estimate(self) -> None:
        """Calling forecast_entry_update on an existing entry must overwrite the p50 estimate."""
        ts = dt(2025, 6, 1, 1, 0, tzinfo=UTC)
        forecasts: dict = {ts: {PERIOD_START: ts, ESTIMATE: 1.0}}
        SolcastApi.forecast_entry_update(forecasts, ts, 2.5)
        assert forecasts[ts][ESTIMATE] == 2.5, f"ESTIMATE should be updated to 2.5, got {forecasts[ts][ESTIMATE]!r}"

    def test_updates_existing_entry_p10_p90(self) -> None:
        """Calling forecast_entry_update on an existing entry must overwrite p10 and p90."""
        ts = dt(2025, 6, 1, 1, 30, tzinfo=UTC)
        forecasts: dict = {ts: {PERIOD_START: ts, ESTIMATE: 1.0, ESTIMATE10: 0.5, ESTIMATE90: 1.5}}
        SolcastApi.forecast_entry_update(forecasts, ts, 2.0, pv10=1.5, pv90=2.5)
        assert forecasts[ts][ESTIMATE10] == 1.5, f"ESTIMATE10 should be updated to 1.5, got {forecasts[ts][ESTIMATE10]!r}"
        assert forecasts[ts][ESTIMATE90] == 2.5, f"ESTIMATE90 should be updated to 2.5, got {forecasts[ts][ESTIMATE90]!r}"


class TestSplitAndStrip:
    """Tests for split_and_strip."""

    def test_single_value(self) -> None:
        """A string with no commas should yield a one-element list."""
        assert split_and_strip("abc") == ["abc"], "Single value without comma should yield a one-element list"

    def test_multiple_values(self) -> None:
        """Comma-separated values should each become a trimmed list item."""
        assert split_and_strip("a, b, c") == ["a", "b", "c"], "Each comma-separated token must be trimmed and returned"

    def test_empty_string_returns_empty_list(self) -> None:
        """An empty input string should return an empty list."""
        assert split_and_strip("") == [], "Empty string must produce an empty list"

    def test_whitespace_only_entries_discarded(self) -> None:
        """Blank entries between commas must be dropped from the result."""
        assert split_and_strip("a, , b") == ["a", "b"], "Blank (whitespace-only) entries must be discarded"

    def test_leading_trailing_whitespace_stripped(self) -> None:
        """Leading and trailing whitespace around each value must be removed."""
        assert split_and_strip("  key1  ,  key2  ") == ["key1", "key2"], "Surrounding whitespace must be stripped from each token"


class TestAzimuthToCompass:
    """Tests for Solcast azimuth to compass conversion helpers."""

    @pytest.mark.parametrize(
        ("solcast_azimuth", "compass_degrees", "compass_direction"),
        [
            (0, 0.0, "N"),
            (90, 270.0, "W"),
            (-90, 90.0, "E"),
            (180, 180.0, "S"),
            (-180, 180.0, "S"),
            (66, 294.0, "WNW"),
        ],
    )
    def test_solcast_azimuth_maps_to_expected_compass(self, solcast_azimuth: float, compass_degrees: float, compass_direction: str) -> None:
        """Solcast azimuth values should map to expected compass bearings and directions."""
        assert azimuth_to_compass_degrees(solcast_azimuth) == compass_degrees
        assert azimuth_to_compass_direction(solcast_azimuth) == compass_direction

    def test_invalid_azimuth_returns_none(self) -> None:
        """Invalid azimuth input should produce None for both helpers."""
        assert azimuth_to_compass_degrees("not-a-number") is None
        assert azimuth_to_compass_direction("not-a-number") is None


class TestOrdinal:
    """Tests for ordinal."""

    def test_st_suffix(self) -> None:
        """Integers ending in 1 (but not 11) should use the 'st' ordinal suffix."""
        assert ordinal(1) == "1st", "1 should produce '1st'"
        assert ordinal(21) == "21st", "21 should produce '21st'"
        assert ordinal(101) == "101st", "101 should produce '101st'"

    def test_nd_suffix(self) -> None:
        """Integers ending in 2 (but not 12) should use the 'nd' ordinal suffix."""
        assert ordinal(2) == "2nd", "2 should produce '2nd'"
        assert ordinal(22) == "22nd", "22 should produce '22nd'"

    def test_rd_suffix(self) -> None:
        """Integers ending in 3 (but not 13) should use the 'rd' ordinal suffix."""
        assert ordinal(3) == "3rd", "3 should produce '3rd'"
        assert ordinal(23) == "23rd", "23 should produce '23rd'"

    def test_th_suffix(self) -> None:
        """Integers ending in 0 or 4-9, and the teens 11-13, should use the 'th' suffix."""
        assert ordinal(4) == "4th", "4 should produce '4th'"
        assert ordinal(11) == "11th", "11 should produce '11th' (teen exception)"
        assert ordinal(12) == "12th", "12 should produce '12th' (teen exception)"
        assert ordinal(13) == "13th", "13 should produce '13th' (teen exception)"
        assert ordinal(111) == "111th", "111 should produce '111th'"
        assert ordinal(112) == "112th", "112 should produce '112th'"

    def test_negative_values(self) -> None:
        """Negative integers must also receive the correct ordinal suffix."""
        assert ordinal(-1) == "-1st", "-1 should produce '-1st'"
        assert ordinal(-11) == "-11th", "-11 should produce '-11th'"
        assert ordinal(-13) == "-13th", "-13 should produce '-13th'"


class TestInterquartileBounds:
    """Tests for interquartile_bounds."""

    def test_small_list_returns_defaults(self) -> None:
        """Lists with fewer than 5 elements should return (0.0, inf) defaults."""
        lower, upper = interquartile_bounds([1, 2, 3, 4])
        assert lower == 0.0, f"Lower bound should default to 0.0 for a small list, got {lower}"
        assert upper == float("inf"), f"Upper bound should default to inf for a small list, got {upper}"

    def test_five_elements_computes_bounds(self) -> None:
        """A five-element list should produce finite bounds that contain the data range."""
        data = [1, 2, 3, 4, 5]
        lower, upper = interquartile_bounds(data)
        assert isinstance(lower, float), f"Lower bound should be a float, got {type(lower)}"
        assert isinstance(upper, float), f"Upper bound should be a float, got {type(upper)}"
        assert lower <= 1, f"Lower bound {lower} should be at most the minimum value 1"
        assert upper >= 5, f"Upper bound {upper} should be at least the maximum value 5"

    def test_custom_factor(self) -> None:
        """A smaller IQR factor should yield tighter bounds than the default."""
        data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        lower_default, upper_default = interquartile_bounds(data)
        lower_tight, upper_tight = interquartile_bounds(data, factor=0.5)
        assert upper_tight < upper_default, "A tighter factor should lower the upper bound"
        assert lower_tight > lower_default, "A tighter factor should raise the lower bound"


class TestDiff:
    """Tests for diff."""

    def test_non_negative_default(self) -> None:
        """Negative differences should be clamped to zero by default."""
        result = diff([1, 3, 2, 5])
        assert result == [2, 0, 3], f"Expected [2, 0, 3] with clamping, got {result}"  # decrease clamped to 0

    def test_signed_diff(self) -> None:
        """With non_negative=False, negative differences should be preserved."""
        result = diff([1, 3, 2, 5], non_negative=False)
        assert result == [2, -1, 3], f"Expected [2, -1, 3] with signed diff, got {result}"

    def test_single_pair(self) -> None:
        """A two-element list should yield a one-element difference list."""
        assert diff([4, 7]) == [3], "diff([4, 7]) should produce [3]"

    def test_uniform_sequence(self) -> None:
        """A uniformly increasing sequence should yield all-ones differences."""
        assert diff([0, 1, 2, 3]) == [1, 1, 1], "Uniform step sequence should produce all-ones diff"


class TestPercentile:
    """Tests for percentile."""

    @pytest.mark.parametrize(
        ("data", "pct", "expected"),
        [
            pytest.param([1.0, 2.0, 3.0, 4.0, 5.0], 0, 1.0, id="p0 of [1..5]"),
            pytest.param([1.0, 2.0, 3.0, 4.0, 5.0], 25, 2.0, id="p25 of [1..5]"),
            pytest.param([1.0, 2.0, 3.0, 4.0, 5.0], 50, 3.0, id="p50 of [1..5]"),
            pytest.param([1.0, 2.0, 3.0, 4.0, 5.0], 75, 4.0, id="p75 of [1..5]"),
            pytest.param([1.0, 2.0, 3.0, 4.0, 5.0], 100, 5.0, id="p100 of [1..5]"),
            pytest.param([5.0], 0, 5.0, id="p0 of [5.0]"),
            pytest.param([5.0], 25, 5.0, id="p25 of [5.0]"),
            pytest.param([5.0], 50, 5.0, id="p50 of [5.0]"),
            pytest.param([5.0], 75, 5.0, id="p75 of [5.0]"),
            pytest.param([5.0], 100, 5.0, id="p100 of [5.0]"),
            pytest.param([0.1] * 10 + [0.5], 90, 0.1, id="p90 of 10x0.1+0.5"),
            pytest.param([0.1] * 8 + [0.5], 90, 0.18, id="p90 of 8x0.1+0.5"),
            pytest.param([], 50, 0.0, id="p50 of []"),
        ],
    )
    def test_percentile(self, data: list[float], pct: int, expected: float) -> None:
        """Percentile values must be computed correctly across a range of inputs."""
        result = round(percentile(data, pct), 2)
        assert result == expected, f"p{pct}: expected {expected}, got {result}"
