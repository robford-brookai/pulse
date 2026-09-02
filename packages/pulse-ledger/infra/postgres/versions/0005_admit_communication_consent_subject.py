"""Widen the three subject-type checks to admit `communication_consent`.

Catalog release 1.1.0 seeds `communication_consent` — a `RECORDED_SUBJECT_TYPES` grain distinct
from the older `consent` (see `pulse_core.generated`), and `record_communication_consent` is the
command consent-ingress and the consent sweep both declare against it. 2.1's live run hit the gap
this closes: `record_communication_consent` fails on `ck_events_subject_type` against a real
migrated Postgres, before catalog validation ever runs (`handoffs/pulse-demo-closeout/task-004.md`).

Three constraints, one vocabulary, same posture as `0004_admit_coverage_subject.py` — `events`,
`current_state`, and `review_queue` widen together, because a table left behind would re-open the
validates-but-cannot-commit gap for whichever write path touches it.

Postgres has no ALTER for a check constraint, so each is dropped and recreated under its
existing name. The downgrade restores 0004's vocabulary and fails, correctly, if
`communication_consent` rows exist — rows outside the narrowed constraint must be dealt with, not
silently stranded.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-02
"""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# The six subject grains of object model v0.7 (migration 0001) plus the coverage subject of
# catalog 1.1.0 (migration 0004) ...
V0004_SUBJECT_TYPES = ("referral", "consent", "enrollment", "billing_episode", "device", "contract", "coverage")
# ... plus the communication_consent subject of the same catalog release.
SUBJECT_TYPES = (*V0004_SUBJECT_TYPES, "communication_consent")

CONSTRAINTS = (
    ("events", "ck_events_subject_type"),
    ("current_state", "ck_current_state_subject_type"),
    ("review_queue", "ck_review_queue_subject_type"),
)


def _one_of(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


def _set_subject_types(values: tuple[str, ...]) -> None:
    for table, name in CONSTRAINTS:
        op.drop_constraint(name, table, schema="ledger", type_="check")
        op.create_check_constraint(name, table, _one_of("subject_type", values), schema="ledger")


def upgrade() -> None:
    _set_subject_types(SUBJECT_TYPES)


def downgrade() -> None:
    _set_subject_types(V0004_SUBJECT_TYPES)
