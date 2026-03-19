"""Solcast API."""

# pylint: disable=pointless-string-statement

from __future__ import annotations

import asyncio
from collections import OrderedDict, defaultdict
import contextlib
import copy
from dataclasses import dataclass
from datetime import date, datetime as dt, timedelta, tzinfo
import logging
from operator import itemgetter
from pathlib import Path
import sys
import time
import traceback
from types import MappingProxyType
from typing import Any

from aiohttp import ClientSession

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .advanced import AdvancedOptions
from .const import (
    ADVANCED_FORECAST_FUTURE_DAYS,
    ADVANCED_HISTORY_MAX_DAYS,
    ALL,
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
    CUSTOM_HOURS,
    DAMPENING_FACTOR,
    DATA_SET_ACTUALS,
    DATA_SET_ACTUALS_UNDAMPENED,
    DATA_SET_FORECAST,
    DATA_SET_FORECAST_UNDAMPENED,
    DOMAIN,
    DT_DATE_FORMAT,
    DT_DATE_ONLY_FORMAT,
    ENTRY_ID,
    ESTIMATE,
    ESTIMATE10,
    ESTIMATE90,
    EXCLUDE_SITES,
    FAILURE,
    FILES,
    FORECASTS,
    GENERATION_ENTITIES,
    GET_ACTUALS,
    HARD_LIMIT_API,
    ISSUE_CORRUPT_FILE,
    ISSUE_RECORDS_MISSING,
    ISSUE_RECORDS_MISSING_FIXABLE,
    ISSUE_RECORDS_MISSING_INITIAL,
    ISSUE_RECORDS_MISSING_UNFIXABLE,
    KEY_ESTIMATE,
    LAST_7D,
    LAST_14D,
    LAST_24H,
    LAST_ATTEMPT,
    LAST_UPDATED,
    LEARN_MORE_CORRUPT_FILE,
    LEARN_MORE_MISSING_FORECAST_DATA,
    PERIOD_START,
    RESOURCE_ID,
    SITE_EXPORT_ENTITY,
    SITE_EXPORT_LIMIT,
    SITE_INFO,
    SUCCESS,
    SUCCESS_FORCED,
    UNKNOWN,
    USE_ACTUALS,
    WINTER_TIME,
)
from .dampen import Dampening
from .fetcher import Fetcher
from .forecast import ForecastQuery
from .sites_cache import FRESH_DATA, SitesCache
from .util import (
    AutoUpdate,
    DateTimeHelper,
    HistoryType,
    SitesStatus,
    SolcastApiStatus,
    UsageStatus,
    redact_api_key,
)

_LOGGER = logging.getLogger(__name__)

# Return the function name at a specified caller depth. 0=current, 1=caller, 2=caller of caller, etc.
FunctionName = lambda n=0: sys._getframe(n + 1).f_code.co_name  # noqa: E731, SLF001 # type: ignore[no-redef]


@dataclass
class ConnectionOptions:
    """Solcast options for the integration."""

    api_key: str
    api_limit: str
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

        # Public attributes.
        self.advanced_options: dict[str, Any] = {}
        self.aiohttp_session = aiohttp_session
        self.api_limits: dict[str, int] = {}
        self.api_used: dict[str, int] = {}
        self.auto_update_divisions: int = 0
        self.custom_hour_sensor: int = options.custom_hour_sensor
        self.damp: dict[str, float] = options.dampening
        self.data: dict[str, Any] = copy.deepcopy(FRESH_DATA)
        self.data_actuals: dict[str, Any] = copy.deepcopy(FRESH_DATA)
        self.data_actuals_dampened: dict[str, Any] = copy.deepcopy(FRESH_DATA)
        self.data_energy_dashboard: dict[str, Any] = {}
        self.data_estimated_actuals: list[dict[str, Any]] = []
        self.data_estimated_actuals_dampened: list[dict[str, Any]] = []
        self.data_forecasts: list[dict[str, Any]] = []
        self.data_forecasts_undampened: list[dict[str, Any]] = []
        self.data_undampened: dict[str, Any] = copy.deepcopy(FRESH_DATA)
        self.dt_helper = DateTimeHelper(options.tz)
        self.entry = entry
        self.entry_options: dict[str, Any] = {}
        if self.entry is not None:
            self.entry_options = {**self.entry.options}
        self.estimate_set: list[str] = self._get_estimate_set(options)
        self.extant_advanced_options: dict[str, Any] = {}
        self.hard_limit: str = options.hard_limit
        self.hass: HomeAssistant = hass
        self.headers: dict[str, str] = {}
        self.integration_version: str = ""
        self.latest_period: dt | None = None
        self.loaded_data = False
        self.options: ConnectionOptions = options
        self.peak_intervals: dict[int, float] = dict.fromkeys(range(48), -1.0)
        self.reauth_required: bool = False
        self.serialise_lock = asyncio.Lock()
        self.site_data_forecasts: dict[str, list[dict[str, Any]]] = {}
        self.site_data_forecasts_undampened: dict[str, list[dict[str, Any]]] = {}
        self.sites: list[dict[str, Any]] = []
        self.sites_status: SitesStatus = SitesStatus.UNKNOWN
        self.status: SolcastApiStatus = SolcastApiStatus.UNKNOWN
        self.status_message: str = ""
        self.suppress_advanced_watchdog_reload: bool = False
        self.tally: dict[str, float | None] = {}
        self.tasks: dict[str, Any] = {}
        self.tz = options.tz
        self.usage_status: UsageStatus = UsageStatus.UNKNOWN
        self.use_forecast_confidence = f"pv_{options.key_estimate}"

        # Private attributes.
        self._sites_actual_hard_limit: defaultdict[str, Any] = defaultdict(dict)
        self._sites_actual_hard_limit_undampened: defaultdict[str, Any] = defaultdict(dict)
        self._sites_hard_limit: defaultdict[str, Any] = defaultdict(dict)
        self._sites_hard_limit_undampened: defaultdict[str, Any] = defaultdict(dict)

        # Configuration directory and file paths.
        self.config_dir = f"{hass.config.config_dir}/{CONFIG_DISCRETE_NAME}" if CONFIG_FOLDER_DISCRETE else hass.config.config_dir
        (Path(self.config_dir).mkdir(parents=False, exist_ok=True)) if CONFIG_FOLDER_DISCRETE else None
        _LOGGER.debug("Configuration directory is %s", self.config_dir)

        file_path = Path(self.config_dir) / Path(options.file_path).name
        self.filename = f"{file_path}"
        self.filename_actuals = f"{file_path.parent / file_path.stem}-actuals{file_path.suffix}"
        self.filename_actuals_dampened = f"{file_path.parent / file_path.stem}-actuals-dampened{file_path.suffix}"
        self.filename_advanced = f"{file_path.parent / file_path.stem}-advanced{file_path.suffix}"
        self.filename_dampening = f"{file_path.parent / file_path.stem}-dampening{file_path.suffix}"
        self.filename_dampening_history = f"{file_path.parent / file_path.stem}-dampening-history{file_path.suffix}"
        self.filename_generation = f"{file_path.parent / file_path.stem}-generation{file_path.suffix}"
        self.filename_undampened = f"{file_path.parent / file_path.stem}-undampened{file_path.suffix}"

        # Child objects.
        self.advanced_opt = AdvancedOptions(self)
        self.dampening = Dampening(self)
        self.fetcher = Fetcher(self)
        self.query = ForecastQuery(self)
        self.sites_cache = SitesCache(self)

    def _migrate_config_files(self) -> list[str]:
        """Migrate config files to discrete folder if required."""

        source_path = Path(self.config_dir) / ".." if CONFIG_FOLDER_DISCRETE else Path(self.config_dir) / "solcast_solar"
        if source_path.exists():
            for file in source_path.glob("solcast*.json"):
                target_path = Path(self.config_dir) / file.name
                _LOGGER.info("Migrating config directory file %s to %s", file.resolve(), target_path)
                file.replace(target_path)

        unlinked: list[str] = []
        for file in Path(self.config_dir).glob("solcast*.json"):
            if file.stat().st_size == 0:
                _LOGGER.critical("Removing zero-length file %s", file.resolve())
                file.unlink()
                unlinked.append(str(file.name))
            else:
                _LOGGER.debug("File %s has length %d", file.resolve(), file.stat().st_size)

        with contextlib.suppress(OSError):
            ((Path(self.config_dir) / "solcast_solar").rmdir()) if not CONFIG_FOLDER_DISCRETE else None

        return unlinked

    async def async_migrate_config_files(self) -> None:
        """Migrate config files to discrete folder if required."""
        unlinked = await self.hass.async_add_executor_job(self._migrate_config_files)

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
            self.options.api_limit,
            self.options.host,
            self.options.file_path,
            self.options.tz,
            self.options.auto_update,
            # Options that can be dynamically set...
            self.damp,
            options[CUSTOM_HOURS],
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
        self.use_forecast_confidence = f"pv_{self.options.key_estimate}"
        self.estimate_set = self._get_estimate_set(self.options)

    def _get_estimate_set(self, options: ConnectionOptions) -> list[str]:
        estimate_set: list[str] = []
        if options.attr_brk_estimate:
            estimate_set.append(ESTIMATE)
        if options.attr_brk_estimate10:
            estimate_set.append(ESTIMATE10)
        if options.attr_brk_estimate90:
            estimate_set.append(ESTIMATE90)
        return estimate_set

    @property
    def dampening_enabled(self) -> bool:
        """Whether dampening is enabled.

        Returns:
            bool: Whether dampening is enabled.
        """
        return (
            self.options.auto_dampen
            or bool(self.dampening.factors)
            or (not self.options.auto_dampen and not self.dampening.factors and sum(self.options.dampening.values()) != 24)
        )

    @property
    def last_attempt(self) -> dt:
        """Date/time of last attempted forecast update.

        Returns:
            dt: The date/time of last attempt.
        """
        return self.data[LAST_ATTEMPT].replace(microsecond=0)

    @property
    def estimated_actuals_updated_today(self) -> bool:
        """Whether estimated actuals were updated today.

        Returns:
            bool: True if updated today, False otherwise.
        """
        return self.data_actuals[LAST_UPDATED].astimezone(self.tz).date() == dt.now(self.tz).date()

    @property
    def successes_forced_24h(self) -> int:
        """Number of successful forced updates today.

        Uses the maximum across all API keys.

        Returns:
            int: The maximum per-key count of successful forced site API calls since midnight.
        """
        forced = self.data[SUCCESS][SUCCESS_FORCED]
        return max(forced.values()) if forced else 0

    @property
    def failures_last_24h(self) -> int:
        """Number of failures in the last 24 hours.

        Returns:
            int: The number of failures in the last 24 hours.
        """
        return self.data[FAILURE][LAST_24H]

    @property
    def failures_last_7d(self) -> int:
        """Number of failures in the last 7 days.

        Returns:
            int: The number of failures in the last 7 days.
        """
        return sum(self.data[FAILURE][LAST_7D])

    @property
    def failures_last_14d(self) -> int:
        """Number of failures in the last 14 days.

        Returns:
            int: The number of failures in the last 14 days.
        """
        return sum(self.data[FAILURE][LAST_14D])

    @property
    def api_used_count(self) -> int:
        """API polling count for this UTC 24hr period (minimum of all API keys).

        A maximum is used because forecasts are polled at the same time for each configured API key. Should
        one API key fail but the other succeed then usage will be misaligned, so the highest usage of all
        API keys will apply.

        Returns:
            int: The tracked API usage count.
        """
        return max(list(self.api_used.values()))

    @property
    def api_limit(self) -> int:
        """API polling limit for this UTC 24hr period (minimum of all API keys).

        A minimum is used because forecasts are polled at the same time, so even if one API key has a
        higher limit that limit will never be reached.

        Returns:
            int: The lowest API limit of all configured API keys.
        """
        return min(list(self.api_limits.values()))

    @property
    def last_updated(self) -> dt | None:
        """When the data was last updated.

        Returns:
            dt | None: The last successful forecast fetch.
        """
        return self.data[LAST_UPDATED].astimezone(self.tz) if self.data.get(LAST_UPDATED) is not None else None

    def _site_api_key(self, site: str) -> str | None:
        api_key: str | None = None
        for _site in self.sites:
            if _site[RESOURCE_ID] == site:
                api_key = _site[CONF_API_KEY]
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

    def _hard_limit_for_key(self, api_key: str) -> float:
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

    async def _build_hard_limit(
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
                api_key_sites[site[CONF_API_KEY] if multi_key else ALL][site[RESOURCE_ID]] = {
                    EARLIEST_PERIOD: data[SITE_INFO][site[RESOURCE_ID]][FORECASTS][0][PERIOD_START],
                    LAST_PERIOD: data[SITE_INFO][site[RESOURCE_ID]][FORECASTS][-1][PERIOD_START],
                }
            if data_set == DATA_SET_FORECAST:
                _LOGGER.debug("Hard limit for individual API keys %s (%s)", multi_key, data_set)
            for api_key, sites in api_key_sites.items():
                hard_limit = self._hard_limit_for_key(api_key)
                _api_key = redact_api_key(api_key) if multi_key else ALL
                siteinfo = {site: {forecast[PERIOD_START]: forecast for forecast in data[SITE_INFO][site][FORECASTS]} for site in sites}
                earliest: dt = dt.now(self.tz)
                latest: dt = earliest
                for limits in sites.values():
                    if len(sites_hard_limit[api_key]) == 0:
                        msg = f"Build hard limit period values from scratch for {data_set} {_api_key}"
                        if msg not in build_logged:
                            build_logged.append(msg)
                            _LOGGER.debug(msg)
                        earliest = min(earliest, limits[EARLIEST_PERIOD])
                    else:
                        earliest = self.dt_helper.day_start_utc()  # Past hard limits done, so re-calculate from today onwards
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
                        dt.strftime(earliest.astimezone(self.tz), DT_DATE_FORMAT),
                        dt.strftime(latest.astimezone(self.tz), DT_DATE_FORMAT),
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
        commencing: date = dt.now(self.tz).date() - timedelta(days=self.advanced_options[ADVANCED_HISTORY_MAX_DAYS])
        last_day: date = dt.now(self.tz).date()

        actuals: dict[dt, dict[str, dt | float]] = {}
        actuals_dampened: dict[dt, dict[str, dt | float]] = {}

        self.data_estimated_actuals = []
        self.data_estimated_actuals_dampened = []

        logged_hard_limit: list[str] = []

        build_success = True

        async def build_data_actuals(
            data: dict[str, Any],
            commencing: date,
            actuals: dict[dt, dict[str, dt | float]],
            sites_hard_limit: defaultdict[str, dict[str, dict[dt, Any]]],
            dampened: bool = False,
        ) -> list[Any]:
            nonlocal build_success

            api_key: str | None = None

            try:
                multi_key = await self._build_hard_limit(
                    data,
                    sites_hard_limit,
                    logged_hard_limit,
                    (ESTIMATE,),
                    data_set=DATA_SET_ACTUALS if dampened else DATA_SET_ACTUALS_UNDAMPENED,
                )

                # Build total actuals with proportionate hard limit applied.
                for resource_id, siteinfo in data.get(SITE_INFO, {}).items():
                    api_key = self._site_api_key(resource_id) if multi_key else ALL
                    site_actuals: dict[dt, dict[str, Any]] = {}

                    if api_key is not None:
                        for actual_count, actual in enumerate(siteinfo[FORECASTS]):
                            period_start = actual[PERIOD_START]
                            period_start_local = period_start.astimezone(self.tz)

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
        self.data_estimated_actuals = await build_data_actuals(
            self.data_actuals, commencing, actuals, self._sites_actual_hard_limit_undampened
        )
        self.data_estimated_actuals_dampened = await build_data_actuals(
            self.data_actuals_dampened, commencing, actuals_dampened, self._sites_actual_hard_limit, dampened=True
        )
        _LOGGER.debug("Task build_data_actuals took %.3f seconds", time.time() - start_time)
        self.data_energy_dashboard = self.query.make_energy_dict()

        return build_success

    async def build_forecast_data(self) -> bool:
        """Build data structures needed, adjusting if setting a hard limit.

        Returns:
            bool: A flag indicating success or failure.
        """
        TALLY = "tally"

        today: date = dt.now(self.tz).date()
        commencing: date = dt.now(self.tz).date() - timedelta(days=self.advanced_options[ADVANCED_HISTORY_MAX_DAYS])
        commencing_undampened: date = dt.now(self.tz).date() - timedelta(days=14)
        last_day: date = dt.now(self.tz).date() + timedelta(days=self.advanced_options[ADVANCED_FORECAST_FUTURE_DAYS])
        logged_hard_limit: list[str] = []

        forecasts: dict[dt, dict[str, dt | float]] = {}
        forecasts_undampened: dict[dt, dict[str, dt | float]] = {}

        build_success = True  # Be optimistic

        async def build_data(
            data: dict[str, Any],
            commencing: date,
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
                multi_key = await self._build_hard_limit(
                    data,
                    sites_hard_limit,
                    logged_hard_limit,
                    (ESTIMATE, ESTIMATE10, ESTIMATE90),
                    data_set=DATA_SET_FORECAST if dampened else DATA_SET_FORECAST_UNDAMPENED,
                )

                # Build per-site and total forecasts with proportionate hard limit applied.
                for resource_id, siteinfo in data.get(SITE_INFO, {}).items():
                    api_key = self._site_api_key(resource_id) if multi_key else ALL
                    if dampened:
                        tally = None
                    site_forecasts: dict[dt, dict[str, dt | float]] = {}

                    if api_key is not None:
                        for forecast_count, forecast in enumerate(siteinfo[FORECASTS]):
                            period_start = forecast[PERIOD_START]
                            period_start_local = period_start.astimezone(self.tz)

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
                                                forecast[self.use_forecast_confidence],
                                                sites_hard_limit[api_key][self.use_forecast_confidence]
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
                                        if dampened and self.options.auto_dampen and period_start >= self.dt_helper.day_start_utc():
                                            forecasts[period_start][DAMPENING_FACTOR] = round(self.dampening.auto_factors[period_start], 4)

                            # Prevent blocking
                            if forecast_count % 200 == 0:
                                await asyncio.sleep(0)

                        site_data_forecasts[resource_id] = sorted(site_forecasts.values(), key=itemgetter(PERIOD_START))
                        if dampened:
                            rounded_tally: Any = round(tally, 4) if tally is not None else 0.0
                            if tally is not None:
                                siteinfo[TALLY] = rounded_tally
                            self.tally[resource_id] = rounded_tally
                            _LOGGER.debug(
                                "Forecasts dictionary length for %s is %s (%s un-dampened)",
                                resource_id,
                                len(forecasts),
                                len(self.data_undampened[SITE_INFO][resource_id][FORECASTS]),
                            )

                if dampened:
                    self.data_forecasts = sorted(forecasts.values(), key=itemgetter(PERIOD_START))
                else:
                    self.data_forecasts_undampened = sorted(forecasts.values(), key=itemgetter(PERIOD_START))
            except Exception as e:  # noqa: BLE001, handle all exceptions
                _LOGGER.error("Exception in build_data(): %s: %s", e, traceback.format_exc())
                self.data_forecasts = []
                self.data_forecasts_undampened = []
                if dampened:
                    for site in self.sites:
                        self.tally[site[RESOURCE_ID]] = None
                build_success = False

        start_time = time.time()
        await build_data(self.data, commencing, forecasts, self.site_data_forecasts, self._sites_hard_limit, dampened=True)
        if build_success:
            await build_data(
                self.data_undampened,
                commencing_undampened,
                forecasts_undampened,
                self.site_data_forecasts_undampened,
                self._sites_hard_limit_undampened,
            )
        _LOGGER.debug("Task build_data took %.3f seconds", time.time() - start_time)
        self.data_energy_dashboard = self.query.make_energy_dict()

        await self.check_data_records()
        await self.query.recalculate_splines()
        return build_success

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
        interval_assessment: dict[date, Any] = {}

        # The latest period is used to determine whether any history should be updated on stale start.
        self.latest_period = self.data_forecasts[-1][PERIOD_START] if len(self.data_forecasts) > 0 else None

        for future_day in range(self.advanced_options[ADVANCED_FORECAST_FUTURE_DAYS]):
            start_utc = self.dt_helper.day_start_utc(future=future_day)
            end_utc = self.dt_helper.day_start_utc(future=future_day + 1)
            start_index, end_index = self.query.get_list_slice(self.data_forecasts, start_utc, end_utc)

            expected_intervals = 48
            _is_dst: bool | None = (
                self.dt_helper.is_interval_dst(self.data_forecasts[start_index]) if start_index < len(self.data_forecasts) else None
            )
            for interval in range(start_index, min(len(self.data_forecasts), start_index + 8)):
                is_daylight = self.dt_helper.is_interval_dst(self.data_forecasts[interval])
                if is_daylight != _is_dst:
                    time_transitioning = True
                    expected_intervals = 50 if _is_dst else 46
                    break
            intervals = end_index - start_index
            forecasts_date = dt.now(self.tz).date() + timedelta(days=future_day)

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
            _LOGGER.debug("Transitioning between %s time", "standard/Summer" if str(self.tz) not in WINTER_TIME else "standard/Winter")
        if contiguous > 1:
            _LOGGER.debug(
                "Forecast data from %s to %s contains all intervals",
                contiguous_start_date.strftime(DT_DATE_ONLY_FORMAT),
                contiguous_end_date.strftime(DT_DATE_ONLY_FORMAT),
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
                            day.strftime(DT_DATE_ONLY_FORMAT),
                        )
                    case _:
                        (_LOGGER.debug if contiguous == self.advanced_options[ADVANCED_FORECAST_FUTURE_DAYS] - 1 else _LOGGER.warning)(
                            "Forecast data for %s contains %d of %d intervals%s",
                            day.strftime(DT_DATE_ONLY_FORMAT),
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
                    raise_issue = ISSUE_RECORDS_MISSING_UNFIXABLE if any(self.data[FAILURE][LAST_14D]) else ISSUE_RECORDS_MISSING_FIXABLE

                # If auto-update is enabled yet the prior forecast update was manual then do not raise an issue.
                raise_issue = None if self.data[AUTO_UPDATED] == 0 and self.entry.options[AUTO_UPDATE] != AutoUpdate.NONE else raise_issue
                if raise_issue is not None and issue_registry.async_get_issue(DOMAIN, raise_issue) is None:
                    _LOGGER.warning("Raise issue `%s` for missing forecast data", raise_issue)
                    ir.async_create_issue(
                        self.hass,
                        DOMAIN,
                        raise_issue,
                        is_fixable=self.entry.options[AUTO_UPDATE] == AutoUpdate.NONE and not any(self.data[FAILURE][LAST_14D]),
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
