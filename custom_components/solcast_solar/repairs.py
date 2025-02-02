"""Repairs for the Solcast Solar integration."""

import logging
from typing import Any

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import AUTO_UPDATE, DOMAIN
from .util import SolcastConfigEntry

_LOGGER = logging.getLogger(__name__)

AUTO_UPDATE_OPTIONS: list[SelectOptionDict] = [
    SelectOptionDict(label="sunrise_sunset", value="1"),
    SelectOptionDict(label="all_day", value="2"),
]


class SolcastRepair(RepairsFlow):
    """Handler for an issue fixing flow."""

    entry: SolcastConfigEntry

    def __init__(self, *, entry: SolcastConfigEntry) -> None:
        """Create flow."""

        self.entry = entry
        super().__init__()

    @callback
    def _async_get_placeholders(self) -> dict[str, str]:
        issue_registry = ir.async_get(self.hass)
        placeholders: dict = {}
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

        if user_input is not None:
            opts = {AUTO_UPDATE: int(user_input[AUTO_UPDATE])}
            new_options = {**self.entry.options, **opts}
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

    match issue_id:
        case "records_missing_fixable":
            return RecordsMissingRepairFlow(entry=data["entry"])

    return ConfirmRepairFlow()
