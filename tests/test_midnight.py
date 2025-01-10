"""Test midnight rollover."""

from datetime import datetime as dt
import logging

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.solcastapi import SolcastApi
from homeassistant.core import HomeAssistant

from . import DEFAULT_INPUT1, async_cleanup_integration_tests, async_init_integration


@pytest.fixture(autouse=True)
def frozen_time() -> None:
    """Override autouse fixture for this module.

    Using other mock times.
    """
    return


_LOGGER = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_midnight(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test midnight updates."""

    try:
        # Test midnight UTC usage reset.
        freezer.move_to(f"{dt.now().date()} 23:59:59")

        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator

        assert hass.states.get("sensor.solcast_pv_forecast_api_used").state == "4"

        coordinator._intervals = [dt.fromisoformat(f"{dt.now().date()}T00:59:30+00:00"), *coordinator._intervals]  # Inject expired interval
        caplog.clear()
        coordinator._data_updated = False  # Improve test coverage
        await coordinator.async_refresh()
        for _ in range(30):
            freezer.tick()
            coordinator._data_updated = True
            await coordinator.async_refresh()
            await hass.async_block_till_done()
            # Result is used for the next test. An update task must be pending, which should occur at nine minutes past the hour.
            if "API Used to 0" in caplog.text and "Create task pending_update" in caplog.text:  # Relies on SENSOR_UPDATE_LOGGING enabled
                break

        assert "Reset API usage" in caplog.text
        assert hass.states.get("sensor.solcast_pv_forecast_api_used").state == "0"

        # Test auto-update occurs just after midnight UTC.
        caplog.clear()
        for _ in range(1000):
            freezer.tick(0.01)
            await hass.async_block_till_done()
            if "Completed task pending_update" in caplog.text:
                break
        assert "Completed task pending_update" in caplog.text

        # Test midnight local happenings.
        freezer.move_to(f"{dt.now().date()} 13:59:59")

        caplog.clear()
        for _ in range(30):
            freezer.tick()
            await hass.async_block_till_done()
            if "Date has changed" in caplog.text:
                break

        assert "Date has changed" in caplog.text
        assert "Forecast data from" in caplog.text
        assert "Sun rise / set today" in caplog.text
        assert "Auto forecast updates for today" in caplog.text
        assert "Updating sensor" in caplog.text

    finally:
        await async_cleanup_integration_tests(hass)
