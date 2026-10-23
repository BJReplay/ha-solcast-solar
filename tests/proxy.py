#!/usr/bin/env python3
"""Cron-driven Solcast proxy; resource reads never collect data.

Connections always use HTTPS; upstream certificate validation is enabled by
default, and the proxy uses an ad-hoc certificate. Accounts are learned from
caller API keys
on discovery or resource requests. Collection starts at the next UTC cron
occurrence. State is in memory and lost on restart.
"""

import argparse
from collections.abc import Callable
from contextlib import suppress
import copy
from dataclasses import dataclass, field
import datetime
from email.utils import parsedate_to_datetime
import http.client
import json
import logging
import math
import random
import re
import ssl
import threading
from typing import Any
from urllib import error as urllib_error, request as urllib_request
from urllib.parse import urlencode

from cronsim import CronSim, CronSimError
from flask import Flask, Response, jsonify, request
import isodate

DEFAULT_PORT = 8443
DEFAULT_SOLCAST_PORT = 443
DEFAULT_SOLCAST_HOST = "api.solcast.com.au"
FORECAST_REQUEST_HOURS = 336
ACTUALS_REQUEST_HOURS = 168
PROXY_NAME = "solcast-proxy"
PROXY_VERSION = "2.0"
PROXY_SCHEDULES = {
    "forecasts": {
        "cron": "55 2,7,12,17 * * *",
        "note": "UTC; each collection cycle makes at most ten attempts.",
    },
    "estimated_actuals": {
        "cron": "45 22 * * *",
        "note": "Once per day, UTC, without DST adjustment.",
    },
}
app = Flask(__name__)
_LOGGER = logging.getLogger(__name__)
_API_KEY_PATTERN = re.compile(r"(api_key=)([^&\s\"']+)")


def _redact_api_key_query(value: str) -> str:
    """Keep last six chars of api_key query values."""

    return _API_KEY_PATTERN.sub(lambda match: f"{match.group(1)}******{match.group(2)[-6:]}", value)


def _utc_now() -> datetime.datetime:
    """Return an aware UTC timestamp."""
    return datetime.datetime.now(datetime.UTC)  # pylint: disable=home-assistant-enforce-utcnow


def _iso_utc(value: datetime.datetime | None) -> str:
    """Format a response-header timestamp."""
    return value.astimezone(datetime.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z") if value else ""


def _timestamp_ms(value: datetime.datetime | None) -> int | None:
    """Format a status-report timestamp."""
    return int(value.timestamp() * 1000) if value else None


class _WerkzeugLogFilter(logging.Filter):
    """Suppress startup noise and redact API keys in Werkzeug access logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Return False to suppress a record, or True to allow it (possibly modified)."""
        msg = record.getMessage()
        if msg.startswith("WARNING: This is a development server.") or " * Running on http" in msg or "Press CTRL+C to quit" in msg:
            return False
        if isinstance(record.args, tuple) and len(record.args) >= 2:
            with suppress(IndexError, TypeError):
                request_line = str(record.args[0])
                status = str(record.args[1])
                if "HTTP/" in request_line and status.isdigit():
                    record.msg = 'Request: "%s" -> %s'
                    record.args = (_redact_api_key_query(request_line), status)
        return True


@dataclass
class UpstreamResponse:
    """An upstream result, including rate-limit guidance."""

    status: int
    payload: Any = None
    detail: str = ""
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class Resource:
    """Collection state for one account, site and data kind."""

    api_key: str
    site: str
    kind: str
    hours: int
    next_attempt_at: datetime.datetime | None
    forecast_end: datetime.datetime | None = None
    history_hours: float = 0
    payload: dict[str, Any] | None = None
    fetched_at: datetime.datetime | None = None
    last_success_at: datetime.datetime | None = None
    status: int = 0
    detail: str = ""
    rate_limit_headers: dict[str, str] = field(default_factory=dict)
    error_payload: Any = None
    consecutive_failures: int = 0
    attempt_result: str = "not_fetched"
    attempts: int = 0
    retries_used: int = 0
    retrying: bool = False
    cycle_started_at: datetime.datetime | None = None
    give_up: bool = False
    halted: bool = False
    in_flight: bool = False

    def headers(self) -> dict[str, str]:
        """Report collection state without changing it on consumer reads."""
        return {
            "x-proxy-consecutive-failures": str(self.consecutive_failures),
            "x-proxy-give-up": str(self.give_up).lower(),
            "x-proxy-last-fetch-at": _iso_utc(self.fetched_at),
            "x-proxy-last-fetch-status": self.attempt_result,
            "x-proxy-last-success-at": _iso_utc(self.last_success_at),
            "x-proxy-next-attempt-at": _iso_utc(self.next_attempt_at),
            "x-proxy-upstream-status": str(self.status),
            "x-proxy-retries-used": str(self.retries_used),
            "x-proxy-halted": str(self.halted).lower(),
            "x-proxy-fetch-in-progress": str(self.in_flight).lower(),
        }

    def status_entry(self) -> dict[str, Any]:
        """Expose status without exposing account credentials."""
        return {
            "fetchedAt": _timestamp_ms(self.fetched_at),
            "ok": self.status == 200,
            "status": self.status,
            "detail": self.detail.replace(self.api_key, "[redacted]"),
            "rateLimitHeaders": self.rate_limit_headers or None,
            "lastSuccessAt": _timestamp_ms(self.last_success_at),
            "consecutiveFailures": self.consecutive_failures,
            "attemptResult": self.attempt_result,
            "retriesUsed": self.retries_used,
            "nextAttemptAt": _timestamp_ms(self.next_attempt_at),
            "giveUp": self.give_up,
            "halted": self.halted,
            "cacheHours": self.hours,
        }


def _upstream_url(path: str) -> str:
    """Return the configured upstream URL."""
    return f"https://{app.config.get('SOLCAST_HOST', DEFAULT_SOLCAST_HOST)}:{app.config.get('SOLCAST_PORT', DEFAULT_SOLCAST_PORT)}{path}"


def _fetch_upstream(path: str, query_string: str = "", timeout: float = 30) -> UpstreamResponse:
    """Fetch JSON and preserve rate-limit headers, including Retry-After."""
    url = _upstream_url(path)
    if query_string:
        url += f"?{query_string}"
    outgoing = urllib_request.Request(url, headers={"User-Agent": f"{PROXY_NAME}/{PROXY_VERSION}"})
    verify_upstream_ssl = app.config.get("VERIFY_UPSTREAM_SSL", True)
    if verify_upstream_ssl:
        context = ssl.create_default_context()
    else:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    try:
        with urllib_request.urlopen(outgoing, timeout=timeout, context=context) as response:
            data = response.read()
            payload = json.loads(data.decode("utf-8")) if data else None
            return UpstreamResponse(response.status, payload, headers=dict(response.headers.items()))
    except urllib_error.HTTPError as err:
        try:
            decoded = err.read().decode("utf-8", errors="replace")
        except (http.client.HTTPException, OSError) as read_err:
            return UpstreamResponse(502, detail=type(read_err).__name__)
        try:
            payload = json.loads(decoded) if decoded else None
        except json.JSONDecodeError:
            payload = None
        return UpstreamResponse(err.code, payload, decoded, dict(err.headers.items()) if err.headers else {})
    except (urllib_error.URLError, TimeoutError, OSError, http.client.HTTPException) as err:
        # Exception messages can contain the full URL, including credentials.
        return UpstreamResponse(502, detail=type(err).__name__)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return UpstreamResponse(502, detail="Invalid upstream JSON")


class SolcastProxy:
    """Collect independently of readers and share account-scoped caches."""

    def __init__(
        self,
        fetch: Callable[[str, str], UpstreamResponse] | None = None,
        now: Callable[[], datetime.datetime] = _utc_now,
        forecast_cron: str = "55 2,7,12,17 * * *",
        actuals_cron: str = "45 22 * * *",
        max_attempts: int = 10,
        retry_backoff: int = 15,
        jitter: Callable[[], int] | None = None,
    ) -> None:
        """Configure collection without making network calls."""
        for expression in (forecast_cron, actuals_cron):
            if len(expression.split()) != 5:
                raise ValueError("Schedules must be valid five-field cron expressions")
            try:
                CronSim(expression, datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC))
            except CronSimError:
                raise ValueError("Schedules must be valid five-field cron expressions")
        if min(max_attempts, retry_backoff) < 1:
            raise ValueError("Retry settings must be positive")
        self.fetch = fetch or _fetch_upstream
        self.now = now
        self.schedules = copy.deepcopy(PROXY_SCHEDULES)
        self.schedules["forecasts"]["cron"] = forecast_cron
        self.schedules["estimated_actuals"]["cron"] = actuals_cron
        self.schedules["forecasts"]["note"] = f"UTC; each collection cycle makes at most {max_attempts} attempts."
        self.max_attempts = max_attempts
        self.retry_backoff = retry_backoff
        self.jitter = jitter or (lambda: random.randrange(15))
        self.resources: dict[tuple[str, str, str], Resource] = {}
        self.accounts: dict[str, set[str]] = {}
        self.discovered_accounts: set[str] = set()
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def next_cron(self, kind: str, now: datetime.datetime) -> datetime.datetime:
        """Find the next strictly future UTC occurrence."""
        return next(CronSim(self.schedules[kind]["cron"], now.astimezone(datetime.UTC)))

    def next_cron_at_or_after(self, kind: str, when: datetime.datetime) -> datetime.datetime:
        """First UTC occurrence at or after a time."""
        return self.next_cron(kind, when.astimezone(datetime.UTC) - datetime.timedelta(microseconds=1))

    def collection_hours(self, record: Resource) -> int:
        """Request beyond both platform limits and let upstream cap the data."""
        if record.kind == "forecasts":
            return FORECAST_REQUEST_HOURS
        return ACTUALS_REQUEST_HOURS

    def discovery_headers(self) -> dict[str, str]:
        """Advertise a versioned scheduling contract for future consumers."""
        return {
            "x-solcast-proxy": "true",
            "x-proxy-name": PROXY_NAME,
            "x-proxy-version": PROXY_VERSION,
            "x-proxy-forecast-cron": self.schedules["forecasts"]["cron"],
            "x-proxy-estimated-actuals-cron": self.schedules["estimated_actuals"]["cron"],
            "x-proxy-timezone": "UTC",
            "x-proxy-status-url": "/proxy-status",
            "x-proxy-poll-delay-seconds": "5",
        }

    def discover(self, api_key: str) -> UpstreamResponse:
        """Discover sites live and register resources for scheduled collection."""
        result = self.fetch("/rooftop_sites", urlencode({"format": "json", "api_key": api_key}))
        if result.status != 200 or not isinstance(result.payload, dict):
            return result
        sites = {
            site["resource_id"]
            for site in result.payload.get("sites", [])
            if isinstance(site, dict) and isinstance(site.get("resource_id"), str)
        }
        now = self.now()
        with self.lock:
            self.accounts[api_key] = sites
            self.discovered_accounts.add(api_key)
            for key in list(self.resources):
                if key[0] == api_key and key[1] not in sites:
                    del self.resources[key]
            for site in sorted(sites):
                self._register_site(api_key, site, now)
        return result

    def _register_site(self, api_key: str, site: str, now: datetime.datetime) -> None:
        """Remember caller credentials; upstream collection validates new sites."""
        self.accounts.setdefault(api_key, set()).add(site)
        for kind in ("forecasts", "estimated_actuals"):
            key = (api_key, site, kind)
            if key not in self.resources:
                self.resources[key] = Resource(api_key, site, kind, 0, self.next_cron(kind, now))

    def run_pending(self) -> None:
        """Collect each due resource once; schedule retries rather than sleeping."""
        with self.lock:
            now = self.now()
            for record in self.resources.values():
                if (
                    record.retrying
                    and record.cycle_started_at is not None
                    and now >= record.cycle_started_at + datetime.timedelta(minutes=15)
                ):
                    record.retrying = False
                    record.give_up = True
                    record.attempt_result = "give_up"
                    record.next_attempt_at = self.next_cron(record.kind, record.cycle_started_at)
            due = [
                record
                for record in self.resources.values()
                if not record.halted and not record.in_flight and record.next_attempt_at is not None and record.next_attempt_at <= now
            ]
            for record in due:
                record.in_flight = True
        try:
            for record in due:
                if self.stop_event.is_set():
                    break
                with self.lock:
                    if not record.retrying:
                        record.attempts = 0
                        record.cycle_started_at = self.now()
                    assert record.cycle_started_at is not None
                    remaining = 900 - (self.now() - record.cycle_started_at).total_seconds()
                    if remaining <= 0:
                        record.retrying = False
                        record.give_up = True
                        record.attempt_result = "give_up"
                        record.next_attempt_at = self.next_cron(record.kind, record.cycle_started_at)
                        continue
                    hours = self.collection_hours(record)
                query = urlencode({"format": "json", "api_key": record.api_key, "hours": hours})
                path = f"/rooftop_sites/{record.site}/{record.kind}"
                if self.fetch is _fetch_upstream:
                    result = _fetch_upstream(path, query, timeout=max(0.001, min(30, remaining)))
                else:
                    result = self.fetch(path, query)
                with self.lock:
                    self._record_attempt(record, result)
        finally:
            with self.lock:
                for record in due:
                    record.in_flight = False

    def _record_attempt(self, record: Resource, result: UpstreamResponse) -> None:
        """Retain successful payloads independently of failed collection state."""
        now = self.now()
        record.attempts += 1
        record.retries_used = record.attempts - 1
        record.fetched_at = now
        valid_payload = isinstance(result.payload, dict) and isinstance(result.payload.get(record.kind), list)
        record.status = 502 if result.status == 200 and not valid_payload else result.status
        record.detail = "Invalid upstream resource payload" if result.status == 200 and not valid_payload else result.detail
        record.error_payload = copy.deepcopy(result.payload) if result.status != 200 else None
        record.rate_limit_headers = {
            key: value
            for key, value in result.headers.items()
            if key.lower() == "retry-after" or key.lower().startswith(("x-ratelimit", "ratelimit"))
        }
        assert record.cycle_started_at is not None
        next_cycle_at = self.next_cron(record.kind, record.cycle_started_at)
        cycle_cutoff_at = min(next_cycle_at, record.cycle_started_at + datetime.timedelta(minutes=15))
        record.give_up = False
        record.retrying = False
        if result.status == 200 and valid_payload:
            record.next_attempt_at = next_cycle_at
            if record.kind == "forecasts":
                record.forecast_end = self._forecast_end(result.payload[record.kind])
                record.hours = (
                    max(0, math.ceil((record.forecast_end - now).total_seconds() / 3600)) if record.forecast_end is not None else 0
                )
            else:
                record.history_hours = self._history_hours(result.payload[record.kind])
                record.hours = math.ceil(record.history_hours)
            record.payload = copy.deepcopy(result.payload)
            record.last_success_at = now
            record.consecutive_failures = 0
            record.attempt_result = "retry_success" if record.retries_used else "clean_success"
            return
        record.consecutive_failures += 1
        response_status = result.payload.get("response_status") if isinstance(result.payload, dict) else None
        if result.status == 429 and isinstance(response_status, dict) and response_status.get("error_code") == "TooManyRequests":
            record.attempt_result = "budget_exhausted"
            record.give_up = True
            record.next_attempt_at = next_cycle_at
            return
        if 400 <= result.status < 500 and result.status not in (408, 425, 429):
            record.attempt_result = "permanent_error"
            record.give_up = True
            record.halted = True
            record.next_attempt_at = None
            return
        if record.attempts >= self.max_attempts:
            record.attempt_result = "give_up"
            record.give_up = True
            record.next_attempt_at = next_cycle_at
            return
        delay = record.attempts * self.retry_backoff + self.jitter()
        retry_after = next(
            (value for key, value in result.headers.items() if key.lower() == "retry-after"),
            None,
        )
        if retry_after is not None:
            try:
                delay = max(delay, int(retry_after))
            except ValueError:
                with suppress(ValueError, TypeError, OverflowError):
                    delay = max(
                        delay,
                        int((parsedate_to_datetime(retry_after) - now).total_seconds()),
                    )
        retry_at = now + datetime.timedelta(seconds=delay)
        if retry_at >= cycle_cutoff_at:
            record.attempt_result = "give_up"
            record.give_up = True
            record.next_attempt_at = self.next_cron_at_or_after(record.kind, retry_at)
            return
        record.next_attempt_at = retry_at
        record.retrying = True
        record.attempt_result = "retrying"

    def resource_response(self, site_id: str, kind: str) -> Response | tuple[Response, int]:
        """Validate and slice cached data; reads cannot initiate collection."""
        api_key = request.args.get("api_key", "")
        if not api_key:
            return jsonify(error="API key required"), 400
        try:
            hours = int(request.args.get("hours", ""))
        except ValueError:
            return jsonify(error="hours must be a positive integer"), 400
        if hours <= 0 or request.args.get("format", "json") != "json":
            return jsonify(error="Positive hours and JSON format required"), 400
        with self.lock:
            if api_key not in self.discovered_accounts:
                self._register_site(api_key, site_id, self.now())
            record = self.resources.get((api_key, site_id, kind))
            if record is None:
                return jsonify(error="Unknown rooftop site for this account"), 404
            headers = record.headers()
            payload = copy.deepcopy(record.payload)
            cache_hours = record.hours
            forecast_end = record.forecast_end
            history_hours = record.history_hours
            collected_at = record.last_success_at
            upstream_status = record.status
            budget_exhausted = record.attempt_result == "budget_exhausted"
            error_payload = copy.deepcopy(record.error_payload)
            now = self.now()
        if upstream_status == 429:
            # JSON null is the integration's load-shedding signal, not quota exhaustion.
            response = jsonify(error_payload if budget_exhausted else None)
            response.status_code = 429
        elif payload is None:
            response = jsonify(error="No scheduled collection has succeeded yet")
            response.status_code = 503
        else:
            payload[kind] = self._slice(payload[kind], kind, now, hours)
            response = jsonify(payload)
        available_hours = cache_hours
        if collected_at is not None:
            if kind == "forecasts":
                available_hours = max(0, (forecast_end - now).total_seconds() / 3600) if forecast_end is not None else 0
            else:
                available_hours = max(0, history_hours - (now - collected_at).total_seconds() / 3600)
        headers.update(
            {
                "x-proxy-requested-hours": str(hours),
                "x-proxy-cache-hours": str(cache_hours),
                "x-proxy-hours-truncated": str(hours > available_hours).lower(),
                "Cache-Control": "no-store",
            }
        )
        response.headers.update(headers)
        return response

    @staticmethod
    def _forecast_period(
        row: dict[str, Any],
    ) -> tuple[datetime.datetime, datetime.datetime]:
        """Parse a Solcast interval used for slicing and coverage."""
        end = datetime.datetime.fromisoformat(row["period_end"]).astimezone(datetime.UTC)
        if "period_start" in row:
            start = datetime.datetime.fromisoformat(row["period_start"]).astimezone(datetime.UTC)
        else:
            duration = isodate.parse_duration(row.get("period", "PT30M"))
            if not isinstance(duration, datetime.timedelta):
                raise ValueError("Period must be a fixed duration")
            start = end - datetime.timedelta(seconds=duration.total_seconds())
        return start, end

    @classmethod
    def _forecast_end(cls, rows: list[dict[str, Any]]) -> datetime.datetime | None:
        """Measure returned coverage rather than the oversized request horizon."""
        ends = []
        for row in rows:
            try:
                _, end = cls._forecast_period(row)
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            ends.append(end)
        return max(ends, default=None)

    @classmethod
    def _history_hours(cls, rows: list[dict[str, Any]]) -> float:
        """Measure the span of the returned history rather than requested hours."""
        intervals = []
        for row in rows:
            try:
                intervals.append(cls._forecast_period(row))
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
        if not intervals:
            return 0
        start = min(start for start, _ in intervals)
        end = max(end for _, end in intervals)
        return max(0, (end - start).total_seconds() / 3600)

    @classmethod
    def _slice(cls, rows: list[dict[str, Any]], kind: str, now: datetime.datetime, hours: int) -> list[dict[str, Any]]:
        """Slice forecast overlap or actual period ends, preserving API fields."""
        result = []
        for row in rows:
            try:
                if kind == "estimated_actuals":
                    end = datetime.datetime.fromisoformat(row["period_end"]).astimezone(datetime.UTC)
                    include = -hours * 3600 < (end - now).total_seconds() <= 0
                else:
                    start, end = cls._forecast_period(row)
                    include = end > now and (start - now).total_seconds() < hours * 3600
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if include:
                result.append(row)
        return result

    def status(self) -> dict[str, Any]:
        """Report resource state, using opaque labels for duplicate account sites."""
        with self.lock:
            sites: dict[str, set[str]] = {}
            for api_key, site, _ in self.resources:
                sites.setdefault(site, set()).add(api_key)
            account_ids = {key: index for index, key in enumerate(self.accounts, 1)}
            resources: dict[str, Any] = {}
            for (api_key, site, kind), record in self.resources.items():
                label = site if len(sites[site]) == 1 else f"account-{account_ids[api_key]}:{site}"
                resources.setdefault(label, {})[kind] = record.status_entry()
            return {
                "proxy": {
                    "name": PROXY_NAME,
                    "version": PROXY_VERSION,
                    "rate_limited_by_upstream": any(record.status == 429 for record in self.resources.values()),
                    "note": "Consumer resource reads never fetch upstream; only scheduled collection does.",
                    "timezone": "UTC",
                    "poll_delay_seconds": 5,
                },
                "schedules": copy.deepcopy(self.schedules),
                "resources": resources,
            }

    def start(self) -> None:
        """Start the interruptible background scheduler."""
        if self.thread is not None and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name="solcast-proxy-collector", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        """Collect independently of Flask consumer requests."""
        while not self.stop_event.is_set():
            try:
                self.run_pending()
            except (ValueError, TypeError, OSError):
                _LOGGER.error("Unexpected proxy collection error", exc_info=False)
            self.stop_event.wait(0.5)

    def stop(self) -> None:
        """Stop scheduling and join the current collection operation."""
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join()


proxy = SolcastProxy()


def _get_proxy() -> SolcastProxy:
    """Use the CLI-configured instance, or the import-safe default."""
    return app.extensions.get("solcast_proxy", proxy)


@app.get("/rooftop_sites")
def get_sites() -> Response:
    """Live discovery with proxy scheduling capability headers."""
    api_key = request.args.get("api_key")
    if not api_key or request.args.get("format", "json") != "json":
        response = jsonify(error="API key and JSON format required")
        response.status_code = 400
    else:
        result = _get_proxy().discover(api_key)
        response = jsonify(result.payload) if result.payload is not None else Response(result.detail)
        response.status_code = result.status
    response.headers.update(_get_proxy().discovery_headers())
    return response


@app.get("/rooftop_sites/<site_id>/forecasts")
def get_site_forecasts(site_id: str) -> Response | tuple[Response, int]:
    """Serve forecasts with resource-specific collection headers."""
    return _get_proxy().resource_response(site_id, "forecasts")


@app.get("/rooftop_sites/<site_id>/estimated_actuals")
def get_site_estimated_actuals(site_id: str) -> Response | tuple[Response, int]:
    """Serve actuals with resource-specific collection headers."""
    return _get_proxy().resource_response(site_id, "estimated_actuals")


@app.get("/proxy_status")
@app.get("/proxy-status")
def get_proxy_status() -> Response:
    """Report per-resource status, without a misleading global fetch header."""
    return jsonify(_get_proxy().status())


def build_parser() -> argparse.ArgumentParser:
    """Parse listening, upstream and scheduling settings."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solcast-host", default=DEFAULT_SOLCAST_HOST)
    parser.add_argument("--solcast-port", type=int, default=DEFAULT_SOLCAST_PORT)
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Disable TLS certificate verification for the upstream Solcast host.",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--forecast-cron", default=PROXY_SCHEDULES["forecasts"]["cron"])
    parser.add_argument("--actuals-cron", default=PROXY_SCHEDULES["estimated_actuals"]["cron"])
    parser.add_argument("--debug", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    """Start independent collection and the consumer-facing HTTPS server."""
    parser = build_parser()
    args = parser.parse_args(argv)
    app.config.update(
        SOLCAST_HOST=args.solcast_host,
        SOLCAST_PORT=args.solcast_port,
        VERIFY_UPSTREAM_SSL=not args.no_verify,
    )
    try:
        configured_proxy = SolcastProxy(
            forecast_cron=args.forecast_cron,
            actuals_cron=args.actuals_cron,
        )
    except ValueError as err:
        parser.error(str(err))
    app.extensions["solcast_proxy"] = configured_proxy
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.%(msecs)03d %(levelname)s [%(name)s:%(filename)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
    logging.getLogger("werkzeug").addFilter(_WerkzeugLogFilter())
    configured_proxy.start()
    try:
        app.run(
            host=args.host,
            port=args.port,
            debug=args.debug,
            use_reloader=False,
            ssl_context="adhoc",
        )
    finally:
        configured_proxy.stop()


if __name__ == "__main__":
    main()
