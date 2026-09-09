"""Tests for migration 0021 (patients.ledger_seq, the patient-state projection's citation).

`enrollment_status` loses its `server_default` — the projection always supplies a value,
so a default is a trap for the next writer that forgets to. `ledger_seq BIGINT NULL` is
the citation column: set by every projection write, null on a legacy row (design.md
decisions 3, 5). `patient_graph_summary` is a materialized view and cannot be altered in
place, so the migration drops and recreates it with `ledger_seq` in the select and
group-by, and its unique index recreated identically (design.md decision 7).
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS = REPO_ROOT / "infra" / "postgres" / "versions"
SOURCE = VERSIONS / "0021_patients_ledger_seq.py"


def _source() -> str:
    return SOURCE.read_text()


def _upgrade(src: str) -> str:
    return src.split("def upgrade(")[1].split("def downgrade(")[0]


def _downgrade(src: str) -> str:
    return src.split("def downgrade(")[1]


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
    assert 'revision = "0021"' in src
    assert 'down_revision = "0020"' in src, "0021 must chain onto 0020, the head before it"


def test_has_upgrade_and_downgrade():
    src = _source()
    assert "def upgrade(" in src
    assert "def downgrade(" in src


def test_drops_enrollment_status_default():
    upgrade = _upgrade(_source())
    assert '"enrollment_status"' in upgrade
    assert "server_default=None" in upgrade, "The projection always supplies a value; a default is a trap"


def test_enrollment_status_alter_touches_only_the_default():
    """Only the default goes; every projected write and every legacy row already has a value."""
    upgrade = _upgrade(_source())
    alter_call = upgrade.split('alter_column("patients", "enrollment_status"')[1].split(")")[0]
    assert "nullable" not in alter_call, "enrollment_status must stay NOT NULL — only the default is dropped"


def test_adds_ledger_seq_column():
    upgrade = _upgrade(_source())
    assert '"ledger_seq"' in upgrade
    assert "sa.BigInteger()" in upgrade
    assert "nullable=True" in upgrade, "A legacy row carries no citation — null must be allowed"


def test_recreates_materialized_view():
    src = _source()
    assert src.count("DROP MATERIALIZED VIEW IF EXISTS patient_graph_summary") >= 1
    assert src.count("CREATE MATERIALIZED VIEW patient_graph_summary") == 2, (
        "Recreated once in upgrade, once in downgrade — a materialized view cannot be altered in place"
    )


def test_view_select_and_group_by_include_ledger_seq():
    upgrade = _upgrade(_source())
    view_sql = upgrade.split("CREATE MATERIALIZED VIEW patient_graph_summary AS")[1]
    assert "p.ledger_seq" in view_sql.split("FROM patients")[0], "ledger_seq must be in the select list"
    group_by = view_sql.split("GROUP BY")[1].split("\n")[0]
    assert "p.ledger_seq" in group_by, "Every selected non-aggregate column must be in the group-by"


def test_view_unique_index_recreated():
    upgrade = _upgrade(_source())
    assert "CREATE UNIQUE INDEX idx_patient_graph_summary_pk ON patient_graph_summary (patient_id)" in upgrade


def test_downgrade_restores_default_and_drops_column():
    downgrade = _downgrade(_source())
    assert 'drop_column("patients", "ledger_seq")' in downgrade
    assert 'server_default="pending"' in downgrade, "Downgrade restores the original default"


def test_downgrade_view_has_no_ledger_seq():
    downgrade = _downgrade(_source())
    view_sql = downgrade.split("CREATE MATERIALIZED VIEW patient_graph_summary AS")[1]
    select_list = view_sql.split("FROM patients")[0]
    assert "ledger_seq" not in select_list, "Downgrade's recreated view matches the pre-0021 shape"


# --- The chain ----------------------------------------------------------------


def test_exactly_one_head():
    chain = _revisions()
    pointed_to = {down for down in chain.values() if down is not None}
    heads = sorted(set(chain) - pointed_to)
    assert heads == ["0021"], f"Expected exactly one head (0021), found: {heads}"


def test_chain_is_connected():
    chain = _revisions()
    roots = [rev for rev, down in chain.items() if down is None]
    assert roots == ["0001"], f"Expected 0001 to be the only root, found: {roots}"
    for revision, down in chain.items():
        if down is not None:
            assert down in chain, f"{revision} chains onto {down!r}, which does not exist"
