"""Exercise integration retries against the cron-driven proxy's HTTP routes."""

from collections import deque
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock
from urllib.parse import parse_qs, urlsplit

from freezegun.api import FrozenDateTimeFactory
import pytest

pytest.importorskip("flask", reason="Flask is required for proxy integration tests")

from flask.testing import FlaskClient

from homeassistant.components.recorder import Recorder
from homeassistant.components.solcast_solar.const import (
    ADVANCED_SSL_VERIFY,
    API_KEY,
    DOMAIN,
    ESTIMATED_ACTUALS,
    FORECASTS,
    ISSUE_API_UNAVAILABLE,
    RESOURCE_ID,
)
from homeassistant.components.solcast_solar.fetcher import Fetcher
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from . import DEFAULT_INPUT1, async_cleanup_integration_tests, async_init_integration


@pytest.fixture(autouse=True)
def frozen_time() -> None:
    """Use the freezer fixture instead of the integration's autouse clock."""


@dataclass
class ProxyRetryHarness:
    """Bridge real integration HTTP requests to an isolated Flask proxy."""

    module: ModuleType
    freezer: FrozenDateTimeFactory
    fetcher: Fetcher
    kind: str
    site: str
    api_key: str
    clock: datetime
    cached_payload: dict[str, Any] = field(default_factory=dict)
    responses: deque[Any] = field(default_factory=deque)
    upstream_calls: list[datetime] = field(default_factory=list)
    polls: list[tuple[datetime, int, Any]] = field(default_factory=list)
    poll_headers: list[dict[str, str]] = field(default_factory=list)
    delays: list[int] = field(default_factory=list)
    simulator: Any = None
    client: FlaskClient = field(init=False)

    def fetch(self, path: str, query_string: str) -> Any:
        """Discover the integration's site and provide queued upstream results."""
        query = parse_qs(query_string)
        assert query[API_KEY] == [self.api_key]
        assert query["format"] == ["json"]
        if path == "/rooftop_sites":
            return self.module.UpstreamResponse(200, {"sites": [{RESOURCE_ID: self.site}]})
        assert path == f"/rooftop_sites/{self.site}/{self.kind}"
        expected_hours = {FORECASTS: 336, ESTIMATED_ACTUALS: 168}[self.kind]
        assert query["hours"] == [str(expected_hours)]
        self.upstream_calls.append(self.clock)
        if self.responses:
            return self.responses.popleft()
        return self.module.UpstreamResponse(429)

    def advance(self, delay: int) -> None:
        """Advance both clocks and execute due cron collections without waiting."""
        self.clock += timedelta(seconds=delay)
        self.freezer.tick(delay)
        self.simulator.run_pending()

    async def sleep(self, delay: int) -> None:
        """Replace only the integration's retry sleep, not asyncio scheduling."""
        self.delays.append(delay)
        self.advance(delay)

    async def get(
        self,
        url: str,
        params: dict[str, str | int],
        headers: dict[str, str],
        ssl: bool,
    ) -> MagicMock:
        """Expose Flask response status and bodies through the aiohttp interface."""
        assert params == {"format": "json", API_KEY: self.api_key, "hours": 48}
        assert ssl is self.fetcher.api.advanced_options[ADVANCED_SSL_VERIFY]
        response = self.client.get(urlsplit(url).path, query_string=params)
        payload = response.get_json()
        self.polls.append((self.clock, response.status_code, payload))
        self.poll_headers.append(dict(response.headers))
        result = MagicMock(status=response.status_code, url=str(url))
        result.headers = response.headers
        result.json = AsyncMock(return_value=payload)
        result.text = AsyncMock(return_value=response.get_data(as_text=True))
        return result

    async def fetch_data(self) -> dict[str, Any] | str | None:
        """Run the production fetcher's full retry and repair-issue handling."""
        return await self.fetcher.fetch_data(
            hours=48,
            path=self.kind,
            site=self.site,
            api_key=self.api_key,
            force=True,
        )


@pytest.fixture
async def proxy_retry(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> AsyncGenerator[ProxyRetryHarness]:
    """Warm a real scheduled cache, then start a rate-limited collection cycle."""
    try:
        clock = datetime(2025, 1, 11, tzinfo=UTC)
        freezer.move_to(clock)
        entry = await async_init_integration(hass, DEFAULT_INPUT1)
        coordinator = entry.runtime_data.coordinator
        solcast = coordinator.solcast
        await coordinator.tasks_cancel()
        await solcast.tasks_cancel()
        await hass.async_block_till_done()

        name = "tests.components.solcast_solar._proxy_retry_integration_proxy"
        spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name("proxy.py"))
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        harness = ProxyRetryHarness(
            module,
            freezer,
            solcast.fetcher,
            kind,
            solcast.sites[0][RESOURCE_ID],
            solcast.sites[0][API_KEY],
            clock,
        )
        harness.simulator = module.SolcastProxy(
            fetch=harness.fetch,
            now=lambda: harness.clock,
            forecast_cron="1 * * * *" if kind == FORECASTS else "45 22 * * *",
            actuals_cron="1 * * * *" if kind == ESTIMATED_ACTUALS else "45 22 * * *",
            jitter=lambda: 14,
        )
        monkeypatch.setattr(module, "proxy", harness.simulator)
        module.app.config["TESTING"] = True
        harness.client = module.app.test_client()
        discovery = harness.client.get(
            "/rooftop_sites",
            query_string={"format": "json", API_KEY: harness.api_key},
        )
        assert discovery.status_code == 200
        assert discovery.get_json() == {"sites": [{RESOURCE_ID: harness.site}]}

        missing = harness.client.get(
            f"/rooftop_sites/{harness.site}/{kind}",
            query_string={"format": "json", API_KEY: harness.api_key, "hours": 48},
        )
        assert missing.status_code == 503
        assert missing.headers["x-proxy-cache-hours"] == "0"
        assert missing.headers["x-proxy-hours-truncated"] == "true"
        assert harness.upstream_calls == []
        period_end = {
            FORECASTS: "2025-01-13T00:00:00Z",
            ESTIMATED_ACTUALS: "2025-01-11T00:01:00Z",
        }[kind]
        cached = {
            kind: [{"period_end": period_end, "period": "PT30M", "pv_estimate": 1}],
            "cache_generation": "last-good",
        }
        harness.cached_payload = cached
        harness.responses.append(module.UpstreamResponse(200, cached))
        harness.advance(60)
        warm = harness.client.get(
            f"/rooftop_sites/{harness.site}/{kind}",
            query_string={"format": "json", API_KEY: harness.api_key, "hours": 48},
        )
        assert warm.status_code == 200
        assert warm.get_json() == cached
        assert warm.headers["x-proxy-cache-hours"] == {FORECASTS: "48", ESTIMATED_ACTUALS: "1"}[kind]
        assert warm.headers["x-proxy-hours-truncated"] == "true"
        # Count only upstream attempts in the subsequent failing/recovering cycle.
        harness.upstream_calls.clear()
        harness.advance(3600)
        assert harness.simulator.status()["resources"][harness.site][kind]["status"] == 429
        assert harness.simulator.resources[(harness.api_key, harness.site, kind)].payload == cached
        harness.advance(5)

        session = MagicMock()
        session.get = AsyncMock(side_effect=harness.get)
        monkeypatch.setattr(solcast, "aiohttp_session", session)
        monkeypatch.setattr(solcast.fetcher, "_sleep", harness.sleep)
        monkeypatch.setattr(
            "homeassistant.components.solcast_solar.fetcher.random.randrange",
            Mock(return_value=14),
        )
        yield harness
    finally:
        await async_cleanup_integration_tests(hass)


@pytest.mark.parametrize(
    "kind",
    [
        pytest.param(FORECASTS, id="forecasts"),
        pytest.param(ESTIMATED_ACTUALS, id="actuals"),
    ],
)
async def test_proxy_retry_exhaustion(
    proxy_retry: ProxyRetryHarness,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Ten null-body 429 polls must not consume retained last-good cached data."""
    start = proxy_retry.clock
    result = await proxy_retry.fetch_data()

    assert result == "429/Try again later after 10 attempts"
    assert [(status, payload) for _, status, payload in proxy_retry.polls] == [(429, None)] * 10
    assert proxy_retry.polls[0][0] == datetime(2025, 1, 11, 1, 1, 5, tzinfo=UTC)
    assert proxy_retry.delays == [attempt * 15 + 14 for attempt in range(1, 10)]
    assert (proxy_retry.clock - start).total_seconds() == 801
    assert (proxy_retry.clock - proxy_retry.upstream_calls[0]).total_seconds() <= 900
    assert len(proxy_retry.upstream_calls) == 10
    assert proxy_retry.upstream_calls[1] - proxy_retry.upstream_calls[0] == timedelta(seconds=34)
    record = proxy_retry.simulator.resources[(proxy_retry.api_key, proxy_retry.site, proxy_retry.kind)]
    assert record.status == 429
    assert record.attempts == 10
    assert record.retries_used == 9
    assert record.give_up is True
    assert record.attempt_result == "give_up"
    assert record.payload == proxy_retry.cached_payload
    horizon = {FORECASTS: 48, ESTIMATED_ACTUALS: 1}[proxy_retry.kind]
    assert record.hours == horizon
    assert {headers["x-proxy-cache-hours"] for headers in proxy_retry.poll_headers} == {str(horizon)}
    assert {headers["x-proxy-hours-truncated"] for headers in proxy_retry.poll_headers} == {"true"}
    assert proxy_retry.poll_headers[0]["x-proxy-last-fetch-status"] == "retrying"
    assert proxy_retry.poll_headers[-1]["x-proxy-upstream-status"] == "429"
    assert proxy_retry.poll_headers[-1]["x-proxy-retries-used"] == "9"
    assert proxy_retry.poll_headers[-1]["x-proxy-give-up"] == "true"
    assert proxy_retry.poll_headers[-1]["x-proxy-last-fetch-status"] == "give_up"
    issue = issue_registry.async_get_issue(DOMAIN, ISSUE_API_UNAVAILABLE)
    assert issue is not None
    assert issue.is_fixable is False
    assert issue.severity is ir.IssueSeverity.WARNING


@pytest.mark.parametrize(
    "kind",
    [
        pytest.param(FORECASTS, id="forecasts"),
        pytest.param(ESTIMATED_ACTUALS, id="actuals"),
    ],
)
async def test_proxy_retry_recovery(
    proxy_retry: ProxyRetryHarness,
    hass: HomeAssistant,
    issue_registry: ir.IssueRegistry,
) -> None:
    """A scheduled retry success returns fresh data and clears an existing issue."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_API_UNAVAILABLE,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_API_UNAVAILABLE,
    )
    assert issue_registry.async_get_issue(DOMAIN, ISSUE_API_UNAVAILABLE) is not None
    period_end = {
        FORECASTS: "2025-01-13T00:00:00Z",
        ESTIMATED_ACTUALS: "2025-01-11T01:01:00Z",
    }[proxy_retry.kind]
    payload = {proxy_retry.kind: [{"period_end": period_end, "period": "PT30M", "pv_estimate": 2}]}
    proxy_retry.responses.append(proxy_retry.module.UpstreamResponse(200, payload))
    start = proxy_retry.clock

    result = await proxy_retry.fetch_data()

    assert result == payload
    assert [(status, body) for _, status, body in proxy_retry.polls] == [
        (429, None),
        (200, payload),
    ]
    assert proxy_retry.delays == [29]
    assert proxy_retry.polls[0][0] == datetime(2025, 1, 11, 1, 1, 5, tzinfo=UTC)
    assert proxy_retry.polls[1][0] == datetime(2025, 1, 11, 1, 1, 34, tzinfo=UTC)
    assert (proxy_retry.clock - start).total_seconds() == 29
    assert (proxy_retry.clock - proxy_retry.upstream_calls[0]).total_seconds() <= 900
    assert len(proxy_retry.upstream_calls) == 2
    assert proxy_retry.upstream_calls[1] - proxy_retry.upstream_calls[0] == timedelta(seconds=34)
    record = proxy_retry.simulator.resources[(proxy_retry.api_key, proxy_retry.site, proxy_retry.kind)]
    assert record.status == 200
    assert record.attempt_result == "retry_success"
    assert record.payload == payload
    horizon = {FORECASTS: 47, ESTIMATED_ACTUALS: 1}[proxy_retry.kind]
    assert record.hours == horizon
    assert proxy_retry.poll_headers[0]["x-proxy-cache-hours"] == {FORECASTS: "48", ESTIMATED_ACTUALS: "1"}[proxy_retry.kind]
    assert proxy_retry.poll_headers[-1]["x-proxy-cache-hours"] == str(horizon)
    assert proxy_retry.poll_headers[-1]["x-proxy-hours-truncated"] == "true"
    assert proxy_retry.poll_headers[-1]["x-proxy-upstream-status"] == "200"
    assert proxy_retry.poll_headers[-1]["x-proxy-retries-used"] == "1"
    assert proxy_retry.poll_headers[-1]["x-proxy-give-up"] == "false"
    assert proxy_retry.poll_headers[-1]["x-proxy-last-fetch-status"] == "retry_success"
    assert issue_registry.async_get_issue(DOMAIN, ISSUE_API_UNAVAILABLE) is None
