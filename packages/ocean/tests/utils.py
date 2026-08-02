"""Shared test utilities for root-level tests.

The primary concern is that multiple services all expose a `src` package.
setup_service() ensures the correct service directory is at the front of
sys.path and that any stale `src.*` cache from a previous service is cleared,
so imports like `from src.X import Y` resolve to the right service.
"""
from __future__ import annotations

import pathlib
import sys

_ROOT = pathlib.Path(__file__).parents[1]  # ocean/


def setup_service(name: str) -> None:
    """Configure sys.path so that `from src.X import Y` resolves to `services/<name>/src/X.py`.

    Clears any cached `src` or `src.*` modules first to avoid stale imports
    from a different service that was set up earlier in the same pytest session.
    """
    svc_path = str(_ROOT / "services" / name)

    # Evict stale src cache — must happen before path manipulation
    for key in list(sys.modules.keys()):
        if key == "src" or key.startswith("src."):
            del sys.modules[key]

    # Remove any other service directories that were previously at the front
    sys.path = [p for p in sys.path if not (
        p.startswith(str(_ROOT / "services")) and p != svc_path
    )]

    # Insert this service at position 0 so it wins any `src` import
    if svc_path in sys.path:
        sys.path.remove(svc_path)
    sys.path.insert(0, svc_path)
