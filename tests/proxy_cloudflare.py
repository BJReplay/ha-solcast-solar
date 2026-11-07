#!/usr/bin/env python3
"""Cloudflare Worker Solcast proxy with Durable Object coordination.

Design goals:
- HTTP header/endpoint expected by the HA integration
- Minimise CPU usage on free tier
- Perform lock-step retries across all resources when any retryable failure happens

Lock-step rule:
- If one resource gets a retryable failure (especially 429), all resources are put
  into a shared retry cycle
- Retries are driven by one Durable Object alarm (per-second backoff)
- Success exits retry mode for everyone; repeated failures continue lock-step retries.
  One out, all out. All in, happy days.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import asdict, dataclass, field
import datetime as dt
import json
import math
import random
import re
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse

from js import Headers, Request, fetch as js_fetch
from workers import DurableObject, Response, WorkerEntrypoint

DEFAULT_SOLCAST_HOST = "api.solcast.com.au"
DEFAULT_SOLCAST_PORT = 443
PROXY_NAME = "solcast-proxy"
PROXY_VERSION = "cloudflare-do-1.0"
DEFAULT_FORECAST_CRON = "55 2,7,12,17 * * *"
DEFAULT_ACTUALS_CRON = "45 22 * * *"
DEFAULT_POLL_DELAY_SECONDS = "5"
FORECAST_REQUEST_HOURS = 336
ACTUALS_REQUEST_HOURS = 168

FORECAST_KIND = "forecasts"
ACTUALS_KIND = "estimated_actuals"

_RESOURCE_KINDS = (FORECAST_KIND, ACTUALS_KIND)


@dataclass
class ResourceState:
    """Persisted collection state for one account+site+kind resource."""

    api_key: str
    site: str
    kind: str
    hours: int = 0
    forecast_end: str | None = None
    history_hours: float = 0
    payload: dict[str, Any] | None = None
    error_payload: Any = None
    fetched_at: str | None = None
    last_success_at: str | None = None
    status: int = 0
    detail: str = ""
    rate_limit_headers: dict[str, str] = field(default_factory=dict)
    consecutive_failures: int = 0
    attempt_result: str = "not_fetched"
    retries_used: int = 0
    retrying: bool = False
    give_up: bool = False
    halted: bool = False
    in_flight: bool = False
    next_attempt_at: str | None = None


@dataclass
class RetryState:
    """Lock-step retry state."""

    active: bool = False
    attempts: int = 0
    next_attempt_at: str | None = None
    last_status: int = 0
    kinds: list[str] = field(default_factory=list)


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _iso(value: dt.datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _from_iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    with suppress(ValueError):
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.UTC)
    return None


def _ts_ms(value: dt.datetime | None) -> int | None:
    if value is None:
        return None
    return int(value.timestamp() * 1000)


def _resource_id(api_key: str, site: str, kind: str) -> str:
    return f"{api_key}|{site}|{kind}"


def _bool_header(value: bool) -> str:
    return "true" if value else "false"


def _discovery_headers(env: Any) -> dict[str, str]:
    return {
        "x-solcast-proxy": "true",
        "x-proxy-name": PROXY_NAME,
        "x-proxy-version": PROXY_VERSION,
        "x-proxy-forecast-cron": str(getattr(env, "FORECAST_CRON", DEFAULT_FORECAST_CRON)),
        "x-proxy-estimated-actuals-cron": str(getattr(env, "ACTUALS_CRON", DEFAULT_ACTUALS_CRON)),
        "x-proxy-timezone": "UTC",
        "x-proxy-status-url": "/proxy-status",
        "x-proxy-poll-delay-seconds": str(getattr(env, "POLL_DELAY_SECONDS", DEFAULT_POLL_DELAY_SECONDS)),
    }


def _row_start(row: dict[str, Any], end: dt.datetime) -> dt.datetime:
    """Resolve interval starts from Solcast's period-end and ISO time duration."""
    if "period_start" in row:
        return dt.datetime.fromisoformat(row["period_start"]).astimezone(dt.UTC)
    duration = re.fullmatch(r"PT(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?", row["period"])
    if duration is None or not any(duration.groups()):
        raise ValueError("Invalid Solcast period")
    hours, minutes, seconds = (float(value or 0) for value in duration.groups())
    return end - dt.timedelta(hours=hours, minutes=minutes, seconds=seconds)


def _slice_rows(rows: list[dict[str, Any]], kind: str, now: dt.datetime, hours: int) -> list[dict[str, Any]]:
    sliced: list[dict[str, Any]] = []
    for row in rows:
        try:
            end = dt.datetime.fromisoformat(row["period_end"]).astimezone(dt.UTC)
            if kind == ACTUALS_KIND:
                include = -hours * 3600 < (end - now).total_seconds() <= 0
            else:
                start = _row_start(row, end)
                include = end > now and (start - now).total_seconds() < hours * 3600
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if include:
            sliced.append(row)
    return sliced


def _next_retry(now: dt.datetime, attempts: int, backoff_seconds: int) -> dt.datetime:
    """Per-second retry timing for DO alarms."""
    jitter = random.randrange(15)
    delay = max(1, attempts * backoff_seconds + jitter)
    return now + dt.timedelta(seconds=delay)


def _resource_headers(resource: ResourceState, retry_state: RetryState) -> dict[str, str]:
    retrying = retry_state.active and resource.kind in retry_state.kinds
    next_retry = _from_iso(retry_state.next_attempt_at) if retrying else None
    upstream_status = retry_state.last_status if retrying else resource.status
    return {
        "x-proxy-consecutive-failures": str(resource.consecutive_failures),
        "x-proxy-give-up": _bool_header(resource.give_up),
        "x-proxy-last-fetch-at": _iso(_from_iso(resource.fetched_at)),
        "x-proxy-last-fetch-status": "retrying" if retrying else resource.attempt_result,
        "x-proxy-last-success-at": _iso(_from_iso(resource.last_success_at)),
        "x-proxy-next-attempt-at": _iso(next_retry) if retrying else "",
        "x-proxy-upstream-status": str(upstream_status),
        "x-proxy-retries-used": str(retry_state.attempts if retrying else resource.retries_used),
        "x-proxy-halted": _bool_header(resource.halted),
        "x-proxy-fetch-in-progress": _bool_header(resource.in_flight),
    }


def _json_response(payload: Any, status: int, headers: dict[str, str] | None = None) -> Response:
    return Response(
        json.dumps(payload),
        status=status,
        headers=[("content-type", "application/json"), *(headers or {}).items()],
    )


async def _fetch_upstream(env: Any, path: str, query: str = "") -> tuple[int, Any, str, dict[str, str]]:
    host = str(getattr(env, "SOLCAST_HOST", DEFAULT_SOLCAST_HOST))
    port = int(getattr(env, "SOLCAST_PORT", DEFAULT_SOLCAST_PORT))
    url = f"https://{host}:{port}{path}"
    if query:
        url = f"{url}?{query}"

    headers = Headers.new()
    headers.set("User-Agent", f"{PROXY_NAME}/{PROXY_VERSION}")
    response = await js_fetch(url, {"method": "GET", "headers": headers})

    status = int(response.status)
    text = await response.text()
    payload: Any = None
    detail = text if status >= 400 else ""
    with suppress(json.JSONDecodeError):
        payload = json.loads(text) if text else None

    guidance: dict[str, str] = {}
    for key, value in response.headers:
        k = str(key)
        if k.lower() == "retry-after" or k.lower().startswith(("x-ratelimit", "ratelimit")):
            guidance[k] = str(value)

    return status, payload, detail, guidance


class ProxyCoordinator(DurableObject):
    """Durable Object: single-writer coordinator for state and retries."""

    def __init__(self, state: Any, env: Any) -> None:
        super().__init__(state, env)
        self.state = state
        self.env = env

    async def _load(self) -> dict[str, Any]:
        data = await self.state.storage.get("state")
        if isinstance(data, str):
            data = json.loads(data)
        if not isinstance(data, dict):
            data = {
                "accounts": {},
                "resources": {},
                "retry": asdict(RetryState()),
            }
        data.setdefault("accounts", {})
        data.setdefault("resources", {})
        data.setdefault("retry", asdict(RetryState()))
        return data

    async def _save(self, data: dict[str, Any]) -> None:
        await self.state.storage.put("state", json.dumps(data))

    async def _register_sites(self, data: dict[str, Any], api_key: str, sites: set[str]) -> None:
        data["accounts"][api_key] = sorted(sites)
        stale_resources = [rid for rid, raw in data["resources"].items() if raw["api_key"] == api_key and raw["site"] not in sites]
        for rid in stale_resources:
            del data["resources"][rid]
        for site in sites:
            for kind in _RESOURCE_KINDS:
                rid = _resource_id(api_key, site, kind)
                if rid not in data["resources"]:
                    data["resources"][rid] = asdict(ResourceState(api_key=api_key, site=site, kind=kind))
        if not data["resources"]:
            data["retry"] = asdict(RetryState())
            await self.state.storage.deleteAlarm()

    async def _discover(self, api_key: str) -> tuple[int, Any, str]:
        status, payload, detail, _headers = await _fetch_upstream(
            self.env,
            "/rooftop_sites",
            urlencode({"format": "json", "api_key": api_key}),
        )
        if status != 200:
            return status, payload, detail

        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("sites"), list)
            or any(
                not isinstance(site, dict) or not isinstance(site.get("resource_id"), str) or not site["resource_id"]
                for site in payload["sites"]
            )
        ):
            return (
                502,
                {"error": "Invalid rooftop sites response from upstream"},
                "Invalid rooftop sites response from upstream",
            )
        sites = {site["resource_id"] for site in payload["sites"]}

        data = await self._load()
        await self._register_sites(data, api_key, sites)
        await self._save(data)
        return status, payload, detail

    async def _collect_one(self, resource: ResourceState, hours: int) -> tuple[ResourceState, bool, bool, bool]:
        """Collect one resource.

        Returns:
        - updated resource
        - success
        - retryable failure
        - explicit 429 failure
        """
        now = _utc_now()
        resource.in_flight = True
        resource.fetched_at = _iso(now)

        path = f"/rooftop_sites/{resource.site}/{resource.kind}"
        query = urlencode({"format": "json", "api_key": resource.api_key, "hours": hours})
        status, payload, detail, guidance = await _fetch_upstream(self.env, path, query)

        resource.status = status
        resource.detail = detail
        resource.rate_limit_headers = guidance
        resource.error_payload = payload if status != 200 else None

        if status == 200 and isinstance(payload, dict) and isinstance(payload.get(resource.kind), list):
            rows = payload[resource.kind]
            resource.payload = payload
            resource.last_success_at = _iso(now)
            resource.consecutive_failures = 0
            resource.give_up = False
            resource.retrying = False
            resource.attempt_result = "clean_success"
            resource.next_attempt_at = None
            if resource.kind == FORECAST_KIND:
                ends: list[dt.datetime] = []
                for row in rows:
                    with suppress(KeyError, TypeError, ValueError):
                        ends.append(dt.datetime.fromisoformat(row["period_end"]).astimezone(dt.UTC))
                if ends:
                    forecast_end = max(ends)
                    resource.forecast_end = _iso(forecast_end)
                    resource.hours = max(0, math.ceil((forecast_end - now).total_seconds() / 3600))
                else:
                    resource.forecast_end = None
                    resource.hours = 0
            else:
                starts: list[dt.datetime] = []
                ends: list[dt.datetime] = []
                for row in rows:
                    with suppress(KeyError, TypeError, ValueError):
                        end = dt.datetime.fromisoformat(row["period_end"]).astimezone(dt.UTC)
                        start = _row_start(row, end)
                        starts.append(start)
                        ends.append(end)
                if starts and ends:
                    span = max(ends) - min(starts)
                    resource.history_hours = max(0.0, span.total_seconds() / 3600)
                    resource.hours = math.ceil(resource.history_hours)
                else:
                    resource.history_hours = 0.0
                    resource.hours = 0
            resource.in_flight = False
            return resource, True, False, False

        resource.consecutive_failures += 1
        resource.attempt_result = "retrying"
        resource.in_flight = False

        retryable = not (400 <= status < 500 and status not in (408, 425, 429))
        is_429 = status == 429
        if not retryable:
            resource.attempt_result = "permanent_error"
            resource.halted = True
            resource.give_up = True
            resource.retrying = False
            resource.next_attempt_at = None
        return resource, False, retryable, is_429

    async def _run_cycle(self, kind_filter: str | None = None) -> None:
        """Run a collection cycle.

        If a retryable failure occurs for any resource, all resources enter
        lock-step retry mode with one shared next-attempt timestamp.
        """
        data = await self._load()
        retry = RetryState(**data["retry"])
        now = _utc_now()

        resources = [ResourceState(**raw) for raw in data["resources"].values()]
        kinds = set(retry.kinds) if retry.active else set()
        if kind_filter is not None:
            kinds.add(kind_filter)
        resources = [r for r in resources if r.kind in kinds]

        if not resources:
            return

        any_retryable = False
        any_429 = False
        all_success = True

        for resource in resources:
            if resource.halted:
                continue
            hours = FORECAST_REQUEST_HOURS if resource.kind == FORECAST_KIND else ACTUALS_REQUEST_HOURS
            updated, success, retryable, is_429 = await self._collect_one(resource, hours)
            data["resources"][_resource_id(updated.api_key, updated.site, updated.kind)] = asdict(updated)
            all_success = all_success and success
            any_retryable = any_retryable or retryable
            any_429 = any_429 or is_429

        max_attempts = int(getattr(self.env, "MAX_ATTEMPTS", "5"))
        backoff_seconds = int(getattr(self.env, "RETRY_BACKOFF_SECONDS", "45"))

        if all_success:
            retry.active = False
            retry.kinds = []
            retry.attempts = 0
            retry.next_attempt_at = None
            retry.last_status = 200
            for rid, raw in data["resources"].items():
                if raw["kind"] not in kinds:
                    continue
                state = ResourceState(**raw)
                state.retrying = False
                state.give_up = False
                state.next_attempt_at = None
                if state.attempt_result == "clean_success" and retry.attempts > 0:
                    state.attempt_result = "retry_success"
                data["resources"][rid] = asdict(state)
            with suppress(Exception):
                await self.state.storage.deleteAlarm()
        elif any_retryable:
            retry.active = True
            retry.kinds = sorted(kinds)
            retry.attempts += 1
            retry.last_status = 429 if any_429 else 502
            if retry.attempts > max_attempts:
                retry.active = False
                retry.kinds = []
                retry.next_attempt_at = None
                for rid, raw in data["resources"].items():
                    if raw["kind"] not in kinds:
                        continue
                    state = ResourceState(**raw)
                    state.retrying = False
                    state.give_up = True
                    state.attempt_result = "give_up"
                    state.next_attempt_at = None
                    data["resources"][rid] = asdict(state)
                with suppress(Exception):
                    await self.state.storage.deleteAlarm()
            else:
                next_retry = _next_retry(now, retry.attempts, backoff_seconds)
                retry.next_attempt_at = _iso(next_retry)
                for rid, raw in data["resources"].items():
                    if raw["kind"] not in kinds:
                        continue
                    state = ResourceState(**raw)
                    if not state.halted:
                        state.retrying = True
                        state.give_up = False
                        state.attempt_result = "retrying"
                        state.next_attempt_at = retry.next_attempt_at
                        if any_429:
                            state.status = 429
                    data["resources"][rid] = asdict(state)
                await self.state.storage.setAlarm(int(next_retry.timestamp() * 1000))
        else:
            # Permanent failures only; no lock-step retries.
            retry.active = False
            retry.kinds = []
            retry.next_attempt_at = None
            with suppress(Exception):
                await self.state.storage.deleteAlarm()

        data["retry"] = asdict(retry)
        await self._save(data)

    async def _resource_response(self, request_url: str, site_id: str, kind: str) -> Response:
        parsed = urlparse(request_url)
        qs = parse_qs(parsed.query)

        api_key = (qs.get("api_key") or [""])[0]
        if not api_key:
            return _json_response({"error": "API key required"}, 400)

        format_param = (qs.get("format") or ["json"])[0]
        hours_raw = (qs.get("hours") or [""])[0]
        try:
            hours = int(hours_raw)
        except ValueError:
            hours = 0

        if format_param != "json" or hours <= 0:
            return _json_response({"error": "Positive hours and JSON format required"}, 400)

        data = await self._load()
        rid = _resource_id(api_key, site_id, kind)
        raw = data["resources"].get(rid)
        if raw is None:
            # bootstrap account/sites via live discovery
            status, _payload, _detail = await self._discover(api_key)
            if status != 200:
                return _json_response({"error": "Unknown rooftop site for this account"}, 404)
            data = await self._load()
            raw = data["resources"].get(rid)
            if raw is None:
                return _json_response({"error": "Unknown rooftop site for this account"}, 404)

        resource = ResourceState(**raw)
        retry = RetryState(**data["retry"])
        headers = _resource_headers(resource, retry)

        now = _utc_now()
        payload = resource.payload

        if resource.status == 429:
            response_payload = resource.error_payload if resource.attempt_result == "budget_exhausted" else None
            response_status = 429
        elif payload is None:
            response_payload = {"error": "No scheduled collection has succeeded yet"}
            response_status = 503
        else:
            payload_copy = json.loads(json.dumps(payload))
            rows = payload_copy.get(kind, [])
            if isinstance(rows, list):
                payload_copy[kind] = _slice_rows(rows, kind, now, hours)
            response_payload = payload_copy
            response_status = 200

        available_hours = float(resource.hours)
        if resource.last_success_at:
            collected_at = _from_iso(resource.last_success_at) or now
            if kind == FORECAST_KIND and resource.forecast_end:
                forecast_end = _from_iso(resource.forecast_end)
                available_hours = max(0.0, (forecast_end - now).total_seconds() / 3600) if forecast_end else 0.0
            elif kind == ACTUALS_KIND:
                available_hours = max(0.0, resource.history_hours - (now - collected_at).total_seconds() / 3600)

        headers.update(
            {
                "x-proxy-requested-hours": str(hours),
                "x-proxy-cache-hours": str(resource.hours),
                "x-proxy-hours-truncated": _bool_header(hours > available_hours),
                "cache-control": "no-store",
            }
        )

        return _json_response(response_payload, response_status, headers)

    async def _status_response(self) -> Response:
        data = await self._load()
        retry = RetryState(**data["retry"])

        account_ids = {api_key: idx for idx, api_key in enumerate(data["accounts"], 1)}
        resources: dict[str, Any] = {}
        for raw in data["resources"].values():
            state = ResourceState(**raw)
            retrying = retry.active and state.kind in retry.kinds
            label = f"account-{account_ids.get(state.api_key, 0)}:{state.site}"
            resources.setdefault(label, {})[state.kind] = {
                "fetchedAt": _ts_ms(_from_iso(state.fetched_at)),
                "ok": state.status == 200,
                "status": retry.last_status if retrying else state.status,
                "detail": state.detail,
                "rateLimitHeaders": state.rate_limit_headers or None,
                "lastSuccessAt": _ts_ms(_from_iso(state.last_success_at)),
                "consecutiveFailures": state.consecutive_failures,
                "attemptResult": "retrying" if retrying else state.attempt_result,
                "retriesUsed": retry.attempts if retrying else state.retries_used,
                "nextAttemptAt": _ts_ms(_from_iso(retry.next_attempt_at if retrying else state.next_attempt_at)),
                "giveUp": state.give_up,
                "halted": state.halted,
                "cacheHours": state.hours,
            }

        body = {
            "proxy": {
                "name": PROXY_NAME,
                "version": PROXY_VERSION,
                "rate_limited_by_upstream": retry.active and retry.last_status == 429,
                "note": "Reads never collect upstream forecasts/actuals; collection is scheduled.",
                "timezone": "UTC",
                "poll_delay_seconds": int(getattr(self.env, "POLL_DELAY_SECONDS", DEFAULT_POLL_DELAY_SECONDS)),
            },
            "schedules": {
                "forecasts": {
                    "cron": str(getattr(self.env, "FORECAST_CRON", DEFAULT_FORECAST_CRON)),
                    "note": "UTC; lock-step retries are alarm-driven.",
                },
                "estimated_actuals": {
                    "cron": str(getattr(self.env, "ACTUALS_CRON", DEFAULT_ACTUALS_CRON)),
                    "note": "UTC; lock-step retries are alarm-driven.",
                },
            },
            "resources": resources,
            "retry": {
                "active": retry.active,
                "kinds": retry.kinds,
                "attempts": retry.attempts,
                "nextAttemptAt": _ts_ms(_from_iso(retry.next_attempt_at)),
                "status": retry.last_status,
            },
        }

        return _json_response(body, 200)

    async def fetch(self, request: Any) -> Response:
        request_url = str(request.url)
        parsed = urlparse(request_url)
        path = parsed.path

        if path == "/__scheduled":
            qs = parse_qs(parsed.query)
            cron_value = (qs.get("cron") or [""])[0]
            forecast_cron = str(getattr(self.env, "FORECAST_CRON", DEFAULT_FORECAST_CRON))
            actuals_cron = str(getattr(self.env, "ACTUALS_CRON", DEFAULT_ACTUALS_CRON))
            if cron_value == forecast_cron:
                await self._run_cycle(FORECAST_KIND)
            elif cron_value == actuals_cron:
                await self._run_cycle(ACTUALS_KIND)
            return Response(None, status=204)

        if path == "/rooftop_sites":
            qs = parse_qs(parsed.query)
            headers = _discovery_headers(self.env)
            api_key = (qs.get("api_key") or [""])[0]
            fmt = (qs.get("format") or ["json"])[0]
            if not api_key or fmt != "json":
                response = _json_response({"error": "API key and JSON format required"}, 400, headers)
            else:
                status, payload, detail = await self._discover(api_key)
                if payload is not None:
                    response = _json_response(payload, status, headers)
                else:
                    response = Response(detail or "", status=status, headers=list(headers.items()))
            return response

        if path.endswith("/forecasts") and "/rooftop_sites/" in path:
            site_id = path.split("/")[2]
            return await self._resource_response(request_url, site_id, FORECAST_KIND)

        if path.endswith("/estimated_actuals") and "/rooftop_sites/" in path:
            site_id = path.split("/")[2]
            return await self._resource_response(request_url, site_id, ACTUALS_KIND)

        if path in ("/proxy-status", "/proxy_status"):
            return await self._status_response()

        return Response("Not found", status=404)

    async def alarm(self) -> None:
        """Durable Object alarm callback: run lock-step retry when active."""
        data = await self._load()
        retry = RetryState(**data["retry"])
        if not retry.active:
            return
        if not retry.kinds:
            # Old retry state has no trustworthy collection scope.
            data["retry"] = asdict(RetryState())
            await self.state.storage.deleteAlarm()
            await self._save(data)
            return
        await self._run_cycle(None)


def _coordinator_stub(env: Any) -> Any:
    namespace = env.PROXY_COORDINATOR
    return namespace.getByName("global")


class Default(WorkerEntrypoint):
    """Cloudflare Python worker entrypoint."""

    async def fetch(self, request: Any) -> Response:
        """Route all API traffic through the coordinator DO."""
        return await _coordinator_stub(self.env).fetch(request)

    async def scheduled(self, controller: Any, _ctx: Any) -> None:
        """Dispatch scheduled cycles to the coordinator DO."""
        cron_value = quote(str(controller.cron), safe="")
        request = Request.new(f"https://proxy.internal/__scheduled?cron={cron_value}", {"method": "POST"})
        await _coordinator_stub(self.env).fetch(request)
