"""Config and options flow for Solcast PV SimCity."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

DOMAIN = "solcast_sim"

_FIELD_DEFAULTS: dict[str, Any] = {
    "api_key": "1",
    "timezone": "Australia/Melbourne",
    "export_factor": 1.0,
    "export_limit_kw": 5.0,
    "battery_capacity_kwh": 13.5,
    "battery_initial_soc": 50.0,
    "battery_max_charge_kw": 5.0,
    "battery_max_discharge_kw": 5.0,
    "house_load_kw": 1.0,
    "free_charge_kw": 5.0,
    "free_charge_start": "11:00:00",
    "free_charge_end": "14:00:00",
}

_FIELD_VALIDATORS: dict[str, Any] = {
    "api_key": str,
    "timezone": str,
    "export_factor": vol.Coerce(float),
    "export_limit_kw": vol.Coerce(float),
    "battery_capacity_kwh": vol.Coerce(float),
    "battery_initial_soc": vol.Coerce(float),
    "battery_max_charge_kw": vol.Coerce(float),
    "battery_max_discharge_kw": vol.Coerce(float),
    "house_load_kw": vol.Coerce(float),
    "free_charge_kw": vol.Coerce(float),
    "free_charge_start": selector.TimeSelector(),
    "free_charge_end": selector.TimeSelector(),
}


def _build_schema(current: dict[str, Any] | None = None) -> vol.Schema:
    """Build config/options schema from shared field definitions."""
    values = current or {}
    return vol.Schema(
        {
            vol.Required(key, default=values.get(key, default)): _FIELD_VALIDATORS[key]
            for key, default in _FIELD_DEFAULTS.items()
        }
    )


class SolcastSimConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Solcast PV SimCity."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        if user_input is not None:
            await self.async_set_unique_id(user_input["api_key"])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"Solcast PV SimCity ({user_input['api_key']})",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return SolcastSimOptionsFlow(config_entry)


class SolcastSimOptionsFlow(OptionsFlow):
    """Options flow for Solcast PV SimCity."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle options."""
        current = {**self._config_entry.data, **self._config_entry.options}

        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(current),
        )
