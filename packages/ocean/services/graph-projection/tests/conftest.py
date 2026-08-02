"""Put the service root on `sys.path` so `from src...` resolves.

These tests import the service as `src.handlers.…`, which only resolves when
`services/graph-projection` is importable. Collecting the whole directory happens to arrange
that; running one module by path does not. Stating it here makes either invocation work.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = str(Path(__file__).parents[1])
if _SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _SERVICE_ROOT)
