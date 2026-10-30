"""Contract tests for the scheduled, cache-only Solcast proxy."""

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.message import Message
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import ssl
import sys
import threading
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

pytest.importorskip("flask", reason="Flask is required to run proxy tests")

from flask.testing import FlaskClient
from werkzeug.test import TestResponse as ClientResponse

KINDS = ("forecasts", "estimated_actuals")
API_KEY = "private+key&with=reserved characters"
SITE_ID = "1111-1111-1111-1111"
OTHER_SITE_ID = "2222-2222-2222-2222"
REGISTERED_AT = datetime(2026, 9, 6, 7, 54, tzinfo=UTC)
FORECAST_AT = datetime(2026, 9, 6, 7, 55, tzinfo=UTC)
ACTUALS_AT = datetime(2026, 9, 6, 22, 45, tzinfo=UTC)
FORECAST_CRON = "55 2,7,12,17 * * *"
ACTUALS_CRON = "45 22 * * *"


def _collection_time(kind: str) -> datetime:
    """Return the first scheduled collection time for a resource kind."""
    return {"forecasts": FORECAST_AT, "estimated_actuals": ACTUALS_AT}[kind]


def _next_collection_time(kind: str) -> datetime:
    """Return the second scheduled collection time for a resource kind."""
    return {
        "forecasts": datetime(2026, 9, 6, 12, 55, tzinfo=UTC),
        "estimated_actuals": datetime(2026, 9, 7, 22, 45, tzinfo=UTC),
    }[kind]


def _timestamp(value: datetime) -> str:
    """Format a fixture period timestamp."""
    return value.isoformat().replace("+00:00", "Z")


def _header_time(response: ClientResponse, header: str) -> datetime:
    """Parse a proxy timestamp without depending on fractional precision."""
    return datetime.fromisoformat(response.headers[header])


@dataclass
class ProxyHarness:
    """Drive the public proxy API with a frozen clock and queued responses."""

    module: ModuleType
    clock: list[datetime]
    calls: list[tuple[str, dict[str, list[str]]]] = field(default_factory=list)
    responses: dict[str, deque[Any]] = field(default_factory=dict)
    simulator: Any = None
    client: FlaskClient = field(init=False)

    def fetch(self, path: str, query_string: str) -> Any:
        """Record decoded queries and return the next response for this path."""
        self.calls.append((path, parse_qs(query_string)))
        queued = self.responses.get(path)
        if queued:
            return queued.popleft()
        kind = path.rsplit("/", 1)[-1]
        assert kind in KINDS, f"Unqueued upstream discovery: {path}"
        return self.module.UpstreamResponse(200, {kind: []})

    def queue(
        self,
        path: str,
        status: int = 200,
        payload: Any = None,
        detail: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        """Queue an upstream result without touching proxy internals."""
        self.responses.setdefault(path, deque()).append(self.module.UpstreamResponse(status, payload, detail, headers or {}))

    def discover(self, sites: tuple[str, ...] = (SITE_ID,), api_key: str = API_KEY) -> ClientResponse:
        """Discover sites through Flask and register their resources."""
        payload = {"sites": [{"resource_id": site, "name": site} for site in sites]}
        self.queue("/rooftop_sites", payload=payload)
        response = self.client.get("/rooftop_sites", query_string={"format": "json", "api_key": api_key})
        assert response.status_code == 200
        assert response.get_json() == payload
        return response

    def read(
        self,
        kind: str,
        site: str = SITE_ID,
        api_key: str = API_KEY,
        hours: str | int | None = 168,
        output_format: str = "json",
    ) -> ClientResponse:
        """Read a resource through the same route used by consumers."""
        query = {"api_key": api_key, "format": output_format}
        if hours is not None:
            query["hours"] = str(hours)
        return self.client.get(f"/rooftop_sites/{site}/{kind}", query_string=query)

    def resource_calls(self, kind: str) -> list[tuple[str, dict[str, list[str]]]]:
        """Return collection calls for one kind, excluding live discovery."""
        return [call for call in self.calls if call[0].endswith(f"/{kind}")]

    def collect(self, kind: str, payload: Any) -> ClientResponse:
        """Populate a cache only by advancing to its scheduled collection."""
        assert self.read(kind, hours=168).status_code == 503
        self.queue(f"/rooftop_sites/{SITE_ID}/{kind}", payload=payload)
        self.clock[0] = _collection_time(kind)
        self.simulator.run_pending()
        return self.read(kind)


@pytest.fixture
def proxy(monkeypatch: pytest.MonkeyPatch) -> ProxyHarness:
    """Load an isolated module and install a proxy with no real I/O."""
    name = "tests.components.solcast_solar._proxy_test"
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name("proxy.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    harness = ProxyHarness(module, [REGISTERED_AT])
    harness.simulator = module.SolcastProxy(
        fetch=harness.fetch,
        now=lambda: harness.clock[0],
        jitter=lambda: 0,
    )
    monkeypatch.setattr(module, "proxy", harness.simulator)
    module.app.config["TESTING"] = True
    harness.client = module.app.test_client()
    assert harness.calls == []
    return harness


def test_upstream_response_headers_are_independent(proxy: ProxyHarness) -> None:
    """The response dataclass does not share its default headers dictionary."""
    first = proxy.module.UpstreamResponse(200)
    second = proxy.module.UpstreamResponse(200)
    first.headers["Retry-After"] = "30"
    assert second.headers == {}
    assert second.payload is None
    assert second.detail == ""


def test_discovery_is_live_and_advertises_proxy(proxy: ProxyHarness) -> None:
    """Discovery forwards encoded credentials and advertises the proxy contract."""
    response = proxy.discover()
    assert proxy.calls == [("/rooftop_sites", {"format": ["json"], "api_key": [API_KEY]})]
    expected = {
        "x-solcast-proxy": "true",
        "x-proxy-name": proxy.module.PROXY_NAME,
        "x-proxy-version": proxy.module.PROXY_VERSION,
        "x-proxy-forecast-cron": FORECAST_CRON,
        "x-proxy-estimated-actuals-cron": ACTUALS_CRON,
        "x-proxy-timezone": "UTC",
        "x-proxy-status-url": "/proxy-status",
        "x-proxy-poll-delay-seconds": "5",
    }
    for header, value in expected.items():
        assert response.headers[header] == value
    assert "x-proxy-forecast-timezone" not in response.headers
    proxy.discover()
    assert len(proxy.calls) == 2
    proxy.clock[0] = FORECAST_AT
    proxy.simulator.run_pending()
    assert len(proxy.resource_calls("forecasts")) == 1


def test_direct_discovery_returns_upstream_response(proxy: ProxyHarness) -> None:
    """The injectable discovery API returns the agreed response dataclass."""
    payload = {"sites": [{"resource_id": SITE_ID}]}
    proxy.queue("/rooftop_sites", payload=payload)
    response = proxy.simulator.discover(API_KEY)
    assert isinstance(response, proxy.module.UpstreamResponse)
    assert response.status == 200
    assert response.payload == payload
    assert proxy.calls == [("/rooftop_sites", {"format": ["json"], "api_key": [API_KEY]})]


@pytest.mark.parametrize("kind", KINDS)
def test_registration_schedules_without_consumer_fetch(proxy: ProxyHarness, kind: str) -> None:
    """Registration calculates the next UTC cron and leaves an empty cache."""
    proxy.discover()
    response = proxy.read(kind)
    assert response.status_code == 503
    assert _header_time(response, "x-proxy-next-attempt-at") == _collection_time(kind)
    assert response.headers["x-proxy-last-fetch-at"] == ""
    assert response.headers["x-proxy-last-success-at"] == ""
    assert proxy.resource_calls(kind) == []
    proxy.simulator.run_pending()
    assert len(proxy.calls) == 1


def test_cron_collects_all_sites_and_kinds_independently(proxy: ProxyHarness) -> None:
    """Each currently due resource is fetched once, not once per missed cron."""
    proxy.discover((SITE_ID, OTHER_SITE_ID))
    proxy.clock[0] = FORECAST_AT - timedelta(seconds=1)
    proxy.simulator.run_pending()
    assert len(proxy.calls) == 1
    proxy.clock[0] = FORECAST_AT
    proxy.simulator.run_pending()
    assert proxy.resource_calls("forecasts") == [
        (
            f"/rooftop_sites/{site}/forecasts",
            {"format": ["json"], "api_key": [API_KEY], "hours": ["336"]},
        )
        for site in (SITE_ID, OTHER_SITE_ID)
    ]
    assert proxy.resource_calls("estimated_actuals") == []
    proxy.simulator.run_pending()
    assert len(proxy.resource_calls("forecasts")) == 2
    proxy.clock[0] = _next_collection_time("forecasts")
    proxy.simulator.run_pending()
    assert [query["hours"] for _, query in proxy.resource_calls("forecasts")] == [
        ["336"],
        ["336"],
        ["336"],
        ["336"],
    ]
    proxy.clock[0] = ACTUALS_AT
    proxy.simulator.run_pending()
    assert len(proxy.resource_calls("forecasts")) == 6
    assert proxy.resource_calls("estimated_actuals") == [
        (
            f"/rooftop_sites/{site}/estimated_actuals",
            {"format": ["json"], "api_key": [API_KEY], "hours": ["168"]},
        )
        for site in (SITE_ID, OTHER_SITE_ID)
    ]
    proxy.simulator.run_pending()
    assert len(proxy.resource_calls("estimated_actuals")) == 2
    proxy.clock[0] = _next_collection_time("estimated_actuals")
    proxy.simulator.run_pending()
    assert [query["hours"] for _, query in proxy.resource_calls("estimated_actuals")] == [["168"]] * 4


@pytest.mark.parametrize("kind", KINDS)
def test_success_metadata_and_repeated_cache_reads(proxy: ProxyHarness, kind: str) -> None:
    """Consumer reads preserve collection metadata and never fetch upstream."""
    proxy.discover()
    payload = {kind: [], "site_marker": SITE_ID}
    response = proxy.collect(kind, payload)
    assert response.status_code == 200
    assert response.get_json() == payload
    for header, expected in {
        "x-proxy-last-fetch-status": "clean_success",
        "x-proxy-consecutive-failures": "0",
        "x-proxy-give-up": "false",
        "x-proxy-upstream-status": "200",
        "x-proxy-retries-used": "0",
        "x-proxy-halted": "false",
    }.items():
        assert response.headers[header] == expected
    assert _header_time(response, "x-proxy-last-fetch-at") == _collection_time(kind)
    assert _header_time(response, "x-proxy-last-success-at") == _collection_time(kind)
    assert _header_time(response, "x-proxy-next-attempt-at") == _next_collection_time(kind)
    calls = list(proxy.calls)
    proxy.clock[0] += timedelta(seconds=5)
    for _ in range(3):
        cached = proxy.read(kind)
        assert cached.get_json() == payload
        assert cached.headers["x-proxy-last-fetch-at"] == response.headers["x-proxy-last-fetch-at"]
        assert cached.headers["x-proxy-next-attempt-at"] == response.headers["x-proxy-next-attempt-at"]
    assert proxy.calls == calls


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    ("upstream_status", "detail"),
    [
        pytest.param(429, "", id="empty-rate-limit"),
        pytest.param(503, "unavailable", id="service-unavailable"),
        pytest.param(502, "network failure", id="network-error"),
    ],
)
def test_retry_is_deferred_and_success_resets_failures(proxy: ProxyHarness, kind: str, upstream_status: int, detail: str) -> None:
    """Retryable failures wait for a later tick rather than blocking collection."""
    proxy.discover()
    path = f"/rooftop_sites/{SITE_ID}/{kind}"
    proxy.queue(path, upstream_status, detail=detail)
    proxy.queue(path, payload={kind: []})
    proxy.clock[0] = _collection_time(kind)
    proxy.simulator.run_pending()
    assert len(proxy.resource_calls(kind)) == 1
    failed = proxy.read(kind)
    assert failed.status_code == {429: 429, 503: 503, 502: 503}[upstream_status]
    assert failed.headers["x-proxy-last-fetch-status"] == "retrying"
    assert failed.headers["x-proxy-consecutive-failures"] == "1"
    assert failed.headers["x-proxy-upstream-status"] == str(upstream_status)
    assert failed.headers["x-proxy-retries-used"] == "0"
    assert failed.headers["x-proxy-give-up"] == "false"
    assert failed.headers["x-proxy-halted"] == "false"
    assert _header_time(failed, "x-proxy-next-attempt-at") == (proxy.clock[0] + timedelta(seconds=15))
    proxy.simulator.run_pending()
    proxy.clock[0] += timedelta(seconds=14)
    proxy.simulator.run_pending()
    assert len(proxy.resource_calls(kind)) == 1
    proxy.clock[0] += timedelta(seconds=1)
    proxy.simulator.run_pending()
    response = proxy.read(kind)
    assert len(proxy.resource_calls(kind)) == 2
    assert response.status_code == 200
    assert response.headers["x-proxy-last-fetch-status"] == "retry_success"
    assert response.headers["x-proxy-consecutive-failures"] == "0"
    assert response.headers["x-proxy-retries-used"] == "1"
    assert response.headers["x-proxy-upstream-status"] == "200"
    assert _header_time(response, "x-proxy-last-success-at") == proxy.clock[0]
    assert _header_time(response, "x-proxy-next-attempt-at") == _next_collection_time(kind)


@pytest.mark.parametrize("kind", KINDS)
def test_retry_exhaustion_resumes_at_next_cron(proxy: ProxyHarness, kind: str) -> None:
    """Ten failed attempts give up for this cycle but do not halt the resource."""
    proxy.discover()
    path = f"/rooftop_sites/{SITE_ID}/{kind}"
    for _ in range(10):
        proxy.queue(path, 503)
    proxy.clock[0] = _collection_time(kind)
    for attempt in range(9):
        proxy.simulator.run_pending()
        assert len(proxy.resource_calls(kind)) == attempt + 1
        proxy.clock[0] = _header_time(proxy.read(kind), "x-proxy-next-attempt-at")
    proxy.simulator.run_pending()
    assert len(proxy.resource_calls(kind)) == 10
    response = proxy.read(kind)
    assert response.status_code == 503
    assert response.headers["x-proxy-last-fetch-status"] == "give_up"
    assert response.headers["x-proxy-give-up"] == "true"
    assert response.headers["x-proxy-halted"] == "false"
    assert response.headers["x-proxy-retries-used"] == "9"
    assert _header_time(response, "x-proxy-next-attempt-at") == _next_collection_time(kind)
    proxy.simulator.run_pending()
    assert len(proxy.resource_calls(kind)) == 10
    proxy.queue(path, payload={kind: []})
    proxy.clock[0] = _next_collection_time(kind)
    proxy.simulator.run_pending()
    recovered = proxy.read(kind)
    assert len(proxy.resource_calls(kind)) == 11
    assert recovered.status_code == 200
    assert recovered.headers["x-proxy-last-fetch-status"] == "clean_success"
    assert recovered.headers["x-proxy-consecutive-failures"] == "0"
    assert recovered.headers["x-proxy-give-up"] == "false"
    assert recovered.headers["x-proxy-retries-used"] == "0"


@pytest.mark.parametrize("kind", KINDS)
def test_budget_exhaustion_preserves_cache_until_next_cron(proxy: ProxyHarness, kind: str) -> None:
    """A Solcast daily-budget error keeps good data without immediate retries."""
    proxy.discover()
    payload = {kind: [], "cached": "successful payload"}
    success = proxy.collect(kind, payload)
    proxy.queue(
        f"/rooftop_sites/{SITE_ID}/{kind}",
        429,
        {"response_status": {"error_code": "TooManyRequests"}},
    )
    proxy.clock[0] = _next_collection_time(kind)
    proxy.simulator.run_pending()
    response = proxy.read(kind)
    assert response.status_code == 429
    assert response.get_json() == {"response_status": {"error_code": "TooManyRequests"}}
    assert proxy.simulator.resources[(API_KEY, SITE_ID, kind)].payload == payload
    assert response.headers["x-proxy-upstream-status"] == "429"
    assert response.headers["x-proxy-halted"] == "false"
    assert response.headers["x-proxy-last-success-at"] == success.headers["x-proxy-last-success-at"]
    assert _header_time(response, "x-proxy-last-fetch-at") == proxy.clock[0]
    next_attempt = _header_time(response, "x-proxy-next-attempt-at")
    expected = {
        "forecasts": datetime(2026, 9, 6, 17, 55, tzinfo=UTC),
        "estimated_actuals": datetime(2026, 9, 8, 22, 45, tzinfo=UTC),
    }[kind]
    assert next_attempt == expected
    count = len(proxy.resource_calls(kind))
    proxy.clock[0] += timedelta(minutes=1)
    proxy.simulator.run_pending()
    assert len(proxy.resource_calls(kind)) == count
    proxy.clock[0] = next_attempt
    proxy.simulator.run_pending()
    assert len(proxy.resource_calls(kind)) == count + 1


@pytest.mark.parametrize("kind", KINDS)
def test_retryable_failure_retains_successful_payload(proxy: ProxyHarness, kind: str) -> None:
    """A retrying upstream failure does not replace or discard a good cache."""
    proxy.discover()
    payload = {kind: [], "generation": 1}
    success = proxy.collect(kind, payload)
    proxy.queue(f"/rooftop_sites/{SITE_ID}/{kind}", 429)
    proxy.clock[0] = _next_collection_time(kind)
    proxy.simulator.run_pending()
    response = proxy.read(kind)
    assert response.status_code == 429
    assert response.get_json() is None
    assert response.get_data(as_text=True).strip() == "null"
    assert proxy.simulator.resources[(API_KEY, SITE_ID, kind)].payload == payload
    assert response.headers["x-proxy-last-fetch-status"] == "retrying"
    assert response.headers["x-proxy-upstream-status"] == "429"
    assert response.headers["x-proxy-last-success-at"] == success.headers["x-proxy-last-success-at"]
    assert len(proxy.resource_calls(kind)) == 2


@pytest.mark.parametrize("kind", KINDS)
def test_permanent_failure_halts_only_failed_resource(proxy: ProxyHarness, kind: str) -> None:
    """A forbidden resource is halted while other sites continue collecting."""
    proxy.discover((SITE_ID, OTHER_SITE_ID))
    proxy.queue(f"/rooftop_sites/{SITE_ID}/{kind}", 403)
    proxy.clock[0] = _collection_time(kind)
    proxy.simulator.run_pending()
    response = proxy.read(kind)
    assert response.status_code == 503
    assert response.headers["x-proxy-last-fetch-status"] == "permanent_error"
    assert response.headers["x-proxy-upstream-status"] == "403"
    assert response.headers["x-proxy-halted"] == "true"
    assert response.headers["x-proxy-next-attempt-at"] == ""
    assert proxy.read(kind, site=OTHER_SITE_ID).status_code == 200
    proxy.clock[0] = _next_collection_time(kind)
    proxy.simulator.run_pending()
    paths = [path for path, _ in proxy.resource_calls(kind)]
    assert paths.count(f"/rooftop_sites/{SITE_ID}/{kind}") == 1
    assert paths.count(f"/rooftop_sites/{OTHER_SITE_ID}/{kind}") == 2


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    ("api_key", "site", "expected_status"),
    [
        pytest.param("unknown-key", SITE_ID, 503, id="first-seen-key"),
        pytest.param(API_KEY, "unknown-site", 404, id="unknown-site"),
    ],
)
def test_first_seen_key_or_unknown_discovered_site_do_not_fetch(
    proxy: ProxyHarness, kind: str, api_key: str, site: str, expected_status: int
) -> None:
    """New keys register locally; known account sites retain ownership checks."""
    proxy.discover()
    calls = list(proxy.calls)
    assert proxy.read(kind, site=site, api_key=api_key).status_code == expected_status
    assert proxy.calls == calls


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "hours",
    [
        pytest.param(None, id="missing"),
        pytest.param("0", id="zero"),
        pytest.param("-1", id="negative"),
        pytest.param("bad", id="not-numeric"),
        pytest.param("1.5", id="fractional"),
    ],
)
def test_invalid_hours_do_not_fetch(proxy: ProxyHarness, kind: str, hours: str | None) -> None:
    """Resource hours must be a supplied positive integer."""
    proxy.discover()
    calls = list(proxy.calls)
    assert proxy.read(kind, hours=hours).status_code == 400
    assert proxy.calls == calls


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("output_format", ["xml", "csv"])
def test_non_json_format_does_not_fetch(proxy: ProxyHarness, kind: str, output_format: str) -> None:
    """Only JSON resource output is accepted, including on cache misses."""
    proxy.discover()
    calls = list(proxy.calls)
    assert proxy.read(kind, output_format=output_format).status_code == 400
    assert proxy.calls == calls


@pytest.mark.parametrize("kind", KINDS)
def test_api_keys_have_separate_caches_for_same_site(proxy: ProxyHarness, kind: str) -> None:
    """Two keys for the same site register independent scheduled resources."""
    other_key = "second-private-key"
    proxy.discover()
    proxy.discover(api_key=other_key)
    path = f"/rooftop_sites/{SITE_ID}/{kind}"
    proxy.queue(path, payload={kind: [], "account": "first"})
    proxy.queue(path, payload={kind: [], "account": "second"})
    proxy.clock[0] = _collection_time(kind)
    proxy.simulator.run_pending()
    calls = proxy.resource_calls(kind)
    assert len(calls) == 2
    accounts = {query["api_key"][0]: proxy.read(kind, api_key=query["api_key"][0]).get_json()["account"] for _, query in calls}
    assert set(accounts) == {API_KEY, other_key}
    assert set(accounts.values()) == {"first", "second"}
    assert proxy.read(kind).get_json()["account"] != proxy.read(kind, api_key=other_key).get_json()["account"]
    assert len(proxy.resource_calls(kind)) == 2


@pytest.mark.parametrize("with_period_start", [True, False])
def test_forecast_hours_trim_overlap_and_derive_start(proxy: ProxyHarness, with_period_start: bool) -> None:
    """Forecasts overlap [now, now + hours), including inferred ISO periods."""
    proxy.discover()
    end_offsets = (0, 0.25, 1, 2, 2.25, 2.5, 3)
    rows = [
        {
            "period_end": _timestamp(FORECAST_AT + timedelta(hours=end)),
            "period": "PT30M",
            "pv_estimate": index,
        }
        for index, end in enumerate(end_offsets)
    ]
    starts = [{"period_start": _timestamp(FORECAST_AT + timedelta(hours=end - 0.5))} for end in end_offsets]
    additions = {True: starts, False: [{} for _ in rows]}[with_period_start]
    rows = [row | extra for row, extra in zip(rows, additions, strict=True)]
    proxy.collect("forecasts", {"forecasts": rows, "metadata": "preserved"})
    calls = list(proxy.calls)
    response = proxy.read("forecasts", hours=2)
    assert response.status_code == 200
    assert response.get_json() == {"forecasts": rows[1:5], "metadata": "preserved"}
    assert proxy.calls == calls
    assert proxy.read("forecasts", hours=168).get_json()["forecasts"] == rows[1:]


@pytest.mark.parametrize(
    "interval",
    [
        pytest.param({"period": "PT30M"}, id="explicit-duration"),
        pytest.param({}, id="default-duration"),
        pytest.param(
            {"period_start": _timestamp(ACTUALS_AT - timedelta(minutes=30))},
            id="explicit-start",
        ),
    ],
)
def test_single_actuals_interval_reports_one_cache_hour(proxy: ProxyHarness, interval: dict[str, str]) -> None:
    """One half-hour interval is not a full requested 48-hour history."""
    proxy.discover()
    rows = [{"period_end": _timestamp(ACTUALS_AT), "pv_estimate": 1} | interval]
    proxy.collect("estimated_actuals", {"estimated_actuals": rows})
    calls = list(proxy.calls)
    response = proxy.read("estimated_actuals", hours=48)
    assert response.get_json() == {"estimated_actuals": rows}
    assert response.headers["x-proxy-requested-hours"] == "48"
    assert response.headers["x-proxy-cache-hours"] == "1"
    assert response.headers["x-proxy-hours-truncated"] == "true"
    assert proxy.simulator.status()["resources"][SITE_ID]["estimated_actuals"]["cacheHours"] == 1
    assert proxy.resource_calls("estimated_actuals")[0][1]["hours"] == ["168"]
    assert proxy.calls == calls


@pytest.mark.parametrize(
    ("interval", "expected_hours"),
    [
        pytest.param({}, 2, id="default-half-hour"),
        pytest.param({"period": "PT90M"}, 3, id="ninety-minute-duration"),
        pytest.param(
            {
                "period_start": _timestamp(ACTUALS_AT - timedelta(hours=4.25)),
                "period": "invalid",
            },
            3,
            id="explicit-start-overrides-duration",
        ),
    ],
)
@pytest.mark.parametrize("elapsed", [0, 1800])
def test_actuals_cache_hours_use_valid_history_span(
    proxy: ProxyHarness,
    interval: dict[str, str],
    expected_hours: int,
    elapsed: int,
) -> None:
    """Coverage spans valid returned intervals, not request or collection time."""
    proxy.discover()
    newest = {
        "period_end": _timestamp(ACTUALS_AT - timedelta(hours=2)),
        "period": "PT30M",
        "pv_estimate": 2,
    }
    oldest = {
        "period_end": _timestamp(ACTUALS_AT - timedelta(hours=3)),
        "pv_estimate": 1,
    } | interval
    rows = [
        newest,
        {"period_end": _timestamp(ACTUALS_AT), "period": "invalid"},
        oldest,
        {
            "period_end": _timestamp(ACTUALS_AT - timedelta(hours=168)),
            "period_start": "invalid",
        },
        {"period_end": _timestamp(ACTUALS_AT), "period": "P1M"},
        {"period_end": "invalid"},
        {},
        None,
    ]
    proxy.queue(
        f"/rooftop_sites/{SITE_ID}/estimated_actuals",
        payload={"estimated_actuals": rows},
    )
    original_fetch = proxy.fetch

    def slow_fetch(path: str, query: str) -> Any:
        proxy.clock[0] += timedelta(seconds=elapsed)
        return original_fetch(path, query)

    proxy.simulator.fetch = slow_fetch
    proxy.clock[0] = ACTUALS_AT
    proxy.simulator.run_pending()
    calls = list(proxy.calls)
    response = proxy.read("estimated_actuals", hours=48)
    assert response.status_code == 200
    assert response.headers["x-proxy-cache-hours"] == str(expected_hours)
    assert response.headers["x-proxy-hours-truncated"] == "true"
    assert _header_time(response, "x-proxy-last-success-at") == proxy.clock[0]
    assert proxy.simulator.status()["resources"][SITE_ID]["estimated_actuals"]["cacheHours"] == expected_hours
    assert proxy.resource_calls("estimated_actuals")[0][1]["hours"] == ["168"]
    assert proxy.calls == calls


@pytest.mark.parametrize(
    "rows",
    [
        pytest.param([], id="empty"),
        pytest.param(
            [
                {},
                None,
                {"period_end": "invalid"},
                {"period_end": _timestamp(ACTUALS_AT), "period_start": "invalid"},
                {"period_end": _timestamp(ACTUALS_AT), "period": "invalid"},
                {"period_end": _timestamp(ACTUALS_AT), "period": "P1M"},
            ],
            id="no-valid-intervals",
        ),
    ],
)
def test_actuals_without_valid_history_report_zero_coverage(proxy: ProxyHarness, rows: list[Any]) -> None:
    """Invalid intervals cannot advertise history from the collection request."""
    proxy.discover()
    response = proxy.collect("estimated_actuals", {"estimated_actuals": rows})
    assert response.status_code == 200
    assert response.headers["x-proxy-cache-hours"] == "0"
    assert response.headers["x-proxy-hours-truncated"] == "true"
    assert proxy.simulator.status()["resources"][SITE_ID]["estimated_actuals"]["cacheHours"] == 0


@pytest.mark.parametrize(
    ("elapsed", "truncated"),
    [
        pytest.param(0, "false", id="fresh-exact-span"),
        pytest.param(1, "false", id="exact-aged-boundary"),
        pytest.param(2, "true", id="aged-below-request"),
        pytest.param(10800, "true", id="coverage-expired"),
    ],
)
def test_actuals_truncation_uses_exact_aged_history_span(proxy: ProxyHarness, elapsed: int, truncated: str) -> None:
    """Truncation ages fractional history coverage, not rounded cache hours."""
    proxy.discover()
    rows = [
        {
            "period_end": _timestamp(ACTUALS_AT - timedelta(hours=1, seconds=1)),
            "period": "PT1H",
            "pv_estimate": 1,
        },
        {
            "period_end": _timestamp(ACTUALS_AT),
            "period": "PT30M",
            "pv_estimate": 2,
        },
    ]
    proxy.collect("estimated_actuals", {"estimated_actuals": rows})
    calls = list(proxy.calls)
    proxy.clock[0] += timedelta(seconds=elapsed)
    response = proxy.read("estimated_actuals", hours=2)
    assert response.headers["x-proxy-cache-hours"] == "3"
    assert response.headers["x-proxy-hours-truncated"] == truncated
    assert proxy.calls == calls


def test_actuals_retry_keeps_168_hours_without_relabeling_success(
    proxy: ProxyHarness,
) -> None:
    """Retries retain successful history coverage until new actuals arrive."""
    proxy.simulator = proxy.module.SolcastProxy(
        fetch=proxy.fetch,
        now=lambda: proxy.clock[0],
        actuals_cron="45,59 * * * *",
        jitter=lambda: 0,
    )
    with patch.object(proxy.module, "proxy", proxy.simulator):
        proxy.discover()
        rows = [{"period_end": _timestamp(ACTUALS_AT), "pv_estimate": 1}]
        proxy.collect("estimated_actuals", {"estimated_actuals": rows})
        path = f"/rooftop_sites/{SITE_ID}/estimated_actuals"
        proxy.queue(path, 429)
        proxy.clock[0] = datetime(2026, 9, 6, 22, 59, 50, tzinfo=UTC)
        proxy.simulator.run_pending()
        failed = proxy.read("estimated_actuals", hours=48)
        assert failed.status_code == 429
        assert failed.headers["x-proxy-cache-hours"] == "1"
        proxy.clock[0] = _header_time(failed, "x-proxy-next-attempt-at")
        assert proxy.clock[0] == datetime(2026, 9, 6, 23, 0, 5, tzinfo=UTC)
        proxy.queue(path, 429)
        proxy.simulator.run_pending()
        failed_again = proxy.read("estimated_actuals", hours=10**100)
        assert failed_again.headers["x-proxy-cache-hours"] == "1"
        assert failed_again.headers["x-proxy-hours-truncated"] == "true"
        record = proxy.simulator.resources[(API_KEY, SITE_ID, "estimated_actuals")]
        assert record.payload == {"estimated_actuals": rows}
        assert not hasattr(record, "actuals_hours")
        proxy.clock[0] = _header_time(failed_again, "x-proxy-next-attempt-at")
        fresh = [
            {"period_end": _timestamp(proxy.clock[0]), "pv_estimate": 2},
            {
                "period_end": _timestamp(proxy.clock[0] - timedelta(hours=1)),
                "pv_estimate": 3,
            },
        ]
        proxy.queue(path, payload={"estimated_actuals": fresh})
        proxy.simulator.run_pending()
        recovered = proxy.read("estimated_actuals", hours=48)
        assert recovered.status_code == 200
        assert recovered.get_json() == {"estimated_actuals": fresh}
        assert recovered.headers["x-proxy-cache-hours"] == "2"
        assert recovered.headers["x-proxy-hours-truncated"] == "true"
        assert [query["hours"] for _, query in proxy.resource_calls("estimated_actuals")] == [["168"]] * 4


def test_actuals_hours_trim_lower_exclusive_upper_inclusive(
    proxy: ProxyHarness,
) -> None:
    """Actuals include only period ends in (now - hours, now]."""
    proxy.discover()
    rows = [
        {
            "period_end": _timestamp(ACTUALS_AT + timedelta(hours=offset)),
            "period": "PT30M",
            "pv_estimate": index,
        }
        for index, offset in enumerate((-3, -2, -1.5, -0.5, 0, 0.5))
    ]
    proxy.collect("estimated_actuals", {"estimated_actuals": rows})
    calls = list(proxy.calls)
    response = proxy.read("estimated_actuals", hours=2)
    assert response.status_code == 200
    assert response.get_json() == {"estimated_actuals": rows[2:5]}
    assert proxy.calls == calls
    assert proxy.read("estimated_actuals", hours=168).get_json()["estimated_actuals"] == rows[:5]


def test_oversized_actuals_hours_serve_cache_without_collection(
    proxy: ProxyHarness,
) -> None:
    """Larger actuals reads cannot change empty coverage or collection hours."""
    proxy.discover()
    kind = "estimated_actuals"
    payload = {kind: [], "marker": "cached"}
    proxy.collect(kind, payload)
    calls = list(proxy.calls)
    response = proxy.read(kind, hours=336)
    assert response.status_code == 200
    assert response.get_json() == payload
    assert response.headers["x-proxy-hours-truncated"] == "true"
    assert response.headers["x-proxy-requested-hours"] == "336"
    assert response.headers["x-proxy-cache-hours"] == "0"
    record = proxy.simulator.resources[(API_KEY, SITE_ID, kind)]
    assert record.hours == 0
    assert not hasattr(record, "actuals_hours")
    assert proxy.read(kind, hours=336).status_code == 200
    assert proxy.calls == calls
    proxy.clock[0] = _next_collection_time(kind)
    proxy.simulator.run_pending()
    assert [query["hours"] for _, query in proxy.resource_calls(kind)] == [
        ["168"],
        ["168"],
    ]
    assert proxy.simulator.resources[(API_KEY, SITE_ID, kind)].hours == 0


@pytest.mark.parametrize("hours", [336, 10**100])
def test_oversized_actuals_returns_all_available_aged_history(proxy: ProxyHarness, hours: int) -> None:
    """A large requested horizon must not silently clip retained older history."""
    proxy.discover()
    rows = [
        {
            "period_end": _timestamp(ACTUALS_AT - timedelta(hours=167)),
            "period": "PT30M",
            "pv_estimate": 1,
        }
    ]
    proxy.collect("estimated_actuals", {"estimated_actuals": rows})
    calls = list(proxy.calls)
    proxy.clock[0] += timedelta(days=1)
    response = proxy.read("estimated_actuals", hours=hours)
    assert response.status_code == 200
    assert response.get_json() == {"estimated_actuals": rows}
    assert response.headers["x-proxy-hours-truncated"] == "true"
    assert response.headers["x-proxy-cache-hours"] == "1"
    assert proxy.calls == calls


@pytest.mark.parametrize("status_path", ["/proxy-status", "/proxy_status"])
def test_status_reports_resources_and_never_exposes_keys(proxy: ProxyHarness, status_path: str) -> None:
    """Status preserves proxy/schedule/resource sections but redacts credentials."""
    proxy.discover()
    proxy.collect("forecasts", {"forecasts": []})
    calls = list(proxy.calls)
    response = proxy.client.get(status_path)
    assert response.status_code == 200
    status = response.get_json()
    assert status == proxy.simulator.status()
    assert status["proxy"]["name"] == proxy.module.PROXY_NAME
    assert status["proxy"]["version"] == proxy.module.PROXY_VERSION
    assert status["proxy"]["timezone"] == "UTC"
    assert "forecast_timezone" not in status["proxy"]
    assert status["schedules"]["forecasts"]["cron"] == FORECAST_CRON
    assert status["schedules"]["estimated_actuals"]["cron"] == ACTUALS_CRON
    assert set(status["resources"][SITE_ID]) == set(KINDS)
    forecast = status["resources"][SITE_ID]["forecasts"]
    assert forecast["status"] == 200
    assert forecast["attemptResult"] == "clean_success"
    assert forecast["consecutiveFailures"] == 0
    assert forecast["retriesUsed"] == 0
    assert forecast["fetchedAt"] == int(FORECAST_AT.timestamp() * 1000)
    assert forecast["lastSuccessAt"] == int(FORECAST_AT.timestamp() * 1000)
    assert forecast["cacheHours"] == 0
    serialized = json.dumps(status)
    assert API_KEY not in serialized
    assert "api_key" not in serialized
    assert urlencode({"api_key": API_KEY}) not in serialized
    assert proxy.calls == calls


def test_first_actuals_read_keeps_static_collection_hours(
    proxy: ProxyHarness,
) -> None:
    """Actuals collect 168 hours even before the first consumer request."""
    proxy.discover()
    kind = "estimated_actuals"
    proxy.clock[0] = _collection_time(kind)
    proxy.simulator.run_pending()
    assert proxy.resource_calls(kind)[0][1]["hours"] == ["168"]
    calls = list(proxy.calls)
    response = proxy.read(kind, hours=48)
    assert response.status_code == 200
    assert response.headers["x-proxy-cache-hours"] == "0"
    assert response.headers["x-proxy-hours-truncated"] == "true"
    assert proxy.simulator.resources[(API_KEY, SITE_ID, kind)].hours == 0
    assert proxy.calls == calls
    proxy.clock[0] = _next_collection_time(kind)
    proxy.simulator.run_pending()
    assert proxy.resource_calls(kind)[-1][1]["hours"] == ["168"]
    assert proxy.read(kind, hours=48).headers["x-proxy-cache-hours"] == "0"


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("requested_hours", [2, 48, 168, 336, 400, 10**100])
def test_missing_cache_reports_zero_coverage(proxy: ProxyHarness, kind: str, requested_hours: int) -> None:
    """Consumer hours cannot turn an empty cache into pending coverage."""
    proxy.discover()
    response = proxy.read(kind, hours=requested_hours)
    assert response.status_code == 503
    assert response.headers["x-proxy-cache-hours"] == "0"
    assert response.headers["x-proxy-hours-truncated"] == "true"
    status = proxy.simulator.status()["resources"][SITE_ID]
    assert status["forecasts"]["cacheHours"] == 0
    assert status["estimated_actuals"]["cacheHours"] == 0
    assert proxy.resource_calls(kind) == []
    proxy.clock[0] = _collection_time(kind)
    proxy.simulator.run_pending()
    horizon = {"forecasts": "336", "estimated_actuals": "168"}[kind]
    assert proxy.resource_calls(kind)[0][1]["hours"] == [horizon]
    empty = proxy.read(kind, hours=requested_hours)
    assert empty.status_code == 200
    assert empty.get_json() == {kind: []}
    assert empty.headers["x-proxy-cache-hours"] == "0"
    assert empty.headers["x-proxy-hours-truncated"] == "true"
    assert proxy.simulator.status()["resources"][SITE_ID][kind]["cacheHours"] == 0


@pytest.mark.parametrize("upstream_hours", [336, 48])
def test_forecast_consumers_share_upstream_capped_cache(proxy: ProxyHarness, upstream_hours: int) -> None:
    """Short and huge reads slice capped data without padding or extra fetches."""
    proxy.discover()
    for hours in (2, 168, 400, 10**100):
        assert proxy.read("forecasts", hours=hours).status_code == 503
    assert proxy.resource_calls("forecasts") == []
    rows = [
        {
            "period_end": _timestamp(FORECAST_AT + timedelta(minutes=30 * index)),
            "period": "PT30M",
            "pv_estimate": index,
        }
        for index in range(1, upstream_hours * 2 + 1)
    ]
    payload = {"forecasts": rows, "account_horizon": upstream_hours}
    proxy.queue(f"/rooftop_sites/{SITE_ID}/forecasts", payload=payload)
    proxy.clock[0] = FORECAST_AT
    proxy.simulator.run_pending()
    assert proxy.resource_calls("forecasts")[0][1]["hours"] == ["336"]
    calls = list(proxy.calls)
    short = proxy.read("forecasts", hours=2)
    assert short.get_json() == {
        "forecasts": rows[:4],
        "account_horizon": upstream_hours,
    }
    assert short.headers["x-proxy-hours-truncated"] == "false"
    full = proxy.read("forecasts", hours=upstream_hours)
    assert full.get_json() == payload
    assert full.headers["x-proxy-hours-truncated"] == "false"
    for hours in (400, 10**100):
        response = proxy.read("forecasts", hours=hours)
        assert response.status_code == 200
        assert response.get_json() == payload
        assert response.headers["x-proxy-cache-hours"] == str(upstream_hours)
        assert response.headers["x-proxy-hours-truncated"] == "true"
    assert proxy.simulator.status()["resources"][SITE_ID]["forecasts"]["cacheHours"] == upstream_hours
    assert proxy.calls == calls
    proxy.clock[0] = _next_collection_time("forecasts")
    proxy.simulator.run_pending()
    assert proxy.resource_calls("forecasts")[-1][1]["hours"] == ["336"]


@pytest.mark.parametrize("upstream_hours", [168, 48])
def test_actuals_consumers_share_upstream_capped_cache(proxy: ProxyHarness, upstream_hours: int) -> None:
    """Short and huge reads slice capped history without padding or extra fetches."""
    proxy.discover()
    for hours in (2, 48, 168, 300, 10**100):
        missing = proxy.read("estimated_actuals", hours=hours)
        assert missing.status_code == 503
        assert missing.headers["x-proxy-cache-hours"] == "0"
    assert proxy.resource_calls("estimated_actuals") == []
    rows = [
        {
            "period_end": _timestamp(ACTUALS_AT - timedelta(minutes=30 * index)),
            "period": "PT30M",
            "pv_estimate": index,
        }
        for index in range(upstream_hours * 2)
    ]
    payload = {"estimated_actuals": rows, "account_horizon": upstream_hours}
    proxy.queue(f"/rooftop_sites/{SITE_ID}/estimated_actuals", payload=payload)
    proxy.clock[0] = ACTUALS_AT
    proxy.simulator.run_pending()
    assert proxy.resource_calls("estimated_actuals")[0][1]["hours"] == ["168"]
    calls = list(proxy.calls)
    short = proxy.read("estimated_actuals", hours=2)
    assert short.get_json() == {
        "estimated_actuals": rows[:4],
        "account_horizon": upstream_hours,
    }
    assert short.headers["x-proxy-hours-truncated"] == "false"
    full = proxy.read("estimated_actuals", hours=upstream_hours)
    assert full.get_json() == payload
    assert full.headers["x-proxy-hours-truncated"] == "false"
    for hours in (300, 10**100):
        response = proxy.read("estimated_actuals", hours=hours)
        assert response.status_code == 200
        assert response.get_json() == payload
        assert response.headers["x-proxy-requested-hours"] == str(hours)
        assert response.headers["x-proxy-cache-hours"] == str(upstream_hours)
        assert response.headers["x-proxy-hours-truncated"] == "true"
    record = proxy.simulator.resources[(API_KEY, SITE_ID, "estimated_actuals")]
    assert record.hours == upstream_hours
    assert not hasattr(record, "actuals_hours")
    assert proxy.simulator.status()["resources"][SITE_ID]["estimated_actuals"]["cacheHours"] == upstream_hours
    assert proxy.calls == calls
    proxy.clock[0] = _next_collection_time("estimated_actuals")
    proxy.simulator.run_pending()
    assert proxy.resource_calls("estimated_actuals")[-1][1]["hours"] == ["168"]


@pytest.mark.parametrize("kind", KINDS)
def test_missing_coverage_stays_zero_without_fetch(proxy: ProxyHarness, kind: str) -> None:
    """Clock changes and reads cannot create coverage before collection."""
    proxy.discover()
    assert proxy.read(kind, hours=168).headers["x-proxy-cache-hours"] == "0"
    calls = list(proxy.calls)
    proxy.clock[0] = datetime(2026, 9, 6, 8, 0, 59, tzinfo=UTC)
    response = proxy.read(kind, hours=2)
    assert response.status_code == 503
    assert response.headers["x-proxy-cache-hours"] == "0"
    assert proxy.simulator.status()["resources"][SITE_ID][kind]["cacheHours"] == 0
    assert proxy.calls == calls


@pytest.mark.parametrize(
    "boundary",
    [
        pytest.param(datetime(2026, 9, 7, tzinfo=UTC), id="utc-midnight"),
        pytest.param(datetime(2026, 3, 29, 1, tzinfo=UTC), id="spring-dst-utc-boundary"),
        pytest.param(datetime(2026, 10, 25, 1, tzinfo=UTC), id="fall-dst-utc-boundary"),
    ],
)
def test_forecast_collection_is_constant_across_clock_boundaries(proxy: ProxyHarness, boundary: datetime) -> None:
    """Scheduled requests remain 336 hours across UTC days and DST dates."""
    proxy.clock[0] = boundary - timedelta(minutes=2)
    proxy.simulator = proxy.module.SolcastProxy(
        fetch=proxy.fetch,
        now=lambda: proxy.clock[0],
        forecast_cron="* * * * *",
        jitter=lambda: 0,
    )
    with patch.object(proxy.module, "proxy", proxy.simulator):
        proxy.discover()
        assert proxy.read("forecasts", hours=2).status_code == 503
        proxy.clock[0] = boundary - timedelta(minutes=1)
        proxy.simulator.run_pending()
        proxy.clock[0] = boundary
        proxy.simulator.run_pending()
        proxy.clock[0] += timedelta(minutes=1)
        proxy.simulator.run_pending()
        assert [query["hours"] for _, query in proxy.resource_calls("forecasts")] == [["336"]] * 3
        assert proxy.read("forecasts", hours=2).headers["x-proxy-cache-hours"] == "0"


@pytest.mark.parametrize(
    ("elapsed", "expected_hours", "expected_rows"),
    [
        pytest.param(0, 3, 1, id="fractional-coverage-rounded-up"),
        pytest.param(1800, 2, 1, id="coverage-at-successful-completion"),
        pytest.param(10800, 0, 0, id="coverage-expired-before-completion"),
    ],
)
def test_forecast_cache_hours_use_valid_coverage_at_completion(
    proxy: ProxyHarness, elapsed: int, expected_hours: int, expected_rows: int
) -> None:
    """Coverage ignores unsliceable rows and starts when successful I/O completes."""
    proxy.discover()
    valid = {
        "period_end": _timestamp(FORECAST_AT + timedelta(hours=2.5)),
        "period": "PT30M",
        "pv_estimate": 1,
    }
    later_end = _timestamp(FORECAST_AT + timedelta(hours=400))
    rows = [
        {"period_end": later_end, "period": "invalid"},
        valid,
        {"period_end": later_end, "period_start": "invalid"},
        {"period_end": later_end, "period": "P1M"},
        {"period_end": "invalid"},
        {},
        None,
    ]
    proxy.queue(f"/rooftop_sites/{SITE_ID}/forecasts", payload={"forecasts": rows})
    original_fetch = proxy.fetch

    def slow_fetch(path: str, query: str) -> Any:
        proxy.clock[0] += timedelta(seconds=elapsed)
        return original_fetch(path, query)

    proxy.simulator.fetch = slow_fetch
    proxy.clock[0] = FORECAST_AT
    proxy.simulator.run_pending()
    response = proxy.read("forecasts", hours=3)
    assert response.headers["x-proxy-cache-hours"] == str(expected_hours)
    assert response.headers["x-proxy-hours-truncated"] == "true"
    assert response.get_json() == {"forecasts": [valid][:expected_rows]}
    assert _header_time(response, "x-proxy-last-success-at") == proxy.clock[0]
    assert proxy.simulator.status()["resources"][SITE_ID]["forecasts"]["cacheHours"] == expected_hours
    assert proxy.resource_calls("forecasts")[0][1]["hours"] == ["336"]


def test_forecast_truncation_uses_exact_aged_coverage(proxy: ProxyHarness) -> None:
    """Rounded cache hours do not overstate coverage at the consumer's read time."""
    proxy.discover()
    rows = [
        {
            "period_end": _timestamp(FORECAST_AT + timedelta(hours=2, seconds=1)),
            "period": "PT30M",
            "pv_estimate": 1,
        }
    ]
    proxy.collect("forecasts", {"forecasts": rows})
    calls = list(proxy.calls)
    assert proxy.read("forecasts", hours=3).headers["x-proxy-hours-truncated"] == "true"
    assert proxy.read("forecasts", hours=2).headers["x-proxy-hours-truncated"] == "false"
    proxy.clock[0] += timedelta(seconds=2)
    aged = proxy.read("forecasts", hours=2)
    assert aged.get_json() == {"forecasts": rows}
    assert aged.headers["x-proxy-cache-hours"] == "3"
    assert aged.headers["x-proxy-hours-truncated"] == "true"
    assert proxy.calls == calls


def test_forecast_retry_keeps_336_hours_without_relabeling_success(
    proxy: ProxyHarness,
) -> None:
    """Retries crossing an hour retain successful coverage until a new success."""
    proxy.simulator = proxy.module.SolcastProxy(
        fetch=proxy.fetch,
        now=lambda: proxy.clock[0],
        forecast_cron="55,59 * * * *",
        jitter=lambda: 0,
    )
    with patch.object(proxy.module, "proxy", proxy.simulator):
        proxy.discover()
        assert proxy.read("forecasts", hours=168).status_code == 503
        rows = [
            {
                "period_end": _timestamp(FORECAST_AT + timedelta(hours=3)),
                "period": "PT30M",
                "pv_estimate": 1,
            }
        ]
        proxy.queue(f"/rooftop_sites/{SITE_ID}/forecasts", payload={"forecasts": rows})
        proxy.clock[0] = FORECAST_AT
        proxy.simulator.run_pending()
        assert proxy.read("forecasts", hours=2).headers["x-proxy-cache-hours"] == "3"
        proxy.queue(f"/rooftop_sites/{SITE_ID}/forecasts", 429)
        proxy.clock[0] = datetime(2026, 9, 6, 7, 59, 50, tzinfo=UTC)
        proxy.simulator.run_pending()
        failed = proxy.read("forecasts", hours=2)
        assert failed.status_code == 429
        assert failed.headers["x-proxy-cache-hours"] == "3"
        proxy.clock[0] = _header_time(failed, "x-proxy-next-attempt-at")
        assert proxy.clock[0] == datetime(2026, 9, 6, 8, 0, 5, tzinfo=UTC)
        proxy.queue(f"/rooftop_sites/{SITE_ID}/forecasts", 429)
        proxy.simulator.run_pending()
        assert proxy.resource_calls("forecasts")[-1][1]["hours"] == ["336"]
        failed_again = proxy.read("forecasts", hours=2)
        assert failed_again.headers["x-proxy-cache-hours"] == "3"
        assert proxy.simulator.resources[(API_KEY, SITE_ID, "forecasts")].hours == 3
        proxy.clock[0] = _header_time(failed_again, "x-proxy-next-attempt-at")
        fresh = [
            {
                "period_end": _timestamp(proxy.clock[0] + timedelta(hours=1.5)),
                "period": "PT30M",
                "pv_estimate": 2,
            }
        ]
        proxy.queue(f"/rooftop_sites/{SITE_ID}/forecasts", payload={"forecasts": fresh})
        proxy.simulator.run_pending()
        recovered = proxy.read("forecasts", hours=2)
        assert recovered.status_code == 200
        assert recovered.get_json() == {"forecasts": fresh}
        assert recovered.headers["x-proxy-cache-hours"] == "2"
        assert recovered.headers["x-proxy-hours-truncated"] == "true"
        assert [query["hours"] for _, query in proxy.resource_calls("forecasts")] == [
            ["336"],
            ["336"],
            ["336"],
            ["336"],
        ]


def test_custom_schedules_horizons_backoff_and_jitter(proxy: ProxyHarness) -> None:
    """Custom schedules keep fixed collection hours with retry jitter."""
    proxy.simulator = proxy.module.SolcastProxy(
        fetch=proxy.fetch,
        now=lambda: proxy.clock[0],
        forecast_cron="56 7 * * *",
        actuals_cron="0 8 * * *",
        max_attempts=2,
        retry_backoff=20,
        jitter=lambda: 4,
    )
    with patch.object(proxy.module, "proxy", proxy.simulator):
        proxy.discover()
        assert proxy.read("estimated_actuals", hours=48).status_code == 503
        forecast_at = datetime(2026, 9, 6, 7, 56, tzinfo=UTC)
        assert _header_time(proxy.read("forecasts", hours=96), "x-proxy-next-attempt-at") == forecast_at
        path = f"/rooftop_sites/{SITE_ID}/forecasts"
        proxy.queue(path, 503)
        proxy.queue(path, 503)
        proxy.clock[0] = forecast_at
        proxy.simulator.run_pending()
        assert _header_time(proxy.read("forecasts", hours=96), "x-proxy-next-attempt-at") == forecast_at + timedelta(seconds=24)
        proxy.clock[0] += timedelta(seconds=24)
        proxy.simulator.run_pending()
        assert proxy.read("forecasts", hours=96).headers["x-proxy-last-fetch-status"] == "give_up"
        assert len(proxy.resource_calls("forecasts")) == 2
        assert [query["hours"] for _, query in proxy.resource_calls("forecasts")] == [
            ["336"],
            ["336"],
        ]
        proxy.clock[0] = datetime(2026, 9, 6, 8, tzinfo=UTC)
        proxy.simulator.run_pending()
        assert proxy.resource_calls("estimated_actuals")[0][1]["hours"] == ["168"]


def test_parser_accepts_ports_and_schedules(
    proxy: ProxyHarness,
) -> None:
    """CLI options configure ports and schedules without caller credentials."""
    args = proxy.module.build_parser().parse_args(
        [
            "--solcast-host",
            "upstream.example",
            "--solcast-port",
            "8443",
            "--host",
            "0.0.0.0",
            "--port",
            "9443",
            "--forecast-cron",
            "5 * * * *",
            "--actuals-cron",
            "10 23 * * *",
        ]
    )
    expected = {
        "solcast_host": "upstream.example",
        "solcast_port": 8443,
        "no_verify": False,
        "host": "0.0.0.0",
        "port": 9443,
        "forecast_cron": "5 * * * *",
        "actuals_cron": "10 23 * * *",
    }
    for name, value in expected.items():
        assert getattr(args, name) == value


def test_parser_schedule_defaults(proxy: ProxyHarness) -> None:
    """Default CLI schedules expose no timezone or horizon configuration."""
    args = proxy.module.build_parser().parse_args([])
    assert not hasattr(args, "timezone")
    assert not hasattr(args, "forecast_hours")
    assert not hasattr(args, "actuals_hours")
    assert args.forecast_cron == FORECAST_CRON
    assert args.actuals_cron == ACTUALS_CRON
    assert args.no_verify is False


def test_parser_accepts_no_verify_opt_out(proxy: ProxyHarness) -> None:
    """CLI allows explicit upstream certificate verification opt-out."""
    args = proxy.module.build_parser().parse_args(["--no-verify"])
    assert args.no_verify is True


@pytest.mark.parametrize("option", ["forecast_hours", "actuals_hours", "timezone"])
def test_constructor_rejects_removed_options(proxy: ProxyHarness, option: str) -> None:
    """Startup cannot configure horizons or a forecast timezone."""
    with pytest.raises(TypeError, match=option):
        proxy.module.SolcastProxy(**{option: 48})


@pytest.mark.parametrize("upstream_status", [429, 503])
def test_transport_preserves_http_error_retry_after(proxy: ProxyHarness, upstream_status: int) -> None:
    """HTTP errors retain payloads and Retry-After for scheduler decisions."""
    headers = Message()
    headers["Retry-After"] = "42"
    payload = {"response_status": {"error_code": "test-error"}}
    error = HTTPError(
        "https://upstream.example/rooftop_sites",
        upstream_status,
        "upstream error",
        headers,
        BytesIO(json.dumps(payload).encode()),
    )
    with patch.object(proxy.module.urllib_request, "urlopen", side_effect=error):
        result = proxy.module._fetch_upstream("/rooftop_sites", "format=json")
    assert isinstance(result, proxy.module.UpstreamResponse)
    assert result.status == upstream_status
    assert result.payload == payload
    assert {key.lower(): value for key, value in result.headers.items()}["retry-after"] == "42"


def test_transport_preserves_success_payload_and_headers(proxy: ProxyHarness) -> None:
    """Successful transport returns decoded JSON and upstream headers."""
    upstream = MagicMock()
    upstream.status = 200
    upstream.read.return_value = b'{"sites": []}'
    upstream.headers = {"Retry-After": "5"}
    upstream.__enter__.return_value = upstream
    query = urlencode({"format": "json", "api_key": API_KEY})
    with patch.object(proxy.module.urllib_request, "urlopen", return_value=upstream) as urlopen:
        result = proxy.module._fetch_upstream("/rooftop_sites", query)
    assert result.status == 200
    assert result.payload == {"sites": []}
    assert {key.lower(): value for key, value in result.headers.items()}["retry-after"] == "5"
    request = urlopen.call_args.args[0]
    context = urlopen.call_args.kwargs["context"]
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert urlsplit(request.full_url).scheme == "https"
    assert urlsplit(request.full_url).path == "/rooftop_sites"
    assert parse_qs(urlsplit(request.full_url).query) == {
        "format": ["json"],
        "api_key": [API_KEY],
    }


def test_transport_disables_ssl_verification_when_opted_out(proxy: ProxyHarness) -> None:
    """Explicit opt-out disables upstream certificate and hostname checks."""
    upstream = MagicMock()
    upstream.status = 200
    upstream.read.return_value = b"{}"
    upstream.headers = {}
    upstream.__enter__.return_value = upstream
    proxy.module.app.config["VERIFY_UPSTREAM_SSL"] = False
    try:
        with patch.object(proxy.module.urllib_request, "urlopen", return_value=upstream) as urlopen:
            proxy.module._fetch_upstream("/rooftop_sites", "format=json")
    finally:
        proxy.module.app.config["VERIFY_UPSTREAM_SSL"] = True
    context = urlopen.call_args.kwargs["context"]
    assert context.verify_mode == ssl.CERT_NONE
    assert context.check_hostname is False


def test_transport_maps_network_error_to_retryable_502(proxy: ProxyHarness) -> None:
    """Network errors become structured retryable upstream responses."""
    with patch.object(proxy.module.urllib_request, "urlopen", side_effect=URLError("offline")):
        result = proxy.module._fetch_upstream("/rooftop_sites", "format=json")
    assert result.status == 502
    assert result.payload is None
    assert result.detail == "URLError"


@pytest.mark.parametrize("retry_after", ["60", "Sun, 06 Sep 2026 07:56:00 GMT"])
def test_retry_after_controls_actual_due_time(proxy: ProxyHarness, retry_after: str) -> None:
    """Honor upstream retry guidance without allowing reads to move the timer."""
    proxy.discover()
    proxy.queue(f"/rooftop_sites/{SITE_ID}/forecasts", 429, headers={"Retry-After": retry_after})
    proxy.clock[0] = FORECAST_AT
    proxy.simulator.run_pending()
    response = proxy.read("forecasts")
    assert _header_time(response, "x-proxy-next-attempt-at") == FORECAST_AT + timedelta(seconds=60)
    status = proxy.client.get("/proxy-status").get_json()
    assert status["resources"][SITE_ID]["forecasts"]["rateLimitHeaders"] == {"Retry-After": retry_after}
    proxy.clock[0] += timedelta(seconds=59)
    proxy.simulator.run_pending()
    assert len(proxy.resource_calls("forecasts")) == 1
    proxy.clock[0] += timedelta(seconds=1)
    proxy.simulator.run_pending()
    assert len(proxy.resource_calls("forecasts")) == 2


@pytest.mark.parametrize("jitter", [0, 14])
@pytest.mark.parametrize("kind", KINDS)
def test_repeated_429_matches_integration_backoff(proxy: ProxyHarness, kind: str, jitter: int) -> None:
    """Ten attempts have nine increasing delays, all inside the task deadline."""
    proxy.simulator.jitter = lambda: jitter
    proxy.discover()
    path = f"/rooftop_sites/{SITE_ID}/{kind}"
    for _ in range(10):
        proxy.queue(path, 429)
    start = _collection_time(kind)
    proxy.clock[0] = start
    for attempt in range(1, 10):
        proxy.simulator.run_pending()
        response = proxy.read(kind)
        assert response.status_code == 429
        assert response.get_json() is None
        next_attempt = _header_time(response, "x-proxy-next-attempt-at")
        assert (next_attempt - proxy.clock[0]).total_seconds() == attempt * 15 + jitter
        proxy.clock[0] = next_attempt
    proxy.simulator.run_pending()
    response = proxy.read(kind)
    assert response.status_code == 429
    assert response.get_json() is None
    assert response.headers["x-proxy-give-up"] == "true"
    assert response.headers["x-proxy-retries-used"] == "9"
    assert len(proxy.resource_calls(kind)) == 10
    horizon = {"forecasts": "336", "estimated_actuals": "168"}[kind]
    assert [query["hours"] for _, query in proxy.resource_calls(kind)] == [[horizon]] * 10
    assert (proxy.clock[0] - start).total_seconds() == 675 + jitter * 9
    assert _header_time(response, "x-proxy-next-attempt-at") == _next_collection_time(kind)


def test_first_network_request_counts_against_cycle_deadline(
    proxy: ProxyHarness,
) -> None:
    """Collection time must count upstream I/O, not start the clock afterward."""
    proxy.discover()
    original_fetch = proxy.fetch
    proxy.queue(f"/rooftop_sites/{SITE_ID}/forecasts", 429, headers={"Retry-After": "850"})

    def slow_fetch(path: str, query: str) -> Any:
        proxy.clock[0] += timedelta(seconds=60)
        return original_fetch(path, query)

    proxy.simulator.fetch = slow_fetch
    proxy.clock[0] = FORECAST_AT
    proxy.simulator.run_pending()
    response = proxy.read("forecasts")
    assert response.status_code == 429
    assert response.headers["x-proxy-last-fetch-status"] == "give_up"
    assert _header_time(response, "x-proxy-next-attempt-at") == _next_collection_time("forecasts")
    assert len(proxy.resource_calls("forecasts")) == 1


def test_retry_window_is_bounded_to_fifteen_minutes(proxy: ProxyHarness) -> None:
    """A large Retry-After ends the cycle instead of extending it indefinitely."""
    proxy.discover()
    proxy.queue(f"/rooftop_sites/{SITE_ID}/forecasts", 429, headers={"Retry-After": "901"})
    proxy.clock[0] = FORECAST_AT
    proxy.simulator.run_pending()
    response = proxy.read("forecasts")
    assert response.headers["x-proxy-last-fetch-status"] == "give_up"
    assert _header_time(response, "x-proxy-next-attempt-at") == _next_collection_time("forecasts")
    assert len(proxy.resource_calls("forecasts")) == 1


def test_late_worker_does_not_resume_an_expired_retry_cycle(
    proxy: ProxyHarness,
) -> None:
    """A paused worker must not spend quota on a retry after its hard deadline."""
    proxy.discover()
    proxy.queue(f"/rooftop_sites/{SITE_ID}/forecasts", 429)
    proxy.clock[0] = FORECAST_AT
    proxy.simulator.run_pending()
    proxy.clock[0] += timedelta(minutes=15)
    proxy.simulator.run_pending()
    response = proxy.read("forecasts")
    assert response.headers["x-proxy-last-fetch-status"] == "give_up"
    assert _header_time(response, "x-proxy-next-attempt-at") == _next_collection_time("forecasts")
    assert len(proxy.resource_calls("forecasts")) == 1


def test_paused_retry_expiry_keeps_already_due_cycle(proxy: ProxyHarness) -> None:
    """Paused retry expiry should not skip a cron occurrence that is already due."""
    proxy.discover()
    path = f"/rooftop_sites/{SITE_ID}/estimated_actuals"
    proxy.queue(path, 429)
    proxy.clock[0] = ACTUALS_AT
    proxy.simulator.run_pending()
    # Worker remains paused well past the cycle deadline.
    proxy.clock[0] = ACTUALS_AT + timedelta(days=1, minutes=10)
    proxy.simulator.run_pending()
    response = proxy.read("estimated_actuals")
    assert response.headers["x-proxy-last-fetch-status"] == "clean_success"
    assert len(proxy.resource_calls("estimated_actuals")) == 2


def test_cycle_cutoff_is_anchored_to_cycle_start(proxy: ProxyHarness) -> None:
    """Retry cutoff compares against the cycle's original cron boundary."""
    proxy.simulator.schedules["forecasts"]["cron"] = "* * * * *"
    proxy.discover()
    path = f"/rooftop_sites/{SITE_ID}/forecasts"
    proxy.queue(path, 429, headers={"Retry-After": "20"})
    proxy.clock[0] = datetime(2026, 9, 6, 7, 55, 50, tzinfo=UTC)
    proxy.simulator.run_pending()
    response = proxy.read("forecasts")
    assert response.headers["x-proxy-last-fetch-status"] == "give_up"
    # Retry-After reaches 07:56:10, so the next cron at/after cooldown is 07:57.
    assert _header_time(response, "x-proxy-next-attempt-at") == datetime(2026, 9, 6, 7, 57, tzinfo=UTC)


def test_retry_after_cooldown_is_preserved_across_cycles(proxy: ProxyHarness) -> None:
    """A give-up caused by Retry-After keeps the upstream not-before constraint."""
    proxy.simulator.schedules["forecasts"]["cron"] = "* * * * *"
    proxy.discover()
    path = f"/rooftop_sites/{SITE_ID}/forecasts"
    proxy.queue(path, 429, headers={"Retry-After": "120"})
    proxy.clock[0] = datetime(2026, 9, 6, 7, 55, 50, tzinfo=UTC)
    proxy.simulator.run_pending()
    response = proxy.read("forecasts")
    assert response.headers["x-proxy-last-fetch-status"] == "give_up"
    # Next cron at or after retry_at (07:57:50) is 07:58.
    assert _header_time(response, "x-proxy-next-attempt-at") == datetime(2026, 9, 6, 7, 58, tzinfo=UTC)


def test_background_scheduler_collects_without_a_consumer_read(
    proxy: ProxyHarness,
) -> None:
    """The real worker services due resources independently and stops cleanly."""
    proxy.discover()
    collected = threading.Event()
    original_fetch = proxy.fetch

    def fetch(path: str, query: str) -> Any:
        result = original_fetch(path, query)
        collected.set()
        return result

    proxy.simulator.fetch = fetch
    proxy.clock[0] = FORECAST_AT
    proxy.simulator.start()
    try:
        assert collected.wait(timeout=3)
    finally:
        proxy.simulator.stop()
    assert not proxy.simulator.thread.is_alive()
    assert len(proxy.resource_calls("forecasts")) == 1
    assert proxy.read("forecasts").headers["x-proxy-last-fetch-status"] == "clean_success"


def test_permanent_error_keeps_data_and_other_resource_headers(
    proxy: ProxyHarness,
) -> None:
    """A permanent forecast error cannot erase actuals state or good payloads."""
    proxy.discover()
    proxy.collect("forecasts", {"forecasts": [], "generation": 1})
    proxy.queue(
        f"/rooftop_sites/{SITE_ID}/forecasts",
        payload={"forecasts": [], "generation": 1},
    )
    proxy.collect("estimated_actuals", {"estimated_actuals": [], "generation": 2})
    actuals = proxy.read("estimated_actuals")
    proxy.queue(f"/rooftop_sites/{SITE_ID}/forecasts", 403)
    proxy.clock[0] = datetime(2026, 9, 7, 2, 55, tzinfo=UTC)
    proxy.simulator.run_pending()
    forecast = proxy.read("forecasts")
    assert forecast.status_code == 200
    assert forecast.get_json() == {"forecasts": [], "generation": 1}
    assert forecast.headers["x-proxy-halted"] == "true"
    unchanged = proxy.read("estimated_actuals")
    assert unchanged.get_json() == actuals.get_json()
    assert unchanged.headers["x-proxy-last-fetch-at"] == actuals.headers["x-proxy-last-fetch-at"]
    assert unchanged.headers["x-proxy-halted"] == "false"


@pytest.mark.parametrize("payload", [{}, {"forecasts": "invalid"}, None])
def test_invalid_success_payload_is_a_retryable_failure(proxy: ProxyHarness, payload: Any) -> None:
    """Malformed successful responses cannot masquerade as valid collection."""
    proxy.discover()
    proxy.queue(f"/rooftop_sites/{SITE_ID}/forecasts", payload=payload)
    proxy.clock[0] = FORECAST_AT
    proxy.simulator.run_pending()
    response = proxy.read("forecasts")
    assert response.status_code == 503
    assert response.headers["x-proxy-upstream-status"] == "502"
    assert response.headers["x-proxy-last-fetch-status"] == "retrying"


@pytest.mark.parametrize("kind", KINDS)
def test_resource_first_learns_caller_key_and_multiple_sites(proxy: ProxyHarness, kind: str) -> None:
    """A resource request can be the first contact, without any discovery call."""
    first = proxy.read(kind)
    assert first.status_code == 503
    assert first.headers["x-proxy-last-fetch-status"] == "not_fetched"
    assert _header_time(first, "x-proxy-next-attempt-at") == _collection_time(kind)
    assert proxy.read(kind, site=OTHER_SITE_ID).status_code == 503
    assert proxy.calls == []
    proxy.clock[0] = _collection_time(kind)
    proxy.simulator.run_pending()
    horizon = {"forecasts": "336", "estimated_actuals": "168"}[kind]
    assert proxy.resource_calls(kind) == [
        (
            f"/rooftop_sites/{site}/{kind}",
            {"format": ["json"], "api_key": [API_KEY], "hours": [horizon]},
        )
        for site in (SITE_ID, OTHER_SITE_ID)
    ]
    assert proxy.read(kind).status_code == 200
    assert all(path != "/rooftop_sites" for path, _ in proxy.calls)


@pytest.mark.parametrize("kind", KINDS)
def test_missing_key_cannot_register_or_collect(proxy: ProxyHarness, kind: str) -> None:
    """A caller must provide credentials; startup has no account key defaults."""
    assert proxy.read(kind, api_key="").status_code == 400
    proxy.clock[0] = _collection_time(kind)
    proxy.simulator.run_pending()
    assert proxy.calls == []
    assert proxy.simulator.status()["resources"] == {}


@pytest.mark.parametrize(
    "option",
    [
        "--api-key",
        "--http",
        "--insecure",
        "--solcast-scheme",
        "--cert",
        "--key",
        "--forecast-hours",
        "--actuals-hours",
        "--timezone",
    ],
)
def test_obsolete_credential_and_tls_options_are_rejected(proxy: ProxyHarness, option: str) -> None:
    """Removed credential, TLS, horizon and timezone options are rejected."""
    with pytest.raises(SystemExit) as err:
        proxy.module.build_parser().parse_args([option, "value"])
    assert err.value.code == 2


def test_main_always_uses_adhoc_tls_without_upstream_startup_calls(
    proxy: ProxyHarness,
) -> None:
    """Startup waits for caller keys and always creates an ad-hoc TLS server."""
    configured = MagicMock()
    configured.status.return_value = {"resources": {}}
    with (
        patch.object(proxy.module, "SolcastProxy", return_value=configured) as proxy_class,
        patch.object(proxy.module.app, "run") as run,
    ):
        try:
            proxy.module.main(
                [
                    "--solcast-port",
                    "9443",
                    "--port",
                    "8443",
                ]
            )
        finally:
            proxy.module.app.extensions.pop("solcast_proxy", None)
    assert "timezone" not in proxy_class.call_args.kwargs
    assert run.call_args.kwargs["ssl_context"] == "adhoc"
    configured.discover.assert_not_called()
    configured.start.assert_called_once_with()
    configured.stop.assert_called_once_with()
