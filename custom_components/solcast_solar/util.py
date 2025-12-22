"""Utility."""

# pylint: disable=consider-using-enumerate

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime as dt
from enum import Enum
import json
import logging
import math
import re
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import IntegrationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    DOMAIN,
    DT_DATE_ONLY_FORMAT,
    ESTIMATE,
    ESTIMATE10,
    ESTIMATE90,
    ISSUE_ADVANCED_DEPRECATED,
    ISSUE_ADVANCED_PROBLEM,
    LEARN_MORE_ADVANCED,
    NEW_OPTION,
    OPTION,
    PRIOR_CRASH_EXCEPTION,
    PRIOR_CRASH_PLACEHOLDERS,
    PRIOR_CRASH_TRANSLATION_KEY,
    PROBLEMS,
    STOPS_WORKING,
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


class DateTimeEncoder(json.JSONEncoder):
    """Helper to convert datetime dict values to ISO format."""

    def default(self, o: Any) -> str | Any:
        """Convert to ISO format if datetime."""
        return o.isoformat() if isinstance(o, dt) else super().default(o)


class NoIndentEncoder(json.JSONEncoder):
    """Helper to output semi-indented json."""

    def iterencode(self, o: Any, _one_shot: bool = False):
        """Recursive encoder to indent only top level keys."""
        list_lvl = 0
        raw: Iterator[str] = super().iterencode(o, _one_shot=_one_shot)
        output = ""
        for s in list(raw)[0].splitlines():
            if "[" in s:
                list_lvl += 1
            elif list_lvl > 0:
                s = s.replace(" ", "").rstrip()
                if "]" in s:
                    list_lvl -= 1
                    s += "\n"
            else:
                s += "\n"
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
