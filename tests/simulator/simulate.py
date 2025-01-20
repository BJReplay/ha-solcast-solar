"""Simulated data for Solcast Solar integration."""

import datetime
from datetime import datetime as dt, timedelta
from typing import Any
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
    "no_sites": {
        "sites": [],
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


class SimulatedSolcast:
    """Simulated Solcast API."""

    def __init__(self) -> None:
        """Initialize the API."""
        self.timezone: ZoneInfo = TIMEZONE
        self.cached_actuals = {}
        self.cached_forecasts = {}

    def raw_get_sites(self, api_key) -> dict[str, Any] | None:
        """Return sites for an API key."""

        sites = API_KEY_SITES.get(api_key, {})
        meta = {
            "page_count": 1,
            "current_page": 1,
            "total_records": len(API_KEY_SITES.get(api_key, {}).get("sites", [])),
        }
        if meta["total_records"] is None:
            meta["total_records"] = 0
        return sites | meta if sites is not None else None

    def raw_get_site_estimated_actuals(
        self, site_id: str, api_key: str, hours: int, prefix: str = "pv_estimate", period_end: dt | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        """Return simulated estimated actials for a site.

        The real Solcast API does not return values for estimate 10/90, but the simulator does.
        This is to enable testing of the integration.
        """

        sites = API_KEY_SITES.get(api_key, {}).get("sites")
        if sites is None:
            sites = {}
        site = next((site for site in sites if site.get("resource_id") == site_id), None)
        if not site:
            return {}
        period_end = self.get_period(dt.now(datetime.UTC), timedelta(hours=hours) * -1) if period_end is None else period_end

        lookup = f"{api_key} {site_id} {hours} {period_end}"
        if cached := self.cached_actuals.get(lookup):
            return cached

        self.cached_actuals[lookup] = {
            "estimated_actuals": [
                {
                    "period_end": (period_end + timedelta(minutes=minute * 30)).isoformat(),
                    "period": "PT30M",
                    prefix: self.__pv_interval(site["capacity"], FORECAST, period_end, minute),
                    # The Solcast API does not return these values, but the simulator does
                    prefix + "10": self.__pv_interval(site["capacity"], FORECAST_10, period_end, minute),
                    prefix + "90": self.__pv_interval(site["capacity"], FORECAST_90, period_end, minute),
                }
                for minute in range((hours + 1) * 2)
            ],
        }
        return self.cached_actuals[lookup]

    def raw_get_site_forecasts(
        self, site_id: str, api_key: str, hours: int, prefix: str = "pv_estimate"
    ) -> dict[str, list[dict[str, Any]]]:
        """Return simulated forecasts for a site."""

        sites = API_KEY_SITES.get(api_key, {}).get("sites")
        if sites is None:
            sites = {}
        site = next((site for site in sites if site.get("resource_id") == site_id), None)
        if not site:
            return {}
        period_end = self.get_period(dt.now(datetime.UTC), timedelta(minutes=30))

        lookup = f"{api_key} {site_id} {hours} {period_end}"
        if cached := self.cached_forecasts.get(lookup):
            return cached

        self.cached_forecasts[lookup] = {
            "forecasts": [
                {
                    "period_end": (period_end + timedelta(minutes=minute * 30)).isoformat(),
                    "period": "PT30M",
                    prefix: self.__pv_interval(site["capacity"], FORECAST, period_end, minute),
                    prefix + "10": self.__pv_interval(site["capacity"], FORECAST_10, period_end, minute),
                    prefix + "90": self.__pv_interval(site["capacity"], FORECAST_90, period_end, minute),
                }
                for minute in range(hours * 2 + 1)  # Solcast usually returns one more forecast, not an even number of intervals
            ],
        }
        return self.cached_forecasts[lookup]

    def set_time_zone(self, timezone: ZoneInfo) -> None:
        """Set the time zone."""

        self.timezone = timezone

    def get_period(self, period: dt, delta: timedelta) -> dt:
        """Return the start period and factors for the current time."""
        return period.replace(minute=(int(period.minute / 30) * 30), second=0, microsecond=0) + delta

    def __pv_interval(self, site_capacity: float, estimate: float, period_end: dt, minute: int) -> float:
        """Calculate value for a single interval."""
        return round(
            site_capacity
            * estimate
            * GENERATION_FACTOR[
                int(
                    (period_end + timedelta(minutes=minute * 30)).astimezone(self.timezone).hour * 2
                    + (period_end + timedelta(minutes=minute * 30)).astimezone(self.timezone).minute / 30
                )
            ],
            4,
        )
