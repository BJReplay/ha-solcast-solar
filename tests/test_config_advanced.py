"""Test the Solcast Solar advanced options."""

import asyncio
import copy
import json
import logging
from pathlib import Path
from typing import Any

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar.config_flow import (
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
    CONFIG_DISCRETE_NAME,
    CONFIG_FOLDER_DISCRETE,
    DEFAULT_DAMPENING_SUPPRESSION_ENTITY,
    DEFAULT_SOLCAST_HTTPS_URL,
    DOMAIN,
    GET_ACTUALS,
    ISSUE_ADVANCED_DEPRECATED,
    ISSUE_ADVANCED_PROBLEM,
    PROBLEMS,
    TASK_WATCH_ADVANCED_FILE_CHANGE,
)
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.solcastapi import SolcastApi
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from . import DEFAULT_INPUT1, async_cleanup_integration_tests, async_init_integration

_LOGGER = logging.getLogger(__name__)

# Keep advanced options tests on their own xdist worker to avoid side effects
# with shared filesystem state (the advanced options JSON file).
pytestmark = pytest.mark.xdist_group("solcast_advanced")


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


async def test_advanced_options(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test setting advanced options."""

    _least = 1
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
                last_record = 0
                while not any(text in r.getMessage() for r in caplog.records[last_record:]):
                    last_record = len(caplog.records)
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
                        f"{option}: {value} (must be {_least if 'matching' in option else advanced_options_with_aliases[option]['min']}-{advanced_options_with_aliases[option]['max']})"
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
