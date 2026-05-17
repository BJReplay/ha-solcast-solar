"""Tests for Solcast PV SimCity config entry setup."""

from __future__ import annotations

from custom_components.solcast_sim import (  # pyright: ignore[reportMissingImports]
    DOMAIN,
    _get_adjacent_solcast_api_key,
    _get_api_key_from_entry,
    _sync_api_key_mismatch_issue,
    async_migrate_entry,
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


async def test_get_adjacent_solcast_api_key_present(hass: HomeAssistant) -> None:
    """Return key from adjacent solcast_solar entry."""
    entry = MockConfigEntry(domain="solcast_solar", data={"api_key": "1"}, options={})
    entry.add_to_hass(hass)
    assert _get_adjacent_solcast_api_key(hass) == "1"


async def test_get_adjacent_solcast_api_key_absent(hass: HomeAssistant) -> None:
    """Return None when no adjacent solcast_solar entry."""
    assert _get_adjacent_solcast_api_key(hass) is None


async def test_sync_issue_deleted_when_keys_match(hass: HomeAssistant) -> None:
    """No repair issue created when SimCity and Solcast keys are the same."""
    solar = MockConfigEntry(domain="solcast_solar", data={"api_key": "1"}, options={})
    solar.add_to_hass(hass)
    sim = MockConfigEntry(domain="solcast_sim", data={"api_key": "1"}, options={}, entry_id="sim-1", version=6)
    sim.add_to_hass(hass)

    _sync_api_key_mismatch_issue(hass, sim)

    issue_reg = ir.async_get(hass)
    assert issue_reg.async_get_issue(DOMAIN, "api_key_mismatch_sim-1") is None


async def test_sync_issue_deleted_when_no_solcast_entry(hass: HomeAssistant) -> None:
    """No repair issue when there is no adjacent Solcast integration."""
    sim = MockConfigEntry(domain="solcast_sim", data={"api_key": "1"}, options={}, entry_id="sim-1", version=6)
    sim.add_to_hass(hass)

    _sync_api_key_mismatch_issue(hass, sim)

    issue_reg = ir.async_get(hass)
    assert issue_reg.async_get_issue(DOMAIN, "api_key_mismatch_sim-1") is None


async def test_sync_issue_created_when_keys_differ(hass: HomeAssistant) -> None:
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


async def test_sync_issue_suppressed_when_suppress_pair_matches(hass: HomeAssistant) -> None:
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
