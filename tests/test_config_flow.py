"""Test the Solcast Solar config flow."""

import contextlib
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
from homeassistant.components.sensor import SensorDeviceClass
import homeassistant.components.solcast_solar as solcast_module
from homeassistant.components.solcast_solar import state

# As a core component, these imports would be homeassistant.components.solcast_solar and not config.custom_components.solcast_solar
from homeassistant.components.solcast_solar.config_flow import (
    ATTR_BREAKDOWN,
    CONFIG_DAMP,
    SolcastSolarFlowHandler,
    SolcastSolarOptionFlowHandler,
)
from homeassistant.components.solcast_solar.const import (
    AFFIRMATION_REAUTH_SUCCESSFUL,
    AFFIRMATION_RECONFIGURED,
    AFFIRMATION_UNCHANGED,
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
    DOMAIN,
    EXCEPTION_ACTUALS_WITHOUT_GET,
    EXCEPTION_API_DUPLICATE,
    EXCEPTION_API_ERROR,
    EXCEPTION_API_LOOKS_LIKE_SITE,
    EXCEPTION_CUSTOM_INVALID,
    EXCEPTION_DAMPEN_WITHOUT_ACTUALS,
    EXCEPTION_DAMPEN_WITHOUT_GENERATION,
    EXCEPTION_EXPORT_MULTIPLE_ENTITIES,
    EXCEPTION_EXPORT_NO_ENTITY,
    EXCEPTION_EXPORT_NO_LIMIT,
    EXCEPTION_HARD_NOT_POSITIVE_NUMBER,
    EXCEPTION_HARD_TOO_MANY,
    EXCEPTION_INTERNAL_ERROR,
    EXCEPTION_LIMIT_EXCEEDS_MAXIMUM,
    EXCEPTION_LIMIT_NOT_NUMBER,
    EXCEPTION_LIMIT_ONE_OR_GREATER,
    EXCEPTION_LIMIT_TOO_MANY,
    EXCLUDE_SITES,
    GENERATION_ENTITIES,
    GET_ACTUALS,
    HARD_LIMIT,
    HARD_LIMIT_API,
    KEY_ESTIMATE,
    RESET,
    SITE_DAMP,
    SITE_EXPORT_ENTITY,
    SITE_EXPORT_LIMIT,
    SUGGESTED_VALUE,
    TITLE,
    USE_ACTUALS,
)
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.enums import HistoryType
from homeassistant.components.solcast_solar.solcastapi import LoadStatus, SolcastApi
from homeassistant.config_entries import ConfigEntryState, ConfigFlowResult
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

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
    get_state,
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


def _attr_breakdown_input(data: dict[str, Any]) -> list[str]:
    """Build options-flow attr_breakdown multiselect payload."""

    return [
        key
        for key in (
            BRK_ESTIMATE10,
            BRK_ESTIMATE,
            BRK_ESTIMATE90,
            BRK_SITE,
            BRK_HALFHOURLY,
            BRK_HOURLY,
            BRK_SITE_DETAILED,
        )
        if data.get(key, False)
    ]


def _schema_suggested_values(result: ConfigFlowResult) -> dict[str, Any]:
    """Return suggested values from a flow form schema."""

    data_schema = result.get("data_schema")
    assert data_schema is not None
    return {
        marker.schema: marker.description[SUGGESTED_VALUE]
        for marker in data_schema.schema
        if marker.description and SUGGESTED_VALUE in marker.description
    }


def _assert_flow_error(result: ConfigFlowResult, reason: str) -> None:
    """Assert a local validation key or translated API error detail."""

    errors = result.get("errors")
    assert errors is not None
    if errors["base"] == EXCEPTION_API_ERROR:
        description_placeholders = result.get("description_placeholders")
        assert description_placeholders is not None
        assert reason in description_placeholders["error_detail"]
    else:
        assert errors["base"] == reason


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
    ({CONF_API_KEY: " 555 "}, "Bad API key, 403/Forbidden"),
    ({CONF_API_KEY: KEY1 + "," + KEY2}, None),
]

TEST_KEY_CHANGES: list[tuple[Any, Any, str | None]] = [
    (
        None,
        {CONF_API_KEY: " 555 ", API_LIMIT: "10", AUTO_UPDATE: "1"},
        "Bad API key, 403/Forbidden",
    ),
    (
        None,
        {CONF_API_KEY: "no_sites", API_LIMIT: "10", AUTO_UPDATE: "1"},
        "No sites for the API key",
    ),
    (
        MOCK_BUSY,
        {CONF_API_KEY: "2", API_LIMIT: "10", AUTO_UPDATE: "1"},
        "Error 429/Try again later for API key",
    ),
    (
        MOCK_EXCEPTION,
        {CONF_API_KEY: "2", API_LIMIT: "10", AUTO_UPDATE: "1"},
        None,
    ),
    (
        None,
        {CONF_API_KEY: "1", API_LIMIT: "10", AUTO_UPDATE: "1"},
        None,
    ),
    (
        None,
        {CONF_API_KEY: "2", API_LIMIT: "10", AUTO_UPDATE: "1"},
        None,
    ),
]

TEST_API_LIMIT: list[tuple[dict[Any, Any], dict[Any, Any], str | None]] = [
    (DEFAULT_INPUT1, {CONF_API_KEY: KEY1, API_LIMIT: "invalid", AUTO_UPDATE: "1"}, EXCEPTION_LIMIT_NOT_NUMBER),
    (DEFAULT_INPUT1, {CONF_API_KEY: KEY1, API_LIMIT: "\u00b2", AUTO_UPDATE: "1"}, EXCEPTION_LIMIT_NOT_NUMBER),  # Unicode superscript 2
    (DEFAULT_INPUT1, {CONF_API_KEY: KEY1, API_LIMIT: "", AUTO_UPDATE: "1"}, EXCEPTION_LIMIT_ONE_OR_GREATER),
    (DEFAULT_INPUT1, {CONF_API_KEY: KEY1, API_LIMIT: " ", AUTO_UPDATE: "1"}, EXCEPTION_LIMIT_ONE_OR_GREATER),
    (DEFAULT_INPUT1, {CONF_API_KEY: KEY1, API_LIMIT: ",", AUTO_UPDATE: "1"}, EXCEPTION_LIMIT_ONE_OR_GREATER),
    (DEFAULT_INPUT1, {CONF_API_KEY: KEY1, API_LIMIT: "0", AUTO_UPDATE: "1"}, EXCEPTION_LIMIT_ONE_OR_GREATER),
    (DEFAULT_INPUT1, {CONF_API_KEY: KEY1, API_LIMIT: "51", AUTO_UPDATE: "1"}, EXCEPTION_LIMIT_EXCEEDS_MAXIMUM),
    (DEFAULT_INPUT1, {CONF_API_KEY: KEY1, API_LIMIT: "10,10", AUTO_UPDATE: "1"}, EXCEPTION_LIMIT_TOO_MANY),
    (DEFAULT_INPUT1, {CONF_API_KEY: KEY1, API_LIMIT: "10", AUTO_UPDATE: "1"}, None),
    (DEFAULT_INPUT2, {CONF_API_KEY: KEY1 + "," + KEY2, API_LIMIT: "10,10", AUTO_UPDATE: "1"}, None),
    (DEFAULT_INPUT2, {CONF_API_KEY: KEY1 + "," + KEY2, API_LIMIT: "10,10,10", AUTO_UPDATE: "1"}, EXCEPTION_LIMIT_TOO_MANY),
    (DEFAULT_INPUT2, {CONF_API_KEY: KEY1 + "," + KEY2, API_LIMIT: "10", AUTO_UPDATE: "1"}, None),
]


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
        assert _schema_suggested_values(result) == user_input


async def test_config_api_key_invalid(hass: HomeAssistant) -> None:
    """Test that invalid API key is handled in config flow."""

    await async_setup_aioresponses()

    flow = SolcastSolarFlowHandler()
    flow.hass = hass

    user_input = {CONF_API_KEY: " 555 ", API_LIMIT: "10", AUTO_UPDATE: "1"}
    result = await flow.async_step_user(user_input)
    _assert_flow_error(result, "Bad API key, 403/Forbidden")
    assert _schema_suggested_values(result) == user_input

    user_input = {CONF_API_KEY: "no_sites", API_LIMIT: "10", AUTO_UPDATE: "1"}
    result = await flow.async_step_user(user_input)
    _assert_flow_error(result, "No sites for the API key")
    assert _schema_suggested_values(result) == user_input

    session_set(MOCK_BUSY)
    user_input = {CONF_API_KEY: "1", API_LIMIT: "10", AUTO_UPDATE: "1"}
    result = await flow.async_step_user(user_input)
    _assert_flow_error(result, "Error 429/Try again later for API key")
    assert _schema_suggested_values(result) == user_input
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
        assert _schema_suggested_values(result) == user_input


async def test_reauth_api_key(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that valid/invalid API key is handled in reconfigure.

    Not parameterised for performance reasons and to maintain caches between tests.
    """
    entry = None
    api_key_sites_backup = copy.deepcopy(simulator.API_KEY_SITES)
    try:
        _user_input = 0
        _reason = 1

        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"

        for test in TEST_REAUTH_API_KEY:
            result = await entry.start_reauth_flow(hass)
            assert result.get("type") is FlowResultType.FORM
            assert result.get("step_id") == "reauth_confirm"
            result = await hass.config_entries.flow.async_configure(  # pyright: ignore[reportUnknownMemberType]
                result["flow_id"],
                user_input=test[_user_input],
            )
            await hass.async_block_till_done()
            if result.get("reason") != AFFIRMATION_REAUTH_SUCCESSFUL:
                _assert_flow_error(result, test[_reason])
                assert _schema_suggested_values(result) == test[_user_input]

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
        simulator.API_KEY_SITES.clear()
        simulator.API_KEY_SITES.update(api_key_sites_backup)
        session_clear(MOCK_FORBIDDEN)
        if entry is not None:
            with contextlib.suppress(Exception):
                await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


@pytest.mark.usefixtures("recorder_mock")
async def test_reauth_unchanged_key_retries_setup_without_key_change(hass: HomeAssistant) -> None:
    """Test reauth retries setup without treating an unchanged key as new."""

    entry = MockConfigEntry(domain=DOMAIN, data={"legacy": "value"}, options=copy.deepcopy(DEFAULT_INPUT1), title=TITLE)
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)

    with (
        patch("homeassistant.components.solcast_solar.config_flow.validate_sites", return_value=(200, "")) as mock_validate_sites,
        patch("homeassistant.components.solcast_solar.config_flow.set_sensitive") as mock_set_sensitive,
        patch.object(SolcastSolarFlowHandler, "_mark_reset_old_key") as mock_mark_reset_old_key,
        patch.object(hass.config_entries, "async_update_entry") as mock_update_entry,
        patch.object(hass.config_entries, "async_schedule_reload") as mock_schedule_reload,
    ):
        result = await hass.config_entries.flow.async_configure(  # pyright: ignore[reportUnknownMemberType]
            result["flow_id"], user_input={CONF_API_KEY: KEY1}
        )

    assert result.get("reason") == AFFIRMATION_UNCHANGED
    mock_validate_sites.assert_awaited_once()
    mock_set_sensitive.assert_not_awaited()
    mock_mark_reset_old_key.assert_not_called()
    mock_update_entry.assert_not_called()
    mock_schedule_reload.assert_called_once_with(entry.entry_id)


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
        _user_input = 0
        _reason = 1

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
                user_input=test[_user_input],
            )
            await hass.async_block_till_done()
            if result.get("reason") != AFFIRMATION_RECONFIGURED:
                assert result["errors"]["base"] == test[_reason]  # type: ignore[index]
                assert _schema_suggested_values(result) == test[_user_input]

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


@pytest.mark.usefixtures("recorder_mock")
async def test_reconfigure_errors_then_unchanged_does_not_update(hass: HomeAssistant) -> None:
    """Test unchanged reconfigure values are a no-op after validation errors."""

    entry = MockConfigEntry(domain=DOMAIN, data={"legacy": "value"}, options=copy.deepcopy(DEFAULT_INPUT1), title=TITLE)
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
        data=entry.data,
    )

    for user_input, reason in (
        ({CONF_API_KEY: f"{KEY1},{KEY1}", API_LIMIT: "10", AUTO_UPDATE: "1"}, EXCEPTION_API_DUPLICATE),
        ({CONF_API_KEY: KEY1, API_LIMIT: "invalid", AUTO_UPDATE: "1"}, EXCEPTION_LIMIT_NOT_NUMBER),
    ):
        result = await hass.config_entries.flow.async_configure(  # pyright: ignore[reportUnknownMemberType]
            result["flow_id"], user_input=user_input
        )
        assert result["errors"]["base"] == reason  # type: ignore[index]

    with (
        patch("homeassistant.components.solcast_solar.config_flow.validate_sites") as mock_validate_sites,
        patch("homeassistant.components.solcast_solar.config_flow.set_sensitive") as mock_set_sensitive,
        patch.object(SolcastSolarFlowHandler, "_mark_reset_old_key") as mock_mark_reset_old_key,
        patch.object(hass.config_entries, "async_update_entry") as mock_update_entry,
        patch.object(hass.config_entries, "async_schedule_reload") as mock_schedule_reload,
    ):
        result = await hass.config_entries.flow.async_configure(  # pyright: ignore[reportUnknownMemberType]
            result["flow_id"],
            user_input={
                CONF_API_KEY: entry.options[CONF_API_KEY],
                API_LIMIT: entry.options[API_LIMIT],
                AUTO_UPDATE: str(entry.options[AUTO_UPDATE]),
            },
        )

    assert result.get("reason") == AFFIRMATION_UNCHANGED
    mock_validate_sites.assert_not_awaited()
    mock_set_sensitive.assert_not_awaited()
    mock_mark_reset_old_key.assert_not_called()
    mock_update_entry.assert_not_called()
    mock_schedule_reload.assert_not_called()


@pytest.mark.parametrize(("set", "options", "to_assert"), TEST_KEY_CHANGES)
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
        caplog.clear()
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
        if set is None and options[CONF_API_KEY] == "2":
            assert "Sensitive startup" in caplog.text

        if set:
            session_clear(set)
        if set == MOCK_EXCEPTION:
            assert "Error retrieving sites" in caplog.text
        if to_assert:
            _assert_flow_error(result, to_assert)
            assert _schema_suggested_values(result) == options
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
        _options = 0
        _user_input = 1
        _reason = 2

        _input = None
        for test in TEST_API_LIMIT:
            entry = await async_init_integration(hass, test[_options])  # type: ignore[arg-type]
            state_store = await state.async_get(hass, entry.entry_id)
            assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"
            if _input is None or test[_options] != _input:
                _input = copy.deepcopy(test[_options])
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
                user_input=test[_user_input],  # type: ignore[arg-type]
            )
            await hass.async_block_till_done()
            if test[_user_input][CONF_API_KEY] == KEY1:
                assert not state_store.state.sensitive
            if test[_reason]:
                assert result["errors"]["base"] == test[_reason]  # type: ignore[index]
                assert _schema_suggested_values(result) == test[_user_input]

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
    with patch("homeassistant.components.solcast_solar.config_flow.set_sensitive") as mock_set_sensitive:
        result = await flow.async_step_init(user_input)
    if reason is not None:
        assert result["errors"]["base"] == reason  # type: ignore[index]
        assert _schema_suggested_values(result)[CONF_API_KEY] == user_input[CONF_API_KEY]  # type: ignore[arg-type]
        mock_set_sensitive.assert_not_awaited()


async def test_options_api_key_invalid(hass: HomeAssistant) -> None:
    """Test that invalid API key is handled in options flow."""

    await async_setup_aioresponses()

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1)
    flow.hass = hass

    options = DEFAULT_INPUT1.copy()
    options[SITE_EXPORT_ENTITY] = [options[SITE_EXPORT_ENTITY]]

    with patch("homeassistant.components.solcast_solar.config_flow.set_sensitive") as mock_set_sensitive:
        inject = {CONF_API_KEY: "555"}
        result = await flow.async_step_init({**options, **inject})
        _assert_flow_error(result, "Bad API key, 403/Forbidden")
        assert _schema_suggested_values(result)[CONF_API_KEY] == inject[CONF_API_KEY]  # type: ignore[arg-type]

        inject = {CONF_API_KEY: "no_sites"}
        result = await flow.async_step_init({**options, **inject})
        _assert_flow_error(result, "No sites for the API key")
        assert _schema_suggested_values(result)[CONF_API_KEY] == inject[CONF_API_KEY]  # type: ignore[arg-type]

        session_set(MOCK_BUSY)
        result = await flow.async_step_init(options)
        _assert_flow_error(result, "Error 429/Try again later for API key")
        assert _schema_suggested_values(result)[CONF_API_KEY] == options[CONF_API_KEY]  # type: ignore[arg-type]
        session_clear(MOCK_BUSY)

        mock_set_sensitive.assert_not_awaited()


async def test_options_api_key_change_sets_sensitive(hass: HomeAssistant) -> None:
    """Test that a valid API key change marks the integration sensitive."""

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1)
    flow.hass = hass

    options = copy.deepcopy(DEFAULT_INPUT1)
    options[SITE_EXPORT_ENTITY] = []

    with (
        patch("homeassistant.components.solcast_solar.config_flow.validate_sites", return_value=(200, "")),
        patch("homeassistant.components.solcast_solar.config_flow.set_sensitive") as mock_set_sensitive,
    ):
        await flow.async_step_init(options)

    mock_set_sensitive.assert_awaited_once_with(hass, MOCK_ENTRY1)


async def test_options_api_key_change_defers_sensitive_until_dampen_commit(hass: HomeAssistant) -> None:
    """Test a key change is not sensitive until the dampening step commits."""

    entry = MockConfigEntry(domain=DOMAIN, data={}, options=copy.deepcopy(DEFAULT_INPUT1), title=TITLE)
    flow = SolcastSolarOptionFlowHandler(entry)
    flow.hass = hass
    options = copy.deepcopy(DEFAULT_INPUT1)
    options[CONF_API_KEY] = KEY2
    options[CONFIG_DAMP] = True
    options[SITE_EXPORT_ENTITY] = []

    with (
        patch("homeassistant.components.solcast_solar.config_flow.validate_sites", return_value=(200, "")),
        patch("homeassistant.components.solcast_solar.config_flow.set_sensitive") as mock_set_sensitive,
        patch.object(hass.config_entries, "async_update_entry") as mock_update_entry,
        patch.object(flow, "check_dead") as mock_check_dead,
    ):
        result = await flow.async_step_init(options)
        assert result.get("step_id") == "dampen"
        mock_set_sensitive.assert_not_awaited()
        mock_update_entry.assert_not_called()

        result = await flow.async_step_dampen({f"damp{factor:02d}": 0.8 for factor in range(24)})

    assert result.get("reason") == AFFIRMATION_RECONFIGURED
    mock_set_sensitive.assert_awaited_once_with(hass, entry)
    mock_update_entry.assert_called_once()
    mock_check_dead.assert_awaited_once()


async def test_options_unexpected_exception_is_translated(hass: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """Test unexpected option validation errors use a stable translation key."""

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1)
    flow.hass = hass

    with patch("homeassistant.components.solcast_solar.config_flow.validate_api_key", side_effect=RuntimeError("secret detail")):
        result = await flow.async_step_init(copy.deepcopy(DEFAULT_INPUT1))

    errors = result.get("errors")
    assert errors is not None
    assert errors["base"] == EXCEPTION_INTERNAL_ERROR
    assert "secret detail" not in errors["base"]
    assert "Unexpected exception while validating options" in caplog.text
    assert "Traceback (most recent call last)" in caplog.text
    assert "RuntimeError: secret detail" in caplog.text


async def test_sensor_options_use_original_registry_device_class(hass: HomeAssistant) -> None:
    """Test registry-only sensors use their integration device class."""

    entry = MockConfigEntry(domain=DOMAIN, data={}, options=copy.deepcopy(DEFAULT_INPUT1))
    entity_registry = er.async_get(hass)
    energy_entry = entity_registry.async_get_or_create(
        "sensor", "pytest", "registry_energy", original_device_class=SensorDeviceClass.ENERGY
    )
    power_entry = entity_registry.async_get_or_create("sensor", "pytest", "registry_power", original_device_class=SensorDeviceClass.POWER)
    flow = SolcastSolarOptionFlowHandler(entry)
    flow.hass = hass

    sensors, energy_sensors = flow._build_sensor_options()

    assert {option["value"] for option in sensors} >= {energy_entry.entity_id, power_entry.entity_id}
    assert {option["value"] for option in energy_sensors} >= {energy_entry.entity_id}
    assert power_entry.entity_id not in {option["value"] for option in energy_sensors}


async def test_options_form_configured_defaults(hass: HomeAssistant) -> None:
    """Test configured export and auto-dampening options form defaults."""

    entry_options = copy.deepcopy(DEFAULT_INPUT1)
    entry_options[AUTO_DAMPEN] = True
    entry_options[SITE_EXPORT_ENTITY] = "sensor.grid_export"
    entry_options[SITE_EXPORT_LIMIT] = 5.0
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=entry_options)
    flow = SolcastSolarOptionFlowHandler(entry)
    flow.hass = hass

    result = await flow.async_step_init()
    schema = result["data_schema"].schema  # type: ignore[union-attr]
    export_entity_marker = next(marker for marker in schema if marker == SITE_EXPORT_ENTITY)

    assert export_entity_marker.default() == ["sensor.grid_export"]
    assert CONFIG_DAMP not in schema


async def test_options_duplicate_api_key_then_unchanged_does_not_update(hass: HomeAssistant) -> None:
    """Test restoring unchanged API keys after a duplicate error is a no-op."""

    entry_options = copy.deepcopy(DEFAULT_INPUT2)
    entry_options[HARD_LIMIT_API] = "12.0,6.0"
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=entry_options, title=TITLE)
    flow = SolcastSolarOptionFlowHandler(entry)
    flow.hass = hass
    user_input = copy.deepcopy(entry_options)
    user_input[SITE_EXPORT_ENTITY] = []

    duplicate_input = {**user_input, CONF_API_KEY: f"{KEY1},{KEY1}"}
    result = await flow.async_step_init(duplicate_input)
    assert result["errors"]["base"] == EXCEPTION_API_DUPLICATE  # type: ignore[index]
    suggested_values = _schema_suggested_values(result)  # type: ignore[arg-type]
    assert suggested_values == {key: value for key, value in duplicate_input.items() if key in suggested_values}

    with (
        patch("homeassistant.components.solcast_solar.config_flow.validate_sites") as mock_validate_sites,
        patch("homeassistant.components.solcast_solar.config_flow.set_sensitive") as mock_set_sensitive,
        patch.object(hass.config_entries, "async_update_entry") as mock_update_entry,
        patch.object(flow, "check_dead") as mock_check_dead,
    ):
        result = await flow.async_step_init(user_input)

    assert result.get("reason") == AFFIRMATION_UNCHANGED
    mock_validate_sites.assert_not_awaited()
    mock_set_sensitive.assert_not_awaited()
    mock_update_entry.assert_not_called()
    mock_check_dead.assert_not_awaited()


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
        assert _schema_suggested_values(result)[API_LIMIT] == user_input[API_LIMIT]  # type: ignore[arg-type]


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
        assert _schema_suggested_values(result)[CUSTOM_HOURS] == value  # type: ignore[arg-type]


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
        assert _schema_suggested_values(result)[HARD_LIMIT_API] == value  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("options", "reason"),
    [
        (({GET_ACTUALS: False, USE_ACTUALS: 1, SITE_EXPORT_ENTITY: []}, EXCEPTION_ACTUALS_WITHOUT_GET)),
        (({AUTO_DAMPEN: True, GET_ACTUALS: False, SITE_EXPORT_ENTITY: []}, EXCEPTION_DAMPEN_WITHOUT_ACTUALS)),
        (({AUTO_DAMPEN: True, GET_ACTUALS: True, GENERATION_ENTITIES: [], SITE_EXPORT_ENTITY: []}, EXCEPTION_DAMPEN_WITHOUT_GENERATION)),
        (({SITE_EXPORT_ENTITY: ["entity.one", "entity.two"]}, EXCEPTION_EXPORT_MULTIPLE_ENTITIES)),
        (({SITE_EXPORT_LIMIT: 5, SITE_EXPORT_ENTITY: []}, EXCEPTION_EXPORT_NO_ENTITY)),
        (({SITE_EXPORT_LIMIT: 0, SITE_EXPORT_ENTITY: ["test.entity"]}, EXCEPTION_EXPORT_NO_LIMIT)),
        (({SITE_EXPORT_LIMIT: "0", SITE_EXPORT_ENTITY: ["test.entity"]}, EXCEPTION_EXPORT_NO_LIMIT)),
    ],
)
async def test_options_auto_dampen(hass: HomeAssistant, options: dict[str, Any], reason: str | None) -> None:
    """Test that valid/invalid auto-dampen settings are handled."""

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1)
    flow.hass = hass
    user_input = copy.deepcopy(DEFAULT_INPUT1) | options
    result = await flow.async_step_init(user_input)
    assert result["errors"]["base"] == reason  # type: ignore[index]
    suggested_values = _schema_suggested_values(result)  # type: ignore[arg-type]
    assert all(suggested_values[key] == value for key, value in options.items() if key in suggested_values)


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

        with (
            patch.object(hass.config_entries, "async_update_entry") as mock_update_entry,
            patch.object(flow, "check_dead") as mock_check_dead,
        ):
            result = await flow.async_step_dampen(user_input)

        assert result.get("reason") == AFFIRMATION_UNCHANGED
        mock_update_entry.assert_not_called()
        mock_check_dead.assert_not_awaited()

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

    _start_version = 3
    _final_version = 19
    _v3options: dict[str, Any] = {
        CONF_API_KEY: "1",
        "const_disableautopoll": False,
    }
    try:
        config_dir = f"{hass.config.config_dir}/{CONFIG_DISCRETE_NAME}" if CONFIG_FOLDER_DISCRETE else hass.config.config_dir
        entry = await async_init_integration(hass, copy.deepcopy(_v3options), version=_start_version)
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"

        assert entry.version == _final_version
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
        entry = await async_init_integration(hass, copy.deepcopy(_v3options), version=_start_version)
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
        user_input[ATTR_BREAKDOWN] = _attr_breakdown_input(user_input)
        for key in (BRK_ESTIMATE10, BRK_ESTIMATE, BRK_ESTIMATE90, BRK_SITE, BRK_HALFHOURLY, BRK_HOURLY, BRK_SITE_DETAILED):
            user_input.pop(key, None)
        await set_presumed_dead(hass, entry, True)
        result = await hass.config_entries.options.async_init(entry.entry_id)
        await hass.async_block_till_done()
        result = await hass.config_entries.options.async_configure(  # pyright: ignore[reportUnknownMemberType]
            result["flow_id"],
            user_input,
        )
        await hass.async_block_till_done()  # Integration will reload
        assert "Integration presumed dead, reloading" in caplog.text or "Integration reload already in progress" in caplog.text
        coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator
        solcast: SolcastApi = coordinator.solcast
        assert solcast.sites_status is LoadStatus.OK, f"Expected sites status LoadStatus.OK, got {solcast.sites_status}"
        assert solcast.loaded_data is True, "Solcast data should be loaded"

        assert await hass.config_entries.async_unload(entry.entry_id), "Config entry unload failed"
        await hass.async_block_till_done()

        # Test dampening step can  be reached
        option = {CONFIG_DAMP: True, USE_ACTUALS: "0", SITE_EXPORT_ENTITY: []}
        user_input = DEFAULT_INPUT1_NO_DAMP | option
        user_input[ATTR_BREAKDOWN] = _attr_breakdown_input(user_input)
        for key in (BRK_ESTIMATE10, BRK_ESTIMATE, BRK_ESTIMATE90, BRK_SITE, BRK_HALFHOURLY, BRK_HOURLY, BRK_SITE_DETAILED):
            user_input.pop(key, None)

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


async def test_check_dead_reload_without_presumed_dead_warning(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test check_dead reload path does not warn about presumed death when crash-state is clear."""

    try:
        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"

        await set_presumed_dead(hass, entry, False)
        assert await hass.config_entries.async_unload(entry.entry_id), "Config entry unload failed"
        await hass.async_block_till_done()

        option_flow = SolcastSolarOptionFlowHandler(entry)
        option_flow.hass = hass

        caplog.clear()
        await option_flow.check_dead()
        await hass.async_block_till_done()

        assert "Integration presumed dead, reloading" not in caplog.text
        assert "Integration not loaded during options update, reloading" in caplog.text
        assert entry.state is ConfigEntryState.LOADED, "Config entry should be reloaded"

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_check_dead_skips_when_reload_in_progress(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test check_dead does not log presumed-dead or trigger reload while setup is in progress."""

    try:
        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"

        await set_presumed_dead(hass, entry, True)
        entry._state = ConfigEntryState.SETUP_IN_PROGRESS  # pyright: ignore[reportAttributeAccessIssue]

        option_flow = SolcastSolarOptionFlowHandler(entry)
        option_flow.hass = hass

        caplog.set_level(logging.DEBUG)
        with patch.object(hass.config_entries, "async_reload", wraps=hass.config_entries.async_reload) as reload_mock:
            caplog.clear()
            await option_flow.check_dead()
            await hass.async_block_till_done()

            assert "Integration presumed dead, reloading" not in caplog.text
            reload_mock.assert_not_called()

        entry._state = ConfigEntryState.LOADED  # pyright: ignore[reportAttributeAccessIssue]

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_check_dead_presumed_dead_branch(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test check_dead runs presumed-dead warning/clear branch when entry is not loaded."""

    try:
        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        assert entry.state is ConfigEntryState.LOADED, "Integration presumed dead after setup"

        await set_presumed_dead(hass, entry, True)
        assert await hass.config_entries.async_unload(entry.entry_id), "Config entry unload failed"
        await hass.async_block_till_done()

        option_flow = SolcastSolarOptionFlowHandler(entry)
        option_flow.hass = hass

        with patch.object(hass.config_entries, "async_reload", return_value=True) as reload_mock:
            caplog.clear()
            await option_flow.check_dead()
            await hass.async_block_till_done()

            reload_mock.assert_called_once_with(entry.entry_id)

        state = await get_state(hass, entry)
        assert state.presumed_dead is False

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
