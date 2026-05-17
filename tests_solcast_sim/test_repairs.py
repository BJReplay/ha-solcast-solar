"""Tests for Solcast PV SimCity repair flows."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from custom_components.solcast_sim.repairs import (  # pyright: ignore[reportMissingImports]
    REPAIR_ACTION,
    REPAIR_ACTION_KEEP,
    REPAIR_ACTION_SYNC,
    ApiKeyMismatchRepairFlow,
    _get_adjacent_solcast_api_key,
    _get_api_key_from_entry,
    async_create_fix_flow,
)

from homeassistant.core import HomeAssistant

from tests.common import MockConfigEntry


def test_get_api_key_from_entry_data_only() -> None:
    """Return canonical key from entry.data when options is empty."""
    entry = MockConfigEntry(domain="solcast_sim", data={"api_key": " 1 "}, options={})
    result = _get_api_key_from_entry(entry)
    assert result == "1"


def test_get_api_key_from_entry_options_override_data() -> None:
    """Prefer entry.options value over entry.data."""
    entry = MockConfigEntry(
        domain="solcast_sim",
        data={"api_key": "1"},
        options={"api_key": "2"},
    )
    result = _get_api_key_from_entry(entry)
    assert result == "2"


def test_get_api_key_from_entry_missing_key() -> None:
    """Return empty string when api_key is absent."""
    entry = MockConfigEntry(domain="solcast_sim", data={}, options={})
    result = _get_api_key_from_entry(entry)
    assert result == ""


async def test_get_adjacent_solcast_api_key_returns_key(hass: HomeAssistant) -> None:
    """Return canonical key from the adjacent solcast_solar entry."""
    entry = MockConfigEntry(domain="solcast_solar", data={"api_key": " 1 "}, options={})
    entry.add_to_hass(hass)
    assert _get_adjacent_solcast_api_key(hass) == "1"


async def test_get_adjacent_solcast_api_key_returns_none_when_absent(hass: HomeAssistant) -> None:
    """Return None when there is no adjacent solcast_solar entry."""
    assert _get_adjacent_solcast_api_key(hass) is None


async def test_get_adjacent_solcast_api_key_skips_empty_key(hass: HomeAssistant) -> None:
    """Skip a solcast_solar entry whose api_key is empty."""
    entry = MockConfigEntry(domain="solcast_solar", data={"api_key": ""}, options={})
    entry.add_to_hass(hass)
    assert _get_adjacent_solcast_api_key(hass) is None


async def test_async_create_fix_flow_returns_repair_flow_instance(hass: HomeAssistant) -> None:
    """Factory returns an ApiKeyMismatchRepairFlow with the correct entry_id."""
    flow = await async_create_fix_flow(hass, "api_key_mismatch_abc", {"entry_id": "abc"})
    assert isinstance(flow, ApiKeyMismatchRepairFlow)
    assert flow._entry_id == "abc"


async def test_async_create_fix_flow_uses_empty_entry_id_when_data_is_none(hass: HomeAssistant) -> None:
    """Factory handles None data gracefully."""
    flow = await async_create_fix_flow(hass, "api_key_mismatch_abc", None)
    assert isinstance(flow, ApiKeyMismatchRepairFlow)
    assert flow._entry_id == ""


def _make_repair_flow(hass: HomeAssistant, entry_id: str) -> ApiKeyMismatchRepairFlow:
    """Create a repair flow instance with hass set and minimal attrs."""
    flow = ApiKeyMismatchRepairFlow(entry_id)
    flow.hass = hass
    flow.handler = "solcast_sim"
    flow.issue_id = f"api_key_mismatch_{entry_id}"
    return flow


async def test_repair_flow_aborts_when_entry_not_found(hass: HomeAssistant) -> None:
    """Abort with entry_not_found when entry_id does not exist."""
    flow = _make_repair_flow(hass, "nonexistent-entry")
    result = await flow.async_step_init(None)
    assert result["type"] == "abort"  # pyright: ignore[reportTypedDictNotRequiredAccess]
    assert result["reason"] == "entry_not_found"  # pyright: ignore[reportTypedDictNotRequiredAccess]


async def test_repair_flow_aborts_when_no_solcast_entry(hass: HomeAssistant) -> None:
    """Abort with missing_solcast when no adjacent solcast_solar entry exists."""
    entry = MockConfigEntry(
        domain="solcast_sim",
        data={"api_key": "1"},
        options={},
        entry_id="sim-abc",
        version=6,
    )
    entry.add_to_hass(hass)
    flow = _make_repair_flow(hass, "sim-abc")
    result = await flow.async_step_init(None)
    assert result["type"] == "abort"  # pyright: ignore[reportTypedDictNotRequiredAccess]
    assert result["reason"] == "missing_solcast"  # pyright: ignore[reportTypedDictNotRequiredAccess]


async def test_repair_flow_shows_form_when_no_user_input(hass: HomeAssistant) -> None:
    """Show the repair form when no user_input is provided."""
    solar_entry = MockConfigEntry(domain="solcast_solar", data={"api_key": "2"}, options={})
    solar_entry.add_to_hass(hass)
    sim_entry = MockConfigEntry(
        domain="solcast_sim",
        data={"api_key": "1"},
        options={},
        entry_id="sim-abc",
        version=6,
    )
    sim_entry.add_to_hass(hass)
    flow = _make_repair_flow(hass, "sim-abc")
    result = await flow.async_step_init(None)
    assert result["type"] == "form"  # pyright: ignore[reportTypedDictNotRequiredAccess]
    assert result["step_id"] == "init"  # pyright: ignore[reportTypedDictNotRequiredAccess]


async def test_repair_flow_sync_action_updates_api_key(hass: HomeAssistant) -> None:
    """SYNC action updates SimCity api_key to match Solcast and reloads entry."""
    solar_entry = MockConfigEntry(domain="solcast_solar", data={"api_key": "2"}, options={})
    solar_entry.add_to_hass(hass)
    sim_entry = MockConfigEntry(
        domain="solcast_sim",
        data={"api_key": "1"},
        options={},
        entry_id="sim-abc",
        version=6,
    )
    sim_entry.add_to_hass(hass)

    flow = _make_repair_flow(hass, "sim-abc")
    with patch.object(hass.config_entries, "async_reload", new=AsyncMock()) as mock_reload:
        result = await flow.async_step_init({REPAIR_ACTION: REPAIR_ACTION_SYNC})

    assert result["type"] == "create_entry"  # pyright: ignore[reportTypedDictNotRequiredAccess]
    updated_entry = hass.config_entries.async_get_entry("sim-abc")
    assert updated_entry is not None
    assert updated_entry.options["api_key"] == "2"
    mock_reload.assert_called_once_with("sim-abc")


async def test_repair_flow_keep_action_stores_suppress_pair(hass: HomeAssistant) -> None:
    """KEEP action stores the mismatch pair in options to suppress the issue."""
    solar_entry = MockConfigEntry(domain="solcast_solar", data={"api_key": "2"}, options={})
    solar_entry.add_to_hass(hass)
    sim_entry = MockConfigEntry(
        domain="solcast_sim",
        data={"api_key": "1"},
        options={},
        entry_id="sim-abc",
        version=6,
    )
    sim_entry.add_to_hass(hass)

    flow = _make_repair_flow(hass, "sim-abc")
    with patch.object(hass.config_entries, "async_reload", new=AsyncMock()) as mock_reload:
        result = await flow.async_step_init({REPAIR_ACTION: REPAIR_ACTION_KEEP})

    assert result["type"] == "create_entry"  # pyright: ignore[reportTypedDictNotRequiredAccess]
    updated_entry = hass.config_entries.async_get_entry("sim-abc")
    assert updated_entry is not None
    assert updated_entry.options["api_key_mismatch_suppress_pair"] == "1|2"
    mock_reload.assert_called_once_with("sim-abc")


async def test_repair_flow_sync_removes_suppress_pair(hass: HomeAssistant) -> None:
    """SYNC action removes api_key_mismatch_suppress_pair if present."""
    solar_entry = MockConfigEntry(domain="solcast_solar", data={"api_key": "2"}, options={})
    solar_entry.add_to_hass(hass)
    sim_entry = MockConfigEntry(
        domain="solcast_sim",
        data={"api_key": "1"},
        options={"api_key_mismatch_suppress_pair": "1|old"},
        entry_id="sim-abc",
        version=6,
    )
    sim_entry.add_to_hass(hass)

    flow = _make_repair_flow(hass, "sim-abc")
    with patch.object(hass.config_entries, "async_reload", new=AsyncMock()):
        await flow.async_step_init({REPAIR_ACTION: REPAIR_ACTION_SYNC})

    updated_entry = hass.config_entries.async_get_entry("sim-abc")
    assert updated_entry is not None
    assert "api_key_mismatch_suppress_pair" not in updated_entry.options
