"""Tests for Solcast PV SimCity config and options flows."""

from __future__ import annotations

from custom_components.solcast_sim.config_flow import (  # pyright: ignore[reportMissingImports]
    SolcastSimConfigFlow,
    _default_api_key_from_solcast,
    _normalise_api_key,
    _normalise_battery_power_limits,
    _normalise_cloudiness_profile,
    _normalise_shade_dimensions,
)
import pytest

from homeassistant.config_entries import HANDLERS
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from tests.common import MockConfigEntry, MockModule, mock_integration, mock_platform


@pytest.fixture(autouse=True)
def register_solcast_sim_integration(hass: HomeAssistant) -> None:
    """Register a mock solcast_sim integration so config flow lookups work."""
    mock_integration(
        hass,
        MockModule(
            "solcast_sim",
            partial_manifest={"config_flow": True, "single_config_entry": False},
        ),
    )
    mock_platform(hass, "solcast_sim.config_flow", None)
    HANDLERS["solcast_sim"] = SolcastSimConfigFlow


@pytest.fixture
def ignore_translations_for_mock_domains() -> list[str]:
    """Do not validate translations for the mocked solcast_sim domain."""
    return ["solcast_sim"]


def test_normalise_shade_dimensions_valid() -> None:
    """Accept a valid three-part dimensions string."""
    assert _normalise_shade_dimensions("12.0, 8.0, 15.0") == "12.0, 8.0, 15.0"


def test_normalise_shade_dimensions_strips_whitespace() -> None:
    """Accept whitespace-padded values."""
    assert _normalise_shade_dimensions("  6.0 , 4.0 , 10.0 ") == "6.0, 4.0, 10.0"


@pytest.mark.parametrize(
    "value",
    [
        "12.0, 8.0",  # Only two parts
        "0.0, 8.0, 15.0",  # Height zero
        "abc, def, ghi",  # Non-numeric
        "",  # Empty
    ],
)
def test_normalise_shade_dimensions_rejects_invalid(value: str) -> None:
    """Reject malformed shade dimension strings."""
    with pytest.raises(ValueError):
        _normalise_shade_dimensions(value)


def test_normalise_cloudiness_profile_valid() -> None:
    """Accept a valid two-part cloudiness profile."""
    assert _normalise_cloudiness_profile("0.0, 0.7") == "0.0, 0.7"


def test_normalise_cloudiness_profile_rejects_wrong_parts() -> None:
    """Reject profiles with wrong number of parts."""
    with pytest.raises(ValueError):
        _normalise_cloudiness_profile("0.0")


def test_normalise_cloudiness_profile_rejects_non_numeric() -> None:
    """Reject non-numeric cloudiness profiles."""
    with pytest.raises(ValueError):
        _normalise_cloudiness_profile("high, variable")


def test_normalise_battery_power_limits_valid() -> None:
    """Accept valid charge/discharge limits."""
    assert _normalise_battery_power_limits("5.0, 5.0") == "5.0, 5.0"


def test_normalise_battery_power_limits_rejects_negative() -> None:
    """Reject negative power limits."""
    with pytest.raises(ValueError):
        _normalise_battery_power_limits("-1.0, 5.0")


def test_normalise_battery_power_limits_rejects_wrong_parts() -> None:
    """Reject limits with wrong number of parts."""
    with pytest.raises(ValueError):
        _normalise_battery_power_limits("5.0")


def test_normalise_battery_power_limits_rejects_non_numeric() -> None:
    """Reject non-numeric limits."""
    with pytest.raises(ValueError):
        _normalise_battery_power_limits("fast, slow")


def test_normalise_api_key_accepts_valid_key() -> None:
    """Accept a known API key."""
    result = _normalise_api_key("1")
    assert result == "1"


def test_normalise_api_key_rejects_unknown_key() -> None:
    """Reject an unrecognised API key."""
    with pytest.raises(ValueError, match="invalid_api_key"):
        _normalise_api_key("not-a-real-key-xyz")


def test_normalise_api_key_rejects_empty() -> None:
    """Reject an empty API key."""
    with pytest.raises(ValueError, match="invalid_api_key"):
        _normalise_api_key("")


def test_default_api_key_from_solcast_returns_none_without_hass() -> None:
    """Return None when hass is None."""
    assert _default_api_key_from_solcast(None) is None


async def test_default_api_key_from_solcast_returns_none_when_no_entries(hass: HomeAssistant) -> None:
    """Return None when there are no adjacent Solcast entries."""
    result = _default_api_key_from_solcast(hass)
    assert result is None


async def test_default_api_key_from_solcast_returns_key_from_entry(hass: HomeAssistant) -> None:
    """Return canonical key when an adjacent Solcast entry exists."""
    entry = MockConfigEntry(
        domain="solcast_solar",
        data={"api_key": " 1 "},
        options={},
    )
    entry.add_to_hass(hass)
    result = _default_api_key_from_solcast(hass)
    assert result == "1"


async def test_default_api_key_from_solcast_skips_empty_key(hass: HomeAssistant) -> None:
    """Skip entries that have an empty api_key."""
    entry = MockConfigEntry(
        domain="solcast_solar",
        data={"api_key": ""},
        options={},
    )
    entry.add_to_hass(hass)
    result = _default_api_key_from_solcast(hass)
    assert result is None


_VALID_USER_INPUT = {
    "api_key": "1",
    "season": "auto",
    "cloudiness_profile": "0.0, 0.7",
    "estimated_actuals_uncertainty_pct": 15.0,
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
}


async def test_config_flow_shows_form_on_initial_open(hass: HomeAssistant) -> None:
    """Show the user form on first step with no input."""
    result = await hass.config_entries.flow.async_init("solcast_sim", context={"source": "user"})
    assert result["type"] == FlowResultType.FORM  # pyright: ignore[reportTypedDictNotRequiredAccess]
    assert result["step_id"] == "user"  # pyright: ignore[reportTypedDictNotRequiredAccess]


async def test_config_flow_creates_entry_with_valid_input(hass: HomeAssistant) -> None:
    """Create a config entry when all input is valid."""
    result = await hass.config_entries.flow.async_init("solcast_sim", context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input=_VALID_USER_INPUT)
    assert result["type"] == FlowResultType.CREATE_ENTRY  # pyright: ignore[reportTypedDictNotRequiredAccess]
    assert result["data"]["api_key"] == "1"  # pyright: ignore[reportTypedDictNotRequiredAccess]


async def test_config_flow_aborts_on_duplicate_api_key(hass: HomeAssistant) -> None:
    """Abort flow when the same API key is already configured."""
    existing = MockConfigEntry(
        domain="solcast_sim",
        data=_VALID_USER_INPUT,
        unique_id="1",
        version=6,
    )
    existing.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init("solcast_sim", context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input=_VALID_USER_INPUT)
    assert result["type"] == FlowResultType.ABORT  # pyright: ignore[reportTypedDictNotRequiredAccess]
    assert result["reason"] == "already_configured"  # pyright: ignore[reportTypedDictNotRequiredAccess]


async def test_config_flow_shows_error_for_invalid_api_key(hass: HomeAssistant) -> None:
    """Show api_key error when an unknown key is submitted."""
    bad_input = {**_VALID_USER_INPUT, "api_key": "not-valid-xyz"}
    result = await hass.config_entries.flow.async_init("solcast_sim", context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input=bad_input)
    assert result["type"] == FlowResultType.FORM  # pyright: ignore[reportTypedDictNotRequiredAccess]
    errors = result["errors"]  # pyright: ignore[reportTypedDictNotRequiredAccess]
    assert errors is not None
    assert "api_key" in errors


async def test_config_flow_shows_error_for_invalid_shade_dimensions(hass: HomeAssistant) -> None:
    """Show shade_dimensions error when dimensions are malformed."""
    bad_input = {**_VALID_USER_INPUT, "shade_dimensions": "bad, data"}
    result = await hass.config_entries.flow.async_init("solcast_sim", context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input=bad_input)
    assert result["type"] == FlowResultType.FORM  # pyright: ignore[reportTypedDictNotRequiredAccess]
    errors = result["errors"]  # pyright: ignore[reportTypedDictNotRequiredAccess]
    assert errors is not None
    assert "shade_dimensions" in errors


async def test_config_flow_shows_error_for_invalid_cloudiness_profile(hass: HomeAssistant) -> None:
    """Show cloudiness_profile error for a malformed profile."""
    bad_input = {**_VALID_USER_INPUT, "cloudiness_profile": "only_one"}
    result = await hass.config_entries.flow.async_init("solcast_sim", context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input=bad_input)
    assert result["type"] == FlowResultType.FORM  # pyright: ignore[reportTypedDictNotRequiredAccess]
    errors = result["errors"]  # pyright: ignore[reportTypedDictNotRequiredAccess]
    assert errors is not None
    assert "cloudiness_profile" in errors


async def test_config_flow_shows_error_for_invalid_battery_limits(hass: HomeAssistant) -> None:
    """Show battery_power_limits_kw error when limits are malformed."""
    bad_input = {**_VALID_USER_INPUT, "battery_power_limits_kw": "-1.0, 5.0"}
    result = await hass.config_entries.flow.async_init("solcast_sim", context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input=bad_input)
    assert result["type"] == FlowResultType.FORM  # pyright: ignore[reportTypedDictNotRequiredAccess]
    errors = result["errors"]  # pyright: ignore[reportTypedDictNotRequiredAccess]
    assert errors is not None
    assert "battery_power_limits_kw" in errors


async def test_config_flow_shows_error_for_invalid_shade_density_profile(hass: HomeAssistant) -> None:
    """Show shade_density_profile error for a non-ascending profile."""
    bad_input = {**_VALID_USER_INPUT, "shade_density_profile": "0.9, 0.5, 1.0"}
    result = await hass.config_entries.flow.async_init("solcast_sim", context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input=bad_input)
    assert result["type"] == FlowResultType.FORM  # pyright: ignore[reportTypedDictNotRequiredAccess]
    errors = result["errors"]  # pyright: ignore[reportTypedDictNotRequiredAccess]
    assert errors is not None
    assert "shade_density_profile" in errors


async def test_options_flow_shows_form_on_initial_open(hass: HomeAssistant) -> None:
    """Show the options form on first open with no input."""
    entry = MockConfigEntry(
        domain="solcast_sim",
        data=_VALID_USER_INPUT,
        options={},
        version=6,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM  # pyright: ignore[reportTypedDictNotRequiredAccess]
    assert result["step_id"] == "init"  # pyright: ignore[reportTypedDictNotRequiredAccess]


async def test_options_flow_saves_valid_input(hass: HomeAssistant) -> None:
    """Create an options entry when all input is valid."""
    entry = MockConfigEntry(
        domain="solcast_sim",
        data=_VALID_USER_INPUT,
        options={},
        version=6,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    updated = {**_VALID_USER_INPUT, "house_load_kw": 1.5}
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input=updated)
    assert result["type"] == FlowResultType.CREATE_ENTRY  # pyright: ignore[reportTypedDictNotRequiredAccess]
    assert result["data"]["house_load_kw"] == 1.5  # pyright: ignore[reportTypedDictNotRequiredAccess]


async def test_options_flow_shows_error_for_invalid_api_key(hass: HomeAssistant) -> None:
    """Show api_key error when an unknown key is submitted via options."""
    entry = MockConfigEntry(
        domain="solcast_sim",
        data=_VALID_USER_INPUT,
        options={},
        version=6,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    bad_input = {**_VALID_USER_INPUT, "api_key": "not-valid-xyz"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input=bad_input)
    assert result["type"] == FlowResultType.FORM  # pyright: ignore[reportTypedDictNotRequiredAccess]
    options_errors = result["errors"]  # pyright: ignore[reportTypedDictNotRequiredAccess]
    assert options_errors is not None
    assert "api_key" in options_errors


@pytest.mark.parametrize(
    ("field", "bad_value", "expected_error_field"),
    [
        pytest.param("shade_dimensions", "bad, data", "shade_dimensions", id="shade_dimensions"),
        pytest.param("cloudiness_profile", "only_one", "cloudiness_profile", id="cloudiness_profile"),
        pytest.param("battery_power_limits_kw", "-1.0, 5.0", "battery_power_limits_kw", id="battery_limits"),
        pytest.param("shade_density_profile", "0.9, 0.5, 1.0", "shade_density_profile", id="shade_density"),
    ],
)
async def test_options_flow_shows_error_for_invalid_fields(
    hass: HomeAssistant,
    field: str,
    bad_value: str,
    expected_error_field: str,
) -> None:
    """Show field-specific error when options input is invalid."""
    entry = MockConfigEntry(domain="solcast_sim", data=_VALID_USER_INPUT, options={}, version=6)
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    bad_input = {**_VALID_USER_INPUT, field: bad_value}
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input=bad_input)

    assert result["type"] == FlowResultType.FORM  # pyright: ignore[reportTypedDictNotRequiredAccess]
    errors = result["errors"]  # pyright: ignore[reportTypedDictNotRequiredAccess]
    assert errors is not None
    assert expected_error_field in errors
