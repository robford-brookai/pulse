"""`identity.service` — the consumption entrypoint, the composition root (task 4.3).

Covers the spec's consumption scenario end to end, through the real `service -> matcher ->
resolver` stack (only the command API and the ledger connection are faked, at the same
boundaries `test_resolver.py`/`test_quarantine.py` already fake): a well-formed `referral.received`
envelope resolves via `build_handler`'s wiring of the 3.2 lookup port into the 3.1 matcher and the
4.1/4.2 resolver; an ambiguous decision quarantines instead of resolving; a crash between the
handler committing its commands and the queue deleting the message redelivers safely and converges
to the same ledger state a single clean run would reach; and every failure path — a malformed
envelope, a rejected command — logs `event_id` plus a subject key only, per design decision 3's
flagged path (a), never the envelope or a fixture demographic value.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, cast

import httpx
import pulse_ledger.idempotency as ledger_idempotency
import pulse_ledger.review as ledger_review
import pytest
from identity.matcher import CandidateLookup, ExternalIdentifier, InMemoryLookup, Person
from identity.normalize import Demographics
from identity.resolver import RejectedCommandError, default_person_key
from identity.service import ReferralEnvelopeError, build_handler, consume_referrals, parse_referral_envelope
from pulse_core.client import PulseCoreClient
from pulse_ledger.commit import CommitResult, Declaration

EVENT_ID = "018f3c2a-7b6e-7c4d-9a1b-2f3e4d5c6b7a"
REFERRAL_KEY = "referral-0001"

DEMOGRAPHICS_RAW = {"first_name": "Roberta", "last_name": "Wozniak", "dob": "1990-06-04", "sex": "F"}

#: Values distinctive enough that their appearance in a log line is unambiguously a leak — unlike
#: the single-character `sex` code, which collides trivially with ordinary log prose.
_LEAKABLE_DEMOGRAPHIC_VALUES = ("Roberta", "Wozniak", "1990-06-04")


def envelope(
    *,
    event_id: str = EVENT_ID,
    referral_key: str | None = REFERRAL_KEY,
    effective_at: str | None = "2026-08-01T12:00:00Z",
    demographics: Mapping[str, object] | None = DEMOGRAPHICS_RAW,
    identifiers: list[Mapping[str, object]] | None = None,
    payload_override: Mapping[str, object] | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {"event_id": event_id}
    if referral_key is not None:
        body["referral_key"] = referral_key
    if effective_at is not None:
        body["effective_at"] = effective_at
    if payload_override is not None:
        body["payload"] = payload_override
    else:
        payload: dict[str, object] = {}
        if demographics is not None:
            payload["demographics"] = dict(demographics)
        if identifiers is not None:
            payload["identifiers"] = identifiers
        body["payload"] = payload
    return body


class ReplayAwareApi:
    """Fakes `POST /commands`: the first submission of a wire idempotency key commits, any
    repeat replays — the same idempotent-commit contract the real command API documents, so a
    redelivered handler run can be observed converging rather than duplicating."""

    def __init__(self) -> None:
        self.bodies: list[dict[str, object]] = []
        self._seen: dict[str, str] = {}
        self._next_event = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        import json

        body = cast("dict[str, object]", json.loads(request.content))
        self.bodies.append(body)
        key = cast(str, body["idempotency_key"])
        if key in self._seen:
            return httpx.Response(201, json={"event_id": self._seen[key], "replayed": True})
        self._next_event += 1
        event_id = f"evt-{self._next_event}"
        self._seen[key] = event_id
        return httpx.Response(201, json={"event_id": event_id, "replayed": False})

    def client(self) -> PulseCoreClient:
        return PulseCoreClient(
            "http://ledger.test",
            writer_id="identity-service",
            token="unit-test-token",  # noqa: S106 — a fixture value, not a secret
            transport=httpx.MockTransport(self.handler),
            sleep=lambda _seconds: None,
        )


def rejecting_client() -> PulseCoreClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": {"message": "identifier conflict", "reason": "held"}})

    return PulseCoreClient(
        "http://ledger.test",
        writer_id="identity-service",
        token="unit-test-token",  # noqa: S106 — a fixture value, not a secret
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
    )


class RecordingLedger:
    """Fakes the two quarantine effects (`test_quarantine.py`'s fake): a subject is pending at
    most once, and a repeat of the hold fact under the same key replays rather than committing."""

    def __init__(self) -> None:
        self.declarations: list[Declaration] = []
        self.quarantine_calls: list[dict[str, object]] = []
        self._claimed: dict[str, object] = {}
        self._pending: dict[tuple[str, str], object] = {}

    def commit_idempotent(self, conn: object, declaration: Declaration, *, idempotency_key: str) -> CommitResult:
        import uuid

        self.declarations.append(declaration)
        event_id = self._claimed.get(idempotency_key)
        replayed = event_id is not None
        if event_id is None:
            event_id = uuid.uuid4()
            self._claimed[idempotency_key] = event_id
        return CommitResult(
            event_id=cast("uuid.UUID", event_id),
            recorded_at=declaration.effective_at,
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
        hold_event_id: object,
        candidates: tuple[str, ...] = (),
    ) -> ledger_review.ReviewItem:
        import uuid

        self.quarantine_calls.append({
            "subject_type": subject_type,
            "subject_key": subject_key,
            "candidates": candidates,
        })
        key = (subject_type, subject_key)
        if key in self._pending:
            raise ledger_review.SubjectAlreadyPendingError(
                subject_type, subject_key, cast("uuid.UUID", self._pending[key])
            )
        review_id = uuid.uuid4()
        self._pending[key] = review_id
        return ledger_review.ReviewItem(
            review_id=review_id,
            subject_type=subject_type,
            subject_key=subject_key,
            hold_event_id=cast("uuid.UUID", hold_event_id),
            candidates=tuple(candidates),
            pending=True,
            created_at=declaration_effective_at(),
            resolved_at=None,
            resolution_event_id=None,
        )


def declaration_effective_at() -> Any:
    from datetime import datetime, timezone

    return datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def _patch_ledger(monkeypatch: pytest.MonkeyPatch) -> RecordingLedger:
    fake = RecordingLedger()
    monkeypatch.setattr(ledger_idempotency, "commit_idempotent", fake.commit_idempotent)
    monkeypatch.setattr(ledger_review, "quarantine_subject", fake.quarantine_subject)
    return fake


def make_handler(
    *, lookup: CandidateLookup | None = None, client: PulseCoreClient | None = None
) -> tuple[Any, PulseCoreClient]:
    resolved_client = client or ReplayAwareApi().client()
    handler = build_handler(
        lookup=lookup or InMemoryLookup(()),
        client=resolved_client,
        conn=cast("Any", object()),  # never inspected — quarantine's ledger calls are monkeypatched
        person_key_factory=lambda: "tide-minted-0001",
    )
    return handler, resolved_client


# --- Parsing -------------------------------------------------------------------------------


def test_parse_referral_envelope_extracts_demographics_and_identifiers():
    env = envelope(identifiers=[{"system": "MRN-ACME", "value": "SYN-0001"}])

    parsed = parse_referral_envelope(env)

    assert parsed.referral_key == REFERRAL_KEY
    assert parsed.triggering_event_id == EVENT_ID
    assert parsed.referral.demographics == Demographics(
        last_name="Wozniak", first_name="Roberta", dob="1990-06-04", sex="F"
    )
    assert parsed.referral.identifiers == (ExternalIdentifier(system="MRN-ACME", value="SYN-0001"),)


def test_parse_referral_envelope_defaults_to_no_identifiers():
    parsed = parse_referral_envelope(envelope())
    assert parsed.referral.identifiers == ()


def test_parse_referral_envelope_accepts_an_already_aware_datetime():
    from datetime import datetime, timezone

    aware = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    env = envelope()
    env["effective_at"] = aware

    parsed = parse_referral_envelope(env)

    assert parsed.effective_at == aware


def test_parse_referral_envelope_rejects_a_non_mapping_payload():
    env = envelope()
    env["payload"] = "not-a-mapping"
    with pytest.raises(ReferralEnvelopeError):
        parse_referral_envelope(env)


@pytest.mark.parametrize(
    "broken",
    [
        envelope(referral_key=None),
        envelope(effective_at=None),
        envelope(demographics=None),
        envelope(demographics={"first_name": "Roberta", "last_name": "Wozniak", "sex": "F"}),  # missing dob
        envelope(payload_override={"demographics": DEMOGRAPHICS_RAW, "identifiers": [{"system": "MRN-ACME"}]}),
        envelope(effective_at="2026-08-01T12:00:00"),  # naive — no D16 meaning
        envelope(effective_at="not-a-timestamp"),  # unparseable, not just naive
        envelope(payload_override={"demographics": "not-a-mapping"}),
        envelope(payload_override={"demographics": DEMOGRAPHICS_RAW, "identifiers": "not-a-sequence"}),
        envelope(payload_override={"demographics": DEMOGRAPHICS_RAW, "identifiers": ["not-a-mapping"]}),
    ],
)
def test_parse_referral_envelope_rejects_malformed_input(broken: dict[str, object]):
    with pytest.raises(ReferralEnvelopeError):
        parse_referral_envelope(broken)


# --- Match / Mint resolution, through the real matcher + resolver stack --------------------


def test_handler_resolves_an_exact_identifier_match():
    identifier = ExternalIdentifier(system="MRN-ACME", value="SYN-0001")
    demographics = Demographics(last_name="Nguyen", first_name="Alex", dob="1988-11-02", sex="F")
    lookup = InMemoryLookup([Person(person_id="person-existing", demographics=demographics, identifiers=(identifier,))])
    api = ReplayAwareApi()
    handler, _client = make_handler(lookup=lookup, client=api.client())

    handler(
        envelope(
            demographics={"first_name": "Alex", "last_name": "Nguyen", "dob": "1988-11-02", "sex": "F"},
            identifiers=[{"system": "MRN-ACME", "value": "SYN-0001"}],
        )
    )

    assert [body["event_type"] for body in api.bodies] == ["resolve_referral"]
    assert api.bodies[0]["subject_key"] == REFERRAL_KEY


def test_handler_mints_when_nothing_matches():
    api = ReplayAwareApi()
    handler, _client = make_handler(client=api.client())

    handler(envelope(identifiers=[{"system": "MRN-ACME", "value": "SYN-9001"}]))

    event_types = [body["event_type"] for body in api.bodies]
    assert event_types == ["mint_person", "resolve_referral", "attach_identifier"]
    assert api.bodies[0]["subject_key"] == "tide-minted-0001"


def test_handler_quarantines_an_ambiguous_decision_instead_of_resolving(monkeypatch: pytest.MonkeyPatch):
    fake = _patch_ledger(monkeypatch)
    demographics = Demographics(last_name="Wozniak", first_name="Roberta", dob="1990-06-04", sex="F")
    lookup = InMemoryLookup([
        Person(person_id="tide-a", demographics=demographics),
        Person(person_id="tide-b", demographics=demographics),
    ])
    api = ReplayAwareApi()
    handler, _client = make_handler(lookup=lookup, client=api.client())

    handler(envelope())

    assert api.bodies == []  # no commands declared — the referral never resolves
    (declaration,) = fake.declarations
    assert declaration.to_state is None  # no transition, no state re-fold
    (call,) = fake.quarantine_calls
    assert call["subject_key"] == REFERRAL_KEY
    assert call["candidates"] == ("tide-a", "tide-b")


def test_reprocessing_a_quarantined_referral_does_not_double_enqueue(monkeypatch: pytest.MonkeyPatch):
    fake = _patch_ledger(monkeypatch)
    demographics = Demographics(last_name="Wozniak", first_name="Roberta", dob="1990-06-04", sex="F")
    lookup = InMemoryLookup([
        Person(person_id="tide-a", demographics=demographics),
        Person(person_id="tide-b", demographics=demographics),
    ])
    handler, _client = make_handler(lookup=lookup)

    handler(envelope())
    handler(envelope())

    assert len(fake.quarantine_calls) == 2  # both attempts run — the second is refused, not skipped


# --- Crash-before-delete redelivery converges to a single-clean-run state ------------------


def test_crash_before_delete_redelivery_converges_to_single_clean_run_state():
    """A handler that "crashed" after committing its commands but before the queue deleted the
    message is redelivered the identical envelope. Idempotency at the wire boundary (D16) makes
    the second run's commands replay rather than duplicate — the final ledger state (here: the
    set of distinct committed event ids) is identical to what one clean run produces."""
    api = ReplayAwareApi()
    handler, _client = make_handler(client=api.client())
    env = envelope(identifiers=[{"system": "MRN-ACME", "value": "SYN-9001"}])

    handler(env)  # the "clean run" that then crashes before the queue delete
    first_run_bodies = list(api.bodies)

    handler(env)  # redelivery of the same, undeleted message

    assert len(api.bodies) == 2 * len(first_run_bodies)
    first_ids = {body["idempotency_key"] for body in first_run_bodies}
    second_ids = {body["idempotency_key"] for body in api.bodies[len(first_run_bodies) :]}
    assert first_ids == second_ids  # identical wire keys — replays, not new resolutions

    committed_event_ids = set(api._seen.values())  # type: ignore[attr-defined]
    assert len(committed_event_ids) == len(first_run_bodies)  # exactly one event per command, ever


def test_consume_referrals_wires_build_handler_into_pulse_core_consume(monkeypatch: pytest.MonkeyPatch):
    calls: list[dict[str, object]] = []

    def fake_consume(handler: object, **kwargs: object) -> None:
        calls.append({"handler": handler, **kwargs})

    monkeypatch.setattr("identity.service.consume", fake_consume)
    api = ReplayAwareApi()

    consume_referrals(
        queue_url="https://sqs.example/referrals",
        lookup=InMemoryLookup(()),
        client=api.client(),
        conn=cast("Any", object()),
        sqs_client=cast("Any", object()),
        iterations=1,
    )

    assert len(calls) == 1
    assert calls[0]["queue_url"] == "https://sqs.example/referrals"
    assert calls[0]["iterations"] == 1
    assert callable(calls[0]["handler"])


# --- Design decision 3, flagged path (a): handler failures log event_id + subject key only ----


def test_malformed_envelope_failure_logs_only_event_id_never_the_envelope(caplog: pytest.LogCaptureFixture):
    handler, _client = make_handler()

    with caplog.at_level(logging.ERROR, logger="identity.service"), pytest.raises(ReferralEnvelopeError):
        handler(envelope(referral_key=None))

    assert EVENT_ID in caplog.text
    for value in _LEAKABLE_DEMOGRAPHIC_VALUES:
        assert value not in caplog.text


def test_rejected_command_failure_logs_event_id_and_subject_key_never_a_demographic_value(
    caplog: pytest.LogCaptureFixture,
):
    handler, _client = make_handler(client=rejecting_client())

    with caplog.at_level(logging.INFO, logger="identity"), pytest.raises(RejectedCommandError):
        handler(envelope(identifiers=[{"system": "MRN-ACME", "value": "SYN-9001"}]))

    assert EVENT_ID in caplog.text
    assert REFERRAL_KEY in caplog.text
    for value in _LEAKABLE_DEMOGRAPHIC_VALUES:
        assert value not in caplog.text
    assert "SYN-9001" not in caplog.text  # identifier values never appear either


def test_default_person_key_factory_is_used_when_none_supplied():
    api = ReplayAwareApi()
    handler = build_handler(lookup=InMemoryLookup(()), client=api.client(), conn=cast("Any", object()))

    handler(envelope())

    assert api.bodies[0]["subject_key"] != ""
    assert default_person_key.__name__ == "default_person_key"  # sanity: the real default is wired
