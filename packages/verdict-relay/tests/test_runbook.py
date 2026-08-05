"""Docs-consistency gate for the relay runbook (task 5.1, spec verdict-relay-run).

Spec scenario "The runbook covers both monitored failure modes": the published runbook exists,
names both §1.5 monitored failure modes (verdict staleness > 26 h, run failure), the diagnostic
reads (the five receipt counts and the summary line), the rejected-vs-failed distinction, the
recovery-overlap replay semantics (design risk 4), and safe re-run against the persisted cursor.

The runbook lives under `docs/`, so `task check`'s docs step (`mkdocs build -s`) already builds it
strict — a broken link or malformed page fails CI there; this file checks the operator content.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNBOOK_PATH = REPO_ROOT / "docs" / "runbooks" / "verdict-relay.md"


def _runbook() -> str:
    assert RUNBOOK_PATH.is_file(), f"runbook missing at {RUNBOOK_PATH}"
    return RUNBOOK_PATH.read_text().lower()


def test_runbook_exists() -> None:
    assert RUNBOOK_PATH.is_file()


def test_names_both_monitored_failure_modes() -> None:
    text = _runbook()
    assert "staleness" in text and "26" in text, "staleness > 26 h monitor not named"
    assert "run failure" in text, "run-failure monitor not named"


def test_documents_the_receipt_reads() -> None:
    text = _runbook()
    for count in ("declared", "replayed", "skipped_stale", "rejected", "failed"):
        assert count in text, f"receipt count {count!r} not documented"
    assert "summary line" in text


def test_distinguishes_rejected_from_failed() -> None:
    text = _runbook()
    assert "rejected" in text and "failed" in text
    assert "never retried" in text or "not retried" in text


def test_documents_recovery_overlap_and_safe_rerun() -> None:
    text = _runbook()
    assert "persisted cursor" in text
    assert "recovery overlap" in text or "recovery-overlap" in text
    assert "replay" in text
    assert "re-run" in text or "rerun" in text or "resumed run" in text
