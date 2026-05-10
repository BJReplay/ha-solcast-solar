"""Config and options flow for Solcast PV SimCity."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .sim_core import (
    API_KEY_SITES,
    canonicalise_api_keys,
    normalise_shade_density_profile,
    parse_api_keys,
)

_ENTRY_VERSION = 6
DOMAIN = "solcast_sim"
ADJACENT_SOLCAST_DOMAIN = "solcast_solar"


def _default_api_key_from_solcast(hass: HomeAssistant | None) -> str | None:
    """Return canonical API key list from an adjacent Solcast integration entry."""
    if hass is None:
        return None

    for entry in hass.config_entries.async_entries(ADJACENT_SOLCAST_DOMAIN):
        values = {**entry.data, **entry.options}
        api_key = str(values.get("api_key", "")).strip()
        if not api_key:
            continue
        return canonicalise_api_keys(api_key)
    return None


def _normalise_shade_dimensions(value: str) -> str:
    """Validate and normalise a comma-separated 'height, width, distance' string."""
    try:
        parts = [p.strip() for p in str(value).split(",")]
        if len(parts) != 3:
            raise ValueError  # noqa: TRY301
        h, w, d = float(parts[0]), float(parts[1]), float(parts[2])
    except (ValueError, TypeError) as err:
        raise ValueError("invalid_shade_dimensions") from err
    if h <= 0.0 or w <= 0.0 or d <= 0.0:
        raise ValueError("invalid_shade_dimensions")
    return f"{h}, {w}, {d}"


def _normalise_cloudiness_profile(value: str) -> str:
    """Validate and normalise comma-separated cloudiness bias, variability."""
    try:
        parts = [p.strip() for p in str(value).split(",")]
        if len(parts) != 2:
            raise ValueError  # noqa: TRY301
        bias, variability = float(parts[0]), float(parts[1])
    except (ValueError, TypeError) as err:
        raise ValueError("invalid_cloudiness_profile") from err
    return f"{bias}, {variability}"


def _normalise_battery_power_limits(value: str) -> str:
    """Validate and normalise comma-separated max charge, max discharge."""
    try:
        parts = [p.strip() for p in str(value).split(",")]
        if len(parts) != 2:
            raise ValueError  # noqa: TRY301
        charge, discharge = float(parts[0]), float(parts[1])
    except (ValueError, TypeError) as err:
        raise ValueError("invalid_battery_power_limits") from err
    if charge < 0.0 or discharge < 0.0:
        raise ValueError("invalid_battery_power_limits")
    return f"{charge}, {discharge}"


def _normalise_api_key(value: str) -> str:
    """Validate and normalise API key(s) as comma-separated values."""
    canonical = canonicalise_api_keys(value)
    api_keys = parse_api_keys(canonical)
    if not api_keys:
        raise ValueError("invalid_api_key")
    if any(api_key not in API_KEY_SITES for api_key in api_keys):
        raise ValueError("invalid_api_key")
    return canonical


_DEFAULTS: Mapping[str, Any] = MappingProxyType(
    {
        "api_key": "1",
        "season": "auto",
        "cloudiness_profile": "0.0, 0.7",
        "estimated_actuals_uncertainty_pct": 2.2,
        "shade_dimensions": "12.0, 8.0, 15.0",
        "shade_azimuth_deg": 0.0,
        "shade_opacity": 0.0,
        "shade_density_profile": "0.3, 0.8, 1.0",
        "export_factor": 1.0,
        "export_limit_kw": 5.0,
        "battery_capacity_kwh": 13.5,
        "battery_power_limits_kw": "5.0, 5.0",
        "house_load_kw": 1.0,
        "free_charge_start": "11:00:00",
        "free_charge_end": "14:00:00",
    }
)

_CONFIG_FIELD_DEFAULTS: Mapping[str, Any] = _DEFAULTS
_OPTIONS_FIELD_DEFAULTS: Mapping[str, Any] = _DEFAULTS

_FIELD_VALIDATORS: dict[str, Any] = {
    "api_key": str,
    "season": selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=["auto", "spring", "summer", "autumn", "winter"],
            mode=selector.SelectSelectorMode.DROPDOWN,
            translation_key="season",
        )
    ),
    "cloudiness_profile": str,
    "estimated_actuals_uncertainty_pct": vol.All(vol.Coerce(float), vol.Range(min=0.0, max=10.0)),
    "shade_dimensions": str,
    "shade_azimuth_deg": vol.All(vol.Coerce(float), vol.Range(min=-180.0, max=180.0)),
    "shade_opacity": vol.Coerce(float),
    "shade_density_profile": str,
    "export_factor": vol.Coerce(float),
    "export_limit_kw": vol.Coerce(float),
    "battery_capacity_kwh": vol.Coerce(float),
    "battery_power_limits_kw": str,
    "house_load_kw": vol.Coerce(float),
    "free_charge_start": selector.TimeSelector(),
    "free_charge_end": selector.TimeSelector(),
}


def _build_schema(field_defaults: Mapping[str, Any], current: dict[str, Any] | None = None) -> vol.Schema:
    """Build config/options schema from shared field definitions."""
    values = current or {}
    return vol.Schema(
        {vol.Required(key, default=values.get(key, default)): _FIELD_VALIDATORS[key] for key, default in field_defaults.items()}
    )


class SolcastSimConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Solcast PV SimCity."""

    VERSION = _ENTRY_VERSION

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                user_input["api_key"] = _normalise_api_key(user_input["api_key"])
            except ValueError:
                errors["api_key"] = "invalid_api_key"

            try:
                user_input["cloudiness_profile"] = _normalise_cloudiness_profile(user_input["cloudiness_profile"])
            except ValueError:
                errors["cloudiness_profile"] = "invalid_cloudiness_profile"

            try:
                user_input["shade_dimensions"] = _normalise_shade_dimensions(user_input["shade_dimensions"])
            except ValueError:
                errors["shade_dimensions"] = "invalid_shade_dimensions"

            try:
                user_input["shade_density_profile"] = normalise_shade_density_profile(user_input["shade_density_profile"])
            except ValueError:
                errors["shade_density_profile"] = "invalid_shade_density_profile"

            try:
                user_input["battery_power_limits_kw"] = _normalise_battery_power_limits(user_input["battery_power_limits_kw"])
            except ValueError:
                errors["battery_power_limits_kw"] = "invalid_battery_power_limits"

        if user_input is not None and not errors:
            await self.async_set_unique_id(user_input["api_key"])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"Solcast PV SimCity ({user_input['api_key']})",
                data=user_input,
            )

        defaults = dict(_CONFIG_FIELD_DEFAULTS)
        if solcast_api_key := _default_api_key_from_solcast(self.hass):
            defaults["api_key"] = solcast_api_key

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(defaults),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return SolcastSimOptionsFlow(config_entry)


class SolcastSimOptionsFlow(OptionsFlow):
    """Options flow for Solcast PV SimCity."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialise options flow."""
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle options."""
        current = {**self._config_entry.data, **self._config_entry.options}
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                user_input["api_key"] = _normalise_api_key(user_input["api_key"])
            except ValueError:
                errors["api_key"] = "invalid_api_key"

            try:
                user_input["cloudiness_profile"] = _normalise_cloudiness_profile(user_input["cloudiness_profile"])
            except ValueError:
                errors["cloudiness_profile"] = "invalid_cloudiness_profile"

            try:
                user_input["shade_dimensions"] = _normalise_shade_dimensions(user_input["shade_dimensions"])
            except ValueError:
                errors["shade_dimensions"] = "invalid_shade_dimensions"

            try:
                user_input["shade_density_profile"] = normalise_shade_density_profile(user_input["shade_density_profile"])
            except ValueError:
                errors["shade_density_profile"] = "invalid_shade_density_profile"

            try:
                user_input["battery_power_limits_kw"] = _normalise_battery_power_limits(user_input["battery_power_limits_kw"])
            except ValueError:
                errors["battery_power_limits_kw"] = "invalid_battery_power_limits"

        if user_input is not None and not errors:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(_OPTIONS_FIELD_DEFAULTS, current),
            errors=errors,
        )
