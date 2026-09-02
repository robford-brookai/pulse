"""The `billing_engine.subject_facts` store — the durable half of fact folding (task 3.2).

`fold_event` (`billing.facts`) decides *whether* an event contributes anything new;
`PostgresFactStore.apply_event` is the only thing that decides *when* — it reads the current row
with `FOR UPDATE` inside one transaction so two concurrent applies for the same subject can never
race past the fold's own redelivery/ordering check, then writes the fold's answer in the same
transaction. A `None` fold (redelivery, or an event older than what is already folded) commits
nothing: the transaction still closes, but no row changes.

No PHI reaches this module's own code: `facts` is opaque JSONB the fold assembles from event
payloads, and every SQL identifier here is a fixed literal — no caller-shaped column or table name
ever reaches a query string.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping

import psycopg
from psycopg.types.json import Jsonb

from billing.facts import SubjectFactsSnapshot, fold_event

_SELECT_FOR_UPDATE_SQL = """
    SELECT facts, last_event_id FROM billing_engine.subject_facts
     WHERE subject_type = %(subject_type)s AND subject_key = %(subject_key)s
     FOR UPDATE
"""

_UPSERT_SQL = """
    INSERT INTO billing_engine.subject_facts (subject_type, subject_key, facts, last_event_id, updated_at)
    VALUES (%(subject_type)s, %(subject_key)s, %(facts)s, %(last_event_id)s, now())
    ON CONFLICT (subject_type, subject_key) DO UPDATE
       SET facts = EXCLUDED.facts, last_event_id = EXCLUDED.last_event_id, updated_at = now()
"""


class PostgresFactStore:
    """Folds one event onto `billing_engine.subject_facts`, transactionally.

    `conn` is a caller-owned `psycopg.Connection` to the `billing_engine`-holding database — this
    class never opens or closes one, so a consumer loop can share a single long-lived connection
    across many messages (`billing.consumer`) and a test can share one against the throwaway
    per-test cluster (`tests/conftest.py`).
    """

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def apply_event(self, envelope: Mapping[str, object]) -> bool:
        """Fold one event; `True` if the row changed, `False` if the fold found nothing new.

        The subject fields are read straight off the envelope for the `SELECT ... FOR UPDATE` —
        `fold_event` itself validates and re-derives them, so a malformed envelope still raises
        the kit's `RowValidationError` before any row lock is taken.
        """
        subject_type = envelope.get("subject_type")
        subject_key = envelope.get("subject_key")
        with self._conn.transaction():
            existing = (
                self._load_locked(subject_type, subject_key)
                if isinstance(subject_type, str) and isinstance(subject_key, str)
                else None
            )
            next_snapshot = fold_event(existing, envelope)
            if next_snapshot is None:
                return False
            self._conn.execute(
                _UPSERT_SQL,
                {
                    "subject_type": next_snapshot.subject_type,
                    "subject_key": next_snapshot.subject_key,
                    "facts": Jsonb(dict(next_snapshot.facts)),
                    "last_event_id": uuid.UUID(next_snapshot.last_event_id),
                },
            )
        return True

    def _load_locked(self, subject_type: str, subject_key: str) -> SubjectFactsSnapshot | None:
        cursor = self._conn.execute(
            _SELECT_FOR_UPDATE_SQL,
            {"subject_type": subject_type, "subject_key": subject_key},
        )
        row = cursor.fetchone()
        if row is None:
            return None
        facts, last_event_id = row
        return SubjectFactsSnapshot(
            subject_type=subject_type,
            subject_key=subject_key,
            facts=facts,
            last_event_id=str(last_event_id),
        )
