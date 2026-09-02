"""The published event envelope, defined once.

Two readers hand a committed event to the same consumers: the outbox relay (`relay.py`, over the
bus) and the per-subject history read (`reads.subject_history`, over the command API's read
surface). A projection folding a subject's history to rebuild its rows must see exactly the shape
it saw when the events arrived live — a rebuild that folds a *different* envelope is not a rebuild
of the same events, and it would disagree with incremental apply on precisely the fields the two
shapes differ in. So the shape lives here and both readers call it.

`effective_at` is the ledger's canonical name for business time and `occurred_at` is emitted beside
it with the same value — the same alias the write path accepts (commit.py, decision 5), so a
consumer written against either name reads the one fact. `seq` and the subject pair travel with the
envelope because per-subject ordering is only checkable by a consumer that can see the sequence it
is meant to hold.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: The `ledger.events` columns an envelope is built from, as a SELECT fragment. Named once so the
#: relay's claim query and the history read cannot select different halves of the same shape.
EVENT_COLUMNS = (
    "e.event_type, e.effective_at, e.recorded_at, e.producer, e.schema_version,"
    " e.rule_version, e.correlation_id, e.causation_id, e.actor_type, e.actor_id,"
    " e.actor_authority, e.evidence, e.evidence_class, e.epoch, e.reverses_event_id,"
    " e.payload"
)


def event_envelope(row: Mapping[str, Any]) -> dict[str, Any]:
    """The published envelope for one committed event row joined to its outbox `seq`."""
    return {
        "event_id": str(row["event_id"]),
        "event_type": row["event_type"],
        "subject_type": row["subject_type"],
        "subject_key": row["subject_key"],
        "seq": row["seq"],
        "effective_at": row["effective_at"].isoformat(),
        "occurred_at": row["effective_at"].isoformat(),
        "recorded_at": row["recorded_at"].isoformat(),
        "producer": row["producer"],
        "schema_version": row["schema_version"],
        "rule_version": row["rule_version"],
        "correlation_id": str(row["correlation_id"]) if row["correlation_id"] else None,
        "causation_id": str(row["causation_id"]) if row["causation_id"] else None,
        "reverses_event_id": str(row["reverses_event_id"]) if row["reverses_event_id"] else None,
        "actor": {
            "type": row["actor_type"],
            "id": row["actor_id"],
            "authority": row["actor_authority"],
        },
        "evidence": row["evidence"],
        "evidence_class": row["evidence_class"],
        "epoch": row["epoch"],
        "payload": row["payload"],
    }
