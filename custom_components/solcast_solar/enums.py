"""Enumerations and result types used across the Solcast integration."""

from datetime import datetime as dt
from enum import Enum
from typing import NamedTuple


class SolcastApiStatus(Enum):
    """The state of the Solcast API."""

    OK = 0
    DATA_CORRUPT = 1
    DATA_INCOMPATIBLE = 2
    BUILD_FAILED_FORECASTS = 3
    BUILD_FAILED_ACTUALS = 4
    ERROR = 5
    UNKNOWN = 99


class UpdateOutcome(Enum):
    """The result of an update attempt."""

    SUCCESS = 0
    FAILED = 1
    ABORTED = 2
    SKIPPED = 3


class UpdateResult(NamedTuple):
    """Result payload for update attempts."""

    outcome: UpdateOutcome
    message: str


class LoadStatus(Enum):
    """The state of load sites/cache."""

    OK = 0
    BAD_KEY = 1
    ERROR = 2
    NO_SITES = 3
    CACHE_INVALID = 4
    API_BUSY = 5
    UNKNOWN = 99


class AutoUpdate(int, Enum):
    """The auto update mode."""

    NONE = 0
    DAYLIGHT = 1
    ALL_DAY = 2


class HistoryType(int, Enum):
    """The type of history data."""

    FORECASTS = 0
    ESTIMATED_ACTUALS = 1
    ESTIMATED_ACTUALS_ADJUSTED = 2


class EnergyResult(NamedTuple):
    """Result from compute_energy_intervals."""

    uniform_increment: bool
    upper: float
    ignored: dict[dt, bool]
