"""Solcast forecast query and spline interpolation engine."""

# pylint: disable=pointless-string-statement

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime as dt, timedelta
import logging
import math
import time
from typing import TYPE_CHECKING, Any

from .const import (
    ADVANCED_HISTORY_MAX_DAYS,
    ALL,
    ANALYSIS,
    DATA_CORRECT,
    DAY_NAME,
    DETAILED_FORECAST,
    DETAILED_HOURLY,
    DT_DAYNAME,
    ESTIMATE,
    ESTIMATE10,
    ESTIMATE90,
    NAME,
    PERIOD_START,
    RESOURCE_ID,
    SITE_ATTRIBUTE_AZIMUTH,
    SITE_ATTRIBUTE_CAPACITY,
    SITE_ATTRIBUTE_CAPACITY_DC,
    SITE_ATTRIBUTE_INSTALL_DATE,
    SITE_ATTRIBUTE_LATITUDE,
    SITE_ATTRIBUTE_LONGITUDE,
    SITE_ATTRIBUTE_LOSS_FACTOR,
    SITE_ATTRIBUTE_TAGS,
    SITE_ATTRIBUTE_TILT,
)
from .util import HistoryType, cubic_interp

if TYPE_CHECKING:
    from .solcastapi import SolcastApi

_LOGGER = logging.getLogger(__name__)


class ForecastQuery:
    """Forecast query and spline interpolation engine."""

    def __init__(self, api: SolcastApi) -> None:
        """Initialise the forecast query engine.

        Arguments:
            api: The parent SolcastApi instance.
        """
        self.api = api
        self._forecasts_moment: dict[str, dict[str, list[float]]] = {}
        self._forecasts_remaining: dict[str, dict[str, list[float]]] = {}
        self._spline_period: list[int] = list(range(0, 90000, 1800))

    def get_rooftop_site_total_today(self, site: str) -> float | None:
        """Return total kW for today for a site.

        Arguments:
            site (str): A Solcast site ID.

        Returns:
            float | None: Total site kW forecast today.
        """
        if self.api.tally.get(site) is None:
            _LOGGER.warning("Site total kW forecast today is currently unavailable for %s", site)
        return self.api.tally.get(site)

    async def get_forecast_list(self, *args: Any) -> tuple[dict[str, Any], ...]:
        """Get forecasts.

        Arguments:
            args (tuple): [0] (dt) = from timestamp, [1] (dt) = to timestamp, [2] = site, [3] (bool) = dampened or un-dampened.

        Returns:
            tuple(dict[str, Any], ...): Forecasts representing the range specified.
        """

        if args[2] == ALL:
            data_forecasts = self.api.data_forecasts if not args[3] else self.api.data_forecasts_undampened
        else:
            data_forecasts = self.api.site_data_forecasts[args[2]] if not args[3] else self.api.site_data_forecasts_undampened[args[2]]
        start_index, end_index = self.get_list_slice(data_forecasts, args[0], args[1], search_past=True)
        if start_index == 0 and end_index == 0:
            # Range could not be found
            raise ValueError(
                f"Range is invalid {args[0]} to {args[1]}, earliest forecast is {data_forecasts[0][PERIOD_START]}, latest forecast is {data_forecasts[-1][PERIOD_START]}"
            )
        forecast_slice = data_forecasts[start_index:end_index]

        return tuple({**data, PERIOD_START: data[PERIOD_START].astimezone(self.api.tz)} for data in forecast_slice)

    async def get_estimate_list(self, *args: Any) -> tuple[dict[str, Any], ...]:
        """Get estimated actuals.

        Arguments:
            args (tuple): [0] (dt) = from timestamp, [1] (dt) = to timestamp, [2] (bool) = dampened or un-dampened (default undampened).

        Returns:
            tuple(dict[str, Any], ...): Estimated actuals representing the range specified.
        """

        data = self.api.data_estimated_actuals if args[2] else self.api.data_estimated_actuals_dampened
        start_index, end_index = self.get_list_slice(data, args[0], args[1], search_past=True)
        if start_index == 0 and end_index == 0:
            # Range could not be found
            raise ValueError("Range is invalid")
        estimate_slice = data[start_index:end_index]

        return tuple({**data, PERIOD_START: data[PERIOD_START].astimezone(self.api.tz)} for data in estimate_slice)

    def get_rooftop_site_extra_data(self, site: str = "") -> dict[str, Any]:
        """Return information about a site.

        Arguments:
            site (str): An optional Solcast site ID.

        Returns:
            dict: Site attributes that have been configured at solcast.com.
        """
        target_site = tuple(_site for _site in self.api.sites if _site[RESOURCE_ID] == site)
        _site: dict[str, Any] = target_site[0]
        result = {
            NAME: _site.get(NAME),
            RESOURCE_ID: _site.get(RESOURCE_ID),
            SITE_ATTRIBUTE_CAPACITY: _site.get(SITE_ATTRIBUTE_CAPACITY),
            SITE_ATTRIBUTE_CAPACITY_DC: _site.get(SITE_ATTRIBUTE_CAPACITY_DC),
            SITE_ATTRIBUTE_LONGITUDE: _site.get(SITE_ATTRIBUTE_LONGITUDE),
            SITE_ATTRIBUTE_LATITUDE: _site.get(SITE_ATTRIBUTE_LATITUDE),
            SITE_ATTRIBUTE_AZIMUTH: _site.get(SITE_ATTRIBUTE_AZIMUTH),
            SITE_ATTRIBUTE_TILT: _site.get(SITE_ATTRIBUTE_TILT),
            SITE_ATTRIBUTE_INSTALL_DATE: _site.get(SITE_ATTRIBUTE_INSTALL_DATE),
            SITE_ATTRIBUTE_LOSS_FACTOR: _site.get(SITE_ATTRIBUTE_LOSS_FACTOR),
            SITE_ATTRIBUTE_TAGS: _site.get(SITE_ATTRIBUTE_TAGS),
        }
        return {k: v for k, v in result.items() if v is not None}

    def get_forecast_day(self, future_day: int) -> dict[str, Any] | None:
        """Return forecast data for the Nth day ahead.

        Arguments:
            future_day (int): A day (0 = today, 1 = tomorrow, etc., with a maximum of day FORECAST_DAYS - 1).

        Returns:
            dict: Includes the day name, whether there are issues with the data in terms of completeness,
            and detailed half-hourly forecast (and site breakdown if that option is configured), and a
            detailed hourly forecast (and site breakdown if that option is configured).
        """
        no_data_error = True

        def build_hourly(forecast: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [
                {
                    PERIOD_START: forecast[index][PERIOD_START],
                    ESTIMATE: round(
                        (forecast[index][ESTIMATE] + forecast[index + 1][ESTIMATE]) / 2,
                        4,
                    ),
                    ESTIMATE10: round(
                        (forecast[index][ESTIMATE10] + forecast[index + 1][ESTIMATE10]) / 2,
                        4,
                    ),
                    ESTIMATE90: round(
                        (forecast[index][ESTIMATE90] + forecast[index + 1][ESTIMATE90]) / 2,
                        4,
                    ),
                }
                for index in range(1 if len(forecast) % 2 == 1 else 0, len(forecast), 2)
                if len(forecast) > 0
            ]

        def get_start_and_end(forecasts: list[dict[str, Any]]) -> tuple[int, int, dt, dt]:
            start_utc = self.api.dt_helper.day_start_utc(future=future_day)
            start, _ = self.get_list_slice(forecasts, start_utc)
            end_utc = min(
                self.api.dt_helper.day_start_utc(future=future_day + 1), forecasts[-1][PERIOD_START]
            )  # Don't go past the last forecast.
            end, _ = self.get_list_slice(forecasts, end_utc)
            if not start:
                # Data is missing, so adjust the start time to the first available forecast.
                start, _ = self.get_list_slice(forecasts, forecasts[0][PERIOD_START])
                start_utc = forecasts[0][PERIOD_START]
            return start, end, start_utc, end_utc

        start_index, end_index, start_utc, _ = get_start_and_end(self.api.data_forecasts)

        site_data_forecast: dict[str, list[dict[str, Any]]] = {}
        forecast_slice = self.api.data_forecasts[start_index:end_index]
        if self.api.options.attr_brk_site_detailed:
            for site in self.api.sites:
                site_start_index, site_end_index, _, _ = get_start_and_end(self.api.site_data_forecasts[site[RESOURCE_ID]])
                site_data_forecast[site[RESOURCE_ID]] = self.api.site_data_forecasts[site[RESOURCE_ID]][site_start_index:site_end_index]

        _tuple = [{**forecast, PERIOD_START: forecast[PERIOD_START].astimezone(self.api.tz)} for forecast in forecast_slice]
        tuples: dict[str, list[dict[str, Any]]] = {}
        if self.api.options.attr_brk_site_detailed:
            for site in self.api.sites:
                tuples[site[RESOURCE_ID]] = [
                    {
                        **forecast,
                        PERIOD_START: forecast[PERIOD_START].astimezone(self.api.tz),
                    }
                    for forecast in site_data_forecast[site[RESOURCE_ID]]
                ]

        if len(_tuple) < 48:
            no_data_error = False

        hourly_tuple: list[dict[str, Any]] = []
        hourly_tuples: dict[str, list[dict[str, Any]]] = {}
        if self.api.options.attr_brk_hourly:
            hourly_tuple = build_hourly(_tuple)
            if self.api.options.attr_brk_site_detailed:
                hourly_tuples = {}
                for site in self.api.sites:
                    hourly_tuples[site[RESOURCE_ID]] = build_hourly(tuples[site[RESOURCE_ID]])

        estimate10_kwh = 0.0
        estimate90_kwh = 0.0
        spread_kwh = 0.0
        confidence = 1.0
        confidence_intervals = []
        if _tuple:
            estimate10_kwh = round(0.5 * sum(p[ESTIMATE10] for p in _tuple), 4)
            estimate90_kwh = round(0.5 * sum(p[ESTIMATE90] for p in _tuple), 4)
            spread_kwh = round(estimate90_kwh - estimate10_kwh, 4)
            confidence = round(1.0 - spread_kwh / estimate90_kwh, 4) if estimate90_kwh > 0 else 1.0
            confidence_intervals = [
                {
                    PERIOD_START: p[PERIOD_START],
                    "spread_kwh": round(0.5 * (p[ESTIMATE90] - p[ESTIMATE10]), 4),
                    "confidence": round(1.0 - 0.5 * (p[ESTIMATE90] - p[ESTIMATE10]) / (0.5 * p[ESTIMATE90]), 4)
                    if p[ESTIMATE90] > 0
                    else 1.0,
                }
                for p in _tuple
            ]

        result: dict[str, Any] = {
            DAY_NAME: start_utc.astimezone(self.api.tz).strftime(DT_DAYNAME),
            DATA_CORRECT: no_data_error,
            ANALYSIS: {
                "estimate10_kwh": estimate10_kwh,
                "estimate90_kwh": estimate90_kwh,
                "spread_kwh": spread_kwh,
                "confidence": confidence,
                "intervals": confidence_intervals,
            },
        }
        if self.api.options.attr_brk_halfhourly:
            result[DETAILED_FORECAST] = _tuple
            if self.api.options.attr_brk_site_detailed:
                for site in self.api.sites:
                    result[f"{DETAILED_FORECAST}_{site[RESOURCE_ID].replace('-', '_')}"] = tuples[site[RESOURCE_ID]]
        if self.api.options.attr_brk_hourly:
            result[DETAILED_HOURLY] = hourly_tuple
            if self.api.options.attr_brk_site_detailed:
                for site in self.api.sites:
                    result[f"{DETAILED_HOURLY}_{site[RESOURCE_ID].replace('-', '_')}"] = hourly_tuples[site[RESOURCE_ID]]
        return result

    def get_forecast_n_hour(
        self,
        n_hour: int,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> int | None:
        """Return forecast for the Nth hour.

        Arguments:
            n_hour (int): An hour into the future, or the current hour (0 = current and 1 = next hour are used).
            site (str): An optional Solcast site ID, used to build site breakdown attributes.
            forecast_confidence (str): An optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            int | None - A forecast for an hour period as Wh (either used for a sensor or its attributes).
        """
        start_utc = self.api.dt_helper.hour_start_utc() + timedelta(hours=n_hour)
        end_utc = start_utc + timedelta(hours=1)
        estimate = self._get_forecast_pv_estimates(start_utc, end_utc, site=site, forecast_confidence=forecast_confidence)
        return round(500 * estimate) if estimate is not None else None

    def get_forecast_custom_hours(
        self,
        n_hours: int,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> int | None:
        """Return forecast for the next N hours.

        Arguments:
            n_hours (int): A number of hours into the future.
            site (str): An optional Solcast site ID, used to build site breakdown attributes.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            int | None - A forecast for a multiple hour period as Wh (either used for a sensor or its attributes).
        """
        start_utc = self.api.dt_helper.now_utc()
        end_utc = start_utc + timedelta(hours=n_hours)
        remaining = self._get_forecast_pv_remaining(
            start_utc,
            end_utc=end_utc,
            site=site,
            forecast_confidence=forecast_confidence,
        )
        return round(1000 * remaining) if remaining is not None else None

    def get_power_n_minutes(
        self,
        n_mins: int,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> int | None:
        """Return expected power generation in the next N minutes.

        Arguments:
            n_mins (int): A number of minutes into the future.
            site (str): An optional Solcast site ID, used to build site breakdown attributes.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            int | None: A power forecast in N minutes as W (either used for a sensor or its attributes).
        """
        time_utc = self.api.dt_helper.now_utc() + timedelta(minutes=n_mins)
        forecast = self._get_forecast_pv_moment(time_utc, site=site, forecast_confidence=forecast_confidence)
        return round(1000 * forecast) if forecast is not None else None

    def get_peak_power_day(
        self,
        n_day: int,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> int | None:
        """Return maximum forecast Watts for N days ahead.

        Arguments:
            n_day (int): A number representing a day (0 = today, 1 = tomorrow, etc., with a maximum of day FORECAST_DAYS - 1).
            site (str): An optional Solcast site ID, used to build site breakdown attributes.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            int | None: An expected peak generation for a given day as Watts.
        """
        forecast_confidence = self.api.use_forecast_confidence if forecast_confidence is None else forecast_confidence
        start_utc = self.api.dt_helper.day_start_utc(future=n_day)
        end_utc = self.api.dt_helper.day_start_utc(future=n_day + 1)
        result = self._get_max_forecast_pv_estimate(start_utc, end_utc, site=site, forecast_confidence=forecast_confidence)
        return int(round(1000 * result[forecast_confidence])) if result is not None else None

    def get_peak_time_day(
        self,
        n_day: int,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> dt | None:
        """Return hour of max generation for site N days ahead.

        Arguments:
            n_day (int): A number representing a day (0 = today, 1 = tomorrow, etc., with a maximum of day FORECAST_DAYS - 1).
            site (str): An optional Solcast site ID, used to build site breakdown attributes.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            dt | None: The date and time of expected peak generation for a given day.
        """
        start_utc = self.api.dt_helper.day_start_utc(future=n_day)
        end_utc = self.api.dt_helper.day_start_utc(future=n_day + 1)
        result = self._get_max_forecast_pv_estimate(start_utc, end_utc, site=site, forecast_confidence=forecast_confidence)
        return result[PERIOD_START].astimezone(self.api.tz) if result is not None else None

    def get_forecast_remaining_today(self, n: int = 0, site: str | None = None, forecast_confidence: str | None = None) -> float | None:
        """Return remaining forecasted production for today.

        Arguments:
            n (int): Not used.
            site (str): An optional Solcast site ID, used to build site breakdown attributes.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            float | None: The expected remaining solar generation for the current day as kWh.
        """
        start_utc = self.api.dt_helper.now_utc()
        end_utc = self.api.dt_helper.day_start_utc(future=1)
        remaining = self._get_forecast_pv_remaining(
            start_utc,
            end_utc=end_utc,
            site=site,
            forecast_confidence=forecast_confidence,
        )
        return round(remaining, 4) if remaining is not None else None

    def get_total_energy_forecast_day(
        self,
        n_day: int,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> float | None:
        """Return forecast production total for N days ahead.

        Arguments:
            n_day (int): A day (0 = today, 1 = tomorrow, etc., with a maximum of day FORECAST_DAYS - 1).
            site (str): An optional Solcast site ID, used to build site breakdown attributes.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            float | None: The forecast total solar generation for a given day as kWh.
        """
        start_utc = self.api.dt_helper.day_start_utc(future=n_day)
        end_utc = self.api.dt_helper.day_start_utc(future=n_day + 1)
        estimate = self._get_forecast_pv_estimates(start_utc, end_utc, site=site, forecast_confidence=forecast_confidence)
        return round(0.5 * estimate, 4) if estimate is not None else None

    def get_forecast_attributes(self, get_forecast_value: Any, n: int = 0) -> dict[str, Any]:
        """Return forecast attributes for the 'n' forecast value for all sites and individual sites.

        Arguments:
            get_forecast_value (function): A function to get the forecast value.
            n (int): A minute, hour or day into the future.

        Returns:
            dict: Sensor attributes for the period, depending on the configured options.
        """
        result: dict[str, Any] = {}
        if self.api.options.attr_brk_site:
            for site in self.api.sites:
                result[site[RESOURCE_ID].replace("-", "_")] = get_forecast_value(n, site=site[RESOURCE_ID])
                for forecast_confidence in self.api.estimate_set:
                    result[forecast_confidence.replace("pv_", "") + "_" + site[RESOURCE_ID].replace("-", "_")] = get_forecast_value(
                        n,
                        site=site[RESOURCE_ID],
                        forecast_confidence=forecast_confidence,
                    )
        for forecast_confidence in self.api.estimate_set:
            result[forecast_confidence.replace("pv_", "")] = get_forecast_value(n, forecast_confidence=forecast_confidence)
        return result

    def get_list_slice(
        self,
        data: list[dict[str, Any]],
        start_utc: dt,
        end_utc: dt | None = None,
        search_past: bool = False,
    ) -> tuple[int, int]:
        """Return forecast data list slice start and end indexes for interval.

        Arguments:
            data (list): The data to search, either actual or forecast total data or site breakdown data.
            start_utc (datetime): Start of time period requested in UTC.
            end_utc (datetime): Optional end of time period requested in UTC (if omitted, thirty minutes beyond start).
            search_past (bool): Optional flag to indicate that past periods should be searched.

        Returns:
            tuple(int, int): List index of start of period, list index of end of period.
        """
        if end_utc is None:
            end_utc = start_utc + timedelta(seconds=1800)
        start_index = -1
        end_index = len(data)
        for test_index in range(0 if search_past else self._calc_forecast_start_index(data), end_index):
            forecast_period = data[test_index][PERIOD_START]
            # After the last segment.
            if end_utc <= forecast_period:
                end_index = test_index
                break
            # First segment.
            if start_utc < forecast_period + timedelta(seconds=1800) and start_index == -1:
                start_index = test_index
        # Never found.
        if start_index == -1:
            start_index = 0
            end_index = 0
        return start_index, end_index

    def _get_spline(
        self,
        spline: dict[str, list[float]],
        start: int,
        xx: list[int],
        data: list[dict[str, Any]],
        confidences: list[str],
        reducing: bool = False,
    ) -> None:
        """Build a forecast spline, momentary or day reducing.

        Arguments:
            spline (dict): The data structure to populate.
            start (int): The starting index of the data slice.
            xx (list): Seconds intervals of the day, one for each 5-minute interval (plus another hours worth).
            data (list): The data structure used to build the spline, either total data or site breakdown data.
            confidences (list): The forecast types to build, pv_estimate, pv_estimate10 or pv_estimate90.
            reducing (bool): A flag to indicate whether a momentary power spline should be built, or a reducing energy spline, default momentary.
        """
        for forecast_confidence in confidences:
            try:
                spline_period_length = len(xx) // 6
                y = [data[start + index][forecast_confidence] for index in range(spline_period_length)]
                if reducing:
                    # Build a decreasing set of forecasted values instead.
                    y = [0.5 * sum(y[index:]) for index in range(spline_period_length)]
                spline[forecast_confidence] = cubic_interp(xx, self._spline_period[-spline_period_length:], y)
                spline[forecast_confidence] = [0] * (len(self._spline_period) - len(xx)) + spline[forecast_confidence]
                self._sanitise_spline(spline, forecast_confidence, xx, y, reducing=reducing)
                continue
            except IndexError:
                pass
            spline[forecast_confidence] = [0] * (len(self._spline_period) * 6)

    def _sanitise_spline(
        self,
        spline: dict[str, list[float]],
        forecast_confidence: str,
        xx: list[int],
        y: list[float],
        reducing: bool = False,
    ) -> None:
        """Ensure that no negative values are returned, and also shifts the spline to account for half-hour average input values.

        Arguments:
            spline (dict): The data structure to sanitise.
            forecast_confidence (str): The forecast type to sanitise, pv_estimate, pv_estimate10 or pv_estimate90.
            xx (list): Seconds intervals of the day, one for each 5-minute interval (plus another hours worth).
            y (list): The period momentary or reducing input data used for the spline calculation.
            reducing (bool): A flag to indicate whether the spline is momentary power, or reducing energy, default momentary.
        """
        offset = int(xx[0] / 300)  # To cater for less intervals than the spline period
        for interval in xx:
            spline_index = int(interval / 300) - offset  # Every five minutes
            # Suppress negative values.
            if math.copysign(1.0, spline[forecast_confidence][spline_index]) < 0:
                spline[forecast_confidence][spline_index] = 0.0
            # Suppress spline bounce.
            if reducing:
                if (
                    spline_index + 1 <= len(xx) - 1
                    and spline[forecast_confidence][spline_index + 1] > spline[forecast_confidence][spline_index]
                ):
                    spline[forecast_confidence][spline_index + 1] = spline[forecast_confidence][spline_index]
            else:
                y_index = int(math.floor(interval / 1800))  # Every half hour
                if y_index + 1 <= len(y) - 1 and y[y_index] == 0 and y[y_index + 1] == 0:
                    spline[forecast_confidence][spline_index] = 0.0
        # Shift right by fifteen minutes because 30-minute averages, padding as appropriate.
        if reducing:
            spline[forecast_confidence] = ([spline[forecast_confidence][0]] * 3) + spline[forecast_confidence]
        else:
            spline[forecast_confidence] = ([0] * 3) + spline[forecast_confidence]

    def _build_spline(self, variant: dict[str, dict[str, list[float]]], reducing: bool = False) -> None:
        """Build cubic splines for interpolated inter-interval momentary or reducing estimates.

        Arguments:
            variant (dict[str, list[float]): The variant variable to populate, _forecasts_moment or _forecasts_reducing.
            reducing (bool): A flag to indicate whether the spline is momentary power, or reducing energy, default momentary.
        """
        df = [self.api.use_forecast_confidence]
        for enabled, estimate in (
            (self.api.options.attr_brk_estimate, ESTIMATE),
            (self.api.options.attr_brk_estimate10, ESTIMATE10),
            (self.api.options.attr_brk_estimate90, ESTIMATE90),
        ):
            if enabled and estimate not in df:
                df.append(estimate)

        start: int = 0
        end: int = 0
        xx: list[int] = []

        def get_start_and_end(forecasts: list[dict[str, Any]]) -> tuple[int, int, list[int]]:
            try:
                start, end = self.get_list_slice(forecasts, self.api.dt_helper.day_start_utc())  # Get start of day index.
                if start:
                    xx = list(range(0, 1800 * len(self._spline_period), 300))
                else:
                    # Data is missing at the start of the set, so adjust the start time to the first available forecast.
                    start, end = self.get_list_slice(forecasts, forecasts[0][PERIOD_START], self.api.dt_helper.day_start_utc(future=1))
                    xx = list(range(1800 * (48 - (end - start)), 1800 * len(self._spline_period), 300))
            except IndexError:
                start = 0
                end = 0
                xx = []
            return start, end, xx

        variant[ALL] = {}
        start, end, xx = get_start_and_end(self.api.data_forecasts)
        if end:
            self._get_spline(variant[ALL], start, xx, self.api.data_forecasts, df, reducing=reducing)
        if self.api.options.attr_brk_site:
            for site in self.api.sites:
                variant[site[RESOURCE_ID]] = {}
                if self.api.site_data_forecasts.get(site[RESOURCE_ID]):
                    start, end, xx = get_start_and_end(self.api.site_data_forecasts[site[RESOURCE_ID]])
                    if end:
                        self._get_spline(
                            variant[site[RESOURCE_ID]],
                            start,
                            xx,
                            self.api.site_data_forecasts[site[RESOURCE_ID]],
                            df,
                            reducing=reducing,
                        )

    async def _spline_moments(self) -> None:
        """Build the moments splines."""
        self._build_spline(self._forecasts_moment)

    async def _spline_remaining(self) -> None:
        """Build the descending splines."""
        self._build_spline(self._forecasts_remaining, reducing=True)

    async def recalculate_splines(self) -> None:
        """Recalculate both the moment and remaining splines."""
        start_time = time.time()
        await self._spline_moments()
        await self._spline_remaining()
        _LOGGER.debug("Task recalculate_splines took %.3f seconds", time.time() - start_time)

    def _get_moment(self, site: str | None, forecast_confidence: str | None, n_min: float) -> float | None:
        """Get a time value from a moment spline.

        Arguments:
            site (str | None): A Solcast site ID.
            forecast_confidence (str): The forecast type, pv_estimate, pv_estimate10 or pv_estimate90.
            n_min (float): Minute of the day.

        Returns:
            float | None: A splined forecasted value as kW.
        """
        variant: list[float] | None = self._forecasts_moment[ALL if site is None else site].get(
            self.api.use_forecast_confidence if forecast_confidence is None else forecast_confidence
        )
        offset = (
            (len(self._spline_period) * 6 - len(variant)) + 3 if variant is not None else 0
        )  # To cater for less intervals than the spline period
        return variant[int(n_min / 300) - offset] if variant and len(variant) > 0 else None

    def _get_remaining(self, site: str | None, forecast_confidence: str | None, n_min: float) -> float | None:
        """Get a remaining value at a given five-minute point from a reducing spline.

        Arguments:
            site (str | None): A Solcast site ID.
            forecast_confidence (str): The forecast type, pv_estimate, pv_estimate10 or pv_estimate90.
            n_min (float): The minute of the day.

        Returns:
            float | None: A splined forecasted remaining value as kWh.
        """
        variant: list[float] | None = self._forecasts_remaining[ALL if site is None else site].get(
            self.api.use_forecast_confidence if forecast_confidence is None else forecast_confidence
        )
        offset = (
            (len(self._spline_period) * 6 - len(variant)) + 3 if variant is not None else 0
        )  # To cater for less intervals than the spline period
        return variant[int(n_min / 300) - offset] if variant and len(variant) > 0 else None

    def _get_forecast_pv_remaining(
        self,
        start_utc: dt,
        end_utc: dt | None = None,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> float | None:
        """Return estimate remaining for a period.

        The start_utc and end_utc will be adjusted to the most recent five-minute period start. Where
        end_utc is present the forecasted remaining energy between the two datetime values is calculated.

        Arguments:
            start_utc (datetime): Start of time period in UTC.
            end_utc (datetime): Optional end of time period in UTC. If omitted then a result for the start_utc only is returned.
            site (str): Optional Solcast site ID, used to provide site breakdown.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            float | None: Energy forecast to be remaining for a period as kWh.
        """
        data = self.api.data_forecasts if site is None else self.api.site_data_forecasts[site]
        forecast_confidence = self.api.use_forecast_confidence if forecast_confidence is None else forecast_confidence
        start_utc = start_utc.replace(minute=math.floor(start_utc.minute / 5) * 5)
        start_index, end_index = self.get_list_slice(  # Get start and end indexes for the requested range.
            data, start_utc, end_utc
        )
        if (start_index == 0 and end_index == 0) or data[len(data) - 1][PERIOD_START] < end_utc:
            return None  # Set sensor to unavailable
        day_start = self.api.dt_helper.day_start_utc()
        result = self._get_remaining(site, forecast_confidence, (start_utc - day_start).total_seconds())
        if end_utc is not None:
            end_utc = end_utc.replace(minute=math.floor(end_utc.minute / 5) * 5)
            if end_utc < day_start + timedelta(seconds=1800 * len(self._spline_period)) and result is not None:
                # End is within today so use spline data.
                if (val := self._get_remaining(site, forecast_confidence, (end_utc - day_start).total_seconds())) is not None:
                    result -= val
            elif result is not None:
                # End is beyond today, so revert to simple linear interpolation.
                start_index_post_spline, _ = self.get_list_slice(  # Get post-spline day onwards start index.
                    data,
                    day_start + timedelta(seconds=1800 * len(self._spline_period)),
                )
                for forecast in data[start_index_post_spline:end_index]:
                    forecast_period_next = forecast[PERIOD_START] + timedelta(seconds=1800)
                    seconds = 1800
                    interval = 0.5 * forecast[forecast_confidence]
                    if end_utc < forecast_period_next:
                        seconds -= (forecast_period_next - end_utc).total_seconds()
                        result += interval * seconds / 1800
                    else:
                        result += interval
        return max(0, result) if result is not None else None

    def _get_forecast_pv_estimates(
        self,
        start_utc: dt,
        end_utc: dt,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> float | None:
        """Return energy total for a period.

        Arguments:
            start_utc (datetime): Start of time period datetime in UTC.
            end_utc (datetime): End of time period datetime in UTC.
            site (str): Optional Solcast site ID, used to provide site breakdown.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            float | None: Energy forecast total for a period as kWh.
        """
        data = self.api.data_forecasts if site is None else self.api.site_data_forecasts[site]
        forecast_confidence = self.api.use_forecast_confidence if forecast_confidence is None else forecast_confidence
        result = 0
        start_index, end_index = self.get_list_slice(  # Get start and end indexes for the requested range.
            data, start_utc, end_utc
        )
        if start_index == 0 and end_index == 0:
            return None
        for forecast_slice in data[start_index:end_index]:
            result += forecast_slice[forecast_confidence]
        return result

    def _get_forecast_pv_moment(
        self,
        time_utc: dt,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> float | None:
        """Return forecast power for a point in time.

        Arguments:
            time_utc (datetime): A moment in UTC to return.
            site (str): Optional Solcast site ID, used to provide site breakdown.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            float | None: Forecast power for a point in time as kW (from splined data).
        """
        forecast_confidence = self.api.use_forecast_confidence if forecast_confidence is None else forecast_confidence
        day_start = self.api.dt_helper.day_start_utc()
        time_utc = time_utc.replace(minute=math.floor(time_utc.minute / 5) * 5)
        return self._get_moment(site, forecast_confidence, (time_utc - day_start).total_seconds())

    def _get_max_forecast_pv_estimate(
        self,
        start_utc: dt,
        end_utc: dt,
        site: str | None = None,
        forecast_confidence: str | None = None,
    ) -> dict[str, Any] | None:
        """Return forecast maximum interval for a period.

        Arguments:
            start_utc (datetime): Start of time period datetime in UTC.
            end_utc (datetime): End of time period datetime in UTC.
            site (str): Optional Solcast site ID, used to provide site breakdown.
            forecast_confidence (str): A optional forecast type, used to select the pv_estimate, pv_estimate10 or pv_estimate90 returned.

        Returns:
            dict[str, Any] | None: The interval data with largest generation for a period.
        """
        result: dict[str, Any] | None = None
        data = self.api.data_forecasts if site is None else self.api.site_data_forecasts[site]
        forecast_confidence = self.api.use_forecast_confidence if forecast_confidence is None else forecast_confidence
        start_index, end_index = self.get_list_slice(data, start_utc, end_utc)
        if start_index == 0 and end_index == 0:
            return None  # Set sensor to unavailable
        result = data[start_index]
        for forecast_slice in data[start_index:end_index]:
            if result[forecast_confidence] < forecast_slice[forecast_confidence]:
                result = forecast_slice
        return result

    def get_energy_data(self) -> dict[str, Any] | None:
        """Get energy data.

        Returns:
            dict[str, Any] | None: A Home Assistant energy dashboard compatible data set.
        """
        return self.api.data_energy_dashboard

    def make_energy_dict(self) -> dict[str, dict[str, float]]:
        """Make a Home Assistant Energy dashboard compatible dictionary.

        Returns:
            dict[str, dict[str, float]]: An Energy dashboard compatible data structure.
        """
        if self.api.options.use_actuals == HistoryType.FORECASTS:
            return {
                "wh_hours": OrderedDict(
                    sorted(
                        {
                            forecast[PERIOD_START].isoformat(): round(forecast[self.api.use_forecast_confidence] * 500, 0)
                            for index, forecast in enumerate(self.api.data_forecasts)
                            if index > 1
                            and index < len(self.api.data_forecasts) - 2
                            and (
                                forecast[self.api.use_forecast_confidence] > 0
                                or self.api.data_forecasts[index - 1][self.api.use_forecast_confidence] > 0
                                or self.api.data_forecasts[index + 1][self.api.use_forecast_confidence] > 0
                                or (
                                    forecast[PERIOD_START].minute == 30
                                    and self.api.data_forecasts[index - 2][self.api.use_forecast_confidence] > 0.2
                                )
                                or (
                                    forecast[PERIOD_START].minute == 30
                                    and self.api.data_forecasts[index + 2][self.api.use_forecast_confidence] > 0.2
                                )
                            )
                        }.items()
                    )
                )
            }

        # Show estimated actuals on Energy dashboard, so combine past estimated actuals with forecast start of today onwards
        _data = (
            self.api.data_estimated_actuals
            if self.api.options.use_actuals == HistoryType.ESTIMATED_ACTUALS
            else self.api.data_estimated_actuals_dampened
        )
        forecasts_start, _ = self.get_list_slice(self.api.data_forecasts, self.api.dt_helper.day_start_utc(), search_past=True)
        actuals_start, actuals_end = self.get_list_slice(
            _data,
            self.api.dt_helper.day_start_utc() - timedelta(days=self.api.advanced_options[ADVANCED_HISTORY_MAX_DAYS]),
            self.api.dt_helper.day_start_utc(),
            search_past=True,
        )
        return {
            "wh_hours": OrderedDict(
                sorted(
                    (
                        {
                            actual[PERIOD_START].isoformat(): round(actual[ESTIMATE] * 500, 0)
                            for index, actual in enumerate(_data)
                            if index > actuals_start + 1
                            and index < actuals_end - 2
                            and (
                                actual[ESTIMATE] > 0
                                or _data[index - 1][ESTIMATE] > 0
                                or _data[index + 1][ESTIMATE] > 0
                                or (actual[PERIOD_START].minute == 30 and _data[index - 2][ESTIMATE] > 0.2)
                                or (actual[PERIOD_START].minute == 30 and _data[index + 2][ESTIMATE] > 0.2)
                            )
                        }
                        | {
                            forecast[PERIOD_START].isoformat(): round(forecast[self.api.use_forecast_confidence] * 500, 0)
                            for index, forecast in enumerate(self.api.data_forecasts)
                            if index >= forecasts_start
                            and index < len(self.api.data_forecasts) - 2
                            and (
                                forecast[ESTIMATE] > 0
                                or self.api.data_forecasts[index - 1][ESTIMATE] > 0
                                or self.api.data_forecasts[index + 1][ESTIMATE] > 0
                                or (forecast[PERIOD_START].minute == 30 and self.api.data_forecasts[index - 2][ESTIMATE] > 0.2)
                                or (forecast[PERIOD_START].minute == 30 and self.api.data_forecasts[index + 2][ESTIMATE] > 0.2)
                            )
                        }
                    ).items()
                )
            )
        }

    def _calc_forecast_start_index(self, data: list[dict[str, Any]]) -> int:
        """Get the start of forecasts as-at just before midnight.

        Doesn't stop at midnight because some sensors may need the previous interval,
        and searches in reverse because less to iterate.

        Arguments:
            data (list): The data structure to search, either total data or site breakdown data.

        Returns:
            int: The starting index of the data structure just prior to midnight local time.
        """
        index = 0
        midnight_utc = self.api.dt_helper.day_start_utc()
        for index in range(len(data) - 1, -1, -1):
            if data[index][PERIOD_START] < midnight_utc:
                break
        return index
