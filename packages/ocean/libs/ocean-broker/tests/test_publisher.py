"""Tests for EventBridgePublisher — the `event-transport` spec scenarios.

The publish-failure paths matter more than the happy one. Verification item V5 found six of the
thirteen publish sites had no dead-letter fallback at all, so an event the broker rejected was
simply gone. These assert the fallback actually catches every rejection shape, including the one
that does not raise.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from ocean_broker.publisher import MAX_ENTRY_BYTES, EventBridgePublisher, PublishError

ENVELOPE = {
    "event_id": "evt-1",
    "event_type": "alert.raised",
    "entity_id": "alert-1",
    "correlation_id": "corr-1",
    "payload": {"severity": "high"},
}


class FakeClient:
    """Records entries and replays a scripted response."""

    def __init__(self, response: dict[str, Any] | None = None, raises: Exception | None = None) -> None:
        self.entries: list[dict[str, Any]] = []
        self._response = response if response is not None else {"FailedEntryCount": 0}
        self._raises = raises

    def put_events(self, *, Entries: list[dict[str, Any]]) -> dict[str, Any]:
        self.entries.extend(Entries)
        if self._raises:
            raise self._raises
        return self._response


class FakeSession:
    def __init__(self, sink: list[dict[str, Any]]) -> None:
        self._sink = sink

    async def execute(self, _stmt: object, params: dict[str, Any]) -> None:
        self._sink.append(params)

    def begin(self) -> FakeSession:
        return self

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


def fake_session_maker(sink: list[dict[str, Any]]):
    def _maker() -> FakeSession:
        return FakeSession(sink)

    return _maker


def make(response=None, raises=None) -> tuple[EventBridgePublisher, FakeClient, list[dict[str, Any]]]:
    client = FakeClient(response, raises)
    sink: list[dict[str, Any]] = []
    return EventBridgePublisher(client, "ocean-bus", fake_session_maker(sink)), client, sink


# --- addressing -------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_addressing_comes_from_the_catalog_not_the_caller() -> None:
    pub, client, _ = make()
    assert await pub.publish("alerts", ENVELOPE) is True
    (entry,) = client.entries
    assert entry["Source"] == "ocean"
    assert entry["DetailType"] == "alerts"
    assert entry["EventBusName"] == "ocean-bus"


@pytest.mark.asyncio
async def test_event_type_is_not_promoted_to_detail_type() -> None:
    """detail-type carries the domain. event_type keeps changing as the catalog grows."""
    pub, client, _ = make()
    await pub.publish("alerts", ENVELOPE)
    (entry,) = client.entries
    assert entry["DetailType"] == "alerts"
    assert json.loads(entry["Detail"])["event_type"] == "alert.raised"


@pytest.mark.asyncio
async def test_envelope_crosses_whole() -> None:
    pub, client, _ = make()
    await pub.publish("alerts", ENVELOPE)
    assert json.loads(client.entries[0]["Detail"]) == ENVELOPE


@pytest.mark.asyncio
async def test_key_travels_in_the_envelope_and_does_not_route() -> None:
    """The key no longer picks a partition; it is what consumer sequence guards group by."""
    pub, client, _ = make()
    await pub.publish("alerts", ENVELOPE, key="patient-7")
    await pub.publish("alerts", ENVELOPE, key="patient-9")
    assert [json.loads(e["Detail"])["key"] for e in client.entries] == ["patient-7", "patient-9"]
    assert {e["DetailType"] for e in client.entries} == {"alerts"}


@pytest.mark.asyncio
async def test_publishing_does_not_mutate_the_caller_envelope() -> None:
    pub, _, _ = make()
    original = dict(ENVELOPE)
    await pub.publish("alerts", ENVELOPE, key="patient-7")
    assert original == ENVELOPE


@pytest.mark.asyncio
async def test_an_unknown_domain_raises_rather_than_dead_lettering() -> None:
    """A domain that is not in the catalog is a wiring bug, not a runtime failure to absorb."""
    pub, _, sink = make()
    with pytest.raises(KeyError):
        await pub.publish("not-a-domain", ENVELOPE)
    assert sink == []


@pytest.mark.asyncio
async def test_the_retired_warehouse_dlq_domain_is_not_publishable() -> None:
    pub, _, _ = make()
    with pytest.raises(KeyError):
        await pub.publish("warehouse-dlq", ENVELOPE)


# --- failure paths ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_raising_client_dead_letters() -> None:
    pub, _, sink = make(raises=RuntimeError("network down"))
    assert await pub.publish("alerts", ENVELOPE) is False
    assert len(sink) == 1
    assert "network down" in sink[0]["error"]


@pytest.mark.asyncio
async def test_a_partial_failure_response_dead_letters() -> None:
    """PutEvents answers 200 with per-entry failures. A non-raising call is not success."""
    pub, _, sink = make(
        response={
            "FailedEntryCount": 1,
            "Entries": [{"ErrorCode": "ThrottlingException", "ErrorMessage": "rate exceeded"}],
        }
    )
    assert await pub.publish("alerts", ENVELOPE) is False
    assert "ThrottlingException" in sink[0]["error"]
    assert "rate exceeded" in sink[0]["error"]


@pytest.mark.asyncio
async def test_an_oversized_entry_dead_letters_before_the_call() -> None:
    pub, client, sink = make()
    huge = {**ENVELOPE, "payload": {"blob": "x" * (MAX_ENTRY_BYTES + 1)}}
    assert await pub.publish("alerts", huge) is False
    assert client.entries == [], "an entry known to be over the limit should not be sent"
    assert "over the" in sink[0]["error"]


@pytest.mark.asyncio
async def test_the_dead_lettered_payload_is_the_envelope() -> None:
    pub, _, sink = make(raises=RuntimeError("boom"))
    await pub.publish("alerts", ENVELOPE, key="patient-7")
    assert json.loads(sink[0]["payload"])["event_id"] == "evt-1"
    assert sink[0]["key"] == "patient-7"
    assert sink[0]["retry_count"] == 0


@pytest.mark.asyncio
async def test_no_dlq_configured_raises_rather_than_losing_the_event() -> None:
    """Silently logging here is how the six unprotected publish sites lost events."""
    pub = EventBridgePublisher(FakeClient(raises=RuntimeError("boom")), "ocean-bus", None)
    with pytest.raises(PublishError, match="event lost"):
        await pub.publish("alerts", ENVELOPE)
