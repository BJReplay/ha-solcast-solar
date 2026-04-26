"""Unit tests for utility functions in util.py."""

from datetime import UTC, datetime as dt
import math

import pytest

from homeassistant.components.solcast_solar.const import (
    API_LIMIT,
    CUSTOM_HOURS,
    ESTIMATE,
    ESTIMATE10,
    ESTIMATE90,
    ISSUE_UNUSUAL_AZIMUTH_NORTHERN,
    ISSUE_UNUSUAL_AZIMUTH_SOUTHERN,
)
from homeassistant.components.solcast_solar.util import (
    check_unusual_azimuth,
    cubic_interp,
    diff,
    forecast_entry_update,
    format_site_key,
    get_solcast_base_url,
    http_status_translate,
    interquartile_bounds,
    ordinal,
    percentile,
    redact_api_key,
    redact_lat_lon,
    redact_lat_lon_simple,
    redact_msg_api_key,
    split_and_strip,
    sync_legacy_keys,
)


class TestGetSolcastBaseUrl:
    """Tests for get_solcast_base_url."""

    def test_no_port_returns_url_unchanged(self) -> None:
        """Port <= 0 must return the URL with no modification."""
        assert get_solcast_base_url("https://api.solcast.com.au", 0) == "https://api.solcast.com.au", (
            "Port 0 should leave the URL unchanged"
        )
        assert get_solcast_base_url("https://api.solcast.com.au", -1) == "https://api.solcast.com.au", (
            "Negative port should leave the URL unchanged"
        )

    def test_trailing_slash_stripped(self) -> None:
        """Trailing slashes on the base URL should be removed."""
        assert get_solcast_base_url("https://api.solcast.com.au/", 0) == "https://api.solcast.com.au", (
            "Trailing slash must be stripped from the base URL"
        )

    def test_port_injected_into_netloc(self) -> None:
        """A positive port should appear in the returned URL."""
        result = get_solcast_base_url("https://api.solcast.com.au", 8080)
        assert ":8080" in result, f"Port 8080 should appear in the netloc of {result!r}"
        assert result.startswith("https://"), f"Scheme must be preserved as https://, got {result!r}"

    def test_path_preserved_with_port(self) -> None:
        """Any path component must be preserved when a port is injected."""
        result = get_solcast_base_url("https://api.solcast.com.au/v2", 9000)
        assert "/v2" in result, f"Path '/v2' must be preserved in {result!r}"
        assert ":9000" in result, f"Port 9000 must appear in {result!r}"

    def test_ipv6_address_bracketed(self) -> None:
        """IPv6 addresses must be wrapped in brackets when a port is added."""
        result = get_solcast_base_url("https://[::1]", 8080)
        assert "[::1]:8080" in result, f"IPv6 address with port should appear as '[::1]:8080' in {result!r}"


class TestHttpStatusTranslate:
    """Tests for http_status_translate."""

    def test_known_code_returns_string(self) -> None:
        """Known HTTP status codes should return a slash-delimited description string."""
        assert http_status_translate(200) == "200/Success", "HTTP 200 should map to '200/Success'"
        assert http_status_translate(429) == "429/Try again later", "HTTP 429 should map to '429/Try again later'"
        assert http_status_translate(418) == "418/I'm a teapot", "HTTP 418 should map to the teapot status string"

    def test_unknown_code_returns_int(self) -> None:
        """HTTP 999 is a sentinel for a prior crash and should contain that text."""
        result = http_status_translate(999)
        assert "Prior crash" in str(result), f"HTTP 999 result {result!r} should contain 'Prior crash'"

    def test_completely_unknown_code_returns_int(self) -> None:
        """A status code with no translation entry should be returned as-is."""
        result = http_status_translate(599)
        assert result == 599, f"Unknown status 599 should be returned unchanged, got {result!r}"


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


class TestFormatSiteKey:
    """Tests for format_site_key."""

    def test_hyphens_replaced_with_underscores(self) -> None:
        """Hyphens in a site key must be replaced with underscores."""
        assert format_site_key("1234-abcd-5678-efgh") == "1234_abcd_5678_efgh", "Hyphens must be converted to underscores"

    def test_no_hyphens_unchanged(self) -> None:
        """A key without hyphens must pass through unchanged."""
        assert format_site_key("abc123") == "abc123", "Key without hyphens must be returned as-is"


class TestRedactApiKey:
    """Tests for redact_api_key and redact_msg_api_key."""

    def test_redact_api_key_masks_all_but_last_six(self) -> None:
        """All but the last six characters must be replaced with asterisks."""
        key = "ABCDEFGHIJKLMNOP"
        result = redact_api_key(key)
        assert result.endswith("KLMNOP"), f"Last 6 chars of key should be preserved, got {result!r}"
        assert result.startswith("******"), f"Redacted key should start with 6 asterisks, got {result!r}"
        assert len(result) == 12, f"Redacted key should be 12 chars (6 stars + 6 suffix), got length {len(result)}"

    def test_redact_msg_api_key_replaces_in_message(self) -> None:
        """The API key in the message must be replaced with its redacted form."""
        key = "ABCDEFGHIJKLMNOP"
        msg = f"Fetching key={key}"
        result = redact_msg_api_key(msg, key)
        assert key not in result, "Full API key must not appear in the redacted message"
        assert "KLMNOP" in result, "The last 6 chars of the key should still appear in the redacted message"

    def test_redact_msg_api_key_leaves_unrelated_message_intact(self) -> None:
        """A message that does not contain the API key must be returned unchanged."""
        result = redact_msg_api_key("No key here", "SOMEKEY123456")
        assert result == "No key here", "Message without the API key must be returned unchanged"


class TestRedactLatLon:
    """Tests for redact_lat_lon and redact_lat_lon_simple."""

    def test_redact_lat_lon_simple_masks_decimal_places(self) -> None:
        """Decimal parts of lat/lon values must be replaced with asterisks."""
        result = redact_lat_lon_simple("lat=12.34567, lon=-98.765")
        assert "12.******" in result, f"Lat decimal part should be masked in {result!r}"
        assert "-98.******" in result, f"Lon decimal part should be masked in {result!r}"
        assert "34567" not in result, f"Raw decimal digits must not appear in redacted output {result!r}"

    def test_redact_lat_lon_masks_coordinate_values(self) -> None:
        """Latitude and longitude values must be fully masked."""
        result = redact_lat_lon("{'latitude': 12.3456, 'longitude': -98.7654}")
        assert "12.3456" not in result, f"Raw latitude must not appear in {result!r}"
        assert "**.******" in result, f"Latitude should be replaced with a masked placeholder in {result!r}"

    def test_redact_lat_lon_simple_no_decimals_unchanged(self) -> None:
        """A string with no decimal coordinates must pass through unchanged."""
        assert redact_lat_lon_simple("value=5") == "value=5", "String with no decimal coordinates must be returned unchanged"


class TestCheckUnusualAzimuth:
    """Tests for check_unusual_azimuth."""

    def test_northern_facing_south_is_not_unusual(self) -> None:
        """A north-hemisphere site facing south (180°) is a normal orientation."""
        unusual, _, _ = check_unusual_azimuth(51.5, 180)
        assert not unusual, "North-hemisphere site facing 180° (south) should not be flagged as unusual"

    def test_northern_facing_north_positive_is_unusual(self) -> None:
        """A north-hemisphere site facing northeast (45°) should be flagged as unusual."""
        unusual, issue_key, _ = check_unusual_azimuth(51.5, 45)
        assert unusual, "North-hemisphere site facing 45° (northeast) should be flagged as unusual"
        assert issue_key == ISSUE_UNUSUAL_AZIMUTH_NORTHERN, f"Expected northern issue key, got {issue_key!r}"

    def test_southern_facing_north_is_not_unusual(self) -> None:
        """A south-hemisphere site facing north (0°) is a normal orientation."""
        unusual, _, _ = check_unusual_azimuth(-33.9, 0)
        assert not unusual, "South-hemisphere site facing 0° (north) should not be flagged as unusual"

    def test_southern_facing_south_is_unusual(self) -> None:
        """A south-hemisphere site facing south (160°) should be flagged as unusual."""
        unusual, issue_key, _ = check_unusual_azimuth(-33.9, 160)
        assert unusual, "South-hemisphere site facing 160° (south) should be flagged as unusual"
        assert issue_key == ISSUE_UNUSUAL_AZIMUTH_SOUTHERN, f"Expected southern issue key, got {issue_key!r}"

    def test_northern_negative_azimuth_valid(self) -> None:
        """A north-hemisphere site with a westerly negative azimuth (-135°) is a normal orientation."""
        unusual, _, _ = check_unusual_azimuth(51.5, -135)
        assert not unusual, "North-hemisphere site facing -135° (southwest) should not be flagged as unusual"

    def test_northern_negative_azimuth_invalid(self) -> None:
        """A north-hemisphere site with a northerly negative azimuth (-45°) should be flagged."""
        unusual, issue_key, _ = check_unusual_azimuth(51.5, -45)
        assert unusual, "North-hemisphere site facing -45° (northwest) should be flagged as unusual"
        assert issue_key == ISSUE_UNUSUAL_AZIMUTH_NORTHERN, f"Expected northern issue key, got {issue_key!r}"


class TestSyncLegacyKeys:
    """Tests for sync_legacy_keys."""

    def test_api_quota_synced_from_api_limit(self) -> None:
        """The legacy api_quota key should be kept in sync with API_LIMIT."""
        data = {"api_quota": "old", API_LIMIT: "25"}
        sync_legacy_keys(data)
        assert data["api_quota"] == "25", f"api_quota should be synced from {API_LIMIT!r}, got {data['api_quota']!r}"

    def test_customhoursensor_synced_from_custom_hours(self) -> None:
        """The legacy customhoursensor key should be kept in sync with CUSTOM_HOURS."""
        data = {"customhoursensor": 0, CUSTOM_HOURS: 72}
        sync_legacy_keys(data)
        assert data["customhoursensor"] == 72, f"customhoursensor should be synced from {CUSTOM_HOURS!r}, got {data['customhoursensor']!r}"

    def test_no_legacy_keys_unchanged(self) -> None:
        """When no legacy keys are present, none should be created."""
        data = {API_LIMIT: "10", CUSTOM_HOURS: 24}
        sync_legacy_keys(data)
        assert "api_quota" not in data, "api_quota must not be inserted when absent from the entry data"
        assert "customhoursensor" not in data, "customhoursensor must not be inserted when absent from the entry data"


class TestForecastEntryUpdate:
    """Tests for forecast_entry_update."""

    def test_creates_new_entry_without_p10_p90(self) -> None:
        """A new entry with only p50 should contain pv_estimate but no p10/p90 keys."""
        forecasts: dict = {}
        ts = dt(2025, 6, 1, 0, 0, tzinfo=UTC)
        forecast_entry_update(forecasts, ts, 1.5)
        assert forecasts[ts]["pv_estimate"] == 1.5, "pv_estimate must be stored with the provided value"
        assert "pv_estimate10" not in forecasts[ts], "pv_estimate10 must not be present when p10 was not supplied"

    def test_creates_new_entry_with_p10_p90(self) -> None:
        """A new entry created with all three estimates should store each under its constant key."""
        forecasts: dict = {}
        ts = dt(2025, 6, 1, 0, 30, tzinfo=UTC)
        forecast_entry_update(forecasts, ts, 1.5, pv10=1.0, pv90=2.0)
        assert forecasts[ts][ESTIMATE] == 1.5, "p50 estimate must be stored under ESTIMATE"
        assert forecasts[ts][ESTIMATE10] == 1.0, "p10 estimate must be stored under ESTIMATE10"
        assert forecasts[ts][ESTIMATE90] == 2.0, "p90 estimate must be stored under ESTIMATE90"

    def test_updates_existing_entry_estimate(self) -> None:
        """Calling forecast_entry_update on an existing entry must overwrite the p50 estimate."""
        ts = dt(2025, 6, 1, 1, 0, tzinfo=UTC)
        forecasts: dict = {ts: {"period_start": ts, ESTIMATE: 1.0}}
        forecast_entry_update(forecasts, ts, 2.5)
        assert forecasts[ts][ESTIMATE] == 2.5, f"ESTIMATE should be updated to 2.5, got {forecasts[ts][ESTIMATE]!r}"

    def test_updates_existing_entry_p10_p90(self) -> None:
        """Calling forecast_entry_update on an existing entry must overwrite p10 and p90."""
        ts = dt(2025, 6, 1, 1, 30, tzinfo=UTC)
        forecasts: dict = {ts: {"period_start": ts, ESTIMATE: 1.0, ESTIMATE10: 0.5, ESTIMATE90: 1.5}}
        forecast_entry_update(forecasts, ts, 2.0, pv10=1.5, pv90=2.5)
        assert forecasts[ts][ESTIMATE10] == 1.5, f"ESTIMATE10 should be updated to 1.5, got {forecasts[ts][ESTIMATE10]!r}"
        assert forecasts[ts][ESTIMATE90] == 2.5, f"ESTIMATE90 should be updated to 2.5, got {forecasts[ts][ESTIMATE90]!r}"


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
        """Integers ending in 0 or 4–9, and the teens 11–13, should use the 'th' suffix."""
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
