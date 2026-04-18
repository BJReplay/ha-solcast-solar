"""Tests for the Solcast WSGI simulator CLI."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import patch


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
        with patch("pathlib.Path.exists", return_value=True), patch("subprocess.check_call"):
            spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def test_wsgi_sim_parser_accepts_port() -> None:
    """The simulator parser accepts an explicit TCP port."""

    module = _load_wsgi_sim_module()

    args = module.build_parser().parse_args(["--port", "8443", "--no429"])

    assert args.port == 8443
    assert args.no429 is True


def test_wsgi_sim_main_uses_configured_port() -> None:
    """The simulator starts Flask on the configured TCP port."""

    module = _load_wsgi_sim_module()

    with (
        patch.object(module, "get_time_zone"),
        patch.object(module.random, "seed"),
        patch.object(module.app, "run") as mock_run,
    ):
        module.main(["--port", "8443", "--no429"])

    mock_run.assert_called_once_with(
        debug=False,
        host="127.0.0.1",
        port=8443,
        ssl_context=("cert.pem", "key.pem"),
    )
