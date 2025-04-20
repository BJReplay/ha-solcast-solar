"""Tests for the Solcast Solar energy dashboard."""

from datetime import datetime as dt

import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar.const import CONFIG_VERSION, DOMAIN
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.energy import async_get_solar_forecast
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import DEFAULT_INPUT1, async_cleanup_integration_tests, async_init_integration

from tests.common import MockConfigEntry


async def test_energy_data(
    recorder_mock: Recorder,
    hass: HomeAssistant,
) -> None:
    """Test energy dashboard data structure."""

    # Test that the function returns None if the domain is not yet available
    not_available_entry = MockConfigEntry(
        domain=DOMAIN, unique_id="solcast_pv_solar", title="Solcast PV Forecast", data={}, options=DEFAULT_INPUT1, version=CONFIG_VERSION
    )
    assert await async_get_solar_forecast(hass, not_available_entry.entry_id) is None

    entry: ConfigEntry = await async_init_integration(hass, DEFAULT_INPUT1)
    coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator

    # Test that the function returns None if the coordinator does not exist
    runtime_data = entry.runtime_data.coordinator
    entry.runtime_data.coordinator = None
    assert await async_get_solar_forecast(hass, entry.entry_id) is None
    entry.runtime_data.coordinator = runtime_data

    try:
        response = await async_get_solar_forecast(hass, entry.entry_id)

        if response is not None:
            # Test dictionary structure and length
            assert response.get("wh_hours") is not None
            day_start = coordinator.solcast.get_day_start_utc()
            day_start_earliest_whole_day = coordinator.solcast.get_day_start_utc(future=-6)
            today_and_beyond = 0
            earliest_and_beyond = 0
            for timestamp, wh_hour in response["wh_hours"].items():
                assert type(dt.fromisoformat(timestamp)) is dt
                assert wh_hour % 1 == 0
                if dt.fromisoformat(timestamp) >= day_start:
                    today_and_beyond += 1
                if dt.fromisoformat(timestamp) >= day_start_earliest_whole_day:
                    earliest_and_beyond += 1

            # Test that at least seven days of thirty time periods from today onwards are present
            assert today_and_beyond >= 30 * 7

            # Test that at least thirteen days of thirty time periods from earliest whole day onwards are present
            assert earliest_and_beyond >= 30 * 13
        else:
            pytest.fail("Energy data is None")

    finally:
        assert await async_cleanup_integration_tests(hass)
