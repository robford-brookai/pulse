"""The companion binding table — an idempotency key's authenticated claim (ADR-0007, amends D16).

`idempotency_keys` maps key → event and is kept forever, but nothing there records *who* claimed
the key or *what* they sent: the text before the colon is client-supplied and the digest after it
is the SDK's, over a client-only `logical_time` the server never receives. Any authenticated writer
presenting another's key text is therefore answered with that writer's event, and a colliding key
is absorbed rather than refused. Task 1.1 defined both missing halves as values
(`pulse_ledger.request_fingerprint`); this migration gives them a place to live so the commit path
(task 2.1) can require them to match before it replays anything.

**Additive, not a rewrite.** `idempotency_keys` is untouched: its primary key keeps the lifetime
global reservation, so no historical key is released into a new namespace, and no legacy row is
migrated here. Deriving a binding for a legacy key is task 2.2's work, and it may only do so from
an original event that proves every canonical field — guessing one is exactly what ADR-0007 forbids.

**A binding cannot name an event its key did not claim.** Rather than a foreign key to `events`
plus an application check that the two agree, the reference is composite: `(key, event_id)` points
at `idempotency_keys (key, event_id)`, so "the binding's event" and "the key's event" are one fact
the store cannot hold two answers for. That target needs a unique constraint to point at, which is
what `uq_idempotency_keys_key_event` adds — redundant with the existing primary key on `key` alone
and therefore free of new uniqueness semantics. Event existence comes along transitively: the row
it names is itself keyed to `ledger.events`.

**The version is a column as well as a prefix.** `fingerprint` stores the producer's own
`"{version}:{sha256}"` spelling, so a v1 digest can never be read as another version's; the
`fingerprint_version` column carries the same value out where the rollout inventory can index and
count it, and a check constraint makes the two unable to disagree.

**Writes only append.** The service role receives SELECT and INSERT and nothing else: a binding,
like the key and the event it names, is retained, never corrected in place. UPDATE, DELETE and
TRUNCATE are revoked on all three retained relations — bindings, keys and events — in both
directions. The revokes are executed rather than left implicit in an absent grant because a
previous deploy may have handed the role one of them: running this migration *removes* an existing
excess grant. It does not immunise the tables against a future `GRANT`, which would reopen access
until a migration runs again.

**Downgrade preserves data; it rolls back schema access, not the deployed binary.** ADR-0007
requires binding rows to survive a rollback — a rollback re-opens the old collision behaviour and
must be recorded and bounded, not made clean by dropping the evidence of what was already bound. So
`downgrade` revokes the service role's access and leaves the table, its rows and its constraints in
place, which is exactly the 0005 privilege set; `upgrade` is written to be re-runnable over that
retained table, so going forward again restores access to the retained bindings rather than
starting over. Rolling the application binary back is a separate operation from this.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

SERVICE_ROLE = "pulse_ledger_service"

TABLE = "idempotency_bindings"

#: A stored fingerprint's shape: the producer's version tag, then its lowercase hex sha256
#: (`pulse_ledger.request_fingerprint.request_fingerprint`).
FINGERPRINT_FORMAT = "^v[0-9]+:[0-9a-f]{64}$"

#: The unique constraint the composite foreign key points at. Redundant with `idempotency_keys`'
#: primary key on `key` alone, so it adds a reference target and no new uniqueness rule.
KEY_EVENT_UNIQUE = "uq_idempotency_keys_key_event"


def _binding_table_exists() -> bool:
    """Whether a previous upgrade already created the table and a downgrade retained its rows."""
    inspector = sa.inspect(op.get_bind())
    return inspector.has_table(TABLE, schema="ledger")


def _create_binding_table() -> None:
    op.create_unique_constraint(KEY_EVENT_UNIQUE, "idempotency_keys", ["key", "event_id"], schema="ledger")
    op.create_table(
        TABLE,
        # One binding per key: a second claim, by the same writer or another, is a duplicate the
        # store refuses before any application check runs.
        sa.Column("key", sa.Text(), primary_key=True),
        # The credential-resolved writer, never the key's client-supplied prefix (D15, ADR-0007).
        sa.Column("writer_id", sa.Text(), nullable=False),
        sa.Column("fingerprint_version", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("btrim(writer_id) <> ''", name=f"ck_{TABLE}_writer_id_present"),
        sa.CheckConstraint(f"fingerprint ~ '{FINGERPRINT_FORMAT}'", name=f"ck_{TABLE}_fingerprint_format"),
        sa.CheckConstraint(
            "split_part(fingerprint, ':', 1) = fingerprint_version",
            name=f"ck_{TABLE}_fingerprint_version_matches",
        ),
        sa.ForeignKeyConstraint(
            ["key", "event_id"],
            ["ledger.idempotency_keys.key", "ledger.idempotency_keys.event_id"],
            name=f"fk_{TABLE}_key_event",
        ),
        schema="ledger",
    )
    # The reverse direction: which key a committed event was claimed under, for the legacy
    # reconstruction and inventory reads (task 2.2).
    op.create_index(f"ix_{TABLE}_event", TABLE, ["event_id"], schema="ledger")


#: The three relations this change retains for the ledger's lifetime, and which the service role
#: may therefore append to and read but never rewrite or empty.
RETAINED_TABLES = (TABLE, "idempotency_keys", "events")


def _set_service_access(*, granted: bool) -> None:
    """The service role's access to the binding table, in both directions of the rollout."""
    if granted:
        op.execute(f"GRANT SELECT, INSERT ON ledger.{TABLE} TO {SERVICE_ROLE}")
    else:
        op.execute(f"REVOKE SELECT, INSERT ON ledger.{TABLE} FROM {SERVICE_ROLE}")
    # Append-only for the service in either direction. Executed rather than left implicit in an
    # absent grant because an earlier deploy may already have handed the role one of these: running
    # the migration removes the excess. It does not stop a future GRANT from reopening them.
    for table in RETAINED_TABLES:
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON ledger.{table} FROM {SERVICE_ROLE}")


def upgrade() -> None:
    # Re-runnable over a table a downgrade retained: the rollout's forward step after an
    # application rollback restores access to the existing bindings, it does not start over.
    if not _binding_table_exists():
        _create_binding_table()
    _set_service_access(granted=True)


def downgrade() -> None:
    # No DROP TABLE: the bindings, the keys and the events are retained (ADR-0007). The service
    # loses its access to the binding table; the record of what was already bound survives.
    _set_service_access(granted=False)
