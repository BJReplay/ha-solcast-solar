"""Days far below the usual share of the estimated actuals, as after curtailment, an outage or snow, are left out."""

import copy
from datetime import UTC, datetime as dt, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from homeassistant.components.solcast_solar.const import (
    ADVANCED_AUTOMATED_DAMPENING_ELEVATION_ADJUSTMENT,
    ADVANCED_OPTIONS,
    DEFAULT,
    ESTIMATE,
    EXPORT_LIMITING,
    FORECASTS,
    GENERATION,
    LAST_UPDATED,
    PERIOD_START,
    RESOURCE_ID,
    SITE_INFO,
    VERSION,
)
from homeassistant.components.solcast_solar.dampen import Dampening
from homeassistant.components.solcast_solar.dates import DateTimeHelper
from homeassistant.components.solcast_solar.forecast import ForecastQuery

NOON = timedelta(hours=12)


def _dampening(generated: list[float]) -> tuple[Dampening, list[dt]]:
    """Return a dampening for one day per value: an estimated actual of 1 kWh at noon, and the kWh generated then."""
    api = MagicMock()
    api.tz = UTC
    api.dt_helper = DateTimeHelper(UTC)
    api.options = SimpleNamespace(auto_dampen=True, get_actuals=True, tz=UTC, exclude_sites=[])
    api.advanced_options = {key: copy.deepcopy(value[DEFAULT]) for key, value in ADVANCED_OPTIONS.items() if DEFAULT in value}
    api.advanced_options[ADVANCED_AUTOMATED_DAMPENING_ELEVATION_ADJUSTMENT] = False
    api.sites = [{RESOURCE_ID: "site"}]
    api.query = ForecastQuery(api)
    today = api.dt_helper.day_start_utc()
    days = [today - timedelta(days=len(generated) - day) for day in range(len(generated))]
    estimated = [{PERIOD_START: day + NOON, ESTIMATE: 2.0} for day in days]  # 2 kW for half an hour is 1 kWh
    api.data_actuals = {SITE_INFO: {"site": {FORECASTS: estimated}}}
    dampening = Dampening(api)
    dampening.data_generation = {
        LAST_UPDATED: today,
        VERSION: 1,
        GENERATION: [{PERIOD_START: day + NOON, GENERATION: kwh, EXPORT_LIMITING: False} for day, kwh in zip(days, generated, strict=True)],
    }
    return dampening, days


async def test_curtailed_day_left_out() -> None:
    """The roof usually generates its estimated actual, on the fourth day only 30 % of it: below 60 % of usual, left out."""
    dampening, days = _dampening([1.0, 1.0, 1.0, 0.3, 1.0])

    assert dampening.curtailed_days() == {days[3]}
    _, _, generation, _ = await dampening.prepare_data()
    assert sorted(generation) == [days[0] + NOON, days[1] + NOON, days[2] + NOON, days[4] + NOON]


async def test_curtailed_days_found_when_they_are_many() -> None:
    """Three of five days at 20 to 30 %, as after a week with a full battery: compared with the good days, all three go."""
    dampening, days = _dampening([0.2, 1.0, 0.25, 1.0, 0.3])

    assert dampening.curtailed_days() == {days[0], days[2], days[4]}


async def test_shaded_roof_keeps_its_days() -> None:
    """A shaded roof usually generates 40 % of its estimated actual, so 35 % is a normal day for it (the limit is 24 %)."""
    dampening, _ = _dampening([0.4, 0.4, 0.35, 0.4, 0.4])

    assert dampening.curtailed_days() == set()


async def test_excluded_rooftop_not_counted() -> None:
    """A rooftop excluded from the totals has no generation entity, so its estimated actuals do not lower the share."""
    dampening, days = _dampening([1.0, 1.0, 1.0, 1.0, 1.0])
    dampening.api.sites.append({RESOURCE_ID: "remote"})
    dampening.api.options.exclude_sites = ["remote"]
    remote = [{PERIOD_START: day + NOON, ESTIMATE: 2.0} for day in days[:2]]  # Counted, it would halve the first two days
    dampening.api.data_actuals[SITE_INFO]["remote"] = {FORECASTS: remote}

    assert dampening.curtailed_days() == set()


async def test_export_limited_intervals_not_counted() -> None:
    """A sunny day held at the export limit at noon: only its other interval counts, and that one is normal, so the day stays.

    Counted, the limited half hour (0.1 of 1 kWh) would pull the day to 55 % of its estimated actuals, below the 60 % limit.
    """
    dampening, days = _dampening([1.0, 1.0, 1.0, 1.0, 0.1])
    dampening.data_generation[GENERATION][-1][EXPORT_LIMITING] = True
    morning = days[4] + NOON - timedelta(minutes=30)
    dampening.data_generation[GENERATION].append({PERIOD_START: morning, GENERATION: 1.0, EXPORT_LIMITING: False})
    dampening.api.data_actuals[SITE_INFO]["site"][FORECASTS].append({PERIOD_START: morning, ESTIMATE: 2.0})

    assert dampening.curtailed_days() == set()
