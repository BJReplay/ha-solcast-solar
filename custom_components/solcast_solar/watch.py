"""Solcast file monitoring."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, Any

from watchfiles import Change, awatch

from homeassistant.core import CALLBACK_TYPE
from homeassistant.helpers.event import async_call_later

from .const import (
    ADVANCED_RELOAD_ON_ADVANCED_CHANGE,
    CONFIG_DISCRETE_NAME,
    CONFIG_FOLDER_DISCRETE,
    SITE_DAMP,
    TASK_WATCH_ADVANCED,
    TASK_WATCH_ADVANCED_FILE_CHANGE,
    TASK_WATCH_DAMPENING,
    TASK_WATCH_DAMPENING_FILE_CHANGE,
    TASK_WATCH_DAMPENING_LEGACY,
)

if TYPE_CHECKING:
    from datetime import datetime as dt

    from .coordinator import SolcastUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class FileWatcher:
    """File monitoring for the Solcast Solar integration."""

    def __init__(self, coordinator: SolcastUpdateCoordinator) -> None:
        """Initialise the file watcher.

        Arguments:
            coordinator: The update coordinator.

        """
        self.coordinator = coordinator
        self._pending_restart: CALLBACK_TYPE | None = None

    def _awatch_kwargs(self, stop_event: Event | None) -> dict[str, Any]:
        """Return common watchfiles arguments for responsive shutdown."""
        return {
            "debounce": 50,
            "step": 10,
            "stop_event": stop_event,
        }

    def _start_managed_task(self, task_name: str, coro: Any) -> None:
        """Start a task whose cancellation also stops its watchfiles iterator."""
        coordinator = self.coordinator
        stop_event = Event()
        task = asyncio.create_task(coro(stop_event))

        def cancel() -> None:
            stop_event.set()
            task.cancel()

        coordinator.tasks[task_name] = cancel

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
            lambda stop_event: self.watch_for_file(
                TASK_WATCH_ADVANCED,
                coordinator.file_advanced,
                self.watch_advanced_file,
                process_on_add=True,
                stop_event=stop_event,
            ),
        )
        if not coordinator.solcast.options.auto_dampen:
            self._start_managed_task(
                TASK_WATCH_DAMPENING_FILE_CHANGE,
                lambda stop_event: self.watch_for_file(
                    TASK_WATCH_DAMPENING,
                    coordinator.file_dampening,
                    self.watch_dampening_file,
                    process_on_add=False,
                    stop_event=stop_event,
                ),
            )
            if CONFIG_FOLDER_DISCRETE:
                self._start_managed_task(
                    TASK_WATCH_DAMPENING_LEGACY,
                    self.watch_for_dampening_legacy_location,
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

    def _watch_dir(self, file_path: str) -> str:
        """Return the directory to watch for a given file path."""
        if CONFIG_FOLDER_DISCRETE:
            return f"{self.coordinator.hass.config.config_dir}/{CONFIG_DISCRETE_NAME}"
        return str(Path(file_path).parent)

    async def watch_for_file(
        self,
        task: str,
        file_path: str,
        handler: Any,
        process_on_add: bool = True,
        stop_event: Event | None = None,
    ) -> None:
        """Watch for file creation and start the handler task when the file appears."""
        coordinator = self.coordinator

        if self._path_exists(file_path):
            self._start_managed_task(task, lambda handler_stop_event: handler(False, handler_stop_event))
            _LOGGER.debug("Running task %s", task)

        async for changes in awatch(
            self._watch_dir(file_path),
            watch_filter=lambda change, path: path == file_path and change == Change.added,
            **self._awatch_kwargs(stop_event),
        ):
            for change_type, changed_path in changes:
                if (
                    change_type == Change.added
                    and changed_path == file_path
                    and coordinator.tasks.get(task) is None
                    and self._path_exists(file_path)
                ):
                    self._start_managed_task(task, lambda handler_stop_event: handler(process_on_add, handler_stop_event))
                    _LOGGER.debug("Running task %s", task)

    async def _handle_dampening_update(self, file_path: str) -> None:
        """Refresh dampening data after a file change."""
        coordinator = self.coordinator

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
        stop_event: Event | None = None,
    ) -> None:
        """Watch for granular dampening JSON file modification."""
        coordinator = self.coordinator
        task = TASK_WATCH_DAMPENING
        file_path = coordinator.file_dampening

        try:
            if initial_change:
                await self._handle_dampening_update(file_path)

            async for changes in awatch(
                str(Path(file_path).parent),
                watch_filter=lambda change, path: path == file_path,
                **self._awatch_kwargs(stop_event),
            ):
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
            if coordinator.tasks.get(task) is not None:
                if stop_event is None:
                    coordinator.tasks[task]()
                coordinator.tasks.pop(task)
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
        stop_event: Event | None = None,
    ) -> None:
        """Watch for advanced options JSON file modification."""
        coordinator = self.coordinator
        task = TASK_WATCH_ADVANCED
        file_path = coordinator.file_advanced

        try:
            _LOGGER.debug("Monitoring %s", file_path)
            if initial_change:
                await self._handle_advanced_update()

            async for changes in awatch(
                str(Path(file_path).parent),
                watch_filter=lambda change, path: path == file_path,
                **self._awatch_kwargs(stop_event),
            ):
                deleted = False
                for change_type, _ in changes:
                    if change_type == Change.deleted:
                        deleted = True
                        break
                    if change_type == Change.modified:
                        await self._handle_advanced_update()
                if deleted:
                    _LOGGER.debug("Advanced options file deleted, no longer monitoring %s for changes", file_path)
                    coordinator.solcast.advanced_opt.set_default_advanced_options()
                    break
        finally:
            if coordinator.tasks.get(task) is not None:
                if stop_event is None:
                    coordinator.tasks[task]()
                coordinator.tasks.pop(task)
                _LOGGER.debug("Cancelled task %s", task)

    async def watch_for_dampening_legacy_location(self, stop_event: Event | None = None) -> None:
        """Watch for dampening file modification in the legacy config location."""
        coordinator = self.coordinator
        from datetime import datetime as dt  # noqa: PLC0415

        end_date = dt(2026, 6, 1, tzinfo=coordinator.solcast.options.tz)
        if dt.now(coordinator.solcast.options.tz) < end_date:
            task = TASK_WATCH_DAMPENING_LEGACY
            _file_dampening_legacy = coordinator.file_dampening.replace("/solcast_solar", "")

            try:
                async for changes in awatch(
                    coordinator.hass.config.config_dir,
                    watch_filter=lambda change, path: path == _file_dampening_legacy and change == Change.added,
                    **self._awatch_kwargs(stop_event),
                ):
                    for change_type, changed_path in changes:
                        if (
                            change_type == Change.added
                            and changed_path == _file_dampening_legacy
                            and Path(_file_dampening_legacy).exists()
                            and dt.now(coordinator.solcast.options.tz) < end_date
                        ):
                            Path(_file_dampening_legacy).rename(coordinator.file_dampening)
                            _LOGGER.warning(
                                "Moved dampening file %s from legacy config to %s, auto-moving will cease 1st June 2026",
                                _file_dampening_legacy,
                                coordinator.file_dampening,
                            )
                    if dt.now(coordinator.solcast.options.tz) >= end_date:
                        break
            finally:
                if coordinator.tasks.get(task) is not None:
                    coordinator.tasks.pop(task)
                _LOGGER.debug("Cancelled task %s", task)
