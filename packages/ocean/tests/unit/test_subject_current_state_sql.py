"""STG_EVENTS.SUBJECT_CURRENT_STATE view (reconciliation-sweeps task 1.2) — offline, no live
Snowflake.

Parses the committed `subject_current_state.sql` and asserts its shape: the fold window (latest
landed event per subject by `seq`), the floor predicate bounding it below by the pinned
`min_complete_from` watermark, and the work order's column set.
"""

from __future__ import annotations

import re
from pathlib import Path

_SQL_PATH = Path(__file__).resolve().parents[2] / "infra" / "snowflake" / "subject_current_state.sql"

#: The work order's pinned floor — every one of these must appear as an output column.
_MINIMUM_COLUMNS = frozenset({
    "subject_type",
    "subject_key",
    "seq",
    "state",
    "_loaded_at",
})

#: The `min_complete_from` watermark pinned in docs/contracts/publishes.md at feed revival
#: (design.md decision 5) — this view's floor must match it exactly, not restate it drifted.
_MIN_COMPLETE_FROM = "2026-08-26"


def _sql_text() -> str:
    return _SQL_PATH.read_text()


def _select_columns(sql: str) -> list[str]:
    """Output column names, in order, parsed from the `SELECT ... FROM` list.

    Mirrors `test_stg_events_sql.py`'s parser: each line is either `<expr> AS <name>` or a bare
    passthrough column.
    """
    select_block = sql.split("SELECT", 1)[1].split("\nFROM ", 1)[0]
    columns = []
    for raw_line in select_block.splitlines():
        line = raw_line.strip().rstrip(",")
        if not line:
            continue
        match = re.search(r'\bAS\s+"?([A-Za-z_][A-Za-z0-9_]*)"?\s*$', line, re.IGNORECASE)
        columns.append(match.group(1) if match else line.strip('"'))
    return columns


def test_folds_latest_by_seq_per_subject() -> None:
    sql = _sql_text()
    assert "PARTITION BY subject_type, subject_key ORDER BY seq DESC" in sql
    assert "QUALIFY ROW_NUMBER() OVER (PARTITION BY subject_type, subject_key ORDER BY seq DESC) = 1" in sql


def test_floor_predicate_bounds_loaded_at_by_min_complete_from() -> None:
    sql = _sql_text()
    assert f"_loaded_at >= '{_MIN_COMPLETE_FROM}'" in sql, (
        "floor predicate must bound _loaded_at by the pinned min_complete_from watermark"
    )


def test_minimum_columns_are_present() -> None:
    columns = set(_select_columns(_sql_text()))
    missing = _MINIMUM_COLUMNS - columns
    assert not missing, f"missing pinned minimum column(s): {sorted(missing)}"


def test_state_is_extracted_from_payload_to_state() -> None:
    sql = _sql_text()
    assert "payload:to_state::VARCHAR" in sql, (
        "state must come from the same payload.to_state key pulse_ledger.fold uses"
    )


def test_reads_from_the_deduplicated_events_view_not_the_raw_landing() -> None:
    sql = _sql_text()
    assert "FROM STREAMLINE.STG_EVENTS.EVENTS" in sql, (
        "must fold over the already-deduplicated STG_EVENTS.EVENTS view, never OCEAN_RAW.EVENTS directly"
    )
