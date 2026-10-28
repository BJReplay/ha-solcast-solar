"""Tests for the Solcast Sim custom component."""

from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
import sys

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
if str(_CONFIG_DIR) not in sys.path:
    sys.path.insert(0, str(_CONFIG_DIR))

# Core 2026.11 moved these test helpers into the package pytest_homeassistant, so keep their old names working.
if find_spec("tests.common") is None:
    for _name in ("common", "typing", "ignore_uncaught_exceptions", "components.diagnostics", "components.recorder.common"):
        sys.modules[f"tests.{_name}"] = import_module(f"pytest_homeassistant.{_name}")
