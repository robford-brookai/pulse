"""`LedgerLookup`: the live `CandidateLookup` adapter over `pulse_ledger.identity`.

No live network (`conftest.py` blocks sockets) — `pulse_ledger.identity.lookup_identifier` and
`find_candidates` are monkeypatched rather than run against a real connection; `LedgerLookup`
itself does not know or care what backs `psycopg.Connection`, so a plain sentinel object stands in
for one.

Two things this suite has to prove:

1. Port conformance — driven through `matcher.resolve`, `LedgerLookup` yields the identical
   decisions `InMemoryLookup` (3.1) yields for the same store, across the full trichotomy.
2. The composite tier transmits only the sha256 digest — never a readable composite — in every
   call `find_candidates` receives, whether inspected directly or through a full resolution.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, cast

import psycopg
import pulse_ledger.identity as ledger_identity
import pytest
from fixtures.loader import load_all_cases
from identity.lookup import LedgerLookup
from identity.matcher import (
    Ambiguous,
    CandidateLookup,
    ExternalIdentifier,
    InMemoryLookup,
    Match,
    Mint,
    Person,
    Referral,
    resolve,
)
from identity.normalize import Demographics
from pulse_ledger.identity import IdentifierBinding

CASES = load_all_cases()

DECISION_CASES = (
    "exact_identifier_hit",
    "composite_unique_hit",
    "mint_unknown_everything",
    "two_candidate_ambiguity",
    "near_miss_different_dob",
)

_CONN = cast(psycopg.Connection, object())  # LedgerLookup never inspects the connection.


def demographics(raw: dict[str, Any]) -> Demographics:
    return Demographics(
        last_name=raw["last_name"],
        first_name=raw["first_name"],
        dob=raw["dob"],
        sex=raw["sex"],
    )


def identifiers(raw: list[dict[str, str]]) -> tuple[ExternalIdentifier, ...]:
    return tuple(ExternalIdentifier(system=entry["system"], value=entry["value"]) for entry in raw)


def leakable_values(raw: dict[str, Any]) -> tuple[str, ...]:
    """Demographic values long enough for containment to mean something (mirrors test_matcher.py)."""
    return tuple(str(value) for value in raw.values() if len(str(value)) > 2)


def referral_of(case: dict[str, Any]) -> Referral:
    raw = case["referral"]
    return Referral(demographics=demographics(raw["demographics"]), identifiers=identifiers(raw["identifiers"]))


def persons_of(case: dict[str, Any]) -> list[Person]:
    return [
        Person(
            person_id=person["person_id"],
            demographics=demographics(person["demographics"]),
            identifiers=identifiers(person["identifiers"]),
        )
        for person in case["existing_persons"]
    ]


class _FakeLedger:
    """Same lookups the real ledger offers, backed by an `InMemoryLookup` instead of Postgres.

    `LedgerLookup` only ever calls `ledger_identity.lookup_identifier` / `find_candidates` with the
    signatures this fakes — everything downstream of that boundary (SQL, the connection) is
    `pulse_ledger`'s to test, not this package's.
    """

    def __init__(self, persons: list[Person]) -> None:
        self._inner = InMemoryLookup(persons)

    def lookup_identifier(self, conn: object, *, system: str, value: str) -> IdentifierBinding | None:
        person_key = self._inner.lookup_identifier(system, value)
        if person_key is None:
            return None
        return IdentifierBinding(
            system=system,
            value=value,
            person_key=person_key,
            actor_type="system",
            actor_id="identity-resolver",
            attached_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
        )

    def find_candidates(self, conn: object, match_key: str) -> list[str]:
        return list(self._inner.find_candidates(match_key))


def _patch_ledger(monkeypatch: pytest.MonkeyPatch, persons: list[Person]) -> _FakeLedger:
    fake = _FakeLedger(persons)
    monkeypatch.setattr(ledger_identity, "lookup_identifier", fake.lookup_identifier)
    monkeypatch.setattr(ledger_identity, "find_candidates", fake.find_candidates)
    return fake


# --- Port conformance: same store, same decision as the in-memory adapter ---------------------


def test_satisfies_the_candidate_lookup_port():
    lookup: CandidateLookup = LedgerLookup(_CONN)
    assert isinstance(lookup, CandidateLookup)


@pytest.mark.parametrize("name", DECISION_CASES)
def test_resolves_identically_to_the_in_memory_adapter(monkeypatch: pytest.MonkeyPatch, name: str):
    case = CASES[name]
    persons = persons_of(case)
    _patch_ledger(monkeypatch, persons)

    live_decision = resolve(referral_of(case), LedgerLookup(_CONN))
    memory_decision = resolve(referral_of(case), InMemoryLookup(persons))

    assert live_decision == memory_decision


def test_exact_identifier_hit_matches_the_identifier_holder(monkeypatch: pytest.MonkeyPatch):
    case = CASES["exact_identifier_hit"]
    _patch_ledger(monkeypatch, persons_of(case))
    decision = resolve(referral_of(case), LedgerLookup(_CONN))
    assert isinstance(decision, Match)
    assert decision.person_id == case["expected_person_id"]


def test_zero_candidates_mints(monkeypatch: pytest.MonkeyPatch):
    case = CASES["mint_unknown_everything"]
    _patch_ledger(monkeypatch, persons_of(case))
    assert isinstance(resolve(referral_of(case), LedgerLookup(_CONN)), Mint)


def test_two_candidates_quarantine(monkeypatch: pytest.MonkeyPatch):
    case = CASES["two_candidate_ambiguity"]
    _patch_ledger(monkeypatch, persons_of(case))
    decision = resolve(referral_of(case), LedgerLookup(_CONN))
    assert isinstance(decision, Ambiguous)
    assert decision.candidates == tuple(case["expected_candidate_person_ids"])


def test_no_binding_returns_none(monkeypatch: pytest.MonkeyPatch):
    _patch_ledger(monkeypatch, [])
    assert LedgerLookup(_CONN).lookup_identifier("MRN-ACME", "SYN-0000") is None


def test_no_candidates_returns_empty(monkeypatch: pytest.MonkeyPatch):
    _patch_ledger(monkeypatch, [])
    assert tuple(LedgerLookup(_CONN).find_candidates("0" * 64)) == ()


# --- The adapter passes through, it does not decide ---------------------------------------------


def test_lookup_identifier_unwraps_the_binding_to_a_bare_person_key(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[object, str, str]] = []

    def fake_lookup_identifier(conn: object, *, system: str, value: str) -> IdentifierBinding:
        calls.append((conn, system, value))
        return IdentifierBinding(
            system=system,
            value=value,
            person_key="tide-000000000000000a",
            actor_type="system",
            actor_id="identity-resolver",
            attached_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
        )

    monkeypatch.setattr(ledger_identity, "lookup_identifier", fake_lookup_identifier)
    result = LedgerLookup(_CONN).lookup_identifier("MRN-ACME", "SYN-1234")

    assert result == "tide-000000000000000a"
    assert calls == [(_CONN, "MRN-ACME", "SYN-1234")]


def test_find_candidates_forwards_the_connection_and_key_unchanged(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[object, str]] = []

    def fake_find_candidates(conn: object, match_key: str) -> list[str]:
        calls.append((conn, match_key))
        return ["tide-000000000000000a", "tide-000000000000000b"]

    monkeypatch.setattr(ledger_identity, "find_candidates", fake_find_candidates)
    result = LedgerLookup(_CONN).find_candidates("f" * 64)

    assert list(result) == ["tide-000000000000000a", "tide-000000000000000b"]
    assert calls == [(_CONN, "f" * 64)]


# --- Only the digest ever reaches the ledger for the composite tier -----------------------------


def test_find_candidates_receives_only_the_digest_never_a_readable_composite(monkeypatch: pytest.MonkeyPatch):
    """Direct call: whatever string is handed to `find_candidates` passes straight through."""
    calls: list[str] = []

    def fake_find_candidates(conn: object, match_key: str) -> list[str]:
        calls.append(match_key)
        return []

    monkeypatch.setattr(ledger_identity, "find_candidates", fake_find_candidates)
    LedgerLookup(_CONN).find_candidates("a" * 64)

    assert calls == ["a" * 64]


def test_full_resolution_transmits_only_the_digest_for_the_composite_tier(monkeypatch: pytest.MonkeyPatch):
    """End to end through `resolve`: the matcher hashes before it ever calls `find_candidates`."""
    case = CASES["composite_unique_hit"]
    candidate_calls: list[str] = []
    identifier_calls: list[tuple[str, str]] = []
    fake = _patch_ledger(monkeypatch, persons_of(case))

    def recording_find_candidates(conn: object, match_key: str) -> list[str]:
        candidate_calls.append(match_key)
        return fake.find_candidates(conn, match_key)

    def recording_lookup_identifier(conn: object, *, system: str, value: str) -> IdentifierBinding | None:
        identifier_calls.append((system, value))
        return fake.lookup_identifier(conn, system=system, value=value)

    monkeypatch.setattr(ledger_identity, "find_candidates", recording_find_candidates)
    monkeypatch.setattr(ledger_identity, "lookup_identifier", recording_lookup_identifier)

    resolve(referral_of(case), LedgerLookup(_CONN))

    (match_key,) = candidate_calls
    assert len(match_key) == 64
    assert all(character in "0123456789abcdef" for character in match_key)
    for value in leakable_values(case["referral"]["demographics"]):
        assert value.casefold() not in match_key
    # The referral in this case carries no identifiers, so the identifier tier makes no call —
    # it is the composite tier's digest, and only that, that reaches the ledger here.
    assert identifier_calls == []
