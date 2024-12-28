"""Test the Solcast Solar config flow."""

import copy
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock

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
    DEFAULT_INPUT1,
    DEFAULT_INPUT2,
    async_cleanup_integration_tests,
    async_init_integration,
)

from tests.common import MockConfigEntry

_LOGGER = logging.getLogger(__name__)

KEY1 = "65sa6d46-sadf876_sd54"
KEY2 = "65sa6946-glad876_pf69"

DEFAULT_INPUT1 = copy.deepcopy(DEFAULT_INPUT1)
DEFAULT_INPUT1[CONF_API_KEY] = KEY1

DEFAULT_INPUT2 = copy.deepcopy(DEFAULT_INPUT2)
DEFAULT_INPUT2[CONF_API_KEY] = KEY1 + "," + KEY2

MOCK_ENTRY1 = MockConfigEntry(domain=DOMAIN, data={}, options=DEFAULT_INPUT1)
MOCK_ENTRY2 = MockConfigEntry(domain=DOMAIN, data={}, options=DEFAULT_INPUT2)


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


async def api_key(step, expect):
    """Test that valid/invalid API key is handled."""

    user_input = {CONF_API_KEY: "1234-5678-8765-4321", API_QUOTA: "10", AUTO_UPDATE: "1"}
    result = await step(user_input)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "API key looks like a site ID"

    user_input = {CONF_API_KEY: KEY1 + "," + KEY1, API_QUOTA: "10", AUTO_UPDATE: "1"}
    result = await step(user_input)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "Duplicate API key specified"

    user_input = {CONF_API_KEY: KEY1, API_QUOTA: "10", AUTO_UPDATE: "0"}
    result = await step(user_input)
    assert result["type"] == expect

    user_input = {CONF_API_KEY: KEY1, API_QUOTA: "10", AUTO_UPDATE: "1"}
    result = await step(user_input)
    assert result["type"] == expect

    user_input = {CONF_API_KEY: KEY1 + "," + KEY2, API_QUOTA: "10", AUTO_UPDATE: "2"}
    result = await step(user_input)
    assert result["type"] == expect

    user_input = {CONF_API_KEY: KEY1 + "," + KEY2, API_QUOTA: "0", AUTO_UPDATE: "2"}
    result = await step(user_input)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "API limit must be one or greater"


async def api_quota(hass: HomeAssistant, step, expect):
    """Test that valid/invalid API quota is handled."""

    user_input = copy.deepcopy(DEFAULT_INPUT1)
    user_input[API_QUOTA] = "1nvalid"
    result = await step(user_input)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "API limit is not a number"

    user_input[API_QUOTA] = "0"
    result = await step(user_input)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "API limit must be one or greater"

    user_input[API_QUOTA] = "10,10"
    result = await step(user_input)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "There are more API limit counts entered than keys"

    user_input[API_QUOTA] = "10"
    result = await step(user_input)
    assert result["type"] == expect

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY2)
    flow.hass = hass
    user_input = copy.deepcopy(DEFAULT_INPUT2)

    user_input[API_QUOTA] = "10,10"
    result = await step(user_input)
    assert result["type"] == expect

    user_input[API_QUOTA] = "10,10,10"
    result = await step(user_input)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "There are more API limit counts entered than keys"

    user_input[API_QUOTA] = "10"
    result = await step(user_input)
    assert result["type"] == expect


async def test_api_key(hass: HomeAssistant) -> None:
    """Test that valid/invalid API key is handled."""

    flow = SolcastSolarFlowHandler()
    flow.hass = hass

    result = await flow.async_step_user()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    await api_key(flow.async_step_user, FlowResultType.CREATE_ENTRY)


async def test_api_quota(hass: HomeAssistant) -> None:
    """Test that valid/invalid API quota is handled."""

    flow = SolcastSolarFlowHandler()
    flow.hass = hass

    await api_quota(hass, flow.async_step_user, FlowResultType.CREATE_ENTRY)


async def test_option_api_key(hass: HomeAssistant) -> None:
    """Test that valid/invalid API key is handled."""

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1)
    flow.hass = hass

    await api_key(flow.async_step_init, FlowResultType.FORM)


async def test_option_api_quota(hass: HomeAssistant) -> None:
    """Test that valid/invalid API quota is handled."""

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1)
    flow.hass = hass

    await api_key(flow.async_step_init, FlowResultType.FORM)


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
    config_dir = hass.data[DOMAIN][entry.entry_id].solcast._config_dir

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
        assert hass.data[DOMAIN].get("has_loaded", False) is True
        assert entry.options.get(API_QUOTA) == "50"

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    finally:
        assert await async_cleanup_integration_tests(hass, config_dir)
