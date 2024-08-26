"""Support for Solcast PV forecast."""

# pylint: disable=C0304, C0321, E0401, E1135, W0212, W0613, W0702, W0718

import logging
import traceback
import random
import os
import json
from datetime import timedelta
from typing import Final
import aiofiles

import voluptuous as vol
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
    API_QUOTA,
    CUSTOM_HOUR_SENSOR,
    KEY_ESTIMATE,
    BRK_ESTIMATE,
    BRK_ESTIMATE10,
    BRK_ESTIMATE90,
    BRK_SITE,
    BRK_HALFHOURLY,
    BRK_HOURLY,
)

from .coordinator import SolcastUpdateCoordinator
from .solcastapi import ConnectionOptions, SolcastApi

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

    optdamp = {}
    try:
        #if something ever goes wrong with the damp factors just create a blank 1.0
        for a in range(0,24):
            optdamp[str(a)] = entry.options[f"damp{str(a).zfill(2)}"]
    except:
        new = {**entry.options}
        for a in range(0,24):
            new[f"damp{str(a).zfill(2)}"] = 1.0
        entry.options = {**new}
        for a in range(0,24):
            optdamp[str(a)] = 1.0

    # Introduced in core 2024.6.0: async_get_time_zone
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
        optdamp,
        entry.options.get(CUSTOM_HOUR_SENSOR, 1),
        entry.options.get(KEY_ESTIMATE, "estimate"),
        (entry.options.get(HARD_LIMIT,100000) / 1000),
        entry.options.get(BRK_ESTIMATE, True),
        entry.options.get(BRK_ESTIMATE10, True),
        entry.options.get(BRK_ESTIMATE90, True),
        entry.options.get(BRK_SITE, True),
        entry.options.get(BRK_HALFHOURLY, True),
        entry.options.get(BRK_HOURLY, True),
    )

    solcast = SolcastApi(aiohttp_client.async_get_clientsession(hass), options)

    try:
        await solcast.sites_data()
        if solcast._sites_loaded:
            await solcast.sites_usage()
    except Exception as ex:
        raise ConfigEntryNotReady(f"Getting sites data failed: {ex}") from ex

    if not solcast._sites_loaded:
        raise ConfigEntryNotReady('Sites data could not be retrieved')

    status = await solcast.load_saved_data()
    if status != '':
        raise ConfigEntryNotReady(status)

    try:
        _VERSION = ""  # pylint: disable=C0103
        integration = await loader.async_get_integration(hass, DOMAIN)
        _VERSION = str(integration.version) # pylint: disable=C0103
        _LOGGER.info('''\n%s
Solcast integration version: %s\n
This is a custom integration. When troubleshooting a problem, after
reviewing open and closed issues, and the discussions, check the
required automation is functioning correctly and try enabling debug
logging to see more. Troubleshooting tips available at:
https://github.com/BJReplay/ha-solcast-solar/discussions/38\n
Beta versions may also have addressed some issues so look at those.\n
If all else fails, then open an issue and our community will try to
help: https://github.com/BJReplay/ha-solcast-solar/issues
%s''', '-'*67, _VERSION, '-'*67)
    except loader.IntegrationNotFound:
        pass

    coordinator = SolcastUpdateCoordinator(hass, solcast, _VERSION)

    await coordinator.setup()

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_update_options))

    _LOGGER.debug("UTC times are converted to %s", hass.config.time_zone)

    if options.hard_limit < 100:
        _LOGGER.info("Solcast inverter hard limit value has been set. If the forecasts and graphs are not as you expect, remove this setting")

    # If the integration has failed for some time and then is restarted retrieve forecasts
    if solcast.get_api_used_count() == 0 and solcast.get_last_updated_datetime() < solcast.get_day_start_utc() - timedelta(days=1):
        try:
            _LOGGER.info('Integration has been failed for some time, or your update automation has not been running (see readme). Retrieving forecasts.')
            #await solcast.sites_weather()
            await solcast.http_data(dopast=False)
            coordinator._data_updated = True
            await coordinator.update_integration_listeners()
            coordinator._data_updated = False
        except Exception as e:
            _LOGGER.error("Exception force fetching data on stale start: %s", e)
            _LOGGER.error(traceback.format_exc())

    async def handle_service_update_forecast(call: ServiceCall):
        """Handle service call"""
        _LOGGER.info("Service call: %s", SERVICE_UPDATE)
        await coordinator.service_event_update()

    async def handle_service_clear_solcast_data(call: ServiceCall):
        """Handle service call"""
        _LOGGER.info("Service call: %s", SERVICE_CLEAR_DATA)
        await coordinator.service_event_delete_old_solcast_json_file()

    async def handle_service_get_solcast_data(call: ServiceCall) -> ServiceResponse:
        """Handle service call"""
        try:
            _LOGGER.info("Service call: %s", SERVICE_QUERY_FORECAST_DATA)

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
            _LOGGER.info("Service call: %s", SERVICE_SET_DAMPENING)

            factors = call.data.get(DAMP_FACTOR, None)

            if factors is None:
                raise HomeAssistantError("Error processing {SERVICE_SET_DAMPENING}: Empty factor string")
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
        except intent.IntentHandleError as err:
            raise HomeAssistantError(f"Error processing {SERVICE_SET_DAMPENING}: {err}") from err

    async def handle_service_set_hard_limit(call: ServiceCall):
        """Handle service call"""
        try:
            _LOGGER.info("Service call: %s", SERVICE_SET_HARD_LIMIT)

            hl = call.data.get(HARD_LIMIT, 100000)


            if hl is None:
                raise HomeAssistantError(f"Error processing {SERVICE_SET_HARD_LIMIT}: Empty hard limit value")
            else:
                val = int(hl)
                if val < 0:  # if not a positive int print message and ask for input again
                    raise HomeAssistantError(f"Error processing {SERVICE_SET_HARD_LIMIT}: Hard limit value not a positive number")

                opt = {**entry.options}
                opt[HARD_LIMIT] = val
                # solcast._hardlimit = val
                hass.config_entries.async_update_entry(entry, options=opt)

        except ValueError as err:
            raise HomeAssistantError(f"Error processing {SERVICE_SET_HARD_LIMIT}: Hard limit value not a positive number") from err
        except intent.IntentHandleError as err:
            raise HomeAssistantError(f"Error processing {SERVICE_SET_DAMPENING}: {err}") from err

    async def handle_service_remove_hard_limit(call: ServiceCall):
        """Handle service call"""
        try:
            _LOGGER.info("Service call: %s", SERVICE_REMOVE_HARD_LIMIT)

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
    """Unload a config entry"""
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
    """Remove ConfigEntry device"""
    device_registry(hass).async_remove_device(device.id)
    return True

async def async_update_options(hass: HomeAssistant, entry: ConfigEntry):
    """Reload..."""
    await hass.config_entries.async_reload(entry.entry_id)

async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry"""
    def upgraded():
        _LOGGER.debug("Upgraded to options version %s", config_entry.version)

    try:
        _LOGGER.debug("Options version %s", config_entry.version)
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
    if config_entry.version < 5:
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
    if config_entry.version < 6:
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
    if config_entry.version < 7:
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

    #new 4.0.39
    #attributes to include
    if config_entry.version < 8:
        new = {**config_entry.options}
        if new.get(BRK_ESTIMATE) is None: new[BRK_ESTIMATE] = True
        if new.get(BRK_ESTIMATE10) is None: new[BRK_ESTIMATE10] = True
        if new.get(BRK_ESTIMATE90) is None: new[BRK_ESTIMATE90] = True
        if new.get(BRK_SITE) is None: new[BRK_SITE] = True
        if new.get(BRK_HALFHOURLY)is None: new[BRK_HALFHOURLY] = True
        if new.get(BRK_HOURLY) is None: new[BRK_HOURLY] = True
        try:
            hass.config_entries.async_update_entry(config_entry, options=new, version=8)
            upgraded()
        except Exception as e:
            if "unexpected keyword argument 'version'" in e:
                config_entry.version = 8
                hass.config_entries.async_update_entry(config_entry, options=new_options)
                upgraded()
            else:
                raise

    #new 4.1.3
    #API quota
    if config_entry.version < 9:
        new = {**config_entry.options}
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
            _LOGGER.warning('Could not load API usage cache quota while upgrading config, using default: %s', e)
            default = '10'
        if new.get(API_QUOTA) is None: new[API_QUOTA] = default
        try:
            hass.config_entries.async_update_entry(config_entry, options=new, version=9)
            upgraded()
        except Exception as e:
            if "unexpected keyword argument 'version'" in e:
                config_entry.version = 9
                hass.config_entries.async_update_entry(config_entry, options=new_options)
                upgraded()
            else:
                raise

    return True