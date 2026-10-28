"""Tests for Solcast Solar issue registry behaviors and quota warnings."""

import asyncio
from contextlib import suppress
import copy
from types import SimpleNamespace
from typing import Any

from custom_components.solcast_solar.const import (
    ACTUALS_COST,
    API_LIMIT,
    API_USED,
    AUTO_UPDATE,
    CONFIGURED_VALUE,
    DOMAIN,
    GET_ACTUALS,
    ISSUE_ACTUALS_API_LIMIT,
    ISSUE_ACTUALS_QUOTA_TODAY,
    SUGGESTED_VALUE,
    TASK_ACTUALS_FETCH,
    USE_ACTUALS,
)
from custom_components.solcast_solar.coordinator import SolcastUpdateCoordinator
from custom_components.solcast_solar.enums import AutoUpdate
from custom_components.solcast_solar.fetcher import Fetcher
from custom_components.solcast_solar.issues import (
    sync_actuals_api_limit_issue,
    sync_actuals_quota_risk_issue,
)
from custom_components.solcast_solar.solcastapi import SolcastApi
import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from . import (
    DEFAULT_INPUT1,
    MOCK_OVER_LIMIT,
    async_cleanup_integration_tests,
    async_init_integration,
    session_clear,
    session_set,
)
from .test_integration import patch_solcast_api


@pytest.fixture(autouse=True)
def frozen_time() -> None:
    """Disable the global freezer fixture for this module."""


async def test_pop_task_result_handles_cancelled_task() -> None:
    """Ensure cancelled fetch tasks are popped without raising."""

    api = SimpleNamespace(tasks={})
    fetcher = Fetcher(api=api)  # pyright: ignore[reportArgumentType]

    task = asyncio.create_task(asyncio.sleep(5))
    api.tasks[TASK_ACTUALS_FETCH] = task
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task

    result = fetcher._pop_task_result(TASK_ACTUALS_FETCH)

    assert result is None
    assert TASK_ACTUALS_FETCH not in api.tasks


def test_pop_task_result_handles_missing_task() -> None:
    """Ensure missing fetch tasks return None without raising."""

    api = SimpleNamespace(tasks={})
    fetcher = Fetcher(api=api)  # pyright: ignore[reportArgumentType]

    assert fetcher._pop_task_result(TASK_ACTUALS_FETCH) is None


async def test_pop_task_result_handles_task_exception() -> None:
    """Ensure failed fetch tasks are popped and converted to None."""

    api = SimpleNamespace(tasks={})
    fetcher = Fetcher(api=api)  # pyright: ignore[reportArgumentType]

    async def _fail() -> None:
        raise RuntimeError("Magic smoke released")

    task = asyncio.create_task(_fail())
    api.tasks[TASK_ACTUALS_FETCH] = task
    with suppress(RuntimeError):
        await task

    result = fetcher._pop_task_result(TASK_ACTUALS_FETCH)

    assert result is None
    assert TASK_ACTUALS_FETCH not in api.tasks


@pytest.mark.parametrize(API_LIMIT, ["10", "50"])
async def test_actuals_api_limit_issue_raised_and_cleared(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    issue_registry: ir.IssueRegistry,
    api_limit: str,
) -> None:
    """Test warning issue is raised and then cleared for estimated actuals with auto-update."""

    try:
        options = copy.deepcopy(DEFAULT_INPUT1)
        options[API_LIMIT] = api_limit
        options[AUTO_UPDATE] = AutoUpdate.DAYLIGHT
        options[GET_ACTUALS] = True
        entry = await async_init_integration(hass, options)

        issue = issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_API_LIMIT)
        assert issue is not None, "Issue should exist"
        assert issue.is_persistent is False, "Issue should not be persistent"

        solcast = entry.runtime_data.coordinator.solcast
        api_keys = [api_key.strip() for api_key in entry.options[CONF_API_KEY].split(",") if api_key.strip()]
        limits = [limit.strip() for limit in entry.options[API_LIMIT].split(",") if limit.strip()]
        while len(limits) < len(api_keys):
            limits.append(limits[-1])
        sites_per_key = dict.fromkeys(api_keys, 0)
        for site in solcast.sites:
            sites_per_key[site[CONF_API_KEY]] += 1
        configured_value = ",".join(limits[: len(api_keys)])
        suggested_value = ",".join(str(max(int(limits[index]) - sites_per_key[api_keys[index]], 1)) for index in range(len(api_keys)))

        assert issue.translation_placeholders is not None, "Issue should have translation placeholders"
        assert issue.translation_placeholders[CONFIGURED_VALUE] == configured_value
        assert issue.translation_placeholders[SUGGESTED_VALUE] == suggested_value

        # User resolves by disabling estimated actuals acquisition
        new_options = {**entry.options, GET_ACTUALS: False}
        hass.config_entries.async_update_entry(entry, options=new_options)
        await hass.async_block_till_done()

        assert issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_API_LIMIT) is None, "Issue ISSUE_ACTUALS_API_LIMIT should not exist"
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_actuals_api_limit_issue_not_raised_when_auto_update_disabled(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Test warning issue is not raised when auto-update is disabled."""

    try:
        options = copy.deepcopy(DEFAULT_INPUT1)
        options[API_LIMIT] = "10"
        options[AUTO_UPDATE] = AutoUpdate.NONE
        options[GET_ACTUALS] = True
        await async_init_integration(hass, options)

        assert issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_API_LIMIT) is None, "Issue ISSUE_ACTUALS_API_LIMIT should not exist"
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_actuals_api_limit_issue_invalid_option_paths(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Test helper paths for invalid option values clear the warning issue safely."""

    try:
        options = copy.deepcopy(DEFAULT_INPUT1)
        options[API_LIMIT] = "10"
        options[AUTO_UPDATE] = AutoUpdate.DAYLIGHT
        options[GET_ACTUALS] = True
        entry = await async_init_integration(hass, options)
        solcast = entry.runtime_data.coordinator.solcast

        valid: dict[str, Any] = {
            CONF_API_KEY: options[CONF_API_KEY],
            API_LIMIT: "10",
            AUTO_UPDATE: AutoUpdate.DAYLIGHT,
            GET_ACTUALS: True,
        }

        sync_actuals_api_limit_issue(hass, valid, solcast.sites)
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_API_LIMIT) is not None, "Issue ISSUE_ACTUALS_API_LIMIT should exist"

        sync_actuals_api_limit_issue(hass, {**valid, AUTO_UPDATE: "bad"}, solcast.sites)
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_API_LIMIT) is None, "Issue ISSUE_ACTUALS_API_LIMIT should not exist"

        sync_actuals_api_limit_issue(hass, valid, solcast.sites)
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_API_LIMIT) is not None, "Issue ISSUE_ACTUALS_API_LIMIT should exist"

        sync_actuals_api_limit_issue(hass, {**valid, CONF_API_KEY: ""}, solcast.sites)
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_API_LIMIT) is None, "Issue ISSUE_ACTUALS_API_LIMIT should not exist"

        sync_actuals_api_limit_issue(hass, valid, solcast.sites)
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_API_LIMIT) is not None, "Issue ISSUE_ACTUALS_API_LIMIT should exist"

        sync_actuals_api_limit_issue(hass, {**valid, API_LIMIT: "NaN"}, solcast.sites)
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_API_LIMIT) is None, "Issue ISSUE_ACTUALS_API_LIMIT should not exist"

        # Numeric comparison is per key: suggested 8,48 from 10,50 still raises.
        numeric = {
            CONF_API_KEY: "a,b",
            API_LIMIT: "10,50",
            AUTO_UPDATE: AutoUpdate.DAYLIGHT,
            GET_ACTUALS: True,
        }
        fake_sites = [
            {CONF_API_KEY: "a"},
            {CONF_API_KEY: "a"},
            {CONF_API_KEY: "b"},
            {CONF_API_KEY: "b"},
        ]
        sync_actuals_api_limit_issue(hass, numeric, fake_sites)
        issue = issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_API_LIMIT)
        assert issue is not None, "Issue should exist"
        assert issue.translation_placeholders is not None, "Issue should have translation placeholders"
        assert issue.translation_placeholders[CONFIGURED_VALUE] == "10,50"
        assert issue.translation_placeholders[SUGGESTED_VALUE] == "8,48"
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_actuals_quota_today_issue_raised_when_quota_at_risk(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Test that the quota risk issue is raised when typical usage plus actuals cost exceeds the inferred quota."""

    try:
        fake_sites = [{CONF_API_KEY: "key1"}]
        api_typical: dict[str, int] = {"key1": 10}
        api_limit = 9

        sync_actuals_quota_risk_issue(hass, fake_sites, api_typical, {}, {}, api_limit, get_actuals=True)
        issue = issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_QUOTA_TODAY)
        assert issue is not None, "Issue ISSUE_ACTUALS_QUOTA_TODAY should exist"
        assert issue.is_persistent is False, "Issue should not be persistent"
        assert issue.translation_placeholders is not None, "Issue should have translation placeholders"
        assert issue.translation_placeholders[API_USED] == "10"
        assert issue.translation_placeholders[API_LIMIT] == "10"
        assert issue.translation_placeholders[ACTUALS_COST] == "1"
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_actuals_quota_today_issue_per_key_math(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Test that the quota risk issue uses per-key site counts, not the total across all keys."""

    try:
        fake_sites = [
            {CONF_API_KEY: "key1"},
            {CONF_API_KEY: "key1"},
            {CONF_API_KEY: "key2"},
        ]
        api_typical: dict[str, int] = {"key1": 9, "key2": 9}
        api_limit = 9

        sync_actuals_quota_risk_issue(hass, fake_sites, api_typical, {}, {}, api_limit, get_actuals=True)
        issue = issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_QUOTA_TODAY)
        assert issue is not None, "Issue should be raised: key1 typical 9 + 2 actuals = 11 > 10"
        assert issue.translation_placeholders is not None
        assert issue.translation_placeholders[API_USED] == "9"
        assert issue.translation_placeholders[API_LIMIT] == "10"
        assert issue.translation_placeholders[ACTUALS_COST] == "2", (
            "actuals_cost must be key1's site count (2), not total sites across both keys (3)"
        )

        ir.async_delete_issue(hass, DOMAIN, ISSUE_ACTUALS_QUOTA_TODAY)
        api_typical2: dict[str, int] = {"key1": 7, "key2": 10}
        sync_actuals_quota_risk_issue(hass, fake_sites, api_typical2, {}, {}, api_limit, get_actuals=True)
        issue2 = issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_QUOTA_TODAY)
        assert issue2 is not None, "Issue should be raised: key2 typical 10 + 1 = 11 > 10"
        assert issue2.translation_placeholders is not None
        assert issue2.translation_placeholders[API_USED] == "10"
        assert issue2.translation_placeholders[ACTUALS_COST] == "1"
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_actuals_quota_today_issue_not_raised_when_within_quota(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Test that the quota risk issue is not raised when typical usage plus actuals cost is within the inferred quota."""

    try:
        fake_sites = [{CONF_API_KEY: "key1"}]
        api_limit = 9

        api_typical: dict[str, int] = {"key1": 8}
        sync_actuals_quota_risk_issue(hass, fake_sites, api_typical, {}, {}, api_limit, get_actuals=True)
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_QUOTA_TODAY) is None, (
            "Issue should not exist: typical 8 + 1 actuals = 9, not > inferred quota 10"
        )

        sync_actuals_quota_risk_issue(hass, fake_sites, {"key1": 10}, {}, {}, 10, get_actuals=True)
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_QUOTA_TODAY) is None, (
            "Issue should not exist at the hobbyist maximum (actuals_api_limit covers this case)"
        )
        sync_actuals_quota_risk_issue(hass, fake_sites, {"key1": 50}, {}, {}, 50, get_actuals=True)
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_QUOTA_TODAY) is None, (
            "Issue should not exist at the hobbyist maximum of 50"
        )
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_actuals_quota_today_issue_persists_until_config_reduced(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Test that a raised quota risk issue is not auto-cleared by a transient drop in typical usage."""

    try:
        fake_sites = [{CONF_API_KEY: "key1"}, {CONF_API_KEY: "key1"}]
        api_limit = 9

        sync_actuals_quota_risk_issue(hass, fake_sites, {"key1": 9}, {}, {}, api_limit, get_actuals=True)
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_QUOTA_TODAY) is not None, (
            "Issue should be raised: typical 9 + 2 actuals = 11 > inferred quota 10"
        )

        sync_actuals_quota_risk_issue(hass, fake_sites, {"key1": 5}, {}, {}, api_limit, get_actuals=True)
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_QUOTA_TODAY) is not None, (
            "Issue should persist: configuration api_limit(9)+2 actuals=11 > inferred quota 10, regardless of the current typical being low"
        )

        sync_actuals_quota_risk_issue(hass, fake_sites, {"key1": 5}, {}, {}, 8, get_actuals=True)
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_QUOTA_TODAY) is None, (
            "Issue should be cleared once api_limit(8)+2 actuals=10 <= inferred quota 10"
        )
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_actuals_quota_today_issue_persists_after_429(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Test that the quota risk issue is not cleared by a 429 quota-exceeded response."""

    try:
        options = copy.deepcopy(DEFAULT_INPUT1)
        options[GET_ACTUALS] = True
        options[USE_ACTUALS] = 1
        entry = await async_init_integration(hass, options)
        coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator
        solcast: SolcastApi = patch_solcast_api(coordinator.solcast)
        caplog.clear()

        for key in solcast.api_typical:
            solcast.api_typical[key] = 50
        sync_actuals_quota_risk_issue(
            hass, solcast.sites, solcast.api_typical, solcast.api_used, solcast.api_forced, solcast.api_limit, get_actuals=True
        )
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_QUOTA_TODAY) is not None, "Issue should exist before 429"

        session_set(MOCK_OVER_LIMIT)
        try:
            await solcast.fetcher.update_estimated_actuals()
        finally:
            session_clear(MOCK_OVER_LIMIT)

        assert "No valid data was returned for estimated_actuals" in caplog.text
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_QUOTA_TODAY) is not None, (
            "Issue ISSUE_ACTUALS_QUOTA_TODAY should persist after a 429: the configuration is still risky"
        )
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_actuals_quota_today_issue_cleared_when_get_actuals_disabled(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Test that the runtime quota risk issue clears when estimated actuals fetching is disabled."""

    try:
        fake_sites = [{CONF_API_KEY: "key1"}]
        api_typical: dict[str, int] = {"key1": 10}
        api_limit = 9

        sync_actuals_quota_risk_issue(hass, fake_sites, api_typical, {}, {}, api_limit, get_actuals=True)
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_QUOTA_TODAY) is not None, "Issue should exist before clearing"

        sync_actuals_quota_risk_issue(hass, fake_sites, api_typical, {}, {}, api_limit, get_actuals=False)
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_QUOTA_TODAY) is None, (
            "Issue ISSUE_ACTUALS_QUOTA_TODAY should be cleared when get_actuals is disabled"
        )
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_actuals_quota_today_issue_raised_by_todays_usage_exceeding_typical(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Test that today's running total serves as a floor when it exceeds the persisted typical."""

    try:
        fake_sites = [{CONF_API_KEY: "key1"}]
        api_typical: dict[str, int] = {"key1": 5}
        api_used: dict[str, int] = {"key1": 9}
        api_limit = 9

        sync_actuals_quota_risk_issue(hass, fake_sites, api_typical, api_used, {}, api_limit, get_actuals=True)
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_QUOTA_TODAY) is None, (
            "Issue should NOT exist: effective 9 + 1 actuals = 10, not > inferred quota 10"
        )

        api_used["key1"] = 10
        sync_actuals_quota_risk_issue(hass, fake_sites, api_typical, api_used, {}, api_limit, get_actuals=True)
        issue = issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_QUOTA_TODAY)
        assert issue is not None, "Issue should be raised: today's 10 calls + 1 actuals = 11 > inferred quota 10"
        assert issue.translation_placeholders is not None
        assert issue.translation_placeholders[API_USED] == "10"
        assert issue.translation_placeholders[API_LIMIT] == "10"
        assert issue.translation_placeholders[ACTUALS_COST] == "1"

        api_used["key1"] = 5
        api_forced: dict[str, int] = {"key1": 5}
        sync_actuals_quota_risk_issue(hass, fake_sites, api_typical, api_used, api_forced, api_limit, get_actuals=True)
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_QUOTA_TODAY) is not None, (
            "Issue should be raised: today's 5 tracked + 5 forced + 1 actuals = 11 > inferred quota 10"
        )
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_actuals_quota_today_issue_suppressed_when_allow_exceed_and_high_limit(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Test that the quota risk issue is never raised when allow_exceed_api_limit_maximum is set and api_limit > 50."""

    try:
        fake_sites = [{CONF_API_KEY: "key1"}]
        api_limit = 4000

        api_typical: dict[str, int] = {"key1": api_limit}
        sync_actuals_quota_risk_issue(
            hass,
            fake_sites,
            api_typical,
            {"key1": api_limit},
            {},
            api_limit,
            get_actuals=True,
            allow_exceed_api_limit_maximum=True,
        )
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_QUOTA_TODAY) is None, (
            "Issue should NOT be raised when allow_exceed_api_limit_maximum=True and api_limit > 50"
        )

        sync_actuals_quota_risk_issue(
            hass,
            fake_sites,
            {"key1": 10},
            {},
            {},
            9,
            get_actuals=True,
            allow_exceed_api_limit_maximum=True,
        )
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_QUOTA_TODAY) is not None, (
            "Issue should be raised when allow_exceed=True but api_limit=9 (quota=9) and typical 10 + 1 > 9"
        )
        ir.async_delete_issue(hass, DOMAIN, ISSUE_ACTUALS_QUOTA_TODAY)

        sync_actuals_quota_risk_issue(
            hass,
            fake_sites,
            {"key1": 10},
            {},
            {},
            9,
            get_actuals=True,
            allow_exceed_api_limit_maximum=False,
        )
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_QUOTA_TODAY) is not None, (
            "Issue should be raised for a sub-maximum limit without allow_exceed_api_limit_maximum"
        )
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_actuals_api_limit_issue_single_limit_multiple_keys(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Test that a single API limit covering multiple keys shows one suggested value."""

    try:
        options = copy.deepcopy(DEFAULT_INPUT1)
        options[API_LIMIT] = "10"
        options[AUTO_UPDATE] = AutoUpdate.DAYLIGHT
        options[GET_ACTUALS] = True
        await async_init_integration(hass, options)

        single_limit = {
            CONF_API_KEY: "a,b",
            API_LIMIT: "10",
            AUTO_UPDATE: AutoUpdate.DAYLIGHT,
            GET_ACTUALS: True,
        }
        fake_sites = [
            {CONF_API_KEY: "a"},
            {CONF_API_KEY: "a"},
            {CONF_API_KEY: "b"},
        ]
        sync_actuals_api_limit_issue(hass, single_limit, fake_sites)
        issue = issue_registry.async_get_issue(DOMAIN, ISSUE_ACTUALS_API_LIMIT)
        assert issue is not None, "Issue should exist"
        assert issue.translation_placeholders is not None, "Issue should have translation placeholders"
        assert issue.translation_placeholders[CONFIGURED_VALUE] == "10"
        assert issue.translation_placeholders[SUGGESTED_VALUE] == "8"
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"
