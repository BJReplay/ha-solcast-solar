"""Solcast config flow."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant import config_entries
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
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

from . import entry_state, get_session_headers, get_version, state
from .advanced import async_is_allow_exceed_api_limit
from .const import (
    AFFIRMATION_REAUTH_SUCCESSFUL,
    AFFIRMATION_RECONFIGURED,
    AFFIRMATION_UNCHANGED,
    API_LIMIT,
    AUTO_DAMPEN,
    AUTO_UPDATE,
    BASE,
    BRK_ESTIMATE,
    BRK_ESTIMATE10,
    BRK_ESTIMATE90,
    BRK_HALFHOURLY,
    BRK_HOURLY,
    BRK_SITE,
    BRK_SITE_DETAILED,
    CONFIG_DAMP,
    CONFIG_VERSION,
    CUSTOM_HOURS,
    DEFAULT_SOLCAST_HTTPS_URL,
    DEVICE_NAME,
    DOMAIN,
    ENERGY_HISTORY,
    ENTRY_ID,
    EXCEPTION_ACTUALS_WITHOUT_GET,
    EXCEPTION_API_ERROR,
    EXCEPTION_CUSTOM_INVALID,
    EXCEPTION_DAMPEN_WITHOUT_ACTUALS,
    EXCEPTION_DAMPEN_WITHOUT_GENERATION,
    EXCEPTION_EXPORT_MULTIPLE_ENTITIES,
    EXCEPTION_EXPORT_NO_ENTITY,
    EXCEPTION_EXPORT_NO_LIMIT,
    EXCEPTION_GENERATION_MIXED_TYPES,
    EXCEPTION_INTERNAL_ERROR,
    EXCLUDE_SITES,
    GENERATION_ENTITIES,
    GET_ACTUALS,
    HARD_LIMIT_API,
    KEY_ESTIMATE,
    NAME,
    RESOURCE_ID,
    SITE_DAMP,
    SITE_EXPORT_ENTITY,
    SITE_EXPORT_LIMIT,
    SUGGESTED_VALUE,
    TITLE,
    UNKNOWN,
    USE_ACTUALS,
)
from .enums import HistoryType, LoadStatus
from .log import get_logger
from .migration import sync_legacy_keys
from .solcastapi import ConnectionOptions, SolcastApi
from .state import set_sensitive
from .validators import (
    All,
    Coerce,
    Optional,
    Range,
    Required,
    Schema,
    validate_api_key,
    validate_api_limit,
    validate_custom_hours_value,
    validate_hard_limit_value,
)

_LOGGER = get_logger(__name__)

AUTO_UPDATE_OPTIONS: list[SelectOptionDict] = [
    SelectOptionDict(label="none", value="0"),
    SelectOptionDict(label="sunrise_sunset", value="1"),
    SelectOptionDict(label="all_day", value="2"),
]

ATTR_BREAKDOWN = "attr_breakdown"
BREAKDOWN_ATTRIBUTE_OPTIONS: tuple[str, ...] = (
    BRK_ESTIMATE10,
    BRK_ESTIMATE,
    BRK_ESTIMATE90,
    BRK_SITE,
    BRK_HALFHOURLY,
    BRK_HOURLY,
    BRK_SITE_DETAILED,
)


async def _get_time_zone(hass: HomeAssistant) -> ZoneInfo | timezone:
    tz = await dt_util.async_get_time_zone(hass.config.time_zone)
    return tz if tz is not None else dt_util.UTC


async def _async_is_allow_exceed_api_limit(hass: HomeAssistant) -> bool:
    """Check if the allow exceed API limit advanced option is enabled."""

    return await async_is_allow_exceed_api_limit(hass)


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
        user_input[API_LIMIT],
        DEFAULT_SOLCAST_HTTPS_URL,
        hass.config.path(f"{hass.config.config_dir}/solcast.json"),
        await _get_time_zone(hass),
        user_input[AUTO_UPDATE],
        {str(a): 1.0 for a in range(24)},
        user_input[CUSTOM_HOURS],
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
    await solcast.async_migrate_config_files()
    await solcast.advanced_opt.read_advanced_options()
    solcast.headers = get_session_headers(solcast, await get_version(hass))

    status, message, api_key_in_error = await solcast.sites_cache.get_sites_and_usage(prior_crash=False, use_cache=False)
    if status != 200:
        if status in (401, 403):
            return status, f"Bad API key, {message} returned for {api_key_in_error}"
        return status, f"Error {message} for API key {api_key_in_error}"
    if solcast.sites_status == LoadStatus.NO_SITES:
        return 404, f"No sites for the API key {api_key_in_error} are configured at solcast.com"
    return 200, ""


@config_entries.HANDLERS.register(DOMAIN)
class SolcastSolarFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle the config flow."""

    VERSION = CONFIG_VERSION

    _entry: ConfigEntry | None = None

    def _mark_reset_old_key(self) -> None:
        """Signal next options update to treat the API key as freshly reconfigured."""
        assert self._entry is not None
        entry_state.get(self._entry.entry_id).reset_old_key = True

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
        self._entry = self.hass.config_entries.async_get_entry(self.context.get(ENTRY_ID, ""))
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle a re-key flow."""
        errors: dict[str, str] = {}
        description_placeholders = {DEVICE_NAME: self._entry.title if self._entry is not None else UNKNOWN}
        submitted_input: dict[str, Any] | None = None

        all_config_data = {**self._entry.options} if self._entry is not None else {}

        if user_input is not None:
            submitted_input = {**user_input}
            api_key, _, abort = validate_api_key(user_input)
            if abort is not None:
                errors[BASE] = abort
            if not errors:
                key_changed = api_key != all_config_data[CONF_API_KEY]
                all_config_data[CONF_API_KEY] = api_key
                status, message = await validate_sites(self.hass, all_config_data)
                if status != 200:
                    errors[BASE] = EXCEPTION_API_ERROR
                    description_placeholders["error_detail"] = message
                elif key_changed and self._entry is not None:
                    await set_sensitive(self.hass, self._entry)
            if not errors:
                result = self.async_abort(reason=EXCEPTION_INTERNAL_ERROR)
                if self._entry is not None:
                    if key_changed:
                        self._mark_reset_old_key()
                        sync_legacy_keys(all_config_data)
                        self.hass.config_entries.async_update_entry(self._entry, title=TITLE, options=all_config_data)
                    if self._entry.state is not ConfigEntryState.LOADED:
                        _LOGGER.debug("Loading presumed dead integration")
                        await (await state.async_get(self.hass, self._entry.entry_id)).async_clear()
                        self.hass.config_entries.async_schedule_reload(self._entry.entry_id)
                    result = self.async_abort(reason=AFFIRMATION_REAUTH_SUCCESSFUL if key_changed else AFFIRMATION_UNCHANGED)
                return result

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                Schema(
                    {
                        Required(CONF_API_KEY, default=all_config_data[CONF_API_KEY]): str,
                    }
                ),  # pyright: ignore[reportArgumentType]
                submitted_input if errors else None,
            ),
            description_placeholders=description_placeholders,
            errors=errors,
        )

    async def async_step_reconfigure(self, entry: Mapping[str, Any]) -> ConfigFlowResult:
        """Reconfigure API key, limit and auto-update."""
        self._entry = self.hass.config_entries.async_get_entry(self.context.get(ENTRY_ID, ""))
        return await self.async_step_reconfigure_confirm()

    async def async_step_reconfigure_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle a reconfiguration flow."""
        errors: dict[str, str] = {}
        description_placeholders = {DEVICE_NAME: self._entry.title if self._entry is not None else UNKNOWN}
        submitted_input: dict[str, Any] | None = None

        all_config_data = {**self._entry.options} if self._entry is not None else {}

        if user_input is not None:
            submitted_input = {**user_input}
            api_key, api_count, abort = validate_api_key(user_input)
            api_limit = "10"
            if abort is not None:
                errors[BASE] = abort
            if not errors:
                allow_exceed = await _async_is_allow_exceed_api_limit(self.hass)
                api_limit, abort = validate_api_limit(user_input, api_count, allow_exceed=allow_exceed)
                if abort is not None:
                    errors[BASE] = abort
            if not errors:
                key_changed = api_key != all_config_data[CONF_API_KEY]
                options_changed = (
                    key_changed
                    or api_limit != all_config_data[API_LIMIT]
                    or int(user_input[AUTO_UPDATE]) != int(all_config_data[AUTO_UPDATE])
                )
                all_config_data[CONF_API_KEY] = api_key
                all_config_data[API_LIMIT] = api_limit
                all_config_data[AUTO_UPDATE] = int(user_input[AUTO_UPDATE])

                if key_changed:
                    status, message = await validate_sites(self.hass, all_config_data)
                    if status != 200:
                        errors[BASE] = EXCEPTION_API_ERROR
                        description_placeholders["error_detail"] = message
                    elif self._entry is not None:
                        await set_sensitive(self.hass, self._entry)
            if not errors:
                result = self.async_abort(reason=EXCEPTION_INTERNAL_ERROR)
                if self._entry is not None:
                    if options_changed:
                        sync_legacy_keys(all_config_data)
                        if key_changed:
                            self._mark_reset_old_key()
                        self.hass.config_entries.async_update_entry(self._entry, title=TITLE, options=all_config_data)
                        if self._entry.state is not ConfigEntryState.LOADED:
                            _LOGGER.debug("Loading presumed dead integration")
                            await (await state.async_get(self.hass, self._entry.entry_id)).async_clear()
                            self.hass.config_entries.async_schedule_reload(self._entry.entry_id)
                    result = self.async_abort(reason=AFFIRMATION_RECONFIGURED if options_changed else AFFIRMATION_UNCHANGED)
                return result

        return self.async_show_form(
            step_id="reconfigure_confirm",
            data_schema=self.add_suggested_values_to_schema(
                Schema(
                    {
                        Required(CONF_API_KEY, default=all_config_data[CONF_API_KEY]): str,
                        Required(API_LIMIT, default=all_config_data[API_LIMIT]): str,
                        Required(AUTO_UPDATE, default=str(all_config_data[AUTO_UPDATE])): SelectSelector(
                            SelectSelectorConfig(options=AUTO_UPDATE_OPTIONS, mode=SelectSelectorMode.DROPDOWN, translation_key=AUTO_UPDATE)
                        ),
                    }
                ),  # pyright: ignore[reportArgumentType]
                submitted_input if errors else None,
            ),
            description_placeholders=description_placeholders,
            errors=errors,
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle a flow initiated by the user.

        Arguments:
            user_input (dict[str, Any] | None, optional): The config submitted by a user. Defaults to None.

        Returns:
            FlowResult: The form to show.

        """
        errors: dict[str, str] = {}
        description_placeholders: dict[str, str] = {}
        submitted_input: dict[str, Any] | None = None

        if user_input is not None:
            submitted_input = {**user_input}
            api_key, api_count, abort = validate_api_key(user_input)
            api_limit = "10"
            if abort is not None:
                errors[BASE] = abort
            if not errors:
                allow_exceed = await _async_is_allow_exceed_api_limit(self.hass)
                api_limit, abort = validate_api_limit(user_input, api_count, allow_exceed=allow_exceed)
                if abort is not None:
                    errors[BASE] = abort
            if not errors:
                options: dict[str, Any] = {
                    CONF_API_KEY: api_key,
                    API_LIMIT: api_limit,
                    AUTO_UPDATE: int(user_input[AUTO_UPDATE]),
                    # Remaining options set to default
                    CUSTOM_HOURS: 1,
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

                status, message = await validate_sites(self.hass, options)
                if status != 200:
                    errors[BASE] = EXCEPTION_API_ERROR
                    description_placeholders["error_detail"] = message
                else:
                    return self.async_create_entry(
                        title=TITLE, data={}, options=options | {f"damp{factor:02d}": 1.0 for factor in range(24)}
                    )

        solcast_json_exists = Path(f"{self.hass.config.config_dir}/solcast.json").is_file()
        _LOGGER.debug(
            "File solcast.json %s",
            "exists, defaulting to auto-update off" if solcast_json_exists else "does not exist, defaulting to auto-update on",
        )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                Schema(
                    {
                        Required(CONF_API_KEY, default=""): str,
                        Required(API_LIMIT, default="10"): str,
                        Required(AUTO_UPDATE, default=str(int(not solcast_json_exists))): SelectSelector(
                            SelectSelectorConfig(options=AUTO_UPDATE_OPTIONS, mode=SelectSelectorMode.DROPDOWN, translation_key=AUTO_UPDATE)
                        ),
                    }
                ),  # pyright: ignore[reportArgumentType]
                submitted_input if errors else None,
            ),
            description_placeholders=description_placeholders,
            errors=errors,
        )


class SolcastSolarOptionFlowHandler(OptionsFlow):
    """Handle options."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialise options flow.

        Arguments:
            config_entry (ConfigEntry): The integration entry instance, contains the configuration.

        """
        self._entry = config_entry
        self._options = config_entry.options
        self._all_config_data: dict[str, Any] | None = None
        self._api_key_changed = False

    async def check_dead(self) -> None:
        """Check if the integration is presumed dead and reload if so."""

        if self._entry.state is ConfigEntryState.SETUP_IN_PROGRESS:
            _LOGGER.debug("Integration reload already in progress")
            return

        if self._entry.state is not ConfigEntryState.LOADED:
            state_store = await state.async_get(self.hass, self._entry.entry_id)
            if state_store.state.presumed_dead:
                _LOGGER.warning("Integration presumed dead, reloading")
                await state_store.async_clear()
            else:
                _LOGGER.debug("Integration not loaded during options update, reloading")
            await self.hass.config_entries.async_reload(self._entry.entry_id)

    def _build_sensor_options(self) -> tuple[list[SelectOptionDict], list[SelectOptionDict]]:
        """Build sorted sensor and energy sensor option lists for the options form.

        Returns:
            tuple[list[SelectOptionDict], list[SelectOptionDict]]: Sorted lists of sensors
                Energy/power and energy-only sensors, excluding own entities.

        """
        entity_registry = er.async_get(self.hass)
        own_entities = {entry for entry, details in entity_registry.entities.items() if details.config_entry_id == self._entry.entry_id}
        sensors: list[SelectOptionDict] = [
            SelectOptionDict(label=entry, value=entry)
            for entry, details in entity_registry.entities.items()
            if entry not in own_entities
            and entry.startswith("sensor.")
            and details.disabled_by is None
            and (details.device_class or details.original_device_class) in (SensorDeviceClass.ENERGY, SensorDeviceClass.POWER)
        ]
        state_entities = self.hass.states.async_entity_ids("sensor")
        sensor_values = {option["value"] for option in sensors}
        sensors += [
            SelectOptionDict(label=entity, value=entity)
            for entity in state_entities
            if entity not in sensor_values
            and entity not in own_entities
            and (_state := self.hass.states.get(entity)) is not None
            and (device_class := _state.attributes.get("device_class")) is not None
            and isinstance(device_class, str)
            and device_class
            in (
                SensorDeviceClass.ENERGY,
                SensorDeviceClass.POWER,
            )
        ]
        sensors.sort(key=lambda x: x["label"])
        energy_sensors: list[SelectOptionDict] = [
            SelectOptionDict(label=entry, value=entry)
            for entry, details in entity_registry.entities.items()
            if entry not in own_entities
            and entry.startswith("sensor.")
            and details.disabled_by is None
            and (details.device_class or details.original_device_class) == SensorDeviceClass.ENERGY
        ]
        energy_sensor_values = {option["value"] for option in energy_sensors}
        energy_sensors += [
            SelectOptionDict(label=entity, value=entity)
            for entity in state_entities
            if entity not in energy_sensor_values
            and entity not in own_entities
            and (_state := self.hass.states.get(entity)) is not None
            and (device_class := _state.attributes.get("device_class")) is not None
            and isinstance(device_class, str)
            and device_class == SensorDeviceClass.ENERGY
        ]
        energy_sensors.sort(key=lambda x: x["label"])
        return sensors, energy_sensors

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:  # noqa: C901
        """Initialise main options flow step.

        Arguments:
            user_input (dict, optional): The input provided by the user. Defaults to None.

        Returns:
            Any: Either an error, or the configuration dialogue results.

        """
        errors: dict[str, str] = {}
        description_placeholders: dict[str, str] = {}
        submitted_input: dict[str, Any] | None = None

        if user_input is not None:
            submitted_input = {**user_input}
            try:
                # Normalize empty/None limit values to 0 to allow clearing
                if SITE_EXPORT_LIMIT in user_input and user_input[SITE_EXPORT_LIMIT] in (None, "", "0"):
                    user_input[SITE_EXPORT_LIMIT] = 0.0

                all_config_data = {**self._options}
                _old_api_key = self._entry.options[CONF_API_KEY]

                all_config_data[CONF_API_KEY], api_count, abort = validate_api_key(user_input)
                if abort is not None:
                    errors[BASE] = abort
                    _LOGGER.debug("Options validation failed: %s", abort)

                if not errors:
                    all_config_data[API_LIMIT], abort = validate_api_limit(
                        user_input,
                        api_count,
                        allow_exceed=await _async_is_allow_exceed_api_limit(self.hass),
                    )
                    if abort is not None:
                        errors[BASE] = abort
                        _LOGGER.debug("Options validation failed: %s", abort)

                if not errors:
                    # Validate the custom hours sensor.
                    custom_hour_sensor, abort = validate_custom_hours_value(str(user_input[CUSTOM_HOURS]))
                    if abort is not None:
                        errors[BASE] = EXCEPTION_CUSTOM_INVALID
                        _LOGGER.debug("Options validation failed: %s", errors[BASE])
                    else:
                        all_config_data[CUSTOM_HOURS] = custom_hour_sensor

                if not errors:
                    # Validate the hard limit.
                    hard_limit, abort = validate_hard_limit_value(user_input[HARD_LIMIT_API], api_count)
                    if abort is not None:
                        errors[BASE] = abort
                        _LOGGER.debug("Options validation failed: %s", errors[BASE])
                    else:
                        all_config_data[HARD_LIMIT_API] = hard_limit

                # Validate estimated actuals and auto-dampen.
                all_config_data[GET_ACTUALS] = user_input.get(GET_ACTUALS, False)
                all_config_data[USE_ACTUALS] = int(user_input.get(USE_ACTUALS, 0))
                all_config_data[GENERATION_ENTITIES] = user_input.get(GENERATION_ENTITIES, [])
                all_config_data[AUTO_DAMPEN] = user_input.get(AUTO_DAMPEN, False)
                all_config_data[SITE_EXPORT_ENTITY] = user_input[SITE_EXPORT_ENTITY][0] if user_input.get(SITE_EXPORT_ENTITY) else ""
                all_config_data[SITE_EXPORT_LIMIT] = user_input.get(SITE_EXPORT_LIMIT, 0)
                # If site export entity is removed, automatically clear the limit since it's irrelevant
                if not all_config_data[SITE_EXPORT_ENTITY]:
                    all_config_data[SITE_EXPORT_LIMIT] = 0.0
                if not errors:
                    if int(user_input.get(USE_ACTUALS, 0)) != HistoryType.FORECASTS and not user_input.get(GET_ACTUALS, False):
                        errors[BASE] = EXCEPTION_ACTUALS_WITHOUT_GET
                        _LOGGER.debug("Options validation failed: %s", errors[BASE])
                if not errors:
                    if user_input.get(AUTO_DAMPEN, False) and not user_input.get(GET_ACTUALS, False):
                        errors[BASE] = EXCEPTION_DAMPEN_WITHOUT_ACTUALS
                        _LOGGER.debug("Options validation failed: %s", errors[BASE])
                if not errors:
                    if user_input.get(AUTO_DAMPEN, False) and not user_input[GENERATION_ENTITIES]:
                        errors[BASE] = EXCEPTION_DAMPEN_WITHOUT_GENERATION
                        _LOGGER.debug("Options validation failed: %s", errors[BASE])
                if not errors and len(user_input.get(GENERATION_ENTITIES, [])) > 1:
                    gen_entities = user_input[GENERATION_ENTITIES]
                    device_classes = set()
                    _entity_registry = er.async_get(self.hass)
                    for gen_entity in gen_entities:
                        r_entity = _entity_registry.async_get(gen_entity)
                        dc = r_entity.device_class or r_entity.original_device_class if r_entity is not None else None
                        if dc not in (SensorDeviceClass.ENERGY, SensorDeviceClass.POWER):
                            entity_state = self.hass.states.get(gen_entity)
                            dc = entity_state.attributes.get("device_class") if entity_state is not None else None
                        if dc in (SensorDeviceClass.ENERGY, SensorDeviceClass.POWER):
                            device_classes.add(dc)
                    if len(device_classes) > 1:
                        errors[BASE] = EXCEPTION_GENERATION_MIXED_TYPES
                        _LOGGER.debug("Options validation failed: %s", errors[BASE])
                if not errors:
                    if user_input.get(SITE_EXPORT_ENTITY, []) != [] and len(user_input.get(SITE_EXPORT_ENTITY, [])) > 1:
                        errors[BASE] = EXCEPTION_EXPORT_MULTIPLE_ENTITIES
                        _LOGGER.debug("Options validation failed: %s", errors[BASE])
                if not errors:
                    # Require entity and limit to be both set or both cleared. No partial configurations.
                    site_export_limit = user_input.get(SITE_EXPORT_LIMIT, 0)
                    # Extract entity the same way it's extracted above (first element of list, or empty string)
                    site_export_entity = user_input[SITE_EXPORT_ENTITY][0] if user_input.get(SITE_EXPORT_ENTITY) else ""
                    if site_export_limit > 0.0 and not site_export_entity:
                        errors[BASE] = EXCEPTION_EXPORT_NO_ENTITY
                        _LOGGER.debug("Options validation failed: %s", errors[BASE])
                    elif site_export_limit == 0.0 and site_export_entity:
                        # If entity is set, limit must also be set (> 0)
                        errors[BASE] = EXCEPTION_EXPORT_NO_LIMIT
                        _LOGGER.debug("Options validation failed: %s", errors[BASE])
                if not errors:
                    # Disable granular dampening if requested.
                    if user_input.get(SITE_DAMP) is not None:
                        all_config_data[SITE_DAMP] = user_input[SITE_DAMP]

                    all_config_data[AUTO_UPDATE] = int(user_input[AUTO_UPDATE])
                    all_config_data[KEY_ESTIMATE] = user_input[KEY_ESTIMATE]
                    selected_breakdowns = set(user_input.get(ATTR_BREAKDOWN, []))
                    for breakdown_key in BREAKDOWN_ATTRIBUTE_OPTIONS:
                        all_config_data[breakdown_key] = (
                            breakdown_key in selected_breakdowns
                            if ATTR_BREAKDOWN in user_input
                            else user_input.get(breakdown_key, all_config_data.get(breakdown_key, False))
                        )
                    all_config_data[EXCLUDE_SITES] = user_input.get(EXCLUDE_SITES, [])

                    self._all_config_data = all_config_data

                    if all_config_data[CONF_API_KEY] != _old_api_key:
                        status, message = await validate_sites(self.hass, all_config_data)
                        if status != 200:
                            errors[BASE] = EXCEPTION_API_ERROR
                            description_placeholders["error_detail"] = message

                if not errors:
                    self._api_key_changed = all_config_data[CONF_API_KEY] != _old_api_key
                    if user_input.get(CONFIG_DAMP) and not user_input.get(AUTO_DAMPEN, False):
                        return await self.async_step_dampen()

                    sync_legacy_keys(all_config_data)
                    if all_config_data != self._entry.options:
                        if self._api_key_changed:
                            await set_sensitive(self.hass, self._entry)
                        self.hass.config_entries.async_update_entry(self._entry, title=TITLE, options=all_config_data)
                        await self.check_dead()
                        return self.async_abort(reason=AFFIRMATION_RECONFIGURED)
                    return self.async_abort(reason=AFFIRMATION_UNCHANGED)
            except Exception:
                _LOGGER.exception("Unexpected exception while validating options")
                errors[BASE] = EXCEPTION_INTERNAL_ERROR

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

        solcast = None
        if self._entry is not None:
            runtime_data = getattr(self._entry, "runtime_data", None)
            if runtime_data is not None:
                solcast = runtime_data.coordinator.solcast
        exclude: list[SelectOptionDict] = [SelectOptionDict(label="not_loaded", value="")]
        if solcast is not None:
            exclude = [
                SelectOptionDict(label=site[NAME] + " (" + site[RESOURCE_ID] + ")", value=site[RESOURCE_ID]) for site in solcast.sites
            ]

        sensors, energy_sensors = self._build_sensor_options()

        if self._options.get(SITE_EXPORT_ENTITY, "") != "":
            site_export_default = [self._options[SITE_EXPORT_ENTITY]]
        else:
            site_export_default = []
        if not self._options[AUTO_DAMPEN]:
            damp = {
                Optional(CONFIG_DAMP, default=False)
                if not self._options[SITE_DAMP]
                else Optional(SITE_DAMP, default=self._options[SITE_DAMP]): bool
            }
        else:
            damp = {}
        breakdown_defaults = [breakdown_key for breakdown_key in BREAKDOWN_ATTRIBUTE_OPTIONS if self._options.get(breakdown_key, False)]
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                Schema(
                    {
                        Required(CONF_API_KEY, default=self._options.get(CONF_API_KEY)): str,
                        Required(API_LIMIT, default=self._options[API_LIMIT]): str,
                        Required(AUTO_UPDATE, default=str(int(self._options[AUTO_UPDATE]))): SelectSelector(
                            SelectSelectorConfig(options=update, mode=SelectSelectorMode.DROPDOWN, translation_key=AUTO_UPDATE)
                        ),
                        Required(KEY_ESTIMATE, default=self._options.get(KEY_ESTIMATE, "estimate")): SelectSelector(
                            SelectSelectorConfig(options=forecasts, mode=SelectSelectorMode.DROPDOWN, translation_key=KEY_ESTIMATE)
                        ),
                        Required(CUSTOM_HOURS, default=self._options[CUSTOM_HOURS]): int,
                        Required(HARD_LIMIT_API, default=self._options.get(HARD_LIMIT_API)): str,
                        Optional(ATTR_BREAKDOWN, default=breakdown_defaults): SelectSelector(
                            SelectSelectorConfig(
                                options=[SelectOptionDict(label=option, value=option) for option in BREAKDOWN_ATTRIBUTE_OPTIONS],
                                mode=SelectSelectorMode.DROPDOWN,
                                multiple=True,
                                translation_key=ATTR_BREAKDOWN,
                            )
                        ),
                        Optional(EXCLUDE_SITES, default=self._options.get(EXCLUDE_SITES, [])): SelectSelector(
                            SelectSelectorConfig(options=exclude, mode=SelectSelectorMode.DROPDOWN, multiple=True)
                        ),
                        Optional(GET_ACTUALS, default=self._options[GET_ACTUALS]): bool,
                        Optional(AUTO_DAMPEN, default=self._options[AUTO_DAMPEN]): bool,
                        Optional(GENERATION_ENTITIES, default=self._options.get(GENERATION_ENTITIES, [])): SelectSelector(
                            SelectSelectorConfig(options=sensors, mode=SelectSelectorMode.DROPDOWN, multiple=True)
                        ),
                        Optional(SITE_EXPORT_ENTITY, default=site_export_default): SelectSelector(
                            SelectSelectorConfig(options=energy_sensors, mode=SelectSelectorMode.DROPDOWN, multiple=True)
                        ),
                        Optional(
                            SITE_EXPORT_LIMIT,
                            default=self._options.get(SITE_EXPORT_LIMIT, 0.0),
                        ): All(Coerce(float), Range(min=0.0, max=100.0)),
                        Required(USE_ACTUALS, default=str(int(self._options.get(USE_ACTUALS, 0)))): SelectSelector(
                            SelectSelectorConfig(options=history, mode=SelectSelectorMode.DROPDOWN, translation_key=ENERGY_HISTORY)
                        ),
                    }
                    | damp
                ),  # pyright: ignore[reportArgumentType]
                submitted_input if errors else None,
            ),
            description_placeholders=description_placeholders,
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

            sync_legacy_keys(all_config_data)
            if all_config_data != self._entry.options:
                if self._api_key_changed:
                    await set_sensitive(self.hass, self._entry)
                self.hass.config_entries.async_update_entry(self._entry, title=TITLE, options=all_config_data)
                await self.check_dead()
                return self.async_abort(reason=AFFIRMATION_RECONFIGURED)
            return self.async_abort(reason=AFFIRMATION_UNCHANGED)

        return self.async_show_form(
            step_id="dampen",
            data_schema=Schema(
                {
                    Required(f"damp{factor:02d}", description={SUGGESTED_VALUE: extant_factors[f"damp{factor:02d}"]}): All(
                        Coerce(float), Range(min=0.0, max=1.0)
                    )
                    for factor in range(24)
                }
            ),  # pyright: ignore[reportArgumentType]
            errors=errors,
        )
