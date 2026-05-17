"""Cross-reload per-entry ephemeral state.

Stores small flags that must survive an integration reload.
"""

from dataclasses import dataclass


@dataclass
class EntryEphemeralState:
    """Per-entry flags that survive integration reload but not HA restart."""

    old_api_key: str | None = None
    old_hard_limit: str | None = None
    reset_old_key: bool = False


_STATES: dict[str, EntryEphemeralState] = {}


def get(entry_id: str) -> EntryEphemeralState:
    """Return the ephemeral state for a config entry, creating it if absent."""
    state = _STATES.get(entry_id)
    if state is None:
        state = EntryEphemeralState()
        _STATES[entry_id] = state
    return state
