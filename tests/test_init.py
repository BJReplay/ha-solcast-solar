"""Tests for the Solcast Solar initialisation."""

import asyncio
import datetime
from datetime import datetime as dt, timedelta
import logging

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


async def test_init(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test integration init."""

    # Test bad API startup with bad API key and no dampening factors
    entry = await async_init_integration(hass, BAD_INPUT)
    assert hass.data[DOMAIN].get("has_loaded") is None
    assert "Dampening factors corrupt or not found, setting to 1.0" in caplog.text
    assert "solcast_solar integration not ready yet: Getting sites data failed: 'badkey'" in caplog.text
    caplog.clear()

    # Test good startup
    entry = await async_init_integration(hass, DEFAULT_INPUT1)
    assert hass.data[DOMAIN].get("has_loaded") is True
    coordinator: SolcastUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    solcast: SolcastApi = coordinator.solcast
    assert solcast.sites_loaded is True
    assert solcast._loaded_data is True
    assert "Dampening factors corrupt or not found, setting to 1.0" not in caplog.text

    # Test coordinator tasks are created
    assert len(coordinator.tasks.keys()) == 3

    # Test expected services are registered
    assert len(hass.services.async_services_for_domain(DOMAIN).keys()) == len(SERVICES)
    for service in SERVICES:
        assert hass.services.has_service(DOMAIN, service) is True

    # Test refused update without forcing
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "update_forecasts", {}, blocking=True)

    # Test forced update and clear data
    async def _exec_update(action: str):
        async with asyncio.timeout(5):
            reset_date = dt(year=2020, month=1, day=1, hour=1, minute=1, second=1, tzinfo=datetime.UTC)
            solcast._data["last_updated"] = reset_date
            await hass.services.async_call(DOMAIN, action, {}, blocking=True)
            await hass.async_block_till_done()
            while solcast._data["last_updated"] == reset_date:  # Wait for task to complete
                await asyncio.sleep(0.01)
            assert solcast._data["last_updated"] != reset_date

    await _exec_update("force_update_forecasts")
    await _exec_update("clear_all_solcast_data")

    # Do not clean up caches, as cahed data is loaded in the next test

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_dampening_actions(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test dampening actions."""

    entry = await async_init_integration(hass, DEFAULT_INPUT1)
    config_dir = hass.data[DOMAIN][entry.entry_id].solcast._config_dir
    assert hass.data[DOMAIN].get("has_loaded") is True
    try:
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

        assert "ERROR" not in caplog.text

    finally:
        assert await async_cleanup_integration_tests(hass, config_dir)


async def test_hard_limit_actions(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test hard limit actions."""

    entry = await async_init_integration(hass, DEFAULT_INPUT1)
    config_dir = hass.data[DOMAIN][entry.entry_id].solcast._config_dir
    assert hass.data[DOMAIN].get("has_loaded") is True
    try:
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
        for estimate in ["pv_estimate", "pv_estimate10", "pv_estimate90"]:
            assert len(hass.data[DOMAIN][entry.entry_id].solcast._sites_hard_limit["all"][estimate]) > 0
            assert len(hass.data[DOMAIN][entry.entry_id].solcast._sites_hard_limit_undampened["all"][estimate]) > 0

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

        entry = await async_init_integration(hass, DEFAULT_INPUT2)
        await hass.services.async_call(DOMAIN, "set_hard_limit", {"hard_limit": "5.0,5.0"}, blocking=True)
        await hass.async_block_till_done()  # Because integration reloads
        assert hass.data[DOMAIN][entry.entry_id].solcast.hard_limit == "5.0,5.0"
        for api_key in entry.options["api_key"].split(","):
            for estimate in ["pv_estimate", "pv_estimate10", "pv_estimate90"]:
                assert len(hass.data[DOMAIN][entry.entry_id].solcast._sites_hard_limit[api_key][estimate]) > 0
                assert len(hass.data[DOMAIN][entry.entry_id].solcast._sites_hard_limit_undampened[api_key][estimate]) > 0

        await hass.services.async_call(DOMAIN, "remove_hard_limit", {}, blocking=True)
        await hass.async_block_till_done()  # Because integration reloads
        assert hass.data[DOMAIN][entry.entry_id].solcast.hard_limit == "100.0"
        assert len(hass.data[DOMAIN][entry.entry_id].solcast._sites_hard_limit["all"]["pv_estimate"]) == 0
        assert len(hass.data[DOMAIN][entry.entry_id].solcast._sites_hard_limit_undampened["all"]["pv_estimate"]) == 0

        assert "ERROR" not in caplog.text

    finally:
        assert await async_cleanup_integration_tests(hass, config_dir)


async def test_query_forecast_data_action(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test query forecast data."""

    entry = await async_init_integration(hass, DEFAULT_INPUT1)
    solcast: SolcastApi = hass.data[DOMAIN][entry.entry_id].solcast
    config_dir = hass.data[DOMAIN][entry.entry_id].solcast._config_dir
    assert hass.data[DOMAIN].get("has_loaded") is True
    try:
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
