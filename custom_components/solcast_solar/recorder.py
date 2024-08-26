"""Integration platform for recorder."""

# pylint: disable=C0304, E0401, W0613

from __future__ import annotations

from homeassistant.core import HomeAssistant, callback


@callback
def exclude_attributes(hass: HomeAssistant) -> set[str]:
    """Exclude potentially large attributes from being recorded in the database."""
    return {"detailedForecast", "detailedHourly", "hard_limit"}