"""The `billing_engine.subject_facts` store — the durable half of fact folding (task 3.2).

`fold_event` (`billing.facts`) decides *whether* an event contributes anything new;
`PostgresFactStore.apply_event` is the only thing that decides *when* — it reads the current row
with `FOR UPDATE` inside one transaction so two concurrent applies for the same subject can never
race past the fold's own redelivery/ordering check, then writes the fold's answer in the same
transaction. A `None` fold (redelivery, or an event older than what is already folded) commits
nothing: the transaction still closes, but no row changes.

`record_evaluation` (billing-connector task 2.3) is the one write here that is not a fold: the
append to `billing_engine.evaluations` the connector's service makes once the ledger has answered
a declared verdict. It shares this class because it shares the connection and the schema, not
because it shares the fold's transactional dance — it is a single idempotent insert.

No PHI reaches this module's own code: `facts` is opaque JSONB the fold assembles from event
payloads, and every SQL identifier here is a fixed literal — no caller-shaped column or table name
ever reaches a query string.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import TYPE_CHECKING

import psycopg
from psycopg.types.json import Jsonb

from billing.facts import SubjectFactsSnapshot, fold_event

if TYPE_CHECKING:
    from datetime import datetime

_SELECT_FOR_UPDATE_SQL = """
    SELECT facts, last_event_id, updated_at FROM billing_engine.subject_facts
     WHERE subject_type = %(subject_type)s AND subject_key = %(subject_key)s
     FOR UPDATE
"""

_SELECT_SQL = """
    SELECT facts, last_event_id, updated_at FROM billing_engine.subject_facts
     WHERE subject_type = %(subject_type)s AND subject_key = %(subject_key)s
"""

_INSERT_EVALUATION_SQL = """
    INSERT INTO billing_engine.evaluations
        (subject_type, subject_key, verdict_type, rule_version, outcome, as_of, declared_event_id)
    VALUES (%(subject_type)s, %(subject_key)s, %(verdict_type)s, %(rule_version)s, %(outcome)s,
            %(as_of)s, %(declared_event_id)s)
    ON CONFLICT (declared_event_id) DO NOTHING
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

    def load_snapshot(self, subject_type: str, subject_key: str) -> SubjectFactsSnapshot | None:
        """Read one subject's current fact snapshot, unlocked — the read path
        `billing_connector.evaluate.evaluate_subject` (task 2.1) uses to derive `facts_stale`
        from `updated_at` and to hand the rule registry a fact snapshot. No `FOR UPDATE`: this is
        an evaluate-time read, not a fold, so it never needs `apply_event`'s transactional
        guarantee against a concurrent fold for the same subject.
        """
        cursor = self._conn.execute(
            _SELECT_SQL,
            {"subject_type": subject_type, "subject_key": subject_key},
        )
        row = cursor.fetchone()
        if row is None:
            return None
        facts, last_event_id, updated_at = row
        return SubjectFactsSnapshot(
            subject_type=subject_type,
            subject_key=subject_key,
            facts=facts,
            last_event_id=str(last_event_id),
            updated_at=updated_at,
        )

    def record_evaluation(
        self,
        *,
        subject_type: str,
        subject_key: str,
        verdict_type: str,
        rule_version: str,
        outcome: str,
        as_of: datetime,
        declared_event_id: str,
    ) -> bool:
        """Append one evaluation to `billing_engine.evaluations`; `True` if a row was written.

        The write path `billing_connector.service.run_batch` (billing-connector task 2.3) calls
        once per declared verdict, after the ledger has answered, so the row carries the declared
        event id the spec requires ("Each evaluation SHALL be recorded in the engine's
        `evaluations` store with the declared event id"). Deliberately *not* called from the
        connector's `evaluate.py` or `declare.py`: evaluation is pure over a fact snapshot and
        declaration owns the command API, so the one place that holds both an `Evaluation` and
        the ledger's answer for it is the service that orchestrates them.

        Idempotent by `declared_event_id`, the table's own unique key: a replayed submission
        answers with the event id the original commit produced, so re-declaring an unchanged
        evaluation conflicts onto the row already there and writes nothing new (spec:
        "Re-evaluating unchanged facts declares nothing new"). Returns `False` in exactly that
        case.

        Every argument is a qualification fact or a lineage pointer — a subject key, a verdict
        type, a rule version, an outcome, a time, an event id. No monetary value is accepted
        here, so none can reach this table by way of this method (spec: "No monetary value
        crosses the seam"). `declared_event_id` is parsed as a UUID before it reaches SQL, so a
        malformed id raises rather than widening the column's shape.
        """
        with self._conn.transaction():
            cursor = self._conn.execute(
                _INSERT_EVALUATION_SQL,
                {
                    "subject_type": subject_type,
                    "subject_key": subject_key,
                    "verdict_type": verdict_type,
                    "rule_version": rule_version,
                    "outcome": outcome,
                    "as_of": as_of,
                    "declared_event_id": uuid.UUID(declared_event_id),
                },
            )
        return cursor.rowcount == 1

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
        facts, last_event_id, updated_at = row
        return SubjectFactsSnapshot(
            subject_type=subject_type,
            subject_key=subject_key,
            facts=facts,
            last_event_id=str(last_event_id),
            updated_at=updated_at,
        )
