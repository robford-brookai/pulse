"""The STG_EVENTS.EVENTS contract-row test (snowflake-projection task 1.3).

Pins the published `docs/contracts/publishes.md` row for `STREAMLINE.STG_EVENTS.EVENTS`: the
row exists, carries the verbatim freshness query, the `min_complete_from` placeholder, and the
`projection-rebuild-drill` sentence, and every column the committed view actually outputs
(parsed straight from `stg_events_events.sql`, not retyped here) appears in the row.

Delta scenario covered: snowflake-stg-events / "The published row bounds completeness".

Offline, no network, no credentials — reads only the committed docs and SQL.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLISHES_PATH = REPO_ROOT / "docs" / "contracts" / "publishes.md"
SQL_PATH = REPO_ROOT / "packages" / "ocean" / "infra" / "snowflake" / "stg_events_events.sql"

#: The verbatim freshness query the work order pins — copied character-for-character.
_FRESHNESS_QUERY = (
    "SELECT TIMESTAMPDIFF('minute', MAX(_loaded_at), CURRENT_TIMESTAMP()) FROM STREAMLINE.OCEAN_RAW.EVENTS"
)


def _publishes_text() -> str:
    return PUBLISHES_PATH.read_text(encoding="utf-8")


def _sql_text() -> str:
    return SQL_PATH.read_text(encoding="utf-8")


def _select_columns(sql: str) -> list[str]:
    """Output column names, in order, parsed from the `SELECT ... FROM` list.

    Mirrors `packages/ocean/tests/unit/test_stg_events_sql.py`'s parser: each line is either
    `<expr> AS <name>` or a bare passthrough column (`_topic`, `_loaded_at`).
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


def _stg_events_row_block(text: str) -> str:
    """The table row for `STREAMLINE.STG_EVENTS.EVENTS` plus its immediately adjacent prose.

    Grabs from the row's own line through the next 15 lines, so prose directly under the row
    (e.g. a sentence naming `projection-rebuild-drill`) counts as "adjacent" per the task.
    """
    marker = "STREAMLINE.STG_EVENTS.EVENTS"
    idx = text.index(marker)
    tail = text[idx:]
    lines = tail.splitlines()
    return "\n".join(lines[:16])


def test_publishes_contains_stg_events_row() -> None:
    assert "STREAMLINE.STG_EVENTS.EVENTS" in _publishes_text(), (
        "docs/contracts/publishes.md is missing the STREAMLINE.STG_EVENTS.EVENTS row"
    )


def test_stg_events_row_carries_the_pinned_facts() -> None:
    block = _stg_events_row_block(_publishes_text())
    for needle in (_FRESHNESS_QUERY, "min_complete_from", "projection-rebuild-drill"):
        assert needle in block, f"STG_EVENTS.EVENTS row (or its adjacent prose) is missing {needle!r}"


def test_min_complete_from_uses_the_stamped_at_revival_placeholder() -> None:
    block = _stg_events_row_block(_publishes_text())
    assert "`stamped-at-revival`" in block, (
        "min_complete_from must carry the literal inline-code placeholder `stamped-at-revival`, "
        "never a link (mkdocs build -s treats a broken link as an error)"
    )


def test_every_view_column_appears_in_the_contract_row() -> None:
    columns = _select_columns(_sql_text())
    block = _stg_events_row_block(_publishes_text())
    missing = [column for column in columns if column not in block]
    assert not missing, (
        f"STG_EVENTS.EVENTS contract row is missing column(s) present in stg_events_events.sql: {missing}"
    )


def test_ocean_raw_events_row_states_freshness_expectation() -> None:
    text = _publishes_text()
    idx = text.index("STREAMLINE.OCEAN_RAW.EVENTS")
    row_line = text[idx : text.index("\n", idx)]
    assert "warehouse-sync consumer" in row_line, (
        "OCEAN_RAW.EVENTS row must append the freshness expectation naming the provisioned warehouse-sync consumer"
    )
