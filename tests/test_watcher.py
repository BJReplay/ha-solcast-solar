"""Tests for Solcast file watcher behavior."""

import asyncio
from collections.abc import AsyncGenerator, Callable
import logging
import os
from pathlib import Path
from typing import Any
import unittest.mock

from asyncinotify import Inotify, Mask
from custom_components.solcast_solar.watch import Change, FileWatcher, awatch
from freezegun.api import FrozenDateTimeFactory
import pytest


@pytest.mark.asyncio
async def test_watch_dampening_file_missing() -> None:
    """Ignore a missing dampening file while processing an update event."""

    cancel = unittest.mock.Mock()
    coordinator = unittest.mock.MagicMock()
    coordinator.file_dampening = "/config/solcast_solar/solcast-dampening.json"
    coordinator.tasks = {"watch_dampening": cancel}
    coordinator.solcast = unittest.mock.MagicMock()
    coordinator.solcast.dampening.factors_mtime = 1.0
    coordinator.solcast.dampening.granular_serialising = False
    coordinator.solcast.dampening.refresh_granular_data = unittest.mock.AsyncMock()
    coordinator.solcast.dampening.apply_forward = unittest.mock.AsyncMock()
    coordinator.solcast.build_forecast_data = unittest.mock.AsyncMock()
    coordinator.update_integration_listeners = unittest.mock.AsyncMock()

    watcher = FileWatcher(coordinator)

    async def mock_awatch(*args: Any, **kwargs: Any) -> Any:
        """Yield a modify event (with missing file) then a delete event."""
        yield {(Change.modified, "/config/solcast_solar/solcast-dampening.json")}
        yield {(Change.deleted, "/config/solcast_solar/solcast-dampening.json")}

    with (
        unittest.mock.patch("custom_components.solcast_solar.watch.awatch", mock_awatch),
        unittest.mock.patch("custom_components.solcast_solar.watch.Path.stat", side_effect=FileNotFoundError),
    ):
        await watcher.watch_dampening_file()

    cancel.assert_not_called()  # Ended by itself
    assert "watch_dampening" not in coordinator.tasks
    coordinator.solcast.dampening.refresh_granular_data.assert_not_awaited()
    coordinator.solcast.dampening.apply_forward.assert_not_awaited()
    coordinator.solcast.build_forecast_data.assert_not_awaited()
    coordinator.update_integration_listeners.assert_not_awaited()


@pytest.mark.asyncio
async def test_watch_dampening_file_initial_change() -> None:
    """Process initial file change when watch starts with initial_change enabled."""

    cancel = unittest.mock.Mock()
    coordinator = unittest.mock.MagicMock()
    coordinator.file_dampening = "/config/solcast_solar/solcast-dampening.json"
    coordinator.tasks = {"watch_dampening": cancel}

    watcher = FileWatcher(coordinator)
    watcher._handle_dampening_update = unittest.mock.AsyncMock()

    async def mock_awatch(*args: Any, **kwargs: Any) -> Any:
        """Run the initial change, then end the watcher with a delete."""
        await kwargs["ready"]()
        yield {(Change.deleted, "/config/solcast_solar/solcast-dampening.json")}

    with (
        unittest.mock.patch("custom_components.solcast_solar.watch.awatch", mock_awatch),
        unittest.mock.patch.object(watcher, "_path_exists", return_value=False),
    ):
        await watcher.watch_dampening_file(initial_change=True)

    watcher._handle_dampening_update.assert_awaited_once_with("/config/solcast_solar/solcast-dampening.json")


@pytest.mark.asyncio
async def test_watch_dampening_file_recreated_then_deleted() -> None:
    """Continue monitoring when file is recreated, then stop on actual delete."""

    cancel = unittest.mock.Mock()
    coordinator = unittest.mock.MagicMock()
    coordinator.file_dampening = "/config/solcast_solar/solcast-dampening.json"
    coordinator.tasks = {"watch_dampening": cancel}
    coordinator.solcast = unittest.mock.MagicMock()
    coordinator.solcast.entry = None
    coordinator.solcast.entry_options = {}
    coordinator.solcast.damp = {}
    coordinator.solcast.dampening = unittest.mock.MagicMock()
    coordinator.solcast.dampening.granular_serialising = False

    watcher = FileWatcher(coordinator)

    async def mock_awatch(*args: Any, **kwargs: Any) -> Any:
        """Yield two delete events: first with recreation, second final deletion."""
        yield {(Change.deleted, "/config/solcast_solar/solcast-dampening.json")}
        yield {(Change.deleted, "/config/solcast_solar/solcast-dampening.json")}

    with (
        unittest.mock.patch("custom_components.solcast_solar.watch.awatch", mock_awatch),
        unittest.mock.patch.object(watcher, "_path_exists", side_effect=[True, False]),
    ):
        await watcher.watch_dampening_file()

    cancel.assert_not_called()  # Ended by itself
    coordinator.solcast.dampening.set_allow_granular_reset.assert_called_once_with(True)


@pytest.mark.asyncio
async def test_watch_dampening_file_rapid_churn() -> None:
    """Verify rapid modify/delete/recreate churn."""

    cancel = unittest.mock.Mock()
    coordinator = unittest.mock.MagicMock()
    coordinator.file_dampening = "/config/solcast_solar/solcast-dampening.json"
    coordinator.tasks = {"watch_dampening": cancel}
    coordinator.solcast = unittest.mock.MagicMock()
    coordinator.solcast.entry = None
    coordinator.solcast.entry_options = {}
    coordinator.solcast.damp = {}
    coordinator.solcast.dampening = unittest.mock.MagicMock()
    coordinator.solcast.dampening.granular_serialising = False

    watcher = FileWatcher(coordinator)
    watcher._handle_dampening_update = unittest.mock.AsyncMock()

    async def mock_awatch(*args: Any, **kwargs: Any) -> Any:
        """Yield modify/delete/recreate/modify/delete churn sequence."""
        yield {(Change.modified, "/config/solcast_solar/solcast-dampening.json")}
        yield {(Change.deleted, "/config/solcast_solar/solcast-dampening.json")}
        yield {(Change.modified, "/config/solcast_solar/solcast-dampening.json")}
        yield {(Change.deleted, "/config/solcast_solar/solcast-dampening.json")}

    with (
        unittest.mock.patch("custom_components.solcast_solar.watch.awatch", mock_awatch),
        unittest.mock.patch.object(watcher, "_path_exists", side_effect=[True, False]),
    ):
        await watcher.watch_dampening_file()

    watcher._handle_dampening_update.assert_has_awaits(
        [
            unittest.mock.call("/config/solcast_solar/solcast-dampening.json"),
            unittest.mock.call("/config/solcast_solar/solcast-dampening.json"),
        ]
    )
    cancel.assert_not_called()  # Ended by itself
    assert "watch_dampening" not in coordinator.tasks
    coordinator.solcast.dampening.set_allow_granular_reset.assert_called_once_with(True)


@pytest.mark.asyncio
async def test_watch_advanced_task_ends_by_itself() -> None:
    """Remove the task entry when the advanced watcher ends by itself."""

    cancel = unittest.mock.Mock()
    coordinator = unittest.mock.MagicMock()
    coordinator.file_advanced = "/config/solcast_solar/solcast-advanced.json"
    coordinator.tasks = {"watch_advanced": cancel}
    coordinator.solcast = unittest.mock.MagicMock()
    coordinator.solcast.advanced_opt = unittest.mock.MagicMock()
    coordinator.solcast.advanced_opt.set_default_advanced_options = unittest.mock.Mock()

    watcher = FileWatcher(coordinator)

    async def mock_awatch(*args: Any, **kwargs: Any) -> Any:
        """Yield delete event so watcher exits and finally block runs."""
        yield {(Change.deleted, "/config/solcast_solar/solcast-advanced.json")}

    with unittest.mock.patch("custom_components.solcast_solar.watch.awatch", mock_awatch):
        await watcher.watch_advanced_file()

    cancel.assert_not_called()  # Ended by itself
    assert "watch_advanced" not in coordinator.tasks


@pytest.mark.asyncio
async def test_handle_advanced_update_cancels_pending() -> None:
    """Cancel and replace a pending restart when advanced options change twice before restart fires."""

    coordinator = unittest.mock.MagicMock()
    coordinator.solcast = unittest.mock.MagicMock()
    coordinator.solcast.advanced_options = {"reload_on_advanced_change": True}
    coordinator.solcast.advanced_opt.read_advanced_options = unittest.mock.AsyncMock(return_value=True)

    cancel_first = unittest.mock.Mock()
    cancel_second = unittest.mock.Mock()
    call_later_returns = iter([cancel_first, cancel_second])

    watcher = FileWatcher(coordinator)

    with unittest.mock.patch(
        "custom_components.solcast_solar.watch.async_call_later",
        side_effect=lambda *a, **kw: next(call_later_returns),
    ):
        # First change: _pending_restart is None, so no cancel; schedules cancel_first
        await watcher._handle_advanced_update()
        assert watcher._pending_restart is cancel_first
        cancel_first.assert_not_called()

        # Second change before restart fires: cancels cancel_first, schedules cancel_second
        await watcher._handle_advanced_update()
        cancel_first.assert_called_once()
        assert watcher._pending_restart is cancel_second


def test_path_exists_oserror_returns_false() -> None:
    """Return False when Path.exists() raises OSError (e.g. a transient filesystem race)."""

    coordinator = unittest.mock.MagicMock()
    coordinator.hass.config.config_dir = "/config"
    watcher = FileWatcher(coordinator)

    with unittest.mock.patch("custom_components.solcast_solar.watch.Path.exists", side_effect=OSError):
        assert watcher._path_exists("/config/solcast_solar/solcast-dampening.json") is False


@pytest.mark.asyncio
async def test_watch_advanced_file_recreated() -> None:
    """Keep monitoring when the advanced options file is back by the time a delete is handled."""

    coordinator = unittest.mock.MagicMock()
    coordinator.file_advanced = "/config/solcast_solar/solcast-advanced.json"
    coordinator.tasks = {"watch_advanced": unittest.mock.Mock()}
    watcher = FileWatcher(coordinator)
    defaults = coordinator.solcast.advanced_opt.set_default_advanced_options

    async def mock_awatch(*args: Any, **kwargs: Any) -> Any:
        yield {(Change.deleted, "/config/solcast_solar/solcast-advanced.json")}
        yield {(Change.deleted, "/config/solcast_solar/solcast-advanced.json")}

    with (
        unittest.mock.patch("custom_components.solcast_solar.watch.awatch", mock_awatch),
        unittest.mock.patch.object(watcher, "_path_exists", side_effect=[True, False]) as exists,
    ):
        await watcher.watch_advanced_file()

    assert exists.call_count == 2  # Options kept after the first delete
    defaults.assert_called_once()


@pytest.mark.asyncio
async def test_watch_for_file_restarts_handler_on_any_change() -> None:
    """Start the handler on any change while none runs and the file exists."""

    coordinator = unittest.mock.MagicMock()
    coordinator.tasks = {}
    watcher = FileWatcher(coordinator)
    handler = unittest.mock.Mock()

    async def mock_awatch(*args: Any, **kwargs: Any) -> Any:
        yield {(Change.modified, "/config/solcast_solar/solcast-advanced.json")}
        yield {(Change.deleted, "/config/solcast_solar/solcast-advanced.json")}

    with (
        unittest.mock.patch("custom_components.solcast_solar.watch.awatch", mock_awatch),
        unittest.mock.patch.object(watcher, "_path_exists", return_value=True),
        unittest.mock.patch.object(watcher, "_start_managed_task") as start,
    ):
        await watcher.watch_for_file("watch_advanced", "/config/solcast_solar/solcast-advanced.json", handler, process_on_add=True)

    handler.assert_called_once_with(True)
    start.assert_called_once_with("watch_advanced", handler.return_value)


@pytest.mark.asyncio
async def test_handle_dampening_update_skips_own_write(tmp_path: Path) -> None:
    """Do not rebuild while this integration writes the dampening file itself."""

    file = tmp_path / "solcast-dampening.json"
    file.write_text("{}", encoding="utf-8")
    coordinator = unittest.mock.MagicMock()
    coordinator.solcast.dampening.factors_mtime = 0.0  # Stale, so only the guard stops a rebuild
    coordinator.solcast.dampening.refresh_granular_data = unittest.mock.AsyncMock()
    coordinator.solcast.dampening.apply_forward = unittest.mock.AsyncMock()
    coordinator.solcast.build_forecast_data = unittest.mock.AsyncMock()
    coordinator.update_integration_listeners = unittest.mock.AsyncMock()
    watcher = FileWatcher(coordinator)

    coordinator.solcast.dampening.granular_serialising = True
    await watcher._handle_dampening_update(str(file))
    coordinator.solcast.dampening.refresh_granular_data.assert_not_awaited()

    coordinator.solcast.dampening.granular_serialising = False
    await watcher._handle_dampening_update(str(file))
    coordinator.solcast.dampening.refresh_granular_data.assert_awaited_once()


async def _loop_passes() -> None:
    """Let pending callbacks run. Counts loop passes, as frozen_time stops the clock."""
    for _ in range(20):
        await asyncio.sleep(0)


async def _watching(file: Path, ready: Callable[[], None] | None = None) -> tuple[AsyncGenerator[set[tuple[Change, str]]], asyncio.Task[Any]]:
    """Start a watcher and return it with its pending first change."""
    is_ready = asyncio.Event()

    async def set_ready() -> None:
        if ready is not None:
            ready()
        is_ready.set()

    changes = awatch(str(file), ready=set_ready)
    first = asyncio.ensure_future(anext(changes))
    await is_ready.wait()
    return changes, first


# Real inotify. With the clock frozen a missing event hangs, hence the timeouts.


@pytest.mark.timeout(10)
@pytest.mark.asyncio
async def test_awatch_reports_complete_files(tmp_path: Path, frozen_time: FrozenDateTimeFactory) -> None:
    """Report written, replaced and touched files once each, and ignore other files."""

    file = tmp_path / "solcast-dampening.json"
    name = str(file)
    modified = {(Change.modified, name)}

    def create() -> None:
        fd = os.open(file, os.O_WRONLY | os.O_CREAT)
        os.write(fd, b"{}")
        os.fchmod(fd, 0o600)  # Before close, as installers do
        os.close(fd)

    changes, first = await _watching(file, ready=create)  # Fails if ready ran before the watch
    assert await first == modified

    pending = asyncio.ensure_future(anext(changes))
    (tmp_path / "other.json").write_text("{}", encoding="utf-8")
    await _loop_passes()
    assert not pending.done()  # Fails if other files are reported

    file.write_text('{"all": []}', encoding="utf-8")
    os.utime(file, (1, 1))  # Same read as the write: one change
    assert await pending == modified

    os.utime(file)
    assert await anext(changes) == modified

    file.unlink()  # Fails if the pair above left a second change
    pending = asyncio.ensure_future(anext(changes))
    await _loop_passes()
    frozen_time.tick(2)
    assert await pending == {(Change.deleted, name)}

    replacement = tmp_path / "solcast-dampening.tmp"
    replacement.write_text("{}", encoding="utf-8")
    replacement.replace(file)
    assert await anext(changes) == modified

    file.unlink()
    file.symlink_to(tmp_path / "other.json")
    assert await anext(changes) == modified  # Back at once: replaced
    await changes.aclose()


@pytest.mark.timeout(10)
@pytest.mark.asyncio
async def test_awatch_waits_before_reporting_a_delete(tmp_path: Path, frozen_time: FrozenDateTimeFactory) -> None:
    """A file renamed away is reported deleted only if it stays away for a second."""

    file = tmp_path / "solcast-advanced.json"
    name = str(file)
    file.write_text("{}", encoding="utf-8")
    changes, first = await _watching(file)

    file.unlink()
    file.write_text("{}", encoding="utf-8")  # Delete-and-rewrite save
    assert await first == {(Change.modified, name)}
    pending = asyncio.ensure_future(anext(changes))
    await _loop_passes()
    frozen_time.tick(2)
    await _loop_passes()
    assert not pending.done()  # Fails if the replaced file still counts as deleted

    file.rename(tmp_path / "solcast-advanced.bak")
    await _loop_passes()
    frozen_time.tick(0.9)
    await _loop_passes()
    assert not pending.done()
    frozen_time.tick(0.2)
    assert await pending == {(Change.deleted, name)}

    pending = asyncio.ensure_future(anext(changes))
    await _loop_passes()
    frozen_time.tick(2)
    await _loop_passes()
    assert not pending.done()  # Fails if the delete is reported again
    (tmp_path / "solcast-advanced.bak").rename(file)
    assert await pending == {(Change.modified, name)}

    file.unlink()
    fd = os.open(file, os.O_WRONLY | os.O_CREAT)  # Back but still open: no deadline
    pending = asyncio.ensure_future(anext(changes))
    await _loop_passes()
    frozen_time.tick(2)
    await _loop_passes()
    assert not pending.done()
    os.write(fd, b"{}")
    os.close(fd)
    assert await pending == {(Change.modified, name)}
    await changes.aclose()


@pytest.mark.timeout(10)
@pytest.mark.asyncio
async def test_awatch_ends_when_directory_goes(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Report the file deleted and stop when the watched directory is removed."""

    folder = tmp_path / "solcast_solar"
    folder.mkdir()
    file = folder / "solcast-advanced.json"
    file.write_text("{}", encoding="utf-8")
    changes, first = await _watching(file)
    file.unlink()
    folder.rmdir()
    assert await first == {(Change.deleted, str(file))}
    with pytest.raises(StopAsyncIteration):
        await anext(changes)
    assert f"{folder} is gone" in caplog.text


@pytest.mark.asyncio
async def test_awatch_missing_directory(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Warn, still run ready, and yield nothing when the directory cannot be watched."""

    caplog.set_level(logging.WARNING)
    missing = tmp_path / "missing"
    ready = unittest.mock.AsyncMock()
    assert [c async for c in awatch(str(missing / "solcast-advanced.json"), ready=ready)] == []
    ready.assert_awaited_once()
    assert f"Cannot watch {missing} for changes" in caplog.text


@pytest.mark.asyncio
async def test_awatch_without_inotify(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Warn and still run ready when no inotify instance can be created."""

    ready = unittest.mock.AsyncMock()
    with unittest.mock.patch("custom_components.solcast_solar.watch.Inotify", side_effect=OSError(24, "Too many open files")):
        assert [c async for c in awatch(str(tmp_path / "solcast-advanced.json"), ready=ready)] == []
    ready.assert_awaited_once()
    assert "Too many open files" in caplog.text


@pytest.mark.timeout(10)
@pytest.mark.asyncio
async def test_awatch_closes_its_descriptor(tmp_path: Path) -> None:
    """Cancelling the watcher closes the inotify descriptor."""

    instances: list[Inotify] = []

    class Recording(Inotify):
        def __init__(self) -> None:
            super().__init__()
            instances.append(self)

    with unittest.mock.patch("custom_components.solcast_solar.watch.Inotify", Recording):
        _, first = await _watching(tmp_path / "solcast-advanced.json")
    (inotify,) = instances
    assert inotify.fd >= 0
    first.cancel()  # Like cancelling the handler task
    with pytest.raises(asyncio.CancelledError):
        await first
    with pytest.raises(ValueError, match="closed"):
        _ = inotify.fd  # Still referenced here, so garbage collection cannot have closed it


def _event(mask: Mask, name: str | None = None) -> unittest.mock.Mock:
    event = unittest.mock.Mock(mask=mask)
    event.name = None if name is None else Path(name)  # name= in the constructor names the mock itself
    return event


class FakeInotify:
    """Replay events a few loop passes apart, so they are not merged."""

    events: tuple[unittest.mock.Mock, ...] = ()

    def __init__(self) -> None:
        """Start from the events of the class."""
        self.queue = list(self.events)

    def add_watch(self, path: str, mask: Mask) -> None:
        """Watch nothing."""

    def close(self) -> None:
        """Close nothing."""

    async def get(self) -> Any:
        """Return the next event a little later."""
        await _loop_passes()
        return self.queue.pop(0)


@pytest.mark.parametrize(
    ("events", "exists", "expected"),
    [
        # Overflow after delete and create, file present: both states must reset, or the ATTRIB is lost
        (
            [_event(Mask.DELETE, "f.json"), _event(Mask.CREATE, "f.json"), _event(Mask.Q_OVERFLOW), _event(Mask.ATTRIB, "f.json")],
            True,
            [{Change.modified}, {Change.modified}],
        ),
        # Overflow, file gone: deleted, reported when the watch goes away. UNMOUNT stands in for a nameless event
        ([_event(Mask.UNMOUNT), _event(Mask.Q_OVERFLOW)], False, [{Change.deleted}]),
        # ATTRIB before the close must not report a half-written file
        ([_event(Mask.CREATE, "f.json"), _event(Mask.ATTRIB, "f.json"), _event(Mask.CLOSE_WRITE, "f.json")], True, [{Change.modified}]),
        # A writer still holding the removed file must not bring it back
        ([_event(Mask.DELETE, "f.json"), _event(Mask.CLOSE_WRITE, "f.json")], False, [{Change.deleted}]),
    ],
)
@pytest.mark.asyncio
async def test_awatch_event_sequences(tmp_path: Path, events: list[unittest.mock.Mock], exists: bool, expected: list[set[Change]]) -> None:
    """Follow event sequences that real files cannot produce on demand."""

    file = tmp_path / "f.json"
    if exists:
        file.write_text("{}", encoding="utf-8")
    fake = type("Fake", (FakeInotify,), {"events": (*events, _event(Mask.IGNORED))})
    with unittest.mock.patch("custom_components.solcast_solar.watch.Inotify", fake):
        changes = [c async for c in awatch(str(file))]
    assert changes == [{(change, str(file)) for change in batch} for batch in expected]


@pytest.mark.timeout(10)
@pytest.mark.asyncio
async def test_awatch_directory_of_that_name_is_not_the_file(tmp_path: Path, frozen_time: FrozenDateTimeFactory) -> None:
    """A directory created under the file's name does not hold off the delete."""

    file = tmp_path / "f.json"
    file.write_text("{}", encoding="utf-8")
    changes, first = await _watching(file)
    file.unlink()
    file.mkdir()
    await _loop_passes()
    frozen_time.tick(2)
    assert await first == {(Change.deleted, str(file))}
    await changes.aclose()


@pytest.mark.timeout(10)
@pytest.mark.asyncio
async def test_awatch_change_then_delete_reports_only_the_delete(tmp_path: Path, frozen_time: FrozenDateTimeFactory) -> None:
    """A change that is followed at once by a delete is not reported for a file that is gone."""

    class Burst(FakeInotify):
        events = (_event(Mask.CLOSE_WRITE, "f.json"), _event(Mask.DELETE, "f.json"))

        async def get(self) -> Any:
            """Return queued events at once, like one kernel read, then wait."""
            if not self.queue:
                await asyncio.Event().wait()
            return self.queue.pop(0)

    file = tmp_path / "f.json"
    with unittest.mock.patch("custom_components.solcast_solar.watch.Inotify", Burst):
        changes = awatch(str(file))
        pending = asyncio.ensure_future(anext(changes))
        await _loop_passes()
        frozen_time.tick(2)
        assert await pending == {(Change.deleted, str(file))}
        await changes.aclose()
