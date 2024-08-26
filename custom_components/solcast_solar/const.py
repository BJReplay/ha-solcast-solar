"""Constants for the Solcast Solar integration."""

# pylint: disable=C0304, E0401

from __future__ import annotations

from typing import Final

from homeassistant.helpers import selector

DOMAIN = "solcast_solar"
TITLE = "Solcast Solar"
SOLCAST_URL = "https://api.solcast.com.au"

ATTR_ENTRY_TYPE: Final = "entry_type"
ENTRY_TYPE_SERVICE: Final = "service"

ATTRIBUTION: Final = "Data retrieved from Solcast"

API_QUOTA = "api_quota"
CUSTOM_HOUR_SENSOR = "customhoursensor"
KEY_ESTIMATE = "key_estimate"
BRK_ESTIMATE = "attr_brk_estimate"
BRK_ESTIMATE10 = "attr_brk_estimate10"
BRK_ESTIMATE90 = "attr_brk_estimate90"
BRK_SITE = "attr_brk_site"
BRK_HALFHOURLY = "attr_brk_halfhourly"
BRK_HOURLY = "attr_brk_hourly"

SERVICE_UPDATE = "update_forecasts"
SERVICE_CLEAR_DATA = "clear_all_solcast_data"
SERVICE_QUERY_FORECAST_DATA = "query_forecast_data"
SERVICE_SET_DAMPENING = "set_dampening"
SERVICE_SET_HARD_LIMIT = "set_hard_limit"
SERVICE_REMOVE_HARD_LIMIT = "remove_hard_limit"

CONFIG_OPTIONS = [
    selector.SelectOptionDict(value="configure_api", label="option1"),
    selector.SelectOptionDict(value="configure_dampening", label="option2"),
    selector.SelectOptionDict(value="configure_customsensor", label="option3"),
    selector.SelectOptionDict(value="configure_attributes", label="option4"),
]