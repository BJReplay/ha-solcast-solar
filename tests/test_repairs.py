"""Test the Solcast Solar repairs flow."""

import asyncio
import copy
import datetime
from datetime import datetime as dt, timedelta
import json
import logging
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.components.repairs import ConfirmRepairFlow
from homeassistant.components.solcast_solar.const import (
    AUTO_UPDATE,
    CONFIG_DISCRETE_NAME,
    CONFIG_FOLDER_DISCRETE,
    DOMAIN,
    SERVICE_CLEAR_DATA,
    SERVICE_UPDATE,
)
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.repairs import async_create_fix_flow
from homeassistant.components.solcast_solar.solcastapi import SolcastApi
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir

from . import (
    DEFAULT_INPUT1,
    MOCK_OVER_LIMIT,
    ZONE_RAW,
    async_cleanup_integration_tests,
    async_init_integration,
    session_clear,
    session_set,
)
from .simulator import API_KEY_SITES

_LOGGER = logging.getLogger(__name__)


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> tuple[SolcastUpdateCoordinator | None, SolcastApi | None]:
    """Reload the integration."""

    _LOGGER.warning("Reloading integration")
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    if hass.data[DOMAIN].get(entry.entry_id):
        try:
            coordinator = entry.runtime_data.coordinator
            return coordinator, coordinator.solcast  # noqa: TRY300
        except:  # noqa: E722
            _LOGGER.error("Failed to load coordinator (or solcast), which may be expected given test conditions")
    return None, None


async def test_missing_data_fixable(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    issue_registry: ir.IssueRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test missing fixable."""

    try:
        options = copy.deepcopy(DEFAULT_INPUT1)
        options[AUTO_UPDATE] = "0"
        entry = await async_init_integration(hass, options)
        config_dir = f"{hass.config.config_dir}/{CONFIG_DISCRETE_NAME}" if CONFIG_FOLDER_DISCRETE else hass.config.config_dir

        def remove_future_forecasts():
            for file_name in [f"{config_dir}/solcast.json", f"{config_dir}/solcast-undampened.json"]:
                data_file = Path(file_name)
                data = json.loads(data_file.read_text(encoding="utf-8"))
                # Remove future forecasts from "now" plus six days
                for site in data["siteinfo"].values():
                    site["forecasts"] = [
                        f for f in site["forecasts"] if f["period_start"] < (dt.now(datetime.UTC) + timedelta(days=4)).isoformat()
                    ]
                data_file.write_text(json.dumps(data), encoding="utf-8")
                _LOGGER.critical("%s: %s", data_file, len(data["siteinfo"]["1111-1111-1111-1111"]["forecasts"]))

        remove_future_forecasts()
        await _reload(hass, entry)

        # Assert the issue is present, fixable and non-persistent
        assert len(issue_registry.issues) == 1
        issue = list(issue_registry.issues.values())[0]
        assert issue.domain == DOMAIN
        assert issue.issue_id == "records_missing_fixable"
        assert issue.is_fixable is True
        assert issue.is_persistent is False

        flow = await async_create_fix_flow(hass, "not_handled_issue", {})
        assert type(flow) is ConfirmRepairFlow

        flow = await async_create_fix_flow(hass, issue.issue_id, {"contiguous": 8, "entry_id": entry.entry_id})
        flow.hass = hass
        flow.issue_id = "records_missing_fixable"

        result = await flow.async_step_init()  # type: ignore[attr-defined]
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "offer_auto"

        result = await flow.async_step_offer_auto({AUTO_UPDATE: "1"})  # type: ignore[attr-defined]
        await hass.async_block_till_done()

        assert "Options updated, action: The integration will reload" in caplog.text
        assert "Auto forecast updates" in caplog.text
        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "reconfigured"

    finally:
        await async_cleanup_integration_tests(hass)


async def test_missing_data_initial(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    issue_registry: ir.IssueRegistry,
    caplog: pytest.LogCaptureFixture,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test missing data after history reset."""

    try:

        def assert_issue_present():
            # Assert the issue is present, unfixable and persistent
            assert len(issue_registry.issues) == 1
            issue = list(issue_registry.issues.values())[0]
            assert issue.domain == DOMAIN
            assert issue.issue_id == "records_missing_initial"
            assert issue.is_fixable is False
            assert issue.is_persistent is True

        def assert_issue_not_present():
            # Assert the issue is not present
            assert len(issue_registry.issues) == 0

        async def update_forecast():
            await hass.services.async_call(DOMAIN, SERVICE_UPDATE, {}, blocking=True)
            async with asyncio.timeout(100):
                while "Completed task update" not in caplog.text:
                    freezer.tick(0.1)
                    await hass.async_block_till_done()

        options = copy.deepcopy(DEFAULT_INPUT1)
        options[AUTO_UPDATE] = "0"
        entry = await async_init_integration(hass, options)
        solcast = entry.runtime_data.coordinator.solcast

        caplog.clear()
        session_set(MOCK_OVER_LIMIT)
        await hass.services.async_call(DOMAIN, SERVICE_CLEAR_DATA, {}, blocking=True)
        await hass.async_block_till_done()

        assert_issue_present()

        caplog.clear()
        session_clear(MOCK_OVER_LIMIT)
        await solcast.reset_api_usage(force=True)
        assert "Reset API usage" in caplog.text
        await update_forecast()
        assert_issue_present()

        caplog.clear()
        freezer.move_to((dt.now(tz=ZoneInfo(ZONE_RAW))).replace(hour=23, minute=59, second=0, microsecond=0))
        await update_forecast()

        caplog.clear()
        freezer.move_to((dt.now(tz=ZoneInfo(ZONE_RAW)) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0))
        await hass.async_block_till_done()
        await update_forecast()
        assert_issue_not_present()

    finally:
        await async_cleanup_integration_tests(hass)


@pytest.mark.parametrize(
    "scenario",
    [
        {"latitude": -37.8136, "azimuth": +50, "unusual": False},
        {"latitude": -37.8136, "azimuth": -50, "unusual": False},
        {"latitude": -37.8136, "azimuth": +150, "proposal": +30, "unusual": True},
        {"latitude": -37.8136, "azimuth": -150, "proposal": -30, "unusual": True},
        {"latitude": +37.8136, "azimuth": +50, "proposal": +130, "unusual": True},
        {"latitude": +37.8136, "azimuth": -50, "proposal": -130, "unusual": True},
        {"latitude": +37.8136, "azimuth": +150, "unusual": False},
        {"latitude": +37.8136, "azimuth": -150, "unusual": False},
        {"latitude": +37.8136, "azimuth": 90, "unusual": False},
        {"latitude": -37.8136, "azimuth": -90, "unusual": False},
        {"latitude": +37.8136, "azimuth": 180, "unusual": False},
        {"latitude": -37.8136, "azimuth": 0, "unusual": False},
    ],
)
async def test_unusual_azimuth(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    issue_registry: ir.IssueRegistry,
    scenario: dict[str, Any],
) -> None:
    """Test unusual azimuth."""

    old_latitude = API_KEY_SITES["1"]["sites"][0]["latitude"]
    old_azimuth = API_KEY_SITES["1"]["sites"][0]["azimuth"]
    API_KEY_SITES["1"]["sites"][0]["latitude"] = scenario["latitude"]
    API_KEY_SITES["1"]["sites"][0]["azimuth"] = scenario["azimuth"]
    entry = await async_init_integration(hass, DEFAULT_INPUT1)

    try:
        if scenario["unusual"]:
            # Assert the issue is present and persistent
            assert len(issue_registry.issues) == 1
            issue = list(issue_registry.issues.values())[0]
            assert f"Raise issue `{issue.issue_id}`" in caplog.text
            assert issue.domain == DOMAIN
            assert issue.issue_id == "unusual_azimuth_northern" if scenario["latitude"] > 0 else "unusual_azimuth_southern"
            assert issue.is_fixable is False
            assert issue.is_persistent is True
            assert issue.translation_placeholders is not None
            assert issue.translation_placeholders.get("proposal") == str(scenario["proposal"])
            assert re.search(r"WARNING.+Unusual azimuth", caplog.text) is not None

            if scenario["proposal"] != -130:
                # Fix the issue at Solcast and reload the integration
                API_KEY_SITES["1"]["sites"][0]["latitude"] = old_latitude
                API_KEY_SITES["1"]["sites"][0]["azimuth"] = old_azimuth
                await _reload(hass, entry)
                assert len(issue_registry.issues) == 0
            else:
                assert "Re-serialising sites cache for" in caplog.text
                caplog.clear()
                # Dismiss the issue and reload the integration
                ir.async_ignore_issue(hass, DOMAIN, issue.issue_id, True)
                await _reload(hass, entry)
                assert len(list(issue_registry.issues.values())) == 0
                assert "Remove ignored issue for unusual_azimuth_northern" in caplog.text
                assert f"Raise issue `{issue.issue_id}`" not in caplog.text
                assert len(issue_registry.issues) == 0
                caplog.clear()
                await _reload(hass, entry)
                assert re.search(r"DEBUG.+Unusual azimuth", caplog.text) is not None
        else:
            # Assert the issue is not present
            assert len(issue_registry.issues) == 0

    finally:
        API_KEY_SITES["1"]["sites"][0]["latitude"] = old_latitude
        API_KEY_SITES["1"]["sites"][0]["azimuth"] = old_azimuth
        await async_cleanup_integration_tests(hass)
