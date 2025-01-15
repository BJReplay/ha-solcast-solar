"""Test the Solcast Solar config flow."""

import copy
import json
import logging
from pathlib import Path

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant import config_entries
from homeassistant.components.recorder import Recorder

# As a core component, these imports would be homeassistant.components.solcast_solar and not config.custom_components.solcast_solar
from homeassistant.components.solcast_solar.config_flow import (
    CONFIG_DAMP,
    SolcastSolarFlowHandler,
    SolcastSolarOptionFlowHandler,
)
from homeassistant.components.solcast_solar.const import (
    API_QUOTA,
    AUTO_UPDATE,
    BRK_ESTIMATE,
    BRK_ESTIMATE10,
    BRK_ESTIMATE90,
    BRK_HALFHOURLY,
    BRK_HOURLY,
    BRK_SITE,
    BRK_SITE_DETAILED,
    CUSTOM_HOUR_SENSOR,
    DOMAIN,
    HARD_LIMIT,
    HARD_LIMIT_API,
    KEY_ESTIMATE,
    SITE_DAMP,
    TITLE,
)
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.solcastapi import SitesStatus, SolcastApi
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from . import (
    DEFAULT_INPUT1,
    DEFAULT_INPUT1_NO_DAMP,
    DEFAULT_INPUT2,
    KEY1,
    KEY2,
    MOCK_BUSY,
    async_cleanup_integration_tests,
    async_init_integration,
    async_setup_aioresponses,
    session_set,
    session_clear,
)

from tests.common import MockConfigEntry

_LOGGER = logging.getLogger(__name__)

API_KEY1 = "65sa6d46-sadf876_sd54"
API_KEY2 = "65sa6946-glad876_pf69"

DEFAULT_INPUT1_COPY = copy.deepcopy(DEFAULT_INPUT1)
DEFAULT_INPUT1_COPY[CONF_API_KEY] = API_KEY1

DEFAULT_INPUT2_COPY = copy.deepcopy(DEFAULT_INPUT2)
DEFAULT_INPUT2_COPY[CONF_API_KEY] = API_KEY1 + "," + API_KEY2

MOCK_ENTRY1 = MockConfigEntry(domain=DOMAIN, data={}, options=DEFAULT_INPUT1_COPY)
MOCK_ENTRY2 = MockConfigEntry(domain=DOMAIN, data={}, options=DEFAULT_INPUT2_COPY)

TEST_API_KEY = [
    ({CONF_API_KEY: "1234-5678-8765-4321", API_QUOTA: "10", AUTO_UPDATE: "1"}, FlowResultType.ABORT, "API key looks like a site ID"),
    ({CONF_API_KEY: KEY1 + "," + KEY1, API_QUOTA: "10", AUTO_UPDATE: "1"}, FlowResultType.ABORT, "Duplicate API key specified"),
    ({CONF_API_KEY: KEY1, API_QUOTA: "10", AUTO_UPDATE: "0"}, None, None),
    ({CONF_API_KEY: KEY1, API_QUOTA: "10", AUTO_UPDATE: "1"}, None, None),
    ({CONF_API_KEY: KEY1 + "," + KEY2, API_QUOTA: "10", AUTO_UPDATE: "2"}, None, None),
    ({CONF_API_KEY: KEY1 + "," + KEY2, API_QUOTA: "0", AUTO_UPDATE: "2"}, FlowResultType.ABORT, "API limit must be one or greater"),
]

TEST_BAD_KEY_INJECTION = [
    {
        "options": {CONF_API_KEY: "555", API_QUOTA: "10", AUTO_UPDATE: "1"},
        "assert": "Bad API key, 401/Unauth",
        "set": None,
    },
    {
        "options": {CONF_API_KEY: "no_sites", API_QUOTA: "10", AUTO_UPDATE: "1"},
        "assert": "No sites found for API key",
        "set": None,
    },
    {
        "options": {CONF_API_KEY: "1", API_QUOTA: "10", AUTO_UPDATE: "1"},
        "assert": "Error 429/Try again later for API key",
        "set": MOCK_BUSY,
    },
]

TEST_API_QUOTA = [
    (DEFAULT_INPUT1, {CONF_API_KEY: KEY1, API_QUOTA: "invalid", AUTO_UPDATE: "1"}, FlowResultType.ABORT, "API limit is not a number"),
    (DEFAULT_INPUT1, {CONF_API_KEY: KEY1, API_QUOTA: "0", AUTO_UPDATE: "1"}, FlowResultType.ABORT, "API limit must be one or greater"),
    (
        DEFAULT_INPUT1,
        {CONF_API_KEY: KEY1, API_QUOTA: "10,10", AUTO_UPDATE: "1"},
        FlowResultType.ABORT,
        "There are more API limit counts entered than keys",
    ),
    (DEFAULT_INPUT1, {CONF_API_KEY: KEY1, API_QUOTA: "10", AUTO_UPDATE: "1"}, None, None),
    (DEFAULT_INPUT2, {CONF_API_KEY: KEY1 + "," + KEY2, API_QUOTA: "10,10", AUTO_UPDATE: "1"}, None, None),
    (
        DEFAULT_INPUT2,
        {CONF_API_KEY: KEY1 + "," + KEY2, API_QUOTA: "10,10,10", AUTO_UPDATE: "1"},
        FlowResultType.ABORT,
        "There are more API limit counts entered than keys",
    ),
    (DEFAULT_INPUT2, {CONF_API_KEY: KEY1 + "," + KEY2, API_QUOTA: "10", AUTO_UPDATE: "1"}, None, None),
]


async def test_single_instance(
    recorder_mock: Recorder,
    hass: HomeAssistant,
) -> None:
    """Test allow a single config only."""
    MockConfigEntry(domain=DOMAIN).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_create_entry(hass: HomeAssistant) -> None:
    """Test that a valid user input creates an entry."""

    await async_setup_aioresponses()

    flow = SolcastSolarFlowHandler()
    flow.hass = hass

    expected_options = {
        CONF_API_KEY: KEY1,
        API_QUOTA: "10",
        AUTO_UPDATE: 1,
        CUSTOM_HOUR_SENSOR: 1,
        HARD_LIMIT_API: "100.0",
        KEY_ESTIMATE: "estimate",
        BRK_ESTIMATE: True,
        BRK_ESTIMATE10: True,
        BRK_ESTIMATE90: True,
        BRK_SITE: True,
        BRK_HALFHOURLY: True,
        BRK_HOURLY: True,
        BRK_SITE_DETAILED: False,
    }

    user_input = {CONF_API_KEY: KEY1, API_QUOTA: "10", AUTO_UPDATE: "1"}
    result = await flow.async_step_user(user_input)
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == TITLE
    assert result["data"] == {}
    for key, expect in expected_options.items():
        assert result["options"][key] == expect


@pytest.mark.parametrize(("user_input", "result", "reason"), TEST_API_KEY)
async def test_init_api_key(hass: HomeAssistant, user_input, result, reason) -> None:
    """Test that valid/invalid API key is handled in init."""

    flow = SolcastSolarFlowHandler()
    flow.hass = hass

    result = await flow.async_step_user()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    result = await flow.async_step_user(user_input)
    assert result["type"] == result if result is None else FlowResultType.CREATE_ENTRY
    if result == FlowResultType.ABORT:
        assert result["reason"] == reason


async def test_config_api_key_invalid(hass: HomeAssistant) -> None:
    """Test that invalid API key is handled in config flow."""

    await async_setup_aioresponses()

    flow = SolcastSolarFlowHandler()
    flow.hass = hass

    result = await flow.async_step_user({CONF_API_KEY: "555", API_QUOTA: "10", AUTO_UPDATE: "1"})
    assert result["type"] == FlowResultType.ABORT
    assert "Bad API key, 401/Unauth" in result["reason"]

    result = await flow.async_step_user({CONF_API_KEY: "no_sites", API_QUOTA: "10", AUTO_UPDATE: "1"})
    assert result["type"] == FlowResultType.ABORT
    assert "No sites found for API key" in result["reason"]

    session_set(MOCK_BUSY)
    result = await flow.async_step_user({CONF_API_KEY: "1", API_QUOTA: "10", AUTO_UPDATE: "1"})
    assert result["type"] == FlowResultType.ABORT
    assert "Error 429/Try again later for API key" in result["reason"]
    session_clear(MOCK_BUSY)


@pytest.mark.parametrize(("options", "user_input", "result", "reason"), TEST_API_QUOTA)
async def test_config_api_quota(hass: HomeAssistant, options, user_input, result, reason) -> None:
    """Test that valid/invalid API quota is handled in init."""

    flow = SolcastSolarFlowHandler()
    flow.hass = hass

    result = await flow.async_step_user()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    result = await flow.async_step_user(user_input)
    assert result["type"] == result if result is None else FlowResultType.CREATE_ENTRY
    if result == FlowResultType.ABORT:
        assert result["reason"] == reason


async def test_reconfigure_api_key(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that valid/invalid API key is handled in reconfigure.

    Not parameterised for performance reasons.
    """
    USER_INPUT = 0
    TYPE = 1
    REASON = 2

    try:
        entry = await async_init_integration(hass, DEFAULT_INPUT1)

        assert hass.data[DOMAIN].get("presumed_dead", True) is False
        for test in TEST_API_KEY:
            for source in [config_entries.SOURCE_REAUTH, config_entries.SOURCE_RECONFIGURE]:
                result = await hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": source, "entry_id": entry.entry_id},
                    data=entry.data,
                )
                await hass.async_block_till_done()
                assert result["type"] is FlowResultType.FORM
                assert result["step_id"] == "reconfigure_confirm"
                result = await hass.config_entries.flow.async_configure(
                    result["flow_id"],
                    user_input=test[USER_INPUT],
                )
                await hass.async_block_till_done()
                if result["reason"] not in ("reconfigured", None):
                    assert result["type"] == test[TYPE]
                    assert result["reason"] == test[REASON]

        for test in TEST_BAD_KEY_INJECTION:
            _LOGGER.critical(test)
            flow = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
                data=entry.data,
            )
            await hass.async_block_till_done()
            if test["set"]:
                session_set(test["set"])
            result = await hass.config_entries.flow.async_configure(
                flow["flow_id"],
                user_input=test["options"],
            )
            if test["set"]:
                session_clear(test["set"])
            assert result["type"] == FlowResultType.ABORT
            assert test["assert"] in result["reason"]

    finally:
        assert await async_cleanup_integration_tests(hass)


async def test_reconfigure_api_quota(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that valid/invalid API quota is handled in reconfigure.

    Not parameterised for performance reasons.
    """
    OPTIONS = 0
    USER_INPUT = 1
    TYPE = 2
    REASON = 3

    try:
        _input = None
        for test in TEST_API_QUOTA:
            if _input is None or test[OPTIONS] != _input:
                entry = await async_init_integration(hass, test[OPTIONS])
                assert hass.data[DOMAIN].get("presumed_dead", True) is False
                _input = copy.deepcopy(test[OPTIONS])
            for source in [config_entries.SOURCE_REAUTH, config_entries.SOURCE_RECONFIGURE]:
                result = await hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={
                        "source": source,
                        "entry_id": entry.entry_id,
                    },
                    data=entry.data,
                )
                await hass.async_block_till_done()
                assert result["type"] == FlowResultType.FORM
                assert result["step_id"] == "reconfigure_confirm"
                result = await hass.config_entries.flow.async_configure(
                    result["flow_id"],
                    user_input=test[USER_INPUT],
                )
                if result["reason"] not in ("reconfigured", None):
                    assert result["type"] == test[TYPE]
                    assert result["reason"] == test[REASON]

    finally:
        assert await async_cleanup_integration_tests(hass)


@pytest.mark.parametrize(("user_input", "result", "reason"), TEST_API_KEY)
async def test_options_api_key(hass: HomeAssistant, user_input, result, reason) -> None:
    """Test that valid/invalid API key is handled in option flow init."""

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1)
    flow.hass = hass

    result = await flow.async_step_init()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"
    result = await flow.async_step_init(user_input)
    assert result["type"] == result if result is None else FlowResultType.FORM
    if result == FlowResultType.ABORT:
        assert result["reason"] == reason


async def test_options_api_key_invalid(hass: HomeAssistant) -> None:
    """Test that invalid API key is handled in options flow."""

    await async_setup_aioresponses()

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1)
    flow.hass = hass

    options = DEFAULT_INPUT1

    inject = {CONF_API_KEY: "555"}
    result = await flow.async_step_init({**options, **inject})
    assert result["type"] == FlowResultType.ABORT
    assert "Bad API key, 401/Unauth" in result["reason"]

    inject = {CONF_API_KEY: "no_sites"}
    result = await flow.async_step_init({**options, **inject})
    assert result["type"] == FlowResultType.ABORT
    assert "No sites found for API key" in result["reason"]

    session_set(MOCK_BUSY)
    result = await flow.async_step_init(options)
    assert result["type"] == FlowResultType.ABORT
    assert "Error 429/Try again later for API key" in result["reason"]
    session_clear(MOCK_BUSY)


@pytest.mark.parametrize(("options", "user_input", "result", "reason"), TEST_API_QUOTA)
async def test_options_api_quota(hass: HomeAssistant, options, user_input, result, reason) -> None:
    """Test that valid/invalid API quota is handled in option flow init."""

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1)
    flow.hass = hass

    result = await flow.async_step_init()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"
    result = await flow.async_step_init({**options, **user_input})
    assert result["type"] == result if result is None else FlowResultType.FORM
    if result == FlowResultType.ABORT:
        assert result["reason"] == reason


@pytest.mark.parametrize(
    ("options", "value", "result", "reason"),
    [
        ((DEFAULT_INPUT1, 0, FlowResultType.ABORT, "Custom sensor not between 1 and 144")),
        ((DEFAULT_INPUT1, 145, FlowResultType.ABORT, "Custom sensor not between 1 and 144")),
        ((DEFAULT_INPUT1, 8, FlowResultType.FORM, "")),
    ],
)
async def test_options_custom_hour_sensor(hass: HomeAssistant, options, value, result, reason) -> None:
    """Test that valid/invalid custom hour sensor is handled."""

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1)
    flow.hass = hass

    user_input = copy.deepcopy(options)
    user_input[CUSTOM_HOUR_SENSOR] = value
    _result = await flow.async_step_init(user_input)
    assert _result["type"] == result
    if _result == FlowResultType.ABORT:
        assert _result["reason"] == reason


@pytest.mark.parametrize(
    ("options", "value", "result", "reason"),
    [
        ((DEFAULT_INPUT1, "invalid", FlowResultType.ABORT, "Hard limit is not a positive number")),
        ((DEFAULT_INPUT1, "-1", FlowResultType.ABORT, "Hard limit is not a positive number")),
        ((DEFAULT_INPUT1, "6,6.0", FlowResultType.ABORT, "There are more hard limits entered than keys")),
        ((DEFAULT_INPUT1, "6", FlowResultType.FORM, "")),
        ((DEFAULT_INPUT2, "6,6.0", FlowResultType.FORM, "")),
        ((DEFAULT_INPUT2, "6", FlowResultType.FORM, "")),
    ],
)
async def test_options_hard_limit(hass: HomeAssistant, options, value, result, reason) -> None:
    """Test that valid/invalid hard limit is handled."""

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1 if options == DEFAULT_INPUT1 else MOCK_ENTRY2)
    flow.hass = hass
    user_input = copy.deepcopy(options)
    user_input[HARD_LIMIT_API] = value
    _result = await flow.async_step_init(user_input)
    assert _result["type"] == result
    if _result == FlowResultType.ABORT:
        assert _result["reason"] == reason


async def test_step_to_dampen(hass: HomeAssistant) -> None:
    """Test opening the dampening step."""

    user_input = copy.deepcopy(DEFAULT_INPUT1)
    user_input[CONFIG_DAMP] = True

    entry = MockConfigEntry(domain=DOMAIN, data={}, options=user_input)
    flow = SolcastSolarOptionFlowHandler(entry)
    flow.hass = hass
    result = await flow.async_step_init(user_input)
    await hass.async_block_till_done()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "dampen"


@pytest.mark.parametrize(
    ("value", "result"),
    [
        ({f"damp{factor:02d}": 0.8 for factor in range(24)}, FlowResultType.FORM),
    ],
)
async def test_dampen(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    value,
    result,
) -> None:
    """Test dampening step."""

    user_input = {**copy.deepcopy(DEFAULT_INPUT1), **value}

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1)
    flow.hass = hass

    _result = await flow.async_step_dampen(user_input)
    assert _result["step_id"] == "dampen"
    assert _result["type"] == result


async def test_entry_options_upgrade(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that entry options are upgraded as expected."""

    START_VERSION = 3
    FINAL_VERSION = 14
    V3OPTIONS = {
        CONF_API_KEY: "1",
        "const_disableautopoll": False,
    }
    config_dir = hass.config.config_dir
    entry = await async_init_integration(hass, copy.deepcopy(V3OPTIONS), version=START_VERSION)
    assert hass.data[DOMAIN].get("presumed_dead", True) is False

    try:
        assert entry.version == FINAL_VERSION
        # V4
        assert entry.options.get("const_disableautopoll") is None
        # V5
        for a in range(24):
            assert entry.options.get(f"damp{a:02d}") == 1.0
        # V6
        assert entry.options.get(CUSTOM_HOUR_SENSOR) == 1
        # V7
        assert entry.options.get(KEY_ESTIMATE) == "estimate"
        # V8
        assert entry.options.get(BRK_ESTIMATE) is True
        assert entry.options.get(BRK_ESTIMATE10) is True
        assert entry.options.get(BRK_ESTIMATE90) is True
        assert entry.options.get(BRK_SITE) is True
        assert entry.options.get(BRK_HALFHOURLY) is True
        assert entry.options.get(BRK_HOURLY) is True
        # V9
        assert entry.options.get(API_QUOTA) == "10"
        # V12
        assert entry.options.get(AUTO_UPDATE) == 0
        assert entry.options.get(BRK_SITE_DETAILED) is False
        assert entry.options.get(SITE_DAMP) is False  # "Hidden"-ish option
        # V14
        assert entry.options.get(HARD_LIMIT) is None
        assert entry.options.get(HARD_LIMIT_API) == "100.0"

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

        # Test API limit gets imported from existing cache in upgrade to V9
        data_file = Path(f"{config_dir}/solcast-usage.json")
        data_file.write_text(
            json.dumps({"daily_limit": 50, "daily_limit_consumed": 34, "reset": "2024-01-01T00:00:00+00:00"}), encoding="utf-8"
        )
        entry = await async_init_integration(hass, copy.deepcopy(V3OPTIONS), version=START_VERSION)
        assert hass.data[DOMAIN].get("presumed_dead", True) is False
        assert entry.options.get(API_QUOTA) == "50"

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    finally:
        assert await async_cleanup_integration_tests(hass)


async def test_presumed_dead_and_full_flow(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test presumption of death by setting "presumed dead" flag, and testing a config change."""

    entry = await async_init_integration(hass, DEFAULT_INPUT1)

    try:
        # Test presumed dead
        caplog.clear()
        assert hass.data[DOMAIN].get("presumed_dead", True) is False

        option = {BRK_ESTIMATE: False}
        user_input = DEFAULT_INPUT1_NO_DAMP | option
        hass.data[DOMAIN]["presumed_dead"] = True

        result = await hass.config_entries.options.async_init(entry.entry_id)
        await hass.async_block_till_done()
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input,
        )
        await hass.async_block_till_done()  # Integration will reload
        assert "Integration presumed dead, reloading" in caplog.text
        coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator
        solcast: SolcastApi = coordinator.solcast
        assert solcast.sites_status is SitesStatus.OK
        assert solcast._loaded_data is True

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

        # Test dampening step can  be reached
        option = {CONFIG_DAMP: True}
        user_input = DEFAULT_INPUT1_NO_DAMP | option

        result = await hass.config_entries.options.async_init(entry.entry_id)
        await hass.async_block_till_done()
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input,
        )
        await hass.async_block_till_done()
        assert result["type"] == FlowResultType.FORM

        user_input = {f"damp{factor:02d}": 0.9 for factor in range(24)}
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input,
        )
        await hass.async_block_till_done()
        assert result["result"] is True
        assert result["type"] == FlowResultType.CREATE_ENTRY

    finally:
        assert await async_cleanup_integration_tests(hass)
