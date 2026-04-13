"""Test forecasts update retry mechanism."""

import asyncio
from datetime import timedelta
import json
import logging
from pathlib import Path
from typing import Any
from unittest import mock

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar.const import (
    DOMAIN,
    SERVICE_FORCE_UPDATE_FORECASTS,
)
from homeassistant.components.solcast_solar.util import UpdateOutcome, UpdateResult
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from . import (
    CONFIG_DISCRETE_NAME,
    CONFIG_FOLDER_DISCRETE,
    DEFAULT_INPUT1,
    MOCK_BUSY,
    async_cleanup_integration_tests,
    async_init_integration,
    session_clear,
    session_set,
)


class AsyncMockDoNothing(mock.MagicMock):
    """Do nothing. Used to replace asyncio sleep."""

    async def __call__(self, *args: Any, **kwargs: Any) -> None:
        """Do nothing."""
        return super().__call__(*args, **kwargs)


@pytest.fixture(autouse=True)
def frozen_time() -> None:
    """Override autouse fixture for this module.

    Using other mock times.
    """
    return


_LOGGER = logging.getLogger(__name__)


def _occurs_in_log(caplog: pytest.LogCaptureFixture, text: str, occurrences: int) -> None:
    occurs = 0
    for entry in caplog.messages:
        if text in entry:
            occurs += 1
    assert occurrences == occurs, f"Expected {text!r} to occur {occurrences} times in the log, found {occurs}"


def _log_level_for(caplog: pytest.LogCaptureFixture, text: str) -> int:
    """Return the level of the first caplog record whose message contains text."""
    for record in caplog.records:
        if text in record.getMessage():
            return record.levelno
    raise AssertionError(f"No log record found containing: {text!r}")


@pytest.mark.asyncio
async def test_forecast_retry(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test retry mechanism."""

    try:
        freezer.move_to("2025-01-11 00:00:00")  # A pending update will be queued for 00:00:09 UTC

        config_dir = f"{hass.config.config_dir}/{CONFIG_DISCRETE_NAME}" if CONFIG_FOLDER_DISCRETE else hass.config.config_dir
        if CONFIG_FOLDER_DISCRETE:
            Path(config_dir).mkdir(parents=False, exist_ok=True)
        Path(f"{config_dir}/solcast-advanced.json").write_text(
            json.dumps(
                {
                    "trigger_on_api_unavailable": "Automation unavailable",
                    "trigger_on_api_available": "Automation available",
                }
            ),
            encoding="utf-8",
        )

        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        coordinator = entry.runtime_data.coordinator
        solcast = coordinator.solcast

        assert await async_setup_component(
            hass,
            "automation",
            {
                "automation": [
                    {
                        "id": "automation_available",
                        "alias": "Automation available",
                        "trigger": {"platform": "event", "event_type": "test_event"},
                        "action": {"service": "persistent_notification.create"},
                    },
                    {
                        "id": "automation_unavailable",
                        "alias": "Automation unavailable",
                        "trigger": {"platform": "event", "event_type": "test_event"},
                        "action": {"service": "persistent_notification.create"},
                    },
                ]
            },
        ), "Automation component setup failed"
        await hass.async_block_till_done()

        session_set(MOCK_BUSY)
        caplog.clear()

        solcast.data["last_updated"] -= timedelta(minutes=20)
        with mock.patch("homeassistant.components.solcast_solar.fetcher.Fetcher._sleep", new_callable=AsyncMockDoNothing):
            async with asyncio.timeout(10):
                while "Raise issue for api_unavailable" not in caplog.text:
                    freezer.tick(0.1)
                    await hass.async_block_till_done()

        assert "API was tried 10 times, but all attempts failed" in caplog.text
        _occurs_in_log(caplog, "Call status 429/Try again later", 10)
        assert "Forecast has not been updated: 429/Try again later after 10 attempts, next auto update at" in caplog.text
        assert "Completed task pending_update_009" in caplog.text
        assert "Raise issue for api_unavailable" in caplog.text
        await solcast.tasks_cancel()
        await coordinator.tasks_cancel()

        session_clear(MOCK_BUSY)
        caplog.clear()
        await hass.services.async_call(DOMAIN, SERVICE_FORCE_UPDATE_FORECASTS, {}, blocking=True)
        async with asyncio.timeout(10):
            while "Remove issue for api_unavailable" not in caplog.text:
                freezer.tick(0.1)
                await hass.async_block_till_done()
        assert "Remove issue for api_unavailable" in caplog.text
        await solcast.tasks_cancel()
        await coordinator.tasks_cancel()

    finally:
        await async_cleanup_integration_tests(hass)


@pytest.mark.asyncio
async def test_log_update_failure_only_enabled(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test retry mechanism with log_update_failure_only enabled.

    Retry messages must be at DEBUG level, and the only forecast-update
    warning must be the final summary containing the failure reason.
    """

    try:
        freezer.move_to("2025-01-11 00:00:00")

        config_dir = f"{hass.config.config_dir}/{CONFIG_DISCRETE_NAME}" if CONFIG_FOLDER_DISCRETE else hass.config.config_dir
        if CONFIG_FOLDER_DISCRETE:
            Path(config_dir).mkdir(parents=False, exist_ok=True)
        Path(f"{config_dir}/solcast-advanced.json").write_text(
            json.dumps(
                {
                    "trigger_on_api_unavailable": "Automation unavailable",
                    "trigger_on_api_available": "Automation available",
                    "log_update_failure_only": True,
                }
            ),
            encoding="utf-8",
        )

        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        coordinator = entry.runtime_data.coordinator
        solcast = coordinator.solcast

        session_set(MOCK_BUSY)
        caplog.clear()
        caplog.set_level(logging.DEBUG)

        solcast.data["last_updated"] -= timedelta(minutes=20)
        with mock.patch("homeassistant.components.solcast_solar.fetcher.Fetcher._sleep", new_callable=AsyncMockDoNothing):
            async with asyncio.timeout(10):
                while "Raise issue for api_unavailable" not in caplog.text:
                    freezer.tick(0.1)
                    await hass.async_block_till_done()

        # Retry-related messages must be logged at DEBUG (not WARNING).
        assert _log_level_for(caplog, "Call status 429/Try again later, pausing") == logging.DEBUG
        # API usage status must not be logged as ERROR when enabled.
        assert _log_level_for(caplog, "Call status 429/Try again later, API used is") == logging.DEBUG
        # Retry exhaustion should not produce an extra log line when enabled.
        assert "API was tried 10 times, but all attempts failed" not in caplog.text
        # The overall forecast-not-updated summary stays WARNING and carries the reason.
        assert (
            _log_level_for(
                caplog,
                "Forecast has not been updated: 429/Try again later after 10 attempts, next auto update at",
            )
            == logging.WARNING
        )

        await solcast.tasks_cancel()
        await coordinator.tasks_cancel()

    finally:
        await async_cleanup_integration_tests(hass)


@pytest.mark.asyncio
async def test_forecast_abort_does_not_build_actuals(
    recorder_mock: Recorder,
    hass: HomeAssistant,
) -> None:
    """Ensure aborted forecast updates do not rebuild estimated actual data."""

    try:
        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        coordinator = entry.runtime_data.coordinator

        with (
            mock.patch.object(
                coordinator.solcast.fetcher,
                "get_forecast_update",
                new=mock.AsyncMock(return_value=UpdateResult(UpdateOutcome.ABORTED, "Forecast update aborted")),
            ),
            mock.patch.object(
                coordinator.solcast,
                "build_actual_data",
                new=mock.AsyncMock(return_value=True),
            ) as build_actual_data,
        ):
            await coordinator._updater.forecast_update(completion="Completed task update")

        build_actual_data.assert_not_awaited()

    finally:
        await async_cleanup_integration_tests(hass)
