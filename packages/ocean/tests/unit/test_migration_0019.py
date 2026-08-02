"""Tests for migration 0019 (event-time columns for the wave-2a sequence guards).

Two things are checked here. The first is that 0019 says what the wave-2a guards
need it to say: one nullable, defaultless TIMESTAMPTZ column named last_event_at
on each of the four guarded tables, reversed by the downgrade.

The second is the whole revision chain. Tasks 3.1-3.5 each add a guard from a
worktree branched off main, and every one of them needs this column. Had they
each written their own migration they would have written four files numbered
0019, all with down_revision 0018, and the merge would have produced four
alembic heads. test_exactly_one_head is the standing check against that, for
0019 and for every migration after it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS = REPO_ROOT / "infra" / "postgres" / "versions"
SOURCE = VERSIONS / "0019_event_time_guard_columns.py"

# The tables a wave-2a guard protects. `outcomes` is deliberately absent: it is
# append-only (ON CONFLICT (outcome_id) DO NOTHING) and needs no guard column.
GUARDED_TABLES = ("interactions", "device_associations", "signals", "slack_messages")

COLUMN = "last_event_at"


def _source() -> str:
    return SOURCE.read_text()


def _module_constants(source: str) -> dict[str, object]:
    """Module-level literal assignments, read without importing (alembic is not installed)."""
    constants: dict[str, object] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                try:
                    constants[target.id] = ast.literal_eval(node.value)
                except ValueError:
                    continue
    return constants


def _revisions() -> dict[str, str | None]:
    """Map revision -> down_revision for every migration in the chain."""
    chain: dict[str, str | None] = {}
    for path in sorted(VERSIONS.glob("[0-9]*.py")):
        constants = _module_constants(path.read_text())
        revision = constants.get("revision")
        assert isinstance(revision, str), f"{path.name} declares no revision"
        assert revision not in chain, f"{path.name} reuses revision {revision!r} — duplicate migration number"
        down = constants.get("down_revision")
        chain[revision] = down if isinstance(down, str) else None
    return chain


# --- The migration itself ---------------------------------------------------


def test_source_file_exists():
    assert SOURCE.exists(), f"Expected migration file at {SOURCE}"


def test_revision_identifiers():
    src = _source()
    assert 'revision = "0019"' in src
    assert 'down_revision = "0018"' in src, "0019 must chain onto 0018, the head before it"


@pytest.mark.parametrize("table", GUARDED_TABLES)
def test_adds_column_to_each_guarded_table(table: str):
    src = _source()
    assert table in src, f"Migration 0019 must add {COLUMN} to {table} — a wave-2a guard reads it there"


def test_column_is_named_last_event_at():
    assert f'"{COLUMN}"' in _source(), f"Guards 3.1-3.5 are written against the name {COLUMN}"


def test_column_is_timestamptz():
    assert "sa.DateTime(timezone=True)" in _source(), "Event time is stored with its timezone"


def test_column_is_nullable():
    assert "nullable=True" in _source(), (
        "Pre-migration rows have no known event time; a NULL must read as always-overwritable"
    )


def test_no_processing_time_default():
    src = _source()
    upgrade = src.split("def upgrade(")[1].split("def downgrade(")[0]
    assert "server_default" not in upgrade, (
        "A now() default records processing time, which is the defect wave 2a removes"
    )
    assert "now()" not in upgrade


def test_touches_exactly_the_guarded_tables():
    """outcomes is append-only (ON CONFLICT DO NOTHING); fulfillments and returns are unscoped."""
    declared = _module_constants(_source()).get("GUARDED_TABLES")
    assert isinstance(declared, tuple)
    assert set(declared) == set(GUARDED_TABLES)


def test_downgrade_drops_every_column_the_upgrade_added():
    src = _source()
    downgrade = src.split("def downgrade(")[1]
    assert "drop_column" in downgrade
    assert COLUMN in downgrade


def test_has_upgrade_and_downgrade():
    src = _source()
    assert "def upgrade(" in src
    assert "def downgrade(" in src


# --- The chain --------------------------------------------------------------


def test_exactly_one_head():
    """No migration may be a head other than the newest one.

    A head is a revision nothing else points back to. Two heads mean two
    migrations claimed the same predecessor, which is what happens when
    parallel worktrees each write their own next migration.
    """
    chain = _revisions()
    pointed_to = {down for down in chain.values() if down is not None}
    heads = sorted(set(chain) - pointed_to)
    assert heads == ["0019"], f"Expected exactly one head (0019), found: {heads}"


def test_chain_is_connected():
    """Every down_revision names a migration that exists, and only 0001 has none."""
    chain = _revisions()
    roots = [rev for rev, down in chain.items() if down is None]
    assert roots == ["0001"], f"Expected 0001 to be the only root, found: {roots}"
    for revision, down in chain.items():
        if down is not None:
            assert down in chain, f"{revision} chains onto {down!r}, which does not exist"
