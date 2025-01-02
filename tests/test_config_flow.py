"""Test the Solcast Solar config flow."""

import copy
import json
import logging
from pathlib import Path

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
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from . import (
    CONFIG_DIR,
    DEFAULT_INPUT1,
    DEFAULT_INPUT2,
    KEY1,
    KEY2,
    async_cleanup_integration_tests,
    async_init_integration,
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

    flow = SolcastSolarFlowHandler()
    flow.hass = hass

    user_input = {CONF_API_KEY: KEY1, API_QUOTA: "10", AUTO_UPDATE: "1"}
    result = await flow.async_step_user(user_input)
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == TITLE
    assert result["data"] == {}
    assert result["options"][CONF_API_KEY] == KEY1
    assert result["options"][API_QUOTA] == "10"
    assert result["options"][AUTO_UPDATE] == 1
    assert result["options"][CUSTOM_HOUR_SENSOR] == 1
    assert result["options"][HARD_LIMIT_API] == "100.0"
    assert result["options"][KEY_ESTIMATE] == "estimate"
    assert result["options"][BRK_ESTIMATE] is True
    assert result["options"][BRK_ESTIMATE10] is True
    assert result["options"][BRK_ESTIMATE90] is True
    assert result["options"][BRK_SITE] is True
    assert result["options"][BRK_HALFHOURLY] is True
    assert result["options"][BRK_HOURLY] is True
    assert result["options"][BRK_SITE_DETAILED] is False


TEST_API_KEY = [
    {
        "set": {CONF_API_KEY: "1234-5678-8765-4321", API_QUOTA: "10", AUTO_UPDATE: "1"},
        "expect_type": FlowResultType.ABORT,
        "expect_reason": "API key looks like a site ID",
    },
    {
        "set": {CONF_API_KEY: KEY1 + "," + KEY1, API_QUOTA: "10", AUTO_UPDATE: "1"},
        "expect_type": FlowResultType.ABORT,
        "expect_reason": "Duplicate API key specified",
    },
    {"set": {CONF_API_KEY: KEY1, API_QUOTA: "10", AUTO_UPDATE: "0"}},
    {"set": {CONF_API_KEY: KEY1, API_QUOTA: "10", AUTO_UPDATE: "1"}},
    {"set": {CONF_API_KEY: KEY1 + "," + KEY2, API_QUOTA: "10", AUTO_UPDATE: "2"}},
    {
        "set": {CONF_API_KEY: KEY1 + "," + KEY2, API_QUOTA: "0", AUTO_UPDATE: "2"},
        "expect_type": FlowResultType.ABORT,
        "expect_reason": "API limit must be one or greater",
    },
]

TEST_API_QUOTA = [
    {
        "input": DEFAULT_INPUT1,
        "set": {CONF_API_KEY: KEY1, API_QUOTA: "1nvalid", AUTO_UPDATE: "1"},
        "expect_type": FlowResultType.ABORT,
        "expect_reason": "API limit is not a number",
    },
    {
        "input": DEFAULT_INPUT1,
        "set": {CONF_API_KEY: KEY1, API_QUOTA: "0", AUTO_UPDATE: "1"},
        "expect_type": FlowResultType.ABORT,
        "expect_reason": "API limit must be one or greater",
    },
    {
        "input": DEFAULT_INPUT1,
        "set": {CONF_API_KEY: KEY1, API_QUOTA: "10,10", AUTO_UPDATE: "1"},
        "expect_type": FlowResultType.ABORT,
        "expect_reason": "There are more API limit counts entered than keys",
    },
    {
        "input": DEFAULT_INPUT1,
        "set": {CONF_API_KEY: KEY1, API_QUOTA: "10", AUTO_UPDATE: "1"},
    },
    {
        "input": DEFAULT_INPUT2,
        "set": {CONF_API_KEY: KEY1 + "," + KEY2, API_QUOTA: "10,10", AUTO_UPDATE: "1"},
    },
    {
        "input": DEFAULT_INPUT2,
        "set": {CONF_API_KEY: KEY1 + "," + KEY2, API_QUOTA: "10,10,10", AUTO_UPDATE: "1"},
        "expect_type": FlowResultType.ABORT,
        "expect_reason": "There are more API limit counts entered than keys",
    },
    {
        "input": DEFAULT_INPUT2,
        "set": {CONF_API_KEY: KEY1 + "," + KEY2, API_QUOTA: "10", AUTO_UPDATE: "1"},
    },
]


async def test_init_api_key(hass: HomeAssistant) -> None:
    """Test that valid/invalid API key is handled in init."""

    flow = SolcastSolarFlowHandler()
    flow.hass = hass

    result = await flow.async_step_user()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    for test in TEST_API_KEY:
        result = await flow.async_step_user(test["set"])
        assert result["type"] == test.get("expect_type", FlowResultType.CREATE_ENTRY)
        if test.get("expect_type", FlowResultType.CREATE_ENTRY) is FlowResultType.ABORT:
            assert result["reason"] == test["expect_reason"]


async def test_init_api_quota(hass: HomeAssistant) -> None:
    """Test that valid/invalid API quota is handled in init."""

    flow = SolcastSolarFlowHandler()
    flow.hass = hass

    for test in TEST_API_QUOTA:
        result = await flow.async_step_user(test["set"])
        assert result["type"] == test.get("expect_type", FlowResultType.CREATE_ENTRY)
        if test.get("expect_type", FlowResultType.CREATE_ENTRY) is FlowResultType.ABORT:
            assert result["reason"] == test["expect_reason"]


async def test_reconfigure_api_key(recorder_mock: Recorder, hass: HomeAssistant) -> None:
    """Test that valid/invalid API key is handled in reconfigure."""

    entry = await async_init_integration(hass, DEFAULT_INPUT1)
    assert hass.data[DOMAIN].get("has_loaded", False) is True

    for test in TEST_API_KEY:
        for flow in [entry.start_reauth_flow, entry.start_reconfigure_flow]:
            result = await flow(hass)

            assert result["type"] == FlowResultType.FORM
            assert result["step_id"] == "reconfigure_confirm"
            _result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input=test["set"],
            )
            if _result["reason"] != "reconfigured":
                assert _result["reason"] == test.get("expect_reason", "")
                assert _result["type"] == test["expect_type"]


async def test_reconfigure_api_quota(recorder_mock: Recorder, hass: HomeAssistant) -> None:
    """Test that valid/invalid API quota is handled in reconfigure."""

    _input = None
    for test in TEST_API_QUOTA:
        if _input is None or test["input"] != _input:
            entry = await async_init_integration(hass, test["input"])
            assert hass.data[DOMAIN].get("has_loaded", False) is True
            _input = copy.deepcopy(test["input"])
        for flow in [entry.start_reauth_flow, entry.start_reconfigure_flow]:
            result = await flow(hass)

            assert result["type"] == FlowResultType.FORM
            assert result["step_id"] == "reconfigure_confirm"
            _result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input=test["set"],
            )
            if _result["reason"] != "reconfigured":
                assert _result["reason"] == test.get("expect_reason", "")
                assert _result["type"] == test["expect_type"]


async def test_option_api_key(hass: HomeAssistant) -> None:
    """Test that valid/invalid API key is handled."""

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1)
    flow.hass = hass

    for test in TEST_API_KEY:
        result = await flow.async_step_init(test["set"])
        assert result["type"] == test.get("expect_type", FlowResultType.FORM)
        if test.get("expect_type", FlowResultType.FORM) is FlowResultType.ABORT:
            assert result["reason"] == test["expect_reason"]


async def test_option_api_quota(hass: HomeAssistant) -> None:
    """Test that valid/invalid API quota is handled."""

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1)
    flow.hass = hass

    for test in TEST_API_QUOTA:
        result = await flow.async_step_init(test["set"])
        assert result["type"] == test.get("expect_type", FlowResultType.FORM)
        if test.get("expect_type", FlowResultType.FORM) is FlowResultType.ABORT:
            assert result["reason"] == test["expect_reason"]


async def test_option_custom_hour_sensor(hass: HomeAssistant) -> None:
    """Test that valid/invalid custom hour sensor is handled."""

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1)
    flow.hass = hass

    user_input = copy.deepcopy(DEFAULT_INPUT1)
    user_input[CUSTOM_HOUR_SENSOR] = 0
    result = await flow.async_step_init(user_input)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "Custom sensor not between 1 and 144"

    user_input[CUSTOM_HOUR_SENSOR] = 145
    result = await flow.async_step_init(user_input)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "Custom sensor not between 1 and 144"

    user_input[CUSTOM_HOUR_SENSOR] = 8
    result = await flow.async_step_init(user_input)
    assert result["type"] == FlowResultType.FORM


async def test_option_hard_limit(hass: HomeAssistant) -> None:
    """Test that valid/invalid hard limit is handled."""

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1)
    flow.hass = hass
    user_input = copy.deepcopy(DEFAULT_INPUT1)

    user_input[HARD_LIMIT_API] = "invalid"
    result = await flow.async_step_init(user_input)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "Hard limit is not a positive number"

    user_input[HARD_LIMIT_API] = "-1"
    result = await flow.async_step_init(user_input)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "Hard limit is not a positive number"

    user_input[HARD_LIMIT_API] = "6,6.0"
    result = await flow.async_step_init(user_input)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "There are more hard limits entered than keys"

    user_input[HARD_LIMIT_API] = "6"
    result = await flow.async_step_init(user_input)
    assert result["type"] == FlowResultType.FORM

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY2)
    flow.hass = hass
    user_input = copy.deepcopy(DEFAULT_INPUT2)

    user_input[HARD_LIMIT_API] = "6,6.0"
    result = await flow.async_step_init(user_input)
    assert result["type"] == FlowResultType.FORM

    user_input[HARD_LIMIT_API] = "6"
    result = await flow.async_step_init(user_input)
    assert result["type"] == FlowResultType.FORM


async def test_step_to_dampen(hass: HomeAssistant) -> None:
    """Test opening the dampening step."""

    user_input = copy.deepcopy(DEFAULT_INPUT1)
    # user_input[SITE_DAMP] = True
    user_input[CONFIG_DAMP] = True

    entry = MockConfigEntry(domain=DOMAIN, data={}, options=user_input)
    flow = SolcastSolarOptionFlowHandler(entry)
    flow.hass = hass

    result = await flow.async_step_init(user_input)
    await hass.async_block_till_done()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "dampen"


async def test_dampen(hass: HomeAssistant) -> None:
    """Test dampening step."""

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1)
    flow.hass = hass

    result = await flow.async_step_dampen()

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "dampen"

    user_input = {f"damp{factor:02d}": 1.0 for factor in range(24)}
    result = await flow.async_step_dampen(user_input)
    assert result["type"] == FlowResultType.FORM

    user_input = {f"damp{factor:02d}": 0.0 for factor in range(24)}
    result = await flow.async_step_dampen(user_input)
    assert result["type"] == FlowResultType.FORM


async def test_entry_options_upgrade(
    recorder_mock: Recorder,
    hass: HomeAssistant,
) -> None:
    """Test that entry options are upgraded as expected."""

    START_VERSION = 3
    FINAL_VERSION = 14
    V3OPTIONS = {
        CONF_API_KEY: "1",
        "const_disableautopoll": False,
    }
    entry = await async_init_integration(hass, copy.deepcopy(V3OPTIONS), version=START_VERSION)
    assert hass.data[DOMAIN].get("has_loaded", False) is True

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
        data_file = Path(f"{CONFIG_DIR}/solcast-usage.json")
        data_file.write_text(
            json.dumps({"daily_limit": 50, "daily_limit_consumed": 34, "reset": "2024-01-01T00:00:00+00:00"}), encoding="utf-8"
        )
        entry = await async_init_integration(hass, copy.deepcopy(V3OPTIONS), version=START_VERSION)
        assert hass.data[DOMAIN].get("has_loaded", False) is True
        assert entry.options.get(API_QUOTA) == "50"

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    finally:
        assert await async_cleanup_integration_tests(hass)
