"""The property test (task 5.1): resolution of any fixture set is order-independent and re-run-
identical, driven through the library entrypoint directly — `identity.matcher.resolve` plus
`identity.resolver.act`/`quarantine` — no queue, no `identity.service` process in the loop.

This is what proves the genesis batch-invocation contract: genesis calls `resolve()` (and then
`act()`/`quarantine()`) as a plain function import across a batch of referrals, never through
`pulse_core.client.consume`, and must land on the exact same typed decisions and the exact same
idempotent commands the service path (task 4.3) produces one referral at a time. If this module
ever needs a queue or an `httpx` transport wired to a live service, the property it proves is gone.

Two properties, over every fixture in `tests/fixtures/` that carries a `decision` kind (task 2.2):

- **Order-independence**: shuffling a referral's identifiers, or the order existing persons were
  loaded into the lookup store, never changes the decision. `test_matcher.py` already checks this
  per-case with a couple of hand-picked orderings; this file checks it exhaustively — every
  permutation, for every case — because "any fixture set" is the spec's word, not "some".
- **Re-run-identical**: resolving the same case twice yields `==` decisions, and carrying a
  decision through to commands twice (the same referral key, the same triggering event) is
  idempotent — the second run's commands replay rather than committing again, at whichever
  effectful boundary the decision's kind reaches (`act()` for `Match`/`Mint`, `quarantine()` for
  `Ambiguous`).
"""

from __future__ import annotations

import itertools
import json
import uuid
from datetime import datetime, timezone
from typing import Any, cast

import httpx
import pulse_ledger.idempotency as ledger_idempotency
import pulse_ledger.review as ledger_review
import pytest
from fixtures.loader import load_all_cases
from identity.matcher import (
    Ambiguous,
    Decision,
    ExternalIdentifier,
    InMemoryLookup,
    Match,
    Mint,
    Person,
    Referral,
    resolve,
)
from identity.normalize import Demographics
from identity.resolver import act as resolver_act
from identity.resolver import quarantine
from pulse_core.client import PulseCoreClient, ResponseClassification
from pulse_ledger.commit import CommitResult, Declaration

EFFECTIVE_AT = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)

CASES = load_all_cases()

#: Every fixture of `kind: decision` — the ones a full resolve-then-act/quarantine pipeline
#: applies to. `ambiguous_dob_format` (`kind: ambiguous_dob`) and `suffix_casing_pairs`
#: (`kind: normalization_pairs`) are excluded: they exercise `normalize.py` directly, not a
#: decision, and 3.1/3.2's own suites already cover them.
DECISION_CASE_NAMES = tuple(sorted(name for name, case in CASES.items() if case["kind"] == "decision"))


def demographics(raw: dict[str, Any]) -> Demographics:
    return Demographics(last_name=raw["last_name"], first_name=raw["first_name"], dob=raw["dob"], sex=raw["sex"])


def identifiers(raw: list[dict[str, str]]) -> tuple[ExternalIdentifier, ...]:
    return tuple(ExternalIdentifier(system=entry["system"], value=entry["value"]) for entry in raw)


def referral_of(case: dict[str, Any], *, identifier_order: tuple[ExternalIdentifier, ...] | None = None) -> Referral:
    raw = case["referral"]
    ordered = identifier_order if identifier_order is not None else identifiers(raw["identifiers"])
    return Referral(demographics=demographics(raw["demographics"]), identifiers=ordered)


def persons_of(case: dict[str, Any]) -> tuple[Person, ...]:
    return tuple(
        Person(
            person_id=person["person_id"],
            demographics=demographics(person["demographics"]),
            identifiers=identifiers(person["identifiers"]),
        )
        for person in case["existing_persons"]
    )


def lookup_of(case: dict[str, Any], *, person_order: tuple[Person, ...] | None = None) -> InMemoryLookup:
    return InMemoryLookup(person_order if person_order is not None else persons_of(case))


# --- Property 1: order-independence — every permutation, every decision case -------------------


@pytest.mark.parametrize("name", DECISION_CASE_NAMES)
def test_referral_identifier_order_never_changes_the_decision(name: str):
    case = CASES[name]
    baseline = resolve(referral_of(case), lookup_of(case))
    raw_identifiers = identifiers(case["referral"]["identifiers"])
    for ordering in itertools.permutations(raw_identifiers):
        decision = resolve(referral_of(case, identifier_order=ordering), lookup_of(case))
        assert decision == baseline, f"{name}: identifier order {ordering} changed the decision"


@pytest.mark.parametrize("name", DECISION_CASE_NAMES)
def test_existing_person_load_order_never_changes_the_decision(name: str):
    case = CASES[name]
    baseline = resolve(referral_of(case), lookup_of(case))
    persons = persons_of(case)
    for ordering in itertools.permutations(persons):
        decision = resolve(referral_of(case), lookup_of(case, person_order=ordering))
        assert decision == baseline, f"{name}: existing-person load order {ordering} changed the decision"


# --- Property 2: re-run-identical — resolving twice yields an equal decision --------------------


@pytest.mark.parametrize("name", DECISION_CASE_NAMES)
def test_resolution_is_re_run_identical_for_every_case(name: str):
    case = CASES[name]
    first = resolve(referral_of(case), lookup_of(case))
    second = resolve(referral_of(case), lookup_of(case))
    assert first == second
    assert first.evidence == second.evidence


# --- Property 3: idempotent commands on replay, at whichever boundary the decision reaches ------
#
# `Match`/`Mint` reach `act()` (a `PulseCoreClient` faked at the `httpx` transport, same posture as
# `test_resolver.py`); `Ambiguous` reaches `quarantine()` (`pulse_ledger` faked at the module
# boundary, same posture as `test_quarantine.py`). Both fakes answer "already happened" on a
# repeat, exactly as their real counterparts do under D16 — proving replay is a no-op regardless of
# which effectful boundary a case's decision kind lands on.


class ScriptedApi:
    """A command API that answers `committed` once per distinct request body, `replayed` after.

    Unlike `test_resolver.py`'s `ScriptedApi` (a fixed response script), this one keys off the
    request's own `idempotency_key` — the property under test is "the same logical resolution,
    submitted twice, replays," and the wire key is what a real ledger would key its own replay
    detection on.
    """

    def __init__(self) -> None:
        self.bodies: list[dict[str, object]] = []
        self._seen: set[str] = set()

    def handler(self, request: httpx.Request) -> httpx.Response:
        parsed = cast("dict[str, object]", json.loads(request.content))
        self.bodies.append(parsed)
        key = cast(str, parsed["idempotency_key"])
        event_id = f"event-{key[:16]}"
        first_time = key not in self._seen
        self._seen.add(key)
        return httpx.Response(201, json={"event_id": event_id, "replayed": not first_time})

    def client(self) -> PulseCoreClient:
        return PulseCoreClient(
            "http://ledger.test",
            writer_id="identity-service",
            token="unit-test-token",  # noqa: S106 — a fixture value, not a secret
            transport=httpx.MockTransport(self.handler),
            max_attempts=1,
            sleep=lambda _seconds: None,
        )


def _minted_person_key(name: str) -> str:
    return f"tide-{name}-minted"


def _act_pipeline(case: dict[str, Any], decision: Decision, *, api: ScriptedApi, name: str):
    return resolver_act(
        decision,
        referral_of(case),
        referral_key=f"referral-{name}",
        triggering_event_id=f"event-{name}",
        effective_at=EFFECTIVE_AT,
        lookup=lookup_of(case),
        client=api.client(),
        person_key_factory=lambda: _minted_person_key(name),
    )


@pytest.mark.parametrize("name", [n for n in DECISION_CASE_NAMES if CASES[n]["expected_decision"] in ("match", "mint")])
def test_match_and_mint_decisions_replay_idempotently_through_act(name: str):
    case = CASES[name]
    decision = resolve(referral_of(case), lookup_of(case))
    assert isinstance(decision, Match | Mint)

    api = ScriptedApi()
    first = _act_pipeline(case, decision, api=api, name=name)
    second = _act_pipeline(case, decision, api=api, name=name)

    assert [c.command_type for c in first.commands] == [c.command_type for c in second.commands]
    assert [c.idempotency_key for c in first.commands] == [c.idempotency_key for c in second.commands]
    assert first.person_key == second.person_key
    assert all(c.classification is ResponseClassification.COMMITTED for c in first.commands)
    assert all(c.classification is ResponseClassification.REPLAYED for c in second.commands)


class RecordingLedger:
    """Fakes `commit_idempotent` / `quarantine_subject`, replaying on a repeated idempotency key.

    Same contract `test_quarantine.py`'s fake documents: a key seen before answers with the event
    it already claimed, and a subject already pending answers via `SubjectAlreadyPendingError`
    rather than a second row.
    """

    def __init__(self) -> None:
        self._claimed: dict[str, Any] = {}
        self._pending: dict[tuple[str, str], Any] = {}

    def commit_idempotent(self, conn: object, declaration: Declaration, *, idempotency_key: str) -> CommitResult:
        event_id = self._claimed.get(idempotency_key)
        replayed = event_id is not None
        if event_id is None:
            event_id = uuid.uuid4()
            self._claimed[idempotency_key] = event_id
        return CommitResult(
            event_id=event_id,
            recorded_at=EFFECTIVE_AT,
            rule_version="appendix-c-v0.7",
            outbox_seq=1,
            state=None,
            replayed=replayed,
        )

    def quarantine_subject(
        self,
        conn: object,
        *,
        subject_type: str,
        subject_key: str,
        hold_event_id: Any,
        candidates: tuple[str, ...] = (),
    ) -> ledger_review.ReviewItem:
        key = (subject_type, subject_key)
        if key in self._pending:
            raise ledger_review.SubjectAlreadyPendingError(subject_type, subject_key, self._pending[key])
        review_id = uuid.uuid4()
        self._pending[key] = review_id
        return ledger_review.ReviewItem(
            review_id=review_id,
            subject_type=subject_type,
            subject_key=subject_key,
            hold_event_id=hold_event_id,
            candidates=tuple(candidates),
            pending=True,
            created_at=EFFECTIVE_AT,
            resolved_at=None,
            resolution_event_id=None,
        )


@pytest.mark.parametrize("name", [n for n in DECISION_CASE_NAMES if CASES[n]["expected_decision"] == "ambiguous"])
def test_ambiguous_decisions_replay_idempotently_through_quarantine(name: str, monkeypatch: pytest.MonkeyPatch):
    case = CASES[name]
    decision = resolve(referral_of(case), lookup_of(case))
    assert isinstance(decision, Ambiguous)

    fake = RecordingLedger()
    monkeypatch.setattr(ledger_idempotency, "commit_idempotent", fake.commit_idempotent)
    monkeypatch.setattr(ledger_review, "quarantine_subject", fake.quarantine_subject)

    def quarantine_over() -> Any:
        return quarantine(
            decision,
            referral_key=f"referral-{name}",
            triggering_event_id=f"event-{name}",
            effective_at=EFFECTIVE_AT,
            conn=object(),  # type: ignore[arg-type]  # never inspected — both effects are faked
        )

    first = quarantine_over()
    second = quarantine_over()

    assert second.review_id == first.review_id
    assert second.hold_event_id == first.hold_event_id
    assert second.candidates == first.candidates


# --- The genesis contract itself: `resolve`/`act`/`quarantine` are plain function imports --------
#
# Structural, not a `sys.modules` check: another test module in the same session legitimately
# imports `identity.service` (task 4.3's own suite), so a module-presence assertion here would be
# false the moment this file runs alongside it, not because the property is false. The actual
# proof is this file's own import list (top of file) — every entrypoint used above is
# `identity.matcher.resolve` or `identity.resolver.act`/`quarantine`, called as ordinary function
# imports against an in-process lookup and fakes, with no `identity.service`, no `pulse_core.client
# .consume`, and no queue anywhere in this module.


@pytest.mark.parametrize("name", DECISION_CASE_NAMES)
def test_every_decision_case_resolves_to_its_expected_typed_decision(name: str):
    """The full library entrypoint, exercised once per case: the same typed decision every time."""
    case = CASES[name]
    decision = resolve(referral_of(case), lookup_of(case))
    expected_type = {"match": Match, "mint": Mint, "ambiguous": Ambiguous}[case["expected_decision"]]
    assert type(decision) is expected_type
    assert decision.evidence.rule_id == case["expected_rule_id"]
