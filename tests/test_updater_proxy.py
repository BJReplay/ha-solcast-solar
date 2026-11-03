"""Proxy-mode scheduling tests for updater."""

from __future__ import annotations

from datetime import UTC, datetime as dt, timedelta, timezone, tzinfo
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, call
from zoneinfo import ZoneInfo

from custom_components.solcast_solar.const import (
    ADVANCED_AUTOMATED_DAMPENING_GENERATION_FETCH_DELAY,
    ADVANCED_ESTIMATED_ACTUALS_FETCH_DELAY,
    TASK_FORECASTS_FETCH,
)
from custom_components.solcast_solar.enums import AutoUpdate
from custom_components.solcast_solar.updater import Updater
import pytest


def _make_updater(
    proxy_mode: bool, proxy_forecast_cron: str | None = None, proxy_actuals_cron: str | None = None, tz: tzinfo = UTC
) -> tuple[Updater, Any]:
    """Create an Updater with lightweight coordinator/solcast stubs."""

    scheduled: list[tuple[object, object]] = []

    def fake_track_point_in_utc_time(_hass: object, callback: object, when: object) -> object:
        scheduled.append((callback, when))
        return lambda: None

    class _DateHelper:
        @staticmethod
        def real_now_utc() -> dt:
            return dt(2026, 11, 1, 18, 24, 0, tzinfo=UTC)

        @staticmethod
        def day_start_utc() -> dt:
            return dt(2026, 11, 1, 0, 0, 0, tzinfo=UTC)

    solcast = SimpleNamespace(
        proxy_mode=proxy_mode,
        proxy_halted=False,
        proxy_next_attempt_at=None,
        proxy_poll_delay_seconds=5,
        proxy_forecast_cron=proxy_forecast_cron,
        proxy_actuals_cron=proxy_actuals_cron,
        tasks={},
        options=SimpleNamespace(auto_update=AutoUpdate.ALL_DAY, tz=tz, get_actuals=False, auto_dampen=False, generation_entities=[]),
        fetcher=SimpleNamespace(set_next_update=lambda _x: None),
        dt_helper=_DateHelper(),
        failures_last_24h=0,
        failures_last_7d=0,
        failures_last_14d=0,
        last_attempt=dt(2026, 11, 1, 18, 0, 0, tzinfo=UTC),
        sites=[],
        api_typical=0,
        api_used=0,
        api_forced=0,
        api_limit=10,
        advanced_options={ADVANCED_ESTIMATED_ACTUALS_FETCH_DELAY: 0, ADVANCED_AUTOMATED_DAMPENING_GENERATION_FETCH_DELAY: 0},
    )
    coordinator = SimpleNamespace(
        solcast=solcast,
        hass=SimpleNamespace(),
        tasks={},
    )

    updater = Updater(coordinator)  # pyright: ignore[reportArgumentType]
    updater._intervals = [dt(2026, 11, 1, 20, 0, 0, tzinfo=UTC)]
    updater._test_scheduled = scheduled

    return updater, fake_track_point_in_utc_time


@pytest.mark.asyncio
async def test_update_setup_skips_local_intervals_when_proxy_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proxy mode should not assemble or keep local sunrise/all-day intervals."""

    updater, _ = _make_updater(proxy_mode=True)
    called: dict[str, bool] = {"calculated": False}

    def _mark_calculated(*_args: object, **_kwargs: object) -> None:
        called["calculated"] = True

    monkeypatch.setattr(updater, "_calculate_forecast_updates", _mark_calculated)

    updater.update_setup(init=True)

    assert updater._intervals == []
    assert called["calculated"] is False


@pytest.mark.asyncio
async def test_check_forecast_fetch_derives_schedule_from_proxy_cron(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proxy cron should bootstrap next-attempt scheduling when header timing is not yet known."""

    updater, fake_track = _make_updater(proxy_mode=True, proxy_forecast_cron="*/10 * * * *")
    monkeypatch.setattr("custom_components.solcast_solar.updater.async_track_point_in_utc_time", fake_track)

    await updater.check_forecast_fetch()

    assert updater._coordinator.solcast.proxy_next_attempt_at is not None
    assert updater._coordinator.solcast.proxy_next_attempt_at.minute == 30
    assert "pending_proxy_update" in updater._coordinator.tasks
    assert updater._test_scheduled[0][1] == dt(2026, 11, 1, 18, 30, 5, tzinfo=UTC)


@pytest.mark.parametrize(
    ("cron_expression", "base_time", "expected"),
    [
        pytest.param("*/10 * * * *", dt(2026, 11, 1, 18, 24, tzinfo=UTC), dt(2026, 11, 1, 18, 30, tzinfo=UTC), id="step"),
        pytest.param("*/10 * * * *", dt(2026, 11, 1, 18, 30, tzinfo=UTC), dt(2026, 11, 1, 18, 40, tzinfo=UTC), id="exclusive-boundary"),
        pytest.param(
            "*/10 * * * *", dt(2026, 11, 1, 18, 29, 59, 999999, tzinfo=UTC), dt(2026, 11, 1, 18, 30, tzinfo=UTC), id="fractional-second"
        ),
        pytest.param("55 2,7,12,17 * * *", dt(2026, 11, 1, 18, 24, tzinfo=UTC), dt(2026, 11, 2, 2, 55, tzinfo=UTC), id="list-next-day"),
        pytest.param("10-50/20 18-20 * * *", dt(2026, 11, 1, 18, 24, tzinfo=UTC), dt(2026, 11, 1, 18, 30, tzinfo=UTC), id="range-step"),
        pytest.param("0 9 * * MON", dt(2026, 11, 1, 18, 24, tzinfo=UTC), dt(2026, 11, 2, 9, tzinfo=UTC), id="weekday"),
        pytest.param("0 0 1 * *", dt(2026, 11, 1, 18, 24, tzinfo=UTC), dt(2026, 12, 1, tzinfo=UTC), id="monthly"),
        pytest.param("0 0 1 JAN *", dt(2026, 11, 1, 18, 24, tzinfo=UTC), dt(2027, 1, 1, tzinfo=UTC), id="yearly"),
        pytest.param("0 0 29 FEB *", dt(2026, 11, 1, 18, 24, tzinfo=UTC), dt(2028, 2, 29, tzinfo=UTC), id="leap-day"),
        pytest.param(
            "0 19 * * *", dt(2026, 11, 2, 5, 24, tzinfo=timezone(timedelta(hours=11))), dt(2026, 11, 1, 19, tzinfo=UTC), id="utc-schedule"
        ),
    ],
)
def test_next_from_proxy_cron(cron_expression: str, base_time: dt, expected: dt) -> None:
    """Cron fallback matches the proxy's UTC interpretation and excludes the base time."""
    updater, _ = _make_updater(proxy_mode=True)

    assert updater._next_from_proxy_cron(base_time, cron_expression) == expected


@pytest.mark.parametrize(
    "cron_expression",
    [
        pytest.param("", id="empty"),
        pytest.param("* * * *", id="missing-field"),
        pytest.param("* * * * * *", id="extra-field"),
        pytest.param("*/0 * * * *", id="zero-step"),
        pytest.param("60 * * * *", id="invalid-minute"),
        pytest.param("* 24 * * *", id="invalid-hour"),
        pytest.param("0 0 31 FEB *", id="impossible-date"),
    ],
)
async def test_invalid_proxy_cron_does_not_schedule(monkeypatch: pytest.MonkeyPatch, cron_expression: str) -> None:
    """Invalid cron metadata leaves the fallback unscheduled rather than raising."""
    updater, fake_track = _make_updater(proxy_mode=True, proxy_forecast_cron=cron_expression)
    monkeypatch.setattr("custom_components.solcast_solar.updater.async_track_point_in_utc_time", fake_track)

    await updater.check_forecast_fetch()

    assert updater._coordinator.solcast.proxy_next_attempt_at is None
    assert updater._test_scheduled == []


async def test_proxy_header_timestamp_takes_precedence_over_cron(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cron fallback never replaces the retry timestamp supplied by the proxy."""
    updater, fake_track = _make_updater(proxy_mode=True, proxy_forecast_cron="*/10 * * * *")
    monkeypatch.setattr("custom_components.solcast_solar.updater.async_track_point_in_utc_time", fake_track)
    next_attempt = dt(2026, 11, 1, 18, 24, 29, tzinfo=UTC)
    updater._coordinator.solcast.proxy_next_attempt_at = next_attempt

    await updater.check_forecast_fetch()

    assert updater._coordinator.solcast.proxy_next_attempt_at == next_attempt
    assert updater._test_scheduled[0][1] == next_attempt + timedelta(seconds=5)


@pytest.mark.parametrize(
    ("next_attempt", "expected"),
    [
        pytest.param(dt(2026, 11, 1, 18, 24, 29, tzinfo=UTC), dt(2026, 11, 1, 18, 24, 34, tzinfo=UTC), id="retry"),
        pytest.param(dt(2026, 11, 1, 18, 23, 29, tzinfo=UTC), dt(2026, 11, 1, 18, 24, 5, tzinfo=UTC), id="overdue"),
    ],
)
async def test_proxy_follow_schedules_exact_time(monkeypatch: pytest.MonkeyPatch, next_attempt: dt, expected: dt) -> None:
    """Short retry timestamps are scheduled without waiting for five-minute checks."""
    updater, fake_track = _make_updater(proxy_mode=True)
    monkeypatch.setattr("custom_components.solcast_solar.updater.async_track_point_in_utc_time", fake_track)
    updater._coordinator.solcast.proxy_next_attempt_at = next_attempt

    await updater.check_forecast_fetch()

    assert updater._test_scheduled[0][1] == expected


async def test_proxy_follow_does_not_overlap_active_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """No follow callback is queued while the consolidated fetcher owns retries."""
    updater, fake_track = _make_updater(proxy_mode=True)
    monkeypatch.setattr("custom_components.solcast_solar.updater.async_track_point_in_utc_time", fake_track)
    updater._coordinator.solcast.proxy_next_attempt_at = dt(2026, 11, 1, 18, 24, 29, tzinfo=UTC)
    updater._coordinator.solcast.tasks[TASK_FORECASTS_FETCH] = object()

    await updater.check_forecast_fetch()

    assert updater._test_scheduled == []


@pytest.mark.parametrize(
    ("actuals_cron", "expected"),
    [
        pytest.param("55 23 * * *", dt(2026, 11, 1, 23, 55, 5, tzinfo=UTC), id="upcoming"),
        pytest.param("30 18 * * *", dt(2026, 11, 1, 18, 30, 5, tzinfo=UTC), id="just-ahead"),
    ],
)
async def test_proxy_actuals_follow_cron(monkeypatch: pytest.MonkeyPatch, actuals_cron: str, expected: dt) -> None:
    """Estimated actuals are collected at the proxy's actuals cron plus the poll offset."""
    updater, fake_track = _make_updater(proxy_mode=True, proxy_actuals_cron=actuals_cron)
    monkeypatch.setattr("custom_components.solcast_solar.updater.async_track_point_in_utc_time", fake_track)
    monkeypatch.setattr("custom_components.solcast_solar.updater.sync_actuals_quota_risk_issue", lambda *args, **kwargs: None)
    updater._coordinator.solcast.options.get_actuals = True
    updater._coordinator.solcast.estimated_actuals_updated_today = False

    assert await updater.check_estimated_actuals_fetch() is True

    assert "new_day_actuals" in updater._coordinator.tasks
    assert [when for _, when in updater._test_scheduled] == [expected]


async def test_proxy_actuals_missed_cron_schedules_promptly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Starting after today's proxy collection fetches its cached actuals shortly rather than waiting a day."""
    updater, fake_track = _make_updater(proxy_mode=True, proxy_actuals_cron="0 1 * * *")
    monkeypatch.setattr("custom_components.solcast_solar.updater.async_track_point_in_utc_time", fake_track)
    monkeypatch.setattr("custom_components.solcast_solar.updater.sync_actuals_quota_risk_issue", lambda *args, **kwargs: None)
    updater._coordinator.solcast.options.get_actuals = True
    updater._coordinator.solcast.estimated_actuals_updated_today = False

    assert await updater.check_estimated_actuals_fetch() is True

    now = dt(2026, 11, 1, 18, 24, 0, tzinfo=UTC)
    [(_, when)] = updater._test_scheduled
    assert now + timedelta(seconds=30) <= when <= now + timedelta(seconds=59)


@pytest.mark.parametrize("actuals_cron", [pytest.param(None, id="not-advertised"), pytest.param("* * *", id="invalid")])
async def test_proxy_actuals_without_usable_cron_uses_local_schedule(monkeypatch: pytest.MonkeyPatch, actuals_cron: str | None) -> None:
    """A proxy that advertises no usable actuals cron leaves the local midnight schedule in place."""
    updater, fake_track = _make_updater(proxy_mode=True, proxy_actuals_cron=actuals_cron)
    monkeypatch.setattr("custom_components.solcast_solar.updater.async_track_point_in_utc_time", fake_track)
    monkeypatch.setattr("custom_components.solcast_solar.updater.sync_actuals_quota_risk_issue", lambda *args, **kwargs: None)
    local = Mock(return_value=dt(2026, 11, 2, 0, 5, tzinfo=UTC))
    monkeypatch.setattr(updater, "_local_actuals_update_at", local)
    updater._coordinator.solcast.options.get_actuals = True
    updater._coordinator.solcast.estimated_actuals_updated_today = False

    assert await updater.check_estimated_actuals_fetch() is True

    local.assert_called_once()
    assert [when for _, when in updater._test_scheduled] == [dt(2026, 11, 2, 0, 5, tzinfo=UTC)]


async def test_proxy_actuals_validation_runs_when_today_already_updated(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Startup still validates proxy actuals cron even when no actuals fetch is scheduled today."""
    updater, _ = _make_updater(proxy_mode=True, proxy_actuals_cron="30 13 * * *", tz=ZoneInfo("Australia/Sydney"))
    monkeypatch.setattr("custom_components.solcast_solar.updater.sync_actuals_quota_risk_issue", lambda *args, **kwargs: None)
    solcast = updater._coordinator.solcast
    solcast.options.get_actuals = True
    solcast.estimated_actuals_updated_today = True

    assert await updater.check_estimated_actuals_fetch() is False

    errors = [record for record in caplog.records if record.levelname == "ERROR"]
    assert len(errors) == 1
    assert "estimated actuals schedule" in errors[0].getMessage()


@pytest.mark.parametrize(
    ("zone", "cron", "flagged"),
    [
        pytest.param("UTC", "55 23 * * *", True, id="utc-late-evening"),
        pytest.param("Australia/Sydney", "55 23 * * *", True, id="sydney-late-morning"),
        pytest.param("America/New_York", "55 23 * * *", True, id="new-york-evening"),
        pytest.param("Australia/Sydney", "30 13 * * *", True, id="sydney-00:30-in-summer"),
        pytest.param("Australia/Sydney", "0 14 * * *", False, id="sydney-midnight-in-winter"),
        pytest.param("Australia/Brisbane", "0 14 * * *", False, id="brisbane-midnight-no-dst"),
        pytest.param("Australia/Brisbane", "59 13 * * *", True, id="brisbane-late-evening-no-dst"),
        pytest.param("Europe/London", "30 23 * * *", True, id="london-00:30-in-summer"),
        pytest.param("UTC", "* * * * *", False, id="every-minute-no-dst"),
        pytest.param("Australia/Sydney", "* * * * *", False, id="every-minute-dst"),
        pytest.param("UTC", "0 9 * * MON", True, id="weekly-skips-days"),
    ],
)
async def test_proxy_actuals_cron_suitability(caplog: pytest.LogCaptureFixture, zone: str, cron: str, flagged: bool) -> None:
    """An unsuitable proxy actuals cron is reported once at ERROR level and is still followed."""
    updater, _ = _make_updater(proxy_mode=True, proxy_actuals_cron=cron, tz=ZoneInfo(zone))

    assert updater._proxy_actuals_update_at() is not None
    assert updater._proxy_actuals_update_at() is not None

    errors = [record for record in caplog.records if record.levelname == "ERROR"]
    assert len(errors) == int(flagged)


@pytest.mark.parametrize(
    ("cron", "delay", "dampening", "flagged"),
    [
        pytest.param("0 0 * * *", 0, True, True, id="same-minute-as-generation"),
        pytest.param("0 0 * * *", 0, False, False, id="no-dampening"),
        pytest.param("1 0 * * *", 0, True, False, id="minute-after-generation"),
        pytest.param("30 0 * * *", 60, True, True, id="before-delayed-generation"),
        pytest.param("5 1 * * *", 60, True, False, id="after-delayed-generation"),
    ],
)
async def test_proxy_actuals_cron_after_generation(
    caplog: pytest.LogCaptureFixture, cron: str, delay: int, dampening: bool, flagged: bool
) -> None:
    """A proxy actuals cron that fires before generation data is fetched is reported at ERROR level."""
    updater, _ = _make_updater(proxy_mode=True, proxy_actuals_cron=cron)
    solcast = updater._coordinator.solcast
    solcast.options.auto_dampen = dampening
    solcast.options.generation_entities = ["sensor.pv_generation"] if dampening else []
    solcast.advanced_options[ADVANCED_AUTOMATED_DAMPENING_GENERATION_FETCH_DELAY] = delay

    assert updater._proxy_actuals_update_at() is not None

    errors = [record.getMessage() for record in caplog.records if record.levelname == "ERROR"]
    assert ["generation data fetch" in message for message in errors] == [True] * int(flagged)


async def test_forecast_update_rechecks_proxy_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    """A completed forecast update re-evaluates the proxy follow schedule."""
    updater, _ = _make_updater(proxy_mode=True)
    coordinator = updater._coordinator
    coordinator.solcast.sites_cache = SimpleNamespace(stale_usage_cache=False)
    coordinator.solcast.fetcher.get_forecast_update = AsyncMock()
    coordinator.update_integration_listeners = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()
    check = AsyncMock()
    monkeypatch.setattr(updater, "_check_proxy_forecast_fetch", check)

    await updater.forecast_update()

    check.assert_awaited_once()


async def test_proxy_follow_reschedules_changed_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    """A newly advertised retry replaces the previous follow event."""
    updater, fake_track = _make_updater(proxy_mode=True)
    monkeypatch.setattr("custom_components.solcast_solar.updater.async_track_point_in_utc_time", fake_track)
    updater._coordinator.solcast.proxy_next_attempt_at = dt(2026, 11, 1, 18, 24, 29, tzinfo=UTC)
    await updater.check_forecast_fetch()

    updater._coordinator.solcast.proxy_next_attempt_at += timedelta(seconds=44)
    await updater.check_forecast_fetch()

    assert updater._proxy_scheduled_for == dt(2026, 11, 1, 18, 25, 18, tzinfo=UTC)
    assert len(updater._test_scheduled) == 2


@pytest.mark.parametrize("pending", [pytest.param(False, id="no-event"), pytest.param(True, id="pending-event")])
async def test_halted_proxy_cancels_follow_event(pending: bool) -> None:
    """A halted proxy clears scheduling and the displayed next update."""
    updater, _ = _make_updater(proxy_mode=True)
    cancel = Mock()
    updater._coordinator.tasks = {"pending_proxy_update": cancel} if pending else {}
    updater._proxy_scheduled_for = dt(2026, 11, 1, 18, 30, tzinfo=UTC)
    updater._coordinator.solcast.proxy_halted = True
    updater._coordinator.solcast.fetcher.set_next_update = Mock()

    await updater.check_forecast_fetch()

    assert cancel.call_count == int(pending)
    assert updater._coordinator.tasks == {}
    assert updater._proxy_scheduled_for is None
    assert updater._test_scheduled == []
    updater._coordinator.solcast.fetcher.set_next_update.assert_called_once_with(None)


@pytest.mark.parametrize("active_fetch", [pytest.param(False, id="fetch"), pytest.param(True, id="already-fetching")])
async def test_proxy_follow_callback_clears_event_and_avoids_overlap(monkeypatch: pytest.MonkeyPatch, active_fetch: bool) -> None:
    """A fired follow callback relinquishes its event before starting a fetch."""
    updater, fake_track = _make_updater(proxy_mode=True)
    monkeypatch.setattr("custom_components.solcast_solar.updater.async_track_point_in_utc_time", fake_track)
    updater._coordinator.solcast.proxy_next_attempt_at = dt(2026, 11, 1, 18, 30, tzinfo=UTC)
    await updater.check_forecast_fetch()
    updater._coordinator.solcast.tasks = {TASK_FORECASTS_FETCH: object()} if active_fetch else {}
    fetch = AsyncMock()
    monkeypatch.setattr(updater, "forecast_update", fetch)

    await updater._fetch_proxy()

    assert "pending_proxy_update" not in updater._coordinator.tasks
    assert updater._proxy_scheduled_for is None
    assert fetch.await_count == int(not active_fetch)
    assert fetch.await_args_list == [call(completion="Completed task pending_proxy_update")] * int(not active_fetch)
