"""Fixture builders for billing-connector tests (task 1.4).

`make_facts`/`make_stale_facts` build a `billing.facts.SubjectFactsSnapshot` — the same shape
the engine's own fold (`billing.facts.fold_event`) produces — so a wave-1 `evaluate_subject`
fixture starts from a row the real store schema can hold, never an invented shape. `make_event`
builds one ledger event envelope `fold_event` accepts (`event_id`, `subject_type`,
`subject_key`, `effective_at`, `payload`), for tests exercising the fold itself or `service.py`'s
consume handler. `FakeCommandTransport` records every command a declare submits without opening
a socket, standing in for `httpx.MockTransport` scripted with canned responses (verdict-relay's
`ScriptedApi`, `test_fixture_corpus.py`) — `declare.declare_pair` (task 2.2) is the first real
caller; this ships now so its tests do not also have to invent the fake.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import cast

import httpx
from billing.facts import SubjectFactsSnapshot
from pulse_core.client import PulseCoreClient

#: Reserved key `billing.facts` folds the last-applied event's effective time under — mirrored
#: here rather than imported, since the engine module keeps it private (a leading double
#: underscore no real payload field uses).
_FOLDED_AS_OF_KEY = "__folded_as_of__"

DEFAULT_SUBJECT_TYPE = "billing_episode"
DEFAULT_SUBJECT_KEY = "episode-1001"
DEFAULT_EVENT_ID = "event-1"

#: `make_stale_facts`'s default staleness margin — comfortably past any `stale_after` a test
#: configures without hardcoding one, since `Config.stale_after` is not this module's concern.
_DEFAULT_STALE_BY = timedelta(days=2)


def make_event(
    *,
    event_id: str = DEFAULT_EVENT_ID,
    subject_type: str = DEFAULT_SUBJECT_TYPE,
    subject_key: str = DEFAULT_SUBJECT_KEY,
    effective_at: datetime | None = None,
    payload: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """One ledger event envelope `billing.facts.fold_event` accepts.

    `effective_at` defaults to now (timezone-aware, per `required_timestamp`); `payload` defaults
    to an empty qualification-fact object — never a monetary field (spec: "No monetary value
    crosses the seam").
    """
    as_of = effective_at or datetime.now(timezone.utc)
    return {
        "event_id": event_id,
        "subject_type": subject_type,
        "subject_key": subject_key,
        "effective_at": as_of.isoformat(),
        "payload": dict(payload or {}),
    }


def make_facts(
    *,
    subject_type: str = DEFAULT_SUBJECT_TYPE,
    subject_key: str = DEFAULT_SUBJECT_KEY,
    facts: Mapping[str, object] | None = None,
    last_event_id: str = DEFAULT_EVENT_ID,
    folded_as_of: datetime | None = None,
) -> SubjectFactsSnapshot:
    """A fresh `subject_facts` snapshot: `folded_as_of` defaults to now, so evaluating this row
    against any reasonable `stale_after` reports `facts_stale=False` (spec: "A fresh watermark
    evaluates the rule").
    """
    as_of = folded_as_of or datetime.now(timezone.utc)
    merged: dict[str, object] = {**dict(facts or {}), _FOLDED_AS_OF_KEY: as_of.isoformat()}
    return SubjectFactsSnapshot(
        subject_type=subject_type,
        subject_key=subject_key,
        facts=merged,
        last_event_id=last_event_id,
    )


def make_stale_facts(
    *,
    subject_type: str = DEFAULT_SUBJECT_TYPE,
    subject_key: str = DEFAULT_SUBJECT_KEY,
    facts: Mapping[str, object] | None = None,
    last_event_id: str = DEFAULT_EVENT_ID,
    stale_by: timedelta = _DEFAULT_STALE_BY,
) -> SubjectFactsSnapshot:
    """A `subject_facts` snapshot whose watermark is `stale_by` old — evaluates
    `facts_stale=True` against any threshold shorter than that (spec: "Staleness comes from the
    connector's own watermark", "A stale watermark yields awaiting_source").
    """
    return make_facts(
        subject_type=subject_type,
        subject_key=subject_key,
        facts=facts,
        last_event_id=last_event_id,
        folded_as_of=datetime.now(timezone.utc) - stale_by,
    )


class FakeCommandTransport:
    """The command API faked at the client boundary; the last scripted response repeats.

    A caller that scripts no responses gets one synthesized `committed` reply per call, keyed by
    call order, so a fixture that only cares about the submitted body need not script anything.
    """

    def __init__(self, responses: list[httpx.Response] | None = None) -> None:
        self.bodies: list[dict[str, object]] = []
        self._responses = list(responses or [])

    def handler(self, request: httpx.Request) -> httpx.Response:
        parsed: object = json.loads(request.content)
        assert isinstance(parsed, dict)
        self.bodies.append(cast("dict[str, object]", parsed))
        if not self._responses:
            return httpx.Response(201, json={"event_id": f"event-{len(self.bodies)}", "replayed": False})
        return self._responses[min(len(self.bodies), len(self._responses)) - 1]

    def client(self, *, base_url: str = "http://ledger.test", writer_id: str = "billing-connector") -> PulseCoreClient:
        return PulseCoreClient(
            base_url,
            writer_id=writer_id,
            token="unit-test-token",  # noqa: S106 — a fixture value, not a secret
            transport=httpx.MockTransport(self.handler),
            max_attempts=1,
        )
