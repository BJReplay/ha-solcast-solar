"""Tests for the number of forecast intervals expected per local day."""

import copy
from datetime import UTC, datetime, timedelta, tzinfo
from importlib import resources
from typing import Any
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar.const import (
    AUTO_UPDATE,
    DOMAIN,
    GET_ACTUALS,
    ISSUE_RECORDS_MISSING_FIXABLE,
    ISSUE_RECORDS_MISSING_UNFIXABLE,
    PERIOD_START,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from . import DEFAULT_INPUT1, async_cleanup_integration_tests, async_init_integration


@pytest.fixture(autouse=True)
def frozen_time() -> None:
    """Override autouse frozen_time fixture for this module."""
    return


class FlagOnlyChange(tzinfo):
    """UTC-7 all year, marked as summer time until 2026-11-01 02:00 local, like America/Vancouver in tzdata 2026e."""

    _offset = timedelta(hours=-7)
    _flag_end = datetime(2026, 11, 1, 2)

    def utcoffset(self, dt: datetime | None) -> timedelta:
        """Return the offset, which never changes."""
        return self._offset

    def dst(self, dt: datetime | None) -> timedelta:
        """Return one hour before the flag ends and zero after it."""
        return timedelta(hours=1) if dt is not None and dt.replace(tzinfo=None) < self._flag_end else timedelta(0)

    def tzname(self, dt: datetime | None) -> str:
        """Return the name."""
        return "PDT" if self.dst(dt) else "MST"

    def fromutc(self, dt: datetime) -> datetime:
        """Return local time for a UTC time."""
        return (dt + self._offset).replace(tzinfo=self)


def _zone(name: str, key: str | None = None) -> ZoneInfo:
    """Load a zone from the tzdata package, independent of the system time zone database."""
    with resources.files("tzdata.zoneinfo").joinpath(*name.split("/")).open("rb") as file:
        return ZoneInfo.from_file(file, key=key or name)


LONDON = _zone("Europe/London")
SYDNEY = _zone("Australia/Sydney")
ATHENS = _zone("Europe/Athens")
LORD_HOWE = _zone("Australia/Lord_Howe")
# The tzdata package marks Dublin winter -1 hour. Other databases mark summer +1 hour, like London.
DUBLIN_WINTER_MINUS = _zone("Europe/Dublin")
DUBLIN_SUMMER_PLUS = _zone("Europe/London", "Europe/Dublin")


async def _init(hass: HomeAssistant, tz: tzinfo, timezone: str, options: dict[str, Any] | None = None) -> ConfigEntry:
    """Set up the integration with the given tzinfo as its time zone."""
    with patch(f"homeassistant.components.{DOMAIN}.__get_time_zone", AsyncMock(return_value=tz)):
        return await async_init_integration(hass, options or DEFAULT_INPUT1, timezone=timezone)


def test_dublin_zones_mark_summer_both_ways() -> None:
    """The two Dublin zones really differ in how they mark summer time."""
    winter = datetime(2026, 1, 15, 12)
    summer = datetime(2026, 7, 15, 12)
    for zone, marks in ((DUBLIN_WINTER_MINUS, (-1, 0)), (DUBLIN_SUMMER_PLUS, (0, 1))):
        assert (winter.replace(tzinfo=zone).dst(), summer.replace(tzinfo=zone).dst()) == tuple(timedelta(hours=h) for h in marks)


@pytest.mark.parametrize("source", ["synthetic", "tzdata"])
async def test_dst_flag_change_without_clock_change(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    issue_registry: ir.IssueRegistry,
    caplog: pytest.LogCaptureFixture,
    source: str,
) -> None:
    """A day whose DST flag ends without a clock change has 48 intervals, and missing data is still found."""

    tz: tzinfo = FlagOnlyChange() if source == "synthetic" else _zone("America/Vancouver")
    before = datetime(2026, 11, 1, 8, tzinfo=UTC).astimezone(tz)
    after = datetime(2026, 11, 1, 10, tzinfo=UTC).astimezone(tz)
    if (before.utcoffset(), before.dst(), after.dst()) != (timedelta(hours=-7), timedelta(hours=1), timedelta(0)):
        pytest.skip("tzdata older than 2026e")

    try:
        freezer.move_to("2026-10-25T12:00:00-07:00")
        options = copy.deepcopy(DEFAULT_INPUT1)
        options[AUTO_UPDATE] = "0"
        options[GET_ACTUALS] = False
        entry = await _init(hass, tz, "America/Vancouver", options)
        solcast = entry.runtime_data.coordinator.solcast

        assert "Forecast data from 2026-10-25 to 2026-11-06 contains all intervals" in caplog.text
        assert "missing forecast data" not in caplog.text
        assert "Transitioning from" not in caplog.text
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_RECORDS_MISSING_FIXABLE) is None
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_RECORDS_MISSING_UNFIXABLE) is None

        # Remove the interval at 02:00 local, when the DST flag ends.
        solcast.data_forecasts = [f for f in solcast.data_forecasts if f[PERIOD_START] != datetime(2026, 11, 1, 9, tzinfo=UTC)]
        caplog.clear()
        await solcast.check_data_records()

        assert "Forecast data for 2026-11-01 contains 47 of 48 intervals, so is missing forecast data" in caplog.text
        assert issue_registry.async_get_issue(DOMAIN, ISSUE_RECORDS_MISSING_FIXABLE) is not None

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"


@pytest.mark.parametrize(
    ("zone", "freeze_at", "transition"),
    [
        pytest.param(LONDON, "2026-03-27T12:00:00+00:00", "standard to summer", id="London spring"),
        pytest.param(LONDON, "2026-10-23T12:00:00+01:00", "summer to standard", id="London autumn"),
        pytest.param(SYDNEY, "2026-04-03T12:00:00+11:00", "summer to standard", id="Sydney autumn"),
        pytest.param(SYDNEY, "2026-10-02T12:00:00+10:00", "standard to summer", id="Sydney spring"),
        pytest.param(ATHENS, "2026-10-23T12:00:00+03:00", "summer to standard", id="Athens autumn at 04:00"),
        pytest.param(LORD_HOWE, "2026-10-02T12:00:00+10:30", "standard to summer", id="Lord Howe spring by 30 minutes"),
        pytest.param(DUBLIN_WINTER_MINUS, "2026-03-27T12:00:00+00:00", "winter to summer", id="Dublin winter -1h spring"),
        pytest.param(DUBLIN_WINTER_MINUS, "2026-10-23T12:00:00+01:00", "summer to winter", id="Dublin winter -1h autumn"),
        pytest.param(DUBLIN_SUMMER_PLUS, "2026-03-27T12:00:00+00:00", "winter to summer", id="Dublin summer +1h spring"),
        pytest.param(DUBLIN_SUMMER_PLUS, "2026-10-23T12:00:00+01:00", "summer to winter", id="Dublin summer +1h autumn"),
    ],
)
async def test_clock_change_days(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
    zone: ZoneInfo,
    freeze_at: str,
    transition: str,
) -> None:
    """A day with a clock change expects as many intervals as it has, whichever way the database marks summer time."""

    try:
        freezer.move_to(freeze_at)
        await _init(hass, zone, zone.key)
        first = datetime.fromisoformat(freeze_at).date()

        assert f"Transitioning from {transition} time" in caplog.text
        assert f"Forecast data from {first} to {first + timedelta(days=12)} contains all intervals" in caplog.text
        assert "missing forecast data" not in caplog.text

    finally:
        assert await async_cleanup_integration_tests(hass), "Integration test cleanup failed"
