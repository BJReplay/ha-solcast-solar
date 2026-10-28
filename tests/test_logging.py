"""Test Solcast Solar logging helpers."""

import logging

from custom_components.solcast_solar.log import (
    _LOG_FILTER,
    _LOG_MESSAGE_REWRITES,
    get_logger,
)


def test_log_filter() -> None:
    """Test a configured log rewrite."""
    source_message, (replacement_message, _) = next(iter(_LOG_MESSAGE_REWRITES.items()))
    record = logging.LogRecord(
        "test",
        logging.DEBUG,
        "",
        0,
        source_message,
        ("solcast_solar", 0.0, True),
        None,
    )

    assert _LOG_FILTER.filter(record)
    assert record.msg == replacement_message
    assert record.args == ("solcast_solar", True)
    assert record.getMessage() == "Finished fetching solcast_solar data (success: True)"


def test_log_filter_ignores_other_messages() -> None:
    """Test future messages pass through untouched unless configured."""
    record = logging.LogRecord(
        "test",
        logging.DEBUG,
        "",
        0,
        "Finished updating %s data",
        ("solcast_solar",),
        None,
    )

    assert _LOG_FILTER.filter(record)
    assert record.msg == "Finished updating %s data"
    assert record.args == ("solcast_solar",)


def test_log_filter_ignores_invalid_arguments() -> None:
    """Test a configured rewrite with missing arguments passes through untouched."""
    source_message = next(iter(_LOG_MESSAGE_REWRITES))
    record = logging.LogRecord(
        "test",
        logging.DEBUG,
        "",
        0,
        source_message,
        ("solcast_solar",),
        None,
    )

    assert _LOG_FILTER.filter(record)
    assert record.msg == source_message
    assert record.args == ("solcast_solar",)


def test_get_logger() -> None:
    """Test the shared filter is attached to an integration logger."""
    logger = get_logger("custom_components.solcast_solar.test")

    assert _LOG_FILTER in logger.filters
