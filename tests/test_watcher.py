"""Tests for Solcast file watcher behavior."""

from typing import Any
import unittest.mock

from custom_components.solcast_solar.watch import FileWatcher
import pytest
from watchfiles import Change


@pytest.mark.asyncio
async def test_watch_dampening_file_missing() -> None:
    """Ignore a missing dampening file while processing an update event."""

    cancel = unittest.mock.Mock()
    coordinator = unittest.mock.MagicMock()
    coordinator.file_dampening = "/config/solcast_solar/solcast-dampening.json"
    coordinator.tasks = {"watch_dampening": cancel}
    coordinator.solcast = unittest.mock.MagicMock()
    coordinator.solcast.dampening.factors_mtime = 1.0
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

    cancel.assert_called_once()
    assert "watch_dampening" not in coordinator.tasks
    coordinator.solcast.dampening.refresh_granular_data.assert_not_awaited()
    coordinator.solcast.dampening.apply_forward.assert_not_awaited()
    coordinator.solcast.build_forecast_data.assert_not_awaited()
    coordinator.update_integration_listeners.assert_not_awaited()


def test_watch_dir_non_discrete() -> None:
    """Return parent directory when discrete config folder mode is disabled."""

    coordinator = unittest.mock.MagicMock()
    coordinator.hass.config.config_dir = "/config"
    watcher = FileWatcher(coordinator)

    with unittest.mock.patch("custom_components.solcast_solar.watch.CONFIG_FOLDER_DISCRETE", False):
        assert watcher._watch_dir("/config/solcast_solar/solcast-dampening.json") == "/config/solcast_solar"


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
        """Yield one delete event to terminate the watcher quickly."""
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

    cancel.assert_called_once()
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
    cancel.assert_called_once()
    assert "watch_dampening" not in coordinator.tasks
    coordinator.solcast.dampening.set_allow_granular_reset.assert_called_once_with(True)


@pytest.mark.asyncio
async def test_watch_advanced_task_cancel_without_stop() -> None:
    """Cancel callback is called when advanced watcher exits without stop_event."""

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

    cancel.assert_called_once()
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
