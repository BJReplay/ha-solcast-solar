"""Tests for the Solcast Solar diagnostics and system health."""

import copy
import datetime
from datetime import datetime as dt, timedelta
import logging
import unittest.mock

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar.const import (
    ACTUALS_ATTEMPT,
    ACTUALS_UPDATED,
    API_FORCE_USED,
    API_KEYS_CONFIGURED,
    API_LIMIT,
    API_REMAINING,
    API_USED,
    AUTO_DAMPEN,
    AUTO_UPDATE,
    AUTO_UPDATED,
    DAILY_TYPICAL_FORECAST_UPDATES,
    DATA_SET_FORECAST,
    DOMAIN,
    EXCLUDE_SITES,
    FORECASTS,
    GENERATION_ENTITIES,
    GET_ACTUALS,
    HARD_LIMIT,
    KEY_ESTIMATE,
    LAST_24H,
    LAST_ATTEMPT,
    LAST_UPDATED,
    RESOURCE_ID,
    SERVICE_DIAGNOSTIC,
    SERVICE_SET_HARD_LIMIT,
    SITE_ATTRIBUTE_CAPACITY,
    SITE_ATTRIBUTE_CAPACITY_DC,
    SITE_ATTRIBUTE_COMPASS_DEGREES,
    SITE_ATTRIBUTE_COMPASS_DIRECTION,
    SITE_EXPORT_ENTITY,
    SITE_INFO,
    SITES,
    SITES_STATUS,
    USAGE_STATUS,
)
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.enums import LoadStatus
from homeassistant.components.solcast_solar.solcastapi import SolcastApi
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import RegistryEntryDisabler
from homeassistant.util import dt as dt_util

from . import (
    DEFAULT_INPUT1,
    ZONE_RAW,
    async_cleanup_integration_tests,
    async_init_integration,
    no_error_or_exception,
)
from .test_integration import patch_solcast_api

from tests.components.diagnostics import (
    get_diagnostics_for_config_entry,  # pyright:ignore[reportUnknownVariableType]
)
from tests.typing import (
    ClientSessionGenerator,  # pyright:ignore[reportUnknownVariableType]
)

_LOGGER = logging.getLogger(__name__)


async def test_diagnostics(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    hass_client: ClientSessionGenerator,  # pyright:ignore[reportUnknownParameterType]
) -> None:
    """Test diagnostics output."""

    try:
        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        freezer.move_to(dt_util.now() + timedelta(minutes=1))
        await hass.async_block_till_done()
        coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator
        solcast: SolcastApi = coordinator.solcast

        diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)
        assert ZONE_RAW in diagnostics["tz_conversion"]["repr"]  # type: ignore[call-overload, index, operator] # pyright: ignore[reportOperatorIssue, reportIndexIssue, reportCallIssue, reportArgumentType, reportOptionalSubscript]
        assert diagnostics["health_check"]["api"][API_USED] == 4, (  # type: ignore[call-overload, index]
            f"Expected 4 used API requests, got {diagnostics['health_check']['api'][API_USED]}"  # type: ignore[call-overload, index]
        )
        health_api = diagnostics["health_check"]["api"]  # type: ignore[call-overload, index]
        assert health_api[DAILY_TYPICAL_FORECAST_UPDATES] == solcast.api_typical_forecast_updates_count  # type: ignore[index]
        assert diagnostics["health_check"]["api"][API_LIMIT] == int(DEFAULT_INPUT1[API_LIMIT]), (  # type: ignore[call-overload, index]
            f"API limit mismatch: expected {int(DEFAULT_INPUT1[API_LIMIT])}, got {diagnostics['health_check']['api'][API_LIMIT]}"  # type: ignore[call-overload, index]
        )
        assert diagnostics["rooftop_site_count"] == 2, f"Expected 2 rooftop sites, got {diagnostics['rooftop_site_count']}"
        assert diagnostics["health_check"]["configuration"][HARD_LIMIT] == "100.0", "Hard limit should not be set initially"  # type: ignore[call-overload, index]
        assert "health_check" in diagnostics
        assert diagnostics["health_check"]["overall_status"] == "ok"  # type: ignore[call-overload, index]
        assert diagnostics["health_check"]["api"][API_KEYS_CONFIGURED] == 1  # type: ignore[call-overload, index]
        assert CONF_API_KEY not in diagnostics["health_check"]  # type: ignore[operator]
        for site in diagnostics["health_check"]["sites"]:  # type: ignore[index]
            assert "azimuth" in site
            assert SITE_ATTRIBUTE_COMPASS_DEGREES in site
            assert SITE_ATTRIBUTE_COMPASS_DIRECTION in site
        for site, data in diagnostics["data"][SITE_INFO].items():  # type: ignore[call-overload, index, union-attr] # pyright: ignore[reportArgumentType, reportIndexIssue, reportOptionalSubscript, reportUnknownMemberType]
            assert site in ["1111-1111-1111-1111", "2222-2222-2222-2222"], f"Unexpected site ID: {site}"
            assert len(data[FORECASTS]) > 300, f"Site {site}: expected > 300 forecasts, got {len(data[FORECASTS])}"  # type: ignore[arg-type, call-overload, index] # pyright: ignore[reportArgumentType, reportIndexIssue, reportOptionalSubscript, reportUnknownMemberType]
        assert diagnostics["energy_forecasts_graph"][solcast.dt_helper.now_utc().replace(hour=2, minute=0, second=0).isoformat()] == 3600.0  # type: ignore[call-overload, index]

        await hass.services.async_call(DOMAIN, SERVICE_SET_HARD_LIMIT, {HARD_LIMIT: "5.0"}, blocking=True)
        await hass.async_block_till_done()  # Because integration reloads
        diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)
        assert diagnostics["health_check"]["configuration"][HARD_LIMIT] == "5.0", "Expected hard limit to be updated to 5.0"  # type: ignore[call-overload, index]

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_diagnostic(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test the diagnostic self-test action returns a structured health report."""

    try:
        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        patch_solcast_api(entry.runtime_data.coordinator.solcast)
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"

        result = await hass.services.async_call(DOMAIN, SERVICE_DIAGNOSTIC, {}, blocking=True, return_response=True)
        assert result is not None, "Result should not be None"
        data = result["data"]

        assert "overall_status" in data  # pyright: ignore[reportOperatorIssue]
        assert "issues" in data  # pyright: ignore[reportOperatorIssue]
        assert "api" in data  # pyright: ignore[reportOperatorIssue]
        assert "sites" in data  # pyright: ignore[reportOperatorIssue]
        assert "cache_files" in data  # pyright: ignore[reportOperatorIssue]
        assert "configuration" in data  # pyright: ignore[reportOperatorIssue]
        assert "dampening" in data  # pyright: ignore[reportOperatorIssue]
        assert "forecast_health" in data  # pyright: ignore[reportOperatorIssue]
        assert "actuals_health" in data  # pyright: ignore[reportOperatorIssue]
        assert "excluded_sites" in data  # pyright: ignore[reportOperatorIssue]
        assert "usage_health" in data  # pyright: ignore[reportOperatorIssue]
        assert "generation_entities" in data  # pyright: ignore[reportOperatorIssue]
        assert "export_entity" in data  # pyright: ignore[reportOperatorIssue]
        assert "recorder_available" in data  # pyright: ignore[reportOperatorIssue]

        api = data["api"]  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportCallIssue, reportArgumentType]
        assert api[API_KEYS_CONFIGURED] == 1  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert isinstance(api[API_USED], int)  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert isinstance(api[API_LIMIT], int)  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert isinstance(api[API_REMAINING], int)  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert isinstance(api[DAILY_TYPICAL_FORECAST_UPDATES], int)  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert isinstance(api[API_FORCE_USED], int)  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert isinstance(api[ACTUALS_UPDATED], str)  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert isinstance(api[ACTUALS_ATTEMPT], str)  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert "status" in api  # pyright: ignore[reportOperatorIssue]
        assert SITES_STATUS in api  # pyright: ignore[reportOperatorIssue]
        assert api[USAGE_STATUS] == "OK"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        assert len(data[SITES]) > 0  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        for site in data[SITES]:  # type: ignore # pyright: ignorereportOptionalIterable, [reportArgumentType, reportCallIssue]  # noqa: PGH003
            assert RESOURCE_ID in site
            assert SITE_ATTRIBUTE_CAPACITY in site
            assert SITE_ATTRIBUTE_CAPACITY_DC in site
            assert SITE_ATTRIBUTE_COMPASS_DEGREES in site
            assert SITE_ATTRIBUTE_COMPASS_DIRECTION in site

        assert isinstance(data["cache_files"][DATA_SET_FORECAST], bool)  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert isinstance(data["cache_files"]["advanced"], bool)  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        config = data["configuration"]  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert config[AUTO_UPDATE] in ("DAYLIGHT", "1")  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert config[KEY_ESTIMATE] == "estimate"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert config[GET_ACTUALS] is True, "Expected get_actuals to be True"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert config[AUTO_DAMPEN] is False, "Expected auto_dampen to be False"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        dampening = data["dampening"]  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert isinstance(dampening["enabled"], bool)  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert dampening["auto_dampening"] is False, "Expected auto_dampening to be False"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        forecast_health = data["forecast_health"]  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert forecast_health["status"] in {"fresh", "indeterminate"}  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        actuals_health = data["actuals_health"]  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert actuals_health["status"] == "fresh"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert actuals_health["site_data_present"] is True  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        excluded_sites = data["excluded_sites"]  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert excluded_sites["all_valid"] is True  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        usage_health = data["usage_health"]  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert usage_health["status"] == "OK"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert usage_health["ok"] is True  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        assert data["recorder_available"] is True, "Expected recorder_available to be True"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data[GENERATION_ENTITIES] == []  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["export_entity"] == {}  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        no_error_or_exception(caplog)

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_diagnostic_generation_entity_states(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test generation entity diagnostics for not found, disabled, unavailable, and OK states."""

    try:
        entity_id = "sensor.test_generation_entity"
        options = copy.deepcopy(DEFAULT_INPUT1)
        options[AUTO_DAMPEN] = True
        options[GENERATION_ENTITIES] = [entity_id]
        entry = await async_init_integration(hass, options)
        patch_solcast_api(entry.runtime_data.coordinator.solcast)
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"

        result = await hass.services.async_call(DOMAIN, SERVICE_DIAGNOSTIC, {}, blocking=True, return_response=True)
        entity_registry = er.async_get(hass)
        entity_registry.async_get_or_create(
            "sensor",
            "pytest",
            "test_generation_entity",
            config_entry=entry,
            suggested_object_id="test_generation_entity",
        )
        data = result["data"]  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["overall_status"] == "issues_found"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert any(entity_id in issue for issue in data["issues"])  # pyright: ignore[reportGeneralTypeIssues, reportOptionalIterable, reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data[GENERATION_ENTITIES][0]["entity_id"] == entity_id  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data[GENERATION_ENTITIES][0]["status"] == "not_found"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        entity_registry.async_update_entity(entity_id, disabled_by=RegistryEntryDisabler.USER)
        await hass.async_block_till_done()
        result = await hass.services.async_call(DOMAIN, SERVICE_DIAGNOSTIC, {}, blocking=True, return_response=True)
        data = result["data"]  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["overall_status"] == "issues_found"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert any("disabled" in issue for issue in data["issues"])  # pyright: ignore[reportGeneralTypeIssues, reportOptionalIterable, reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data[GENERATION_ENTITIES][0]["status"] == "disabled"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        entity_registry.async_update_entity(entity_id, disabled_by=None)
        await hass.async_block_till_done()
        hass.states.async_set(entity_id, "unavailable")
        await hass.async_block_till_done()
        result = await hass.services.async_call(DOMAIN, SERVICE_DIAGNOSTIC, {}, blocking=True, return_response=True)
        data = result["data"]  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["overall_status"] == "issues_found"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert any("unavailable" in issue for issue in data["issues"])  # pyright: ignore[reportGeneralTypeIssues, reportOptionalIterable, reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data[GENERATION_ENTITIES][0]["entity_id"] == entity_id  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data[GENERATION_ENTITIES][0]["status"] == "unavailable"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        hass.states.async_set(entity_id, "1.5")
        await hass.async_block_till_done()
        result = await hass.services.async_call(DOMAIN, SERVICE_DIAGNOSTIC, {}, blocking=True, return_response=True)
        data = result["data"]  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data[GENERATION_ENTITIES][0]["entity_id"] == entity_id  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data[GENERATION_ENTITIES][0]["status"] == "ok"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        no_error_or_exception(caplog)

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_diagnostic_auto_dampen_no_entities(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that self-test reports auto-dampening without generation entities."""

    try:
        options = copy.deepcopy(DEFAULT_INPUT1)
        options[AUTO_DAMPEN] = True
        options[GENERATION_ENTITIES] = []
        entry = await async_init_integration(hass, options)
        patch_solcast_api(entry.runtime_data.coordinator.solcast)
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"

        result = await hass.services.async_call(DOMAIN, SERVICE_DIAGNOSTIC, {}, blocking=True, return_response=True)
        data = result["data"]  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        assert data["overall_status"] == "issues_found"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert any("no generation entities" in issue.lower() for issue in data["issues"])  # pyright: ignore[reportGeneralTypeIssues, reportOptionalIterable, reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        no_error_or_exception(caplog)

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_diagnostic_export_entity_states(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test export entity diagnostics for not found, disabled, unavailable, and OK states."""

    try:
        entity_id = "sensor.test_export_entity"
        options = copy.deepcopy(DEFAULT_INPUT1)
        options[SITE_EXPORT_ENTITY] = entity_id
        entry = await async_init_integration(hass, options)
        patch_solcast_api(entry.runtime_data.coordinator.solcast)
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"

        result = await hass.services.async_call(DOMAIN, SERVICE_DIAGNOSTIC, {}, blocking=True, return_response=True)
        data = result["data"]  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["overall_status"] == "issues_found"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["export_entity"]["entity_id"] == entity_id  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["export_entity"]["status"] == "not_found"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert any("Export entity" in issue for issue in data["issues"])  # pyright: ignore[reportGeneralTypeIssues, reportOptionalIterable, reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        entity_registry = er.async_get(hass)
        entity_registry.async_get_or_create(
            "sensor",
            "pytest",
            "test_export_entity",
            config_entry=entry,
            suggested_object_id="test_export_entity",
        )

        entity_registry.async_update_entity(entity_id, disabled_by=RegistryEntryDisabler.USER)
        await hass.async_block_till_done()
        result = await hass.services.async_call(DOMAIN, SERVICE_DIAGNOSTIC, {}, blocking=True, return_response=True)
        data = result["data"]  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["overall_status"] == "issues_found"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["export_entity"]["entity_id"] == entity_id  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["export_entity"]["status"] == "disabled"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        entity_registry.async_update_entity(entity_id, disabled_by=None)
        await hass.async_block_till_done()
        hass.states.async_set(entity_id, "unavailable")
        await hass.async_block_till_done()
        result = await hass.services.async_call(DOMAIN, SERVICE_DIAGNOSTIC, {}, blocking=True, return_response=True)
        data = result["data"]  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["export_entity"]["entity_id"] == entity_id  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["export_entity"]["status"] == "unavailable"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        hass.states.async_set(entity_id, "42.5")
        await hass.async_block_till_done()
        result = await hass.services.async_call(DOMAIN, SERVICE_DIAGNOSTIC, {}, blocking=True, return_response=True)
        data = result["data"]  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["export_entity"]["entity_id"] == entity_id  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["export_entity"]["status"] == "ok"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        no_error_or_exception(caplog)

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_diagnostic_api_and_cache_issues(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that self-test detects API quota exhaustion, failures, and missing cache."""

    try:
        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        solcast: SolcastApi = patch_solcast_api(entry.runtime_data.coordinator.solcast)
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"

        original_used = solcast.api_used.copy()
        original_failure = solcast.data["failure"][LAST_24H]
        original_filename = solcast.filename
        for key in solcast.api_used:
            solcast.api_used[key] = solcast.api_limit
        solcast.data["failure"][LAST_24H] = 3
        solcast.filename = "/nonexistent/path/forecast.json"

        result = await hass.services.async_call(DOMAIN, SERVICE_DIAGNOSTIC, {}, blocking=True, return_response=True)
        data = result["data"]  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        assert data["overall_status"] == "issues_found"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert any("quota exhausted" in issue.lower() for issue in data["issues"])  # pyright: ignore[reportGeneralTypeIssues, reportOptionalIterable, reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert any("failure" in issue.lower() for issue in data["issues"])  # pyright: ignore[reportGeneralTypeIssues, reportOptionalIterable, reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert any("cache file missing" in issue.lower() for issue in data["issues"])  # pyright: ignore[reportGeneralTypeIssues, reportOptionalIterable, reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["api"][API_REMAINING] == 0  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        solcast.api_used = original_used
        solcast.data["failure"][LAST_24H] = original_failure
        solcast.filename = original_filename

        no_error_or_exception(caplog)

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_diagnostic_no_sites(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that self-test detects no sites configured."""

    try:
        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        solcast: SolcastApi = patch_solcast_api(entry.runtime_data.coordinator.solcast)
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"

        original_sites = solcast.sites
        solcast.sites = []

        result = await hass.services.async_call(DOMAIN, SERVICE_DIAGNOSTIC, {}, blocking=True, return_response=True)
        data = result["data"]  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        assert data["overall_status"] == "issues_found"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert any("no sites" in issue.lower() for issue in data["issues"])  # pyright: ignore[reportGeneralTypeIssues, reportOptionalIterable, reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["sites"] == []  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        solcast.sites = original_sites

        no_error_or_exception(caplog)

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_diagnostic_recorder_unavailable(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that self-test detects recorder unavailable with auto-dampening."""

    try:
        options = copy.deepcopy(DEFAULT_INPUT1)
        options[AUTO_DAMPEN] = True
        options[GENERATION_ENTITIES] = []
        entry = await async_init_integration(hass, options)
        patch_solcast_api(entry.runtime_data.coordinator.solcast)
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"

        original_contains = hass.config.components.__contains__

        def mock_contains(item: str) -> bool:
            if item == "recorder":
                return False
            return original_contains(item)

        with unittest.mock.patch.object(type(hass.config.components), "__contains__", side_effect=mock_contains):
            result = await hass.services.async_call(DOMAIN, SERVICE_DIAGNOSTIC, {}, blocking=True, return_response=True)
        data = result["data"]  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        assert data["overall_status"] == "issues_found"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["recorder_available"] is False, "Expected recorder_available to be False"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert any("recorder" in issue.lower() for issue in data["issues"])  # pyright: ignore[reportGeneralTypeIssues, reportOptionalIterable, reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        no_error_or_exception(caplog)

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_diagnostic_stale_forecast_and_actuals_health(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that the diagnostic reports stale forecast and actuals health."""

    try:
        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        solcast: SolcastApi = patch_solcast_api(entry.runtime_data.coordinator.solcast)
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"

        stale_time = solcast.dt_helper.day_start_utc(future=-2)
        solcast.data[LAST_UPDATED] = stale_time
        solcast.data[LAST_ATTEMPT] = stale_time
        solcast.data[AUTO_UPDATED] = 1
        solcast.data_actuals[LAST_UPDATED] = stale_time
        solcast.data_actuals[LAST_ATTEMPT] = stale_time
        solcast.data_actuals[SITE_INFO] = {}

        result = await hass.services.async_call(DOMAIN, SERVICE_DIAGNOSTIC, {}, blocking=True, return_response=True)
        data = result["data"]  # pyright: ignore[reportOptionalSubscript]

        assert data["overall_status"] == "issues_found"  # type: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["forecast_health"]["status"] == "stale"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["actuals_health"]["status"] == "missing"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert any("Forecast data is stale" in issue for issue in data["issues"])  # type: ignore[reportGeneralTypeIssues, reportOptionalIterable, reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert any("actuals data" in issue.lower() for issue in data["issues"])  # type: ignore[reportGeneralTypeIssues, reportOptionalIterable, reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        configured_site_ids = {site[RESOURCE_ID] for site in solcast.sites}
        solcast.data[LAST_UPDATED] = dt.fromtimestamp(0, datetime.UTC)
        solcast.data[LAST_ATTEMPT] = dt.fromtimestamp(0, datetime.UTC)
        solcast.data[AUTO_UPDATED] = 0
        solcast.data_actuals[LAST_UPDATED] = stale_time
        solcast.data_actuals[LAST_ATTEMPT] = stale_time
        solcast.data_actuals[SITE_INFO] = {site_id: {FORECASTS: [{}]} for site_id in configured_site_ids}

        result = await hass.services.async_call(DOMAIN, SERVICE_DIAGNOSTIC, {}, blocking=True, return_response=True)
        data = result["data"]  # pyright: ignore[reportOptionalSubscript]

        assert data["forecast_health"]["status"] == "missing"  # type: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["actuals_health"]["status"] == "stale"  # type: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert any("Forecast data has not been fetched yet" in issue for issue in data["issues"])  # type: ignore[reportGeneralTypeIssues, reportOptionalIterable, reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert any("Estimated actuals data is stale" in issue for issue in data["issues"])  # type: ignore[reportGeneralTypeIssues, reportOptionalIterable, reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        no_error_or_exception(caplog)

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_diagnostic_empty_actuals_site_data_reports_missing(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that empty actuals forecast lists are treated as missing data."""

    try:
        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        solcast: SolcastApi = patch_solcast_api(entry.runtime_data.coordinator.solcast)

        stale_time = solcast.dt_helper.day_start_utc(future=-2)
        configured_site_ids = {site[RESOURCE_ID] for site in solcast.sites}
        solcast.data_actuals[LAST_UPDATED] = stale_time
        solcast.data_actuals[LAST_ATTEMPT] = stale_time
        solcast.data_actuals[SITE_INFO] = {site_id: {FORECASTS: []} for site_id in configured_site_ids}

        result = await hass.services.async_call(DOMAIN, SERVICE_DIAGNOSTIC, {}, blocking=True, return_response=True)
        data = result["data"]  # pyright: ignore[reportOptionalSubscript]

        assert data["actuals_health"]["status"] == "missing"  # type: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["actuals_health"]["site_data_present"] is False  # type: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert any("no actuals data is available" in issue.lower() for issue in data["issues"])  # type: ignore[reportGeneralTypeIssues, reportOptionalIterable, reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        no_error_or_exception(caplog)

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_diagnostic_usage_status_and_excluded_sites(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that the diagnostic reports usage status and invalid excluded sites."""

    try:
        options = copy.deepcopy(DEFAULT_INPUT1)
        options[EXCLUDE_SITES] = ["missing-site-id"]
        entry = await async_init_integration(hass, options)
        solcast: SolcastApi = patch_solcast_api(entry.runtime_data.coordinator.solcast)
        solcast.usage_status = LoadStatus.ERROR
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"

        result = await hass.services.async_call(DOMAIN, SERVICE_DIAGNOSTIC, {}, blocking=True, return_response=True)
        data = result["data"]  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        assert data["api"]["usage_status"] == "ERROR"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["usage_health"]["status"] == "ERROR"  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["usage_health"]["ok"] is False  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["excluded_sites"]["all_valid"] is False  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert data["excluded_sites"]["unknown_sites"] == ["missing-site-id"]  # pyright: ignore[reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]
        assert any("Excluded sites are not configured" in issue for issue in data["issues"])  # pyright: ignore[reportGeneralTypeIssues, reportOptionalIterable, reportOptionalSubscript, reportIndexIssue, reportArgumentType, reportCallIssue]

        no_error_or_exception(caplog)

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"
