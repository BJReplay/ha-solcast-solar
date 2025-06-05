"""Test the Solcast Solar repairs flow."""

import copy
import datetime
from datetime import datetime as dt, timedelta
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.components.repairs import ConfirmRepairFlow
from homeassistant.components.solcast_solar.const import AUTO_UPDATE, DOMAIN
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.repairs import async_create_fix_flow
from homeassistant.components.solcast_solar.solcastapi import SolcastApi
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir

from . import DEFAULT_INPUT1, async_cleanup_integration_tests, async_init_integration
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

    options = copy.deepcopy(DEFAULT_INPUT1)
    options[AUTO_UPDATE] = "0"
    entry = await async_init_integration(hass, options)

    try:

        def remove_future_forecasts():
            data_file = Path(f"{hass.config.config_dir}/solcast.json")
            data = json.loads(data_file.read_text(encoding="utf-8"))
            # Remove future forecasts from "now" plus six days
            for site in data["siteinfo"].values():
                site["forecasts"] = [
                    f for f in site["forecasts"] if f["period_start"] < (dt.now(datetime.UTC) + timedelta(days=6)).isoformat()
                ]
            data_file.write_text(json.dumps(data), encoding="utf-8")

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

        flow = await async_create_fix_flow(hass, issue.issue_id, {"entry": entry})
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


@pytest.mark.parametrize(
    "scenario",
    [
        {"latitude": -37.8136, "azimuth": +50, "implausible": False},
        {"latitude": -37.8136, "azimuth": -50, "implausible": False},
        {"latitude": -37.8136, "azimuth": +150, "proposal": +30, "implausible": True},
        {"latitude": -37.8136, "azimuth": -150, "proposal": -30, "implausible": True},
        {"latitude": +37.8136, "azimuth": +50, "proposal": +130, "implausible": True},
        {"latitude": +37.8136, "azimuth": -50, "proposal": -130, "implausible": True},
        {"latitude": +37.8136, "azimuth": +150, "implausible": False},
        {"latitude": +37.8136, "azimuth": -150, "implausible": False},
    ],
)
async def test_implausible_azimuth(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    issue_registry: ir.IssueRegistry,
    scenario: dict[str, Any],
) -> None:
    """Test implausible azimuth."""

    old_latitude = API_KEY_SITES["1"]["sites"][0]["latitude"]
    old_azimuth = API_KEY_SITES["1"]["sites"][0]["azimuth"]
    API_KEY_SITES["1"]["sites"][0]["latitude"] = scenario["latitude"]
    API_KEY_SITES["1"]["sites"][0]["azimuth"] = scenario["azimuth"]
    entry = await async_init_integration(hass, DEFAULT_INPUT1)

    try:
        if scenario["implausible"]:
            # Assert the issue is present and persistent
            assert len(issue_registry.issues) == 1
            issue = list(issue_registry.issues.values())[0]
            assert issue.domain == DOMAIN
            assert issue.issue_id == "implausible_azimuth_northern" if scenario["latitude"] > 0 else "implausible_azimuth_southern"
            assert issue.is_fixable is False
            assert issue.is_persistent is True
            assert issue.translation_placeholders is not None
            assert issue.translation_placeholders.get("proposal") == str(scenario["proposal"])

            # Fix the issue at Solcast and reload the integration
            API_KEY_SITES["1"]["sites"][0]["latitude"] = old_latitude
            API_KEY_SITES["1"]["sites"][0]["azimuth"] = old_azimuth
            await _reload(hass, entry)
            assert len(issue_registry.issues) == 0
        else:
            # Assert the issue is not present
            assert len(issue_registry.issues) == 0

    finally:
        API_KEY_SITES["1"]["sites"][0]["latitude"] = old_latitude
        API_KEY_SITES["1"]["sites"][0]["azimuth"] = old_azimuth
        await async_cleanup_integration_tests(hass)
