"""Solcast service actions."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
from enum import Enum
import logging
from pathlib import Path
from typing import Any, Final

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ConfigEntryAuthFailed, ServiceValidationError
from homeassistant.helpers import (
    config_validation as cv,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.util import dt as dt_util

from .const import (
    ACTION,
    ACTUALS_ATTEMPT,
    ACTUALS_UPDATED,
    API_FORCE_USED,
    API_KEYS_CONFIGURED,
    API_LIMIT,
    API_REMAINING,
    API_USED,
    AUTO_DAMPEN,
    AUTO_UPDATE,
    AUTO_UPDATED,
    BRK_ESTIMATE,
    BRK_ESTIMATE10,
    BRK_ESTIMATE90,
    BRK_HALFHOURLY,
    BRK_HOURLY,
    BRK_SITE,
    BRK_SITE_DETAILED,
    COMPLETION,
    CUSTOM_HOURS,
    DAMP_FACTOR,
    DOMAIN,
    EVENT_END_DATETIME,
    EVENT_START_DATETIME,
    EXCEPTION_ACTUALS_NOT_ENABLED,
    EXCEPTION_ACTUALS_WITHOUT_GET,
    EXCEPTION_AUTO_USE_FORCE,
    EXCEPTION_AUTO_USE_NORMAL,
    EXCEPTION_DAMP_AUTO_ENABLED,
    EXCEPTION_DAMP_COUNT_NOT_CORRECT,
    EXCEPTION_DAMP_ERROR_PARSING,
    EXCEPTION_DAMP_NO_ALL_24,
    EXCEPTION_DAMP_NO_FACTORS,
    EXCEPTION_DAMP_OUTSIDE_RANGE,
    EXCEPTION_DAMPEN_WITHOUT_ACTUALS,
    EXCEPTION_DAMPEN_WITHOUT_GENERATION,
    EXCEPTION_EXPORT_NO_ENTITY,
    EXCEPTION_INIT_KEY_INVALID,
    EXCEPTION_INTEGRATION_NOT_LOADED,
    EXCEPTION_INVALID_QUERY_RANGE,
    EXCEPTION_NOT_A_SITE,
    EXCEPTION_SET_OPTIONS_EMPTY,
    EXCLUDE_SITES,
    FAILURES_LAST_7D,
    FAILURES_LAST_24H,
    FORECASTS,
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
    LAST_ATTEMPT,
    LAST_UPDATED,
    NEED_HISTORY_HOURS,
    RESOURCE_ID,
    SCHEMA,
    SERVICE_CLEAR_DATA,
    SERVICE_DIAGNOSTIC,
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
    SITE_INFO,
    SITES_STATUS,
    STATUS,
    SUPPORTS_RESPONSE as SUPPORTS_RESPONSE_KEY,
    TASK_ACTUALS_FETCH,
    TASK_FORECASTS_FETCH,
    TASK_FORECASTS_FETCH_IMMEDIATE,
    UNDAMPENED,
    USAGE_STATUS,
    USE_ACTUALS,
)
from .coordinator import SolcastUpdateCoordinator
from .solcastapi import SolcastApi
from .updater import Updater
from .util import (
    AutoUpdate,
    UsageStatus,
    async_is_allow_exceed_api_limit,
    split_and_strip,
    sync_legacy_keys,
)
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

# Deprecated
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


_LOGGER = logging.getLogger(__name__)

_ALL_ACTIONS: Final = [
    SERVICE_CLEAR_DATA,
    SERVICE_DIAGNOSTIC,
    SERVICE_FORCE_UPDATE_ESTIMATES,
    SERVICE_FORCE_UPDATE_FORECASTS,
    SERVICE_GET_DAMPENING,
    SERVICE_GET_OPTIONS,
    SERVICE_QUERY_ESTIMATE_DATA,
    SERVICE_QUERY_FORECAST_DATA,
    SERVICE_SET_DAMPENING,
    SERVICE_SET_OPTIONS,
    SERVICE_UPDATE,
    # Deprecated...
    SERVICE_REMOVE_HARD_LIMIT,
    SERVICE_SET_CUSTOM_HOURS,
    SERVICE_SET_HARD_LIMIT,
]


class ServiceActions:
    """Service actions for the Solcast Solar integration."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: SolcastUpdateCoordinator,
        solcast: SolcastApi,
        updater: Updater,
    ) -> None:
        """Initialise the service actions.

        Arguments:
            hass: The Home Assistant instance.
            entry: The integration entry instance.
            coordinator: The update coordinator.
            solcast: The Solcast API instance.
            updater: The update helper owned by the coordinator.

        """
        self._hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self._solcast = solcast
        self._updater = updater
        self._register()

    async def async_update_forecast(self, call: ServiceCall | None = None, **kwargs: Any) -> None:
        """Handle update forecast action and internal forecast refresh requests."""
        if call is not None:
            _LOGGER.info("Action: Fetching forecast")

        if self._coordinator.tasks.get(TASK_FORECASTS_FETCH_IMMEDIATE) is None and self._solcast.tasks.get(TASK_FORECASTS_FETCH) is None:
            if self._solcast.reauth_required:
                raise ConfigEntryAuthFailed(
                    translation_domain=DOMAIN,
                    translation_key=EXCEPTION_INIT_KEY_INVALID,
                )

            if self._solcast.options.auto_update != AutoUpdate.NONE and "ignore_auto_enabled" not in kwargs:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key=EXCEPTION_AUTO_USE_FORCE,
                )

            update_kwargs: dict[str, Any] = {
                COMPLETION: kwargs.get(COMPLETION, "Completed task update"),
                NEED_HISTORY_HOURS: kwargs.get(NEED_HISTORY_HOURS, 0),
            }
            task = asyncio.create_task(self._updater.forecast_update(**update_kwargs))
            self._coordinator.tasks[TASK_FORECASTS_FETCH_IMMEDIATE] = task.cancel
            return

        _LOGGER.warning("Forecast update already in progress, ignoring action")

    async def async_force_update_forecast(self, call: ServiceCall) -> None:
        """Handle force update forecast action."""
        _LOGGER.info("Forced update: Fetching forecast")

        if self._coordinator.tasks.get(TASK_FORECASTS_FETCH_IMMEDIATE) is None and self._solcast.tasks.get(TASK_FORECASTS_FETCH) is None:
            if self._solcast.reauth_required:
                raise ConfigEntryAuthFailed(
                    translation_domain=DOMAIN,
                    translation_key=EXCEPTION_INIT_KEY_INVALID,
                )

            if self._solcast.options.auto_update == AutoUpdate.NONE:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key=EXCEPTION_AUTO_USE_NORMAL,
                )

            task = asyncio.create_task(self._updater.forecast_update(force=True, completion="Completed task force_update"))
            self._coordinator.tasks[TASK_FORECASTS_FETCH_IMMEDIATE] = task.cancel
            return

        _LOGGER.warning("Forecast update already in progress, ignoring action")

    async def async_force_update_estimates(self, call: ServiceCall) -> None:
        """Handle force update estimated actuals action."""
        _LOGGER.info("Forced update: Fetching estimated actuals")

        if not self._solcast.entry_options[GET_ACTUALS]:
            _LOGGER.debug("Estimated actuals not enabled, ignoring service action")
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key=EXCEPTION_ACTUALS_NOT_ENABLED)

        if self._coordinator.tasks.get(TASK_ACTUALS_FETCH) is None:
            task = asyncio.create_task(self._updater.update_estimated_actuals_history())
            self._coordinator.tasks[TASK_ACTUALS_FETCH] = task.cancel
            return

        _LOGGER.warning("Estimated actuals update already in progress, ignoring action")

    async def async_clear_solcast_data(self, call: ServiceCall) -> None:
        """Handle clear data action."""
        _LOGGER.info("Action: Clearing history and fetching past actuals and forecast")

        await self._solcast.tasks_cancel()
        await self._coordinator.tasks_cancel_specific(TASK_FORECASTS_FETCH_IMMEDIATE)
        await self._hass.async_block_till_done()
        await self._solcast.sites_cache.delete_solcast_file()
        await self._coordinator.update_integration_listeners()

    def _get_service_actions(self) -> dict[str, dict[str, Any]]:
        """Return the mapping of service action names to their configuration.

        Returns:
            The service action definitions for registration.

        """
        return {
            SERVICE_CLEAR_DATA: {ACTION: self.async_clear_solcast_data},
            SERVICE_DIAGNOSTIC: {
                ACTION: self.async_diagnostic,
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
            SERVICE_SET_DAMPENING: {ACTION: self.async_set_dampening, SCHEMA: SERVICE_DAMP_SCHEMA},
            SERVICE_SET_OPTIONS: {ACTION: self.async_set_options, SCHEMA: SERVICE_SET_OPTIONS_SCHEMA},
            SERVICE_UPDATE: {ACTION: self.async_update_forecast},
            # Deprecated...
            SERVICE_REMOVE_HARD_LIMIT: {ACTION: self.async_remove_hard_limit},
            SERVICE_SET_CUSTOM_HOURS: {ACTION: self.async_set_custom_hours, SCHEMA: SERVICE_CUSTOM_HOURS_SCHEMA},
            SERVICE_SET_HARD_LIMIT: {ACTION: self.async_set_hard_limit, SCHEMA: SERVICE_HARD_LIMIT_SCHEMA},
        }

    def _register(self) -> None:
        """Register all service actions with Home Assistant."""
        for action, call in self._get_service_actions().items():
            _LOGGER.debug("Register action %s.%s", DOMAIN, action)
            self._hass.services.async_remove(DOMAIN, action)  # Remove the stub action
            if call.get(SUPPORTS_RESPONSE_KEY):
                self._hass.services.async_register(DOMAIN, action, call[ACTION], call[SCHEMA], call[SUPPORTS_RESPONSE_KEY])
                continue
            if call.get(SCHEMA):
                self._hass.services.async_register(DOMAIN, action, call[ACTION], call[SCHEMA])
                continue
            self._hass.services.async_register(DOMAIN, action, call[ACTION])

    async def async_get_forecast_data(self, call: ServiceCall) -> dict[str, Any] | None:
        """Handle query forecast data action.

        Arguments:
            call: The data to act on: a start and optional end date/time, optional dampened/undampened, optional site.

        Returns:
            The Solcast data from start to end date/times.

        """
        try:
            _LOGGER.info("Action: Query forecast data")
            site = call.data.get(SITE, "all").replace("_", "-")
            if site != "all" and site not in [s[RESOURCE_ID] for s in self._solcast.sites]:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key=EXCEPTION_NOT_A_SITE)
            data = await self._solcast.query.get_forecast_list(
                dt_util.as_utc(call.data.get(EVENT_START_DATETIME, dt_util.now())),
                dt_util.as_utc(call.data.get(EVENT_END_DATETIME, dt_util.now())),
                site,
                call.data.get(UNDAMPENED, False),
            )
        except ValueError as e:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=EXCEPTION_INVALID_QUERY_RANGE,
            ) from e

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
            day_start = self._solcast.dt_helper.day_start_utc()
            data = await self._solcast.query.get_estimate_list(
                dt_util.as_utc(call.data.get(EVENT_START_DATETIME, day_start - timedelta(days=1))),
                dt_util.as_utc(call.data.get(EVENT_END_DATETIME, day_start)),
                call.data.get(UNDAMPENED, True),
            )
        except ValueError as e:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=EXCEPTION_INVALID_QUERY_RANGE,
            ) from e

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
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key=EXCEPTION_NOT_A_SITE)
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
            self._solcast.dampening.factors[site] = [float(f) for f in factors]
            await self._solcast.dampening.serialise_granular()
            old_damp = opt.get(SITE_DAMP, False)
            opt[SITE_DAMP] = True  # Set "hidden" option.
            if opt[SITE_DAMP] == old_damp:
                await self._solcast.dampening.apply_forward()
                await self._coordinator.solcast.build_forecast_data()
        await self._coordinator.update_integration_listeners()

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

    async def async_diagnostic(self, call: ServiceCall) -> dict[str, Any]:
        """Handle diagnostic action.

        Arguments:
            call: Not used.

        Returns:
            A structured health report covering API, sites, data cache,
            configuration, dampening, generation entities, and export entity.

        """
        _LOGGER.info("Action: Diagnostic")

        return {"data": build_health_check_report(self._hass, self._coordinator, self._solcast)}

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

    def _apply_validated_option(
        self,
        call_data: dict[str, Any],
        opt: dict[str, Any],
        input_key: str,
        validator: Callable[[str], tuple[Any, str | None]],
        option_key: str | None = None,
    ) -> None:
        """Validate and apply a simple string-backed option if present."""
        if (value := call_data.get(input_key)) is None:
            return

        validated_value, error = validator(value)
        if error is not None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key=error)

        opt[option_key or input_key] = validated_value

    def _apply_option(
        self,
        call_data: dict[str, Any],
        opt: dict[str, Any],
        input_key: str,
        option_key: str | None = None,
        transform: Callable[[Any], Any] | None = None,
    ) -> None:
        """Apply an option directly or via a simple transform if present."""
        if (value := call_data.get(input_key)) is None:
            return

        opt[option_key or input_key] = transform(value) if transform is not None else value

    async def _async_apply_api_related_options(self, call_data: dict[str, Any], opt: dict[str, Any]) -> None:
        """Validate and apply options that depend on API key count."""
        if (api_key := call_data.get(CONF_API_KEY)) is not None:
            validated_key, api_count, error = validate_api_key_value(api_key)
            if error is not None:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key=error)
            opt[CONF_API_KEY] = validated_key
        else:
            api_count = len(opt[CONF_API_KEY].split(","))

        if (api_limit := call_data.get(API_LIMIT)) is not None:
            allow_exceed = await async_is_allow_exceed_api_limit(self._hass)
            validated_quota, error = validate_api_limit_value(api_limit, api_count, allow_exceed=allow_exceed)
            if error is not None:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key=error)
            opt[API_LIMIT] = validated_quota

        if (hard_limit := call_data.get(HARD_LIMIT)) is not None:
            validated_limit, error = validate_hard_limit_value(hard_limit, api_count)
            if error is not None:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key=error)
            opt[HARD_LIMIT_API] = validated_limit

    async def async_set_options(self, call: ServiceCall) -> None:
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
        await self._async_apply_api_related_options(call.data, opt)

        # Apply validated options.
        for input_key, validator, option_key in (
            (AUTO_UPDATE, validate_auto_update_value, None),
            (KEY_ESTIMATE, validate_key_estimate_value, None),
            (CUSTOM_HOURS, validate_custom_hours_value, None),
            (USE_ACTUALS, validate_use_actuals_value, None),
            (SITE_EXPORT_LIMIT, validate_export_limit_value, None),
        ):
            self._apply_validated_option(call.data, opt, input_key, validator, option_key)

        # Apply boolean options.
        for key in (
            AUTO_DAMPEN,
            BRK_ESTIMATE,
            BRK_ESTIMATE10,
            BRK_ESTIMATE90,
            BRK_HALFHOURLY,
            BRK_HOURLY,
            BRK_SITE,
            BRK_SITE_DETAILED,
            GET_ACTUALS,
        ):
            self._apply_option(call.data, opt, key)

        # Apply transformed list/string options.
        for input_key, transform in (
            (GENERATION_ENTITIES, split_and_strip),
            (EXCLUDE_SITES, split_and_strip),
            (SITE_EXPORT_ENTITY, str.strip),
        ):
            self._apply_option(call.data, opt, input_key, transform=transform)

        # Cross-validate interdependent options.
        if opt.get(USE_ACTUALS, 0) != 0 and not opt.get(GET_ACTUALS, False):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key=EXCEPTION_ACTUALS_WITHOUT_GET)
        if opt.get(AUTO_DAMPEN, False) and not opt.get(GET_ACTUALS, False):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key=EXCEPTION_DAMPEN_WITHOUT_ACTUALS)
        if opt.get(AUTO_DAMPEN, False) and not opt.get(GENERATION_ENTITIES, []):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key=EXCEPTION_DAMPEN_WITHOUT_GENERATION)
        if opt.get(SITE_EXPORT_LIMIT, 0) > 0.0 and not opt.get(SITE_EXPORT_ENTITY, ""):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key=EXCEPTION_EXPORT_NO_ENTITY)

        # Sync legacy keys before updating the entry to keep downgrade compatibility.
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


def _is_unset_timestamp(value: Any) -> bool:
    """Return whether a timestamp-like value has not been meaningfully set."""
    return not isinstance(value, datetime) or value.timestamp() == 0


def _format_timestamp(value: Any, timezone: Any) -> str | None:
    """Format a timestamp-like value if it is meaningfully set."""
    return value.astimezone(timezone).replace(microsecond=0).isoformat() if not _is_unset_timestamp(value) else None


def _evaluate_forecast_health(coordinator: SolcastUpdateCoordinator, solcast: SolcastApi, issues: list[str]) -> dict[str, Any]:
    """Evaluate forecast freshness using the same rules as runtime recovery."""
    raw_last_updated = solcast.data.get(LAST_UPDATED)
    raw_last_attempt = solcast.data.get(LAST_ATTEMPT)
    stale_start = solcast.sites_cache.stale_data
    interval_just_passed = coordinator.interval_just_passed
    expected_interval = interval_just_passed.astimezone(solcast.tz).isoformat() if interval_just_passed is not None else None
    auto_update_value = int(solcast.options.auto_update)
    auto_updated = int(solcast.data.get(AUTO_UPDATED, 0))
    missed_auto_update = False
    indeterminate = False

    if auto_update_value != AutoUpdate.NONE:
        if auto_updated == 99999 or auto_updated != coordinator.divisions:
            indeterminate = True
        elif (
            auto_updated > 0
            and interval_just_passed is not None
            and isinstance(raw_last_attempt, datetime)
            and raw_last_attempt < interval_just_passed
        ):
            missed_auto_update = True

    if _is_unset_timestamp(raw_last_updated):
        status = "missing"
        issues.append("Forecast data has not been fetched yet")
    elif stale_start:
        status = "stale"
        issues.append("Forecast data is stale")
    elif missed_auto_update:
        status = "missed_interval"
        issues.append("Forecast data missed the expected auto-update interval")
    elif indeterminate:
        status = "indeterminate"
    else:
        status = "fresh"

    return {
        "status": status,
        "stale_start": stale_start,
        "missed_auto_update": missed_auto_update,
        "expected_interval": expected_interval,
        "auto_update_divisions": coordinator.divisions,
        "last_updated": _format_timestamp(raw_last_updated, solcast.tz),
        "last_attempt": _format_timestamp(raw_last_attempt, solcast.tz),
    }


def _evaluate_actuals_health(solcast: SolcastApi, configured_site_ids: set[str], issues: list[str]) -> dict[str, Any]:
    """Evaluate whether actuals are enabled, present, and fresh enough to use."""
    if not solcast.options.get_actuals:
        return {
            "status": "disabled",
            "site_data_present": False,
            "configured_sites": sorted(configured_site_ids),
            "sites_with_data": [],
            "missing_sites": sorted(configured_site_ids),
            "last_updated": None,
            "last_attempt": None,
        }

    actuals_site_info = solcast.data_actuals.get(SITE_INFO, {})
    sites_with_data = sorted(site_id for site_id in configured_site_ids if actuals_site_info.get(site_id, {}).get(FORECASTS))
    missing_sites = sorted(configured_site_ids - set(sites_with_data))
    raw_last_updated = solcast.data_actuals.get(LAST_UPDATED)
    raw_last_attempt = solcast.data_actuals.get(LAST_ATTEMPT)
    stale_actuals = (
        isinstance(raw_last_updated, datetime)
        and not _is_unset_timestamp(raw_last_updated)
        and raw_last_updated < solcast.dt_helper.day_start_utc(future=-1)
    )

    if _is_unset_timestamp(raw_last_updated) or not sites_with_data:
        status = "missing"
        issues.append("Estimated actuals are enabled but no actuals data is available")
    elif stale_actuals:
        status = "stale"
        issues.append("Estimated actuals data is stale")
    else:
        status = "fresh"

    return {
        "status": status,
        "site_data_present": bool(sites_with_data),
        "configured_sites": sorted(configured_site_ids),
        "sites_with_data": sites_with_data,
        "missing_sites": missing_sites,
        "last_updated": _format_timestamp(raw_last_updated, solcast.tz),
        "last_attempt": _format_timestamp(raw_last_attempt, solcast.tz),
    }


def _evaluate_excluded_sites(configured_site_ids: set[str], excluded_sites: set[str], issues: list[str]) -> dict[str, Any]:
    """Evaluate whether excluded site IDs match configured sites."""
    unknown_sites = sorted(excluded_sites - configured_site_ids)
    if unknown_sites:
        issues.append(f"Excluded sites are not configured: {', '.join(unknown_sites)}")

    return {
        "configured": sorted(excluded_sites),
        "unknown_sites": unknown_sites,
        "all_valid": not unknown_sites,
    }


def _check_entity_status(
    hass: HomeAssistant,
    entity_id: str,
    entity_registry: er.EntityRegistry,
    entity_label: str,
    issues: list[str],
) -> dict[str, Any]:
    """Check entity registry and state, returning a status dict and appending any issues found."""
    check: dict[str, Any] = {"entity_id": entity_id}
    r_entity = entity_registry.async_get(entity_id)
    if r_entity is None:
        check["status"] = "not_found"
        issues.append(f"{entity_label} {entity_id} not found in registry")
    elif r_entity.disabled_by is not None:
        check["status"] = "disabled"
        issues.append(f"{entity_label} {entity_id} is disabled")
    else:
        state = hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown"):
            check["status"] = "unavailable"
            issues.append(f"{entity_label} {entity_id} is unavailable")
        else:
            check["status"] = "ok"
    return check


def build_health_check_report(hass: HomeAssistant, coordinator: SolcastUpdateCoordinator, solcast: SolcastApi) -> dict[str, Any]:
    """Build the structured Solcast health report used by diagnostics surfaces."""
    issues: list[str] = []

    api_keys_count = len(split_and_strip(solcast.options.api_key))
    api_used = solcast.api_used_count
    api_limit_val = solcast.api_limit
    api_remaining = max(api_limit_val - api_used, 0)
    if api_remaining == 0:
        issues.append("API quota exhausted for today")

    last_updated = solcast.last_updated
    last_attempt = solcast.last_attempt
    actuals_updated = solcast.data_actuals.get(LAST_UPDATED)
    actuals_attempt = solcast.data_actuals.get(LAST_ATTEMPT)

    api_status = {
        API_KEYS_CONFIGURED: api_keys_count,
        API_USED: api_used,
        API_LIMIT: api_limit_val,
        API_REMAINING: api_remaining,
        API_FORCE_USED: solcast.successes_forced_24h,
        LAST_UPDATED: str(last_updated.astimezone(solcast.tz)) if last_updated else "never",
        LAST_ATTEMPT: str(last_attempt.astimezone(solcast.tz)) if last_attempt else "never",
        ACTUALS_UPDATED: str(actuals_updated.astimezone(solcast.tz)) if actuals_updated else "never",
        ACTUALS_ATTEMPT: str(actuals_attempt.astimezone(solcast.tz)) if actuals_attempt else "never",
        FAILURES_LAST_24H: solcast.failures_last_24h,
        FAILURES_LAST_7D: solcast.failures_last_7d,
        STATUS: solcast.status.name,
        SITES_STATUS: solcast.sites_status.name,
        USAGE_STATUS: solcast.usage_status.name,
    }

    if solcast.failures_last_24h > 0:
        issues.append(f"{solcast.failures_last_24h} API failure(s) since midnight UTC")

    sites_info: list[dict[str, Any]] = []
    configured_site_ids: set[str] = set()
    for site in solcast.sites:
        configured_site_ids.add(site.get(RESOURCE_ID, "unknown"))
        sites_info.append(
            {
                "resource_id": site.get(RESOURCE_ID, "unknown"),
                "name": site.get("name", ""),
            }
        )
    if not solcast.sites:
        issues.append("No sites configured")

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

    dampening_status: dict[str, Any] = {
        "enabled": solcast.dampening_enabled,
        "auto_dampening": opts.auto_dampen,
        "has_granular_factors": bool(solcast.dampening.factors),
        "dampening_file_exists": cache_files.get("dampening", False),
    }

    usage_health = {
        "status": solcast.usage_status.name,
        "ok": solcast.usage_status == UsageStatus.OK,
    }

    forecast_health = _evaluate_forecast_health(coordinator, solcast, issues)
    actuals_health = _evaluate_actuals_health(solcast, configured_site_ids, issues)
    excluded_sites_health = _evaluate_excluded_sites(configured_site_ids, set(opts.exclude_sites), issues)

    generation_entity_checks: list[dict[str, Any]] = []
    if opts.auto_dampen and opts.generation_entities:
        entity_registry = er.async_get(hass)
        generation_entity_checks = [
            _check_entity_status(hass, entity_id, entity_registry, "Generation entity", issues) for entity_id in opts.generation_entities
        ]
    elif opts.auto_dampen and not opts.generation_entities:
        issues.append("Auto-dampening enabled but no generation entities configured")

    export_entity_check: dict[str, Any] = {}
    if opts.site_export_entity:
        entity_id = opts.site_export_entity
        entity_registry = er.async_get(hass)
        export_entity_check = _check_entity_status(hass, entity_id, entity_registry, "Export entity", issues)

    recorder_available = "recorder" in hass.config.components
    if not recorder_available and opts.auto_dampen:
        issues.append("Recorder not available but required for auto-dampening")

    return {
        "overall_status": "ok" if not issues else "issues_found",
        "issues": issues,
        "api": api_status,
        "sites": sites_info,
        "cache_files": cache_files,
        "configuration": config_summary,
        "dampening": dampening_status,
        "forecast_health": forecast_health,
        "actuals_health": actuals_health,
        "excluded_sites": excluded_sites_health,
        "usage_health": usage_health,
        "generation_entities": generation_entity_checks,
        "export_entity": export_entity_check,
        "recorder_available": recorder_available,
    }


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
