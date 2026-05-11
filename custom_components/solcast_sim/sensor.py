"""Solcast PV SimCity sensor platform."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.sun import get_astral_location

from .entities import build_entities
from .guidance import (
    CLIMATE_CACHE_FILENAME,
    GUIDANCE_UPDATE_INTERVAL,
    async_fetch_climate_normals as _async_fetch_climate_normals,
    async_write_guidance_file as _async_write_guidance_file,
    build_storage_path as _build_storage_path,
    load_climate_cache as _load_climate_cache,
    save_climate_cache as _save_climate_cache,
)
from .restore_helpers import (
    prime_model_from_restore_state as _prime_model_from_restore_state,
)
from .sim_core import (
    API_KEY_SITES,
    SimulationProfile,
    SolcastSimBatteryModel,
    canonicalise_api_keys as _canonicalise_api_keys,
    clip as _clip,
    derived_random_seed as _derived_random_seed,
    parse_api_keys as _parse_api_keys,
    parse_shade_azimuth_to_compass as _parse_shade_azimuth_to_compass,
    parse_shade_density_profile as _parse_shade_density_profile,
    seconds_since_midnight as _seconds_since_midnight,
    time_str_to_seconds as _time_str_to_seconds,
)

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(seconds=5)


def _describe_interval(interval: timedelta) -> str:
    """Return a plain-English cadence string for logs."""
    if interval == timedelta(hours=1):
        return "hourly"
    if interval == timedelta(days=1):
        return "daily"
    if interval == timedelta(minutes=1):
        return "every minute"
    total_seconds = int(interval.total_seconds())
    return f"every {total_seconds} seconds"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Solcast PV SimCity sensors from a config entry."""
    config = {**entry.data, **entry.options}
    api_keys_csv = _canonicalise_api_keys(str(config.get("api_key", "1")))
    api_keys = _parse_api_keys(api_keys_csv)
    latitude = float(getattr(hass.config, "latitude", 0.0))
    longitude = float(getattr(hass.config, "longitude", 0.0))
    tz = ZoneInfo(str(getattr(hass.config, "time_zone", "UTC")))
    astral_location, astral_elevation = get_astral_location(hass)
    export_factor: float = float(config.get("export_factor", 1.0))
    export_limit_kw: float = float(config.get("export_limit_kw", 5.0))
    season: str = str(config.get("season", "auto"))
    _cloud_profile_raw: str = str(config.get("cloudiness_profile", "0.0, 0.7"))
    _cloud_profile_parts = [p.strip() for p in _cloud_profile_raw.split(",")]
    cloudiness_bias: float = float(_cloud_profile_parts[0])
    cloud_variability: float = float(_cloud_profile_parts[1])
    estimated_actuals_uncertainty_pct: float = float(config.get("estimated_actuals_uncertainty_pct", 15.0))
    _shade_dims_raw: str = str(config.get("shade_dimensions", "12.0, 8.0, 15.0"))
    _shade_parts = [p.strip() for p in str(_shade_dims_raw).split(",")]
    shade_height_m: float = max(0.0, float(_shade_parts[0]))
    shade_width_m: float = max(0.0, float(_shade_parts[1]))
    shade_distance_m: float = max(0.0, float(_shade_parts[2]))
    shade_azimuth_deg: float = _parse_shade_azimuth_to_compass(float(config.get("shade_azimuth_deg", 0.0)))
    shade_opacity: float = _clip(float(config.get("shade_opacity", 0.0)), 0.0, 1.0)
    shade_density_profile = _parse_shade_density_profile(str(config.get("shade_density_profile", "0.3, 0.8, 1.0")))
    random_seed: str = _derived_random_seed(api_keys_csv, latitude, longitude)
    battery_capacity_kwh: float = float(config.get("battery_capacity_kwh", 13.5))
    _battery_limits_raw: str = str(config.get("battery_power_limits_kw", "5.0, 5.0"))
    _battery_limits_parts = [p.strip() for p in _battery_limits_raw.split(",")]
    battery_max_charge_kw: float = float(_battery_limits_parts[0])
    battery_max_discharge_kw: float = float(_battery_limits_parts[1])
    house_load_kw: float = float(config.get("house_load_kw", 1.0))
    free_charge_start_s: int = _time_str_to_seconds(config.get("free_charge_start", "11:00:00"))
    free_charge_end_s: int = _time_str_to_seconds(config.get("free_charge_end", "14:00:00"))
    invalid_api_keys = [api_key for api_key in api_keys if api_key not in API_KEY_SITES]
    if invalid_api_keys:
        raise ValueError(f"solcast_sim: invalid api_key value(s) {invalid_api_keys}. Available keys: {list(API_KEY_SITES)}")

    sites: list[dict[str, Any]] = []
    seen_site_ids: set[str] = set()
    for api_key in api_keys:
        for site in API_KEY_SITES[api_key]["sites"]:
            site_id = str(site["resource_id"])
            if site_id in seen_site_ids:
                continue
            seen_site_ids.add(site_id)
            sites.append(site)

    _LOGGER.info(
        "Setting up simulation profile with API key(s) %s, %s site(s), Home Assistant timezone %s, season %s",
        api_keys_csv,
        len(sites),
        tz,
        season,
    )

    config_dir = Path(hass.config.config_dir)
    climate_cache_path = _build_storage_path(config_dir, CLIMATE_CACHE_FILENAME)
    climate_months: list[dict[str, float]] | None = await hass.async_add_executor_job(
        _load_climate_cache, climate_cache_path, latitude, longitude
    )
    if climate_months is None:
        climate_months = await _async_fetch_climate_normals(hass, latitude, longitude)
        if climate_months is not None:
            await hass.async_add_executor_job(_save_climate_cache, climate_cache_path, latitude, longitude, climate_months)
            _LOGGER.debug("Climate normals fetched from Open-Meteo for configured location")
        else:
            _LOGGER.warning(
                "Could not fetch climate normals from Open-Meteo for configured location; using built-in seasonal defaults",
            )
    else:
        _LOGGER.debug("Climate normals loaded from cache for configured location")

    climate_cloud_means = tuple(m["mean"] for m in climate_months) if climate_months else None
    climate_cloud_stds = tuple(m["std"] for m in climate_months) if climate_months else None

    profile = SimulationProfile(
        season=season,
        latitude=latitude,
        longitude=longitude,
        cloudiness_bias=cloudiness_bias,
        cloud_variability=cloud_variability,
        estimated_actuals_uncertainty_pct=estimated_actuals_uncertainty_pct,
        shade_height_m=shade_height_m,
        shade_width_m=shade_width_m,
        shade_distance_m=shade_distance_m,
        shade_azimuth_deg=shade_azimuth_deg,
        shade_opacity=shade_opacity,
        shade_density_profile=shade_density_profile,
        astral_location=astral_location,
        astral_elevation=astral_elevation,
        random_seed=random_seed,
        climate_monthly_cloud=climate_cloud_means,
        climate_monthly_cloud_std=climate_cloud_stds,
    )

    await _async_write_guidance_file(hass, profile, tz, sites)
    _LOGGER.debug("Guidance file generated for timezone %s", tz)

    @callback
    def _handle_guidance_refresh(_now: datetime) -> None:
        hass.async_create_task(_async_write_guidance_file(hass, profile, tz, sites))

    entry.async_on_unload(async_track_time_interval(hass, _handle_guidance_refresh, GUIDANCE_UPDATE_INTERVAL))
    _LOGGER.debug("Guidance refresh scheduled %s", _describe_interval(GUIDANCE_UPDATE_INTERVAL))

    model = SolcastSimBatteryModel(
        sites,
        tz,
        profile,
        export_factor,
        export_limit_kw,
        battery_capacity_kwh,
        battery_max_charge_kw,
        battery_max_discharge_kw,
        house_load_kw,
        free_charge_start_s,
        free_charge_end_s,
    )
    await _prime_model_from_restore_state(hass, entry.domain, model)
    model.prime_power_state(_seconds_since_midnight(tz))

    entities = build_entities(sites, tz, profile, model)
    async_add_entities(entities)
    _LOGGER.info("Added %s sensor entities", len(entities))
