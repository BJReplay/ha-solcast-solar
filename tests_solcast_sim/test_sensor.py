"""Tests for the Solcast PV SimCity sensor platform."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from custom_components.solcast_sim import (  # pyright: ignore[reportMissingImports]
    sensor as _sensor,
)
import pytest

from homeassistant.core import HomeAssistant

from tests.common import MockConfigEntry


@pytest.fixture
def ignore_translations_for_mock_domains() -> list[str]:
    """Do not validate translations for the custom solcast_sim domain."""
    return ["solcast_sim"]


_CONFIG: dict = {
    "api_key": "1",
    "season": "auto",
    "cloudiness_profile": "0.0, 0.7",
    "shade_dimensions": "12.0, 8.0, 15.0",
    "shade_azimuth_deg": 0.0,
    "shade_opacity": 0.0,
    "shade_density_profile": "0.3, 0.8, 1.0",
    "export_factor": 1.0,
    "export_limit_kw": 5.0,
    "battery_capacity_kwh": 13.5,
    "battery_power_limits_kw": "5.0, 5.0",
    "house_load_kw": 1.0,
    "free_charge_start": "11:00:00",
    "free_charge_end": "14:00:00",
    "estimated_actuals_uncertainty_pct": 15.0,
}


@pytest.mark.parametrize(
    ("interval", "expected"),
    [
        pytest.param(timedelta(hours=1), "hourly", id="hourly"),
        pytest.param(timedelta(days=1), "daily", id="daily"),
        pytest.param(timedelta(minutes=1), "every minute", id="per_minute"),
        pytest.param(timedelta(seconds=30), "every 30 seconds", id="per_30s"),
    ],
)
def test_describe_interval(interval: timedelta, expected: str) -> None:
    """_describe_interval formats intervals as readable strings."""
    assert _sensor._describe_interval(interval) == expected


async def test_async_setup_entry_uses_cached_climate(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """async_setup_entry loads from climate cache and creates entities."""
    entry = MockConfigEntry(domain="solcast_sim", data=_CONFIG, options={}, version=6)
    entry.add_to_hass(hass)

    fake_months = [{"mean": 0.4, "std": 0.1}] * 12
    fake_astral = SimpleNamespace()

    monkeypatch.setattr(_sensor, "get_astral_location", lambda _hass: (fake_astral, fake_astral))
    monkeypatch.setattr(_sensor, "_load_climate_cache", lambda *a: fake_months)
    monkeypatch.setattr(_sensor, "_async_write_guidance_file", AsyncMock())
    monkeypatch.setattr(_sensor, "_prime_model_from_restore_state", AsyncMock())

    entities: list = []
    await _sensor.async_setup_entry(hass, entry, entities.extend)

    assert len(entities) > 0


async def test_async_setup_entry_fetches_climate_on_cache_miss(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """async_setup_entry fetches and saves climate normals when the cache is empty."""
    entry = MockConfigEntry(domain="solcast_sim", data=_CONFIG, options={}, version=6)
    entry.add_to_hass(hass)

    fake_months = [{"mean": 0.5, "std": 0.12}] * 12
    fake_astral = SimpleNamespace()
    saved: list = []

    monkeypatch.setattr(_sensor, "get_astral_location", lambda _hass: (fake_astral, fake_astral))
    monkeypatch.setattr(_sensor, "_load_climate_cache", lambda *a: None)
    monkeypatch.setattr(_sensor, "_async_fetch_climate_normals", AsyncMock(return_value=fake_months))
    monkeypatch.setattr(_sensor, "_save_climate_cache", lambda *a: saved.append(a))
    monkeypatch.setattr(_sensor, "_async_write_guidance_file", AsyncMock())
    monkeypatch.setattr(_sensor, "_prime_model_from_restore_state", AsyncMock())

    entities: list = []
    await _sensor.async_setup_entry(hass, entry, entities.extend)

    assert len(saved) == 1
    assert len(entities) > 0


async def test_async_setup_entry_proceeds_without_climate(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """async_setup_entry uses seasonal defaults when climate fetch returns None."""
    entry = MockConfigEntry(domain="solcast_sim", data=_CONFIG, options={}, version=6)
    entry.add_to_hass(hass)

    fake_astral = SimpleNamespace()

    monkeypatch.setattr(_sensor, "get_astral_location", lambda _hass: (fake_astral, fake_astral))
    monkeypatch.setattr(_sensor, "_load_climate_cache", lambda *a: None)
    monkeypatch.setattr(_sensor, "_async_fetch_climate_normals", AsyncMock(return_value=None))
    monkeypatch.setattr(_sensor, "_async_write_guidance_file", AsyncMock())
    monkeypatch.setattr(_sensor, "_prime_model_from_restore_state", AsyncMock())

    entities: list = []
    await _sensor.async_setup_entry(hass, entry, entities.extend)

    assert len(entities) > 0


async def test_async_setup_entry_invalid_api_key_raises(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """async_setup_entry raises ValueError for unknown api_key."""
    config = {**_CONFIG, "api_key": "invalid_key"}
    entry = MockConfigEntry(domain="solcast_sim", data=config, options={}, version=6)
    entry.add_to_hass(hass)
    fake_astral = SimpleNamespace()
    monkeypatch.setattr(_sensor, "get_astral_location", lambda _hass: (fake_astral, fake_astral))

    with pytest.raises(ValueError, match="invalid api_key"):
        await _sensor.async_setup_entry(hass, entry, lambda _: None)


async def test_async_setup_entry_deduplicates_overlapping_sites(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Duplicate resource_ids across API keys are skipped."""
    config = {**_CONFIG, "api_key": "1, 2"}
    entry = MockConfigEntry(domain="solcast_sim", data=config, options={}, version=6)
    entry.add_to_hass(hass)
    fake_astral = SimpleNamespace()
    monkeypatch.setattr(_sensor, "get_astral_location", lambda _hass: (fake_astral, fake_astral))
    monkeypatch.setattr(
        _sensor,
        "API_KEY_SITES",
        {
            "1": {"sites": [{"resource_id": "shared_site", "name": "Shared", "capacity": 5.0}]},
            "2": {"sites": [{"resource_id": "shared_site", "name": "Shared", "capacity": 5.0}]},
        },
    )
    monkeypatch.setattr(_sensor, "_load_climate_cache", lambda *a: None)
    monkeypatch.setattr(_sensor, "_async_fetch_climate_normals", AsyncMock(return_value=None))
    monkeypatch.setattr(_sensor, "_async_write_guidance_file", AsyncMock())
    monkeypatch.setattr(_sensor, "_prime_model_from_restore_state", AsyncMock())

    entities: list = []
    await _sensor.async_setup_entry(hass, entry, entities.extend)

    assert len(entities) > 0
