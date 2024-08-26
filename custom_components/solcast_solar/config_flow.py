"""Config flow for Solcast Solar integration"""

# pylint: disable=C0304, E0401, W0702

from __future__ import annotations
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_API_KEY
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant import config_entries
from .const import DOMAIN, TITLE, CONFIG_OPTIONS, API_QUOTA, CUSTOM_HOUR_SENSOR, BRK_ESTIMATE, BRK_ESTIMATE10, BRK_ESTIMATE90, BRK_SITE, BRK_HALFHOURLY, BRK_HOURLY

@config_entries.HANDLERS.register(DOMAIN)
class SolcastSolarFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle the config flow."""

    VERSION = 9 #v5 started 4.0.8, #6 started 4.0.15, #7 started 4.0.16, #8 started 4.0.39, #9 started 4.1.3

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> SolcastSolarOptionFlowHandler:
        """Get the options flow for this handler."""
        return SolcastSolarOptionFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initiated by the user."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            return self.async_create_entry(
                title= TITLE,
                data = {},
                options={
                    CONF_API_KEY: user_input[CONF_API_KEY],
                    API_QUOTA: "10",
                    "damp00":1.0,
                    "damp01":1.0,
                    "damp02":1.0,
                    "damp03":1.0,
                    "damp04":1.0,
                    "damp05":1.0,
                    "damp06":1.0,
                    "damp07":1.0,
                    "damp08":1.0,
                    "damp09":1.0,
                    "damp10":1.0,
                    "damp11":1.0,
                    "damp12":1.0,
                    "damp13":1.0,
                    "damp14":1.0,
                    "damp15":1.0,
                    "damp16":1.0,
                    "damp17":1.0,
                    "damp18":1.0,
                    "damp19":1.0,
                    "damp20":1.0,
                    "damp21":1.0,
                    "damp22":1.0,
                    "damp23":1.0,
                    "customhoursensor":1,
                    BRK_ESTIMATE: True,
                    BRK_ESTIMATE10: True,
                    BRK_ESTIMATE90: True,
                    BRK_SITE: True,
                    BRK_HALFHOURLY: True,
                    BRK_HOURLY: True,
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY, default=""): str,
                    vol.Required(API_QUOTA, default="10"): str,
                }
            ),
        )


class SolcastSolarOptionFlowHandler(OptionsFlow):
    """Handle options"""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow"""
        self.config_entry = config_entry
        self.options = dict(config_entry.options)

    async def async_step_init(self, user_input=None) -> Any:
        """Initialise steps"""

        errors = {}
        if user_input is not None:
            if "solcast_config_action" in user_input:
                next_action = user_input["solcast_config_action"]
                if next_action == "configure_dampening":
                    return await self.async_step_dampen()
                elif next_action == "configure_api":
                    return await self.async_step_api()
                elif next_action == "configure_customsensor":
                    return await self.async_step_customsensor()
                elif next_action == "configure_attributes":
                    return await self.async_step_attributes()
                else:
                    errors["base"] = "incorrect_options_action"

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("solcast_config_action"): SelectSelector(
                        SelectSelectorConfig(
                            options=CONFIG_OPTIONS,
                            mode=SelectSelectorMode.LIST,
                            translation_key="solcast_config_action",
                        )
                    )
                }
            ),
            errors=errors
        )

    async def async_step_api(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage the API key/quota"""

        errors = {}
        api_quota = self.config_entry.options[API_QUOTA]

        if user_input is not None:
            try:
                api_quota = user_input[API_QUOTA]

                all_config_data = {**self.config_entry.options}
                k = user_input["api_key"].replace(" ","").strip()
                k = ','.join([s for s in k.split(',') if s])
                all_config_data["api_key"] = k
                all_config_data[API_QUOTA] = api_quota

                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    title=TITLE,
                    options=all_config_data,
                )
                return self.async_create_entry(title=TITLE, data=None)
            except:
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="api",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY, default=self.config_entry.options.get(CONF_API_KEY),): str,
                    vol.Required(API_QUOTA, default=self.config_entry.options.get(API_QUOTA),): str,
                }
            ),
            errors=errors,
        )

    async def async_step_dampen(self, user_input: dict[str, Any] | None = None) -> FlowResult: #user_input=None):
        """Manage the hourly factor options"""

        errors = {}

        damp00 = self.config_entry.options["damp00"]
        damp01 = self.config_entry.options["damp01"]
        damp02 = self.config_entry.options["damp02"]
        damp03 = self.config_entry.options["damp03"]
        damp04 = self.config_entry.options["damp04"]
        damp05 = self.config_entry.options["damp05"]
        damp06 = self.config_entry.options["damp06"]
        damp07 = self.config_entry.options["damp07"]
        damp08 = self.config_entry.options["damp08"]
        damp09 = self.config_entry.options["damp09"]
        damp10 = self.config_entry.options["damp10"]
        damp11 = self.config_entry.options["damp11"]
        damp12 = self.config_entry.options["damp12"]
        damp13 = self.config_entry.options["damp13"]
        damp14 = self.config_entry.options["damp14"]
        damp15 = self.config_entry.options["damp15"]
        damp16 = self.config_entry.options["damp16"]
        damp17 = self.config_entry.options["damp17"]
        damp18 = self.config_entry.options["damp18"]
        damp19 = self.config_entry.options["damp19"]
        damp20 = self.config_entry.options["damp20"]
        damp21 = self.config_entry.options["damp21"]
        damp22 = self.config_entry.options["damp22"]
        damp23 = self.config_entry.options["damp23"]

        if user_input is not None:
            try:
                damp00 = user_input["damp00"]
                damp01 = user_input["damp01"]
                damp02 = user_input["damp02"]
                damp03 = user_input["damp03"]
                damp04 = user_input["damp04"]
                damp05 = user_input["damp05"]
                damp06 = user_input["damp06"]
                damp07 = user_input["damp07"]
                damp08 = user_input["damp08"]
                damp09 = user_input["damp09"]
                damp10 = user_input["damp10"]
                damp11 = user_input["damp11"]
                damp12 = user_input["damp12"]
                damp13 = user_input["damp13"]
                damp14 = user_input["damp14"]
                damp15 = user_input["damp15"]
                damp16 = user_input["damp16"]
                damp17 = user_input["damp17"]
                damp18 = user_input["damp18"]
                damp19 = user_input["damp19"]
                damp20 = user_input["damp20"]
                damp21 = user_input["damp21"]
                damp22 = user_input["damp22"]
                damp23 = user_input["damp23"]

                all_config_data = {**self.config_entry.options}
                all_config_data["damp00"] = damp00
                all_config_data["damp01"] = damp01
                all_config_data["damp02"] = damp02
                all_config_data["damp03"] = damp03
                all_config_data["damp04"] = damp04
                all_config_data["damp05"] = damp05
                all_config_data["damp06"] = damp06
                all_config_data["damp07"] = damp07
                all_config_data["damp08"] = damp08
                all_config_data["damp09"] = damp09
                all_config_data["damp10"] = damp10
                all_config_data["damp11"] = damp11
                all_config_data["damp12"] = damp12
                all_config_data["damp13"] = damp13
                all_config_data["damp14"] = damp14
                all_config_data["damp15"] = damp15
                all_config_data["damp16"] = damp16
                all_config_data["damp17"] = damp17
                all_config_data["damp18"] = damp18
                all_config_data["damp19"] = damp19
                all_config_data["damp20"] = damp20
                all_config_data["damp21"] = damp21
                all_config_data["damp22"] = damp22
                all_config_data["damp23"] = damp23

                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    title=TITLE,
                    options=all_config_data,
                )

                return self.async_create_entry(title=TITLE, data=None)
            except:
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="dampen",
            data_schema=vol.Schema(
                {
                    vol.Required("damp00", description={"suggested_value": damp00}):
                            vol.All(vol.Coerce(float), vol.Range(min=0.0,max=1.0)),
                    vol.Required("damp01", description={"suggested_value": damp01}):
                            vol.All(vol.Coerce(float), vol.Range(min=0.0,max=1.0)),
                    vol.Required("damp02", description={"suggested_value": damp02}):
                            vol.All(vol.Coerce(float), vol.Range(min=0.0,max=1.0)),
                    vol.Required("damp03", description={"suggested_value": damp03}):
                            vol.All(vol.Coerce(float), vol.Range(min=0.0,max=1.0)),
                    vol.Required("damp04", description={"suggested_value": damp04}):
                            vol.All(vol.Coerce(float), vol.Range(min=0.0,max=1.0)),
                    vol.Required("damp05", description={"suggested_value": damp05}):
                            vol.All(vol.Coerce(float), vol.Range(min=0.0,max=1.0)),
                    vol.Required("damp06", description={"suggested_value": damp06}):
                            vol.All(vol.Coerce(float), vol.Range(min=0.0,max=1.0)),
                    vol.Required("damp07", description={"suggested_value": damp07}):
                            vol.All(vol.Coerce(float), vol.Range(min=0.0,max=1.0)),
                    vol.Required("damp08", description={"suggested_value": damp08}):
                            vol.All(vol.Coerce(float), vol.Range(min=0.0,max=1.0)),
                    vol.Required("damp09", description={"suggested_value": damp09}):
                            vol.All(vol.Coerce(float), vol.Range(min=0.0,max=1.0)),
                    vol.Required("damp10", description={"suggested_value": damp10}):
                            vol.All(vol.Coerce(float), vol.Range(min=0.0,max=1.0)),
                    vol.Required("damp11", description={"suggested_value": damp11}):
                            vol.All(vol.Coerce(float), vol.Range(min=0.0,max=1.0)),
                    vol.Required("damp12", description={"suggested_value": damp12}):
                            vol.All(vol.Coerce(float), vol.Range(min=0.0,max=1.0)),
                    vol.Required("damp13", description={"suggested_value": damp13}):
                            vol.All(vol.Coerce(float), vol.Range(min=0.0,max=1.0)),
                    vol.Required("damp14", description={"suggested_value": damp14}):
                            vol.All(vol.Coerce(float), vol.Range(min=0.0,max=1.0)),
                    vol.Required("damp15", description={"suggested_value": damp15}):
                            vol.All(vol.Coerce(float), vol.Range(min=0.0,max=1.0)),
                    vol.Required("damp16", description={"suggested_value": damp16}):
                            vol.All(vol.Coerce(float), vol.Range(min=0.0,max=1.0)),
                    vol.Required("damp17", description={"suggested_value": damp17}):
                            vol.All(vol.Coerce(float), vol.Range(min=0.0,max=1.0)),
                    vol.Required("damp18", description={"suggested_value": damp18}):
                            vol.All(vol.Coerce(float), vol.Range(min=0.0,max=1.0)),
                    vol.Required("damp19", description={"suggested_value": damp19}):
                            vol.All(vol.Coerce(float), vol.Range(min=0.0,max=1.0)),
                    vol.Required("damp20", description={"suggested_value": damp20}):
                            vol.All(vol.Coerce(float), vol.Range(min=0.0,max=1.0)),
                    vol.Required("damp21", description={"suggested_value": damp21}):
                            vol.All(vol.Coerce(float), vol.Range(min=0.0,max=1.0)),
                    vol.Required("damp22", description={"suggested_value": damp22}):
                            vol.All(vol.Coerce(float), vol.Range(min=0.0,max=1.0)),
                    vol.Required("damp23", description={"suggested_value": damp23}):
                            vol.All(vol.Coerce(float), vol.Range(min=0.0,max=1.0)),
                }
            ),
            errors=errors,
        )

    async def async_step_customsensor(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage the custom X hour sensor option"""

        errors = {}

        customhoursensor = self.config_entry.options[CUSTOM_HOUR_SENSOR]

        if user_input is not None:
            try:
                customhoursensor = user_input[CUSTOM_HOUR_SENSOR]

                all_config_data = {**self.config_entry.options}
                all_config_data[CUSTOM_HOUR_SENSOR] = customhoursensor

                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    title=TITLE,
                    options=all_config_data,
                )

                return self.async_create_entry(title=TITLE, data=None)
            except:
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="customsensor",
            data_schema=vol.Schema(
                {
                    vol.Required(CUSTOM_HOUR_SENSOR, description={"suggested_value": customhoursensor}):
                            vol.All(vol.Coerce(int), vol.Range(min=1,max=144)),
                }
            ),
            errors=errors,
        )

    async def async_step_attributes(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage the attributes present"""

        errors = {}

        estimate_breakdown = self.config_entry.options[BRK_ESTIMATE]
        estimate_breakdown10 = self.config_entry.options[BRK_ESTIMATE10]
        estimate_breakdown90 = self.config_entry.options[BRK_ESTIMATE90]
        site_breakdown = self.config_entry.options[BRK_SITE]
        half_hourly = self.config_entry.options[BRK_HALFHOURLY]
        hourly = self.config_entry.options[BRK_HOURLY]

        if user_input is not None:
            try:
                estimate_breakdown = user_input[BRK_ESTIMATE]
                estimate_breakdown10 = user_input[BRK_ESTIMATE10]
                estimate_breakdown90 = user_input[BRK_ESTIMATE90]
                site_breakdown = user_input[BRK_SITE]
                half_hourly = user_input[BRK_HALFHOURLY]
                hourly = user_input[BRK_HOURLY]

                all_config_data = {**self.config_entry.options}
                all_config_data[BRK_ESTIMATE] = estimate_breakdown
                all_config_data[BRK_ESTIMATE10] = estimate_breakdown10
                all_config_data[BRK_ESTIMATE90] = estimate_breakdown90
                all_config_data[BRK_SITE] = site_breakdown
                all_config_data[BRK_HALFHOURLY] = half_hourly
                all_config_data[BRK_HOURLY] = hourly

                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    title=TITLE,
                    options=all_config_data,
                )

                return self.async_create_entry(title=TITLE, data=None)
            except:
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="attributes",
            data_schema=vol.Schema(
                {
                    vol.Required(BRK_ESTIMATE10, description={"suggested_value": estimate_breakdown10}): bool,
                    vol.Required(BRK_ESTIMATE, description={"suggested_value": estimate_breakdown}): bool,
                    vol.Required(BRK_ESTIMATE90, description={"suggested_value": estimate_breakdown90}): bool,
                    vol.Required(BRK_SITE, description={"suggested_value": site_breakdown}): bool,
                    vol.Required(BRK_HALFHOURLY, description={"suggested_value": half_hourly}): bool,
                    vol.Required(BRK_HOURLY, description={"suggested_value": hourly}): bool,
                }
            ),
            errors=errors,
        )