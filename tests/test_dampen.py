"""Tests for the Solcast Solar automated dampening."""

import asyncio
from collections.abc import Callable
import contextlib
import copy
import datetime
from datetime import datetime as dt, timedelta
import json
import logging
import os
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp
from aiohttp import ClientConnectionError
import pytest
from voluptuous.error import MultipleInvalid

from homeassistant.components.recorder import Recorder, get_instance
from homeassistant.components.recorder.history import state_changes_during_period
from homeassistant.components.solcast_solar.const import (
    API_QUOTA,
    AUTO_DAMPEN,
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
    EVENT_END_DATETIME,
    EVENT_START_DATETIME,
    EXCLUDE_SITES,
    GENERATION_ENTITIES,
    GET_ACTUALS,
    HARD_LIMIT_API,
    KEY_ESTIMATE,
    SITE,
    SITE_EXPORT_ENTITY,
    SITE_EXPORT_LIMIT,
    UNDAMPENED,
    USE_ACTUALS,
)
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.solcastapi import (
    ConnectionOptions,
    SitesStatus,
    SolcastApi,
)
from homeassistant.components.solcast_solar.util import AutoUpdate
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ServiceValidationError
from homeassistant.util import dt as dt_util

from . import (
    BAD_INPUT,
    DEFAULT_INPUT1,
    DEFAULT_INPUT2,
    DEFAULT_INPUT_NO_SITES,
    MOCK_ALTER_HISTORY,
    MOCK_BAD_REQUEST,
    MOCK_BUSY,
    MOCK_BUSY_UNEXPECTED,
    MOCK_CORRUPT_ACTUALS,
    MOCK_CORRUPT_FORECAST,
    MOCK_CORRUPT_SITES,
    MOCK_EXCEPTION,
    MOCK_FORBIDDEN,
    MOCK_NOT_FOUND,
    MOCK_OVER_LIMIT,
    ZONE_RAW,
    async_cleanup_integration_tests,
    async_init_integration,
    async_setup_extra_sensors,
    session_clear,
    session_reset_usage,
    session_set,
)

ZONE = ZoneInfo(ZONE_RAW)
NOW = dt.now(ZONE)

_LOGGER = logging.getLogger(__name__)


def get_now_utc() -> dt:
    """Mock get_now_utc, spoof middle-of-the-day-ish."""

    return NOW.replace(hour=12, minute=27, second=0, microsecond=0).astimezone(datetime.UTC)


def get_real_now_utc() -> dt:
    """Mock get_real_now_utc, spoof middle-of-the-day-ish."""

    return NOW.replace(hour=12, minute=27, second=27, microsecond=27272).astimezone(datetime.UTC)


def get_hour_start_utc() -> dt:
    """Mock get_hour_start_utc, spoof middle-of-the-day-ish."""

    return NOW.replace(hour=12, minute=0, second=0, microsecond=0).astimezone(datetime.UTC)


def patch_solcast_api(solcast: SolcastApi):
    """Patch SolcastApi to return a fixed time.

    Cannot use freezegun with these tests because time must tick (the tick= option won't work).
    """
    solcast.get_now_utc = get_now_utc  # type: ignore[method-assign]
    solcast.get_real_now_utc = get_real_now_utc  # type: ignore[method-assign]
    solcast.get_hour_start_utc = get_hour_start_utc  # type: ignore[method-assign]
    return solcast


def _no_exception(caplog: pytest.LogCaptureFixture):
    assert "Error" not in caplog.text
    assert "Exception" not in caplog.text


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> tuple[SolcastUpdateCoordinator | None, SolcastApi | None]:
    """Reload the integration."""

    _LOGGER.warning("Reloading integration")
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    if hass.data[DOMAIN].get(entry.entry_id):
        try:
            coordinator = entry.runtime_data.coordinator
            return coordinator, patch_solcast_api(coordinator.solcast)
        except:  # noqa: E722
            _LOGGER.error("Failed to load coordinator (or solcast), which may be expected given test conditions")
    return None, None


async def test_auto_dampen(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test automated dampening."""

    try:
        config_dir = hass.config.config_dir

        options = copy.deepcopy(DEFAULT_INPUT1)
        options[GET_ACTUALS] = True
        options[USE_ACTUALS] = True
        options[AUTO_DAMPEN] = True
        options[GENERATION_ENTITIES] = ["sensor.solar_export_sensor_1111_1111_1111_1111", "sensor.solar_export_sensor_2222_2222_2222_2222"]
        entry = await async_init_integration(hass, options, extra_sensors=True)
        coordinator = entry.runtime_data.coordinator
        solcast = patch_solcast_api(coordinator.solcast)

        # Reload to load saved data and prime initial generation
        coordinator, solcast = await _reload(hass, entry)
        if coordinator is None or solcast is None:
            pytest.fail("Reload failed")

        # Assert good start, that actuals are enabled, and that the cache is saved
        _LOGGER.debug("Testing good start happened")
        assert hass.data[DOMAIN].get("presumed_dead", True) is False
        _no_exception(caplog)
        assert Path(f"{config_dir}/solcast-actuals.json").is_file()
        assert Path(f"{config_dir}/solcast-generation.json").is_file()

        assert "Interval 08:30 has peak estimated actual 0.936" in caplog.text
        assert "Max generation: 0.800, [0.8, 0.8, 0.8, 0.8, 0.8]" in caplog.text

        caplog.clear()

    finally:
        assert await async_cleanup_integration_tests(hass)
