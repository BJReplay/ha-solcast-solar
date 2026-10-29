"""Solcast file monitoring."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import aclosing
from dataclasses import dataclass
from datetime import datetime as dt
from enum import IntEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from asyncinotify import Event, Inotify, Mask

from homeassistant.core import CALLBACK_TYPE
from homeassistant.helpers.event import async_call_later

from .const import (
    ADVANCED_RELOAD_ON_ADVANCED_CHANGE,
    SITE_DAMP,
    TASK_WATCH_ADVANCED,
    TASK_WATCH_ADVANCED_FILE_CHANGE,
    TASK_WATCH_DAMPENING,
    TASK_WATCH_DAMPENING_FILE_CHANGE,
)

if TYPE_CHECKING:
    from .coordinator import SolcastUpdateCoordinator

from .log import get_logger

_LOGGER = get_logger(__name__)

# CLOSE_WRITE rather than MODIFY, so a file is read only once it is complete.
_MASK = Mask.CREATE | Mask.CLOSE_WRITE | Mask.ATTRIB | Mask.MOVED_TO | Mask.DELETE | Mask.MOVED_FROM
# Editors and Samba save by deleting and rewriting. A file back within this time
# was replaced, which must not turn dampening off.
_REPLACED_WITHIN = 1.0


class Change(IntEnum):
    """A change to a watched file."""

    modified = 1
    deleted = 2


@dataclass(slots=True)
class _Tracker:
    """State of the watched file between events, and what is still to be reported."""

    path: Path
    writing: bool = False
    modified: bool = False
    deleted_at: float | None = None

    def event(self, mask: Mask, now: float) -> None:
        """Take in an event for the file."""
        if Mask.ISDIR in mask:
            return
        if Mask.DELETE in mask or Mask.MOVED_FROM in mask:
            self.writing = self.modified = False
            self.deleted_at = now
            return
        if Mask.CREATE in mask and not self.path.is_symlink():
            self.writing = True
            return
        if Mask.ATTRIB in mask and self.writing:
            return
        if self.deleted_at is not None and not self.writing and (Mask.CLOSE_WRITE in mask or Mask.ATTRIB in mask):
            return  # A writer still holding the removed file does not bring it back
        self.writing = False
        self.deleted_at = None  # Back in time, so replaced rather than deleted
        self.modified = True

    def overflow(self, now: float) -> None:
        """Go by the file as it is now, since events were lost."""
        self.writing = False
        if self.path.exists():
            self.deleted_at = None
            self.modified = True
        else:
            self.modified = False
            if self.deleted_at is None:
                self.deleted_at = now


async def awatch(file_path: str, ready: Callable[[], Awaitable[None]] | None = None) -> AsyncGenerator[set[tuple[Change, str]]]:
    """Yield changes to one file as inotify reports them.

    No thread and no polling, so an idle watch costs nothing. New and replaced
    files count as modified. ready runs after the watch is set, so a file
    created in between is not missed.
    """
    directory = str(Path(file_path).parent)
    inotify: Inotify | None = None
    try:
        inotify = Inotify()
        inotify.add_watch(directory, _MASK)
    except OSError as e:
        _LOGGER.warning("Cannot watch %s for changes (%s), changes apply on reload", directory, e)
        if inotify is not None:
            inotify.close()
            inotify = None
    loop = asyncio.get_running_loop()
    tracker = _Tracker(Path(file_path))
    get: asyncio.Task[Event] | None = None  # Outlives each wait: cancelling a finished read would drop its events
    try:
        if ready is not None:
            await ready()
        if inotify is None:
            return
        while True:
            if get is None:
                get = asyncio.ensure_future(inotify.get())
            if tracker.modified:
                # Merge events from the same read, so cp -p (close, then utime) rebuilds once
                await asyncio.sleep(0)
                if not get.done():
                    tracker.modified = False
                    yield {(Change.modified, file_path)}
                    continue
            elif tracker.deleted_at is not None and not tracker.writing:  # Recreated but still open: no deadline
                await asyncio.wait({get}, timeout=max(0.0, tracker.deleted_at + _REPLACED_WITHIN - loop.time()))
                if not get.done():
                    tracker.deleted_at = None
                    yield {(Change.deleted, file_path)}
                    continue
            else:
                await asyncio.wait({get})
            event = get.result()
            get = None
            if Mask.IGNORED in event.mask:
                _LOGGER.warning("%s is gone, changes to %s apply on reload", directory, tracker.path.name)
                if tracker.deleted_at is not None:
                    yield {(Change.deleted, file_path)}
                elif tracker.modified:
                    yield {(Change.modified, file_path)}
                return
            if Mask.Q_OVERFLOW in event.mask:
                tracker.overflow(loop.time())
            elif event.name is not None and event.name.name == tracker.path.name:
                tracker.event(event.mask, loop.time())
    finally:
        try:
            if get is not None:
                get.cancel()
                await asyncio.wait({get})
        finally:
            if inotify is not None:
                inotify.close()


class FileWatcher:
    """File monitoring for the Solcast Solar integration."""

    def __init__(self, coordinator: SolcastUpdateCoordinator) -> None:
        """Initialise the file watcher.

        Arguments:
            coordinator: The update coordinator.

        """
        self.coordinator = coordinator
        self._pending_restart: CALLBACK_TYPE | None = None

    def _start_managed_task(self, task_name: str, coro: Any) -> None:
        """Start a task that the coordinator can cancel."""
        self.coordinator.tasks[task_name] = asyncio.create_task(coro).cancel

    def _path_exists(self, file_path: str) -> bool:
        """Return whether a path exists, tolerating transient filesystem races."""
        try:
            return Path(file_path).exists()
        except OSError:
            return False

    async def setup(self) -> None:
        """Set up file watcher tasks."""
        coordinator = self.coordinator
        self._start_managed_task(
            TASK_WATCH_ADVANCED_FILE_CHANGE,
            self.watch_for_file(
                TASK_WATCH_ADVANCED,
                coordinator.file_advanced,
                self.watch_advanced_file,
                process_on_add=True,
            ),
        )
        if not coordinator.solcast.options.auto_dampen:
            self._start_managed_task(
                TASK_WATCH_DAMPENING_FILE_CHANGE,
                self.watch_for_file(
                    TASK_WATCH_DAMPENING,
                    coordinator.file_dampening,
                    self.watch_dampening_file,
                    process_on_add=False,
                ),
            )
        else:
            _LOGGER.debug("Not monitoring dampening file, auto-dampening is enabled")

    async def _restart(self, _called_at: dt | None = None) -> None:
        """Restart the integration to apply advanced configuration changes."""
        self._pending_restart = None
        coordinator = self.coordinator
        await coordinator.solcast.tasks_cancel()
        await coordinator.tasks_cancel()
        await coordinator.hass.config_entries.async_reload(coordinator.entry.entry_id)

    async def watch_for_file(
        self,
        task: str,
        file_path: str,
        handler: Any,
        process_on_add: bool = True,
    ) -> None:
        """Watch for file creation and start the handler task when the file appears."""
        coordinator = self.coordinator

        async def start_if_present() -> None:
            if self._path_exists(file_path):
                self._start_managed_task(task, handler(False))
                _LOGGER.debug("Running task %s", task)

        async with aclosing(awatch(file_path, ready=start_if_present)) as watcher:
            async for changes in watcher:
                for change_type, _ in changes:
                    if change_type != Change.deleted and coordinator.tasks.get(task) is None and self._path_exists(file_path):
                        self._start_managed_task(task, handler(process_on_add))
                        _LOGGER.debug("Running task %s", task)

    async def _handle_dampening_update(self, file_path: str) -> None:
        """Refresh dampening data after a file change."""
        coordinator = self.coordinator
        if coordinator.solcast.dampening.granular_serialising:
            return  # Written by this integration, which applies it itself

        try:
            dampening_mtime = Path(file_path).stat().st_mtime
        except FileNotFoundError:
            return

        if coordinator.solcast.dampening.factors_mtime != dampening_mtime:
            _LOGGER.debug("Granular dampening mtime changed")
            await coordinator.solcast.dampening.refresh_granular_data()
            await coordinator.solcast.dampening.apply_forward()
            _LOGGER.debug("Recalculate forecasts and refresh sensors")
            await coordinator.solcast.build_forecast_data()
            await coordinator.update_integration_listeners()

    async def watch_dampening_file(
        self,
        initial_change: bool = False,
    ) -> None:
        """Watch for granular dampening JSON file modification."""
        coordinator = self.coordinator
        task = TASK_WATCH_DAMPENING
        file_path = coordinator.file_dampening

        async def initial() -> None:
            if initial_change:
                await self._handle_dampening_update(file_path)

        try:
            async with aclosing(awatch(file_path, ready=initial)) as watcher:
                async for changes in watcher:
                    deleted = False
                    for change_type, _ in changes:
                        if change_type == Change.deleted:
                            deleted = True
                            break
                        if change_type == Change.modified:
                            await self._handle_dampening_update(file_path)
                    if deleted:
                        if self._path_exists(file_path):
                            _LOGGER.debug("Granular dampening file recreation detected, continuing to monitor %s", file_path)
                            continue
                        if coordinator.solcast.dampening.granular_serialising:
                            _LOGGER.debug("Granular dampening file write in progress, continuing to monitor %s", file_path)
                            continue
                        _LOGGER.debug("Granular dampening file deleted, no longer monitoring %s for changes", file_path)
                        coordinator.solcast.dampening.factors = {}
                        entry = coordinator.solcast.entry
                        opt = {**coordinator.solcast.entry_options}
                        opt[SITE_DAMP] = False
                        for hour in range(24):
                            opt[f"damp{hour:02}"] = coordinator.solcast.damp.get(f"{hour}", opt.get(f"damp{hour:02}", 1.0))
                        coordinator.solcast.dampening.set_allow_granular_reset(True)
                        if entry is not None:
                            coordinator.hass.config_entries.async_update_entry(entry, options=opt)
                        break
        finally:
            if coordinator.tasks.pop(task, None) is not None:
                _LOGGER.debug("Cancelled task %s", task)

    async def _handle_advanced_update(self) -> None:
        """Reload advanced options after a file change."""
        coordinator = self.coordinator

        change = await coordinator.solcast.advanced_opt.read_advanced_options()
        if change and coordinator.solcast.advanced_options.get(ADVANCED_RELOAD_ON_ADVANCED_CHANGE, False):
            _LOGGER.debug("Advanced options changed, restarting")
            if self._pending_restart is not None:
                self._pending_restart()
            self._pending_restart = async_call_later(coordinator.hass, 1, self._restart)

    async def watch_advanced_file(
        self,
        initial_change: bool = False,
    ) -> None:
        """Watch for advanced options JSON file modification."""
        coordinator = self.coordinator
        task = TASK_WATCH_ADVANCED
        file_path = coordinator.file_advanced

        async def initial() -> None:
            if initial_change:
                await self._handle_advanced_update()

        try:
            _LOGGER.debug("Monitoring %s", file_path)
            async with aclosing(awatch(file_path, ready=initial)) as watcher:
                async for changes in watcher:
                    deleted = False
                    for change_type, _ in changes:
                        if change_type == Change.deleted:
                            deleted = True
                            break
                        if change_type == Change.modified:
                            await self._handle_advanced_update()
                    if deleted:
                        if self._path_exists(file_path):
                            _LOGGER.debug("Advanced options file recreation detected, continuing to monitor %s", file_path)
                            continue
                        _LOGGER.debug("Advanced options file deleted, no longer monitoring %s for changes", file_path)
                        coordinator.solcast.advanced_opt.set_default_advanced_options()
                        break
        finally:
            if coordinator.tasks.pop(task, None) is not None:
                _LOGGER.debug("Cancelled task %s", task)
