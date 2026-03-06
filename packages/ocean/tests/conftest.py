"""Root test conftest — sys.path setup and shared markers.

Adds the tests/ directory itself to sys.path so that tests/utils.py is
importable as `utils` from any test file under tests/.
"""
from __future__ import annotations

import pathlib
import sys

# Make tests/ itself importable so test files can do `from utils import setup_service`
_TESTS_DIR = pathlib.Path(__file__).parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
