"""Solcast file monitoring."""

from __future__ import annotations

import asyncio
from enum import Enum
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from watchdog.events import (
    DirCreatedEvent,
    DirDeletedEvent,
    DirModifiedEvent,
    DirMovedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from homeassistant.helpers.event import async_call_later

from .const import (
    ADVANCED_RELOAD_ON_ADVANCED_CHANGE,
    CONFIG_DISCRETE_NAME,
    CONFIG_FOLDER_DISCRETE,
    EVENT,
    SITE_DAMP,
    TASK_WATCHDOG_ADVANCED,
    TASK_WATCHDOG_ADVANCED_FILE_CHANGE,
    TASK_WATCHDOG_DAMPENING,
    TASK_WATCHDOG_DAMPENING_FILE_CHANGE,
    TASK_WATCHDOG_DAMPENING_LEGACY,
)

if TYPE_CHECKING:
    from datetime import datetime as dt

    from .coordinator import SolcastUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class FileEvent(Enum):
    """File event types."""

    NO_EVENT = 0
    CREATE = 1
    UPDATE = 2
    DELETE = 3


class StartEventHandler(FileSystemEventHandler):
    """Handle start file monitoring."""

    def __init__(self, watcher: FileWatcher, task: str, path: str, direct_task: str = "") -> None:
        """Initialise the start event handler.

        Arguments:
            watcher: The file watcher instance.
            task: The task identifier.
            path: The file path to watch.
            direct_task: An optional direct task identifier.

        """
        self._watcher = watcher
        self._task = task
        self._direct_task = direct_task
        self._path = path
        super().__init__()

    def on_created(self, event: DirCreatedEvent | FileCreatedEvent) -> None:
        """File has been created."""
        coordinator = self._watcher.coordinator
        if isinstance(event, FileCreatedEvent) and (coordinator.tasks.get(self._task) is None or self._direct_task):
            if event.src_path == self._path:
                self._watcher.watchdog[self._task if not self._direct_task else self._direct_task][EVENT] = FileEvent.CREATE

    def on_moved(self, event: DirMovedEvent | FileMovedEvent) -> None:
        """File has been moved/renamed away from self._path."""
        coordinator = self._watcher.coordinator
        # Moved out
        if isinstance(event, FileMovedEvent) and coordinator.tasks.get(self._task) is not None:
            if event.src_path == self._path:
                self._watcher.watchdog[self._task][EVENT] = FileEvent.DELETE
        # Moved in
        if isinstance(event, FileMovedEvent) and coordinator.tasks.get(self._task) is None:
            if event.dest_path == self._path:
                self._watcher.watchdog[self._task][EVENT] = FileEvent.CREATE


class EventHandler(FileSystemEventHandler):
    """Handle file modification."""

    def __init__(self, watcher: FileWatcher, task: str, path: str) -> None:
        """Initialise the event handler.

        Arguments:
            watcher: The file watcher instance.
            task: The task identifier.
            path: The file path to watch.

        """
        self._watcher = watcher
        self._task = task
        self._path = path
        super().__init__()

    def on_deleted(self, event: DirDeletedEvent | FileDeletedEvent) -> None:
        """File has been deleted."""
        self._watcher.watchdog[self._task][EVENT] = FileEvent.DELETE

    def on_modified(self, event: DirModifiedEvent | FileModifiedEvent) -> None:
        """File has been modified."""
        if isinstance(event, FileModifiedEvent) and self._watcher.watchdog[self._task][EVENT] != FileEvent.UPDATE:
            self._watcher.watchdog[self._task][EVENT] = FileEvent.UPDATE


class FileWatcher:
    """File monitoring for the Solcast Solar integration."""

    def __init__(self, coordinator: SolcastUpdateCoordinator) -> None:
        """Initialise the file watcher.

        Arguments:
            coordinator: The update coordinator.

        """
        self.coordinator = coordinator
        self.watchdog: dict[str, dict[str, Any]] = {
            TASK_WATCHDOG_DAMPENING: {EVENT: FileEvent.NO_EVENT},
            TASK_WATCHDOG_DAMPENING_LEGACY: {EVENT: FileEvent.NO_EVENT},
            TASK_WATCHDOG_ADVANCED: {EVENT: FileEvent.NO_EVENT},
        }

    async def setup(self) -> None:
        """Set up file watchdog tasks."""
        coordinator = self.coordinator
        coordinator.tasks[TASK_WATCHDOG_ADVANCED_FILE_CHANGE] = (
            asyncio.create_task(self.watch_for_file(TASK_WATCHDOG_ADVANCED, coordinator.file_advanced, self.watch_advanced_file))
        ).cancel
        if not coordinator.solcast.options.auto_dampen:
            coordinator.tasks[TASK_WATCHDOG_DAMPENING_FILE_CHANGE] = (
                asyncio.create_task(self.watch_for_file(TASK_WATCHDOG_DAMPENING, coordinator.file_dampening, self.watch_dampening_file))
            ).cancel
            if CONFIG_FOLDER_DISCRETE:
                coordinator.tasks[TASK_WATCHDOG_DAMPENING_LEGACY] = (asyncio.create_task(self.watch_for_dampening_legacy_location())).cancel
        else:
            _LOGGER.debug("Not monitoring dampening file, auto-dampening is enabled")

    async def _restart(self, called_at: dt | None = None) -> None:
        """Restart the integration to apply advanced configuration changes."""
        coordinator = self.coordinator
        await coordinator.solcast.tasks_cancel()
        await coordinator.tasks_cancel()
        await coordinator.hass.config_entries.async_reload(coordinator.entry.entry_id)

    async def watch_for_file(self, task: str, file_path: str, handler: Any) -> None:
        """Watch for file modification."""
        coordinator = self.coordinator

        try:
            if Path(file_path).exists():
                coordinator.tasks[task] = (asyncio.create_task(handler())).cancel
                _LOGGER.debug("Running task %s", task)

            observer = Observer()
            observer.schedule(
                StartEventHandler(self, task, file_path),
                path=f"{coordinator.hass.config.config_dir}/{CONFIG_DISCRETE_NAME}"
                if CONFIG_FOLDER_DISCRETE
                else coordinator.hass.config.config_dir,
                recursive=False,
            )
            observer.start()

            try:
                while not coordinator.hass.is_stopping:
                    await asyncio.sleep(1)
                    if self.watchdog[task][EVENT] == FileEvent.CREATE and coordinator.tasks.get(task) is None and Path(file_path).exists():
                        self.watchdog[task][EVENT] = FileEvent.UPDATE
                        coordinator.tasks[task] = (asyncio.create_task(handler())).cancel
                        _LOGGER.debug("Running task %s", task)
            finally:
                observer.stop()
                observer.join()
        finally:
            self.watchdog[task][EVENT] = FileEvent.NO_EVENT

    async def watch_dampening_file(self) -> None:
        """Watch for granular dampening JSON file modification."""
        coordinator = self.coordinator
        task = TASK_WATCHDOG_DAMPENING
        try:
            event_handler = EventHandler(self, task, coordinator.file_dampening)
            observer = Observer()
            observer.schedule(event_handler, path=coordinator.file_dampening, recursive=False)
            observer.start()

            try:
                while not coordinator.hass.is_stopping and coordinator.tasks and self.watchdog[task][EVENT] != FileEvent.DELETE:
                    await asyncio.sleep(0.5)
                    if (
                        self.watchdog[task][EVENT] == FileEvent.UPDATE
                        and coordinator.solcast.dampening.factors_mtime != Path(coordinator.file_dampening).stat().st_mtime
                    ):
                        self.watchdog[task][EVENT] = FileEvent.NO_EVENT
                        _LOGGER.debug("Granular dampening mtime changed")
                        await coordinator.solcast.dampening.refresh_granular_data()
                        await coordinator.solcast.dampening.apply_forward()
                        _LOGGER.debug("Recalculate forecasts and refresh sensors")
                        await coordinator.solcast.build_forecast_data()
                        await coordinator.update_integration_listeners()
                if self.watchdog[task][EVENT] == FileEvent.DELETE:
                    _LOGGER.debug("Granular dampening file deleted, no longer monitoring %s for changes", coordinator.file_dampening)
                    coordinator.solcast.dampening.factors = {}
                    entry = coordinator.solcast.entry
                    opt = coordinator.solcast.entry_options
                    opt[SITE_DAMP] = False  # Clear "hidden" option.
                    coordinator.solcast.dampening.set_allow_granular_reset(True)
                    if entry is not None:
                        coordinator.hass.config_entries.async_update_entry(entry, options=opt)
            finally:
                observer.stop()
                observer.join()
        finally:
            self.watchdog[task][EVENT] = FileEvent.NO_EVENT
            if coordinator.tasks.get(task) is not None:
                coordinator.tasks[task]()  # Cancel the task
                coordinator.tasks.pop(task)
                _LOGGER.debug("Cancelled task %s", task)

    async def watch_advanced_file(self) -> None:
        """Watch for advanced options JSON file modification."""
        coordinator = self.coordinator
        task = TASK_WATCHDOG_ADVANCED
        try:
            event_handler = EventHandler(self, task, coordinator.file_advanced)
            observer = Observer()
            observer.schedule(event_handler, path=coordinator.file_advanced, recursive=False)
            observer.start()
            _LOGGER.debug("Monitoring %s", coordinator.file_advanced)

            try:
                while not coordinator.hass.is_stopping and coordinator.tasks and self.watchdog[task][EVENT] != FileEvent.DELETE:
                    await asyncio.sleep(0.5)
                    if self.watchdog[task][EVENT] == FileEvent.UPDATE:
                        self.watchdog[task][EVENT] = FileEvent.NO_EVENT
                        change = await coordinator.solcast.advanced_opt.read_advanced_options()
                        if change and coordinator.solcast.advanced_options.get(ADVANCED_RELOAD_ON_ADVANCED_CHANGE, False):
                            _LOGGER.debug("Advanced options changed, restarting")
                            async_call_later(coordinator.hass, 1, self._restart)
                if self.watchdog[task][EVENT] == FileEvent.DELETE:
                    _LOGGER.debug("Advanced options file deleted, no longer monitoring %s for changes", coordinator.file_advanced)
                    coordinator.solcast.advanced_opt.set_default_advanced_options()
            finally:
                observer.stop()
                observer.join()
        finally:
            self.watchdog[task][EVENT] = FileEvent.NO_EVENT
            if coordinator.tasks.get(task) is not None:
                coordinator.tasks[task]()  # Cancel the task
                coordinator.tasks.pop(task)
                _LOGGER.debug("Cancelled task %s", task)

    async def watch_for_dampening_legacy_location(self) -> None:
        """Watch for dampening file modification in the legacy config location."""
        coordinator = self.coordinator
        from datetime import datetime as dt  # noqa: PLC0415

        end_date = dt(2026, 6, 1, tzinfo=coordinator.solcast.options.tz)
        if dt.now(coordinator.solcast.options.tz) < end_date:
            task = TASK_WATCHDOG_DAMPENING_LEGACY
            _file_dampening_legacy = coordinator.file_dampening.replace("/solcast_solar", "")

            try:
                observer = Observer()
                observer.schedule(
                    StartEventHandler(self, "blah", _file_dampening_legacy, direct_task=task),
                    path=coordinator.hass.config.config_dir,
                    recursive=False,
                )
                observer.start()

                try:
                    while not coordinator.hass.is_stopping and dt.now(coordinator.solcast.options.tz) < end_date:
                        await asyncio.sleep(1)
                        if self.watchdog[task][EVENT] == FileEvent.CREATE and Path(_file_dampening_legacy).exists():
                            Path(_file_dampening_legacy).rename(coordinator.file_dampening)
                            _LOGGER.warning(
                                "Moved dampening file %s from legacy config to %s, auto-moving will cease 1st June 2026",
                                _file_dampening_legacy,
                                coordinator.file_dampening,
                            )
                            self.watchdog[task][EVENT] = FileEvent.NO_EVENT
                finally:
                    observer.stop()
                    observer.join()
            finally:
                self.watchdog[task][EVENT] = FileEvent.NO_EVENT
                _LOGGER.debug("Cancelled task %s", task) if coordinator.tasks.get(task) is not None else None
                coordinator.tasks.pop(task) if coordinator.tasks.get(task) is not None else None
