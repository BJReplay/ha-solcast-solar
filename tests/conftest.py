"""Test configuration for Solcast Solar integration."""

from collections.abc import Generator
from datetime import datetime as dt
import logging
from pathlib import Path

import freezegun
from freezegun.api import FrozenDateTimeFactory
import pytest

from . import aioresponses_reset

import tests.common as tests_common

_SUPPRESS_LOGGERS = [
    "homeassistant.core",
    "homeassistant.components.recorder.core",
    "homeassistant.components.recorder.pool",
    "homeassistant.components.recorder.pool.MutexPool",
    "sqlalchemy.engine.Engine",
    "watchfiles",
    "asyncio",
]


@pytest.fixture(autouse=True)
def suppress_noisy_loggers() -> Generator[None]:
    """Disable noisy loggers for the duration of each test only."""
    loggers = [logging.getLogger(name) for name in _SUPPRESS_LOGGERS]
    previous = [logger.disabled for logger in loggers]
    for logger in loggers:
        logger.disabled = True
    yield
    for logger, was_disabled in zip(loggers, previous, strict=True):
        logger.disabled = was_disabled


@pytest.fixture(autouse=True)
def reset_aioresponses() -> Generator[None]:
    """Ensure the aiohttp mock is stopped after every test."""
    yield
    aioresponses_reset()


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
