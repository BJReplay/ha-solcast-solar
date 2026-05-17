"""Tests for the Solcast WSGI simulator CLI."""


import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import patch
from zoneinfo import ZoneInfo

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
        ):
            spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _test_client(module: ModuleType):
    """Return a Flask test client with 418 responses disabled."""
    setattr(module, "BOMB_418", False)
    module.app.config["TESTING"] = True  # type: ignore[attr-defined]
    return module.app.test_client()  # type: ignore[attr-defined]


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
