"""Unit tests for the per-entry crash-state store."""

from datetime import UTC, datetime as dt

import pytest

from homeassistant.components.solcast_solar import crash_state
from homeassistant.components.solcast_solar.crash_state import (
    CrashStateStore,
    async_get,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed


@pytest.mark.asyncio
async def test_async_load_restores_state_from_disk(hass: HomeAssistant) -> None:
    """A fresh store should rehydrate every field saved by a prior instance."""
    entry_id = "crash_state_load_test"
    crash_state._STORES.pop(entry_id, None)  # noqa: SLF001
    saved = CrashStateStore(hass, entry_id)
    saved.state.presumed_dead = True
    saved.state.crash_time = dt(2025, 6, 1, 12, 30, tzinfo=UTC)
    saved.state.exception_class = ConfigEntryAuthFailed
    saved.state.translation_key = "auth_failed"
    saved.state.translation_placeholders = {"reason": "bad_key"}
    await saved.async_save()

    crash_state._STORES.pop(entry_id, None)  # noqa: SLF001
    loaded = await async_get(hass, entry_id)
    assert loaded.state.presumed_dead is True
    assert loaded.state.crash_time == dt(2025, 6, 1, 12, 30, tzinfo=UTC)
    assert loaded.state.exception_class is ConfigEntryAuthFailed
    assert loaded.state.translation_key == "auth_failed"
    assert loaded.state.translation_placeholders == {"reason": "bad_key"}

    await loaded.async_clear()
    crash_state._STORES.pop(entry_id, None)  # noqa: SLF001
