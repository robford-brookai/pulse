"""Fact folding — the pure core of the engine's consume loop (task 3.2, design.md decision 5).

The engine's `subject_facts` row is a per-(subject_type, subject_key) snapshot folded from every
committed ledger event the queue delivers for it (billing-engine spec references design.md
decision 5: "enough to make re-evaluation idempotent"). Folding one event onto an existing
snapshot must hold two properties, both pure functions of the envelope and the current row —
`fold_event` is where both live, so the store (`billing.store`) never has to reason about either:

- **Idempotent on redelivery.** `subject_facts.last_event_id` is the per-subject high-water
  mark (schema comment, `infra/postgres/versions/0001_billing_engine_schema.py`): an event whose
  id the row already recorded as applied folds to `None` — nothing to write — however many times
  the queue redelivers it.
- **Ordered by business time, not delivery time.** The bus makes no delivery-order promise, so a
  merge that trusted arrival order could let a stale, backdated event clobber a fact a
  later-arriving-but-earlier-effective event already established. Every fold instead compares the
  incoming event's `effective_at` against the snapshot's own recorded effective time (carried
  inside `facts` under `_FOLDED_AS_OF_KEY`, since the schema keeps no separate column for it) and
  applies only when the incoming fact is at or after it — last-write-wins by effective time, tied
  toward applying, the same rule the ledger's own state projection uses
  (`pulse_ledger.relay`: "state projection is last-write-wins by occurred_at").

`_FOLDED_AS_OF_KEY` is the one reserved key in an otherwise flat merge of each event's `payload`
onto the snapshot: every other key a rule module (task 3.3) reads off `subject_facts.facts` is
exactly a payload field name from some event's envelope, undisturbed by folding.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from pulse_core.connector import RowValidationError, required_string, required_timestamp

#: Reserved key inside `facts` holding the effective time of the last event the fold applied —
#: never a real fact field, since no envelope payload uses a leading double underscore.
_FOLDED_AS_OF_KEY = "__folded_as_of__"


@dataclass(frozen=True)
class SubjectFactsSnapshot:
    """One `billing_engine.subject_facts` row, as the fold reads and writes it."""

    subject_type: str
    subject_key: str
    facts: Mapping[str, object]
    last_event_id: str

    @property
    def folded_as_of(self) -> str | None:
        value = self.facts.get(_FOLDED_AS_OF_KEY)
        return value if isinstance(value, str) else None


def fold_event(
    existing: SubjectFactsSnapshot | None,
    envelope: Mapping[str, object],
) -> SubjectFactsSnapshot | None:
    """The next snapshot after one event, or `None` when the event contributes nothing new.

    `None` covers both a redelivery of an already-applied event id and a fact that arrived out of
    order (an incoming `effective_at` strictly before the snapshot's own) — the caller
    (`billing.store.PostgresFactStore`) treats either as "nothing to write," which is what makes
    the fold idempotent under both replay and reordering without the store needing its own
    comparison logic.

    Raises whatever `required_string`/`required_timestamp` raise (`RowValidationError`, from the
    connector kit — connector-kit spec: "a malformed row is named... never a payload value") when
    the envelope is missing `event_id`, `subject_type`, `subject_key`, `effective_at`, or carries a
    non-object `payload`.
    """
    event_id = required_string(envelope, "event_id")
    subject_type = required_string(envelope, "subject_type")
    subject_key = required_string(envelope, "subject_key")
    effective_at = required_timestamp(envelope, "effective_at")
    payload = envelope.get("payload")
    if not isinstance(payload, Mapping):
        raise RowValidationError("payload", "payload is not a JSON object")

    if existing is not None and existing.last_event_id == event_id:
        return None  # exact redelivery — this event already folded

    if existing is not None and existing.folded_as_of is not None:
        # `existing.folded_as_of` was itself produced by a prior `required_timestamp` call below
        # (it is `envelope["effective_at"]` from whichever event last applied), so it is always a
        # well-formed ISO-8601 instant — a plain parse, not another `required_timestamp` round trip.
        already_folded_as_of = datetime.fromisoformat(existing.folded_as_of)
        if effective_at < already_folded_as_of:
            return None  # out of order: an earlier fact than what is already folded

    merged: dict[str, object] = dict(existing.facts) if existing is not None else {}
    merged.update(payload)
    merged[_FOLDED_AS_OF_KEY] = envelope["effective_at"]

    return SubjectFactsSnapshot(
        subject_type=subject_type,
        subject_key=subject_key,
        facts=merged,
        last_event_id=event_id,
    )
