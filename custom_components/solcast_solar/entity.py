"""Shared entities for Solcast."""


from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import CONFIGURATION_URL, DOMAIN, INTEGRATION, MANUFACTURER


def build_service_device_info(entry: ConfigEntry, version: str) -> DeviceInfo:
    """Build shared device info for Solcast service entities."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=INTEGRATION,
        manufacturer=MANUFACTURER,
        model=INTEGRATION,
        entry_type=DeviceEntryType.SERVICE,
        sw_version=version,
        configuration_url=CONFIGURATION_URL,
    )
