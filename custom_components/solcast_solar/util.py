"""Utility."""

# pylint: disable=consider-using-enumerate

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime as dt
from enum import Enum
import json
import math
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

if TYPE_CHECKING:
    from . import coordinator


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

    def __init__(self, *args, **kwargs) -> None:
        """Initialise the decoder."""
        json.JSONDecoder.__init__(self, object_hook=self.object_hook, *args, **kwargs)  # noqa: B026

    def object_hook(self, o: Any) -> dict:
        """Return converted datetimes."""
        result = {}
        for key, value in o.items():
            try:
                result[key] = dt.fromisoformat(value)
            except:  # noqa: E722
                result[key] = value
        return result


def cubic_interp(x0: list, x: list, y: list) -> list:
    """Build a cubic spline.

    Arguments:
        x0 (list): List of floats to interpolate at
        x (list): List of floats in increasing order
        y (list): List of floats to interpolate

    Returns:
        list: Array of interpolated values.

    """

    def diff(lst: list) -> list:  # numpy-like diff
        size = len(lst) - 1
        r = [0] * size
        for i in range(size):
            r[i] = lst[i + 1] - lst[i]
        return r

    def clip(lst: list, min_val: float, max_val: float, in_place: bool = False) -> list:  # numpy-like clip
        if not in_place:
            lst = lst[:]
        for i in range(len(lst)):
            if lst[i] < min_val:
                lst[i] = min_val
            elif lst[i] > max_val:
                lst[i] = max_val
        return lst

    def search_sorted(list_to_insert: list, insert_into: list) -> list:  # numpy-like search_sorted
        def float_search_sorted(float_to_insert, insert_into):
            for i in range(len(insert_into)):
                if float_to_insert <= insert_into[i]:
                    return i
            return len(insert_into)

        return [float_search_sorted(i, insert_into) for i in list_to_insert]

    def subtract(a: float, b: float) -> float:
        return a - b

    size: int = len(x)
    x_diff: list = diff(x)
    y_diff: list = diff(y)

    li: list = [0] * size
    li_1: list = [0] * (size - 1)
    z: list = [0] * (size)

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

    xi1 = [x[num] for num in index]
    xi0 = [x[num - 1] for num in index]
    yi1 = [y[num] for num in index]
    yi0 = [y[num - 1] for num in index]
    zi1 = [z[num] for num in index]
    zi0 = [z[num - 1] for num in index]
    hi1 = list(map(subtract, xi1, xi0))

    f0 = [0] * len(hi1)
    for j in range(len(f0)):
        f0[j] = round(
            zi0[j] / (6 * hi1[j]) * (xi1[j] - x0[j]) ** 3
            + zi1[j] / (6 * hi1[j]) * (x0[j] - xi0[j]) ** 3
            + (yi1[j] / hi1[j] - zi1[j] * hi1[j] / 6) * (x0[j] - xi0[j])
            + (yi0[j] / hi1[j] - zi0[j] * hi1[j] / 6) * (xi1[j] - x0[j]),
            4,
        )

    return f0
