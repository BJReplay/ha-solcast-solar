"""Solcast datetime and JSON encoding/decoding utilities."""

from collections.abc import Iterator
from datetime import UTC, datetime as dt, timedelta, tzinfo
import json
from typing import Any

from homeassistant.util import dt as dt_util

from .const import PERIOD_START


class DateTimeHelper:
    """Timezone-aware datetime helper methods."""

    def __init__(self, tz: tzinfo) -> None:
        """Initialise the datetime helper.

        Arguments:
            tz: The timezone to use for local time calculations.

        """
        self._tz = tz

    def day_start(self, ts: dt) -> dt:
        """Get day start datetime for a given timestamp."""
        return ts.astimezone(self._tz).replace(hour=0, minute=0, second=0, microsecond=0)

    def day_start_utc(self, future: int = 0) -> dt:
        """Return the UTC datetime representing midnight local time.

        Arguments:
            future: An optional number of days into the future (or negative number for into the past).

        Returns:
            datetime: The UTC date and time representing midnight local time.

        """
        for_when = (dt_util.now(self._tz) + timedelta(days=future)).astimezone(self._tz)
        return for_when.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)

    def dst(self, dt_obj: dt | None = None) -> bool:
        """Return whether a given date is daylight savings time, or for zones using winter time whether summer time."""
        result = False
        if dt_obj is not None:
            local = dt_obj.astimezone(self._tz)
            # Summer time is one hour ahead of the smaller offset of the year. Not tzinfo.dst(): for Dublin,
            # some time zone databases mark winter (-1 hour) and others summer (+1 hour).
            offsets = [dt(local.year, month, 1, tzinfo=self._tz).utcoffset() or timedelta(0) for month in (1, 7)]
            result = local.utcoffset() == min(offsets) + timedelta(hours=1)
        return result

    def hour_start_utc(self) -> dt:
        """Return the UTC datetime representing the start of the current hour."""
        return dt_util.now(self._tz).replace(minute=0, second=0, microsecond=0).astimezone(UTC)

    @property
    def is_dublin(self) -> bool:
        """Return whether the timezone is Dublin, which has unique DST."""
        return str(self._tz) in ("Europe/Dublin", "Dublin")

    def is_interval_dst(self, interval: dict[str, Any]) -> bool:
        """Return whether an interval is daylight savings time, or for zones using winter time whether summer time."""
        return self.dst(interval[PERIOD_START].astimezone(self._tz))

    def now_utc(self) -> dt:
        """Return the UTC datetime as at the previous minute boundary."""
        return dt_util.now(self._tz).replace(second=0, microsecond=0).astimezone(UTC)

    def real_now_utc(self) -> dt:
        """Return the UTC datetime including seconds/microseconds."""
        return dt_util.now(self._tz).astimezone(UTC)

    def utc_previous_midnight(self) -> dt:
        """Return the UTC datetime representing midnight UTC of the current day."""
        return dt_util.now().astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


class DateTimeEncoder(json.JSONEncoder):
    """Helper to convert datetime dict values to ISO format."""

    def default(self, o: Any) -> str | Any:
        """Convert to ISO format if datetime."""
        return o.isoformat() if isinstance(o, dt) else super().default(o)


class NoIndentEncoder(DateTimeEncoder):
    """Helper to output semi-indented json."""

    def __init__(self, *args, above_level=0, **kwargs) -> None:
        """Initialise the encoder."""
        super().__init__(*args, **kwargs)
        self.above_level = above_level

    def iterencode(self, o: Any, _one_shot: bool = False):
        """Recursive encoder to indent only top level keys."""
        list_lvl = 0
        up = ("[", "{")
        down = ("]", "}")
        raw: Iterator[str] = super().iterencode(o, _one_shot=_one_shot)
        output = ""
        for s in list(raw)[0].splitlines():
            level_down = any(c in s for c in down)
            if any(c in s for c in up):
                list_lvl += 1
                if list_lvl <= self.above_level:
                    s += "\n"
            elif list_lvl > self.above_level:
                s = s.replace(" ", "").rstrip()
                if level_down:
                    s += "\n"
            else:
                s += "\n"
            if level_down:
                list_lvl -= 1
            output += s
        yield output


class JSONDecoder(json.JSONDecoder):
    """Helper to convert ISO format dict values to datetime."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialise the decoder."""
        json.JSONDecoder.__init__(self, object_hook=self.date_hook, *args, **kwargs)  # noqa: B026

    def date_hook(self, o: Any) -> dict[str, Any]:
        """Return converted datetimes."""
        result: dict[str, Any] = {}
        for key, value in o.items():
            try:
                result[key] = dt.fromisoformat(value)
            except (TypeError, ValueError):
                result[key] = value
        return result
