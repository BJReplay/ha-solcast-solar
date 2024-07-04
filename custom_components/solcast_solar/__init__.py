"""Support for Solcast PV forecast."""

import logging
import random

from homeassistant import loader
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import (HomeAssistant,
                                ServiceCall,
                                ServiceResponse,
                                SupportsResponse,)
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import aiohttp_client, intent
from homeassistant.helpers.device_registry import async_get as device_registry
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    SERVICE_CLEAR_DATA,
    SERVICE_UPDATE,
    SERVICE_QUERY_FORECAST_DATA,
    SERVICE_SET_DAMPENING,
    SERVICE_SET_HARD_LIMIT,
    SERVICE_REMOVE_HARD_LIMIT,
    SOLCAST_URL,
    CUSTOM_HOUR_SENSOR,
    KEY_ESTIMATE
)

from .coordinator import SolcastUpdateCoordinator
from .solcastapi import ConnectionOptions, SolcastApi

from typing import Final

import voluptuous as vol

PLATFORMS = [Platform.SENSOR, Platform.SELECT,]

_LOGGER = logging.getLogger(__name__)

DAMP_FACTOR = "damp_factor"
SERVICE_DAMP_SCHEMA: Final = vol.All(
        {
            vol.Required(DAMP_FACTOR): cv.string,
        }
)

HARD_LIMIT = "hard_limit"
SERVICE_HARD_LIMIT_SCHEMA: Final = vol.All(
        {
            vol.Required(HARD_LIMIT): cv.Number,
        }
)

EVENT_START_DATETIME = "start_date_time"
EVENT_END_DATETIME = "end_date_time"
SERVICE_QUERY_SCHEMA: Final = vol.All(
        {
            vol.Required(EVENT_START_DATETIME): cv.datetime,
            vol.Required(EVENT_END_DATETIME): cv.datetime,
        }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up solcast parameters."""

    random.seed()

    _VERSION = ""
    try:
        integration = await loader.async_get_integration(hass, DOMAIN)
        _VERSION = str(integration.version)
        _LOGGER.info(
            f"\n{'-'*67}\n"
            f"Solcast integration version: {_VERSION}\n\n"
            f"This is a custom integration. When troubleshooting a problem, after\n"
            f"reviewing open and closed issues, and the discussions, check the\n"
            f"required automation is functioning correctly and try enabling debug\n"
            f"logging to see more. Troubleshooting tips available at:\n"
            f"https://github.com/BJReplay/ha-solcast-solar/discussions/38\n\n"
            f"Beta versions may also have addressed some issues so look at those.\n\n"
            f"If all else fails, then open an issue and our community will try to\n"
            f"help: https://github.com/BJReplay/ha-solcast-solar/issues\n"
            f"{'-'*67}")
    except loader.IntegrationNotFound:
        pass

    #new in v4.0.16 for the selector of which field to use from the data
    if entry.options.get(KEY_ESTIMATE,None) is None:
        new = {**entry.options}
        new[KEY_ESTIMATE] = "estimate"
        hass.config_entries.async_update_entry(entry, options=new, version=7)

    optdamp = {}
    try:
        #if something goes wrong ever with the damp factors just create a blank 1.0
        for a in range(0,24):
            optdamp[str(a)] = entry.options[f"damp{str(a).zfill(2)}"]
    except Exception as ex:
        new = {**entry.options}
        for a in range(0,24):
            new[f"damp{str(a).zfill(2)}"] = 1.0
        entry.options = {**new}
        for a in range(0,24):
            optdamp[str(a)] = 1.0

    # Introduced in 2024.6.0: async_get_time_zone
    try:
        dt_util.async_get_time_zone
        asynctz = True
    except:
        asynctz = False
    if asynctz:
        tz = await dt_util.async_get_time_zone(hass.config.time_zone)
    else:
        tz = dt_util.get_time_zone(hass.config.time_zone)
    options = ConnectionOptions(
        entry.options[CONF_API_KEY],
        SOLCAST_URL,
        hass.config.path('/config/solcast.json'),
        tz,
        optdamp,
        entry.options[CUSTOM_HOUR_SENSOR],
        entry.options.get(KEY_ESTIMATE,"estimate"),
        (entry.options.get(HARD_LIMIT,100000)/1000),
    )

    solcast = SolcastApi(aiohttp_client.async_get_clientsession(hass), options)

    try:
        await solcast.sites_data()
        await solcast.sites_usage()
    except Exception as ex:
        raise ConfigEntryNotReady(f"Getting sites data failed: {ex}") from ex

    await solcast.load_saved_data()

    coordinator = SolcastUpdateCoordinator(hass, solcast, _VERSION)

    await coordinator.setup()

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_update_options))

    _LOGGER.info(f"Solcast API data UTC times are converted to {hass.config.time_zone}")

    if options.hard_limit < 100:
        _LOGGER.info(
            f"Solcast inverter hard limit value has been set. If the forecasts and graphs are not as you expect, try running the service 'solcast_solar.remove_hard_limit' to remove this setting. "
            f"This setting is really only for advanced quirky solar setups."
        )

    async def handle_service_update_forecast(call: ServiceCall):
        """Handle service call"""
        _LOGGER.info(f"Solcast service call: {SERVICE_UPDATE}")
        await coordinator.service_event_update()

    async def handle_service_clear_solcast_data(call: ServiceCall):
        """Handle service call"""
        _LOGGER.info(f"Solcast service call: {SERVICE_CLEAR_DATA}")
        await coordinator.service_event_delete_old_solcast_json_file()

    async def handle_service_get_solcast_data(call: ServiceCall) -> ServiceResponse:
        """Handle service call"""
        try:
            _LOGGER.info(f"Solcast service call: {SERVICE_QUERY_FORECAST_DATA}")

            start = call.data.get(EVENT_START_DATETIME, dt_util.now())
            end = call.data.get(EVENT_END_DATETIME, dt_util.now())

            d = await coordinator.service_query_forecast_data(dt_util.as_utc(start), dt_util.as_utc(end))
        except intent.IntentHandleError as err:
            raise HomeAssistantError(f"Error processing {SERVICE_QUERY_FORECAST_DATA}: {err}") from err

        if call.return_response:
            return {"data": d}

        return None

    async def handle_service_set_dampening(call: ServiceCall):
        """Handle service call"""
        try:
            _LOGGER.info(f"Solcast service call: {SERVICE_SET_DAMPENING}")

            factors = call.data.get(DAMP_FACTOR, None)

            if factors == None:
                raise HomeAssistantError(f"Error processing {SERVICE_SET_DAMPENING}: Empty factor string")
            else:
                factors = factors.strip().replace(" ","")
                if len(factors) == 0:
                    raise HomeAssistantError(f"Error processing {SERVICE_SET_DAMPENING}: Empty factor string")
                else:
                    sp = factors.split(",")
                    if (len(sp)) != 24:
                        raise HomeAssistantError(f"Error processing {SERVICE_SET_DAMPENING}: Not 24 hourly factor items")
                    else:
                        for i in sp:
                            #this will fail is its not a number
                            if float(i) < 0 or float(i) > 1:
                                raise HomeAssistantError(f"Error processing {SERVICE_SET_DAMPENING}: Factor value outside 0.0 to 1.0")
                        d= {}
                        opt = {**entry.options}
                        for i in range(0,24):
                            d.update({f"{i}": float(sp[i])})
                            opt[f"damp{i:02}"] = float(sp[i])

                        solcast._damp = d
                        hass.config_entries.async_update_entry(entry, options=opt)

            #why is this here?? why did i make it delete the file when changing the damp factors??
            #await coordinator.service_event_delete_old_solcast_json_file()
        except intent.IntentHandleError as err:
            raise HomeAssistantError(f"Error processing {SERVICE_SET_DAMPENING}: {err}") from err

    async def handle_service_set_hard_limit(call: ServiceCall):
        """Handle service call"""
        try:
            _LOGGER.info(f"Solcast service call: {SERVICE_SET_HARD_LIMIT}")

            hl = call.data.get(HARD_LIMIT, 100000)


            if hl == None:
                raise HomeAssistantError(f"Error processing {SERVICE_SET_HARD_LIMIT}: Empty hard limit value")
            else:
                val = int(hl)
                if val < 0:  # if not a positive int print message and ask for input again
                    raise HomeAssistantError(f"Error processing {SERVICE_SET_HARD_LIMIT}: Hard limit value not a positive number")

                opt = {**entry.options}
                opt[HARD_LIMIT] = val
                # solcast._hardlimit = val
                hass.config_entries.async_update_entry(entry, options=opt)

        except ValueError:
            raise HomeAssistantError(f"Error processing {SERVICE_SET_HARD_LIMIT}: Hard limit value not a positive number")
        except intent.IntentHandleError as err:
            raise HomeAssistantError(f"Error processing {SERVICE_SET_DAMPENING}: {err}") from err

    async def handle_service_remove_hard_limit(call: ServiceCall):
        """Handle service call"""
        try:
            _LOGGER.info(f"Solcast service call: {SERVICE_REMOVE_HARD_LIMIT}")

            opt = {**entry.options}
            opt[HARD_LIMIT] = 100000
            hass.config_entries.async_update_entry(entry, options=opt)

        except intent.IntentHandleError as err:
            raise HomeAssistantError(f"Error processing {SERVICE_REMOVE_HARD_LIMIT}: {err}") from err

    hass.services.async_register(
        DOMAIN, SERVICE_UPDATE, handle_service_update_forecast
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
        DOMAIN, SERVICE_SET_HARD_LIMIT, handle_service_set_hard_limit, SERVICE_HARD_LIMIT_SCHEMA
    )

    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE_HARD_LIMIT, handle_service_remove_hard_limit
    )

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
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
    device_registry(hass).async_remove_device(device.id)
    return True

async def async_update_options(hass: HomeAssistant, entry: ConfigEntry):
    """Reload..."""
    await hass.config_entries.async_reload(entry.entry_id)

async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    def upgraded():
        _LOGGER.debug("SOLCAST - Upgraded to options version %s", config_entry.version)

    try:
        _LOGGER.debug("SOLCAST - Options version %s", config_entry.version)
    except:
        pass

    if config_entry.version < 4:
        new_options = {**config_entry.options}
        new_options.pop("const_disableautopoll", None)
        try:
            hass.config_entries.async_update_entry(config_entry, options=new_options, version=4)
            upgraded()
        except Exception as e:
            if "unexpected keyword argument 'version'" in e:
                config_entry.version = 4
                hass.config_entries.async_update_entry(config_entry, options=new_options)
                upgraded()
            else:
                raise

    #new 4.0.8
    #dampening factor for each hour
    if config_entry.version == 4:
        new = {**config_entry.options}
        for a in range(0,24):
            new[f"damp{str(a).zfill(2)}"] = 1.0
        try:
            hass.config_entries.async_update_entry(config_entry, options=new, version=5)
            upgraded()
        except Exception as e:
            if "unexpected keyword argument 'version'" in e:
                config_entry.version = 5
                hass.config_entries.async_update_entry(config_entry, options=new_options)
                upgraded()
            else:
                raise

    #new 4.0.15
    #custom sensor for 'next x hours'
    if config_entry.version == 5:
        new = {**config_entry.options}
        new[CUSTOM_HOUR_SENSOR] = 1
        try:
            hass.config_entries.async_update_entry(config_entry, options=new, version=6)
            upgraded()
        except Exception as e:
            if "unexpected keyword argument 'version'" in e:
                config_entry.version = 6
                hass.config_entries.async_update_entry(config_entry, options=new_options)
                upgraded()
            else:
                raise

    #new 4.0.16
    #which estimate value to use for data calcs est,est10,est90
    if config_entry.version == 6:
        new = {**config_entry.options}
        new[KEY_ESTIMATE] = "estimate"
        try:
            hass.config_entries.async_update_entry(config_entry, options=new, version=7)
            upgraded()
        except Exception as e:
            if "unexpected keyword argument 'version'" in e:
                config_entry.version = 7
                hass.config_entries.async_update_entry(config_entry, options=new_options)
                upgraded()
            else:
                raise

    return True