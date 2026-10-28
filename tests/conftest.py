"""Test configuration for Solcast Solar integration."""

from collections.abc import Generator
from datetime import datetime as dt
import logging
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from custom_components.solcast_solar import const
import freezegun
from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant import loader
from homeassistant.core import HomeAssistant
from homeassistant.util.yaml import load_yaml_dict  # pyright: ignore[reportUnknownVariableType]

from . import aioresponses_reset

from tests.common import QualityScaleStatus
import tests.components.conftest as core_conftest
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
    "watchfiles.main",
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


@pytest.fixture
def hass(hass: HomeAssistant) -> HomeAssistant:
    """Load solcast_solar from custom_components, as Home Assistant does for users.

    Same as Core's enable_custom_integrations fixture, which as an autouse fixture would set up hass before recorder_mock.
    """
    hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
    return hass


@pytest.fixture(autouse=True)
def fail_on_custom_integration_report() -> Generator[None]:
    """Fail a test when Core reports a wrong or deprecated call by this integration.

    For a built-in integration Core raises in many of these cases, for a custom integration it only logs
    "Detected that custom integration ...". This keeps such calls failing in the tests first.
    """
    reports: list[str] = []

    def collect(record: logging.LogRecord) -> bool:
        if record.getMessage().startswith(f"Detected that custom integration '{const.DOMAIN}'"):
            reports.append(record.getMessage())
        return True

    frame_logger = logging.getLogger("homeassistant.helpers.frame")
    level = frame_logger.level
    frame_logger.setLevel(logging.WARNING)  # Core reports at WARNING; a test that raises the root level must not hide it.
    frame_logger.addFilter(collect)
    yield
    frame_logger.removeFilter(collect)
    frame_logger.setLevel(level)
    if reports:
        pytest.fail("\n".join(reports))


@pytest.fixture(autouse=True, scope="session")
def quality_scale_from_custom_components() -> Generator[None]:
    """Let Core's translation checks read quality_scale.yaml of this integration from custom_components.

    Core reads homeassistant/components/<domain>/quality_scale.yaml. Without that file it skips the check for untranslated
    exceptions and does not require data_description in config flows. Core runs the exception check after the test, so
    the scope is session. Other integrations keep Core's own functions.
    """
    rules = cast(dict[str, Any], load_yaml_dict(Path(const.__file__).with_name("quality_scale.yaml"))["rules"])
    # Same as Core's get_quality_scale, with the path of this integration. A rule is a status or a mapping with a status.
    statuses = {rule: QualityScaleStatus(details if isinstance(details, str) else details["status"]) for rule, details in rules.items()}
    core_get_quality_scale = core_conftest.get_quality_scale
    core_get_rules = core_conftest._get_integration_quality_scale  # pyright: ignore[reportPrivateUsage]

    def get_quality_scale(domain: str) -> dict[str, QualityScaleStatus]:
        return statuses if domain == const.DOMAIN else core_get_quality_scale(domain)

    def get_rules(domain: str) -> dict[str, Any]:
        return rules if domain == const.DOMAIN else core_get_rules(domain)

    with (
        patch.object(core_conftest, "get_quality_scale", get_quality_scale),
        patch.object(core_conftest, "_get_integration_quality_scale", get_rules),
    ):
        yield


@pytest.fixture
def hass_config_dir(hass_tmp_config_dir: str) -> str:
    """Use a per-test config directory so xdist workers do not share files."""
    return hass_tmp_config_dir


# Slowest tests.  Placing them first in the queue ensures xdist dispatches each to a separate worker.
_SLOW_FIRST: tuple[str, ...] = (
    "test_api_failure",
    "test_remaining_actions",
    "test_adaptive_auto_dampen",
    "test_auto_dampen",
    "test_advanced_options",
    "test_scenarios",
    "test_reconfigure_api_quota",
    "test_reauth_api_key",
    "test_reconfigure_api_key1",
    "test_integration_runtime_and_dampening_flow",
)


def pytest_collection_modifyitems(config: Any, items: list[Any]) -> None:
    """Move the slowest tests to the front so xdist workers start on them first."""
    if not config.getoption("--dist", default="no").startswith(("load", "worksteal")):
        return
    slow, rest = [], []
    for item in items:
        base = item.name.split("[")[0]
        (slow if base in _SLOW_FIRST else rest).append(item)
    slow.sort(key=lambda i: _SLOW_FIRST.index(i.name.split("[")[0]))
    items[:] = slow + rest
