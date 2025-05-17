"""Tests for the Solcast Solar diagnostics and system health."""

import logging

from freezegun.api import FrozenDateTimeFactory

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar.const import API_QUOTA, DOMAIN
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.solcastapi import SolcastApi
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

    entry = await async_init_integration(hass, DEFAULT_INPUT1)
    coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator
    solcast: SolcastApi = coordinator.solcast

    try:
        diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)
        assert ZONE_RAW in diagnostics["tz_conversion"]["repr"]  # type: ignore[call-overload, index, operator] # pyright: ignore[reportOperatorIssue, reportIndexIssue, reportCallIssue, reportArgumentType, reportOptionalSubscript]
        assert diagnostics["used_api_requests"] == 4
        assert diagnostics["api_request_limit"] == int(DEFAULT_INPUT1[API_QUOTA])
        assert diagnostics["rooftop_site_count"] == 2
        assert diagnostics["forecast_hard_limit_set"] is False
        for site, data in diagnostics["data"][0]["siteinfo"].items():  # type: ignore[call-overload, index, union-attr] # pyright: ignore[reportArgumentType, reportIndexIssue, reportOptionalSubscript, reportUnknownMemberType]
            assert site in ["1111-1111-1111-1111", "2222-2222-2222-2222"]
            assert len(data["forecasts"]) > 300  # type: ignore[arg-type, call-overload, index] # pyright: ignore[reportArgumentType, reportIndexIssue, reportOptionalSubscript, reportUnknownMemberType]
        assert diagnostics["energy_forecasts_graph"][solcast.get_now_utc().replace(hour=2, minute=0, second=0).isoformat()] == 3600.0  # type: ignore[call-overload, index]

        await hass.services.async_call(DOMAIN, "set_hard_limit", {"hard_limit": "5.0"}, blocking=True)
        await hass.async_block_till_done()  # Because integration reloads
        diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)
        assert diagnostics["forecast_hard_limit_set"] is True

    finally:
        assert await async_cleanup_integration_tests(hass)
