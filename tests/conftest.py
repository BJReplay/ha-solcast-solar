"""Test configuration for Solcast Solar integration."""

import logging

import pytest

from . import REQUEST_CONTEXT, ResponseMocker

disable_loggers = [
    "homeassistant.core",
    "homeassistant.components.recorder.core",
    "homeassistant.components.recorder.pool",
    "homeassistant.components.recorder.pool.MutexPool",
    "sqlalchemy.engine.Engine",
]


def pytest_configure():
    """Disable loggers."""
    for logger_name in disable_loggers:
        logger = logging.getLogger(logger_name)
        logger.disabled = True


@pytest.fixture(autouse=True)
def set_request_context(request: pytest.FixtureRequest):
    """Set request context for every test."""
    REQUEST_CONTEXT.set(request)


@pytest.fixture
def response_mocker():
    """Mock fixture for responses."""
    mocker = ResponseMocker()
    yield mocker
    mocker.responses.clear()
