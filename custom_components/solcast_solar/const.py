"""Constants for the Solcast Solar integration."""

import types
from typing import Any, Final

# Development flags
SENSOR_UPDATE_LOGGING: Final[bool] = False

# Integration constants
ACTION: Final[str] = "action"
ADVANCED_INVALID_JSON_TASK: Final[str] = "advanced_invalid_json"
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
ADVANCED_AUTOMATED_DAMPENING_NO_DELTA_ADJUSTMENT: Final[str] = "automated_dampening_no_delta_adjustment"
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
ADVANCED_GRANULAR_DAMPENING_DELTA_ADJUSTMENT: Final[str] = "granular_dampening_delta_adjustment"
ADVANCED_HISTORY_MAX_DAYS: Final[str] = "history_max_days"
ADVANCED_RELOAD_ON_ADVANCED_CHANGE: Final[str] = "reload_on_advanced_change"
ADVANCED_SOLCAST_URL: Final[str] = "solcast_url"
ADVANCED_TRIGGER_ON_API_AVAILABLE: Final[str] = "trigger_on_api_available"
ADVANCED_TRIGGER_ON_API_UNAVAILABLE: Final[str] = "trigger_on_api_unavailable"
ADVANCED_USER_AGENT: Final[str] = "user_agent"
AFFIRMATION_REAUTH_SUCCESSFUL: Final[str] = "reauth_successful"
AFFIRMATION_RECONFIGURED: Final[str] = "reconfigured"
ALIASES: Final[str] = "aliases"
ALL: Final[str] = "all"
API_KEY: Final[str] = "api_key"
API_QUOTA: Final[str] = "api_quota"
ATTR_ENTRY_TYPE: Final[str] = "entry_type"
ATTRIBUTION: Final[str] = "Data retrieved from Solcast"
AUTO_DAMPEN: Final[str] = "auto_dampen"
AUTO_UPDATE: Final[str] = "auto_update"
AUTO_UPDATE_DIVISIONS: Final[str] = "auto_update_divisions"
AUTO_UPDATE_NEXT: Final[str] = "next_auto_update"
AUTO_UPDATE_QUEUE: Final[str] = "auto_update_queue"
AUTO_UPDATED: Final[str] = "auto_updated"
BASE: Final[str] = "base"
BRK_ESTIMATE: Final[str] = "attr_brk_estimate"
BRK_ESTIMATE10: Final[str] = "attr_brk_estimate10"
BRK_ESTIMATE90: Final[str] = "attr_brk_estimate90"
BRK_HALFHOURLY: Final[str] = "attr_brk_halfhourly"
BRK_HOURLY: Final[str] = "attr_brk_hourly"
BRK_SITE: Final[str] = "attr_brk_site"
BRK_SITE_DETAILED: Final[str] = "attr_brk_detailed"
COMPLETION: Final[str] = "completion"
CONFIG_DAMP: Final[str] = "config_damp"
CONFIG_DISCRETE_NAME: Final[str] = "solcast_solar"
CONFIG_FOLDER_DISCRETE: Final[bool] = True  # Whether to use a sub-folder for config files
CONFIG_VERSION: Final[int] = 18
CURRENT_NAME: Final[str] = "current_name"
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
DAY_NAME: Final[str] = "dayname"
DEFAULT: Final[str] = "default"
DEFAULT_DAMPENING_DELTA_ADJUSTMENT_MODEL: Final[int] = 0  # Logarithmic adjustment is default model
DEFAULT_DAMPENING_INSIGNIFICANT: Final[float] = 0.95  # Dampening factors considered insignificant for automated dampening
DEFAULT_DAMPENING_INSIGNIFICANT_ADJ: Final[float] = 0.95  # Adjusted dampening factors considered insignificant for automated dampening
DEFAULT_DAMPENING_LOG_DELTA_ADJUSTMENT: Final[bool] = True  # Whether to logarithmically adjust applied automated dampening factors
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
DEFAULT_GRANULAR_DAMPENING_DELTA_ADJUSTMENT: Final[bool] = False  # Whether to use delta adjustment for granular dampening
DEFAULT_HISTORY_MAX: Final[int] = 730  # Maximum number of history days to keep
DEFAULT_SOLCAST_HTTPS_URL: Final[str] = "https://api.solcast.com.au"
DELAYED_RESTART_ON_CRASH: Final[int] = 15  # Minutes to delay restart after crash
DEPRECATED: Final[str] = "deprecated"
DESCRIPTION: Final[str] = "description"
DETAILED_FORECAST: Final[str] = "detailedForecast"
DETAILED_HOURLY: Final[str] = "detailedHourly"
DEVICE_NAME: Final[str] = "device_name"
DISMISSAL: Final[str] = "dismissal"
DOMAIN: Final[str] = "solcast_solar"
DT_DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"
DT_DATE_FORMAT_UTC: Final[str] = "%Y-%m-%d %H:%M:%S UTC"
DT_DATE_MONTH_DAY: Final[str] = "%m-%d"
DT_DATE_ONLY_FORMAT: Final[str] = "%Y-%m-%d"
DT_TIME_FORMAT: Final[str] = "%H:%M:%S"
ENABLED_BY_DEFAULT: Final[str] = "enabled_by_default"
ENERGY_HISTORY: Final[str] = "energy_history"
ENTITY_API_COUNTER: Final[str] = "api_counter"
ENTITY_API_LIMIT: Final[str] = "api_limit"
ENTITY_DAMPEN: Final[str] = "dampen"
ENTITY_FORECAST_CUSTOM_HOURS: Final[str] = "forecast_custom_hours"
ENTITY_FORECAST_NEXT_HOUR: Final[str] = "forecast_next_hour"
ENTITY_FORECAST_THIS_HOUR: Final[str] = "forecast_this_hour"
ENTITY_FORECAST_REMAINING_TODAY: Final[str] = "forecast_remaining_today"
ENTITY_FORECAST_REMAINING_TODAY_OLD: Final[str] = "get_remaining_today"
ENTITY_LAST_UPDATED: Final[str] = "last_updated"
ENTITY_LAST_UPDATED_OLD: Final[str] = "lastupdated"
ENTITY_PEAK_W_TIME_TODAY: Final[str] = "peak_w_time_today"
ENTITY_PEAK_W_TIME_TOMORROW: Final[str] = "peak_w_time_tomorrow"
ENTITY_PEAK_W_TODAY: Final[str] = "peak_w_today"
ENTITY_PEAK_W_TOMORROW: Final[str] = "peak_w_tomorrow"
ENTITY_POWER_NOW: Final[str] = "power_now"
ENTITY_POWER_NOW_1HR: Final[str] = "power_now_1hr"
ENTITY_POWER_NOW_30M: Final[str] = "power_now_30m"
ENTITY_TOTAL_KWH_FORECAST: Final[str] = "total_kwh_forecast"
ENTITY_TOTAL_KWH_FORECAST_TODAY: Final[str] = "total_kwh_forecast_today"
ENTITY_TOTAL_KWH_FORECAST_TOMORROW: Final[str] = "total_kwh_forecast_tomorrow"
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
EXCEPTION_ACTUALS_NOT_ENABLED: Final[str] = "actuals_not_enabled"
EXCEPTION_ACTUALS_WITHOUT_GET: Final[str] = "actuals_without_get"
EXCEPTION_API_DUPLICATE: Final[str] = "api_duplicate"
EXCEPTION_API_LOOKS_LIKE_SITE: Final[str] = "api_looks_like_site"
EXCEPTION_AUTO_USE_FORCE: Final[str] = "auto_use_force"
EXCEPTION_AUTO_USE_NORMAL: Final[str] = "auto_use_normal"
EXCEPTION_BUILD_FAILED_ACTUALS: Final[str] = "build_failed_actuals"
EXCEPTION_BUILD_FAILED_FORECASTS: Final[str] = "build_failed_forecasts"
EXCEPTION_CUSTOM_INVALID: Final[str] = "custom_invalid"
EXCEPTION_DAMP_AUTO_ENABLED: Final[str] = "damp_auto_enabled"
EXCEPTION_DAMP_COUNT_NOT_CORRECT: Final[str] = "damp_count_not_correct"
EXCEPTION_DAMP_NO_ALL_24: Final[str] = "damp_no_all_24"
EXCEPTION_DAMP_NOT_SITE: Final[str] = "damp_not_site"
EXCEPTION_DAMP_ERROR_PARSING: Final[str] = "damp_error_parsing"
EXCEPTION_DAMP_OUTSIDE_RANGE: Final[str] = "damp_outside_range"
EXCEPTION_DAMP_NO_FACTORS: Final[str] = "damp_no_factors"
EXCEPTION_DAMPEN_WITHOUT_ACTUALS: Final[str] = "dampen_without_actuals"
EXCEPTION_DAMPEN_WITHOUT_GENERATION: Final[str] = "dampen_without_generation"
EXCEPTION_EXPORT_MULTIPLE_ENTITIES: Final[str] = "export_multiple_entities"
EXCEPTION_EXPORT_NO_ENTITY: Final[str] = "export_no_entity"
EXCEPTION_HARD_NOT_NUMBER: Final[str] = "hard_not_number"
EXCEPTION_HARD_NOT_POSITIVE_NUMBER: Final[str] = "hard_not_positive_number"
EXCEPTION_HARD_TOO_MANY: Final[str] = "hard_too_many"
EXCEPTION_INTEGRATION_NOT_LOADED: Final[str] = "integration_not_loaded"
EXCEPTION_INTEGRATION_PRIOR_CRASH: Final[str] = "integration_prior_crash"
EXCEPTION_INIT_CANNOT_GET_SITES: Final[str] = "init_cannot_get_sites"
EXCEPTION_INIT_CANNOT_GET_SITES_CACHE_INVALID: Final[str] = "init_cannot_get_sites_cache_invalid"
EXCEPTION_INIT_CORRUPT: Final[str] = "init_corrupt"
EXCEPTION_INIT_INCOMPATIBLE: Final[str] = "init_incompatible"
EXCEPTION_INIT_KEY_INVALID: Final[str] = "init_key_invalid"
EXCEPTION_INIT_NO_SITES: Final[str] = "init_no_sites"
EXCEPTION_INIT_UNKNOWN: Final[str] = "init_unknown"
EXCEPTION_INIT_USAGE_CORRUPT: Final[str] = "init_usage_corrupt"
EXCEPTION_INTERNAL_ERROR: Final[str] = "internal_error"
EXCEPTION_LIMIT_NOT_NUMBER: Final[str] = "limit_not_number"
EXCEPTION_LIMIT_ONE_OR_GREATER: Final[str] = "limit_one_or_greater"
EXCEPTION_SINGLE_INSTANCE_ALLOWED: Final[str] = "single_instance_allowed"
EXCLUDE_SITES: Final[str] = "exclude_sites"
EXPORT_LIMITING: Final[str] = "export_limiting"
EXTANT: Final[str] = "extant"
FACTOR: Final[str] = "factor"
FACTORS: Final[str] = "factors"
FAILURE: Final[str] = "failure"
FILES: Final[str] = "files"
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
INTEGRATION: Final[str] = "Solcast PV Forecast"
INTEGRATION_AUTOMATED: Final[str] = "integration_automated"
INTERVAL: Final[str] = "interval"
ISSUE_API_UNAVAILABLE: Final[str] = "api_unavailable"
ISSUE_ADVANCED_DEPRECATED: Final[str] = "advanced_deprecated"
ISSUE_ADVANCED_PROBLEM: Final[str] = "advanced_problem"
ISSUE_CORRUPT_FILE: Final[str] = "corrupt_file"
ISSUE_RECORDS_MISSING: Final[str] = "records_missing"
ISSUE_RECORDS_MISSING_FIXABLE: Final[str] = "records_missing_fixable"
ISSUE_RECORDS_MISSING_INITIAL: Final[str] = "records_missing_initial"
ISSUE_RECORDS_MISSING_UNFIXABLE: Final[str] = "records_missing_unfixable"
ISSUE_UNUSUAL_AZIMUTH_NORTHERN: Final[str] = "unusual_azimuth_northern"
ISSUE_UNUSUAL_AZIMUTH_SOUTHERN: Final[str] = "unusual_azimuth_southern"
JSON: Final[str] = "json"
JSON_VERSION: Final[int] = 8
KEY_ESTIMATE: Final[str] = "key_estimate"
LAST_ATTEMPT: Final[str] = "last_attempt"
LAST_UPDATED: Final[str] = "last_updated"
NAME: Final[str] = "name"
NEW_OPTION: Final[str] = "new_option"
LAST_24H: Final[str] = "last_24h"
LAST_7D: Final[str] = "last_7d"
LAST_14D: Final[str] = "last_14d"
LEARN_MORE: Final[str] = "learn_more"
LEARN_MORE_ADVANCED: Final[str] = "https://github.com/BJReplay/ha-solcast-solar/blob/main/ADVOPTIONS.md"
LEARN_MORE_CORRUPT_FILE: Final[str] = "https://github.com/BJReplay/ha-solcast-solar?tab=readme-ov-file#known-issues"
LEARN_MORE_MISSING_FORECAST_DATA: Final[str] = "https://github.com/BJReplay/ha-solcast-solar/blob/main/FAQ.md"
LEARN_MORE_UNUSUAL_AZIMUTH: Final[str] = "https://github.com/BJReplay/ha-solcast-solar?tab=readme-ov-file#solcast-requirements"
MANUFACTURER: Final[str] = "BJReplay"
MAXIMUM: Final[str] = "max"
MESSAGE: Final[str] = "message"
METHOD: Final[str] = "method"
MINIMUM: Final[str] = "min"
NEED_HISTORY_HOURS: Final[str] = "need_history_hours"
OLD_API_KEY: Final[str] = "old_api_key"
OLD_HARD_LIMIT: Final[str] = "old_hard_limit"
OPTION: Final[str] = "option"
OPTION_GREATER_THAN_OR_EQUAL: Final[str] = "greater_than_or_equal"
OPTION_LESS_THAN_OR_EQUAL: Final[str] = "less_than_or_equal"
OPTION_NOT_SET_IF: Final[str] = "not_set_if"
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
PROBLEMS: Final[str] = "problems"
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
SITE_ATTRIBUTE_AZIMUTH: Final[str] = "azimuth"
SITE_ATTRIBUTE_CAPACITY: Final[str] = "capacity"
SITE_ATTRIBUTE_CAPACITY_DC: Final[str] = "capacity_dc"
SITE_ATTRIBUTE_INSTALL_DATE: Final[str] = "install_date"
SITE_ATTRIBUTE_LATITUDE: Final[str] = "latitude"
SITE_ATTRIBUTE_LONGITUDE: Final[str] = "longitude"
SITE_ATTRIBUTE_LOSS_FACTOR: Final[str] = "loss_factor"
SITE_ATTRIBUTE_TAGS: Final[str] = "tags"
SITE_ATTRIBUTE_TILT: Final[str] = "tilt"
SITES: Final[str] = "sites"
SITES_DATA: Final[str] = "site_data"
SITE_DAMP: Final[str] = "site_damp"
SITE_EXPORT_ENTITY: Final[str] = "site_export_entity"
SITE_EXPORT_LIMIT: Final[str] = "site_export_limit"
SITE_INFO: Final[str] = "siteinfo"
SOLCAST: Final[str] = "solcast"
STOPS_WORKING: Final[str] = "stops_working"
SUGGESTED_VALUE: Final[str] = "suggested_value"
SUPPORTS_RESPONSE: Final[str] = "supports_response"
TASK_ACTUALS_FETCH: Final[str] = "update_actuals"
TASK_CHECK_FETCH: Final[str] = "check_fetch"
TASK_FORECASTS_FETCH: Final[str] = "update_forecasts"
TASK_FORECASTS_FETCH_IMMEDIATE: Final[str] = "update_forecasts_immediate"
TASK_LISTENERS: Final[str] = "listeners"
TASK_MIDNIGHT_UPDATE: Final[str] = "midnight_update"
TASK_NEW_DAY_ACTUALS: Final[str] = "new_day_actuals"
TASK_NEW_DAY_GENERATION: Final[str] = "new_day_generation"
TASK_WATCHDOG_ADVANCED: Final[str] = "watchdog_advanced"
TASK_WATCHDOG_ADVANCED_FILE_CHANGE: Final[str] = "watchdog_advanced_file_change"
TASK_WATCHDOG_DAMPENING: Final[str] = "watchdog_dampening"
TASK_WATCHDOG_DAMPENING_LEGACY: Final[str] = "watchdog_dampening_legacy"
TASK_WATCHDOG_DAMPENING_FILE_CHANGE: Final[str] = "watchdog_dampening_file_change"
TITLE: Final[str] = "Solcast Solar"
TOTAL_RECORDS: Final[str] = "total_records"
UNDAMPENED: Final[str] = "undampened"
UNKNOWN: Final[str] = "unknown"
UNRECORDED_ATTRIBUTES: Final[str] = "unrecorded_attributes"
UPGRADE_FUNCTION: Final[str] = "upgrade_function"
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
    ADVANCED_AUTOMATED_DAMPENING_NO_DELTA_ADJUSTMENT: {
        ADVANCED_TYPE: ADVANCED_OPTION.BOOL,
        DEFAULT: not DEFAULT_DAMPENING_LOG_DELTA_ADJUSTMENT,
        ALIASES: [{NAME: "automated_dampening_no_delta_corrections", DEPRECATED: True}],
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
    ADVANCED_HISTORY_MAX_DAYS: {
        ADVANCED_TYPE: ADVANCED_OPTION.INT,
        MINIMUM: 22,
        MAXIMUM: 3650,
        DEFAULT: DEFAULT_HISTORY_MAX,
        ALIASES: [
            {
                NAME: "forecast_history_max_days",
                DEPRECATED: True,
                # STOPS_WORKING: "2026-05-01", # Example of when to stop supporting deprecated alias
            }
        ],
    },
    ADVANCED_GRANULAR_DAMPENING_DELTA_ADJUSTMENT: {
        ADVANCED_TYPE: ADVANCED_OPTION.BOOL,
        DEFAULT: DEFAULT_GRANULAR_DAMPENING_DELTA_ADJUSTMENT,
        OPTION_NOT_SET_IF: [ADVANCED_AUTOMATED_DAMPENING_NO_DELTA_ADJUSTMENT],
    },
    ADVANCED_RELOAD_ON_ADVANCED_CHANGE: {ADVANCED_TYPE: ADVANCED_OPTION.BOOL, DEFAULT: False},
    ADVANCED_SOLCAST_URL: {ADVANCED_TYPE: ADVANCED_OPTION.STR, DEFAULT: DEFAULT_SOLCAST_HTTPS_URL},
    ADVANCED_TRIGGER_ON_API_AVAILABLE: {ADVANCED_TYPE: ADVANCED_OPTION.STR, DEFAULT: ""},
    ADVANCED_TRIGGER_ON_API_UNAVAILABLE: {ADVANCED_TYPE: ADVANCED_OPTION.STR, DEFAULT: ""},
    ADVANCED_USER_AGENT: {ADVANCED_TYPE: ADVANCED_OPTION.STR, DEFAULT: DEFAULT},
}
