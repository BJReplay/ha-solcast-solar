"""Constants for the Solcast Solar integration."""

# pylint: disable=C0304, E0401

from __future__ import annotations
from typing import Final

# Development flags
FORECAST_DEBUG_LOGGING = False
SENSOR_DEBUG_LOGGING = False
SPLINE_DEBUG_LOGGING = False

# Integration constants
API_QUOTA = "api_quota"
ATTR_ENTRY_TYPE: Final = "entry_type"
ATTRIBUTION: Final = "Data retrieved from Solcast"
AUTO_UPDATE = "auto_update"
BRK_ESTIMATE = "attr_brk_estimate"
BRK_ESTIMATE10 = "attr_brk_estimate10"
BRK_ESTIMATE90 = "attr_brk_estimate90"
BRK_HALFHOURLY = "attr_brk_halfhourly"
BRK_HOURLY = "attr_brk_hourly"
BRK_SITE = "attr_brk_site"
BRK_SITE_DETAILED = "attr_brk_detailed"
CONFIG_DAMP = "config_damp"
CUSTOM_HOUR_SENSOR = "customhoursensor"
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
DATE_FORMAT_UTC = '%Y-%m-%d %H:%M:%S UTC'
DOMAIN = "solcast_solar"
ENTRY_TYPE_SERVICE: Final = "service"
HARD_LIMIT = "hard_limit"
INIT_MSG = """This is a custom integration. When troubleshooting a problem, after
reviewing open and closed issues, and the discussions, check any
automation is functioning correctly (unless auto-update is
enabled). Troubleshooting tips available at:
https://github.com/BJReplay/ha-solcast-solar/discussions/38

Beta versions may also have addressed issues so look at those.

If all else fails, then open an issue and our community will try to
help: https://github.com/BJReplay/ha-solcast-solar/issues"""
KEY_ESTIMATE = "key_estimate"
MANUFACTURER = "BJReplay"
SERVICE_CLEAR_DATA = "clear_all_solcast_data"
SERVICE_FORCE_UPDATE = "force_update_forecasts"
SERVICE_GET_DAMPENING = "get_dampening"
SERVICE_QUERY_FORECAST_DATA = "query_forecast_data"
SERVICE_REMOVE_HARD_LIMIT = "remove_hard_limit"
SERVICE_SET_DAMPENING = "set_dampening"
SERVICE_SET_HARD_LIMIT = "set_hard_limit"
SERVICE_UPDATE = "update_forecasts"
SITE_DAMP = "site_damp"
SOLCAST_URL = "https://api.solcast.com.au"
TITLE = "Solcast Solar"