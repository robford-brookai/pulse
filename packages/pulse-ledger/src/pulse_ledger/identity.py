"""The identity registry: what the deterministic matcher (S1.4) reads before it resolves a referral.

Two lookups, in the order v1's matcher runs them:

1. **Exact match on an ExternalIdentifier `(system, value)`** — wins outright. `(system, value)` is
   the primary key of `ledger.external_identifiers`, so "at most one person holds an identifier" is
   a store guarantee, not a rule the resolver has to remember. `attach_identifier` reports the
   holder by name when a second person is declared against a binding that already exists.
2. **Candidate retrieval by the normalized composite** — the fallback when no identifier matches.
   Zero candidates mints, one matches, more than one quarantines; the outcomes are the matcher's,
   the lookup is here.

**The composite is a digest, never demographics.** The matcher's composite is last name + DOB +
sex + first-initial — PHI, all four fields. What reaches this package is `sha256` of the normalized
composite: `register_match_key` refuses anything that is not 64 lowercase hex characters, so the
readable form cannot be stored here even by a caller who passes the wrong argument. Normalization
rules and the hashing live with the matcher (`packages/identity`, S1.4), which is also the only
place that ever holds the demographics.

ExternalIdentifier is a registry, not a state-bearing subject — the object model has always said so
(`design/migration/rpc-object-model-assessment.md`: "registry (child), (system, value) → Person",
state-bearing: no), and the catalog agrees: `person` is absent from `TRANSITIONS` and from the
`events.subject_type` check constraint. So an attachment is a registry row with its actor
attribution, not an event, and it is append-only for the service role: rebinding an identifier from
one patient to another is a `merge_person` declaration, never an UPDATE here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

import psycopg

#: A normalized-composite digest: sha256, lowercase hex. Mirrors `ck_person_match_keys_digest`.
MATCH_KEY_PATTERN = re.compile(r"\A[0-9a-f]{64}\Z")


class IdentifierConflictError(ValueError):
    """`(system, value)` is already held by a different person.

    Carries the holder, because a resolver that cannot name the conflicting person cannot escalate
    the conflict — a duplicate MRN across two patients is a data-integrity incident, not a retry.
    """

    def __init__(self, system: str, value: str, holder: str, requested: str) -> None:
        self.system = system
        self.value = value
        self.holder = holder
        self.requested = requested
        super().__init__(
            f"identifier ({system!r}, {value!r}) is already attached to person {holder!r}; "
            f"refusing to bind it to {requested!r}"
        )


class MalformedMatchKeyError(ValueError):
    """A match key that is not a digest — the readable composite would be PHI in the ledger."""

    def __init__(self) -> None:
        super().__init__(
            "match_key must be the sha256 digest of the normalized composite (64 lowercase hex "
            "characters); the readable composite is PHI and must not reach the ledger"
        )


class BlankFieldError(ValueError):
    """An identifier field that is empty or whitespace — an identity nothing can be resolved by."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"{name!r} must not be blank")


@dataclass(frozen=True)
class IdentifierBinding:
    """One ExternalIdentifier and the person it resolves to."""

    system: str
    value: str
    person_key: str
    actor_type: str
    actor_id: str
    attached_at: datetime


_SELECT_BINDING = "SELECT system, value, person_key, actor_type, actor_id, attached_at FROM ledger.external_identifiers"


def _require_text(value: str, name: str) -> str:
    if not value or not value.strip():
        raise BlankFieldError(name)
    return value


def _binding(row: tuple[object, ...]) -> IdentifierBinding:
    return IdentifierBinding(
        system=str(row[0]),
        value=str(row[1]),
        person_key=str(row[2]),
        actor_type=str(row[3]),
        actor_id=str(row[4]),
        attached_at=row[5],  # type: ignore[arg-type]
    )


def attach_identifier(
    conn: psycopg.Connection,
    *,
    system: str,
    value: str,
    person_key: str,
    actor_type: str,
    actor_id: str,
) -> IdentifierBinding:
    """Bind `(system, value)` to `person_key`, enforcing uniqueness at resolution time.

    Re-attaching the same identifier to the same person is a replay: the existing binding is
    returned, with its original `attached_at`, and no second row is written. Attaching it to a
    different person raises `IdentifierConflictError` naming the current holder.

    The insert races safely without a lock: `ON CONFLICT DO NOTHING` decides, and the loser reads
    the winning row back to find out which case it is in.
    """
    _require_text(system, "system")
    _require_text(value, "value")
    _require_text(person_key, "person_key")
    inserted = conn.execute(
        "INSERT INTO ledger.external_identifiers (system, value, person_key, actor_type, actor_id)"
        " VALUES (%(system)s, %(value)s, %(person_key)s, %(actor_type)s, %(actor_id)s)"
        " ON CONFLICT (system, value) DO NOTHING"
        " RETURNING system, value, person_key, actor_type, actor_id, attached_at",
        {
            "system": system,
            "value": value,
            "person_key": person_key,
            "actor_type": actor_type,
            "actor_id": actor_id,
        },
    ).fetchone()
    if inserted is not None:
        return _binding(inserted)

    existing = lookup_identifier(conn, system=system, value=value)
    if existing is None:  # pragma: no cover - the conflicting row cannot vanish; nothing deletes it
        raise IdentifierConflictError(system, value, holder="unknown", requested=person_key)
    if existing.person_key != person_key:
        raise IdentifierConflictError(system, value, holder=existing.person_key, requested=person_key)
    return existing


def lookup_identifier(conn: psycopg.Connection, *, system: str, value: str) -> IdentifierBinding | None:
    """The person holding `(system, value)` exactly, or `None` if the ledger holds no such binding."""
    row = conn.execute(
        f"{_SELECT_BINDING} WHERE system = %s AND value = %s",
        (system, value),
    ).fetchone()
    return None if row is None else _binding(row)


def identifiers_for_person(conn: psycopg.Connection, person_key: str) -> list[IdentifierBinding]:
    """Every identifier one person holds, in `(system, value)` order — the resolver's evidence."""
    cursor = conn.execute(
        f"{_SELECT_BINDING} WHERE person_key = %s ORDER BY system, value",
        (person_key,),
    )
    return [_binding(row) for row in cursor.fetchall()]


def register_match_key(conn: psycopg.Connection, *, person_key: str, match_key: str) -> None:
    """Index one person under a normalized-composite digest, idempotently.

    A person may carry several digests over time — a name change mints another and the old one keeps
    matching the records that still use it — so this adds rather than replaces.

    Raises `MalformedMatchKeyError` unless `match_key` is a sha256 digest.
    """
    _require_text(person_key, "person_key")
    if not MATCH_KEY_PATTERN.match(match_key):
        raise MalformedMatchKeyError
    conn.execute(
        "INSERT INTO ledger.person_match_keys (person_key, match_key) VALUES (%s, %s)"
        " ON CONFLICT (person_key, match_key) DO NOTHING",
        (person_key, match_key),
    )


def find_candidates(conn: psycopg.Connection, match_key: str) -> list[str]:
    """Persons indexed under this composite digest, in key order.

    The list's length is the matcher's decision: none mints, one matches, several quarantine. The
    ledger returns the set and takes no view.

    Raises `MalformedMatchKeyError` for a non-digest argument — a lookup by readable demographics
    would otherwise return nothing and read as "no candidates", which is the wrong answer to give a
    matcher about to mint a duplicate patient.
    """
    if not MATCH_KEY_PATTERN.match(match_key):
        raise MalformedMatchKeyError
    cursor = conn.execute(
        "SELECT person_key FROM ledger.person_match_keys WHERE match_key = %s ORDER BY person_key",
        (match_key,),
    )
    return [person_key for (person_key,) in cursor.fetchall()]
