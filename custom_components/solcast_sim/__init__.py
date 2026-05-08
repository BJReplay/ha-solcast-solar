"""Solcast PV SimCity custom component."""

from collections.abc import Callable
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .sim_core import canonicalise_api_keys

PLATFORMS = [Platform.SENSOR]
_LOGGER = logging.getLogger(__name__)
DOMAIN = "solcast_sim"
ADJACENT_SOLCAST_DOMAIN = "solcast_solar"
ISSUE_ID_API_KEY_MISMATCH = "api_key_mismatch_{entry_id}"
API_KEY_MISMATCH_SUPPRESS_OPTION = "api_key_mismatch_suppress_pair"


def _get_api_key_from_entry(entry: ConfigEntry) -> str:
    """Return canonical API key string from config entry values."""
    values = {**entry.data, **entry.options}
    return canonicalise_api_keys(str(values.get("api_key", "")).strip())


def _get_adjacent_solcast_api_key(hass: HomeAssistant) -> str | None:
    """Return canonical API key string from adjacent Solcast integration, if available."""
    for entry in hass.config_entries.async_entries(ADJACENT_SOLCAST_DOMAIN):
        api_key = _get_api_key_from_entry(entry)
        if api_key:
            return api_key
    return None


def _sync_api_key_mismatch_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Create or clear a repair issue based on SimCity/Solcast API key mismatch."""
    issue_id = ISSUE_ID_API_KEY_MISMATCH.format(entry_id=entry.entry_id)
    simcity_api_keys = _get_api_key_from_entry(entry)
    solcast_api_keys = _get_adjacent_solcast_api_key(hass)
    values = {**entry.data, **entry.options}
    suppress_pair = str(values.get(API_KEY_MISMATCH_SUPPRESS_OPTION, ""))

    if not solcast_api_keys or simcity_api_keys == solcast_api_keys:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return

    mismatch_pair = f"{simcity_api_keys}|{solcast_api_keys}"
    if suppress_pair == mismatch_pair:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return

    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=True,
        is_persistent=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="api_key_mismatch",
        translation_placeholders={
            "simcity_api_keys": simcity_api_keys,
            "solcast_api_keys": solcast_api_keys,
        },
        data={"entry_id": entry.entry_id},
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Solcast PV SimCity from a config entry."""
    _LOGGER.debug("Setting up config entry %s", entry.entry_id)
    _sync_api_key_mismatch_issue(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    _LOGGER.info("Config entry %s set up", entry.entry_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading config entry %s", entry.entry_id)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        _LOGGER.info("Config entry %s unloaded", entry.entry_id)
    else:
        _LOGGER.warning("Config entry %s failed to unload cleanly", entry.entry_id)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options change."""
    _LOGGER.debug("Options updated, reloading config entry %s", entry.entry_id)
    _sync_api_key_mismatch_issue(hass, entry)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries to current version.

    v2: Group shade fields into shade_dimensions
    v3: Group related comma-separated fields for location, cloudiness, and battery limits
    v4: Remove entry-specific location/timezone fields in favour of Home Assistant core config
    """
    if entry.version > 4:
        _LOGGER.error("Cannot migrate entry version %s", entry.version)
        return False

    _LOGGER.debug("Config entry version %s", entry.version)

    def __v2(values: dict[str, Any]) -> dict[str, Any]:
        """v2 migration: group shade dimensions."""
        new_values = dict(values)
        if "shade_dimensions" not in new_values:
            height = float(new_values.pop("shade_height_m", 12.0))
            width = float(new_values.pop("shade_width_m", 8.0))
            distance = float(new_values.pop("shade_distance_m", 15.0))
            new_values["shade_dimensions"] = f"{height}, {width}, {distance}"
        return new_values

    def __v3(values: dict[str, Any]) -> dict[str, Any]:
        """v3 migration: group related CSV fields."""
        new_values = dict(values)
        if "location_coordinates" not in new_values:
            latitude = float(new_values.pop("latitude", 0.0))
            longitude = float(new_values.pop("longitude", 0.0))
            new_values["location_coordinates"] = f"{latitude}, {longitude}"
        else:
            new_values.pop("latitude", None)
            new_values.pop("longitude", None)

        if "cloudiness_profile" not in new_values:
            cloudiness_bias = float(new_values.pop("cloudiness_bias", 0.0))
            cloud_variability = float(new_values.pop("cloud_variability", 0.7))
            new_values["cloudiness_profile"] = f"{cloudiness_bias}, {cloud_variability}"
        else:
            new_values.pop("cloudiness_bias", None)
            new_values.pop("cloud_variability", None)

        if "battery_power_limits_kw" not in new_values:
            max_charge = float(new_values.pop("battery_max_charge_kw", 5.0))
            max_discharge = float(new_values.pop("battery_max_discharge_kw", 5.0))
            new_values["battery_power_limits_kw"] = f"{max_charge}, {max_discharge}"
        else:
            new_values.pop("battery_max_charge_kw", None)
            new_values.pop("battery_max_discharge_kw", None)

        return new_values

    def __v4(values: dict[str, Any]) -> dict[str, Any]:
        """v4 migration: remove entry-specific location and timezone fields."""
        new_values = dict(values)
        new_values.pop("location_coordinates", None)
        new_values.pop("timezone", None)
        new_values.pop("latitude", None)
        new_values.pop("longitude", None)
        return new_values

    def upgrade_to(version: int, upgrade_function: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        """Apply migration step and report the version bump."""
        if entry.version < version:
            hass.config_entries.async_update_entry(
                entry,
                data=upgrade_function(dict(entry.data)),
                options=upgrade_function(dict(entry.options)),
                version=version,
            )
            _LOGGER.info("Upgraded config entry to version %s", entry.version)

    upgrades: list[tuple[int, Callable[[dict[str, Any]], dict[str, Any]]]] = [
        (2, __v2),
        (3, __v3),
        (4, __v4),
    ]
    for version, upgrade_function in upgrades:
        upgrade_to(version, upgrade_function)

    return True
