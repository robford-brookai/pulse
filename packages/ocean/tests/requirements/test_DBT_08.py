"""DBT-08: Incremental models use 4-hour lookback window for late-arriving events."""
from __future__ import annotations

from pathlib import Path

CORE_DIR = Path(__file__).resolve().parents[2] / ".repos" / "streamline" / "dbt_project" / "models" / "ocean" / "core"


def test_core_models_have_incremental_lookback():
    """Every core model SQL file must contain the 4-hour lookback pattern."""
    core_files = list(CORE_DIR.glob("core_ocean_*.sql"))
    assert len(core_files) >= 4, f"Expected at least 4 core models, found {len(core_files)}"
    for f in core_files:
        content = f.read_text()
        assert "is_incremental()" in content, f"{f.name} missing is_incremental() block"
        assert "DATEADD(hour, -4," in content or "dateadd(hour, -4," in content.lower(), \
            f"{f.name} missing 4-hour lookback window"
