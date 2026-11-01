"""Proxy-mode scheduling tests for updater."""

from __future__ import annotations

from datetime import UTC, datetime as dt, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from custom_components.solcast_solar.const import TASK_FORECASTS_FETCH
from custom_components.solcast_solar.enums import AutoUpdate
from custom_components.solcast_solar.updater import Updater
import pytest


def _make_updater(proxy_mode: bool, proxy_forecast_cron: str | None = None) -> tuple[Updater, Any]:
    """Create an Updater with lightweight coordinator/solcast stubs."""

    scheduled: list[tuple[object, object]] = []

    def fake_track_point_in_utc_time(_hass: object, callback: object, when: object) -> object:
        scheduled.append((callback, when))
        return lambda: None

    class _DateHelper:
        @staticmethod
        def real_now_utc() -> dt:
            return dt(2026, 11, 1, 18, 24, 0, tzinfo=UTC)

    solcast = SimpleNamespace(
        proxy_mode=proxy_mode,
        proxy_halted=False,
        proxy_next_attempt_at=None,
        proxy_poll_delay_seconds=5,
        proxy_forecast_cron=proxy_forecast_cron,
        tasks={},
        options=SimpleNamespace(auto_update=AutoUpdate.ALL_DAY, tz=UTC),
        fetcher=SimpleNamespace(set_next_update=lambda _x: None),
        dt_helper=_DateHelper(),
        failures_last_24h=0,
        failures_last_7d=0,
        failures_last_14d=0,
        last_attempt=dt(2026, 11, 1, 18, 0, 0, tzinfo=UTC),
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
        pytest.param("*/10 * * * *", dt(2026, 11, 1, 18, 29, 59, 999999, tzinfo=UTC), dt(2026, 11, 1, 18, 30, tzinfo=UTC), id="fractional-second"),
        pytest.param("55 2,7,12,17 * * *", dt(2026, 11, 1, 18, 24, tzinfo=UTC), dt(2026, 11, 2, 2, 55, tzinfo=UTC), id="list-next-day"),
        pytest.param("10-50/20 18-20 * * *", dt(2026, 11, 1, 18, 24, tzinfo=UTC), dt(2026, 11, 1, 18, 30, tzinfo=UTC), id="range-step"),
        pytest.param("0 9 * * MON", dt(2026, 11, 1, 18, 24, tzinfo=UTC), dt(2026, 11, 2, 9, tzinfo=UTC), id="weekday"),
        pytest.param("0 0 1 * *", dt(2026, 11, 1, 18, 24, tzinfo=UTC), dt(2026, 12, 1, tzinfo=UTC), id="monthly"),
        pytest.param("0 0 1 JAN *", dt(2026, 11, 1, 18, 24, tzinfo=UTC), dt(2027, 1, 1, tzinfo=UTC), id="yearly"),
        pytest.param("0 0 29 FEB *", dt(2026, 11, 1, 18, 24, tzinfo=UTC), dt(2028, 2, 29, tzinfo=UTC), id="leap-day"),
        pytest.param("0 19 * * *", dt(2026, 11, 2, 5, 24, tzinfo=timezone(timedelta(hours=11))), dt(2026, 11, 1, 19, tzinfo=UTC), id="utc-schedule"),
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
async def test_invalid_proxy_cron_does_not_schedule(
    monkeypatch: pytest.MonkeyPatch, cron_expression: str
) -> None:
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
async def test_proxy_follow_schedules_exact_time(
    monkeypatch: pytest.MonkeyPatch, next_attempt: dt, expected: dt
) -> None:
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
