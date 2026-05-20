"""Tests for the Solcast Solar diagnostics and system health."""

from datetime import datetime as dt, timedelta
import logging

from freezegun.api import FrozenDateTimeFactory

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar.const import (
    API_KEYS_CONFIGURED,
    API_LIMIT,
    API_USED,
    DOMAIN,
    FORECASTS,
    HARD_LIMIT,
    SERVICE_SET_HARD_LIMIT,
    SITE_ATTRIBUTE_COMPASS_DEGREES,
    SITE_ATTRIBUTE_COMPASS_DIRECTION,
    SITE_INFO,
)
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.solcastapi import SolcastApi
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from . import (
    DEFAULT_INPUT1,
    ZONE_RAW,
    async_cleanup_integration_tests,
    async_init_integration,
)

from tests.components.diagnostics import (
    get_diagnostics_for_config_entry,  # pyright:ignore[reportUnknownVariableType]
)
from tests.typing import (
    ClientSessionGenerator,  # pyright:ignore[reportUnknownVariableType]
)

_LOGGER = logging.getLogger(__name__)


async def test_diagnostics(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    hass_client: ClientSessionGenerator,  # pyright:ignore[reportUnknownParameterType]
) -> None:
    """Test diagnostics output."""

    try:
        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        freezer.move_to(dt.now() + timedelta(minutes=1))
        await hass.async_block_till_done()
        coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator
        solcast: SolcastApi = coordinator.solcast

        diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)
        assert ZONE_RAW in diagnostics["tz_conversion"]["repr"]  # type: ignore[call-overload, index, operator] # pyright: ignore[reportOperatorIssue, reportIndexIssue, reportCallIssue, reportArgumentType, reportOptionalSubscript]
        assert diagnostics["health_check"]["api"][API_USED] == 4, (  # type: ignore[call-overload, index]
            f"Expected 4 used API requests, got {diagnostics['health_check']['api'][API_USED]}"  # type: ignore[call-overload, index]
        )
        assert diagnostics["health_check"]["api"][API_LIMIT] == int(DEFAULT_INPUT1[API_LIMIT]), (  # type: ignore[call-overload, index]
            f"API limit mismatch: expected {int(DEFAULT_INPUT1[API_LIMIT])}, got {diagnostics['health_check']['api'][API_LIMIT]}"  # type: ignore[call-overload, index]
        )
        assert diagnostics["rooftop_site_count"] == 2, f"Expected 2 rooftop sites, got {diagnostics['rooftop_site_count']}"
        assert diagnostics["health_check"]["configuration"][HARD_LIMIT] == "100.0", "Hard limit should not be set initially"  # type: ignore[call-overload, index]
        assert "health_check" in diagnostics
        assert diagnostics["health_check"]["overall_status"] == "ok"  # type: ignore[call-overload, index]
        assert diagnostics["health_check"]["api"][API_KEYS_CONFIGURED] == 1  # type: ignore[call-overload, index]
        assert CONF_API_KEY not in diagnostics["health_check"]  # type: ignore[operator]
        for site in diagnostics["health_check"]["sites"]:  # type: ignore[index]
            assert "solcast_azimuth" in site
            assert SITE_ATTRIBUTE_COMPASS_DEGREES in site
            assert SITE_ATTRIBUTE_COMPASS_DIRECTION in site
        for site, data in diagnostics["data"][SITE_INFO].items():  # type: ignore[call-overload, index, union-attr] # pyright: ignore[reportArgumentType, reportIndexIssue, reportOptionalSubscript, reportUnknownMemberType]
            assert site in ["1111-1111-1111-1111", "2222-2222-2222-2222"], f"Unexpected site ID: {site}"
            assert len(data[FORECASTS]) > 300, f"Site {site}: expected > 300 forecasts, got {len(data[FORECASTS])}"  # type: ignore[arg-type, call-overload, index] # pyright: ignore[reportArgumentType, reportIndexIssue, reportOptionalSubscript, reportUnknownMemberType]
        assert diagnostics["energy_forecasts_graph"][solcast.dt_helper.now_utc().replace(hour=2, minute=0, second=0).isoformat()] == 3600.0  # type: ignore[call-overload, index]

        await hass.services.async_call(DOMAIN, SERVICE_SET_HARD_LIMIT, {HARD_LIMIT: "5.0"}, blocking=True)
        await hass.async_block_till_done()  # Because integration reloads
        diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)
        assert diagnostics["health_check"]["configuration"][HARD_LIMIT] == "5.0", "Expected hard limit to be updated to 5.0"  # type: ignore[call-overload, index]

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"
