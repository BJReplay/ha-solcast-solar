"""Repairs for the Solcast PV SimCity integration."""

from __future__ import annotations

from typing import Any, cast

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir, selector

from .sim_core import canonicalise_api_keys

ADJACENT_SOLCAST_DOMAIN = "solcast_solar"
API_KEY_OPTION = "api_key"
API_KEY_MISMATCH_SUPPRESS_OPTION = "api_key_mismatch_suppress_pair"
ENTRY_ID = "entry_id"
REPAIR_ACTION = "repair_action"
REPAIR_ACTION_SYNC = "sync"
REPAIR_ACTION_KEEP = "keep"


def _get_api_key_from_entry(entry: ConfigEntry) -> str:
    """Return canonical API key string from config entry values."""
    values = {**entry.data, **entry.options}
    return canonicalise_api_keys(str(values.get(API_KEY_OPTION, "")).strip())


def _get_adjacent_solcast_api_key(hass: HomeAssistant) -> str | None:
    """Return canonical API key string from adjacent Solcast integration, if available."""
    for entry in hass.config_entries.async_entries(ADJACENT_SOLCAST_DOMAIN):
        api_key = _get_api_key_from_entry(entry)
        if api_key:
            return api_key
    return None


class ApiKeyMismatchRepairFlow(RepairsFlow):
    """Repair flow to synchronise SimCity API keys with Solcast API keys."""

    def __init__(self, entry_id: str) -> None:
        """Initialise flow with target SimCity entry id."""
        self._entry_id = entry_id
        super().__init__()

    async def async_step_init(self, user_input: dict[str, str] | None = None) -> data_entry_flow.FlowResult:
        """Handle mismatch explanation and chosen repair action."""
        if (entry := self.hass.config_entries.async_get_entry(self._entry_id)) is None:
            return self.async_abort(reason="entry_not_found")

        if (solcast_api_keys := _get_adjacent_solcast_api_key(self.hass)) is None:
            return self.async_abort(reason="missing_solcast")

        mismatch_pair = f"{_get_api_key_from_entry(entry)}|{solcast_api_keys}"

        if user_input is not None and REPAIR_ACTION in user_input:
            action = user_input[REPAIR_ACTION]
            if action not in (REPAIR_ACTION_SYNC, REPAIR_ACTION_KEEP):
                return self.async_show_form(
                    step_id="init",
                    data_schema=vol.Schema(
                        {
                            vol.Required(REPAIR_ACTION, default=REPAIR_ACTION_SYNC): selector.SelectSelector(
                                selector.SelectSelectorConfig(
                                    options=[REPAIR_ACTION_SYNC, REPAIR_ACTION_KEEP],
                                    mode=selector.SelectSelectorMode.DROPDOWN,
                                    translation_key=REPAIR_ACTION,
                                )
                            )
                        }
                    ),
                )

            new_options: dict[str, Any] = {**entry.options}
            if action == REPAIR_ACTION_SYNC:
                new_options[API_KEY_OPTION] = solcast_api_keys
                new_options.pop(API_KEY_MISMATCH_SUPPRESS_OPTION, None)
            else:
                new_options[API_KEY_MISMATCH_SUPPRESS_OPTION] = mismatch_pair

            self.hass.config_entries.async_update_entry(entry, options=new_options)
            await self.hass.config_entries.async_reload(entry.entry_id)
            return self.async_create_entry(data={})

        description_placeholders = None
        issue_registry = ir.async_get(self.hass)
        if issue := issue_registry.async_get_issue(self.handler, self.issue_id):
            description_placeholders = issue.translation_placeholders

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(REPAIR_ACTION, default=REPAIR_ACTION_SYNC): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[REPAIR_ACTION_SYNC, REPAIR_ACTION_KEEP],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            translation_key=REPAIR_ACTION,
                        )
                    )
                }
            ),
            description_placeholders=description_placeholders,
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, Any] | None,
) -> RepairsFlow:
    """Create fix flow for SimCity repairs issues."""
    del hass

    entry_id = cast(str, (data or {}).get(ENTRY_ID, ""))
    return ApiKeyMismatchRepairFlow(entry_id)
