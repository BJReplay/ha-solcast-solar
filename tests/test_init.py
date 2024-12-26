"""Tests for the Solcast Solar initialisation."""

import asyncio
import datetime
from datetime import datetime as dt, timedelta
import json
import logging
from pathlib import Path

import pytest
from voluptuous.error import MultipleInvalid

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar.const import (
    DOMAIN,
    EVENT_END_DATETIME,
    EVENT_START_DATETIME,
    SITE,
    UNDAMPENED,
)
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.solcastapi import SolcastApi
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from . import (
    BAD_INPUT,
    DEFAULT_INPUT1,
    DEFAULT_INPUT2,
    ZONE,
    async_cleanup_integration_tests,
    async_init_integration,
)

_LOGGER = logging.getLogger(__name__)

SERVICES = [
    "clear_all_solcast_data",
    "force_update_forecasts",
    "get_dampening",
    "query_forecast_data",
    "remove_hard_limit",
    "set_dampening",
    "set_hard_limit",
    "update_forecasts",
]


@pytest.mark.parametrize(
    "input",
    [
        BAD_INPUT,
        DEFAULT_INPUT1,
        DEFAULT_INPUT2,
    ],
)
async def test_init(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    input: dict,
) -> None:
    """Test integration init."""

    # Test startup
    entry = await async_init_integration(hass, input)

    if input == BAD_INPUT:
        assert hass.data[DOMAIN].get("has_loaded") is None
        assert "Dampening factors corrupt or not found, setting to 1.0" in caplog.text
        assert "Error getting sites for the API key ******badkey, is the key correct?" in caplog.text
        return

    assert hass.data[DOMAIN].get("has_loaded") is True
    config_dir = hass.data[DOMAIN][entry.entry_id].solcast._config_dir
    coordinator: SolcastUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    solcast: SolcastApi = coordinator.solcast
    # assert "Creating usage cache for" in caplog.text
    assert solcast.sites_loaded is True
    assert solcast._loaded_data is True
    assert "Dampening factors corrupt or not found, setting to 1.0" not in caplog.text
    assert solcast._tz == ZONE

    # Test cache files are as expected
    if len(input["api_key"].split(",")) == 1:
        assert not Path(f"{config_dir}/solcast-sites-1.json").is_file()
        assert not Path(f"{config_dir}/solcast-sites-2.json").is_file()
        assert Path(f"{config_dir}/solcast-sites.json").is_file()
        assert not Path(f"{config_dir}/solcast-usage-1.json").is_file()
        assert not Path(f"{config_dir}/solcast-usage-2.json").is_file()
        assert Path(f"{config_dir}/solcast-usage.json").is_file()
    else:
        assert Path(f"{config_dir}/solcast-sites-1.json").is_file()
        assert Path(f"{config_dir}/solcast-sites-2.json").is_file()
        assert not Path(f"{config_dir}/solcast-sites.json").is_file()
        assert Path(f"{config_dir}/solcast-usage-1.json").is_file()
        assert Path(f"{config_dir}/solcast-usage-2.json").is_file()
        assert not Path(f"{config_dir}/solcast-usage.json").is_file()

    # Test coordinator tasks are created
    assert len(coordinator.tasks.keys()) == 3

    # Test expected services are registered
    assert len(hass.services.async_services_for_domain(DOMAIN).keys()) == len(SERVICES)
    for service in SERVICES:
        assert hass.services.has_service(DOMAIN, service) is True

    # Test refused update without forcing
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "update_forecasts", {}, blocking=True)

    async def _exec_update(action: str, last_update_delta: int = 0):
        """Execute an action and wait for completion."""
        async with asyncio.timeout(2):
            if last_update_delta == 0:
                last_updated = dt(year=2020, month=1, day=1, hour=1, minute=1, second=1, tzinfo=datetime.UTC)
            else:
                last_updated = solcast._data["last_updated"] - timedelta(seconds=last_update_delta)
                _LOGGER.info("Mock last updated: %s", last_updated)
            solcast._data["last_updated"] = last_updated
            await hass.services.async_call(DOMAIN, action, {}, blocking=True)
            await hass.async_block_till_done()
            while (
                "Forecast update completed successfully" not in caplog.text
                and "Not requesting a solar forecast" not in caplog.text
                and "ERROR" not in caplog.text
            ):  # Wait for task to complete
                await asyncio.sleep(0.01)

    # Test forced update and clear data actions
    await _exec_update("force_update_forecasts")
    await _exec_update("clear_all_solcast_data")

    # Test for API key redaction
    for api_key in input["api_key"].split(","):
        assert "key=" + api_key not in caplog.text
        assert "key: " + api_key not in caplog.text
        assert "sites-" + api_key not in caplog.text
        assert "usage-" + api_key not in caplog.text

    # Test update within ten seconds of prior update
    solcast.options.auto_update = 0
    await _exec_update("update_forecasts", last_update_delta=5)
    assert "Not requesting a solar forecast because time is within ten seconds of last update" in caplog.text
    assert "ERROR" not in caplog.text
    caplog.clear()

    # Create a granular dampening file to be read on next update
    granular_dampening = (
        {
            "1111-1111-1111-1111": [0.8] * 24,
            "2222-2222-2222-2222": [0.9] * 24,
        }
        if input == DEFAULT_INPUT1
        else {
            "1111-1111-1111-1111": [0.7] * 48,
            "2222-2222-2222-2222": [0.8] * 48,
            "3333-3333-3333-3333": [0.9] * 48,
        }
    )
    granular_dampening_file = Path(f"{config_dir}/solcast-dampening.json")
    granular_dampening_file.write_text(json.dumps(granular_dampening), encoding="utf-8")

    # Test update beyond ten seconds of prior update
    solcast.options.auto_update = 0
    await _exec_update("update_forecasts", last_update_delta=20)
    assert "Not requesting a solar forecast because time is within ten seconds of last update" not in caplog.text
    assert "Forecast update completed successfully" in caplog.text
    assert "contains all intervals" in caplog.text
    assert "Valid granular dampening: True" in caplog.text
    caplog.clear()

    granular_dampening_file.unlink()

    # Test reset usage cache
    for api_key in input["api_key"].split(","):
        solcast._api_used_reset[api_key] = solcast._api_used_reset[api_key] - timedelta(hours=24)
    await solcast.reset_api_usage()
    assert "Reset API usage" in caplog.text
    await solcast.reset_api_usage()
    assert "Usage cache is fresh, so not resetting" in caplog.text

    assert "WARNING" not in caplog.text
    assert "ERROR" not in caplog.text

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    # Do not clean up caches, as cahed data is loaded in the next test


async def test_remaining_actions(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test remaining actions."""

    entry = await async_init_integration(hass, DEFAULT_INPUT1)
    solcast: SolcastApi = hass.data[DOMAIN][entry.entry_id].solcast
    config_dir = hass.data[DOMAIN][entry.entry_id].solcast._config_dir
    assert hass.data[DOMAIN].get("has_loaded") is True

    try:
        # Last load was using two API keys, three sites so test for site removal
        assert "Sites cache exists" in caplog.text
        assert "Renaming" in caplog.text
        assert "Removing orphaned" in caplog.text
        assert "Site resource id 3333-3333-3333-3333 is no longer configured" in caplog.text
        assert len(solcast.sites) == 2

        # Test set/get dampening factors
        dampening = await hass.services.async_call(DOMAIN, "get_dampening", {}, blocking=True, return_response=True)
        assert dampening.get("data", [{}])[0] == {
            "site": "all",
            "damp_factor": ("1.0," * 24)[:-1],
        }
        with pytest.raises(MultipleInvalid):
            # No factors
            await hass.services.async_call(DOMAIN, "set_dampening", {}, blocking=True)
        with pytest.raises(ServiceValidationError):
            # Insufficient dampening factors
            await hass.services.async_call(DOMAIN, "set_dampening", {"damp_factor": "0.5"}, blocking=True)
        with pytest.raises(ServiceValidationError):
            # Too many dampening factors
            await hass.services.async_call(DOMAIN, "set_dampening", {"damp_factor": "0.5," * 15}, blocking=True)
        with pytest.raises(ServiceValidationError):
            # Specifying site with 24 dampening factors
            await hass.services.async_call(DOMAIN, "set_dampening", {"site": "all", "damp_factor": ("1.0," * 24)[:-1]}, blocking=True)
        await hass.services.async_call(DOMAIN, "set_dampening", {"damp_factor": ("0.5," * 24)[:-1]}, blocking=True)
        dampening = await hass.services.async_call(DOMAIN, "get_dampening", {}, blocking=True, return_response=True)
        assert dampening.get("data", [{}])[0] == {"site": "all", "damp_factor": ("0.5," * 24)[:-1]}
        # Granular dampening
        await hass.services.async_call(DOMAIN, "set_dampening", {"damp_factor": ("0.5," * 48)[:-1]}, blocking=True)
        await hass.async_block_till_done()  # Because options change
        assert Path(f"{config_dir}/solcast-dampening.json").is_file()
        dampening = await hass.services.async_call(DOMAIN, "get_dampening", {}, blocking=True, return_response=True)
        assert dampening.get("data", [{}])[0] == {"site": "all", "damp_factor": ("0.5," * 48)[:-1]}

        async def _clear_granular_dampening():
            # Clear granular dampening
            await hass.services.async_call(DOMAIN, "set_dampening", {"damp_factor": ("1.0," * 24)[:-1]}, blocking=True)
            await hass.async_block_till_done()  # Because options change
            dampening = await hass.services.async_call(DOMAIN, "get_dampening", {}, blocking=True, return_response=True)
            assert dampening.get("data", [{}])[0] == {
                "site": "all",
                "damp_factor": ("1.0," * 24)[:-1],
            }

        await _clear_granular_dampening()
        # Granular dampening with site
        await hass.services.async_call(
            DOMAIN, "set_dampening", {"site": "1111-1111-1111-1111", "damp_factor": ("0.5," * 48)[:-1]}, blocking=True
        )
        await hass.async_block_till_done()  # Because options change
        dampening = await hass.services.async_call(
            DOMAIN, "get_dampening", {"site": "1111-1111-1111-1111"}, blocking=True, return_response=True
        )
        assert dampening.get("data", [{}])[0] == {"site": "1111-1111-1111-1111", "damp_factor": ("0.5," * 48)[:-1]}
        await _clear_granular_dampening()

        # Test set/clear hard limit
        with pytest.raises(MultipleInvalid):
            # No hard limit
            await hass.services.async_call(DOMAIN, "set_hard_limit", {}, blocking=True)
        with pytest.raises(ServiceValidationError):
            # Too many hard limits
            await hass.services.async_call(DOMAIN, "set_hard_limit", {"hard_limit": "5.0,5.0,5.0"}, blocking=True)

        await hass.services.async_call(DOMAIN, "set_hard_limit", {"hard_limit": "5.0"}, blocking=True)
        await hass.async_block_till_done()  # Because integration reloads
        assert hass.data[DOMAIN][entry.entry_id].solcast.hard_limit == "5.0"
        assert "Build hard limit period values from scratch for dampened" in caplog.text
        assert "Build hard limit period values from scratch for un-dampened" in caplog.text
        for estimate in ["pv_estimate", "pv_estimate10", "pv_estimate90"]:
            assert len(hass.data[DOMAIN][entry.entry_id].solcast._sites_hard_limit["all"][estimate]) > 0
            assert len(hass.data[DOMAIN][entry.entry_id].solcast._sites_hard_limit_undampened["all"][estimate]) > 0

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

        assert "ERROR" not in caplog.text
        caplog.clear()

        # Switch to using two API keys, three sites
        entry = await async_init_integration(hass, DEFAULT_INPUT2)

        await hass.services.async_call(DOMAIN, "set_hard_limit", {"hard_limit": "5.0,5.0"}, blocking=True)
        await hass.async_block_till_done()  # Because integration reloads
        assert hass.data[DOMAIN][entry.entry_id].solcast.hard_limit == "5.0,5.0"
        assert "Build hard limit period values from scratch for dampened" in caplog.text
        assert "Build hard limit period values from scratch for un-dampened" in caplog.text
        for api_key in entry.options["api_key"].split(","):
            for estimate in ["pv_estimate", "pv_estimate10", "pv_estimate90"]:
                assert len(hass.data[DOMAIN][entry.entry_id].solcast._sites_hard_limit[api_key][estimate]) > 0
                assert len(hass.data[DOMAIN][entry.entry_id].solcast._sites_hard_limit_undampened[api_key][estimate]) > 0

        await hass.services.async_call(DOMAIN, "remove_hard_limit", {}, blocking=True)
        await hass.async_block_till_done()  # Because integration reloads
        assert hass.data[DOMAIN][entry.entry_id].solcast.hard_limit == "100.0"
        assert len(hass.data[DOMAIN][entry.entry_id].solcast._sites_hard_limit["all"]["pv_estimate"]) == 0
        assert len(hass.data[DOMAIN][entry.entry_id].solcast._sites_hard_limit_undampened["all"]["pv_estimate"]) == 0

        # Test query forecast data
        queries = [
            {
                "query": {
                    EVENT_START_DATETIME: solcast.get_day_start_utc().isoformat(),
                    EVENT_END_DATETIME: solcast.get_day_start_utc(future=1).isoformat(),
                },
                "expected": 48,
            },
            {
                "query": {
                    EVENT_START_DATETIME: solcast.get_day_start_utc().isoformat(),
                    EVENT_END_DATETIME: solcast.get_day_start_utc(future=1).isoformat(),
                    UNDAMPENED: True,
                },
                "expected": 48,
            },
            {
                "query": {
                    EVENT_START_DATETIME: (solcast.get_day_start_utc(future=-1) + timedelta(hours=3)).isoformat(),
                    EVENT_END_DATETIME: solcast.get_day_start_utc().isoformat(),
                    SITE: "1111-1111-1111-1111",
                },
                "expected": 42,
            },
            {
                "query": {
                    EVENT_START_DATETIME: solcast.get_day_start_utc(future=-3).isoformat(),
                    EVENT_END_DATETIME: solcast.get_day_start_utc(future=-1).isoformat(),
                    SITE: "2222-2222-2222-2222",
                    UNDAMPENED: True,
                },
                "expected": 96,
            },
        ]
        for query in queries:
            forecast_data = await hass.services.async_call(
                DOMAIN, "query_forecast_data", query["query"], blocking=True, return_response=True
            )
            assert len(forecast_data.get("data", [])) == query["expected"]

        assert "ERROR" not in caplog.text

    finally:
        assert await async_cleanup_integration_tests(hass, config_dir)
