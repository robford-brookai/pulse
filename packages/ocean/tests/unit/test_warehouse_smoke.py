"""Verify warehouse_smoke.py --dry-run exits cleanly."""

from __future__ import annotations

import subprocess


def test_warehouse_smoke_dry_run():
    result = subprocess.run(
        ["uv", "run", "python", "scripts/warehouse_smoke.py", "--dry-run"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "DRY RUN" in result.stdout
