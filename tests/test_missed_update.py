"""Catching up a missed automated forecast update when Home Assistant starts.

Each test restarts at a given time and counts the forecast updates the start check fetches.
The Berlin examples have four updates a day, at 07:44, 10:26, 13:07 and 15:48.
"""

from datetime import datetime as dt
import logging
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components import solcast_solar
from homeassistant.components.solcast_solar.const import AUTO_UPDATED, LAST_ATTEMPT
from homeassistant.components.solcast_solar.dates import DateTimeHelper
from homeassistant.components.solcast_solar.enums import AutoUpdate

BERLIN = ZoneInfo("Europe/Berlin")
SYDNEY = ZoneInfo("Australia/Sydney")

check_missed_update = getattr(solcast_solar, "__check_auto_update_missed")


async def start(
    freezer: FrozenDateTimeFactory,
    restart: dt,
    last_update: dt,
    missed_update: dt,
    call_left: bool = True,
) -> int:
    """Restart at `restart` and return how many forecast updates the start check fetched."""
    freezer.move_to(restart)
    updates = []

    async def update_forecast(**kwargs: Any) -> None:
        updates.append(kwargs)

    solcast = SimpleNamespace(
        options=SimpleNamespace(auto_update=AutoUpdate.DAYLIGHT, tz=restart.tzinfo),
        dt_helper=DateTimeHelper(restart.tzinfo),
        data={AUTO_UPDATED: 4, LAST_ATTEMPT: last_update},
        forecast_update_fits=call_left,
        latest_period=None,
    )
    coordinator = SimpleNamespace(solcast=solcast, divisions=4, interval_just_passed=missed_update)
    await check_missed_update(coordinator, SimpleNamespace(async_update_forecast=update_forecast))
    return len(updates)


@pytest.fixture(autouse=True)
def debug_logs(caplog: pytest.LogCaptureFixture) -> None:
    """Record the debug lines of the start check."""
    caplog.set_level(logging.DEBUG)


async def test_yesterdays_update_is_not_caught_up_at_night(freezer: FrozenDateTimeFactory, caplog: pytest.LogCaptureFixture) -> None:
    """A restart at 03:00 leaves yesterday's 15:48 update to today's first update at 07:44."""
    fetched = await start(
        freezer,
        restart=dt(2026, 10, 15, 3, 0, tzinfo=BERLIN),
        last_update=dt(2026, 10, 14, 13, 7, tzinfo=BERLIN),
        missed_update=dt(2026, 10, 14, 15, 48, tzinfo=BERLIN),
    )
    assert fetched == 0
    assert "due yesterday" in caplog.text


async def test_morning_update_is_caught_up_after_utc_midnight(freezer: FrozenDateTimeFactory) -> None:
    """In Sydney the UTC day starts at 11:00. A restart at 11:10 still fetches the 10:00 update of the same morning."""
    fetched = await start(
        freezer,
        restart=dt(2026, 10, 15, 11, 10, tzinfo=SYDNEY),
        last_update=dt(2026, 10, 15, 6, 30, tzinfo=SYDNEY),
        missed_update=dt(2026, 10, 15, 10, 0, tzinfo=SYDNEY),
    )
    assert fetched == 1


async def test_missed_update_without_a_call_left_is_not_caught_up(freezer: FrozenDateTimeFactory, caplog: pytest.LogCaptureFixture) -> None:
    """With no API call left there is nothing to fetch, and no warning is logged."""
    fetched = await start(
        freezer,
        restart=dt(2026, 10, 15, 12, 0, tzinfo=BERLIN),
        last_update=dt(2026, 10, 15, 7, 44, tzinfo=BERLIN),
        missed_update=dt(2026, 10, 15, 10, 26, tzinfo=BERLIN),
        call_left=False,
    )
    assert fetched == 0
    assert "no API call is left" in caplog.text
    assert "WARNING" not in caplog.text
