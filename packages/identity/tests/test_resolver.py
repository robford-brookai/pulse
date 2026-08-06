"""`identity.resolver` — decisions to commands (task 4.1).

Covers the spec's resolution scenarios: a `Match` with a new identifier declares both commands
with evidence; a `Mint` declares `mint_person` before `resolve_referral` before attaching; an
identifier the person already holds is skipped, not re-attached; replaying the identical
resolution derives the identical wire idempotency key so the ledger sees no new events; a
`rejected` response stops the sequence and carries the rejection; a `transient` response (after
the client's own retry budget is spent) raises rather than looping. Plus a caplog scan across the
resolver's own decision/evidence logging for fixture demographic strings (flagged path (c),
design decision 3).

The command API is faked at the client boundary (`httpx.MockTransport` under a real
`PulseCoreClient`), same posture as `verdict_relay.declarer`'s tests; `conftest.py` blocks sockets.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import cast

import httpx
import pytest
from identity.matcher import (
    Ambiguous,
    CandidateLookup,
    Decision,
    Evidence,
    ExternalIdentifier,
    InMemoryLookup,
    Match,
    Mint,
    Person,
    Referral,
)
from identity.normalize import Demographics
from identity.resolver import (
    PersonKeyFactory,
    RejectedCommandError,
    ResolutionOutcome,
    TransientCommandError,
    act,
    default_person_key,
)
from pulse_core.client import PulseCoreClient, ResponseClassification

EFFECTIVE_AT = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
EVENT_ID = "018f3c2a-7b6e-7c4d-9a1b-2f3e4d5c6b7a"

DEMOGRAPHICS = Demographics(last_name="Wozniak", first_name="Roberta", dob="1990-06-04", sex="f")


def committed(event_id: str) -> httpx.Response:
    return httpx.Response(201, json={"event_id": event_id, "replayed": False})


def replayed(event_id: str) -> httpx.Response:
    return httpx.Response(201, json={"event_id": event_id, "replayed": True})


def rejected(reason: str = "identifier already held by another person") -> httpx.Response:
    return httpx.Response(
        422,
        json={"detail": {"message": "identifier conflict", "reason": reason, "catalog_version": "appendix-c-v0.7"}},
    )


def transient() -> httpx.Response:
    return httpx.Response(503, text="upstream unavailable")


class ScriptedApi:
    """The command API faked at the client boundary: one scripted answer per POST, in order.

    Records every request body so a test can inspect the wire-level `idempotency_key`,
    `event_type`, `subject_key`, and `evidence` fields exactly as `PulseCoreClient` sent them.
    """

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.bodies: list[dict[str, object]] = []
        self._responses = responses

    def handler(self, request: httpx.Request) -> httpx.Response:
        parsed: object = json.loads(request.content)
        assert isinstance(parsed, dict)
        self.bodies.append(cast("dict[str, object]", parsed))
        return self._responses[min(len(self.bodies), len(self._responses)) - 1]

    def client(self, *, max_attempts: int = 1) -> PulseCoreClient:
        return PulseCoreClient(
            "http://ledger.test",
            writer_id="identity-service",
            token="unit-test-token",  # noqa: S106 — a fixture value, not a secret
            transport=httpx.MockTransport(self.handler),
            max_attempts=max_attempts,
            sleep=lambda _seconds: None,
        )


def mapping_of(body: dict[str, object], key: str) -> dict[str, object]:
    """A nested JSON object field (`payload`/`evidence`), typed for further subscripting."""
    return cast("dict[str, object]", body[key])


def identifier(system: str = "MRN-ACME", value: str = "SYN-0001") -> ExternalIdentifier:
    return ExternalIdentifier(system=system, value=value)


def evidence(rule_id: str = "composite_unique", candidate_count: int = 1) -> Evidence:
    return Evidence(
        matched_fields=("last_name", "dob", "sex", "first_initial"), rule_id=rule_id, candidate_count=candidate_count
    )


def referral(*identifiers: ExternalIdentifier) -> Referral:
    return Referral(demographics=DEMOGRAPHICS, identifiers=identifiers)


def act_over(
    decision: Decision,
    ref: Referral,
    api: ScriptedApi,
    *,
    lookup: CandidateLookup | None = None,
    max_attempts: int = 1,
    event_id: str = EVENT_ID,
    person_key_factory: PersonKeyFactory = default_person_key,
) -> ResolutionOutcome:
    return act(
        decision,
        ref,
        referral_key="referral-0001",
        triggering_event_id=event_id,
        effective_at=EFFECTIVE_AT,
        lookup=lookup or InMemoryLookup(()),
        client=api.client(max_attempts=max_attempts),
        person_key_factory=person_key_factory,
    )


# --- Match: resolves and attaches only unheld identifiers -------------------------------------


def test_match_with_new_identifier_declares_both_commands_with_evidence():
    api = ScriptedApi([committed("e1"), committed("e2")])
    decision = Match(person_id="tide-000000000000000a", evidence=evidence())

    outcome = act_over(decision, referral(identifier()), api)

    assert [command.command_type for command in outcome.commands] == ["resolve_referral", "attach_identifier"]
    assert outcome.person_key == "tide-000000000000000a"
    resolve_body, attach_body = api.bodies
    assert resolve_body["event_type"] == "resolve_referral"
    assert resolve_body["subject_key"] == "referral-0001"
    assert mapping_of(resolve_body, "payload")["person_key"] == "tide-000000000000000a"
    assert attach_body["event_type"] == "attach_identifier"
    assert attach_body["subject_key"] == "tide-000000000000000a"
    assert attach_body["payload"] == {"system": "MRN-ACME", "value": "SYN-0001"}
    for body in (resolve_body, attach_body):
        command_evidence = mapping_of(body, "evidence")
        assert command_evidence == {
            "matched_fields": ["last_name", "dob", "sex", "first_initial"],
            "rule_id": "composite_unique",
            "candidate_count": 1,
            "idempotency_key": command_evidence["idempotency_key"],
        }
        assert isinstance(body["idempotency_key"], str) and body["idempotency_key"]


def test_already_held_identifiers_are_skipped_not_re_attached():
    held = identifier(system="MRN-ACME", value="SYN-0001")
    fresh = identifier(system="MRN-OTHER", value="SYN-0002")
    person_key = "tide-000000000000000a"
    lookup = InMemoryLookup([Person(person_id=person_key, demographics=DEMOGRAPHICS, identifiers=(held,))])
    decision = Match(person_id=person_key, evidence=evidence())
    api = ScriptedApi([committed("e1"), committed("e2")])

    outcome = act_over(decision, referral(held, fresh), api, lookup=lookup)

    assert [command.command_type for command in outcome.commands] == ["resolve_referral", "attach_identifier"]
    _resolve_body, attach_body = api.bodies
    assert attach_body["payload"] == {"system": "MRN-OTHER", "value": "SYN-0002"}


def test_match_with_no_new_identifiers_declares_only_resolve_referral():
    held = identifier()
    person_key = "tide-000000000000000a"
    lookup = InMemoryLookup([Person(person_id=person_key, demographics=DEMOGRAPHICS, identifiers=(held,))])
    decision = Match(person_id=person_key, evidence=evidence())
    api = ScriptedApi([committed("e1")])

    outcome = act_over(decision, referral(held), api, lookup=lookup)

    assert [command.command_type for command in outcome.commands] == ["resolve_referral"]


# --- Mint: mint_person, then resolve_referral, then attach, in that order ----------------------


def test_mint_ordering():
    api = ScriptedApi([committed("e1"), committed("e2"), committed("e3")])
    decision = Mint(evidence=evidence(rule_id="composite_none", candidate_count=0))

    outcome = act_over(decision, referral(identifier()), api, person_key_factory=lambda: "tide-minted-0001")

    assert [command.command_type for command in outcome.commands] == [
        "mint_person",
        "resolve_referral",
        "attach_identifier",
    ]
    assert outcome.person_key == "tide-minted-0001"
    mint_body, resolve_body, attach_body = api.bodies
    assert mint_body["subject_key"] == "tide-minted-0001"
    assert resolve_body["subject_key"] == "referral-0001"
    assert mapping_of(resolve_body, "payload")["person_key"] == "tide-minted-0001"
    assert attach_body["subject_key"] == "tide-minted-0001"


class _UnconsultedLookupError(AssertionError):
    """A mint decision consulted the lookup port; it must not — a new person holds nothing yet."""


class ExplodingLookup:
    """Fails loudly if a mint decision ever consults it: a brand-new person can't hold anything."""

    def lookup_identifier(self, system: str, value: str) -> str | None:
        raise _UnconsultedLookupError

    def find_candidates(self, match_key: str) -> tuple[str, ...]:
        raise _UnconsultedLookupError


def test_mint_never_consults_the_lookup_for_already_held_identifiers():
    api = ScriptedApi([committed("e1"), committed("e2"), committed("e3")])
    decision = Mint(evidence=evidence(rule_id="composite_none", candidate_count=0))

    act_over(decision, referral(identifier()), api, lookup=ExplodingLookup(), person_key_factory=lambda: "tide-0001")


# --- Rejects Ambiguous outright: quarantine is task 4.2's job ----------------------------------


def test_rejects_ambiguous_decisions_outright():
    api = ScriptedApi([])
    decision = Ambiguous(
        candidates=("tide-a", "tide-b"), evidence=evidence(rule_id="composite_ambiguous", candidate_count=2)
    )

    with pytest.raises(TypeError, match="Ambiguous"):
        act_over(decision, referral(), api)
    assert api.bodies == []


# --- Idempotency: the identical resolution replayed derives the identical wire key ------------


def test_identical_resolution_replayed_derives_the_identical_wire_key():
    decision = Match(person_id="tide-000000000000000a", evidence=evidence())
    ref = referral(identifier())

    first_api = ScriptedApi([committed("e1"), committed("e2")])
    first = act_over(decision, ref, first_api)

    second_api = ScriptedApi([replayed("e1"), replayed("e2")])
    second = act_over(decision, ref, second_api)

    assert [body["idempotency_key"] for body in first_api.bodies] == [
        body["idempotency_key"] for body in second_api.bodies
    ]
    assert [outcome.classification for outcome in first.commands] == [
        ResponseClassification.COMMITTED,
        ResponseClassification.COMMITTED,
    ]
    assert [outcome.classification for outcome in second.commands] == [
        ResponseClassification.REPLAYED,
        ResponseClassification.REPLAYED,
    ]
    assert [outcome.idempotency_key for outcome in first.commands] == [
        outcome.idempotency_key for outcome in second.commands
    ]


def test_a_different_triggering_event_derives_a_different_audit_key():
    decision = Mint(evidence=evidence(rule_id="composite_none", candidate_count=0))
    ref = referral()

    first_api = ScriptedApi([committed("e1"), committed("e2")])
    first = act_over(decision, ref, first_api, event_id="event-one", person_key_factory=lambda: "tide-0001")

    second_api = ScriptedApi([committed("e3"), committed("e4")])
    second = act_over(decision, ref, second_api, event_id="event-two", person_key_factory=lambda: "tide-0001")

    assert first.commands[0].idempotency_key != second.commands[0].idempotency_key


# --- rejected stops the sequence; transient raises once the client's own retries are spent -----


def test_rejected_stops_the_sequence_and_carries_the_rejection():
    api = ScriptedApi([committed("e1"), rejected("identifier held by tide-000000000000000c")])
    decision = Match(person_id="tide-000000000000000a", evidence=evidence())

    with pytest.raises(RejectedCommandError) as excinfo:
        act_over(decision, referral(identifier(), identifier(system="MRN-OTHER", value="SYN-0002")), api)

    assert excinfo.value.command_type == "attach_identifier"
    assert len(excinfo.value.completed) == 1
    assert excinfo.value.completed[0].command_type == "resolve_referral"
    # The sequence stopped: no third command (the second attach_identifier) was ever sent.
    assert len(api.bodies) == 2


def test_transient_exhausted_raises_rather_than_looping_forever():
    api = ScriptedApi([transient()])
    decision = Match(person_id="tide-000000000000000a", evidence=evidence())

    with pytest.raises(TransientCommandError) as excinfo:
        act_over(decision, referral(), api, max_attempts=2)

    assert excinfo.value.command_type == "resolve_referral"
    assert excinfo.value.response.attempts == 2


# --- No fixture demographic string reaches the resolver's own logging (design decision 3c) -----


def leakable_values(demographics: Demographics, *identifiers: ExternalIdentifier) -> tuple[str, ...]:
    values = [demographics.last_name, demographics.first_name, str(demographics.dob), demographics.sex]
    values.extend(identifier.value for identifier in identifiers)
    return tuple(value for value in values if len(value) > 2)


def test_no_fixture_demographic_or_identifier_value_reaches_the_resolver_logs(caplog: pytest.LogCaptureFixture):
    held = identifier(system="MRN-ACME", value="SYN-SECRET-0001")
    fresh = identifier(system="MRN-OTHER", value="SYN-SECRET-0002")
    person_key = "tide-000000000000000a"
    lookup = InMemoryLookup([Person(person_id=person_key, demographics=DEMOGRAPHICS, identifiers=(held,))])
    decision = Match(person_id=person_key, evidence=evidence())
    api = ScriptedApi([committed("e1"), rejected("identifier held by tide-000000000000000c")])

    caplog.set_level(logging.DEBUG, logger="identity.resolver")
    with pytest.raises(RejectedCommandError):
        act_over(decision, referral(held, fresh), api, lookup=lookup)

    rendered = "\n".join(record.getMessage() for record in caplog.records)
    for value in leakable_values(DEMOGRAPHICS, held, fresh):
        assert value.casefold() not in rendered.casefold()


# --- Person-key minting -------------------------------------------------------------------------


def test_default_person_key_mints_a_fresh_opaque_key_each_call():
    first, second = default_person_key(), default_person_key()
    assert first != second
    assert first.startswith("tide-")
