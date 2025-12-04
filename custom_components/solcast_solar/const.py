"""Constants for the Solcast Solar integration."""

import types
from typing import Any, Final

# Development flags
SENSOR_UPDATE_LOGGING: Final[bool] = False

# Integration constants
ACTION: Final[str] = "action"
ADVANCED_OPTION = types.SimpleNamespace()
ADVANCED_OPTION.BOOL = "bool"
ADVANCED_OPTION.INT = "int"
ADVANCED_OPTION.FLOAT = "float"
ADVANCED_OPTION.LIST_INT = "list_int"
ADVANCED_OPTION.LIST_TIME = "list_time"
ADVANCED_OPTION.STR = "str"
ADVANCED_OPTION.TIME = "time"
ADVANCED_TYPE: Final[str] = "type"
ADVANCED_API_RAISE_ISSUES: Final[str] = "api_raise_issues"
ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL: Final[str] = "automated_dampening_delta_adjustment_model"
ADVANCED_AUTOMATED_DAMPENING_GENERATION_FETCH_DELAY: Final[str] = "automated_dampening_generation_fetch_delay"
ADVANCED_AUTOMATED_DAMPENING_GENERATION_HISTORY_LOAD_DAYS: Final[str] = "automated_dampening_generation_history_load_days"
ADVANCED_AUTOMATED_DAMPENING_IGNORE_INTERVALS: Final[str] = "automated_dampening_ignore_intervals"
ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR: Final[str] = "automated_dampening_insignificant_factor"
ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR_ADJUSTED: Final[str] = "automated_dampening_insignificant_factor_adjusted"
ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_GENERATION: Final[str] = "automated_dampening_minimum_matching_generation"
ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_INTERVALS: Final[str] = "automated_dampening_minimum_matching_intervals"
ADVANCED_AUTOMATED_DAMPENING_MODEL: Final[str] = "automated_dampening_model"
ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS: Final[str] = "automated_dampening_model_days"
ADVANCED_AUTOMATED_DAMPENING_NO_DELTA_CORRECTIONS: Final[str] = "automated_dampening_no_delta_corrections"
ADVANCED_AUTOMATED_DAMPENING_NO_LIMITING_CONSISTENCY: Final[str] = "automated_dampening_no_limiting_consistency"
ADVANCED_AUTOMATED_DAMPENING_PRESERVE_UNMATCHED_FACTORS: Final[str] = "automated_dampening_preserve_unmatched_factors"
ADVANCED_AUTOMATED_DAMPENING_SIMILAR_PEAK: Final[str] = "automated_dampening_similar_peak"
ADVANCED_AUTOMATED_DAMPENING_SUPPRESSION_ENTITY: Final[str] = "automated_dampening_suppression_entity"
ADVANCED_ENTITY_LOGGING: Final[str] = "entity_logging"
ADVANCED_ESTIMATED_ACTUALS_FETCH_DELAY: Final[str] = "estimated_actuals_fetch_delay"
ADVANCED_ESTIMATED_ACTUALS_LOG_APE_PERCENTILES: Final[str] = "estimated_actuals_log_ape_percentiles"
ADVANCED_ESTIMATED_ACTUALS_LOG_MAPE_BREAKDOWN: Final[str] = "estimated_actuals_log_mape_breakdown"
ADVANCED_FORECAST_FUTURE_DAYS: Final[str] = "forecast_future_days"
ADVANCED_FORECAST_DAY_ENTITIES: Final[str] = "forecast_day_entities"
ADVANCED_FORECAST_HISTORY_MAX_DAYS: Final[str] = "forecast_history_max_days"
ADVANCED_RELOAD_ON_ADVANCED_CHANGE: Final[str] = "reload_on_advanced_change"
ADVANCED_SOLCAST_URL: Final[str] = "solcast_url"
ADVANCED_TRIGGER_ON_API_AVAILABLE: Final[str] = "trigger_on_api_available"
ADVANCED_TRIGGER_ON_API_UNAVAILABLE: Final[str] = "trigger_on_api_unavailable"
ADVANCED_USER_AGENT: Final[str] = "user_agent"
ALL: Final[str] = "all"
API_KEY: Final[str] = "api_key"
API_QUOTA: Final[str] = "api_quota"
API_UNAVAILABLE: Final[str] = "api_unavailable"
ATTR_ENTRY_TYPE: Final[str] = "entry_type"
ATTRIBUTION: Final[str] = "Data retrieved from Solcast"
AUTO_DAMPEN: Final[str] = "auto_dampen"
AUTO_UPDATE: Final[str] = "auto_update"
AUTO_UPDATE_DIVISIONS: Final[str] = "auto_update_divisions"
AUTO_UPDATE_QUEUE: Final[str] = "auto_update_queue"
AUTO_UPDATED: Final[str] = "auto_updated"
AZIMUTH: Final[str] = "azimuth"
BASE: Final[str] = "base"
BRK_ESTIMATE: Final[str] = "attr_brk_estimate"
BRK_ESTIMATE10: Final[str] = "attr_brk_estimate10"
BRK_ESTIMATE90: Final[str] = "attr_brk_estimate90"
BRK_HALFHOURLY: Final[str] = "attr_brk_halfhourly"
BRK_HOURLY: Final[str] = "attr_brk_hourly"
BRK_SITE: Final[str] = "attr_brk_site"
BRK_SITE_DETAILED: Final[str] = "attr_brk_detailed"
CAPACITY: Final[str] = "capacity"
CAPACITY_DC: Final[str] = "capacity_dc"
COMPLETION: Final[str] = "completion"
CONFIG_DAMP: Final[str] = "config_damp"
CONFIG_DISCRETE_NAME: Final[str] = "solcast_solar"
CONFIG_FOLDER_DISCRETE: Final[bool] = True  # Whether to use a sub-folder for config files
CONFIG_VERSION: Final[int] = 18
CORRECT: Final[str] = "correct"
CUSTOM_HOURS: Final[str] = "custom_hours"
CUSTOM_HOUR_SENSOR: Final[str] = "customhoursensor"
DAILY_LIMIT: Final[str] = "daily_limit"
DAILY_LIMIT_CONSUMED: Final[str] = "daily_limit_consumed"
DAMP_FACTOR: Final[str] = "damp_factor"
DAMPENING_FACTOR: Final[str] = "dampening_factor"
DATA_CORRECT: Final[str] = "dataCorrect"
DATA_SET_ACTUALS: Final[str] = "actuals"
DATA_SET_ACTUALS_UNDAMPENED: Final[str] = "undampened actuals"
DATA_SET_FORECAST: Final[str] = "forecast"
DATA_SET_FORECAST_UNDAMPENED: Final[str] = "undampened forecast"
DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"
DATE_FORMAT_UTC: Final[str] = "%Y-%m-%d %H:%M:%S UTC"
DATE_MONTH_DAY: Final[str] = "%m-%d"
DATE_ONLY_FORMAT: Final[str] = "%Y-%m-%d"
DAY_NAME: Final[str] = "dayname"
DEFAULT: Final[str] = "default"
DEFAULT_DAMPENING_DELTA_ADJUSTMENT_MODEL: Final[int] = 0  # Logarithmic adjustment is default model
DEFAULT_DAMPENING_INSIGNIFICANT: Final[float] = 0.95  # Dampening factors considered insignificant for automated dampening
DEFAULT_DAMPENING_INSIGNIFICANT_ADJ: Final[float] = 0.95  # Adjusted dampening factors considered insignificant for automated dampening
DEFAULT_DAMPENING_LOG_DELTA_CORRECTIONS: Final[bool] = True  # Whether to logarithmically adjust applied automated dampening factors
DEFAULT_DAMPENING_MINIMUM_GENERATION: Final[int] = 2  # Minimum number of matching intervals with generation data to consider
DEFAULT_DAMPENING_MINIMUM_INTERVALS: Final[int] = 2  # Minimum number of matching intervals to consider for automated dampening
DEFAULT_DAMPENING_MODEL: Final[int] = 0  # Damping calculation model (0 = Default, 1 = Max matched, 2 = Mean matched, 3 = Min matched)
DEFAULT_DAMPENING_MODEL_DAYS: Final[int] = 14  # Number of days over which to model automated dampening
DEFAULT_DAMPENING_NO_LIMITING_CONSISTENCY: Final[bool] = False  # Whether to ignore intervals that have been limited at least once
DEFAULT_DAMPENING_SIMILAR_PEAK: Final[float] = 0.90  # Factor to consider similar estimated actual peak generation for automated dampening
DEFAULT_DAMPENING_SUPPRESSION_ENTITY: Final[str] = "solcast_suppress_auto_dampening"  # Entity ID to invalidate generation when active
DEFAULT_ESTIMATED_ACTUALS_FETCH_DELAY: Final[int] = 0  # Minutes to wait after midnight before get estimated actuals (plus random offset)
DEFAULT_FORECAST_DAYS: Final[int] = 14  # Minimum 8, maximum 14
DEFAULT_FORECAST_DAY_SENSORS: Final[int] = 8  # Minimum 8, maximum 14
DEFAULT_GENERATION_FETCH_DELAY: Final[int] = 0  # Minutes to wait after midnight before get past day generation
DEFAULT_GENERATION_HISTORY_LOAD_DAYS: Final[int] = 7  # Number of days of generation history to load when no data present
DEFAULT_HISTORY_MAX: Final[int] = 730  # Maximum number of history days to keep
DEFAULT_SOLCAST_HTTPS_URL: Final[str] = "https://api.solcast.com.au"
DELAYED_RESTART_ON_CRASH: Final[int] = 15  # Minutes to delay restart after crash
DESCRIPTION: Final[str] = "description"
DETAILED_FORECAST: Final[str] = "detailedForecast"
DETAILED_HOURLY: Final[str] = "detailedHourly"
DEVICE_NAME: Final[str] = "device_name"
DISMISSAL: Final[str] = "dismissal"
DOMAIN: Final[str] = "solcast_solar"
EARLIEST_PERIOD: Final[str] = "earliest_period"
ENABLED_BY_DEFAULT: Final[str] = "enabled_by_default"
ENTRY_ID: Final[str] = "entry_id"
ENTRY_OPTIONS: Final[str] = "entry_options"
ENTRY_TYPE_SERVICE: Final[str] = "service"
ERROR_CODE: Final[str] = "error_code"
ESTIMATE: Final[str] = "pv_estimate"
ESTIMATE10: Final[str] = "pv_estimate10"
ESTIMATE90: Final[str] = "pv_estimate90"
ESTIMATED_ACTUALS: Final[str] = "estimated_actuals"
EVENT: Final[str] = "event"
EVENT_END_DATETIME: Final[str] = "end_date_time"
EVENT_START_DATETIME: Final[str] = "start_date_time"
EXCLUDE_SITES: Final[str] = "exclude_sites"
EXPECTED_INTERVALS: Final[str] = "expected_intervals"
EXPORT_LIMITING: Final[str] = "export_limiting"
EXTANT: Final[str] = "extant"
FACTOR: Final[str] = "factor"
FACTORS: Final[str] = "factors"
FAILURE: Final[str] = "failure"
FORECASTS: Final[str] = "forecasts"
FORMAT: Final[str] = "format"
GENERATION: Final[str] = "generation"
GENERATION_ENTITIES: Final[str] = "generation_entities"
GENERATION_VERSION: Final[int] = 1
GET_ACTUALS: Final[str] = "get_actuals"
HARD_LIMIT: Final[str] = "hard_limit"
HARD_LIMIT_API: Final[str] = "hard_limit_api"
HEADERS_ACCEPT: Final[str] = "Accept"
HEADERS_USER_AGENT: Final[str] = "User-Agent"
HOURS: Final[str] = "hours"
IGNORE_AUTO_ENABLED: Final[str] = "ignore_auto_enabled"
INSTALL_DATE: Final[str] = "install_date"
INTEGRATION: Final[str] = "Solcast PV Forecast"
INTEGRATION_AUTOMATED: Final[str] = "integration_automated"
INTERVAL: Final[str] = "interval"
INTERVALS: Final[str] = "intervals"
JSON: Final[str] = "json"
JSON_VERSION: Final[int] = 8
KEY_API_COUNTER: Final[str] = "api_counter"
KEY_API_LIMIT: Final[str] = "api_limit"
KEY_DAMPEN: Final[str] = "dampen"
KEY_ESTIMATE: Final[str] = "key_estimate"
KEY_FORECAST_CUSTOM_HOURS: Final[str] = "forecast_custom_hours"
KEY_FORECAST_NEXT_HOUR: Final[str] = "forecast_next_hour"
KEY_FORECAST_THIS_HOUR: Final[str] = "forecast_this_hour"
KEY_FORECAST_REMAINING_TODAY: Final[str] = "forecast_remaining_today"
KEY_FORECAST_REMAINING_TODAY_OLD: Final[str] = "get_remaining_today"
KEY_LAST_UPDATED: Final[str] = "last_updated"
KEY_LAST_UPDATED_OLD: Final[str] = "lastupdated"
KEY_PEAK_W_TIME_TODAY: Final[str] = "peak_w_time_today"
KEY_PEAK_W_TIME_TOMORROW: Final[str] = "peak_w_time_tomorrow"
KEY_PEAK_W_TODAY: Final[str] = "peak_w_today"
KEY_PEAK_W_TOMORROW: Final[str] = "peak_w_tomorrow"
KEY_POWER_NOW: Final[str] = "power_now"
KEY_POWER_NOW_1HR: Final[str] = "power_now_1hr"
KEY_POWER_NOW_30M: Final[str] = "power_now_30m"
KEY_SITES_DATA: Final[str] = "site_data"
KEY_TOTAL_KWH_FORECAST: Final[str] = "total_kwh_forecast"
KEY_TOTAL_KWH_FORECAST_TODAY: Final[str] = "total_kwh_forecast_today"
KEY_TOTAL_KWH_FORECAST_TOMORROW: Final[str] = "total_kwh_forecast_tomorrow"
LAST_24H: Final[str] = "last_24h"
LAST_7D: Final[str] = "last_7d"
LAST_14D: Final[str] = "last_14d"
LAST_ATTEMPT: Final[str] = "last_attempt"
LAST_PERIOD: Final[str] = "last_period"
LAST_UPDATED: Final[str] = "last_updated"
LATITUDE: Final[str] = "latitude"
LEARN_MORE: Final[str] = "learn_more"
LEARN_MORE_MISSING_FORECAST_DATA: Final[str] = "https://github.com/BJReplay/ha-solcast-solar/blob/main/FAQ.md"
LEARN_MORE_UNUSUAL_AZIMUTH: Final[str] = "https://github.com/BJReplay/ha-solcast-solar?tab=readme-ov-file#solcast-requirements"
LONGITUDE: Final[str] = "longitude"
LOSS_FACTOR: Final[str] = "loss_factor"
MANUFACTURER: Final[str] = "BJReplay"
MAXIMUM: Final[str] = "max"
MESSAGE: Final[str] = "message"
METHOD: Final[str] = "method"
MINIMUM: Final[str] = "min"
NAME: Final[str] = "name"
NEXT_AUTO_UPDATE: Final[str] = "next_auto_update"
NEED_HISTORY_HOURS: Final[str] = "need_history_hours"
OLD_API_KEY: Final[str] = "old_api_key"
OLD_HARD_LIMIT: Final[str] = "old_hard_limit"
OPTION_GREATER_THAN_OR_EQUAL: Final[str] = "greater_than_or_equal"
OPTION_LESS_THAN_OR_EQUAL: Final[str] = "less_than_or_equal"
PERIOD_END: Final[str] = "period_end"
PERIOD_START: Final[str] = "period_start"
PLATFORM_BINARY_SENSOR: Final[str] = "binary_sensor"
PLATFORM_SENSOR: Final[str] = "sensor"
PLATFORM_SWITCH: Final[str] = "switch"
PRESUMED_DEAD: Final[str] = "presumed_dead"
PRIOR_CRASH_EXCEPTION: Final[str] = "prior_crash_exception"
PRIOR_CRASH_PLACEHOLDERS: Final[str] = "prior_crash_placeholders"
PRIOR_CRASH_TIME: Final[str] = "prior_crash_time"
PRIOR_CRASH_TRANSLATION_KEY: Final[str] = "prior_crash_translation_key"
PROPOSAL: Final[str] = "proposal"
RESET: Final[str] = "reset"
RESET_OLD_KEY: Final[str] = "reset_old_key"
RESOURCE_ID: Final[str] = "resource_id"
RESPONSE_STATUS: Final[str] = "response_status"
SCHEMA: Final[str] = "schema"
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
SITE: Final[str] = "site"
SITES: Final[str] = "sites"
SITE_DAMP: Final[str] = "site_damp"
SITE_EXPORT_ENTITY: Final[str] = "site_export_entity"
SITE_EXPORT_LIMIT: Final[str] = "site_export_limit"
SITE_INFO: Final[str] = "siteinfo"
SOLCAST: Final[str] = "solcast"
SUGGESTED_VALUE: Final[str] = "suggested_value"
SUPPORTS_RESPONSE: Final[str] = "supports_response"
TAGS: Final[str] = "tags"
TALLY: Final[str] = "tally"
TASK_ACTUALS_FETCH: Final[str] = "update_actuals"
TASK_CHECK_FETCH: Final[str] = "check_fetch"
TASK_FORECASTS_FETCH: Final[str] = "update_forecasts"
TASK_FORECASTS_FETCH_IMMEDIATE: Final[str] = "update_forecasts_immediate"
TASK_LISTENERS: Final[str] = "listeners"
TASK_MIDNIGHT_UPDATE: Final[str] = "midnight_update"
TASK_NEW_DAY_ACTUALS: Final[str] = "new_day_actuals"
TASK_NEW_DAY_GENERATION: Final[str] = "new_day_generation"
TASK_WATCHDOG_ADVANCED: Final[str] = "watchdog_advanced"
TASK_WATCHDOG_ADVANCED_START: Final[str] = "watchdog_advanced_start"
TASK_WATCHDOG_DAMPENING: Final[str] = "watchdog_dampening"
TASK_WATCHDOG_DAMPENING_LEGACY: Final[str] = "watchdog_dampening_legacy"
TASK_WATCHDOG_DAMPENING_START: Final[str] = "watchdog_dampening_start"
TIME_FORMAT: Final[str] = "%H:%M:%S"
TITLE: Final[str] = "Solcast Solar"
TILT: Final[str] = "tilt"
TOTAL_RECORDS: Final[str] = "total_records"
TRANSLATE_ACTUALS_NOT_ENABLED: Final[str] = "actuals_not_enabled"
TRANSLATE_ACTUALS_WITHOUT_GET: Final[str] = "actuals_without_get"
TRANSLATE_API_DUPLICATE: Final[str] = "api_duplicate"
TRANSLATE_API_LOOKS_LIKE_SITE: Final[str] = "api_looks_like_site"
TRANSLATE_AUTO_USE_FORCE: Final[str] = "auto_use_force"
TRANSLATE_AUTO_USE_NORMAL: Final[str] = "auto_use_normal"
TRANSLATE_BUILD_FAILED_ACTUALS: Final[str] = "build_failed_actuals"
TRANSLATE_BUILD_FAILED_FORECASTS: Final[str] = "build_failed_forecasts"
TRANSLATE_CUSTOM_INVALID: Final[str] = "custom_invalid"
TRANSLATE_DAMP_AUTO_ENABLED: Final[str] = "damp_auto_enabled"
TRANSLATE_DAMP_COUNT_NOT_CORRECT: Final[str] = "damp_count_not_correct"
TRANSLATE_DAMP_NO_ALL_24: Final[str] = "damp_no_all_24"
TRANSLATE_DAMP_NOT_SITE: Final[str] = "damp_not_site"
TRANSLATE_DAMP_ERROR_PARSING: Final[str] = "damp_error_parsing"
TRANSLATE_DAMP_OUTSIDE_RANGE: Final[str] = "damp_outside_range"
TRANSLATE_DAMP_NO_FACTORS: Final[str] = "damp_no_factors"
TRANSLATE_DAMPEN_WITHOUT_ACTUALS: Final[str] = "dampen_without_actuals"
TRANSLATE_DAMPEN_WITHOUT_GENERATION: Final[str] = "dampen_without_generation"
TRANSLATE_ENERGY_HISTORY: Final[str] = "energy_history"
TRANSLATE_EXPORT_MULTIPLE_ENTITIES: Final[str] = "export_multiple_entities"
TRANSLATE_EXPORT_NO_ENTITY: Final[str] = "export_no_entity"
TRANSLATE_HARD_NOT_NUMBER: Final[str] = "hard_not_number"
TRANSLATE_HARD_NOT_POSITIVE_NUMBER: Final[str] = "hard_not_positive_number"
TRANSLATE_HARD_TOO_MANY: Final[str] = "hard_too_many"
TRANSLATE_INTEGRATION_NOT_LOADED: Final[str] = "integration_not_loaded"
TRANSLATE_INTEGRATION_PRIOR_CRASH: Final[str] = "integration_prior_crash"
TRANSLATE_INIT_CANNOT_GET_SITES: Final[str] = "init_cannot_get_sites"
TRANSLATE_INIT_CANNOT_GET_SITES_CACHE_INVALID: Final[str] = "init_cannot_get_sites_cache_invalid"
TRANSLATE_INIT_CORRUPT: Final[str] = "init_corrupt"
TRANSLATE_INIT_INCOMPATIBLE: Final[str] = "init_incompatible"
TRANSLATE_INIT_KEY_INVALID: Final[str] = "init_key_invalid"
TRANSLATE_INIT_NO_SITES: Final[str] = "init_no_sites"
TRANSLATE_INIT_UNKNOWN: Final[str] = "init_unknown"
TRANSLATE_INIT_USAGE_CORRUPT: Final[str] = "init_usage_corrupt"
TRANSLATE_INTERNAL_ERROR: Final[str] = "internal_error"
TRANSLATE_KEY_ESTIMATE: Final[str] = "key_estimate"
TRANSLATE_LIMIT_NOT_NUMBER: Final[str] = "limit_not_number"
TRANSLATE_LIMIT_ONE_OR_GREATER: Final[str] = "limit_one_or_greater"
TRANSLATE_REAUTH_SUCCESSFUL: Final[str] = "reauth_successful"
TRANSLATE_RECONFIGURED: Final[str] = "reconfigured"
TRANSLATE_SINGLE_INSTANCE_ALLOWED: Final[str] = "single_instance_allowed"
UNDAMPENED: Final[str] = "undampened"
UNKNOWN: Final[str] = "unknown"
UNRECORDED_ATTRIBUTES: Final[str] = "unrecorded_attributes"
UNUSUAL_AZIMUTH_NORTHERN: Final[str] = "unusual_azimuth_northern"
UNUSUAL_AZIMUTH_SOUTHERN: Final[str] = "unusual_azimuth_southern"
UPGRADE_FUNCTION: Final[str] = "function"
USE_ACTUALS: Final[str] = "use_actuals"
VALUE: Final[str] = "value"
VERSION: Final[str] = "version"
WINTER_TIME: Final[list[str]] = ["Europe/Dublin"]  # Zones that use "Winter time" rather than "Daylight time"


ADVANCED_OPTIONS: Final[dict[str, dict[str, Any]]] = {
    ADVANCED_API_RAISE_ISSUES: {ADVANCED_TYPE: ADVANCED_OPTION.BOOL, DEFAULT: True},
    ADVANCED_AUTOMATED_DAMPENING_GENERATION_FETCH_DELAY: {
        ADVANCED_TYPE: ADVANCED_OPTION.INT,
        MINIMUM: 0,
        MAXIMUM: 120,
        DEFAULT: DEFAULT_GENERATION_FETCH_DELAY,
        OPTION_LESS_THAN_OR_EQUAL: [ADVANCED_ESTIMATED_ACTUALS_FETCH_DELAY],
    },
    ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL: {
        ADVANCED_TYPE: ADVANCED_OPTION.INT,
        MINIMUM: 0,
        MAXIMUM: 1,
        DEFAULT: DEFAULT_DAMPENING_DELTA_ADJUSTMENT_MODEL,
    },
    ADVANCED_AUTOMATED_DAMPENING_GENERATION_HISTORY_LOAD_DAYS: {
        ADVANCED_TYPE: ADVANCED_OPTION.INT,
        MINIMUM: 1,
        MAXIMUM: 21,
        DEFAULT: DEFAULT_GENERATION_HISTORY_LOAD_DAYS,
    },
    ADVANCED_AUTOMATED_DAMPENING_IGNORE_INTERVALS: {ADVANCED_TYPE: ADVANCED_OPTION.LIST_TIME, DEFAULT: []},
    ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR: {
        ADVANCED_TYPE: ADVANCED_OPTION.FLOAT,
        MINIMUM: 0.0,
        MAXIMUM: 1.0,
        DEFAULT: DEFAULT_DAMPENING_INSIGNIFICANT,
    },
    ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR_ADJUSTED: {
        ADVANCED_TYPE: ADVANCED_OPTION.FLOAT,
        MINIMUM: 0.0,
        MAXIMUM: 1.0,
        DEFAULT: DEFAULT_DAMPENING_INSIGNIFICANT_ADJ,
    },
    ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_GENERATION: {
        ADVANCED_TYPE: ADVANCED_OPTION.INT,
        MINIMUM: 1,
        MAXIMUM: 21,
        DEFAULT: DEFAULT_DAMPENING_MINIMUM_GENERATION,
        OPTION_LESS_THAN_OR_EQUAL: [ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_INTERVALS, ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS],
    },
    ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_INTERVALS: {
        ADVANCED_TYPE: ADVANCED_OPTION.INT,
        MINIMUM: 1,
        MAXIMUM: 21,
        DEFAULT: DEFAULT_DAMPENING_MINIMUM_INTERVALS,
        OPTION_GREATER_THAN_OR_EQUAL: [ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_GENERATION],
        OPTION_LESS_THAN_OR_EQUAL: [ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS],
    },
    ADVANCED_AUTOMATED_DAMPENING_MODEL: {
        ADVANCED_TYPE: ADVANCED_OPTION.INT,
        MINIMUM: 0,
        MAXIMUM: 3,
        DEFAULT: DEFAULT_DAMPENING_MODEL,
    },
    ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS: {
        ADVANCED_TYPE: ADVANCED_OPTION.INT,
        MINIMUM: 2,
        MAXIMUM: 21,
        DEFAULT: DEFAULT_DAMPENING_MODEL_DAYS,
    },
    ADVANCED_AUTOMATED_DAMPENING_NO_DELTA_CORRECTIONS: {
        ADVANCED_TYPE: ADVANCED_OPTION.BOOL,
        DEFAULT: not DEFAULT_DAMPENING_LOG_DELTA_CORRECTIONS,
    },
    ADVANCED_AUTOMATED_DAMPENING_NO_LIMITING_CONSISTENCY: {
        ADVANCED_TYPE: ADVANCED_OPTION.BOOL,
        DEFAULT: DEFAULT_DAMPENING_NO_LIMITING_CONSISTENCY,
    },
    ADVANCED_AUTOMATED_DAMPENING_PRESERVE_UNMATCHED_FACTORS: {
        ADVANCED_TYPE: ADVANCED_OPTION.BOOL,
        DEFAULT: False,
    },
    ADVANCED_AUTOMATED_DAMPENING_SIMILAR_PEAK: {
        ADVANCED_TYPE: ADVANCED_OPTION.FLOAT,
        MINIMUM: 0.0,
        MAXIMUM: 1.0,
        DEFAULT: DEFAULT_DAMPENING_SIMILAR_PEAK,
    },
    ADVANCED_AUTOMATED_DAMPENING_SUPPRESSION_ENTITY: {ADVANCED_TYPE: ADVANCED_OPTION.STR, DEFAULT: DEFAULT_DAMPENING_SUPPRESSION_ENTITY},
    ADVANCED_ENTITY_LOGGING: {ADVANCED_TYPE: ADVANCED_OPTION.BOOL, DEFAULT: SENSOR_UPDATE_LOGGING},
    ADVANCED_ESTIMATED_ACTUALS_FETCH_DELAY: {
        ADVANCED_TYPE: ADVANCED_OPTION.INT,
        MINIMUM: 0,
        MAXIMUM: 120,
        DEFAULT: DEFAULT_ESTIMATED_ACTUALS_FETCH_DELAY,
        OPTION_GREATER_THAN_OR_EQUAL: [ADVANCED_AUTOMATED_DAMPENING_GENERATION_FETCH_DELAY],
    },
    ADVANCED_ESTIMATED_ACTUALS_LOG_APE_PERCENTILES: {ADVANCED_TYPE: ADVANCED_OPTION.LIST_INT, DEFAULT: [50]},
    ADVANCED_ESTIMATED_ACTUALS_LOG_MAPE_BREAKDOWN: {ADVANCED_TYPE: ADVANCED_OPTION.BOOL, DEFAULT: False},
    ADVANCED_FORECAST_FUTURE_DAYS: {ADVANCED_TYPE: ADVANCED_OPTION.INT, MINIMUM: 8, MAXIMUM: 14, DEFAULT: DEFAULT_FORECAST_DAYS},
    ADVANCED_FORECAST_DAY_ENTITIES: {
        ADVANCED_TYPE: ADVANCED_OPTION.INT,
        MINIMUM: 8,
        MAXIMUM: 14,
        DEFAULT: DEFAULT_FORECAST_DAY_SENSORS,
        OPTION_LESS_THAN_OR_EQUAL: [ADVANCED_FORECAST_FUTURE_DAYS],
    },
    ADVANCED_FORECAST_HISTORY_MAX_DAYS: {ADVANCED_TYPE: ADVANCED_OPTION.INT, MINIMUM: 22, MAXIMUM: 3650, DEFAULT: DEFAULT_HISTORY_MAX},
    ADVANCED_RELOAD_ON_ADVANCED_CHANGE: {ADVANCED_TYPE: ADVANCED_OPTION.BOOL, DEFAULT: False},
    ADVANCED_SOLCAST_URL: {ADVANCED_TYPE: ADVANCED_OPTION.STR, DEFAULT: DEFAULT_SOLCAST_HTTPS_URL},
    ADVANCED_TRIGGER_ON_API_AVAILABLE: {ADVANCED_TYPE: ADVANCED_OPTION.STR, DEFAULT: ""},
    ADVANCED_TRIGGER_ON_API_UNAVAILABLE: {ADVANCED_TYPE: ADVANCED_OPTION.STR, DEFAULT: ""},
    ADVANCED_USER_AGENT: {ADVANCED_TYPE: ADVANCED_OPTION.STR, DEFAULT: DEFAULT},
}
