"""Utility."""

# pylint: disable=consider-using-enumerate

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime as dt, timedelta, tzinfo
from enum import Enum
import json
import logging
import math
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, NamedTuple

from homeassistant.const import ATTR_ENTITY_ID, CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import IntegrationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    API_LIMIT,
    AUTO_UPDATE,
    AUTO_UPDATED,
    CUSTOM_HOURS,
    DOMAIN,
    DT_DATE_ONLY_FORMAT,
    ESTIMATE,
    ESTIMATE10,
    ESTIMATE90,
    FAILURE,
    FORECASTS,
    GET_ACTUALS,
    INTEGRATION_VERSION,
    ISSUE_ACTUALS_API_LIMIT,
    ISSUE_ADVANCED_DEPRECATED,
    ISSUE_ADVANCED_PROBLEM,
    ISSUE_UNUSUAL_AZIMUTH_NORTHERN,
    ISSUE_UNUSUAL_AZIMUTH_SOUTHERN,
    LAST_7D,
    LAST_14D,
    LAST_24H,
    LAST_ATTEMPT,
    LAST_UPDATED,
    LEARN_MORE_ADVANCED,
    NEW_OPTION,
    OPTION,
    PERIOD_START,
    PRIOR_CRASH_EXCEPTION,
    PRIOR_CRASH_PLACEHOLDERS,
    PRIOR_CRASH_TRANSLATION_KEY,
    PROBLEMS,
    SITE_INFO,
    STOPS_WORKING,
    VERSION,
    WINTER_TIME,
)

if TYPE_CHECKING:
    from . import coordinator

# Status code translation, HTTP and more.
# A HTTP 418 error is included here for fun. This was introduced in RFC2324#section-2.3.2 as an April Fools joke in 1998.
# A HTTP 420 error is a Demolition Man reference previously used by Twitter to indicate rate limiting, seen rarely (and oddly) by this integration.
# 400-599 = HTTP
# 900-999 = Integration-specific situation to be potentially handled with retries.
STATUS_TRANSLATE: dict[int, str] = {
    200: "Success",
    400: "Bad request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not found",
    418: "I'm a teapot",
    420: "Enhance your calm",
    429: "Try again later",
    500: "Internal web server error",
    501: "Not implemented",
    502: "Bad gateway",
    503: "Service unavailable",
    504: "Gateway timeout",
    996: "Connection refused",
    997: "Connect call failed",
    999: "Prior crash",
}

_LOGGER = logging.getLogger(__name__)


@dataclass
class SolcastData:
    """Runtime data definition."""

    if TYPE_CHECKING:
        coordinator: coordinator.SolcastUpdateCoordinator
    else:
        coordinator: DataUpdateCoordinator[None]


class SolcastApiStatus(Enum):
    """The state of the Solcast API."""

    OK = 0
    DATA_CORRUPT = 1
    DATA_INCOMPATIBLE = 2
    BUILD_FAILED_FORECASTS = 3
    BUILD_FAILED_ACTUALS = 4
    ERROR = 5
    UNKNOWN = 99


class DataCallStatus(Enum):
    """The result of a data call."""

    SUCCESS = 0
    FAIL = 1
    ABORT = 2


class SitesStatus(Enum):
    """The state of load sites."""

    OK = 0
    BAD_KEY = 1
    ERROR = 2
    NO_SITES = 3
    CACHE_INVALID = 4
    API_BUSY = 5
    UNKNOWN = 99


class UsageStatus(Enum):
    """The state of API usage."""

    OK = 0
    ERROR = 1
    UNKNOWN = 99


class AutoUpdate(int, Enum):
    """The type of history data."""

    NONE = 0
    DAYLIGHT = 1
    ALL_DAY = 2


class HistoryType(int, Enum):
    """The type of history data."""

    FORECASTS = 0
    ESTIMATED_ACTUALS = 1
    ESTIMATED_ACTUALS_ADJUSTED = 2


def sync_actuals_api_limit_issue(hass: HomeAssistant, options: Mapping[str, Any], sites: list[dict[str, Any]]) -> None:
    """Raise or remove warning issue when estimated actuals consume auto-update API calls."""

    issue_registry = ir.async_get(hass)

    def _remove_issue() -> None:
        if issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_API_LIMIT) is not None:
            _LOGGER.debug("Remove issue for %s", ISSUE_ACTUALS_API_LIMIT)
            ir.async_delete_issue(hass, DOMAIN, ISSUE_ACTUALS_API_LIMIT)

    try:
        auto_update = int(options.get(AUTO_UPDATE, AutoUpdate.NONE))
    except (TypeError, ValueError):
        _remove_issue()
        return

    if auto_update == AutoUpdate.NONE or not options.get(GET_ACTUALS, False):
        _remove_issue()
        return

    api_keys = [key.strip() for key in str(options.get(CONF_API_KEY, "")).split(",") if key.strip()]
    api_limits = [limit.strip() for limit in str(options.get(API_LIMIT, "")).split(",") if limit.strip()]
    if not api_keys or not api_limits:
        _remove_issue()
        return

    original_limit_count = len(api_limits)
    while len(api_limits) < len(api_keys):
        api_limits.append(api_limits[-1])

    try:
        configured_limits = [int(api_limits[index]) for index in range(len(api_keys))]
    except ValueError:
        _remove_issue()
        return

    if not configured_limits or not all(limit in (10, 50) for limit in configured_limits):
        _remove_issue()
        return

    sites_per_key = dict.fromkeys(api_keys, 0)
    for site in sites:
        if (site_key := site.get(CONF_API_KEY)) in sites_per_key:
            sites_per_key[site_key] += 1

    suggested_limits = [max(configured_limits[index] - sites_per_key.get(api_keys[index], 0), 1) for index in range(len(api_keys))]

    if all(configured_limits[index] <= suggested_limits[index] for index in range(len(configured_limits))):
        _remove_issue()
        return

    if original_limit_count == 1:
        configured_value = str(configured_limits[0])
        suggested_value = str(min(suggested_limits))
    else:
        configured_value = ",".join(str(limit) for limit in configured_limits)
        suggested_value = ",".join(str(limit) for limit in suggested_limits)
    _LOGGER.debug(
        "Raise issue `%s` for configured API limits %s, suggested %s",
        ISSUE_ACTUALS_API_LIMIT,
        configured_value,
        suggested_value,
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_ACTUALS_API_LIMIT,
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_ACTUALS_API_LIMIT,
        translation_placeholders={
            "configured_value": configured_value,
            "suggested_value": suggested_value,
        },
    )


def sync_legacy_keys(data: dict[str, Any]) -> None:
    """Keep legacy option key names in sync with their renamed counterparts.

    Maintains "api_quota" and "customhoursensor" alongside the current
    API_LIMIT and CUSTOM_HOURS keys so that a downgrade to a version
    predating their rename can still read the stored values.
    """
    if "api_quota" in data:
        data["api_quota"] = data[API_LIMIT]
    if "customhoursensor" in data:
        data["customhoursensor"] = data[CUSTOM_HOURS]


class DateTimeHelper:
    """Timezone-aware datetime helper methods."""

    def __init__(self, tz: tzinfo) -> None:
        """Initialise the datetime helper.

        Arguments:
            tz: The timezone to use for local time calculations.

        """
        self._tz = tz

    def day_start(self, ts: dt) -> dt:
        """Get day start datetime for a given timestamp."""
        return ts.astimezone(self._tz).replace(hour=0, minute=0, second=0, microsecond=0)

    def day_start_utc(self, future: int = 0) -> dt:
        """Return the UTC datetime representing midnight local time.

        Arguments:
            future: An optional number of days into the future (or negative number for into the past).

        Returns:
            datetime: The UTC date and time representing midnight local time.

        """
        for_when = (dt.now(self._tz) + timedelta(days=future)).astimezone(self._tz)
        return for_when.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)

    def dst(self, dt_obj: dt | None = None) -> bool:
        """Return whether a given date is daylight savings time, or for zones using Winter time whether standard time."""
        result = False
        if dt_obj is not None:
            delta = timedelta(hours=1) if str(self._tz) not in WINTER_TIME else timedelta(hours=0)
            result = dt_obj.astimezone(self._tz).dst() == delta
        return result

    def hour_start_utc(self) -> dt:
        """Return the UTC datetime representing the start of the current hour."""
        return dt.now(self._tz).replace(minute=0, second=0, microsecond=0).astimezone(UTC)

    def is_interval_dst(self, interval: dict[str, Any]) -> bool:
        """Return whether an interval is daylight savings time, or for zones using Winter time whether standard time."""
        return self.dst(interval[PERIOD_START].astimezone(self._tz))

    def now_utc(self) -> dt:
        """Return the UTC datetime as at the previous minute boundary."""
        return dt.now(self._tz).replace(second=0, microsecond=0).astimezone(UTC)

    def real_now_utc(self) -> dt:
        """Return the UTC datetime including seconds/microseconds."""
        return dt.now(self._tz).astimezone(UTC)

    def utc_previous_midnight(self) -> dt:
        """Return the UTC datetime representing midnight UTC of the current day."""
        return dt.now().astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


class DateTimeEncoder(json.JSONEncoder):
    """Helper to convert datetime dict values to ISO format."""

    def default(self, o: Any) -> str | Any:
        """Convert to ISO format if datetime."""
        return o.isoformat() if isinstance(o, dt) else super().default(o)


class NoIndentEncoder(DateTimeEncoder):
    """Helper to output semi-indented json."""

    def __init__(self, *args, above_level=0, **kwargs) -> None:
        """Initialise the encoder."""
        super().__init__(*args, **kwargs)
        self.above_level = above_level

    def iterencode(self, o: Any, _one_shot: bool = False):
        """Recursive encoder to indent only top level keys."""
        list_lvl = 0
        up = ("[", "{")
        down = ("]", "}")
        raw: Iterator[str] = super().iterencode(o, _one_shot=_one_shot)
        output = ""
        for s in list(raw)[0].splitlines():
            level_down = any(c in s for c in down)
            if any(c in s for c in up):
                list_lvl += 1
                if list_lvl <= self.above_level:
                    s += "\n"
            elif list_lvl > self.above_level:
                s = s.replace(" ", "").rstrip()
                if level_down:
                    s += "\n"
            else:
                s += "\n"
            if level_down:
                list_lvl -= 1
            output += s
        yield output


class JSONDecoder(json.JSONDecoder):
    """Helper to convert ISO format dict values to datetime."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialise the decoder."""
        json.JSONDecoder.__init__(self, object_hook=self.date_hook, *args, **kwargs)  # noqa: B026

    def date_hook(self, o: Any) -> dict[str, Any]:
        """Return converted datetimes."""
        result: dict[str, Any] = {}
        for key, value in o.items():
            try:
                result[key] = dt.fromisoformat(value)
            except:  # noqa: E722
                result[key] = value
        return result


def http_status_translate(status: int) -> str | Any:
    """Translate HTTP status code to a human-readable translation."""

    return (f"{status}/{STATUS_TRANSLATE[status]}") if STATUS_TRANSLATE.get(status) else status


def api_key_last_six(api_key: str) -> str:
    """Return last six characters of API key."""

    return api_key[-6:]


def redact_api_key(api_key: str) -> str:
    """Obfuscate API key."""

    return "*" * 6 + api_key_last_six(api_key)


def redact_msg_api_key(msg: str, api_key: str) -> str:
    """Obfuscate API key in messages."""

    return (
        msg.replace("key=" + api_key, "key=" + redact_api_key(api_key))
        .replace("key': '" + api_key, "key': '" + redact_api_key(api_key))
        .replace("sites-" + api_key, "sites-" + redact_api_key(api_key))
        .replace("usage-" + api_key, "usage-" + redact_api_key(api_key))
    )


def redact_lat_lon_simple(s: str) -> str:
    """Redact latitude and longitude decimal places in a string."""

    return re.sub(r"\.[0-9]+", ".******", s)


def redact_lat_lon(s: str) -> str:
    """Redact latitude and longitude in a string."""

    return re.sub(r"itude\': [0-9\-\.]+", "itude': **.******", s)


def check_unusual_azimuth(latitude: float, azimuth: float) -> tuple[bool, str, int]:
    """Classify whether an azimuth is unusual for the given latitude.

    Returns a tuple of (unusual, issue_key, proposal) where:
        unusual: True if the azimuth is unusual for the hemisphere.
        issue_key: The issue key string (northern or southern).
        proposal: The suggested corrected azimuth value.
    """
    unusual = False
    proposal = 0
    if latitude > 0:
        # Northern hemisphere: azimuth should be 90..180 or -180..-90
        issue_key = ISSUE_UNUSUAL_AZIMUTH_NORTHERN
        if azimuth > 0 and not (90 <= azimuth <= 180):
            unusual = True
            proposal = 180 - int(azimuth)
        if azimuth < 0 and not (-180 <= azimuth <= -90):
            unusual = True
            proposal = -180 - int(azimuth)
    else:
        # Southern hemisphere: azimuth should be 0..90 or -90..0
        issue_key = ISSUE_UNUSUAL_AZIMUTH_SOUTHERN
        if azimuth > 0 and not (0 <= azimuth <= 90):
            unusual = True
            proposal = 180 - int(azimuth)
        if azimuth < 0 and not (-90 <= azimuth <= 0):
            unusual = True
            proposal = -180 - int(azimuth)
    return unusual, issue_key, proposal


class SchemaIncompatibleError(Exception):
    """Raised when cache data cannot be upgraded due to incompatible structure."""


def upgrade_cache_schema(
    data: dict[str, Any],
    from_version: int,
    first_site_id: str | None,
    auto_update_enabled: bool,
) -> int:
    """Upgrade a cache data dict from *from_version* to the current JSON_VERSION.

    The dict is mutated in-place. Returns the version after upgrade.

    Raises:
        SchemaIncompatibleError: If the data structure is incompatible and
            cannot be upgraded.
    """

    json_version = from_version

    # Test for incompatible data.
    if data.get(SITE_INFO) is None and data.get(FORECASTS) is None:
        raise SchemaIncompatibleError("Neither siteinfo nor forecasts present")
    if data.get(SITE_INFO) is not None:
        site_info = data.get(SITE_INFO, {})
        site_entry = site_info.get(first_site_id, {}) if first_site_id else {}
        if not isinstance(site_entry.get(FORECASTS), list):
            raise SchemaIncompatibleError("siteinfo forecasts is not a list")
    if data.get(FORECASTS) is not None:
        if not isinstance(data.get(FORECASTS), list):
            raise SchemaIncompatibleError("Top-level forecasts is not a list")

    # V3 and prior versions did not have a version key.
    if json_version < 4:
        data[VERSION] = 4
        json_version = 4

    # Add LAST_ATTEMPT and AUTO_UPDATED as of v5.
    # Ancient v3 versions did not have the SITE_INFO key.
    if json_version < 5:
        _LOGGER.debug("Upgrading to v5 cache structure")
        data[VERSION] = 5
        data[LAST_ATTEMPT] = data[LAST_UPDATED]
        data[AUTO_UPDATED] = auto_update_enabled
        if data.get(SITE_INFO) is None:
            if data.get(FORECASTS) is not None and first_site_id is not None:
                data[SITE_INFO] = {first_site_id: {FORECASTS: data.get(FORECASTS)}}
                data.pop(FORECASTS, None)
                data.pop("energy", None)
        json_version = 5

    # Alter AUTO_UPDATED boolean flag to int, introduced v4.3.0.
    if json_version < 6:
        _LOGGER.debug("Upgrading to v6 cache structure")
        data[VERSION] = 6
        data[AUTO_UPDATED] = 99999 if auto_update_enabled else 0
        json_version = 6

    # Add failure statistics, introduced v4.3.5.
    if json_version < 7:
        _LOGGER.debug("Upgrading to v7 cache structure")
        data[VERSION] = 7
        data[FAILURE] = {LAST_24H: 0, LAST_7D: [0] * 7}
        json_version = 7

    if json_version < 8:
        _LOGGER.debug("Upgrading to v8 cache structure")
        data[VERSION] = 8
        data[FAILURE][LAST_14D] = data[FAILURE][LAST_7D] + [0] * 7
        json_version = 8

    # Add integration version, introduced v4.x.x.
    if json_version < 9:
        _LOGGER.debug("Upgrading to v9 cache structure")
        data[VERSION] = 9
        data[INTEGRATION_VERSION] = "unknown"
        json_version = 9

    return json_version


def forecast_entry_update(forecasts: dict[dt, Any], period_start: dt, pv: float, pv10: float | None = None, pv90: float | None = None):
    """Update an individual forecast entry."""

    extant = forecasts.get(period_start)
    if extant:  # Update existing.
        forecasts[period_start][ESTIMATE] = pv
        if pv10 is not None:
            forecasts[period_start][ESTIMATE10] = pv10
        if pv90 is not None:
            forecasts[period_start][ESTIMATE90] = pv90
    elif pv10 is not None:
        forecasts[period_start] = {
            "period_start": period_start,
            "pv_estimate": pv,
            "pv_estimate10": pv10,
            "pv_estimate90": pv90,
        }
    else:
        forecasts[period_start] = {
            "period_start": period_start,
            "pv_estimate": pv,
        }


def raise_and_record(
    hass: HomeAssistant, exception: type[IntegrationError], translation_key: str, translation_placeholders: dict | None = None
) -> None:
    """Raise and record an exception during initialisation."""
    hass.data[DOMAIN][PRIOR_CRASH_EXCEPTION] = exception
    hass.data[DOMAIN][PRIOR_CRASH_TRANSLATION_KEY] = translation_key
    hass.data[DOMAIN][PRIOR_CRASH_PLACEHOLDERS] = translation_placeholders
    raise exception(translation_domain=DOMAIN, translation_key=translation_key, translation_placeholders=translation_placeholders)


async def raise_or_clear_advanced_problems(problems: list[str], hass: HomeAssistant):
    """Raise or clear advanced unknown option issues."""
    issue_registry = ir.async_get(hass)
    if problems:
        problem_list = "".join([("\n* " + problem) for problem in sorted(problems)])
        issue = issue_registry.async_get_issue(DOMAIN, ISSUE_ADVANCED_PROBLEM)
        if (
            issue is not None
            and issue.translation_placeholders is not None
            and issue.translation_placeholders.get(PROBLEMS) != problem_list
        ):
            ir.async_delete_issue(hass, DOMAIN, ISSUE_ADVANCED_PROBLEM)
            await hass.async_block_till_done()
        _LOGGER.debug("Raising advanced option problems issue for: %s", ", ".join(problems))
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_ADVANCED_PROBLEM,
            is_fixable=False,
            is_persistent=True,
            translation_key=ISSUE_ADVANCED_PROBLEM,
            translation_placeholders={
                PROBLEMS: problem_list,
            },
            severity=ir.IssueSeverity.ERROR,
            learn_more_url=LEARN_MORE_ADVANCED,
        )
        issue = issue_registry.async_get_issue(DOMAIN, ISSUE_ADVANCED_PROBLEM)
    else:
        issue_registry = ir.async_get(hass)
        issue = issue_registry.async_get_issue(DOMAIN, ISSUE_ADVANCED_PROBLEM)
        if issue is not None:
            _LOGGER.debug("Removing advanced problems issue")
            ir.async_delete_issue(hass, DOMAIN, ISSUE_ADVANCED_PROBLEM)


async def raise_or_clear_advanced_deprecated(
    deprecated_in_use: dict[str, str], hass: HomeAssistant, stops_working: dict[str, dt] | None = None
):
    """Raise or clear advanced deprecated option issues."""
    if deprecated_in_use:
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_ADVANCED_DEPRECATED,
            is_fixable=False,
            is_persistent=True,
            translation_key=ISSUE_ADVANCED_DEPRECATED,
            translation_placeholders={
                OPTION: ", ".join(deprecated_in_use.keys()),
                NEW_OPTION: ", ".join(deprecated_in_use.values()),
                STOPS_WORKING: (
                    " ("
                    + ", ".join(
                        [
                            f"{option} stops working after {date.strftime(DT_DATE_ONLY_FORMAT)}"
                            for option, date in stops_working.items()
                            if option in deprecated_in_use
                        ]
                    )
                    + ")"
                )
                if stops_working
                else "",
            },
            severity=ir.IssueSeverity.WARNING,
            learn_more_url=LEARN_MORE_ADVANCED,
        )
    else:
        issue_registry = ir.async_get(hass)
        issue = issue_registry.async_get_issue(DOMAIN, ISSUE_ADVANCED_DEPRECATED)
        if issue is not None:
            _LOGGER.debug("Removing advanced deprecation issue")
            ir.async_delete_issue(hass, DOMAIN, ISSUE_ADVANCED_DEPRECATED)


async def async_trigger_automation_by_name(hass: HomeAssistant, name: str) -> bool:
    """Trigger an automation by friendly name; returns True if found and triggered."""
    success = False
    entity_id = None
    for state in hass.states.async_all("automation"):
        if state.attributes.get("friendly_name") == name:
            entity_id = state.entity_id
    if entity_id:
        await hass.services.async_call("automation", "trigger", {ATTR_ENTITY_ID: entity_id}, blocking=True)
        success = True
    return success


async def clear_cache(filename: str, warn: bool = True):
    """Deletes filename if it exists."""
    if Path(filename).is_file():
        Path(filename).unlink()
        _LOGGER.debug("Deleted cache file %s", filename.split("/")[-1])
    elif warn:
        _LOGGER.warning("There is no %s to delete", filename.split("/")[-1])


def percentile(data: list[Any], _percentile: float) -> float | int:
    """Find the given percentile in a sorted list of values."""

    if not data:
        return 0.0
    k = (len(data) - 1) * (_percentile / 100)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return data[int(k)]
    d0 = data[int(f)] * (c - k)
    d1 = data[int(c)] * (k - f)
    return round(d0 + d1, 4)


def ordinal(value: int) -> str:
    """Return a number with an ordinal suffix."""

    abs_value = abs(value)
    return f"{value}{'th' if 11 <= abs_value % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(abs_value % 10, 'th')}"


def interquartile_bounds(sorted_data: list[Any], factor: float = 1.5) -> tuple[float | int, float | int]:
    """Return the lower and upper interquartile bounds of a sorted data set."""

    lower = 0.0
    upper = float("inf")
    iqr = 0.0
    if len(sorted_data) > 4:
        q1 = percentile(sorted_data, 25)
        q3 = percentile(sorted_data, 75)
        iqr = round(q3 - q1, 5)
        lower = round(q1 - factor * iqr, 4)
        upper = round(q3 + factor * iqr, 4)
    return (lower, upper)


def diff(lst: list[Any], non_negative: bool = True) -> list[Any]:
    """Build a numpy-like diff."""

    size = len(lst) - 1
    r: list[int | float] = [0] * size
    for i in range(size):
        r[i] = max(0, lst[i + 1] - lst[i]) if non_negative else lst[i + 1] - lst[i]
    return r


class EnergyResult(NamedTuple):
    """Result from compute_energy_intervals."""

    uniform_increment: bool
    upper: float
    ignored: dict[dt, bool]


def compute_power_intervals(
    power_readings: list[tuple[dt, float]],
    generation_intervals: dict[dt, float],
) -> bool:
    """Compute time-weighted average power per 30-minute interval and add kWh to generation_intervals.

    Returns True if power readings were sufficient, False otherwise.
    """

    if len(power_readings) <= 1:
        return False

    for interval_start in generation_intervals:
        interval_end = interval_start + timedelta(minutes=30)
        weighted_sum = 0.0
        total_weight = 0.0

        for i, (reading_time, power_kw) in enumerate(power_readings):
            if i + 1 < len(power_readings):
                next_time = power_readings[i + 1][0]
            else:
                next_time = interval_end

            seg_start = max(reading_time, interval_start)
            seg_end = min(next_time, interval_end)

            if seg_start < seg_end:
                duration = (seg_end - seg_start).total_seconds()
                weighted_sum += power_kw * duration
                total_weight += duration

        if total_weight > 0:
            avg_power_kw = weighted_sum / total_weight
            generation_intervals[interval_start] += avg_power_kw * 0.5

    return True


def compute_energy_intervals(
    sample_time: list[dt],
    sample_generation: list[float],
    sample_generation_time: list[dt],
    sample_timedelta: list[int],
    generation_intervals: dict[dt, float],
    period_start: dt,
    period_end: dt,
) -> EnergyResult:
    """Distribute energy deltas across 30-minute intervals, filtering excessive jumps.

    Modifies generation_intervals in place. Returns an EnergyResult with diagnostic info.
    """

    # Determine generation-consistent or time-consistent increments.
    uniform_increment = False
    non_zero_samples = sorted([round(sample, 5) for sample in sample_generation if sample > 0.0003])
    if percentile(non_zero_samples, 25) == percentile(non_zero_samples, 75):
        uniform_increment = True
    else:
        non_zero_samples = sorted([sample for sample in sample_timedelta if sample > 0])
    _, upper = interquartile_bounds(non_zero_samples, factor=(1.5 if uniform_increment else 2.2))
    upper += 0.1 if uniform_increment else 1
    time_delta_samples = [sample for sample in sample_timedelta if sample > 0]
    if time_delta_samples:
        _, time_upper = interquartile_bounds(time_delta_samples, factor=2.2)
        time_upper += 1
    else:
        time_upper = 0

    ignored: dict[dt, bool] = {}
    last_interval: dt | None = None
    prev_report_time: dt | None = None

    if (
        len(sample_time) == len(sample_generation)
        and len(sample_time) == len(sample_generation_time)
        and len(sample_time) == len(sample_timedelta)
    ):
        for idx, (interval, kWh, report_time, time_delta) in enumerate(
            zip(sample_time, sample_generation, sample_generation_time, sample_timedelta, strict=True)
        ):
            is_excessive = False
            if interval != last_interval:
                last_interval = interval
                if uniform_increment:
                    if round(kWh, 4) > upper:
                        is_excessive = True
                        ignored[interval] = True
                elif time_delta > upper and kWh > 0.0003:
                    if kWh > 0.14:
                        is_excessive = True
                        ignored[interval] = True
                if is_excessive:
                    ignored[interval - timedelta(minutes=30)] = True

            if not is_excessive and idx > 0 and prev_report_time is not None:
                delta_start = prev_report_time
                delta_end = report_time
                current_interval_start = interval
                prev_interval_start = delta_start.replace(minute=delta_start.minute // 30 * 30, second=0, microsecond=0)

                if prev_report_time == period_start:
                    generation_intervals[current_interval_start] += kWh
                    prev_report_time = report_time
                    continue

                if report_time == period_end:
                    if prev_interval_start in generation_intervals:
                        generation_intervals[prev_interval_start] += kWh
                    prev_report_time = report_time
                    continue

                if time_upper and time_delta > time_upper and kWh > 0.0003:
                    generation_intervals[current_interval_start] += kWh
                elif prev_interval_start == current_interval_start:
                    generation_intervals[interval] += kWh
                else:
                    total_seconds = (delta_end - delta_start).total_seconds()
                    if total_seconds > 0:
                        intervals_crossed = []
                        temp_interval = prev_interval_start
                        while temp_interval <= current_interval_start:
                            interval_end = temp_interval + timedelta(minutes=30)
                            overlap_start = max(delta_start, temp_interval)
                            overlap_end = min(delta_end, interval_end)
                            if overlap_start < overlap_end:
                                overlap_seconds = (overlap_end - overlap_start).total_seconds()
                                proportion = overlap_seconds / total_seconds
                                intervals_crossed.append((temp_interval, proportion))
                            temp_interval = interval_end

                        for crossed_interval, proportion in intervals_crossed:
                            if crossed_interval in generation_intervals:
                                generation_intervals[crossed_interval] += kWh * proportion
            elif not is_excessive and idx == 0:
                generation_intervals[interval] += kWh

            prev_report_time = report_time

        for interval in ignored:
            generation_intervals[interval] = 0.0

    return EnergyResult(uniform_increment=uniform_increment, upper=upper, ignored=ignored)


def cubic_interp(x0: list[Any], x: list[Any], y: list[Any]) -> list[Any]:
    """Build a cubic spline.

    Arguments:
        x0 (list): List of numbers to interpolate at
        x (list): List of numbers in increasing order
        y (list): List of floats to interpolate

    Returns:
        list: Array of interpolated values.

    """

    def clip(lst: list[Any], min_val: float, max_val: float, in_place: bool = False) -> list[Any]:  # numpy-like clip
        if not in_place:
            lst = lst[:]
        for i in range(len(lst)):
            if lst[i] < min_val:
                lst[i] = min_val
            elif lst[i] > max_val:
                lst[i] = max_val
        return lst

    def search_sorted(list_to_insert: list[Any], insert_into: list[Any]) -> list[Any]:  # numpy-like search_sorted
        def float_search_sorted(float_to_insert: Any, insert_into: list[Any]) -> int:
            for i in range(len(insert_into)):
                if float_to_insert <= insert_into[i]:
                    return i
            return len(insert_into)

        return [float_search_sorted(i, insert_into) for i in list_to_insert]

    def subtract(a: float, b: float) -> float:
        return a - b

    size: int = len(x)
    x_diff: list[Any] = diff(x, non_negative=False)
    y_diff: list[Any] = diff(y, non_negative=False)

    li: list[Any] = [0] * size
    li_1: list[Any] = [0] * (size - 1)
    z: list[Any] = [0] * (size)

    li[0] = math.sqrt(2 * x_diff[0])
    li_1[0] = 0.0
    b0: float = 0.0
    z[0] = b0 / li[0]

    bi: float = 0.0

    for i in range(1, size - 1, 1):
        li_1[i] = x_diff[i - 1] / li[i - 1]
        li[i] = math.sqrt(2 * (x_diff[i - 1] + x_diff[i]) - li_1[i - 1] * li_1[i - 1])
        bi = 6 * (y_diff[i] / x_diff[i] - y_diff[i - 1] / x_diff[i - 1])
        z[i] = (bi - li_1[i - 1] * z[i - 1]) / li[i]

    i = size - 1
    li_1[i - 1] = x_diff[-1] / li[i - 1]
    li[i] = math.sqrt(2 * x_diff[-1] - li_1[i - 1] * li_1[i - 1])
    bi = 0.0
    z[i] = (bi - li_1[i - 1] * z[i - 1]) / li[i]

    i = size - 1
    z[i] = z[i] / li[i]
    for i in range(size - 2, -1, -1):
        z[i] = (z[i] - li_1[i - 1] * z[i + 1]) / li[i]

    index = search_sorted(x0, x)
    index = clip(index, 1, size - 1)

    xi1: list[Any] = [x[num] for num in index]
    xi0: list[Any] = [x[num - 1] for num in index]
    yi1: list[Any] = [y[num] for num in index]
    yi0: list[Any] = [y[num - 1] for num in index]
    zi1: list[Any] = [z[num] for num in index]
    zi0: list[Any] = [z[num - 1] for num in index]
    hi1 = list(map(subtract, xi1, xi0))

    f0: list[Any] = [0] * len(hi1)
    for j in range(len(f0)):
        f0[j] = round(
            zi0[j] / (6 * hi1[j]) * (xi1[j] - x0[j]) ** 3
            + zi1[j] / (6 * hi1[j]) * (x0[j] - xi0[j]) ** 3
            + (yi1[j] / hi1[j] - zi1[j] * hi1[j] / 6) * (x0[j] - xi0[j])
            + (yi0[j] / hi1[j] - zi0[j] * hi1[j] / 6) * (xi1[j] - x0[j]),
            4,
        )

    return f0
