"""Tests for the Solcast Solar select."""

import logging

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.components.select import (
    ATTR_OPTION,
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.components.solcast_solar.const import DOMAIN
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.select import PVEstimateMode
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import DEFAULT_INPUT1, async_cleanup_integration_tests, async_init_integration

_LOGGER = logging.getLogger(__name__)


@pytest.mark.parametrize(
    ("entity_key", "resulting_state", "test_entity", "expected_value"),
    [
        (PVEstimateMode.ESTIMATE, "estimate", "forecast_today", "42.552"),
        (PVEstimateMode.ESTIMATE10, "estimate10", "forecast_today", "35.46"),
        (PVEstimateMode.ESTIMATE90, "estimate90", "forecast_today", "47.28"),
    ],
)
async def test_select_change_value(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    entity_registry: er.EntityRegistry,
    entity_key: PVEstimateMode,
    resulting_state: str,
    test_entity: str,
    expected_value: float,
) -> None:
    """Test estimate mode selector."""

    entry = await async_init_integration(hass, DEFAULT_INPUT1)
    coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator

    try:
        assert (
            select_entity_id := entity_registry.async_get_entity_id(
                SELECT_DOMAIN,
                DOMAIN,
                "estimate_mode",
            )
        ) is not None
        assert hass.states.get(select_entity_id).state == "estimate"

        await hass.services.async_call(
            SELECT_DOMAIN,
            SERVICE_SELECT_OPTION,
            {ATTR_ENTITY_ID: select_entity_id, ATTR_OPTION: resulting_state},
            blocking=True,
        )

        assert hass.states.get(select_entity_id).state == resulting_state
        assert coordinator.solcast.options.key_estimate == resulting_state
        state = hass.states.get(f"sensor.solcast_pv_forecast_{test_entity}")
        assert state.state == expected_value

    finally:
        assert await async_cleanup_integration_tests(hass)
