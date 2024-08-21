#!/usr/bin/python3

import asyncio
import logging
import traceback
from .const import SOLCAST_URL
from homeassistant.util import dt as dt_util

from aiohttp import ClientSession

from .solcastapi import ConnectionOptions, SolcastApi

logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger(__name__)


async def test():
    print('This script is for development purposes only')
    try:
        optdamp = {}
        for a in range(0,24): optdamp[str(a)] = 1.0

        options = ConnectionOptions(
            "apikeygoeshere",
            SOLCAST_URL,
            'solcast.json',
            "/config",
            await dt_util.async_get_time_zone(hass.config.time_zone),
            optdamp,
            1,
            "estimate",
            100,
            True,
            True,
            True,
            True,
            True,
            True
        )
        
        async with ClientSession() as session:
            solcast = SolcastApi(session, options, apiCacheEnabled=True)
            await solcast.sites_data()
            await solcast.load_saved_data()
            print("Total today " + str(solcast.get_total_kwh_forecast_today()))
            print("Peak today " + str(solcast.get_peak_w_today()))
            print("Peak time today " + str(solcast.get_peak_w_time_today()))
    except Exception as err:
        _LOGGER.error("async_setup_entry: %s",traceback.format_exc())
        return False


asyncio.run(test())