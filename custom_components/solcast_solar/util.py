"""Utility."""

# pylint: disable=consider-using-enumerate

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime as dt
from enum import Enum
import json
import logging
import math
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

if TYPE_CHECKING:
    from . import coordinator

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
    DATA_INCOMPATIBLE = 1
    ERROR = 2


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


class Api(Enum):
    """The APIs at Solcast."""

    HOBBYIST = 0
    ADVANCED = 1


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


def find_percentile(data: list[float], percentile: float) -> float:
    """Find the given percentile in a sorted list of values."""

    if not data:
        return 0.0
    k = (len(data) - 1) * (percentile / 100)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return data[int(k)]
    d0 = data[int(f)] * (c - k)
    d1 = data[int(c)] * (k - f)
    return d0 + d1


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
