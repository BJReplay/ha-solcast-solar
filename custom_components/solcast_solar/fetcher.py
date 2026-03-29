"""Solcast HTTP fetch and update orchestration."""

# pylint: disable=pointless-string-statement

from __future__ import annotations

import asyncio
import copy
from datetime import UTC, datetime as dt, timedelta
from hashlib import md5
import json
import logging
import math
from operator import itemgetter
import random
import time
from typing import TYPE_CHECKING, Any

from aiohttp import ClientConnectionError, ClientResponseError
from aiohttp.client_reqrep import ClientResponse

from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir

from .const import (
    ADVANCED_FORECAST_FUTURE_DAYS,
    ADVANCED_HISTORY_MAX_DAYS,
    ADVANCED_LOG_UPDATE_FAILURE_ONLY,
    ADVANCED_SOLCAST_URL,
    ADVANCED_TRIGGER_ON_API_AVAILABLE,
    ADVANCED_TRIGGER_ON_API_UNAVAILABLE,
    API_KEY,
    AUTO_UPDATED,
    DOMAIN,
    DT_DATE_ONLY_FORMAT,
    ERROR_CODE,
    ESTIMATE,
    ESTIMATE10,
    ESTIMATE90,
    ESTIMATED_ACTUALS,
    EXCEPTION_BUILD_FAILED_ACTUALS,
    EXCEPTION_BUILD_FAILED_FORECASTS,
    FAILURE,
    FORECASTS,
    FORMAT,
    HOURS,
    ISSUE_API_UNAVAILABLE,
    ISSUE_RECORDS_MISSING_INITIAL,
    JSON,
    LAST_7D,
    LAST_14D,
    LAST_24H,
    LAST_ATTEMPT,
    LAST_UPDATED,
    LEARN_MORE_MISSING_FORECAST_DATA,
    MESSAGE,
    PERIOD_END,
    PERIOD_START,
    RESOURCE_ID,
    RESPONSE_STATUS,
    SITE_INFO,
    SUCCESS,
    SUCCESS_FORCED,
    SUCCESS_TRACKED,
    TASK_ACTUALS_FETCH,
    TASK_FORECASTS_FETCH,
    UPDATE_BACKOFF,
    UPDATE_TRIES,
)
from .util import (
    AutoUpdate,
    DataCallStatus,
    SolcastApiStatus,
    UpdateOutcome,
    UpdateResult,
    async_trigger_automation_by_name,
    forecast_entry_update,
    http_status_translate,
    raise_and_record,
    redact_api_key,
    redact_msg_api_key,
)

if TYPE_CHECKING:
    from .solcastapi import SolcastApi

_LOGGER = logging.getLogger(__name__)


class Fetcher:
    """HTTP fetch and update orchestration."""

    def __init__(self, api: SolcastApi) -> None:
        """Initialise the fetch and update engine.

        Arguments:
            api: The parent SolcastApi instance.
        """
        self.api = api
        self._next_update: str | None = None

    async def build_forecast_and_actuals(self, raise_exc=False) -> bool:
        """Build the forecast and estimated actual data.

        Arguments:
            raise_exc (bool): Whether to raise exceptions on failure. Only set when the integration is starting up.

        Returns:
            bool: True if both forecast and actual data built successfully, False otherwise.
        """

        success = True
        if self.api.loaded_data:
            # Create an up-to-date forecast.
            if self.api.status == SolcastApiStatus.OK and not await self.api.build_forecast_data():
                self.api.status = SolcastApiStatus.BUILD_FAILED_FORECASTS
                success = False
                (_LOGGER.warning if self.api.advanced_options[ADVANCED_LOG_UPDATE_FAILURE_ONLY] else _LOGGER.error)(
                    "Failed to build forecast data"
                )
                if raise_exc:
                    raise_and_record(self.api.hass, ConfigEntryNotReady, EXCEPTION_BUILD_FAILED_FORECASTS)
            if self.api.status == SolcastApiStatus.OK and self.api.options.get_actuals and not await self.api.build_actual_data():
                self.api.status = SolcastApiStatus.BUILD_FAILED_ACTUALS
                success = False
                (_LOGGER.warning if self.api.advanced_options[ADVANCED_LOG_UPDATE_FAILURE_ONLY] else _LOGGER.error)(
                    "Failed to build estimated actuals data"
                )
                if raise_exc:
                    raise_and_record(self.api.hass, ConfigEntryNotReady, EXCEPTION_BUILD_FAILED_ACTUALS)
        return success

    async def reset_failure_stats(self) -> None:
        """Reset the failure statistics and the success counters."""

        _LOGGER.debug("Resetting failure statistics")
        self.api.data[FAILURE][LAST_24H] = 0
        self.api.data[FAILURE][LAST_7D] = [0, *self.api.data[FAILURE][LAST_7D][:-1]]
        self.api.data[FAILURE][LAST_14D] = [0, *self.api.data[FAILURE][LAST_14D][:-1]]
        self.api.data[SUCCESS][SUCCESS_TRACKED] = {}
        self.api.data[SUCCESS][SUCCESS_FORCED] = {}
        await self.api.sites_cache.serialise_data(self.api.data, self.api.filename)

    async def update_estimated_actuals(self, dampen_yesterday: bool = False) -> None:
        """Update estimated actuals."""

        status: DataCallStatus = DataCallStatus.SUCCESS
        reason: str = ""
        recovered_periods_by_site: dict[str, set[float]] = {}
        yesterday_start = self.api.dt_helper.day_start_utc(future=-1)

        start_time = time.time()

        for site in self.api.sites:
            _LOGGER.info("Getting estimated actuals update for site %s", site[RESOURCE_ID])
            api_key = site[API_KEY]

            new_data: list[dict[str, Any]] = []

            act_response: dict[str, Any] | None
            try:
                self.api.tasks[TASK_ACTUALS_FETCH] = asyncio.create_task(
                    self.fetch_data(
                        hours=168,
                        path=ESTIMATED_ACTUALS,
                        site=site[RESOURCE_ID],
                        api_key=api_key,
                        force=True,
                    )
                )
                await self.api.tasks[TASK_ACTUALS_FETCH]
            finally:
                act_response = (
                    self.api.tasks.pop(TASK_ACTUALS_FETCH).result() if self.api.tasks.get(TASK_ACTUALS_FETCH) is not None else None
                )
            if not isinstance(act_response, dict):
                _LOGGER.error("No valid data was returned for estimated_actuals so this may cause issues")
                _LOGGER.debug("API did not return a json object, returned `%s`", act_response)
                status = DataCallStatus.FAIL
                reason = "No valid json returned"
                break

            estimate_actuals: list[dict[str, Any]] = act_response.get(ESTIMATED_ACTUALS, [])
            dampened_periods = (
                {actual[PERIOD_START].timestamp() for actual in self.api.data_actuals_dampened[SITE_INFO][site[RESOURCE_ID]][FORECASTS]}
                if self.api.data_actuals_dampened[SITE_INFO].get(site[RESOURCE_ID])
                else set()
            )

            oldest = (dt.now(self.api.tz).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=7)).astimezone(UTC)

            for estimate_actual in estimate_actuals:
                period_start = dt.fromisoformat(estimate_actual[PERIOD_END]).astimezone(UTC).replace(second=0, microsecond=0) - timedelta(
                    minutes=30
                )
                if period_start > oldest:
                    new_data.append(
                        {
                            PERIOD_START: period_start,
                            ESTIMATE: estimate_actual[ESTIMATE],
                        }
                    )

            # Load the actuals history and add or update the new entries.
            actuals = (
                {actual[PERIOD_START]: actual for actual in self.api.data_actuals[SITE_INFO][site[RESOURCE_ID]][FORECASTS]}
                if self.api.data_actuals[SITE_INFO].get(site[RESOURCE_ID])
                else {}
            )
            for actual in new_data:
                forecast_entry_update(
                    actuals,
                    actual[PERIOD_START],
                    round(actual[ESTIMATE], 4),
                )
                period_start_key = actual[PERIOD_START].timestamp()
                if actual[PERIOD_START] < yesterday_start and period_start_key not in dampened_periods:
                    recovered_periods_by_site.setdefault(site[RESOURCE_ID], set()).add(period_start_key)

            await self.sort_and_prune(
                site[RESOURCE_ID], self.api.data_actuals, self.api.advanced_options[ADVANCED_HISTORY_MAX_DAYS], actuals
            )
            _LOGGER.debug("Estimated actuals dictionary for site %s length %s", site[RESOURCE_ID], len(actuals))
            self.increment_success_count(force=True, api_key=api_key)

        if status == DataCallStatus.SUCCESS and dampen_yesterday:
            # Backfill recovered historical actuals with the latest dampening factors if needed, then
            # apply normal yesterday dampening.
            await self.api.dampening.apply_recovered_history(recovered_periods_by_site)
            await self.api.dampening.apply_yesterday()

        if status != DataCallStatus.SUCCESS:
            (_LOGGER.warning if self.api.advanced_options[ADVANCED_LOG_UPDATE_FAILURE_ONLY] else _LOGGER.error)(
                "Update estimated actuals failed: %s", reason
            )
        else:
            self.api.data_actuals[LAST_UPDATED] = dt.now(UTC).replace(microsecond=0)
            self.api.data_actuals[LAST_ATTEMPT] = dt.now(UTC).replace(microsecond=0)
            await self.api.sites_cache.serialise_data(self.api.data_actuals, self.api.filename_actuals)
            self.api.data_actuals_dampened[LAST_UPDATED] = dt.now(UTC).replace(microsecond=0)
            self.api.data_actuals_dampened[LAST_ATTEMPT] = dt.now(UTC).replace(microsecond=0)
            await self.api.sites_cache.serialise_data(self.api.data_actuals_dampened, self.api.filename_actuals_dampened)
            await self.api.sites_cache.serialise_data(self.api.data, self.api.filename)

        _LOGGER.debug("Task update_estimated_actuals took %.3f seconds", time.time() - start_time)

    async def get_forecast_update(self, do_past_hours: int = 0, force: bool = False) -> UpdateResult:
        """Request forecast data for all sites.

        Arguments:
            do_past_hours (int): A optional number of past actual forecast hours that should be retrieved.
            force (bool): A forced update, which does not update the internal API use counter.

        Returns:
            UpdateResult: A typed outcome and a message.
        """
        last_attempt = dt.now(UTC)
        status = ""

        def next_update():
            if self._next_update is not None:
                return f", next auto update at {self._next_update}"
            return ""

        if last_updated := self.api.last_updated:
            if last_updated + timedelta(seconds=10) > dt.now(UTC):
                status = f"Not requesting a solar forecast because time is within ten seconds of last update ({last_updated.astimezone(self.api.tz)})"
                _LOGGER.warning(status)
                if self._next_update is not None:
                    _LOGGER.info("Forecast update suppressed%s", next_update())
                return UpdateResult(UpdateOutcome.SKIPPED, status)

        await self.api.dampening.refresh_granular_data()

        failure = False
        sites_attempted = 0
        sites_succeeded = 0
        reason = "Unknown"
        for site in self.api.sites:
            sites_attempted += 1
            _LOGGER.info(
                "Getting forecast update for site %s%s",
                site[RESOURCE_ID],
                f", including {do_past_hours} hours of past data" if do_past_hours > 0 else "",
            )
            result, reason = await self.http_data_call(
                site=site[RESOURCE_ID],
                api_key=site[API_KEY],
                do_past_hours=do_past_hours,
                force=force,
            )
            if result == DataCallStatus.FAIL:
                failure = True
                (_LOGGER.warning if len(self.api.sites) > 1 and sites_succeeded and not force else _LOGGER.debug)(
                    "Forecast update for site %s failed%s%s",
                    site[RESOURCE_ID],
                    " so not getting remaining sites" if sites_attempted < len(self.api.sites) else "",
                    " - API use count may be odd" if len(self.api.sites) > 1 and sites_succeeded and not force else "",
                )
                status = "At least one site forecast get failed" if len(self.api.sites) > 1 else "Forecast get failed"
                break
            if result == DataCallStatus.ABORT:
                _LOGGER.info("Forecast update aborted%s", next_update())
                return UpdateResult(UpdateOutcome.ABORTED, "Forecast update aborted")
            if result == DataCallStatus.SUCCESS:
                sites_succeeded += 1
                self.increment_success_count(force, site[API_KEY])

        if sites_attempted > 0 and not failure:
            await self.api.dampening.apply_forward(do_past_hours=do_past_hours)

            b_status = await self.api.build_forecast_data()
            self.api.loaded_data = True

            async def set_metadata_and_serialise(data: dict[str, Any]):
                data[LAST_UPDATED] = dt.now(UTC).replace(microsecond=0)
                data[LAST_ATTEMPT] = last_attempt
                # Set to divisions if auto update is enabled, but not forced, in which case set to 99999 (otherwise zero).
                data[AUTO_UPDATED] = (
                    self.api.auto_update_divisions
                    if self.api.options.auto_update != AutoUpdate.NONE and not force
                    else 0
                    if not force
                    else 99999
                )
                return await self.api.sites_cache.serialise_data(
                    data, self.api.filename if data == self.api.data else self.api.filename_undampened
                )

            s_status = await set_metadata_and_serialise(self.api.data)
            await set_metadata_and_serialise(self.api.data_undampened)
            self.api.loaded_data = True

            if b_status and s_status:
                _LOGGER.info("Forecast update completed successfully%s", next_update())
        else:
            _LOGGER.warning("Forecast has not been updated: %s%s", reason, next_update())
            status = f"At least one site forecast get failed: {reason}"
        return UpdateResult(UpdateOutcome.SUCCESS if status == "" else UpdateOutcome.FAILED, status)

    def set_next_update(self, next_update: str | None) -> None:
        """Set the next update time.

        Arguments:
            next_update (str | None): A string containing the time that the next auto update will occur.
        """
        self._next_update = next_update

    async def sort_and_prune(self, site: str | None, data: dict[str, Any], past_days: int, forecasts: dict[Any, Any]) -> None:
        """Sort and prune a forecast list."""

        _past_days = self.api.dt_helper.day_start_utc(future=past_days * -1)
        _forecasts: list[dict[str, Any]] = sorted(
            filter(
                lambda forecast: forecast[PERIOD_START] >= _past_days,
                forecasts.values(),
            ),
            key=itemgetter(PERIOD_START),
        )
        data[SITE_INFO].update({site: {FORECASTS: copy.deepcopy(_forecasts)}})

    async def http_data_call(
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
            last_day = self.api.dt_helper.day_start_utc(future=self.api.advanced_options[ADVANCED_FORECAST_FUTURE_DAYS])
            hours = math.ceil((last_day - self.api.dt_helper.now_utc()).total_seconds() / 3600)
            _LOGGER.debug(
                "Polling API for site %s, last day %s, %d hours",
                site,
                last_day.strftime(DT_DATE_ONLY_FORMAT),
                hours,
            )

            new_data: list[dict[str, Any]] = []

            # Fetch past data. (Run once, for a new install or if the solcast.json file is deleted. This will use up api call quota.)

            if do_past_hours > 0:
                act_response: dict[str, Any] | None
                try:
                    self.api.tasks[TASK_FORECASTS_FETCH] = asyncio.create_task(
                        self.fetch_data(
                            hours=do_past_hours,
                            path=ESTIMATED_ACTUALS,
                            site=site,
                            api_key=api_key,
                            force=force,
                        )
                    )
                    await self.api.tasks[TASK_FORECASTS_FETCH]
                finally:
                    act_response = (
                        self.api.tasks.pop(TASK_FORECASTS_FETCH).result() if self.api.tasks.get(TASK_FORECASTS_FETCH) is not None else None
                    )
                if not isinstance(act_response, dict):
                    failure = True
                    _LOGGER.error(
                        "No valid data was returned for estimated_actuals so this will cause issues (API limit may be exhausted, or Solcast might have a problem)"
                    )
                    _LOGGER.debug("API did not return a json object, returned `%s`", act_response)
                    return DataCallStatus.FAIL, "No valid json returned"

                estimate_actuals: list[dict[str, Any]] = act_response.get(ESTIMATED_ACTUALS, [])

                oldest = (dt.now(self.api.tz).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=7)).astimezone(UTC)

                actuals: dict[dt, Any] = {}
                for estimate_actual in estimate_actuals:
                    period_start = dt.fromisoformat(estimate_actual[PERIOD_END]).astimezone(UTC).replace(
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

                await self.sort_and_prune(site, self.api.data_actuals, self.api.advanced_options[ADVANCED_HISTORY_MAX_DAYS], actuals)

                self.api.data_actuals[LAST_UPDATED] = dt.now(UTC).replace(microsecond=0)
                self.api.data_actuals[LAST_ATTEMPT] = dt.now(UTC).replace(microsecond=0)

            # Fetch latest data.

            response: dict[str, Any] | None = None
            if self.api.tasks.get(TASK_FORECASTS_FETCH) is not None:
                _LOGGER.warning("A fetch task is already running, so aborting forecast update")
                return DataCallStatus.ABORT, "Fetch already running"
            try:
                self.api.tasks[TASK_FORECASTS_FETCH] = asyncio.create_task(
                    self.fetch_data(
                        hours=hours,
                        path=FORECASTS,
                        site=site,
                        api_key=api_key,
                        force=force,
                    )
                )
                await self.api.tasks[TASK_FORECASTS_FETCH]
            finally:
                response = (
                    self.api.tasks.pop(TASK_FORECASTS_FETCH).result() if self.api.tasks.get(TASK_FORECASTS_FETCH) is not None else None
                )

            if not isinstance(response, dict):
                failure = True
                _LOGGER.debug("API did not return a json object. Returned %s", response)
                if isinstance(response, str) and response:
                    return DataCallStatus.FAIL, response
                return DataCallStatus.FAIL, "No valid json returned"

            latest_forecasts = response.get(FORECASTS, [])

            _LOGGER.debug("%d records returned", len(latest_forecasts))

            for forecast in latest_forecasts:
                period_start = dt.fromisoformat(forecast[PERIOD_END]).astimezone(UTC).replace(second=0, microsecond=0) - timedelta(
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
                forecasts_undampened = {
                    forecast[PERIOD_START]: forecast for forecast in self.api.data_undampened[SITE_INFO][site][FORECASTS]
                }
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

            await self.sort_and_prune(site, self.api.data_undampened, 14, forecasts_undampened)
        finally:
            issue_registry = ir.async_get(self.api.hass)
            if (
                failure
                and (
                    self.api.data_undampened[SITE_INFO].get(site) is None
                    or self.api.data_undampened[SITE_INFO][site][FORECASTS][0][PERIOD_START] > dt.now(UTC) - timedelta(hours=1)
                )
                and issue_registry.async_get_issue(DOMAIN, ISSUE_RECORDS_MISSING_INITIAL) is None
            ):
                _LOGGER.warning("Raise issue `%s` for missing forecast data", ISSUE_RECORDS_MISSING_INITIAL)
                ir.async_create_issue(
                    self.api.hass,
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
        self.api.data[FAILURE][LAST_24H] += 1
        self.api.data[FAILURE][LAST_7D][0] = self.api.data[FAILURE][LAST_24H]
        self.api.data[FAILURE][LAST_14D][0] = self.api.data[FAILURE][LAST_24H]

    def increment_success_count(self, force: bool, api_key: str) -> None:
        """Increment the appropriate success counter once per successful site API call.

        Arguments:
            force (bool): True if the update was a forced update (quota not consumed).
            api_key (str): The API key used for the site fetch.
        """
        key = md5(api_key[-6:].encode()).hexdigest()
        if force:
            forced = self.api.data[SUCCESS][SUCCESS_FORCED]
            forced[key] = forced.get(key, 0) + 1
            _LOGGER.debug("Forced API counter for %s incremented from %d to %d", redact_api_key(api_key), forced[key] - 1, forced[key])
        else:
            tracked = self.api.data[SUCCESS][SUCCESS_TRACKED]
            tracked[key] = tracked.get(key, 0) + 1
            # Tracked increments are already logged.

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
        failure_reason: str | None = None

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
                    issue_registry = ir.async_get(self.api.hass)

                    if self.api.api_used[api_key] < self.api.api_limits[api_key] or force:
                        url = f"{self.api.advanced_options[ADVANCED_SOLCAST_URL]}/rooftop_sites/{site}/{path}"
                        params: dict[str, str | int] = {FORMAT: JSON, API_KEY: api_key, HOURS: hours}

                        tries = UPDATE_TRIES
                        counter = 0
                        backoff = UPDATE_BACKOFF  # On every retry the back-off increases by (at least) UPDATE_BACKOFF seconds more than the previous back-off.
                        while True:
                            _LOGGER.debug("Fetching path %s", path)
                            counter += 1
                            response_text = ""
                            try:
                                response: ClientResponse = await self.api.aiohttp_session.get(
                                    url=url, params=params, headers=self.api.headers, ssl=False
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
                                            self.api.api_used[api_key] = self.api.api_limits[api_key]
                                            await self.api.sites_cache.serialise_usage(api_key)
                                            break
                                        status = 1000
                                        _LOGGER.warning("An unexpected error occurred: %s", response_status.get(MESSAGE))
                                        break
                                else:
                                    received_429 += 1
                            if counter >= tries:
                                failure_reason = f"{http_status_translate(status)} after {tries} attempts"
                                if not self.api.advanced_options[ADVANCED_LOG_UPDATE_FAILURE_ONLY]:
                                    _LOGGER.error("API was tried %d times, but all attempts failed", tries)
                                break
                            # Integration fetch is in a possibly recoverable state, so delay (15 seconds * counter),
                            # plus a random number of seconds between zero and 15.
                            delay: int = (counter * backoff) + random.randrange(0, 15)
                            (_LOGGER.debug if self.api.advanced_options[ADVANCED_LOG_UPDATE_FAILURE_ONLY] else _LOGGER.warning)(
                                "Call status %s, pausing %d seconds before retry",
                                http_status_translate(status),
                                delay,
                            )
                            await self._sleep(delay)

                        if status == 200:
                            if not force:
                                _LOGGER.debug(
                                    "API returned data, tracked API counter incremented from %d to %d",
                                    self.api.api_used[api_key],
                                    self.api.api_used[api_key] + 1,
                                )
                                self.api.api_used[api_key] += 1
                                await self.api.sites_cache.serialise_usage(api_key)
                            else:
                                _LOGGER.debug("API returned data")
                            response_json = response_text
                            response_json = json.loads(response_json)
                            if issue_registry.async_get_issue(DOMAIN, ISSUE_API_UNAVAILABLE) is not None:
                                _LOGGER.debug("Remove issue for %s", ISSUE_API_UNAVAILABLE)
                                ir.async_delete_issue(self.api.hass, DOMAIN, ISSUE_API_UNAVAILABLE)
                                if (trigger := self.api.advanced_options[ADVANCED_TRIGGER_ON_API_AVAILABLE]) and trigger:
                                    await async_trigger_automation_by_name(self.api.hass, trigger)
                            _LOGGER.debug(
                                "Task fetch_data took %.3f seconds",
                                time.time() - start_time,
                            )
                            return response_json
                        elif status in (400, 404):  # noqa: RET505
                            _LOGGER.error("Unexpected error getting sites, status %s returned", http_status_translate(status))
                        elif status == 403:  # Forbidden.
                            _LOGGER.error("API key %s is forbidden, re-authentication required", redact_api_key(api_key))
                            self.api.reauth_required = True
                        elif status == 998:  # Exceeded API limit.
                            _LOGGER.error(
                                "API allowed polling limit has been exceeded, API counter set to %d/%d",
                                self.api.api_used[api_key],
                                self.api.api_limits[api_key],
                            )
                        elif status == 1000:  # Unexpected response.
                            _LOGGER.error("Unexpected response received")
                        else:  # Other, or unknown status.
                            (_LOGGER.debug if self.api.advanced_options[ADVANCED_LOG_UPDATE_FAILURE_ONLY] else _LOGGER.error)(
                                "Call status %s, API used is %d/%d",
                                http_status_translate(status),
                                self.api.api_used[api_key],
                                self.api.api_limits[api_key],
                            )
                            _LOGGER.debug("HTTP session status %s", http_status_translate(status))

                            if received_429 == tries:
                                if issue_registry.async_get_issue(DOMAIN, ISSUE_API_UNAVAILABLE) is None:
                                    _LOGGER.debug("Raise issue for %s", ISSUE_API_UNAVAILABLE)
                                    ir.async_create_issue(
                                        self.api.hass,
                                        DOMAIN,
                                        ISSUE_API_UNAVAILABLE,
                                        is_fixable=False,
                                        is_persistent=True,
                                        severity=ir.IssueSeverity.WARNING,
                                        translation_key=ISSUE_API_UNAVAILABLE,
                                        learn_more_url=LEARN_MORE_MISSING_FORECAST_DATA,
                                    )
                                    if (trigger := self.api.advanced_options[ADVANCED_TRIGGER_ON_API_UNAVAILABLE]) and trigger:
                                        await async_trigger_automation_by_name(self.api.hass, trigger)

                    else:
                        _LOGGER.warning(
                            "API polling limit exhausted, not getting forecast for site %s, API used is %d/%d",
                            site,
                            self.api.api_used[api_key],
                            self.api.api_limits[api_key],
                        )
                        return None

        except asyncio.exceptions.CancelledError:
            _LOGGER.info("Fetch cancelled")
        except json.decoder.JSONDecodeError:
            return response_text

        if failure_reason is not None:
            return failure_reason

        return None
