"""The two-tier deterministic match: exact identifier, then composite, decided by count alone.

`resolve(referral, lookup)` is the whole surface. It is pure — no ledger writes, no queue, no
clock, no I/O of its own: demographics and identifiers in through a candidate-lookup port, a frozen
decision out (design decision 1). That is what lets the determinism tests shuffle inputs and re-run
without mocking effects, and what lets genesis adjudication call this in batch as a function import
rather than a service dependency.

**Tier 1 — exact identifier.** `(system, value)` is the primary key of
`ledger.external_identifiers`, so at most one person holds an identifier by construction. A hit
resolves outright and the composite tier is never consulted — not "consulted and ignored", never
called, which `test_exact_identifier_hit_never_consults_the_composite_tier` observes through a
counting adapter.

**Tier 2 — composite.** Look up candidates by the sha256 digest of the normalized composite and
decide by the candidate count alone: zero mints, exactly one matches, more than one quarantines.
There is no scoring, no threshold, and no tie-break anywhere in this module. **v1 is deterministic
only**: a wrong auto-merge in a HIPAA system is a reportable event, so every ambiguity goes to a
human and the accepted cost is human workload, never a wrong merge.

**Two identifiers pointing at two people is a conflict, not a choice.** The spec's tier-1
requirement is written for the single-hit case; a referral carrying identifiers held by *different*
persons is the same class of incident as `IdentifierConflictError` on the write path, so it
quarantines under its own rule id (`identifier_conflict`) rather than resolving to whichever
identifier happened to be examined first. Picking one would be deterministic and wrong.

**Evidence carries field names, never field values** (design decision 2). Evidence travels in
command payloads to the ledger; a demographic value here would re-import exactly the PHI the digest
design removed. `Referral` and `Person` transiently hold demographics on their way into
`composite_digest`, so both redact under `__repr__`/`__str__` — a traceback rendering a list of
referrals leaks nothing.

The rule ids and the `resolve` signature are a published contract, not internal refactoring
freedom: they appear in evidence records, review-queue triage, the runbook, and genesis's batch
harness. Changing either follows the published-contract rules.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from identity.normalize import Demographics, composite_digest

__all__ = [
    "COMPOSITE_FIELDS",
    "IDENTIFIER_FIELDS",
    "RULE_COMPOSITE_AMBIGUOUS",
    "RULE_COMPOSITE_NONE",
    "RULE_COMPOSITE_UNIQUE",
    "RULE_IDENTIFIER_CONFLICT",
    "RULE_IDENTIFIER_EXACT",
    "Ambiguous",
    "CandidateLookup",
    "Decision",
    "DuplicatePersonError",
    "Evidence",
    "ExternalIdentifier",
    "IdentifierAlreadyHeldError",
    "InMemoryLookup",
    "LookupStoreError",
    "Match",
    "Mint",
    "Person",
    "Referral",
    "resolve",
]

#: Tier 1 decided. Exactly one person holds an identifier the referral carries.
RULE_IDENTIFIER_EXACT = "identifier_exact"
#: Tier 1 found two or more *different* holders across the referral's identifiers. Quarantine.
RULE_IDENTIFIER_CONFLICT = "identifier_conflict"
#: Tier 2 found exactly one candidate under the composite digest.
RULE_COMPOSITE_UNIQUE = "composite_unique"
#: Tier 2 found no candidate. Mint.
RULE_COMPOSITE_NONE = "composite_none"
#: Tier 2 found more than one candidate. Quarantine; v1 never chooses between them.
RULE_COMPOSITE_AMBIGUOUS = "composite_ambiguous"

#: The fields tier 1 keys on, by name. Values never appear in evidence.
IDENTIFIER_FIELDS = ("identifier_system", "identifier_value")
#: The fields tier 2 keys on, by name — the composite of `normalize.py`, in composite order.
COMPOSITE_FIELDS = ("last_name", "dob", "sex", "first_initial")

_REDACTED = "<REDACTED>"


@dataclass(frozen=True)
class ExternalIdentifier:
    """One `(system, value)` binding as the referral carries it."""

    system: str
    value: str


@dataclass(frozen=True)
class Referral:
    """The matcher's input: what a referral says about who its patient is.

    A transient PHI holder — nothing downstream of `resolve` keeps one, and its repr redacts so an
    f-string in a log line or a container repr in a traceback yields no demographic value and no
    identifier (design decision 3).
    """

    demographics: Demographics
    identifiers: tuple[ExternalIdentifier, ...] = ()

    def __repr__(self) -> str:
        return f"Referral({_REDACTED})"

    __str__ = __repr__


@dataclass(frozen=True)
class Person:
    """An existing person as the in-memory adapter holds it: an id, its identifiers, its demographics.

    Only `InMemoryLookup` takes these — the live adapter (task 3.2) reads the ledger, which stores
    digests and never demographics. Redacts for the same reason `Referral` does.
    """

    person_id: str
    demographics: Demographics
    identifiers: tuple[ExternalIdentifier, ...] = ()

    def __repr__(self) -> str:
        return f"Person(person_id={self.person_id!r}, {_REDACTED})"

    __str__ = __repr__


@dataclass(frozen=True)
class Evidence:
    """Why a decision was made, in a form a reviewer can read without re-running the matcher.

    `matched_fields` names the fields the deciding tier keyed on — *names only*, never values. On a
    mint it names the fields that were searched and found nothing, which is what a reviewer needs to
    know to reproduce the empty candidate set.
    """

    matched_fields: tuple[str, ...]
    rule_id: str
    candidate_count: int


@dataclass(frozen=True)
class Match:
    """Resolve the referral to this existing person."""

    person_id: str
    evidence: Evidence


@dataclass(frozen=True)
class Mint:
    """Nothing matched. Create a new person."""

    evidence: Evidence


@dataclass(frozen=True)
class Ambiguous:
    """More than one person could be meant. Quarantine for a human; v1 never chooses."""

    candidates: tuple[str, ...]
    evidence: Evidence


#: The published decision type.
Decision = Match | Mint | Ambiguous


@runtime_checkable
class CandidateLookup(Protocol):
    """The read port the matcher decides against (design decision 4).

    Two methods, named for the ledger read surface they wrap, so the live adapter (task 3.2) is a
    thin pass-through over `pulse_ledger.identity.lookup_identifier` / `find_candidates`. The port
    is part of the entrypoint contract; the live adapter is not. Genesis brings its own adapter if
    it batches reads.
    """

    def lookup_identifier(self, system: str, value: str) -> str | None:
        """The person holding `(system, value)` exactly, or `None`. At most one by construction."""
        ...

    def find_candidates(self, match_key: str) -> Sequence[str]:
        """Persons indexed under this composite digest. The length is the decision; order is stable."""
        ...


class LookupStoreError(ValueError):
    """The in-memory adapter was given a store the real ledger could not hold."""


class DuplicatePersonError(LookupStoreError):
    """Two `Person` entries share a `person_id` — the ledger's person key is unique."""

    def __init__(self, person_id: str) -> None:
        super().__init__(f"duplicate person_id {person_id!r}")
        self.person_id = person_id


class IdentifierAlreadyHeldError(LookupStoreError):
    """One `(system, value)` bound to two persons — the `external_identifiers` primary key forbids it.

    Names the system and the holder, never the identifier value: this package names fields, not
    values, on every rejection path (design decision 3b).
    """

    def __init__(self, system: str, holder: str) -> None:
        super().__init__(f"an identifier in system {system!r} is already held by person {holder!r}")
        self.system = system
        self.holder = holder


class InMemoryLookup:
    """The in-memory `CandidateLookup` — what tests and genesis harnesses build stores with.

    It refuses stores the ledger's own constraints would refuse: one `(system, value)` held by two
    people, or a duplicated `person_id`. A fake that is laxer than the real thing lets a matcher bug
    pass its tests, and this is the one module where that is not an acceptable trade.
    """

    def __init__(self, persons: Iterable[Person] = ()) -> None:
        by_identifier: dict[tuple[str, str], str] = {}
        by_digest: dict[str, list[str]] = {}
        seen: set[str] = set()
        for person in persons:
            if person.person_id in seen:
                raise DuplicatePersonError(person.person_id)
            seen.add(person.person_id)
            for identifier in person.identifiers:
                key = (identifier.system, identifier.value)
                holder = by_identifier.get(key)
                if holder is not None and holder != person.person_id:
                    raise IdentifierAlreadyHeldError(identifier.system, holder)
                by_identifier[key] = person.person_id
            by_digest.setdefault(composite_digest(person.demographics), []).append(person.person_id)
        self._by_identifier = by_identifier
        self._by_digest = {digest: tuple(sorted(ids)) for digest, ids in by_digest.items()}

    def lookup_identifier(self, system: str, value: str) -> str | None:
        return self._by_identifier.get((system, value))

    def find_candidates(self, match_key: str) -> tuple[str, ...]:
        return self._by_digest.get(match_key, ())


def resolve(referral: Referral, lookup: CandidateLookup) -> Decision:
    """Decide who this referral is about: the published matcher entrypoint.

    Tier 1 (exact identifier) short-circuits — when it decides, no composite digest is computed and
    no candidate lookup happens. Tier 2 decides by candidate count alone. Order-independent and
    re-run-identical: the same referral against the same store always yields an equal decision, and
    the referral's identifier order never reaches the result.

    Raises `NormalizationError` (from `normalize.py`) when tier 2 is reached and a demographic field
    cannot be normalized deterministically — an ambiguous DOB is rejected to the caller, never
    guessed into a match key. The error names the field and a rule id, never the value.
    """
    identifier_decision = _identifier_tier(referral, lookup)
    if identifier_decision is not None:
        return identifier_decision
    return _composite_tier(referral, lookup)


def _identifier_tier(referral: Referral, lookup: CandidateLookup) -> Decision | None:
    """Every identifier is looked up, not just until the first hit — otherwise a conflict hides.

    Returns `None` when no identifier is known, which is the only path to the composite tier.
    """
    holders: set[str] = set()
    for identifier in sorted(referral.identifiers, key=lambda entry: (entry.system, entry.value)):
        holder = lookup.lookup_identifier(identifier.system, identifier.value)
        if holder is not None:
            holders.add(holder)
    if not holders:
        return None
    if len(holders) == 1:
        return Match(
            person_id=next(iter(holders)),
            evidence=Evidence(matched_fields=IDENTIFIER_FIELDS, rule_id=RULE_IDENTIFIER_EXACT, candidate_count=1),
        )
    candidates = tuple(sorted(holders))
    return Ambiguous(
        candidates=candidates,
        evidence=Evidence(
            matched_fields=IDENTIFIER_FIELDS,
            rule_id=RULE_IDENTIFIER_CONFLICT,
            candidate_count=len(candidates),
        ),
    )


def _composite_tier(referral: Referral, lookup: CandidateLookup) -> Decision:
    """Count alone decides. No scoring, no threshold, no tie-break — deliberately (design — v1)."""
    candidates = tuple(sorted(lookup.find_candidates(composite_digest(referral.demographics))))
    count = len(candidates)
    if count == 0:
        return Mint(evidence=_composite_evidence(RULE_COMPOSITE_NONE, 0))
    if count == 1:
        return Match(person_id=candidates[0], evidence=_composite_evidence(RULE_COMPOSITE_UNIQUE, 1))
    return Ambiguous(candidates=candidates, evidence=_composite_evidence(RULE_COMPOSITE_AMBIGUOUS, count))


def _composite_evidence(rule_id: str, candidate_count: int) -> Evidence:
    return Evidence(matched_fields=COMPOSITE_FIELDS, rule_id=rule_id, candidate_count=candidate_count)
