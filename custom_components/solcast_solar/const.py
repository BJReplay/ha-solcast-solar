"""Constants for the Solcast Solar integration."""

from typing import Any, Final

# Development flags
SENSOR_UPDATE_LOGGING: bool = False

# Integration constants
API_QUOTA: Final[str] = "api_quota"
ATTR_ENTRY_TYPE: Final[str] = "entry_type"
ATTRIBUTION: Final[str] = "Data retrieved from Solcast"
AUTO_DAMPEN: Final[str] = "auto_dampen"
AUTO_UPDATE: Final[str] = "auto_update"
BRK_ESTIMATE: Final[str] = "attr_brk_estimate"
BRK_ESTIMATE10: Final[str] = "attr_brk_estimate10"
BRK_ESTIMATE90: Final[str] = "attr_brk_estimate90"
BRK_HALFHOURLY: Final[str] = "attr_brk_halfhourly"
BRK_HOURLY: Final[str] = "attr_brk_hourly"
BRK_SITE: Final[str] = "attr_brk_site"
BRK_SITE_DETAILED: Final[str] = "attr_brk_detailed"
CONFIG_DAMP: Final[str] = "config_damp"
CONFIG_VERSION: Final[int] = 18
CUSTOM_HOUR_SENSOR: Final[str] = "customhoursensor"
DAMP_FACTOR: Final[str] = "damp_factor"
DAMPENING_INSIGNIFICANT: Final[float] = 0.95  # Dampening factors considered insignificant for automated dampening
DAMPENING_INSIGNIFICANT_ADJ: Final[float] = 0.95  # Adjusted dampening factors considered insignificant for automated dampening
DAMPENING_LOG_DELTA_CORRECTIONS: Final[bool] = True  # Whether to logarithmically adjust applied automated dampening factors
DAMPENING_MINIMUM_GENERATION: Final[int] = 2  # Minimum number of matching intervals with generation data to consider
DAMPENING_MINIMUM_INTERVALS: Final[int] = 2  # Minimum number of matching intervals to consider for automated dampening
DAMPENING_MODEL_DAYS: Final[int] = 14  # Number of days over which to model automated dampening
DAMPENING_NO_LIMITING_CONSISTENCY: Final[bool] = False  # Whether to ignore intervals that have been limited at least once
DAMPENING_SIMILAR_PEAK: Final[float] = 0.90  # Factor to consider similar estimated actual peak generation for automated dampening
DATE_MONTH_DAY: Final[str] = "%m-%d"
DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"
DATE_FORMAT_UTC: Final[str] = "%Y-%m-%d %H:%M:%S UTC"
DATE_ONLY_FORMAT: Final[str] = "%Y-%m-%d"
DOMAIN: Final[str] = "solcast_solar"
ENTRY_TYPE_SERVICE: Final[str] = "service"
ESTIMATED_ACTUALS_FETCH_DELAY: Final[int] = 0  # Minutes to wait after midnight before fetching estimated actuals (plus random offset)
EVENT_END_DATETIME: Final[str] = "end_date_time"
EVENT_START_DATETIME: Final[str] = "start_date_time"
EXCLUDE_SITES: Final[str] = "exclude_sites"
FORECAST_DAYS: Final[int] = 14  # Minimum 8, maximum 14
FORECAST_DAY_SENSORS: Final[int] = 8  # Minimum 8, maximum 14
GENERATION_ENTITIES: Final[str] = "generation_entities"
GENERATION_HISTORY_LOAD_DAYS: Final[int] = 7  # Number of days of generation history to load when no data present
GENERATION_VERSION: Final[int] = 1
GET_ACTUALS: Final[str] = "get_actuals"
HARD_LIMIT: Final[str] = "hard_limit"
HARD_LIMIT_API: Final[str] = "hard_limit_api"
HISTORY_MAX: Final[int] = 730  # Maximum number of history days to keep
KEY_ESTIMATE: Final[str] = "key_estimate"
MANUFACTURER: Final[str] = "BJReplay"
SERVICE_CLEAR_DATA: Final[str] = "clear_all_solcast_data"
SERVICE_FORCE_UPDATE_ESTIMATES: Final[str] = "force_update_estimates"
SERVICE_FORCE_UPDATE_FORECASTS: Final[str] = "force_update_forecasts"
SERVICE_GET_DAMPENING: Final[str] = "get_dampening"
SERVICE_QUERY_ESTIMATE_DATA: Final[str] = "query_estimate_data"
SERVICE_QUERY_FORECAST_DATA: Final[str] = "query_forecast_data"
SERVICE_REMOVE_HARD_LIMIT: Final[str] = "remove_hard_limit"
SERVICE_SET_DAMPENING: Final[str] = "set_dampening"
SERVICE_SET_HARD_LIMIT: Final[str] = "set_hard_limit"
SERVICE_UPDATE: Final[str] = "update_forecasts"
TIME_FORMAT: Final[str] = "%H:%M:%S"
SITE: Final[str] = "site"
SITE_DAMP: Final[str] = "site_damp"
SITE_EXPORT_ENTITY: Final[str] = "site_export_entity"
SITE_EXPORT_LIMIT: Final[str] = "site_export_limit"
SOLCAST_URL: Final[str] = "https://api.solcast.com.au"
TITLE: Final[str] = "Solcast Solar"
UNDAMPENED: Final[str] = "undampened"
USE_ACTUALS: Final[str] = "use_actuals"
WINTER_TIME: Final[list[str]] = ["Europe/Dublin"]  # Zones that use "Winter time" rather than "Daylight time"

ADVANCED_OPTIONS: dict[str, dict[str, Any]] = {
    "automated_dampening_delta_adjustment_model": {"type": "int", "min": 0, "max": 0, "default": 0},
    "automated_dampening_generation_history_load_days": {"type": "int", "min": 1, "max": 21, "default": GENERATION_HISTORY_LOAD_DAYS},
    "automated_dampening_ignore_intervals": {"type": "list", "default": []},
    "automated_dampening_insignificant_factor": {"type": "float", "min": 0.0, "max": 1.0, "default": DAMPENING_INSIGNIFICANT},
    "automated_dampening_insignificant_factor_adjusted": {"type": "float", "min": 0.0, "max": 1.0, "default": DAMPENING_INSIGNIFICANT_ADJ},
    "automated_dampening_minimum_matching_generation": {"type": "int", "min": 1, "max": 21, "default": DAMPENING_MINIMUM_GENERATION},
    "automated_dampening_minimum_matching_intervals": {"type": "int", "min": 1, "max": 21, "default": DAMPENING_MINIMUM_INTERVALS},
    "automated_dampening_model_days": {"type": "int", "min": 2, "max": 21, "default": DAMPENING_MODEL_DAYS},
    "automated_dampening_no_delta_corrections": {"type": "bool", "default": not DAMPENING_LOG_DELTA_CORRECTIONS},
    "automated_dampening_no_limiting_consistency": {"type": "bool", "default": DAMPENING_NO_LIMITING_CONSISTENCY},
    "automated_dampening_similar_peak": {"type": "float", "min": 0.0, "max": 1.0, "default": DAMPENING_SIMILAR_PEAK},
    "entity_logging": {"type": "bool", "default": SENSOR_UPDATE_LOGGING},
    "estimated_actuals_fetch_delay": {"type": "int", "min": 0, "max": 120, "default": ESTIMATED_ACTUALS_FETCH_DELAY},
    "forecast_future_days": {"type": "int", "min": 8, "max": 14, "default": FORECAST_DAYS},
    "forecast_day_entities": {"type": "int", "min": 8, "max": 14, "default": FORECAST_DAY_SENSORS},
    "forecast_history_max_days": {"type": "int", "min": 22, "max": 3650, "default": HISTORY_MAX},
    "reload_on_advanced_change": {"type": "bool", "default": False},
    "solcast_url": {"type": "str", "default": SOLCAST_URL},
}
