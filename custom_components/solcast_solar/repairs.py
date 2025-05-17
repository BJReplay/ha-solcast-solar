"""Repairs for the Solcast Solar integration."""

import logging
from typing import Any

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,  # pyright: ignore[reportUnknownVariableType]
    SelectSelectorConfig,
    SelectSelectorMode,
)

from . import current_entry
from .const import AUTO_UPDATE, DOMAIN

_LOGGER = logging.getLogger(__name__)

AUTO_UPDATE_OPTIONS: list[SelectOptionDict] = [
    SelectOptionDict(label="sunrise_sunset", value="1"),
    SelectOptionDict(label="all_day", value="2"),
]


class SolcastRepair(RepairsFlow):
    """Handler for an issue fixing flow."""

    entry: ConfigEntry | None

    def __init__(self, *, entry: ConfigEntry | None) -> None:
        """Create flow."""

        self.entry = entry
        super().__init__()

    @callback
    def _async_get_placeholders(self) -> dict[str, str]:
        issue_registry = ir.async_get(self.hass)
        placeholders: dict[str, Any] = {}
        if issue := issue_registry.issues.get((DOMAIN, self.issue_id)):
            if issue.learn_more_url:
                placeholders["learn_more"] = issue.learn_more_url

        return placeholders


class RecordsMissingRepairFlow(SolcastRepair):
    """Handler to enable auto-update."""

    async def async_step_init(self, user_input: dict[str, str] | None = None) -> data_entry_flow.FlowResult:
        """Handle the init."""

        return await self.async_step_offer_auto()

    async def async_step_offer_auto(self, user_input: dict[str, str] | None = None) -> data_entry_flow.FlowResult:
        """Handle the offer to enable auto-update."""

        if user_input is not None and self.entry is not None:
            opts = {AUTO_UPDATE: int(user_input[AUTO_UPDATE])}
            new_options: dict[str, Any] = {**self.entry.options, **opts}
            self.hass.config_entries.async_update_entry(self.entry, options=new_options)
            return self.async_abort(reason="reconfigured")

        placeholders = self._async_get_placeholders()
        return self.async_show_form(
            step_id="offer_auto",
            data_schema=vol.Schema(
                {
                    vol.Required(AUTO_UPDATE, default="1"): SelectSelector(
                        SelectSelectorConfig(options=AUTO_UPDATE_OPTIONS, mode=SelectSelectorMode.DROPDOWN, translation_key="auto_update")
                    ),
                }
            ),
            description_placeholders=placeholders,
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, Any],
) -> RepairsFlow:
    """Create flow."""

    if issue_id == "records_missing_fixable":
        return RecordsMissingRepairFlow(entry=current_entry.get())

    return ConfirmRepairFlow()
