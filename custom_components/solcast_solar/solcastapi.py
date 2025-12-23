"""Solcast API."""

# pylint: disable=pointless-string-statement

from __future__ import annotations

import asyncio
from collections import OrderedDict, defaultdict
import contextlib
import copy
from dataclasses import dataclass
import datetime
from datetime import date, datetime as dt, timedelta, tzinfo
import json
import logging
import math
from operator import itemgetter
from pathlib import Path
import random
import re
import sys
import time
import traceback
from types import MappingProxyType
from typing import Any, Final, cast

import aiofiles
from aiohttp import ClientConnectionError, ClientResponseError, ClientSession
from aiohttp.client_reqrep import ClientResponse

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import state_changes_during_period
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, ATTR_UNIT_OF_MEASUREMENT, CONF_API_KEY
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import (
    ConfigEntryError,
    ConfigEntryNotReady,
    ServiceValidationError,
)
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from .const import (
    ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL,
    ADVANCED_AUTOMATED_DAMPENING_GENERATION_HISTORY_LOAD_DAYS,
    ADVANCED_AUTOMATED_DAMPENING_IGNORE_INTERVALS,
    ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR,
    ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR_ADJUSTED,
    ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_GENERATION,
    ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_INTERVALS,
    ADVANCED_AUTOMATED_DAMPENING_MODEL,
    ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS,
    ADVANCED_AUTOMATED_DAMPENING_NO_DELTA_ADJUSTMENT,
    ADVANCED_AUTOMATED_DAMPENING_NO_LIMITING_CONSISTENCY,
    ADVANCED_AUTOMATED_DAMPENING_PRESERVE_UNMATCHED_FACTORS,
    ADVANCED_AUTOMATED_DAMPENING_SIMILAR_PEAK,
    ADVANCED_AUTOMATED_DAMPENING_SUPPRESSION_ENTITY,
    ADVANCED_FORECAST_FUTURE_DAYS,
    ADVANCED_GRANULAR_DAMPENING_DELTA_ADJUSTMENT,
    ADVANCED_HISTORY_MAX_DAYS,
    ADVANCED_INVALID_JSON_TASK,
    ADVANCED_OPTION,
    ADVANCED_OPTIONS,
    ADVANCED_SOLCAST_URL,
    ADVANCED_TRIGGER_ON_API_AVAILABLE,
    ADVANCED_TRIGGER_ON_API_UNAVAILABLE,
    ADVANCED_TYPE,
    ALIASES,
    ALL,
    API_KEY,
    AUTO_DAMPEN,
    AUTO_UPDATE,
    AUTO_UPDATED,
    BRK_ESTIMATE,
    BRK_ESTIMATE10,
    BRK_ESTIMATE90,
    BRK_HALFHOURLY,
    BRK_HOURLY,
    BRK_SITE,
    BRK_SITE_DETAILED,
    CONFIG_DISCRETE_NAME,
    CONFIG_FOLDER_DISCRETE,
    CURRENT_NAME,
    CUSTOM_HOUR_SENSOR,
    DAILY_LIMIT,
    DAILY_LIMIT_CONSUMED,
    DAMPENING_FACTOR,
    DATA_CORRECT,
    DATA_SET_ACTUALS,
    DATA_SET_ACTUALS_UNDAMPENED,
    DATA_SET_FORECAST,
    DATA_SET_FORECAST_UNDAMPENED,
    DAY_NAME,
    DEFAULT,
    DEPRECATED,
    DETAILED_FORECAST,
    DETAILED_HOURLY,
    DISMISSAL,
    DOMAIN,
    DT_DATE_FORMAT,
    DT_DATE_MONTH_DAY,
    DT_DATE_ONLY_FORMAT,
    ENTRY_ID,
    ENTRY_OPTIONS,
    ERROR_CODE,
    ESTIMATE,
    ESTIMATE10,
    ESTIMATE90,
    ESTIMATED_ACTUALS,
    EXCEPTION_BUILD_FAILED_ACTUALS,
    EXCEPTION_BUILD_FAILED_FORECASTS,
    EXCEPTION_INIT_CORRUPT,
    EXCEPTION_INIT_INCOMPATIBLE,
    EXCLUDE_SITES,
    EXPORT_LIMITING,
    EXTANT,
    FAILURE,
    FILES,
    FORECASTS,
    FORMAT,
    GENERATION,
    GENERATION_ENTITIES,
    GENERATION_VERSION,
    GET_ACTUALS,
    HARD_LIMIT_API,
    HOURS,
    ISSUE_API_UNAVAILABLE,
    ISSUE_CORRUPT_FILE,
    ISSUE_RECORDS_MISSING,
    ISSUE_RECORDS_MISSING_FIXABLE,
    ISSUE_RECORDS_MISSING_INITIAL,
    ISSUE_RECORDS_MISSING_UNFIXABLE,
    ISSUE_UNUSUAL_AZIMUTH_NORTHERN,
    ISSUE_UNUSUAL_AZIMUTH_SOUTHERN,
    JSON,
    JSON_VERSION,
    KEY_ESTIMATE,
    LAST_7D,
    LAST_14D,
    LAST_24H,
    LAST_ATTEMPT,
    LAST_UPDATED,
    LEARN_MORE,
    LEARN_MORE_CORRUPT_FILE,
    LEARN_MORE_MISSING_FORECAST_DATA,
    LEARN_MORE_UNUSUAL_AZIMUTH,
    MAXIMUM,
    MESSAGE,
    MINIMUM,
    NAME,
    OLD_API_KEY,
    OPTION_GREATER_THAN_OR_EQUAL,
    OPTION_LESS_THAN_OR_EQUAL,
    OPTION_NOT_SET_IF,
    PERIOD_END,
    PERIOD_START,
    PLATFORM_BINARY_SENSOR,
    PLATFORM_SENSOR,
    PLATFORM_SWITCH,
    PROPOSAL,
    RESET,
    RESOURCE_ID,
    RESPONSE_STATUS,
    SITE,
    SITE_ATTRIBUTE_AZIMUTH,
    SITE_ATTRIBUTE_CAPACITY,
    SITE_ATTRIBUTE_CAPACITY_DC,
    SITE_ATTRIBUTE_INSTALL_DATE,
    SITE_ATTRIBUTE_LATITUDE,
    SITE_ATTRIBUTE_LONGITUDE,
    SITE_ATTRIBUTE_LOSS_FACTOR,
    SITE_ATTRIBUTE_TAGS,
    SITE_ATTRIBUTE_TILT,
    SITE_DAMP,
    SITE_EXPORT_ENTITY,
    SITE_EXPORT_LIMIT,
    SITE_INFO,
    SITES,
    STOPS_WORKING,
    TASK_ACTUALS_FETCH,
    TASK_FORECASTS_FETCH,
    TOTAL_RECORDS,
    UNKNOWN,
    USE_ACTUALS,
    VERSION,
    WINTER_TIME,
)
from .util import (
    AutoUpdate,
    DataCallStatus,
    DateTimeEncoder,
    HistoryType,
    JSONDecoder,
    NoIndentEncoder,
    SitesStatus,
    SolcastApiStatus,
    UsageStatus,
    cubic_interp,
    diff,
    forecast_entry_update,
    http_status_translate,
    interquartile_bounds,
    percentile,
    raise_and_record,
    raise_or_clear_advanced_deprecated,
    raise_or_clear_advanced_problems,
    redact_api_key,
    redact_lat_lon,
    redact_lat_lon_simple,
    redact_msg_api_key,
)

GRANULAR_DAMPENING_OFF: Final[bool] = False
GRANULAR_DAMPENING_ON: Final[bool] = True
SET_ALLOW_RESET: Final[bool] = True

FRESH_DATA: Final[dict[str, Any]] = {
    SITE_INFO: {},
    LAST_UPDATED: dt.fromtimestamp(0, datetime.UTC),
    LAST_ATTEMPT: dt.fromtimestamp(0, datetime.UTC),
    AUTO_UPDATED: 0,
    FAILURE: {LAST_24H: 0, LAST_7D: [0] * 7, LAST_14D: [0] * 14},
    VERSION: JSON_VERSION,
}


_LOGGER = logging.getLogger(__name__)

# Return the function name at a specified caller depth. 0=current, 1=caller, 2=caller of caller, etc.
FunctionName = lambda n=0: sys._getframe(n + 1).f_code.co_name  # noqa: E731, SLF001 # type: ignore[no-redef]


@dataclass
class ConnectionOptions:
    """Solcast options for the integration."""

    api_key: str
    api_quota: str
    host: str
    file_path: str
    tz: tzinfo
    auto_update: AutoUpdate
    dampening: dict[str, float]
    custom_hour_sensor: int
    key_estimate: str
    hard_limit: str
    attr_brk_estimate: bool
    attr_brk_estimate10: bool
    attr_brk_estimate90: bool
    attr_brk_site: bool
    attr_brk_halfhourly: bool
    attr_brk_hourly: bool
    attr_brk_site_detailed: bool
    exclude_sites: list[str]
    get_actuals: bool
    use_actuals: HistoryType
    generation_entities: list[str]
    site_export_entity: str
    site_export_limit: float
    auto_dampen: bool


class SolcastApi:  # pylint: disable=too-many-public-methods
    """The Solcast API."""

    def __init__(
        self,
        aiohttp_session: ClientSession,
        options: ConnectionOptions,
        hass: HomeAssistant,
        entry: ConfigEntry | None = None,
    ) -> None:
        """Initialise the API interface.

        Arguments:
            aiohttp_session (ClientSession): The aiohttp client session provided by Home Assistant
            options (ConnectionOptions): The integration stored configuration options.
            hass (HomeAssistant): The Home Assistant instance.
            entry (ConfigEntry): The entry options.
        """

        self.advanced_options: dict[str, Any] = {}
        self.auto_update_divisions: int = 0
        self.custom_hour_sensor: int = options.custom_hour_sensor
        self.damp: dict[str, float] = options.dampening
        self.entry = entry
        self.entry_options: dict[str, Any] = {}
        if self.entry is not None:
            self.entry_options = {**self.entry.options}
        self.estimate_set: list[str] = self.__get_estimate_set(options)
        self.granular_dampening: dict[str, list[float]] = {}
        self.granular_dampening_mtime: float = 0
        self.hard_limit: str = options.hard_limit
        self.hass: HomeAssistant = hass
        self.headers: dict[str, str] = {}
        self.latest_period: dt | None = None
        self.options: ConnectionOptions = options
        self.reauth_required: bool = False
        self.sites: list[dict[str, Any]] = []
        self.sites_status: SitesStatus = SitesStatus.UNKNOWN
        self.status: SolcastApiStatus = SolcastApiStatus.UNKNOWN
        self.status_message: str = ""
        self.tasks: dict[str, Any] = {}
        self.usage_status: UsageStatus = UsageStatus.UNKNOWN

        file_path = Path(options.file_path)
        self.set_default_advanced_options()

        self._aiohttp_session = aiohttp_session
        self._api_limit: dict[str, int] = {}
        self._api_used: dict[str, int] = {}
        self._api_used_reset: dict[str, dt | None] = {}
        self._auto_dampening_factors: dict[dt, float] = {}
        self._data: dict[str, Any] = copy.deepcopy(FRESH_DATA)
        self._data_actuals: dict[str, Any] = copy.deepcopy(FRESH_DATA)
        self._data_actuals_dampened: dict[str, Any] = copy.deepcopy(FRESH_DATA)
        self._data_energy_dashboard: dict[str, Any] = {}
        self._data_estimated_actuals: list[dict[str, Any]] = []
        self._data_estimated_actuals_dampened: list[dict[str, Any]] = []
        self._data_forecasts: list[dict[str, Any]] = []
        self._data_forecasts_undampened: list[dict[str, Any]] = []
        self._data_generation: dict[str, list[dict[str, Any]] | Any] = {
            LAST_UPDATED: dt.fromtimestamp(0, datetime.UTC),
            GENERATION: [],
            VERSION: GENERATION_VERSION,
        }
        self._data_undampened: dict[str, Any] = copy.deepcopy(FRESH_DATA)
        self._dismissal: dict[str, bool] = {}
        self._extant_sites: defaultdict[str, list[dict[str, Any]]] = defaultdict(list[dict[str, Any]])
        self._extant_usage: defaultdict[str, dict[str, Any]] = defaultdict(dict[str, Any])
        self._filename = options.file_path
        self._filename_actuals = f"{file_path.parent / file_path.stem}-actuals{file_path.suffix}"
        self._filename_actuals_dampened = f"{file_path.parent / file_path.stem}-actuals-dampened{file_path.suffix}"
        self._filename_advanced = f"{file_path.parent / file_path.stem}-advanced{file_path.suffix}"
        self._filename_dampening = f"{file_path.parent / file_path.stem}-dampening{file_path.suffix}"
        self._filename_generation = f"{file_path.parent / file_path.stem}-generation{file_path.suffix}"
        self._filename_undampened = f"{file_path.parent / file_path.stem}-undampened{file_path.suffix}"
        self._forecasts_moment: dict[str, dict[str, list[float]]] = {}
        self._forecasts_remaining: dict[str, dict[str, list[float]]] = {}
        self._granular_allow_reset = True
        self._loaded_data = False
        self._next_update: str | None = None
        self._rekey: dict[str, Any] = {}
        self._peak_intervals: dict[int, float] = dict.fromkeys(range(48), -1.0)
        self._site_data_forecasts: dict[str, list[dict[str, Any]]] = {}
        self._site_data_forecasts_undampened: dict[str, list[dict[str, Any]]] = {}
        self._site_latitude: defaultdict[str, dict[str, bool | float | int | None]] = defaultdict(dict[str, bool | float | int | None])
        self._sites_hard_limit: defaultdict[str, Any] = defaultdict(dict)
        self._sites_hard_limit_undampened: defaultdict[str, Any] = defaultdict(dict)
        self._sites_actual_hard_limit: defaultdict[str, Any] = defaultdict(dict)
        self._sites_actual_hard_limit_undampened: defaultdict[str, Any] = defaultdict(dict)
        self._spline_period = list(range(0, 90000, 1800))
        self._serialise_lock = asyncio.Lock()
        self._tally: dict[str, float | None] = {}
        self._tz = options.tz
        self._use_forecast_confidence = f"pv_{options.key_estimate}"

        self._config_dir = f"{hass.config.config_dir}/{CONFIG_DISCRETE_NAME}" if CONFIG_FOLDER_DISCRETE else hass.config.config_dir
        (Path(self._config_dir).mkdir(parents=False, exist_ok=True)) if CONFIG_FOLDER_DISCRETE else None
        _LOGGER.debug("Configuration directory is %s", self._config_dir)
        self.migrate_config_files()

    def migrate_config_files(self) -> None:
        """Migrate config files to discrete folder if required."""

        source_path = Path(self._config_dir) / ".." if CONFIG_FOLDER_DISCRETE else Path(self._config_dir) / "solcast_solar"
        if source_path.exists():
            for file in source_path.glob("solcast*.json"):
                target_path = Path(self._config_dir) / file.name
                _LOGGER.info("Migrating config directory file %s to %s", file.resolve(), target_path)
                file.replace(target_path)

        unlinked: list[str] = []
        for file in Path(self._config_dir).glob("solcast*.json"):
            if file.stat().st_size == 0:
                _LOGGER.critical("Removing zero-length file %s", file.resolve())
                file.unlink()
                unlinked.append(str(file.name))
            else:
                _LOGGER.debug("File %s has length %d", file.resolve(), file.stat().st_size)
        if unlinked:
            _LOGGER.debug("Raise issue `%s` for files %s", ISSUE_CORRUPT_FILE, str(unlinked))
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                ISSUE_CORRUPT_FILE,
                is_fixable=False,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_CORRUPT_FILE,
                translation_placeholders={
                    FILES: str(unlinked),
                },
                learn_more_url=LEARN_MORE_CORRUPT_FILE,
            )
        with contextlib.suppress(OSError):
            ((Path(self._config_dir) / "solcast_solar").rmdir()) if not CONFIG_FOLDER_DISCRETE else None

    async def tasks_cancel(self):
        """Cancel all tasks."""

        for task, cancel in self.tasks.items():
            _LOGGER.debug("Cancelling solcastapi task %s", task)
            cancel.cancel()

    async def set_options(self, options: MappingProxyType[str, Any]):
        """Set the class option variables (called by __init__ to avoid an integration reload).

        Arguments:
            options (dict): The integration entry options.
        """
        self.damp = {str(hour): options[f"damp{hour:02}"] for hour in range(24)}
        self.options = ConnectionOptions(
            # All these options require a reload, and can not be dynamically set, hence retrieval from self.options...
            self.options.api_key,
            self.options.api_quota,
            self.options.host,
            self.options.file_path,
            self.options.tz,
            self.options.auto_update,
            # Options that can be dynamically set...
            self.damp,
            options[CUSTOM_HOUR_SENSOR],
            options.get(KEY_ESTIMATE, self.options.key_estimate),
            options.get(HARD_LIMIT_API, "100.0"),
            options[BRK_ESTIMATE],
            options[BRK_ESTIMATE10],
            options[BRK_ESTIMATE90],
            options[BRK_SITE],
            options[BRK_HALFHOURLY],
            options[BRK_HOURLY],
            options[BRK_SITE_DETAILED],
            options[EXCLUDE_SITES],
            options[GET_ACTUALS],
            options[USE_ACTUALS],
            options[GENERATION_ENTITIES],
            options[SITE_EXPORT_ENTITY],
            options[SITE_EXPORT_LIMIT],
            options[AUTO_DAMPEN],
        )
        self.hard_limit = self.options.hard_limit
        self._use_forecast_confidence = f"pv_{self.options.key_estimate}"
        self.estimate_set = self.__get_estimate_set(self.options)

    def _advanced_options_with_aliases(self) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
        """Return advanced options including aliases."""

        deprecated: dict[str, str] = {}
        advanced_options_with_aliases = copy.deepcopy(ADVANCED_OPTIONS)
        for option, characteristics in advanced_options_with_aliases.copy().items():
            advanced_options_with_aliases[option][CURRENT_NAME] = option
            for alias in characteristics.get(ALIASES, []):
                if not (
                    not alias[DEPRECATED]
                    and (
                        dt.strptime(
                            alias.get(STOPS_WORKING, dt.strftime(dt.now(self.options.tz) - timedelta(days=1), DT_DATE_ONLY_FORMAT)),
                            DT_DATE_ONLY_FORMAT,
                        ).date()
                        > dt.now(self.options.tz).date()
                    )
                ):
                    advanced_options_with_aliases[alias[NAME]] = characteristics
                    del advanced_options_with_aliases[alias[NAME]][ALIASES]
                    advanced_options_with_aliases[alias[NAME]][CURRENT_NAME] = option
                    if alias[DEPRECATED]:
                        deprecated[alias[NAME]] = alias.get(STOPS_WORKING)
        return advanced_options_with_aliases, deprecated

    def _advanced_with_aliases(self, names: dict[str, Any]) -> list[str]:
        """Return advanced options including aliases."""

        advanced_options_with_aliases, _ = self._advanced_options_with_aliases()
        present_names: list[str] = []
        name: str
        for name in names:
            if advanced_options_with_aliases.get(name) is not None:
                present_names.append(advanced_options_with_aliases[name][CURRENT_NAME])
            else:
                present_names.extend(
                    [
                        characteristics[CURRENT_NAME]
                        for _, characteristics in advanced_options_with_aliases.items()
                        for alias in characteristics.get(ALIASES, [])
                        if name == alias[NAME]
                    ]
                )
        return present_names

    async def read_advanced_options(self) -> bool:  # noqa: C901
        """Read advanced JSON file options, validate and set them."""

        advanced_options_proposal: dict[str, Any] = copy.deepcopy(self.advanced_options)
        change = False
        if Path(self._filename_advanced).exists():
            _LOGGER.debug("Advanced options file %s exists", self._filename_advanced)
            deprecated_in_use: dict[str, str] = {}
            problems: list[str] = []

            def add_problem(issue_problem: str, *args) -> None:
                """Add an advanced option problem to the issues registry."""
                nonlocal problems
                problem = issue_problem % args if args else issue_problem
                _LOGGER.error(problem)
                problems.append(problem)

            async def add_problem_later(issue_problem: str, *args) -> None:
                """Add an advanced option problem to the issues registry."""
                try:
                    if self.hass is not None:
                        problem = issue_problem % args if args else issue_problem
                        _LOGGER.warning("Raise issue in 60 seconds if unresolved: %s", problem)
                        for _ in range(600):
                            await asyncio.sleep(0.1)
                        _LOGGER.error(problem)
                        await raise_or_clear_advanced_problems([problem], self.hass)
                except asyncio.CancelledError:
                    self.tasks.pop(ADVANCED_INVALID_JSON_TASK, None)

            try:
                async with aiofiles.open(self._filename_advanced) as file:
                    _VALIDATION = {
                        ADVANCED_OPTION.INT: r"^\d+$",
                        ADVANCED_OPTION.TIME: r"^([01]?[0-9]|2[0-3]):[03]{1}0$",
                    }
                    advanced_options_with_aliases = self._advanced_options_with_aliases()

                    content = await file.read()
                    if content.replace("\n", "").replace("\r", "").strip() != "":  # i.e. not empty
                        response_json = ""
                        value: int | float | str | list[str] | None
                        new_value: int | float | str | list[str]
                        if self.tasks.get(ADVANCED_INVALID_JSON_TASK) is not None:
                            self.tasks[ADVANCED_INVALID_JSON_TASK].cancel()
                            self.tasks.pop(ADVANCED_INVALID_JSON_TASK)
                        with contextlib.suppress(json.JSONDecodeError):
                            response_json = json.loads(content)
                        if not isinstance(response_json, dict):
                            self.tasks[ADVANCED_INVALID_JSON_TASK] = asyncio.create_task(
                                add_problem_later("Advanced options file invalid format, expected JSON `dict`: %s", self._filename_advanced)
                            )
                            return change
                        options_present = self._advanced_with_aliases(response_json)
                        for option, new_value in response_json.items():
                            if advanced_options_with_aliases[0].get(option) is None:
                                add_problem("Unknown option: %s, ignored", option)
                                continue
                            if option in advanced_options_with_aliases[1]:
                                deprecated_in_use[option] = advanced_options_with_aliases[0][option][CURRENT_NAME]
                                _LOGGER.warning(
                                    "Advanced option %s is deprecated, please use %s",
                                    option,
                                    advanced_options_with_aliases[0][option][CURRENT_NAME],
                                )
                            value = self.advanced_options.get(option)
                            if new_value != value:
                                valid = True
                                if isinstance(new_value, type(value)):
                                    match advanced_options_with_aliases[0][option][ADVANCED_TYPE]:
                                        case ADVANCED_OPTION.INT | ADVANCED_OPTION.FLOAT:
                                            if (
                                                new_value < advanced_options_with_aliases[0][option][MINIMUM]
                                                or new_value > advanced_options_with_aliases[0][option][MAXIMUM]
                                            ):
                                                add_problem(
                                                    "Invalid value for advanced option %s: %s (must be %s-%s)",
                                                    option,
                                                    new_value,
                                                    advanced_options_with_aliases[0][option][MINIMUM],
                                                    advanced_options_with_aliases[0][option][MAXIMUM],
                                                )
                                                valid = False
                                        # case ADVANCED_OPTION.TIME:
                                        #    if re.match(_VALIDATION[ADVANCED_OPTION.TIME], new_value) is None:  # pyright: ignore[reportArgumentType, reportCallIssue]
                                        #        add_problem("Invalid time in advanced option %s: %s", option, new_value)
                                        #        valid = False
                                        case ADVANCED_OPTION.LIST_INT | ADVANCED_OPTION.LIST_TIME:
                                            member_type = advanced_options_with_aliases[0][option][ADVANCED_TYPE].split("_")[1]
                                            seen_members: list[Any] = []
                                            member: Any
                                            for member in new_value:  # pyright: ignore[reportOptionalIterable, reportGeneralTypeIssues]
                                                if re.match(_VALIDATION[member_type], str(member)) is None:
                                                    add_problem("Invalid %s in advanced option %s: %s", member_type, option, member)
                                                    valid = False
                                                    continue
                                                if member in seen_members:
                                                    add_problem("Duplicate %s in advanced option %s: %s", member_type, option, member)
                                                    valid = False
                                                    continue
                                                seen_members.append(member)
                                        case _:
                                            pass
                                    if (
                                        option == ADVANCED_GRANULAR_DAMPENING_DELTA_ADJUSTMENT
                                        and new_value
                                        and not self.options.get_actuals
                                    ):
                                        add_problem("Granular dampening delta adjustment requires estimated actuals to be fetched")
                                        valid = False
                                else:
                                    add_problem("Type mismatch for advanced option %s: should be %s", option, type(value).__name__)
                                    valid = False
                                if valid:
                                    advanced_options_proposal[advanced_options_with_aliases[0][option][CURRENT_NAME]] = new_value
                                    if advanced_options_with_aliases[0][option][ADVANCED_TYPE] in (
                                        ADVANCED_OPTION.FLOAT,
                                        ADVANCED_OPTION.INT,
                                    ):
                                        _LOGGER.debug(
                                            "Advanced option proposed %s: %s",
                                            advanced_options_with_aliases[0][option][CURRENT_NAME],
                                            new_value,
                                        )

                    invalid: list[str] = []
                    for option, value in advanced_options_proposal.items():
                        if advanced_options_with_aliases[0][option].get(OPTION_GREATER_THAN_OR_EQUAL) is not None:
                            if any(
                                value < advanced_options_proposal[opt]
                                for opt in advanced_options_with_aliases[0][option][OPTION_GREATER_THAN_OR_EQUAL]
                            ):
                                add_problem(
                                    "Advanced option %s: %s must be greater than or equal to the value of %s",
                                    option,
                                    value,
                                    ", ".join(
                                        [
                                            f"{opt} ({advanced_options_proposal[opt]})"
                                            for opt in advanced_options_with_aliases[0][option][OPTION_GREATER_THAN_OR_EQUAL]
                                        ]
                                    ),
                                )
                                invalid.append(option)
                        if advanced_options_with_aliases[0][option].get(OPTION_LESS_THAN_OR_EQUAL) is not None:
                            if any(
                                value > advanced_options_proposal[opt]
                                for opt in advanced_options_with_aliases[0][option][OPTION_LESS_THAN_OR_EQUAL]
                            ):
                                add_problem(
                                    "Advanced option %s: %s must be less than or equal to the value of %s",
                                    option,
                                    value,
                                    ", ".join(
                                        [
                                            f"{opt} ({advanced_options_proposal[opt]})"
                                            for opt in advanced_options_with_aliases[0][option][OPTION_LESS_THAN_OR_EQUAL]
                                        ]
                                    ),
                                )
                                invalid.append(option)
                        if advanced_options_with_aliases[0][option].get(OPTION_NOT_SET_IF) is not None:
                            if any(advanced_options_proposal[opt] for opt in advanced_options_with_aliases[0][option][OPTION_NOT_SET_IF]):
                                add_problem(
                                    "Advanced option %s: %s can not be set with %s",
                                    option,
                                    value,
                                    ", ".join(
                                        [
                                            f"{opt}: {advanced_options_proposal[opt]}"
                                            for opt in advanced_options_with_aliases[0][option][OPTION_NOT_SET_IF]
                                        ]
                                    ),
                                )
                                invalid.append(option)

                    for option, value in advanced_options_proposal.items():
                        default = advanced_options_with_aliases[0][option][DEFAULT]
                        option = advanced_options_with_aliases[0][option][CURRENT_NAME]
                        if option in invalid:
                            advanced_options_proposal[advanced_options_with_aliases[0][option][CURRENT_NAME]] = self.advanced_options.get(
                                advanced_options_with_aliases[0][option][CURRENT_NAME], default
                            )
                            continue
                        if option not in options_present:
                            if value != default:
                                advanced_options_proposal[option] = default
                                _LOGGER.debug("Advanced option default set %s: %s", option, default)
                                change = True
                        elif value != default:
                            _LOGGER.debug("Advanced option set %s: %s", option, value)
                            change = True
                        elif value != self.advanced_options.get(option):
                            advanced_options_proposal[option] = default
                            _LOGGER.debug("Advanced option default set %s: %s", option, default)
                            change = True
                    self.advanced_options.update(advanced_options_proposal)
            finally:
                await raise_or_clear_advanced_problems(problems, self.hass)
                await raise_or_clear_advanced_deprecated(
                    deprecated_in_use,
                    self.hass,
                    stops_working={
                        o: dt.strptime(stops, DT_DATE_ONLY_FORMAT)
                        for o, stops in advanced_options_with_aliases[1].items()
                        if stops is not None
                    },
                )

        return change

    def get_filename_advanced(self) -> str:
        """Return the advanced configuration filename."""
        return self._filename_advanced

    def log_advanced_options(self) -> None:
        """Log the advanced options that are set differently to their defaults."""

        advanced_options_with_aliases, _ = self._advanced_options_with_aliases()
        for key, value in advanced_options_with_aliases.items():
            if key not in self.advanced_options or self.advanced_options.get(key) != value[DEFAULT]:
                _LOGGER.debug("Advanced option set %s: %s", key, self.advanced_options.get(key))

    def set_default_advanced_options(self) -> None:
        """Set the default advanced options."""

        advanced_options_with_aliases, _ = self._advanced_options_with_aliases()
        initial = not self.advanced_options
        for key, value in advanced_options_with_aliases.items():
            if key not in self.advanced_options or self.advanced_options.get(key) != value[DEFAULT]:
                self.advanced_options[key] = value[DEFAULT]
                if not initial:
                    _LOGGER.debug("Advanced option default set %s: %s", key, value[DEFAULT])

    def get_filename_dampening(self) -> str:
        """Return the dampening configuration filename."""
        return self._filename_dampening

    def __get_estimate_set(self, options: ConnectionOptions) -> list[str]:
        estimate_set: list[str] = []
        if options.attr_brk_estimate:
            estimate_set.append(ESTIMATE)
        if options.attr_brk_estimate10:
            estimate_set.append(ESTIMATE10)
        if options.attr_brk_estimate90:
            estimate_set.append(ESTIMATE90)
        return estimate_set

    def get_data(self) -> dict[str, Any]:
        """Return the dampened data dictionary.

        Returns:
            dict[str, Any]: Dampened forecast detail list of the sum of all site forecasts.
        """
        return self._data

    def get_data_generation(self) -> dict[str, Any]:
        """Return the generation dictionary.

        Returns:
            dict[str, Any]: Generation forecast detail list of the sum of all site forecasts.
        """
        return self._data_generation

    def is_stale_data(self) -> bool:
        """Return whether the forecast was last updated some time ago (i.e. is stale).

        Returns:
            bool: True for stale, False if updated recently.
        """
        last_updated = self.get_last_updated()
        return last_updated is not None and last_updated < self.get_day_start_utc(future=-1)

    def is_stale_usage_cache(self) -> bool:
        """Return whether the usage cache was last reset over 24-hours ago (i.e. is stale).

        Returns:
            bool: True for stale, False if reset recently.
        """
        api_keys = self.options.api_key.split(",")
        for api_key in api_keys:
            api_key = api_key.strip()
            api_used_reset = self._api_used_reset.get(api_key)
            if api_used_reset is not None and api_used_reset < self.__get_utc_previous_midnight():
                return True
        return False

    def __is_multi_key(self) -> bool:
        """Test whether multiple API keys are in use.

        Returns:
            bool: True for multiple API Solcast accounts configured. If configured then separate files will be used for caches.
        """
        return len(self.options.api_key.split(",")) > 1

    def __get_usage_cache_filename(self, api_key: str) -> str:
        """Build an API cache filename.

        Arguments:
            api_key (str): An individual Solcast account API key.

        Returns:
            str: A fully qualified cache filename using a simple name or separate files for more than one API key.
        """
        return f"{self._config_dir}/solcast-usage{'' if not self.__is_multi_key() else '-' + api_key}.json"

    def __get_sites_cache_filename(self, api_key: str) -> str:
        """Build a site details cache filename.

        Arguments:
            api_key (str): An individual Solcast account API key.

        Returns:
            str: A fully qualified cache filename using a simple name or separate files for more than one API key.
        """
        return f"{self._config_dir}/solcast-sites{'' if not self.__is_multi_key() else '-' + api_key}.json"

    async def serialise_data(self, data: dict[str, Any], filename: str) -> bool:
        """Serialize data to file.

        Arguments:
            data (dict): The data to serialise.
            filename (str): The name of the file

        Returns:
            bool: Success or failure.
        """
        if self._loaded_data and data[LAST_UPDATED] != dt.fromtimestamp(0, datetime.UTC):
            payload = json.dumps(data, ensure_ascii=False, cls=DateTimeEncoder)
            async with self._serialise_lock, aiofiles.open(filename, "w") as file:
                await file.write(payload)
            log_file = {
                self._filename: "dampened",
                self._filename_undampened: "undampened",
                self._filename_actuals: "estimated actual",
                self._filename_actuals_dampened: "dampened estimated actual",
                self._filename_generation: "generation",
            }
            _LOGGER.debug(
                "Saved %s cache",
                log_file.get(filename, UNKNOWN),
            )
            return True
        _LOGGER.warning("Not serialising empty data for %s", filename)
        return False

    async def __sites_data(self, prior_crash: bool = False, use_cache: bool = True) -> tuple[int, str, str]:  # noqa: C901
        """Request site details.

        If the sites cannot be loaded then the integration cannot function, and this will
        result in Home Assistant repeatedly trying to initialise.

        If the sites cache exists and is valid then it is loaded on API error.

        Arguments:
            prior_crash (bool): When a prior crash during init has occurred use cached sites, and do not call Solcast.
            use_cache (bool): When True, use the cache if it exists and is valid.

        Returns:
            tuple[int, str, str]: The status code, message and relevant API key.
        """
        one_only = False
        status = 999

        async def load_cache(cache_filename: str) -> dict[str, Any]:
            _LOGGER.info("Loading cached sites for %s", redact_api_key(api_key))
            async with aiofiles.open(cache_filename) as file:
                return json.loads(await file.read())

        async def save_cache(cache_filename: str, response_data: dict[str, Any]):
            _LOGGER.debug("Writing sites cache for %s", redact_api_key(api_key))
            async with self._serialise_lock, aiofiles.open(cache_filename, "w") as file:
                await file.write(json.dumps(response_json, ensure_ascii=False))

        async def load_dismissals(cache_filename: str) -> None:
            _LOGGER.info("Loading warning dismissals for %s", redact_api_key(api_key))
            async with aiofiles.open(cache_filename) as file:
                content = json.loads(await file.read())
                sites = content.get(SITES, [])
                for site in sites:
                    site_id = site.get(RESOURCE_ID)
                    if site_id is not None:
                        self._dismissal[site_id] = False if site.get(DISMISSAL) is None else site.get(DISMISSAL)

        def cached_sites_unavailable(at_least_one_only: bool = False) -> None:
            nonlocal one_only

            if not at_least_one_only:
                _LOGGER.error(
                    "Cached sites are not yet available for %s to cope with API call failure",
                    redact_api_key(api_key),
                )
                _LOGGER.error("At least one successful API 'get sites' call is needed, so the integration will not function correctly")
                one_only = True

        def set_sites(response_json: dict[str, Any], api_key: str) -> None:
            sites_data = response_json
            _LOGGER.debug(
                "Sites data %s",
                redact_msg_api_key(redact_lat_lon(str(sites_data)), api_key),
            )
            for site in sites_data[SITES]:
                site[API_KEY] = api_key
                site.pop(SITE_ATTRIBUTE_LONGITUDE, None)
                self._site_latitude[site[RESOURCE_ID]][SITE_ATTRIBUTE_LATITUDE] = site.pop(SITE_ATTRIBUTE_LATITUDE, None)
                self._site_latitude[site[RESOURCE_ID]][SITE_ATTRIBUTE_AZIMUTH] = site[SITE_ATTRIBUTE_AZIMUTH]
            self.sites = self.sites + sites_data[SITES]
            self._api_used_reset[api_key] = None
            _LOGGER.debug(
                "Sites loaded%s",
                (" for " + redact_api_key(api_key)) if self.__is_multi_key() else "",
            )

        def check_rekey(response_json: dict[str, Any], api_key: str) -> bool:
            _LOGGER.debug("Checking rekey for %s", redact_api_key(api_key))

            cache_status = False
            all_sites = sorted([site[RESOURCE_ID] for site in response_json[SITES]])
            self._rekey[api_key] = None
            for key in self._extant_sites:
                extant_sites = sorted([site[RESOURCE_ID] for site in self._extant_sites[key]])
                if all_sites == extant_sites:
                    if api_key != key:
                        # Re-keyed API key...
                        # * Update the sites cache to the new key (an API failure may have occurred on load).
                        # Note that if an API failure had occurred then the sites are not really known, so this key change is a guess at best.
                        _LOGGER.info("API key %s has changed", redact_api_key(api_key))
                        self._rekey[api_key] = key
                        for site in response_json[SITES]:
                            site[API_KEY] = api_key
                    cache_status = True
            return cache_status

        self.sites = []
        api_key_in_error = ""
        api_keys = self.options.api_key.split(",")

        try:
            for api_key in api_keys:
                response_json: dict[str, Any] = {}
                api_key = api_key.strip()
                cache_filename = self.__get_sites_cache_filename(api_key)
                cache_exists = Path(cache_filename).is_file()
                if not cache_exists:
                    prior_crash = False
                else:
                    await load_dismissals(cache_filename)
                _LOGGER.debug(
                    "%s",
                    f"Sites cache {'exists' if cache_exists else 'does not yet exist'} for {redact_api_key(api_key)}",
                )
                success = False

                if not prior_crash:
                    url = f"{self.advanced_options[ADVANCED_SOLCAST_URL]}/rooftop_sites"
                    params = {FORMAT: JSON, API_KEY: api_key}
                    _LOGGER.debug("Connecting to %s?format=json&api_key=%s", url, redact_api_key(api_key))
                    response: ClientResponse = await self._aiohttp_session.get(url=url, params=params, headers=self.headers, ssl=False)
                    status = response.status
                    (_LOGGER.debug if status == 200 else _LOGGER.warning)(
                        "HTTP session returned status %s%s",
                        http_status_translate(status),
                        ", trying cache" if status not in (200, 403) and cache_exists and use_cache else "",
                    )
                    text_response = ""
                    try:
                        text_response = await response.text()
                        if text_response != "":
                            response_json = json.loads(text_response)
                    except json.decoder.JSONDecodeError:
                        _LOGGER.error("API did not return a json object, returned `%s`", text_response)
                        status = 500
                else:
                    status = 999  # Force a cache load instead of using the API

                if status == 200:
                    for site in response_json.get(SITES, []):
                        site[API_KEY] = api_key
                        site[DISMISSAL] = self._dismissal.get(site[RESOURCE_ID], False)
                    if response_json[TOTAL_RECORDS] > 0:
                        set_sites(response_json, api_key)
                        _ = check_rekey(response_json, api_key)
                        await save_cache(cache_filename, response_json)
                        success = True
                        self.sites_status = SitesStatus.OK
                    else:
                        _LOGGER.error(
                            "No sites for the API key %s are configured at solcast.com",
                            redact_api_key(api_key),
                        )
                        cache_exists = False  # Prevent cache load if no sites
                        self.sites_status = SitesStatus.NO_SITES
                        api_key_in_error = redact_api_key(api_key)
                        break

                if not success:
                    if cache_exists and use_cache:
                        _LOGGER.warning(
                            "Get sites failed, last call result: %s, using cached data",
                            http_status_translate(status),
                        )
                    else:
                        _LOGGER.error(
                            "Get sites failed, last call result: %s",
                            http_status_translate(status),
                        )
                    if status != 200:
                        api_key_in_error = redact_api_key(api_key)
                    if status != 200 and cache_exists and use_cache:
                        response_json = await load_cache(cache_filename)
                        success = True
                        self.sites_status = SitesStatus.OK
                        if status == 403:
                            self.sites_status = SitesStatus.BAD_KEY
                            break
                        status = 200
                        if not check_rekey(response_json, api_key):
                            self.sites_status = SitesStatus.CACHE_INVALID
                            _LOGGER.info(
                                "API key %s has changed and sites are different invalidating the cache, not using cached data",
                                redact_api_key(api_key),
                            )
                            success = False
                        if success:
                            set_sites(response_json, api_key)
                    elif not cache_exists:
                        cached_sites_unavailable()
                        if status in (401, 403):
                            self.sites_status = SitesStatus.BAD_KEY
                            break
                        if status in (429, 420):
                            self.sites_status = SitesStatus.API_BUSY
                            break
                        self.sites_status = SitesStatus.ERROR
                        api_key_in_error = redact_api_key(api_key)
                        break

                if status == 200 and success:
                    pass
                else:
                    cached_sites_unavailable(at_least_one_only=True)
        except (ClientConnectionError, ClientResponseError, ConnectionRefusedError, TimeoutError) as e:
            _LOGGER.error("Connection error: %s", e)
            self.sites_status = SitesStatus.ERROR
            api_key_in_error = ""
            _LOGGER.error("Error retrieving sites: %s", e)
            if use_cache:
                _LOGGER.info("Attempting to continue with cached sites")
                error = False
                self.sites = []
                for api_key in api_keys:
                    api_key = api_key.strip()
                    cache_filename = self.__get_sites_cache_filename(api_key)
                    if Path(cache_filename).is_file():  # Cache exists, so load it
                        response_json = await load_cache(cache_filename)
                        set_sites(response_json, api_key)
                        _ = check_rekey(response_json, api_key)
                        self.sites_status = SitesStatus.OK
                    else:
                        self.sites_status = SitesStatus.ERROR
                        error = True
                        cached_sites_unavailable()
                        api_key_in_error = redact_api_key(api_key)
                        break
                if error:
                    _LOGGER.error(
                        "Suggestion: Check your overall HA configuration, specifically networking related (Is IPV6 an issue for you? DNS? Proxy?)"
                    )
            return (
                200 if self.sites_status == SitesStatus.OK else 999,
                "Cached sites loaded" if self.sites_status == SitesStatus.OK else "Cached sites not loaded",
                api_key_in_error,
            )
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Exception in __sites_data(): %s: %s", e, traceback.format_exc())
            return 999, f"Exception in __sites_data(): {e}", ""

        return status, http_status_translate(status), api_key_in_error

    async def __serialise_usage(self, api_key: str, reset: bool = False) -> None:
        """Serialise the usage cache file.

        Arguments:
            api_key (str): An individual Solcast account API key.
            reset (bool): Whether to reset API key usage to zero.
        """
        filename = self.__get_usage_cache_filename(api_key)
        if reset:
            self._api_used_reset[api_key] = self.__get_utc_previous_midnight()
        _LOGGER.debug(
            "Writing API usage cache %s",
            redact_msg_api_key(filename, api_key),
        )
        json_content: dict[str, Any] = {
            DAILY_LIMIT: self._api_limit[api_key],
            DAILY_LIMIT_CONSUMED: self._api_used[api_key],
            RESET: self._api_used_reset[api_key],
        }
        payload = json.dumps(json_content, ensure_ascii=False, cls=DateTimeEncoder)
        async with self._serialise_lock, aiofiles.open(filename, "w") as file:
            await file.write(payload)

    async def __sites_usage(self) -> None:
        """Load api usage cache.

        The Solcast API for hobbyists is limited in the number of API calls that are
        allowed, and usage of this quota is tracked by the integration. There is not
        currently an API call to determine limit and usage, hence this tracking.

        The limit is specified by the user in integration configuration.
        """
        try:

            async def sanitise_and_set_usage(api_key: str, usage: dict[str, Any]):
                self._api_limit[api_key] = usage.get(DAILY_LIMIT, 10)
                assert isinstance(self._api_limit[api_key], int), "daily_limit is not an integer"
                self._api_used[api_key] = usage.get(DAILY_LIMIT_CONSUMED, 0)
                assert isinstance(self._api_used[api_key], int), "daily_limit_consumed is not an integer"
                self._api_used_reset[api_key] = usage.get(RESET, self.__get_utc_previous_midnight())
                assert isinstance(self._api_used_reset[api_key], dt), "reset is not a datetime"
                if (used_reset := self._api_used_reset[api_key]) is not None:
                    _LOGGER.debug(
                        "Usage cache for %s last reset %s",
                        redact_api_key(api_key),
                        used_reset.astimezone(self._tz).strftime(DT_DATE_FORMAT),
                    )
                if usage[DAILY_LIMIT] != quota[api_key]:  # Limit has been adjusted, so rewrite the cache.
                    self._api_limit[api_key] = quota[api_key]
                    await self.__serialise_usage(api_key)
                    _LOGGER.info("Usage loaded and cache updated with new limit")
                else:
                    _LOGGER.debug(
                        "Usage loaded%s",
                        (" for " + redact_api_key(api_key)) if self.__is_multi_key() else "",
                    )
                if used_reset is not None:
                    if self.get_real_now_utc() > used_reset + timedelta(hours=24):
                        _LOGGER.warning(
                            "Resetting usage for %s, last reset was more than 24-hours ago",
                            redact_api_key(api_key),
                        )
                        self._api_used[api_key] = 0
                        await self.__serialise_usage(api_key, reset=True)

            self.usage_status = UsageStatus.OK
            api_keys = self.options.api_key.split(",")
            api_quota = self.options.api_quota.split(",")
            for index in range(len(api_keys)):  # If only one quota value is present, yet there are multiple sites then use the same quota.
                if len(api_quota) < index + 1:
                    api_quota.append(api_quota[index - 1])
            quota = {api_keys[index].strip(): int(api_quota[index].strip()) for index in range(len(api_quota))}

            for api_key in api_keys:
                api_key = api_key.strip()
                old_api_key = self._rekey.get(api_key)  # For a re-keyed API key.
                cache_filename = self.__get_usage_cache_filename(api_key)
                _LOGGER.debug(
                    "%s for %s",
                    "Usage cache " + ("exists" if Path(cache_filename).is_file() else "does not yet exist"),
                    redact_api_key(api_key),
                )
                cache = True
                usage: dict[str, Any] = {}
                if Path(cache_filename).is_file():
                    usage = self._extant_usage.get(old_api_key, {}) if old_api_key is not None else {}
                    if not old_api_key:
                        async with aiofiles.open(cache_filename) as file:
                            try:
                                usage = json.loads(await file.read(), cls=JSONDecoder)
                            except json.decoder.JSONDecodeError:
                                _LOGGER.error(
                                    "The usage cache for %s is corrupt, re-creating cache with zero usage",
                                    redact_api_key(api_key),
                                )
                                cache = False
                    if cache and usage:
                        await sanitise_and_set_usage(api_key, usage)
                else:
                    cache = False
                if not cache:
                    if old_api_key:
                        # Multi-key, so the old cache has been removed
                        _LOGGER.debug("Using extant cache data for API key %s", redact_api_key(api_key))
                        usage = self._extant_usage.get(old_api_key, {}) if old_api_key is not None else {}
                        await sanitise_and_set_usage(api_key, usage)
                    else:
                        _LOGGER.warning("Creating usage cache for %s, assuming zero API used", redact_api_key(api_key))
                        self._api_limit[api_key] = quota[api_key]
                        self._api_used[api_key] = 0
                        self._api_used_reset[api_key] = self.__get_utc_previous_midnight()
                    await self.__serialise_usage(api_key, reset=True)
                _LOGGER.debug(
                    "API counter for %s is %d/%d",
                    redact_api_key(api_key),
                    self._api_used[api_key],
                    self._api_limit[api_key],
                )

        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Exception in __sites_usage(): %s: %s", e, traceback.format_exc())
            self.usage_status = UsageStatus.ERROR

    async def reset_usage_cache(self):
        """Reset all usage caches."""
        api_keys = self.options.api_key.split(",")
        for api_key in api_keys:
            api_key = api_key.strip()
            self._api_used[api_key] = 0
            await self.__serialise_usage(api_key, reset=True)

    async def cleanup_issues(self, any_unusual: bool = True) -> None:
        """Check and clean up any existing issues if the conditions are now resolved."""
        issue_registry = ir.async_get(self.hass)
        for issue in [ISSUE_UNUSUAL_AZIMUTH_NORTHERN, ISSUE_UNUSUAL_AZIMUTH_SOUTHERN]:
            if (i := issue_registry.async_get_issue(DOMAIN, issue)) is not None:
                if (
                    i.dismissed_version is not None
                    and i.translation_placeholders is not None
                    and self._dismissal.get(i.translation_placeholders.get(SITE, ""), False)
                ) or not any_unusual:
                    _LOGGER.debug("Remove %sissue for %s", "ignored " if i.dismissed_version is not None else "", issue)
                    ir.async_delete_issue(self.hass, DOMAIN, issue)

    async def get_sites_and_usage(self, prior_crash: bool = False, use_cache: bool = True) -> tuple[int, str, str]:  # noqa: C901
        """Get the sites and usage, and validate API key changes against the cache files in use.

        Both the sites and usage are gathered here.

        Additionally, transitions from a multi-API key set up to a single API key are
        tracked at startup, and necessary adjustments are made to file naming.

        Single key installations have cache files named like `solcast-sites.json`, while
        multi-key installations have caches named `solcast-sites-api_key.json`

        The reason is that sites are loaded in groups of API key, and similarly for API
        usage, so these must be cached separately.

        Arguments:
            prior_crash (bool): When a prior crash during init has occurred use cached sites, and do not call Solcast.
            use_cache (bool): When True, use the cache if it exists and is valid.

        Returns:
            tuple[int, str, str]: The status code, message and relevant API key from load sites.
        """
        issue_registry = ir.async_get(self.hass)

        def rename(file1: str, file2: str, api_key: str):
            if Path(file1).is_file():
                _LOGGER.info("Renaming %s to %s", redact_msg_api_key(file1, api_key), redact_msg_api_key(file2, api_key))
                Path(file1).rename(Path(file2))

        async def test_unusual_azimuth() -> None:
            """Test for unusual azimuth values."""
            _LOGGER.debug("Testing for unusual azimuth values")
            any_unusual = False
            any_raised = False
            old_sites = copy.deepcopy(self.sites)
            raise_issue = ""
            for site, v in self._site_latitude.items():
                unusual = False
                proposal = 0
                if v[SITE_ATTRIBUTE_LATITUDE] is None:
                    # Using cached data, so latitude is not known
                    continue
                if SITE_ATTRIBUTE_LATITUDE in v and SITE_ATTRIBUTE_AZIMUTH in v:
                    azimuth = v[SITE_ATTRIBUTE_AZIMUTH]
                    if azimuth is not None:
                        if v[SITE_ATTRIBUTE_LATITUDE] > 0:  # pyright: ignore[reportOptionalOperand] - weird pyright warning
                            # Northern hemisphere, so azimuth should be 90 to 180, or -90 to -180
                            raise_issue = ISSUE_UNUSUAL_AZIMUTH_NORTHERN
                            if azimuth > 0 and not (90 <= azimuth <= 180):
                                unusual = True
                                proposal = 180 - int(azimuth)
                            if azimuth < 0 and not (-180 <= azimuth <= -90):
                                unusual = True
                                proposal = -180 - int(azimuth)
                        else:
                            # Southern hemisphere, so azimuth should be 0 to 90, or -90 to 0
                            raise_issue = ISSUE_UNUSUAL_AZIMUTH_SOUTHERN
                            if azimuth > 0 and not (0 <= azimuth <= 90):
                                unusual = True
                                proposal = 180 - int(azimuth)
                            if azimuth < 0 and not (-90 <= azimuth <= 0):
                                unusual = True
                                proposal = -180 - int(azimuth)
                    if unusual:
                        log = (
                            _LOGGER.warning
                            if issue_registry.async_get_issue(DOMAIN, ISSUE_UNUSUAL_AZIMUTH_NORTHERN) is None
                            and issue_registry.async_get_issue(DOMAIN, ISSUE_UNUSUAL_AZIMUTH_SOUTHERN) is None
                            and not self._dismissal.get(site, False)
                            else _LOGGER.debug
                        )
                        log(redact_lat_lon_simple(f"Unusual azimuth {azimuth} for site {site}, latitude {v[SITE_ATTRIBUTE_LATITUDE]}"))

                    if unusual and not any_raised and raise_issue != "":
                        if not self._dismissal.get(site, False):
                            # If azimuth is unusual then raise an issue.
                            _LOGGER.debug("Raise issue `%s` for site %s", raise_issue, site)
                            any_raised = True
                            ir.async_create_issue(
                                self.hass,
                                DOMAIN,
                                raise_issue,
                                is_fixable=False,
                                is_persistent=True,
                                severity=ir.IssueSeverity.WARNING,
                                translation_key=raise_issue,
                                translation_placeholders={
                                    SITE: site,
                                    SITE_ATTRIBUTE_LATITUDE: str(v[SITE_ATTRIBUTE_LATITUDE]),
                                    PROPOSAL: str(proposal),
                                    EXTANT: str(v[SITE_ATTRIBUTE_AZIMUTH]),
                                    LEARN_MORE: "",
                                },
                                learn_more_url=LEARN_MORE_UNUSUAL_AZIMUTH,
                            )
                            raise_issue = ""
                            self._dismissal[site] = True
                            for s in self.sites:
                                if s[RESOURCE_ID] == site:
                                    s[DISMISSAL] = True
                                    break
                        any_unusual = True

            await self.cleanup_issues(any_unusual)

            if self.sites != old_sites:
                # Sites have been updated with dismissables, so re-serialise the sites cache(s).
                for api_key in self.options.api_key.split(","):
                    api_key = api_key.strip()
                    cache_filename = self.__get_sites_cache_filename(api_key)
                    for site in self.sites:
                        if site.get(API_KEY) == api_key:
                            break
                    _LOGGER.debug("Re-serialising sites cache for %s", redact_api_key(api_key))
                    payload = json.dumps({SITES: [site for site in self.sites if site.get(API_KEY) == api_key]}, ensure_ascii=False)
                    async with self._serialise_lock, aiofiles.open(cache_filename, "w") as file:
                        await file.write(payload)

        async def from_single_site_to_multi(api_keys: list[str]):
            """Transition from a single API key to multiple API keys."""
            single_sites = f"{self._config_dir}/solcast-sites.json"
            single_usage = f"{self._config_dir}/solcast-usage.json"
            if Path(single_sites).is_file():
                async with aiofiles.open(single_sites) as file:
                    single_api_key = json.loads(await file.read(), cls=JSONDecoder)[SITES][0].get(API_KEY, api_keys[0])
                multi_sites = f"{self._config_dir}/solcast-sites-{single_api_key}.json"
                if not Path(multi_sites).is_file() and Path(single_sites).is_file():
                    multi_usage = f"{self._config_dir}/solcast-usage-{single_api_key}.json"
                    rename(single_sites, multi_sites, single_api_key)
                    rename(single_usage, multi_usage, single_api_key)

        async def from_multi_site_to_single(api_keys: list[str]):
            """Transition from multiple API keys to a single API key."""
            single_sites = f"{self._config_dir}/solcast-sites.json"
            if not Path(single_sites).is_file():
                rename(f"{self._config_dir}/solcast-sites-{api_keys[0]}.json", single_sites, api_keys[0])
                rename(f"{self._config_dir}/solcast-usage-{api_keys[0]}.json", f"{self._config_dir}/solcast-usage.json", api_keys[0])

        def remove_orphans(all_cached: list[str], multi_cached: list[str]):
            """Remove orphaned cache files."""
            for file in all_cached:
                if file not in multi_cached:
                    component_parts = re.search(r"(.+solcast-(sites-|usage-))(.+)(\.json)", file)
                    if component_parts is not None:
                        _LOGGER.warning(
                            "Removing orphaned %s",
                            component_parts.group(1) + "******" + component_parts.group(3)[-6:] + component_parts.group(4),
                        )
                        Path(file).unlink()

        def list_all_files() -> tuple[list[str], list[str]]:
            sites = [str(sites) for sites in Path(self._config_dir).glob("solcast-sites*.json")]
            usage = [str(usage) for usage in Path(self._config_dir).glob("solcast-usage*.json")]
            return sorted(sites), sorted(usage)

        def list_multi_key_files() -> tuple[list[str], list[str]]:
            sites = [str(sites) for sites in Path(self._config_dir).glob("solcast-sites-*.json")]
            usage = [str(usage) for usage in Path(self._config_dir).glob("solcast-usage-*.json")]
            return sorted(sites), sorted(usage)

        async def load_extant_sites_and_usage(sites: list[str], usages: list[str]):
            extant_sites: dict[str, list[dict[str, Any]]] = defaultdict(list)  # Existing sites in caches
            extant_usage: dict[str, dict[str, Any]] = defaultdict(dict)  # Existing usage in caches, separated by API key
            single_key = None
            for site in sites:
                async with aiofiles.open(site) as file:
                    try:
                        response_json = json.loads(await file.read(), cls=JSONDecoder)
                    except json.decoder.JSONDecodeError:
                        _LOGGER.error("JSONDecodeError, sites ignored: %s", site)
                        continue
                    for _site in response_json.get(SITES, []):
                        if _site.get(API_KEY):
                            extant_sites[_site[API_KEY]].append(_site)
                            if not self.__is_multi_key():
                                single_key = _site[API_KEY]
                        elif not self.__is_multi_key():  # The key is unknown because old schema version
                            extant_sites[UNKNOWN].append(_site)
            for usage in usages:
                async with aiofiles.open(usage) as file:
                    try:
                        response_json = json.loads(await file.read(), cls=JSONDecoder)
                    except json.decoder.JSONDecodeError:
                        _LOGGER.error("JSONDecodeError, usage ignored: %s", usage)
                        continue
                    match = re.search(r"solcast-usage-(.+)\.json", usage)
                    if match:
                        extant_usage[match.group(1)] = response_json
                    elif not self.__is_multi_key() and single_key:
                        extant_usage[single_key] = response_json
                    else:  # The key is unknown because old schema version
                        extant_usage[UNKNOWN] = response_json
            return extant_sites, extant_usage

        api_keys = [api_key.strip() for api_key in self.options.api_key.split(",")]
        if self.__is_multi_key():
            await from_single_site_to_multi(api_keys)
        else:
            await from_multi_site_to_single(api_keys)
        multi_sites = [f"{self._config_dir}/solcast-sites-{api_key}.json" for api_key in api_keys]
        multi_usage = [f"{self._config_dir}/solcast-usage-{api_key}.json" for api_key in api_keys]

        all_sites, all_usage = await self.hass.async_add_executor_job(list_all_files)
        multi_key_sites, multi_key_usage = await self.hass.async_add_executor_job(list_multi_key_files)
        self._extant_sites, self._extant_usage = await load_extant_sites_and_usage(all_sites, all_usage)
        remove_orphans(multi_key_sites, multi_sites)
        remove_orphans(multi_key_usage, multi_usage)

        status, message, api_key_in_error = await self.__sites_data(prior_crash=prior_crash, use_cache=use_cache)
        if self.sites_status == SitesStatus.OK:
            await test_unusual_azimuth()
            await self.__sites_usage()

        return status, message, api_key_in_error

    async def reset_api_usage(self, force: bool = False) -> None:
        """Reset the daily API usage counter.

        Arguments:
            force (bool): Force the reset even if the cache is not stale.
        """
        if force or self.is_stale_usage_cache():
            _LOGGER.debug("Reset API usage")
            for api_key in self._api_used:
                self._api_used[api_key] = 0
                await self.__serialise_usage(api_key, reset=True)
        else:
            _LOGGER.debug("Usage cache is fresh, so not resetting")

    async def serialise_granular_dampening(self) -> None:
        """Serialise the site dampening file."""
        filename = self.get_filename_dampening()
        _LOGGER.debug("Writing granular dampening to %s", filename)
        payload = json.dumps(
            self.granular_dampening,
            ensure_ascii=False,
            cls=NoIndentEncoder,
            indent=2,
        )
        async with self._serialise_lock, aiofiles.open(filename, "w") as file:
            await file.write(payload)
        self.granular_dampening_mtime = Path(filename).stat().st_mtime
        _LOGGER.debug(
            "Granular dampening file mtime %s",
            dt.fromtimestamp(self.granular_dampening_mtime, self._tz).strftime(DT_DATE_FORMAT),
        )

    async def granular_dampening_data(self) -> bool:
        """Read the current granular dampening file.

        Returns:
            bool: Granular dampening in use.
        """

        def option(enable: bool, set_allow_reset: bool = False):
            site_damp = self.entry_options.get(SITE_DAMP, False) if self.entry_options.get(SITE_DAMP) is not None else False
            if enable ^ site_damp:
                options = {**self.entry_options}
                options[SITE_DAMP] = enable
                self.entry_options[SITE_DAMP] = enable
                if set_allow_reset:
                    self._granular_allow_reset = enable
                if self.entry is not None:
                    self.hass.config_entries.async_update_entry(self.entry, options=options)
            return enable

        error = False
        return_value = False
        mtime = True
        filename = self.get_filename_dampening()
        try:
            if not Path(filename).is_file():
                self.granular_dampening = {}
                self.granular_dampening_mtime = 0
                mtime = False
                return option(GRANULAR_DAMPENING_OFF)
            async with aiofiles.open(filename) as file:
                content = await file.read()
                try:
                    response_json = json.loads(content)
                except json.decoder.JSONDecodeError:
                    _LOGGER.error("JSONDecodeError, dampening ignored: %s", filename)
                    error = True
                    return option(GRANULAR_DAMPENING_OFF, SET_ALLOW_RESET)
                self.granular_dampening = cast(dict[str, Any], response_json)
                if (
                    content.replace("\n", "").replace("\r", "").strip() != ""
                    and isinstance(response_json, dict)
                    and self.granular_dampening
                ):
                    first_site_len = 0
                    for site, damp_list in self.granular_dampening.items():
                        if first_site_len == 0:
                            first_site_len = len(damp_list)
                        elif len(damp_list) != first_site_len:
                            _LOGGER.error(
                                "Number of dampening factors for all sites must be the same in %s, dampening ignored",
                                filename,
                            )
                            self.granular_dampening = {}
                            error = True
                        if len(damp_list) not in (24, 48):
                            _LOGGER.error(
                                "Number of dampening factors for site %s must be 24 or 48 in %s, dampening ignored",
                                site,
                                filename,
                            )
                            self.granular_dampening = {}
                            error = True
                    if error:
                        return_value = option(GRANULAR_DAMPENING_OFF, SET_ALLOW_RESET)
                    else:
                        _LOGGER.debug("Granular dampening %s", str(self.granular_dampening))
                        return_value = option(GRANULAR_DAMPENING_ON, SET_ALLOW_RESET)
            return return_value
        finally:
            if mtime:
                self.granular_dampening_mtime = Path(filename).stat().st_mtime if Path(filename).exists() else 0
            if error:
                self.granular_dampening = {}

    async def refresh_granular_dampening_data(self) -> None:
        """Load granular dampening data if the file has changed."""
        if Path(self.get_filename_dampening()).is_file():
            mtime = Path(self.get_filename_dampening()).stat().st_mtime
            if mtime != self.granular_dampening_mtime:
                await self.granular_dampening_data()
                _LOGGER.info("Granular dampening loaded")
                _LOGGER.debug(
                    "Granular dampening file mtime %s",
                    dt.fromtimestamp(mtime, self._tz).strftime(DT_DATE_FORMAT),
                )

    def allow_granular_dampening_reset(self) -> bool:
        """Allow options change to reset the granular dampening file to an empty dictionary."""
        return self._granular_allow_reset

    def set_allow_granular_dampening_reset(self, enable: bool) -> None:
        """Set/clear allow reset granular dampening file to an empty dictionary by options change."""
        self._granular_allow_reset = enable

    async def get_dampening(self, site: str | None, site_underscores: bool) -> list[dict[str, Any]]:
        """Retrieve the currently set dampening factors.

        Arguments:
            site (str): An optional site.
            site_underscores (bool): Whether to replace dashes with underscores in returned site names.

        Returns:
            (list[dict[str, Any]]): The action response for the presently set dampening factors.
        """
        if self.entry_options.get(SITE_DAMP):
            if not site:
                sites = [_site[RESOURCE_ID] for _site in self.sites]
            else:
                sites = [site]
            all_set = self.granular_dampening.get(ALL) is not None
            if site:
                if not all_set:
                    if site in self.granular_dampening:
                        return [
                            {
                                SITE: _site if not site_underscores else _site.replace("-", "_"),
                                "damp_factor": ",".join(str(factor) for factor in self.granular_dampening[_site]),
                            }
                            for _site in sites
                            if self.granular_dampening.get(_site)
                        ]
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key="damp_not_for_site",
                        translation_placeholders={SITE: site},
                    )
                if site != ALL:
                    if site in self.granular_dampening:
                        _LOGGER.warning(
                            "There is dampening for site %s, but it is being overridden by an all sites entry, returning the 'all' entries instead",
                            site,
                        )
                    else:
                        _LOGGER.warning(
                            "There is no dampening set for site %s, but it is being overridden by an all sites entry, returning the 'all' entries instead",
                            site,
                        )
                return [
                    {
                        SITE: ALL,
                        "damp_factor": ",".join(str(factor) for factor in self.granular_dampening[ALL]),
                    }
                ]
            if all_set:
                return [
                    {
                        SITE: ALL,
                        "damp_factor": ",".join(str(factor) for factor in self.granular_dampening[ALL]),
                    }
                ]
            return [
                {
                    SITE: _site if not site_underscores else _site.replace("-", "_"),
                    "damp_factor": ",".join(str(factor) for factor in self.granular_dampening[_site]),
                }
                for _site in sites
                if self.granular_dampening.get(_site)
            ]
        if not site or site == ALL:
            return [
                {
                    SITE: ALL,
                    "damp_factor": ",".join(str(factor) for _, factor in self.damp.items()),
                }
            ]
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="damp_use_all",
            translation_placeholders={SITE: site},
        )

    async def load_saved_data(self) -> bool:  # noqa: C901
        """Load the saved solcast.json data.

        This also checks for new API keys and site removal.

        Returns:
            bool: True if data was loaded successfully, False otherwise.
        """

        file = ""
        try:
            if len(self.sites) > 0:

                async def load_data(filename: str, set_loaded: bool = True) -> dict[str, Any] | None:
                    nonlocal file

                    if Path(filename).is_file():
                        file = filename
                        async with aiofiles.open(filename) as data_file:
                            json_data: dict[str, Any] = json.loads(await data_file.read(), cls=JSONDecoder)
                            if not isinstance(json_data, dict):
                                _LOGGER.error("The %s cache appears corrupt", filename)
                                raise_and_record(self.hass, ConfigEntryNotReady, EXCEPTION_INIT_CORRUPT, {"file": file})
                            json_version = json_data.get(VERSION, 1)
                            _LOGGER.debug(
                                "Data cache %s exists, file type is %s",
                                filename,
                                type(json_data),
                            )
                            data = json_data
                            if set_loaded:
                                self._loaded_data = True
                            log_file = {
                                self._filename: "Dampened",
                                self._filename_undampened: "Undampened",
                                self._filename_actuals: "Estimated actual",
                                self._filename_actuals_dampened: "Dampened estimated actual",
                            }
                            _LOGGER.debug("%s data loaded", log_file.get(filename, "Unknown"))
                            if json_version != JSON_VERSION:
                                _LOGGER.info(
                                    "Upgrading %s cache version from v%d to v%d",
                                    filename.lower(),
                                    json_version,
                                    JSON_VERSION,
                                )
                                # If the file structure must change then upgrade it
                                current_version = json_version

                                # Test for incompatible data
                                if data.get(SITE_INFO) is None and data.get(FORECASTS) is None:
                                    # Need one or the other to be able to upgrade.
                                    self.status = SolcastApiStatus.DATA_INCOMPATIBLE
                                if data.get(SITE_INFO) is not None:
                                    if not isinstance(data.get(SITE_INFO, {}).get(self.sites[0][RESOURCE_ID], {}).get(FORECASTS), list):
                                        self.status = SolcastApiStatus.DATA_INCOMPATIBLE
                                if data.get(FORECASTS) is not None:
                                    if not isinstance(data.get(FORECASTS), list):
                                        self.status = SolcastApiStatus.DATA_INCOMPATIBLE
                                if self.status == SolcastApiStatus.DATA_INCOMPATIBLE:
                                    _LOGGER.critical("The %s appears incompatible, so cannot upgrade it", filename)
                                    raise_and_record(self.hass, ConfigEntryError, EXCEPTION_INIT_INCOMPATIBLE, {"file": file})

                                # What happened before v4 stays before v4. BJReplay has no visibility of ancient.
                                # V3 and prior versions of the solcast.json file did not have a version key.
                                if json_version < 4:
                                    data[VERSION] = 4
                                    json_version = 4
                                # Add LAST_ATTEMPT and AUTO_UPDATED to cache structure as of v5, introduced v4.2.5.
                                # Ancient v3 versions of this code did not have the SITE_INFO key to contain forecasts, so fix that.
                                if json_version < 5:
                                    _LOGGER.debug("Upgrading to v5 cache structure")
                                    data[VERSION] = 5
                                    data[LAST_ATTEMPT] = data[LAST_UPDATED]
                                    data[AUTO_UPDATED] = self.options.auto_update != AutoUpdate.NONE
                                    if data.get(SITE_INFO) is None:
                                        if (
                                            data.get(FORECASTS) is not None
                                            and len(self.sites) > 0
                                            and self.sites[0].get(RESOURCE_ID) is not None
                                        ):
                                            data[SITE_INFO] = {self.sites[0][RESOURCE_ID]: {FORECASTS: data.get(FORECASTS)}}
                                            data.pop(FORECASTS, None)
                                            data.pop("energy", None)
                                    json_version = 5
                                # Alter AUTO_UPDATED boolean flag to be the integer number of auto-update divisions, introduced v4.3.0.
                                if json_version < 6:
                                    _LOGGER.debug("Upgrading to v6 cache structure")
                                    data[VERSION] = 6
                                    data[AUTO_UPDATED] = 99999 if self.options.auto_update != AutoUpdate.NONE else 0
                                    json_version = 6
                                # Add failure statistics to cache structure, introduced v4.3.5.
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

                                if json_version > current_version:
                                    await self.serialise_data(data, filename)
                        if self.status == SolcastApiStatus.UNKNOWN:
                            self.status = SolcastApiStatus.OK
                        return data
                    return None

                async def load_generation_data() -> dict[str, Any] | None:
                    nonlocal file

                    data = None
                    if Path(self._filename_generation).is_file():
                        file = self._filename_generation
                        async with aiofiles.open(self._filename_generation) as data_file:
                            json_data: dict[str, Any] = json.loads(await data_file.read(), cls=JSONDecoder)
                            # Note that the generation data cache does not have a version number
                            # Future changes to the structure, if any, will need to be handled here by checking current version by allowing for None
                            _LOGGER.debug(
                                "Data cache %s exists, file type is %s",
                                self._filename_generation,
                                type(json_data),
                            )
                            if isinstance(json_data, dict):
                                data = json_data
                                _LOGGER.debug("Generation data loaded")
                    return data

                async def adds_moves_changes():
                    # Check for any new API keys so no sites data yet for those, and also for API key change.
                    serialise = False
                    reset_usage = False
                    new_sites: dict[str, str] = {}
                    cache_sites = list(self._data[SITE_INFO].keys())
                    old_api_keys = (
                        self.hass.data[DOMAIN].get(OLD_API_KEY, self.hass.data[DOMAIN][ENTRY_OPTIONS].get(CONF_API_KEY, "")).split(",")
                    )
                    for site in self.sites:
                        api_key = site[API_KEY]
                        site = site[RESOURCE_ID]
                        if site not in cache_sites or len(self._data[SITE_INFO][site].get(FORECASTS, [])) == 0:
                            new_sites[site] = api_key
                            if (
                                api_key not in old_api_keys
                            ):  # If a new site is seen in conjunction with an API key change then reset the usage.
                                reset_usage = True
                    with contextlib.suppress(Exception):
                        del self.hass.data[DOMAIN][OLD_API_KEY]

                    if reset_usage:
                        _LOGGER.info("An API key has changed with a new site added, resetting usage")
                        await self.reset_api_usage(force=True)

                    if len(new_sites.keys()) > 0:
                        # Some site data does not exist yet so get it.
                        # Do not alter self._data[LAST_ATTEMPT], as this is not a scheduled thing
                        _LOGGER.info("New site(s) have been added, so getting forecast data for them")
                        for site, api_key in new_sites.items():
                            await self.__http_data_call(site=site, api_key=api_key, do_past_hours=168)

                        _now = dt.now(datetime.UTC).replace(microsecond=0)
                        update: dict[str, Any] = {LAST_UPDATED: _now, LAST_ATTEMPT: _now, VERSION: JSON_VERSION}
                        self._data |= update
                        self._data_undampened |= update
                        self._data_actuals |= update
                        serialise = True

                        self._loaded_data = True

                    # Check for sites that need to be removed.
                    remove_sites: list[str] = []
                    configured_sites = [site[RESOURCE_ID] for site in self.sites]
                    for site in cache_sites:
                        if site not in configured_sites:
                            _LOGGER.warning(
                                "Site resource id %s is no longer configured, will remove saved data from %s, %s, %s, %s",
                                site,
                                self._filename,
                                self._filename_undampened,
                                self._filename_actuals,
                                self._filename_actuals_dampened,
                            )
                            remove_sites.append(site)

                    for site in remove_sites:
                        for data in [self._data, self._data_undampened, self._data_actuals]:
                            with contextlib.suppress(Exception):
                                del data[SITE_INFO][site]
                    if len(remove_sites) > 0:
                        serialise = True

                    if serialise:
                        await self.apply_forward_dampening()
                        for filename, data in {
                            self._filename: self._data,
                            self._filename_undampened: self._data_undampened,
                            self._filename_actuals: self._data_actuals,
                            self._filename_actuals_dampened: self._data_actuals,
                        }.items():
                            await self.serialise_data(data, filename)

                dampened_data = await load_data(self._filename)
                if dampened_data is not None:
                    self._data = dampened_data
                    # Load the un-dampened history
                    undampened_data = await load_data(self._filename_undampened, set_loaded=False)
                    if undampened_data is not None and self.status == SolcastApiStatus.OK:
                        self._data_undampened = undampened_data
                    # Load the estimated actuals history
                    actuals_data = await load_data(self._filename_actuals, set_loaded=False)
                    if actuals_data is not None and self.status == SolcastApiStatus.OK:
                        self._data_actuals = actuals_data
                    # Load the dampened estimated actuals history
                    actuals_dampened_data = await load_data(self._filename_actuals_dampened, set_loaded=False)
                    if actuals_dampened_data is not None and self.status == SolcastApiStatus.OK:
                        self._data_actuals_dampened = actuals_dampened_data
                    elif actuals_data:
                        self._data_actuals_dampened = actuals_data
                    # Load the generation history
                    generation_data = await load_generation_data()
                    if generation_data:
                        self._data_generation = generation_data
                    # If configured to get generation but there is no cached data, then get it.
                    if self.options.auto_dampen and self.options.generation_entities and len(self._data_generation[GENERATION]) == 0:
                        await self.get_pv_generation()
                    # Check for sites changes.
                    await adds_moves_changes()
                    # Migrate un-dampened history data to the un-dampened cache if needed.
                    await self.__migrate_undampened_history()
                else:
                    # There is no cached data, so start fresh.
                    self._data = copy.deepcopy(FRESH_DATA)
                    self._data_undampened = copy.deepcopy(FRESH_DATA)
                    self._data_actuals = copy.deepcopy(FRESH_DATA)
                    self._data_actuals_dampened = copy.deepcopy(FRESH_DATA)
                    self._loaded_data = False

                if not self._loaded_data:
                    # No file to load.
                    _LOGGER.warning("There is no solcast.json to load, so fetching solar forecast, including past forecasts")
                    # Could be a brand new install of the integration, or the file has been removed. Get the forecast and past actuals.
                    self.status_message = await self.get_forecast_update(do_past_hours=168)
                    if self.status_message != "":
                        return False
                    self._loaded_data = True
                    for filename, data in {
                        self._filename: self._data,
                        self._filename_undampened: self._data_undampened,
                        self._filename_actuals: self._data_actuals,
                        self._filename_actuals_dampened: self._data_actuals_dampened,
                    }.items():
                        await self.serialise_data(data, filename)
        except json.decoder.JSONDecodeError:
            _LOGGER.error("The cached data in %s is corrupt in load_saved_data()", file)
            self.status = SolcastApiStatus.DATA_CORRUPT
            raise_and_record(self.hass, ConfigEntryNotReady, EXCEPTION_INIT_CORRUPT, {"file": file})
        return True

    async def build_forecast_and_actuals(self, raise_exc=False) -> bool:
        """Build the forecast and estimated actual data.

        Arguments:
            raise_exc (bool): Whether to raise exceptions on failure. Only set when the integration is starting up.

        Returns:
            bool: True if both forecast and actual data built successfully, False otherwise.
        """

        success = True
        if self._loaded_data:
            # Create an up-to-date forecast.
            if self.status == SolcastApiStatus.OK and not await self.build_forecast_data():
                self.status = SolcastApiStatus.BUILD_FAILED_FORECASTS
                success = False
                _LOGGER.error("Failed to build forecast data")
                if raise_exc:
                    raise_and_record(self.hass, ConfigEntryNotReady, EXCEPTION_BUILD_FAILED_FORECASTS)
            if self.status == SolcastApiStatus.OK and self.options.get_actuals and not await self.build_actual_data():
                self.status = SolcastApiStatus.BUILD_FAILED_ACTUALS
                success = False
                _LOGGER.error("Failed to build estimated actuals data")
                if raise_exc:
                    raise_and_record(self.hass, ConfigEntryNotReady, EXCEPTION_BUILD_FAILED_ACTUALS)
        return success

    async def reset_failure_stats(self) -> None:
        """Reset the failure statistics."""

        _LOGGER.debug("Resetting failure statistics")
        self._data[FAILURE][LAST_24H] = 0
        self._data[FAILURE][LAST_7D] = [0, *self._data[FAILURE][LAST_7D][:-1]]
        self._data[FAILURE][LAST_14D] = [0, *self._data[FAILURE][LAST_14D][:-1]]
        await self.serialise_data(self._data, self._filename)

    def get_last_attempt(self) -> dt:
        """Get the date/time of last attempted forecast update.

        Returns:
            dt: The date/time of last attempt.
        """
        return self._data[LAST_ATTEMPT].replace(microsecond=0)

    def get_estimated_actuals_updated_today(self) -> bool:
        """Check if estimated actuals were updated today.

        Returns:
            bool: True if updated today, False otherwise.
        """
        return self._data_actuals[LAST_UPDATED].astimezone(self._tz).date() == dt.now(self._tz).date()

    def get_failures_last_24h(self) -> int:
        """Get the number of failures in the last 24 hours.

        Returns:
            int: The number of failures in the last 24 hours.
        """
        return self._data[FAILURE][LAST_24H]

    def get_failures_last_7d(self) -> int:
        """Get the number of failures in the last 7 days.

        Returns:
            list[int]: The number of failures in the last 7 days.
        """
        return sum(self._data[FAILURE][LAST_7D])

    def get_failures_last_14d(self) -> int:
        """Get the number of failures in the last 14 days.

        Returns:
            list[int]: The number of failures in the last 14 days.
        """
        return sum(self._data[FAILURE][LAST_14D])

    async def delete_solcast_file(self, *args: tuple[Any]) -> None:
        """Delete the solcast json files.

        Note: This will immediately trigger a forecast get with estimated actual history, so this
        is an integration reset.

        Arguments:
            args (tuple): Not used.
        """
        _LOGGER.debug("Action to delete old solcast json files")
        for filename in [self._filename, self._filename_undampened, self._filename_actuals, self._filename_actuals_dampened]:
            if Path(filename).is_file():
                Path(filename).unlink()
            else:
                _LOGGER.warning("There is no %s to delete", filename.split("/")[-1])
        self._loaded_data = False
        await self.load_saved_data()

    async def get_forecast_list(self, *args: Any) -> tuple[dict[str, Any], ...]:
        """Get forecasts.

        Arguments:
            args (tuple): [0] (dt) = from timestamp, [1] (dt) = to timestamp, [2] = site, [3] (bool) = dampened or un-dampened.

        Returns:
            tuple(dict[str, Any], ...): Forecasts representing the range specified.
        """

        if args[2] == ALL:
            data_forecasts = self._data_forecasts if not args[3] else self._data_forecasts_undampened
        else:
            data_forecasts = self._site_data_forecasts[args[2]] if not args[3] else self._site_data_forecasts_undampened[args[2]]
        start_index, end_index = self.__get_list_slice(data_forecasts, args[0], args[1], search_past=True)
        if start_index == 0 and end_index == 0:
            # Range could not be found
            raise ValueError(
                f"Range is invalid {args[0]} to {args[1]}, earliest forecast is {data_forecasts[0][PERIOD_START]}, latest forecast is {data_forecasts[-1][PERIOD_START]}"
            )
        forecast_slice = data_forecasts[start_index:end_index]

        return tuple({**data, PERIOD_START: data[PERIOD_START].astimezone(self._tz)} for data in forecast_slice)

    async def get_estimate_list(self, *args: Any) -> tuple[dict[str, Any], ...]:
        """Get estimated actuals.

        Arguments:
            args (tuple): [0] (dt) = from timestamp, [1] (dt) = to timestamp, [2] (bool) = dampened or un-dampened (default undampened).

        Returns:
            tuple(dict[str, Any], ...): Estimated actuals representing the range specified.
        """

        data = self._data_estimated_actuals if args[2] else self._data_estimated_actuals_dampened
        start_index, end_index = self.__get_list_slice(data, args[0], args[1], search_past=True)
        if start_index == 0 and end_index == 0:
            # Range could not be found
            raise ValueError("Range is invalid")
        estimate_slice = data[start_index:end_index]

        return tuple({**data, PERIOD_START: data[PERIOD_START].astimezone(self._tz)} for data in estimate_slice)

    def get_earliest_estimate_after(self, data: list[dict[str, Any]], after: dt, dampened: bool = False) -> dt | None:
        """Get the earliest estimated actual datetime after a specified datetime."""
        earliest = None
        if len(data) > 0:
            # Find all actuals with period_start >= after, then get the earliest one
            in_scope_actuals = [actual[PERIOD_START] for actual in data if actual[PERIOD_START] >= after]
            earliest = min(in_scope_actuals) if in_scope_actuals else None
            _LOGGER.debug(
                "Earliest applicable %s estimated actual datetime is %s",
                "dampened" if dampened else "undampened",
                earliest,
            )
        return earliest

    def get_earliest_estimate_after_undampened(self, after: dt) -> dt | None:
        """Get the earliest contiguous undampened estimated actual datetime.

        Returns:
            dt | None: The earliest undampened estimated actual datetime, or None if no data.
        """
        return self.get_earliest_estimate_after(self._data_estimated_actuals, after=after)

    def get_earliest_estimate_after_dampened(self, after: dt) -> dt | None:
        """Get the earliest contiguous dampened estimated actual datetime.

        Returns:
            dt | None: The earliest dampened estimated actual datetime, or None if no data.
        """
        return self.get_earliest_estimate_after(self._data_estimated_actuals_dampened, after=after, dampened=True)

    def get_api_used_count(self) -> int:
        """Return API polling count for this UTC 24hr period (minimum of all API keys).

        A maximum is used because forecasts are polled at the same time for each configured API key. Should
        one API key fail but the other succeed then usage will be misaligned, so the highest usage of all
        API keys will apply.

        Returns:
            int: The tracked API usage count.
        """
        return max(list(self._api_used.values()))

    def get_api_limit(self) -> int:
        """Return API polling limit for this UTC 24hr period (minimum of all API keys).

        A minimum is used because forecasts are polled at the same time, so even if one API key has a
        higher limit that limit will never be reached.

        Returns:
            int: The lowest API limit of all configured API keys.
        """
        return min(list(self._api_limit.values()))

    def get_last_updated(self) -> dt | None:
        """Return when the data was last updated.

        Returns:
            dt | None: The last successful forecast fetch.
        """
        return self._data[LAST_UPDATED].astimezone(self._tz) if self._data.get(LAST_UPDATED) is not None else None

    def get_dampen(self) -> bool:
        """Return whether dampening is enabled.

        Returns:
            bool: Whether dampening is enabled.
        """
        return (
            self.options.auto_dampen
            or self.granular_dampening != {}
            or (not self.options.auto_dampen and self.granular_dampening == {} and sum(self.options.dampening.values()) != 24)
        )

    def get_rooftop_site_total_today(self, site: str) -> float | None:
        """Return total kW for today for a site.

        Arguments:
            site (str): A Solcast site ID.

        Returns:
            float | None: Total site kW forecast today.
        """
        if self._tally.get(site) is None:
            _LOGGER.warning("Site total kW forecast today is currently unavailable for %s", site)
        return self._tally.get(site)

    def get_rooftop_site_extra_data(self, site: str = "") -> dict[str, Any]:
        """Return information about a site.

        Arguments:
            site (str): An optional Solcast site ID.

        Returns:
            dict: Site attributes that have been configured at solcast.com.
        """
        target_site = tuple(_site for _site in self.sites if _site[RESOURCE_ID] == site)
        _site: dict[str, Any] = target_site[0]
        result = {
            NAME: _site.get(NAME),
            RESOURCE_ID: _site.get(RESOURCE_ID),
            SITE_ATTRIBUTE_CAPACITY: _site.get(SITE_ATTRIBUTE_CAPACITY),
            SITE_ATTRIBUTE_CAPACITY_DC: _site.get(SITE_ATTRIBUTE_CAPACITY_DC),
            SITE_ATTRIBUTE_LONGITUDE: _site.get(SITE_ATTRIBUTE_LONGITUDE),
            SITE_ATTRIBUTE_LATITUDE: _site.get(SITE_ATTRIBUTE_LATITUDE),
            SITE_ATTRIBUTE_AZIMUTH: _site.get(SITE_ATTRIBUTE_AZIMUTH),
            SITE_ATTRIBUTE_TILT: _site.get(SITE_ATTRIBUTE_TILT),
            SITE_ATTRIBUTE_INSTALL_DATE: _site.get(SITE_ATTRIBUTE_INSTALL_DATE),
            SITE_ATTRIBUTE_LOSS_FACTOR: _site.get(SITE_ATTRIBUTE_LOSS_FACTOR),
            SITE_ATTRIBUTE_TAGS: _site.get(SITE_ATTRIBUTE_TAGS),
        }
        return {k: v for k, v in result.items() if v is not None}

    def dst(self, dt_obj: dt | None = None) -> bool:
        """Return whether a given date is daylight savings time, or for zones using Winter time whether standard time."""
        result = False
        if dt_obj is not None:
            delta = timedelta(hours=1) if str(self._tz) not in WINTER_TIME else timedelta(hours=0)
            result = dt_obj.astimezone(self._tz).dst() == delta
        return result

    def is_interval_dst(self, interval: dict[str, Any]) -> bool:
        """Return whether an interval is daylight savings time, or for zones using Winter time whether standard time."""
        return self.dst(interval[PERIOD_START].astimezone(self._tz))

    def get_day_start_utc(self, future: int = 0) -> dt:
        """Datetime helper.

        Arguments:
            future(int): An optional number of days into the future (or negative number for into the past)

        Returns:
            datetime: The UTC date and time representing midnight local time.
        """
        for_when = (dt.now(self._tz) + timedelta(days=future)).astimezone(self._tz)
        return for_when.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(datetime.UTC)

    def __get_utc_previous_midnight(self) -> dt:
        """Datetime helper.

        Returns:
            datetime: The UTC date and time representing midnight UTC of the current day.
        """
        return dt.now().astimezone(datetime.UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    def get_now_utc(self) -> dt:
        """Datetime helper.

        Returns:
            datetime: The UTC date and time representing now as at the previous minute boundary.
        """
        return dt.now(self._tz).replace(second=0, microsecond=0).astimezone(datetime.UTC)

    def get_real_now_utc(self) -> dt:
        """Datetime helper.

        Returns:
            datetime: The UTC date and time representing now including seconds/microseconds.
        """
        return dt.now(self._tz).astimezone(datetime.UTC)

    def get_hour_start_utc(self) -> dt:
        """Datetime helper.

        Returns:
            datetime: The UTC date and time representing the start of the current hour.
        """
        return dt.now(self._tz).replace(minute=0, second=0, microsecond=0).astimezone(datetime.UTC)

    def get_forecast_day(self, future_day: int) -> dict[str, Any] | None:
        """Return forecast data for the Nth day ahead.

        Arguments:
            future_day (int): A day (0 = today, 1 = tomorrow, etc., with a maximum of day FORECAST_DAYS - 1).

        Returns:
            dict: Includes the day name, whether there are issues with the data in terms of completeness,
            and detailed half-hourly forecast (and site breakdown if that option is configured), and a
            detailed hourly forecast (and site breakdown if that option is configured).
        """
        no_data_error = True

        def build_hourly(forecast: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [
                {
                    PERIOD_START: forecast[index][PERIOD_START],
                    ESTIMATE: round(
                        (forecast[index][ESTIMATE] + forecast[index + 1][ESTIMATE]) / 2,
                        4,
                    ),
                    ESTIMATE10: round(
                        (forecast[index][ESTIMATE10] + forecast[index + 1][ESTIMATE10]) / 2,
                        4,
                    ),
                    ESTIMATE90: round(
                        (forecast[index][ESTIMATE90] + forecast[index + 1][ESTIMATE90]) / 2,
                        4,
                    ),
                }
                for index in range(1 if len(forecast) % 2 == 1 else 0, len(forecast), 2)
                if len(forecast) > 0
            ]

        def get_start_and_end(forecasts: list[dict[str, Any]]) -> tuple[int, int, dt, dt]:
            start_utc = self.get_day_start_utc(future=future_day)
            start, _ = self.__get_list_slice(forecasts, start_utc)
            end_utc = min(self.get_day_start_utc(future=future_day + 1), forecasts[-1][PERIOD_START])  # Don't go past the last forecast.
            end, _ = self.__get_list_slice(forecasts, end_utc)
            if not start:
                # Data is missing, so adjust the start time to the first available forecast.
                start, _ = self.__get_list_slice(forecasts, forecasts[0][PERIOD_START])
                start_utc = forecasts[0][PERIOD_START]
            return start, end, start_utc, end_utc

        start_index, end_index, start_utc, _ = get_start_and_end(self._data_forecasts)

        site_data_forecast: dict[str, list[dict[str, Any]]] = {}
        forecast_slice = self._data_forecasts[start_index:end_index]
        if self.options.attr_brk_site_detailed:
            for site in self.sites:
                site_start_index, site_end_index, _, _ = get_start_and_end(self._site_data_forecasts[site[RESOURCE_ID]])
                site_data_forecast[site[RESOURCE_ID]] = self._site_data_forecasts[site[RESOURCE_ID]][site_start_index:site_end_index]

        _tuple = [{**forecast, PERIOD_START: forecast[PERIOD_START].astimezone(self._tz)} for forecast in forecast_slice]
        tuples: dict[str, list[dict[str, Any]]] = {}
        if self.options.attr_brk_site_detailed:
            for site in self.sites:
                tuples[site[RESOURCE_ID]] = [
                    {
                        **forecast,
                        PERIOD_START: forecast[PERIOD_START].astimezone(self._tz),
                    }
                    for forecast in site_data_forecast[site[RESOURCE_ID]]
                ]

        if len(_tuple) < 48:
            no_data_error = False

        hourly_tuple: list[dict[str, Any]] = []
        hourly_tuples: dict[str, list[dict[str, Any]]] = {}
        if self.options.attr_brk_hourly:
            hourly_tuple = build_hourly(_tuple)
            if self.options.attr_brk_site_detailed:
                hourly_tuples = {}
                for site in self.sites:
                    hourly_tuples[site[RESOURCE_ID]] = build_hourly(tuples[site[RESOURCE_ID]])

        result: dict[str, Any] = {
            DAY_NAME: start_utc.astimezone(self._tz).strftime("%A"),
            DATA_CORRECT: no_data_error,
        }
        if self.options.attr_brk_halfhourly:
            result[DETAILED_FORECAST] = _tuple
            if self.options.attr_brk_site_detailed:
                for site in self.sites:
                    result[f"{DETAILED_FORECAST}_{site[RESOURCE_ID].replace('-', '_')}"] = tuples[site[RESOURCE_ID]]
        if self.options.attr_brk_hourly:
            result[DETAILED_HOURLY] = hourly_tuple
            if self.options.attr_brk_site_detailed:
                for site in self.sites:
                    result[f"{DETAILED_HOURLY}_{site[RESOURCE_ID].replace('-', '_')}"] = hourly_tuples[site[RESOURCE_ID]]
        return result

    def get_forecast_n_hour(
        self,
        n_hour: int,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> int | None:
        """Return forecast for the Nth hour.

        Arguments:
            n_hour (int): An hour into the future, or the current hour (0 = current and 1 = next hour are used).
            site (str): An optional Solcast site ID, used to build site breakdown attributes.
            forecast_confidence (str): An optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            int | None - A forecast for an hour period as Wh (either used for a sensor or its attributes).
        """
        start_utc = self.get_hour_start_utc() + timedelta(hours=n_hour)
        end_utc = start_utc + timedelta(hours=1)
        estimate = self.__get_forecast_pv_estimates(start_utc, end_utc, site=site, forecast_confidence=forecast_confidence)
        return round(500 * estimate) if estimate is not None else None

    def get_forecast_custom_hours(
        self,
        n_hours: int,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> int | None:
        """Return forecast for the next N hours.

        Arguments:
            n_hours (int): A number of hours into the future.
            site (str): An optional Solcast site ID, used to build site breakdown attributes.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            int | None - A forecast for a multiple hour period as Wh (either used for a sensor or its attributes).
        """
        start_utc = self.get_now_utc()
        end_utc = start_utc + timedelta(hours=n_hours)
        remaining = self.__get_forecast_pv_remaining(
            start_utc,
            end_utc=end_utc,
            site=site,
            forecast_confidence=forecast_confidence,
        )
        return round(1000 * remaining) if remaining is not None else None

    def get_power_n_minutes(
        self,
        n_mins: int,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> int | None:
        """Return expected power generation in the next N minutes.

        Arguments:
            n_mins (int): A number of minutes into the future.
            site (str): An optional Solcast site ID, used to build site breakdown attributes.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            int | None: A power forecast in N minutes as W (either used for a sensor or its attributes).
        """
        time_utc = self.get_now_utc() + timedelta(minutes=n_mins)
        forecast = self.__get_forecast_pv_moment(time_utc, site=site, forecast_confidence=forecast_confidence)
        return round(1000 * forecast) if forecast is not None else None

    def get_peak_power_day(
        self,
        n_day: int,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> int | None:
        """Return maximum forecast Watts for N days ahead.

        Arguments:
            n_day (int): A number representing a day (0 = today, 1 = tomorrow, etc., with a maximum of day FORECAST_DAYS - 1).
            site (str): An optional Solcast site ID, used to build site breakdown attributes.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            int | None: An expected peak generation for a given day as Watts.
        """
        forecast_confidence = self._use_forecast_confidence if forecast_confidence is None else forecast_confidence
        start_utc = self.get_day_start_utc(future=n_day)
        end_utc = self.get_day_start_utc(future=n_day + 1)
        result = self.__get_max_forecast_pv_estimate(start_utc, end_utc, site=site, forecast_confidence=forecast_confidence)
        return int(round(1000 * result[forecast_confidence])) if result is not None else None

    def get_peak_time_day(
        self,
        n_day: int,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> dt | None:
        """Return hour of max generation for site N days ahead.

        Arguments:
            n_day (int): A number representing a day (0 = today, 1 = tomorrow, etc., with a maximum of day FORECAST_DAYS - 1).
            site (str): An optional Solcast site ID, used to build site breakdown attributes.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            dt | None: The date and time of expected peak generation for a given day.
        """
        start_utc = self.get_day_start_utc(future=n_day)
        end_utc = self.get_day_start_utc(future=n_day + 1)
        result = self.__get_max_forecast_pv_estimate(start_utc, end_utc, site=site, forecast_confidence=forecast_confidence)
        return result[PERIOD_START].astimezone(self._tz) if result is not None else None

    def get_forecast_remaining_today(self, n: int = 0, site: str | None = None, forecast_confidence: str | None = None) -> float | None:
        """Return remaining forecasted production for today.

        Arguments:
            n (int): Not used.
            site (str): An optional Solcast site ID, used to build site breakdown attributes.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            float | None: The expected remaining solar generation for the current day as kWh.
        """
        start_utc = self.get_now_utc()
        end_utc = self.get_day_start_utc(future=1)
        remaining = self.__get_forecast_pv_remaining(
            start_utc,
            end_utc=end_utc,
            site=site,
            forecast_confidence=forecast_confidence,
        )
        return round(remaining, 4) if remaining is not None else None

    def get_total_energy_forecast_day(
        self,
        n_day: int,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> float | None:
        """Return forecast production total for N days ahead.

        Arguments:
            n_day (int): A day (0 = today, 1 = tomorrow, etc., with a maximum of day FORECAST_DAYS - 1).
            site (str): An optional Solcast site ID, used to build site breakdown attributes.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            float | None: The forecast total solar generation for a given day as kWh.
        """
        start_utc = self.get_day_start_utc(future=n_day)
        end_utc = self.get_day_start_utc(future=n_day + 1)
        estimate = self.__get_forecast_pv_estimates(start_utc, end_utc, site=site, forecast_confidence=forecast_confidence)
        return round(0.5 * estimate, 4) if estimate is not None else None

    def get_forecast_attributes(self, get_forecast_value: Any, n: int = 0) -> dict[str, Any]:
        """Return forecast attributes for the 'n' forecast value for all sites and individual sites.

        Arguments:
            get_forecast_value (function): A function to get the forecast value.
            n (int): A minute, hour or day into the future.

        Returns:
            dict: Sensor attributes for the period, depending on the configured options.
        """
        result: dict[str, Any] = {}
        if self.options.attr_brk_site:
            for site in self.sites:
                result[site[RESOURCE_ID].replace("-", "_")] = get_forecast_value(n, site=site[RESOURCE_ID])
                for forecast_confidence in self.estimate_set:
                    result[forecast_confidence.replace("pv_", "") + "_" + site[RESOURCE_ID].replace("-", "_")] = get_forecast_value(
                        n,
                        site=site[RESOURCE_ID],
                        forecast_confidence=forecast_confidence,
                    )
        for forecast_confidence in self.estimate_set:
            result[forecast_confidence.replace("pv_", "")] = get_forecast_value(n, forecast_confidence=forecast_confidence)
        return result

    def __get_list_slice(
        self,
        data: list[dict[str, Any]],
        start_utc: dt,
        end_utc: dt | None = None,
        search_past: bool = False,
    ) -> tuple[int, int]:
        """Return forecast data list slice start and end indexes for interval.

        Arguments:
            data (list): The data to search, either actual or forecast total data or site breakdown data.
            start_utc (datetime): Start of time period requested in UTC.
            end_utc (datetime): Optional end of time period requested in UTC (if omitted, thirty minutes beyond start).
            search_past (bool): Optional flag to indicate that past periods should be searched.

        Returns:
            tuple(int, int): List index of start of period, list index of end of period.
        """
        if end_utc is None:
            end_utc = start_utc + timedelta(seconds=1800)
        start_index = -1
        end_index = len(data)
        for test_index in range(0 if search_past else self.__calc_forecast_start_index(data), end_index):
            forecast_period = data[test_index][PERIOD_START]
            # After the last segment.
            if end_utc <= forecast_period:
                end_index = test_index
                break
            # First segment.
            if start_utc < forecast_period + timedelta(seconds=1800) and start_index == -1:
                start_index = test_index
        # Never found.
        if start_index == -1:
            start_index = 0
            end_index = 0
        return start_index, end_index

    def __get_spline(
        self,
        spline: dict[str, list[float]],
        start: int,
        xx: list[int],
        data: list[dict[str, Any]],
        confidences: list[str],
        reducing: bool = False,
    ) -> None:
        """Build a forecast spline, momentary or day reducing.

        Arguments:
            spline (dict): The data structure to populate.
            start (int): The starting index of the data slice.
            xx (list): Seconds intervals of the day, one for each 5-minute interval (plus another hours worth).
            data (list): The data structure used to build the spline, either total data or site breakdown data.
            confidences (list): The forecast types to build, pv_estimate, pv_estimate10 or pv_estimate90.
            reducing (bool): A flag to indicate whether a momentary power spline should be built, or a reducing energy spline, default momentary.
        """
        for forecast_confidence in confidences:
            try:
                spline_period_length = len(xx) // 6
                y = [data[start + index][forecast_confidence] for index in range(spline_period_length)]
                if reducing:
                    # Build a decreasing set of forecasted values instead.
                    y = [0.5 * sum(y[index:]) for index in range(spline_period_length)]
                spline[forecast_confidence] = cubic_interp(xx, self._spline_period[-spline_period_length:], y)
                spline[forecast_confidence] = [0] * (len(self._spline_period) - len(xx)) + spline[forecast_confidence]
                self.__sanitise_spline(spline, forecast_confidence, xx, y, reducing=reducing)
                continue
            except IndexError:
                pass
            spline[forecast_confidence] = [0] * (len(self._spline_period) * 6)

    def __sanitise_spline(
        self,
        spline: dict[str, list[float]],
        forecast_confidence: str,
        xx: list[int],
        y: list[float],
        reducing: bool = False,
    ) -> None:
        """Ensure that no negative values are returned, and also shifts the spline to account for half-hour average input values.

        Arguments:
            spline (dict): The data structure to sanitise.
            forecast_confidence (str): The forecast type to sanitise, pv_estimate, pv_estimate10 or pv_estimate90.
            xx (list): Seconds intervals of the day, one for each 5-minute interval (plus another hours worth).
            y (list): The period momentary or reducing input data used for the spline calculation.
            reducing (bool): A flag to indicate whether the spline is momentary power, or reducing energy, default momentary.
        """
        offset = int(xx[0] / 300)  # To cater for less intervals than the spline period
        for interval in xx:
            spline_index = int(interval / 300) - offset  # Every five minutes
            # Suppress negative values.
            if math.copysign(1.0, spline[forecast_confidence][spline_index]) < 0:
                spline[forecast_confidence][spline_index] = 0.0
            # Suppress spline bounce.
            if reducing:
                if (
                    spline_index + 1 <= len(xx) - 1
                    and spline[forecast_confidence][spline_index + 1] > spline[forecast_confidence][spline_index]
                ):
                    spline[forecast_confidence][spline_index + 1] = spline[forecast_confidence][spline_index]
            else:
                y_index = int(math.floor(interval / 1800))  # Every half hour
                if y_index + 1 <= len(y) - 1 and y[y_index] == 0 and y[y_index + 1] == 0:
                    spline[forecast_confidence][spline_index] = 0.0
        # Shift right by fifteen minutes because 30-minute averages, padding as appropriate.
        if reducing:
            spline[forecast_confidence] = ([spline[forecast_confidence][0]] * 3) + spline[forecast_confidence]
        else:
            spline[forecast_confidence] = ([0] * 3) + spline[forecast_confidence]

    def __build_spline(self, variant: dict[str, dict[str, list[float]]], reducing: bool = False) -> None:
        """Build cubic splines for interpolated inter-interval momentary or reducing estimates.

        Arguments:
            variant (dict[str, list[float]): The variant variable to populate, _forecasts_moment or _forecasts_reducing.
            reducing (bool): A flag to indicate whether the spline is momentary power, or reducing energy, default momentary.
        """
        df = [self._use_forecast_confidence]
        for enabled, estimate in (
            (self.options.attr_brk_estimate, ESTIMATE),
            (self.options.attr_brk_estimate10, ESTIMATE10),
            (self.options.attr_brk_estimate90, ESTIMATE90),
        ):
            if enabled and estimate not in df:
                df.append(estimate)

        start: int = 0
        end: int = 0
        xx: list[int] = []

        def get_start_and_end(forecasts: list[dict[str, Any]]) -> tuple[int, int, list[int]]:
            try:
                start, end = self.__get_list_slice(forecasts, self.get_day_start_utc())  # Get start of day index.
                if start:
                    xx = list(range(0, 1800 * len(self._spline_period), 300))
                else:
                    # Data is missing at the start of the set, so adjust the start time to the first available forecast.
                    start, end = self.__get_list_slice(forecasts, forecasts[0][PERIOD_START], self.get_day_start_utc(future=1))
                    xx = list(range(1800 * (48 - (end - start)), 1800 * len(self._spline_period), 300))
            except IndexError:
                start = 0
                end = 0
                xx = []
            return start, end, xx

        variant[ALL] = {}
        start, end, xx = get_start_and_end(self._data_forecasts)
        if end:
            self.__get_spline(variant[ALL], start, xx, self._data_forecasts, df, reducing=reducing)
        if self.options.attr_brk_site:
            for site in self.sites:
                variant[site[RESOURCE_ID]] = {}
                if self._site_data_forecasts.get(site[RESOURCE_ID]):
                    start, end, xx = get_start_and_end(self._site_data_forecasts[site[RESOURCE_ID]])
                    if end:
                        self.__get_spline(
                            variant[site[RESOURCE_ID]],
                            start,
                            xx,
                            self._site_data_forecasts[site[RESOURCE_ID]],
                            df,
                            reducing=reducing,
                        )

    async def __spline_moments(self):
        """Build the moments splines."""
        self.__build_spline(self._forecasts_moment)

    async def __spline_remaining(self):
        """Build the descending splines."""
        self.__build_spline(self._forecasts_remaining, reducing=True)

    async def recalculate_splines(self):
        """Recalculate both the moment and remaining splines."""
        start_time = time.time()
        await self.__spline_moments()
        await self.__spline_remaining()
        _LOGGER.debug("Task recalculate_splines took %.3f seconds", time.time() - start_time)

    def __get_moment(self, site: str | None, forecast_confidence: str | None, n_min: float) -> float | None:
        """Get a time value from a moment spline.

        Arguments:
            site (str | None): A Solcast site ID.
            forecast_confidence (str): The forecast type, pv_estimate, pv_estimate10 or pv_estimate90.
            n_min (float): Minute of the day.

        Returns:
            float | None: A splined forecasted value as kW.
        """
        variant: list[float] | None = self._forecasts_moment[ALL if site is None else site].get(
            self._use_forecast_confidence if forecast_confidence is None else forecast_confidence
        )
        offset = (
            (len(self._spline_period) * 6 - len(variant)) + 3 if variant is not None else 0
        )  # To cater for less intervals than the spline period
        return variant[int(n_min / 300) - offset] if variant and len(variant) > 0 else None

    def __get_remaining(self, site: str | None, forecast_confidence: str | None, n_min: float) -> float | None:
        """Get a remaining value at a given five-minute point from a reducing spline.

        Arguments:
            site (str | None): A Solcast site ID.
            forecast_confidence (str): The forecast type, pv_estimate, pv_estimate10 or pv_estimate90.
            n_min (float): The minute of the day.

        Returns:
            float | None: A splined forecasted remaining value as kWh.
        """
        variant: list[float] | None = self._forecasts_remaining[ALL if site is None else site].get(
            self._use_forecast_confidence if forecast_confidence is None else forecast_confidence
        )
        offset = (
            (len(self._spline_period) * 6 - len(variant)) + 3 if variant is not None else 0
        )  # To cater for less intervals than the spline period
        return variant[int(n_min / 300) - offset] if variant and len(variant) > 0 else None

    def __get_forecast_pv_remaining(
        self,
        start_utc: dt,
        end_utc: dt | None = None,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> float | None:
        """Return estimate remaining for a period.

        The start_utc and end_utc will be adjusted to the most recent five-minute period start. Where
        end_utc is present the forecasted remaining energy between the two datetime values is calculated.

        Arguments:
            start_utc (datetime): Start of time period in UTC.
            end_utc (datetime): Optional end of time period in UTC. If omitted then a result for the start_utc only is returned.
            site (str): Optional Solcast site ID, used to provide site breakdown.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            float | None: Energy forecast to be remaining for a period as kWh.
        """
        data = self._data_forecasts if site is None else self._site_data_forecasts[site]
        forecast_confidence = self._use_forecast_confidence if forecast_confidence is None else forecast_confidence
        start_utc = start_utc.replace(minute=math.floor(start_utc.minute / 5) * 5)
        start_index, end_index = self.__get_list_slice(  # Get start and end indexes for the requested range.
            data, start_utc, end_utc
        )
        if (start_index == 0 and end_index == 0) or data[len(data) - 1][PERIOD_START] < end_utc:
            return None  # Set sensor to unavailable
        day_start = self.get_day_start_utc()
        result = self.__get_remaining(site, forecast_confidence, (start_utc - day_start).total_seconds())
        if end_utc is not None:
            end_utc = end_utc.replace(minute=math.floor(end_utc.minute / 5) * 5)
            if end_utc < day_start + timedelta(seconds=1800 * len(self._spline_period)) and result is not None:
                # End is within today so use spline data.
                if (val := self.__get_remaining(site, forecast_confidence, (end_utc - day_start).total_seconds())) is not None:
                    result -= val
            elif result is not None:
                # End is beyond today, so revert to simple linear interpolation.
                start_index_post_spline, _ = self.__get_list_slice(  # Get post-spline day onwards start index.
                    data,
                    day_start + timedelta(seconds=1800 * len(self._spline_period)),
                )
                for forecast in data[start_index_post_spline:end_index]:
                    forecast_period_next = forecast[PERIOD_START] + timedelta(seconds=1800)
                    seconds = 1800
                    interval = 0.5 * forecast[forecast_confidence]
                    if end_utc < forecast_period_next:
                        seconds -= (forecast_period_next - end_utc).total_seconds()
                        result += interval * seconds / 1800
                    else:
                        result += interval
        return max(0, result) if result is not None else None

    def __get_forecast_pv_estimates(
        self,
        start_utc: dt,
        end_utc: dt,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> float | None:
        """Return energy total for a period.

        Arguments:
            start_utc (datetime): Start of time period datetime in UTC.
            end_utc (datetime): End of time period datetime in UTC.
            site (str): Optional Solcast site ID, used to provide site breakdown.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            float | None: Energy forecast total for a period as kWh.
        """
        data = self._data_forecasts if site is None else self._site_data_forecasts[site]
        forecast_confidence = self._use_forecast_confidence if forecast_confidence is None else forecast_confidence
        result = 0
        start_index, end_index = self.__get_list_slice(  # Get start and end indexes for the requested range.
            data, start_utc, end_utc
        )
        if start_index == 0 and end_index == 0:
            return None
        for forecast_slice in data[start_index:end_index]:
            result += forecast_slice[forecast_confidence]
        return result

    def __get_forecast_pv_moment(
        self,
        time_utc: dt,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> float | None:
        """Return forecast power for a point in time.

        Arguments:
            time_utc (datetime): A moment in UTC to return.
            site (str): Optional Solcast site ID, used to provide site breakdown.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            float | None: Forecast power for a point in time as kW (from splined data).
        """
        forecast_confidence = self._use_forecast_confidence if forecast_confidence is None else forecast_confidence
        day_start = self.get_day_start_utc()
        time_utc = time_utc.replace(minute=math.floor(time_utc.minute / 5) * 5)
        return self.__get_moment(site, forecast_confidence, (time_utc - day_start).total_seconds())

    def __get_max_forecast_pv_estimate(
        self,
        start_utc: dt,
        end_utc: dt,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> dict[str, Any] | None:
        """Return forecast maximum interval for a period.

        Arguments:
            start_utc (datetime): Start of time period datetime in UTC.
            end_utc (datetime): End of time period datetime in UTC.
            site (str): Optional Solcast site ID, used to provide site breakdown.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            dict[str, Any] | None: The interval data with largest generation for a period.
        """
        result: dict[str, Any] | None = None
        data = self._data_forecasts if site is None else self._site_data_forecasts[site]
        forecast_confidence = self._use_forecast_confidence if forecast_confidence is None else forecast_confidence
        start_index, end_index = self.__get_list_slice(data, start_utc, end_utc)
        if start_index == 0 and end_index == 0:
            return None  # Set sensor to unavailable
        result = data[start_index]
        for forecast_slice in data[start_index:end_index]:
            if result[forecast_confidence] < forecast_slice[forecast_confidence]:
                result = forecast_slice
        return result

    def get_energy_data(self) -> dict[str, Any] | None:
        """Get energy data.

        Returns:
            dict[str, Any] | None: A Home Assistant energy dashboard compatible data set.
        """
        return self._data_energy_dashboard

    def __get_conversion_factor(self, entity: str, entity_history: list[State] | None = None, is_export: bool = False) -> float:
        """Get the conversion factor for an electricity energy entity to convert to kWh."""

        energy_unit_factors = {
            "mWh": 1e-6,
            "Wh": 0.001,
            "kWh": 1.0,
            "MWh": 1000.0,
        }
        entity_type = "Export entity" if is_export else "Entity"
        entity_unit = None

        if entity_history:
            # Check the entity history for the unit of measurement.
            latest_state = entity_history[-1]
            if hasattr(latest_state, "attributes") and latest_state.attributes:
                entity_unit = latest_state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)

        if not entity_unit:
            # If not found, get the unit of measurement from the entity registry.
            entity_registry = er.async_get(self.hass)
            entity_entry = entity_registry.async_get(entity)
            if entity_entry and entity_entry.unit_of_measurement:
                entity_unit = entity_entry.unit_of_measurement

        if not entity_unit:
            _LOGGER.warning("%s %s has no %s, assuming kWh", entity_type, entity, ATTR_UNIT_OF_MEASUREMENT)
            return 1.0

        conversion_factor = energy_unit_factors.get(entity_unit)
        if conversion_factor is None:
            _LOGGER.error("%s %s has an unsupported %s '%s', assuming kWh", entity_type, entity, ATTR_UNIT_OF_MEASUREMENT, entity_unit)
            return 1.0

        if conversion_factor != 1.0:
            _LOGGER.debug("%s %s uses %s, applying conversion factor %s", entity_type, entity, entity_unit, conversion_factor)

        return conversion_factor

    async def get_pv_generation(self) -> None:  # noqa: C901
        """Get PV generation from external entity/entities.

        Sensors must be increasing energy values (may reset at midnight), and the entities must have state history.
        Supports both kWh and other (e.g. Wh) sane electricity energy units with automatic conversion.
        Very large units of measurement are not supported (e.g. GWh, TWh) because of precision loss.
        """

        start_time = time.time()

        _ON = ("on", "1", "true", "True")
        _ALL = ("on", "off", "1", "0", "true", "false", "True", "False")

        # Load the generation history.
        generation: dict[dt, dict[str, Any]] = {generated[PERIOD_START]: generated for generated in self._data_generation[GENERATION]}
        days = 1 if len(generation) > 0 else self.advanced_options[ADVANCED_AUTOMATED_DAMPENING_GENERATION_HISTORY_LOAD_DAYS]

        entity_registry = er.async_get(self.hass)

        for day in range(days):
            # PV generation
            generation_intervals: dict[dt, float] = {
                self.get_day_start_utc(future=(-1 * day)) - timedelta(days=1) + timedelta(minutes=minute): 0
                for minute in range(0, 1440, 30)
            }
            for entity in self.options.generation_entities:
                r_entity = entity_registry.async_get(entity)
                if r_entity is None:
                    _LOGGER.error("Generation entity %s is not a valid entity", entity)
                    continue
                if r_entity.disabled_by is not None:
                    _LOGGER.error("Generation entity %s is disabled, please enable it", entity)
                    continue
                entity_history = await get_instance(self.hass).async_add_executor_job(
                    state_changes_during_period,
                    self.hass,
                    self.get_day_start_utc(future=(-1 * day)) - timedelta(days=1),
                    self.get_day_start_utc(future=(-1 * day)),
                    entity,
                )
                if entity_history.get(entity) and len(entity_history[entity]) > 4:
                    _LOGGER.debug("Retrieved day %d PV generation data from entity: %s", -1 + day * -1, entity)

                    # Get the conversion factor for the entity to convert to kWh.
                    conversion_factor = self.__get_conversion_factor(entity, entity_history[entity], is_export=False)
                    # Arrange the generation samples into half-hour intervals.
                    sample_time: list[dt] = [
                        e.last_updated.astimezone(datetime.UTC).replace(
                            minute=e.last_updated.astimezone(datetime.UTC).minute // 30 * 30, second=0, microsecond=0
                        )
                        for e in entity_history[entity]
                        if e.state.replace(".", "").isnumeric()
                    ]
                    # Build a list of generation delta values.
                    sample_generation: list[float] = [
                        0.0,
                        *diff([float(e.state) * conversion_factor for e in entity_history[entity] if e.state.replace(".", "").isnumeric()]),
                    ]
                    sample_generation_time: list[dt] = [
                        e.last_updated.astimezone(datetime.UTC) for e in entity_history[entity] if e.state.replace(".", "").isnumeric()
                    ]
                    sample_timedelta: list[int] = [
                        0,
                        *diff(
                            [
                                (
                                    e.last_updated.astimezone(datetime.UTC)
                                    - (self.get_day_start_utc(future=(-1 * day)) - timedelta(days=1))
                                ).total_seconds()
                                for e in entity_history[entity]
                                if e.state.replace(".", "").isnumeric()
                            ]
                        ),
                    ]

                    # Detemine generation-consistent or time-consistent increments, and the inter-quartile upper bound for ignoring excessive jumps.
                    uniform_increment = False
                    non_zero_samples = sorted([round(sample, 5) for sample in sample_generation if sample > 0.0003])
                    if percentile(non_zero_samples, 25) == percentile(non_zero_samples, 75):
                        uniform_increment = True
                    else:
                        non_zero_samples = sorted([sample for sample in sample_timedelta if sample > 0])
                    _, upper = interquartile_bounds(non_zero_samples, factor=(1.5 if uniform_increment else 2.2))
                    upper += 0.1 if uniform_increment else 1
                    _LOGGER.debug(
                        f"%s increments detected for entity: %s, outlier upper bound: {'%.3f kWh' if uniform_increment else '%d seconds'}",  # noqa: G004
                        "Generation-consistent" if uniform_increment else "Time-consistent",
                        entity,
                        upper,
                    )

                    # Build generation values for each interval, ignoring any excessive jumps.
                    ignored: dict[dt, bool] = {}
                    last_interval: dt | None = None
                    if (
                        len(sample_time) == len(sample_generation)
                        and len(sample_time) == len(sample_generation_time)
                        and len(sample_time) == len(sample_timedelta)
                    ):
                        for interval, kWh, report_time, time_delta in zip(
                            sample_time, sample_generation, sample_generation_time, sample_timedelta, strict=True
                        ):
                            if interval != last_interval:
                                # Only check the first sample of each interval for an excessive jump
                                last_interval = interval
                                if uniform_increment:
                                    if round(kWh, 4) > upper:  # Ignore excessive jumps.
                                        ignored[interval] = True
                                    else:
                                        generation_intervals[interval] += kWh
                                elif time_delta > upper and kWh > 0.0003:  # Ignore excessive jumps.
                                    if kWh <= 0.14:  # Small increments are probably valid
                                        generation_intervals[interval] += kWh
                                    else:
                                        ignored[interval] = True
                                else:
                                    generation_intervals[interval] += kWh
                                if ignored.get(interval):
                                    # Invalidate both this interval and the previous one because errant sample straddles the half-hour boundary.
                                    ignored[interval - timedelta(minutes=30)] = True
                                    _LOGGER.debug(
                                        "Ignoring excessive PV generation jump of %.3f kWh, time delta %d seconds, at %s from entity: %s; Invalidating intervals %s and %s",
                                        kWh,
                                        time_delta,
                                        report_time.astimezone(self._tz).strftime("%Y-%m-%d %H:%M:%S"),
                                        entity,
                                        (interval - timedelta(minutes=30)).astimezone(self._tz).strftime("%H:%M"),
                                        interval.astimezone(self._tz).strftime("%H:%M"),
                                    )
                            else:
                                generation_intervals[interval] += kWh
                        for interval in ignored:
                            generation_intervals[interval] = 0.0
                else:
                    _LOGGER.debug(
                        "No day %d PV generation data (or barely any) from entity: %s (%s)",
                        -1 + day * -1,
                        entity,
                        entity_history.get(entity),
                    )
            for i, gen in generation_intervals.items():
                generation_intervals[i] = round(gen, 3)

            export_limiting: dict[dt, bool] = {
                self.get_day_start_utc(future=(-1 * day)) - timedelta(days=1) + timedelta(minutes=minute): False
                for minute in range(0, 1440, 30)
            }

            # Identify intervals intentionally disabled by the user.
            platforms = [PLATFORM_BINARY_SENSOR, PLATFORM_SENSOR, PLATFORM_SWITCH]
            find_entity = self.advanced_options[ADVANCED_AUTOMATED_DAMPENING_SUPPRESSION_ENTITY]
            entity = ""
            found = False
            for p in platforms:
                entity = f"{p}.{find_entity}"
                r_entity = entity_registry.async_get(entity)
                if r_entity is not None and r_entity.disabled_by is None:
                    found = True
                    break
            if found:
                _LOGGER.debug("Suppression entity %s exists", entity)
                query_start_time = self.get_day_start_utc(future=(-1 * day)) - timedelta(days=1)
                query_end_time = self.get_day_start_utc(future=(-1 * day))

                # Get state changes during the period
                entity_history = await get_instance(self.hass).async_add_executor_job(
                    state_changes_during_period,
                    self.hass,
                    query_start_time,
                    query_end_time,
                    entity,
                    True,  # No attributes
                    False,  # Descending order
                    None,  # Limit
                    True,  # Include start time state
                )

                if entity_history.get(entity) and len(entity_history[entity]):
                    entity_state: dict[dt, bool] = {}
                    state = False

                    for e in entity_history[entity]:
                        if e.state not in _ALL:
                            continue
                        interval = e.last_updated.astimezone(datetime.UTC).replace(
                            minute=e.last_updated.astimezone(datetime.UTC).minute // 30 * 30, second=0, microsecond=0
                        )
                        if e.state in _ON:
                            state = True
                            if not entity_state.get(interval):
                                entity_state[interval] = state
                                if state and entity_state.get(interval + timedelta(minutes=30)) is not None:
                                    entity_state.pop(interval + timedelta(minutes=30))
                            _LOGGER.debug(
                                "Interval %s state change %s at %s",
                                interval.astimezone(self._tz).strftime("%Y-%m-%d %H:%M"),
                                entity_state[interval],
                                e.last_updated.astimezone(self._tz).strftime("%Y-%m-%d %H:%M"),
                            )
                        elif state:
                            state = False
                            entity_state[interval + timedelta(minutes=30)] = False
                            _LOGGER.debug(
                                "Interval %s state change %s at %s",
                                (interval + timedelta(minutes=30)).astimezone(self._tz).strftime("%Y-%m-%d %H:%M"),
                                entity_state[interval + timedelta(minutes=30)],
                                e.last_updated.astimezone(self._tz).strftime("%Y-%m-%d %H:%M"),
                            )
                    state = False
                    for interval in export_limiting:
                        if entity_state.get(interval) is not None:
                            state = entity_state[interval]
                        export_limiting[interval] = state
                        if state:
                            _LOGGER.debug(
                                "Auto-dampen suppressed for interval %s", interval.astimezone(self._tz).strftime("%Y-%m-%d %H:%M")
                            )

            # Detect site export limiting
            if self.options.site_export_limit > 0 and self.options.site_export_entity != "":
                _INTERVAL = 5  # The time window in minutes to detect export limiting

                entity = self.options.site_export_entity
                r_entity = entity_registry.async_get(entity)
                if r_entity is None:
                    _LOGGER.error("Site export entity %s is not a valid entity", entity)
                    entity = ""
                elif r_entity.disabled_by is not None:
                    _LOGGER.error("Site export entity %s is disabled, please enable it", entity)
                    entity = ""
                export_intervals: dict[dt, float] = {
                    self.get_day_start_utc(future=(-1 * day)) - timedelta(days=1) + timedelta(minutes=minute): 0
                    for minute in range(0, 1440, _INTERVAL)
                }
                if entity:
                    entity_history = await get_instance(self.hass).async_add_executor_job(
                        state_changes_during_period,
                        self.hass,
                        self.get_day_start_utc(future=(-1 * day)) - timedelta(days=1),
                        self.get_day_start_utc(future=(-1 * day)),
                        entity,
                    )
                    if entity_history.get(entity) and len(entity_history[entity]):
                        # Get the conversion factor for the entity to convert to kWh.
                        conversion_factor = self.__get_conversion_factor(entity, entity_history[entity], is_export=False)
                        # Arrange the site export samples into intervals.
                        sample_time: list[dt] = [
                            e.last_updated.astimezone(datetime.UTC).replace(
                                minute=e.last_updated.astimezone(datetime.UTC).minute // _INTERVAL * _INTERVAL, second=0, microsecond=0
                            )
                            for e in entity_history[entity]
                            if e.state.replace(".", "").isnumeric()
                        ]
                        # Build a list of export delta values.
                        sample_export: list[float] = [
                            0.0,
                            *diff(
                                [float(e.state) * conversion_factor for e in entity_history[entity] if e.state.replace(".", "").isnumeric()]
                            ),
                        ]
                        for interval, kWh in zip(sample_time, sample_export, strict=True):
                            export_intervals[interval] += kWh
                        # Convert to export per interval in kW.
                        for i, export in export_intervals.items():
                            export_intervals[i] = round(export * (60 / _INTERVAL), 3)

                        for i, export in export_intervals.items():
                            export_interval = i.replace(minute=i.minute // 30 * 30)
                            if export >= self.options.site_export_limit and generation_intervals[export_interval] > 0:
                                export_limiting[export_interval] = True
                    else:
                        _LOGGER.debug("No site export history found for %s", entity)

            # Add recent generation intervals to the history.
            generation.update(
                {
                    i: {PERIOD_START: i, GENERATION: generated, EXPORT_LIMITING: export_limiting[i]}
                    for i, generated in generation_intervals.items()
                }
            )

        # Trim, sort and serialise.
        self._data_generation = {
            LAST_UPDATED: dt.now(datetime.UTC).replace(microsecond=0),
            GENERATION: sorted(
                filter(
                    lambda generated: generated[PERIOD_START] >= self.get_day_start_utc(future=-22),
                    generation.values(),
                ),
                key=itemgetter(PERIOD_START),
            ),
        }
        await self.serialise_data(self._data_generation, self._filename_generation)
        _LOGGER.debug("Task get_pv_generation took %.3f seconds", time.time() - start_time)

    def adjusted_interval(self, interval: dict[str, Any]) -> int:
        """Adjust a forecast/actual interval as standard time."""
        offset = 1 if self.is_interval_dst(interval) else 0
        return (
            ((interval[PERIOD_START].astimezone(self._tz).hour - offset) * 2 + interval[PERIOD_START].astimezone(self._tz).minute // 30)
            if interval[PERIOD_START].astimezone(self._tz).hour - offset >= 0
            else 0
        )

    def adjusted_interval_dt(self, interval: dt) -> int:
        """Adjust a datetime as standard time."""
        offset = 1 if self.dst(interval.astimezone(self._tz)) else 0
        return (
            ((interval.astimezone(self._tz).hour - offset) * 2 + interval.astimezone(self._tz).minute // 30)
            if interval.astimezone(self._tz).hour - offset >= 0
            else 0
        )

    async def model_automated_dampening(self, force: bool = False) -> None:  # noqa: C901
        """Model the automated dampening of the forecast data.

        Look for consistently low PV generation in consistently high estimated actual intervals.
        Dampening factors are always referenced using standard time (not daylight savings time).
        """
        start_time = time.time()

        deal_breaker = ""
        deal_breaker_site = ""
        actuals: OrderedDict[dt, float] = OrderedDict()
        if (self.options.auto_dampen or self.advanced_options[ADVANCED_GRANULAR_DAMPENING_DELTA_ADJUSTMENT]) and self.options.get_actuals:
            _LOGGER.debug("Determining peak estimated actual intervals")
            for site in self.sites:
                if self._data_actuals[SITE_INFO].get(site[RESOURCE_ID]) is None:
                    deal_breaker = "No estimated actuals yet"
                    deal_breaker_site = site[RESOURCE_ID]
                    break
                if site[RESOURCE_ID] in self.options.exclude_sites:
                    _LOGGER.debug("Auto-dampening suppressed: Excluded site for %s", site[RESOURCE_ID])
                    continue
                start, end = self.__get_list_slice(
                    self._data_actuals[SITE_INFO][site[RESOURCE_ID]][FORECASTS],
                    self.get_day_start_utc() - timedelta(days=self.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS]),
                    self.get_day_start_utc(),
                    search_past=True,
                )
                site_actuals = {
                    actual[PERIOD_START]: actual for actual in self._data_actuals[SITE_INFO][site[RESOURCE_ID]][FORECASTS][start:end]
                }
                for period_start, actual in site_actuals.items():
                    extant: float | None = actuals.get(period_start)
                    if extant is not None:
                        actuals[period_start] += actual[ESTIMATE] * 0.5
                    else:
                        actuals[period_start] = actual[ESTIMATE] * 0.5

            if deal_breaker == "":
                # Collect top intervals from the past MODEL_DAYS days.
                self._peak_intervals = dict.fromkeys(range(48), 0.0)
                for period_start, actual in actuals.items():
                    interval = self.adjusted_interval_dt(period_start)
                    if self._peak_intervals[interval] < actual:
                        self._peak_intervals[interval] = round(actual, 3)

        if not self.options.auto_dampen and not force:
            _LOGGER.debug("Automated dampening is not enabled, skipping model_automated_dampening()")
            return
        _LOGGER.debug("Modelling automated dampening factors")

        if deal_breaker == "":
            if len(self._data_generation[GENERATION]) == 0:
                deal_breaker = "No generation yet"

        if deal_breaker != "":
            _LOGGER.info("Auto-dampening suppressed: %s%s", deal_breaker, f" for {deal_breaker_site}" if deal_breaker_site != "" else "")
            return

        ignored_intervals: list[int] = []  # Intervals to ignore in local time zone
        for time_string in self.advanced_options[ADVANCED_AUTOMATED_DAMPENING_IGNORE_INTERVALS]:
            hour, minute = map(int, time_string.split(":"))
            interval = hour * 2 + minute // 30
            ignored_intervals.append(interval)

        export_limited_intervals = dict.fromkeys(range(50), False)
        if not self.advanced_options[ADVANCED_AUTOMATED_DAMPENING_NO_LIMITING_CONSISTENCY]:
            for gen in self._data_generation[GENERATION][-1 * self.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS] * 48 :]:
                if gen[EXPORT_LIMITING]:
                    export_limited_intervals[self.adjusted_interval(gen)] = True

        generation: dict[dt, float] = {}
        for gen in self._data_generation[GENERATION][-1 * self.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS] * 48 :]:
            if not self.advanced_options[ADVANCED_AUTOMATED_DAMPENING_NO_LIMITING_CONSISTENCY]:
                if not export_limited_intervals[self.adjusted_interval(gen)]:
                    generation[gen[PERIOD_START]] = gen[GENERATION]
            elif not gen[EXPORT_LIMITING]:
                generation[gen[PERIOD_START]] = gen[GENERATION]

        # Collect intervals that are close to the peak.
        matching_intervals: dict[int, list[dt]] = {i: [] for i in range(48)}
        for period_start, actual in actuals.items():
            interval = self.adjusted_interval_dt(period_start)
            if actual > self.advanced_options[ADVANCED_AUTOMATED_DAMPENING_SIMILAR_PEAK] * self._peak_intervals[interval]:
                matching_intervals[interval].append(period_start)

        # Defaults.
        dampening: list[float] = [1.0] * 48

        # Check the generation for each interval and determine if it is consistently lower than the peak.
        for interval, matching in matching_intervals.items():
            # Get current factor if required
            if self.advanced_options[ADVANCED_AUTOMATED_DAMPENING_PRESERVE_UNMATCHED_FACTORS]:
                prior_factor = self.granular_dampening[ALL][interval] if self.granular_dampening.get(ALL) is not None else 1.0

            dst_offset = (
                1 if self.dst(dt.now(self._tz).replace(hour=interval // 2, minute=30 * (interval % 2), second=0, microsecond=0)) else 0
            )
            interval_time = f"{interval // 2 + (dst_offset):02}:{30 * (interval % 2):02}"
            if interval + dst_offset * 2 in ignored_intervals:
                _LOGGER.debug("Interval %s is intentionally ignored, skipping", interval_time)
                continue
            generation_samples: list[float] = [
                round(generation.get(timestamp, 0.0), 3) for timestamp in matching if generation.get(timestamp, 0.0) != 0.0
            ]
            preserve_this_interval = False
            if len(matching) > 0:
                msg = ""
                log_msg = True
                _LOGGER.debug(
                    "Interval %s has peak estimated actual %.3f and %d matching intervals: %s",
                    interval_time,
                    self._peak_intervals[interval],
                    len(matching),
                    ", ".join([date.astimezone(self._tz).strftime(DT_DATE_MONTH_DAY) for date in matching]),
                )
                match self.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL]:
                    case 1 | 2 | 3:
                        if len(matching) >= self.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_INTERVALS]:
                            actual_samples: list[float] = [
                                actuals.get(timestamp, 0.0) for timestamp in matching if generation.get(timestamp, 0.0) != 0.0
                            ]
                            _LOGGER.debug(
                                "Selected %d estimated actuals for %s: %s",
                                len(actual_samples),
                                interval_time,
                                ", ".join(f"{act:.3f}" for act in actual_samples),
                            )
                            _LOGGER.debug(
                                "Selected %d generation records for %s: %s", len(generation_samples), interval_time, generation_samples
                            )
                            if len(generation_samples) >= self.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_GENERATION]:
                                if len(actual_samples) == len(generation_samples):
                                    raw_factors: list[float] = []
                                    for act, gen in zip(actual_samples, generation_samples, strict=True):
                                        raw_factors.append(min(gen / act, 1.0)) if act > 0 else 1.0
                                    _LOGGER.debug(
                                        "Candidate factors for %s: %s",
                                        interval_time,
                                        ", ".join(f"{fact:.3f}" for fact in raw_factors),
                                    )
                                    match self.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MODEL]:
                                        case 1:  # max factor from matched pairs
                                            factor = max(raw_factors)
                                        case 2:  # average factor from matched pairs
                                            factor = sum(raw_factors) / len(raw_factors)
                                        case 3:  # min factor from matched pairs
                                            factor = min(raw_factors)
                                    factor = round(factor, 3) if factor > 0 else 1.0
                                    if self.advanced_options[ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR] <= factor < 1.0:
                                        msg = f"Ignoring insignificant factor for {interval_time} of {factor:.3f}"
                                        factor = 1.0
                                    else:
                                        msg = f"Auto-dampen factor for {interval_time} is {factor:.3f}"
                                    dampening[interval] = factor
                                msg = (
                                    f"Mismatched sample lengths for {interval_time}: {len(actual_samples)} actuals vs {len(generation_samples)} generations"
                                    if len(actual_samples) != len(generation_samples)
                                    else msg
                                )
                            else:
                                msg = f"Not enough reliable generation samples for {interval_time} to determine dampening ({len(generation_samples)})"
                                preserve_this_interval = self.advanced_options[ADVANCED_AUTOMATED_DAMPENING_PRESERVE_UNMATCHED_FACTORS]
                    case _:
                        peak = max(generation_samples) if len(generation_samples) > 0 else 0.0
                        _LOGGER.debug("Interval %s max generation: %.3f, %s", interval_time, peak, generation_samples)
                        if len(matching) >= self.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_INTERVALS]:
                            if peak < self._peak_intervals[interval]:
                                if (
                                    len(generation_samples)
                                    >= self.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_GENERATION]
                                ):
                                    factor = (peak / self._peak_intervals[interval]) if self._peak_intervals[interval] != 0 else 1.0
                                    if self.advanced_options[ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR] <= factor < 1.0:
                                        msg = f"Ignoring insignificant factor for {interval_time} of {factor:.3f}"
                                        factor = 1.0
                                    else:
                                        msg = f"Auto-dampen factor for {interval_time} is {factor:.3f}"
                                    dampening[interval] = round(factor, 3)
                                else:
                                    msg = f"Not enough reliable generation samples for {interval_time} to determine dampening ({len(generation_samples)})"
                                    preserve_this_interval = self.advanced_options[ADVANCED_AUTOMATED_DAMPENING_PRESERVE_UNMATCHED_FACTORS]
                            else:
                                log_msg = False

                if not preserve_this_interval:
                    msg = (
                        f"Not enough matching intervals for {interval_time} to determine dampening"
                        if len(matching) < self.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_INTERVALS]
                        else msg
                    )
                    preserve_this_interval = (
                        self.advanced_options[ADVANCED_AUTOMATED_DAMPENING_PRESERVE_UNMATCHED_FACTORS]
                        and len(matching) < self.advanced_options[ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_INTERVALS]
                    )

                if preserve_this_interval:
                    dampening[interval] = prior_factor
                    msg = msg + f", preserving prior factor {prior_factor:.3f}" if prior_factor != 1.0 else msg

                if log_msg and msg != "":
                    _LOGGER.debug(msg)

        if dampening != self.granular_dampening.get(ALL):
            self.granular_dampening[ALL] = dampening
            await self.serialise_granular_dampening()
            await self.granular_dampening_data()
        _LOGGER.debug("Task model_automated_dampening took %.3f seconds", time.time() - start_time)

    async def update_estimated_actuals(self, dampen_yesterday: bool = False) -> None:
        """Update estimated actuals."""

        status: DataCallStatus = DataCallStatus.SUCCESS
        reason: str = ""

        start_time = time.time()

        for site in self.sites:
            _LOGGER.info("Getting estimated actuals update for site %s", site[RESOURCE_ID])
            api_key = site[API_KEY]

            new_data: list[dict[str, Any]] = []

            act_response: dict[str, Any] | None
            try:
                self.tasks[TASK_ACTUALS_FETCH] = asyncio.create_task(
                    self.fetch_data(
                        hours=168,
                        path=ESTIMATED_ACTUALS,
                        site=site[RESOURCE_ID],
                        api_key=api_key,
                        force=True,
                    )
                )
                await self.tasks[TASK_ACTUALS_FETCH]
            finally:
                act_response = self.tasks.pop(TASK_ACTUALS_FETCH).result() if self.tasks.get(TASK_ACTUALS_FETCH) is not None else None
            if not isinstance(act_response, dict):
                _LOGGER.error("No valid data was returned for estimated_actuals so this may cause issues")
                _LOGGER.error("API did not return a json object, returned `%s`", act_response)
                status = DataCallStatus.FAIL
                reason = "No valid json returned"
                break

            estimate_actuals: list[dict[str, Any]] = act_response.get(ESTIMATED_ACTUALS, [])

            oldest = (dt.now(self._tz).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6)).astimezone(datetime.UTC)

            for estimate_actual in estimate_actuals:
                period_start = dt.fromisoformat(estimate_actual[PERIOD_END]).astimezone(datetime.UTC).replace(
                    second=0, microsecond=0
                ) - timedelta(minutes=30)
                if period_start > oldest:
                    new_data.append(
                        {
                            PERIOD_START: period_start,
                            ESTIMATE: estimate_actual[ESTIMATE],
                        }
                    )

            # Load the actuals history and add or update the new entries.
            actuals = (
                {actual[PERIOD_START]: actual for actual in self._data_actuals[SITE_INFO][site[RESOURCE_ID]][FORECASTS]}
                if self._data_actuals[SITE_INFO].get(site[RESOURCE_ID])
                else {}
            )
            for actual in new_data:
                forecast_entry_update(
                    actuals,
                    actual[PERIOD_START],
                    round(actual[ESTIMATE], 4),
                )

            await self.sort_and_prune(site[RESOURCE_ID], self._data_actuals, self.advanced_options[ADVANCED_HISTORY_MAX_DAYS], actuals)
            _LOGGER.debug("Estimated actuals dictionary for site %s length %s", site[RESOURCE_ID], len(actuals))

        if status == DataCallStatus.SUCCESS and dampen_yesterday:
            # Apply dampening to yesterday actuals, but only if the new factors for the day have not been modelled.

            undampened_interval_pv50: dict[dt, float] = {}
            for site in self.sites:
                if site[RESOURCE_ID] in self.options.exclude_sites:
                    continue
                for forecast in self._data_actuals[SITE_INFO][site[RESOURCE_ID]][FORECASTS]:
                    period_start = forecast[PERIOD_START]
                    if period_start >= self.get_day_start_utc(future=-1) and period_start < self.get_day_start_utc():
                        if period_start not in undampened_interval_pv50:
                            undampened_interval_pv50[period_start] = forecast[ESTIMATE] * 0.5
                        else:
                            undampened_interval_pv50[period_start] += forecast[ESTIMATE] * 0.5

            for site in self.sites:
                if site[RESOURCE_ID] not in self.options.exclude_sites:
                    _LOGGER.debug("Apply dampening to previous day estimated actuals for %s", site[RESOURCE_ID])
                    # Load the undampened estimated actual day yesterday.
                    actuals_undampened_day = [
                        actual
                        for actual in self._data_actuals[SITE_INFO][site[RESOURCE_ID]][FORECASTS]
                        if actual[PERIOD_START] >= self.get_day_start_utc(future=-1) and actual[PERIOD_START] < self.get_day_start_utc()
                    ]
                    extant_actuals = (
                        {actual[PERIOD_START]: actual for actual in self._data_actuals_dampened[SITE_INFO][site[RESOURCE_ID]][FORECASTS]}
                        if self._data_actuals_dampened[SITE_INFO].get(site[RESOURCE_ID])
                        else {}
                    )

                    for actual in actuals_undampened_day:
                        period_start = actual[PERIOD_START]
                        undampened = actual[ESTIMATE]
                        factor = self.__get_dampening_factor(
                            site[RESOURCE_ID], period_start.astimezone(self._tz), undampened_interval_pv50.get(period_start, -1.0)
                        )
                        dampened = round(undampened * factor, 4)
                        forecast_entry_update(
                            extant_actuals,
                            period_start,
                            dampened,
                        )

                    await self.sort_and_prune(
                        site[RESOURCE_ID],
                        self._data_actuals_dampened,
                        self.advanced_options[ADVANCED_HISTORY_MAX_DAYS],
                        extant_actuals,
                    )

        if status != DataCallStatus.SUCCESS:
            _LOGGER.error("Update estimated actuals failed: %s", reason)
        else:
            self._data_actuals[LAST_UPDATED] = dt.now(datetime.UTC).replace(microsecond=0)
            self._data_actuals[LAST_ATTEMPT] = dt.now(datetime.UTC).replace(microsecond=0)
            await self.serialise_data(self._data_actuals, self._filename_actuals)
            self._data_actuals_dampened[LAST_UPDATED] = dt.now(datetime.UTC).replace(microsecond=0)
            self._data_actuals_dampened[LAST_ATTEMPT] = dt.now(datetime.UTC).replace(microsecond=0)
            await self.serialise_data(self._data_actuals_dampened, self._filename_actuals_dampened)

        _LOGGER.debug("Task update_estimated_actuals took %.3f seconds", time.time() - start_time)

    async def get_forecast_update(self, do_past_hours: int = 0, force: bool = False) -> str:
        """Request forecast data for all sites.

        Arguments:
            do_past_hours (int): A optional number of past actual forecast hours that should be retrieved.
            force (bool): A forced update, which does not update the internal API use counter.

        Returns:
            str: An error message, or an empty string for no error.
        """
        last_attempt = dt.now(datetime.UTC)
        status = ""

        def next_update():
            if self._next_update is not None:
                return f", next auto update at {self._next_update}"
            return ""

        if last_updated := self.get_last_updated():
            if last_updated + timedelta(seconds=10) > dt.now(datetime.UTC):
                status = f"Not requesting a solar forecast because time is within ten seconds of last update ({last_updated.astimezone(self._tz)})"
                _LOGGER.warning(status)
                if self._next_update is not None:
                    _LOGGER.info("Forecast update suppressed%s", next_update())
                return status

        await self.refresh_granular_dampening_data()

        failure = False
        sites_attempted = 0
        sites_succeeded = 0
        reason = "Unknown"
        for site in self.sites:
            sites_attempted += 1
            _LOGGER.info(
                "Getting forecast update for site %s%s",
                site[RESOURCE_ID],
                f", including {do_past_hours} hours of past data" if do_past_hours > 0 else "",
            )
            result, reason = await self.__http_data_call(
                site=site[RESOURCE_ID],
                api_key=site[API_KEY],
                do_past_hours=do_past_hours,
                force=force,
            )
            if result == DataCallStatus.FAIL:
                failure = True
                _LOGGER.warning(
                    "Forecast update for site %s failed%s%s",
                    site[RESOURCE_ID],
                    " so not getting remaining sites" if sites_attempted < len(self.sites) else "",
                    " - API use count may be odd" if len(self.sites) > 1 and sites_succeeded and not force else "",
                )
                status = "At least one site forecast get failed" if len(self.sites) > 1 else "Forecast get failed"
                break
            if result == DataCallStatus.ABORT:
                _LOGGER.info("Forecast update aborted%s", next_update())
                return ""
            if result == DataCallStatus.SUCCESS:
                sites_succeeded += 1

        if sites_attempted > 0 and not failure:
            await self.apply_forward_dampening(do_past_hours=do_past_hours)

            b_status = await self.build_forecast_data()
            self._loaded_data = True

            async def set_metadata_and_serialise(data: dict[str, Any]):
                data[LAST_UPDATED] = dt.now(datetime.UTC).replace(microsecond=0)
                data[LAST_ATTEMPT] = last_attempt
                # Set to divisions if auto update is enabled, but not forced, in which case set to 99999 (otherwise zero).
                data[AUTO_UPDATED] = (
                    self.auto_update_divisions if self.options.auto_update != AutoUpdate.NONE and not force else 0 if not force else 99999
                )
                return await self.serialise_data(data, self._filename if data == self._data else self._filename_undampened)

            s_status = await set_metadata_and_serialise(self._data)
            await set_metadata_and_serialise(self._data_undampened)
            self._loaded_data = True

            if b_status and s_status:
                _LOGGER.info("Forecast update completed successfully%s", next_update())
        else:
            _LOGGER.warning("Forecast has not been updated%s", next_update())
            status = f"At least one site forecast get failed: {reason}"
        return status

    def set_next_update(self, next_update: str | None) -> None:
        """Set the next update time.

        Arguments:
            next_update (str | None): A string containing the time that the next auto update will occur.
        """
        self._next_update = next_update

    async def __migrate_undampened_history(self):
        """Migrate un-dampened forecasts if un-dampened data for a site does not exist."""
        apply_dampening: list[str] = []
        forecasts: dict[str, dict[dt, Any]] = {}
        past_days = self.get_day_start_utc(future=-14)
        for site in self.sites:
            site = site[RESOURCE_ID]
            if not self._data_undampened[SITE_INFO].get(site) or len(self._data_undampened[SITE_INFO][site].get(FORECASTS, [])) == 0:
                _LOGGER.info(
                    "Migrating un-dampened history to %s for %s",
                    self._filename_undampened,
                    site,
                )
                apply_dampening.append(site)
            else:
                continue
            # Load the forecast history.
            forecasts[site] = {forecast[PERIOD_START]: forecast for forecast in self._data[SITE_INFO][site][FORECASTS]}
            forecasts_undampened: list[dict[str, Any]] = []
            # Migrate forecast history if un-dampened data does not yet exist.
            if len(forecasts[site]) > 0:
                forecasts_undampened = sorted(
                    {
                        forecast[PERIOD_START]: forecast
                        for forecast in self._data[SITE_INFO][site][FORECASTS]
                        if forecast[PERIOD_START] >= past_days
                    }.values(),
                    key=itemgetter(PERIOD_START),
                )
                _LOGGER.debug(
                    "Migrating %d forecast entries to un-dampened forecasts for site %s",
                    len(forecasts_undampened),
                    site,
                )
            self._data_undampened[SITE_INFO].update({site: {FORECASTS: copy.deepcopy(forecasts_undampened)}})

        if len(apply_dampening) > 0:
            self._data_undampened[LAST_UPDATED] = dt.now(datetime.UTC).replace(microsecond=0)
            await self.serialise_data(self._data_undampened, self._filename_undampened)

        if len(apply_dampening) > 0:
            await self.apply_forward_dampening(applicable_sites=apply_dampening)
            await self.serialise_data(self._data, self._filename)

    def __get_dampening_granular_factor(
        self, site: str, period_start: dt, interval_pv50: float = -1.0, record_adjustment: bool = False
    ) -> float:
        """Retrieve a granular dampening factor."""
        factor = self.granular_dampening[site][
            period_start.hour
            if len(self.granular_dampening[site]) == 24
            else ((period_start.hour * 2) + (1 if period_start.minute > 0 else 0))
        ]
        if (
            site == ALL
            and (self.options.auto_dampen or self.advanced_options[ADVANCED_GRANULAR_DAMPENING_DELTA_ADJUSTMENT])
            and self.granular_dampening.get(ALL)
        ):
            interval = self.adjusted_interval_dt(period_start)
            factor = min(1.0, self.granular_dampening[ALL][interval])
            if (
                not self.advanced_options[ADVANCED_AUTOMATED_DAMPENING_NO_DELTA_ADJUSTMENT]
                and self._peak_intervals[interval] > 0
                and interval_pv50 > 0
                and factor < 1.0
            ):
                interval_time = period_start.astimezone(self._tz).strftime(DT_DATE_FORMAT)
                factor_pre_adjustment = factor

                match self.advanced_options[ADVANCED_AUTOMATED_DAMPENING_DELTA_ADJUSTMENT_MODEL]:
                    case 1:
                        # Adjust the factor based on forecast vs. peak interval using squared ratio
                        factor = max(factor, factor + ((1.0 - factor) * ((1.0 - (interval_pv50 / self._peak_intervals[interval])) ** 2)))
                    case _:
                        # Adjust the factor based on forecast vs. peak interval delta-logarithmically.
                        factor = max(
                            factor,
                            min(1.0, factor + ((1.0 - factor) * (math.log(self._peak_intervals[interval]) - math.log(interval_pv50)))),
                        )
                if (
                    record_adjustment
                    and period_start.astimezone(self._tz).date() == dt.now(self._tz).date()
                    and round(factor, 3) != round(factor_pre_adjustment, 3)
                ):
                    _LOGGER.debug(
                        "%sdjusted granular dampening factor for %s, %.3f (was %.3f, peak %.3f, interval pv50 %.3f)",
                        "Ignoring insignificant a"
                        if self.advanced_options[ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR_ADJUSTED] <= factor < 1.0
                        else "A",
                        interval_time,
                        factor,
                        factor_pre_adjustment,
                        self._peak_intervals[interval],
                        interval_pv50,
                    )
                if factor >= self.advanced_options[ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR_ADJUSTED]:
                    factor = 1.0

        return min(1.0, factor)

    def __get_dampening_factor(self, site: str | None, period_start: dt, interval_pv50: float, record_adjustment: bool = False) -> float:
        """Retrieve either a traditional or granular dampening factor."""
        if site is not None:
            if self.entry_options.get(SITE_DAMP):
                if self.granular_dampening.get(ALL):
                    return self.__get_dampening_granular_factor(ALL, period_start, interval_pv50, record_adjustment=record_adjustment)
                if self.granular_dampening.get(site):
                    return self.__get_dampening_granular_factor(site, period_start)
                return 1.0
        return self.damp.get(f"{period_start.hour}", 1.0)

    async def apply_forward_dampening(self, applicable_sites: list[str] | None = None, do_past_hours: int = 0) -> None:
        """Apply dampening to forward forecasts."""
        if len(self._data_undampened[SITE_INFO]) > 0:
            _LOGGER.debug("Applying future dampening")

            self._auto_dampening_factors = {
                period_start: factor
                for period_start, factor in self._auto_dampening_factors.items()
                if period_start >= self.get_day_start_utc()
            }

            undampened_interval_pv50: dict[dt, float] = {}
            for site in self.sites:
                if site[RESOURCE_ID] in self.options.exclude_sites:
                    continue
                for forecast in self._data_undampened[SITE_INFO][site[RESOURCE_ID]][FORECASTS]:
                    period_start = forecast[PERIOD_START]
                    if period_start >= self.get_day_start_utc():
                        if period_start not in undampened_interval_pv50:
                            undampened_interval_pv50[period_start] = forecast[ESTIMATE] * 0.5
                        else:
                            undampened_interval_pv50[period_start] += forecast[ESTIMATE] * 0.5

            record_adjustment = True
            for site in self.sites:
                # Load all forecasts.
                forecasts_undampened_future = [
                    forecast
                    for forecast in self._data_undampened[SITE_INFO][site[RESOURCE_ID]][FORECASTS]
                    if forecast[PERIOD_START]
                    >= (
                        self.get_day_start_utc()
                        if self._data[SITE_INFO].get(site[RESOURCE_ID])
                        else self.get_day_start_utc() - timedelta(hours=do_past_hours)
                    )  # Was >= dt.now(datetime.UTC)
                ]
                forecasts = (
                    {forecast[PERIOD_START]: forecast for forecast in self._data[SITE_INFO][site[RESOURCE_ID]][FORECASTS]}
                    if self._data[SITE_INFO].get(site[RESOURCE_ID])
                    else {}
                )

                if site[RESOURCE_ID] not in self.options.exclude_sites and (
                    (site[RESOURCE_ID] in applicable_sites) if applicable_sites else True
                ):
                    # Apply dampening to forward data
                    for forecast in sorted(forecasts_undampened_future, key=itemgetter(PERIOD_START)):
                        period_start = forecast[PERIOD_START]
                        pv = round(forecast[ESTIMATE], 4)
                        pv10 = round(forecast[ESTIMATE10], 4)
                        pv90 = round(forecast[ESTIMATE90], 4)

                        # Retrieve the dampening factor for the period, and dampen the estimates.
                        dampening_factor = self.__get_dampening_factor(
                            site[RESOURCE_ID],
                            period_start.astimezone(self._tz),
                            undampened_interval_pv50.get(period_start, -1),
                            record_adjustment=record_adjustment,
                        )
                        if record_adjustment:
                            self._auto_dampening_factors[period_start] = dampening_factor
                        pv_dampened = round(pv * dampening_factor, 4)
                        pv10_dampened = round(pv10 * dampening_factor, 4)
                        pv90_dampened = round(pv90 * dampening_factor, 4)

                        # Add or update the new entries.
                        forecast_entry_update(forecasts, period_start, pv_dampened, pv10_dampened, pv90_dampened)
                    record_adjustment = False
                else:
                    for forecast in sorted(forecasts_undampened_future, key=itemgetter(PERIOD_START)):
                        period_start = forecast[PERIOD_START]
                        forecast_entry_update(
                            forecasts,
                            period_start,
                            round(forecast[ESTIMATE], 4),
                            round(forecast[ESTIMATE10], 4),
                            round(forecast[ESTIMATE90], 4),
                        )

                await self.sort_and_prune(site[RESOURCE_ID], self._data, self.advanced_options[ADVANCED_HISTORY_MAX_DAYS], forecasts)

    async def sort_and_prune(self, site: str | None, data: dict[str, Any], past_days: int, forecasts: dict[Any, Any]) -> None:
        """Sort and prune a forecast list."""

        _past_days = self.get_day_start_utc(future=past_days * -1)
        _forecasts: list[dict[str, Any]] = sorted(
            filter(
                lambda forecast: forecast[PERIOD_START] >= _past_days,
                forecasts.values(),
            ),
            key=itemgetter(PERIOD_START),
        )
        data[SITE_INFO].update({site: {FORECASTS: copy.deepcopy(_forecasts)}})

    async def __http_data_call(
        self,
        site: str | None = None,
        api_key: str | None = None,
        do_past_hours: int = 0,
        force: bool = False,
    ) -> tuple[DataCallStatus, str]:
        """Request forecast data via the Solcast API.

        Arguments:
            site (str): A Solcast site ID
            api_key (str): A Solcast API key appropriate to use for the site
            do_past_hours (int): A optional number of past actual forecast hours that should be retrieved.
            force (bool): A forced update, which does not update the internal API use counter.

        Returns:
            tuple[DataCallStatus, str]: A flag indicating success, failure or abort, and a reason for failure.
        """
        failure = False

        try:
            last_day = self.get_day_start_utc(future=self.advanced_options[ADVANCED_FORECAST_FUTURE_DAYS])
            hours = math.ceil((last_day - self.get_now_utc()).total_seconds() / 3600)
            _LOGGER.debug(
                "Polling API for site %s, last day %s, %d hours",
                site,
                last_day.strftime("%Y-%m-%d"),
                hours,
            )

            new_data: list[dict[str, Any]] = []

            # Fetch past data. (Run once, for a new install or if the solcast.json file is deleted. This will use up api call quota.)

            if do_past_hours > 0:
                act_response: dict[str, Any] | None
                try:
                    self.tasks[TASK_FORECASTS_FETCH] = asyncio.create_task(
                        self.fetch_data(
                            hours=do_past_hours,
                            path=ESTIMATED_ACTUALS,
                            site=site,
                            api_key=api_key,
                            force=force,
                        )
                    )
                    await self.tasks[TASK_FORECASTS_FETCH]
                finally:
                    act_response = (
                        self.tasks.pop(TASK_FORECASTS_FETCH).result() if self.tasks.get(TASK_FORECASTS_FETCH) is not None else None
                    )
                if not isinstance(act_response, dict):
                    failure = True
                    _LOGGER.error(
                        "No valid data was returned for estimated_actuals so this will cause issues (API limit may be exhausted, or Solcast might have a problem)"
                    )
                    _LOGGER.error("API did not return a json object, returned `%s`", act_response)
                    return DataCallStatus.FAIL, "No valid json returned"

                estimate_actuals: list[dict[str, Any]] = act_response.get(ESTIMATED_ACTUALS, [])

                oldest = (dt.now(self._tz).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6)).astimezone(datetime.UTC)

                actuals: dict[dt, Any] = {}
                for estimate_actual in estimate_actuals:
                    period_start = dt.fromisoformat(estimate_actual[PERIOD_END]).astimezone(datetime.UTC).replace(
                        second=0, microsecond=0
                    ) - timedelta(minutes=30)
                    if period_start > oldest:
                        new_data.append(
                            {
                                PERIOD_START: period_start,
                                ESTIMATE: estimate_actual[ESTIMATE],
                                ESTIMATE10: 0,
                                ESTIMATE90: 0,
                            }
                        )
                for actual in new_data:
                    period_start = actual[PERIOD_START]

                    # Add or update the new entries.
                    forecast_entry_update(
                        actuals,
                        period_start,
                        round(actual[ESTIMATE], 4),
                    )

                await self.sort_and_prune(site, self._data_actuals, self.advanced_options[ADVANCED_HISTORY_MAX_DAYS], actuals)

                self._data_actuals[LAST_UPDATED] = dt.now(datetime.UTC).replace(microsecond=0)
                self._data_actuals[LAST_ATTEMPT] = dt.now(datetime.UTC).replace(microsecond=0)

            # Fetch latest data.

            response: dict[str, Any] | None = None
            if self.tasks.get(TASK_FORECASTS_FETCH) is not None:
                _LOGGER.warning("A fetch task is already running, so aborting forecast update")
                return DataCallStatus.ABORT, "Fetch already running"
            try:
                self.tasks[TASK_FORECASTS_FETCH] = asyncio.create_task(
                    self.fetch_data(
                        hours=hours,
                        path=FORECASTS,
                        site=site,
                        api_key=api_key,
                        force=force,
                    )
                )
                await self.tasks[TASK_FORECASTS_FETCH]
            finally:
                response = self.tasks.pop(TASK_FORECASTS_FETCH).result() if self.tasks.get(TASK_FORECASTS_FETCH) is not None else None
            if response is None:
                _LOGGER.error("No data was returned for forecasts")

            if not isinstance(response, dict):
                failure = True
                _LOGGER.error("API did not return a json object. Returned %s", response)
                return DataCallStatus.FAIL, "No valid json returned"

            latest_forecasts = response.get(FORECASTS, [])

            _LOGGER.debug("%d records returned", len(latest_forecasts))

            for forecast in latest_forecasts:
                period_start = dt.fromisoformat(forecast[PERIOD_END]).astimezone(datetime.UTC).replace(second=0, microsecond=0) - timedelta(
                    minutes=30
                )
                if period_start < last_day:
                    new_data.append(
                        {
                            PERIOD_START: period_start,
                            ESTIMATE: forecast[ESTIMATE],
                            ESTIMATE10: forecast[ESTIMATE10],
                            ESTIMATE90: forecast[ESTIMATE90],
                        }
                    )

            # Add or update forecasts with the latest data.

            # Load the forecast history.
            try:
                forecasts_undampened = {forecast[PERIOD_START]: forecast for forecast in self._data_undampened[SITE_INFO][site][FORECASTS]}
            except:  # noqa: E722
                forecasts_undampened = {}

            # Add new data to the undampened forecasts.
            for forecast in new_data:
                period_start = forecast[PERIOD_START]
                forecast_entry_update(
                    forecasts_undampened,
                    period_start,
                    round(forecast[ESTIMATE], 4),
                    round(forecast[ESTIMATE10], 4),
                    round(forecast[ESTIMATE90], 4),
                )

            await self.sort_and_prune(site, self._data_undampened, 14, forecasts_undampened)
        finally:
            issue_registry = ir.async_get(self.hass)
            if (
                failure
                and (
                    self._data_undampened[SITE_INFO].get(site) is None
                    or self._data_undampened[SITE_INFO][site][FORECASTS][0][PERIOD_START] > dt.now(datetime.UTC) - timedelta(hours=1)
                )
                and issue_registry.async_get_issue(DOMAIN, ISSUE_RECORDS_MISSING_INITIAL) is None
            ):
                _LOGGER.warning("Raise issue `%s` for missing forecast data", ISSUE_RECORDS_MISSING_INITIAL)
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    ISSUE_RECORDS_MISSING_INITIAL,
                    is_fixable=False,
                    is_persistent=True,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key=ISSUE_RECORDS_MISSING_INITIAL,
                    learn_more_url=LEARN_MORE_MISSING_FORECAST_DATA,
                )

        return DataCallStatus.SUCCESS, ""

    async def _sleep(self, delay: int):
        """Sleep for a specified number of seconds."""

        for _ in range(delay * 10):
            await asyncio.sleep(0.1)

    def increment_failure_count(self):
        """Increment all three failure counters."""
        self._data[FAILURE][LAST_24H] += 1
        self._data[FAILURE][LAST_7D][0] = self._data[FAILURE][LAST_24H]
        self._data[FAILURE][LAST_14D][0] = self._data[FAILURE][LAST_24H]

    async def async_get_automation_entity_id_by_name(self, name: str) -> str | None:
        """Return the first automation entity_id whose friendly_name matches name."""
        entity_id = None
        for state in self.hass.states.async_all("automation"):
            if state.attributes.get("friendly_name") == name:
                entity_id = state.entity_id
        return entity_id

    async def async_trigger_automation_by_name(self, name: str) -> bool:
        """Trigger an automation by friendly name; returns True if found and triggered."""
        success = False
        entity_id = await self.async_get_automation_entity_id_by_name(name)
        if entity_id:
            await self.hass.services.async_call("automation", "trigger", {ATTR_ENTITY_ID: entity_id}, blocking=True)
            success = True
        return success

    async def fetch_data(  # noqa: C901
        self,
        hours: int = 0,
        path: str = "error",
        site: str | None = None,
        api_key: str | None = None,
        force: bool = False,
    ) -> dict[str, Any] | str | None:
        """Fetch forecast data.

        Arguments:
            hours (int): Number of hours to fetch, normally 168, or seven days.
            path (str): The path to follow. FORECASTS or ESTIMATED_ACTUALS. Omitting this parameter will result in an error.
            site (str): A Solcast site ID.
            api_key (str): A Solcast API key appropriate to use for the site.
            force (bool): A forced update, which does not update the internal API use counter.

        Returns:
            dict[str, Any] | str | None: Raw forecast data points, the response text, or None if unsuccessful.
        """
        response_text = ""
        received_429: int = 0

        try:
            if api_key is not None and site is not None:
                # One site is fetched, and retries ensure that the site is actually fetched.
                # Occasionally the Solcast API is busy, and returns a 429 status, which is a
                # request to try again later. (It could also indicate that the API limit for
                # the day has been exceeded, and this is catered for by examining additional
                # status.)

                # The retry mechanism is a "back-off", where the interval between attempted
                # fetches is increased each time. All attempts possible span a maximum of
                # fifteen minutes, and this is also the timeout limit set for the entire
                # async operation.

                start_time = time.time()

                async with asyncio.timeout(900):
                    issue_registry = ir.async_get(self.hass)

                    if self._api_used[api_key] < self._api_limit[api_key] or force:
                        url = f"{self.advanced_options[ADVANCED_SOLCAST_URL]}/rooftop_sites/{site}/{path}"
                        params: dict[str, str | int] = {FORMAT: JSON, API_KEY: api_key, HOURS: hours}

                        tries = 10
                        counter = 0
                        backoff = 15  # On every retry the back-off increases by (at least) fifteen seconds more than the previous back-off.
                        while True:
                            _LOGGER.debug("Fetching path %s", path)
                            counter += 1
                            response_text = ""
                            try:
                                response: ClientResponse = await self._aiohttp_session.get(
                                    url=url, params=params, headers=self.headers, ssl=False
                                )
                                _LOGGER.debug("Fetch data url %s", redact_msg_api_key(str(response.url), api_key))
                                status = response.status
                                if status == 200:
                                    response_text = await response.text()
                            except TimeoutError:
                                _LOGGER.error("Connection error: Timed out connecting to server")
                                status = 1000
                                self.increment_failure_count()
                                break
                            except ConnectionRefusedError as e:
                                _LOGGER.error("Connection error, connection refused: %s", e)
                                status = 1000
                                self.increment_failure_count()
                                break
                            except (ClientConnectionError, ClientResponseError) as e:
                                _LOGGER.error("Client error: %s", e)
                                status = 1000
                                self.increment_failure_count()
                                break
                            if status in (200, 400, 401, 403, 404, 500):  # Do not retry for these statuses.
                                if status != 200:
                                    self.increment_failure_count()
                                break
                            if status == 429:
                                self.increment_failure_count()
                                # Test for API limit exceeded.
                                # {"response_status":{"error_code":"TooManyRequests","message":"You have exceeded your free daily limit.","errors":[]}}
                                response_json = await response.json(content_type=None)
                                if response_json is not None:
                                    response_status = response_json.get(RESPONSE_STATUS)
                                    if response_status is not None:
                                        if response_status.get(ERROR_CODE) == "TooManyRequests":
                                            _LOGGER.debug("Set status to 998, API limit exceeded")
                                            status = 998
                                            self._api_used[api_key] = self._api_limit[api_key]
                                            await self.__serialise_usage(api_key)
                                            break
                                        status = 1000
                                        _LOGGER.warning("An unexpected error occurred: %s", response_status.get(MESSAGE))
                                        break
                                else:
                                    received_429 += 1
                            if counter >= tries:
                                _LOGGER.error("API was tried %d times, but all attempts failed", tries)
                                break
                            # Integration fetch is in a possibly recoverable state, so delay (15 seconds * counter),
                            # plus a random number of seconds between zero and 15.
                            delay: int = (counter * backoff) + random.randrange(0, 15)
                            _LOGGER.warning(
                                "Call status %s, pausing %d seconds before retry",
                                http_status_translate(status),
                                delay,
                            )
                            await self._sleep(delay)

                        if status == 200:
                            if not force:
                                _LOGGER.debug(
                                    "API returned data, API counter incremented from %d to %d",
                                    self._api_used[api_key],
                                    self._api_used[api_key] + 1,
                                )
                                self._api_used[api_key] += 1
                                await self.__serialise_usage(api_key)
                            else:
                                _LOGGER.debug("API returned data, using force fetch so not incrementing API counter")
                            response_json = response_text
                            response_json = json.loads(response_json)
                            if issue_registry.async_get_issue(DOMAIN, ISSUE_API_UNAVAILABLE) is not None:
                                _LOGGER.debug("Remove issue for %s", ISSUE_API_UNAVAILABLE)
                                ir.async_delete_issue(self.hass, DOMAIN, ISSUE_API_UNAVAILABLE)
                                if (trigger := self.advanced_options[ADVANCED_TRIGGER_ON_API_AVAILABLE]) and trigger:
                                    await self.async_trigger_automation_by_name(trigger)
                            _LOGGER.debug(
                                "Task fetch_data took %.3f seconds",
                                time.time() - start_time,
                            )
                            return response_json
                        elif status in (400, 404):  # noqa: RET505
                            _LOGGER.error("Unexpected error getting sites, status %s returned", http_status_translate(status))
                        elif status == 403:  # Forbidden.
                            _LOGGER.error("API key %s is forbidden, re-authentication required", redact_api_key(api_key))
                            self.reauth_required = True
                        elif status == 998:  # Exceeded API limit.
                            _LOGGER.error(
                                "API allowed polling limit has been exceeded, API counter set to %d/%d",
                                self._api_used[api_key],
                                self._api_limit[api_key],
                            )
                        elif status == 1000:  # Unexpected response.
                            _LOGGER.error("Unexpected response received")
                        else:  # Other, or unknown status.
                            _LOGGER.error(
                                "Call status %s, API used is %d/%d",
                                http_status_translate(status),
                                self._api_used[api_key],
                                self._api_limit[api_key],
                            )
                            _LOGGER.debug("HTTP session status %s", http_status_translate(status))

                            if received_429 == tries and issue_registry.async_get_issue(DOMAIN, ISSUE_API_UNAVAILABLE) is None:
                                _LOGGER.debug("Raise issue for %s", ISSUE_API_UNAVAILABLE)
                                ir.async_create_issue(
                                    self.hass,
                                    DOMAIN,
                                    ISSUE_API_UNAVAILABLE,
                                    is_fixable=False,
                                    severity=ir.IssueSeverity.WARNING,
                                    translation_key=ISSUE_API_UNAVAILABLE,
                                    learn_more_url=LEARN_MORE_MISSING_FORECAST_DATA,
                                )
                                if (trigger := self.advanced_options[ADVANCED_TRIGGER_ON_API_UNAVAILABLE]) and trigger:
                                    await self.async_trigger_automation_by_name(trigger)

                    else:
                        _LOGGER.warning(
                            "API polling limit exhausted, not getting forecast for site %s, API used is %d/%d",
                            site,
                            self._api_used[api_key],
                            self._api_limit[api_key],
                        )
                        return None

        except asyncio.exceptions.CancelledError:
            _LOGGER.info("Fetch cancelled")
        except json.decoder.JSONDecodeError:
            return response_text

        return None

    def __make_energy_dict(self) -> dict[str, dict[str, float]]:
        """Make a Home Assistant Energy dashboard compatible dictionary.

        Returns:
            dict[str, dict[str, float]]: An Energy dashboard compatible data structure.
        """
        if self.options.use_actuals == HistoryType.FORECASTS:
            return {
                "wh_hours": OrderedDict(
                    sorted(
                        {
                            forecast[PERIOD_START].isoformat(): round(forecast[self._use_forecast_confidence] * 500, 0)
                            for index, forecast in enumerate(self._data_forecasts)
                            if index > 1
                            and index < len(self._data_forecasts) - 2
                            and (
                                forecast[self._use_forecast_confidence] > 0
                                or self._data_forecasts[index - 1][self._use_forecast_confidence] > 0
                                or self._data_forecasts[index + 1][self._use_forecast_confidence] > 0
                                or (
                                    forecast[PERIOD_START].minute == 30
                                    and self._data_forecasts[index - 2][self._use_forecast_confidence] > 0.2
                                )
                                or (
                                    forecast[PERIOD_START].minute == 30
                                    and self._data_forecasts[index + 2][self._use_forecast_confidence] > 0.2
                                )
                            )
                        }.items()
                    )
                )
            }

        # Show estimated actuals on Energy dashboard, so combine past estimated actuals with forecast start of today onwards
        _data = (
            self._data_estimated_actuals
            if self.options.use_actuals == HistoryType.ESTIMATED_ACTUALS
            else self._data_estimated_actuals_dampened
        )
        forecasts_start, _ = self.__get_list_slice(self._data_forecasts, self.get_day_start_utc(), search_past=True)
        actuals_start, actuals_end = self.__get_list_slice(
            _data,
            self.get_day_start_utc() - timedelta(days=self.advanced_options[ADVANCED_HISTORY_MAX_DAYS]),
            self.get_day_start_utc(),
            search_past=True,
        )
        return {
            "wh_hours": OrderedDict(
                sorted(
                    (
                        {
                            actual[PERIOD_START].isoformat(): round(actual[ESTIMATE] * 500, 0)
                            for index, actual in enumerate(_data)
                            if index > actuals_start + 1
                            and index < actuals_end - 2
                            and (
                                actual[ESTIMATE] > 0
                                or _data[index - 1][ESTIMATE] > 0
                                or _data[index + 1][ESTIMATE] > 0
                                or (actual[PERIOD_START].minute == 30 and _data[index - 2][ESTIMATE] > 0.2)
                                or (actual[PERIOD_START].minute == 30 and _data[index + 2][ESTIMATE] > 0.2)
                            )
                        }
                        | {
                            forecast[PERIOD_START].isoformat(): round(forecast[self._use_forecast_confidence] * 500, 0)
                            for index, forecast in enumerate(self._data_forecasts)
                            if index >= forecasts_start
                            and index < len(self._data_forecasts) - 2
                            and (
                                forecast[ESTIMATE] > 0
                                or self._data_forecasts[index - 1][ESTIMATE] > 0
                                or self._data_forecasts[index + 1][ESTIMATE] > 0
                                or (forecast[PERIOD_START].minute == 30 and self._data_forecasts[index - 2][ESTIMATE] > 0.2)
                                or (forecast[PERIOD_START].minute == 30 and self._data_forecasts[index + 2][ESTIMATE] > 0.2)
                            )
                        }
                    ).items()
                )
            )
        }

    def __site_api_key(self, site: str) -> str | None:
        api_key: str | None = None
        for _site in self.sites:
            if _site[RESOURCE_ID] == site:
                api_key = _site[API_KEY]
                break
        return api_key

    def hard_limit_set(self) -> tuple[bool, bool]:
        """Determine whether a hard limit is set.

        Returns:
            tuple[bool, bool]: Flags indicating whether a hard limit is set, and whether multiple keys are in use.
        """
        limit_set = False
        hard_limit = self.hard_limit.split(",")
        multi_key = len(hard_limit) > 1
        for limit in hard_limit:
            if limit != "100.0":
                limit_set = True
                break
        return limit_set, multi_key

    def __hard_limit_for_key(self, api_key: str) -> float:
        hard_limit = self.hard_limit.split(",")
        limit = 100.0
        if len(hard_limit) == 1:
            limit = float(hard_limit[0])
        else:
            for index, key in enumerate(self.options.api_key.split(",")):
                if key == api_key:
                    limit = float(hard_limit[index])
                    break
        return limit

    async def __build_hard_limit(
        self,
        data: dict[str, Any],
        sites_hard_limit: defaultdict[str, dict[str, dict[dt, Any]]],
        logged_hard_limit: list[str],
        estimates: tuple[str, ...],
        data_set: str = UNKNOWN,
    ) -> bool:
        """Build per-site hard limit.

        The API key hard limit for each site is calculated as proportion of the site contribution for the account.
        """

        EARLIEST_PERIOD = "earliest_period"
        LAST_PERIOD = "last_period"

        start_time = time.time()
        build_logged: list[str] = []

        hard_limit_set, multi_key = self.hard_limit_set()
        if hard_limit_set:
            api_key_sites: defaultdict[str, Any] = defaultdict(dict)
            for site in self.sites:
                if data[SITE_INFO].get(site[RESOURCE_ID]) is None:
                    continue
                api_key_sites[site[API_KEY] if multi_key else ALL][site[RESOURCE_ID]] = {
                    EARLIEST_PERIOD: data[SITE_INFO][site[RESOURCE_ID]][FORECASTS][0][PERIOD_START],
                    LAST_PERIOD: data[SITE_INFO][site[RESOURCE_ID]][FORECASTS][-1][PERIOD_START],
                }
            if data_set == DATA_SET_FORECAST:
                _LOGGER.debug("Hard limit for individual API keys %s (%s)", multi_key, data_set)
            for api_key, sites in api_key_sites.items():
                hard_limit = self.__hard_limit_for_key(api_key)
                _api_key = redact_api_key(api_key) if multi_key else ALL
                siteinfo = {site: {forecast[PERIOD_START]: forecast for forecast in data[SITE_INFO][site][FORECASTS]} for site in sites}
                earliest: dt = dt.now(self._tz)
                latest: dt = earliest
                for limits in sites.values():
                    if len(sites_hard_limit[api_key]) == 0:
                        msg = f"Build hard limit period values from scratch for {data_set} {_api_key}"
                        if msg not in build_logged:
                            build_logged.append(msg)
                            _LOGGER.debug(msg)
                        earliest = min(earliest, limits[EARLIEST_PERIOD])
                    else:
                        earliest = self.get_day_start_utc()  # Past hard limits done, so re-calculate from today onwards
                    latest = limits[LAST_PERIOD]
                if _api_key not in logged_hard_limit:
                    logged_hard_limit.append(_api_key)
                    _LOGGER.debug(
                        "Hard limit for API key %s is %s",
                        _api_key,
                        hard_limit,
                    )
                    _LOGGER.debug(
                        "Earliest period %s, latest period %s (%s)",
                        dt.strftime(earliest.astimezone(self._tz), DT_DATE_FORMAT),
                        dt.strftime(latest.astimezone(self._tz), DT_DATE_FORMAT),
                        data_set,
                    )
                periods: list[dt] = [earliest + timedelta(minutes=30 * x) for x in range(int((latest - earliest).total_seconds() / 1800))]
                sites_hard_limit[api_key] = {est: {} for est in estimates}
                for count, period in enumerate(periods):
                    for pv_estimate in estimates:
                        estimate = {site: siteinfo[site].get(period, {}).get(pv_estimate) for site in sites}
                        total_estimate = sum(estimate[site] for site in sites if estimate[site] is not None)
                        if total_estimate == 0:
                            continue
                        sites_hard_limit[api_key][pv_estimate][period] = {
                            site: estimate[site] / total_estimate * hard_limit for site in sites if estimate[site] is not None
                        }
                    # Prevent blocking
                    if count % 200 == 0:
                        await asyncio.sleep(0)
            _LOGGER.debug(
                "Build hard limit processing took %.3f seconds for %s",
                time.time() - start_time,
                data_set,
            )
        elif multi_key:
            for api_key in self.options.api_key.split(","):
                sites_hard_limit[api_key] = {est: {} for est in estimates}
        else:
            sites_hard_limit[ALL] = {est: {} for est in estimates}
        return multi_key

    async def build_actual_data(self) -> bool:
        """Build data structures needed, adjusting if setting a hard limit.

        Returns:
            bool: A flag indicating success or failure.
        """
        commencing: datetime.date = dt.now(self._tz).date() - timedelta(days=self.advanced_options[ADVANCED_HISTORY_MAX_DAYS])
        last_day: datetime.date = dt.now(self._tz).date()

        actuals: dict[dt, dict[str, dt | float]] = {}
        actuals_dampened: dict[dt, dict[str, dt | float]] = {}

        self._data_estimated_actuals = []
        self._data_estimated_actuals_dampened = []

        logged_hard_limit: list[str] = []

        build_success = True

        async def build_data_actuals(
            data: dict[str, Any],
            commencing: datetime.date,
            actuals: dict[dt, dict[str, dt | float]],
            sites_hard_limit: defaultdict[str, dict[str, dict[dt, Any]]],
            dampened: bool = False,
        ) -> list[Any]:
            nonlocal build_success

            api_key: str | None = None

            try:
                multi_key = await self.__build_hard_limit(
                    data,
                    sites_hard_limit,
                    logged_hard_limit,
                    (ESTIMATE,),
                    data_set=DATA_SET_ACTUALS if dampened else DATA_SET_ACTUALS_UNDAMPENED,
                )

                # Build total actuals with proportionate hard limit applied.
                for resource_id, siteinfo in data.get(SITE_INFO, {}).items():
                    api_key = self.__site_api_key(resource_id) if multi_key else ALL
                    site_actuals: dict[dt, dict[str, Any]] = {}

                    if api_key is not None:
                        for actual_count, actual in enumerate(siteinfo[FORECASTS]):
                            period_start = actual[PERIOD_START]
                            period_start_local = period_start.astimezone(self._tz)

                            if commencing < period_start_local.date() < last_day:
                                # Record the individual site actual.
                                site_actuals[period_start] = {
                                    PERIOD_START: period_start,
                                    ESTIMATE: min(
                                        actual[ESTIMATE],
                                        sites_hard_limit[api_key][ESTIMATE].get(period_start, {}).get(resource_id, 100),
                                    ),
                                }

                                # If the site is not excluded, add to the total.
                                if resource_id not in self.options.exclude_sites:
                                    extant: dict[str, Any] | None = actuals.get(period_start)
                                    if extant is not None:
                                        extant[ESTIMATE] = round(
                                            extant[ESTIMATE] + site_actuals[period_start][ESTIMATE],
                                            4,
                                        )
                                    else:
                                        actuals[period_start] = {
                                            PERIOD_START: period_start,
                                            ESTIMATE: round(site_actuals[period_start][ESTIMATE], 4),
                                        }

                            # Prevent blocking
                            if actual_count % 200 == 0:
                                await asyncio.sleep(0)

                        if not dampened:
                            _LOGGER.debug(
                                "Estimated actuals dictionary length for %s is %s",
                                resource_id,
                                len(data[SITE_INFO][resource_id][FORECASTS]),
                            )

                return sorted(actuals.values(), key=itemgetter(PERIOD_START))
            except Exception as e:  # noqa: BLE001
                _LOGGER.error("Exception in build_data_actuals(): %s: %s", e, traceback.format_exc())
                build_success = False
                return []

        start_time = time.time()
        self._data_estimated_actuals = await build_data_actuals(
            self._data_actuals, commencing, actuals, self._sites_actual_hard_limit_undampened
        )
        self._data_estimated_actuals_dampened = await build_data_actuals(
            self._data_actuals_dampened, commencing, actuals_dampened, self._sites_actual_hard_limit, dampened=True
        )
        _LOGGER.debug("Task build_data_actuals took %.3f seconds", time.time() - start_time)
        self._data_energy_dashboard = self.__make_energy_dict()

        return build_success

    async def build_forecast_data(self) -> bool:
        """Build data structures needed, adjusting if setting a hard limit.

        Returns:
            bool: A flag indicating success or failure.
        """
        TALLY = "tally"

        today: datetime.date = dt.now(self._tz).date()
        commencing: datetime.date = dt.now(self._tz).date() - timedelta(days=self.advanced_options[ADVANCED_HISTORY_MAX_DAYS])
        commencing_undampened: datetime.date = dt.now(self._tz).date() - timedelta(days=14)
        last_day: datetime.date = dt.now(self._tz).date() + timedelta(days=self.advanced_options[ADVANCED_FORECAST_FUTURE_DAYS])
        logged_hard_limit: list[str] = []

        forecasts: dict[dt, dict[str, dt | float]] = {}
        forecasts_undampened: dict[dt, dict[str, dt | float]] = {}

        build_success = True  # Be optimistic

        async def build_data(
            data: dict[str, Any],
            commencing: datetime.date,
            forecasts: dict[dt, dict[str, dt | float]],
            site_data_forecasts: dict[str, list[dict[str, dt | float]]],
            sites_hard_limit: defaultdict[str, dict[str, dict[dt, Any]]],
            dampened: bool = False,
        ):
            nonlocal build_success

            site = None
            tally: Any = None
            api_key: str | None = None

            try:
                multi_key = await self.__build_hard_limit(
                    data,
                    sites_hard_limit,
                    logged_hard_limit,
                    (ESTIMATE, ESTIMATE10, ESTIMATE90),
                    data_set=DATA_SET_FORECAST if dampened else DATA_SET_FORECAST_UNDAMPENED,
                )

                # Build per-site and total forecasts with proportionate hard limit applied.
                for resource_id, siteinfo in data.get(SITE_INFO, {}).items():
                    api_key = self.__site_api_key(resource_id) if multi_key else ALL
                    if dampened:
                        tally = None
                    site_forecasts: dict[dt, dict[str, dt | float]] = {}

                    if api_key is not None:
                        for forecast_count, forecast in enumerate(siteinfo[FORECASTS]):
                            period_start = forecast[PERIOD_START]
                            period_start_local = period_start.astimezone(self._tz)

                            if commencing < period_start_local.date() < last_day:
                                # Record the individual site forecast.
                                site_forecasts[period_start] = {
                                    PERIOD_START: period_start,
                                } | {
                                    est: round(
                                        min(
                                            forecast[est],
                                            sites_hard_limit[api_key][est].get(period_start, {}).get(resource_id, 100),
                                        ),
                                        4,
                                    )
                                    for est in [ESTIMATE, ESTIMATE10, ESTIMATE90]
                                }

                                if resource_id not in self.options.exclude_sites:
                                    # If the forecast is for today, and the site is not excluded, add to the total.
                                    if dampened and period_start_local.date() == today:
                                        if tally is None:
                                            tally = 0.0
                                        tally += (
                                            min(
                                                forecast[self._use_forecast_confidence],
                                                sites_hard_limit[api_key][self._use_forecast_confidence]
                                                .get(period_start, {})
                                                .get(resource_id, 100),
                                            )
                                            * 0.5
                                        )

                                    extant: dict[str, Any] | None = forecasts.get(period_start)
                                    if extant is not None:
                                        for est in [ESTIMATE, ESTIMATE10, ESTIMATE90]:
                                            extant[est] = round(
                                                extant[est] + site_forecasts[period_start][est],
                                                4,
                                            )
                                    else:
                                        forecasts[period_start] = {
                                            PERIOD_START: period_start,
                                        } | {est: site_forecasts[period_start][est] for est in (ESTIMATE, ESTIMATE10, ESTIMATE90)}
                                        if dampened and self.options.auto_dampen and period_start >= self.get_day_start_utc():
                                            forecasts[period_start][DAMPENING_FACTOR] = round(self._auto_dampening_factors[period_start], 4)

                            # Prevent blocking
                            if forecast_count % 200 == 0:
                                await asyncio.sleep(0)

                        site_data_forecasts[resource_id] = sorted(site_forecasts.values(), key=itemgetter(PERIOD_START))
                        if dampened:
                            rounded_tally: Any = round(tally, 4) if tally is not None else 0.0
                            if tally is not None:
                                siteinfo[TALLY] = rounded_tally
                            self._tally[resource_id] = rounded_tally
                            _LOGGER.debug(
                                "Forecasts dictionary length for %s is %s (%s un-dampened)",
                                resource_id,
                                len(forecasts),
                                len(self._data_undampened[SITE_INFO][resource_id][FORECASTS]),
                            )

                if dampened:
                    self._data_forecasts = sorted(forecasts.values(), key=itemgetter(PERIOD_START))
                else:
                    self._data_forecasts_undampened = sorted(forecasts.values(), key=itemgetter(PERIOD_START))
            except Exception as e:  # noqa: BLE001, handle all exceptions
                _LOGGER.error("Exception in build_data(): %s: %s", e, traceback.format_exc())
                self._data_forecasts = []
                self._data_forecasts_undampened = []
                if dampened:
                    for site in self.sites:
                        self._tally[site[RESOURCE_ID]] = None
                build_success = False

        start_time = time.time()
        await build_data(self._data, commencing, forecasts, self._site_data_forecasts, self._sites_hard_limit, dampened=True)
        if build_success:
            await build_data(
                self._data_undampened,
                commencing_undampened,
                forecasts_undampened,
                self._site_data_forecasts_undampened,
                self._sites_hard_limit_undampened,
            )
        _LOGGER.debug("Task build_data took %.3f seconds", time.time() - start_time)
        self._data_energy_dashboard = self.__make_energy_dict()

        await self.check_data_records()
        await self.recalculate_splines()
        return build_success

    def __calc_forecast_start_index(self, data: list[dict[str, Any]]) -> int:
        """Get the start of forecasts as-at just before midnight.

        Doesn't stop at midnight because some sensors may need the previous interval,
        and searches in reverse because less to iterate.

        Arguments:
            data (list): The data structure to search, either total data or site breakdown data.

        Returns:
            int: The starting index of the data structure just prior to midnight local time.
        """
        index = 0
        midnight_utc = self.get_day_start_utc()
        for index in range(len(data) - 1, -1, -1):
            if data[index][PERIOD_START] < midnight_utc:
                break
        return index

    async def check_data_records(self) -> None:
        """Log whether all records are present for each day."""

        CONTIGUOUS = "contiguous"
        CORRECT = "correct"
        INTERVALS = "intervals"
        EXPECTED_INTERVALS = "expected_intervals"

        contiguous: int = 0
        contiguous_start_date: Any = None
        contiguous_end_date: Any = None
        all_records_good = True
        time_transitioning = False
        interval_assessment: dict[datetime.date, Any] = {}

        # The latest period is used to determine whether any history should be updated on stale start.
        self.latest_period = self._data_forecasts[-1][PERIOD_START] if len(self._data_forecasts) > 0 else None

        for future_day in range(self.advanced_options[ADVANCED_FORECAST_FUTURE_DAYS]):
            start_utc = self.get_day_start_utc(future=future_day)
            end_utc = self.get_day_start_utc(future=future_day + 1)
            start_index, end_index = self.__get_list_slice(self._data_forecasts, start_utc, end_utc)

            expected_intervals = 48
            _is_dst: bool | None = (
                self.is_interval_dst(self._data_forecasts[start_index]) if start_index < len(self._data_forecasts) else None
            )
            for interval in range(start_index, min(len(self._data_forecasts), start_index + 8)):
                is_daylight = self.is_interval_dst(self._data_forecasts[interval])
                if is_daylight != _is_dst:
                    time_transitioning = True
                    expected_intervals = 50 if _is_dst else 46
                    break
            intervals = end_index - start_index
            forecasts_date = dt.now(self._tz).date() + timedelta(days=future_day)

            def set_assessment(forecasts_date: date, expected_intervals: int, intervals: int, contiguous: int, is_correct: bool) -> int:
                nonlocal all_records_good, contiguous_end_date
                interval_assessment[forecasts_date] = {
                    EXPECTED_INTERVALS: expected_intervals,
                    INTERVALS: intervals,
                    CORRECT: is_correct,
                }
                if is_correct:
                    if all_records_good:
                        contiguous += 1
                        contiguous_end_date = forecasts_date
                else:
                    all_records_good = False
                return contiguous

            if intervals == expected_intervals:
                contiguous = set_assessment(forecasts_date, expected_intervals, intervals, contiguous, True)
            else:
                contiguous = set_assessment(forecasts_date, expected_intervals, intervals, contiguous, False)
            if future_day == 0 and interval_assessment[forecasts_date][CORRECT]:
                contiguous_start_date = forecasts_date
        if time_transitioning:
            _LOGGER.debug("Transitioning between %s time", "standard/Summer" if str(self._tz) not in WINTER_TIME else "standard/Winter")
        if contiguous > 1:
            _LOGGER.debug(
                "Forecast data from %s to %s contains all intervals",
                contiguous_start_date.strftime("%Y-%m-%d"),
                contiguous_end_date.strftime("%Y-%m-%d"),
            )
        else:
            contiguous_end_date = None
        if contiguous < self.advanced_options[ADVANCED_FORECAST_FUTURE_DAYS]:
            for day, assessment in OrderedDict(sorted(interval_assessment.items(), key=lambda k: k[0])).items():
                if contiguous_end_date is not None and day <= contiguous_end_date:
                    continue
                match assessment[CORRECT]:
                    case True:
                        _LOGGER.debug(
                            "Forecast data for %s contains all intervals",
                            day.strftime("%Y-%m-%d"),
                        )
                    case _:
                        (_LOGGER.debug if contiguous == self.advanced_options[ADVANCED_FORECAST_FUTURE_DAYS] - 1 else _LOGGER.warning)(
                            "Forecast data for %s contains %d of %d intervals%s",
                            day.strftime("%Y-%m-%d"),
                            assessment[INTERVALS],
                            assessment[EXPECTED_INTERVALS],
                            ", which may be expected"
                            if contiguous == self.advanced_options[ADVANCED_FORECAST_FUTURE_DAYS] - 1
                            else ", so is missing forecast data",
                        )
        issue_registry = ir.async_get(self.hass)

        def _remove_issues():
            # Remove any relevant issues that may exist.
            for check_issue in (
                ISSUE_RECORDS_MISSING,
                ISSUE_RECORDS_MISSING_FIXABLE,
                ISSUE_RECORDS_MISSING_INITIAL,  # Raised elsewhere but cleaned up here
                ISSUE_RECORDS_MISSING_UNFIXABLE,
            ):
                if issue_registry.async_get_issue(DOMAIN, check_issue) is not None:
                    _LOGGER.debug("Remove issue for %s", check_issue)
                    ir.async_delete_issue(self.hass, DOMAIN, check_issue)

        if 0 < contiguous < self.advanced_options[ADVANCED_FORECAST_FUTURE_DAYS] - 1:
            if self.entry is not None:
                # If auto-update is enabled then raise an un-fixable issue, otherwise raise a fixable issue unless there have been failues seen.
                raise_issue: str | None = None
                if self.entry.options[AUTO_UPDATE] == AutoUpdate.NONE:
                    raise_issue = ISSUE_RECORDS_MISSING_UNFIXABLE if any(self._data[FAILURE][LAST_14D]) else ISSUE_RECORDS_MISSING_FIXABLE

                # If auto-update is enabled yet the prior forecast update was manual then do not raise an issue.
                raise_issue = None if self._data[AUTO_UPDATED] == 0 and self.entry.options[AUTO_UPDATE] != AutoUpdate.NONE else raise_issue
                if raise_issue is not None and issue_registry.async_get_issue(DOMAIN, raise_issue) is None:
                    _LOGGER.warning("Raise issue `%s` for missing forecast data", raise_issue)
                    ir.async_create_issue(
                        self.hass,
                        DOMAIN,
                        raise_issue,
                        is_fixable=self.entry.options[AUTO_UPDATE] == AutoUpdate.NONE and any(self._data[FAILURE][LAST_14D]) == 0,
                        data={CONTIGUOUS: contiguous, ENTRY_ID: self.entry.entry_id if self.entry is not None else ""},
                        severity=ir.IssueSeverity.WARNING,
                        translation_key=raise_issue,
                        learn_more_url=LEARN_MORE_MISSING_FORECAST_DATA,
                    )
                if not raise_issue:
                    _remove_issues()
        if contiguous >= self.advanced_options[ADVANCED_FORECAST_FUTURE_DAYS] - 1:
            # If data is all (or mostly) present then remove any relevant issues.
            _remove_issues()
