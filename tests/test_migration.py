"""Unit tests for migration.py."""

from custom_components.solcast_solar.const import API_LIMIT, CUSTOM_HOURS
from custom_components.solcast_solar.migration import sync_legacy_keys


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
