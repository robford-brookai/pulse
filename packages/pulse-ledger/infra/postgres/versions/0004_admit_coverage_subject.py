"""Widen the three subject-type checks to admit `coverage`.

Catalog release 1.1.0 added the `coverage` subject (patient x payer grain, `ownership: ledger`);
this migration widens the record in the same change, per the billing-state spec: a catalog-legal
coverage transition must never validate against the generated adjacency and then be refused by
the store. Three constraints, one vocabulary — `events`, `current_state`, and `review_queue` all
widen together, because a table left behind would re-open that gap for whichever write path
touches it.

`communication_consent` (catalog-present, `ownership: recorded`) stays outside the record —
`test_communication_consent_validates_but_cannot_yet_be_committed` still pins that mismatch.

Postgres has no ALTER for a check constraint, so each is dropped and recreated under its
existing name. The downgrade restores the six-grain vocabulary of 0001 and fails, correctly,
if coverage rows exist — rows outside the narrowed constraint must be dealt with, not silently
stranded.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-19
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

# The six subject grains of object model v0.7 (migration 0001) ...
V0_7_SUBJECT_TYPES = ("referral", "consent", "enrollment", "billing_episode", "device", "contract")
# ... plus the coverage subject of catalog 1.1.0.
SUBJECT_TYPES = (*V0_7_SUBJECT_TYPES, "coverage")

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
    _set_subject_types(V0_7_SUBJECT_TYPES)
