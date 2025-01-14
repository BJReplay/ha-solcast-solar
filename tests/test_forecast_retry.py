"""Test midnight rollover."""

import logging

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.core import HomeAssistant

from . import (
    DEFAULT_INPUT1,
    MOCK_BUSY,
    async_cleanup_integration_tests,
    async_init_integration,
    session_set,
)


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
    """Test midnight updates."""

    try:
        freezer.move_to("2025-01-10 23:59:59")  # A pending update will be queued for 00:00:07 UTC

        await async_init_integration(hass, DEFAULT_INPUT1)

        session_set(MOCK_BUSY)
        caplog.clear()

        for _ in range(900):
            freezer.tick()
            await hass.async_block_till_done()

        assert "API was tried 10 times, but all attempts failed" in caplog.text
        _occurs_in_log(caplog, "Call status 429/Try again later", 10)
        assert "No data was returned for forecasts" in caplog.text
        assert "Forecast has not been updated, next auto update at" in caplog.text
        assert "Completed task pending_update_007" in caplog.text

    finally:
        await async_cleanup_integration_tests(hass)
