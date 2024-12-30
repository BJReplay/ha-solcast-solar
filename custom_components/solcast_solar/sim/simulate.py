"""Simulated data for Solcast Solar integration."""

import datetime
from datetime import datetime as dt, timedelta
from zoneinfo import ZoneInfo

API_KEY_SITES = {
    "1": {
        "sites": [
            {
                "resource_id": "1111-1111-1111-1111",
                "name": "First Site",
                "latitude": -11.11111,
                "longitude": 111.1111,
                "install_date": "2024-01-01T00:00:00+00:00",
                "loss_factor": 0.99,
                "capacity": 5.0,
                "capacity_dc": 6.2,
                "azimuth": 90,
                "tilt": 30,
                "location": "Downunder",
            },
            {
                "resource_id": "2222-2222-2222-2222",
                "name": "Second Site",
                "latitude": -11.11111,
                "longitude": 111.1111,
                "install_date": "2024-01-01T00:00:00+00:00",
                "loss_factor": 0.99,
                "capacity": 3.0,
                "capacity_dc": 4.2,
                "azimuth": 90,
                "tilt": 30,
                "location": "Downunder",
            },
        ],
        "counter": 0,
    },
    "2": {
        "sites": [
            {
                "resource_id": "3333-3333-3333-3333",
                "name": "Third Site",
                "latitude": -11.11111,
                "longitude": 111.1111,
                "install_date": "2024-01-01T00:00:00+00:00",
                "loss_factor": 0.99,
                "capacity": 3.0,
                "capacity_dc": 3.5,
                "azimuth": 90,
                "tilt": 30,
                "location": "Downunder",
            },
        ],
        "counter": 0,
    },
    "3": {
        "sites": [
            {
                "resource_id": "4444-4444-4444-4444",
                "name": "Fourth Site",
                "latitude": -11.11111,
                "longitude": 111.1111,
                "install_date": "2024-01-01T00:00:00+00:00",
                "loss_factor": 0.99,
                "capacity": 4.5,
                "capacity_dc": 5.0,
                "azimuth": 90,
                "tilt": 30,
                "location": "Downunder",
            },
            {
                "resource_id": "5555-5555-5555-5555",
                "name": "Fifth Site",
                "latitude": -11.11111,
                "longitude": 111.1111,
                "install_date": "2024-01-01T00:00:00+00:00",
                "loss_factor": 0.99,
                "capacity": 3.2,
                "capacity_dc": 3.7,
                "azimuth": 90,
                "tilt": 30,
                "location": "Downunder",
            },
            {
                "resource_id": "6666-6666-6666-6666",
                "name": "Sixth Site",
                "latitude": -11.11111,
                "longitude": 111.1111,
                "install_date": "2024-01-01T00:00:00+00:00",
                "loss_factor": 0.99,
                "capacity": 4.2,
                "capacity_dc": 4.8,
                "azimuth": 90,
                "tilt": 30,
                "location": "Downunder",
            },
        ],
        "counter": 0,
    },
    "aaaa-aaaa": {
        "sites": [
            {
                "resource_id": "7777-7777-7777-7777",
                "name": "Seventh Site",
                "latitude": -11.11111,
                "longitude": 111.1111,
                "install_date": "2024-01-01T00:00:00+00:00",
                "loss_factor": 0.99,
                "capacity": 3.0,
                "capacity_dc": 3.5,
                "azimuth": 90,
                "tilt": 30,
                "location": "Downunder",
            },
        ],
        "counter": 0,
    },
}
FORECAST = 0.9
FORECAST_10 = 0.75
FORECAST_90 = 1.0
GENERATION_FACTOR = [
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0.01,
    0.025,
    0.04,
    0.075,
    0.11,
    0.17,
    0.26,
    0.38,
    0.52,
    0.65,
    0.8,
    0.9,
    0.97,
    1,
    1,
    0.97,
    0.9,
    0.8,
    0.65,
    0.52,
    0.38,
    0.26,
    0.17,
    0.11,
    0.075,
    0.04,
    0.025,
    0.01,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
]
TIMEZONE = ZoneInfo("Australia/Melbourne")


def get_period(period, delta):
    """Return the start period and factors for the current time."""
    return period.replace(minute=(int(period.minute / 30) * 30), second=0, microsecond=0) + delta


def set_time_zone(time_zone):
    """Set the time zone."""

    global TIMEZONE
    TIMEZONE = time_zone


def raw_get_sites(api_key):
    """Return sites for an API key."""

    sites = API_KEY_SITES[api_key]
    meta = {
        "page_count": 1,
        "current_page": 1,
        "total_records": 1,
    }
    return sites | meta


def pv_interval(site_capacity, estimate, period_end, minute):
    """Calculate value for a single interval."""
    return round(
        site_capacity
        * estimate
        * GENERATION_FACTOR[
            int(
                (period_end + timedelta(minutes=minute * 30)).astimezone(TIMEZONE).hour * 2
                + (period_end + timedelta(minutes=minute * 30)).astimezone(TIMEZONE).minute / 30
            )
        ],
        4,
    )


def raw_get_site_estimated_actuals(site_id, api_key, hours, key="pv_estimate", period_end=None):
    """Return simulated estimated actials for a site.

    The real Solcast API does not return values for estimate 10/90, but the simulator does.
    This is to enable testing of the integration.
    """

    site = next((site for site in API_KEY_SITES[api_key]["sites"] if site["resource_id"] == site_id), None)
    period_end = get_period(dt.now(datetime.UTC), timedelta(hours=hours) * -1) if period_end is None else period_end
    return {
        "estimated_actuals": [
            {
                "period_end": (period_end + timedelta(minutes=minute * 30)).isoformat(),
                key: pv_interval(site["capacity"], FORECAST, period_end, minute),
                key + "10": pv_interval(site["capacity"], FORECAST_10, period_end, minute),
                key + "90": pv_interval(site["capacity"], FORECAST_90, period_end, minute),
                "period": "PT30M",
            }
            for minute in range((hours + 1) * 2)
        ],
    }


def raw_get_site_forecasts(site_id, api_key, hours, key="pv_estimate"):
    """Return simulated forecasts for a site."""

    site = next((site for site in API_KEY_SITES[api_key]["sites"] if site["resource_id"] == site_id), None)
    period_end = get_period(dt.now(datetime.UTC), timedelta(minutes=30))
    return {
        "forecasts": [
            {
                "period_end": (period_end + timedelta(minutes=minute * 30)).isoformat(),
                key: pv_interval(site["capacity"], FORECAST, period_end, minute),
                key + "10": pv_interval(site["capacity"], FORECAST_10, period_end, minute),
                key + "90": pv_interval(site["capacity"], FORECAST_90, period_end, minute),
                "period": "PT30M",
            }
            for minute in range(hours * 2 + 1)  # Solcast usually returns one more forecast, not an even number of intervals
        ],
    }
