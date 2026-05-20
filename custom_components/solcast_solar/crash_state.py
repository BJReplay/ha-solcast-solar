"""Persistent per-entry crash state for the Solcast integration.

Stored format on disk::

    {
        "presumed_dead": bool,
        "crash_time": str | None, (ISO format)
        "exception_code": str | None,
        "translation_key": str | None,
        "translation_placeholders": dict[str, Any] | None,
    }
"""

from dataclasses import dataclass
from datetime import datetime as dt
from typing import Any, TypedDict

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
    IntegrationError,
)
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_STORAGE_VERSION = 1

_CODE_TO_EXCEPTION: dict[str, type[IntegrationError]] = {
    "auth_failed": ConfigEntryAuthFailed,
    "not_ready": ConfigEntryNotReady,
    "fatal": ConfigEntryError,
}
_EXCEPTION_TO_CODE: dict[type[IntegrationError], str] = {cls: code for code, cls in _CODE_TO_EXCEPTION.items()}


class _StoredState(TypedDict, total=False):
    presumed_dead: bool
    crash_time: str | None
    exception_code: str | None
    translation_key: str | None
    translation_placeholders: dict[str, Any] | None


@dataclass
class CrashState:
    """In-memory view of crash state for a single config entry."""

    presumed_dead: bool = False
    crash_time: dt | None = None
    exception_class: type[IntegrationError] | None = None
    translation_key: str | None = None
    translation_placeholders: dict[str, Any] | None = None


class CrashStateStore:
    """Per-entry crash state backed by helpers.storage.Store."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialise the backing store for a config entry."""
        self._store: Store[_StoredState] = Store(hass, _STORAGE_VERSION, f"{DOMAIN}.crash_state.{entry_id}")
        self.state: CrashState = CrashState()

    async def async_load(self) -> None:
        """Populate self.state from disk, if any data is present."""
        data = await self._store.async_load()
        if not data:
            return
        self.state.presumed_dead = bool(data.get("presumed_dead", False))
        crash_time = data.get("crash_time")
        self.state.crash_time = dt.fromisoformat(crash_time) if crash_time else None
        exception_code = data.get("exception_code")
        self.state.exception_class = _CODE_TO_EXCEPTION.get(exception_code) if exception_code else None
        self.state.translation_key = data.get("translation_key")
        self.state.translation_placeholders = data.get("translation_placeholders")

    def _as_stored(self) -> _StoredState:
        crash_time = self.state.crash_time
        exception_class = self.state.exception_class
        return {
            "presumed_dead": self.state.presumed_dead,
            "crash_time": crash_time.isoformat() if crash_time else None,
            "exception_code": _EXCEPTION_TO_CODE.get(exception_class) if exception_class else None,
            "translation_key": self.state.translation_key,
            "translation_placeholders": self.state.translation_placeholders,
        }

    async def async_save(self) -> None:
        """Persist the current self.state to disk."""
        await self._store.async_save(self._as_stored())

    async def async_clear(self) -> None:
        """Reset state and remove the on-disk store."""
        self.state = CrashState()
        await self._store.async_remove()

    async def async_clear_after_success(self) -> None:
        """Clear crash window state after a successful setup."""
        self.state.presumed_dead = False
        self.state.crash_time = None
        self.state.translation_key = None
        self.state.translation_placeholders = None
        await self._store.async_save(self._as_stored())


# Module-level cache so config entry uses one CrashStateStore. One entry.
_STORES: dict[str, CrashStateStore] = {}


async def async_get(hass: HomeAssistant, entry_id: str) -> CrashStateStore:
    """Return the crash-state store for the entry, loading from disk on first use."""
    store = _STORES.get(entry_id)
    if store is None:
        store = CrashStateStore(hass, entry_id)
        await store.async_load()
        _STORES[entry_id] = store
    return store
