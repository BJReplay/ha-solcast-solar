"""Tests for the Solcast WSGI simulator CLI."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import importlib.util
import json
import math
from pathlib import Path
import ssl
import sys
from types import ModuleType
from unittest.mock import patch
from zoneinfo import ZoneInfo

from cryptography import x509
from custom_components.solcast_solar.const import ESTIMATED_ACTUALS, FORECASTS, SITES
from freezegun.api import FrozenDateTimeFactory
import pytest

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


@pytest.mark.parametrize(
    ("args", "port", "debug"),
    [
        pytest.param(["--port", "8443"], 8443, False, id="configured-port"),
        pytest.param([], 443, False, id="default-port"),
        pytest.param(["--debug"], 443, True, id="debug"),
    ],
)
def test_wsgi_sim_main(args: list[str], port: int, debug: bool) -> None:
    """The simulator uses ephemeral TLS without a reloader replacing its certificate."""
    module = _load_wsgi_sim_module()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    with (
        patch.object(module, "get_time_zone"),
        patch.object(module.random, "seed"),
        patch.object(module, "_ssl_context") as mock_context,
        patch.object(module.app, "run") as mock_run,
    ):
        mock_context.return_value.__enter__.return_value = context
        module.main(args)
    mock_run.assert_called_once_with(
        debug=debug,
        host="127.0.0.1",
        port=port,
        use_reloader=False,
        ssl_context=context,
    )
    mock_context.return_value.__exit__.assert_called_once()


def test_wsgi_sim_tls_is_memory_backed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Expose only a live public certificate and leave no PEM files behind."""
    module = _load_wsgi_sim_module()
    monkeypatch.chdir(tmp_path)
    caplog.set_level("INFO")
    with module._ssl_context() as context:
        assert isinstance(context, ssl.SSLContext)
        cert_path = Path(caplog.records[-1].getMessage().split("public certificate: ", 1)[1])
        assert cert_path.readlink().as_posix().startswith("/memfd:solcast-simulator-cert")
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        names = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        assert "localhost" in names.get_values_for_type(x509.DNSName)
        ssl.create_default_context(cafile=str(cert_path))
        assert list(tmp_path.iterdir()) == []
    assert not cert_path.exists()


def test_wsgi_sim_import_does_not_generate_certificate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Importing the simulator must not create persistent certificates."""
    monkeypatch.chdir(tmp_path)
    with patch("subprocess.check_call") as mock_subprocess:
        _load_wsgi_sim_module()
    mock_subprocess.assert_not_called()
    assert list(tmp_path.iterdir()) == []
