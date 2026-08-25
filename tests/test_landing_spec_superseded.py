"""The events-leg supersession note (snowflake-projection 1.2).

Pins the note added to `design/platform/snowflake-landing-spec.md`, directly under the
`## Pipeline` heading: the CDC events leg (Twenty-Postgres CDC -> `RAW_TWENTY.DOMAIN_EVENT` ->
STG_EVENTS) it introduces is superseded — the ledger is the record, envelopes land via
`warehouse-event-sync` in `STREAMLINE.OCEAN_RAW.EVENTS`, and STG_EVENTS is now defined by the
`snowflake-stg-events` capability (design.md decision 1). The note must land within 40 lines of
the heading, and it must not delete or rewrite the leg's existing text — the CDC leg description,
the entity-CDC dimension views, and MART_STATE stay as-is.

Delta scenario covered: snowflake-projection design.md decision 1, task 1.2.

Offline, no network, no credentials — reads only the committed doc.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = REPO_ROOT / "design" / "platform" / "snowflake-landing-spec.md"

#: The three strings the supersession note must carry, within 40 lines of `## Pipeline`.
#: "superseded" is matched case-insensitively; the other two are exact identifiers.
REQUIRED_STRINGS = ("OCEAN_RAW.EVENTS", "snowflake-stg-events")

#: Text that must survive untouched — the leg this change supersedes, and the sections the
#: task says remain as-is.
PRESERVED_STRINGS = (
    "Twenty Postgres (workspace schema: `domainEvent`",
    "CREATE OR REPLACE VIEW STG_EVENTS.EVENTS AS",
    "MART_STATE",
)

PIPELINE_HEADING = re.compile(r"^## Pipeline\s*$", re.MULTILINE)


def _doc_text() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def _pipeline_window(text: str, *, lines: int = 40) -> str:
    match = PIPELINE_HEADING.search(text)
    assert match, "design/platform/snowflake-landing-spec.md has no `## Pipeline` heading"
    start = match.end()
    window_lines = text[start:].splitlines()[:lines]
    return "\n".join(window_lines)


def test_pipeline_heading_exists() -> None:
    """The note's anchor point is present."""
    assert DOC_PATH.exists(), f"{DOC_PATH.relative_to(REPO_ROOT)} is missing"
    assert PIPELINE_HEADING.search(_doc_text())


def test_supersession_note_present_within_40_lines_of_pipeline_heading() -> None:
    """The note states the events leg is superseded, and points at its replacement."""
    window = _pipeline_window(_doc_text())
    assert re.search(r"superseded", window, re.IGNORECASE), (
        "no case-insensitive 'superseded' within 40 lines of `## Pipeline` in design/platform/snowflake-landing-spec.md"
    )
    missing = [needle for needle in REQUIRED_STRINGS if needle not in window]
    assert not missing, (
        f"the supersession note is missing {missing} within 40 lines of `## Pipeline` — "
        "it must name the real landing (`OCEAN_RAW.EVENTS`) and the capability that now "
        "defines STG_EVENTS (`snowflake-stg-events`)"
    )


def test_events_leg_text_is_preserved() -> None:
    """The note is additive: the superseded leg's own text, and the untouched sections,
    are not deleted or rewritten."""
    text = _doc_text()
    missing = [needle for needle in PRESERVED_STRINGS if needle not in text]
    assert not missing, (
        f"design/platform/snowflake-landing-spec.md is missing {missing} — "
        "the task requires a note, not a rewrite of the CDC leg, STG_EVENTS SQL, or MART_STATE"
    )
