"""The handling layer around the apply core: orphan parking and payload-free write failure.

Pins the twenty-projection spec scenarios owned by task 2.2: an event whose subject resolves
to no board record parks — processing completes, the orphan count increments, and the log line
carries the subject key and event id only ("An orphan event parks cleanly"); a failed REST
write retries with capped backoff and then surfaces with no payload content in any log line or
metric, against a scripted failure body carrying a synthetic record value ("A failed write
logs no payload").

All data is synthetic: spine IDs and program codes only, never a name or demographic.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from twenty_projection.apply import Applied, ProjectionRestClient, ProjectionWriteError
from twenty_projection.handling import Parked, ProjectionMetrics, handle_event

PLURAL = "patientPrograms"

#: The synthetic record value every scripted failure body carries; no log line or metric may.
SYNTHETIC_BODY_VALUE = "synthetic-record-value"


class ScriptedTwenty:
    """A fixture Twenty whose PATCH answers follow a script of status codes.

    The listing side mirrors `FixtureTwenty` in `test_apply.py` (pinned filter grammar,
    `data.<plural>` shape). Every failing PATCH body carries `SYNTHETIC_BODY_VALUE`, so any
    handling code that reads a failure body into a log or metric fails the payload assertions.
    An empty script means every PATCH succeeds.
    """

    def __init__(self, records: list[dict[str, Any]], *, patch_script: list[int] | None = None) -> None:
        self.records = {str(record["id"]): dict(record) for record in records}
        self.patch_script = list(patch_script or [])
        self.patch_attempts = 0
        self.patches: list[tuple[str, dict[str, Any]]] = []

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
        self.patch_attempts += 1
        if self.patch_script:
            status = self.patch_script.pop(0)
            if status >= 400:
                return httpx.Response(status, json={"error": f"value '{SYNTHETIC_BODY_VALUE}' refused"})
        fields = json.loads(request.content)
        self.patches.append((record_id, fields))
        self.records[record_id].update(fields)
        return httpx.Response(200, json={"data": {"updatePatientProgram": dict(self.records[record_id])}})


def board_record(
    record_id: str = "rec-1",
    *,
    subject: str = "pt-0001",
    program: str = "CCM",
    watermark: int | None = None,
) -> dict[str, Any]:
    return {
        "id": record_id,
        "canonicalPatientId": subject,
        "programCode": program,
        "lifecycleStatus": "PENDING_START",
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
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "event_type": "enrollment.declared",
        "subject_type": "enrollment",
        "subject_key": subject,
        "seq": seq,
        "effective_at": "2026-08-18T12:00:00+00:00",
        "payload": {"to_state": to_state, "program": program},
    }


def make_rest_client(fixture: ScriptedTwenty) -> ProjectionRestClient:
    token = "fixture-token"  # noqa: S105 — a fixture placeholder, not a credential
    return ProjectionRestClient("https://twenty.fixture", token=token, transport=fixture.transport())


def all_log_text(caplog: pytest.LogCaptureFixture) -> str:
    """Every captured line, attached exception text included, so nothing logged escapes the
    payload assertions."""
    parts: list[str] = []
    for record in caplog.records:
        parts.append(record.getMessage())
        if record.exc_info and record.exc_info[1] is not None:
            parts.append(repr(record.exc_info[1]))
    return "\n".join(parts)


def test_orphan_event_parks_cleanly(caplog: pytest.LogCaptureFixture) -> None:
    """Spec: An orphan event parks cleanly — completes, counts, logs identifiers only."""
    fixture = ScriptedTwenty([])
    metrics = ProjectionMetrics()
    with make_rest_client(fixture) as client, caplog.at_level("DEBUG", logger="twenty_projection.handling"):
        result = handle_event(enrollment_event(event_id="evt-orphan"), client=client, metrics=metrics)

    assert isinstance(result, Parked)
    assert result.subject_key == "pt-0001"
    assert result.event_id == "evt-orphan"
    assert metrics.orphans_parked == 1
    assert fixture.patches == []

    park_lines = [record.getMessage() for record in caplog.records]
    assert len(park_lines) == 1
    line = park_lines[0]
    # The subject key and event id, and nothing from the payload.
    assert "pt-0001" in line
    assert "evt-orphan" in line
    assert "active" not in line
    assert "2026-08-18T12:00:00" not in line


def test_orphan_does_not_block_subsequent_events() -> None:
    """Parking is per event: the consumer keeps applying after an orphan."""
    fixture = ScriptedTwenty([board_record(subject="pt-000b", watermark=None)])
    metrics = ProjectionMetrics()
    with make_rest_client(fixture) as client:
        parked = handle_event(enrollment_event(subject="pt-000a", event_id="evt-a"), client=client, metrics=metrics)
        applied = handle_event(enrollment_event(subject="pt-000b", event_id="evt-b"), client=client, metrics=metrics)

    assert isinstance(parked, Parked)
    assert isinstance(applied, Applied)
    assert metrics.orphans_parked == 1
    assert [record_id for record_id, _ in fixture.patches] == ["rec-1"]


def test_failed_write_retries_then_surfaces_without_payload(caplog: pytest.LogCaptureFixture) -> None:
    """Spec: A failed write logs no payload — retried, surfaced, body value nowhere."""
    fixture = ScriptedTwenty([board_record(watermark=None)], patch_script=[500, 500, 500, 500])
    metrics = ProjectionMetrics()
    slept: list[float] = []
    with (
        make_rest_client(fixture) as client,
        caplog.at_level("DEBUG"),
        pytest.raises(ProjectionWriteError) as excinfo,
    ):
        handle_event(
            enrollment_event(event_id="evt-fail"),
            client=client,
            metrics=metrics,
            max_attempts=3,
            sleep=slept.append,
        )

    assert fixture.patch_attempts == 3
    assert len(slept) == 2  # a sleep between attempts, none after the last
    assert metrics.write_failures == 1
    assert excinfo.value.status_code == 500

    logged = all_log_text(caplog)
    assert SYNTHETIC_BODY_VALUE not in logged
    assert SYNTHETIC_BODY_VALUE not in str(excinfo.value)
    # The surfaced failure names the record and event, never payload values.
    assert "evt-fail" in logged
    assert "active" not in logged
    assert "2026-08-18T12:00:00" not in logged


def test_transient_write_failure_recovers_without_surfacing(caplog: pytest.LogCaptureFixture) -> None:
    fixture = ScriptedTwenty([board_record(watermark=None)], patch_script=[500])
    metrics = ProjectionMetrics()
    slept: list[float] = []
    with make_rest_client(fixture) as client, caplog.at_level("DEBUG"):
        result = handle_event(
            enrollment_event(seq=3),
            client=client,
            metrics=metrics,
            max_attempts=3,
            sleep=slept.append,
        )

    assert isinstance(result, Applied)
    assert fixture.patch_attempts == 2
    assert len(slept) == 1
    assert metrics.write_failures == 0
    assert fixture.records["rec-1"]["projectionSeq"] == 3
    assert SYNTHETIC_BODY_VALUE not in all_log_text(caplog)


def test_non_retryable_write_surfaces_immediately(caplog: pytest.LogCaptureFixture) -> None:
    """A 4xx answer is not a transient fault: no retry, no sleep, one surfaced failure."""
    fixture = ScriptedTwenty([board_record(watermark=None)], patch_script=[400])
    metrics = ProjectionMetrics()
    slept: list[float] = []
    with (
        make_rest_client(fixture) as client,
        caplog.at_level("DEBUG"),
        pytest.raises(ProjectionWriteError) as excinfo,
    ):
        handle_event(
            enrollment_event(),
            client=client,
            metrics=metrics,
            max_attempts=3,
            sleep=slept.append,
        )

    assert fixture.patch_attempts == 1
    assert slept == []
    assert metrics.write_failures == 1
    assert excinfo.value.status_code == 400
    assert SYNTHETIC_BODY_VALUE not in all_log_text(caplog)


def test_metrics_carry_counts_only() -> None:
    """The metric surface is counters — nothing stringly a payload value could ride in on."""
    metrics = ProjectionMetrics()
    assert all(isinstance(value, int) for value in vars(metrics).values())
