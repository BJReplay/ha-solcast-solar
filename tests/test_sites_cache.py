"""Unit tests for Solcast sites cache helper methods."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, timedelta
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from homeassistant.components.solcast_solar.const import (
    API_KEY,
    FORECASTS,
    RESOURCE_ID,
    SITE_ATTRIBUTE_AZIMUTH,
    SITE_ATTRIBUTE_LATITUDE,
    SITE_INFO,
    SITES,
    TOTAL_RECORDS,
)
from homeassistant.components.solcast_solar.enums import LoadStatus
from homeassistant.components.solcast_solar.sites_cache import SitesCache
from homeassistant.util import dt as dt_util


class _ExecutorHass:
    """Minimal hass-like object for executor jobs."""

    def __init__(self, fail_copy: bool = False) -> None:
        """Initialise test executor behavior."""
        self.fail_copy = fail_copy

    async def async_add_executor_job(self, func: Any, *args: Any) -> Any:
        """Run an executor job inline for tests."""
        if self.fail_copy and getattr(func, "__name__", "") == "copy2":
            raise OSError("simulated copy failure")
        return func(*args)


def _make_sites_cache(tmp_path: Path, fail_copy: bool = False) -> SitesCache:
    """Create SitesCache with a minimal fake API object."""
    api = SimpleNamespace(config_dir=str(tmp_path), hass=_ExecutorHass(fail_copy=fail_copy))
    return SitesCache(api)  # pyright: ignore[reportArgumentType]


def test_site_transfer_signature_none_missing_fields(tmp_path: Path) -> None:
    """Signature should be None when required fields are absent."""
    sites_cache = _make_sites_cache(tmp_path)

    assert sites_cache._site_transfer_signature({"capacity_dc": 4.2, "tilt": 30}) is None


def test_site_transfer_signature_none_capacity_not_numeric(tmp_path: Path) -> None:
    """Signature should be None when numeric conversion fails."""
    sites_cache = _make_sites_cache(tmp_path)

    assert sites_cache._site_transfer_signature({"name": "Site", "capacity_dc": "bad", "tilt": 30}) is None


def test_infer_site_transfer_map_returns_empty_on_invalid_extant_site(tmp_path: Path) -> None:
    """Invalid extant metadata should abort transfer inference."""
    sites_cache = _make_sites_cache(tmp_path)

    extant_sites = [{RESOURCE_ID: None, "name": "Second Site", "capacity_dc": 4.2, "tilt": 30}]
    api_sites = [{RESOURCE_ID: "7777-7777-7777-7777", "name": "Second Site", "capacity_dc": 4.2, "tilt": 30}]

    assert sites_cache._infer_site_transfer_map(api_sites, extant_sites) == {}


def test_infer_site_transfer_map_returns_empty_invalid_site(tmp_path: Path) -> None:
    """Invalid API metadata should aborrt transfer inference."""
    sites_cache = _make_sites_cache(tmp_path)

    extant_sites = [{RESOURCE_ID: "2222-2222-2222-2222", "name": "Second Site", "capacity_dc": 4.2, "tilt": 30}]
    api_sites = [{RESOURCE_ID: None, "name": "Second Site", "capacity_dc": 4.2, "tilt": 30}]

    assert sites_cache._infer_site_transfer_map(api_sites, extant_sites) == {}


def test_apply_site_transfer_false_site_info_not_dict(tmp_path: Path) -> None:
    """No migration should occur when SITE_INFO is not a dict."""
    sites_cache = _make_sites_cache(tmp_path)

    data: dict[str, Any] = {SITE_INFO: []}

    assert sites_cache._apply_site_transfer_to_cached_data(data, {"old": "new"}) is False


def test_apply_site_transfer_merges_forecasts(tmp_path: Path) -> None:
    """Transfer should merge old forecasts into extant new-site forecasts."""
    sites_cache = _make_sites_cache(tmp_path)

    old_site_id = "2222-2222-2222-2222"
    new_site_id = "7777-7777-7777-7777"
    data: dict[str, Any] = {
        SITE_INFO: {
            old_site_id: {FORECASTS: [{"k": 1}, {"k": 2}]},
            new_site_id: {FORECASTS: [{"k": 2}, {"k": 3}]},
        }
    }

    changed = sites_cache._apply_site_transfer_to_cached_data(data, {old_site_id: new_site_id})

    assert changed is True
    assert old_site_id not in data[SITE_INFO]
    assert data[SITE_INFO][new_site_id][FORECASTS] == [{"k": 2}, {"k": 3}, {"k": 1}]


def test_match_site_set_against_combined_extant_handles_key_collapse(tmp_path: Path) -> None:
    """Combined extant site matching should recognise a transferred site when keys collapse."""
    sites_cache = _make_sites_cache(tmp_path)

    api_sites = [
        {RESOURCE_ID: "1111-1111-1111-1111", "name": "First Site", "capacity_dc": 6.2, "tilt": 30},
        {RESOURCE_ID: "2222-2222-2222-2222", "name": "Second Site", "capacity_dc": 4.2, "tilt": 30},
        {RESOURCE_ID: "3333-3333-3333-3333", "name": "Third Site", "capacity_dc": 3.5, "tilt": 30},
    ]
    extant_sites = [
        {RESOURCE_ID: "1111-1111-1111-1111", "name": "First Site", "capacity_dc": 6.2, "tilt": 30},
        {RESOURCE_ID: "7777-7777-7777-7777", "name": "Second Site", "capacity_dc": 4.2, "tilt": 30},
        {RESOURCE_ID: "3333-3333-3333-3333", "name": "Third Site", "capacity_dc": 3.5, "tilt": 30},
    ]

    assert sites_cache._match_site_set_against_extant(api_sites, extant_sites) == {"7777-7777-7777-7777": "2222-2222-2222-2222"}


def test_match_site_set_against_extant_returns_none_without_api_site_ids(tmp_path: Path) -> None:
    """Matching should fail when API sites contain no valid resource ids."""
    sites_cache = _make_sites_cache(tmp_path)

    api_sites = [{RESOURCE_ID: None, "name": "First Site", "capacity_dc": 6.2, "tilt": 30}]
    extant_sites = [{RESOURCE_ID: "1111-1111-1111-1111", "name": "First Site", "capacity_dc": 6.2, "tilt": 30}]

    assert sites_cache._match_site_set_against_extant(api_sites, extant_sites) is None


@pytest.mark.asyncio
async def test_backup_caches_prunes_old_creates_current(tmp_path: Path) -> None:
    """Backup helper should prune old dated backups and create today's backup."""
    sites_cache = _make_sites_cache(tmp_path)

    cache_file = tmp_path / "solcast.json"
    cache_file.write_text("{}", encoding="utf-8")

    old_day = (dt_util.now(UTC) - timedelta(days=1)).strftime("%y%m%d")
    today = dt_util.now(UTC).strftime("%y%m%d")
    old_backup = tmp_path / f"solcast-{old_day}.json.bak"
    old_backup.write_text("{}", encoding="utf-8")
    legacy_backup = tmp_path / f"solcast-{today}-auto_backup.json"
    legacy_backup.write_text("{}", encoding="utf-8")

    await sites_cache._backup_json_caches()

    assert not old_backup.exists()
    assert not legacy_backup.exists()
    assert (tmp_path / f"solcast-{today}.json.bak").is_file()


@pytest.mark.asyncio
async def test_backup_caches_handles_errors(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Backup helper should tolerate copy failures and log a warning."""
    sites_cache = _make_sites_cache(tmp_path, fail_copy=True)
    caplog.set_level(logging.WARNING)

    cache_file = tmp_path / "solcast.json"
    cache_file.write_text("{}", encoding="utf-8")

    await sites_cache._backup_json_caches()

    assert "Could not create backup" in caplog.text


@pytest.mark.asyncio
async def test_sites_data_uses_combined_extant_match_for_key_collapse(tmp_path: Path) -> None:
    """_sites_data should fall back to combined extant sites when keys collapse."""

    api = SimpleNamespace(
        config_dir=str(tmp_path),
        options=SimpleNamespace(api_key="newkey"),
        sites_status=LoadStatus.OK,
        sites=[],
        http_status_translate=lambda status: f"{status}",
        entry=None,
    )
    sites_cache = SitesCache(api)  # pyright: ignore[reportArgumentType]

    response_json = {
        SITES: [
            {
                RESOURCE_ID: "1111-1111-1111-1111",
                "name": "First Site",
                "capacity_dc": 6.2,
                "tilt": 30,
                SITE_ATTRIBUTE_LATITUDE: -11.11111,
                SITE_ATTRIBUTE_AZIMUTH: 66,
            },
            {
                RESOURCE_ID: "3333-3333-3333-3333",
                "name": "Third Site",
                "capacity_dc": 3.5,
                "tilt": 30,
                SITE_ATTRIBUTE_LATITUDE: -11.11111,
                SITE_ATTRIBUTE_AZIMUTH: 66,
            },
        ],
        TOTAL_RECORDS: 2,
    }
    (tmp_path / "solcast-sites.json").write_text(json.dumps(response_json), encoding="utf-8")

    sites_cache._extant_sites = defaultdict(
        list,
        {
            "old-key-a": [
                {RESOURCE_ID: "1111-1111-1111-1111", "name": "First Site", "capacity_dc": 6.2, "tilt": 30},
                {RESOURCE_ID: "2222-2222-2222-2222", "name": "Second Site", "capacity_dc": 4.2, "tilt": 30},
            ],
            "old-key-b": [
                {RESOURCE_ID: "1111-1111-1111-1111", "name": "First Site", "capacity_dc": 6.2, "tilt": 30},
            ],
            "old-key-c": [
                {RESOURCE_ID: "3333-3333-3333-3333", "name": "Third Site", "capacity_dc": 3.5, "tilt": 30},
            ],
        },
    )

    match_calls: list[list[dict[str, Any]]] = []
    original_match = sites_cache._match_site_set_against_extant

    def tracking_match(api_sites: list[dict[str, Any]], extant_sites: list[dict[str, Any]]) -> dict[str, str] | None:
        match_calls.append(extant_sites)
        return original_match(api_sites, extant_sites)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sites_cache, "_old_api_key_for_comparison", lambda: "old-key-a,old-key-b,old-key-c")
        mp.setattr(sites_cache, "_match_site_set_against_extant", tracking_match)
        status, _, _ = await sites_cache._sites_data(prior_crash=True, use_cache=True)

    assert status == 200
    assert api.sites_status is LoadStatus.OK
    assert len(api.sites) == 2
    assert all(site[API_KEY] == "newkey" for site in api.sites)

    assert len(match_calls) == 4
    assert [site[RESOURCE_ID] for site in match_calls[-1]] == [
        "1111-1111-1111-1111",
        "2222-2222-2222-2222",
        "3333-3333-3333-3333",
    ]
