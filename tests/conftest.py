"""Test configuration for Solcast Solar integration."""

from collections.abc import Generator
from datetime import datetime as dt
import logging

import freezegun
from freezegun.api import FrozenDateTimeFactory
import pytest

from . import aioresponses_reset

from tests.ignore_uncaught_exceptions import IGNORE_UNCAUGHT_EXCEPTIONS

# Background tasks can fire during teardown under parallel execution, producing
# an asyncio exception (InvalidStateError, CancelledError) when the entry is
# already unloading. Suppress here.
IGNORE_UNCAUGHT_EXCEPTIONS.append(
    (
        "tests.components.solcast_solar.test_integration",
        "test_integration",
    )
)

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
def hass_config_dir(hass_tmp_config_dir: str) -> str:
    """Use a per-test config directory so xdist workers do not share files."""
    return hass_tmp_config_dir
