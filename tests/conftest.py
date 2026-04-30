"""Test configuration for Solcast Solar integration."""

from collections.abc import Generator
from datetime import datetime as dt
import logging
from pathlib import Path

import freezegun
from freezegun.api import FrozenDateTimeFactory
import pytest

import tests.common as tests_common

disable_loggers = [
    "homeassistant.core",
    "homeassistant.components.recorder.core",
    "homeassistant.components.recorder.pool",
    "homeassistant.components.recorder.pool.MutexPool",
    "sqlalchemy.engine.Engine",
    "watchdog.observers.inotify_buffer",
    "asyncio",
]


def pytest_configure():
    """Disable loggers."""

    for logger_name in disable_loggers:
        logger = logging.getLogger(logger_name)
        logger.disabled = True


@pytest.fixture(autouse=True)
def frozen_time() -> Generator[FrozenDateTimeFactory]:
    """Freeze test time."""

    with freezegun.freeze_time(f"{dt.now().date()} 12:27:27", tz_offset=-10) as freeze:
        yield freeze  # type: ignore[misc]


@pytest.fixture(autouse=True)
def isolate_test_config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Use a per-test config directory so xdist workers do not share files."""

    def _get_test_config_dir(*add_path: str) -> str:
        return str(tmp_path.joinpath(*add_path))

    monkeypatch.setattr(tests_common, "get_test_config_dir", _get_test_config_dir)
