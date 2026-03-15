"""Unit tests for upgrade_cache_schema in util.py and config entry schema migration."""

import copy

import pytest

from homeassistant.components.solcast_solar.const import (
    AUTO_UPDATED,
    FAILURE,
    FORECASTS,
    INTEGRATION_VERSION,
    JSON_VERSION,
    LAST_7D,
    LAST_14D,
    LAST_24H,
    LAST_ATTEMPT,
    LAST_UPDATED,
    SITE_INFO,
    VERSION,
)
from homeassistant.components.solcast_solar.util import (
    SchemaIncompatibleError,
    upgrade_cache_schema,
)

SITE_ID = "3333-3333-3333-3333"
SAMPLE_FORECASTS: list = [{"period_start": "2025-01-01T00:00:00", "pv_estimate": 1.0}]
LAST_UPDATED_VALUE = "2025-01-01T00:00:00+00:00"

# Base data resembling a current v9 cache file.
BASE_DATA: dict = {
    SITE_INFO: {SITE_ID: {FORECASTS: copy.deepcopy(SAMPLE_FORECASTS)}},
    LAST_UPDATED: LAST_UPDATED_VALUE,
    LAST_ATTEMPT: LAST_UPDATED_VALUE,
    AUTO_UPDATED: 0,
    FAILURE: {LAST_24H: 0, LAST_7D: [0] * 7, LAST_14D: [0] * 14},
    INTEGRATION_VERSION: "",
    VERSION: JSON_VERSION,
}


def test_upgrade_from_v4() -> None:
    """Test upgrading v4 cache data to the current version."""
    data = copy.deepcopy(BASE_DATA)
    data[VERSION] = 4
    data.pop(LAST_ATTEMPT)
    data.pop(AUTO_UPDATED)

    result = upgrade_cache_schema(data, 4, SITE_ID, auto_update_enabled=True)

    assert result == JSON_VERSION
    assert data[VERSION] == JSON_VERSION
    assert data[LAST_ATTEMPT] == LAST_UPDATED_VALUE
    assert data[AUTO_UPDATED] == 99999
    assert data[FAILURE] == {LAST_24H: 0, LAST_7D: [0] * 7, LAST_14D: [0] * 14}
    assert data[INTEGRATION_VERSION] == "unknown"


def test_upgrade_from_ancient() -> None:
    """Test upgrading ancient (v1, no version key) cache data to the current version."""
    data = copy.deepcopy(BASE_DATA)
    data.pop(VERSION)
    data.pop(LAST_ATTEMPT)
    data.pop(AUTO_UPDATED)
    data[FORECASTS] = copy.deepcopy(SAMPLE_FORECASTS)
    data.pop(SITE_INFO)

    result = upgrade_cache_schema(data, 1, SITE_ID, auto_update_enabled=True)

    assert result == JSON_VERSION
    assert data[VERSION] == JSON_VERSION
    assert data[LAST_ATTEMPT] == LAST_UPDATED_VALUE
    assert data[AUTO_UPDATED] == 99999
    assert data[INTEGRATION_VERSION] == "unknown"
    # Forecasts should have been migrated under siteinfo.
    assert data[SITE_INFO] == {SITE_ID: {FORECASTS: SAMPLE_FORECASTS}}
    assert FORECASTS not in data


def test_upgrade_auto_update_disabled() -> None:
    """Test upgrade with auto_update disabled sets auto_updated to zero."""
    data = copy.deepcopy(BASE_DATA)
    data[VERSION] = 4
    data.pop(LAST_ATTEMPT)
    data.pop(AUTO_UPDATED)

    result = upgrade_cache_schema(data, 4, SITE_ID, auto_update_enabled=False)

    assert result == JSON_VERSION
    assert data[AUTO_UPDATED] == 0


def test_incompatible_no_siteinfo_no_forecasts() -> None:
    """Test that data with neither siteinfo nor forecasts is incompatible."""
    data = {
        LAST_UPDATED: LAST_UPDATED_VALUE,
        "some_stuff": {"fraggle": "rock"},
    }

    with pytest.raises(SchemaIncompatibleError, match="Neither siteinfo nor forecasts"):
        upgrade_cache_schema(data, 1, SITE_ID, auto_update_enabled=True)


def test_incompatible_siteinfo_wrong_shape() -> None:
    """Test that siteinfo with wrong internal structure is incompatible."""
    data = copy.deepcopy(BASE_DATA)
    data.pop(VERSION, None)
    data[SITE_INFO] = {"weird": "stuff"}
    data[FORECASTS] = "favourable"
    data.pop(LAST_ATTEMPT)
    data.pop(AUTO_UPDATED)

    with pytest.raises(SchemaIncompatibleError, match="siteinfo forecasts is not a list"):
        upgrade_cache_schema(data, 1, SITE_ID, auto_update_enabled=True)


def test_incompatible_forecasts_not_a_list() -> None:
    """Test that top-level forecasts that is not a list is incompatible."""
    data = {LAST_UPDATED: LAST_UPDATED_VALUE, FORECASTS: "bad"}

    with pytest.raises(SchemaIncompatibleError, match="Top-level forecasts is not a list"):
        upgrade_cache_schema(data, 1, SITE_ID, auto_update_enabled=True)
