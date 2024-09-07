"""Constants for the Solcast Solar integration."""

# pylint: disable=C0304, E0401

from __future__ import annotations
from typing import Final
from homeassistant.helpers import selector

API_QUOTA = "api_quota"
ATTR_ENTRY_TYPE: Final = "entry_type"
ATTRIBUTION: Final = "Data retrieved from Solcast"
BRK_ESTIMATE = "attr_brk_estimate"
BRK_ESTIMATE10 = "attr_brk_estimate10"
BRK_ESTIMATE90 = "attr_brk_estimate90"
BRK_HALFHOURLY = "attr_brk_halfhourly"
BRK_HOURLY = "attr_brk_hourly"
BRK_SITE = "attr_brk_site"
CONFIG_DAMP = "config_damp"
'''
CONFIG_OPTIONS = [
    selector.SelectOptionDict(value="configure_api", label="option1"),
    selector.SelectOptionDict(value="configure_dampening", label="option2"),
    selector.SelectOptionDict(value="configure_customsensor", label="option3"),
    selector.SelectOptionDict(value="configure_attributes", label="option4"),
]
'''
CONFIG_OPTIONS = [
    "configure_api",
    "configure_dampening",
    "configure_customsensor",
    "configure_attributes",
]
CUSTOM_HOUR_SENSOR = "customhoursensor"
DOMAIN = "solcast_solar"
ENTRY_TYPE_SERVICE: Final = "service"
KEY_ESTIMATE = "key_estimate"
SERVICE_CLEAR_DATA = "clear_all_solcast_data"
SERVICE_QUERY_FORECAST_DATA = "query_forecast_data"
SERVICE_REMOVE_HARD_LIMIT = "remove_hard_limit"
SERVICE_SET_DAMPENING = "set_dampening"
SERVICE_SET_HARD_LIMIT = "set_hard_limit"
SERVICE_UPDATE = "update_forecasts"
SOLCAST_URL = "https://api.solcast.com.au"
TITLE = "Solcast Solar"