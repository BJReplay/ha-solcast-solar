"""Solcast PV forecast, initialisation."""

from collections.abc import Awaitable, Callable
import contextlib
from datetime import datetime as dt, timedelta
import json
import logging
from pathlib import Path
import random
from typing import Any, Final
import zoneinfo

import aiofiles
import voluptuous as vol

from homeassistant import loader
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
    ServiceValidationError,
)
from homeassistant.helpers import (
    aiohttp_client,
    config_validation as cv,
    entity_registry as er,
)
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import (
    ACTION,
    ADVANCED_USER_AGENT,
    API_KEY,
    API_QUOTA,
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
    CONFIG_DISCRETE_NAME,
    CONFIG_FOLDER_DISCRETE,
    CUSTOM_HOUR_SENSOR,
    DAILY_LIMIT,
    DAMP_FACTOR,
    DEFAULT_SOLCAST_HTTPS_URL,
    DELAYED_RESTART_ON_CRASH,
    DOMAIN,
    DT_DATE_FORMAT,
    ENTRY_OPTIONS,
    EVENT_END_DATETIME,
    EVENT_START_DATETIME,
    EXCEPTION_DAMP_AUTO_ENABLED,
    EXCEPTION_DAMP_COUNT_NOT_CORRECT,
    EXCEPTION_DAMP_ERROR_PARSING,
    EXCEPTION_DAMP_NO_ALL_24,
    EXCEPTION_DAMP_NO_FACTORS,
    EXCEPTION_DAMP_NOT_SITE,
    EXCEPTION_DAMP_OUTSIDE_RANGE,
    EXCEPTION_HARD_NOT_POSITIVE_NUMBER,
    EXCEPTION_HARD_TOO_MANY,
    EXCEPTION_INIT_CANNOT_GET_SITES,
    EXCEPTION_INIT_CANNOT_GET_SITES_CACHE_INVALID,
    EXCEPTION_INIT_KEY_INVALID,
    EXCEPTION_INIT_NO_SITES,
    EXCEPTION_INIT_UNKNOWN,
    EXCEPTION_INIT_USAGE_CORRUPT,
    EXCEPTION_INTEGRATION_NOT_LOADED,
    EXCEPTION_INTEGRATION_PRIOR_CRASH,
    EXCLUDE_SITES,
    GENERATION_ENTITIES,
    GET_ACTUALS,
    HARD_LIMIT,
    HARD_LIMIT_API,
    HEADERS_ACCEPT,
    HEADERS_USER_AGENT,
    KEY_ESTIMATE,
    LAST_ATTEMPT,
    OLD_API_KEY,
    OLD_HARD_LIMIT,
    PRESUMED_DEAD,
    PRIOR_CRASH_EXCEPTION,
    PRIOR_CRASH_PLACEHOLDERS,
    PRIOR_CRASH_TIME,
    PRIOR_CRASH_TRANSLATION_KEY,
    RESET_OLD_KEY,
    RESOURCE_ID,
    SCHEMA,
    SERVICE_CLEAR_DATA,
    SERVICE_FORCE_UPDATE_ESTIMATES,
    SERVICE_FORCE_UPDATE_FORECASTS,
    SERVICE_GET_DAMPENING,
    SERVICE_QUERY_ESTIMATE_DATA,
    SERVICE_QUERY_FORECAST_DATA,
    SERVICE_REMOVE_HARD_LIMIT,
    SERVICE_SET_DAMPENING,
    SERVICE_SET_HARD_LIMIT,
    SERVICE_UPDATE,
    SITE,
    SITE_DAMP,
    SITE_EXPORT_ENTITY,
    SITE_EXPORT_LIMIT,
    SOLCAST,
    SUPPORTS_RESPONSE,
    UNDAMPENED,
    UPGRADE_FUNCTION,
    USE_ACTUALS,
    VERSION,
)
from .coordinator import SolcastUpdateCoordinator
from .solcastapi import ConnectionOptions, SolcastApi
from .util import (
    AutoUpdate,
    HistoryType,
    SitesStatus,
    SolcastData,
    UsageStatus,
    raise_and_record,
)

PLATFORMS: Final = [
    Platform.SELECT,
    Platform.SENSOR,
]
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

_LOGGER = logging.getLogger(__name__)


def __log_init_message(entry: ConfigEntry, version: str, solcast: SolcastApi) -> None:
    _LOGGER.debug("UTC times are converted to %s", solcast.options.tz)
    _LOGGER.debug("Successful init")
    _LOGGER.info("Solcast integration version %s", version)


async def get_version(hass: HomeAssistant) -> str:
    """Get the version of the integration."""
    return str((await loader.async_get_integration(hass, DOMAIN)).version)


def __setup_storage(hass: HomeAssistant) -> None:
    if not hass.data.get(DOMAIN):
        hass.data[DOMAIN] = {}


async def __get_time_zone(hass: HomeAssistant) -> zoneinfo.ZoneInfo:
    tz = await dt_util.async_get_time_zone(hass.config.time_zone)
    return tz if tz is not None else zoneinfo.ZoneInfo("UTC")


async def __get_options(hass: HomeAssistant, entry: ConfigEntry) -> ConnectionOptions:
    __log_entry_options(entry)

    try:
        # If something goes wrong with the damp factors then create a default list of no dampening
        dampening_option = {str(a): entry.options[f"damp{str(a).zfill(2)}"] for a in range(24)}
    except:  # noqa: E722
        _LOGGER.warning("Dampening factors corrupt or not found, setting to 1.0")
        new_options = {**entry.options}
        for a in range(24):
            new_options[f"damp{str(a).zfill(2)}"] = 1.0
        hass.config_entries.async_update_entry(entry, options=new_options)
        dampening_option = {str(a): 1.0 for a in range(24)}

    return ConnectionOptions(
        entry.options[CONF_API_KEY],
        entry.options.get(API_QUOTA, 10),
        DEFAULT_SOLCAST_HTTPS_URL,
        hass.config.path(
            f"{hass.config.config_dir}/{CONFIG_DISCRETE_NAME}/solcast.json"
            if CONFIG_FOLDER_DISCRETE
            else f"{hass.config.config_dir}/solcast.json"
        ),
        await __get_time_zone(hass),
        entry.options.get(AUTO_UPDATE, AutoUpdate.NONE),
        dampening_option,
        entry.options.get(CUSTOM_HOUR_SENSOR, 1),
        entry.options.get(KEY_ESTIMATE, "estimate"),
        entry.options.get(HARD_LIMIT_API, "100.0"),
        entry.options.get(BRK_ESTIMATE, True),
        entry.options.get(BRK_ESTIMATE10, True),
        entry.options.get(BRK_ESTIMATE90, True),
        entry.options.get(BRK_SITE, True),
        entry.options.get(BRK_HALFHOURLY, True),
        entry.options.get(BRK_HOURLY, True),
        entry.options.get(BRK_SITE_DETAILED, False),
        entry.options.get(EXCLUDE_SITES, []),
        entry.options.get(GET_ACTUALS, False),
        entry.options.get(USE_ACTUALS, HistoryType.FORECASTS),
        entry.options.get(GENERATION_ENTITIES, []),
        entry.options.get(SITE_EXPORT_ENTITY, ""),
        entry.options.get(SITE_EXPORT_LIMIT, 0.0),
        entry.options.get(AUTO_DAMPEN, False),
    )


def __log_entry_options(entry: ConfigEntry) -> None:
    display_options: dict[str, str] = {
        "Options actuals": "_actuals",
        "Options attributes": "attr_",
        "Options auto": "auto_",
        "Options custom": "custom",
        "Options estimate": "key_est",
        "Options exclude": "exclude_",
        "Options export": "export",
        "Options generation": "generation",
        "Options limit": "hard_",
        "Options schema": "VERSION",
        "Options update_max": "api_quota",
    }
    for display, isin in display_options.items():
        _LOGGER.debug(
            "%s: %s",
            display,
            {k: v for k, v in entry.options.items() if isin in k} if isin != "VERSION" else "v" + str(entry.version),
        )


def __log_hard_limit_set(solcast: SolcastApi) -> None:
    hard_limit_set, _ = solcast.hard_limit_set()
    if hard_limit_set:
        _LOGGER.info(
            "Hard limit is set to limit peak forecast values (%s)",
            ", ".join(f"{limit}kW" for limit in solcast.hard_limit.split(",")),
        )


def get_session_headers(solcast: SolcastApi, version: str) -> dict[str, str]:
    """Get the headers for the session based on the integration version."""
    raw_version = version.replace("v", "")
    headers = {
        HEADERS_ACCEPT: "application/json",
        HEADERS_USER_AGENT: ("ha-solcast-solar-integration/" + raw_version)
        if solcast.advanced_options[ADVANCED_USER_AGENT] == "default"
        else solcast.advanced_options[ADVANCED_USER_AGENT],
    }
    _LOGGER.debug("Session headers %s", headers)
    return headers


async def __get_granular_dampening(hass: HomeAssistant, entry: ConfigEntry, solcast: SolcastApi) -> None:
    opt = {**entry.options}
    # Set internal per-site dampening set flag. This is a hidden option until True.
    opt[SITE_DAMP] = await solcast.granular_dampening_data()
    hass.config_entries.async_update_entry(entry, options=opt)


def __need_history_hours(coordinator: SolcastUpdateCoordinator) -> int:
    need_history_hours: int = 0
    if coordinator.solcast.latest_period is not None and coordinator.solcast.latest_period < dt_util.now(dt_util.UTC):
        need_history_hours = min(int((dt_util.now(dt_util.UTC) - coordinator.solcast.latest_period).total_seconds() / 3600) + 1, 168)
        _LOGGER.debug("Need to fetch %s hours of history because very stale start", need_history_hours)
    return need_history_hours


async def __check_stale_start(coordinator: SolcastUpdateCoordinator) -> bool:
    """Check whether the integration has been failed for some time and then is restarted, and if so update forecast."""
    _LOGGER.debug("Checking for stale start")
    stale = False
    if coordinator.solcast.is_stale_data():
        _LOGGER.warning("The update automation has not been running, updating forecast")
        kwargs: dict[str, Any] = {
            "ignore_auto_enabled": True,
            "completion": "Completed task stale_update",
            "need_history_hours": __need_history_hours(coordinator),
        }
        await coordinator.service_event_update(**kwargs)
        stale = True
    else:
        _LOGGER.debug("Start is not stale")
    return stale


async def __check_auto_update_missed(coordinator: SolcastUpdateCoordinator) -> bool:
    """Check whether an auto-update has been missed, and if so update forecast."""
    stale = False
    if coordinator.solcast.options.auto_update != AutoUpdate.NONE:
        auto_updated = coordinator.solcast.get_data()[AUTO_UPDATED]
        if auto_updated == 99999 or auto_updated != coordinator.divisions:  # Cannot determine freshness
            _LOGGER.debug("Cannot determine freshness of auto-update forecast (last update forced, or configuration changed)")
            stale = False
        elif auto_updated > 0:
            _LOGGER.debug("Checking whether auto update forecast is stale")
            if (
                coordinator.interval_just_passed is not None
                and coordinator.solcast.get_data()[LAST_ATTEMPT] < coordinator.interval_just_passed
            ):
                _LOGGER.info(
                    "Last auto update forecast recorded (%s) is older than expected, should be (%s), updating forecast",
                    coordinator.solcast.get_data()[LAST_ATTEMPT].astimezone(coordinator.solcast.options.tz).strftime(DT_DATE_FORMAT),
                    coordinator.interval_just_passed.astimezone(coordinator.solcast.options.tz).strftime(DT_DATE_FORMAT),
                )
                kwargs: dict[str, Any] = {
                    "ignore_auto_enabled": True,
                    "completion": "Completed task update_missed",
                    "need_history_hours": __need_history_hours(coordinator),
                }
                await coordinator.service_event_update(**kwargs)
                stale = True
            else:
                _LOGGER.debug("Auto update forecast is fresh")
    return stale


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:  # noqa: C901
    """Set up the integration.

    * Get and sanitise options.
    * Instantiate the main class.
    * Load Solcast sites and API usage.
    * Load previously saved data.
    * Instantiate the coordinator.
    * Add unload hook on options change.
    * Trigger a forecast update after a 'stale' start.
    * Trigger a forecast update after a missed auto-update.
    * Replace stub service call actions with the real thing now config entry is available.

    Arguments:
        hass (HomeAssistant): The Home Assistant instance.
        entry (ConfigEntry): The integration entry instance, contains the options and other information.

    Raises:
        ConfigEntryAuthFailed: Instructs Home Assistant that the integration cannot be loaded due to authentication failure.
        ConfigEntryError: Instructs Home Assistant that the integration cannot be loaded when a load failure occurs.
        ConfigEntryNotReady: Instructs Home Assistant that the integration is not yet ready when a load failure occurs.

    Returns:
        bool: Whether setup has completed successfully.

    """

    random.seed()

    version = await get_version(hass)
    options = await __get_options(hass, entry)
    __setup_storage(hass)

    prior_crash = hass.data[DOMAIN].get(PRESUMED_DEAD, False)
    prior_crash_time: dt | None = hass.data[DOMAIN].get(PRIOR_CRASH_TIME)
    deny_startup: bool = prior_crash_time is not None
    if prior_crash:
        if not deny_startup:
            _LOGGER.debug("Prior crash detected, set the time of crash")
            hass.data[DOMAIN][PRIOR_CRASH_TIME] = dt_util.now(dt_util.UTC)  # Set the time of the crash.
        elif prior_crash_time < dt_util.now(dt_util.UTC) - timedelta(minutes=DELAYED_RESTART_ON_CRASH):
            _LOGGER.info("Prior crash was more than %d minutes ago, allowing sites to be reloaded", DELAYED_RESTART_ON_CRASH)
            hass.data[DOMAIN][PRIOR_CRASH_TIME] = dt_util.now(dt_util.UTC)
            prior_crash = False
    if prior_crash and deny_startup:
        _LOGGER.warning(
            "Prior crash detected (%s), skipping load for %d minutes to avoid repeated crashes - fix the issue and restart Home Assistant to retry sooner",
            dt.strftime(prior_crash_time, DT_DATE_FORMAT),
            DELAYED_RESTART_ON_CRASH,
        )
        if hass.data[DOMAIN].get(PRIOR_CRASH_EXCEPTION) is not None:
            _LOGGER.debug(
                "Raising prior exception: %s(%s)",
                hass.data[DOMAIN].get(PRIOR_CRASH_EXCEPTION),
                hass.data[DOMAIN].get(PRIOR_CRASH_TRANSLATION_KEY),
            )
            raise hass.data[DOMAIN][PRIOR_CRASH_EXCEPTION](  # Re-raise prior exception
                translation_domain=DOMAIN,
                translation_key=hass.data[DOMAIN].get(PRIOR_CRASH_TRANSLATION_KEY, EXCEPTION_INTEGRATION_PRIOR_CRASH),
                translation_placeholders=hass.data[DOMAIN].get(PRIOR_CRASH_PLACEHOLDERS),
            )

    hass.data[DOMAIN][PRESUMED_DEAD] = True  # Presumption that init will not be successful.
    solcast = SolcastApi(aiohttp_client.async_get_clientsession(hass), options, hass, entry)
    await solcast.read_advanced_options()

    solcast.headers = get_session_headers(solcast, version)
    await solcast.get_sites_and_usage(prior_crash=prior_crash)
    match solcast.sites_status:
        case SitesStatus.BAD_KEY:
            raise_and_record(hass, ConfigEntryAuthFailed, EXCEPTION_INIT_KEY_INVALID)
        case SitesStatus.API_BUSY:
            raise_and_record(hass, ConfigEntryNotReady, EXCEPTION_INIT_CANNOT_GET_SITES)
        case SitesStatus.ERROR:
            raise_and_record(hass, ConfigEntryError, EXCEPTION_INIT_CANNOT_GET_SITES)
        case SitesStatus.CACHE_INVALID:
            raise_and_record(hass, ConfigEntryError, EXCEPTION_INIT_CANNOT_GET_SITES_CACHE_INVALID)
        case SitesStatus.NO_SITES:
            raise_and_record(hass, ConfigEntryError, EXCEPTION_INIT_NO_SITES)
        case SitesStatus.UNKNOWN:
            raise_and_record(hass, ConfigEntryError, EXCEPTION_INIT_UNKNOWN)
        case SitesStatus.OK:
            pass
    match solcast.usage_status:
        case UsageStatus.ERROR:
            raise_and_record(hass, ConfigEntryError, EXCEPTION_INIT_USAGE_CORRUPT)
        case _:
            pass

    await __get_granular_dampening(hass, entry, solcast)
    hass.data[DOMAIN][SOLCAST] = solcast
    hass.data[DOMAIN][ENTRY_OPTIONS] = {**entry.options}

    if await solcast.load_saved_data():
        await solcast.model_automated_dampening()
        await solcast.apply_forward_dampening()
        await solcast.build_forecast_and_actuals(raise_exc=True)

    coordinator = SolcastUpdateCoordinator(hass, entry, solcast, version)
    entry.runtime_data = SolcastData(coordinator=coordinator)
    await coordinator.setup()
    await coordinator.async_config_entry_first_refresh()

    __log_init_message(entry, version, solcast)

    entry.async_on_unload(entry.add_update_listener(async_update_options))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    __log_hard_limit_set(solcast)

    _LOGGER.debug("Clear presumed dead flag")
    hass.data[DOMAIN][PRESUMED_DEAD] = False  # Initialisation was successful, so we're not dead.
    hass.data[DOMAIN].pop(PRIOR_CRASH_TIME, None)
    hass.data[DOMAIN].pop(PRIOR_CRASH_TRANSLATION_KEY, None)
    hass.data[DOMAIN].pop(PRIOR_CRASH_PLACEHOLDERS, None)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = True

    if not await __check_auto_update_missed(coordinator):
        await __check_stale_start(coordinator)

    async def action_call_update_forecast(call: ServiceCall) -> None:
        """Handle action.

        Arguments:
            call (ServiceCall): Not used.

        """
        _LOGGER.info("Action: Fetching forecast")
        await coordinator.service_event_update()

    async def action_call_force_update_forecast(call: ServiceCall) -> None:
        """Handle action.

        Arguments:
            call (ServiceCall): Not used.

        """
        _LOGGER.info("Forced update: Fetching forecast")
        await coordinator.service_event_force_update()

    async def action_call_force_update_estimates(call: ServiceCall) -> None:
        """Handle action.

        Arguments:
            call (ServiceCall): Not used.

        """
        _LOGGER.info("Forced update: Fetching estimated actuals")
        await coordinator.service_event_force_update_estimates()

    async def action_call_clear_solcast_data(call: ServiceCall) -> None:
        """Handle action.

        Arguments:
            call (ServiceCall): Not used.

        """
        _LOGGER.info("Action: Clearing history and fetching past actuals and forecast")
        await coordinator.service_event_delete_old_solcast_json_file()

    async def action_call_get_forecast_data(call: ServiceCall) -> dict[str, Any] | None:
        """Handle action.

        Arguments:
            call (ServiceCall): The data to act on: a start and optional end date/time (defaults to now), optional dampened/undampened, optional site.

        Returns:
            dict[str, Any] | None: The Solcast data from start to end date/times.

        """
        try:
            _LOGGER.info("Action: Query forecast data")
            data = await coordinator.service_query_forecast_data(
                dt_util.as_utc(call.data.get(EVENT_START_DATETIME, dt_util.now())),
                dt_util.as_utc(call.data.get(EVENT_END_DATETIME, dt_util.now())),
                call.data.get(SITE, "all").replace("_", "-"),
                call.data.get(UNDAMPENED, False),
            )
        except ValueError as e:
            raise ServiceValidationError(f"{e}") from e

        return {"data": data}

    async def action_call_get_estimate_data(call: ServiceCall) -> dict[str, Any] | None:
        """Handle action.

        Arguments:
            call (ServiceCall): The data to act on: an optional start and end date/time (defaults to all of of yesterday).

        Returns:
            dict[str, Any] | None: The Solcast data from start to end date/times.

        """
        try:
            _LOGGER.info("Action: Query estimate data")
            day_start = coordinator.solcast.get_day_start_utc()
            data = await coordinator.service_query_estimate_data(
                dt_util.as_utc(call.data.get(EVENT_START_DATETIME, day_start - timedelta(days=1))),
                dt_util.as_utc(call.data.get(EVENT_END_DATETIME, day_start)),
                call.data.get(UNDAMPENED, True),
            )
        except ValueError as e:
            raise ServiceValidationError(f"{e}") from e

        return {"data": data}

    async def action_call_set_dampening(call: ServiceCall) -> None:
        """Handle action.

        Arguments:
            call (ServiceCall): The data to act on: a set of dampening values, and an optional site.

        Raises:
            HomeAssistantError: Notify Home Assistant that an error has occurred.
            ServiceValidationError: Notify Home Assistant that an error has occurred, with translation.

        """
        _LOGGER.info("Action: Set dampening")

        if solcast.options.auto_dampen:
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
            elif site not in [s[RESOURCE_ID] for s in solcast.sites]:
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

        opt = {**entry.options}

        if site is None:
            damp_factors: dict[str, float] = {}
            for i in range(24):
                factor = float(factors[i])
                damp_factors.update({f"{i}": factor})
                opt[f"damp{i:02}"] = factor
            solcast.damp = damp_factors
            if solcast.granular_dampening:
                _LOGGER.debug("Clear granular dampening")
                opt[SITE_DAMP] = False  # Clear "hidden" option.
                solcast.set_allow_granular_dampening_reset(True)
        else:
            await solcast.refresh_granular_dampening_data()  # Ensure latest file content gets updated
            solcast.granular_dampening[site] = [float(factors[i]) for i in range(len(factors))]
            await solcast.serialise_granular_dampening()
            old_damp = opt.get(SITE_DAMP, False)
            opt[SITE_DAMP] = True  # Set "hidden" option.
            if opt[SITE_DAMP] == old_damp:
                await solcast.apply_forward_dampening()
                await coordinator.solcast.build_forecast_data()
        coordinator.set_data_updated(True)
        await coordinator.update_integration_listeners()
        coordinator.set_data_updated(False)

        hass.config_entries.async_update_entry(entry, options=opt)

    async def action_call_get_dampening(call: ServiceCall) -> dict[str, Any] | None:
        """Handle action.

        Arguments:
            call (ServiceCall): The data to act on: an optional site.

        Raises:
            HomeAssistantError: Notify Home Assistant that an error has occurred.

        """
        _LOGGER.info("Action: Get dampening")

        site = call.data.get(SITE)  # Optional site.
        if site is not None:
            site_underscores = "_" in site
            site = site.lower().replace("_", "-")
        else:
            site_underscores = False
        data = await solcast.get_dampening(site=site, site_underscores=site_underscores)
        return {"data": data}

    async def action_call_set_hard_limit(call: ServiceCall) -> None:
        """Handle action.

        Arguments:
            call (ServiceCall): The data to act on: a hard limit.

        Raises:
            HomeAssistantError: Notify Home Assistant that an error has occurred.
            ServiceValidationError: Notify Home Assistant that an error has occurred, with translation.

        """
        _LOGGER.info("Action: Set hard limit")

        hard_limit = call.data.get(HARD_LIMIT, "100.0")
        to_set: list[str] = []
        for limit in hard_limit.split(","):
            limit = limit.strip()
            if not limit.replace(".", "", 1).isdigit():
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key=EXCEPTION_HARD_NOT_POSITIVE_NUMBER,
                )
            to_set.append(f"{float(limit):.1f}")
        if len(to_set) > len(entry.options[API_KEY].split(",")):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key=EXCEPTION_HARD_TOO_MANY)

        opt = {**entry.options}
        opt[HARD_LIMIT_API] = ",".join(to_set)
        hass.config_entries.async_update_entry(entry, options=opt)

    async def action_call_remove_hard_limit(call: ServiceCall) -> None:
        """Handle action.

        Arguments:
            call (ServiceCall): Not used.

        Raises:
            HomeAssistantError: Notify Home Assistant that an error has occurred.

        """
        _LOGGER.info("Action: Remove hard limit")

        opt = {**entry.options}
        opt[HARD_LIMIT_API] = "100.0"
        hass.config_entries.async_update_entry(entry, options=opt)

    service_actions: dict[str, dict[str, Any]] = {
        SERVICE_CLEAR_DATA: {ACTION: action_call_clear_solcast_data},
        SERVICE_FORCE_UPDATE_ESTIMATES: {ACTION: action_call_force_update_estimates},
        SERVICE_FORCE_UPDATE_FORECASTS: {ACTION: action_call_force_update_forecast},
        SERVICE_GET_DAMPENING: {
            ACTION: action_call_get_dampening,
            SCHEMA: SERVICE_DAMP_GET_SCHEMA,
            SUPPORTS_RESPONSE: SupportsResponse.ONLY,
        },
        SERVICE_QUERY_ESTIMATE_DATA: {
            ACTION: action_call_get_estimate_data,
            SCHEMA: SERVICE_QUERY_ESTIMATE_SCHEMA,
            SUPPORTS_RESPONSE: SupportsResponse.ONLY,
        },
        SERVICE_QUERY_FORECAST_DATA: {
            ACTION: action_call_get_forecast_data,
            SCHEMA: SERVICE_QUERY_SCHEMA,
            SUPPORTS_RESPONSE: SupportsResponse.ONLY,
        },
        SERVICE_REMOVE_HARD_LIMIT: {ACTION: action_call_remove_hard_limit},
        SERVICE_SET_DAMPENING: {ACTION: action_call_set_dampening, SCHEMA: SERVICE_DAMP_SCHEMA},
        SERVICE_SET_HARD_LIMIT: {ACTION: action_call_set_hard_limit, SCHEMA: SERVICE_HARD_LIMIT_SCHEMA},
        SERVICE_UPDATE: {ACTION: action_call_update_forecast},
    }

    for action, call in service_actions.items():
        _LOGGER.debug("Register action %s.%s", DOMAIN, action)
        hass.services.async_remove(DOMAIN, action)  # Remove the error action
        if call.get(SUPPORTS_RESPONSE):
            hass.services.async_register(DOMAIN, action, call[ACTION], call[SCHEMA], call[SUPPORTS_RESPONSE])
            continue
        if call.get(SCHEMA):
            hass.services.async_register(DOMAIN, action, call[ACTION], call[SCHEMA])
            continue
        hass.services.async_register(DOMAIN, action, call[ACTION])

    return True


async def stub_action(call: ServiceCall) -> None:
    """Raise an exception on action when the entry is not loaded.

    Arguments:
        call (ServiceCall): Not used.

    Raises:
        HomeAssistantError: Notify the caller that the integration is not loaded.

    """
    _LOGGER.error("Integration not loaded")
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key=EXCEPTION_INTEGRATION_NOT_LOADED)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration.

    Sets up all actions to return an error state initially.

    Arguments:
        hass (HomeAssistant): The Home Assistant instance.
        config (ConfigType): The configuration dictionary.

    Returns:
        bool: Whether setup has completed successfully.

    """
    actions = [
        SERVICE_CLEAR_DATA,
        SERVICE_FORCE_UPDATE_ESTIMATES,
        SERVICE_FORCE_UPDATE_FORECASTS,
        SERVICE_GET_DAMPENING,
        SERVICE_QUERY_ESTIMATE_DATA,
        SERVICE_QUERY_FORECAST_DATA,
        SERVICE_REMOVE_HARD_LIMIT,
        SERVICE_SET_DAMPENING,
        SERVICE_SET_HARD_LIMIT,
        SERVICE_UPDATE,
    ]
    for action in actions:
        hass.services.async_register(DOMAIN, action, stub_action)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload config entry.

    This also removes the actions available and terminates running tasks.

    Arguments:
        hass (HomeAssistant): The Home Assistant instance.
        entry (ConfigEntry): The integration entry instance.

    Returns:
        bool: Whether the unload completed successfully.

    """
    # Terminate all tasks
    await tasks_cancel(hass, entry)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # Remove all actions
        for action in hass.services.async_services_for_domain(DOMAIN):
            _LOGGER.debug("Remove action %s.%s", DOMAIN, action)
            hass.services.async_remove(DOMAIN, action)
            hass.services.async_register(DOMAIN, action, stub_action)  # Switch to an error action

    return unload_ok


async def tasks_cancel(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Cancel all tasks, both coordinator and solcast.

    Returns:
        bool: Whether the tasks cancel completed successfully.

    """
    coordinator = entry.runtime_data.coordinator

    await coordinator.solcast.tasks_cancel()
    await coordinator.tasks_cancel()

    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:  # noqa: C901
    """Reconfigure the integration when options get updated.

    * Changing API key or limit, auto-update, hard limit or the custom hour sensor results in a restart.
    * Changing dampening results in forecast recalculation and sensor refresh.
    * Other alterations simply refresh sensor values and attributes.

    Arguments:
        hass (HomeAssistant): The Home Assistant instance.
        entry (ConfigEntry): The integration entry instance.

    """
    coordinator = entry.runtime_data.coordinator

    reload = False
    recalculate_and_refresh = False
    recalculate_splines = False

    def changed(config: str) -> bool:
        return hass.data[DOMAIN][ENTRY_OPTIONS].get(config) != entry.options.get(config)

    # Old API key tracking.
    if changed(CONF_API_KEY):
        if hass.data[DOMAIN].get(RESET_OLD_KEY):
            hass.data[DOMAIN].pop(RESET_OLD_KEY)
            hass.data[DOMAIN][OLD_API_KEY] = entry.options.get(CONF_API_KEY)
        else:
            hass.data[DOMAIN][OLD_API_KEY] = hass.data[DOMAIN][ENTRY_OPTIONS].get(CONF_API_KEY)

    # Multi-API key hard limit tracking and clean up.
    if hass.data[DOMAIN].get(OLD_HARD_LIMIT, coordinator.solcast.hard_limit) != entry.options[HARD_LIMIT_API]:
        old_multi_key = len(hass.data[DOMAIN].get(OLD_HARD_LIMIT, coordinator.solcast.hard_limit).split(",")) > 1
        new_multi_key = len(entry.options[HARD_LIMIT_API].split(",")) > 1
        if old_multi_key != new_multi_key:  # Changing from single to multi or vice versa
            entity_registry = er.async_get(hass)
            entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
            if old_multi_key:
                _LOGGER.debug("Hard limit changed from multi to single")
                clean_up = [f"hard_limit_{api_key[-6:]}" for api_key in entry.options[CONF_API_KEY].split(",")]
            else:
                _LOGGER.debug("Hard limit changed from single to multi")
                clean_up = [HARD_LIMIT]
            for entity in entities:
                if entity.unique_id in clean_up:
                    _LOGGER.warning("Cleaning up orphaned %s", entity.entity_id)
                    entity_registry.async_remove(entity.entity_id)
    hass.data[DOMAIN][OLD_HARD_LIMIT] = entry.options[HARD_LIMIT_API]

    # Config changes, which when changed will cause a reload.
    reload = (
        changed(CONF_API_KEY)
        or changed(API_QUOTA)
        or changed(AUTO_UPDATE)
        or changed(HARD_LIMIT_API)
        or changed(CUSTOM_HOUR_SENSOR)
        or changed(SITE_EXPORT_ENTITY)
    )

    # Config changes, which when changed will cause a forecast recalculation only, without reload.
    # Dampening must be the first check with the code as-is...
    if not reload:
        damp_changed = False
        damp_factors: dict[str, float] = {}
        for i in range(24):
            damp_factors.update({f"{i}": entry.options[f"damp{i:02}"]})
            if changed(f"damp{i:02}"):
                recalculate_and_refresh = True
                damp_changed = True
        if recalculate_and_refresh:
            coordinator.solcast.damp = damp_factors

        # Site exclusion changes.
        if changed(EXCLUDE_SITES):
            recalculate_and_refresh = True

        # Attribute changes, which will need a recalculation of splines.
        if not recalculate_and_refresh:
            recalculate_splines = (
                changed(BRK_ESTIMATE) or changed(BRK_ESTIMATE10) or changed(BRK_ESTIMATE90) or changed(BRK_SITE) or changed(KEY_ESTIMATE)
            )

        if changed(AUTO_DAMPEN):
            reload = True
            if hass.data[DOMAIN][ENTRY_OPTIONS].get(AUTO_DAMPEN, False):
                # Turning auto-dampening off, so reset the granular dampening file content.
                path = Path(coordinator.solcast.get_filename_dampening())
                _LOGGER.debug("Unlink %s", path)
                if path.exists():
                    path.unlink()

        if changed(SITE_DAMP):
            damp_changed = True
            if not entry.options[SITE_DAMP]:
                if coordinator.solcast.allow_granular_dampening_reset():
                    coordinator.solcast.granular_dampening = {}
                    path = Path(coordinator.solcast.get_filename_dampening())
                    if path.exists():
                        path.unlink()
            await coordinator.solcast.apply_forward_dampening()

        if damp_changed or changed(USE_ACTUALS):
            recalculate_and_refresh = True

    if reload:
        determination = "The integration will reload"
    elif recalculate_and_refresh:
        determination = "Recalculate forecasts and refresh sensors"
    else:
        determination = "Refresh sensors only" + (", with spline recalculate" if recalculate_splines else "")
    _LOGGER.debug("Options updated, action: %s", determination)
    if not reload:
        await coordinator.solcast.set_options(entry.options)
        if recalculate_and_refresh:
            await coordinator.solcast.build_forecast_data()
            if entry.options.get(GET_ACTUALS):
                await coordinator.solcast.build_actual_data()
        elif recalculate_splines:
            await coordinator.solcast.recalculate_splines()
        coordinator.set_data_updated(True)
        await coordinator.update_integration_listeners()
        coordinator.set_data_updated(False)

        hass.data[DOMAIN][ENTRY_OPTIONS] = {**entry.options}
        coordinator.solcast.entry_options = {**entry.options}
    else:
        # Reload.
        await tasks_cancel(hass, entry)
        await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Upgrade configuration.

    v4:  (ancient)  Remove option for auto-poll
    v5:  (4.0.8)    Dampening factor for each hour
    v6:  (4.0.15)   Add custom sensor for next X hours
    v7:  (4.0.16)   Selectable estimate value to use estimate, estimate10, estimate90
    v8:  (4.0.39)   Selectable attributes for sensors
    v9:  (4.1.3)    API limit (because Solcast removed an API call)
    v10:            Day 1..7 detailed breakdown by site, incorporated in v12 (development version)
    v11:            Auto-update as binaries (development version)
    v12: (4.1.8)    Auto-update as 0=off, 1=sunrise/sunset, 2=24-hour, plus add missing hard limit
    v13:            Unlucky for some, skipped
    v14: (4.2.4)    Hard limit adjustable by Solcast account
    v15: (4.3.3)    Exclude sites from core forecast
    v18: (4.4.0)    Auto-dampen

    An upgrade of the integration will sequentially upgrade options to the current
    version, with this function needing to consider all upgrade history and new defaults.

    An integration downgrade must not cause any issues when future options have been
    configured, with future options then just being unused. To be clear, the intent or
    characteristics of an option cannot change with an upgrade, so if an intent does change
    then a new option must be used (for example, HARD_LIMIT to HARD_LIMIT_API). Prior
    versions must cope with the absence of an option should one be deleted.

    The present version is specified in CONFIG_VERSION (`const.py`).

    Arguments:
        hass (HomeAssistant): The Home Assistant instance.
        entry (ConfigEntry): The integration entry instance, contains the options and other information.

    Returns:
        bool: Whether the config upgrade completed successfully.

    """

    with contextlib.suppress(Exception):
        _LOGGER.debug("Options version %s", entry.version)

    async def upgrade_to(
        version: int, entry: ConfigEntry, upgrade_function: Callable[[HomeAssistant, dict[str, Any]], Awaitable[None]]
    ) -> None:
        def upgraded() -> None:
            _LOGGER.info("Upgraded to options version %s", entry.version)

        if entry.version < version:
            if upgrade_function is not None:
                new_options = {**entry.options}
                await upgrade_function(hass, new_options)
                hass.config_entries.async_update_entry(entry, options=new_options, version=version)
                upgraded()

    async def __v4(hass: HomeAssistant, new_options: dict[str, Any]) -> None:
        with contextlib.suppress(Exception):
            new_options.pop("const_disableautopoll", None)

    async def __v5(hass: HomeAssistant, new_options: dict[str, Any]) -> None:
        for a in range(24):
            new_options[f"damp{str(a).zfill(2)}"] = 1.0

    async def __v6(hass: HomeAssistant, new_options: dict[str, Any]) -> None:
        new_options[CUSTOM_HOUR_SENSOR] = 1

    async def __v7(hass: HomeAssistant, new_options: dict[str, Any]) -> None:
        new_options[KEY_ESTIMATE] = "estimate"

    async def __v8(hass: HomeAssistant, new_options: dict[str, Any]):
        new_options[BRK_ESTIMATE] = True
        new_options[BRK_ESTIMATE10] = True
        new_options[BRK_ESTIMATE90] = True
        new_options[BRK_SITE] = True
        new_options[BRK_HALFHOURLY] = True
        new_options[BRK_HOURLY] = True

    async def __v9(hass: HomeAssistant, new_options: dict[str, Any]) -> None:
        try:
            default_list: list[str] = []
            config_dir = f"{hass.config.config_dir}/{CONFIG_DISCRETE_NAME}" if CONFIG_FOLDER_DISCRETE else hass.config.config_dir
            for api_key in new_options[CONF_API_KEY].split(","):
                api_cache_filename = (
                    f"{config_dir}/solcast-usage{'' if len(new_options[CONF_API_KEY].split(',')) < 2 else '-' + api_key.strip()}.json"
                )
                async with aiofiles.open(api_cache_filename) as f:
                    usage = json.loads(await f.read())
                default_list.append(str(usage[DAILY_LIMIT]))
            default = ",".join(default_list)
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning(
                "Could not load API usage cached limit while upgrading config, using default of ten: %s",
                e,
            )
            default = "10"
        new_options[API_QUOTA] = default

    async def __v12(hass: HomeAssistant, new_options: dict[str, Any]) -> None:
        new_options[AUTO_UPDATE] = int(new_options.get(AUTO_UPDATE, AutoUpdate.NONE))
        new_options[BRK_SITE_DETAILED] = False
        if new_options.get(HARD_LIMIT) is None:  # May already exist.
            new_options[HARD_LIMIT] = 100000

    async def __v14(hass: HomeAssistant, new_options: dict[str, Any]) -> None:
        hard_limit = new_options.get(HARD_LIMIT, 100000) / 1000
        new_options[HARD_LIMIT_API] = f"{hard_limit:.1f}"
        with contextlib.suppress(Exception):
            new_options.pop(HARD_LIMIT)

    async def __v15(hass: HomeAssistant, new_options: dict[str, Any]) -> None:
        new_options[EXCLUDE_SITES] = []

    async def __v18(hass: HomeAssistant, new_options: dict[str, Any]) -> None:
        new_options[GET_ACTUALS] = False
        new_options[USE_ACTUALS] = HistoryType.FORECASTS
        new_options[AUTO_DAMPEN] = False
        new_options[GENERATION_ENTITIES] = []
        new_options[SITE_EXPORT_ENTITY] = ""
        new_options[SITE_EXPORT_LIMIT] = 0.0

    upgrades: list[dict[str, Any]] = [
        {VERSION: 4, UPGRADE_FUNCTION: __v4},
        {VERSION: 5, UPGRADE_FUNCTION: __v5},
        {VERSION: 6, UPGRADE_FUNCTION: __v6},
        {VERSION: 7, UPGRADE_FUNCTION: __v7},
        {VERSION: 8, UPGRADE_FUNCTION: __v8},
        {VERSION: 9, UPGRADE_FUNCTION: __v9},
        {VERSION: 12, UPGRADE_FUNCTION: __v12},
        {VERSION: 14, UPGRADE_FUNCTION: __v14},
        {VERSION: 15, UPGRADE_FUNCTION: __v15},
        {VERSION: 18, UPGRADE_FUNCTION: __v18},
    ]
    for upgrade in upgrades:
        if entry.version < upgrade[VERSION]:
            await upgrade_to(upgrade[VERSION], entry, upgrade[UPGRADE_FUNCTION])

    return True
