"""The conflict contract as a producer sees it — SDK, connector kit, webhook, rollout gate.

Task 3.2 of `idempotency-integrity`. Tasks 1.1-3.1 proved the server half: the fingerprint, the
binding, the commit path's refusal and the three ingresses that carry it
(`packages/pulse-ledger/tests/`). What is still unproven is the half this package owns — that a
*deployed producer's existing retries keep working*, which design §5 makes the acceptance
criterion for every rollout stage, and that the ones that would not are found before enforcement
rather than after.

Four things are asserted here, none of them a second copy of a ledger test:

1. **Valid existing retries.** The key the SDK derives is stable across the spellings a retry
   legitimately varies — object-key order, an equivalent UTC spelling — so an exact retry still
   replays, and a connector's receipt counts it `replayed` and never `committed`.
2. **Conflicts reach a producer as `rejected`, never `transient`.** A 409 that a connector's
   retry loop treated as transient would be retried until its budget burned, forever, since a
   key's claim is kept for the ledger's lifetime. The distinct
   `idempotency_legacy_unverifiable` reason survives to the caller with it.
3. **The fields outside the key.** The D16 key covers subject, command type, payload and
   `logical_time`; canonical request v1 covers `to_state`, `evidence` and `evidence_class` as
   well. A producer that varies one of *those* between retries of one fact keeps deriving the
   same key and starts receiving 409 — the population the compatibility inventory exists to
   find. `TestFieldsOutsideTheKey` is that population, in the shape the deployed producers have.
4. **The rollout gate.** `docs/idempotency-compatibility-inventory.md` is machine-checked here:
   every command-submitting credential has a row, and a row at `unknown` or `fix-required` blocks
   enforcement. The attended preflight (task 4.1,
   `docs/runbooks/idempotency-enforcement-rollout.md`) runs this as its first step.

The ledger is faked at the HTTP boundary (`httpx.MockTransport`), per this package's testing
posture — no live network, no database. `_FakeLedger` implements ADR-0007's binding rule
independently of `pulse_ledger`, which pulse-core does not depend on: if the two ever disagree
about what an exact retry is, that disagreement is the finding.

Every fixture value is synthetic. `_SENTINEL` stands in for the one class of value that must never
leave the process — a payload value, PHI once C1 clears — and `TestNothingLeaks` asserts it
appears in no response, no exception and no log line.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from pulse_core.client import (
    CommandResponse,
    PulseCoreClient,
    ResponseClassification,
    classify_response,
)
from pulse_core.connector.declare import DeclareCounts, TransientExhaustedError, submit_with_retry
from pulse_core.generated import DeclareTransitionCommand, DeclareVerdictCommand, VerdictOutcome

REPO_ROOT = Path(__file__).resolve().parents[3]

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

#: The one value in these fixtures that stands for request content. A payload value is PHI once C1
#: clears, so nothing a producer can observe after a conflict may contain it.
_SENTINEL = "SENTINEL-PAYLOAD-VALUE"

IDEMPOTENCY_CONFLICT = "idempotency_conflict"
IDEMPOTENCY_LEGACY_UNVERIFIABLE = "idempotency_legacy_unverifiable"


# --- the ledger's binding rule, faked at the HTTP boundary ---------------------------------


#: Canonical request v1's field map as the *wire body* spells it, mirroring
#: `pulse_ledger.request_fingerprint.CANONICAL_FIELDS_V1`. Deliberately a second statement of the
#: contract rather than an import: pulse-core does not depend on pulse-ledger, and a producer-side
#: test that imported the server's own normaliser could not catch the server changing it.
#: `evidence_bounds` is absent because it is not a field the SDK body carries.
_CANONICAL_FIELDS_V1 = (
    "subject_type",
    "subject_key",
    "event_type",
    "to_state",
    "effective_at",
    "epoch",
    "evidence_class",
    "evidence",
    "payload",
)


def _canonical(value: object) -> object:
    """Normalise what carries no meaning; keep what does (object-key order out, list order in)."""
    if isinstance(value, Mapping):
        return {key: _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical(member) for member in value]
    return value


def _fingerprint(body: Mapping[str, object]) -> str:
    """The accepted request's v1 fingerprint, over the fields the wire body carries."""
    request = {name: _canonical(body.get(name)) for name in _CANONICAL_FIELDS_V1}
    effective_at = request.get("effective_at")
    if isinstance(effective_at, str):
        request["effective_at"] = datetime.fromisoformat(effective_at).astimezone(timezone.utc).isoformat()
    pre_image = json.dumps({"version": "v1", "request": request}, sort_keys=True, separators=(",", ":"))
    return "v1:" + hashlib.sha256(pre_image.encode()).hexdigest()


def _key_of(body: Mapping[str, object]) -> str | None:
    """The body's `idempotency_key`, or `None` for a keyless command."""
    key = body.get("idempotency_key")
    return key if isinstance(key, str) else None


@dataclass(frozen=True)
class _Binding:
    writer: str
    fingerprint: str | None
    event_id: str


class _FakeLedger:
    """ADR-0007's replay rule over an in-memory key store, at `/commands` and `/webhooks/twenty`.

    A key with no recorded fingerprint is a *legacy* key — claimed before the binding table
    existed. It replays only for a retry whose request the stored event proves; the fixtures below
    mark that with `provable`, which is what `pulse_ledger.legacy_binding` decides from the stored
    event's own columns.
    """

    def __init__(self, *, writers: Mapping[str, str] | None = None) -> None:
        self.bindings: dict[str, _Binding] = {}
        self.legacy_provable: dict[str, bool] = {}
        self.events: list[str] = []
        self.posts: list[httpx.Request] = []
        self._writers = dict(writers or {"unit-test-token": "verdict-relay"})

    # -- seeding ---------------------------------------------------------------------------

    def claim_legacy(self, key: str, *, event_id: str, provable: bool) -> None:
        """A key claimed before the amendment: retained, bound to nothing, replayable only if
        the original event proves the whole canonical request."""
        self.bindings[key] = _Binding(writer="", fingerprint=None, event_id=event_id)
        self.legacy_provable[key] = provable
        self.events.append(event_id)

    # -- the boundary ----------------------------------------------------------------------

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.posts.append(request)
        body = json.loads(request.content)
        if request.url.path == "/webhooks/twenty":
            return self._webhook(request, body)
        return self._command(request, body)

    def _writer_of(self, request: httpx.Request) -> str:
        token = request.headers["Authorization"].removeprefix("Bearer ")
        return self._writers[token]

    def _resolve(self, *, key: str | None, writer: str, body: Mapping[str, object]) -> _Binding | str:
        """The replayed binding, or the reason code this claim is refused with."""
        if key is None:
            return self._commit(key=None, writer=writer, body=body)
        held = self.bindings.get(key)
        if held is None:
            return self._commit(key=key, writer=writer, body=body)
        if held.fingerprint is None:
            # Legacy: bind it now if the stored event proves the request, refuse otherwise. Never
            # a guess, and the key keeps its reservation either way.
            if not self.legacy_provable.get(key, False):
                return IDEMPOTENCY_LEGACY_UNVERIFIABLE
            self.bindings[key] = _Binding(writer=writer, fingerprint=_fingerprint(body), event_id=held.event_id)
            return self.bindings[key]
        if held.writer != writer or held.fingerprint != _fingerprint(body):
            return IDEMPOTENCY_CONFLICT
        return held

    def _commit(self, *, key: str | None, writer: str, body: Mapping[str, object]) -> _Binding:
        event_id = f"event-{len(self.events) + 1}"
        self.events.append(event_id)
        binding = _Binding(writer=writer, fingerprint=_fingerprint(body), event_id=event_id)
        if key is not None:
            self.bindings[key] = binding
        return binding

    def _command(self, request: httpx.Request, body: Mapping[str, object]) -> httpx.Response:
        before = len(self.events)
        outcome = self._resolve(key=_key_of(body), writer=self._writer_of(request), body=body)
        if isinstance(outcome, str):
            return httpx.Response(
                409,
                json={"detail": {"message": "idempotency key is claimed by another request", "reason": outcome}},
                request=request,
            )
        committed = len(self.events) > before
        return httpx.Response(
            201 if committed else 200,
            json={
                "event_id": outcome.event_id,
                "recorded_at": T0.isoformat(),
                "replayed": not committed,
            },
            request=request,
        )

    def _webhook(self, request: httpx.Request, body: Mapping[str, object]) -> httpx.Response:
        """Signed Twenty ingress: 200 whatever the verdict.

        A 4xx past this door is a redelivery instruction, not a message anyone reads, so a
        conflict is a `rejected` disposition inside a 200 — the contract task 3.1 wired in
        `pulse_ledger.api` and the one a connector author must not "improve" into a status code.
        """
        outcome = self._resolve(key=_key_of(body), writer=self._writer_of(request), body=body)
        if isinstance(outcome, str):
            return httpx.Response(200, json={"disposition": "rejected", "reason": outcome}, request=request)
        return httpx.Response(
            200,
            json={"disposition": "committed", "event_id": outcome.event_id},
            request=request,
        )


def _client(
    ledger: _FakeLedger,
    *,
    writer_id: str = "verdict-relay",
    token: str = "unit-test-token",  # noqa: S107 — a fixture value, not a secret
    **kwargs,
) -> PulseCoreClient:
    return PulseCoreClient(
        "http://ledger.test",
        writer_id=writer_id,
        token=token,
        transport=httpx.MockTransport(ledger.handler),
        sleep=lambda _seconds: None,
        **kwargs,
    )


def _verdict(*, reason: str | None = None) -> DeclareVerdictCommand:
    return DeclareVerdictCommand(
        subject_key="referral-synthetic-1",
        subject_type="billing_eligibility",
        outcome=VerdictOutcome.POSITIVE,
        reason=reason,
        rule_version="v0.7",
        as_of=T0,
        lineage={"source": "synthetic", "note": _SENTINEL},
    )


# --- 1. valid existing retries -------------------------------------------------------------


class TestValidExistingRetries:
    """The acceptance criterion for every rollout stage: what works today keeps working."""

    def test_an_exact_retry_replays_the_original_event(self) -> None:
        ledger = _FakeLedger()
        with _client(ledger) as client:
            first = client.submit_command(_verdict(), effective_at=T0)
            second = client.submit_command(_verdict(), effective_at=T0)

        assert first.classification is ResponseClassification.COMMITTED
        assert second.classification is ResponseClassification.REPLAYED
        assert second.event_id == first.event_id
        assert len(ledger.events) == 1, "a retry must not produce a second event"
        assert len(ledger.posts) == 2, "the retry is a request, not a client-side cache hit"

    def test_an_equivalent_utc_spelling_is_the_same_retry(self) -> None:
        """`Z`, `+00:00` and a non-UTC offset for one instant derive one key and one fingerprint."""
        ledger = _FakeLedger()
        elsewhere = T0.astimezone(timezone(timedelta(hours=-7)))
        with _client(ledger) as client:
            first = client.submit_command(_verdict(), effective_at=T0)
            second = client.submit_command(_verdict(), effective_at=elsewhere)

        assert second.classification is ResponseClassification.REPLAYED
        assert second.event_id == first.event_id
        assert len(ledger.events) == 1

    def test_payload_object_key_order_is_not_a_new_request(self) -> None:
        """Two processes that built one payload in different orders are one retry, not a conflict."""
        ledger = _FakeLedger()
        forwards = _verdict()
        backwards = DeclareVerdictCommand(**dict(reversed(list(forwards.model_dump().items()))))
        with _client(ledger) as client:
            first = client.submit_command(forwards, effective_at=T0)
            second = client.submit_command(backwards, effective_at=T0)

        assert second.classification is ResponseClassification.REPLAYED
        assert second.event_id == first.event_id

    def test_a_distinct_fact_derives_its_own_key_and_commits(self) -> None:
        """An ordinary content change is a new key, not a conflict — the SDK derives it from
        the content, so no producer collides by declaring something different."""
        ledger = _FakeLedger()
        with _client(ledger) as client:
            first = client.submit_command(_verdict(), effective_at=T0)
            second = client.submit_command(_verdict(reason="re-read on review"), effective_at=T0)

        assert second.classification is ResponseClassification.COMMITTED
        assert second.event_id != first.event_id
        assert len(ledger.events) == 2

    def test_a_rerun_counts_as_replayed_in_a_connector_receipt(self) -> None:
        """`A rerun declares nothing twice` (connector-kit): the second run's receipt is all
        `replayed` — the counted evidence an attended rehearsal reads."""
        ledger = _FakeLedger()
        subjects = ("referral-synthetic-1", "referral-synthetic-2", "referral-synthetic-3")
        with _client(ledger, max_attempts=1) as client:
            for run in range(2):
                counts = DeclareCounts()
                for subject in subjects:
                    command = _verdict().model_copy(update={"subject_key": subject})
                    response = submit_with_retry(
                        lambda command=command: client.submit_command(command, effective_at=T0),
                        ref=subject,
                        sleep=lambda _seconds: None,
                        jitter=lambda: 1.0,
                    )
                    counts = counts.record(response.classification)
                expected = DeclareCounts(committed=3) if run == 0 else DeclareCounts(replayed=3)
                assert counts == expected

        assert len(ledger.events) == 3


# --- 2. conflicts are rejected, never transient --------------------------------------------


class TestConflictsAreRejectedNotTransient:
    def test_a_conflict_classifies_as_rejected_and_is_not_retried(self) -> None:
        ledger = _FakeLedger()
        with _client(ledger) as client:
            client.submit_command(_verdict(), effective_at=T0)
            ledger.posts.clear()
            conflict = client.submit_command(
                _verdict(),
                effective_at=T0,
                evidence={"window": "widened after the first attempt"},
            )

        assert conflict.classification is ResponseClassification.REJECTED
        assert conflict.attempts == 1, "a 409 retried is a 409 retried forever"
        assert len(ledger.posts) == 1
        assert conflict.rejection is not None
        assert conflict.rejection.reason == IDEMPOTENCY_CONFLICT

    def test_a_connector_retry_loop_settles_a_conflict_without_sleeping(self) -> None:
        """`submit_with_retry` must count a conflict `rejected` and return — not burn its budget
        and raise `TransientExhaustedError`, which is what a transient classification would do."""
        ledger = _FakeLedger()
        slept: list[float] = []
        with _client(ledger, max_attempts=1) as client:
            client.submit_command(_verdict(), effective_at=T0)
            response = submit_with_retry(
                lambda: client.submit_command(_verdict(), effective_at=T0, evidence={"window": "widened"}),
                ref="referral-synthetic-1",
                sleep=slept.append,
                jitter=lambda: 1.0,
            )

        assert response.classification is ResponseClassification.REJECTED
        assert slept == []
        assert DeclareCounts().record(response.classification) == DeclareCounts(rejected=1)

    def test_the_legacy_reason_reaches_the_caller_distinctly(self) -> None:
        """`idempotency_legacy_unverifiable` is a different follow-up from a collision — a
        reconciliation path, not a re-derived key — so it must survive classification."""
        ledger = _FakeLedger()
        with _client(ledger) as client:
            key = _key_for(client, _verdict(), effective_at=T0)
            ledger.claim_legacy(key, event_id="event-legacy", provable=False)
            response = client.submit_command(_verdict(), effective_at=T0)

        assert response.classification is ResponseClassification.REJECTED
        assert response.rejection is not None
        assert response.rejection.reason == IDEMPOTENCY_LEGACY_UNVERIFIABLE
        assert response.attempts == 1

    def test_a_provable_legacy_key_still_replays(self) -> None:
        """The migration's compatible case: a legacy key whose original event proves the request
        binds on first sight and keeps replaying, without releasing or re-pointing the key."""
        ledger = _FakeLedger()
        with _client(ledger) as client:
            key = _key_for(client, _verdict(), effective_at=T0)
            ledger.claim_legacy(key, event_id="event-legacy", provable=True)
            first = client.submit_command(_verdict(), effective_at=T0)
            second = client.submit_command(_verdict(), effective_at=T0)

        assert first.classification is ResponseClassification.REPLAYED
        assert first.event_id == "event-legacy"
        assert second.event_id == "event-legacy"
        assert ledger.events == ["event-legacy"], "binding a legacy key writes no event"


def _key_for(client: PulseCoreClient, command, *, effective_at: datetime, **kwargs) -> str:
    """The key the SDK would derive for this submission, without submitting it.

    Read off a captured request rather than re-derived here: a test that computed the key itself
    would pass while the client derived a different one.
    """
    captured: list[str] = []

    def capture(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content)["idempotency_key"])
        return httpx.Response(201, json={"event_id": "probe"}, request=request)

    with PulseCoreClient(
        "http://ledger.test",
        writer_id=client._writer_id,
        token="unit-test-token",  # noqa: S106 — a fixture value, not a secret
        transport=httpx.MockTransport(capture),
        sleep=lambda _seconds: None,
    ) as probe:
        probe.submit_command(command, effective_at=effective_at, **kwargs)
    return captured[0]


# --- 3. the fields outside the key ---------------------------------------------------------


class TestFieldsOutsideTheKey:
    """The compatibility population: same key, different canonical request.

    The D16 key hashes subject, command type, payload and `logical_time`. Canonical request v1
    also covers `to_state`, `evidence` and `evidence_class`. A producer that varies one of those
    between retries of one fact derives the *same* key and, after enforcement, receives a 409
    where it used to receive the original result. These are the shapes the deployed producers
    actually have, which is why the inventory's "varies between retries" column is producer-side
    evidence and not a ledger query.
    """

    def test_evidence_varying_between_retries_conflicts(self) -> None:
        """`identity.resolver` shape: `candidate_count` and `matched_fields` travel in `evidence`,
        outside the key, and a re-resolution against a grown candidate pool changes them."""
        ledger = _FakeLedger()
        with _client(ledger) as client:
            first = client.submit_command(_verdict(), effective_at=T0, evidence={"rule_id": "R1", "candidate_count": 1})
            second = client.submit_command(
                _verdict(), effective_at=T0, evidence={"rule_id": "R1", "candidate_count": 2}
            )

        assert first.classification is ResponseClassification.COMMITTED
        assert second.classification is ResponseClassification.REJECTED
        assert second.rejection is not None
        assert second.rejection.reason == IDEMPOTENCY_CONFLICT
        assert len(ledger.events) == 1, "a conflict writes nothing"

    def test_to_state_varying_between_retries_conflicts(self) -> None:
        """Relay/connector shape: `to_state` comes from a `transition_by_outcome` mapping, which
        is configuration. Re-declaring one verdict row after that mapping changes keeps the key
        and changes the request."""
        ledger = _FakeLedger()
        command = DeclareTransitionCommand(
            subject_key="referral-synthetic-1", subject_type="coverage", to_state="verified_active"
        )
        with _client(ledger) as client:
            first = client.submit_command(command, effective_at=T0)
            second = client.submit_command(
                command.model_copy(update={"to_state": "verified_inactive"}), effective_at=T0
            )

        assert first.classification is ResponseClassification.COMMITTED
        assert second.classification is ResponseClassification.REJECTED
        assert second.rejection is not None
        assert second.rejection.reason == IDEMPOTENCY_CONFLICT

    def test_an_unchanged_evidence_retry_is_still_a_replay(self) -> None:
        """The other half of the same finding: evidence outside the key costs nothing as long as
        it is derived from the same facts the payload is."""
        ledger = _FakeLedger()
        evidence = {"rule_id": "R1", "matched_fields": ["dob", "last_name"], "candidate_count": 1}
        with _client(ledger) as client:
            first = client.submit_command(_verdict(), effective_at=T0, evidence=dict(evidence))
            second = client.submit_command(_verdict(), effective_at=T0, evidence=dict(evidence))

        assert second.classification is ResponseClassification.REPLAYED
        assert second.event_id == first.event_id

    def test_a_reordered_evidence_list_is_a_different_request(self) -> None:
        """List order is semantic in canonical v1 — normalising it would erase a real difference.
        A producer that cannot promise a stable order must sort before it declares."""
        ledger = _FakeLedger()
        with _client(ledger) as client:
            client.submit_command(_verdict(), effective_at=T0, evidence={"matched_fields": ["dob", "last_name"]})
            reordered = client.submit_command(
                _verdict(), effective_at=T0, evidence={"matched_fields": ["last_name", "dob"]}
            )

        assert reordered.classification is ResponseClassification.REJECTED
        assert reordered.rejection is not None
        assert reordered.rejection.reason == IDEMPOTENCY_CONFLICT


# --- webhook ingress -----------------------------------------------------------------------


class TestSignedTwentyIngress:
    """The webhook's contract: 200 whatever the verdict, and an exact redelivery is stable."""

    def _deliver(self, ledger: _FakeLedger, body: Mapping[str, object]) -> httpx.Response:
        with httpx.Client(
            base_url="http://ledger.test",
            transport=httpx.MockTransport(ledger.handler),
            headers={"Authorization": "Bearer webhook-token"},
        ) as delivery:
            return delivery.post("/webhooks/twenty", json=dict(body))

    def test_an_exact_redelivery_replays_the_same_event(self) -> None:
        ledger = _FakeLedger(writers={"webhook-token": "twenty-webhook"})
        body = {
            "idempotency_key": "twenty-webhook:deadbeef",
            "subject_type": "referral",
            "subject_key": "referral-synthetic-1",
            "event_type": "declare_transition",
            "to_state": "screened",
            "effective_at": T0.isoformat(),
            "payload": {"note": _SENTINEL},
        }
        first = self._deliver(ledger, body)
        second = self._deliver(ledger, body)

        assert (first.status_code, second.status_code) == (200, 200)
        assert second.json()["event_id"] == first.json()["event_id"]
        assert len(ledger.events) == 1

    def test_a_conflicting_delivery_is_a_rejected_disposition_inside_a_200(self) -> None:
        """Not a 4xx: Twenty reads a non-2xx as "deliver again", so a conflict answered with one
        becomes a redelivery storm against a key that can never be claimed."""
        ledger = _FakeLedger(writers={"webhook-token": "twenty-webhook"})
        body = {
            "idempotency_key": "twenty-webhook:deadbeef",
            "subject_type": "referral",
            "subject_key": "referral-synthetic-1",
            "event_type": "declare_transition",
            "to_state": "screened",
            "effective_at": T0.isoformat(),
            "payload": {"note": _SENTINEL},
        }
        self._deliver(ledger, body)
        conflicting = self._deliver(ledger, {**body, "to_state": "outreach"})

        assert conflicting.status_code == 200
        assert conflicting.json() == {"disposition": "rejected", "reason": IDEMPOTENCY_CONFLICT}
        assert len(ledger.events) == 1

    def test_a_webhook_key_is_not_answerable_by_a_bearer_writer(self) -> None:
        """Same key text, different authenticated principal: a conflict, never the webhook's
        event. The key's prefix is client-supplied text and authenticates nothing (D15)."""
        ledger = _FakeLedger(writers={"webhook-token": "twenty-webhook", "relay-token": "verdict-relay"})
        body = {
            "idempotency_key": "twenty-webhook:deadbeef",
            "subject_type": "referral",
            "subject_key": "referral-synthetic-1",
            "event_type": "declare_transition",
            "to_state": "screened",
            "effective_at": T0.isoformat(),
            "payload": {"note": _SENTINEL},
        }
        self._deliver(ledger, body)
        with httpx.Client(
            base_url="http://ledger.test",
            transport=httpx.MockTransport(ledger.handler),
            headers={"Authorization": "Bearer relay-token"},
        ) as bearer:
            stolen = bearer.post("/commands", json=dict(body))

        assert stolen.status_code == 409
        assert stolen.json()["detail"]["reason"] == IDEMPOTENCY_CONFLICT
        assert classify_response(stolen).classification is ResponseClassification.REJECTED


# --- 4. nothing leaks ----------------------------------------------------------------------


class TestNothingLeaks:
    def test_a_conflict_discloses_no_prior_result(self, caplog: pytest.LogCaptureFixture) -> None:
        ledger = _FakeLedger()
        with caplog.at_level(logging.DEBUG), _client(ledger) as client:
            committed = client.submit_command(_verdict(), effective_at=T0)
            conflict = client.submit_command(_verdict(), effective_at=T0, evidence={"window": "widened"})

        assert conflict.event_id is None
        assert conflict.state is None
        assert conflict.recorded_at is None
        assert conflict.rejection is not None
        assert committed.event_id not in repr(conflict)
        observed = repr(conflict) + "".join(record.getMessage() for record in caplog.records)
        assert _SENTINEL not in observed
        assert "v1:" not in observed, "a fingerprint is derived from payload and evidence; it is not safe to surface"

    def test_a_leaky_server_body_still_yields_no_result(self) -> None:
        """Defence in depth: even handed a 409 body carrying the prior event, the SDK surfaces the
        reason and nothing else. A producer cannot be made into a disclosure channel by a server
        regression."""
        leaky = httpx.Response(
            409,
            json={
                "detail": {
                    "message": "idempotency key is claimed by another request",
                    "reason": IDEMPOTENCY_CONFLICT,
                },
                "event_id": "event-1",
                "state": {"status": "screened"},
                "fingerprint": "v1:" + "a" * 64,
            },
            request=httpx.Request("POST", "http://ledger.test/commands"),
        )
        result = classify_response(leaky)

        assert result.classification is ResponseClassification.REJECTED
        assert result.event_id is None
        assert result.state is None
        assert result.rejection is not None
        assert result.rejection.reason == IDEMPOTENCY_CONFLICT
        assert "v1:" not in repr(result)

    def test_an_exhausted_retry_names_the_submission_not_its_content(self) -> None:
        """`ref` is a name, not a request — the one string a connector's failure path prints."""

        def always_transient() -> CommandResponse:
            return classify_response(
                httpx.Response(503, text="upstream unavailable", request=httpx.Request("POST", "http://x/commands"))
            )

        with pytest.raises(TransientExhaustedError) as raised:
            submit_with_retry(
                always_transient,
                ref="referral-synthetic-1",
                max_attempts=2,
                sleep=lambda _seconds: None,
                jitter=lambda: 1.0,
            )

        assert _SENTINEL not in str(raised.value)


# --- the rollout gate ----------------------------------------------------------------------


INVENTORY = REPO_ROOT / "docs" / "idempotency-compatibility-inventory.md"
PRODUCER_REGISTRY = REPO_ROOT / "docs" / "contracts" / "producer-registry.md"

BLOCKING_DISPOSITIONS = frozenset({"unknown", "fix-required"})
DISPOSITIONS = frozenset({"compatible", "migrated", *BLOCKING_DISPOSITIONS})
INGRESSES = frozenset({"bearer", "batch", "webhook"})


@dataclass(frozen=True)
class InventoryRow:
    producer: str
    ingress: str
    retries_keyed: str
    reconstructible: str
    varies: str
    disposition: str
    evidence: str


def _cell(text: str) -> str:
    """One table cell as its bare value: markdown emphasis and code ticks stripped, notes dropped.

    A cell reads `` `unknown` — not yet run ``; the gate is decided by the value before the dash.
    """
    return re.sub(r"[`*]", "", text).split("—")[0].strip()


def _inventory_rows() -> tuple[InventoryRow, ...]:
    """The inventory table's rows. Parsed, not asserted by hand, so the gate follows the page."""
    rows: list[InventoryRow] = []
    in_table = False
    for line in INVENTORY.read_text().splitlines():
        if line.startswith("| Producer |"):
            in_table = True
            continue
        if in_table:
            if not line.startswith("|"):
                break
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) != 7 or set(cells[0]) <= {"-", " "}:
                continue
            rows.append(InventoryRow(*(_cell(cell) for cell in cells)))
    return tuple(rows)


@dataclass(frozen=True)
class RegisteredProducer:
    """One `docs/contracts/producer-registry.md` row, reduced to what the gate needs."""

    system: str
    credential_names: tuple[str, ...]
    status: str

    def represented_in(self, inventory: str) -> bool:
        """Whether the inventory names this producer — by its registry label or its credential.

        Either spelling counts: the inventory lists a credential where one is named and the
        registry's own system label where the credential is a per-human or per-service one with no
        identifier of its own.
        """
        haystack = _normalised(inventory)
        return self.system in haystack or any(_normalised(name) in haystack for name in self.credential_names)


def _normalised(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[`*]", "", text)).strip().lower()


def _registered_producers() -> tuple[RegisteredProducer, ...]:
    """Every registry row that can declare into the ledger.

    `excluded-by-design` rows are dropped: they have no credential and no ledger machine to
    declare into, so an inventory row for one would assert an audit of nothing.
    """
    producers: list[RegisteredProducer] = []
    for line in PRODUCER_REGISTRY.read_text().splitlines():
        if not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 7 or cells[0] == "System" or set(cells[0]) <= {"-", " "}:
            continue
        status = _normalised(cells[5])
        if status == "excluded-by-design":
            continue
        producers.append(
            RegisteredProducer(
                system=_normalised(cells[0]),
                credential_names=tuple(re.findall(r"`([^`\s]+)`", cells[3])),
                status=status,
            )
        )
    return tuple(producers)


def _enforcement_blocked(rows: tuple[InventoryRow, ...]) -> bool:
    """The gate, as `LegacyInventory.enforcement_blocked` states it for the ledger's own rows: an
    empty inventory is not a pass, and one blocking row is enough."""
    return not rows or any(row.disposition in BLOCKING_DISPOSITIONS for row in rows)


class TestRolloutPreflight:
    """The first step of `docs/runbooks/idempotency-enforcement-rollout.md`.

    Run it before an attended rehearsal and before any enforcement flip: it answers "is the gate
    clear" from the committed page rather than from someone's reading of it.
    """

    def test_the_inventory_has_rows_in_the_documented_vocabulary(self) -> None:
        rows = _inventory_rows()
        assert rows, "an empty inventory has not been taken; it cannot clear the gate"
        for row in rows:
            assert row.disposition in DISPOSITIONS, f"{row.producer}: unknown disposition {row.disposition!r}"
            assert row.ingress in INGRESSES, f"{row.producer}: unknown ingress {row.ingress!r}"

    def test_every_command_submitting_producer_has_a_row(self) -> None:
        """A producer absent from the inventory is a producer nobody audited, which is exactly the
        state the gate exists to refuse. `producer-registry.md` is the source of the list, and a
        row excluded by design there (nothing crosses into the ledger at all) is the one omission
        the gate allows."""
        unrepresented = [
            producer.system
            for producer in _registered_producers()
            if not producer.represented_in(INVENTORY.read_text())
        ]
        assert not unrepresented, f"producers with no inventory row: {sorted(unrepresented)}"

    def test_an_unknown_row_blocks_enforcement(self) -> None:
        rows = _inventory_rows()
        unknown = [row for row in rows if row.disposition == "unknown"]
        assert unknown, "the change has not promoted a row; task 4.1's attended run decides them"
        assert _enforcement_blocked(rows)

    def test_a_fully_compatible_inventory_clears_the_gate(self) -> None:
        """The gate is a real check, not one that always says no — it opens when every row is
        decided, which is what the attended run is for."""
        decided = tuple(
            InventoryRow(row.producer, row.ingress, "yes", "yes", "no", "compatible", "receipt")
            for row in _inventory_rows()
        )
        assert not _enforcement_blocked(decided)
        assert _enforcement_blocked(())

    def test_the_page_states_the_gate_it_is_in(self) -> None:
        """The prose and the table cannot disagree: while a row blocks, the page says so."""
        text = INVENTORY.read_text()
        if _enforcement_blocked(_inventory_rows()):
            assert "enforcement is blocked" in text.lower()
