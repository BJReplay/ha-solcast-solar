"""Solcast sites, usage and cache management."""

# pylint: disable=pointless-string-statement

from __future__ import annotations

from collections import defaultdict
import contextlib
import copy
from datetime import UTC, datetime as dt, timedelta
import json
import logging
from pathlib import Path
import re
import traceback
from typing import TYPE_CHECKING, Any, Final

import aiofiles
from aiohttp import ClientConnectionError, ClientResponseError
from aiohttp.client_reqrep import ClientResponse

from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir

from .const import (
    ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_CONFIGURATION,
    ADVANCED_SOLCAST_URL,
    API_KEY,
    AUTO_UPDATED,
    DAILY_LIMIT,
    DAILY_LIMIT_CONSUMED,
    DISMISSAL,
    DOMAIN,
    DT_DATE_FORMAT,
    ENTRY_OPTIONS,
    EXCEPTION_INIT_CORRUPT,
    EXCEPTION_INIT_INCOMPATIBLE,
    EXTANT,
    FAILURE,
    FORECASTS,
    FORMAT,
    GENERATION,
    INTEGRATION_VERSION,
    ISSUE_UNUSUAL_AZIMUTH_NORTHERN,
    ISSUE_UNUSUAL_AZIMUTH_SOUTHERN,
    JSON,
    JSON_VERSION,
    LAST_7D,
    LAST_14D,
    LAST_24H,
    LAST_ATTEMPT,
    LAST_UPDATED,
    LEARN_MORE,
    LEARN_MORE_UNUSUAL_AZIMUTH,
    OLD_API_KEY,
    PERIOD_START,
    PROPOSAL,
    RESET,
    RESOURCE_ID,
    SITE,
    SITE_ATTRIBUTE_AZIMUTH,
    SITE_ATTRIBUTE_LATITUDE,
    SITE_ATTRIBUTE_LONGITUDE,
    SITE_INFO,
    SITES,
    SUCCESS,
    SUCCESS_FORCED,
    SUCCESS_TRACKED,
    TOTAL_RECORDS,
    UNKNOWN,
    VERSION,
)
from .util import (
    AutoUpdate,
    DateTimeEncoder,
    JSONDecoder,
    SchemaIncompatibleError,
    SitesStatus,
    SolcastApiStatus,
    UsageStatus,
    check_unusual_azimuth,
    clear_cache,
    http_status_translate,
    raise_and_record,
    redact_api_key,
    redact_lat_lon,
    redact_lat_lon_simple,
    redact_msg_api_key,
    upgrade_cache_schema,
)

if TYPE_CHECKING:
    from .solcastapi import SolcastApi

FRESH_DATA: Final[dict[str, Any]] = {
    SITE_INFO: {},
    LAST_UPDATED: dt.fromtimestamp(0, UTC),
    LAST_ATTEMPT: dt.fromtimestamp(0, UTC),
    AUTO_UPDATED: 0,
    FAILURE: {LAST_24H: 0, LAST_7D: [0] * 7, LAST_14D: [0] * 14},
    SUCCESS: {SUCCESS_TRACKED: {}, SUCCESS_FORCED: {}},
    INTEGRATION_VERSION: "",
    VERSION: JSON_VERSION,
}


_LOGGER = logging.getLogger(__name__)


class SitesCache:
    """Sites, usage and cache management."""

    def __init__(self, api: SolcastApi) -> None:
        """Initialise sites, usage and cache management.

        Arguments:
            api: The parent SolcastApi instance.
        """
        self.api = api

        # Private attributes (alphabetical).
        self._api_used_reset: dict[str, dt | None] = {}
        self._dismissal: dict[str, bool] = {}
        self._extant_sites: defaultdict[str, list[dict[str, Any]]] = defaultdict(list[dict[str, Any]])
        self._extant_usage: defaultdict[str, dict[str, Any]] = defaultdict(dict[str, Any])
        self._rekey: dict[str, Any] = {}
        self._site_latitude: defaultdict[str, dict[str, bool | float | int | None]] = defaultdict(dict[str, bool | float | int | None])

    # Properties (alphabetical).

    @property
    def multi_key(self) -> bool:
        """Whether multiple API keys are in use.

        Returns:
            bool: True for multiple API Solcast accounts configured. If configured then separate files will be used for caches.
        """
        return len(self.api.options.api_key.split(",")) > 1

    @property
    def stale_data(self) -> bool:
        """Whether the forecast was last updated some time ago (i.e. is stale).

        Returns:
            bool: True for stale, False if updated recently.
        """
        last_updated = self.api.last_updated
        return last_updated is not None and last_updated < self.api.dt_helper.day_start_utc(future=-1)

    @property
    def stale_usage_cache(self) -> bool:
        """Whether the usage cache was last reset over 24-hours ago (i.e. is stale).

        Returns:
            bool: True for stale, False if reset recently.
        """
        api_keys = self.api.options.api_key.split(",")
        for api_key in api_keys:
            api_key = api_key.strip()
            api_used_reset = self._api_used_reset.get(api_key)
            if api_used_reset is not None and api_used_reset < self.api.dt_helper.utc_previous_midnight():
                return True
        return False

    # Public methods (alphabetical).

    async def cleanup_issues(self, any_unusual: bool = True) -> None:
        """Check and clean up any existing issues if the conditions are now resolved."""
        issue_registry = ir.async_get(self.api.hass)
        for issue in [ISSUE_UNUSUAL_AZIMUTH_NORTHERN, ISSUE_UNUSUAL_AZIMUTH_SOUTHERN]:
            if (i := issue_registry.async_get_issue(DOMAIN, issue)) is not None:
                if (
                    i.dismissed_version is not None
                    and i.translation_placeholders is not None
                    and self._dismissal.get(i.translation_placeholders.get(SITE, ""), False)
                ) or not any_unusual:
                    _LOGGER.debug("Remove %sissue for %s", "ignored " if i.dismissed_version is not None else "", issue)
                    ir.async_delete_issue(self.api.hass, DOMAIN, issue)

    async def delete_solcast_file(self, *args: tuple[Any]) -> None:
        """Delete the solcast json files.

        Note: This will immediately trigger a forecast get with estimated actual history, so this
        is an integration reset.

        Arguments:
            args (tuple): Not used.
        """
        _LOGGER.debug("Action to delete old solcast json files")
        for filename in [self.api.filename, self.api.filename_undampened, self.api.filename_actuals, self.api.filename_actuals_dampened]:
            await clear_cache(filename)
        self.api.loaded_data = False
        await self.load_saved_data()

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
        issue_registry = ir.async_get(self.api.hass)

        def rename(file1: str, file2: str, api_key: str):
            if Path(file1).is_file():
                _LOGGER.info("Renaming %s to %s", redact_msg_api_key(file1, api_key), redact_msg_api_key(file2, api_key))
                Path(file1).rename(Path(file2))

        async def test_unusual_azimuth() -> None:
            """Test for unusual azimuth values."""
            _LOGGER.debug("Testing for unusual azimuth values")
            any_unusual = False
            any_raised = False
            old_sites = copy.deepcopy(self.api.sites)
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
                        unusual, raise_issue, proposal = check_unusual_azimuth(
                            v[SITE_ATTRIBUTE_LATITUDE],  # pyright: ignore[reportArgumentType]
                            azimuth,  # pyright: ignore[reportArgumentType]
                        )
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
                                self.api.hass,
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
                            for s in self.api.sites:
                                if s[RESOURCE_ID] == site:
                                    s[DISMISSAL] = True
                                    break
                        any_unusual = True

            await self.cleanup_issues(any_unusual)

            if self.api.sites != old_sites:
                # Sites have been updated with dismissables, so re-serialise the sites cache(s).
                for api_key in self.api.options.api_key.split(","):
                    api_key = api_key.strip()
                    cache_filename = self._get_sites_cache_filename(api_key)
                    for site in self.api.sites:
                        if site.get(API_KEY) == api_key:
                            break
                    _LOGGER.debug("Re-serialising sites cache for %s", redact_api_key(api_key))
                    payload = json.dumps({SITES: [site for site in self.api.sites if site.get(API_KEY) == api_key]}, ensure_ascii=False)
                    async with self.api.serialise_lock, aiofiles.open(cache_filename, "w") as file:
                        await file.write(payload)

        async def from_single_site_to_multi(api_keys: list[str]):
            """Transition from a single API key to multiple API keys."""
            single_sites = f"{self.api.config_dir}/solcast-sites.json"
            single_usage = f"{self.api.config_dir}/solcast-usage.json"
            if Path(single_sites).is_file():
                async with aiofiles.open(single_sites) as file:
                    single_api_key = json.loads(await file.read(), cls=JSONDecoder)[SITES][0].get(API_KEY, api_keys[0])
                multi_sites = f"{self.api.config_dir}/solcast-sites-{single_api_key}.json"
                if not Path(multi_sites).is_file() and Path(single_sites).is_file():
                    multi_usage = f"{self.api.config_dir}/solcast-usage-{single_api_key}.json"
                    rename(single_sites, multi_sites, single_api_key)
                    rename(single_usage, multi_usage, single_api_key)

        async def from_multi_site_to_single(api_keys: list[str]):
            """Transition from multiple API keys to a single API key."""
            single_sites = f"{self.api.config_dir}/solcast-sites.json"
            if not Path(single_sites).is_file():
                rename(f"{self.api.config_dir}/solcast-sites-{api_keys[0]}.json", single_sites, api_keys[0])
                rename(f"{self.api.config_dir}/solcast-usage-{api_keys[0]}.json", f"{self.api.config_dir}/solcast-usage.json", api_keys[0])

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
            sites = [str(sites) for sites in Path(self.api.config_dir).glob("solcast-sites*.json")]
            usage = [str(usage) for usage in Path(self.api.config_dir).glob("solcast-usage*.json")]
            return sorted(sites), sorted(usage)

        def list_multi_key_files() -> tuple[list[str], list[str]]:
            sites = [str(sites) for sites in Path(self.api.config_dir).glob("solcast-sites-*.json")]
            usage = [str(usage) for usage in Path(self.api.config_dir).glob("solcast-usage-*.json")]
            return sorted(sites), sorted(usage)

        async def load_extant_sites_and_usage(sites: list[str], usages: list[str]):
            extant_sites: dict[str, list[dict[str, Any]]] = defaultdict(list)
            extant_usage: dict[str, dict[str, Any]] = defaultdict(dict)
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
                            if not self.multi_key:
                                single_key = _site[API_KEY]
                        elif not self.multi_key:  # The key is unknown because old schema version
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
                    elif not self.multi_key and single_key:
                        extant_usage[single_key] = response_json
                    else:  # The key is unknown because old schema version
                        extant_usage[UNKNOWN] = response_json
            return extant_sites, extant_usage

        api_keys = [api_key.strip() for api_key in self.api.options.api_key.split(",")]
        if self.multi_key:
            await from_single_site_to_multi(api_keys)
        else:
            await from_multi_site_to_single(api_keys)
        multi_sites = [f"{self.api.config_dir}/solcast-sites-{api_key}.json" for api_key in api_keys]
        multi_usage = [f"{self.api.config_dir}/solcast-usage-{api_key}.json" for api_key in api_keys]

        all_sites, all_usage = await self.api.hass.async_add_executor_job(list_all_files)
        multi_key_sites, multi_key_usage = await self.api.hass.async_add_executor_job(list_multi_key_files)
        self._extant_sites, self._extant_usage = await load_extant_sites_and_usage(all_sites, all_usage)
        remove_orphans(multi_key_sites, multi_sites)
        remove_orphans(multi_key_usage, multi_usage)

        status, message, api_key_in_error = await self._sites_data(prior_crash=prior_crash, use_cache=use_cache)
        if self.api.sites_status == SitesStatus.OK:
            await test_unusual_azimuth()
            await self._sites_usage()

        return status, message, api_key_in_error

    async def load_saved_data(self) -> bool:  # noqa: C901
        """Load the saved solcast.json data.

        This also checks for new API keys and site removal.

        Returns:
            bool: True if data was loaded successfully, False otherwise.
        """

        file = ""
        try:
            if len(self.api.sites) > 0:

                async def load_data(filename: str, set_loaded: bool = True) -> dict[str, Any] | None:
                    nonlocal file

                    if Path(filename).is_file():
                        file = filename
                        async with aiofiles.open(filename) as data_file:
                            json_data: dict[str, Any] = json.loads(await data_file.read(), cls=JSONDecoder)
                            if not isinstance(json_data, dict):
                                _LOGGER.error("The %s cache appears corrupt", filename)
                                raise_and_record(self.api.hass, ConfigEntryNotReady, EXCEPTION_INIT_CORRUPT, {"file": file})
                            json_version = json_data.get(VERSION, 1)
                            _LOGGER.debug(
                                "Data cache %s exists, file type is %s",
                                filename,
                                type(json_data),
                            )
                            for site_id, site_data in json_data.get(SITE_INFO, {}).items():
                                bad = [f for f in site_data.get(FORECASTS, []) if PERIOD_START in f and not isinstance(f[PERIOD_START], dt)]
                                if bad:
                                    _LOGGER.warning(
                                        "Dropping %d entry(s) with non-datetime period_start for site %s in %s",
                                        len(bad),
                                        site_id,
                                        filename,
                                    )
                                    site_data[FORECASTS] = [
                                        f for f in site_data[FORECASTS] if not (PERIOD_START in f and not isinstance(f[PERIOD_START], dt))
                                    ]
                            data = json_data
                            if set_loaded:
                                self.api.loaded_data = True
                            log_file = {
                                self.api.filename: "Dampened",
                                self.api.filename_undampened: "Undampened",
                                self.api.filename_actuals: "Estimated actual",
                                self.api.filename_actuals_dampened: "Dampened estimated actual",
                            }
                            _LOGGER.debug("%s data loaded", log_file.get(filename, "Unknown"))
                            if json_version != JSON_VERSION:
                                _LOGGER.info(
                                    "Upgrading %s cache version from v%d to v%d",
                                    filename.lower(),
                                    json_version,
                                    JSON_VERSION,
                                )
                                current_version = json_version

                                first_site_id = self.api.sites[0][RESOURCE_ID] if len(self.api.sites) > 0 else None
                                try:
                                    json_version = upgrade_cache_schema(
                                        data,
                                        json_version,
                                        first_site_id,
                                        self.api.options.auto_update != AutoUpdate.NONE,
                                    )
                                except SchemaIncompatibleError:
                                    self.api.status = SolcastApiStatus.DATA_INCOMPATIBLE
                                    _LOGGER.critical("The %s appears incompatible, so cannot upgrade it", filename)
                                    raise_and_record(self.api.hass, ConfigEntryError, EXCEPTION_INIT_INCOMPATIBLE, {"file": file})

                                if json_version > current_version:
                                    await self.serialise_data(data, filename)
                        if self.api.status == SolcastApiStatus.UNKNOWN:
                            self.api.status = SolcastApiStatus.OK
                        return data
                    return None

                async def adds_moves_changes():
                    # Check for any new API keys so no sites data yet for those, and also for API key change.
                    serialise = False
                    reset_usage = False
                    new_sites: dict[str, str] = {}
                    cache_sites = list(self.api.data[SITE_INFO].keys())
                    old_api_keys = (
                        self.api.hass.data[DOMAIN].get(OLD_API_KEY, self.api.hass.data[DOMAIN][ENTRY_OPTIONS].get(API_KEY, "")).split(",")
                    )
                    for site in self.api.sites:
                        api_key = site[API_KEY]
                        site = site[RESOURCE_ID]
                        if site not in cache_sites or len(self.api.data[SITE_INFO][site].get(FORECASTS, [])) == 0:
                            new_sites[site] = api_key
                            if (
                                api_key not in old_api_keys
                            ):  # If a new site is seen in conjunction with an API key change then reset the usage.
                                reset_usage = True
                    with contextlib.suppress(Exception):
                        del self.api.hass.data[DOMAIN][OLD_API_KEY]

                    if reset_usage:
                        _LOGGER.info("An API key has changed with a new site added, resetting usage")
                        await self.reset_api_usage(force=True)

                    if len(new_sites.keys()) > 0:
                        # Some site data does not exist yet so get it.
                        # Do not alter self.api.data[LAST_ATTEMPT], as this is not a scheduled thing
                        _LOGGER.info("New site(s) have been added, so getting forecast data for them")
                        for site, api_key in new_sites.items():
                            await self.api.fetcher.http_data_call(site=site, api_key=api_key, do_past_hours=168)

                        _now = dt.now(UTC).replace(microsecond=0)
                        update: dict[str, Any] = {LAST_UPDATED: _now, LAST_ATTEMPT: _now, VERSION: JSON_VERSION}
                        self.api.data |= update
                        self.api.data_undampened |= update
                        self.api.data_actuals |= update
                        serialise = True

                        self.api.loaded_data = True

                    # Check for sites that need to be removed.
                    remove_sites: list[str] = []
                    configured_sites = [site[RESOURCE_ID] for site in self.api.sites]
                    for site in cache_sites:
                        if site not in configured_sites:
                            _LOGGER.warning(
                                "Site resource id %s is no longer configured, will remove saved data from %s, %s, %s, %s",
                                site,
                                self.api.filename,
                                self.api.filename_undampened,
                                self.api.filename_actuals,
                                self.api.filename_actuals_dampened,
                            )
                            remove_sites.append(site)

                    for site in remove_sites:
                        for data in [self.api.data, self.api.data_undampened, self.api.data_actuals]:
                            with contextlib.suppress(Exception):
                                del data[SITE_INFO][site]
                    if len(remove_sites) > 0:
                        serialise = True

                    if serialise:
                        await self.api.dampening.apply_forward()
                        for filename, data in {
                            self.api.filename: self.api.data,
                            self.api.filename_undampened: self.api.data_undampened,
                            self.api.filename_actuals: self.api.data_actuals,
                            self.api.filename_actuals_dampened: self.api.data_actuals,
                        }.items():
                            await self.serialise_data(data, filename)

                dampened_data = await load_data(self.api.filename)
                if dampened_data is not None:
                    self.api.data = dampened_data
                    # Load the un-dampened history
                    undampened_data = await load_data(self.api.filename_undampened, set_loaded=False)
                    if undampened_data is not None and self.api.status == SolcastApiStatus.OK:
                        self.api.data_undampened = undampened_data
                    # Load the estimated actuals history
                    actuals_data = await load_data(self.api.filename_actuals, set_loaded=False)
                    if actuals_data is not None and self.api.status == SolcastApiStatus.OK:
                        self.api.data_actuals = actuals_data
                    # Load the dampened estimated actuals history
                    actuals_dampened_data = await load_data(self.api.filename_actuals_dampened, set_loaded=False)
                    if actuals_dampened_data is not None and self.api.status == SolcastApiStatus.OK:
                        self.api.data_actuals_dampened = actuals_dampened_data
                    elif actuals_data:
                        self.api.data_actuals_dampened = actuals_data
                    # Load the generation history
                    file = self.api.filename_generation
                    generation_data = await self.api.dampening.load_generation_data()
                    if generation_data:
                        self.api.dampening.data_generation = generation_data

                    # if using adaptive dampening config load the data
                    if (
                        self.api.options.auto_dampen
                        and self.api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_CONFIGURATION]
                    ):
                        await self.api.dampening.adaptive.load_history()

                    # If configured to get generation but there is no cached data, then get it.
                    if (
                        self.api.options.auto_dampen
                        and self.api.options.generation_entities
                        and len(self.api.dampening.data_generation[GENERATION]) == 0
                    ):
                        await self.api.dampening.get_pv_generation()
                    # Check for sites changes.
                    await adds_moves_changes()
                    # Migrate un-dampened history data to the un-dampened cache if needed.
                    await self.api.dampening.migrate_undampened_history()
                else:
                    # There is no cached data, so start fresh.
                    self.api.data = copy.deepcopy(FRESH_DATA)
                    self.api.data_undampened = copy.deepcopy(FRESH_DATA)
                    self.api.data_actuals = copy.deepcopy(FRESH_DATA)
                    self.api.data_actuals_dampened = copy.deepcopy(FRESH_DATA)
                    self.api.loaded_data = False

                if not self.api.loaded_data:
                    # No file to load.
                    _LOGGER.warning("There is no solcast.json to load, so fetching solar forecast, including past forecasts")
                    # Could be a brand new install of the integration, or the file has been removed. Get the forecast and past actuals.
                    self.api.status_message = await self.api.fetcher.get_forecast_update(do_past_hours=168)
                    if self.api.status_message != "":
                        return False
                    self.api.loaded_data = True
                    for filename, data in {
                        self.api.filename: self.api.data,
                        self.api.filename_undampened: self.api.data_undampened,
                        self.api.filename_actuals: self.api.data_actuals,
                        self.api.filename_actuals_dampened: self.api.data_actuals_dampened,
                    }.items():
                        await self.serialise_data(data, filename)
        except json.decoder.JSONDecodeError:
            _LOGGER.error("The cached data in %s is corrupt in load_saved_data()", file)
            self.api.status = SolcastApiStatus.DATA_CORRUPT
            raise_and_record(self.api.hass, ConfigEntryNotReady, EXCEPTION_INIT_CORRUPT, {"file": file})
        return True

    async def reset_api_usage(self, force: bool = False) -> None:
        """Reset the daily API usage counter.

        Arguments:
            force (bool): Force the reset even if the cache is not stale.
        """
        if force or self.stale_usage_cache:
            _LOGGER.debug("Reset API usage")
            for api_key in self.api.api_used:
                self.api.api_used[api_key] = 0
                await self.serialise_usage(api_key, reset=True)
        else:
            _LOGGER.debug("Usage cache is fresh, so not resetting")

    async def reset_usage_cache(self):
        """Reset all usage caches."""
        api_keys = self.api.options.api_key.split(",")
        for api_key in api_keys:
            api_key = api_key.strip()
            self.api.api_used[api_key] = 0
            await self.serialise_usage(api_key, reset=True)

    async def serialise_data(self, data: dict[str, Any], filename: str) -> bool:
        """Serialise data to file.

        Arguments:
            data (dict): The data to serialise.
            filename (str): The name of the file

        Returns:
            bool: Success or failure.
        """
        if self.api.loaded_data and data[LAST_UPDATED] != dt.fromtimestamp(0, UTC):
            data[INTEGRATION_VERSION] = self.api.integration_version
            payload = json.dumps(data, ensure_ascii=False, cls=DateTimeEncoder)
            async with self.api.serialise_lock, aiofiles.open(filename, "w") as file:
                await file.write(payload)
            log_file = {
                self.api.filename: "dampened",
                self.api.filename_undampened: "undampened",
                self.api.filename_actuals: "estimated actual",
                self.api.filename_actuals_dampened: "dampened estimated actual",
                self.api.filename_generation: "generation",
            }
            _LOGGER.debug(
                "Saved %s cache",
                log_file.get(filename, UNKNOWN),
            )
            return True
        _LOGGER.warning("Not serialising empty data for %s", filename)
        return False

    async def serialise_usage(self, api_key: str, reset: bool = False) -> None:
        """Serialise the usage cache file.

        Arguments:
            api_key (str): An individual Solcast account API key.
            reset (bool): Whether to reset API key usage to zero.
        """
        filename = self._get_usage_cache_filename(api_key)
        if reset:
            self._api_used_reset[api_key] = self.api.dt_helper.utc_previous_midnight()
        _LOGGER.debug(
            "Writing API usage cache %s",
            redact_msg_api_key(filename, api_key),
        )
        json_content: dict[str, Any] = {
            DAILY_LIMIT: self.api.api_limits[api_key],
            DAILY_LIMIT_CONSUMED: self.api.api_used[api_key],
            RESET: self._api_used_reset[api_key],
        }
        payload = json.dumps(json_content, ensure_ascii=False, cls=DateTimeEncoder)
        async with self.api.serialise_lock, aiofiles.open(filename, "w") as file:
            await file.write(payload)

    # Private methods (alphabetical).

    def _get_sites_cache_filename(self, api_key: str) -> str:
        """Build a site details cache filename.

        Arguments:
            api_key (str): An individual Solcast account API key.

        Returns:
            str: A fully qualified cache filename using a simple name or separate files for more than one API key.
        """
        return f"{self.api.config_dir}/solcast-sites{'' if not self.multi_key else '-' + api_key}.json"

    def _get_usage_cache_filename(self, api_key: str) -> str:
        """Build an API cache filename.

        Arguments:
            api_key (str): An individual Solcast account API key.

        Returns:
            str: A fully qualified cache filename using a simple name or separate files for more than one API key.
        """
        return f"{self.api.config_dir}/solcast-usage{'' if not self.multi_key else '-' + api_key}.json"

    async def _sites_data(self, prior_crash: bool = False, use_cache: bool = True) -> tuple[int, str, str]:  # noqa: C901
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
            async with self.api.serialise_lock, aiofiles.open(cache_filename, "w") as file:
                await file.write(json.dumps(response_json, ensure_ascii=False))

        async def load_dismissals(cache_filename: str) -> None:
            _LOGGER.debug("Loading warning dismissals for %s", redact_api_key(api_key))
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
            self.api.sites = self.api.sites + sites_data[SITES]
            self._api_used_reset[api_key] = None
            _LOGGER.debug(
                "Sites loaded%s",
                (" for " + redact_api_key(api_key)) if self.multi_key else "",
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

        self.api.sites = []
        api_key_in_error = ""
        api_keys = self.api.options.api_key.split(",")

        try:
            for api_key in api_keys:
                response_json: dict[str, Any] = {}
                api_key = api_key.strip()
                cache_filename = self._get_sites_cache_filename(api_key)
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
                    url = f"{self.api.advanced_options[ADVANCED_SOLCAST_URL]}/rooftop_sites"
                    params = {FORMAT: JSON, API_KEY: api_key}
                    _LOGGER.debug("Connecting to %s?format=json&api_key=%s", url, redact_api_key(api_key))
                    response: ClientResponse = await self.api.aiohttp_session.get(
                        url=url, params=params, headers=self.api.headers, ssl=False
                    )
                    status = response.status
                    (_LOGGER.debug if status == 200 else _LOGGER.warning)(
                        "HTTP session returned status %s for API key %s%s",
                        http_status_translate(status),
                        redact_api_key(api_key),
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
                    if response_json.get(TOTAL_RECORDS, 0) > 0:
                        set_sites(response_json, api_key)
                        _ = check_rekey(response_json, api_key)
                        await save_cache(cache_filename, response_json)
                        success = True
                        self.api.sites_status = SitesStatus.OK
                    else:
                        _LOGGER.error(
                            "No sites for the API key %s are configured at solcast.com%s",
                            redact_api_key(api_key),
                            f" (did not find total records in response: {redact_msg_api_key(str(response_json), api_key)})"
                            if response_json.get(TOTAL_RECORDS) is None
                            else "",
                        )
                        cache_exists = False  # Prevent cache load if no sites
                        self.api.sites_status = SitesStatus.NO_SITES
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
                        self.api.sites_status = SitesStatus.OK
                        if status == 403:
                            self.api.sites_status = SitesStatus.BAD_KEY
                            break
                        status = 200
                        if not check_rekey(response_json, api_key):
                            self.api.sites_status = SitesStatus.CACHE_INVALID
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
                            self.api.sites_status = SitesStatus.BAD_KEY
                            break
                        if status in (429, 420):
                            self.api.sites_status = SitesStatus.API_BUSY
                            break
                        self.api.sites_status = SitesStatus.ERROR
                        api_key_in_error = redact_api_key(api_key)
                        break

                if status == 200 and success:
                    pass
                else:
                    cached_sites_unavailable(at_least_one_only=True)
        except (ClientConnectionError, ClientResponseError, ConnectionRefusedError, TimeoutError) as e:
            _LOGGER.error("Connection error: %s", e)
            self.api.sites_status = SitesStatus.ERROR
            api_key_in_error = ""
            _LOGGER.error("Error retrieving sites: %s", e)
            if use_cache:
                _LOGGER.info("Attempting to continue with cached sites")
                error = False
                self.api.sites = []
                for api_key in api_keys:
                    api_key = api_key.strip()
                    cache_filename = self._get_sites_cache_filename(api_key)
                    if Path(cache_filename).is_file():  # Cache exists, so load it
                        response_json = await load_cache(cache_filename)
                        set_sites(response_json, api_key)
                        _ = check_rekey(response_json, api_key)
                        self.api.sites_status = SitesStatus.OK
                    else:
                        self.api.sites_status = SitesStatus.ERROR
                        error = True
                        cached_sites_unavailable()
                        api_key_in_error = redact_api_key(api_key)
                        break
                if error:
                    _LOGGER.error(
                        "Suggestion: Check your overall HA configuration, specifically networking related (Is IPV6 an issue for you? DNS? Proxy?)"
                    )
            return (
                200 if self.api.sites_status == SitesStatus.OK else 999,
                "Cached sites loaded" if self.api.sites_status == SitesStatus.OK else "Cached sites not loaded",
                api_key_in_error,
            )
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Exception in _sites_data(): %s: %s", e, traceback.format_exc())
            return 999, f"Exception in _sites_data(): {e}", ""

        return status, http_status_translate(status), api_key_in_error

    async def _sites_usage(self) -> None:
        """Load api usage cache.

        The Solcast API for hobbyists is limited in the number of API calls that are
        allowed, and usage of this quota is tracked by the integration. There is not
        currently an API call to determine limit and usage, hence this tracking.

        The limit is specified by the user in integration configuration.
        """
        try:

            async def sanitise_and_set_usage(api_key: str, usage: dict[str, Any]):
                self.api.api_limits[api_key] = usage.get(DAILY_LIMIT, 10)
                assert isinstance(self.api.api_limits[api_key], int), "daily_limit is not an integer"
                self.api.api_used[api_key] = usage.get(DAILY_LIMIT_CONSUMED, 0)
                assert isinstance(self.api.api_used[api_key], int), "daily_limit_consumed is not an integer"
                self._api_used_reset[api_key] = usage.get(RESET, self.api.dt_helper.utc_previous_midnight())
                assert isinstance(self._api_used_reset[api_key], dt), "reset is not a datetime"
                if (used_reset := self._api_used_reset[api_key]) is not None:
                    _LOGGER.debug(
                        "Usage cache for %s last reset %s",
                        redact_api_key(api_key),
                        used_reset.astimezone(self.api.tz).strftime(DT_DATE_FORMAT),
                    )
                if usage[DAILY_LIMIT] != quota[api_key]:  # Limit has been adjusted, so rewrite the cache.
                    self.api.api_limits[api_key] = quota[api_key]
                    await self.serialise_usage(api_key)
                    _LOGGER.info("Usage loaded and cache updated with new limit")
                else:
                    _LOGGER.debug(
                        "Usage loaded%s",
                        (" for " + redact_api_key(api_key)) if self.multi_key else "",
                    )
                if used_reset is not None:
                    if self.api.dt_helper.real_now_utc() > used_reset + timedelta(hours=24):
                        _LOGGER.warning(
                            "Resetting usage for %s, last reset was more than 24-hours ago",
                            redact_api_key(api_key),
                        )
                        self.api.api_used[api_key] = 0
                        await self.serialise_usage(api_key, reset=True)

            self.api.usage_status = UsageStatus.OK
            api_keys = self.api.options.api_key.split(",")
            api_limit_values = self.api.options.api_limit.split(",")
            for index in range(len(api_keys)):  # If only one limit value is present, yet there are multiple sites then use the same limit.
                if len(api_limit_values) < index + 1:
                    api_limit_values.append(api_limit_values[index - 1])
            quota = {api_keys[index].strip(): int(api_limit_values[index].strip()) for index in range(len(api_limit_values))}

            for api_key in api_keys:
                api_key = api_key.strip()
                old_api_key = self._rekey.get(api_key)  # For a re-keyed API key.
                cache_filename = self._get_usage_cache_filename(api_key)
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
                        self.api.api_limits[api_key] = quota[api_key]
                        self.api.api_used[api_key] = 0
                        self._api_used_reset[api_key] = self.api.dt_helper.utc_previous_midnight()
                    await self.serialise_usage(api_key, reset=True)
                _LOGGER.debug(
                    "API counter for %s is %d/%d",
                    redact_api_key(api_key),
                    self.api.api_used[api_key],
                    self.api.api_limits[api_key],
                )

        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Exception in _sites_usage(): %s: %s", e, traceback.format_exc())
            self.api.usage_status = UsageStatus.ERROR
