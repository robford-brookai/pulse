"""Reconstructing an authenticated binding for a key claimed before bindings existed (ADR-0007).

Idempotency keys are retained for the ledger's lifetime, so every key already stored is a key a
producer may still retry — and none of them carries the two facts the D16 amendment requires before
a replay: the *authenticated writer* who claimed it and the *canonical request* they sent
(`pulse_ledger.request_fingerprint`). Refusing all of them would turn valid deployed retries into
errors; inventing bindings for all of them would hand a key to whoever asked for it next. Design
decision 4 takes the third path: rebuild a binding **only** from what the original event proves,
and refuse the rest with a distinct reason that has a reviewed reconciliation path.

## What the stored event proves

The commit path writes one column per canonical v1 field, so the field map is reconstructible in
full — but only for an event the boundary itself wrote. Every check below is about *provenance*,
not about repairing data:

- **`schema_version` is this build's.** A row stored under a later shape is not evidence of a v1
  request, and this build has no map to read it under. Undecidable, not broken — it is the one
  reason that reports `unknown` rather than `fix-required`.
- **`reverses_event_id` is null.** A reversal is appended by `commit_reversal`, whose payload is a
  reason and not a declared command. There is no accepted request behind it to rebuild.
- **`producer` equals `actor_id`, and `actor_type` is the internal one.** The boundary sets all
  three from a single resolved credential (`Writer.attribution`), so a row where they disagree was
  written by some other path and names no authenticated writer. D15 again: the identity is the
  credential's, never a string that happens to sit in a column.
- **`evidence_bounds` is whole or absent.** One bound does not determine the pair, so there is no
  canonical request to compute — an assumed second bound would be exactly the guess ADR-0007
  forbids.
- **The rebuilt request fingerprints.** A value with no canonical spelling refuses here the same
  way it would have refused at ingress.

Nothing is defaulted and nothing is read from the incoming request: `reconstruct_binding` never
sees it. The caller compares its own binding against the rebuilt one
(`request_fingerprint.classify_binding`), so a mismatch is a conflict on the same footing as any
other — it cannot become an overwrite.

## Reading, never writing

This module only reads. Writing the reconstructed binding belongs in `pulse_ledger.idempotency`,
inside the transaction that is already deciding the replay, so the binding lands in the same
transaction as the answer it justifies and disappears with it if anything after it fails.

## The inventory is a gate

`inventory_legacy_keys` is the population side of the same question, and the evidence behind
`docs/idempotency-compatibility-inventory.md`: one row per producer, at the worst disposition any
of its keys holds, so a producer with a single unreconstructible key is not averaged into looking
ready. Two rules are structural rather than procedural — `enforcement_blocked` is true while any
row is `fix-required` or `unknown`, **and** true for an empty inventory, because no rows means the
inventory was never taken rather than that nothing needs one.

**PHI.** A row carries producer ids, key texts, event ids, counts and reason *names*. Never a
request value, an evidence member, or a fingerprint — a fingerprint is derived from `payload` and
`evidence`, and a digest of a small value space is a lookup table (`request_fingerprint`). The
inventory is written into a doc and a tracking issue, so that constraint is enforced by what
`ProducerRow` is able to hold, not by a caller remembering to redact.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

import psycopg

from pulse_ledger.auth import INTERNAL_ACTOR_TYPE
from pulse_ledger.commit import Declaration
from pulse_ledger.fold import TO_STATE_KEY
from pulse_ledger.request_fingerprint import (
    FINGERPRINT_VERSION,
    FingerprintError,
    WriterBinding,
    request_fingerprint,
)

#: The stored event shape this build's canonical v1 field map is written against. A row at any
#: other version is undecidable here rather than reconstructible or broken.
SUPPORTED_SCHEMA_VERSION = 1


class LegacyReason(str, Enum):
    """Why an event proves no binding. Internal: it reaches the inventory, never a response.

    A caller is told `idempotency_legacy_unverifiable` and nothing more — telling it *which* check
    refused would let it probe what a key already holds, the same reason
    `IdempotencyConflictError` carries one reason for every mismatch.
    """

    UNSUPPORTED_SCHEMA_VERSION = "unsupported_schema_version"
    CORRECTION_EVENT = "correction_event"
    UNATTRIBUTED_WRITER = "unattributed_writer"
    INCOMPLETE_EVIDENCE_BOUNDS = "incomplete_evidence_bounds"
    UNFINGERPRINTABLE_REQUEST = "unfingerprintable_request"


#: Reasons this build cannot decide, as opposed to ones it decides against. They report `unknown`,
#: which blocks the rollout the same way `fix-required` does but names a different follow-up: a
#: field map for that shape, not a producer-side change.
UNDECIDABLE_REASONS = frozenset({LegacyReason.UNSUPPORTED_SCHEMA_VERSION})


class ReconstructionShapeError(ValueError):
    """A reconstruction was built as both a binding and a reason, or as neither.

    A programming error in this module, never a property of stored data — the two outcomes are
    exclusive, and a type that could hold both would let a caller read the binding off a refusal.
    """

    def __init__(self) -> None:
        super().__init__("a reconstruction is either a binding or a reason, never both or neither")


class UnclassifiedProducerError(ValueError):
    """A producer row was assembled with no classified keys, which its construction cannot produce."""

    def __init__(self, counts: object) -> None:
        super().__init__(f"a producer row with no classified keys: {counts!r}")


@dataclass(frozen=True)
class LegacyReconstruction:
    """What an original event proved about the key that claimed it.

    Exactly one of `binding` and `reason` is set. `binding` carries a fingerprint, so this type is
    not safe to log — the same posture `WriterBinding` takes.
    """

    binding: WriterBinding | None = None
    reason: LegacyReason | None = None

    def __post_init__(self) -> None:
        if (self.binding is None) == (self.reason is None):
            raise ReconstructionShapeError()

    @property
    def proved(self) -> bool:
        return self.binding is not None


class LegacyDisposition(str, Enum):
    """A producer's standing against the rollout gate, spelled as the inventory doc spells it."""

    MIGRATED = "migrated"
    COMPATIBLE = "compatible"
    FIX_REQUIRED = "fix-required"
    UNKNOWN = "unknown"


#: Worst first. A producer's row takes the first disposition any of its keys holds, so one
#: unreconstructible key is never averaged away by a thousand compatible ones.
DISPOSITION_PRECEDENCE: tuple[LegacyDisposition, ...] = (
    LegacyDisposition.UNKNOWN,
    LegacyDisposition.FIX_REQUIRED,
    LegacyDisposition.COMPATIBLE,
    LegacyDisposition.MIGRATED,
)

#: The two that block enforcement (`docs/idempotency-compatibility-inventory.md`, Rollout gate).
BLOCKING_DISPOSITIONS = frozenset({LegacyDisposition.FIX_REQUIRED, LegacyDisposition.UNKNOWN})


@dataclass(frozen=True)
class ProducerRow:
    """One producer's keys, summarised for `docs/idempotency-compatibility-inventory.md`.

    `producer` is the stored `producer` column, which is the grouping label and *not* on its own a
    proof of identity — a key whose event fails the attribution check is still listed under the
    producer it claims, which is where a reviewer needs to see it. Reasons are the enum's names,
    never values from the events they describe.
    """

    producer: str
    keys: int
    disposition: LegacyDisposition
    counts: Mapping[LegacyDisposition, int]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class LegacyInventory:
    """Every retained key, by producer — the evidence behind the rollout gate."""

    rows: tuple[ProducerRow, ...]

    @property
    def total_keys(self) -> int:
        return sum(row.keys for row in self.rows)

    @property
    def blocking(self) -> tuple[ProducerRow, ...]:
        return tuple(row for row in self.rows if row.disposition in BLOCKING_DISPOSITIONS)

    @property
    def enforcement_blocked(self) -> bool:
        """True until every producer is `compatible` or `migrated` — and true with no rows at all.

        "No rows" is not a pass: an empty inventory means it has not been taken (the doc's own
        rule), and enforcing on the strength of a query nobody ran is the failure this gate exists
        to prevent.
        """
        return not self.rows or bool(self.blocking)

    def blocking_reasons(self) -> tuple[str, ...]:
        """One line per reason enforcement is still blocked, safe to paste into an issue."""
        if not self.rows:
            return ("no keys inventoried: an empty inventory has not been taken, and cannot clear the gate",)
        return tuple(
            f"{row.producer}: {row.disposition.value} ({row.keys} keys; {', '.join(row.reasons) or 'no reason recorded'})"
            for row in self.blocking
        )


def reconstruct_binding(conn: psycopg.Connection, key: str, event_id: uuid.UUID) -> LegacyReconstruction:
    """The binding the original event proves for `key`, or the reason it proves none.

    Reads the event `key` already claimed and rebuilds the canonical v1 request from its own
    columns. The incoming request is deliberately not a parameter: this answers "what did the
    ledger already accept under this key", and the caller compares.
    """
    row = _stored_event(conn, event_id)
    if row is None:
        # The key's foreign key makes this unreachable through the schema; treated as undecidable
        # rather than asserted away, because a reconstruction that cannot read its evidence has
        # proved nothing either way.
        return LegacyReconstruction(reason=LegacyReason.UNSUPPORTED_SCHEMA_VERSION)
    declaration, reason = _declaration_from(row)
    if declaration is None:
        assert reason is not None  # noqa: S101 — the two are exclusive by construction above
        return LegacyReconstruction(reason=reason)
    try:
        fingerprint = request_fingerprint(declaration)
    except FingerprintError:
        # Names neither the path nor the type here: this value travels to the inventory.
        return LegacyReconstruction(reason=LegacyReason.UNFINGERPRINTABLE_REQUEST)
    return LegacyReconstruction(
        binding=WriterBinding(
            idempotency_key=key,
            writer_id=row["producer"],
            fingerprint=fingerprint,
            event_id=event_id,
        )
    )


def inventory_legacy_keys(conn: psycopg.Connection) -> LegacyInventory:
    """Every retained idempotency key, classified and grouped by the producer of its event.

    One pass over the keys joined to their events and any binding already recorded. Intended for
    the rollout preflight and for a synthetic copy of pre-binding rows — it reads no request values
    out of the process and returns none.
    """
    per_producer: dict[str, Counter[LegacyDisposition]] = {}
    per_producer_reasons: dict[str, set[str]] = {}
    for row in _claimed_events(conn):
        disposition, reason = _classify(conn, row)
        producer = row["producer"]
        per_producer.setdefault(producer, Counter())[disposition] += 1
        if reason is not None:
            per_producer_reasons.setdefault(producer, set()).add(reason.value)
    rows = tuple(
        ProducerRow(
            producer=producer,
            keys=sum(counts.values()),
            disposition=_worst(counts),
            counts=dict(counts),
            reasons=tuple(sorted(per_producer_reasons.get(producer, ()))),
        )
        for producer, counts in sorted(per_producer.items())
    )
    return LegacyInventory(rows=rows)


def _classify(conn: psycopg.Connection, row: Mapping[str, Any]) -> tuple[LegacyDisposition, LegacyReason | None]:
    """One key's standing: already bound, reconstructible, decidably not, or undecidable."""
    if row["bound_version"] is not None:
        # A binding under another version's map can never match a request this build fingerprints,
        # so it is not "migrated" — it needs that version's field map before anyone can say.
        if row["bound_version"] != FINGERPRINT_VERSION:
            return LegacyDisposition.UNKNOWN, LegacyReason.UNSUPPORTED_SCHEMA_VERSION
        return LegacyDisposition.MIGRATED, None
    reconstruction = reconstruct_binding(conn, row["key"], row["event_id"])
    if reconstruction.proved:
        return LegacyDisposition.COMPATIBLE, None
    reason = reconstruction.reason
    assert reason is not None  # noqa: S101 — exclusive with `binding` by construction
    if reason in UNDECIDABLE_REASONS:
        return LegacyDisposition.UNKNOWN, reason
    return LegacyDisposition.FIX_REQUIRED, reason


def _worst(counts: Mapping[LegacyDisposition, int]) -> LegacyDisposition:
    for disposition in DISPOSITION_PRECEDENCE:
        if counts.get(disposition):
            return disposition
    raise UnclassifiedProducerError(dict(counts))


#: Every column a canonical v1 request is rebuilt from, plus the three provenance columns the
#: rebuild is gated on. Fixed and literal — no caller-shaped identifier reaches SQL.
_EVENT_COLUMNS = (
    "subject_type",
    "subject_key",
    "event_type",
    "effective_at",
    "producer",
    "actor_type",
    "actor_id",
    "actor_authority",
    "evidence",
    "evidence_class",
    "evidence_bound_lower",
    "evidence_bound_upper",
    "epoch",
    "reverses_event_id",
    "payload",
    "schema_version",
)


def _stored_event(conn: psycopg.Connection, event_id: uuid.UUID) -> dict[str, Any] | None:
    columns = ", ".join(_EVENT_COLUMNS)
    row = conn.execute(
        f"SELECT {columns} FROM ledger.events WHERE event_id = %s",  # noqa: S608 — a module constant
        (event_id,),
    ).fetchone()
    return None if row is None else dict(zip(_EVENT_COLUMNS, row, strict=True))


def _claimed_events(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Every retained key with its event's producer and the version of any binding it already has."""
    rows = conn.execute(
        "SELECT k.key, k.event_id, e.producer, b.fingerprint_version"
        " FROM ledger.idempotency_keys k"
        " JOIN ledger.events e ON e.event_id = k.event_id"
        " LEFT JOIN ledger.idempotency_bindings b ON b.key = k.key"
        " ORDER BY k.key"
    ).fetchall()
    return [
        {"key": key, "event_id": event_id, "producer": producer, "bound_version": bound_version}
        for key, event_id, producer, bound_version in rows
    ]


def _declaration_from(row: Mapping[str, Any]) -> tuple[Declaration | None, LegacyReason | None]:
    """The accepted request this event proves, or the reason it proves none.

    Every branch is a provenance question. There is deliberately no repair path: a field the event
    does not carry is a field this function refuses over, not one it supplies.
    """
    if row["schema_version"] != SUPPORTED_SCHEMA_VERSION:
        return None, LegacyReason.UNSUPPORTED_SCHEMA_VERSION
    if row["reverses_event_id"] is not None:
        return None, LegacyReason.CORRECTION_EVENT
    if not _attribution_is_credential_derived(row):
        return None, LegacyReason.UNATTRIBUTED_WRITER
    bounds, complete = _evidence_bounds(row)
    if not complete:
        return None, LegacyReason.INCOMPLETE_EVIDENCE_BOUNDS
    payload = dict(row["payload"] or {})
    to_state = payload.pop(TO_STATE_KEY, None)
    if to_state is not None and not isinstance(to_state, str):
        # `Declaration.to_state` is a state name; anything else was not written by this boundary.
        return None, LegacyReason.UNFINGERPRINTABLE_REQUEST
    return (
        Declaration(
            subject_type=row["subject_type"],
            subject_key=row["subject_key"],
            event_type=row["event_type"],
            effective_at=row["effective_at"],
            actor_type=row["actor_type"],
            actor_id=row["actor_id"],
            actor_authority=row["actor_authority"],
            producer=row["producer"],
            to_state=to_state,
            evidence_class=row["evidence_class"],
            epoch=row["epoch"],
            evidence=row["evidence"],
            evidence_bounds=bounds,
            payload=payload,
        ),
        None,
    )


def _attribution_is_credential_derived(row: Mapping[str, Any]) -> bool:
    """Whether one resolved credential could have stamped this event's attribution (D15).

    `Writer.attribution` sets `producer`, `actor_id` and `actor_type` together, so agreement is
    what an event written through the boundary looks like and disagreement is proof it was not.
    The check is necessary, not sufficient — it is why a reconstructed binding is compared against
    the incoming request rather than trusted on its own.
    """
    producer = row["producer"]
    return bool(producer) and producer == row["actor_id"] and row["actor_type"] == INTERNAL_ACTOR_TYPE


def _evidence_bounds(row: Mapping[str, Any]) -> tuple[tuple[datetime, datetime] | None, bool]:
    """The stored bounds as a pair, and whether the stored columns determine one.

    Both null is a complete answer — the request carried no bounds. One null is not: the pair it
    came from cannot be recovered, and assuming the missing half would mint a request nobody sent.
    """
    lower, upper = row["evidence_bound_lower"], row["evidence_bound_upper"]
    if lower is None and upper is None:
        return None, True
    if lower is None or upper is None:
        return None, False
    return (lower, upper), True
