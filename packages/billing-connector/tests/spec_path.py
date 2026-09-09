"""Where the billing-connector spec lives, wherever the change lifecycle has put it.

While the change is in flight the delta spec lives under `openspec/changes/`; once archived
(2026-09-08) the requirements live in the baseline under `openspec/specs/`, with the delta copy
under the dated archive directory as a last resort. Resolving at import time keeps the spec-driven
gates green across the archive instead of turning main red the moment the change directory moves.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def spec_path() -> Path:
    candidates = [
        REPO_ROOT / "openspec" / "changes" / "billing-connector" / "specs" / "billing-connector" / "spec.md",
        REPO_ROOT / "openspec" / "specs" / "billing-connector" / "spec.md",
        *sorted(
            (REPO_ROOT / "openspec" / "changes" / "archive").glob("*-billing-connector/specs/billing-connector/spec.md")
        ),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    msg = "billing-connector spec not found in the change, the baseline, or the archive"
    raise FileNotFoundError(msg)
