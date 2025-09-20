"""Config flow for Solcast Solar integration."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timezone
import logging
from pathlib import Path
import re
import traceback
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,  # pyright: ignore[reportUnknownVariableType]
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.util import dt as dt_util

from . import get_session_headers, get_version
from .const import (
    API_QUOTA,
    AUTO_DAMPEN,
    AUTO_UPDATE,
    BRK_ESTIMATE,
    BRK_ESTIMATE10,
    BRK_ESTIMATE90,
    BRK_HALFHOURLY,
    BRK_HOURLY,
    BRK_SITE,
    BRK_SITE_DETAILED,
    CONFIG_DAMP,
    CONFIG_VERSION,
    CUSTOM_HOUR_SENSOR,
    DOMAIN,
    EXCLUDE_SITES,
    GENERATION_ENTITIES,
    GET_ACTUALS,
    HARD_LIMIT_API,
    KEY_ESTIMATE,
    SITE_DAMP,
    SITE_EXPORT_ENTITY,
    SITE_EXPORT_LIMIT,
    SOLCAST_URL,
    TITLE,
    USE_ACTUALS,
)
from .solcastapi import ConnectionOptions, SolcastApi
from .util import HistoryType, SitesStatus

_LOGGER = logging.getLogger(__name__)

AUTO_UPDATE_OPTIONS: list[SelectOptionDict] = [
    SelectOptionDict(label="none", value="0"),
    SelectOptionDict(label="sunrise_sunset", value="1"),
    SelectOptionDict(label="all_day", value="2"),
]
LIKE_SITE_ID = r"^[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}$"


def validate_api_key(user_input: dict[str, Any]) -> tuple[str, int, str | None]:
    """Validate the API key.

    Arguments:
        user_input (dict[str, Any]): The user input.

    Returns:
        tuple[str, int, str | None]: The API key, API count, and abort result.

    """
    api_key = user_input[CONF_API_KEY].replace(" ", "")
    api_key = [s for s in api_key.split(",") if s]
    for index, key in enumerate(api_key):
        if re.match(LIKE_SITE_ID, key):
            return "", 0, "api_looks_like_site"
        for i, k in enumerate(api_key):
            if index != i and key == k:
                return "", 0, "api_duplicate"
    api_count = len(api_key)
    api_key = ",".join(api_key)
    return api_key, api_count, None


def validate_api_limit(user_input: dict[str, Any], api_count: int) -> tuple[str, str | None]:
    """Validate the API limit.

    Arguments:
        user_input (dict[str, Any]): The user input.
        api_count (int): The number of API keys.

    Returns:
        tuple[str, str | None]: The API limit, and abort result.

    """
    api_quota = user_input[API_QUOTA].replace(" ", "")
    api_quota = [s for s in api_quota.split(",") if s]
    for q in api_quota:
        if not q.isnumeric():
            return "", "limit_not_number"
        if int(q) < 1:
            return "", "limit_one_or_greater"
    if len(api_quota) > api_count:
        return "", "limit_too_many"
    api_quota = ",".join(api_quota)
    return api_quota, None


async def __get_time_zone(hass: HomeAssistant) -> ZoneInfo | timezone:
    tz = await dt_util.async_get_time_zone(hass.config.time_zone)
    return tz if tz is not None else dt_util.UTC


async def validate_sites(hass: HomeAssistant, user_input: dict[str, Any]) -> tuple[int, str]:
    """Validate the keys and sites with an API call.

    Arguments:
        hass: The Home Assistant instance.
        user_input (dict[str, Any]): The user input.

    Returns:
        tuple[int, str]: The test HTTP status and non-blank message for failures.

    """
    session = async_get_clientsession(hass)
    options = ConnectionOptions(
        user_input[CONF_API_KEY],
        user_input[API_QUOTA],
        SOLCAST_URL,
        hass.config.path(f"{hass.config.config_dir}/solcast.json"),
        await __get_time_zone(hass),
        user_input[AUTO_UPDATE],
        {str(a): 1.0 for a in range(24)},
        user_input[CUSTOM_HOUR_SENSOR],
        user_input[KEY_ESTIMATE],
        user_input[HARD_LIMIT_API],
        user_input[BRK_ESTIMATE],
        user_input[BRK_ESTIMATE10],
        user_input[BRK_ESTIMATE90],
        user_input[BRK_SITE],
        user_input[BRK_HALFHOURLY],
        user_input[BRK_HOURLY],
        user_input[BRK_SITE_DETAILED],
        user_input[EXCLUDE_SITES],
        user_input[GET_ACTUALS],
        user_input[USE_ACTUALS],
        user_input[GENERATION_ENTITIES],
        user_input[SITE_EXPORT_ENTITY],
        user_input[SITE_EXPORT_LIMIT],
        user_input[AUTO_DAMPEN],
    )
    solcast = SolcastApi(session, options, hass)
    solcast.headers = get_session_headers(await get_version(hass))

    status, message, api_key_in_error = await solcast.get_sites_and_usage(prior_crash=False, use_cache=False)
    if status != 200:
        if status in (401, 403):
            return status, f"Bad API key, {message} returned for {api_key_in_error}"
        return status, f"Error {message} for API key {api_key_in_error}"
    if solcast.sites_status == SitesStatus.NO_SITES:
        return 404, f"No sites for the API key {api_key_in_error} are configured at solcast.com"
    return 200, ""


@config_entries.HANDLERS.register(DOMAIN)
class SolcastSolarFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle the config flow."""

    VERSION = CONFIG_VERSION

    entry: ConfigEntry | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SolcastSolarOptionFlowHandler:
        """Get the options flow for this handler.

        Arguments:
            config_entry (ConfigEntry): The integration entry instance, contains the configuration.

        Returns:
            SolcastSolarOptionFlowHandler: The config flow handler instance.

        """
        return SolcastSolarOptionFlowHandler(config_entry)

    async def async_step_reauth(self, entry: Mapping[str, Any]) -> ConfigFlowResult:
        """Set a new API key."""
        self.entry = self.hass.config_entries.async_get_entry(self.context.get("entry_id", ""))
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle a re-key flow."""
        errors: dict[str, str] = {}

        all_config_data = {**self.entry.options} if self.entry is not None else {}

        if user_input is not None:
            api_key, _, abort = validate_api_key(user_input)
            if abort is not None:
                errors["base"] = abort
            if not errors:
                all_config_data[CONF_API_KEY] = api_key

                status, message = await validate_sites(self.hass, all_config_data)
                if status != 200:
                    errors["base"] = message
            if not errors:
                self.hass.data[DOMAIN]["reset_old_key"] = True
                result = self.async_abort(reason="Internal error")
                if self.entry is not None:
                    data = {**self.entry.data, **all_config_data}
                    self.hass.config_entries.async_update_entry(self.entry, title=TITLE, options=data)
                    if self.hass.data[DOMAIN].get("presumed_dead", True):
                        _LOGGER.debug("Loading presumed dead integration")
                        self.hass.data[DOMAIN].pop("presumed_dead")
                        self.hass.config_entries.async_schedule_reload(self.entry.entry_id)
                    result = self.async_abort(reason="reauth_successful")
                return result

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY, default=all_config_data[CONF_API_KEY]): str,
                }
            ),
            description_placeholders={"device_name": self.entry.title if self.entry is not None else "unknown"},
            errors=errors,
        )

    async def async_step_reconfigure(self, entry: Mapping[str, Any]) -> ConfigFlowResult:
        """Reconfigure API key, limit and auto-update."""
        self.entry = self.hass.config_entries.async_get_entry(self.context.get("entry_id", ""))
        return await self.async_step_reconfigure_confirm()

    async def async_step_reconfigure_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle a reconfiguration flow."""
        errors: dict[str, str] = {}

        all_config_data = {**self.entry.options} if self.entry is not None else {}

        if user_input is not None:
            api_key, api_count, abort = validate_api_key(user_input)
            api_quota = "10"
            if abort is not None:
                errors["base"] = abort
            if not errors:
                api_quota, abort = validate_api_limit(user_input, api_count)
                if abort is not None:
                    errors["base"] = abort
            if not errors:
                all_config_data[CONF_API_KEY] = api_key
                all_config_data[API_QUOTA] = api_quota
                all_config_data[AUTO_UPDATE] = int(user_input[AUTO_UPDATE])

                status, message = await validate_sites(self.hass, all_config_data)
                if status != 200:
                    errors["base"] = message
            if not errors:
                self.hass.data[DOMAIN]["reset_old_key"] = True
                result = self.async_abort(reason="Internal error")
                if self.entry is not None:
                    data = {**self.entry.data, **all_config_data}
                    self.hass.config_entries.async_update_entry(self.entry, title=TITLE, options=data)
                    if self.hass.data[DOMAIN].get("presumed_dead", True):
                        _LOGGER.debug("Loading presumed dead integration")
                        self.hass.data[DOMAIN].pop("presumed_dead")
                        self.hass.config_entries.async_schedule_reload(self.entry.entry_id)
                    result = self.async_abort(reason="reconfigured")
                return result

        return self.async_show_form(
            step_id="reconfigure_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY, default=all_config_data[CONF_API_KEY]): str,
                    vol.Required(API_QUOTA, default=all_config_data[API_QUOTA]): str,
                    vol.Required(AUTO_UPDATE, default=str(all_config_data[AUTO_UPDATE])): SelectSelector(
                        SelectSelectorConfig(options=AUTO_UPDATE_OPTIONS, mode=SelectSelectorMode.DROPDOWN, translation_key="auto_update")
                    ),
                }
            ),
            description_placeholders={"device_name": self.entry.title if self.entry is not None else "unknown"},
            errors=errors,
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle a flow initiated by the user.

        Arguments:
            user_input (dict[str, Any] | None, optional): The config submitted by a user. Defaults to None.

        Returns:
            FlowResult: The form to show.

        """
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors: dict[str, str] = {}

        if user_input is not None:
            api_key, api_count, abort = validate_api_key(user_input)
            api_quota = "10"
            if abort is not None:
                errors["base"] = abort
            if not errors:
                api_quota, abort = validate_api_limit(user_input, api_count)
                if abort is not None:
                    errors["base"] = abort
            if not errors:
                options: dict[str, Any] = {
                    CONF_API_KEY: api_key,
                    API_QUOTA: api_quota,
                    AUTO_UPDATE: int(user_input[AUTO_UPDATE]),
                    # Remaining options set to default
                    CUSTOM_HOUR_SENSOR: 1,
                    HARD_LIMIT_API: "100.0",
                    KEY_ESTIMATE: "estimate",
                    BRK_ESTIMATE: True,
                    BRK_ESTIMATE10: True,
                    BRK_ESTIMATE90: True,
                    BRK_SITE: True,
                    BRK_HALFHOURLY: True,
                    BRK_HOURLY: True,
                    BRK_SITE_DETAILED: False,
                    EXCLUDE_SITES: [],
                    GET_ACTUALS: False,
                    USE_ACTUALS: HistoryType.FORECASTS,
                    GENERATION_ENTITIES: [],
                    SITE_EXPORT_ENTITY: "",
                    SITE_EXPORT_LIMIT: 0.0,
                    AUTO_DAMPEN: False,
                }
                damp = {f"damp{factor:02d}": 1.0 for factor in range(24)}

                status, message = await validate_sites(self.hass, options)
                if status != 200:
                    errors["base"] = message
                else:
                    return self.async_create_entry(title=TITLE, data={}, options=options | damp)

        solcast_json_exists = Path(f"{self.hass.config.config_dir}/solcast.json").is_file()
        _LOGGER.debug(
            "File solcast.json %s",
            "exists, defaulting to auto-update off" if solcast_json_exists else "does not exist, defaulting to auto-update on",
        )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY, default=""): str,
                    vol.Required(API_QUOTA, default="10"): str,
                    vol.Required(AUTO_UPDATE, default=str(int(not solcast_json_exists))): SelectSelector(
                        SelectSelectorConfig(options=AUTO_UPDATE_OPTIONS, mode=SelectSelectorMode.DROPDOWN, translation_key="auto_update")
                    ),
                }
            ),
            errors=errors,
        )


class SolcastSolarOptionFlowHandler(OptionsFlow):
    """Handle options."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow.

        Arguments:
            config_entry (ConfigEntry): The integration entry instance, contains the configuration.

        """
        self._entry = config_entry
        self._options = config_entry.options
        self._all_config_data: dict[str, Any] | None = None

    async def check_dead(self) -> None:
        """Check if the integration is presumed dead and reload if so."""

        if self.hass.data.get(DOMAIN, {}).get("presumed_dead", True):
            _LOGGER.warning("Integration presumed dead, reloading")
            self.hass.data[DOMAIN].pop("presumed_dead")
            await self.hass.config_entries.async_reload(self._entry.entry_id)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:  # noqa: C901
        """Initialise main options flow step.

        Arguments:
            user_input (dict, optional): The input provided by the user. Defaults to None.

        Returns:
            Any: Either an error, or the configuration dialogue results.

        """
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                all_config_data = {**self._options}
                _old_api_key = all_config_data[CONF_API_KEY]

                all_config_data[CONF_API_KEY], api_count, abort = validate_api_key(user_input)
                if abort is not None:
                    errors["base"] = abort
                    _LOGGER.debug("Options validation failed: %s", abort)

                if not errors:
                    all_config_data[API_QUOTA], abort = validate_api_limit(user_input, api_count)
                    if abort is not None:
                        errors["base"] = abort
                        _LOGGER.debug("Options validation failed: %s", abort)

                if not errors:
                    # Validate the custom hours sensor.
                    custom_hour_sensor = user_input[CUSTOM_HOUR_SENSOR]
                    if custom_hour_sensor < 1 or custom_hour_sensor > 144:
                        errors["base"] = "custom_invalid"
                        _LOGGER.debug("Options validation failed: %s", errors["base"])
                    else:
                        all_config_data[CUSTOM_HOUR_SENSOR] = custom_hour_sensor

                if not errors:
                    # Validate the hard limit.
                    hard_limit = user_input[HARD_LIMIT_API]
                    if hard_limit == "0":  # Hard limit can be disabled by setting to zero or 100
                        hard_limit = "100.0"
                    to_set: list[str] = []
                    for h in hard_limit.split(","):
                        h = h.strip()
                        if not h.replace(".", "", 1).isdigit():
                            errors["base"] = "hard_not_number"
                            _LOGGER.debug("Options validation failed: %s", errors["base"])
                            break
                        val = float(h)
                        to_set.append(f"{val:.1f}")
                    if not errors:
                        if len(to_set) > api_count:
                            errors["base"] = "hard_too_many"
                            _LOGGER.debug("Options validation failed: %s", errors["base"])
                    else:
                        hard_limit = ",".join(to_set)
                        all_config_data[HARD_LIMIT_API] = hard_limit

                # Validate estimated actuals and auto-dampen.
                all_config_data[GET_ACTUALS] = user_input.get(GET_ACTUALS, False)
                all_config_data[USE_ACTUALS] = int(user_input.get(USE_ACTUALS, 0))
                all_config_data[GENERATION_ENTITIES] = user_input.get(GENERATION_ENTITIES, [])
                all_config_data[AUTO_DAMPEN] = user_input.get(AUTO_DAMPEN, False)
                all_config_data[SITE_EXPORT_ENTITY] = user_input[SITE_EXPORT_ENTITY][0] if user_input.get(SITE_EXPORT_ENTITY) else ""
                all_config_data[SITE_EXPORT_LIMIT] = user_input.get(SITE_EXPORT_LIMIT, 0)
                if not errors:
                    if int(user_input.get(USE_ACTUALS, 0)) != HistoryType.FORECASTS and not user_input.get(GET_ACTUALS, False):
                        errors["base"] = "actuals_without_get"
                        _LOGGER.debug("Options validation failed: %s", errors["base"])
                if not errors:
                    if user_input.get(AUTO_DAMPEN, False) and not user_input.get(GET_ACTUALS, False):
                        errors["base"] = "dampen_without_actuals"
                        _LOGGER.debug("Options validation failed: %s", errors["base"])
                if not errors:
                    if user_input.get(AUTO_DAMPEN, False) and not user_input[GENERATION_ENTITIES]:
                        errors["base"] = "dampen_without_generation"
                        _LOGGER.debug("Options validation failed: %s", errors["base"])
                if not errors:
                    if user_input.get(SITE_EXPORT_ENTITY, []) != [] and len(user_input.get(SITE_EXPORT_ENTITY, [])) > 1:
                        errors["base"] = "export_multiple_entities"
                        _LOGGER.debug("Options validation failed: %s", errors["base"])
                if not errors:
                    if user_input.get(SITE_EXPORT_LIMIT, 0) > 0.0 and len(user_input.get(SITE_EXPORT_ENTITY, [])) == 0:
                        errors["base"] = "export_no_entity"
                        _LOGGER.debug("Options validation failed: %s", errors["base"])

                self._options = MappingProxyType(all_config_data)

                if not errors:
                    # Disable granular dampening if requested.
                    if user_input.get(SITE_DAMP) is not None:
                        all_config_data[SITE_DAMP] = user_input[SITE_DAMP]

                    all_config_data[AUTO_UPDATE] = int(user_input[AUTO_UPDATE])
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
                    all_config_data[EXCLUDE_SITES] = user_input.get(EXCLUDE_SITES, [])

                    self._all_config_data = all_config_data

                    if all_config_data[CONF_API_KEY] != _old_api_key:
                        status, message = await validate_sites(self.hass, all_config_data)
                        if status != 200:
                            errors["base"] = message

                if not errors:
                    if user_input.get(CONFIG_DAMP) and not user_input.get(AUTO_DAMPEN, False):
                        return await self.async_step_dampen()

                    self.hass.config_entries.async_update_entry(self._entry, title=TITLE, options=all_config_data)
                    await self.check_dead()
                    return self.async_abort(reason="reconfigured")
            except Exception as e:  # noqa: BLE001
                _LOGGER.error(traceback.format_exc())
                errors["base"] = f"Exception: {e!s}"

        update: list[SelectOptionDict] = [
            SelectOptionDict(label="none", value="0"),
            SelectOptionDict(label="sunrise_sunset", value="1"),
            SelectOptionDict(label="all_day", value="2"),
        ]

        history: list[SelectOptionDict] = [
            SelectOptionDict(label="forecasts", value="0"),
            SelectOptionDict(label="actuals", value="1"),
            SelectOptionDict(label="adjusted_actuals", value="2"),
        ]

        forecasts: list[SelectOptionDict] = [
            SelectOptionDict(label="estimate", value="estimate"),
            SelectOptionDict(label="estimate10", value="estimate10"),
            SelectOptionDict(label="estimate90", value="estimate90"),
        ]

        solcast = self.hass.data.get(DOMAIN, {}).get("solcast")
        exclude: list[SelectOptionDict] = [SelectOptionDict(label="not_loaded", value="")]
        if solcast is not None:
            exclude = [
                SelectOptionDict(label=site["name"] + " (" + site["resource_id"] + ")", value=site["resource_id"]) for site in solcast.sites
            ]

        entity_registry = er.async_get(self.hass)
        sensors: list[SelectOptionDict] = [SelectOptionDict(label="not_loaded", value="")]
        sensors = [
            SelectOptionDict(label=entry, value=entry)
            for entry, details in entity_registry.entities.items()
            if details.domain == "sensor"
            and "solcast_pv_forecast" not in entry
            and details.disabled_by is None
            and (details.device_class == "energy" or details.original_device_class == "energy")
        ]

        if self._options.get(SITE_EXPORT_ENTITY, "") != "":
            site_export_default = [self._options[SITE_EXPORT_ENTITY]]
        else:
            site_export_default = []
        if not self._options[AUTO_DAMPEN]:
            damp = {
                vol.Optional(CONFIG_DAMP, default=False)
                if not self._options[SITE_DAMP]
                else vol.Optional(SITE_DAMP, default=self._options[SITE_DAMP]): bool
            }
        else:
            damp = {}
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY, default=self._options.get(CONF_API_KEY)): str,
                    vol.Required(API_QUOTA, default=self._options[API_QUOTA]): str,
                    vol.Required(AUTO_UPDATE, default=str(int(self._options[AUTO_UPDATE]))): SelectSelector(
                        SelectSelectorConfig(options=update, mode=SelectSelectorMode.DROPDOWN, translation_key="auto_update")
                    ),
                    vol.Required(KEY_ESTIMATE, default=self._options.get(KEY_ESTIMATE, "estimate")): SelectSelector(
                        SelectSelectorConfig(options=forecasts, mode=SelectSelectorMode.DROPDOWN, translation_key="key_estimate")
                    ),
                    vol.Required(CUSTOM_HOUR_SENSOR, default=self._options[CUSTOM_HOUR_SENSOR]): int,
                    vol.Required(HARD_LIMIT_API, default=self._options.get(HARD_LIMIT_API)): str,
                    vol.Optional(BRK_ESTIMATE10, default=self._options[BRK_ESTIMATE10]): bool,
                    vol.Optional(BRK_ESTIMATE, default=self._options[BRK_ESTIMATE]): bool,
                    vol.Optional(BRK_ESTIMATE90, default=self._options[BRK_ESTIMATE90]): bool,
                    vol.Optional(BRK_SITE, default=self._options[BRK_SITE]): bool,
                    vol.Optional(BRK_HALFHOURLY, default=self._options[BRK_HALFHOURLY]): bool,
                    vol.Optional(BRK_HOURLY, default=self._options[BRK_HOURLY]): bool,
                    vol.Optional(BRK_SITE_DETAILED, default=self._options[BRK_SITE_DETAILED]): bool,
                    vol.Optional(EXCLUDE_SITES, default=self._options.get(EXCLUDE_SITES, [])): SelectSelector(
                        SelectSelectorConfig(options=exclude, mode=SelectSelectorMode.DROPDOWN, multiple=True)
                    ),
                    vol.Optional(GET_ACTUALS, default=self._options[GET_ACTUALS]): bool,
                    vol.Optional(AUTO_DAMPEN, default=self._options[AUTO_DAMPEN]): bool,
                    vol.Optional(GENERATION_ENTITIES, default=self._options.get(GENERATION_ENTITIES, [])): SelectSelector(
                        SelectSelectorConfig(options=sensors, mode=SelectSelectorMode.DROPDOWN, multiple=True)
                    ),
                    vol.Optional(SITE_EXPORT_ENTITY, default=site_export_default): SelectSelector(
                        SelectSelectorConfig(options=sensors, mode=SelectSelectorMode.DROPDOWN, multiple=True)
                    ),
                    vol.Optional(
                        SITE_EXPORT_LIMIT,
                        default=self._options.get(SITE_EXPORT_LIMIT, 0.0),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=100.0)),
                    vol.Required(USE_ACTUALS, default=str(int(self._options.get(USE_ACTUALS, 0)))): SelectSelector(
                        SelectSelectorConfig(options=history, mode=SelectSelectorMode.DROPDOWN, translation_key="energy_history")
                    ),
                }
                | damp
            ),
            errors=errors,
        )

    async def async_step_dampen(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the hourly dampening factors sub-option.

        Arguments:
            user_input (dict[str, Any] | None): The input provided by the user. Defaults to None.

        Returns:
            FlowResult: The configuration dialogue results.

        """
        errors: dict[str, str] = {}
        if self._all_config_data is None:
            all_config_data = {**self._options}
        else:
            all_config_data = self._all_config_data
        extant_factors = {f"damp{factor:02d}": all_config_data[f"damp{factor:02d}"] for factor in range(24)}

        if user_input is not None:
            for factor in range(24):
                all_config_data[f"damp{factor:02d}"] = user_input[f"damp{factor:02d}"]
            all_config_data[SITE_DAMP] = False

            self.hass.config_entries.async_update_entry(self._entry, title=TITLE, options=all_config_data)
            await self.check_dead()
            return self.async_abort(reason="reconfigured")

        return self.async_show_form(
            step_id="dampen",
            data_schema=vol.Schema(
                {
                    vol.Required(f"damp{factor:02d}", description={"suggested_value": extant_factors[f"damp{factor:02d}"]}): vol.All(
                        vol.Coerce(float), vol.Range(min=0.0, max=1.0)
                    )
                    for factor in range(24)
                }
            ),
            errors=errors,
        )
