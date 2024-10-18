"""Support for Solcast PV forecast, intialisation."""

# pylint: disable=C0304, C0321, E0401, E1135, W0613, W0702, W0718

import logging
import traceback
import random
import os
import json
from typing import Final, Dict, Any
import asyncio
import aiofiles # type: ignore

import voluptuous as vol # type: ignore
from homeassistant import loader # type: ignore
from homeassistant.config_entries import ConfigEntry # type: ignore
from homeassistant.const import CONF_API_KEY, Platform # type: ignore
from homeassistant.core import (HomeAssistant, # type: ignore
                                ServiceCall,
                                ServiceResponse,
                                SupportsResponse,)
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError, ServiceValidationError # type: ignore
from homeassistant.helpers import config_validation as cv # type: ignore
from homeassistant.helpers import aiohttp_client, intent # type: ignore
from homeassistant.helpers.device_registry import async_get as device_registry # type: ignore
from homeassistant.util import dt as dt_util # type: ignore

from .const import (
    API_QUOTA,
    AUTO_UPDATE,
    BRK_ESTIMATE,
    BRK_ESTIMATE10,
    BRK_ESTIMATE90,
    BRK_SITE,
    BRK_HALFHOURLY,
    BRK_HOURLY,
    BRK_SITE_DETAILED,
    CUSTOM_HOUR_SENSOR,
    DOMAIN,
    HARD_LIMIT,
    INIT_MSG,
    KEY_ESTIMATE,
    SERVICE_CLEAR_DATA,
    SERVICE_FORCE_UPDATE,
    SERVICE_GET_DAMPENING,
    SERVICE_QUERY_FORECAST_DATA,
    SERVICE_SET_DAMPENING,
    SERVICE_SET_HARD_LIMIT,
    SERVICE_REMOVE_HARD_LIMIT,
    SERVICE_UPDATE,
    SITE_DAMP,
    SOLCAST_URL,
)

from .coordinator import SolcastUpdateCoordinator
from .solcastapi import ConnectionOptions, SolcastApi

_LOGGER = logging.getLogger(__name__)

DAMP_FACTOR = "damp_factor"
SITE = "site"
UNDAMPENED = "undampened"
EVENT_END_DATETIME = "end_date_time"
EVENT_START_DATETIME = "start_date_time"
PLATFORMS = [Platform.SENSOR, Platform.SELECT,]
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
        vol.Required(HARD_LIMIT): cv.Number,
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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the integration.

    * Get and sanitise options.
    * Instantiate the main class.
    * Load Solcast sites and API usage.
    * Load previously saved data.
    * Instantiate the coordinator.
    * Add unload hook on options change.
    * Trigger a forecast update for new installs (or after a 'stale' start).
    * Set up service calls.

    Arguments:
        hass (HomeAssistant): The Home Assistant instance.
        entry (ConfigEntry): The integration entry instance, contains the configuration.

    Raises:
        ConfigEntryNotReady: Instructs Home Assistant that the integration is not yet ready when a load failure occurrs.

    Returns:
        bool: Whether setup has completed successfully.
    """
    random.seed()

    optdamp = {}
    try:
        # If something ever goes wrong with the damp factors create a default list of no dampening
        for a in range(0,24):
            optdamp[str(a)] = entry.options[f"damp{str(a).zfill(2)}"]
    except:
        new = {**entry.options}
        for a in range(0,24):
            new[f"damp{str(a).zfill(2)}"] = 1.0
        entry.options = {**new}
        for a in range(0,24):
            optdamp[str(a)] = 1.0

    # async_get_time_zone() mandated in HA core 2024.6.0
    try:
        dt_util.async_get_time_zone # pylint: disable=W0104
        asynctz = True
    except:
        asynctz = False
    if asynctz:
        tz = await dt_util.async_get_time_zone(hass.config.time_zone)
    else:
        tz = dt_util.get_time_zone(hass.config.time_zone)

    options = ConnectionOptions(
        entry.options[CONF_API_KEY],
        entry.options[API_QUOTA],
        SOLCAST_URL,
        hass.config.path(f"{os.path.abspath(os.path.join(os.path.dirname(__file__) ,'../..'))}/solcast.json"),
        tz,
        entry.options.get(AUTO_UPDATE, 0),
        optdamp,
        entry.options.get(CUSTOM_HOUR_SENSOR, 1),
        entry.options.get(KEY_ESTIMATE, "estimate"),
        entry.options.get(HARD_LIMIT,100000) / 1000,
        entry.options.get(BRK_ESTIMATE, True),
        entry.options.get(BRK_ESTIMATE10, True),
        entry.options.get(BRK_ESTIMATE90, True),
        entry.options.get(BRK_SITE, True),
        entry.options.get(BRK_HALFHOURLY, True),
        entry.options.get(BRK_HOURLY, True),
        entry.options.get(BRK_SITE_DETAILED, False),
    )
    _LOGGER.debug("Auto-update options: %s", {k: v for k, v in entry.options.items() if k.startswith('auto_')})
    _LOGGER.debug("Estimate to use options: %s", {k: v for k, v in entry.options.items() if k.startswith('key_est')})
    _LOGGER.debug("Attribute options: %s", {k: v for k, v in entry.options.items() if k.startswith('attr_')})
    _LOGGER.debug("Custom sensor options: %s", {k: v for k, v in entry.options.items() if k.startswith('custom')})
    _LOGGER.debug("Hard limit: %s", {k: v for k, v in entry.options.items() if k.startswith('hard_')})

    solcast = SolcastApi(aiohttp_client.async_get_clientsession(hass), options)

    solcast.entry = entry
    solcast.entry_options = {**entry.options}
    solcast.hass = hass

    if not hass.data.get(DOMAIN):
        hass.data[DOMAIN] = {}

    if hass.data[DOMAIN].get('has_loaded', False):
        init_msg = '' # if the integration has already successfully loaded previously then do not display the full version nag on reload.
        solcast.previously_loaded = True
    else:
        init_msg = INIT_MSG

    try:
        version = ''
        integration = await loader.async_get_integration(hass, DOMAIN)
        version = str(integration.version)
    except loader.IntegrationNotFound:
        pass

    try:
        await solcast.get_sites_and_usage()
    except Exception as e:
        raise ConfigEntryNotReady(f"Getting sites data failed: {e}") from e

    if not solcast.sites_loaded:
        raise ConfigEntryNotReady('Sites data could not be retrieved')

    _LOGGER.debug("Successful init")

    _LOGGER.info(
        "%sSolcast integration version: %s%s%s",
        ('\n' + '-'*67 + '\n') if init_msg != '' else '',
        version,
        ('\n\n' + init_msg) if init_msg != '' else '',('\n' + '-'*67) if init_msg != '' else '',
    )

    granular_dampening = await solcast.granular_dampening_data()
    opt = {**entry.options}
    opt[SITE_DAMP] = granular_dampening # Internal per-site dampening set flag. A hidden option until set.
    hass.config_entries.async_update_entry(entry, options=opt)
    hass.data[DOMAIN]['entry_options'] = entry.options

    status = await solcast.load_saved_data()
    if status != '':
        raise ConfigEntryNotReady(status)

    coordinator = SolcastUpdateCoordinator(hass, solcast, version)
    await coordinator.setup()
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_update_options))

    _LOGGER.debug("UTC times are converted to %s", hass.config.time_zone)

    if not solcast.previously_loaded:
        if options.hard_limit < 100:
            _LOGGER.info("Inverter hard limit value has been set. If the forecasts and graphs are not as you expect, remove this setting")

    hass.data[DOMAIN]['has_loaded'] = True

    # If the integration has been failed for some time and then is restarted retrieve forecasts (i.e Home Assistant down for a while).
    if solcast.is_stale_data():
        try:
            _LOGGER.info("First start, or integration has been failed for some time, retrieving forecasts (or your update automation has not been running - see readme)")
            await coordinator.service_event_update()
        except Exception as e:
            _LOGGER.error("Exception fetching data on stale/initial start: %s: %s", e, traceback.format_exc())
            _LOGGER.warning("Continuing...")

    async def handle_service_update_forecast(call: ServiceCall):
        """Handle service call.

        Arguments:
            call (ServiceCall): Not used.
        """
        _LOGGER.info("Service call: %s", SERVICE_UPDATE)
        await coordinator.service_event_update()

    async def handle_service_force_update_forecast(call: ServiceCall):
        """Handle service call.

        Arguments:
            call (ServiceCall): Not used.
        """
        _LOGGER.info("Service call: %s", SERVICE_FORCE_UPDATE)
        await coordinator.service_event_force_update()

    async def handle_service_clear_solcast_data(call: ServiceCall):
        """Handle service call.

        Arguments:
            call (ServiceCall): Not used.
        """
        _LOGGER.info("Service call: %s", SERVICE_CLEAR_DATA)
        await coordinator.service_event_delete_old_solcast_json_file()

    async def handle_service_get_solcast_data(call: ServiceCall) -> (Dict[str, Any] | None):
        """Handle service call.

        Arguments:
            call (ServiceCall): The data to act on: a start and optional end date/time (defaults to now), optional dampened/undampened, optional site.

        Raises:
            HomeAssistantError: Notify Home Assistant that an error has occurred.
        
        Returns:
            Dict[str, Any] | None: The Solcast data from start to end date/times.
        """
        try:
            _LOGGER.info("Service call: %s", SERVICE_QUERY_FORECAST_DATA)

            start = call.data.get(EVENT_START_DATETIME, dt_util.now())
            end = call.data.get(EVENT_END_DATETIME, dt_util.now())
            site = call.data.get(SITE, 'all')
            undampened = call.data.get(UNDAMPENED, False)

            d = await coordinator.service_query_forecast_data(dt_util.as_utc(start), dt_util.as_utc(end), site, undampened)
        except intent.IntentHandleError as e:
            raise HomeAssistantError(f"Error processing {SERVICE_QUERY_FORECAST_DATA}: {e}") from e

        if call.return_response:
            return {"data": d}

        return None

    async def handle_service_set_dampening(call: ServiceCall):
        """Handle service call.

        Arguments:
            call (ServiceCall): The data to act on: a set of dampening values, and an optional site.

        Raises:
            HomeAssistantError: Notify Home Assistant that an error has occurred.
            ServiceValidationError: Notify Home Assistant that an error has occurred, with translation.
        """
        try:
            _LOGGER.info("Service call: %s", SERVICE_SET_DAMPENING)

            factors = call.data.get(DAMP_FACTOR, None)
            site = call.data.get(SITE, None) # Optional site.

            if factors is None:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key="damp_no_factors")
            factors = factors.strip().replace(' ','')
            if len(factors.split(',')) == 0:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key="damp_no_factors")
            sp = factors.split(",")
            if len(sp) not in (24, 48):
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key="damp_count_not_correct")
            if site is not None:
                site = site.lower()
                if site == 'all':
                    if(len(sp)) != 48:
                        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="damp_no_all_24")
                else:
                    if site not in [s['resource_id'] for s in solcast.sites]:
                        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="damp_not_site")
            else:
                if len(sp) == 48:
                    site = 'all'
            out_of_range = False
            try:
                for i in sp:
                    # This will fail whan outside allowed range.
                    if float(i) < 0 or float(i) > 1:
                        out_of_range = True
            except:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key="damp_error_parsing") #pylint: disable=W0707
            if out_of_range:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key="damp_ouside_range")

            opt = {**entry.options}

            def update_options():
                d = {}
                for i in range(0,24):
                    f = float(sp[i])
                    d.update({f"{i}": f})
                    opt[f"damp{i:02}"] = f
                solcast.damp = d

            if site is None:
                update_options()
                if solcast.granular_dampening:
                    _LOGGER.debug("Clear granular dampening")
                    opt[SITE_DAMP] = False # Clear "hidden" option.
            else:
                await solcast.refresh_granular_dampening_data() # Ensure latest file content gets updated
                solcast.granular_dampening[site] = [float(sp[i]) for i in range(0,len(sp))]
                await solcast.serialise_granular_dampening()
                opt[SITE_DAMP] = True # Set "hidden" option.

            hass.config_entries.async_update_entry(entry, options=opt)
        except intent.IntentHandleError as e:
            raise HomeAssistantError(f"Error processing {SERVICE_SET_DAMPENING}: {e}") from e

    async def handle_service_get_dampening(call: ServiceCall):
        """Handle service call.

        Arguments:
            call (ServiceCall): The data to act on: an optional site.
        """
        try:
            _LOGGER.info("Service call: %s", SERVICE_GET_DAMPENING)

            site = call.data.get(SITE, None) # Optional site.
            d = await solcast.get_dampening(site)
        except intent.IntentHandleError as e:
            raise HomeAssistantError(f"Error processing {SERVICE_GET_DAMPENING}: {e}") from e

        if call.return_response:
            return {"data": d}

        return None

    async def handle_service_set_hard_limit(call: ServiceCall):
        """Handle service call.

        Arguments:
            call (ServiceCall): The data to act on: a hard limit.

        Raises:
            HomeAssistantError: Notify Home Assistant that an error has occurred.
            ServiceValidationError: Notify Home Assistant that an error has occurred, with translation.
        """
        try:
            _LOGGER.info("Service call: %s", SERVICE_SET_HARD_LIMIT)

            hl = call.data.get(HARD_LIMIT, 100000)


            if hl is None:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key="hard_empty")
            else:
                val = int(hl)
                if val < 0:  # If not a positive int print message and ask for input again.
                    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="hard_not_positive_number")

                opt = {**entry.options}
                opt[HARD_LIMIT] = val
                hass.config_entries.async_update_entry(entry, options=opt)

        except ValueError as e:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="hard_not_positive_number") from e
        except intent.IntentHandleError as e:
            raise HomeAssistantError(f"Error processing {SERVICE_SET_HARD_LIMIT}: {e}") from e

    async def handle_service_remove_hard_limit(call: ServiceCall):
        """Handle service call.

        Arguments:
            call (ServiceCall): Not used.

        Raises:
            HomeAssistantError: Notify Home Assistant that an error has occurred.
        """
        try:
            _LOGGER.info("Service call: %s", SERVICE_REMOVE_HARD_LIMIT)

            opt = {**entry.options}
            opt[HARD_LIMIT] = 100000
            hass.config_entries.async_update_entry(entry, options=opt)

        except intent.IntentHandleError as e:
            raise HomeAssistantError(f"Error processing {SERVICE_REMOVE_HARD_LIMIT}: {e}") from e

    hass.services.async_register(
        DOMAIN, SERVICE_UPDATE, handle_service_update_forecast
    )

    hass.services.async_register(
        DOMAIN, SERVICE_FORCE_UPDATE, handle_service_force_update_forecast
    )

    hass.services.async_register(
        DOMAIN, SERVICE_CLEAR_DATA, handle_service_clear_solcast_data
    )

    hass.services.async_register(
        DOMAIN, SERVICE_QUERY_FORECAST_DATA, handle_service_get_solcast_data, SERVICE_QUERY_SCHEMA, SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN, SERVICE_SET_DAMPENING, handle_service_set_dampening, SERVICE_DAMP_SCHEMA
    )

    hass.services.async_register(
        DOMAIN, SERVICE_GET_DAMPENING, handle_service_get_dampening, SERVICE_DAMP_GET_SCHEMA, SupportsResponse.ONLY
    )

    hass.services.async_register(
        DOMAIN, SERVICE_SET_HARD_LIMIT, handle_service_set_hard_limit, SERVICE_HARD_LIMIT_SCHEMA
    )

    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE_HARD_LIMIT, handle_service_remove_hard_limit
    )

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    This also removes the services available.

    Arguments:
        hass (HomeAssistant): The Home Assistant instance.
        entry (ConfigEntry): The integration entry instance, contains the configuration.

    Returns:
        bool: Whether the unload completed successfully.
    """
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    hass.services.async_remove(DOMAIN, SERVICE_UPDATE)
    hass.services.async_remove(DOMAIN, SERVICE_CLEAR_DATA)
    hass.services.async_remove(DOMAIN, SERVICE_QUERY_FORECAST_DATA)
    hass.services.async_remove(DOMAIN, SERVICE_SET_DAMPENING)
    hass.services.async_remove(DOMAIN, SERVICE_SET_HARD_LIMIT)
    hass.services.async_remove(DOMAIN, SERVICE_REMOVE_HARD_LIMIT)

    return unload_ok

async def async_remove_config_entry_device(hass: HomeAssistant, entry: ConfigEntry, device) -> bool:
    """Remove a device.

    Arguments:
        hass (HomeAssistant): The Home Assistant instance.
        entry (ConfigEntry): Not ussed.
        device: The device instance.

    Returns:
        bool: Whether the removal completed successfully.
    """
    device_registry(hass).async_remove_device(device.id)
    return True

async def async_update_options(hass: HomeAssistant, entry: ConfigEntry):
    """Reconfigure the integration when options get updated.

    * Changing API key or limit, auto-update or turning detailed site breakdown on results in a restart.
    * Changing dampening results in forecast recalculation.
    * Other alterations simply refresh sensor values and attributes.

    Arguments:
        hass (HomeAssistant): The Home Assistant instance.
        entry (ConfigEntry): The integration entry instance, contains the configuration.
    """
    coordinator = hass.data[DOMAIN][entry.entry_id]

    def tasks_cancel():
        try:
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
            coordinator.tasks = {}
        except Exception as e:
            _LOGGER.error("Cancelling tasks failed: %s: %s", e, traceback.format_exc())
        coordinator.solcast.tasks = {}

    try:
        reload = False
        recalc = False
        respline = False

        def changed(config):
            return hass.data[DOMAIN]['entry_options'].get(config) != entry.options.get(config)

        # Config changes, which when changed will cause a reload.
        if changed(CONF_API_KEY):
            hass.data[DOMAIN]['old_api_key'] = hass.data[DOMAIN]['entry_options'].get(CONF_API_KEY)
        reload = changed(CONF_API_KEY) or changed(API_QUOTA) or changed(AUTO_UPDATE)

        # Config changes, which when changed will cause a forecast recalculation only, without reload.
        # Dampening must be the first check with the code as-is...
        if not reload:
            d = {}
            for i in range(0,24):
                d.update({f"{i}": entry.options[f"damp{i:02}"]})
                if changed(f"damp{i:02}"):
                    recalc = True
            if recalc:
                coordinator.solcast.damp = d

            if changed(HARD_LIMIT):
                recalc = True
            # Attribute changes, which will need a recalulation of splines
            if not recalc:
                respline = changed(BRK_ESTIMATE) or changed(BRK_ESTIMATE10) or changed(BRK_ESTIMATE90) or changed(BRK_SITE) or changed(KEY_ESTIMATE)

            if changed(SITE_DAMP):
                if not entry.options[SITE_DAMP]:
                    if coordinator.solcast.allow_granular_dampening_reset():
                        coordinator.solcast.granular_dampening = {}
                        await coordinator.solcast.serialise_granular_dampening()
                        _LOGGER.debug("Granular dampening file reset")
                    else:
                        _LOGGER.debug("Granular dampening file not reset")

        if reload:
            determination = 'The integration will reload'
        elif recalc:
            determination = 'Recalculate forecasts and refresh sensors'
        else:
            determination = 'Refresh sensors only' + (' (with spline recalc)' if respline else '')
        _LOGGER.debug("Options updated, action: %s", determination)
        if not reload:
            await coordinator.solcast.set_options(entry.options)
            if recalc:
                await coordinator.solcast.build_forecast_data()
            elif respline:
                await coordinator.solcast.recalculate_splines()
            coordinator.set_data_updated(True)
            await coordinator.update_integration_listeners()
            coordinator.set_data_updated(False)

            hass.data[DOMAIN]['entry_options'] = entry.options
            coordinator.solcast.entry_options = entry.options
        else:
            # Reload
            tasks_cancel()
            await hass.config_entries.async_reload(entry.entry_id)
    except:
        _LOGGER.debug(traceback.format_exc())
        # Restart on exception
        tasks_cancel()
        await hass.config_entries.async_reload(entry.entry_id)

async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Upgrade configuration.

    v4:  (?)        Remove option for auto-poll
    v5:  (4.0.8)    Dampening factor for each hour
    v6:  (4.0.15)   Add custom sensor for next X hours
    v7:  (4.0.16)   Selectable estimate value to use estimate, estimate10, estimate90
    v8:  (4.0.39)   Selectable attributes for sensors
    v9:  (4.1.3)    API limit (because Solcast removed an API call)
    v10: (4.1.8)    Day 1..7 detailed breakdown by site
    v11: (4.1.8)    Auto-update as binaries, plus add missing hard limit
    v12: (4.1.8)    Alter auto-update to 0=off, 1=sunrise/sunset, 2=24-hour

    An upgrade of the integration will sequentially upgrade options to the current
    version, with this function needing to consider all upgrade history and new defaults.

    An integration downgrade must not cause any issues when future options have been
    configured, with future options then just being unused. To be clear, the intent or
    characteristics of an option cannot change with an upgrade. These should also be
    re-defaulted on subsequent upgrade.

    The present version (e.g. `VERSION = 9`) is specified in `config_flow.py`.

    Arguments:
        hass (HomeAssistant): The Home Assistant instance.
        entry (ConfigEntry): The integration entry instance, contains the configuration.

    Returns:
        bool: Whether the config upgrade completed successfully.
    """
    def upgraded():
        _LOGGER.info("Upgraded to options version %s", entry.version)

    try:
        _LOGGER.debug("Options version %s", entry.version)
    except:
        pass

    if entry.version < 4:
        new = {**entry.options}
        new.pop("const_disableautopoll", None)
        try:
            hass.config_entries.async_update_entry(entry, options=new, version=4)
            upgraded()
        except Exception as e:
            if "unexpected keyword argument 'version'" in e:
                entry.version = 4
                hass.config_entries.async_update_entry(entry, options=new)
                upgraded()
            else:
                raise

    if entry.version < 5:
        new = {**entry.options}
        for a in range(0,24):
            new[f"damp{str(a).zfill(2)}"] = 1.0
        try:
            hass.config_entries.async_update_entry(entry, options=new, version=5)
            upgraded()
        except Exception as e:
            if "unexpected keyword argument 'version'" in e:
                entry.version = 5
                hass.config_entries.async_update_entry(entry, options=new)
                upgraded()
            else:
                raise

    if entry.version < 6:
        new = {**entry.options}
        new[CUSTOM_HOUR_SENSOR] = 1
        try:
            hass.config_entries.async_update_entry(entry, options=new, version=6)
            upgraded()
        except Exception as e:
            if "unexpected keyword argument 'version'" in e:
                entry.version = 6
                hass.config_entries.async_update_entry(entry, options=new)
                upgraded()
            else:
                raise

    if entry.version < 7:
        new = {**entry.options}
        new[KEY_ESTIMATE] = "estimate"
        try:
            hass.config_entries.async_update_entry(entry, options=new, version=7)
            upgraded()
        except Exception as e:
            if "unexpected keyword argument 'version'" in e:
                entry.version = 7
                hass.config_entries.async_update_entry(entry, options=new)
                upgraded()
            else:
                raise

    if entry.version < 8:
        new = {**entry.options}
        if new.get(BRK_ESTIMATE) is None: new[BRK_ESTIMATE] = True
        if new.get(BRK_ESTIMATE10) is None: new[BRK_ESTIMATE10] = True
        if new.get(BRK_ESTIMATE90) is None: new[BRK_ESTIMATE90] = True
        if new.get(BRK_SITE) is None: new[BRK_SITE] = True
        if new.get(BRK_HALFHOURLY)is None: new[BRK_HALFHOURLY] = True
        if new.get(BRK_HOURLY) is None: new[BRK_HOURLY] = True
        try:
            hass.config_entries.async_update_entry(entry, options=new, version=8)
            upgraded()
        except Exception as e:
            if "unexpected keyword argument 'version'" in e:
                entry.version = 8
                hass.config_entries.async_update_entry(entry, options=new)
                upgraded()
            else:
                raise

    if entry.version < 9:
        new = {**entry.options}
        try:
            default = []
            _config_dir = os.path.abspath(os.path.join(os.path.dirname(__file__) ,"../.."))
            for spl in new[CONF_API_KEY].split(','):
                api_cache_filename = f"{_config_dir}/solcast-usage{'' if len(new[CONF_API_KEY].split(',')) < 2 else '-' + spl.strip()}.json"
                async with aiofiles.open(api_cache_filename) as f:
                    usage = json.loads(await f.read())
                default.append(str(usage['daily_limit']))
            default = ','.join(default)
        except Exception as e:
            _LOGGER.warning("Could not load API usage cached limit while upgrading config, using default of ten: %s", e)
            default = '10'
        if new.get(API_QUOTA) is None: new[API_QUOTA] = default
        try:
            hass.config_entries.async_update_entry(entry, options=new, version=9)
            upgraded()
        except Exception as e:
            if "unexpected keyword argument 'version'" in e:
                entry.version = 9
                hass.config_entries.async_update_entry(entry, options=new)
                upgraded()
            else:
                raise

    if entry.version < 10:
        new = {**entry.options}
        if new.get(BRK_SITE_DETAILED) is None: new[BRK_SITE_DETAILED] = False
        try:
            hass.config_entries.async_update_entry(entry, options=new, version=10)
            upgraded()
        except Exception as e:
            if "unexpected keyword argument 'version'" in e:
                entry.version = 10
                hass.config_entries.async_update_entry(entry, options=new)
                upgraded()
            else:
                raise

    if entry.version < 11:
        new = {**entry.options}
        if new.get(AUTO_UPDATE) is None: new[AUTO_UPDATE] = False
        if new.get("auto_24_hour") is None: new["auto_24_hour"] = False
        if new.get(HARD_LIMIT) is None: new[HARD_LIMIT] = 100000
        try:
            hass.config_entries.async_update_entry(entry, options=new, version=11)
            upgraded()
        except Exception as e:
            if "unexpected keyword argument 'version'" in e:
                entry.version = 11
                hass.config_entries.async_update_entry(entry, options=new)
                upgraded()
            else:
                raise

    if entry.version < 12:
        new = {**entry.options}
        # Convert from short-lived options schema v11
        new[AUTO_UPDATE] = int(new.get(AUTO_UPDATE, False))
        if new.get("auto_24_hour", False): new[AUTO_UPDATE] = 2
        new.pop("auto_24_hour", None)
        try:
            hass.config_entries.async_update_entry(entry, options=new, version=12)
            upgraded()
        except Exception as e:
            if "unexpected keyword argument 'version'" in e:
                entry.version = 12
                hass.config_entries.async_update_entry(entry, options=new)
                upgraded()
            else:
                raise

    return True