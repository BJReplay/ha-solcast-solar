"""Tests for Solcast PV SimCity config entry setup."""

from __future__ import annotations

from unittest.mock import AsyncMock

from custom_components.solcast_sim import (  # pyright: ignore[reportMissingImports]
    DOMAIN,
    _async_update_listener,
    _get_adjacent_solcast_api_key,
    _get_api_key_from_entry,
    _sync_api_key_mismatch_issue,
    async_migrate_entry,
    async_setup_entry,
    async_unload_entry,
)
import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from tests.common import MockConfigEntry


@pytest.fixture
def ignore_translations_for_mock_domains() -> list[str]:
    """Do not validate translations for the custom solcast_sim domain."""
    return ["solcast_sim"]


def test_get_api_key_from_entry_uses_data() -> None:
    """Return canonical key from entry.data."""
    entry = MockConfigEntry(domain="solcast_sim", data={"api_key": " 1 "}, options={})
    assert _get_api_key_from_entry(entry) == "1"


def test_get_api_key_from_entry_options_override() -> None:
    """Options api_key takes priority over data api_key."""
    entry = MockConfigEntry(domain="solcast_sim", data={"api_key": "1"}, options={"api_key": "2"})
    assert _get_api_key_from_entry(entry) == "2"


def test_get_api_key_from_entry_empty_when_absent() -> None:
    """Return empty string when no api_key present."""
    entry = MockConfigEntry(domain="solcast_sim", data={}, options={})
    assert _get_api_key_from_entry(entry) == ""


async def test_get_adjacent_api_key_present(hass: HomeAssistant) -> None:
    """Return key from adjacent solcast_solar entry."""
    entry = MockConfigEntry(domain="solcast_solar", data={"api_key": "1"}, options={})
    entry.add_to_hass(hass)
    assert _get_adjacent_solcast_api_key(hass) == "1"


async def test_get_adjacent_api_key_absent(hass: HomeAssistant) -> None:
    """Return None when no adjacent solcast_solar entry."""
    assert _get_adjacent_solcast_api_key(hass) is None


async def test_sync_issue_keys_match(hass: HomeAssistant) -> None:
    """No repair issue created when SimCity and Solcast keys are the same."""
    solar = MockConfigEntry(domain="solcast_solar", data={"api_key": "1"}, options={})
    solar.add_to_hass(hass)
    sim = MockConfigEntry(domain="solcast_sim", data={"api_key": "1"}, options={}, entry_id="sim-1", version=6)
    sim.add_to_hass(hass)

    _sync_api_key_mismatch_issue(hass, sim)

    issue_reg = ir.async_get(hass)
    assert issue_reg.async_get_issue(DOMAIN, "api_key_mismatch_sim-1") is None


async def test_sync_issue_no_solcast_entry(hass: HomeAssistant) -> None:
    """No repair issue when there is no adjacent Solcast integration."""
    sim = MockConfigEntry(domain="solcast_sim", data={"api_key": "1"}, options={}, entry_id="sim-1", version=6)
    sim.add_to_hass(hass)

    _sync_api_key_mismatch_issue(hass, sim)

    issue_reg = ir.async_get(hass)
    assert issue_reg.async_get_issue(DOMAIN, "api_key_mismatch_sim-1") is None


async def test_sync_issue_keys_differ(hass: HomeAssistant) -> None:
    """Repair issue created when SimCity and Solcast keys differ."""
    solar = MockConfigEntry(domain="solcast_solar", data={"api_key": "2"}, options={})
    solar.add_to_hass(hass)
    sim = MockConfigEntry(domain="solcast_sim", data={"api_key": "1"}, options={}, entry_id="sim-1", version=6)
    sim.add_to_hass(hass)

    _sync_api_key_mismatch_issue(hass, sim)

    issue_reg = ir.async_get(hass)
    issue = issue_reg.async_get_issue(DOMAIN, "api_key_mismatch_sim-1")
    assert issue is not None
    assert issue.is_fixable


async def test_sync_issue_suppressed(hass: HomeAssistant) -> None:
    """Suppress the repair issue when the suppress pair matches the current mismatch."""
    solar = MockConfigEntry(domain="solcast_solar", data={"api_key": "2"}, options={})
    solar.add_to_hass(hass)
    sim = MockConfigEntry(
        domain="solcast_sim",
        data={"api_key": "1"},
        options={"api_key_mismatch_suppress_pair": "1|2"},
        entry_id="sim-1",
        version=6,
    )
    sim.add_to_hass(hass)

    _sync_api_key_mismatch_issue(hass, sim)

    issue_reg = ir.async_get(hass)
    assert issue_reg.async_get_issue(DOMAIN, "api_key_mismatch_sim-1") is None


async def test_async_migrate_entry_rejects_future_version(hass: HomeAssistant) -> None:
    """Return False and do not migrate when the entry version is too new."""
    entry = MockConfigEntry(
        domain="solcast_sim",
        data={"api_key": "1"},
        options={},
        version=99,
    )
    entry.add_to_hass(hass)

    result = await async_migrate_entry(hass, entry)
    assert result is False


async def test_async_setup_entry_forwards_platforms(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """async_setup_entry forwards platform setup and returns True."""
    entry = MockConfigEntry(
        domain="solcast_sim",
        data={"api_key": "1"},
        options={},
        version=6,
        entry_id="test-setup",
    )
    entry.add_to_hass(hass)
    mock_forward = AsyncMock()
    monkeypatch.setattr(hass.config_entries, "async_forward_entry_setups", mock_forward)

    result = await async_setup_entry(hass, entry)

    assert result is True
    mock_forward.assert_called_once()


async def test_async_unload_entry_success(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """async_unload_entry returns True when all platforms unload successfully."""
    entry = MockConfigEntry(
        domain="solcast_sim",
        data={"api_key": "1"},
        options={},
        version=6,
        entry_id="test-unload",
    )
    entry.add_to_hass(hass)
    monkeypatch.setattr(hass.config_entries, "async_unload_platforms", AsyncMock(return_value=True))

    result = await async_unload_entry(hass, entry)

    assert result is True


async def test_async_unload_entry_failure(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """async_unload_entry returns False when platform unload fails."""
    entry = MockConfigEntry(
        domain="solcast_sim",
        data={"api_key": "1"},
        options={},
        version=6,
        entry_id="test-unload-fail",
    )
    entry.add_to_hass(hass)
    monkeypatch.setattr(hass.config_entries, "async_unload_platforms", AsyncMock(return_value=False))

    result = await async_unload_entry(hass, entry)

    assert result is False


async def test_async_update_listener_reloads(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_async_update_listener triggers a config entry reload."""
    entry = MockConfigEntry(
        domain="solcast_sim",
        data={"api_key": "1"},
        options={},
        version=6,
        entry_id="reload-test",
    )
    entry.add_to_hass(hass)
    mock_reload = AsyncMock()
    monkeypatch.setattr(hass.config_entries, "async_reload", mock_reload)

    await _async_update_listener(hass, entry)

    mock_reload.assert_called_once_with("reload-test")


@pytest.mark.parametrize(
    ("initial_data", "from_version", "expected_key", "expected_value"),
    [
        pytest.param(
            {"api_key": "1", "shade_height_m": 12.0, "shade_width_m": 8.0, "shade_distance_m": 15.0},
            1,
            "shade_dimensions",
            "12.0, 8.0, 15.0",
            id="v1_groups_shade_dimensions",
        ),
        pytest.param(
            {
                "api_key": "1",
                "shade_dimensions": "12.0, 8.0, 15.0",
                "cloudiness_bias": 0.0,
                "cloud_variability": 0.7,
            },
            2,
            "cloudiness_profile",
            "0.0, 0.7",
            id="v2_groups_cloudiness_profile",
        ),
        pytest.param(
            {"api_key": "1", "shade_dimensions": "12.0, 8.0, 15.0"},
            4,
            "estimated_actuals_uncertainty_pct",
            15.0,
            id="v4_adds_uncertainty",
        ),
        pytest.param(
            {
                "api_key": "1",
                "shade_dimensions": "12.0, 8.0, 15.0",
                "estimated_actuals_uncertainty_pct": 15.0,
            },
            5,
            "shade_density_profile",
            "0.3, 0.8, 1.0",
            id="v5_adds_density_profile",
        ),
    ],
)
async def test_migrate_entry_upgrades_to_v6(
    hass: HomeAssistant,
    initial_data: dict,
    from_version: int,
    expected_key: str,
    expected_value: object,
) -> None:
    """async_migrate_entry applies all required upgrade steps and returns True."""
    entry = MockConfigEntry(
        domain="solcast_sim",
        data=initial_data,
        options={},
        version=from_version,
    )
    entry.add_to_hass(hass)

    result = await async_migrate_entry(hass, entry)

    assert result is True
    assert entry.version == 6
    assert entry.data.get(expected_key) == expected_value


async def test_migrate_entry_noop_at_current_version(hass: HomeAssistant) -> None:
    """async_migrate_entry on a current v6 entry makes no changes and returns True."""
    data = {
        "api_key": "1",
        "shade_dimensions": "12.0, 8.0, 15.0",
        "shade_density_profile": "0.3, 0.8, 1.0",
        "estimated_actuals_uncertainty_pct": 15.0,
    }
    entry = MockConfigEntry(domain="solcast_sim", data=data, options={}, version=6)
    entry.add_to_hass(hass)

    result = await async_migrate_entry(hass, entry)

    assert result is True
    assert entry.version == 6
    assert entry.data == data


async def test_migrate_v2_grouped_fields_else_branches(hass: HomeAssistant) -> None:
    """v3 else-branches: already-grouped fields cause old keys to be popped."""
    entry = MockConfigEntry(
        domain="solcast_sim",
        data={
            "api_key": "1",
            "shade_dimensions": "12.0, 8.0, 15.0",
            "location_coordinates": "-33.0, 151.0",
            "latitude": -33.0,
            "longitude": 151.0,
            "cloudiness_profile": "0.0, 0.7",
            "cloudiness_bias": 0.0,
            "cloud_variability": 0.7,
            "battery_power_limits_kw": "5.0, 5.0",
            "battery_max_charge_kw": 5.0,
            "battery_max_discharge_kw": 5.0,
        },
        options={},
        version=2,
    )
    entry.add_to_hass(hass)

    result = await async_migrate_entry(hass, entry)

    assert result is True
    assert entry.version == 6
    assert "latitude" not in entry.data
    assert "longitude" not in entry.data
    assert "cloudiness_bias" not in entry.data
    assert "cloud_variability" not in entry.data
    assert "battery_max_charge_kw" not in entry.data
    assert "battery_max_discharge_kw" not in entry.data
