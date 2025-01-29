"""Test forecasts update retry mechanism."""

from datetime import timedelta
import logging
from unittest import mock

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar.solcastapi import SolcastApi
from homeassistant.core import HomeAssistant

from . import (
    DEFAULT_INPUT1,
    MOCK_BUSY,
    async_cleanup_integration_tests,
    async_init_integration,
    session_set,
)


class AsyncMockDoNothing(mock.MagicMock):
    """Do nothing. Used to replace asyncio sleep."""

    async def __call__(self, *args, **kwargs):
        """Do nothing."""
        return super().__call__(*args, **kwargs)


@pytest.fixture(autouse=True)
def frozen_time() -> None:
    """Override autouse fixture for this module.

    Using other mock times.
    """
    return


_LOGGER = logging.getLogger(__name__)


def _occurs_in_log(caplog: pytest.LogCaptureFixture, text: str, occurrences: int) -> int:
    occurs = 0
    for entry in caplog.messages:
        if text in entry:
            occurs += 1
    assert occurrences == occurs


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

        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        coordinator = entry.runtime_data.coordinator
        solcast = coordinator.solcast

        session_set(MOCK_BUSY)
        caplog.clear()

        solcast._data["last_updated"] -= timedelta(minutes=20)
        with mock.patch("homeassistant.components.solcast_solar.solcastapi.SolcastApi._sleep", new_callable=AsyncMockDoNothing):
            for _ in range(150):
                freezer.tick(0.09)
                await hass.async_block_till_done()

        assert "API was tried 10 times, but all attempts failed" in caplog.text
        _occurs_in_log(caplog, "Call status 429/Try again later", 10)
        assert "No data was returned for forecasts" in caplog.text
        assert "Forecast has not been updated, next auto update at" in caplog.text
        assert "Completed task pending_update_009" in caplog.text

    finally:
        await async_cleanup_integration_tests(hass)
