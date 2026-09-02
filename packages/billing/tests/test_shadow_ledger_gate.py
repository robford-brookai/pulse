"""Shadow-ledger gate (task 3.1) — pins that no state-of-record read ever targets the
`billing_engine` schema (design.md decision 5, risk "Engine state store becomes a shadow
ledger": "the schema holds fact snapshots and evaluation receipts only, rebuildable from the
bus; a scaffold-style test pins that no state-of-record read ever targets it").

`pulse_ledger.reads.state_of_record` is the ledger's one canonical "state of record" reader —
the function every legitimate consumer of ledger state calls instead of querying
`ledger.current_state` directly. A module that both reaches for that function *and* mentions
the `billing_engine` schema is doing one of two things, and both are the violation this schema
must never allow: treating `billing_engine`'s fact/evaluation store as if it answers
`state_of_record` (a second, shadow state of record), or feeding a billing-engine subject
through the ledger's canonical reader as though the engine's own store were the ledger.

Either half alone is fine and expected: `pulse_ledger.reads` is used all over the ledger and
API layers with no idea `billing_engine` exists; the wave-3 reconciliation sweep reads
`billing_engine.evaluations` directly by SQL, never through `state_of_record`. Only the
co-occurrence in one module is the shadow-ledger shape.

Same posture as `pulse_core`'s connector credential gate
(`test_connector_credential_gate.py`): a pure scanning function on file text, red against a
planted violation, green on the real tree.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]

_STATE_OF_RECORD_CALL = re.compile(r"\bstate_of_record\s*\(")
_ENGINE_SCHEMA_MENTION = re.compile(r"\bbilling_engine\b")

#: Every source tree a shadow-ledger read could live in: the workspace packages plus the
#: root package. `packages/billing` itself is excluded — the engine's own migrations and
#: (later) its fact-fold/evaluation code legitimately name the schema they own.
_SCAN_ROOTS = [
    p / "src" for p in sorted((_REPO_ROOT / "packages").iterdir()) if p.name != "billing" and (p / "src").is_dir()
] + [_REPO_ROOT / "src"]


def shadow_ledger_violation(source: str) -> bool:
    """True if `source` calls the ledger's `state_of_record` reader in a module that also
    references the `billing_engine` schema — the shape a shadow-ledger read takes."""
    return bool(_STATE_OF_RECORD_CALL.search(source) and _ENGINE_SCHEMA_MENTION.search(source))


def _scan(root: Path) -> list[str]:
    return [
        str(py_file.relative_to(_REPO_ROOT))
        for py_file in sorted(root.rglob("*.py"))
        if shadow_ledger_violation(py_file.read_text())
    ]


def test_no_state_of_record_read_targets_the_billing_engine_schema() -> None:
    offenders = [finding for root in _SCAN_ROOTS for finding in _scan(root)]
    assert offenders == [], f"state_of_record called alongside billing_engine in: {offenders}"


# --- The gate is live: red against a planted violation, green on either half alone -------------


def test_the_gate_catches_a_planted_shadow_read() -> None:
    fixture = (
        "from pulse_ledger.reads import state_of_record\n\n"
        "def read_engine_state(conn, subject_key):\n"
        "    # WRONG: billing_engine is not the ledger's state of record\n"
        '    return state_of_record(conn, "billing_engine", subject_key)\n'
    )
    assert shadow_ledger_violation(fixture) is True


def test_the_gate_does_not_flag_an_ordinary_ledger_read() -> None:
    fixture = (
        "from pulse_ledger.reads import state_of_record\n\n"
        "def read(conn, subject_type, subject_key):\n"
        "    return state_of_record(conn, subject_type, subject_key)\n"
    )
    assert shadow_ledger_violation(fixture) is False


def test_the_gate_does_not_flag_a_billing_engine_reference_with_no_state_of_record_call() -> None:
    fixture = (
        'def diff_report(conn):\n    return conn.execute("SELECT outcome FROM billing_engine.evaluations").fetchall()\n'
    )
    assert shadow_ledger_violation(fixture) is False
