"""`identity.resolver.quarantine` — `Ambiguous` holds the referral, it never resolves (task 4.2).

Covers the spec's quarantine scenarios: a two-candidate ambiguity commits a `resolution_hold` fact
carrying no `to_state` (so `commit_declaration` skips the state re-fold — the referral is left in
`received`) and enqueues the two pseudonymous person keys with no demographic field; a subject is
pending at most once, so reprocessing an already-quarantined referral does not double-enqueue.

`pulse_ledger.idempotency.commit_idempotent` and `pulse_ledger.review.quarantine_subject` are the
two effects (design decision 6) — faked at the module boundary the same way `test_lookup.py` fakes
`pulse_ledger.identity`, so this suite never opens a real connection (`conftest.py` blocks sockets).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pulse_ledger.idempotency as ledger_idempotency
import pulse_ledger.review as ledger_review
import pytest
from identity.matcher import Ambiguous, Evidence, Match
from identity.resolver import HOLD_EVENT_TYPE, QuarantineOutcome, quarantine
from pulse_ledger.commit import CommitResult, Declaration

EFFECTIVE_AT = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
EVENT_ID = "018f3c2a-7b6e-7c4d-9a1b-2f3e4d5c6b7a"

CANDIDATES = ("tide-000000000000000a", "tide-000000000000000b")


def evidence(rule_id: str = "composite_ambiguous", candidate_count: int = 2) -> Evidence:
    return Evidence(
        matched_fields=("last_name", "dob", "sex", "first_initial"), rule_id=rule_id, candidate_count=candidate_count
    )


def ambiguous(candidates: tuple[str, ...] = CANDIDATES) -> Ambiguous:
    return Ambiguous(candidates=candidates, evidence=evidence(candidate_count=len(candidates)))


class RecordingLedger:
    """Fakes the two effects quarantine declares, recording every call it received.

    `commit_idempotent` answers with a fresh event on the first call for a given key and replays
    the same event for a repeat — the same contract the real ledger function documents — so a test
    can drive redelivery without a database.
    """

    def __init__(self) -> None:
        self.declarations: list[Declaration] = []
        self.idempotency_keys: list[str] = []
        self.quarantine_calls: list[dict[str, object]] = []
        self._claimed: dict[str, uuid.UUID] = {}
        self._pending: dict[tuple[str, str], uuid.UUID] = {}

    def commit_idempotent(self, conn: object, declaration: Declaration, *, idempotency_key: str) -> CommitResult:
        self.declarations.append(declaration)
        self.idempotency_keys.append(idempotency_key)
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
        hold_event_id: uuid.UUID,
        candidates: tuple[str, ...] = (),
    ) -> ledger_review.ReviewItem:
        self.quarantine_calls.append({
            "subject_type": subject_type,
            "subject_key": subject_key,
            "hold_event_id": hold_event_id,
            "candidates": candidates,
        })
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


def _patch_ledger(monkeypatch: pytest.MonkeyPatch) -> RecordingLedger:
    fake = RecordingLedger()
    monkeypatch.setattr(ledger_idempotency, "commit_idempotent", fake.commit_idempotent)
    monkeypatch.setattr(ledger_review, "quarantine_subject", fake.quarantine_subject)
    return fake


def quarantine_over(
    decision: Ambiguous,
    fake: RecordingLedger,
    *,
    referral_key: str = "referral-0001",
    event_id: str = EVENT_ID,
) -> QuarantineOutcome:
    return quarantine(
        decision,
        referral_key=referral_key,
        triggering_event_id=event_id,
        effective_at=EFFECTIVE_AT,
        conn=object(),  # type: ignore[arg-type]  # never inspected — both effects are faked
    )


# --- The spec scenario: two-candidate ambiguity holds and enqueues exactly the candidates -------


def test_two_candidate_ambiguity_holds_the_referral_and_enqueues_both_keys(monkeypatch: pytest.MonkeyPatch):
    fake = _patch_ledger(monkeypatch)
    decision = ambiguous()

    outcome = quarantine_over(decision, fake)

    (declaration,) = fake.declarations
    assert declaration.subject_type == "referral"
    assert declaration.subject_key == "referral-0001"
    assert declaration.event_type == HOLD_EVENT_TYPE
    assert declaration.to_state is None  # no transition, no state re-fold — `received` stands
    assert declaration.evidence == {
        "matched_fields": ["last_name", "dob", "sex", "first_initial"],
        "rule_id": "composite_ambiguous",
        "candidate_count": 2,
        "idempotency_key": fake.idempotency_keys[0],
    }

    (call,) = fake.quarantine_calls
    assert call["subject_type"] == "referral"
    assert call["subject_key"] == "referral-0001"
    assert call["candidates"] == CANDIDATES
    assert call["hold_event_id"] == outcome.hold_event_id

    assert outcome.referral_key == "referral-0001"
    assert outcome.candidates == CANDIDATES


# --- Re-delivery: the subject is pending at most once --------------------------------------------


def test_reprocessing_a_pending_referral_does_not_double_enqueue(monkeypatch: pytest.MonkeyPatch):
    fake = _patch_ledger(monkeypatch)
    decision = ambiguous()

    first = quarantine_over(decision, fake)
    second = quarantine_over(decision, fake)

    assert len(fake.quarantine_calls) == 2  # both attempts run — the second is the one refused
    assert second.review_id == first.review_id
    assert second.hold_event_id == first.hold_event_id
    # The hold fact itself replayed rather than committing a second event.
    assert fake.idempotency_keys[0] == fake.idempotency_keys[1]


def test_redelivery_derives_the_identical_hold_idempotency_key(monkeypatch: pytest.MonkeyPatch):
    fake = _patch_ledger(monkeypatch)
    decision = ambiguous()

    quarantine_over(decision, fake, event_id="event-one")
    quarantine_over(decision, fake, event_id="event-one")

    assert fake.idempotency_keys[0] == fake.idempotency_keys[1]


def test_a_different_triggering_event_derives_a_different_hold_key(monkeypatch: pytest.MonkeyPatch):
    fake = _patch_ledger(monkeypatch)
    decision = ambiguous()

    quarantine_over(decision, fake, referral_key="referral-a", event_id="event-one")
    quarantine_over(decision, fake, referral_key="referral-b", event_id="event-two")

    assert fake.idempotency_keys[0] != fake.idempotency_keys[1]


# --- Only Ambiguous decisions quarantine; act() resolves Match/Mint ------------------------------


def test_quarantine_rejects_non_ambiguous_decisions(monkeypatch: pytest.MonkeyPatch):
    fake = _patch_ledger(monkeypatch)
    decision = Match(person_id="tide-000000000000000a", evidence=evidence(rule_id="composite_unique"))

    with pytest.raises(TypeError, match="Ambiguous"):
        quarantine_over(decision, fake)  # type: ignore[arg-type]

    assert fake.declarations == []
    assert fake.quarantine_calls == []
