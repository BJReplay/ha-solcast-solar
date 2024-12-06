"""Test the Solcast Solar config flow."""

import copy
import logging
from unittest.mock import AsyncMock

# As a core component, these imports would be homeassistant.components.solcast_solar and not config.custom_components.solcast_solar
from config.custom_components.solcast_solar.config_flow import (
    SolcastSolarFlowHandler,
    SolcastSolarOptionFlowHandler,
)
from config.custom_components.solcast_solar.const import (
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
    HARD_LIMIT_API,
    KEY_ESTIMATE,
    SITE_DAMP,
    TITLE,
)

from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from tests.common import MockConfigEntry

_LOGGER = logging.getLogger(__name__)

KEY = "65sa6d46-sadf876_sd54"
DEFAULT_INPUT = {
    CONF_API_KEY: KEY,
    API_QUOTA: "10",
    AUTO_UPDATE: "1",
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
    SITE_DAMP: False,
}
SITE_DAMP = {f"damp{factor:02d}": 1.0 for factor in range(24)}

MOCK_ENTRY = MockConfigEntry(domain=DOMAIN, data={}, options=DEFAULT_INPUT)


async def test_create_entry(hass: HomeAssistant) -> None:
    """Test that a valid user input creates an entry."""
    flow = SolcastSolarFlowHandler()
    flow.hass = hass
    flow.__conflicting_integration = AsyncMock(return_value=(False, ""))

    user_input = {CONF_API_KEY: "65sa6d46-sadf876_sd54", API_QUOTA: "10", AUTO_UPDATE: "1"}
    result = await flow.async_step_user(user_input)
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == TITLE
    assert result["data"] == {}
    assert result["options"][CONF_API_KEY] == KEY
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


async def test_invalid_api_key(hass: HomeAssistant) -> None:
    """Test that invalid API key is handled."""
    flow = SolcastSolarFlowHandler()
    flow.hass = hass
    flow.__conflicting_integration = AsyncMock(return_value=(False, ""))

    user_input = {CONF_API_KEY: "1234-5678-8765-4321", API_QUOTA: "10", AUTO_UPDATE: "1"}
    result = await flow.async_step_user(user_input)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "API key looks like a site ID"

    user_input = {CONF_API_KEY: KEY + "," + KEY, API_QUOTA: "10", AUTO_UPDATE: "1"}
    result = await flow.async_step_user(user_input)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "Duplicate API key specified"


async def test_invalid_api_quota(hass: HomeAssistant) -> None:
    """Test that invalid API quota is handled."""
    flow = SolcastSolarFlowHandler()
    flow.hass = hass
    flow.__conflicting_integration = AsyncMock(return_value=(False, ""))

    user_input = {CONF_API_KEY: KEY, API_QUOTA: "invalid", AUTO_UPDATE: "1"}
    result = await flow.async_step_user(user_input)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "API limit is not a number"

    user_input = {CONF_API_KEY: KEY, API_QUOTA: "0", AUTO_UPDATE: "1"}
    result = await flow.async_step_user(user_input)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "API limit must be one or greater"

    user_input = {CONF_API_KEY: KEY, API_QUOTA: "10,10", AUTO_UPDATE: "1"}
    result = await flow.async_step_user(user_input)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "There are more API limit counts entered than keys"


async def test_option_invalid_api_key(hass: HomeAssistant) -> None:
    """Test that invalid API key is handled."""
    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY)
    flow.hass = hass
    flow.__conflicting_integration = AsyncMock(return_value=(False, ""))

    user_input = {CONF_API_KEY: "1234-5678-8765-4321", API_QUOTA: "10", AUTO_UPDATE: "1"}
    result = await flow.async_step_init(user_input)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "API key looks like a site ID"

    user_input[CONF_API_KEY] = KEY + "," + KEY
    result = await flow.async_step_init(user_input)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "Duplicate API key specified"


async def test_option_invalid_custom_hour_sensor(hass: HomeAssistant) -> None:
    """Test that invalid custom hour sensor is handled."""
    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY)
    flow.hass = hass
    flow.__conflicting_integration = AsyncMock(return_value=(False, ""))

    user_input = copy.deepcopy(DEFAULT_INPUT)
    user_input[CUSTOM_HOUR_SENSOR] = 0
    result = await flow.async_step_init(user_input)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "Custom sensor not between 1 and 144"

    user_input[CUSTOM_HOUR_SENSOR] = 145
    result = await flow.async_step_init(user_input)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "Custom sensor not between 1 and 144"


async def test_option_invalid_api_quota(hass: HomeAssistant) -> None:
    """Test that invalid API quota is handled."""
    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY)
    flow.hass = hass
    flow.__conflicting_integration = AsyncMock(return_value=(False, ""))

    user_input = copy.deepcopy(DEFAULT_INPUT)
    user_input[API_QUOTA] = "invalid"
    result = await flow.async_step_init(user_input)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "API limit is not a number"

    user_input[API_QUOTA] = "0"
    result = await flow.async_step_init(user_input)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "API limit must be one or greater"

    user_input[API_QUOTA] = "10,10"
    result = await flow.async_step_init(user_input)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "There are more API limit counts entered than keys"


async def test_option_invalid_hard_limit(hass: HomeAssistant) -> None:
    """Test that invalid hard limit is handled."""
    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY)
    flow.hass = hass
    flow.__conflicting_integration = AsyncMock(return_value=(False, ""))

    user_input = copy.deepcopy(DEFAULT_INPUT)
    user_input[HARD_LIMIT_API] = "invalid"
    result = await flow.async_step_init(user_input)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "Hard limit is not a positive number"

    user_input[HARD_LIMIT_API] = "-1"
    result = await flow.async_step_init(user_input)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "Hard limit is not a positive number"

    user_input[HARD_LIMIT_API] = "6,6"
    result = await flow.async_step_init(user_input)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "There are more hard limits entered than keys"
