"""Solcast utilities."""

import asyncio
from collections.abc import Generator
import contextlib
import gc
import logging
import math
import sys
from threading import get_ident
from time import perf_counter, thread_time
from types import CodeType
from typing import Any

from .log import get_logger

_LOGGER = get_logger(__name__)


def split_and_strip(value: str) -> list[str]:
    """Split a comma-separated string and strip whitespace, discarding empty items."""

    return [item.strip() for item in value.split(",") if item.strip()]


def azimuth_to_compass_degrees(azimuth: Any) -> float | None:
    """Convert Solcast azimuth to compass degrees in the range [0, 360).

    Solcast azimuth uses N=0, W=+90, E=-90, S=+/-180.
    Standard compass bearings use N=0, E=90, S=180, W=270.
    """
    try:
        return (-float(azimuth)) % 360.0
    except (TypeError, ValueError):
        return None


def azimuth_to_compass_direction(azimuth: Any) -> str | None:
    """Convert an azimuth value to a 16-point cardinal compass direction."""
    if (compass_degrees := azimuth_to_compass_degrees(azimuth)) is None:
        return None

    directions = (
        "N",
        "NNE",
        "NE",
        "ENE",
        "E",
        "ESE",
        "SE",
        "SSE",
        "S",
        "SSW",
        "SW",
        "WSW",
        "W",
        "WNW",
        "NW",
        "NNW",
    )
    return directions[int((compass_degrees + 11.25) // 22.5) % len(directions)]


def percentile(data: list[Any], _percentile: float) -> float | int:
    """Find the given percentile in a sorted list of values."""

    if not data:
        return 0.0
    k = (len(data) - 1) * (_percentile / 100)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return data[int(k)]
    d0 = data[int(f)] * (c - k)
    d1 = data[int(c)] * (k - f)
    return round(d0 + d1, 4)


def ordinal(value: int) -> str:
    """Return a number with an ordinal suffix."""

    abs_value = abs(value)
    return f"{value}{'th' if 11 <= abs_value % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(abs_value % 10, 'th')}"


def interquartile_bounds(sorted_data: list[Any], factor: float = 1.5) -> tuple[float | int, float | int]:
    """Return the lower and upper interquartile bounds of a sorted data set."""

    lower = 0.0
    upper = float("inf")
    iqr = 0.0
    if len(sorted_data) > 4:
        q1 = percentile(sorted_data, 25)
        q3 = percentile(sorted_data, 75)
        iqr = round(q3 - q1, 5)
        lower = round(q1 - factor * iqr, 4)
        upper = round(q3 + factor * iqr, 4)
    return (lower, upper)


def diff(lst: list[Any], non_negative: bool = True) -> list[Any]:
    """Build a numpy-like diff."""

    size = len(lst) - 1
    r: list[int | float] = [0] * size
    for i in range(size):
        r[i] = max(0, lst[i + 1] - lst[i]) if non_negative else lst[i + 1] - lst[i]
    return r


@contextlib.contextmanager
def log_loop_turns(code: CodeType, label: str) -> Generator[None, None, None]:
    """Log coroutine execution slices and GC time, excluding suspended time."""
    if not _LOGGER.isEnabledFor(logging.DEBUG):
        yield
        return

    threshold = asyncio.get_running_loop().slow_callback_duration
    monitoring = sys.monitoring
    for tool_id in (5, 4, 3):
        try:
            monitoring.use_tool_id(tool_id, "solcast-loop-timing")
        except ValueError:
            continue
        break
    else:
        _LOGGER.debug("%s timing skipped: monitoring slots are occupied", label)
        yield
        return

    task = asyncio.current_task()
    thread_id = get_ident()
    started: float | None = None
    cpu_started = 0.0
    gc_started: tuple[float, float, int] | None = None
    gc_elapsed = 0.0
    gc_cpu_elapsed = 0.0
    gc_counts = [0, 0, 0]
    turns = 0
    longest = 0.0
    total_elapsed = 0.0
    total_cpu = 0.0
    total_gc = 0.0
    total_gc_cpu = 0.0
    total_gc_counts = [0, 0, 0]

    def record_gc(phase: str, info: dict[str, int]) -> None:
        nonlocal gc_started, gc_elapsed, gc_cpu_elapsed
        if get_ident() != thread_id or started is None:
            return
        if phase == "start":
            gc_started = (perf_counter(), thread_time(), info["generation"])
        elif phase == "stop" and gc_started is not None:
            wall_start, cpu_start, generation = gc_started
            gc_elapsed += perf_counter() - wall_start
            gc_cpu_elapsed += thread_time() - cpu_start
            gc_counts[generation] += 1
            gc_started = None

    def resume(*event_args: object) -> None:
        nonlocal started, cpu_started, gc_elapsed, gc_cpu_elapsed, gc_counts
        if (not event_args or event_args[0] is code) and asyncio.current_task() is task:
            started = perf_counter()
            cpu_started = thread_time()
            gc_elapsed = 0.0
            gc_cpu_elapsed = 0.0
            gc_counts = [0, 0, 0]

    def suspend(*event_args: object) -> None:
        nonlocal started, turns, longest, total_elapsed, total_cpu, total_gc, total_gc_cpu
        if (not event_args or event_args[0] is code) and asyncio.current_task() is task and started is not None:
            elapsed = perf_counter() - started
            cpu_elapsed = thread_time() - cpu_started
            started = None
            turns += 1
            longest = max(longest, elapsed)
            total_elapsed += elapsed
            total_cpu += cpu_elapsed
            total_gc += gc_elapsed
            total_gc_cpu += gc_cpu_elapsed
            for generation, count in enumerate(gc_counts):
                total_gc_counts[generation] += count
            if elapsed >= threshold:
                _LOGGER.debug(
                    "%s event-loop slice took %.1f ms: CPU=%.1f ms, GC wall=%.1f ms, GC CPU=%.1f ms, GC counts (gen 0/1/2)=%s",
                    label,
                    elapsed * 1000,
                    cpu_elapsed * 1000,
                    gc_elapsed * 1000,
                    gc_cpu_elapsed * 1000,
                    gc_counts,
                )

    events = {
        monitoring.events.PY_RESUME: resume,
        monitoring.events.PY_THROW: resume,
        monitoring.events.PY_YIELD: suspend,
        monitoring.events.PY_RETURN: suspend,
        monitoring.events.PY_UNWIND: suspend,
    }
    try:
        gc.callbacks.append(record_gc)
        for event, handler in events.items():
            monitoring.register_callback(tool_id, event, handler)
        monitoring.set_events(tool_id, monitoring.events.PY_THROW | monitoring.events.PY_UNWIND)
        monitoring.set_local_events(tool_id, code, monitoring.events.PY_RESUME | monitoring.events.PY_YIELD | monitoring.events.PY_RETURN)
        resume()
        yield
    finally:
        suspend()
        gc.callbacks.remove(record_gc)
        monitoring.set_events(tool_id, 0)
        monitoring.set_local_events(tool_id, code, 0)
        for event in events:
            monitoring.register_callback(tool_id, event, None)
        monitoring.free_tool_id(tool_id)
        _LOGGER.debug(
            "%s performance: %d execution slices, longest %.1f ms, total wall=%.1f ms, total CPU=%.1f ms, "
            "GC wall=%.1f ms, GC CPU=%.1f ms, GC counts (gen 0/1/2)=%s (excluding suspended time)",
            label,
            turns,
            longest * 1000,
            total_elapsed * 1000,
            total_cpu * 1000,
            total_gc * 1000,
            total_gc_cpu * 1000,
            total_gc_counts,
        )
