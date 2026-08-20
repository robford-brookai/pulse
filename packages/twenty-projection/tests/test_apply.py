"""The apply core's whole correctness story, against a fixture REST transport.

Pins the twenty-projection spec scenarios owned by task 2.1: a committed enrollment event
writes the full board state — encoded status, as-of from the event's effective time, and the
watermark — in one PATCH ("Drift converges on the next event"); an event at or below the
record's watermark is a logged no-op that never writes ("A late event never regresses the
board"); and watermarks advance per subject ("Watermarks are per subject"). Unresolvable
subjects and failed writes raise typed errors only — parking and payload-free retry logging
are task 2.2's scope, but the error types themselves must already never carry payload content.

All data is synthetic: spine IDs and program codes only, never a name or demographic.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from twenty_projection.apply import (
    AmbiguousSubjectError,
    Applied,
    MalformedEventError,
    ProjectionRestClient,
    ProjectionWriteError,
    SkippedStale,
    SubjectUnresolvedError,
    apply_event,
)

PLURAL = "patientPrograms"


class FixtureTwenty:
    """An in-memory Twenty core REST surface: filtered GET listing plus PATCH by id.

    Mirrors the pinned conventions (`docs/contracts/consumes.md`): `filter=<field>[eq]:<value>`
    comma-joined AND, records listed under `data.<plural>`, a PATCH answered under
    `data.updatePatientProgram`. Records every request so tests can assert what was (not) written.
    """

    def __init__(self, records: list[dict[str, Any]], *, patch_status: int = 200) -> None:
        self.records = {str(record["id"]): dict(record) for record in records}
        self.patch_status = patch_status
        self.patches: list[tuple[str, dict[str, Any]]] = []
        self.get_queries: list[str] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = urlparse(str(request.url)).path
        if request.method == "GET" and path == f"/rest/{PLURAL}":
            return self._list(request)
        if request.method == "PATCH" and path.startswith(f"/rest/{PLURAL}/"):
            return self._patch(request, path.rsplit("/", 1)[1])
        return httpx.Response(404, json={})

    def _list(self, request: httpx.Request) -> httpx.Response:
        params = parse_qs(urlparse(str(request.url)).query)
        raw_filter = params.get("filter", [""])[0]
        self.get_queries.append(raw_filter)
        predicates: dict[str, str] = {}
        for predicate in raw_filter.split(","):
            field, _, value = predicate.partition("[eq]:")
            predicates[field] = value
        matches = [
            record
            for record in self.records.values()
            if all(str(record.get(field)) == value for field, value in predicates.items())
        ]
        limit = int(params.get("limit", ["10"])[0])
        return httpx.Response(200, json={"data": {PLURAL: matches[:limit]}})

    def _patch(self, request: httpx.Request, record_id: str) -> httpx.Response:
        if self.patch_status >= 400:
            # A synthetic record value in the failure body: the typed error must not carry it.
            return httpx.Response(self.patch_status, json={"error": "value 'synthetic-record-value' refused"})
        fields = json.loads(request.content)
        self.patches.append((record_id, fields))
        self.records[record_id].update(fields)
        return httpx.Response(200, json={"data": {"updatePatientProgram": dict(self.records[record_id])}})


def board_record(
    record_id: str = "rec-1",
    *,
    subject: str = "pt-0001",
    program: str = "CCM",
    status: str = "PENDING_START",
    watermark: int | None = None,
) -> dict[str, Any]:
    return {
        "id": record_id,
        "canonicalPatientId": subject,
        "programCode": program,
        "lifecycleStatus": status,
        "lifecycleStatusAsOf": "2026-08-01T00:00:00+00:00",
        "projectionSeq": watermark,
    }


def enrollment_event(
    *,
    subject: str = "pt-0001",
    program: str = "CCM",
    to_state: str = "active",
    seq: int = 1,
    event_id: str = "evt-1",
    effective_at: str = "2026-08-18T12:00:00+00:00",
) -> dict[str, Any]:
    """A committed enrollment envelope as the relay publishes it (relay.py `_envelope`)."""
    return {
        "event_id": event_id,
        "event_type": "enrollment.declared",
        "subject_type": "enrollment",
        "subject_key": subject,
        "seq": seq,
        "effective_at": effective_at,
        "payload": {"to_state": to_state, "program": program},
    }


def make_client(fixture: FixtureTwenty) -> ProjectionRestClient:
    token = "fixture-token"  # noqa: S105 — a fixture placeholder, not a credential
    return ProjectionRestClient("https://twenty.fixture", token=token, transport=fixture.transport())


def test_apply_writes_all_three_fields_encoded_in_one_patch() -> None:
    fixture = FixtureTwenty([board_record(watermark=None)])
    with make_client(fixture) as client:
        result = apply_event(enrollment_event(seq=4), client=client)

    assert isinstance(result, Applied)
    assert fixture.patches == [
        (
            "rec-1",
            {
                "lifecycleStatus": "ACTIVE",
                "lifecycleStatusAsOf": "2026-08-18T12:00:00+00:00",
                "projectionSeq": 4,
            },
        )
    ]


def test_subject_resolves_on_both_denormalized_columns() -> None:
    fixture = FixtureTwenty([
        board_record("rec-ccm", program="CCM", watermark=None),
        board_record("rec-rpm", program="RPM", watermark=None),
    ])
    with make_client(fixture) as client:
        apply_event(enrollment_event(program="RPM", seq=2), client=client)

    assert fixture.get_queries == ["canonicalPatientId[eq]:pt-0001,programCode[eq]:RPM"]
    assert [record_id for record_id, _ in fixture.patches] == ["rec-rpm"]


@pytest.mark.parametrize("seq", [7, 6])
def test_at_or_below_watermark_is_a_logged_noop_without_a_write(seq: int, caplog: pytest.LogCaptureFixture) -> None:
    """Spec: A late event never regresses the board."""
    fixture = FixtureTwenty([board_record(watermark=7)])
    with make_client(fixture) as client, caplog.at_level("INFO", logger="twenty_projection.apply"):
        result = apply_event(enrollment_event(seq=seq, event_id="evt-late"), client=client)

    assert isinstance(result, SkippedStale)
    assert result.seq == seq
    assert result.watermark == 7
    assert fixture.patches == []

    noop_lines = [record.getMessage() for record in caplog.records]
    assert len(noop_lines) == 1
    line = noop_lines[0]
    # Subject and sequences only: identifiers present, payload values absent.
    assert "pt-0001" in line
    assert str(seq) in line
    assert "7" in line
    assert "active" not in line
    assert "2026-08-18T12:00:00" not in line


def test_watermarks_are_per_subject() -> None:
    """Spec: Watermarks are per subject — interleaved events never cross-suppress."""
    fixture = FixtureTwenty([
        board_record("rec-a", subject="pt-000a", watermark=5),
        board_record("rec-b", subject="pt-000b", watermark=2),
    ])
    with make_client(fixture) as client:
        first = apply_event(enrollment_event(subject="pt-000a", seq=6, event_id="evt-a6"), client=client)
        second = apply_event(enrollment_event(subject="pt-000b", seq=3, event_id="evt-b3"), client=client)
        # pt-000a is now at 6; a seq-4 event for it is stale even though pt-000b sits at 3.
        third = apply_event(enrollment_event(subject="pt-000a", seq=4, event_id="evt-a4"), client=client)

    assert isinstance(first, Applied)
    assert isinstance(second, Applied)
    assert isinstance(third, SkippedStale)
    assert fixture.records["rec-a"]["projectionSeq"] == 6
    assert fixture.records["rec-b"]["projectionSeq"] == 3


def test_drift_converges_on_the_next_event() -> None:
    """Spec: Drift converges on the next event — the full-state write erases out-of-band edits."""
    drifted = board_record(status="ENDED", watermark=5)  # moved out of band; ledger says active
    fixture = FixtureTwenty([drifted])
    with make_client(fixture) as client:
        result = apply_event(enrollment_event(to_state="active", seq=6), client=client)

    assert isinstance(result, Applied)
    assert fixture.records["rec-1"]["lifecycleStatus"] == "ACTIVE"
    assert fixture.records["rec-1"]["lifecycleStatusAsOf"] == "2026-08-18T12:00:00+00:00"
    assert fixture.records["rec-1"]["projectionSeq"] == 6


def test_unresolvable_subject_raises_typed_error_naming_identifiers_only() -> None:
    fixture = FixtureTwenty([])
    with make_client(fixture) as client, pytest.raises(SubjectUnresolvedError) as excinfo:
        apply_event(enrollment_event(), client=client)

    assert excinfo.value.subject_key == "pt-0001"
    assert excinfo.value.program == "CCM"
    assert "active" not in str(excinfo.value)
    assert fixture.patches == []


def test_ambiguous_subject_raises_typed_error() -> None:
    fixture = FixtureTwenty([board_record("rec-1", watermark=None), board_record("rec-dup", watermark=None)])
    with make_client(fixture) as client, pytest.raises(AmbiguousSubjectError):
        apply_event(enrollment_event(), client=client)
    assert fixture.patches == []


def test_failed_write_raises_typed_error_without_body_content() -> None:
    fixture = FixtureTwenty([board_record(watermark=None)], patch_status=500)
    with make_client(fixture) as client, pytest.raises(ProjectionWriteError) as excinfo:
        apply_event(enrollment_event(seq=2), client=client)

    assert excinfo.value.status_code == 500
    assert "synthetic-record-value" not in str(excinfo.value)


def _without(envelope: dict[str, Any], key: str) -> dict[str, Any]:
    return {name: value for name, value in envelope.items() if name != key}


def _payload_without(envelope: dict[str, Any], key: str) -> dict[str, Any]:
    payload = dict(envelope["payload"])
    payload.pop(key)
    return {**envelope, "payload": payload}


@pytest.mark.parametrize(
    ("overrides", "dropped", "field_path"),
    [
        ({}, "subject_key", "subject_key"),
        ({"subject_type": "consent"}, None, "subject_type"),
        ({"seq": "4"}, None, "seq"),
        ({}, "payload.to_state", "payload.to_state"),
        ({}, "payload.program", "payload.program"),
        ({"effective_at": "2026-08-18T12:00:00"}, None, "effective_at"),
        ({"subject_key": "pt,0001"}, None, "subject_key"),
    ],
)
def test_malformed_envelope_raises_typed_error(overrides: dict[str, Any], dropped: str | None, field_path: str) -> None:
    envelope = {**enrollment_event(), **overrides}
    if dropped is not None and dropped.startswith("payload."):
        envelope = _payload_without(envelope, dropped.removeprefix("payload."))
    elif dropped is not None:
        envelope = _without(envelope, dropped)
    fixture = FixtureTwenty([board_record(watermark=None)])
    with make_client(fixture) as client, pytest.raises(MalformedEventError) as excinfo:
        apply_event(envelope, client=client)

    assert excinfo.value.field_path == field_path
    assert fixture.patches == []
