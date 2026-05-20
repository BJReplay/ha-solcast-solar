"""Tests for the Solcast Sim custom component."""

from pathlib import Path
import sys

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
if str(_CONFIG_DIR) not in sys.path:
    sys.path.insert(0, str(_CONFIG_DIR))
