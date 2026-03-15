"""Solcast PV forecast, service actions."""

from datetime import timedelta
from enum import Enum
import logging
from pathlib import Path
from typing import Any, Final

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import (
    config_validation as cv,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.util import dt as dt_util

from .const import (
    ACTION,
    API_LIMIT,
    AUTO_DAMPEN,
    AUTO_UPDATE,
    BRK_ESTIMATE,
    BRK_ESTIMATE10,
    BRK_ESTIMATE90,
    BRK_HALFHOURLY,
    BRK_HOURLY,
    BRK_SITE,
    BRK_SITE_DETAILED,
    CUSTOM_HOURS,
    DAMP_FACTOR,
    DOMAIN,
    EVENT_END_DATETIME,
    EVENT_START_DATETIME,
    EXCEPTION_ACTUALS_WITHOUT_GET,
    EXCEPTION_DAMP_AUTO_ENABLED,
    EXCEPTION_DAMP_COUNT_NOT_CORRECT,
    EXCEPTION_DAMP_ERROR_PARSING,
    EXCEPTION_DAMP_NO_ALL_24,
    EXCEPTION_DAMP_NO_FACTORS,
    EXCEPTION_DAMP_NOT_SITE,
    EXCEPTION_DAMP_OUTSIDE_RANGE,
    EXCEPTION_DAMPEN_WITHOUT_ACTUALS,
    EXCEPTION_DAMPEN_WITHOUT_GENERATION,
    EXCEPTION_EXPORT_NO_ENTITY,
    EXCEPTION_INTEGRATION_NOT_LOADED,
    EXCEPTION_SET_OPTIONS_EMPTY,
    EXCLUDE_SITES,
    GENERATION_ENTITIES,
    GET_ACTUALS,
    HARD_LIMIT,
    HARD_LIMIT_API,
    HOURS,
    ISSUE_ACTION_DEPRECATED,
    ISSUE_DEPRECATED_REMOVE_HARD_LIMIT,
    ISSUE_DEPRECATED_SET_CUSTOM_HOURS,
    ISSUE_DEPRECATED_SET_HARD_LIMIT,
    KEY_ESTIMATE,
    RESOURCE_ID,
    SCHEMA,
    SERVICE_CLEAR_DATA,
    SERVICE_DIAGNOSTIC_SELF_TEST,
    SERVICE_FORCE_UPDATE_ESTIMATES,
    SERVICE_FORCE_UPDATE_FORECASTS,
    SERVICE_GET_DAMPENING,
    SERVICE_GET_OPTIONS,
    SERVICE_QUERY_ESTIMATE_DATA,
    SERVICE_QUERY_FORECAST_DATA,
    SERVICE_REMOVE_HARD_LIMIT,
    SERVICE_SET_CUSTOM_HOURS,
    SERVICE_SET_DAMPENING,
    SERVICE_SET_HARD_LIMIT,
    SERVICE_SET_OPTIONS,
    SERVICE_UPDATE,
    SITE,
    SITE_DAMP,
    SITE_EXPORT_ENTITY,
    SITE_EXPORT_LIMIT,
    SUPPORTS_RESPONSE as SUPPORTS_RESPONSE_KEY,
    UNDAMPENED,
    USE_ACTUALS,
)
from .coordinator import SolcastUpdateCoordinator
from .solcastapi import SolcastApi
from .util import sync_legacy_keys
from .validators import (
    validate_api_key_value,
    validate_api_limit_value,
    validate_auto_update_value,
    validate_custom_hours_value,
    validate_export_limit_value,
    validate_hard_limit_value,
    validate_key_estimate_value,
    validate_use_actuals_value,
)

SERVICE_DAMP_SCHEMA: Final = vol.All(
    {
        vol.Required(DAMP_FACTOR): cv.string,
        vol.Optional(SITE): cv.string,
    }
)
SERVICE_DAMP_GET_SCHEMA: Final = vol.All(
    {
        vol.Optional(SITE): cv.string,
    }
)
SERVICE_HARD_LIMIT_SCHEMA: Final = vol.All(
    {
        vol.Required(HARD_LIMIT): cv.string,
    }
)
SERVICE_CUSTOM_HOURS_SCHEMA: Final = vol.All(
    {
        vol.Required(HOURS): cv.string,
    }
)
SERVICE_QUERY_SCHEMA: Final = vol.All(
    {
        vol.Required(EVENT_START_DATETIME): cv.datetime,
        vol.Required(EVENT_END_DATETIME): cv.datetime,
        vol.Optional(UNDAMPENED): cv.boolean,
        vol.Optional(SITE): cv.string,
    }
)
SERVICE_QUERY_ESTIMATE_SCHEMA: Final = vol.All(
    {
        vol.Optional(EVENT_START_DATETIME): cv.datetime,
        vol.Optional(EVENT_END_DATETIME): cv.datetime,
    }
)
SERVICE_SET_OPTIONS_SCHEMA: Final = vol.All(
    {
        vol.Optional(CONF_API_KEY): cv.string,
        vol.Optional(API_LIMIT): cv.string,
        vol.Optional(AUTO_UPDATE): cv.string,
        vol.Optional(KEY_ESTIMATE): cv.string,
        vol.Optional(CUSTOM_HOURS): cv.string,
        vol.Optional(HARD_LIMIT): cv.string,
        vol.Optional(BRK_ESTIMATE): cv.boolean,
        vol.Optional(BRK_ESTIMATE10): cv.boolean,
        vol.Optional(BRK_ESTIMATE90): cv.boolean,
        vol.Optional(BRK_SITE): cv.boolean,
        vol.Optional(BRK_HALFHOURLY): cv.boolean,
        vol.Optional(BRK_HOURLY): cv.boolean,
        vol.Optional(BRK_SITE_DETAILED): cv.boolean,
        vol.Optional(GET_ACTUALS): cv.boolean,
        vol.Optional(USE_ACTUALS): cv.string,
        vol.Optional(AUTO_DAMPEN): cv.boolean,
        vol.Optional(GENERATION_ENTITIES): cv.string,
        vol.Optional(EXCLUDE_SITES): cv.string,
        vol.Optional(SITE_EXPORT_ENTITY): cv.string,
        vol.Optional(SITE_EXPORT_LIMIT): cv.string,
    }
)

_LOGGER = logging.getLogger(__name__)

_ALL_ACTIONS: Final = [
    SERVICE_CLEAR_DATA,
    SERVICE_DIAGNOSTIC_SELF_TEST,
    SERVICE_FORCE_UPDATE_ESTIMATES,
    SERVICE_FORCE_UPDATE_FORECASTS,
    SERVICE_GET_DAMPENING,
    SERVICE_GET_OPTIONS,
    SERVICE_QUERY_ESTIMATE_DATA,
    SERVICE_QUERY_FORECAST_DATA,
    SERVICE_REMOVE_HARD_LIMIT,
    SERVICE_SET_DAMPENING,
    SERVICE_SET_CUSTOM_HOURS,
    SERVICE_SET_HARD_LIMIT,
    SERVICE_SET_OPTIONS,
    SERVICE_UPDATE,
]


async def stub_action(call: ServiceCall) -> None:
    """Raise an exception on action when the entry is not loaded.

    Arguments:
        call: Not used.

    Raises:
        ServiceValidationError: Notify the caller that the integration is not loaded.

    """
    _LOGGER.error("Integration not loaded")
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key=EXCEPTION_INTEGRATION_NOT_LOADED)


def register_stub_actions(hass: HomeAssistant) -> None:
    """Register all actions to return an error state initially.

    Arguments:
        hass: The Home Assistant instance.

    """
    for action in _ALL_ACTIONS:
        hass.services.async_register(DOMAIN, action, stub_action)


def unregister_actions(hass: HomeAssistant) -> None:
    """Replace all real actions with stub error actions.

    Arguments:
        hass: The Home Assistant instance.

    """
    for action in hass.services.async_services_for_domain(DOMAIN):
        _LOGGER.debug("Remove action %s.%s", DOMAIN, action)
        hass.services.async_remove(DOMAIN, action)
        hass.services.async_register(DOMAIN, action, stub_action)


class ServiceActions:
    """Service actions for the Solcast Solar integration."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: SolcastUpdateCoordinator,
        solcast: SolcastApi,
    ) -> None:
        """Initialise the service actions.

        Arguments:
            hass: The Home Assistant instance.
            entry: The integration entry instance.
            coordinator: The update coordinator.
            solcast: The Solcast API instance.

        """
        self._hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self._solcast = solcast
        self._register()

    def _get_service_actions(self) -> dict[str, dict[str, Any]]:
        """Return the mapping of service action names to their configuration.

        Returns:
            The service action definitions for registration.

        """
        return {
            SERVICE_CLEAR_DATA: {ACTION: self.async_clear_solcast_data},
            SERVICE_DIAGNOSTIC_SELF_TEST: {
                ACTION: self.async_diagnostic_self_test,
                SCHEMA: None,
                SUPPORTS_RESPONSE_KEY: SupportsResponse.ONLY,
            },
            SERVICE_FORCE_UPDATE_ESTIMATES: {ACTION: self.async_force_update_estimates},
            SERVICE_FORCE_UPDATE_FORECASTS: {ACTION: self.async_force_update_forecast},
            SERVICE_GET_DAMPENING: {
                ACTION: self.async_get_dampening,
                SCHEMA: SERVICE_DAMP_GET_SCHEMA,
                SUPPORTS_RESPONSE_KEY: SupportsResponse.ONLY,
            },
            SERVICE_GET_OPTIONS: {
                ACTION: self.async_get_options,
                SCHEMA: None,
                SUPPORTS_RESPONSE_KEY: SupportsResponse.ONLY,
            },
            SERVICE_QUERY_ESTIMATE_DATA: {
                ACTION: self.async_get_estimate_data,
                SCHEMA: SERVICE_QUERY_ESTIMATE_SCHEMA,
                SUPPORTS_RESPONSE_KEY: SupportsResponse.ONLY,
            },
            SERVICE_QUERY_FORECAST_DATA: {
                ACTION: self.async_get_forecast_data,
                SCHEMA: SERVICE_QUERY_SCHEMA,
                SUPPORTS_RESPONSE_KEY: SupportsResponse.ONLY,
            },
            SERVICE_REMOVE_HARD_LIMIT: {ACTION: self.async_remove_hard_limit},
            SERVICE_SET_DAMPENING: {ACTION: self.async_set_dampening, SCHEMA: SERVICE_DAMP_SCHEMA},
            SERVICE_SET_CUSTOM_HOURS: {ACTION: self.async_set_custom_hours, SCHEMA: SERVICE_CUSTOM_HOURS_SCHEMA},
            SERVICE_SET_HARD_LIMIT: {ACTION: self.async_set_hard_limit, SCHEMA: SERVICE_HARD_LIMIT_SCHEMA},
            SERVICE_SET_OPTIONS: {ACTION: self.async_set_options, SCHEMA: SERVICE_SET_OPTIONS_SCHEMA},
            SERVICE_UPDATE: {ACTION: self.async_update_forecast},
        }

    def _register(self) -> None:
        """Register all service actions with Home Assistant."""
        for action, call in self._get_service_actions().items():
            _LOGGER.debug("Register action %s.%s", DOMAIN, action)
            self._hass.services.async_remove(DOMAIN, action)  # Remove the error action
            if call.get(SUPPORTS_RESPONSE_KEY):
                self._hass.services.async_register(DOMAIN, action, call[ACTION], call[SCHEMA], call[SUPPORTS_RESPONSE_KEY])
                continue
            if call.get(SCHEMA):
                self._hass.services.async_register(DOMAIN, action, call[ACTION], call[SCHEMA])
                continue
            self._hass.services.async_register(DOMAIN, action, call[ACTION])

    async def async_update_forecast(self, call: ServiceCall) -> None:
        """Handle update forecast action.

        Arguments:
            call: Not used.

        """
        _LOGGER.info("Action: Fetching forecast")
        await self._coordinator.service_event_update()

    async def async_force_update_forecast(self, call: ServiceCall) -> None:
        """Handle force update forecast action.

        Arguments:
            call: Not used.

        """
        _LOGGER.info("Forced update: Fetching forecast")
        await self._coordinator.service_event_force_update()

    async def async_force_update_estimates(self, call: ServiceCall) -> None:
        """Handle force update estimated actuals action.

        Arguments:
            call: Not used.

        """
        _LOGGER.info("Forced update: Fetching estimated actuals")
        await self._coordinator.service_event_force_update_estimates()

    async def async_clear_solcast_data(self, call: ServiceCall) -> None:
        """Handle clear data action.

        Arguments:
            call: Not used.

        """
        _LOGGER.info("Action: Clearing history and fetching past actuals and forecast")
        await self._coordinator.service_event_delete_old_solcast_json_file()

    async def async_get_forecast_data(self, call: ServiceCall) -> dict[str, Any] | None:
        """Handle query forecast data action.

        Arguments:
            call: The data to act on: a start and optional end date/time, optional dampened/undampened, optional site.

        Returns:
            The Solcast data from start to end date/times.

        """
        try:
            _LOGGER.info("Action: Query forecast data")
            data = await self._coordinator.service_query_forecast_data(
                dt_util.as_utc(call.data.get(EVENT_START_DATETIME, dt_util.now())),
                dt_util.as_utc(call.data.get(EVENT_END_DATETIME, dt_util.now())),
                call.data.get(SITE, "all").replace("_", "-"),
                call.data.get(UNDAMPENED, False),
            )
        except ValueError as e:
            raise ServiceValidationError(f"{e}") from e

        return {"data": data}

    async def async_get_estimate_data(self, call: ServiceCall) -> dict[str, Any] | None:
        """Handle query estimate data action.

        Arguments:
            call: The data to act on: an optional start and end date/time (defaults to all of yesterday).

        Returns:
            The Solcast data from start to end date/times.

        """
        try:
            _LOGGER.info("Action: Query estimate data")
            day_start = self._coordinator.solcast.dt_helper.day_start_utc()
            data = await self._coordinator.service_query_estimate_data(
                dt_util.as_utc(call.data.get(EVENT_START_DATETIME, day_start - timedelta(days=1))),
                dt_util.as_utc(call.data.get(EVENT_END_DATETIME, day_start)),
                call.data.get(UNDAMPENED, True),
            )
        except ValueError as e:
            raise ServiceValidationError(f"{e}") from e

        return {"data": data}

    async def async_set_dampening(self, call: ServiceCall) -> None:
        """Handle set dampening action.

        Arguments:
            call: The data to act on: a set of dampening values, and an optional site.

        Raises:
            ServiceValidationError: Notify Home Assistant that an error has occurred, with translation.

        """
        _LOGGER.info("Action: Set dampening")

        if self._solcast.options.auto_dampen:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key=EXCEPTION_DAMP_AUTO_ENABLED)

        factors = call.data.get(DAMP_FACTOR, "")
        site = call.data.get(SITE)  # Optional site.

        factors = factors.strip().replace(" ", "")
        factors = factors.split(",")
        if factors[0] == "":
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key=EXCEPTION_DAMP_NO_FACTORS)
        if len(factors) not in (24, 48):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key=EXCEPTION_DAMP_COUNT_NOT_CORRECT)
        if site is not None:
            site = site.lower().replace("_", "-")
            if site == "all":
                if (len(factors)) != 48:
                    raise ServiceValidationError(translation_domain=DOMAIN, translation_key=EXCEPTION_DAMP_NO_ALL_24)
            elif site not in [s[RESOURCE_ID] for s in self._solcast.sites]:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key=EXCEPTION_DAMP_NOT_SITE)
        elif len(factors) == 48:
            site = "all"
        out_of_range = False
        try:
            for factor in factors:
                if float(factor) < 0 or float(factor) > 1:
                    out_of_range = True
        except:  # noqa: E722
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key=EXCEPTION_DAMP_ERROR_PARSING) from None
        if out_of_range:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key=EXCEPTION_DAMP_OUTSIDE_RANGE)

        opt = {**self._entry.options}

        if site is None:
            damp_factors: dict[str, float] = {}
            for i in range(24):
                factor = float(factors[i])
                damp_factors.update({f"{i}": factor})
                opt[f"damp{i:02}"] = factor
            self._solcast.damp = damp_factors
            if self._solcast.dampening.factors:
                _LOGGER.debug("Clear granular dampening")
                opt[SITE_DAMP] = False  # Clear "hidden" option.
                self._solcast.dampening.set_allow_granular_reset(True)
        else:
            await self._solcast.dampening.refresh_granular_data()  # Ensure latest file content gets updated
            self._solcast.dampening.factors[site] = [float(factors[i]) for i in range(len(factors))]
            await self._solcast.dampening.serialise_granular()
            old_damp = opt.get(SITE_DAMP, False)
            opt[SITE_DAMP] = True  # Set "hidden" option.
            if opt[SITE_DAMP] == old_damp:
                await self._solcast.dampening.apply_forward()
                await self._coordinator.solcast.build_forecast_data()
        self._coordinator.set_data_updated(True)
        await self._coordinator.update_integration_listeners()
        self._coordinator.set_data_updated(False)

        self._hass.config_entries.async_update_entry(self._entry, options=opt)

    async def async_get_options(self, call: ServiceCall) -> dict[str, Any]:
        """Handle get options action.

        Arguments:
            call: Not used.

        Returns:
            The current integration configuration options.

            The API key will be returned in the response unredacted, and this is intentional.
            Why anyone would want this returned is unclear, but if they do, they get it
            unredacted because all config options are treated equally by this action.

            API quota is returned as API limit.

        """
        _LOGGER.info("Action: Get options")
        opt = self._entry.options
        return {
            "data": {
                CONF_API_KEY: opt.get(CONF_API_KEY, ""),
                API_LIMIT: opt.get(API_LIMIT, ""),
                AUTO_UPDATE: opt.get(AUTO_UPDATE, 0),
                KEY_ESTIMATE: opt.get(KEY_ESTIMATE, "estimate"),
                CUSTOM_HOURS: opt.get(CUSTOM_HOURS, 24),
                HARD_LIMIT: opt.get(HARD_LIMIT_API, "100.0"),
                BRK_ESTIMATE: opt.get(BRK_ESTIMATE, True),
                BRK_ESTIMATE10: opt.get(BRK_ESTIMATE10, False),
                BRK_ESTIMATE90: opt.get(BRK_ESTIMATE90, False),
                BRK_SITE: opt.get(BRK_SITE, False),
                BRK_HALFHOURLY: opt.get(BRK_HALFHOURLY, False),
                BRK_HOURLY: opt.get(BRK_HOURLY, False),
                BRK_SITE_DETAILED: opt.get(BRK_SITE_DETAILED, False),
                GET_ACTUALS: opt.get(GET_ACTUALS, False),
                USE_ACTUALS: opt.get(USE_ACTUALS, 0),
                AUTO_DAMPEN: opt.get(AUTO_DAMPEN, False),
                GENERATION_ENTITIES: ",".join(opt.get(GENERATION_ENTITIES, [])),
                EXCLUDE_SITES: ",".join(opt.get(EXCLUDE_SITES, [])),
                SITE_EXPORT_ENTITY: opt.get(SITE_EXPORT_ENTITY, ""),
                SITE_EXPORT_LIMIT: opt.get(SITE_EXPORT_LIMIT, 0.0),
            }
        }

    async def async_diagnostic_self_test(self, call: ServiceCall) -> dict[str, Any]:
        """Handle diagnostic self-test action.

        Arguments:
            call: Not used.

        Returns:
            A structured health report covering API, sites, data cache,
            configuration, dampening, generation entities, and export entity.

        """
        _LOGGER.info("Action: Diagnostic self-test")

        solcast = self._solcast
        issues: list[str] = []

        # API status.
        api_keys_count = len(solcast.options.api_key.split(","))
        api_used = solcast.api_used_count
        api_limit_val = solcast.api_limit
        api_remaining = max(api_limit_val - api_used, 0)
        if api_remaining == 0:
            issues.append("API quota exhausted for today")

        last_updated = solcast.last_updated
        last_attempt = solcast.last_attempt

        api_status = {
            "api_keys_configured": api_keys_count,
            "api_used": api_used,
            "api_limit": api_limit_val,
            "api_remaining": api_remaining,
            "last_updated": str(last_updated) if last_updated else "never",
            "last_attempt": str(last_attempt) if last_attempt else "never",
            "failures_last_24h": solcast.failures_last_24h,
            "failures_last_7d": solcast.failures_last_7d,
            "status": solcast.status.name,
            "sites_status": solcast.sites_status.name,
        }

        if solcast.failures_last_24h > 0:
            issues.append(f"{solcast.failures_last_24h} API failure(s) in the last 24 hours")

        # Sites.
        sites_info: list[dict[str, Any]] = []
        for site in solcast.sites:
            sites_info.append(  # noqa: PERF401
                {
                    "resource_id": site.get(RESOURCE_ID, "unknown"),
                    "name": site.get("name", ""),
                }
            )
        if not solcast.sites:
            issues.append("No sites configured")

        # Data cache files.
        cache_files: dict[str, bool] = {}
        for label, filepath in (
            ("forecast", solcast.filename),
            ("undampened", solcast.filename_undampened),
            ("actuals", solcast.filename_actuals),
            ("actuals_dampened", solcast.filename_actuals_dampened),
            ("dampening", solcast.filename_dampening),
            ("dampening_history", solcast.filename_dampening_history),
            ("generation", solcast.filename_generation),
            ("advanced", solcast.filename_advanced),
        ):
            cache_files[label] = Path(filepath).exists()

        if not cache_files.get("forecast", False):
            issues.append("Forecast cache file missing")

        # Configuration summary.
        opts = solcast.options
        config_summary = {
            "auto_update": opts.auto_update.name if isinstance(opts.auto_update, Enum) else str(opts.auto_update),
            "key_estimate": opts.key_estimate,
            "get_actuals": opts.get_actuals,
            "use_actuals": opts.use_actuals.name if isinstance(opts.use_actuals, Enum) else str(opts.use_actuals),
            "auto_dampen": opts.auto_dampen,
            "hard_limit": opts.hard_limit,
            "excluded_sites": list(opts.exclude_sites),
        }

        # Dampening status.
        dampening_status: dict[str, Any] = {
            "enabled": solcast.dampening_enabled,
            "auto_dampening": opts.auto_dampen,
            "has_granular_factors": bool(solcast.dampening.factors),
            "dampening_file_exists": cache_files.get("dampening", False),
        }

        # Generation entities validation (if auto-dampening is enabled).
        generation_entity_checks: list[dict[str, Any]] = []
        if opts.auto_dampen and opts.generation_entities:
            entity_registry = er.async_get(self._hass)
            for entity_id in opts.generation_entities:
                check: dict[str, Any] = {"entity_id": entity_id}
                r_entity = entity_registry.async_get(entity_id)
                if r_entity is None:
                    check["status"] = "not_found"
                    issues.append(f"Generation entity {entity_id} not found in registry")
                elif r_entity.disabled_by is not None:
                    check["status"] = "disabled"
                    issues.append(f"Generation entity {entity_id} is disabled")
                else:
                    state = self._hass.states.get(entity_id)
                    if state is None or state.state in ("unavailable", "unknown"):
                        check["status"] = "unavailable"
                        issues.append(f"Generation entity {entity_id} is unavailable")
                    else:
                        check["status"] = "ok"
                generation_entity_checks.append(check)
        elif opts.auto_dampen and not opts.generation_entities:
            issues.append("Auto-dampening enabled but no generation entities configured")

        # Export entity validation (if configured).
        export_entity_check: dict[str, Any] = {}
        if opts.site_export_entity:
            entity_id = opts.site_export_entity
            export_entity_check["entity_id"] = entity_id
            entity_registry = er.async_get(self._hass)
            r_entity = entity_registry.async_get(entity_id)
            if r_entity is None:
                export_entity_check["status"] = "not_found"
                issues.append(f"Export entity {entity_id} not found in registry")
            elif r_entity.disabled_by is not None:
                export_entity_check["status"] = "disabled"
                issues.append(f"Export entity {entity_id} is disabled")
            else:
                state = self._hass.states.get(entity_id)
                if state is None or state.state in ("unavailable", "unknown"):
                    export_entity_check["status"] = "unavailable"
                    issues.append(f"Export entity {entity_id} is unavailable")
                else:
                    export_entity_check["status"] = "ok"

        # Recorder availability.
        recorder_available = "recorder" in self._hass.config.components

        if not recorder_available and opts.auto_dampen:
            issues.append("Recorder not available but required for auto-dampening")

        return {
            "data": {
                "overall_status": "ok" if not issues else "issues_found",
                "issues": issues,
                "api": api_status,
                "sites": sites_info,
                "cache_files": cache_files,
                "configuration": config_summary,
                "dampening": dampening_status,
                "generation_entities": generation_entity_checks,
                "export_entity": export_entity_check,
                "recorder_available": recorder_available,
            }
        }

    async def async_get_dampening(self, call: ServiceCall) -> dict[str, Any] | None:
        """Handle get dampening action.

        Arguments:
            call: The data to act on: an optional site.

        Returns:
            The dampening data.

        """
        _LOGGER.info("Action: Get dampening")

        site = call.data.get(SITE)  # Optional site.
        if site is not None:
            site_underscores = "_" in site
            site = site.lower().replace("_", "-")
        else:
            site_underscores = False
        data = await self._solcast.dampening.get(site=site, site_underscores=site_underscores)
        return {"data": data}

    async def async_set_options(self, call: ServiceCall) -> None:  # noqa: C901
        """Handle set options action.

        Arguments:
            call: The data to act on: one or more option key/value pairs.

        Raises:
            ServiceValidationError: Notify that a validation error has occurred.

        """
        if not call.data:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key=EXCEPTION_SET_OPTIONS_EMPTY)

        _LOGGER.info("Action: Set options")

        opt = {**self._entry.options}

        # Validate and apply API key.
        if (api_key := call.data.get(CONF_API_KEY)) is not None:
            validated_key, api_count, error = validate_api_key_value(api_key)
            if error is not None:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key=error)
            opt[CONF_API_KEY] = validated_key
        else:
            api_count = len(opt[CONF_API_KEY].split(","))

        # Validate and apply API limit.
        if (api_limit := call.data.get(API_LIMIT)) is not None:
            validated_quota, error = validate_api_limit_value(api_limit, api_count)
            if error is not None:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key=error)
            opt[API_LIMIT] = validated_quota

        # Validate and apply auto update.
        if (auto_update := call.data.get(AUTO_UPDATE)) is not None:
            validated_auto_update, error = validate_auto_update_value(auto_update)
            if error is not None:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key=error)
            opt[AUTO_UPDATE] = validated_auto_update

        # Validate and apply key estimate.
        if (key_estimate := call.data.get(KEY_ESTIMATE)) is not None:
            validated_estimate, error = validate_key_estimate_value(key_estimate)
            if error is not None:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key=error)
            opt[KEY_ESTIMATE] = validated_estimate

        # Validate and apply custom hours.
        if (custom_hours := call.data.get(CUSTOM_HOURS)) is not None:
            hour_val, error = validate_custom_hours_value(custom_hours)
            if error is not None:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key=error)
            opt[CUSTOM_HOURS] = hour_val

        # Validate and apply hard limit.
        if (hard_limit := call.data.get(HARD_LIMIT)) is not None:
            validated_limit, error = validate_hard_limit_value(hard_limit, api_count)
            if error is not None:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key=error)
            opt[HARD_LIMIT_API] = validated_limit

        # Apply boolean breakdown options.
        for key in (BRK_ESTIMATE, BRK_ESTIMATE10, BRK_ESTIMATE90, BRK_SITE, BRK_HALFHOURLY, BRK_HOURLY, BRK_SITE_DETAILED):
            if (val := call.data.get(key)) is not None:
                opt[key] = val

        # Apply get actuals.
        if (get_actuals := call.data.get(GET_ACTUALS)) is not None:
            opt[GET_ACTUALS] = get_actuals

        # Validate and apply use actuals.
        if (use_actuals := call.data.get(USE_ACTUALS)) is not None:
            validated_use_actuals, error = validate_use_actuals_value(use_actuals)
            if error is not None:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key=error)
            opt[USE_ACTUALS] = validated_use_actuals

        # Apply auto dampen.
        if (auto_dampen := call.data.get(AUTO_DAMPEN)) is not None:
            opt[AUTO_DAMPEN] = auto_dampen

        # Apply generation entities (comma-separated string to list).
        if (gen_entities := call.data.get(GENERATION_ENTITIES)) is not None:
            opt[GENERATION_ENTITIES] = [e.strip() for e in gen_entities.split(",") if e.strip()]

        # Apply exclude sites (comma-separated string to list).
        if (exclude_sites := call.data.get(EXCLUDE_SITES)) is not None:
            opt[EXCLUDE_SITES] = [s.strip() for s in exclude_sites.split(",") if s.strip()]

        # Apply site export entity.
        if (site_export := call.data.get(SITE_EXPORT_ENTITY)) is not None:
            opt[SITE_EXPORT_ENTITY] = site_export.strip()

        # Validate and apply site export limit.
        if (export_limit_str := call.data.get(SITE_EXPORT_LIMIT)) is not None:
            validated_limit, error = validate_export_limit_value(export_limit_str)
            if error is not None:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key=error)
            opt[SITE_EXPORT_LIMIT] = validated_limit

        # Cross-validate interdependent options.
        if opt.get(USE_ACTUALS, 0) != 0 and not opt.get(GET_ACTUALS, False):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key=EXCEPTION_ACTUALS_WITHOUT_GET)
        if opt.get(AUTO_DAMPEN, False) and not opt.get(GET_ACTUALS, False):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key=EXCEPTION_DAMPEN_WITHOUT_ACTUALS)
        if opt.get(AUTO_DAMPEN, False) and not opt.get(GENERATION_ENTITIES, []):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key=EXCEPTION_DAMPEN_WITHOUT_GENERATION)
        if opt.get(SITE_EXPORT_LIMIT, 0) > 0.0 and not opt.get(SITE_EXPORT_ENTITY, ""):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key=EXCEPTION_EXPORT_NO_ENTITY)

        # Sync legacy keys before updating the entry, to keep downgrade compatibility.
        sync_legacy_keys(opt)
        self._hass.config_entries.async_update_entry(self._entry, options=opt)

    async def async_set_hard_limit(self, call: ServiceCall) -> None:
        """Handle set hard limit action (deprecated).

        Arguments:
            call: The data to act on: a hard limit.

        Raises:
            ServiceValidationError: Notify Home Assistant that an error has occurred, with translation.

        """
        _LOGGER.warning("Action: Set hard limit (deprecated, use set_options instead)")
        self._raise_deprecation_issue(ISSUE_DEPRECATED_SET_HARD_LIMIT, SERVICE_SET_HARD_LIMIT)

        hard_limit = call.data.get(HARD_LIMIT, "100.0")
        validated, error = validate_hard_limit_value(hard_limit, len(self._entry.options[CONF_API_KEY].split(",")))
        if error is not None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key=error)

        opt = {**self._entry.options}
        opt[HARD_LIMIT_API] = validated
        self._hass.config_entries.async_update_entry(self._entry, options=opt)

    async def async_set_custom_hours(self, call: ServiceCall) -> None:
        """Handle set custom hours sensor action (deprecated).

        Arguments:
            call: The data to act on: a number of hours for the custom hour sensor.

        Raises:
            ServiceValidationError: Notify that a validation error has occurred.

        """
        _LOGGER.warning("Action: Set custom hours sensor (deprecated, use set_options instead)")
        self._raise_deprecation_issue(ISSUE_DEPRECATED_SET_CUSTOM_HOURS, SERVICE_SET_CUSTOM_HOURS)

        hours_str = call.data.get(HOURS, "")
        hour_val, error = validate_custom_hours_value(hours_str)
        if error is not None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key=error)

        opt = {**self._entry.options}
        opt[CUSTOM_HOURS] = hour_val
        sync_legacy_keys(opt)
        self._hass.config_entries.async_update_entry(self._entry, options=opt)

    async def async_remove_hard_limit(self, call: ServiceCall) -> None:
        """Handle remove hard limit action (deprecated).

        Arguments:
            call: Not used.

        """
        _LOGGER.warning("Action: Remove hard limit (deprecated, use set_options instead)")
        self._raise_deprecation_issue(ISSUE_DEPRECATED_REMOVE_HARD_LIMIT, SERVICE_REMOVE_HARD_LIMIT)

        opt = {**self._entry.options}
        opt[HARD_LIMIT_API] = "100.0"
        self._hass.config_entries.async_update_entry(self._entry, options=opt)

    def _raise_deprecation_issue(self, issue_id: str, action_name: str) -> None:
        """Raise an ignorable repair issue for a deprecated action.

        Arguments:
            issue_id: The unique issue identifier.
            action_name: The deprecated action name.

        """
        ir.async_create_issue(
            self._hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_ACTION_DEPRECATED,
            translation_placeholders={"deprecated_action": action_name, "new_action": SERVICE_SET_OPTIONS},
        )
