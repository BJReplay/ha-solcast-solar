"""Tests for the Solcast WSGI simulator CLI."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import importlib.util
import json
import math
from pathlib import Path
import sys
from types import ModuleType
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.solcast_solar.const import (
    ESTIMATED_ACTUALS,
    FORECASTS,
    SITES,
)

pytest.importorskip("flask", reason="Flask is required to run simulator tests")
pytest.importorskip("isodate", reason="isodate is required to run simulator tests")


def _load_wsgi_sim_module() -> ModuleType:
    """Load the WSGI simulator module without starting the server."""

    module_name = "tests.components.solcast_solar._wsgi_sim_test"
    module_path = Path(__file__).with_name("wsgi_sim.py")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise AssertionError("Could not load wsgi_sim module")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    sys.path.insert(0, str(module_path.parent))
    try:
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("subprocess.check_call", return_value=None),
            patch("os.execl", return_value=None),
            patch("sys.exit", return_value=None),
            patch("logging.config.dictConfig", return_value=None),
        ):
            spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _test_client(module: ModuleType):
    """Return a Flask test client with 418 responses disabled."""
    setattr(module, "BOMB_418", False)  # noqa: B010
    module.app.config["TESTING"] = True  # type: ignore[attr-defined]
    return module.app.test_client()  # type: ignore[attr-defined]


@pytest.fixture
def bounded_route_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Isolate API state and disable failures and guidance for route tests."""
    module = _load_wsgi_sim_module()
    sites = deepcopy(module.API_KEY_SITES)
    for api_key in sites.values():
        api_key["counter"] = 0
    monkeypatch.setattr(module, "API_KEY_SITES", sites)
    monkeypatch.setattr(sys.modules[module.SimulatedSolcast.__module__], "API_KEY_SITES", sites)
    monkeypatch.setattr(module, "BOMB_KEY", [])
    monkeypatch.setattr(module, "BOMB_429", [])
    monkeypatch.setattr(module, "BOMB_418", False)
    monkeypatch.setattr(module, "GUIDANCE_FILE", None)
    monkeypatch.setattr(module, "GUIDANCE_MTIME", None)
    monkeypatch.setattr(module, "simulate", module.SimulatedSolcast())
    module.simulate.set_time_zone(ZoneInfo("UTC"))
    return module


@pytest.mark.parametrize(
    ("route", "response_key", "fields", "maximum", "oversized", "start", "end"),
    [
        pytest.param(
            "/rooftop_sites/1111-1111-1111-1111/forecasts",
            FORECASTS,
            ("pv_estimate", "pv_estimate10", "pv_estimate90"),
            336,
            400,
            0,
            1,
            id="rooftop-forecasts",
        ),
        pytest.param(
            "/rooftop_sites/1111-1111-1111-1111/estimated_actuals",
            ESTIMATED_ACTUALS,
            ("pv_estimate",),
            168,
            300,
            -1,
            0,
            id="rooftop-actuals",
        ),
        pytest.param(
            "/data/forecast/advanced_pv_power",
            FORECASTS,
            ("pv_power_advanced", "pv_power_advanced10", "pv_power_advanced90"),
            336,
            400,
            0,
            1,
            id="advanced-forecasts",
        ),
    ],
)
@pytest.mark.parametrize("request_size", ["small", "maximum", "oversized", "huge"])
@pytest.mark.parametrize("minute", [0, 17], ids=["aligned", "overlapping-period"])
def test_route_hours_bounds(
    bounded_route_module: ModuleType,
    freezer: FrozenDateTimeFactory,
    route: str,
    response_key: str,
    fields: tuple[str, ...],
    maximum: int,
    oversized: int,
    start: int,
    end: int,
    request_size: str,
    minute: int,
) -> None:
    """HTTP horizons are capped, bounded, numeric and never padded."""
    now = datetime(2026, 9, 6, 8, minute, tzinfo=UTC)
    freezer.move_to(now)
    hours = {
        "small": 8,
        "maximum": maximum,
        "oversized": oversized,
        "huge": 10**100,
    }[request_size]
    clamped_hours = min(hours, maximum)
    client = _test_client(bounded_route_module)
    query = {"api_key": "1", "resource_id": "1111-1111-1111-1111", "hours": hours}
    response = client.get(route, query_string=query)
    assert response.status_code == 200
    payload = response.get_json()
    periods = payload[response_key]
    assert len(periods) == clamped_hours * 2
    lower = now + timedelta(hours=start * clamped_hours)
    upper = now + timedelta(hours=end * clamped_hours)
    period_ends = [datetime.fromisoformat(period["period_end"]) for period in periods]
    assert all(lower < period_end.astimezone(UTC) <= upper for period_end in period_ends)
    assert period_ends == sorted(set(period_ends))
    for period in periods:
        assert period["period"] == "PT30M"
        assert set(period) == {"period_end", "period", *fields}
        for field in fields:
            assert type(period[field]) in (int, float)
            assert math.isfinite(period[field])

    capped_response = client.get(route, query_string=query | {"hours": clamped_hours})
    assert capped_response.status_code == 200
    assert payload == capped_response.get_json()


def test_route_actuals_guidance_is_not_padded(
    bounded_route_module: ModuleType,
    freezer: FrozenDateTimeFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing recorder-backed days stay absent from the capped actuals response."""
    now = datetime(2026, 9, 6, 8, tzinfo=UTC)
    freezer.move_to(now)
    monkeypatch.setattr(bounded_route_module.simulate, "_guidance_file_loaded", True)
    bounded_route_module.simulate.set_forecast_guidance({}, {"2026-09-06"})
    client = _test_client(bounded_route_module)
    response = client.get(
        "/rooftop_sites/1111-1111-1111-1111/estimated_actuals",
        query_string={"api_key": "1", "hours": 300},
    )
    assert response.status_code == 200
    periods = response.get_json()[ESTIMATED_ACTUALS]
    assert len(periods) == 17
    assert [datetime.fromisoformat(period["period_end"]) for period in periods] == [
        now.replace(hour=0) + timedelta(minutes=30 * index) for index in range(17)
    ]
    assert all(type(period["pv_estimate"]) in (int, float) for period in periods)
    assert all(math.isfinite(period["pv_estimate"]) for period in periods)


@pytest.mark.parametrize(
    ("kind", "maximum", "collection_hours"),
    [(FORECASTS, 336, 336), (ESTIMATED_ACTUALS, 168, 168)],
)
def test_proxy_collects_capped_wsgi_data(
    bounded_route_module: ModuleType,
    freezer: FrozenDateTimeFactory,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    maximum: int,
    collection_hours: int,
) -> None:
    """The real proxy serves bounded simulator data without any network calls."""
    name = "tests.components.solcast_solar._proxy_wsgi_test"
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name("proxy.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    upstream = _test_client(bounded_route_module)
    calls: list[tuple[str, dict[str, list[str]]]] = []

    def fetch(path: str, query: str) -> Any:
        calls.append((path, parse_qs(query)))
        response = upstream.get(path, query_string=query)
        return module.UpstreamResponse(response.status_code, response.get_json())

    clock = [datetime(2026, 9, 6, 7, 59, tzinfo=UTC)]
    freezer.move_to(clock[0])
    configured = module.SolcastProxy(
        fetch=fetch,
        now=lambda: clock[0],
        forecast_cron="* * * * *",
        actuals_cron="* * * * *",
    )
    monkeypatch.setattr(module, "proxy", configured)
    client = module.app.test_client()
    path = f"/rooftop_sites/1111-1111-1111-1111/{kind}"
    query = {"api_key": "1", "hours": maximum, "format": "json"}
    assert client.get(path, query_string=query).status_code == 503
    assert calls == []
    clock[0] += timedelta(minutes=1)
    freezer.move_to(clock[0])
    configured.run_pending()
    assert len(calls) == 2
    assert (
        path,
        {"api_key": ["1"], "format": ["json"], "hours": [str(collection_hours)]},
    ) in calls
    full = client.get(path, query_string=query)
    assert full.status_code == 200
    assert len(full.get_json()[kind]) == maximum * 2
    assert full.headers["x-proxy-cache-hours"] == str(maximum)
    assert full.headers["x-proxy-hours-truncated"] == "false"
    oversized = client.get(path, query_string=query | {"hours": 1000})
    assert oversized.get_json() == full.get_json()
    assert oversized.headers["x-proxy-hours-truncated"] == "true"
    small = client.get(path, query_string=query | {"hours": 8})
    assert len(small.get_json()[kind]) == 16
    assert len(calls) == 2


@pytest.mark.parametrize("hours", [8, 300])
def test_route_historic_advanced_duration_unchanged(
    bounded_route_module: ModuleType,
    freezer: FrozenDateTimeFactory,
    hours: int,
) -> None:
    """Historical advanced durations keep the shared generator's extra periods."""
    now = datetime(2026, 9, 6, 8, tzinfo=UTC)
    freezer.move_to(now)
    start = now - timedelta(hours=hours)
    client = _test_client(bounded_route_module)
    response = client.get(
        "/data/historic/advanced_pv_power",
        query_string={
            "api_key": "1",
            "resource_id": "1111-1111-1111-1111",
            "start": start.isoformat(),
            "duration": f"PT{hours}H",
        },
    )
    assert response.status_code == 200
    periods = response.get_json()[ESTIMATED_ACTUALS]
    assert len(periods) == (hours + 1) * 2
    assert datetime.fromisoformat(periods[0]["period_end"]) == start + timedelta(minutes=30)
    assert datetime.fromisoformat(periods[-1]["period_end"]) == now + timedelta(hours=1)


def test_wsgi_sim_parser_accepts_port() -> None:
    """The simulator parser accepts an explicit TCP port."""
    module = _load_wsgi_sim_module()
    args = module.build_parser().parse_args(["--port", "8443"])
    assert args.port == 8443


def test_wsgi_sim_parser_default_port() -> None:
    """The simulator parser defaults to port 443."""
    module = _load_wsgi_sim_module()
    args = module.build_parser().parse_args([])
    assert args.port == module.DEFAULT_PORT


def test_wsgi_sim_parser_all_flags() -> None:
    """The simulator parser accepts all supported flags."""
    module = _load_wsgi_sim_module()
    args = module.build_parser().parse_args(["--limit", "100", "--teapot", "--bomb429", "0-5,15", "--bombkey", "30,45", "--debug"])
    assert args.limit == 100
    assert args.teapot is True
    assert args.bomb429 == "0-5,15"
    assert args.bombkey == "30,45"
    assert args.debug is True


def test_apply_args_defaults() -> None:
    """Default args produce the expected runtime values."""
    module = _load_wsgi_sim_module()
    result = module._apply_args(module.build_parser().parse_args([]))
    assert result["API_LIMIT"] == 50
    assert result["BOMB_418"] is False
    assert result["BOMB_429"] == []
    assert result["BOMB_KEY"] == []
    assert module.simulate.actuals_uncertainty_pct == 2.2


def test_apply_args_limit() -> None:
    """--limit overrides the default API call limit."""
    module = _load_wsgi_sim_module()
    result = module._apply_args(module.build_parser().parse_args(["--limit", "100"]))
    assert result["API_LIMIT"] == 100


def test_load_forecast_guidance_file_updates_actuals_uncertainty(tmp_path: Path) -> None:
    """Guidance reload updates the simulator jitter scale dynamically."""
    module = _load_wsgi_sim_module()
    guidance_path = tmp_path / "guidance.json"
    guidance_path.write_text(
        json.dumps(
            {
                "estimated_actuals_uncertainty_pct": 4.4,
                "days": {},
            }
        ),
        encoding="utf-8",
    )

    module.simulate.set_actuals_uncertainty(1.1)
    module.simulate.load_forecast_guidance_file(str(guidance_path))

    assert module.simulate.actuals_uncertainty_pct == 4.4


def test_load_forecast_guidance_file_updates_timezone(tmp_path: Path) -> None:
    """Guidance reload updates simulator timezone for day/slot indexing."""
    module = _load_wsgi_sim_module()
    guidance_path = tmp_path / "guidance.json"
    guidance_path.write_text(
        json.dumps(
            {
                "timezone": "UTC",
                "days": {},
            }
        ),
        encoding="utf-8",
    )

    module.simulate.set_time_zone(ZoneInfo("Australia/Melbourne"))
    module.simulate.load_forecast_guidance_file(str(guidance_path))

    assert module.simulate.timezone.key == "UTC"


def test_apply_args_teapot() -> None:
    """--teapot enables 418 generation."""
    module = _load_wsgi_sim_module()
    result = module._apply_args(module.build_parser().parse_args(["--teapot"]))
    assert result["BOMB_418"] is True


def test_apply_args_bomb429_plain_values() -> None:
    """--bomb429 with comma-separated plain minutes populates the list correctly."""
    module = _load_wsgi_sim_module()
    result = module._apply_args(module.build_parser().parse_args(["--bomb429", "5,15,30"]))
    assert result["BOMB_429"] == [5, 15, 30]


def test_apply_args_bomb429_range() -> None:
    """--bomb429 with a range expands it into individual minutes."""
    module = _load_wsgi_sim_module()
    result = module._apply_args(module.build_parser().parse_args(["--bomb429", "0-2,15"]))
    assert result["BOMB_429"] == [0, 1, 2, 15]


def test_apply_args_bombkey_range() -> None:
    """--bombkey with a range expands it into individual minutes."""
    module = _load_wsgi_sim_module()
    result = module._apply_args(module.build_parser().parse_args(["--bombkey", "30-31,45"]))
    assert result["BOMB_KEY"] == [30, 31, 45]


def test_route_sites_no_api_key() -> None:
    """GET /rooftop_sites without an api_key returns 500."""
    client = _test_client(_load_wsgi_sim_module())
    assert client.get("/rooftop_sites").status_code == 500


def test_route_sites_invalid_key() -> None:
    """GET /rooftop_sites with an unknown api_key returns 403."""
    client = _test_client(_load_wsgi_sim_module())
    assert client.get("/rooftop_sites?api_key=invalid").status_code == 403


def test_route_sites_valid_key() -> None:
    """GET /rooftop_sites with a valid api_key returns a site list."""
    client = _test_client(_load_wsgi_sim_module())
    response = client.get("/rooftop_sites?api_key=1")
    assert response.status_code == 200
    assert SITES in response.get_json()


def test_route_forecasts_valid() -> None:
    """GET /rooftop_sites/<site_id>/forecasts returns forecast data."""
    client = _test_client(_load_wsgi_sim_module())
    response = client.get("/rooftop_sites/1111-1111-1111-1111/forecasts?api_key=1&hours=8")
    assert response.status_code == 200
    assert FORECASTS in response.get_json()


def test_route_forecasts_missing_hours() -> None:
    """GET /rooftop_sites/<site_id>/forecasts without hours returns 500."""
    client = _test_client(_load_wsgi_sim_module())
    assert client.get("/rooftop_sites/1111-1111-1111-1111/forecasts?api_key=1").status_code == 500


def test_route_forecasts_site_not_found() -> None:
    """GET /rooftop_sites/<site_id>/forecasts with an unknown site returns 404."""
    client = _test_client(_load_wsgi_sim_module())
    assert client.get("/rooftop_sites/0000-0000-0000-0000/forecasts?api_key=1&hours=8").status_code == 404


def test_route_estimated_actuals_valid() -> None:
    """GET /rooftop_sites/<site_id>/estimated_actuals returns actuals data."""
    client = _test_client(_load_wsgi_sim_module())
    response = client.get("/rooftop_sites/1111-1111-1111-1111/estimated_actuals?api_key=1&hours=8")
    assert response.status_code == 200
    assert ESTIMATED_ACTUALS in response.get_json()


def test_route_estimated_actuals_refreshes_guidance() -> None:
    """The estimated actuals route refreshes guidance before responding."""
    module = _load_wsgi_sim_module()
    client = _test_client(module)

    with patch.object(module, "_refresh_guidance") as mock_refresh:
        response = client.get("/rooftop_sites/1111-1111-1111-1111/estimated_actuals?api_key=1&hours=8")

    assert response.status_code == 200
    mock_refresh.assert_called_once()


def test_route_estimated_actuals_missing_hours() -> None:
    """GET /rooftop_sites/<site_id>/estimated_actuals without hours returns 500."""
    client = _test_client(_load_wsgi_sim_module())
    assert client.get("/rooftop_sites/1111-1111-1111-1111/estimated_actuals?api_key=1").status_code == 500


def test_wsgi_sim_main_uses_configured_port() -> None:
    """The simulator starts Flask on the configured TCP port."""
    module = _load_wsgi_sim_module()
    with (
        patch.object(module, "get_time_zone"),
        patch.object(module.random, "seed"),
        patch.object(module.app, "run") as mock_run,
    ):
        module.main(["--port", "8443"])
    mock_run.assert_called_once_with(
        debug=False,
        host="127.0.0.1",
        port=8443,
        ssl_context=("cert.pem", "key.pem"),
    )


def test_wsgi_sim_main_default_port() -> None:
    """The simulator starts Flask on port 443 when no port is specified."""
    module = _load_wsgi_sim_module()
    with (
        patch.object(module, "get_time_zone"),
        patch.object(module.random, "seed"),
        patch.object(module.app, "run") as mock_run,
    ):
        module.main([])
    mock_run.assert_called_once_with(
        debug=False,
        host="127.0.0.1",
        port=443,
        ssl_context=("cert.pem", "key.pem"),
    )


def test_wsgi_sim_main_debug_mode() -> None:
    """--debug passes debug=True to Flask."""
    module = _load_wsgi_sim_module()
    with (
        patch.object(module, "get_time_zone"),
        patch.object(module.random, "seed"),
        patch.object(module.app, "run") as mock_run,
    ):
        module.main(["--debug"])
    mock_run.assert_called_once_with(
        debug=True,
        host="127.0.0.1",
        port=443,
        ssl_context=("cert.pem", "key.pem"),
    )
