"""Tests for the auto-update schedule at local midnight.

At local midnight the five-minute update check (``Updater.check_forecast_fetch``) and the daily rebuild of the
update schedule (``SolcastUpdateCoordinator._update_integration_listeners``) fire on the same tick, in no defined
order. The update scheduled for local midnight must be dispatched exactly once whichever runs first, and an update
must only ever remove its own slot from the schedule.
"""

import asyncio
from collections.abc import Awaitable, Callable
import copy
from datetime import datetime as dt, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar.const import (
    API_LIMIT,
    AUTO_UPDATE,
    AUTO_UPDATE_QUEUE,
    LAST_UPDATED,
    TASK_CHECK_FETCH,
    TASK_FORECASTS_FETCH,
    TASK_LISTENERS,
    TASK_MIDNIGHT_UPDATE,
)
from homeassistant.components.solcast_solar.coordinator import SolcastUpdateCoordinator
from homeassistant.components.solcast_solar.enums import UpdateOutcome, UpdateResult
from homeassistant.components.solcast_solar.updater import Updater
from homeassistant.core import HomeAssistant

from . import DEFAULT_INPUT1, async_cleanup_integration_tests, async_init_integration

from tests.common import async_fire_time_changed

SYDNEY = "Australia/Sydney"
SLOTS_PER_DAY = 10


@pytest.fixture(autouse=True)
def frozen_time() -> None:
    """Override autouse fixture for this module.

    Time is moved explicitly to either side of local midnight.
    """
    return


async def _init(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    timezone: str,
    before: str,
    now: str,
) -> tuple[SolcastUpdateCoordinator, Updater]:
    """Set up an all-day schedule, then move to the instant under test.

    The five-minute and UTC midnight trackers are cancelled so that the tests call their callbacks in an explicit order.
    """

    freezer.move_to(before)
    options = copy.deepcopy(DEFAULT_INPUT1)
    options[AUTO_UPDATE] = 2
    options[API_LIMIT] = "20"
    entry = await async_init_integration(hass, options, timezone=timezone)
    coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator
    updater = coordinator.updater
    assert updater.divisions == SLOTS_PER_DAY, "Test expects ten updates per day"
    for task in (TASK_CHECK_FETCH, TASK_LISTENERS, TASK_MIDNIGHT_UPDATE):
        coordinator.tasks.pop(task)()
    freezer.move_to(now)
    return coordinator, updater


def _queue(updater: Updater) -> list[dt]:
    return list(updater.get_auto_update_details()[AUTO_UPDATE_QUEUE])


def _slot(tz: str, day: str, index: int) -> dt:
    """Return the nominal local update slot for a local day: the day is split evenly into ten from local midnight."""

    zone = ZoneInfo(tz)
    start = dt.fromisoformat(day).replace(tzinfo=zone).astimezone(ZoneInfo("UTC"))
    end = (dt.fromisoformat(day) + timedelta(days=1)).replace(tzinfo=zone).astimezone(ZoneInfo("UTC"))
    return (start + (end - start) / SLOTS_PER_DAY * index).astimezone(zone).replace(microsecond=0)


async def _fire(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float = 1.0) -> None:
    """Move on and let any due timer run."""

    freezer.tick(seconds)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def _rebuild(coordinator: SolcastUpdateCoordinator) -> None:
    """Run the daily rebuild of the update schedule, as triggered by the five-minute tick."""

    await coordinator._update_integration_listeners()  # pyright: ignore[reportPrivateUsage]


ORDERINGS: dict[str, tuple[str, ...]] = {
    "rebuild_check_dispatch": ("rebuild", "check", "dispatch"),
    "check_dispatch_rebuild": ("check", "dispatch", "rebuild"),
    "check_rebuild_dispatch": ("check", "rebuild", "dispatch"),
}


@pytest.mark.parametrize("ordering", ORDERINGS.values(), ids=ORDERINGS.keys())
async def test_midnight_update_callback_orderings(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    ordering: tuple[str, ...],
) -> None:
    """Test that the local midnight update is dispatched once, and only its own slot is consumed, in every callback order."""

    try:
        coordinator, updater = await _init(
            hass,
            freezer,
            SYDNEY,
            "2026-10-19 12:50:00+00:00",
            "2026-10-19 13:00:00+00:00",
        )
        midnight = _slot(SYDNEY, "2026-10-20", 0)
        next_slot = _slot(SYDNEY, "2026-10-20", 1)
        assert midnight.isoformat() == "2026-10-20T00:00:00+11:00"
        assert next_slot.isoformat() == "2026-10-20T02:24:00+11:00"
        assert midnight in _queue(updater)  # Not rebuilt yet, so the midnight slot is still queued from yesterday's schedule

        steps: dict[str, Callable[[], Awaitable[None]]] = {
            "rebuild": lambda: _rebuild(coordinator),
            "check": updater.check_forecast_fetch,
            "dispatch": lambda: _fire(hass, freezer),
        }
        with patch.object(updater, "forecast_update", new=AsyncMock()) as forecast_update:
            for step in ordering:
                await steps[step]()
            await hass.async_block_till_done(wait_background_tasks=True)

            assert forecast_update.await_count == 1, f"Midnight update must be dispatched exactly once for {ordering}"
            # The queue holds the next slot, whichever order things happened in
            queue = _queue(updater)
            assert midnight not in queue
            assert queue[0] == next_slot

            # A later tick, and a repeated check, must neither dispatch again nor consume another slot
            freezer.move_to("2026-10-19 13:05:00+00:00")
            await updater.check_forecast_fetch()
            await updater.check_forecast_fetch()
            await _fire(hass, freezer)
            assert forecast_update.await_count == 1
            assert _queue(updater)[0] == next_slot
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_repeated_check_in_window_dispatches_once(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that checking the same five-minute window repeatedly arms a slot only once."""

    try:
        slot = _slot(SYDNEY, "2026-10-20", 1)  # 02:24 AEDT is 15:24 UTC the day before
        _, updater = await _init(
            hass,
            freezer,
            SYDNEY,
            "2026-10-19 15:00:00+00:00",
            "2026-10-19 15:21:30+00:00",
        )
        assert slot in _queue(updater)
        with patch.object(updater, "forecast_update", new=AsyncMock()) as forecast_update:
            for _ in range(3):
                await updater.check_forecast_fetch()
            await _fire(hass, freezer, 151)
            await hass.async_block_till_done(wait_background_tasks=True)
            assert forecast_update.await_count == 1
            assert slot not in _queue(updater)
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_midnight_update_when_check_is_late(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that a check that runs a few seconds after the tick still dispatches the slot due in its window."""

    try:
        coordinator, updater = await _init(
            hass,
            freezer,
            SYDNEY,
            "2026-10-19 12:50:00+00:00",
            "2026-10-19 13:00:00+00:00",
        )
        with patch.object(updater, "forecast_update", new=AsyncMock()) as forecast_update:
            await _rebuild(coordinator)
            freezer.tick(3)  # Rebuild took a while, so the check starts late
            await updater.check_forecast_fetch()
            await _fire(hass, freezer)
            await hass.async_block_till_done(wait_background_tasks=True)
            assert forecast_update.await_count == 1
            assert _queue(updater)[0] == _slot(SYDNEY, "2026-10-20", 1)
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_delayed_fetch_does_not_consume_next_slot(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that a slow fetch still in flight when the schedule is rebuilt and the next tick arrives consumes nothing more."""

    try:
        coordinator, updater = await _init(
            hass,
            freezer,
            SYDNEY,
            "2026-10-19 12:50:00+00:00",
            "2026-10-19 13:00:00+00:00",
        )
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_update(*_args: object, **_kwargs: object) -> None:
            started.set()
            await release.wait()

        with patch.object(updater, "forecast_update", new=AsyncMock(side_effect=slow_update)) as forecast_update:
            await updater.check_forecast_fetch()
            freezer.tick(1)
            async_fire_time_changed(hass)
            async with asyncio.timeout(5):
                await started.wait()
            assert forecast_update.await_count == 1  # In flight, blocked
            await _rebuild(coordinator)
            freezer.move_to("2026-10-19 13:05:00+00:00")
            await updater.check_forecast_fetch()
            assert forecast_update.await_count == 1
            release.set()
            await hass.async_block_till_done(wait_background_tasks=True)
            assert forecast_update.await_count == 1
            assert _queue(updater)[0] == _slot(SYDNEY, "2026-10-20", 1)
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_failed_fetch_consumes_only_its_slot(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that a failed update is not retried by the schedule, and does not take the next slot with it."""

    try:
        coordinator, updater = await _init(
            hass,
            freezer,
            SYDNEY,
            "2026-10-19 12:50:00+00:00",
            "2026-10-19 13:00:00+00:00",
        )
        with patch.object(
            coordinator.solcast.fetcher,
            "get_forecast_update",
            new=AsyncMock(return_value=UpdateResult(UpdateOutcome.FAILED, "Simulated failure")),
        ) as get_forecast_update:
            await _rebuild(coordinator)
            await updater.check_forecast_fetch()
            await _fire(hass, freezer)
            await hass.async_block_till_done(wait_background_tasks=True)
            assert get_forecast_update.await_count == 1
            assert _queue(updater)[0] == _slot(SYDNEY, "2026-10-20", 1)

            freezer.move_to("2026-10-19 13:05:00+00:00")
            await updater.check_forecast_fetch()
            await _fire(hass, freezer)
            assert get_forecast_update.await_count == 1
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_restart_around_midnight(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test restarts either side of local midnight neither lose the midnight update nor repeat it."""

    try:
        # Restarted just before midnight: the slot is armed by the restart, and must not be armed again by the tick
        coordinator, updater = await _init(
            hass,
            freezer,
            SYDNEY,
            "2026-10-19 12:50:00+00:00",
            "2026-10-19 12:58:30+00:00",
        )
        with patch.object(updater, "forecast_update", new=AsyncMock()) as forecast_update:
            updater.update_setup(init=True)
            await updater.check_forecast_fetch()
            freezer.move_to("2026-10-19 13:00:00+00:00")
            await _rebuild(coordinator)
            await updater.check_forecast_fetch()
            await _fire(hass, freezer)
            await hass.async_block_till_done(wait_background_tasks=True)
            assert forecast_update.await_count == 1
            assert _queue(updater)[0] == _slot(SYDNEY, "2026-10-20", 1)

            # Restarted after the midnight slot has passed: it is not fetched by the schedule, and nothing else is lost
            freezer.move_to("2026-10-19 13:02:00+00:00")
            updater.update_setup(init=True)
            await updater.check_forecast_fetch()
            await _fire(hass, freezer)
            assert forecast_update.await_count == 1
            assert _queue(updater)[0] == _slot(SYDNEY, "2026-10-20", 1)
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_utc_midnight_usage_reset_does_not_disturb_schedule(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that the UTC midnight quota reset, which is not local midnight in Sydney, leaves the schedule alone."""

    try:
        coordinator, updater = await _init(
            hass,
            freezer,
            SYDNEY,
            "2026-10-19 23:50:00+00:00",
            "2026-10-20 00:00:00+00:00",
        )
        queue = _queue(updater)
        with patch.object(updater, "forecast_update", new=AsyncMock()) as forecast_update:
            await coordinator._update_utc_midnight_usage_sensor_data()  # pyright: ignore[reportPrivateUsage]
            await updater.check_forecast_fetch()
            await _fire(hass, freezer)
            assert forecast_update.await_count == 0
            assert _queue(updater) == queue
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_local_midnight_coinciding_with_utc_midnight(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that where local midnight is UTC midnight the update follows the quota reset, and is dispatched once."""

    try:
        coordinator, updater = await _init(
            hass,
            freezer,
            "UTC",
            "2026-10-19 23:50:00+00:00",
            "2026-10-20 00:00:00+00:00",
        )
        events: list[str] = []

        async def record_reset(*_args: object, **_kwargs: object) -> None:
            events.append("reset")

        async def record_update(*_args: object, **_kwargs: object) -> None:
            events.append("update")

        with (
            patch.object(
                coordinator.solcast.sites_cache,
                "reset_api_usage",
                new=AsyncMock(side_effect=record_reset),
            ),
            patch.object(updater, "forecast_update", new=AsyncMock(side_effect=record_update)),
        ):
            await coordinator._update_utc_midnight_usage_sensor_data()  # pyright: ignore[reportPrivateUsage]
            await _rebuild(coordinator)
            await updater.check_forecast_fetch()
            await _fire(hass, freezer)
            await hass.async_block_till_done(wait_background_tasks=True)
            assert events == ["reset", "update"]
            assert _queue(updater)[0] == _slot("UTC", "2026-10-20", 1)
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


@pytest.mark.parametrize(
    ("day", "before", "now"),
    [
        (
            "2026-10-04",
            "2026-10-03 13:50:00+00:00",
            "2026-10-03 14:00:00+00:00",
        ),  # Sydney spring forward, 23 hour day
        (
            "2027-04-04",
            "2027-04-03 12:50:00+00:00",
            "2027-04-03 13:00:00+00:00",
        ),  # Sydney fall back, 25 hour day
        (
            "2026-10-05",
            "2026-10-04 12:50:00+00:00",
            "2026-10-04 13:00:00+00:00",
        ),  # Midnight ending the 23 hour day
        (
            "2027-04-05",
            "2027-04-04 13:50:00+00:00",
            "2027-04-04 14:00:00+00:00",
        ),  # Midnight ending the 25 hour day
    ],
    ids=["spring_forward", "fall_back", "after_spring_forward", "after_fall_back"],
)
async def test_midnight_update_across_daylight_saving(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    day: str,
    before: str,
    now: str,
) -> None:
    """Test the midnight update either side of Sydney daylight saving transitions."""

    try:
        coordinator, updater = await _init(hass, freezer, SYDNEY, before, now)
        with patch.object(updater, "forecast_update", new=AsyncMock()) as forecast_update:
            await _rebuild(coordinator)
            await updater.check_forecast_fetch()
            await _fire(hass, freezer)
            await hass.async_block_till_done(wait_background_tasks=True)
            assert forecast_update.await_count == 1
            queue = _queue(updater)
            assert queue[0] == _slot(SYDNEY, day, 1)
            assert _slot(SYDNEY, day, 0) not in queue
            assert len(set(queue)) == len(queue)
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


async def test_update_is_aborted_while_a_fetch_is_running(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that an update is aborted, not stacked, when a forecast fetch is already running.

    A scheduled update is now dispatched once, so an overlapping fetch must be provoked explicitly.
    """

    try:
        coordinator, _ = await _init(hass, freezer, SYDNEY, "2026-10-19 12:50:00+00:00", "2026-10-19 12:55:00+00:00")
        solcast = coordinator.solcast
        solcast.data[LAST_UPDATED] -= timedelta(minutes=20)
        solcast.tasks[TASK_FORECASTS_FETCH] = MagicMock()
        try:
            result = await solcast.fetcher.get_forecast_update()
        finally:
            solcast.tasks.pop(TASK_FORECASTS_FETCH)
        assert result.outcome == UpdateOutcome.ABORTED
        assert "A fetch task is already running, so aborting forecast update" in caplog.text
        assert "Forecast update aborted" in caplog.text
    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"
