"""Tests for the Cloudflare proxy's Durable Object serialization boundary."""

from datetime import UTC, datetime
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def worker_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Load the authoritative Worker without requiring the Cloudflare runtime."""
    js = ModuleType("js")
    js.__dict__.update(Headers=object, Request=object, fetch=AsyncMock())
    workers = ModuleType("workers")
    workers.__dict__.update(DurableObject=object, Response=object, WorkerEntrypoint=object)
    monkeypatch.setitem(sys.modules, "js", js)
    monkeypatch.setitem(sys.modules, "workers", workers)
    name = "tests.components.solcast_solar._proxy_cloudflare_test"
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name("proxy_cloudflare.py"))
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


async def test_storage_round_trip(worker_module: ModuleType) -> None:
    """Store a cloneable JSON string and restore Python state without losing accounts."""
    coordinator = object.__new__(worker_module.ProxyCoordinator)
    storage = SimpleNamespace(get=AsyncMock(), put=AsyncMock())
    coordinator.state = SimpleNamespace(storage=storage)
    state = {
        "accounts": {"1": ["test-site"]},
        "resources": {"1|test-site|forecasts": {"status": 200, "payload": {"forecasts": []}}},
        "retry": {
            "active": False,
            "attempts": 0,
            "next_attempt_at": None,
            "last_status": 0,
        },
    }

    await coordinator._save(state)

    storage.put.assert_awaited_once_with("state", json.dumps(state))
    storage.get.return_value = storage.put.await_args.args[1]
    assert await coordinator._load() == state
    storage.get.assert_awaited_once_with("state")


@pytest.mark.parametrize("stored", [None, "{}", {}], ids=["empty", "json", "dict"])
async def test_storage_defaults(worker_module: ModuleType, stored: str | dict[str, object] | None) -> None:
    """Initialize missing fields for fresh or partially populated state."""
    coordinator = object.__new__(worker_module.ProxyCoordinator)
    coordinator.state = SimpleNamespace(storage=SimpleNamespace(get=AsyncMock(return_value=stored)))

    assert await coordinator._load() == {
        "accounts": {},
        "resources": {},
        "retry": {
            "active": False,
            "attempts": 0,
            "next_attempt_at": None,
            "last_status": 0,
        },
    }


async def test_discovery_response_headers(worker_module: ModuleType) -> None:
    """Pass discovery headers into the SDK response constructor."""
    coordinator = object.__new__(worker_module.ProxyCoordinator)
    coordinator.env = SimpleNamespace()
    coordinator._discover = AsyncMock(return_value=(200, {"sites": []}, ""))
    response = SimpleNamespace(headers={"content-type": "application/json"})

    with patch.object(worker_module, "_json_response", return_value=response) as make_response:
        result = await coordinator.fetch(SimpleNamespace(url="https://localhost/rooftop_sites?api_key=1"))

    assert result is response
    assert result.headers["content-type"] == "application/json"
    make_response.assert_called_once_with({"sites": []}, 200, worker_module._discovery_headers(coordinator.env))
    coordinator._discover.assert_awaited_once_with("1")


@pytest.mark.parametrize(
    "sites",
    [pytest.param(["retained", "new"], id="changed"), pytest.param([], id="empty")],
)
async def test_discovery_removes_stale_sites(worker_module: ModuleType, sites: list[str]) -> None:
    """Reconcile both resource kinds without changing another account's cache or retries."""
    coordinator = object.__new__(worker_module.ProxyCoordinator)
    coordinator.env = SimpleNamespace()
    state = {
        "accounts": {"1": ["removed", "retained"], "2": ["removed"]},
        "resources": {
            worker_module._resource_id(api_key, site, kind): worker_module.asdict(
                worker_module.ResourceState(
                    api_key=api_key,
                    site=site,
                    kind=kind,
                    payload={kind: []},
                    status=200,
                )
            )
            for api_key, site in [("1", "removed"), ("1", "retained"), ("2", "removed")]
            for kind in worker_module._RESOURCE_KINDS
        },
        "retry": worker_module.asdict(worker_module.RetryState(active=True, attempts=1)),
    }
    original_resources = dict(state["resources"])
    storage = SimpleNamespace(
        get=AsyncMock(return_value=json.dumps(state)),
        put=AsyncMock(),
        deleteAlarm=AsyncMock(),
    )
    coordinator.state = SimpleNamespace(storage=storage)
    payload = {"sites": [{"resource_id": site} for site in sites]}

    with patch.object(
        worker_module,
        "_fetch_upstream",
        new=AsyncMock(return_value=(200, payload, "", {})),
    ):
        assert await coordinator._discover("1") == (200, payload, "")

    saved = json.loads(storage.put.await_args.args[1])
    assert saved["accounts"] == {"1": sorted(sites), "2": ["removed"]}
    assert set(saved["resources"]) == {
        worker_module._resource_id(api_key, site, kind)
        for api_key, site in [("1", site) for site in sites] + [("2", "removed")]
        for kind in worker_module._RESOURCE_KINDS
    }
    for rid in original_resources.keys() & saved["resources"].keys():
        assert saved["resources"][rid] == original_resources[rid]
    assert saved["retry"] == state["retry"]
    storage.deleteAlarm.assert_not_awaited()

    with patch.object(
        coordinator,
        "_collect_one",
        new=AsyncMock(side_effect=lambda resource, hours: (resource, True, False, False)),
    ) as collect:
        storage.get.return_value = json.dumps(saved)
        await coordinator._run_cycle()
    assert {call.args[0].site for call in collect.await_args_list if call.args[0].api_key == "1"} == set(sites)


async def test_discovery_removes_last_site_and_alarm(worker_module: ModuleType) -> None:
    """Cancel an outstanding retry when no resources remain."""
    coordinator = object.__new__(worker_module.ProxyCoordinator)
    coordinator.env = SimpleNamespace()
    state = {
        "accounts": {"1": ["removed"]},
        "resources": {
            worker_module._resource_id("1", "removed", kind): worker_module.asdict(
                worker_module.ResourceState(api_key="1", site="removed", kind=kind)
            )
            for kind in worker_module._RESOURCE_KINDS
        },
        "retry": worker_module.asdict(worker_module.RetryState(active=True, attempts=1)),
    }
    storage = SimpleNamespace(
        get=AsyncMock(return_value=json.dumps(state)),
        put=AsyncMock(),
        deleteAlarm=AsyncMock(),
    )
    coordinator.state = SimpleNamespace(storage=storage)

    with patch.object(
        worker_module,
        "_fetch_upstream",
        new=AsyncMock(return_value=(200, {"sites": []}, "", {})),
    ):
        await coordinator._discover("1")

    saved = json.loads(storage.put.await_args.args[1])
    assert saved["accounts"] == {"1": []}
    assert saved["resources"] == {}
    assert saved["retry"] == worker_module.asdict(worker_module.RetryState())
    storage.deleteAlarm.assert_awaited_once_with()


@pytest.mark.parametrize(
    ("status", "payload", "expected_status"),
    [
        pytest.param(429, {"error": "rate limited"}, 429, id="rate-limited"),
        pytest.param(500, None, 500, id="server-error"),
        pytest.param(200, None, 502, id="not-json"),
        pytest.param(200, {}, 502, id="missing-sites"),
        pytest.param(200, {"sites": None}, 502, id="invalid-sites"),
        pytest.param(200, {"sites": [{}]}, 502, id="missing-id"),
        pytest.param(200, {"sites": [{"resource_id": ""}]}, 502, id="empty-id"),
        pytest.param(200, {"sites": [{"resource_id": 1}]}, 502, id="non-string-id"),
        pytest.param(200, {"sites": [None]}, 502, id="invalid-site"),
        pytest.param(200, {"sites": [{"resource_id": "retained"}, {}]}, 502, id="partly-invalid"),
    ],
)
async def test_discovery_failure_preserves_state(worker_module: ModuleType, status: int, payload: object, expected_status: int) -> None:
    """Never treat an unsuccessful or malformed discovery as site removal."""
    coordinator = object.__new__(worker_module.ProxyCoordinator)
    coordinator.env = SimpleNamespace()
    coordinator._load = AsyncMock()
    coordinator._save = AsyncMock()

    with patch.object(
        worker_module,
        "_fetch_upstream",
        new=AsyncMock(return_value=(status, payload, "", {})),
    ):
        result_status, _, _ = await coordinator._discover("1")

    assert result_status == expected_status
    coordinator._load.assert_not_awaited()
    coordinator._save.assert_not_awaited()


def test_json_response_includes_headers(worker_module: ModuleType) -> None:
    """Include proxy headers in the constructor, not a detached header dictionary."""
    with patch.object(worker_module, "Response") as response:
        worker_module._json_response({"sites": []}, 200, {"x-solcast-proxy": "true"})
    response.assert_called_once_with(
        '{"sites": []}',
        status=200,
        headers=[("content-type", "application/json"), ("x-solcast-proxy", "true")],
    )


@pytest.mark.parametrize("kind", ["forecasts", "estimated_actuals"])
async def test_resource_route_uses_site_id(worker_module: ModuleType, kind: str) -> None:
    """Route using the site's path segment, not the resource kind."""
    coordinator = object.__new__(worker_module.ProxyCoordinator)
    coordinator._resource_response = AsyncMock()
    url = f"https://localhost/rooftop_sites/test-site/{kind}?api_key=1&hours=24"

    await coordinator.fetch(SimpleNamespace(url=url))

    coordinator._resource_response.assert_awaited_once_with(url, "test-site", kind)


@pytest.mark.parametrize("period", ["PT30M", "PT0H30M0S", "PT1800S"])
def test_forecast_slicing_without_period_start(worker_module: ModuleType, period: str) -> None:
    """Keep overlapping forecast rows when the API supplies only end and duration."""
    rows = [
        {"period_end": f"2026-11-06T{time}:00Z", "period": period, "pv_estimate": 1.0}
        for time in ("12:00", "12:30", "13:00", "13:30", "14:00")
    ]
    now = datetime(2026, 11, 6, 12, 15, tzinfo=UTC)

    assert worker_module._slice_rows(rows, "forecasts", now, 1) == rows[1:4]


async def test_actuals_coverage_without_period_start(worker_module: ModuleType) -> None:
    """Measure actuals coverage using period duration instead of a missing start."""
    coordinator = object.__new__(worker_module.ProxyCoordinator)
    coordinator.env = SimpleNamespace()
    resource = worker_module.ResourceState(api_key="1", site="test-site", kind="estimated_actuals")
    payload = {
        "estimated_actuals": [
            {"period_end": "2026-11-06T12:00:00Z", "period": "PT30M"},
            {"period_end": "2026-11-06T12:30:00Z", "period": "PT30M"},
        ]
    }
    with patch.object(
        worker_module,
        "_fetch_upstream",
        new=AsyncMock(return_value=(200, payload, "", {})),
    ):
        updated, success, retryable, rate_limited = await coordinator._collect_one(resource, 168)

    assert success
    assert not retryable
    assert not rate_limited
    assert updated.history_hours == 1
    assert updated.hours == 1
