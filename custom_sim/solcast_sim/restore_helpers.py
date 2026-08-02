"""State restoration helpers for Solcast PV SimCity."""

from __future__ import annotations

import contextlib
from datetime import datetime
from functools import partial

from homeassistant.components.recorder import get_instance, history
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.restore_state import async_get as async_get_restore_state

from .sim_core import BATTERY_ENERGY_UNIQUE_ID, SolcastSimBatteryModel

BATTERY_SOC_UNIQUE_ID = "solcast_sim_battery_soc"


def _entity_id_for_unique_id(
    hass: HomeAssistant,
    integration_domain: str,
    unique_id: str,
) -> str | None:
    """Resolve an entity_id from a unique_id."""
    registry = er.async_get(hass)
    return registry.async_get_entity_id(
        "sensor",
        integration_domain,
        unique_id,
    )


def restored_sensor_value(
    hass: HomeAssistant,
    integration_domain: str,
    unique_id: str,
) -> tuple[float, datetime] | None:
    """Return restored value and timestamp for a sensor by unique_id."""
    entity_id = _entity_id_for_unique_id(hass, integration_domain, unique_id)
    if entity_id is None:
        return None

    if (stored := async_get_restore_state(hass).last_states.get(entity_id)) is None:
        return None

    with contextlib.suppress(ValueError, TypeError):
        ts = stored.state.last_updated or stored.state.last_changed or stored.last_seen
        return float(stored.state.state), ts
    return None


async def recorder_sensor_value(
    hass: HomeAssistant,
    entity_id: str,
) -> tuple[float, datetime] | None:
    """Return most recent recorder value and timestamp for an entity."""
    if "recorder" not in hass.config.components:
        return None

    recorder_states = await get_instance(hass).async_add_executor_job(partial(history.get_last_state_changes, hass, 1, entity_id=entity_id))
    if not (states := recorder_states.get(entity_id)):
        return None

    with contextlib.suppress(ValueError, TypeError):
        state = states[-1]
        ts = state.last_updated or state.last_changed
        if ts is None:
            return None
        return float(state.state), ts
    return None


def select_measurement_restore_value(
    cache_state: tuple[float, datetime] | None,
    recorder_state: tuple[float, datetime] | None,
) -> float | None:
    """Select restore value for measurement sensors using newest timestamp."""
    if cache_state is None:
        return recorder_state[0] if recorder_state is not None else None
    if recorder_state is None:
        return cache_state[0]
    return cache_state[0] if cache_state[1] >= recorder_state[1] else recorder_state[0]


async def prime_model_from_restore_state(
    hass: HomeAssistant,
    integration_domain: str,
    model: SolcastSimBatteryModel,
) -> None:
    """Prime model battery state from freshest startup state source."""
    cache_state = restored_sensor_value(hass, integration_domain, BATTERY_ENERGY_UNIQUE_ID)

    recorder_state: tuple[float, datetime] | None = None
    if (energy_entity_id := _entity_id_for_unique_id(hass, integration_domain, BATTERY_ENERGY_UNIQUE_ID)) is not None:
        recorder_state = await recorder_sensor_value(hass, energy_entity_id)

    if (battery_energy := select_measurement_restore_value(cache_state, recorder_state)) is not None:
        model.restore_battery_energy(battery_energy)
        return

    # Restore from SOC sensor if battery-energy state is unavailable.
    cache_soc_state = restored_sensor_value(hass, integration_domain, BATTERY_SOC_UNIQUE_ID)
    recorder_soc_state: tuple[float, datetime] | None = None
    if (soc_entity_id := _entity_id_for_unique_id(hass, integration_domain, BATTERY_SOC_UNIQUE_ID)) is not None:
        recorder_soc_state = await recorder_sensor_value(hass, soc_entity_id)

    if (battery_soc := select_measurement_restore_value(cache_soc_state, recorder_soc_state)) is not None:
        model.restore_battery_soc(battery_soc)
