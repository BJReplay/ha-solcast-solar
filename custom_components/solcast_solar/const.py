"""Constants for the Solcast Solar integration."""

from __future__ import annotations

from typing import Final

# Development flags
FORECAST_DEBUG_LOGGING: Final = False
SENSOR_DEBUG_LOGGING: Final = False
SENSOR_UPDATE_LOGGING: Final = False
SPLINE_DEBUG_LOGGING: Final = False

# Integration constants
API_QUOTA: Final = "api_quota"
ATTR_ENTRY_TYPE: Final = "entry_type"
ATTRIBUTION: Final = "Data retrieved from Solcast"
AUTO_UPDATE = "auto_update"
BRK_ESTIMATE: Final = "attr_brk_estimate"
BRK_ESTIMATE10: Final = "attr_brk_estimate10"
BRK_ESTIMATE90: Final = "attr_brk_estimate90"
BRK_HALFHOURLY: Final = "attr_brk_halfhourly"
BRK_HOURLY: Final = "attr_brk_hourly"
BRK_SITE: Final = "attr_brk_site"
BRK_SITE_DETAILED: Final = "attr_brk_detailed"
CONFIG_DAMP: Final = "config_damp"
CUSTOM_HOUR_SENSOR: Final = "customhoursensor"
TIME_FORMAT: Final = "%H:%M:%S"
DATE_FORMAT: Final = "%Y-%m-%d %H:%M:%S"
DATE_FORMAT_UTC: Final = "%Y-%m-%d %H:%M:%S UTC"
DOMAIN: Final = "solcast_solar"
ENTRY_TYPE_SERVICE: Final = "service"
HARD_LIMIT: Final = "hard_limit"
HARD_LIMIT_API: Final = "hard_limit_api"
INIT_MSG: Final = """This is a custom integration. When troubleshooting a problem, after
reviewing open and closed issues, and the discussions, check any
automation is functioning correctly (unless auto-update is
enabled). Troubleshooting tips available at:
https://github.com/BJReplay/ha-solcast-solar/discussions/38

Beta versions may also have addressed issues so look at those.

If all else fails, then open an issue and our community will try to
help: https://github.com/BJReplay/ha-solcast-solar/issues"""
KEY_ESTIMATE: Final = "key_estimate"
MANUFACTURER: Final = "BJReplay"
SERVICE_CLEAR_DATA: Final = "clear_all_solcast_data"
SERVICE_FORCE_UPDATE: Final = "force_update_forecasts"
SERVICE_GET_DAMPENING: Final = "get_dampening"
SERVICE_QUERY_FORECAST_DATA: Final = "query_forecast_data"
SERVICE_REMOVE_HARD_LIMIT: Final = "remove_hard_limit"
SERVICE_SET_DAMPENING: Final = "set_dampening"
SERVICE_SET_HARD_LIMIT: Final = "set_hard_limit"
SERVICE_UPDATE: Final = "update_forecasts"
SITE_DAMP: Final = "site_damp"
SOLCAST_URL: Final = "https://api.solcast.com.au"
TITLE: Final = "Solcast Solar"
