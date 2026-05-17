"""Tests for Solcast PV SimCity restore helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.solcast_sim.restore_helpers import (  # pyright: ignore[reportMissingImports]
    prime_model_from_restore_state,
    recorder_sensor_value,
    restored_sensor_value,
    select_measurement_restore_value,
)

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

_T1 = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
_T2 = datetime(2025, 1, 1, 13, 0, tzinfo=UTC)


def test_select_both_none_returns_none() -> None:
    """Return None when both sources are unavailable."""
    assert select_measurement_restore_value(None, None) is None


def test_select_cache_none_returns_recorder() -> None:
    """Return recorder value when cache is absent."""
    assert select_measurement_restore_value(None, (5.0, _T1)) == 5.0


def test_select_recorder_none_returns_cache() -> None:
    """Return cache value when recorder is absent."""
    assert select_measurement_restore_value((3.0, _T1), None) == 3.0


def test_select_prefers_newer_cache() -> None:
    """Prefer cache when its timestamp is newer."""
    assert select_measurement_restore_value((3.0, _T2), (5.0, _T1)) == 3.0


def test_select_prefers_newer_recorder() -> None:
    """Prefer recorder when its timestamp is newer."""
    assert select_measurement_restore_value((3.0, _T1), (5.0, _T2)) == 5.0


def test_select_equal_timestamps_prefers_cache() -> None:
    """Return cache value when both timestamps are equal."""
    assert select_measurement_restore_value((3.0, _T1), (5.0, _T1)) == 3.0


async def test_recorder_sensor_value_returns_none_when_recorder_absent(hass: HomeAssistant) -> None:
    """Return None when recorder component is not loaded."""
    # recorder is not in hass.config.components by default in tests
    assert "recorder" not in hass.config.components
    result = await recorder_sensor_value(hass, "sensor.test")
    assert result is None


async def test_recorder_sensor_value_returns_none_when_no_states(hass: HomeAssistant) -> None:
    """Return None when recorder returns no states for the entity."""
    hass.config.components.add("recorder")

    mock_recorder = MagicMock()
    mock_recorder.async_add_executor_job = AsyncMock(return_value={})

    with patch(
        "custom_components.solcast_sim.restore_helpers.get_instance",
        return_value=mock_recorder,
    ):
        result = await recorder_sensor_value(hass, "sensor.test")

    assert result is None
    hass.config.components.remove("recorder")


async def test_recorder_sensor_value_returns_value_and_timestamp(hass: HomeAssistant) -> None:
    """Return (value, timestamp) from the most recent recorder state."""
    hass.config.components.add("recorder")

    ts = datetime(2025, 6, 1, 10, 0, tzinfo=UTC)
    fake_state = SimpleNamespace(state="42.5", last_updated=ts, last_changed=None)

    mock_recorder = MagicMock()
    mock_recorder.async_add_executor_job = AsyncMock(return_value={"sensor.test": [fake_state]})

    with patch(
        "custom_components.solcast_sim.restore_helpers.get_instance",
        return_value=mock_recorder,
    ):
        result = await recorder_sensor_value(hass, "sensor.test")

    assert result == (42.5, ts)
    hass.config.components.remove("recorder")


async def test_recorder_sensor_value_returns_none_for_invalid_state(hass: HomeAssistant) -> None:
    """Return None when the recorder state cannot be parsed as float."""
    hass.config.components.add("recorder")

    ts = datetime(2025, 6, 1, 10, 0, tzinfo=UTC)
    fake_state = SimpleNamespace(state="unavailable", last_updated=ts, last_changed=None)

    mock_recorder = MagicMock()
    mock_recorder.async_add_executor_job = AsyncMock(return_value={"sensor.test": [fake_state]})

    with patch(
        "custom_components.solcast_sim.restore_helpers.get_instance",
        return_value=mock_recorder,
    ):
        result = await recorder_sensor_value(hass, "sensor.test")

    assert result is None
    hass.config.components.remove("recorder")


async def test_restored_sensor_value_returns_none_when_entity_not_registered(hass: HomeAssistant) -> None:
    """Return None when the unique_id is not in the entity registry."""
    result = restored_sensor_value(hass, "solcast_sim", "solcast_sim_battery_energy")
    assert result is None


async def test_restored_sensor_value_returns_none_when_no_restore_state(hass: HomeAssistant) -> None:
    """Return None when entity is registered but has no restore state."""
    registry = er.async_get(hass)
    registry.async_get_or_create(
        domain="sensor",
        platform="solcast_sim",
        unique_id="solcast_sim_battery_energy",
    )

    result = restored_sensor_value(hass, "solcast_sim", "solcast_sim_battery_energy")
    assert result is None


async def test_prime_model_restores_from_battery_energy(hass: HomeAssistant) -> None:
    """Prime model from battery energy when that value is available."""
    model = MagicMock()

    with (
        patch(
            "custom_components.solcast_sim.restore_helpers.restored_sensor_value",
            return_value=(10.0, _T1),
        ),
        patch(
            "custom_components.solcast_sim.restore_helpers.recorder_sensor_value",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "custom_components.solcast_sim.restore_helpers._entity_id_for_unique_id",
            return_value="sensor.battery",
        ),
    ):
        await prime_model_from_restore_state(hass, "solcast_sim", model)

    model.restore_battery_energy.assert_called_once_with(10.0)
    model.restore_battery_soc.assert_not_called()


async def test_prime_model_falls_back_to_battery_soc(hass: HomeAssistant) -> None:
    """Fall back to battery SOC when energy state is unavailable."""
    model = MagicMock()

    def fake_entity_id(hass: HomeAssistant, domain: str, unique_id: str) -> str | None:
        if unique_id == "solcast_sim_battery_energy":
            return "sensor.battery_energy"
        if unique_id == "solcast_sim_battery_soc":
            return "sensor.battery_soc"
        return None

    with (
        patch(
            "custom_components.solcast_sim.restore_helpers.restored_sensor_value",
            return_value=None,
        ),
        patch(
            "custom_components.solcast_sim.restore_helpers.recorder_sensor_value",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "custom_components.solcast_sim.restore_helpers._entity_id_for_unique_id",
            side_effect=fake_entity_id,
        ),
    ):
        # Patch select_measurement_restore_value to return SOC on second call
        call_count = {"n": 0}

        def fake_select(cache, recorder):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return None  # energy not available
            return 80.0  # SOC available

        with patch(
            "custom_components.solcast_sim.restore_helpers.select_measurement_restore_value",
            side_effect=fake_select,
        ):
            await prime_model_from_restore_state(hass, "solcast_sim", model)

    model.restore_battery_energy.assert_not_called()
    model.restore_battery_soc.assert_called_once_with(80.0)


async def test_prime_model_does_nothing_when_no_state_available(hass: HomeAssistant) -> None:
    """Do nothing when neither energy nor SOC state is restorable."""
    model = MagicMock()

    with (
        patch(
            "custom_components.solcast_sim.restore_helpers.restored_sensor_value",
            return_value=None,
        ),
        patch(
            "custom_components.solcast_sim.restore_helpers.recorder_sensor_value",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "custom_components.solcast_sim.restore_helpers._entity_id_for_unique_id",
            return_value=None,
        ),
        patch(
            "custom_components.solcast_sim.restore_helpers.select_measurement_restore_value",
            return_value=None,
        ),
    ):
        await prime_model_from_restore_state(hass, "solcast_sim", model)

    model.restore_battery_energy.assert_not_called()
    model.restore_battery_soc.assert_not_called()
