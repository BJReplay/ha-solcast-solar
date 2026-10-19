"""Tests for the auto-update schedule at local midnight.

At local midnight the five-minute update check (``Updater.check_forecast_fetch``) and the daily rebuild of the
update schedule (``SolcastUpdateCoordinator._update_integration_listeners``) fire on the same tick, in no defined
order, and the update scheduled for local midnight falls exactly on that tick. It must be dispatched exactly once
whichever runs first, and a fired update must only ever remove its own slot from the schedule.
"""

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
import copy
from datetime import datetime as dt, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.solcast_solar.const import (
    API_LIMIT,
    AUTO_UPDATE,
    AUTO_UPDATE_QUEUE,
    DOMAIN,
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

# Local midnight at the start of 2026-10-20 in Sydney (AEDT, UTC+11) is 13:00 UTC the day before
BEFORE = "2026-10-19 12:50:00+00:00"
MIDNIGHT = "2026-10-19 13:00:00+00:00"
NEXT_TICK = "2026-10-19 13:05:00+00:00"

pytestmark = pytest.mark.usefixtures("recorder_mock")

type Init = Callable[[str, str, str], Awaitable[tuple[SolcastUpdateCoordinator, Updater]]]


@pytest.fixture(autouse=True)
def frozen_time() -> None:
    """Override autouse fixture for this module.

    Time is moved explicitly to either side of local midnight.
    """
    return


def _cancel_trackers(coordinator: SolcastUpdateCoordinator) -> None:
    """Cancel the time trackers, so that tests call their callbacks in an explicit order."""

    for task in (TASK_CHECK_FETCH, TASK_LISTENERS, TASK_MIDNIGHT_UPDATE):
        coordinator.tasks.pop(task)()


@pytest.fixture
async def init(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> AsyncGenerator[Init]:
    """Set up an all-day schedule of ten updates, then move to the instant under test."""

    async def _init(timezone: str, before: str, now: str) -> tuple[SolcastUpdateCoordinator, Updater]:
        freezer.move_to(before)
        options = copy.deepcopy(DEFAULT_INPUT1)
        options[AUTO_UPDATE] = 2
        options[API_LIMIT] = "20"
        entry = await async_init_integration(hass, options, timezone=timezone)
        coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator
        assert coordinator.updater.divisions == SLOTS_PER_DAY
        _cancel_trackers(coordinator)
        freezer.move_to(now)
        return coordinator, coordinator.updater

    yield _init
    assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


def _queue(updater: Updater) -> list[dt]:
    return list(updater.get_auto_update_details()[AUTO_UPDATE_QUEUE])


def _slot(timezone: str, day: str, index: int) -> dt:
    """Return the nominal update slot of a local day, which is split evenly into ten from local midnight."""

    zone = ZoneInfo(timezone)
    start = dt.fromisoformat(day).replace(tzinfo=zone).astimezone(ZoneInfo("UTC"))
    end = (dt.fromisoformat(day) + timedelta(days=1)).replace(tzinfo=zone).astimezone(ZoneInfo("UTC"))
    return (start + (end - start) / SLOTS_PER_DAY * index).astimezone(zone)


async def _fire(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float = 1.0) -> None:
    """Move on and let any due timer run."""

    freezer.tick(seconds)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def _run(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    coordinator: SolcastUpdateCoordinator,
    ordering: tuple[str, ...],
) -> None:
    """Run the callbacks of a tick in the given order."""

    steps: dict[str, Callable[[], Awaitable[None]]] = {
        "check": coordinator.updater.check_forecast_fetch,
        "rebuild": coordinator._update_integration_listeners,  # pyright: ignore[reportPrivateUsage]
        "reset": coordinator._update_utc_midnight_usage_sensor_data,  # pyright: ignore[reportPrivateUsage]
        "dispatch": lambda: _fire(hass, freezer),
    }
    for step in ordering:
        await steps[step]()
    await hass.async_block_till_done(wait_background_tasks=True)


ORDERINGS = {
    "rebuild_check_dispatch": ("rebuild", "check", "dispatch"),
    "check_dispatch_rebuild": ("check", "dispatch", "rebuild"),
    "check_rebuild_dispatch": ("check", "rebuild", "dispatch"),
}


@pytest.mark.parametrize("ordering", ORDERINGS.values(), ids=ORDERINGS.keys())
async def test_midnight_update_callback_orderings(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init: Init,
    ordering: tuple[str, ...],
) -> None:
    """Test that the local midnight update is dispatched once, and only its own slot is consumed, in every callback order."""

    coordinator, updater = await init(SYDNEY, BEFORE, MIDNIGHT)
    midnight = _slot(SYDNEY, "2026-10-20", 0)
    next_slot = _slot(SYDNEY, "2026-10-20", 1)
    assert midnight.isoformat() == "2026-10-20T00:00:00+11:00"
    assert next_slot.isoformat() == "2026-10-20T02:24:00+11:00"
    assert midnight in _queue(updater), "The midnight slot is queued from the schedule made the day before"

    with patch.object(updater, "forecast_update", new=AsyncMock()) as forecast_update:
        await _run(hass, freezer, coordinator, ordering)
        assert forecast_update.await_count == 1
        assert midnight not in _queue(updater)
        assert _queue(updater)[0] == next_slot

        # A repeated check and the next tick must neither dispatch again nor consume another slot
        freezer.move_to(NEXT_TICK)
        await updater.check_forecast_fetch()
        await updater.check_forecast_fetch()
        await _fire(hass, freezer)
        assert forecast_update.await_count == 1
        assert _queue(updater)[0] == next_slot


@pytest.mark.parametrize(
    ("day", "before", "now"),
    [
        ("2026-10-04", "2026-10-03 13:50:00+00:00", "2026-10-03 14:00:00+00:00"),  # Spring forward, a 23 hour day
        ("2027-04-04", "2027-04-03 12:50:00+00:00", "2027-04-03 13:00:00+00:00"),  # Fall back, a 25 hour day
        ("2026-10-05", "2026-10-04 12:50:00+00:00", "2026-10-04 13:00:00+00:00"),  # Midnight ending the 23 hour day
        ("2027-04-05", "2027-04-04 13:50:00+00:00", "2027-04-04 14:00:00+00:00"),  # Midnight ending the 25 hour day
    ],
    ids=["spring_forward", "fall_back", "after_spring_forward", "after_fall_back"],
)
async def test_midnight_update_across_daylight_saving(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init: Init,
    day: str,
    before: str,
    now: str,
) -> None:
    """Test the midnight update, and the slot after it, either side of Sydney daylight saving transitions."""

    coordinator, updater = await init(SYDNEY, before, now)
    with patch.object(updater, "forecast_update", new=AsyncMock()) as forecast_update:
        await _run(hass, freezer, coordinator, ORDERINGS["rebuild_check_dispatch"])
        assert forecast_update.await_count == 1
        queue = _queue(updater)
        assert _slot(SYDNEY, day, 0) not in queue
        assert queue[0] == _slot(SYDNEY, day, 1)
        assert len(set(queue)) == len(queue)


@pytest.mark.parametrize(
    "ordering",
    [("reset", "check", "dispatch"), ("check", "reset", "dispatch"), ("check", "dispatch", "reset")],
    ids=["reset_first", "reset_second", "reset_last"],
)
async def test_utc_midnight_quota_reset_coinciding_with_local_midnight(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init: Init,
    ordering: tuple[str, ...],
) -> None:
    """Test that the update is dispatched once, and only its own slot is consumed, wherever the UTC midnight reset falls.

    In the UTC time zone local midnight is UTC midnight, so the reset of the API usage counter, which also rebuilds the
    schedule, runs on the same tick as the check. Where the reset falls decides which UTC day the update is counted
    against, so the order in which the reset and the update happen is checked as well.
    """

    coordinator, updater = await init("UTC", "2026-10-19 23:50:00+00:00", "2026-10-20 00:00:00+00:00")
    events: list[str] = []

    async def reset(*_args: object) -> None:
        events.append("reset")

    async def update(*_args: object, **_kwargs: object) -> None:
        events.append("update")

    with (
        patch.object(coordinator.solcast.sites_cache, "reset_api_usage", new=AsyncMock(side_effect=reset)),
        patch.object(updater, "forecast_update", new=AsyncMock(side_effect=update)),
    ):
        await _run(hass, freezer, coordinator, ordering)
        assert events == ["update" if step == "dispatch" else step for step in ordering if step in ("reset", "dispatch")]
        assert _slot("UTC", "2026-10-20", 0) not in _queue(updater)
        assert _queue(updater)[0] == _slot("UTC", "2026-10-20", 1)


async def test_utc_midnight_quota_reset_leaves_local_schedule_alone(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init: Init,
) -> None:
    """Test that the UTC midnight reset, which is not local midnight in Sydney, neither rebuilds nor dispatches."""

    coordinator, updater = await init(SYDNEY, "2026-10-19 23:50:00+00:00", "2026-10-20 00:00:00+00:00")
    queue = _queue(updater)
    with patch.object(updater, "forecast_update", new=AsyncMock()) as forecast_update:
        await _run(hass, freezer, coordinator, ("reset", "check", "dispatch"))
        assert forecast_update.await_count == 0
        assert _queue(updater) == queue


async def test_repeated_check_in_window_dispatches_once(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init: Init,
) -> None:
    """Test that checking the same five-minute window repeatedly arms a slot only once."""

    slot = _slot(SYDNEY, "2026-10-20", 1)
    _, updater = await init(SYDNEY, "2026-10-19 15:00:00+00:00", "2026-10-19 15:21:30+00:00")
    assert slot in _queue(updater)
    with patch.object(updater, "forecast_update", new=AsyncMock()) as forecast_update:
        for _ in range(3):
            await updater.check_forecast_fetch()
        await _fire(hass, freezer, 151)
        await hass.async_block_till_done(wait_background_tasks=True)
        assert forecast_update.await_count == 1
        assert slot not in _queue(updater)


async def test_midnight_update_when_check_is_late(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init: Init,
) -> None:
    """Test that a check that starts a few seconds after the tick still dispatches the slot due in its window."""

    coordinator, updater = await init(SYDNEY, BEFORE, MIDNIGHT)
    with patch.object(updater, "forecast_update", new=AsyncMock()) as forecast_update:
        await coordinator._update_integration_listeners()  # pyright: ignore[reportPrivateUsage]
        freezer.tick(3)  # The rebuild took a while
        await _run(hass, freezer, coordinator, ("check", "dispatch"))
        assert forecast_update.await_count == 1
        assert _queue(updater)[0] == _slot(SYDNEY, "2026-10-20", 1)


async def test_fetch_in_flight_when_schedule_is_rebuilt(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init: Init,
) -> None:
    """Test that a slow update still running when the schedule is rebuilt and the next tick arrives consumes nothing more."""

    coordinator, updater = await init(SYDNEY, BEFORE, MIDNIGHT)
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
        await coordinator._update_integration_listeners()  # pyright: ignore[reportPrivateUsage]
        freezer.move_to(NEXT_TICK)
        await updater.check_forecast_fetch()
        release.set()
        await hass.async_block_till_done(wait_background_tasks=True)
        assert forecast_update.await_count == 1
        assert _queue(updater)[0] == _slot(SYDNEY, "2026-10-20", 1)


async def test_failed_update_consumes_only_its_slot(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init: Init,
) -> None:
    """Test that a failed update is not retried by the schedule, and does not take the next slot with it."""

    coordinator, updater = await init(SYDNEY, BEFORE, MIDNIGHT)
    with patch.object(
        coordinator.solcast.fetcher,
        "get_forecast_update",
        new=AsyncMock(return_value=UpdateResult(UpdateOutcome.FAILED, "Simulated failure")),
    ) as get_forecast_update:
        await _run(hass, freezer, coordinator, ORDERINGS["rebuild_check_dispatch"])
        assert get_forecast_update.await_count == 1
        assert _queue(updater)[0] == _slot(SYDNEY, "2026-10-20", 1)

        freezer.move_to(NEXT_TICK)
        await updater.check_forecast_fetch()
        await _fire(hass, freezer)
        assert get_forecast_update.await_count == 1


@pytest.mark.parametrize(
    ("restart_at", "dispatches"),
    [
        ("2026-10-19 12:58:30+00:00", 1),  # Before midnight, so the new instance dispatches the midnight update on the tick
        ("2026-10-19 13:02:00+00:00", 0),  # After the midnight slot has passed, which is left to the next scheduled update
    ],
    ids=["before_midnight", "after_midnight"],
)
async def test_restart_around_midnight(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init: Init,
    restart_at: str,
    dispatches: int,
) -> None:
    """Test that restarting the integration around local midnight neither loses the midnight update nor repeats it.

    The config entry is reloaded, so the update schedule and the slots claimed are those of a new instance.
    """

    await init(SYDNEY, BEFORE, restart_at)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    with patch.object(Updater, "forecast_update", new=AsyncMock()) as forecast_update:
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        coordinator: SolcastUpdateCoordinator = entry.runtime_data.coordinator
        updater = coordinator.updater
        _cancel_trackers(coordinator)
        started = forecast_update.await_count

        freezer.move_to(MIDNIGHT if dispatches else NEXT_TICK)
        await _run(hass, freezer, coordinator, ORDERINGS["rebuild_check_dispatch"])
        assert forecast_update.await_count - started == dispatches
        assert _queue(updater)[0] == _slot(SYDNEY, "2026-10-20", 1)

        freezer.move_to(NEXT_TICK)
        await updater.check_forecast_fetch()
        await _fire(hass, freezer)
        assert forecast_update.await_count - started == dispatches


async def test_update_is_aborted_while_a_fetch_is_running(
    init: Init,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that an update is aborted, not stacked, when a forecast fetch is already running.

    A scheduled update is dispatched once, so an overlapping fetch has to be provoked explicitly.
    """

    coordinator, _ = await init(SYDNEY, BEFORE, "2026-10-19 12:55:00+00:00")
    solcast = coordinator.solcast
    solcast.data[LAST_UPDATED] -= timedelta(minutes=20)
    solcast.tasks[TASK_FORECASTS_FETCH] = MagicMock()
    try:
        result = await solcast.fetcher.get_forecast_update()
    finally:
        solcast.tasks.pop(TASK_FORECASTS_FETCH)
    assert result.outcome is UpdateOutcome.ABORTED
    assert "A fetch task is already running, so aborting forecast update" in caplog.text
    assert "Forecast update aborted" in caplog.text
