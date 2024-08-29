"""Integration test - development only"""
#!/usr/bin/python3

# pylint: disable=C0304, E0401, W0702

import asyncio
import logging
import traceback
from aiohttp import ClientSession

from .const import SOLCAST_URL

from .solcastapi import ConnectionOptions, SolcastApi

logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger(__name__)


async def test():
    """testing"""
    print('This script is for development purposes only')
    try:
        optdamp = {}
        for a in range(0,24):
            optdamp[str(a)] = 1.0

        options = ConnectionOptions(
            "apikeygoeshere",
            SOLCAST_URL,
            'solcast.json',
            "/config",
            "Australia/Sydney",
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
            solcast = SolcastApi(session, options, api_cache_enabled=True)
            await solcast.sites_data()
            await solcast.sites_usage()
            await solcast.load_saved_data()
            print("Total today " + str(solcast.get_total_kwh_forecast_day(0)))
            print("Peak today " + str(solcast.get_peak_w_day(0)))
            print("Peak time today " + str(solcast.get_peak_w_time_day(0)))
    except:
        _LOGGER.error(traceback.format_exc())
        return False


asyncio.run(test())