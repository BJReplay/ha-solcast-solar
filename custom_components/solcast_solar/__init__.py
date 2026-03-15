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

from homeassistant import loader
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)
from homeassistant.helpers import aiohttp_client, entity_registry as er
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .actions import ServiceActions, register_stub_actions, unregister_actions
from .const import (
    ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_CONFIGURATION,
    ADVANCED_USER_AGENT,
    API_LIMIT,
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
    CONFIG_VERSION,
    CUSTOM_HOURS,
    DAILY_LIMIT,
    DEFAULT_SOLCAST_HTTPS_URL,
    DELAYED_RESTART_ON_CRASH,
    DOMAIN,
    DT_DATE_FORMAT,
    ENTRY_OPTIONS,
    EXCEPTION_INIT_CANNOT_GET_SITES,
    EXCEPTION_INIT_CANNOT_GET_SITES_CACHE_INVALID,
    EXCEPTION_INIT_KEY_INVALID,
    EXCEPTION_INIT_NO_SITES,
    EXCEPTION_INIT_UNKNOWN,
    EXCEPTION_INIT_USAGE_CORRUPT,
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
    SITE_DAMP,
    SITE_EXPORT_ENTITY,
    SITE_EXPORT_LIMIT,
    SOLCAST,
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
    sync_actuals_api_limit_issue,
)

DAMPENING_ADAPTATIONS_DEVELOPMENT: Final = False  # For development, to force re-modelling of dampening adaptations at startup
ENTRY_OPTIONS_DEVELOPMENT: Final = False  # For development, to force a re-upgrade of options at startup

PLATFORMS: Final = [
    Platform.SELECT,
    Platform.SENSOR,
]

_LOGGER = logging.getLogger(__name__)


def __log_init_message(entry: ConfigEntry, version: str, solcast: SolcastApi) -> None:
    _LOGGER.debug("UTC times are converted to %s", solcast.options.tz)
    _LOGGER.debug("Successful init")
    _LOGGER.debug("Solcast integration version %s", version)


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
        entry.options.get(API_LIMIT, 10),
        DEFAULT_SOLCAST_HTTPS_URL,
        hass.config.path(
            f"{hass.config.config_dir}/{CONFIG_DISCRETE_NAME}/solcast.json"
            if CONFIG_FOLDER_DISCRETE
            else f"{hass.config.config_dir}/solcast.json"
        ),
        await __get_time_zone(hass),
        entry.options.get(AUTO_UPDATE, AutoUpdate.NONE),
        dampening_option,
        entry.options.get(CUSTOM_HOURS, 1),
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
        "Options custom": "custom_",
        "Options estimate": "key_est",
        "Options exclude": "exclude_",
        "Options export": "export",
        "Options generation": "generation",
        "Options limit": "hard_",
        "Options schema": "VERSION",
        "Options update_max": "api_limit",
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
    opt[SITE_DAMP] = await solcast.dampening.granular_data()
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
    if coordinator.solcast.sites_cache.stale_data:
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
        auto_updated = coordinator.solcast.data[AUTO_UPDATED]
        if auto_updated == 99999 or auto_updated != coordinator.divisions:  # Cannot determine freshness
            _LOGGER.debug("Cannot determine freshness of auto-update forecast (last update forced, or configuration changed)")
            stale = False
        elif auto_updated > 0:
            _LOGGER.debug("Checking whether auto update forecast is stale")
            if coordinator.interval_just_passed is not None and coordinator.solcast.data[LAST_ATTEMPT] < coordinator.interval_just_passed:
                _LOGGER.info(
                    "Last auto update forecast recorded (%s) is older than expected, should be (%s), updating forecast",
                    coordinator.solcast.data[LAST_ATTEMPT].astimezone(coordinator.solcast.options.tz).strftime(DT_DATE_FORMAT),
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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
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

    if ENTRY_OPTIONS_DEVELOPMENT:
        await async_migrate_entry(hass, entry)

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
    await solcast.async_migrate_config_files()
    await solcast.advanced_opt.read_advanced_options()

    solcast.headers = get_session_headers(solcast, version)
    solcast.integration_version = version
    await solcast.sites_cache.get_sites_and_usage(prior_crash=prior_crash)
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

    sync_actuals_api_limit_issue(hass, entry.options, solcast.sites)

    await __get_granular_dampening(hass, entry, solcast)
    hass.data[DOMAIN][SOLCAST] = solcast
    hass.data[DOMAIN][ENTRY_OPTIONS] = {**entry.options}

    if await solcast.sites_cache.load_saved_data():
        await solcast.dampening.model_automated()
        await solcast.dampening.apply_forward()
        await solcast.fetcher.build_forecast_and_actuals(raise_exc=True)

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

    ServiceActions(hass, entry, coordinator, solcast)

    if DAMPENING_ADAPTATIONS_DEVELOPMENT:
        if (
            coordinator.solcast.options.auto_dampen
            and coordinator.solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_CONFIGURATION]
        ):
            await coordinator.solcast.dampening.adaptive.update_history()
            await coordinator.solcast.dampening.adaptive.determine_best_settings()

    return True


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration.

    Sets up all actions to return an error state initially.

    Arguments:
        hass (HomeAssistant): The Home Assistant instance.
        config (ConfigType): The configuration dictionary.

    Returns:
        bool: Whether setup has completed successfully.

    """
    register_stub_actions(hass)
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
        unregister_actions(hass)

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
        or changed(API_LIMIT)
        or changed(AUTO_UPDATE)
        or changed(HARD_LIMIT_API)
        or changed(CUSTOM_HOURS)
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
                path = Path(coordinator.solcast.dampening.get_filename())
                _LOGGER.debug("Unlink %s", path)
                if path.exists():
                    path.unlink()

        if changed(SITE_DAMP):
            damp_changed = True
            if not entry.options[SITE_DAMP]:
                if coordinator.solcast.dampening.allow_granular_reset():
                    coordinator.solcast.dampening.factors = {}
                    path = Path(coordinator.solcast.dampening.get_filename())
                    if path.exists():
                        path.unlink()
            await coordinator.solcast.dampening.apply_forward()

        if damp_changed or changed(USE_ACTUALS):
            recalculate_and_refresh = True

    if reload:
        determination = "The integration will reload"
    elif recalculate_and_refresh:
        determination = "Recalculate forecasts and refresh sensors"
    else:
        determination = "Refresh sensors only" + (", with spline recalculate" if recalculate_splines else "")
    _LOGGER.debug("Options updated, action: %s", determination)
    sync_actuals_api_limit_issue(hass, entry.options, coordinator.solcast.sites)
    if not reload:
        await coordinator.solcast.set_options(entry.options)
        if recalculate_and_refresh:
            await coordinator.solcast.build_forecast_data()
            if entry.options.get(GET_ACTUALS):
                await coordinator.solcast.build_actual_data()
        elif recalculate_splines:
            await coordinator.solcast.query.recalculate_splines()
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
    v18: (4.4.0)    Auto-dampen, and add new options for export entity and generation entities
    v19: (4.5.1)    Rename some options for clarity

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
        new_options["customhoursensor"] = 1

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
        new_options["api_quota"] = default

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

    async def __v19(hass: HomeAssistant, new_options: dict[str, Any]) -> None:
        # Rename "api_quota" to "api_limit", and "customhoursensor" to "custom_hours".
        # Old keys are kept for backward compatibility, but no longer maintained.
        if "api_quota" in new_options:
            new_options[API_LIMIT] = new_options["api_quota"]
        if "customhoursensor" in new_options:
            new_options[CUSTOM_HOURS] = new_options["customhoursensor"]

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
        {VERSION: 19, UPGRADE_FUNCTION: __v19},
    ]
    for upgrade in upgrades:
        if (entry.version < upgrade[VERSION]) or (ENTRY_OPTIONS_DEVELOPMENT and upgrade[VERSION] == CONFIG_VERSION):
            await upgrade_to(upgrade[VERSION], entry, upgrade[UPGRADE_FUNCTION])

    return True
