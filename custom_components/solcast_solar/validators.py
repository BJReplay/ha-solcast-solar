"""Solcast PV forecast, config validation functions."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.const import CONF_API_KEY

from .const import (
    API_LIMIT,
    EXCEPTION_API_DUPLICATE,
    EXCEPTION_API_KEY_EMPTY,
    EXCEPTION_API_LOOKS_LIKE_SITE,
    EXCEPTION_HARD_NOT_POSITIVE_NUMBER,
    EXCEPTION_HARD_TOO_MANY,
    EXCEPTION_INVALID_AUTO_UPDATE,
    EXCEPTION_INVALID_CUSTOM_HOURS_FORMAT,
    EXCEPTION_INVALID_CUSTOM_HOURS_RANGE,
    EXCEPTION_INVALID_EXPORT_LIMIT,
    EXCEPTION_INVALID_KEY_ESTIMATE,
    EXCEPTION_INVALID_USE_ACTUALS,
    EXCEPTION_LIMIT_NOT_NUMBER,
    EXCEPTION_LIMIT_ONE_OR_GREATER,
    EXCEPTION_LIMIT_TOO_MANY,
)

LIKE_SITE_ID = r"^[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}$"


def validate_api_key_value(api_key: str) -> tuple[str, int, str | None]:
    """Validate the API key string.

    Arguments:
        api_key: The API key string (comma separated for multiple keys).

    Returns:
        tuple[str, int, str | None]: The validated API key, API count, and error key or None.

    """
    api_key_cleaned = api_key.replace(" ", "")
    keys = [s for s in api_key_cleaned.split(",") if s]
    if not keys:
        return "", 0, EXCEPTION_API_KEY_EMPTY
    for index, key in enumerate(keys):
        if re.match(LIKE_SITE_ID, key):
            return "", 0, EXCEPTION_API_LOOKS_LIKE_SITE
        for i, k in enumerate(keys):
            if index != i and key == k:
                return "", 0, EXCEPTION_API_DUPLICATE
    return ",".join(keys), len(keys), None


def validate_api_key(user_input: dict[str, Any]) -> tuple[str, int, str | None]:
    """Validate the API key from user input dict.

    Arguments:
        user_input (dict[str, Any]): The user input.

    Returns:
        tuple[str, int, str | None]: The API key, API count, and abort result.

    """
    return validate_api_key_value(user_input[CONF_API_KEY])


def validate_api_limit_value(api_limit: str, api_count: int) -> tuple[str, str | None]:
    """Validate the API limit string.

    Arguments:
        api_limit: The API limit string (comma separated for multiple keys).
        api_count: The number of API keys.

    Returns:
        tuple[str, str | None]: The validated API limit string, and error key or None.

    """
    api_limit_cleaned = api_limit.replace(" ", "")
    quotas = [s for s in api_limit_cleaned.split(",") if s]
    for q in quotas:
        if not q.isnumeric():
            return "", EXCEPTION_LIMIT_NOT_NUMBER
        if int(q) < 1:
            return "", EXCEPTION_LIMIT_ONE_OR_GREATER
    if len(quotas) > api_count:
        return "", EXCEPTION_LIMIT_TOO_MANY
    return ",".join(quotas), None


def validate_api_limit(user_input: dict[str, Any], api_count: int) -> tuple[str, str | None]:
    """Validate the API limit from user input dict.

    Arguments:
        user_input (dict[str, Any]): The user input.
        api_count (int): The number of API keys.

    Returns:
        tuple[str, str | None]: The API limit, and abort result.

    """
    return validate_api_limit_value(user_input[API_LIMIT], api_count)


def validate_hard_limit_value(hard_limit: str, api_count: int) -> tuple[str, str | None]:
    """Validate hard limit value(s).

    Arguments:
        hard_limit: The hard limit string (comma separated for multiple API keys).
        api_count: The number of API keys.

    Returns:
        tuple[str, str | None]: The validated hard limit string, and error key or None.

    """
    to_set: list[str] = []
    for h in hard_limit.split(","):
        h = h.strip()
        if not h.replace(".", "", 1).isdigit():
            return "", EXCEPTION_HARD_NOT_POSITIVE_NUMBER
        val = float(h)
        # A value of 0 means "disable the hard limit", normalised to 100.0.
        if val == 0.0:
            val = 100.0
        to_set.append(f"{val:.1f}")
    if len(to_set) > api_count:
        return "", EXCEPTION_HARD_TOO_MANY
    return ",".join(to_set), None


def validate_custom_hours_value(hours_str: str) -> tuple[int, str | None]:
    """Validate custom hours sensor value.

    Arguments:
        hours_str: The hours string.

    Returns:
        tuple[int, str | None]: The validated hours integer, and error key or None.

    """
    hours_str = hours_str.strip()
    if not hours_str.isdigit():
        return 0, EXCEPTION_INVALID_CUSTOM_HOURS_FORMAT
    hour_val = int(hours_str)
    if hour_val < 1 or hour_val > 144:
        return 0, EXCEPTION_INVALID_CUSTOM_HOURS_RANGE
    return hour_val, None


def validate_auto_update_value(value: str) -> tuple[int, str | None]:
    """Validate auto update value.

    Arguments:
        value: The auto update string ("0", "1", or "2").

    Returns:
        tuple[int, str | None]: The validated auto update integer, and error key or None.

    """
    stripped = value.strip()
    if stripped not in ("0", "1", "2"):
        return 0, EXCEPTION_INVALID_AUTO_UPDATE
    return int(stripped), None


def validate_key_estimate_value(value: str) -> tuple[str, str | None]:
    """Validate key estimate value.

    Arguments:
        value: The estimate key ("estimate", "estimate10", or "estimate90").

    Returns:
        tuple[str, str | None]: The validated estimate key, and error key or None.

    """
    if value not in ("estimate", "estimate10", "estimate90"):
        return "", EXCEPTION_INVALID_KEY_ESTIMATE
    return value, None


def validate_use_actuals_value(value: str) -> tuple[int, str | None]:
    """Validate use actuals value.

    Arguments:
        value: The use actuals string ("0", "1", or "2").

    Returns:
        tuple[int, str | None]: The validated use actuals integer, and error key or None.

    """
    stripped = value.strip()
    if stripped not in ("0", "1", "2"):
        return 0, EXCEPTION_INVALID_USE_ACTUALS
    return int(stripped), None


def validate_export_limit_value(value: str) -> tuple[float, str | None]:
    """Validate site export limit value.

    Arguments:
        value: The export limit string.

    Returns:
        tuple[float, str | None]: The validated export limit float, and error key or None.

    """
    try:
        val = float(value)
    except ValueError:
        return 0.0, EXCEPTION_INVALID_EXPORT_LIMIT
    if val < 0.0 or val > 100.0:
        return 0.0, EXCEPTION_INVALID_EXPORT_LIMIT
    return val, None
