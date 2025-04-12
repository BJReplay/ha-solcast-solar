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
    EXCLUDE_SITES,
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
    MOCK_FORBIDDEN,
    async_cleanup_integration_tests,
    async_init_integration,
    async_setup_aioresponses,
    session_clear,
    session_set,
    simulator,
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
    ({CONF_API_KEY: "1234-5678-8765-4321", API_QUOTA: "10", AUTO_UPDATE: "1"}, "API key looks like a site ID"),
    ({CONF_API_KEY: KEY1 + "," + KEY1, API_QUOTA: "10", AUTO_UPDATE: "1"}, "Duplicate API key specified"),
    ({CONF_API_KEY: KEY1, API_QUOTA: "10", AUTO_UPDATE: "0"}, None),
    ({CONF_API_KEY: KEY1, API_QUOTA: "10", AUTO_UPDATE: "1"}, None),
    ({CONF_API_KEY: KEY1 + "," + KEY2, API_QUOTA: "10", AUTO_UPDATE: "2"}, None),
    ({CONF_API_KEY: KEY1 + "," + KEY2, API_QUOTA: "0", AUTO_UPDATE: "2"}, "API limit must be one or greater"),
]

TEST_REAUTH_API_KEY = [
    ({CONF_API_KEY: "1234-5678-8765-4321"}, "API key looks like a site ID"),
    ({CONF_API_KEY: KEY1 + "," + KEY1}, "Duplicate API key specified"),
    ({CONF_API_KEY: "555"}, "Bad API key, 403/Forbidden"),
    ({CONF_API_KEY: KEY1 + "," + KEY2}, None),
]

TEST_KEY_CHANGES = [
    {
        "options": {CONF_API_KEY: "555", API_QUOTA: "10", AUTO_UPDATE: "1"},
        "assert": "Bad API key, 403/Forbidden",
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
    {
        "options": {CONF_API_KEY: "2", API_QUOTA: "10", AUTO_UPDATE: "1"},
        "assert": None,
        "set": None,
    },
]

TEST_API_QUOTA = [
    (DEFAULT_INPUT1, {CONF_API_KEY: KEY1, API_QUOTA: "invalid", AUTO_UPDATE: "1"}, "API limit is not a number"),
    (DEFAULT_INPUT1, {CONF_API_KEY: KEY1, API_QUOTA: "0", AUTO_UPDATE: "1"}, "API limit must be one or greater"),
    (
        DEFAULT_INPUT1,
        {CONF_API_KEY: KEY1, API_QUOTA: "10,10", AUTO_UPDATE: "1"},
        "There are more API limit counts entered than keys",
    ),
    (DEFAULT_INPUT1, {CONF_API_KEY: KEY1, API_QUOTA: "10", AUTO_UPDATE: "1"}, None),
    (DEFAULT_INPUT2, {CONF_API_KEY: KEY1 + "," + KEY2, API_QUOTA: "10,10", AUTO_UPDATE: "1"}, None),
    (
        DEFAULT_INPUT2,
        {CONF_API_KEY: KEY1 + "," + KEY2, API_QUOTA: "10,10,10", AUTO_UPDATE: "1"},
        "There are more API limit counts entered than keys",
    ),
    (DEFAULT_INPUT2, {CONF_API_KEY: KEY1 + "," + KEY2, API_QUOTA: "10", AUTO_UPDATE: "1"}, None),
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
        EXCLUDE_SITES: [],
    }

    user_input = {CONF_API_KEY: KEY1, API_QUOTA: "10", AUTO_UPDATE: "1"}
    result = await flow.async_step_user(user_input)
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == TITLE
    assert result["data"] == {}
    for key, expect in expected_options.items():
        assert result["options"][key] == expect


@pytest.mark.parametrize(("user_input", "reason"), TEST_API_KEY)
async def test_init_api_key(hass: HomeAssistant, user_input, reason) -> None:
    """Test that valid/invalid API key is handled in config flow."""

    flow = SolcastSolarFlowHandler()
    flow.hass = hass

    result = await flow.async_step_user()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    result = await flow.async_step_user(user_input)
    if reason is not None:
        assert result["errors"]["base"] == reason


async def test_config_api_key_invalid(hass: HomeAssistant) -> None:
    """Test that invalid API key is handled in config flow."""

    await async_setup_aioresponses()

    flow = SolcastSolarFlowHandler()
    flow.hass = hass

    result = await flow.async_step_user({CONF_API_KEY: "555", API_QUOTA: "10", AUTO_UPDATE: "1"})
    assert "Bad API key, 403/Forbidden" in result["errors"]["base"]

    result = await flow.async_step_user({CONF_API_KEY: "no_sites", API_QUOTA: "10", AUTO_UPDATE: "1"})
    assert "No sites found for API key" in result["errors"]["base"]

    session_set(MOCK_BUSY)
    result = await flow.async_step_user({CONF_API_KEY: "1", API_QUOTA: "10", AUTO_UPDATE: "1"})
    assert "Error 429/Try again later for API key" in result["errors"]["base"]
    session_clear(MOCK_BUSY)


@pytest.mark.parametrize(("options", "user_input", "reason"), TEST_API_QUOTA)
async def test_config_api_quota(hass: HomeAssistant, options, user_input, reason) -> None:
    """Test that valid/invalid API quota is handled in config flow."""

    flow = SolcastSolarFlowHandler()
    flow.hass = hass

    result = await flow.async_step_user()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    result = await flow.async_step_user(user_input)
    if reason is not None:
        assert result["errors"]["base"] == reason


async def test_reauth_api_key(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that valid/invalid API key is handled in reconfigure.

    Not parameterised for performance reasons and to maintain caches between tests.
    """
    USER_INPUT = 0
    REASON = 1

    try:
        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        assert hass.data[DOMAIN].get("presumed_dead", True) is False

        for test in TEST_REAUTH_API_KEY:
            result = await entry.start_reauth_flow(hass)
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "reauth_confirm"
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input=test[USER_INPUT],
            )
            await hass.async_block_till_done()
            if result.get("reason") != "reauth_successful":
                assert test[REASON] in result["errors"]["base"]

        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

        # Really change key '1' (last test above used API keys '1' and '2', so these are in cached sites/usage)
        entry = await async_init_integration(hass, DEFAULT_INPUT2)
        simulator.API_KEY_SITES["4"] = simulator.API_KEY_SITES.pop("1")  # Change the key
        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_API_KEY: "4" + "," + KEY2},
        )
        await hass.async_block_till_done()
        assert result["reason"] == "reauth_successful"
        assert "An API key has changed, resetting usage" not in caplog.text  # Existing key change, so not seen
        assert "API key ******4 has changed, migrating API usage" in caplog.text
        assert "Using extant cache data for API key ******4" in caplog.text
        assert "API counter for ******4 is 4/20" in caplog.text
        assert "Using extant cache data for API key ******2" not in caplog.text  # Unaffected
        assert "API counter for ******2 is 2/20" in caplog.text  # Unaffected, was 2/20 after previous test
        simulator.API_KEY_SITES["1"] = simulator.API_KEY_SITES.pop("4")  # Restore the key
        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
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
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_API_KEY: "4" + "," + KEY2},
        )
        assert "Test connection to https://api.solcast.com.au/rooftop_sites?format=json&api_key=******4" in caplog.text
        assert "Loading presumed dead integration" in caplog.text
        simulator.API_KEY_SITES["1"] = simulator.API_KEY_SITES.pop("4")  # Restore the key

    finally:
        assert await async_cleanup_integration_tests(hass)


async def test_reconfigure_api_key(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that valid/invalid API key is handled in reconfigure.

    Not parameterised for performance reasons.
    """
    USER_INPUT = 0
    REASON = 1

    try:
        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        assert hass.data[DOMAIN].get("presumed_dead", True) is False

        for test in TEST_API_KEY:
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
                data=entry.data,
            )
            # await hass.async_block_till_done()
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "reconfigure_confirm"
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input=test[USER_INPUT],
            )
            await hass.async_block_till_done()
            if result.get("reason") != "reconfigured":
                assert result["errors"]["base"] == test[REASON]

        for test in TEST_KEY_CHANGES:
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
            await hass.async_block_till_done()
            if test["set"]:
                session_clear(test["set"])
            if test["assert"]:
                assert test["assert"] in result["errors"]["base"]
            else:
                assert result["reason"] == "reconfigured"

        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

        # Test start after reconfigure when presumed dead...
        hass.data[DOMAIN]["presumed_dead"] = True
        simulator.API_KEY_SITES["4"] = simulator.API_KEY_SITES.pop("1")  # Change the key
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id}, data=entry.data
        )
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_API_KEY: "4" + "," + KEY2, API_QUOTA: "10", AUTO_UPDATE: "0"}
        )
        await hass.async_block_till_done()
        assert "Test connection to https://api.solcast.com.au/rooftop_sites?format=json&api_key=******4" in caplog.text
        assert "Loading presumed dead integration" in caplog.text
        simulator.API_KEY_SITES["1"] = simulator.API_KEY_SITES.pop("4")  # Restore the key

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
    REASON = 2

    try:
        _input = None
        for test in TEST_API_QUOTA:
            entry = await async_init_integration(hass, test[OPTIONS])
            assert hass.data[DOMAIN].get("presumed_dead", True) is False

            if _input is None or test[OPTIONS] != _input:
                _input = copy.deepcopy(test[OPTIONS])
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
                data=entry.data,
            )
            await hass.async_block_till_done()
            assert result["type"] == FlowResultType.FORM
            assert result["step_id"] == "reconfigure_confirm"
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input=test[USER_INPUT],
            )
            await hass.async_block_till_done()
            if test[REASON]:
                assert result["errors"]["base"] == test[REASON]

    finally:
        assert await async_cleanup_integration_tests(hass)


@pytest.mark.parametrize(("user_input", "reason"), TEST_API_KEY)
async def test_options_api_key(hass: HomeAssistant, user_input, reason) -> None:
    """Test that valid/invalid API key is handled in option flow init."""

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1)
    flow.hass = hass

    result = await flow.async_step_init()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"
    result = await flow.async_step_init(user_input)
    if reason is not None:
        assert result["errors"]["base"] == reason


async def test_options_api_key_invalid(hass: HomeAssistant) -> None:
    """Test that invalid API key is handled in options flow."""

    await async_setup_aioresponses()

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1)
    flow.hass = hass

    options = DEFAULT_INPUT1

    inject = {CONF_API_KEY: "555"}
    result = await flow.async_step_init({**options, **inject})
    assert "Bad API key, 403/Forbidden" in result["errors"]["base"]

    inject = {CONF_API_KEY: "no_sites"}
    result = await flow.async_step_init({**options, **inject})
    assert "No sites found for API key" in result["errors"]["base"]

    session_set(MOCK_BUSY)
    result = await flow.async_step_init(options)
    assert "Error 429/Try again later for API key" in result["errors"]["base"]
    session_clear(MOCK_BUSY)


@pytest.mark.parametrize(("options", "user_input", "reason"), TEST_API_QUOTA)
async def test_options_api_quota(hass: HomeAssistant, options, user_input, reason) -> None:
    """Test that valid/invalid API quota is handled in option flow init."""

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1)
    flow.hass = hass

    result = await flow.async_step_init()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"
    result = await flow.async_step_init({**options, **user_input})
    if reason is not None:
        assert result["errors"]["base"] == reason


@pytest.mark.parametrize(
    ("options", "value", "reason"),
    [
        ((DEFAULT_INPUT1, 0, "Custom sensor not between 1 and 144")),
        ((DEFAULT_INPUT1, 145, "Custom sensor not between 1 and 144")),
        ((DEFAULT_INPUT1, 8, None)),
    ],
)
async def test_options_custom_hour_sensor(hass: HomeAssistant, options, value, reason) -> None:
    """Test that valid/invalid custom hour sensor is handled."""

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1)
    flow.hass = hass

    user_input = copy.deepcopy(options)
    user_input[CUSTOM_HOUR_SENSOR] = value
    result = await flow.async_step_init(user_input)
    if reason is not None:
        assert result["errors"]["base"] == reason


@pytest.mark.parametrize(
    ("options", "value", "reason"),
    [
        ((DEFAULT_INPUT1, "invalid", "Hard limit is not a positive number")),
        ((DEFAULT_INPUT1, "-1", "Hard limit is not a positive number")),
        ((DEFAULT_INPUT1, "6,6.0", "There are more hard limits entered than keys")),
        ((DEFAULT_INPUT1, "6", None)),
        ((DEFAULT_INPUT2, "6,6.0", None)),
        ((DEFAULT_INPUT2, "6", None)),
    ],
)
async def test_options_hard_limit(hass: HomeAssistant, options, value, reason) -> None:
    """Test that valid/invalid hard limit is handled."""

    flow = SolcastSolarOptionFlowHandler(MOCK_ENTRY1 if options == DEFAULT_INPUT1 else MOCK_ENTRY2)
    flow.hass = hass
    user_input = copy.deepcopy(options)
    user_input[HARD_LIMIT_API] = value
    result = await flow.async_step_init(user_input)
    if reason is not None:
        assert result["errors"]["base"] == reason


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
    ("value"),
    [
        ({f"damp{factor:02d}": 0.8 for factor in range(24)}),
    ],
)
async def test_dampen(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    value,
) -> None:
    """Test dampening step."""

    user_input = {**copy.deepcopy(DEFAULT_INPUT1), **value}
    entry = await async_init_integration(hass, DEFAULT_INPUT1)

    try:
        for key in value:
            assert entry.options[key] == 1.0

        flow = SolcastSolarOptionFlowHandler(entry)
        flow.hass = hass

        result = await flow.async_step_dampen(user_input)
        assert result["reason"] == "reconfigured"
        for key, expect in value.items():
            assert entry.options[key] == expect

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    finally:
        assert await async_cleanup_integration_tests(hass)


async def test_entry_options_upgrade(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that entry options are upgraded as expected."""

    START_VERSION = 3
    FINAL_VERSION = 15
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
        # V15
        assert entry.options.get(EXCLUDE_SITES) == []

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
        assert result["reason"] == "reconfigured"

    finally:
        assert await async_cleanup_integration_tests(hass)
