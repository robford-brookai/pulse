"""Gate: `patients` is written only by the ledger projection handler.

Spec (patient-state-projection, "Only the ledger projection mints or updates a patient row"):
no handler, service, migration data step, or operator path outside
`handlers/patient_state.py` may INSERT into or UPDATE `patients`. This scans every `.py` file
under packages/ocean — excluding tests, which legitimately seed fixture rows — and fails naming
the offending file(s), exactly as the spec's "stray writer is refused" scenario requires.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]  # packages/ocean
ALLOWED_WRITER = Path("services/graph-projection/src/handlers/patient_state.py")

# Word-bounded so "patients_archive" or "patients2" don't false-positive.
_WRITE_PATTERN = re.compile(r"\b(insert\s+into|update)\s+patients\b", re.IGNORECASE)

# Fixture setup in tests legitimately seeds rows directly; docs/tooling noise is irrelevant to a
# source scan. Everything else under packages/ocean is in scope, including scripts/ and infra/.
_EXCLUDED_DIRS = {"tests", "docs", ".git", "__pycache__", ".venv", "node_modules"}


def find_stray_patients_writes(source_root: Path) -> list[Path]:
    """Every `.py` file under `source_root` — excluding tests/docs and the allowed writer — that
    contains an `INSERT INTO patients` or `UPDATE patients` statement. Paths are relative to
    `source_root`, sorted for stable failure messages.
    """
    offenders: list[Path] = []
    for path in sorted(source_root.rglob("*.py")):
        rel = path.relative_to(source_root)
        if any(part in _EXCLUDED_DIRS for part in rel.parts):
            continue
        if rel == ALLOWED_WRITER:
            continue
        if _WRITE_PATTERN.search(path.read_text()):
            offenders.append(rel)
    return offenders


def test_gate_passes_on_the_tree():
    offenders = find_stray_patients_writes(REPO_ROOT)
    assert offenders == [], f"stray patients write(s) outside {ALLOWED_WRITER}: {offenders}"


def test_gate_fails_on_a_planted_stray_insert(tmp_path):
    # Runs on a temp copy — the gate must never mutate or depend on the live tree's state.
    copy_root = tmp_path / "ocean"
    shutil.copytree(
        REPO_ROOT,
        copy_root,
        ignore=shutil.ignore_patterns("tests", "docs", ".venv", "__pycache__", "*.pyc", ".git"),
    )
    stray = copy_root / "services" / "graph-projection" / "src" / "handlers" / "alerts.py"
    stray.write_text(stray.read_text() + '\n\n_STRAY_SQL = "INSERT INTO patients (patient_id) VALUES (:id)"\n')

    offenders = find_stray_patients_writes(copy_root)

    assert offenders == [Path("services/graph-projection/src/handlers/alerts.py")]


def test_the_allowed_writer_itself_is_exempt():
    # patient_state.py's own INSERT is the point of the handler, not a violation.
    writer = REPO_ROOT / ALLOWED_WRITER
    assert writer.exists()
    assert _WRITE_PATTERN.search(writer.read_text())
    assert find_stray_patients_writes(REPO_ROOT) == []
