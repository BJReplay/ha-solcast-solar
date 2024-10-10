"""Config flow for Solcast Solar integration."""

# pylint: disable=C0304, E0401, W0702, W0703

from __future__ import annotations
from typing import Any

import os
from os.path import exists as file_exists
import voluptuous as vol # type: ignore
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow # type: ignore
from homeassistant.const import CONF_API_KEY # type: ignore
from homeassistant.core import callback # type: ignore
from homeassistant.data_entry_flow import FlowResult # type: ignore
from homeassistant import config_entries # type: ignore
from homeassistant.helpers.selector import ( # type: ignore
    SelectSelector,
    SelectOptionDict,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from .const import (
    API_QUOTA,
    AUTO_UPDATE,
    BRK_ESTIMATE,
    BRK_ESTIMATE10,
    BRK_ESTIMATE90,
    BRK_HALFHOURLY,
    BRK_HOURLY,
    BRK_SITE,
    BRK_SITE_DETAILED,
    CONFIG_DAMP,
    CUSTOM_HOUR_SENSOR,
    DOMAIN,
    HARD_LIMIT,
    KEY_ESTIMATE,
    SITE_DAMP,
    TITLE,
)


@config_entries.HANDLERS.register(DOMAIN)
class SolcastSolarFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle the config flow."""

    # 5 started 4.0.8
    # 6 started 4.0.15
    # 7 started 4.0.16
    # 8 started 4.0.39
    # 9 started 4.1.3
    # 10 unreleased
    # 11 unreleased
    # 12 started 4.1.8

    VERSION = 12

    @staticmethod
    @callback
    def async_get_options_flow(
        entry: ConfigEntry,
    ) -> SolcastSolarOptionFlowHandler:
        """Get the options flow for this handler.

        Arguments:
            entry (ConfigEntry): The integration entry instance, contains the configuration.

        Returns:
            SolcastSolarOptionFlowHandler: The congig flow handler instance.
        """
        return SolcastSolarOptionFlowHandler(entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initiated by the user.

        Arguments:
            user_input (dict[str, Any] | None, optional): The config submitted by a user. Defaults to None.

        Returns:
            FlowResult: The form to show.
        """
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            return self.async_create_entry(
                title= TITLE,
                data = {},
                options={
                    CONF_API_KEY: user_input[CONF_API_KEY],
                    API_QUOTA: user_input[API_QUOTA],
                    AUTO_UPDATE: int(user_input[AUTO_UPDATE]),
                    # Remaining options set to default
                    "damp00": 1.0,
                    "damp01": 1.0,
                    "damp02": 1.0,
                    "damp03": 1.0,
                    "damp04": 1.0,
                    "damp05": 1.0,
                    "damp06": 1.0,
                    "damp07": 1.0,
                    "damp08": 1.0,
                    "damp09": 1.0,
                    "damp10": 1.0,
                    "damp11": 1.0,
                    "damp12": 1.0,
                    "damp13": 1.0,
                    "damp14": 1.0,
                    "damp15": 1.0,
                    "damp16": 1.0,
                    "damp17": 1.0,
                    "damp18": 1.0,
                    "damp19": 1.0,
                    "damp20": 1.0,
                    "damp21": 1.0,
                    "damp22": 1.0,
                    "damp23": 1.0,
                    "customhoursensor": 1,
                    HARD_LIMIT: 100000,
                    KEY_ESTIMATE: "estimate",
                    BRK_ESTIMATE: True,
                    BRK_ESTIMATE10: True,
                    BRK_ESTIMATE90: True,
                    BRK_SITE: True,
                    BRK_HALFHOURLY: True,
                    BRK_HOURLY: True,
                    BRK_SITE_DETAILED: False,
                },
            )

        solcast_json_exists = file_exists(f"{os.path.abspath(os.path.join(os.path.dirname(__file__) ,'../..'))}/solcast.json")

        update: list[SelectOptionDict] = [
            SelectOptionDict(label="none", value="0"),
            SelectOptionDict(label="sunrise_sunset", value="1"),
            SelectOptionDict(label="all_day", value="2"),
        ]

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY, default=""): str,
                    vol.Required(API_QUOTA, default="10"): str,
                    vol.Required(AUTO_UPDATE, default=str(int(not solcast_json_exists))): SelectSelector(
                        SelectSelectorConfig(options=update, mode=SelectSelectorMode.DROPDOWN, translation_key="auto_update")
                    ),
                }
            ),
        )


class SolcastSolarOptionFlowHandler(OptionsFlow):
    """Handle options."""

    def __init__(self, entry: ConfigEntry):
        """Initialize options flow.

        Arguments:
            entry (ConfigEntry): The integration entry instance, contains the configuration.
        """
        self.config_entry = entry
        self.options = dict(self.config_entry.options)

    async def async_step_init(self, user_input: dict=None) -> Any:
        """Initialise main dialogue step.

        Arguments:
            user_input (dict, optional): The input provided by the user. Defaults to None.

        Returns:
            Any: Either an error, or the configuration dialogue results.
        """

        errors = {}
        api_key = self.config_entry.options.get(CONF_API_KEY)
        api_quota = self.config_entry.options[API_QUOTA]
        auto_update = self.config_entry.options[AUTO_UPDATE]
        customhoursensor = self.config_entry.options[CUSTOM_HOUR_SENSOR]
        hard_limit = self.config_entry.options.get(HARD_LIMIT, 100000) # Has a get with default because may not feature in an existing user entry config.
        key_estimate = self.config_entry.options.get(KEY_ESTIMATE, "estimate")
        estimate_breakdown = self.config_entry.options[BRK_ESTIMATE]
        estimate_breakdown10 = self.config_entry.options[BRK_ESTIMATE10]
        estimate_breakdown90 = self.config_entry.options[BRK_ESTIMATE90]
        site_breakdown = self.config_entry.options[BRK_SITE]
        half_hourly = self.config_entry.options[BRK_HALFHOURLY]
        hourly = self.config_entry.options[BRK_HOURLY]
        site_detailed = self.config_entry.options[BRK_SITE_DETAILED]
        granular_dampening = self.config_entry.options[SITE_DAMP]

        if user_input is not None:
            try:
                all_config_data = {**self.config_entry.options}

                api_key = user_input["api_key"].replace(" ","")
                api_key = [s for s in api_key.split(',') if s]
                api_count = len(api_key)
                api_key = ','.join(api_key)
                all_config_data["api_key"] = api_key

                api_quota = user_input[API_QUOTA].replace(" ","")
                api_quota = [s for s in api_quota.split(',') if s]
                for q in api_quota:
                    if not q.isnumeric():
                        return self.async_abort(reason="API limit not numeric!")
                    if int(q) < 1:
                        return self.async_abort(reason="API limit must be one  or greater!")
                if len(api_quota) > api_count:
                    return self.async_abort(reason="There are more API limit counts entered than keys!")
                api_quota = ','.join(api_quota)
                all_config_data[API_QUOTA] = api_quota

                all_config_data[AUTO_UPDATE] = int(user_input[AUTO_UPDATE])

                customhoursensor = user_input[CUSTOM_HOUR_SENSOR]
                if customhoursensor < 1 or customhoursensor > 144:
                    return self.async_abort(reason="Custom sensor not between 1 and 144")
                all_config_data[CUSTOM_HOUR_SENSOR] = customhoursensor

                hard_limit = user_input[HARD_LIMIT]
                if hard_limit < 1:
                    return self.async_abort(reason="Hard limit must be a positive number")
                all_config_data[HARD_LIMIT] = hard_limit

                all_config_data[KEY_ESTIMATE] = user_input[KEY_ESTIMATE]

                all_config_data[BRK_ESTIMATE] = user_input[BRK_ESTIMATE]
                all_config_data[BRK_ESTIMATE10] = user_input[BRK_ESTIMATE10]
                all_config_data[BRK_ESTIMATE90] = user_input[BRK_ESTIMATE90]
                all_config_data[BRK_HALFHOURLY] = user_input[BRK_HALFHOURLY]
                all_config_data[BRK_HOURLY] = user_input[BRK_HOURLY]
                site_breakdown = user_input[BRK_SITE]
                all_config_data[BRK_SITE] = site_breakdown
                site_detailed = user_input[BRK_SITE_DETAILED]
                all_config_data[BRK_SITE_DETAILED] = site_detailed

                if user_input.get(SITE_DAMP) is not None:
                    all_config_data[SITE_DAMP] = user_input[SITE_DAMP]

                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    title=TITLE,
                    options=all_config_data,
                )

                if user_input.get(CONFIG_DAMP):
                    return await self.async_step_dampen()

                return self.async_create_entry(title=TITLE, data=None)
            except Exception as e:
                errors["base"] = str(e)

        update: list[SelectOptionDict] = [
            SelectOptionDict(label="none", value="0"),
            SelectOptionDict(label="sunrise_sunset", value="1"),
            SelectOptionDict(label="all_day", value="2"),
        ]

        forecasts: list[SelectOptionDict] = [
            SelectOptionDict(label="estimate", value="estimate"),
            SelectOptionDict(label="estimate10", value="estimate10"),
            SelectOptionDict(label="estimate90", value="estimate90"),
        ]

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY, default=api_key): str,
                    vol.Required(API_QUOTA, default=api_quota): str,
                    vol.Required(AUTO_UPDATE, default=str(int(auto_update))): SelectSelector(
                        SelectSelectorConfig(options=update, mode=SelectSelectorMode.DROPDOWN, translation_key="auto_update")
                    ),
                    vol.Required(KEY_ESTIMATE, default=key_estimate): SelectSelector(
                        SelectSelectorConfig(options=forecasts, mode=SelectSelectorMode.DROPDOWN, translation_key="key_estimate")
                    ),
                    vol.Required(CUSTOM_HOUR_SENSOR, default=customhoursensor): int,
                    vol.Required(HARD_LIMIT, default=hard_limit): int,
                    vol.Optional(BRK_ESTIMATE10, default=estimate_breakdown10): bool,
                    vol.Optional(BRK_ESTIMATE, default=estimate_breakdown): bool,
                    vol.Optional(BRK_ESTIMATE90, default=estimate_breakdown90): bool,
                    vol.Optional(BRK_SITE, default=site_breakdown): bool,
                    vol.Optional(BRK_HALFHOURLY, default=half_hourly): bool,
                    vol.Optional(BRK_HOURLY, default=hourly): bool,
                    vol.Optional(BRK_SITE_DETAILED, default=site_detailed): bool,
                    (vol.Optional(CONFIG_DAMP, default=False) if not granular_dampening else vol.Optional(SITE_DAMP, default=granular_dampening)): bool,
                }
            ),
            errors=errors
        )

    async def async_step_dampen(self, user_input: dict[str, Any] | None = None) -> FlowResult: #user_input=None):
        """Manage the hourly dampening factors sub-option.

        Note that the config option "site_damp" is not exposed in any way to the user. This is a
        hidden option in this options flow used to trigger reset of per-site dampening should the
        overall dampening be set.

        Arguments:
            user_input (dict[str, Any] | None): The input provided by the user. Defaults to None.

        Returns:
            FlowResult: The configuration dialogue results.
        """

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
                all_config_data[SITE_DAMP] = False

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