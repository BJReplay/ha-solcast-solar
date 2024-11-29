"""Solcast PV forecast, initialisation."""

import asyncio
import contextlib
from datetime import timedelta
import json
import logging
import random
import traceback
from typing import Any, Final

import aiofiles  # type: ignore  # noqa: PGH003
import voluptuous as vol

from homeassistant import loader
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import (
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import aiohttp_client, config_validation as cv, intent
import homeassistant.helpers.device_registry as dr
from homeassistant.util import dt as dt_util

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
    CUSTOM_HOUR_SENSOR,
    DATE_FORMAT,
    DOMAIN,
    HARD_LIMIT,
    HARD_LIMIT_API,
    INIT_MSG,
    KEY_ESTIMATE,
    SERVICE_CLEAR_DATA,
    SERVICE_FORCE_UPDATE,
    SERVICE_GET_DAMPENING,
    SERVICE_QUERY_FORECAST_DATA,
    SERVICE_REMOVE_HARD_LIMIT,
    SERVICE_SET_DAMPENING,
    SERVICE_SET_HARD_LIMIT,
    SERVICE_UPDATE,
    SITE_DAMP,
    SOLCAST_URL,
)
from .coordinator import SolcastUpdateCoordinator
from .solcastapi import ConnectionOptions, SolcastApi

DAMP_FACTOR: Final = "damp_factor"
SITE: Final = "site"
UNDAMPENED: Final = "undampened"
EVENT_END_DATETIME: Final = "end_date_time"
EVENT_START_DATETIME: Final = "start_date_time"
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

_LOGGER = logging.getLogger(__name__)


def __log_init_message(version: str, solcast: SolcastApi):
    _LOGGER.debug("UTC times are converted to %s", solcast.options.tz)
    _LOGGER.debug("Successful init")
    _LOGGER.info(
        "%sSolcast integration version: %s%s%s",
        ("\n" + "-" * 67 + "\n") if not solcast.previously_loaded else "",
        version,
        ("\n\n" + INIT_MSG) if not solcast.previously_loaded else "",
        ("\n" + "-" * 67) if not solcast.previously_loaded else "",
    )


async def __get_version(hass: HomeAssistant) -> str:
    try:
        return str((await loader.async_get_integration(hass, DOMAIN)).version)
    except loader.IntegrationNotFound:
        return ""


def __setup_storage(hass: HomeAssistant):
    if not hass.data.get(DOMAIN):
        hass.data[DOMAIN] = {}


async def __get_time_zone(hass: HomeAssistant):
    # async_get_time_zone() mandated in HA core 2024.6.0
    try:
        dt_util.async_get_time_zone  # pylint: disable=W0104  # noqa: B018
        asynctz = True
    except:  # noqa: E722
        asynctz = False
    if asynctz:
        return await dt_util.async_get_time_zone(hass.config.time_zone)
    return dt_util.get_time_zone(hass.config.time_zone)


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
        SOLCAST_URL,
        hass.config.path(f"{hass.config.config_dir}/solcast.json"),
        await __get_time_zone(hass),
        entry.options.get(AUTO_UPDATE, 0),
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
    )


def __log_entry_options(entry: ConfigEntry):
    _LOGGER.debug(
        "Auto-update options: %s",
        {k: v for k, v in entry.options.items() if k.startswith("auto_")},
    )
    _LOGGER.debug(
        "Estimate to use options: %s",
        {k: v for k, v in entry.options.items() if k.startswith("key_est")},
    )
    _LOGGER.debug(
        "Attribute options: %s",
        {k: v for k, v in entry.options.items() if k.startswith("attr_")},
    )
    _LOGGER.debug(
        "Custom sensor options: %s",
        {k: v for k, v in entry.options.items() if k.startswith("custom")},
    )
    _LOGGER.debug(
        "Hard limit: %s",
        {k: v for k, v in entry.options.items() if k.startswith("hard_")},
    )


def __log_hard_limit_set(solcast: SolcastApi):
    if not solcast.previously_loaded:
        hard_limit_set, _ = solcast.hard_limit_set()
        if hard_limit_set:
            _LOGGER.info(
                "Hard limit is set to limit peak forecast values (%s)",
                ", ".join(f"{limit}kW" for limit in solcast.hard_limit.split(",")),
            )


def __get_session_headers(version: str):
    raw_version = version.replace("v", "")
    headers = {
        "Accept": "application/json",
        "User-Agent": "ha-solcast-solar-integration/" + raw_version[: raw_version.rfind(".")],
    }
    _LOGGER.debug("Session headers: %s", headers)
    return headers


async def __get_granular_dampening(hass: HomeAssistant, entry: ConfigEntry, solcast: SolcastApi):
    opt = {**entry.options}
    # Set internal per-site dampening set flag. This is a hidden option until True.
    opt[SITE_DAMP] = await solcast.granular_dampening_data()
    hass.config_entries.async_update_entry(entry, options=opt)
    hass.data[DOMAIN]["entry_options"] = entry.options


async def __check_stale_start(coordinator: SolcastUpdateCoordinator):
    """Check whether the integration has been failed for some time and then is restarted, and if so update forecast."""
    _LOGGER.debug("Checking for stale start")
    if coordinator.solcast.is_stale_data():
        try:
            if coordinator.solcast.options.auto_update == 0:
                _LOGGER.warning("The update automation has not been running, updating forecast")
                await coordinator.service_event_update(completion="Completed task stale_update")
            else:
                _LOGGER.warning("Many auto updates have been missed, updating forecast")
                await coordinator.service_event_update(ignore_auto_enabled=True, completion="Completed task stale_update")
        except Exception as e:  # noqa: BLE001
            _LOGGER.error(
                "Exception fetching data on stale start: %s: %s",
                e,
                traceback.format_exc(),
            )
            _LOGGER.warning("Continuing... ")
    else:
        _LOGGER.debug("Start is not stale")


async def __check_auto_update_missed(coordinator: SolcastUpdateCoordinator):
    """Check whether an auto-update has been missed, and if so update forecast."""
    if coordinator.solcast.options.auto_update > 0:
        if coordinator.solcast.get_data()["auto_updated"]:
            _LOGGER.debug("Checking whether auto update forecast is stale")
            try:
                if (
                    coordinator.interval_just_passed is not None
                    and coordinator.solcast.get_data()["auto_updated"]
                    and coordinator.solcast.get_data()["last_attempt"] < coordinator.interval_just_passed
                ):
                    _LOGGER.info(
                        "Last auto update forecast recorded (%s) is older than expected, should be (%s), updating forecast",
                        coordinator.solcast.get_data()["last_attempt"].astimezone(coordinator.solcast.options.tz).strftime(DATE_FORMAT),
                        coordinator.interval_just_passed.astimezone(coordinator.solcast.options.tz).strftime(DATE_FORMAT),
                    )
                    await coordinator.service_event_update(ignore_auto_enabled=True, completion="Completed task update_missed")
                else:
                    _LOGGER.debug("Auto update forecast is fresh")
            except TypeError:
                _LOGGER.warning("Auto update freshness could not be determined")
            except Exception as e:  # noqa: BLE001
                _LOGGER.error(
                    "Auto update freshness could not be determined: %s: %s",
                    e,
                    traceback.format_exc(),
                )


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
    * Set up service call actions.

    Arguments:
        hass (HomeAssistant): The Home Assistant instance.
        entry (ConfigEntry): The integration entry instance, contains the options and other information.

    Raises:
        ConfigEntryNotReady: Instructs Home Assistant that the integration is not yet ready when a load failure occurs.

    Returns:
        bool: Whether setup has completed successfully.

    """
    random.seed()

    version = await __get_version(hass)
    options = await __get_options(hass, entry)
    __setup_storage(hass)
    solcast = SolcastApi(aiohttp_client.async_get_clientsession(hass), options, hass, entry)
    solcast.headers = __get_session_headers(version)
    solcast.previously_loaded = hass.data[DOMAIN].get("has_loaded", False)

    try:
        await solcast.get_sites_and_usage()
    except Exception as e:
        raise ConfigEntryNotReady(f"Getting sites data failed: {e}") from e
    if not solcast.sites_loaded:
        raise ConfigEntryNotReady("Sites data could not be retrieved")

    __log_init_message(version, solcast)

    await __get_granular_dampening(hass, entry, solcast)
    status = await solcast.load_saved_data()
    if status != "":
        raise ConfigEntryNotReady(status)

    coordinator = SolcastUpdateCoordinator(hass, solcast, version)
    if not await coordinator.setup():
        raise ConfigEntryNotReady("Internal error: Coordinator setup failed")
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    __log_hard_limit_set(solcast)
    await __check_stale_start(coordinator)
    await __check_auto_update_missed(coordinator)
    hass.data[DOMAIN]["has_loaded"] = True

    # Testing of options migration. Used to validate the upgrade process when the options version changes.
    # await __test_options_migration(hass, entry)
    # __log_entry_options(entry)
    # pass  # <<< Set breakpoint here, then "step over" once.

    async def action_call_update_forecast(call: ServiceCall):
        """Handle action.

        Arguments:
            call (ServiceCall): Not used.

        """
        _LOGGER.info("Action: Fetching forecast")
        await coordinator.service_event_update()

    async def action_call_force_update_forecast(call: ServiceCall):
        """Handle action.

        Arguments:
            call (ServiceCall): Not used.

        """
        _LOGGER.info("Forced update: Fetching forecast")
        await coordinator.service_event_force_update()

    async def action_call_clear_solcast_data(call: ServiceCall):
        """Handle action.

        Arguments:
            call (ServiceCall): Not used.

        """
        _LOGGER.info("Action: Clearing history and fetching past actuals and forecast")
        await coordinator.service_event_delete_old_solcast_json_file()

    async def action_call_get_solcast_data(call: ServiceCall) -> dict[str, Any] | None:
        """Handle action.

        Arguments:
            call (ServiceCall): The data to act on: a start and optional end date/time (defaults to now), optional dampened/undampened, optional site.

        Raises:
            HomeAssistantError: Notify Home Assistant that an error has occurred.

        Returns:
            dict[str, Any] | None: The Solcast data from start to end date/times.

        """
        try:
            _LOGGER.info("Action: Query forecast data")
            data = await coordinator.service_query_forecast_data(
                dt_util.as_utc(call.data.get(EVENT_START_DATETIME, dt_util.now())),
                dt_util.as_utc(call.data.get(EVENT_END_DATETIME, dt_util.now())),
                call.data.get(SITE, "all"),
                call.data.get(UNDAMPENED, False),
            )
        except intent.IntentHandleError as e:
            raise HomeAssistantError(f"Error processing {SERVICE_QUERY_FORECAST_DATA}: {e}") from e

        if call.return_response:
            return {"data": data}

        return None

    async def action_call_set_dampening(call: ServiceCall):
        """Handle action.

        Arguments:
            call (ServiceCall): The data to act on: a set of dampening values, and an optional site.

        Raises:
            HomeAssistantError: Notify Home Assistant that an error has occurred.
            ServiceValidationError: Notify Home Assistant that an error has occurred, with translation.

        """
        try:
            _LOGGER.info("Action: Set dampening")

            factors = call.data.get(DAMP_FACTOR, None)
            site = call.data.get(SITE, None)  # Optional site.

            if factors is None:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key="damp_no_factors")
            factors = factors.strip().replace(" ", "")
            if len(factors.split(",")) == 0:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key="damp_no_factors")
            factors = factors.split(",")
            if len(factors) not in (24, 48):
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key="damp_count_not_correct")
            if site is not None:
                site = site.lower()
                if site == "all":
                    if (len(factors)) != 48:
                        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="damp_no_all_24")
                elif site not in [s["resource_id"] for s in solcast.sites]:
                    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="damp_not_site")
            elif len(factors) == 48:
                site = "all"
            out_of_range = False
            try:
                for factor in factors:
                    if float(factor) < 0 or float(factor) > 1:
                        out_of_range = True
            except:  # noqa: E722
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key="damp_error_parsing") from None
            if out_of_range:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key="damp_outside_range")

            opt = {**entry.options}

            if site is None:
                damp_factors = {}
                for i in range(24):
                    factor = float(factors[i])
                    damp_factors.update({f"{i}": factor})
                    opt[f"damp{i:02}"] = factor
                solcast.damp = damp_factors
                if solcast.granular_dampening:
                    _LOGGER.debug("Clear granular dampening")
                    opt[SITE_DAMP] = False  # Clear "hidden" option.
            else:
                await solcast.refresh_granular_dampening_data()  # Ensure latest file content gets updated
                solcast.granular_dampening[site] = [float(factors[i]) for i in range(len(factors))]
                await solcast.serialise_granular_dampening()
                old_damp = opt.get(SITE_DAMP, False)
                opt[SITE_DAMP] = True  # Set "hidden" option.
                if opt[SITE_DAMP] == old_damp:
                    await solcast.reapply_forward_dampening()
                    await coordinator.solcast.build_forecast_data()
                    coordinator.set_data_updated(True)
                    await coordinator.update_integration_listeners()
                    coordinator.set_data_updated(False)

            hass.config_entries.async_update_entry(entry, options=opt)
        except intent.IntentHandleError as e:
            raise HomeAssistantError(f"Error processing {SERVICE_SET_DAMPENING}: {e}") from e

    async def action_call_get_dampening(call: ServiceCall):
        """Handle action.

        Arguments:
            call (ServiceCall): The data to act on: an optional site.

        """
        try:
            _LOGGER.info("Action: Get dampening")

            data = await solcast.get_dampening(call.data.get(SITE, None))  # Optional site.
        except intent.IntentHandleError as e:
            raise HomeAssistantError(f"Error processing {SERVICE_GET_DAMPENING}: {e}") from e

        if call.return_response:
            return {"data": data}

        return None

    async def action_call_set_hard_limit(call: ServiceCall):
        """Handle action.

        Arguments:
            call (ServiceCall): The data to act on: a hard limit.

        Raises:
            HomeAssistantError: Notify Home Assistant that an error has occurred.
            ServiceValidationError: Notify Home Assistant that an error has occurred, with translation.

        """
        try:
            _LOGGER.info("Action: Set hard limit")

            hard_limit = call.data.get(HARD_LIMIT, "100.0")
            if hard_limit is None:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key="hard_empty")
            to_set = []
            for limit in hard_limit.split(","):
                limit = limit.strip()
                if not limit.replace(".", "", 1).isdigit():
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key="hard_not_positive_number",
                    )
                val = float(limit)
                if val < 0:  # If not a positive int print message and ask for input again.
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key="hard_not_positive_number",
                    )
                to_set.append(f"{val:.1f}")

            opt = {**entry.options}
            opt[HARD_LIMIT_API] = ",".join(to_set)
            hass.config_entries.async_update_entry(entry, options=opt)

        except ValueError as e:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="hard_not_positive_number") from e
        except intent.IntentHandleError as e:
            raise HomeAssistantError(f"Error processing {SERVICE_SET_HARD_LIMIT}: {e}") from e

    async def action_call_remove_hard_limit(call: ServiceCall):
        """Handle action.

        Arguments:
            call (ServiceCall): Not used.

        Raises:
            HomeAssistantError: Notify Home Assistant that an error has occurred.

        """
        try:
            _LOGGER.info("Action: Remove hard limit")

            opt = {**entry.options}
            opt[HARD_LIMIT_API] = "100.0"
            hass.config_entries.async_update_entry(entry, options=opt)

        except intent.IntentHandleError as e:
            raise HomeAssistantError(f"Error processing {SERVICE_REMOVE_HARD_LIMIT}: {e}") from e

    service_actions = {
        SERVICE_CLEAR_DATA: {"action": action_call_clear_solcast_data},
        SERVICE_FORCE_UPDATE: {"action": action_call_force_update_forecast},
        SERVICE_GET_DAMPENING: {
            "action": action_call_get_dampening,
            "schema": SERVICE_DAMP_GET_SCHEMA,
            "supports_response": SupportsResponse.ONLY,
        },
        SERVICE_QUERY_FORECAST_DATA: {
            "action": action_call_get_solcast_data,
            "schema": SERVICE_QUERY_SCHEMA,
            "supports_response": SupportsResponse.ONLY,
        },
        SERVICE_REMOVE_HARD_LIMIT: {"action": action_call_remove_hard_limit},
        SERVICE_SET_DAMPENING: {"action": action_call_set_dampening, "schema": SERVICE_DAMP_SCHEMA},
        SERVICE_SET_HARD_LIMIT: {"action": action_call_set_hard_limit, "schema": SERVICE_HARD_LIMIT_SCHEMA},
        SERVICE_UPDATE: {"action": action_call_update_forecast},
    }

    for action, call in service_actions.items():
        _LOGGER.debug("Register action: %s.%s", DOMAIN, action)
        if call.get("supports_response"):
            hass.services.async_register(DOMAIN, action, call["action"], call["schema"], call["supports_response"])
            continue
        if call.get("schema"):
            hass.services.async_register(DOMAIN, action, call["action"], call["schema"])
            continue
        hass.services.async_register(DOMAIN, action, call["action"])

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
    tasks_cancel_ok = await tasks_cancel(hass, entry)
    if not tasks_cancel_ok:
        _LOGGER.error("Tasks cancel failed")

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # Remove all actions
        for action in hass.services.async_services_for_domain(DOMAIN):
            _LOGGER.debug("Remove action: %s.%s", DOMAIN, action)
            hass.services.async_remove(DOMAIN, action)

        hass.data[DOMAIN].pop(entry.entry_id)
    else:
        _LOGGER.error("Unload failed")

    return unload_ok and tasks_cancel_ok


async def async_remove_config_entry_device(hass: HomeAssistant, entry: ConfigEntry, device) -> bool:
    """Remove a device.

    Arguments:
        hass (HomeAssistant): The Home Assistant instance.
        entry (ConfigEntry): Not used.
        device: The device instance.

    Returns:
        bool: Whether the removal completed successfully.

    """
    dr.async_get(hass).async_remove_device(device.id)
    return True


async def tasks_cancel(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Cancel all tasks.

    Returns:
        bool: Whether the tasks cancel completed successfully.

    """
    try:
        coordinator = hass.data[DOMAIN][entry.entry_id]
        # Terminate solcastapi tasks in progress
        for task, cancel in coordinator.solcast.tasks.items():
            _LOGGER.debug("Cancelling solcastapi task %s", task)
            cancel.cancel()
        # Terminate coordinator tasks in progress
        for task, cancel in coordinator.tasks.items():
            _LOGGER.debug("Cancelling coordinator task %s", task)
            if isinstance(cancel, asyncio.Task):
                cancel.cancel()
            else:
                cancel()
    except Exception as e:  # noqa: BLE001
        _LOGGER.error("Cancelling tasks failed: %s: %s", e, traceback.format_exc())
        return False
    finally:
        coordinator.solcast.tasks = {}
        coordinator.tasks = {}
    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry):
    """Reconfigure the integration when options get updated.

    * Changing API key or limit, auto-update or turning detailed site breakdown on results in a restart.
    * Changing dampening results in forecast recalculation.
    * Other alterations simply refresh sensor values and attributes.

    Arguments:
        hass (HomeAssistant): The Home Assistant instance.
        entry (ConfigEntry): The integration entry instance.

    """
    coordinator = hass.data[DOMAIN][entry.entry_id]

    try:
        reload = False
        recalculate_and_refresh = False
        recalculate_splines = False

        def changed(config):
            return hass.data[DOMAIN]["entry_options"].get(config) != entry.options.get(config)

        # Config changes, which when changed will cause a reload.
        if changed(CONF_API_KEY):
            hass.data[DOMAIN]["old_api_key"] = hass.data[DOMAIN]["entry_options"].get(CONF_API_KEY)
        reload = (
            changed(CONF_API_KEY) or changed(API_QUOTA) or changed(AUTO_UPDATE) or changed(HARD_LIMIT_API) or changed(CUSTOM_HOUR_SENSOR)
        )

        # Config changes, which when changed will cause a forecast recalculation only, without reload.
        # Dampening must be the first check with the code as-is...
        if not reload:
            damp_changed = False
            damp_factors = {}
            for i in range(24):
                damp_factors.update({f"{i}": entry.options[f"damp{i:02}"]})
                if changed(f"damp{i:02}"):
                    recalculate_and_refresh = True
                    damp_changed = True
                    break
            if recalculate_and_refresh:
                coordinator.solcast.damp = damp_factors

            # Attribute changes, which will need a recalculation of splines
            if not recalculate_and_refresh:
                recalculate_splines = (
                    changed(BRK_ESTIMATE)
                    or changed(BRK_ESTIMATE10)
                    or changed(BRK_ESTIMATE90)
                    or changed(BRK_SITE)
                    or changed(KEY_ESTIMATE)
                )

            if changed(SITE_DAMP):
                damp_changed = True
                if not entry.options[SITE_DAMP]:
                    if coordinator.solcast.allow_granular_dampening_reset():
                        coordinator.solcast.granular_dampening = {}
                        await coordinator.solcast.serialise_granular_dampening()
                        _LOGGER.debug("Granular dampening file reset")
                    else:
                        _LOGGER.debug("Granular dampening file not reset")
            if damp_changed:
                recalculate_and_refresh = True
                await coordinator.solcast.reapply_forward_dampening()

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
            elif recalculate_splines:
                await coordinator.solcast.recalculate_splines()
            coordinator.set_data_updated(True)
            await coordinator.update_integration_listeners()
            coordinator.set_data_updated(False)

            hass.data[DOMAIN]["entry_options"] = entry.options
            coordinator.solcast.entry_options = entry.options
        else:
            # Reload
            await tasks_cancel(hass, entry)
            await hass.config_entries.async_reload(entry.entry_id)
    except:  # noqa: E722
        _LOGGER.debug(traceback.format_exc())
        # Restart on exception
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

    An upgrade of the integration will sequentially upgrade options to the current
    version, with this function needing to consider all upgrade history and new defaults.

    An integration downgrade must not cause any issues when future options have been
    configured, with future options then just being unused. To be clear, the intent or
    characteristics of an option cannot change with an upgrade, so if an intent does change
    then an new option must be used (for example, HARD_LIMIT to HARD_LIMIT_API). Prior
    versions must cope with the absence of an option should one be deleted.

    The present version (e.g. `VERSION = 14`) is specified in `config_flow.py`.

    Arguments:
        hass (HomeAssistant): The Home Assistant instance.
        entry (ConfigEntry): The integration entry instance, contains the options and other information.

    Returns:
        bool: Whether the config upgrade completed successfully.

    """

    with contextlib.suppress(Exception):
        _LOGGER.debug("Options version %s", entry.version)

    async def upgrade_to(version, entry, upgrade_function):
        def upgraded():
            _LOGGER.info("Upgraded to options version %s", entry.version)

        if entry.version < version:
            new_options = {**entry.options}
            await upgrade_function(hass, new_options)
            try:
                hass.config_entries.async_update_entry(entry, options=new_options, version=version)
                upgraded()
            except Exception as e:
                if "unexpected keyword argument 'version'" in e:
                    entry.version = version
                    hass.config_entries.async_update_entry(entry, options=new_options)
                    upgraded()
                else:
                    raise

    if entry.version < 4:
        await upgrade_to(4, entry, __v4)
    if entry.version < 5:
        await upgrade_to(5, entry, __v5)
    if entry.version < 6:
        await upgrade_to(6, entry, __v6)
    if entry.version < 7:
        await upgrade_to(7, entry, __v7)
    if entry.version < 8:
        await upgrade_to(8, entry, __v8)
    if entry.version < 9:
        await upgrade_to(9, entry, __v9)
    if entry.version < 12:
        await upgrade_to(12, entry, __v12)
    if entry.version < 14:
        await upgrade_to(14, entry, __v14)

    return True


async def __v4(hass: HomeAssistant, new_options):
    with contextlib.suppress(Exception):
        new_options.pop("const_disableautopoll", None)


async def __v5(hass: HomeAssistant, new_options):
    for a in range(24):
        new_options[f"damp{str(a).zfill(2)}"] = 1.0


async def __v6(hass: HomeAssistant, new_options):
    new_options[CUSTOM_HOUR_SENSOR] = 1


async def __v7(hass: HomeAssistant, new_options):
    new_options[KEY_ESTIMATE] = "estimate"


async def __v8(hass: HomeAssistant, new_options):
    new_options[BRK_ESTIMATE] = True
    new_options[BRK_ESTIMATE10] = True
    new_options[BRK_ESTIMATE90] = True
    new_options[BRK_SITE] = True
    new_options[BRK_HALFHOURLY] = True
    new_options[BRK_HOURLY] = True


async def __v9(hass: HomeAssistant, new_options):
    try:
        default = []
        for api_key in new_options[CONF_API_KEY].split(","):
            api_cache_filename = f"{hass.config.config_dir}/solcast-usage{'' if len(new_options[CONF_API_KEY].split(',')) < 2 else '-' + api_key.strip()}.json"
            async with aiofiles.open(api_cache_filename) as f:
                usage = json.loads(await f.read())
            default.append(str(usage["daily_limit"]))
        default = ",".join(default)
    except Exception as e:  # noqa: BLE001
        _LOGGER.warning(
            "Could not load API usage cached limit while upgrading config, using default of ten: %s",
            e,
        )
        default = "10"
    new_options[API_QUOTA] = default


async def __v12(hass: HomeAssistant, new_options):
    new_options[AUTO_UPDATE] = int(new_options.get(AUTO_UPDATE, 0))
    new_options[BRK_SITE_DETAILED] = False
    if new_options.get(HARD_LIMIT) is None:  # May already exist.
        new_options[HARD_LIMIT] = 100000


async def __v14(hass: HomeAssistant, new_options):
    hard_limit = new_options.get(HARD_LIMIT, 100000) / 1000
    new_options[HARD_LIMIT_API] = f"{hard_limit:.1f}"
    with contextlib.suppress(Exception):
        new_options.pop(HARD_LIMIT)


async def __test_options_migration(hass: HomeAssistant, entry: ConfigEntry):
    """Test entry options upgrade.

    Doing this test will result in the integration repeatedlty restarting,
    upgrading the options from V4 onwards at every start. Do not do this
    outside of a dev environment with the ability to set a code breakboint
    after calling the function.

    Un-comment the call in async_setup_entry().
    """

    new_options = {**entry.options}
    # Not sure of version.
    if new_options.get(HARD_LIMIT):
        new_options.pop(HARD_LIMIT)
    # V5
    for a in range(24):
        f = f"damp{str(a).zfill(2)}"
        if new_options.get(f):
            new_options.pop(f)
    # V6
    if new_options.get(CUSTOM_HOUR_SENSOR):
        new_options.pop(CUSTOM_HOUR_SENSOR)
    # V7
    if new_options.get(KEY_ESTIMATE):
        new_options.pop(KEY_ESTIMATE)
    # V8
    if new_options.get(BRK_ESTIMATE):
        new_options.pop(BRK_ESTIMATE)
    if new_options.get(BRK_ESTIMATE10):
        new_options.pop(BRK_ESTIMATE10)
    if new_options.get(BRK_ESTIMATE90):
        new_options.pop(BRK_ESTIMATE90)
    if new_options.get(BRK_SITE):
        new_options.pop(BRK_SITE)
    if new_options.get(BRK_HALFHOURLY):
        new_options.pop(BRK_HALFHOURLY)
    if new_options.get(BRK_HOURLY):
        new_options.pop(BRK_HOURLY)
    # V9
    if new_options.get(API_QUOTA):
        new_options.pop(API_QUOTA)
    # V12
    if new_options.get(AUTO_UPDATE):
        new_options.pop(AUTO_UPDATE)
    if new_options.get(BRK_SITE_DETAILED):
        new_options.pop(BRK_SITE_DETAILED)
    # V14
    if new_options.get(HARD_LIMIT_API):
        new_options.pop(HARD_LIMIT_API)
    hass.config_entries.async_update_entry(entry, options=new_options, version=4)
    await async_migrate_entry(hass, entry)
