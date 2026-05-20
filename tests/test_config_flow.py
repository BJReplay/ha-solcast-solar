"""Test the Solcast Solar config flow."""

import asyncio
import copy
import json
import logging
from pathlib import Path
import re
from typing import Any
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant import config_entries
from homeassistant.components.recorder import Recorder
import homeassistant.components.solcast_solar as solcast_module

# As a core component, these imports would be homeassistant.components.solcast_solar and not config.custom_components.solcast_solar
from homeassistant.components.solcast_solar.config_flow import (
    CONFIG_DAMP,
    SolcastSolarFlowHandler,
    SolcastSolarOptionFlowHandler,
    _async_is_allow_exceed_api_limit,
)
from homeassistant.components.solcast_solar.const import (
    ADVANCED_ALLOW_EXCEED_API_LIMIT_MAXIMUM,
    ADVANCED_API_RAISE_ISSUES,
    ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_CONFIGURATION,
    ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_EXCLUDE,
    ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_MINIMUM_HISTORY_DAYS,
    ADVANCED_AUTOMATED_DAMPENING_GENERATION_FETCH_DELAY,
    ADVANCED_AUTOMATED_DAMPENING_GENERATION_HISTORY_LOAD_DAYS,
    ADVANCED_AUTOMATED_DAMPENING_IGNORE_INTERVALS,
    ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR,
    ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR_ADJUSTED,
    ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_GENERATION,
    ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_INTERVALS,
    ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS,
    ADVANCED_AUTOMATED_DAMPENING_NO_DELTA_ADJUSTMENT,
    ADVANCED_AUTOMATED_DAMPENING_NO_LIMITING_CONSISTENCY,
    ADVANCED_AUTOMATED_DAMPENING_SIMILAR_PEAK,
    ADVANCED_AUTOMATED_DAMPENING_SUPPRESSION_ENTITY,
    ADVANCED_ENTITY_LOGGING,
    ADVANCED_ESTIMATED_ACTUALS_FETCH_DELAY,
    ADVANCED_ESTIMATED_ACTUALS_LOG_APE_PERCENTILES,
    ADVANCED_ESTIMATED_ACTUALS_LOG_MAPE_BREAKDOWN,
    ADVANCED_FORECAST_DAY_ENTITIES,
    ADVANCED_FORECAST_FUTURE_DAYS,
    ADVANCED_GRANULAR_DAMPENING_DELTA_ADJUSTMENT,
    ADVANCED_HISTORY_MAX_DAYS,
    ADVANCED_INVALID_JSON_TASK,
    ADVANCED_OPTION,
    ADVANCED_RELOAD_ON_ADVANCED_CHANGE,
    ADVANCED_SOLCAST_PORT,
    ADVANCED_SOLCAST_URL,
    ADVANCED_TRIGGER_ON_API_AVAILABLE,
    ADVANCED_TRIGGER_ON_API_UNAVAILABLE,
    AFFIRMATION_REAUTH_SUCCESSFUL,
    AFFIRMATION_RECONFIGURED,
    API_LIMIT,
    AUTO_DAMPEN,
    AUTO_UPDATE,
    BRK_ESTIMATE,
    BRK_ESTIMATE10,
    BRK_ESTIMATE90,
    BRK_HALFHOURLY,
    BRK_HOURLY,
    BRK_SITE,
    BRK_SITE_DETAILED,
    CONFIG_DISCRETE_NAME,
    CONFIG_FOLDER_DISCRETE,
    CONFIG_VERSION,
    CUSTOM_HOURS,
    DAILY_LIMIT,
    DAILY_LIMIT_CONSUMED,
    DEFAULT_DAMPENING_SUPPRESSION_ENTITY,
    DEFAULT_SOLCAST_HTTPS_URL,
    DOMAIN,
    EXCEPTION_ACTUALS_WITHOUT_GET,
    EXCEPTION_API_DUPLICATE,
    EXCEPTION_API_LOOKS_LIKE_SITE,
    EXCEPTION_CUSTOM_INVALID,
    EXCEPTION_DAMPEN_WITHOUT_ACTUALS,
    EXCEPTION_DAMPEN_WITHOUT_GENERATION,
    EXCEPTION_EXPORT_MULTIPLE_ENTITIES,
    EXCEPTION_EXPORT_NO_ENTITY,
    EXCEPTION_HARD_NOT_POSITIVE_NUMBER,
    EXCEPTION_HARD_TOO_MANY,
    EXCEPTION_LIMIT_EXCEEDS_MAXIMUM,
    EXCEPTION_LIMIT_NOT_NUMBER,
    EXCEPTION_LIMIT_ONE_OR_GREATER,
    EXCEPTION_LIMIT_TOO_MANY,
    EXCEPTION_SINGLE_INSTANCE_ALLOWED,
    EXCLUDE_SITES,
    GENERATION_ENTITIES,
    GET_ACTUALS,
    HARD_LIMIT,
    HARD_LIMIT_API,
    ISSUE_ADVANCED_DEPRECATED,
    ISSUE_ADVANCED_PROBLEM,
    KEY_ESTIMATE,
    PROBLEMS,
    RESET,
    SITE_DAMP,
    SITE_EXPORT_ENTITY,
    SITE_EXPORT_LIMIT,
    TASK_WATCH_ADVANCED_FILE_CHANGE,
    TITLE,
    USE_ACTUALS,
)
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.solcastapi import SitesStatus, SolcastApi
from homeassistant.components.solcast_solar.util import HistoryType
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from . import (
    DEFAULT_INPUT1,
    DEFAULT_INPUT1_NO_DAMP,
    DEFAULT_INPUT2,
    KEY1,
    KEY2,
    MOCK_BUSY,
    MOCK_EXCEPTION,
    MOCK_FORBIDDEN,
    aioresponses_change_url,
    async_cleanup_integration_caches,
    async_cleanup_integration_tests,
    async_init_integration,
    async_setup_aioresponses,
    session_clear,
    session_set,
    set_presumed_dead,
    simulator,
)

from tests.common import MockConfigEntry

_LOGGER = logging.getLogger(__name__)

# Keep config flow tests on one xdist worker to reduce scheduling variance
# and shared-state side effects across workers.
pytestmark = pytest.mark.xdist_group("solcast_config_flow")

API_KEY1 = "65sa6d46-sadf876_sd54"
API_KEY2 = "65sa6946-glad876_pf69"

DEFAULT_INPUT1_COPY = copy.deepcopy(DEFAULT_INPUT1)
DEFAULT_INPUT1_COPY[CONF_API_KEY] = API_KEY1

DEFAULT_INPUT2_COPY = copy.deepcopy(DEFAULT_INPUT2)
DEFAULT_INPUT2_COPY[CONF_API_KEY] = API_KEY1 + "," + API_KEY2

MOCK_ENTRY1 = MockConfigEntry(domain=DOMAIN, data={}, options=DEFAULT_INPUT1_COPY)
MOCK_ENTRY2 = MockConfigEntry(domain=DOMAIN, data={}, options=DEFAULT_INPUT2_COPY)

TEST_API_KEY: list[tuple[Any, Any]] = [
    ({CONF_API_KEY: "1234-5678-8765-4321", API_LIMIT: "10", AUTO_UPDATE: "1"}, EXCEPTION_API_LOOKS_LIKE_SITE),
    ({CONF_API_KEY: KEY1 + "," + KEY1, API_LIMIT: "10", AUTO_UPDATE: "1"}, EXCEPTION_API_DUPLICATE),
    ({CONF_API_KEY: KEY1, API_LIMIT: "10", AUTO_UPDATE: "0"}, None),
    ({CONF_API_KEY: KEY1, API_LIMIT: "10", AUTO_UPDATE: "1"}, None),
    ({CONF_API_KEY: KEY1 + "," + KEY2, API_LIMIT: "10", AUTO_UPDATE: "2"}, None),
    ({CONF_API_KEY: KEY1 + "," + KEY2, API_LIMIT: "0", AUTO_UPDATE: "2"}, EXCEPTION_LIMIT_ONE_OR_GREATER),
]

TEST_REAUTH_API_KEY: list[tuple[Any, Any]] = [
    ({CONF_API_KEY: "1234-5678-8765-4321"}, EXCEPTION_API_LOOKS_LIKE_SITE),
    ({CONF_API_KEY: KEY1 + "," + KEY1}, EXCEPTION_API_DUPLICATE),
    ({CONF_API_KEY: "555"}, "Bad API key, 403/Forbidden"),
    ({CONF_API_KEY: KEY1 + "," + KEY2}, None),
]

TEST_KEY_CHANGES: list[tuple[Any, Any, str | None, list[str]]] = [
    (
        None,
        {CONF_API_KEY: "555", API_LIMIT: "10", AUTO_UPDATE: "1"},
        "Bad API key, 403/Forbidden",
        ["component.solcast_solar.config.error.Bad API key, 403/Forbidden returned for ******555"],
    ),
    (
        None,
        {CONF_API_KEY: "no_sites", API_LIMIT: "10", AUTO_UPDATE: "1"},
        "No sites for the API key",
        ["component.solcast_solar.config.error.No sites for the API key ******_sites are configured at solcast.com"],
    ),
    (
        MOCK_BUSY,
        {CONF_API_KEY: "1", API_LIMIT: "10", AUTO_UPDATE: "1"},
        "Error 429/Try again later for API key",
        ["component.solcast_solar.config.error.Error 429/Try again later for API key ******1"],
    ),
    (
        MOCK_EXCEPTION,
        {CONF_API_KEY: "2", API_LIMIT: "10", AUTO_UPDATE: "1"},
        None,
        [],
    ),
    (
        None,
        {CONF_API_KEY: "1", API_LIMIT: "10", AUTO_UPDATE: "1"},
        None,
        [],
    ),
]

TEST_API_LIMIT: list[tuple[dict[Any, Any], dict[Any, Any], str | None]] = [
    (DEFAULT_INPUT1, {CONF_API_KEY: KEY1, API_LIMIT: "invalid", AUTO_UPDATE: "1"}, EXCEPTION_LIMIT_NOT_NUMBER),
    (DEFAULT_INPUT1, {CONF_API_KEY: KEY1, API_LIMIT: "0", AUTO_UPDATE: "1"}, EXCEPTION_LIMIT_ONE_OR_GREATER),
    (DEFAULT_INPUT1, {CONF_API_KEY: KEY1, API_LIMIT: "51", AUTO_UPDATE: "1"}, EXCEPTION_LIMIT_EXCEEDS_MAXIMUM),
    (DEFAULT_INPUT1, {CONF_API_KEY: KEY1, API_LIMIT: "10,10", AUTO_UPDATE: "1"}, EXCEPTION_LIMIT_TOO_MANY),
    (DEFAULT_INPUT1, {CONF_API_KEY: KEY1, API_LIMIT: "10", AUTO_UPDATE: "1"}, None),
    (DEFAULT_INPUT2, {CONF_API_KEY: KEY1 + "," + KEY2, API_LIMIT: "10,10", AUTO_UPDATE: "1"}, None),
    (DEFAULT_INPUT2, {CONF_API_KEY: KEY1 + "," + KEY2, API_LIMIT: "10,10,10", AUTO_UPDATE: "1"}, EXCEPTION_LIMIT_TOO_MANY),
    (DEFAULT_INPUT2, {CONF_API_KEY: KEY1 + "," + KEY2, API_LIMIT: "10", AUTO_UPDATE: "1"}, None),
]


async def test_single_instance(
    recorder_mock: Recorder,
    hass: HomeAssistant,
) -> None:
    """Test allow a single config only."""
    MockConfigEntry(domain=DOMAIN).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result.get("type") is FlowResultType.ABORT
    assert result.get("reason") == EXCEPTION_SINGLE_INSTANCE_ALLOWED


async def test_create_entry(hass: HomeAssistant) -> None:
    """Test that a valid user input creates an entry."""

    await async_setup_aioresponses()

    flow = SolcastSolarFlowHandler()
    flow.hass = hass

    expected_options: dict[str, Any] = {
        CONF_API_KEY: KEY1,
        API_LIMIT: "10",
        AUTO_UPDATE: 1,
        CUSTOM_HOURS: 1,
        HARD_LIMIT_API: "100.0",
        KEY_ESTIMATE: "estimate",
        BRK_ESTIMATE: True,
        BRK_ESTIMATE10: True,
        BRK_ESTIMATE90: True,
        BRK_SITE: True,
        BRK_HALFHOURLY: True,
        BRK_HOURLY: True,
        BRK_SITE_DETAILED: False,
        EXCLUDE_SITES: [],
    }

    user_input = {CONF_API_KEY: KEY1, API_LIMIT: "10", AUTO_UPDATE: "1"}
    result = await flow.async_step_user(user_input)
    assert result.get("type") == FlowResultType.CREATE_ENTRY
    assert result.get("title") == TITLE
    assert result.get("data") == {}
    for key, expect in expected_options.items():
        assert result.get("options", {}).get(key) == expect


@pytest.mark.parametrize(("user_input", "reason"), TEST_API_KEY)
async def test_init_api_key(hass: HomeAssistant, user_input: dict[str, Any], reason: str | None) -> None:
    """Test that valid/invalid API key is handled in config flow."""

    flow = SolcastSolarFlowHandler()
    flow.hass = hass

    result = await flow.async_step_user()
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "user"
    result = await flow.async_step_user(user_input)
    if reason is not None:
        assert result["errors"]["base"] == reason  # type: ignore[index]


async def test_config_api_key_invalid(hass: HomeAssistant) -> None:
    """Test that invalid API key is handled in config flow."""

    await async_setup_aioresponses()

    flow = SolcastSolarFlowHandler()
    flow.hass = hass

    result = await flow.async_step_user({CONF_API_KEY: "555", API_LIMIT: "10", AUTO_UPDATE: "1"})
    assert "Bad API key, 403/Forbidden" in result["errors"]["base"]  # type: ignore[index]

    result = await flow.async_step_user({CONF_API_KEY: "no_sites", API_LIMIT: "10", AUTO_UPDATE: "1"})
    assert "No sites for the API key" in result["errors"]["base"]  # type: ignore[index]

    session_set(MOCK_BUSY)
    result = await flow.async_step_user({CONF_API_KEY: "1", API_LIMIT: "10", AUTO_UPDATE: "1"})
    assert "Error 429/Try again later for API key" in result["errors"]["base"]  # type: ignore[index]
    session_clear(MOCK_BUSY)


@pytest.mark.parametrize(("options", "user_input", "reason"), TEST_API_LIMIT)
async def test_config_api_quota(hass: HomeAssistant, options: dict[str, Any], user_input: dict[str, Any], reason: str | None) -> None:
    """Test that valid/invalid API quota is handled in config flow."""

    flow = SolcastSolarFlowHandler()
    flow.hass = hass

    result = await flow.async_step_user()
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "user"
    result = await flow.async_step_user(user_input)
    if reason is not None:
        assert result["errors"]["base"] == reason  # type: ignore[index]


@pytest.mark.parametrize(
    "ignore_missing_translations",
    ["component.solcast_solar.config.error.Bad API key, 403/Forbidden returned for ******555"],
)
async def test_reauth_api_key(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that valid/invalid API key is handled in reconfigure.

    Not parameterised for performance reasons and to maintain caches between tests.
    """
    try:
        USER_INPUT = 0
        REASON = 1

        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"

        for test in TEST_REAUTH_API_KEY:
            result = await entry.start_reauth_flow(hass)
            assert result.get("type") is FlowResultType.FORM
            assert result.get("step_id") == "reauth_confirm"
            result = await hass.config_entries.flow.async_configure(  # pyright: ignore[reportUnknownMemberType]
                result["flow_id"],
                user_input=test[USER_INPUT],
            )
            await hass.async_block_till_done()
            if result.get("reason") != AFFIRMATION_REAUTH_SUCCESSFUL:
                assert test[REASON] in result["errors"]["base"]  # type: ignore[index]

        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

        # Really change key '1' (last test above used API keys '1' and '2', so these are in cached sites/usage)
        entry = await async_init_integration(hass, DEFAULT_INPUT2)
        simulator.API_KEY_SITES["4"] = simulator.API_KEY_SITES.pop("1")  # Change the key
        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(  # pyright: ignore[reportUnknownMemberType]
            result["flow_id"],
            user_input={CONF_API_KEY: "4" + "," + KEY2},
        )
        await hass.async_block_till_done()
        assert result.get("reason") == AFFIRMATION_REAUTH_SUCCESSFUL
        assert "An API key has changed, resetting usage" not in caplog.text  # Existing key change, so not seen
        assert "API key ******4 has changed" in caplog.text
        assert "Using extant cache data for API key ******4" in caplog.text
        assert "API counter for ******4 is 4/20" in caplog.text
        assert "Using extant cache data for API key ******2" not in caplog.text  # Unaffected
        assert "API counter for ******2 is 2/20" in caplog.text  # Unaffected, was 2/20 after previous test
        simulator.API_KEY_SITES["1"] = simulator.API_KEY_SITES.pop("4")  # Restore the key
        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(  # pyright: ignore[reportUnknownMemberType]
            result["flow_id"],
            user_input={CONF_API_KEY: "1" + "," + KEY2},
        )
        await hass.async_block_till_done()

        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

        # Load with an invalid key (will receive 403/Forbidden in get sites call, load cached data and not start)
        session_set(MOCK_FORBIDDEN)
        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        assert "Sites loaded" in caplog.text
        assert "API key is invalid" in caplog.text
        session_clear(MOCK_FORBIDDEN)

        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

        # Test start after reauth when presumed dead...
        simulator.API_KEY_SITES["4"] = simulator.API_KEY_SITES.pop("1")  # Change the key
        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(  # pyright: ignore[reportUnknownMemberType]
            result["flow_id"],
            user_input={CONF_API_KEY: "4" + "," + KEY2},
        )
        assert "Connecting to https://api.solcast.com.au/rooftop_sites?format=json&api_key=******4" in caplog.text
        assert "Loading presumed dead integration" in caplog.text

    finally:
        if simulator.API_KEY_SITES.get("4"):
            simulator.API_KEY_SITES["1"] = simulator.API_KEY_SITES.pop("4")  # Restore the key
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_reconfigure_api_key1(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that valid/invalid API key is handled in reconfigure.

    Not parameterised for performance reasons.
    """
    try:
        USER_INPUT = 0
        REASON = 1

        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"

        for test in TEST_API_KEY:
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
                data=entry.data,
            )
            assert result.get("type") is FlowResultType.FORM
            assert result.get("step_id") == "reconfigure_confirm"
            result = await hass.config_entries.flow.async_configure(  # pyright: ignore[reportUnknownMemberType]
                result["flow_id"],
                user_input=test[USER_INPUT],
            )
            await hass.async_block_till_done()
            if result.get("reason") != AFFIRMATION_RECONFIGURED:
                assert result["errors"]["base"] == test[REASON]  # type: ignore[index]

        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

        # Test start after reconfigure when presumed dead...
        await set_presumed_dead(hass, entry, True)
        simulator.API_KEY_SITES["4"] = simulator.API_KEY_SITES.pop("1")  # Change the key
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id}, data=entry.data
        )
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(  # pyright: ignore[reportUnknownMemberType]
            result["flow_id"], user_input={CONF_API_KEY: "4" + "," + KEY2, API_LIMIT: "10", AUTO_UPDATE: "0"}
        )
        await hass.async_block_till_done()
        assert "Connecting to https://api.solcast.com.au/rooftop_sites?format=json&api_key=******4" in caplog.text
        assert "Loading presumed dead integration" in caplog.text
        simulator.API_KEY_SITES["1"] = simulator.API_KEY_SITES.pop("4")  # Restore the key

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


@pytest.mark.parametrize(("set", "options", "to_assert", "ignore_missing_translations"), TEST_KEY_CHANGES)
async def test_reconfigure_api_key2(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
    set: str,
    options: dict[str, Any],
    to_assert: str,
) -> None:
    """Test that valid/invalid API key is handled in reconfigure."""

    try:
        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"

        if set == MOCK_EXCEPTION:
            await async_cleanup_integration_caches(hass)
        flow = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
            data=entry.data,
        )
        await hass.async_block_till_done()
        if set and set != MOCK_EXCEPTION:
            session_set(set)
        result = await hass.config_entries.flow.async_configure(  # pyright: ignore[reportUnknownMemberType]
            flow["flow_id"],
            user_input=options,
        )
        if set == MOCK_EXCEPTION:
            aioresponses_change_url(
                re.compile(r"https://api\.solcast\.com\.au/rooftop_sites\?.*api_key=.*$"),
                re.compile(r"https://api\.solcastxxxx\.com\.au/rooftop_sites\?.*api_key=.*$"),
            )
        await hass.async_block_till_done()

        if set:
            session_clear(set)
        if set == MOCK_EXCEPTION:
            assert "Error retrieving sites" in caplog.text
            assert "Attempting to continue" in caplog.text
            assert "Sites loaded" in caplog.text
        if to_assert:
            assert to_assert in result["errors"]["base"]  # type: ignore[index]
        else:
            assert result.get("reason") == AFFIRMATION_RECONFIGURED

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_reconfigure_api_quota(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that valid/invalid API quota is handled in reconfigure.

    Not parameterised for performance reasons.
    """
    try:
        OPTIONS = 0
        USER_INPUT = 1
        REASON = 2

        _input = None
        for test in TEST_API_LIMIT:
            entry = await async_init_integration(hass, test[OPTIONS])  # type: ignore[arg-type]
            assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"
            if _input is None or test[OPTIONS] != _input:
                _input = copy.deepcopy(test[OPTIONS])
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
                data=entry.data,
            )
            await hass.async_block_till_done()
            assert result.get("type") == FlowResultType.FORM
            assert result.get("step_id") == "reconfigure_confirm"
            result = await hass.config_entries.flow.async_configure(  # pyright: ignore[reportUnknownMemberType]
                result["flow_id"],
                user_input=test[USER_INPUT],  # type: ignore[arg-type]
            )
            await hass.async_block_till_done()
            if test[REASON]:
                assert result["errors"]["base"] == test[REASON]  # type: ignore[index]

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


@pytest.mark.parametrize(("user_input", "reason"), TEST_API_KEY)
async def test_options_api_key(hass: HomeAssistant, user_input: dict[str, Any], reason: str | None) -> None:
    """Test that valid/invalid API key is handled in option flow init."""

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1)
    flow.hass = hass

    result = await flow.async_step_init()
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "init"
    result = await flow.async_step_init(user_input)
    if reason is not None:
        assert result["errors"]["base"] == reason  # type: ignore[index]


async def test_options_api_key_invalid(hass: HomeAssistant) -> None:
    """Test that invalid API key is handled in options flow."""

    await async_setup_aioresponses()

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1)
    flow.hass = hass

    options = DEFAULT_INPUT1.copy()
    options[SITE_EXPORT_ENTITY] = [options[SITE_EXPORT_ENTITY]]

    inject = {CONF_API_KEY: "555"}
    result = await flow.async_step_init({**options, **inject})
    assert "Bad API key, 403/Forbidden" in result["errors"]["base"]  # type: ignore[index]

    inject = {CONF_API_KEY: "no_sites"}
    result = await flow.async_step_init({**options, **inject})
    assert "No sites for the API key" in result["errors"]["base"]  # type: ignore[index]

    session_set(MOCK_BUSY)
    result = await flow.async_step_init(options)
    assert "Error 429/Try again later for API key" in result["errors"]["base"]  # type: ignore[index]
    session_clear(MOCK_BUSY)


@pytest.mark.parametrize(("options", "user_input", "reason"), TEST_API_LIMIT)
async def test_options_api_quota(hass: HomeAssistant, options: dict[str, Any], user_input: dict[str, Any], reason: str | None) -> None:
    """Test that valid/invalid API quota is handled in option flow init."""

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1)
    flow.hass = hass

    result = await flow.async_step_init()
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "init"
    result = await flow.async_step_init({**options, **user_input})
    if reason is not None:
        assert result["errors"]["base"] == reason  # type: ignore[index]


async def test_allow_exceed_api_limit_advanced_option_enabled(hass: HomeAssistant) -> None:
    """Test advanced option enables exceeding API limit maximum."""

    config_dir = Path(hass.config.config_dir)
    advanced_dir = config_dir / CONFIG_DISCRETE_NAME if CONFIG_FOLDER_DISCRETE else config_dir
    advanced_dir.mkdir(parents=True, exist_ok=True)
    advanced_file = advanced_dir / "solcast-advanced.json"
    advanced_file.write_text(json.dumps({ADVANCED_ALLOW_EXCEED_API_LIMIT_MAXIMUM: True}), encoding="utf-8")

    assert await _async_is_allow_exceed_api_limit(hass), "API limit exceed should be allowed"


async def test_allow_exceed_api_limit_advanced_option_invalid_json(hass: HomeAssistant) -> None:
    """Test invalid advanced options JSON defaults to not allowing exceed."""

    config_dir = Path(hass.config.config_dir)
    advanced_dir = config_dir / CONFIG_DISCRETE_NAME if CONFIG_FOLDER_DISCRETE else config_dir
    advanced_dir.mkdir(parents=True, exist_ok=True)
    advanced_file = advanced_dir / "solcast-advanced.json"
    advanced_file.write_text('{"bad_json":', encoding="utf-8")

    assert not await _async_is_allow_exceed_api_limit(hass), "API limit exceed should not be allowed"


async def test_allow_exceed_api_limit_advanced_option_not_dict(hass: HomeAssistant) -> None:
    """Test that a non-dict advanced options JSON defaults to not allowing exceed."""

    config_dir = Path(hass.config.config_dir)
    advanced_dir = config_dir / CONFIG_DISCRETE_NAME if CONFIG_FOLDER_DISCRETE else config_dir
    advanced_dir.mkdir(parents=True, exist_ok=True)
    advanced_file = advanced_dir / "solcast-advanced.json"
    advanced_file.write_text(json.dumps([True]), encoding="utf-8")

    assert not await _async_is_allow_exceed_api_limit(hass), "API limit exceed should not be allowed"


async def test_allow_exceed_api_limit_advanced_option_not_boolean(hass: HomeAssistant) -> None:
    """Test that a non-boolean override value defaults to not allowing exceed."""

    config_dir = Path(hass.config.config_dir)
    advanced_dir = config_dir / CONFIG_DISCRETE_NAME if CONFIG_FOLDER_DISCRETE else config_dir
    advanced_dir.mkdir(parents=True, exist_ok=True)
    advanced_file = advanced_dir / "solcast-advanced.json"
    advanced_file.write_text(json.dumps({ADVANCED_ALLOW_EXCEED_API_LIMIT_MAXIMUM: "true"}), encoding="utf-8")

    assert not await _async_is_allow_exceed_api_limit(hass), "API limit exceed should not be allowed"


@pytest.mark.parametrize(
    ("options", "value", "reason"),
    [
        ((DEFAULT_INPUT1, 0, EXCEPTION_CUSTOM_INVALID)),
        ((DEFAULT_INPUT1, 145, EXCEPTION_CUSTOM_INVALID)),
        ((DEFAULT_INPUT1, 8, None)),
    ],
)
async def test_options_custom_hour_sensor(hass: HomeAssistant, options: dict[str, Any], value: int, reason: str | None) -> None:
    """Test that valid/invalid custom hour sensor is handled."""

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1)
    flow.hass = hass

    user_input = copy.deepcopy(options)
    user_input[CUSTOM_HOURS] = value
    result = await flow.async_step_init(user_input)
    if reason is not None:
        assert result["errors"]["base"] == reason  # type: ignore[index]


@pytest.mark.parametrize(
    ("options", "value", "reason"),
    [
        ((DEFAULT_INPUT1, "invalid", EXCEPTION_HARD_NOT_POSITIVE_NUMBER)),
        ((DEFAULT_INPUT1, "-1", EXCEPTION_HARD_NOT_POSITIVE_NUMBER)),
        ((DEFAULT_INPUT1, "6,6.0", EXCEPTION_HARD_TOO_MANY)),
        ((DEFAULT_INPUT1, "6", None)),
        ((DEFAULT_INPUT2, "6,6.0", None)),
        ((DEFAULT_INPUT2, "6", None)),
        ((DEFAULT_INPUT2, "0", None)),
    ],
)
async def test_options_hard_limit(hass: HomeAssistant, options: dict[str, Any], value: str, reason: str | None) -> None:
    """Test that valid/invalid hard limit is handled."""

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1 if options == DEFAULT_INPUT1 else MOCK_ENTRY2)
    flow.hass = hass
    user_input = copy.deepcopy(options)
    user_input[HARD_LIMIT_API] = value
    user_input[SITE_EXPORT_ENTITY] = []
    result = await flow.async_step_init(user_input)
    if reason is not None:
        assert result["errors"]["base"] == reason  # type: ignore[index]


@pytest.mark.parametrize(
    ("options", "reason"),
    [
        (({GET_ACTUALS: False, USE_ACTUALS: 1, SITE_EXPORT_ENTITY: []}, EXCEPTION_ACTUALS_WITHOUT_GET)),
        (({AUTO_DAMPEN: True, GET_ACTUALS: False, SITE_EXPORT_ENTITY: []}, EXCEPTION_DAMPEN_WITHOUT_ACTUALS)),
        (({AUTO_DAMPEN: True, GET_ACTUALS: True, GENERATION_ENTITIES: [], SITE_EXPORT_ENTITY: []}, EXCEPTION_DAMPEN_WITHOUT_GENERATION)),
        (({SITE_EXPORT_ENTITY: ["entity.one", "entity.two"]}, EXCEPTION_EXPORT_MULTIPLE_ENTITIES)),
        (({SITE_EXPORT_LIMIT: 5, SITE_EXPORT_ENTITY: []}, EXCEPTION_EXPORT_NO_ENTITY)),
    ],
)
async def test_options_auto_dampen(hass: HomeAssistant, options: dict[str, Any], reason: str | None) -> None:
    """Test that valid/invalid auto-dampen settings are handled."""

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1)
    flow.hass = hass
    user_input = copy.deepcopy(DEFAULT_INPUT1) | options
    result = await flow.async_step_init(user_input)
    assert result["errors"]["base"] == reason  # type: ignore[index]


async def test_step_to_dampen(hass: HomeAssistant) -> None:
    """Test opening the dampening step."""

    user_input = copy.deepcopy(DEFAULT_INPUT1)
    user_input[CONFIG_DAMP] = True
    user_input[SITE_EXPORT_ENTITY] = []

    entry = MockConfigEntry(domain=DOMAIN, data={}, options=user_input)
    flow = SolcastSolarOptionFlowHandler(entry)
    flow.hass = hass
    result = await flow.async_step_init(user_input)
    await hass.async_block_till_done()
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "dampen"


@pytest.mark.parametrize(
    ("value"),
    [
        ({f"damp{factor:02d}": 0.8 for factor in range(24)}),
    ],
)
async def test_dampen(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    value: dict[str, Any],
) -> None:
    """Test dampening step."""

    try:
        user_input: dict[str, Any] = {**copy.deepcopy(DEFAULT_INPUT1), **value}
        entry = await async_init_integration(hass, DEFAULT_INPUT1)

        for key in value:
            assert entry.options[key] == 1.0

        flow = SolcastSolarOptionFlowHandler(entry)
        flow.hass = hass

        result = await flow.async_step_dampen(user_input)
        assert result.get("reason") == AFFIRMATION_RECONFIGURED
        for key, expect in value.items():
            assert entry.options[key] == expect

        assert await hass.config_entries.async_unload(entry.entry_id), "Config entry unload failed"
        await hass.async_block_till_done()

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_entry_options_upgrade(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that entry options are upgraded as expected."""

    START_VERSION = 3
    FINAL_VERSION = 19
    V3OPTIONS: dict[str, Any] = {
        CONF_API_KEY: "1",
        "const_disableautopoll": False,
    }
    try:
        config_dir = f"{hass.config.config_dir}/{CONFIG_DISCRETE_NAME}" if CONFIG_FOLDER_DISCRETE else hass.config.config_dir
        entry = await async_init_integration(hass, copy.deepcopy(V3OPTIONS), version=START_VERSION)
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"

        assert entry.version == FINAL_VERSION
        # V4
        assert entry.options.get("const_disableautopoll") is None, "Expected option const_disableautopoll to be removed"
        # V5
        for a in range(24):
            assert entry.options.get(f"damp{a:02d}") == 1.0
        # V6
        assert entry.options.get("customhoursensor") == 1
        # V7
        assert entry.options.get(KEY_ESTIMATE) == "estimate"
        # V8
        assert entry.options.get(BRK_ESTIMATE) is True, "Expected option BRK_ESTIMATE to be True"
        assert entry.options.get(BRK_ESTIMATE10) is True, "Expected option BRK_ESTIMATE10 to be True"
        assert entry.options.get(BRK_ESTIMATE90) is True, "Expected option BRK_ESTIMATE90 to be True"
        assert entry.options.get(BRK_SITE) is True, "Expected option BRK_SITE to be True"
        assert entry.options.get(BRK_HALFHOURLY) is True, "Expected option BRK_HALFHOURLY to be True"
        assert entry.options.get(BRK_HOURLY) is True, "Expected option BRK_HOURLY to be True"
        # V9
        assert entry.options.get("api_quota") == "10"
        # V12
        assert entry.options.get(AUTO_UPDATE) == 0
        assert entry.options.get(BRK_SITE_DETAILED) is False, "Expected option BRK_SITE_DETAILED to be False"
        assert entry.options.get(SITE_DAMP) is False, "Expected option SITE_DAMP to be False"  # "Hidden"-ish option
        # V14
        assert entry.options.get(HARD_LIMIT) is None, "Expected option HARD_LIMIT to be None"
        assert entry.options.get(HARD_LIMIT_API) == "100.0"
        # V15
        assert entry.options.get(EXCLUDE_SITES) == []
        # V18
        assert entry.options.get(SITE_EXPORT_ENTITY) == ""
        assert entry.options.get(GET_ACTUALS) is False, "Expected option GET_ACTUALS to be False"
        assert entry.options.get(USE_ACTUALS) is HistoryType.FORECASTS
        assert entry.options.get(GENERATION_ENTITIES) == []
        assert entry.options.get(SITE_EXPORT_LIMIT) == 0.0
        assert entry.options.get(AUTO_DAMPEN) is False, "Expected option AUTO_DAMPEN to be False"
        # V19
        assert entry.options.get(API_LIMIT) == "10"
        assert entry.options.get(CUSTOM_HOURS) == 1

        assert await hass.config_entries.async_unload(entry.entry_id), "Config entry unload failed"
        await hass.async_block_till_done()

        # Test API limit gets imported from existing cache in upgrade to V9
        data_file = Path(f"{config_dir}/solcast-usage.json")
        data_file.write_text(json.dumps({DAILY_LIMIT: 50, DAILY_LIMIT_CONSUMED: 34, RESET: "2024-01-01T00:00:00+00:00"}), encoding="utf-8")
        entry = await async_init_integration(hass, copy.deepcopy(V3OPTIONS), version=START_VERSION)
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"
        assert entry.options.get("api_quota") == "50"

        assert await hass.config_entries.async_unload(entry.entry_id), "Config entry unload failed"
        await hass.async_block_till_done()

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_presumed_dead_and_full_flow(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test presumption of death by setting "presumed dead" flag, and testing a config change."""

    try:
        entry = await async_init_integration(hass, DEFAULT_INPUT1)

        # Test presumed dead
        caplog.clear()
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"

        option: dict[str, Any] = {BRK_ESTIMATE: False, USE_ACTUALS: "0", SITE_EXPORT_ENTITY: []}
        user_input = DEFAULT_INPUT1_NO_DAMP | option
        await set_presumed_dead(hass, entry, True)
        result = await hass.config_entries.options.async_init(entry.entry_id)
        await hass.async_block_till_done()
        result = await hass.config_entries.options.async_configure(  # pyright: ignore[reportUnknownMemberType]
            result["flow_id"],
            user_input,
        )
        await hass.async_block_till_done()  # Integration will reload
        assert "Integration presumed dead, reloading" in caplog.text
        coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator
        solcast: SolcastApi = coordinator.solcast
        assert solcast.sites_status is SitesStatus.OK, f"Expected sites status SitesStatus.OK, got {solcast.sites_status}"
        assert solcast.loaded_data is True, "Solcast data should be loaded"

        assert await hass.config_entries.async_unload(entry.entry_id), "Config entry unload failed"
        await hass.async_block_till_done()

        # Test dampening step can  be reached
        option = {CONFIG_DAMP: True, USE_ACTUALS: "0", SITE_EXPORT_ENTITY: []}
        user_input = DEFAULT_INPUT1_NO_DAMP | option

        result = await hass.config_entries.options.async_init(entry.entry_id)
        await hass.async_block_till_done()
        result = await hass.config_entries.options.async_configure(  # pyright: ignore[reportUnknownMemberType]
            result["flow_id"],
            user_input,
        )
        await hass.async_block_till_done()
        assert result.get("type") == FlowResultType.FORM

        user_input = {f"damp{factor:02d}": 0.9 for factor in range(24)}
        result = await hass.config_entries.options.async_configure(  # pyright: ignore[reportUnknownMemberType]
            result["flow_id"],
            user_input,
        )
        await hass.async_block_till_done()
        assert result.get("reason") == AFFIRMATION_RECONFIGURED

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_advanced_options(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test setting advanced options."""

    LEAST = 1
    try:
        issue_registry = ir.async_get(hass)

        config_dir = f"{hass.config.config_dir}/{CONFIG_DISCRETE_NAME}" if CONFIG_FOLDER_DISCRETE else hass.config.config_dir
        options = copy.deepcopy(DEFAULT_INPUT1)
        options[GET_ACTUALS] = False
        entry = await async_init_integration(hass, options)
        coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator
        solcast: SolcastApi = coordinator.solcast
        advanced_options_with_aliases, _ = solcast.advanced_opt.advanced_options_with_aliases()

        async def wait():
            for _ in range(2000):
                freezer.tick(0.1)
                await hass.async_block_till_done()

        async def wait_for(text: str):
            async with asyncio.timeout(300):
                while text not in caplog.text:
                    freezer.tick(0.01)
                    await hass.async_block_till_done()

        data_file = Path(f"{config_dir}/solcast-advanced.json")

        caplog.clear()
        data_file.write_text(json.dumps("   \r \r\n"), encoding="utf-8")
        await wait()
        assert "exists" in caplog.text
        assert "is not valid JSON" not in caplog.text
        assert "Advanced option proposed" not in caplog.text
        assert "Advanced option set" not in caplog.text
        assert "Advanced option default set" not in caplog.text
        assert "JSONDecodeError" not in caplog.text
        data_file.unlink()
        await wait()

        caplog.clear()
        data_file.write_text(json.dumps("[]"), encoding="utf-8")
        await wait()
        assert "Advanced options file invalid format, expected JSON `dict`" in caplog.text
        data_file.unlink()
        await wait()

        _LOGGER.debug("Testing advanced options 1")
        data_file_1: dict[str, Any] = {
            ADVANCED_API_RAISE_ISSUES: True,
            ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_CONFIGURATION: False,
            ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_EXCLUDE: [],
            ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_MINIMUM_HISTORY_DAYS: 3,
            ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_INTERVALS: 2,
            ADVANCED_AUTOMATED_DAMPENING_IGNORE_INTERVALS: ["12:00", "12:30", "13:00", "13:30", "14:00", "14:30", "15:00", "15:30"],
            ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR: 0.95,
            ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR_ADJUSTED: 0.95,
            ADVANCED_AUTOMATED_DAMPENING_NO_DELTA_ADJUSTMENT: False,
            ADVANCED_AUTOMATED_DAMPENING_NO_LIMITING_CONSISTENCY: False,
            ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS: 14,
            ADVANCED_AUTOMATED_DAMPENING_GENERATION_FETCH_DELAY: 0,
            ADVANCED_AUTOMATED_DAMPENING_GENERATION_HISTORY_LOAD_DAYS: 7,
            ADVANCED_AUTOMATED_DAMPENING_SIMILAR_PEAK: 0.90,
            ADVANCED_AUTOMATED_DAMPENING_SUPPRESSION_ENTITY: DEFAULT_DAMPENING_SUPPRESSION_ENTITY,
            ADVANCED_ENTITY_LOGGING: True,  # Inconsistent with the rest, detected as removed and reset to default
            ADVANCED_ESTIMATED_ACTUALS_FETCH_DELAY: 0,
            ADVANCED_ESTIMATED_ACTUALS_LOG_APE_PERCENTILES: [50],
            ADVANCED_ESTIMATED_ACTUALS_LOG_MAPE_BREAKDOWN: False,
            ADVANCED_FORECAST_DAY_ENTITIES: 8,
            ADVANCED_FORECAST_FUTURE_DAYS: 14,
            "forecast_history_max_days": 730,  # Intentionally using deprecated name to test aliasing
            ADVANCED_RELOAD_ON_ADVANCED_CHANGE: False,
            ADVANCED_SOLCAST_PORT: 0,
            ADVANCED_SOLCAST_URL: DEFAULT_SOLCAST_HTTPS_URL,
            ADVANCED_TRIGGER_ON_API_AVAILABLE: "",
            ADVANCED_TRIGGER_ON_API_UNAVAILABLE: "",
        }
        caplog.clear()
        data_file.write_text(json.dumps(data_file_1), encoding="utf-8")
        await wait()
        assert "Running task watch_advanced" in caplog.text
        assert "Monitoring" in caplog.text
        for option, value in data_file_1.items():
            if value == advanced_options_with_aliases[option]["default"]:
                assert f"Advanced option set {option}" not in caplog.text
            else:
                if advanced_options_with_aliases[option]["type"] in (ADVANCED_OPTION.FLOAT, ADVANCED_OPTION.INT):
                    assert f"Advanced option proposed {option}: {value}" in caplog.text
                assert f"Advanced option set {option}: {value}" in caplog.text
        assert "Advanced option forecast_history_max_days is deprecated, please use history_max_days" in caplog.text
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_ADVANCED_DEPRECATED) is not None, "Issue ISSUE_ADVANCED_DEPRECATED should exist"

        caplog.clear()

        _LOGGER.debug("Testing advanced options 2")
        data_file_2: dict[str, Any] = {
            ADVANCED_API_RAISE_ISSUES: False,
            ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_CONFIGURATION: 0,
            ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_EXCLUDE: ["wrong", "wrong", "so wrong"],
            ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_MINIMUM_HISTORY_DAYS: 0,
            ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_GENERATION: 0,
            ADVANCED_AUTOMATED_DAMPENING_MINIMUM_MATCHING_INTERVALS: 0,
            ADVANCED_AUTOMATED_DAMPENING_IGNORE_INTERVALS: ["24:00", "12:20", "13:00", "13:00", "14:00", "14:30", "15:00", "15:30"],
            ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR: 1.1,
            ADVANCED_AUTOMATED_DAMPENING_INSIGNIFICANT_FACTOR_ADJUSTED: 1.1,
            ADVANCED_AUTOMATED_DAMPENING_NO_DELTA_ADJUSTMENT: "wrong_type",
            ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS: 21,
            ADVANCED_AUTOMATED_DAMPENING_GENERATION_FETCH_DELAY: -10,
            ADVANCED_AUTOMATED_DAMPENING_GENERATION_HISTORY_LOAD_DAYS: 22,
            ADVANCED_AUTOMATED_DAMPENING_SIMILAR_PEAK: 1.1,
            ADVANCED_AUTOMATED_DAMPENING_SUPPRESSION_ENTITY: 5,
            ADVANCED_ESTIMATED_ACTUALS_FETCH_DELAY: 140,
            ADVANCED_ESTIMATED_ACTUALS_LOG_APE_PERCENTILES: [10, 50, 10, "wrong_type", 0.5],
            ADVANCED_FORECAST_DAY_ENTITIES: 16,
            ADVANCED_FORECAST_FUTURE_DAYS: 16,
            ADVANCED_HISTORY_MAX_DAYS: 10,
            ADVANCED_GRANULAR_DAMPENING_DELTA_ADJUSTMENT: False,
            ADVANCED_RELOAD_ON_ADVANCED_CHANGE: True,
            "unknown_option": True,
            ADVANCED_SOLCAST_PORT: 8443,
            ADVANCED_SOLCAST_URL: "https://localhost",
        }
        data_file.write_text(json.dumps(data_file_2), encoding="utf-8")
        await wait()
        for option, value in data_file_1.items():
            if option in [ADVANCED_RELOAD_ON_ADVANCED_CHANGE, ADVANCED_SOLCAST_PORT, ADVANCED_SOLCAST_URL]:
                continue
            if advanced_options_with_aliases.get(option) is None:
                assert f"Unknown advanced option ignored: {option}" in caplog.text
                issue = issue_registry.async_get_issue(DOMAIN, ISSUE_ADVANCED_PROBLEM)
                if issue is not None:
                    if issue.translation_placeholders is not None:
                        assert "Unknown" in issue.translation_placeholders["errors"]
                    else:
                        pytest.fail("Expected advanced option issue translation placeholders not found")
                else:
                    pytest.fail("Expected unknown advanced option issue not found")
            elif value != advanced_options_with_aliases.get(option, {}).get("default"):
                if advanced_options_with_aliases[option]["type"] in (int, float):
                    assert (
                        f"{option}: {value} (must be {LEAST if 'matching' in option else advanced_options_with_aliases[option]['min']}-{advanced_options_with_aliases[option]['max']})"
                        not in caplog.text
                    )
                elif advanced_options_with_aliases[option]["type"] is bool:
                    assert f"{option}: {value} (must be bool)" not in caplog.text

        assert "Removing advanced deprecation issue" in caplog.text
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_ADVANCED_DEPRECATED) is None, "Issue ISSUE_ADVANCED_DEPRECATED should not exist"
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_ADVANCED_PROBLEM) is not None, "Issue ISSUE_ADVANCED_PROBLEM should exist"
        assert "Advanced option set api_raise_issues: False" in caplog.text
        assert "Advanced option proposed reload_on_advanced_change: True" not in caplog.text
        assert "Advanced option set reload_on_advanced_change: True" in caplog.text
        assert f"Advanced option proposed {ADVANCED_SOLCAST_PORT}: 8443" in caplog.text
        assert f"Advanced option set {ADVANCED_SOLCAST_PORT}: 8443" in caplog.text
        assert "solcast_url: https://localhost" in caplog.text
        assert "Invalid time in advanced option automated_dampening_ignore_intervals: 24:00" in caplog.text
        assert "Invalid time in advanced option automated_dampening_ignore_intervals: 12:20" in caplog.text
        assert "Duplicate time in advanced option automated_dampening_ignore_intervals: 13:00" in caplog.text
        assert "Invalid int in advanced option estimated_actuals_log_ape_percentiles: wrong_type" in caplog.text
        assert "Invalid int in advanced option estimated_actuals_log_ape_percentiles: 0.5" in caplog.text
        assert "Duplicate int in advanced option estimated_actuals_log_ape_percentiles: 10" in caplog.text
        for i in range(3):
            assert f"Invalid entry in automated_dampening_adaptive_model_exclude at index {i}: expected dict, got str" in caplog.text

        assert "Advanced options changed, restarting" in caplog.text
        assert "Start is not stale" in caplog.text

        # Cause an additional error to check issue gets re-raised
        data_file_2[ADVANCED_AUTOMATED_DAMPENING_MODEL_DAYS] = 99
        data_file.write_text(json.dumps(data_file_2), encoding="utf-8")
        await wait()
        assert "automated_dampening_model_days: 99 (must be 2-21)" in caplog.text
        issue = issue_registry.async_get_issue(DOMAIN, ISSUE_ADVANCED_PROBLEM)
        assert issue is not None and issue.translation_placeholders is not None
        assert "automated_dampening_model_days: 99" in issue.translation_placeholders[PROBLEMS]
        assert "unknown_option" in issue.translation_placeholders[PROBLEMS]

        _LOGGER.debug("Testing advanced options revert to defaults")
        data_file.write_text(json.dumps(data_file_1), encoding="utf-8")
        await wait()
        assert "Removing advanced problems issue" in caplog.text
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_ADVANCED_PROBLEM) is None, "Issue ISSUE_ADVANCED_PROBLEM should not exist"

        caplog.clear()

        _LOGGER.debug("Testing advanced options 3")
        data_file_3: dict[str, Any] = {
            ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_EXCLUDE: [
                {"model": 2},
                {"model": 3, "delta": 1},
                {"model": 3, "delta": "hairy_one"},
                {"model": 3, "delta": {"see": "this_one_coming?"}},
                {"modell": 1, "delta": 1},
                {"model": 1, "delta": 1, "gift_with_purchase": True},
                {"bullshit": "value", "delta": "value", "so wrong": "value"},
            ],
            ADVANCED_AUTOMATED_DAMPENING_GENERATION_FETCH_DELAY: 40,
            ADVANCED_ESTIMATED_ACTUALS_FETCH_DELAY: 30,
            ADVANCED_FORECAST_FUTURE_DAYS: 8,
            ADVANCED_FORECAST_DAY_ENTITIES: 10,
            ADVANCED_GRANULAR_DAMPENING_DELTA_ADJUSTMENT: True,
            ADVANCED_AUTOMATED_DAMPENING_NO_DELTA_ADJUSTMENT: True,
            "forecast_history_max_days": 365,
        }
        data_file.write_text(json.dumps(data_file_3), encoding="utf-8")
        await wait()
        assert "index 0:" not in caplog.text
        assert "index 1:" not in caplog.text
        for i in (2, 3):
            assert (
                f"Invalid value type in automated_dampening_adaptive_model_exclude entry at index {i}: key 'delta' must be an integer"
                in caplog.text
            )
        for i in (4, 6):
            assert f"Missing required keys in automated_dampening_adaptive_model_exclude entry at index {i}" in caplog.text
        assert "Unknown keys in automated_dampening_adaptive_model_exclude entry at index 5:" in caplog.text
        assert "Advanced option automated_dampening_generation_fetch_delay: 40 must be less than or equal" in caplog.text
        assert "Advanced option estimated_actuals_fetch_delay: 30 must be greater than or equal" in caplog.text
        assert "Advanced option forecast_day_entities: 10 must be less than or equal" in caplog.text
        assert "Advanced option proposed forecast_future_days: 8" in caplog.text
        assert "Advanced option set forecast_future_days: 8" in caplog.text
        assert "Advanced option set history_max_days: 365" in caplog.text
        assert "Granular dampening delta adjustment requires estimated actuals" in caplog.text
        assert "Advanced option forecast_history_max_days is deprecated, please use history_max_days" in caplog.text
        assert (
            "Advanced option granular_dampening_delta_adjustment: True can not be set with automated_dampening_no_delta_adjustment: True"
            in caplog.text
        )
        caplog.clear()

        _LOGGER.debug("Testing advanced options configuration file removal")
        data_file = data_file.rename(f"{config_dir}/solcast-advanced.bak")
        await wait()
        assert "Advanced option default set" in caplog.text
        assert "Advanced options file deleted, no longer monitoring" in caplog.text
        caplog.clear()
        data_file = data_file.rename(f"{config_dir}/solcast-advanced.json")
        await wait()
        assert "Running task watch_advanced" in caplog.text

        caplog.clear()

        _LOGGER.debug("Testing advanced options 4")
        requires = {
            ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_CONFIGURATION: [
                {"option": ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_MINIMUM_HISTORY_DAYS, "value": 7},
                {"option": ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_EXCLUDE, "value": [{"model": 1, "delta": 2}]},
            ]
        }
        data_file_4: dict[str, Any] = {
            ADVANCED_AUTOMATED_DAMPENING_ADAPTIVE_MODEL_CONFIGURATION: False,
            **{option["option"]: option["value"] for options in requires.values() for option in options},
        }
        data_file.write_text(json.dumps(data_file_4), encoding="utf-8")
        await wait()
        for require, options in requires.items():
            for option in options:
                assert f"{option['option']} requires {require} to be set" in caplog.text
        caplog.clear()

        _LOGGER.debug("Testing advanced options invalid configuration")
        data_file.write_text('{"option_1": "one", "option_2": "two",}', encoding="utf-8")  # trailing comma
        await wait_for("Raise issue in 60 seconds")
        assert "Advanced options file invalid format, expected JSON `dict`" in caplog.text
        assert "Raise issue in 60 seconds" in caplog.text

        data_file_1[ADVANCED_RELOAD_ON_ADVANCED_CHANGE] = True
        data_file_1[ADVANCED_FORECAST_DAY_ENTITIES] = 14
        data_file.write_text(json.dumps(data_file_1), encoding="utf-8")
        await wait()
        assert ADVANCED_INVALID_JSON_TASK not in solcast.tasks

        caplog.clear()
        entity = "sensor.solcast_pv_forecast_forecast_day_13"
        er.async_get(hass).async_update_entity(entity, disabled_by=None)
        await wait_for("Reloading configuration entries because disabled_by changed")
        await wait_for("Not adding entity Forecast Day 12 because it's disabled")
        entity_state = hass.states.get(entity)
        assert entity_state is not None, "Entity state should not be None"
        assert entity_state.state == "42.552"

        await hass.config_entries.async_unload(entry.entry_id)
        await wait()
        assert f"Cancelling coordinator task {TASK_WATCH_ADVANCED_FILE_CHANGE}" in caplog.text

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


@pytest.mark.usefixtures("recorder_mock")
async def test_entry_options_development_flag(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that ENTRY_OPTIONS_DEVELOPMENT causes re-upgrade of options on every startup.

    An entry already at CONFIG_VERSION would normally skip migration entirely.
    With the flag set, the log should show the current version being recognised
    and then an upgrade message confirming the latest version step re-ran.
    """

    try:
        with patch.object(solcast_module, "ENTRY_OPTIONS_DEVELOPMENT", True):
            await async_init_integration(hass, copy.deepcopy(DEFAULT_INPUT1), version=CONFIG_VERSION)
            assert f"Options version {CONFIG_VERSION}" in caplog.text
            assert f"Upgraded to options version {CONFIG_VERSION}" in caplog.text

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"
