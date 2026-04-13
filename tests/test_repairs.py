"""Test the Solcast Solar repairs flow."""

import asyncio
import copy
import datetime
from datetime import datetime as dt, timedelta
import json
import logging
from pathlib import Path
import re
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
from homeassistant.components.solcast_solar.repairs import async_create_fix_flow
from homeassistant.components.solcast_solar.util import (
    check_unusual_azimuth,
    redact_lat_lon_simple,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir

from . import (
    DEFAULT_INPUT1,
    MOCK_OVER_LIMIT,
    ZONE_RAW,
    async_cleanup_integration_tests,
    async_init_integration,
    reload_integration,
    session_clear,
    session_set,
)
from .simulator import API_KEY_SITES

_LOGGER = logging.getLogger(__name__)


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
        await reload_integration(hass, entry)

        # Assert the issue is present, fixable and non-persistent
        assert len(issue_registry.issues) == 1, f"Expected 1 issue, got {len(issue_registry.issues)}"
        issue = list(issue_registry.issues.values())[0]
        assert issue.domain == DOMAIN, f"Expected domain {DOMAIN}, got {issue.domain}"
        assert issue.issue_id == "records_missing_fixable", f"Expected issue_id 'records_missing_fixable', got {issue.issue_id}"
        assert issue.is_fixable is True, "Missing data issue should be fixable"
        assert issue.is_persistent is False, "Missing data issue should not be persistent"

        flow = await async_create_fix_flow(hass, "not_handled_issue", {})
        assert type(flow) is ConfirmRepairFlow

        flow = await async_create_fix_flow(hass, issue.issue_id, {"contiguous": 8, "entry_id": entry.entry_id})
        flow.hass = hass
        flow.issue_id = issue.issue_id

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
            assert len(issue_registry.issues) == 1, f"Expected 1 issue, got {len(issue_registry.issues)}"
            issue = list(issue_registry.issues.values())[0]
            assert issue.domain == DOMAIN, f"Expected domain {DOMAIN}, got {issue.domain}"
            assert issue.issue_id == "records_missing_initial", f"Expected issue_id 'records_missing_initial', got {issue.issue_id}"
            assert issue.is_fixable is False, "Initial missing data issue should not be fixable"
            assert issue.is_persistent is True, "Initial missing data issue should be persistent"

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
        await solcast.sites_cache.reset_api_usage(force=True)
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
    ("latitude", "azimuth", "expected_unusual", "expected_issue_key", "expected_proposal"),
    [
        # Southern hemisphere — normal azimuths (0..90 or -90..0)
        (-37.8136, 50, False, "unusual_azimuth_southern", 0),
        (-37.8136, -50, False, "unusual_azimuth_southern", 0),
        (-37.8136, 0, False, "unusual_azimuth_southern", 0),
        (-37.8136, -90, False, "unusual_azimuth_southern", 0),
        # Southern hemisphere — unusual azimuths
        (-37.8136, 150, True, "unusual_azimuth_southern", 30),
        (-37.8136, -150, True, "unusual_azimuth_southern", -30),
        # Northern hemisphere — normal azimuths (90..180 or -180..-90)
        (37.8136, 150, False, "unusual_azimuth_northern", 0),
        (37.8136, -150, False, "unusual_azimuth_northern", 0),
        (37.8136, 90, False, "unusual_azimuth_northern", 0),
        (37.8136, 180, False, "unusual_azimuth_northern", 0),
        # Northern hemisphere — unusual azimuths
        (37.8136, 50, True, "unusual_azimuth_northern", 130),
        (37.8136, -50, True, "unusual_azimuth_northern", -130),
    ],
)
def test_unusual_azimuth(
    latitude: float,
    azimuth: int,
    expected_unusual: bool,
    expected_issue_key: str,
    expected_proposal: int,
) -> None:
    """Test unusual azimuth classification for different hemispheres."""

    unusual, issue_key, proposal = check_unusual_azimuth(latitude, azimuth)

    assert unusual is expected_unusual, f"lat={latitude}, az={azimuth}: expected unusual={expected_unusual}, got {unusual}"
    assert issue_key == expected_issue_key, f"lat={latitude}, az={azimuth}: expected issue_key={expected_issue_key!r}, got {issue_key!r}"
    if expected_unusual:
        assert proposal == expected_proposal, f"lat={latitude}, az={azimuth}: expected proposal={expected_proposal}, got {proposal}"


@pytest.mark.parametrize(
    ("input_str", "expected"),
    [
        ("latitude 37.8136", "latitude 37.******"),
        ("longitude -122.4194", "longitude -122.******"),
        ("azimuth 150 for site abc, latitude -37.8136", "azimuth 150 for site abc, latitude -37.******"),
        ("no decimals here", "no decimals here"),
    ],
)
def test_redact_lat_lon_simple(input_str: str, expected: str) -> None:
    """Test redaction of latitude and longitude decimal places."""

    assert redact_lat_lon_simple(input_str) == expected, (
        f"redact({input_str!r}): expected {expected!r}, got {redact_lat_lon_simple(input_str)!r}"
    )


async def test_unusual_azimuth_issue_creation_and_cleanup(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Test unusual azimuth issue creation, dismissal and cleanup paths."""

    old_latitude = API_KEY_SITES["1"]["sites"][0]["latitude"]
    old_azimuth = API_KEY_SITES["1"]["sites"][0]["azimuth"]
    API_KEY_SITES["1"]["sites"][0]["latitude"] = 37.8136
    API_KEY_SITES["1"]["sites"][0]["azimuth"] = 50
    try:
        entry = await async_init_integration(hass, DEFAULT_INPUT1)

        # Assert the issue is present, persistent and has correct placeholders
        assert len(issue_registry.issues) == 1, f"Expected 1 unusual azimuth issue, got {len(issue_registry.issues)}"
        issue = list(issue_registry.issues.values())[0]
        assert f"Raise issue `{issue.issue_id}`" in caplog.text
        assert issue.domain == DOMAIN, f"Expected domain {DOMAIN}, got {issue.domain}"
        assert issue.issue_id == "unusual_azimuth_northern", f"Expected issue_id 'unusual_azimuth_northern', got {issue.issue_id}"
        assert issue.is_fixable is False, "Unusual azimuth issue should not be fixable"
        assert issue.is_persistent is True, "Unusual azimuth issue should be persistent"
        assert issue.translation_placeholders is not None, "Unusual azimuth issue should have translation placeholders"
        assert issue.translation_placeholders.get("proposal") == "130", (
            f"Expected proposal '130', got {issue.translation_placeholders.get('proposal')!r}"
        )
        assert re.search(r"WARNING.+Unusual azimuth", caplog.text) is not None, "Expected WARNING log for unusual azimuth"

        # Dismiss the issue and reload — verifies cleanup_issues and re-serialisation
        assert "Re-serialising sites cache for" in caplog.text
        caplog.clear()
        ir.async_ignore_issue(hass, DOMAIN, issue.issue_id, True)
        await reload_integration(hass, entry)
        assert len(issue_registry.issues) == 0
        assert "Remove ignored issue for unusual_azimuth_northern" in caplog.text
        assert f"Raise issue `{issue.issue_id}`" not in caplog.text

        # Second reload — verify the dismissed state persists (debug log, no warning)
        caplog.clear()
        await reload_integration(hass, entry)
        assert re.search(r"DEBUG.+Unusual azimuth", caplog.text) is not None, "Expected DEBUG log for unusual azimuth"

    finally:
        API_KEY_SITES["1"]["sites"][0]["latitude"] = old_latitude
        API_KEY_SITES["1"]["sites"][0]["azimuth"] = old_azimuth
        await async_cleanup_integration_tests(hass)


async def test_unusual_azimuth_resolved_after_fix(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Test that fixing the azimuth at Solcast clears the issue on reload."""

    old_latitude = API_KEY_SITES["1"]["sites"][0]["latitude"]
    old_azimuth = API_KEY_SITES["1"]["sites"][0]["azimuth"]
    API_KEY_SITES["1"]["sites"][0]["latitude"] = -37.8136
    API_KEY_SITES["1"]["sites"][0]["azimuth"] = 150
    try:
        entry = await async_init_integration(hass, DEFAULT_INPUT1)

        # Issue should be raised for southern hemisphere unusual azimuth
        assert len(issue_registry.issues) == 1
        issue = list(issue_registry.issues.values())[0]
        assert issue.issue_id == "unusual_azimuth_southern"
        assert issue.translation_placeholders is not None, "Issue should have translation placeholders"
        assert issue.translation_placeholders.get("proposal") == "30"

        # Fix the azimuth at Solcast and reload
        API_KEY_SITES["1"]["sites"][0]["latitude"] = old_latitude
        API_KEY_SITES["1"]["sites"][0]["azimuth"] = old_azimuth
        await reload_integration(hass, entry)
        assert len(issue_registry.issues) == 0

    finally:
        API_KEY_SITES["1"]["sites"][0]["latitude"] = old_latitude
        API_KEY_SITES["1"]["sites"][0]["azimuth"] = old_azimuth
        await async_cleanup_integration_tests(hass)
