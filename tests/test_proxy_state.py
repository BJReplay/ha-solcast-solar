"""Test proxy header handling and persisted configuration state."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime as dt
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from cronsim import CronSim
from custom_components.solcast_solar.const import (
    ESTIMATED_ACTUALS,
    PROXY_ACTUALS_CRON,
    PROXY_ACTUALS_TIMES_UTC,
    PROXY_CACHE_STATE,
    PROXY_FORECAST_CRON,
    PROXY_FORECAST_TIMES_UTC,
    PROXY_MODE,
    PROXY_POLL_DELAY_SECONDS,
    PROXY_SAVED_AUTO_UPDATE,
    PROXY_SCHEDULE_DAY_UTC,
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


@pytest.mark.parametrize(
    ("base_time", "cron_expression", "expected"),
    [
        pytest.param(dt(2026, 11, 1, 9, 6, tzinfo=UTC), "*/10 * * * *", dt(2026, 11, 1, 9, 10, tzinfo=UTC), id="valid"),
        pytest.param(dt(2026, 11, 1, 9, 6, tzinfo=UTC), "* * * *", None, id="bad-field-count"),
        pytest.param(dt(2026, 11, 1, 9, 6, tzinfo=UTC), "*/0 * * * *", None, id="cronsim-error"),
    ],
)
def test_proxy_cron_next_occurrence(base_time: dt, cron_expression: str, expected: dt | None) -> None:
    """Cron fallback returns the next UTC time or None for invalid expressions."""
    assert Fetcher._next_from_proxy_cron(base_time, cron_expression) == expected


@pytest.mark.parametrize(
    ("base_time", "schedule_day_utc", "slots_utc", "expected"),
    [
        pytest.param(dt(2026, 11, 1, 18, 24, tzinfo=UTC), None, ("18:30",), None, id="missing-day"),
        pytest.param(dt(2026, 11, 1, 18, 24, tzinfo=UTC), "2026-11-01", (), None, id="no-slots"),
        pytest.param(dt(2026, 11, 1, 18, 24, tzinfo=UTC), "2026-11-01", ("bad",), None, id="invalid-slot"),
        pytest.param(
            dt(2026, 11, 1, 18, 24, tzinfo=UTC),
            "2026-11-01",
            ("18:24", "18:30"),
            dt(2026, 11, 1, 18, 30, tzinfo=UTC),
            id="next-future-slot",
        ),
    ],
)
def test_proxy_schedule_next_occurrence(
    base_time: dt,
    schedule_day_utc: str | None,
    slots_utc: tuple[str, ...],
    expected: dt | None,
) -> None:
    """Schedule-day fallback returns the next future slot, or None when unavailable."""
    assert Fetcher._next_from_proxy_schedule(base_time, schedule_day_utc, slots_utc) == expected


@pytest.mark.parametrize(
    ("base_time", "slots_utc", "poll_delay_seconds", "expected"),
    [
        pytest.param(dt(2026, 11, 1, 18, 24, tzinfo=UTC), ("18:24", "18:30"), 5, dt(2026, 11, 1, 18, 24, tzinfo=UTC), id="inside-window"),
        pytest.param(
            dt(2026, 11, 1, 18, 24, 10, tzinfo=UTC),
            ("18:24", "18:30"),
            5,
            dt(2026, 11, 1, 18, 30, tzinfo=UTC),
            id="outside-window-next-slot",
        ),
        pytest.param(dt(2026, 11, 1, 18, 24, tzinfo=UTC), ("bad",), 5, None, id="invalid-only"),
    ],
)
def test_proxy_schedule_attempt_to_follow(
    base_time: dt,
    slots_utc: tuple[str, ...],
    poll_delay_seconds: int,
    expected: dt | None,
) -> None:
    """Follow attempt prefers latest in-window slot, otherwise the next future slot."""
    assert Fetcher._attempt_to_follow_from_proxy_schedule(base_time, "2026-11-01", slots_utc, poll_delay_seconds) == expected


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

    assert (
        await solcast.fetcher._apply_proxy_resource_headers(
            {
                "x-proxy-upstream-status": "200",
                "x-proxy-next-attempt-at": "2026-11-02T23:55:00+00:00",
                "x-proxy-halted": "false",
                "x-proxy-fetch-in-progress": "false",
                "x-proxy-last-fetch-status": "clean_success",
            },
            path=ESTIMATED_ACTUALS,
        )
        is True
    )

    assert solcast.proxy_mode is True
    assert solcast.proxy_next_attempt_at == next_attempt
    assert solcast.proxy_upstream_status == 429
    assert solcast.proxy_halted is True
    assert solcast.proxy_fetch_in_progress is True
    assert solcast.proxy_last_fetch_status == "retrying"


async def test_forecast_headers_fallback_to_cron_when_retry_time_missing(solcast: SolcastApi) -> None:
    """Forecast header parsing derives next attempt from cron when retry timestamp is absent."""
    now = dt(2026, 11, 1, 9, 6, tzinfo=UTC)
    cron = "*/10 * * * *"
    solcast.proxy_forecast_cron = cron
    expected_next = next(CronSim(cron, now))

    with patch.object(solcast.dt_helper, "real_now_utc", return_value=now):
        assert (
            await solcast.fetcher._apply_proxy_resource_headers(
                {
                    "x-proxy-upstream-status": "200",
                    "x-proxy-next-attempt-at": "",
                    "x-proxy-halted": "false",
                    "x-proxy-fetch-in-progress": "false",
                    "x-proxy-last-fetch-status": "clean_success",
                }
            )
            is True
        )

    assert solcast.proxy_next_attempt_at == expected_next


async def test_forecast_headers_trigger_immediate_proxy_follow_reschedule(solcast: SolcastApi) -> None:
    """Forecast headers should immediately trigger proxy follow rescheduling."""
    callback = AsyncMock()
    solcast.proxy_follow_reschedule = callback

    assert (
        await solcast.fetcher._apply_proxy_resource_headers(
            {
                "x-proxy-upstream-status": "200",
                "x-proxy-next-attempt-at": "2026-11-01T09:10:00+00:00",
                "x-proxy-halted": "false",
                "x-proxy-fetch-in-progress": "false",
                "x-proxy-last-fetch-status": "clean_success",
            }
        )
        is True
    )

    callback.assert_awaited_once()


async def test_actuals_headers_do_not_trigger_proxy_follow_reschedule(solcast: SolcastApi) -> None:
    """Estimated-actuals headers must not trigger forecast follow rescheduling."""
    callback = AsyncMock()
    solcast.proxy_follow_reschedule = callback

    assert (
        await solcast.fetcher._apply_proxy_resource_headers(
            {
                "x-proxy-upstream-status": "200",
                "x-proxy-next-attempt-at": "2026-11-01T09:10:00+00:00",
                "x-proxy-halted": "false",
                "x-proxy-fetch-in-progress": "false",
                "x-proxy-last-fetch-status": "clean_success",
            },
            path=ESTIMATED_ACTUALS,
        )
        is True
    )

    callback.assert_not_awaited()


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
    assert solcast.entry is not None, "An entry is required for this test"
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
    assert solcast.entry is not None, "An entry is required for this test"
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
    ("cron", "expected", "expected_update_calls"),
    [
        pytest.param(" 55 23 * * * ", "55 23 * * *", 0, id="trimmed"),
        pytest.param("   ", None, 1, id="empty"),
        pytest.param(None, None, 1, id="removed"),
    ],
)
async def test_proxy_actuals_cron_persists_once(
    solcast: SolcastApi,
    cron: str | None,
    expected: str | None,
    expected_update_calls: int,
) -> None:
    """Persist normalized actuals cron changes without rewriting unchanged state."""
    assert solcast.entry is not None, "An entry is required for this test"
    await solcast.async_set_proxy_actuals_cron("55 23 * * *")
    with patch.object(solcast.hass.config_entries, "async_update_entry", wraps=solcast.hass.config_entries.async_update_entry) as update:
        await solcast.async_set_proxy_actuals_cron(cron, source="test")

        assert solcast.proxy_actuals_cron == expected
        assert solcast.entry.options[PROXY_ACTUALS_CRON] == expected
        assert solcast.entry_options[PROXY_ACTUALS_CRON] == expected
        assert update.call_count == expected_update_calls

        await solcast.async_set_proxy_actuals_cron(cron, source="test")

        assert update.call_count == expected_update_calls


@pytest.mark.parametrize(
    ("headers", "initial_proxy_mode", "expected_mode", "expected_delay", "expected_cron", "expected_actuals_cron"),
    [
        pytest.param(
            {
                "x-solcast-proxy": "true",
                "x-proxy-poll-delay-seconds": "9",
                "x-proxy-forecast-cron": "*/10 * * * *",
                "x-proxy-estimated-actuals-cron": "55 23 * * *",
            },
            False,
            True,
            9,
            "*/10 * * * *",
            "55 23 * * *",
            id="proxy-discovery",
        ),
        pytest.param(
            {"x-solcast-proxy": "true", "x-proxy-poll-delay-seconds": "invalid"},
            False,
            True,
            5,
            None,
            None,
            id="invalid-delay",
        ),
        pytest.param({"x-solcast-proxy": "TRUE"}, False, True, 5, None, None, id="optional-headers-absent"),
        pytest.param({}, True, False, 5, None, None, id="direct-discovery"),
    ],
)
async def test_discovery_persists_proxy_headers(
    solcast: SolcastApi,
    headers: dict[str, str],
    initial_proxy_mode: bool,
    expected_mode: bool,
    expected_delay: int,
    expected_cron: str | None,
    expected_actuals_cron: str | None,
) -> None:
    """Discovery updates persistent proxy state and the sites cache metadata."""
    assert solcast.entry is not None, "An entry is required for this test"
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
    assert solcast.proxy_actuals_cron == expected_actuals_cron
    assert solcast.entry.options[PROXY_MODE] is expected_mode
    assert solcast.entry.options[PROXY_POLL_DELAY_SECONDS] == expected_delay
    assert solcast.entry.options.get(PROXY_FORECAST_CRON) == expected_cron
    assert solcast.entry.options.get(PROXY_ACTUALS_CRON) == expected_actuals_cron
    assert solcast.proxy_saved_auto_update == int(solcast.options.auto_update)
    assert solcast.entry.options.get(PROXY_SAVED_AUTO_UPDATE) == solcast.proxy_saved_auto_update

    cache_path = solcast.sites_cache._get_sites_cache_filename(solcast.options.api_key)
    cache = json.loads(Path(cache_path).read_text(encoding="utf-8"))
    assert cache[PROXY_CACHE_STATE] == {
        PROXY_MODE: expected_mode,
        PROXY_POLL_DELAY_SECONDS: expected_delay,
        PROXY_FORECAST_CRON: expected_cron,
        PROXY_ACTUALS_CRON: expected_actuals_cron,
    }


async def test_discovery_schedule_headers_persist_proxy_slots(solcast: SolcastApi) -> None:
    """Discovery schedule headers should persist cleaned slot metadata to cache."""
    payload = {SITES: solcast.sites, TOTAL_RECORDS: len(solcast.sites)}
    response = MagicMock(
        status=200,
        headers={
            "x-solcast-proxy": "true",
            "x-proxy-poll-delay-seconds": "9",
            "x-proxy-schedule-day-utc": "2026-11-10",
            "x-proxy-forecast-times-utc": "10:00, invalid,10:00,10:15",
            "x-proxy-estimated-actuals-times-utc": ["13:13", "bad", "13:13"],
        },
    )
    response.text = AsyncMock(return_value=json.dumps(payload))

    session = MagicMock()
    session.get = AsyncMock(return_value=response)
    with patch.object(solcast, "aiohttp_session", session):
        status, _, _ = await solcast.sites_cache._sites_data(use_cache=False)

    assert status == 200
    assert solcast.proxy_mode is True
    assert solcast.proxy_forecast_cron is None
    assert solcast.proxy_actuals_cron is None
    assert solcast.proxy_schedule_day_utc == "2026-11-10"
    assert solcast.proxy_forecast_times_utc == ("10:00", "10:15")
    assert solcast.proxy_actuals_times_utc == ("13:13",)

    cache_path = solcast.sites_cache._get_sites_cache_filename(solcast.options.api_key)
    cache = json.loads(Path(cache_path).read_text(encoding="utf-8"))
    assert cache[PROXY_CACHE_STATE] == {
        PROXY_MODE: True,
        PROXY_POLL_DELAY_SECONDS: 9,
        PROXY_FORECAST_CRON: None,
        PROXY_ACTUALS_CRON: None,
        PROXY_SCHEDULE_DAY_UTC: "2026-11-10",
        PROXY_FORECAST_TIMES_UTC: ["10:00", "10:15"],
        PROXY_ACTUALS_TIMES_UTC: ["13:13"],
    }


async def test_discovery_schedule_headers_ignore_invalid_slot_types_and_empty_tokens(solcast: SolcastApi) -> None:
    """Non-list/non-string slot metadata and empty comma tokens are ignored safely."""
    payload = {SITES: solcast.sites, TOTAL_RECORDS: len(solcast.sites)}
    response = MagicMock(
        status=200,
        headers={
            "x-solcast-proxy": "true",
            "x-proxy-poll-delay-seconds": "9",
            "x-proxy-schedule-day-utc": "2026-11-10",
            "x-proxy-forecast-times-utc": 123,
            "x-proxy-estimated-actuals-times-utc": "13:13, ,13:13",
        },
    )
    response.text = AsyncMock(return_value=json.dumps(payload))

    session = MagicMock()
    session.get = AsyncMock(return_value=response)
    with patch.object(solcast, "aiohttp_session", session):
        status, _, _ = await solcast.sites_cache._sites_data(use_cache=False)

    assert status == 200
    assert solcast.proxy_schedule_day_utc == "2026-11-10"
    assert solcast.proxy_forecast_times_utc == ()
    assert solcast.proxy_actuals_times_utc == ("13:13",)
