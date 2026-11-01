"""Test proxy header handling and persisted configuration state."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime as dt
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.solcast_solar.const import (
    ESTIMATED_ACTUALS,
    PROXY_CACHE_STATE,
    PROXY_FORECAST_CRON,
    PROXY_MODE,
    PROXY_POLL_DELAY_SECONDS,
    PROXY_SAVED_AUTO_UPDATE,
    SITES,
    TOTAL_RECORDS,
)
from custom_components.solcast_solar.fetcher import Fetcher
from custom_components.solcast_solar.solcastapi import SolcastApi
import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.core import HomeAssistant

from . import DEFAULT_INPUT1, async_cleanup_integration_tests, async_init_integration


@pytest.fixture
async def solcast(recorder_mock: Recorder, hass: HomeAssistant) -> AsyncGenerator[SolcastApi]:
    """Set up the integration without background fetch callbacks."""
    try:
        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        await entry.runtime_data.coordinator.tasks_cancel()
        await entry.runtime_data.coordinator.solcast.tasks_cancel()
        yield entry.runtime_data.coordinator.solcast
    finally:
        await async_cleanup_integration_tests(hass)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(None, None, id="missing"),
        pytest.param(" TrUe ", True, id="true"),
        pytest.param(" FaLsE ", False, id="false"),
        pytest.param("unknown", None, id="unknown"),
    ],
)
def test_proxy_boolean_header(value: str | None, expected: bool | None) -> None:
    """Only explicit true/false headers provide a boolean state."""
    assert Fetcher._header_as_bool(value) is expected


@pytest.mark.parametrize("value", [pytest.param(None, id="missing"), pytest.param("invalid", id="invalid")])
def test_proxy_datetime_header_unavailable(value: str | None) -> None:
    """Missing or malformed timestamps do not provide a retry schedule."""
    assert Fetcher._header_as_dt(value) is None


async def test_missing_proxy_resource_headers(solcast: SolcastApi) -> None:
    """An absent header mapping does not enable proxy mode."""
    assert await solcast.fetcher._apply_proxy_resource_headers(None) is False
    assert solcast.proxy_mode is False


async def test_actuals_headers_preserve_forecast_state(solcast: SolcastApi) -> None:
    """Actuals collection state must not replace the forecast retry schedule."""
    next_attempt = dt(2026, 11, 1, 9, 10, tzinfo=UTC)
    solcast.proxy_next_attempt_at = next_attempt
    solcast.proxy_upstream_status = 429
    solcast.proxy_halted = True
    solcast.proxy_fetch_in_progress = True
    solcast.proxy_last_fetch_status = "retrying"

    assert await solcast.fetcher._apply_proxy_resource_headers(
        {
            "x-proxy-upstream-status": "200",
            "x-proxy-next-attempt-at": "2026-11-02T23:55:00+00:00",
            "x-proxy-halted": "false",
            "x-proxy-fetch-in-progress": "false",
            "x-proxy-last-fetch-status": "clean_success",
        },
        path=ESTIMATED_ACTUALS,
    ) is True

    assert solcast.proxy_mode is True
    assert solcast.proxy_next_attempt_at == next_attempt
    assert solcast.proxy_upstream_status == 429
    assert solcast.proxy_halted is True
    assert solcast.proxy_fetch_in_progress is True
    assert solcast.proxy_last_fetch_status == "retrying"


async def test_proxy_mode_without_config_entry(solcast: SolcastApi) -> None:
    """Proxy detection still updates runtime state when there is no config entry."""
    entry = solcast.entry
    solcast.entry = None
    try:
        await solcast.async_set_proxy_mode(True)

        assert solcast.proxy_mode is True
        assert solcast.proxy_saved_auto_update == int(solcast.options.auto_update)
    finally:
        solcast.entry = entry


@pytest.mark.parametrize("delay", [pytest.param(9, id="positive"), pytest.param(-1, id="clamped")])
async def test_proxy_poll_delay_persists_once(solcast: SolcastApi, delay: int) -> None:
    """Persist changed poll delays, but do not rewrite an unchanged value."""
    expected = max(0, delay)
    with patch.object(solcast.hass.config_entries, "async_update_entry", wraps=solcast.hass.config_entries.async_update_entry) as update:
        await solcast.async_set_proxy_poll_delay(delay, source="test")

        assert solcast.proxy_poll_delay_seconds == expected
        assert solcast.entry.options[PROXY_POLL_DELAY_SECONDS] == expected
        assert solcast.entry_options[PROXY_POLL_DELAY_SECONDS] == expected
        update.assert_called_once()

        await solcast.async_set_proxy_poll_delay(delay, source="test")

        update.assert_called_once()


@pytest.mark.parametrize(
    ("cron", "expected"),
    [
        pytest.param("  */10 * * * *  ", "*/10 * * * *", id="trimmed"),
        pytest.param("   ", None, id="empty"),
        pytest.param(None, None, id="removed"),
    ],
)
async def test_proxy_forecast_cron_persists_once(solcast: SolcastApi, cron: str | None, expected: str | None) -> None:
    """Persist normalized cron changes without rewriting unchanged state."""
    await solcast.async_set_proxy_forecast_cron("0 * * * *")
    with patch.object(solcast.hass.config_entries, "async_update_entry", wraps=solcast.hass.config_entries.async_update_entry) as update:
        await solcast.async_set_proxy_forecast_cron(cron, source="test")

        assert solcast.proxy_forecast_cron == expected
        assert solcast.entry.options[PROXY_FORECAST_CRON] == expected
        assert solcast.entry_options[PROXY_FORECAST_CRON] == expected
        update.assert_called_once()

        await solcast.async_set_proxy_forecast_cron(cron, source="test")

        update.assert_called_once()


@pytest.mark.parametrize(
    ("headers", "initial_proxy_mode", "expected_mode", "expected_delay", "expected_cron"),
    [
        pytest.param(
            {"x-solcast-proxy": "true", "x-proxy-poll-delay-seconds": "9", "x-proxy-forecast-cron": "*/10 * * * *"},
            False, True, 9, "*/10 * * * *", id="proxy-discovery",
        ),
        pytest.param(
            {"x-solcast-proxy": "true", "x-proxy-poll-delay-seconds": "invalid"},
            False, True, 5, None, id="invalid-delay",
        ),
        pytest.param({"x-solcast-proxy": "TRUE"}, False, True, 5, None, id="optional-headers-absent"),
        pytest.param({}, True, False, 5, None, id="direct-discovery"),
    ],
)
async def test_discovery_persists_proxy_headers(
    solcast: SolcastApi,
    headers: dict[str, str],
    initial_proxy_mode: bool,
    expected_mode: bool,
    expected_delay: int,
    expected_cron: str | None,
) -> None:
    """Discovery updates persistent proxy state and the sites cache metadata."""
    await solcast.async_set_proxy_mode(initial_proxy_mode)
    payload = {SITES: solcast.sites, TOTAL_RECORDS: len(solcast.sites)}
    response = MagicMock(status=200, headers=headers)
    response.text = AsyncMock(return_value=json.dumps(payload))

    session = MagicMock()
    session.get = AsyncMock(return_value=response)
    with patch.object(solcast, "aiohttp_session", session):
        status, _, _ = await solcast.sites_cache._sites_data(use_cache=False)

    assert status == 200
    assert solcast.proxy_mode is expected_mode
    assert solcast.proxy_poll_delay_seconds == expected_delay
    assert solcast.proxy_forecast_cron == expected_cron
    assert solcast.entry.options[PROXY_MODE] is expected_mode
    assert solcast.entry.options[PROXY_POLL_DELAY_SECONDS] == expected_delay
    assert solcast.entry.options.get(PROXY_FORECAST_CRON) == expected_cron
    assert solcast.proxy_saved_auto_update == int(solcast.options.auto_update)
    assert solcast.entry.options.get(PROXY_SAVED_AUTO_UPDATE) == solcast.proxy_saved_auto_update

    cache_path = solcast.sites_cache._get_sites_cache_filename(solcast.options.api_key)
    cache = json.loads(Path(cache_path).read_text(encoding="utf-8"))
    assert cache[PROXY_CACHE_STATE] == {
        PROXY_MODE: expected_mode,
        PROXY_POLL_DELAY_SECONDS: expected_delay,
        PROXY_FORECAST_CRON: expected_cron,
    }
