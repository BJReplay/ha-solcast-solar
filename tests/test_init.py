"""Tests for the Solcast Solar initialisation."""

import asyncio
import copy
import datetime
from datetime import datetime as dt, timedelta
import json
import logging
from pathlib import Path

import pytest
from voluptuous.error import MultipleInvalid

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar import tasks_cancel
from homeassistant.components.solcast_solar.const import (
    API_QUOTA,
    AUTO_UPDATE,
    DOMAIN,
    EVENT_END_DATETIME,
    EVENT_START_DATETIME,
    HARD_LIMIT_API,
    SITE,
    UNDAMPENED,
)
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.solcastapi import SolcastApi
from homeassistant.const import CONF_API_KEY
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


async def _exec_update(
    hass: HomeAssistant, solcast: SolcastApi, caplog: any, action: str, last_update_delta: int = 0, wait: bool = True
) -> None:
    """Execute an action and wait for completion."""
    caplog.clear()
    async with asyncio.timeout(2):
        if last_update_delta == 0:
            last_updated = dt(year=2020, month=1, day=1, hour=1, minute=1, second=1, tzinfo=datetime.UTC)
        else:
            last_updated = solcast._data["last_updated"] - timedelta(seconds=last_update_delta)
            _LOGGER.info("Mock last updated: %s", last_updated)
        solcast._data["last_updated"] = last_updated
        await hass.services.async_call(DOMAIN, action, {}, blocking=True)
        await hass.async_block_till_done()
        if wait:
            while (
                "Forecast update completed successfully" not in caplog.text
                and "Not requesting a solar forecast" not in caplog.text
                and "ERROR" not in caplog.text
            ):  # Wait for task to complete
                await asyncio.sleep(0.01)


@pytest.mark.parametrize(
    "options",
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
    options: dict,
) -> None:
    """Test integration init."""

    # Test startup
    entry = await async_init_integration(hass, options)

    if options == BAD_INPUT:
        assert hass.data[DOMAIN].get("has_loaded") is None
        assert "Dampening factors corrupt or not found, setting to 1.0" in caplog.text
        assert "Error getting sites for the API key ******badkey, is the key correct?" in caplog.text
        return

    assert hass.data[DOMAIN].get("has_loaded") is True
    config_dir = hass.data[DOMAIN][entry.entry_id].solcast._config_dir
    coordinator: SolcastUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    solcast: SolcastApi = coordinator.solcast
    granular_dampening_file = Path(f"{config_dir}/solcast-dampening.json")
    if options == DEFAULT_INPUT2:
        assert granular_dampening_file.is_file()

    try:
        assert solcast.sites_loaded is True
        assert solcast._loaded_data is True
        assert "Dampening factors corrupt or not found, setting to 1.0" not in caplog.text
        assert solcast._tz == ZONE

        # Test cache files are as expected
        if len(options["api_key"].split(",")) == 1:
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
            # Will exist from the prior test
            assert f"Data cache {config_dir}/solcast.json exists" in caplog.text
            assert f"Data cache {config_dir}/solcast-undampened.json exists" in caplog.text

        # Test coordinator tasks are created
        assert len(coordinator.tasks.keys()) == 3

        # Test expected services are registered
        assert len(hass.services.async_services_for_domain(DOMAIN).keys()) == len(SERVICES)
        for service in SERVICES:
            assert hass.services.has_service(DOMAIN, service) is True

        # Test refused update without forcing
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, "update_forecasts", {}, blocking=True)

        # Test forced update and clear data actions
        await _exec_update(hass, solcast, caplog, "force_update_forecasts")
        await _exec_update(hass, solcast, caplog, "force_update_forecasts", wait=False)
        await _exec_update(hass, solcast, caplog, "clear_all_solcast_data")

        # Test for API key redaction
        for api_key in options["api_key"].split(","):
            assert "key=" + api_key not in caplog.text
            assert "key: " + api_key not in caplog.text
            assert "sites-" + api_key not in caplog.text
            assert "usage-" + api_key not in caplog.text

        # Test update within ten seconds of prior update
        solcast.options.auto_update = 0
        await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=5)
        assert "Not requesting a solar forecast because time is within ten seconds of last update" in caplog.text
        assert "ERROR" not in caplog.text
        caplog.clear()

        # Create a granular dampening file to be read on next update
        granular_dampening = (
            {
                "1111-1111-1111-1111": [0.8] * 48,
                "2222-2222-2222-2222": [0.9] * 48,
            }
            if options == DEFAULT_INPUT1
            else {
                "1111-1111-1111-1111": [0.7] * 24,
                "2222-2222-2222-2222": [0.8] * 48,
                "3333-3333-3333-3333": [0.9] * 48,
            }
        )
        granular_dampening_file.write_text(json.dumps(granular_dampening), encoding="utf-8")

        # Test update beyond ten seconds of prior update, also with stale usage cache
        for api_key in options["api_key"].split(","):
            solcast._api_used_reset[api_key] = dt.now(datetime.UTC) - timedelta(days=5)
        solcast.options.auto_update = 0
        await _exec_update(hass, solcast, caplog, "update_forecasts", last_update_delta=20)
        await hass.async_block_till_done()

        assert "Not requesting a solar forecast because time is within ten seconds of last update" not in caplog.text
        assert "resetting API usage" in caplog.text
        assert "Writing API usage cache file" in caplog.text
        assert "Started task midnight_update" in caplog.text
        if options == DEFAULT_INPUT2:
            assert "Number of dampening factors for all sites must be the same" in caplog.text
        else:
            assert "Valid granular dampening: True" in caplog.text
            assert "Forecast update completed successfully" in caplog.text
            assert "contains all intervals" in caplog.text
        caplog.clear()

        # Test reset usage cache
        for api_key in options["api_key"].split(","):
            solcast._api_used_reset[api_key] = solcast._api_used_reset[api_key] - timedelta(hours=24)
        await solcast.reset_api_usage()
        assert "Reset API usage" in caplog.text
        await solcast.reset_api_usage()
        assert "Usage cache is fresh, so not resetting" in caplog.text

        assert "WARNING" not in caplog.text
        assert "ERROR" not in caplog.text

        # Test clear data action when no solcast.json exists
        if options == DEFAULT_INPUT2:
            Path(f"{config_dir}/solcast.json").unlink()
            Path(f"{config_dir}/solcast-undampened.json").unlink()
            with pytest.raises(ServiceValidationError):
                await hass.services.async_call(DOMAIN, "clear_all_solcast_data", {}, blocking=True)

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    finally:
        # Do not clean up caches, as cahed data is loaded in the next test
        # assert await async_cleanup_integration_tests(hass, config_dir)

        if options == DEFAULT_INPUT2:
            granular_dampening_file.unlink()


async def test_remaining_actions(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test remaining actions."""

    entry = await async_init_integration(hass, DEFAULT_INPUT1)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    solcast: SolcastApi = coordinator.solcast
    config_dir = solcast._config_dir
    assert hass.data[DOMAIN].get("has_loaded") is True

    def occurs_in_log(text: str, occurrences: int) -> int:
        occurs = 0
        for entry in caplog.messages:
            if text in entry:
                occurs += 1
        assert occurrences == occurs

    try:
        # Test logs for cache load
        assert "Sites cache exists" in caplog.text
        assert "Usage cache exists" in caplog.text
        occurs_in_log("Renaming", 2)
        occurs_in_log("Removing orphaned", 2)

        # Forced update when auto-update is disabled
        solcast.options.auto_update = 0
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, "force_update_forecasts", {}, blocking=True)

        # Test set/get dampening factors
        async def _clear_granular_dampening():
            # Clear granular dampening
            await hass.services.async_call(DOMAIN, "set_dampening", {"damp_factor": ("1.0," * 24)[:-1]}, blocking=True)
            await hass.async_block_till_done()  # Because options change
            dampening = await hass.services.async_call(DOMAIN, "get_dampening", {}, blocking=True, return_response=True)
            assert dampening.get("data", [{}])[0] == {
                "site": "all",
                "damp_factor": ("1.0," * 24)[:-1],
            }

        dampening = await hass.services.async_call(DOMAIN, "get_dampening", {}, blocking=True, return_response=True)
        assert dampening.get("data", [{}])[0] == {
            "site": "all",
            "damp_factor": ("1.0," * 24)[:-1],
        }
        odd_factors = [
            {"damp_factor": "  "},  # No factors
            {"damp_factor": ("0.5," * 5)[:-1]},  # Insufficient factors
            {"damp_factor": ("0.5," * 15)[:-1]},  # Not 24 or 48 factors
            {"damp_factor": ("1.5," * 24)[:-1]},  # Out of range factors
            {"damp_factor": ("0.8f," * 24)[:-1]},  # Weird factors
        ]
        with pytest.raises(MultipleInvalid):
            await hass.services.async_call(DOMAIN, "set_dampening", {}, blocking=True)
        for factors in odd_factors:
            with pytest.raises(ServiceValidationError):
                await hass.services.async_call(DOMAIN, "set_dampening", factors, blocking=True)
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
        # Trigger re-apply forward dampening
        await hass.services.async_call(DOMAIN, "set_dampening", {"damp_factor": ("0.75," * 48)[:-1]}, blocking=True)
        await hass.async_block_till_done()  # Because options change
        await _clear_granular_dampening()
        # Granular dampening with site
        await hass.services.async_call(
            DOMAIN, "set_dampening", {"site": "1111-1111-1111-1111", "damp_factor": ("0.5," * 48)[:-1]}, blocking=True
        )
        await hass.async_block_till_done()  # Because options change
        dampening = await hass.services.async_call(DOMAIN, "get_dampening", {}, blocking=True, return_response=True)
        assert dampening.get("data", [{}])[0] == {"site": "1111-1111-1111-1111", "damp_factor": ("0.5," * 48)[:-1]}
        dampening = await hass.services.async_call(
            DOMAIN, "get_dampening", {"site": "1111-1111-1111-1111"}, blocking=True, return_response=True
        )
        assert dampening.get("data", [{}])[0] == {"site": "1111-1111-1111-1111", "damp_factor": ("0.5," * 48)[:-1]}
        with pytest.raises(ServiceValidationError):
            dampening = await hass.services.async_call(
                DOMAIN, "set_dampening", {"site": "9999-9999-9999-9999", "damp_factor": ("0.5," * 48)[:-1]}, blocking=True
            )
        with pytest.raises(ServiceValidationError):
            dampening = await hass.services.async_call(
                DOMAIN, "get_dampening", {"site": "9999-9999-9999-9999"}, blocking=True, return_response=True
            )
        await hass.services.async_call(DOMAIN, "set_dampening", {"site": "all", "damp_factor": ("0.5," * 48)[:-1]}, blocking=True)
        caplog.clear()
        dampening = await hass.services.async_call(
            DOMAIN, "get_dampening", {"site": "1111-1111-1111-1111"}, blocking=True, return_response=True
        )
        assert "being overridden by an all sites entry" in caplog.text
        dampening = await hass.services.async_call(
            DOMAIN, "get_dampening", {"site": "2222-2222-2222-2222"}, blocking=True, return_response=True
        )
        assert "being overridden by an all sites entry" in caplog.text
        await _clear_granular_dampening()

        # Test set/clear hard limit
        with pytest.raises(MultipleInvalid):
            # No hard limit
            await hass.services.async_call(DOMAIN, "set_hard_limit", {}, blocking=True)
        with pytest.raises(ServiceValidationError):
            # Silly hard limit
            await hass.services.async_call(DOMAIN, "set_hard_limit", {"hard_limit": "zzzzzz"}, blocking=True)
        with pytest.raises(ServiceValidationError):
            # Negative hard limit
            await hass.services.async_call(DOMAIN, "set_hard_limit", {"hard_limit": "-5"}, blocking=True)
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

        await hass.services.async_call(DOMAIN, "set_hard_limit", {"hard_limit": "5000"}, blocking=True)
        await hass.async_block_till_done()  # Because integration reloads
        assert hass.data[DOMAIN][entry.entry_id].solcast.hard_limit == "5000.0"
        assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set").state == "5.0 MW"

        await hass.services.async_call(DOMAIN, "set_hard_limit", {"hard_limit": "5000000"}, blocking=True)
        await hass.async_block_till_done()  # Because integration reloads
        assert hass.data[DOMAIN][entry.entry_id].solcast.hard_limit == "5000000.0"
        assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set").state == "5.0 GW"

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

        assert "ERROR" not in caplog.text
        caplog.clear()

        # Switch to using two API keys, three sites, start with an out-of-date usage cache
        usage_file = Path(f"{config_dir}/solcast-usage.json")
        data = json.loads(usage_file.read_text(encoding="utf-8"))
        data["reset"] = (dt.now(datetime.UTC) - timedelta(days=5)).isoformat()
        usage_file.write_text(json.dumps(data), encoding="utf-8")
        config = copy.deepcopy(DEFAULT_INPUT2)
        config[API_QUOTA] = "20,20"
        entry = await async_init_integration(hass, config)

        await hass.services.async_call(DOMAIN, "set_hard_limit", {"hard_limit": "100.0,100.0"}, blocking=True)
        await hass.async_block_till_done()  # Because integration reloads
        assert hass.data[DOMAIN][entry.entry_id].solcast.hard_limit == "100.0,100.0"
        assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set_1").state == "False"
        assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set_2").state == "False"

        await hass.services.async_call(DOMAIN, "set_hard_limit", {"hard_limit": "5.0,5.0"}, blocking=True)
        await hass.async_block_till_done()  # Because integration reloads
        assert hass.data[DOMAIN][entry.entry_id].solcast.hard_limit == "5.0,5.0"
        assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set_1").state == "5.0 kW"
        assert hass.states.get("sensor.solcast_pv_forecast_hard_limit_set_2").state == "5.0 kW"
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
        # pass


async def test_scenarios(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test integration start with stale data."""

    options = copy.deepcopy(DEFAULT_INPUT1)
    options[HARD_LIMIT_API] = "6.0"
    entry = await async_init_integration(hass, options)
    solcast: SolcastApi = hass.data[DOMAIN][entry.entry_id].solcast
    config_dir = hass.data[DOMAIN][entry.entry_id].solcast._config_dir
    try:
        assert hass.data[DOMAIN].get("has_loaded") is True
        assert "Hard limit is set to limit peak forecast values" in caplog.text

        data_file = Path(f"{config_dir}/solcast.json")

        def alter_last_updated():
            data = json.loads(data_file.read_text(encoding="utf-8"))
            data["last_updated"] = (dt.now(datetime.UTC) - timedelta(days=5)).isoformat()
            data["last_attempt"] = data["last_updated"]
            data["auto_updated"] = True
            data_file.write_text(json.dumps(data), encoding="utf-8")

        def corrupt_data():
            data = json.loads(data_file.read_text(encoding="utf-8"))
            data["siteinfo"]["3333-3333-3333-3333"]["forecasts"] = [{"bob": 0}]
            # data["last_updated"] = "sdkjfhkjsfh"
            data_file.write_text(json.dumps(data), encoding="utf-8")

        async def reload():
            await hass.config_entries.async_reload(entry.entry_id)
            await hass.async_block_till_done()

        # Test stale start with auto update enabled
        alter_last_updated()
        await reload()
        assert "Many auto updates have been missed, updating forecast" in caplog.text
        assert solcast._data["last_updated"] > dt.now(datetime.UTC) - timedelta(minutes=10)
        caplog.clear()
        await tasks_cancel(hass, entry)

        # Test stale start with auto update disabled
        opt = {**entry.options}
        opt[AUTO_UPDATE] = 0
        hass.config_entries.async_update_entry(entry, options=opt)
        await hass.async_block_till_done()
        alter_last_updated()
        await reload()
        assert "The update automation has not been running, updating forecast" in caplog.text
        assert solcast._data["last_updated"] > dt.now(datetime.UTC) - timedelta(minutes=10)
        caplog.clear()
        await tasks_cancel(hass, entry)

        # Test API key change
        opt = {**entry.options}
        opt[CONF_API_KEY] = "2"
        hass.config_entries.async_update_entry(entry, options=opt)
        await hass.async_block_till_done()
        assert "Options updated, action: The integration will reload" in caplog.text
        assert "Migrating un-dampened history" in caplog.text
        assert "An API key has changed, resetting usage" in caplog.text
        assert "Reset API usage" in caplog.text
        assert "New site(s) have been added" in caplog.text
        assert "Site resource id 1111-1111-1111-1111 is no longer configured" in caplog.text
        assert "Site resource id 2222-2222-2222-2222 is no longer configured" in caplog.text
        caplog.clear()

        # Test corrupt data start, integration will not load
        corrupt_data()
        await reload()
        assert "Failed to build forecast data" in caplog.text
        assert "UnboundLocalError in check_data_records()" in caplog.text
        caplog.clear()

    finally:
        assert await async_cleanup_integration_tests(hass, config_dir)
