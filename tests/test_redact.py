"""Unit tests for redact.py."""

from custom_components.solcast_solar.const import (
    SITE_ATTRIBUTE_LATITUDE,
    SITE_ATTRIBUTE_LONGITUDE,
)
from custom_components.solcast_solar.redact import (
    format_site_key,
    redact_api_key,
    redact_filename_api_key,
    redact_lat_lon,
    redact_lat_lon_simple,
    redact_msg_api_key,
)


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

    def test_redact_filename_api_key_sites(self) -> None:
        """A sites filename with key segment should have the key redacted."""
        filename = "solcast-sites-BlAhDeBlAhBlAhBlAhABCDEF-260101.json.bak"
        result = redact_filename_api_key(filename)

        assert result == "solcast-sites-******ABCDEF-260101.json.bak"

    def test_redact_filename_api_key_usage(self) -> None:
        """A usage filename with key segment should have the key redacted."""
        filename = "solcast-usage-FeEeFiIiFoOoOoFuMmUVWXYZ-260101.json.bak"
        result = redact_filename_api_key(filename)

        assert result == "solcast-usage-******UVWXYZ-260101.json.bak"

    def test_redact_filename_no_key_undampened(self) -> None:
        """An undampened filename with no key should be unchanged."""
        filename = "solcast-undampened-260101.json.bak"
        result = redact_filename_api_key(filename)

        assert result == "solcast-undampened-260101.json.bak"

    def test_redact_filename_no_key_actuals(self) -> None:
        """A dampened actuals filename with no key should be unchanged."""
        filename = "solcast-actuals-dampened-260101.json.bak"
        result = redact_filename_api_key(filename)

        assert result == "solcast-actuals-dampened-260101.json.bak"


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
        result = redact_lat_lon(f"{{{SITE_ATTRIBUTE_LATITUDE!r}: 12.3456, {SITE_ATTRIBUTE_LONGITUDE!r}: -98.7654}}")
        assert "12.3456" not in result, f"Raw latitude must not appear in {result!r}"
        assert "**.******" in result, f"Latitude should be replaced with a masked placeholder in {result!r}"

    def test_redact_lat_lon_simple_no_decimals_unchanged(self) -> None:
        """A string with no decimal coordinates must pass through unchanged."""
        assert redact_lat_lon_simple("value=5") == "value=5", "String with no decimal coordinates must be returned unchanged"
