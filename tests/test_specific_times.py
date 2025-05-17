"""Test midnight rollover."""

from datetime import datetime as dt
import logging

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
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
        freezer.move_to("2025-01-10 23:59:59")

        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator

        assert hass.states.get("sensor.solcast_pv_forecast_api_used").state == "4"  # type: ignore[union-attr]
        assert "Transitioning between summer/standard time" not in caplog.text

        coordinator._intervals = [  # Inject expired interval  # pyright: ignore[reportPrivateUsage]
            dt.fromisoformat("2025-01-10T00:59:30+00:00"),
            *coordinator._intervals,  # Inject expired interval  # pyright: ignore[reportPrivateUsage]
        ]
        caplog.clear()
        coordinator._data_updated = False  # Improve test coverage  # pyright: ignore[reportPrivateUsage]
        await coordinator.async_refresh()
        for _ in range(30):
            freezer.tick()
            coordinator._data_updated = True  # pyright: ignore[reportPrivateUsage]
            await coordinator.async_refresh()
            await hass.async_block_till_done()
            # Result is used for the next test. An update task must be pending, which should occur at nine minutes past the hour.
            if "API Used to 0" in caplog.text and "Create task pending_update" in caplog.text:  # Relies on SENSOR_UPDATE_LOGGING enabled
                break

        assert "Reset API usage" in caplog.text
        assert hass.states.get("sensor.solcast_pv_forecast_api_used").state == "0"  # type: ignore[union-attr]

        # Test auto-update occurs just after midnight UTC.
        caplog.clear()
        for _ in range(2000):  # Twenty virtual seconds
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


async def test_timezone_transition(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test summer time transitions."""

    try:
        # Test transition from summer to standard time.
        freezer.move_to("2025-04-04 00:00:00")
        entry = await async_init_integration(hass, DEFAULT_INPUT1, timezone="Australia/Sydney")

        assert "Transitioning between summer/standard time" in caplog.text
        assert "Forecast data from 2025-04-04 to 2025-04-10 contains all intervals" in caplog.text

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

        caplog.clear()
        await async_cleanup_integration_tests(hass)

        # Test transition from standard to summer time.
        freezer.move_to("2025-10-01 00:00:00")
        entry = await async_init_integration(hass, DEFAULT_INPUT1, timezone="Australia/Sydney")

        assert "Transitioning between summer/standard time" in caplog.text
        assert "Forecast data from 2025-10-01 to 2025-10-07 contains all intervals" in caplog.text

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    finally:
        await async_cleanup_integration_tests(hass)
