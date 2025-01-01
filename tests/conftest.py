"""Test configuration for Solcast Solar integration."""

import logging

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
