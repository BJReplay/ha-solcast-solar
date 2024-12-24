"""Tests for the Solcast Solar energy dashboard."""

from datetime import datetime as dt

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar.const import DOMAIN
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.energy import async_get_solar_forecast
from homeassistant.core import HomeAssistant

from . import DEFAULT_INPUT1, async_cleanup_integration_tests, async_init_integration


async def test_energy_data(
    recorder_mock: Recorder,
    hass: HomeAssistant,
) -> None:
    """Test energy dashboard data structure."""

    entry = await async_init_integration(hass, DEFAULT_INPUT1)
    coordinator: SolcastUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    response = await async_get_solar_forecast(hass, entry.entry_id)

    # Test dictionary structure and length
    assert response.get("wh_hours") is not None
    assert len(response.get("wh_hours")) >= 420
    day_start = coordinator.solcast.get_day_start_utc()
    day_start_earliest_whole_day = coordinator.solcast.get_day_start_utc(future=-6)
    today_and_beyond = 0
    earliest_and_beyond = 0
    for timestamp, wh_hour in response.get("wh_hours").items():
        assert type(dt.fromisoformat(timestamp)) is dt
        assert wh_hour % 1 == 0
        if dt.fromisoformat(timestamp) >= day_start:
            today_and_beyond += 1
        if dt.fromisoformat(timestamp) >= day_start_earliest_whole_day:
            earliest_and_beyond += 1

    # Test that eight days of thirty time periods from today onwards are present
    assert today_and_beyond == 30 * 8

    # Test that fourteen days of thirty time periods from earliest whole day onwards are present
    assert earliest_and_beyond == 30 * 14

    assert await async_cleanup_integration_tests(hass, coordinator.solcast._config_dir)
