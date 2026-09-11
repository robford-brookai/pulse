"""Transport reorder, duplicate ids, and late redrive at the projection boundary (task 2.2).

The relay-fairness spec's publication-order guarantee is a *publisher* contract, not a promise
about what a subscriber sees arrive: "Consumers dedupe on `event_id`... its manual redrive SHALL
be treated as a possible late delivery by consumers" and "Transport reorder and late redrive
preserve projection correctness" (spec: "subscriber arrival order is not assumed"). This file
proves the existing projection boundary already honors that — the relay may publish 1, 2, 3 in
order and a subscriber can still observe 3, 1, 2, a duplicate `event_id`, or a redrive of an
event older than what has already landed — and that two independent mechanisms, not one, are
what preserve correctness:

- **In-process dedupe** (`pulse_core.connector.InMemoryDeduper`, wired by `consume_once`): a
  message whose `event_id` this run has already seen is deleted without calling the handler
  again. Gone on restart — an optimization against ordinary redelivery, not a durability
  guarantee.
- **The monotonic watermark** (`apply_event`'s `is_watermark_stale` check against the board's
  `projectionSeq`): a lower-or-equal `seq` is a no-op *write*, independent of the deduper's
  memory. This is the backstop that holds even when the in-process dedupe has forgotten
  everything — across a crash and restart, or simply because a stale event's `event_id` was
  never seen before (a genuine reorder, not a redelivery).

No production code changes: the existing contract already holds under every interleaving below.

All data is synthetic: spine IDs and program codes only. The queue and the Twenty REST surface
are both fixtures — sockets are blocked by conftest.py.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from twenty_projection.apply import ProjectionRestClient
from twenty_projection.consumer import ConsumerConfig, run

PLURAL = "patientPrograms"
QUEUE_URL = "https://sqs.fixture/000000000000/twenty-projection"


# --- Fixtures: a scripted queue and a scripted Twenty sharing one journal ------------------------
# (Same shape as test_consumer.py's fixtures — kept local so this file proves the contract on its
# own, without importing another test module's helpers as production surface.)


class FixtureQueue:
    """A fake SQS client: scripted delivery batches, deletions recorded into a shared journal."""

    def __init__(self, deliveries: list[list[dict[str, Any]]], journal: list[tuple[str, str]]) -> None:
        self.deliveries = [list(batch) for batch in deliveries]
        self.journal = journal

    def receive_message(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["QueueUrl"] == QUEUE_URL
        batch = self.deliveries.pop(0) if self.deliveries else []
        return {"Messages": batch}

    def delete_message(self, **kwargs: Any) -> None:
        assert kwargs["QueueUrl"] == QUEUE_URL
        self.journal.append(("delete", kwargs["ReceiptHandle"]))


class FixtureTwenty:
    """A fake Twenty REST surface: filtered listing, PATCHes journaled onto one record store."""

    def __init__(self, records: list[dict[str, Any]], journal: list[tuple[str, str]]) -> None:
        self.records = {str(record["id"]): dict(record) for record in records}
        self.journal = journal
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
        fields = json.loads(request.content)
        self.patches.append((record_id, fields))
        self.journal.append(("patch", record_id))
        self.records[record_id].update(fields)
        return httpx.Response(200, json={"data": {"updatePatientProgram": dict(self.records[record_id])}})


def board_record(record_id: str = "rec-1", *, subject: str = "pt-0001", program: str = "CCM") -> dict[str, Any]:
    return {
        "id": record_id,
        "canonicalPatientId": subject,
        "programCode": program,
        "lifecycleStatus": "PENDING_START",
        "lifecycleStatusAsOf": "2026-08-01T00:00:00+00:00",
        "projectionSeq": None,
    }


def enrollment_envelope(
    *,
    subject: str = "pt-0001",
    program: str = "CCM",
    to_state: str = "active",
    seq: int = 1,
    event_id: str = "evt-1",
    effective_at: str = "2026-08-18T12:00:00+00:00",
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "event_type": "enrollment.declared",
        "subject_type": "enrollment",
        "subject_key": subject,
        "seq": seq,
        "effective_at": effective_at,
        "payload": {"to_state": to_state, "program": program},
    }


def queue_message(envelope: dict[str, Any], *, receipt: str) -> dict[str, Any]:
    """An EventBridge-delivered message: the envelope rides whole inside `detail`."""
    return {"Body": json.dumps({"detail": envelope}), "ReceiptHandle": receipt}


def fixture_config() -> ConsumerConfig:
    token = "fixture-token"  # noqa: S105 — a fixture placeholder, not a credential
    return ConsumerConfig(
        target="dev",
        twenty_url="https://twenty.fixture",
        twenty_token=token,
        queue_url=QUEUE_URL,
    )


def run_fixture(twenty: FixtureTwenty, queue: FixtureQueue, *, iterations: int) -> None:
    config = fixture_config()
    with ProjectionRestClient(config.twenty_url, token=config.twenty_token, transport=twenty.transport()) as client:
        run(config, client=client, sqs_client=queue, iterations=iterations)


# --- Scenario: Transport reorder and late redrive preserve projection correctness ----------------
#
# spec: openspec/changes/relay-fairness/specs/ledger-distribution/spec.md
# "GIVEN events delivered out of sequence, duplicate event ids, and an older manually redriven
#  event / WHEN existing projection consumers process these deliveries / THEN duplicate
#  suppression and each consumer's watermark/replay contract preserve the projection; subscriber
#  arrival order is not assumed"


def test_reordered_delivery_converges_on_the_highest_sequence() -> None:
    """seq 3 arrives before seq 1 and seq 2 (a transport reorder): the record ends at seq 3, and
    the later-arriving, lower-numbered events are no-ops, not overwrites."""
    journal: list[tuple[str, str]] = []
    twenty = FixtureTwenty([board_record()], journal)
    queue = FixtureQueue(
        [
            [queue_message(enrollment_envelope(event_id="evt-3", seq=3, to_state="active"), receipt="rh-3")],
            [queue_message(enrollment_envelope(event_id="evt-1", seq=1, to_state="pending"), receipt="rh-1")],
            [queue_message(enrollment_envelope(event_id="evt-2", seq=2, to_state="paused"), receipt="rh-2")],
        ],
        journal,
    )

    run_fixture(twenty, queue, iterations=3)

    # Only the highest sequence ever wrote — the two behind it were skipped as stale.
    assert len(twenty.patches) == 1
    record_id, fields = twenty.patches[0]
    assert record_id == "rec-1"
    assert fields["projectionSeq"] == 3
    assert fields["lifecycleStatus"] == "ACTIVE"
    # Every message still deletes: a stale event is a projection no-op, not a queue failure.
    assert journal == [
        ("patch", "rec-1"),
        ("delete", "rh-3"),
        ("delete", "rh-1"),
        ("delete", "rh-2"),
    ]
    # The board never regressed to a lower-sequence event's state.
    assert twenty.records["rec-1"]["lifecycleStatus"] == "ACTIVE"
    assert twenty.records["rec-1"]["projectionSeq"] == 3


def test_duplicate_event_id_within_one_run_applies_once() -> None:
    """The same `event_id` redelivered (e.g. a visibility-timeout re-receive) is deduped by the
    in-process deduper before it ever reaches the apply core a second time."""
    journal: list[tuple[str, str]] = []
    envelope = enrollment_envelope(event_id="evt-dup", seq=5)
    twenty = FixtureTwenty([board_record()], journal)
    queue = FixtureQueue(
        [
            [queue_message(envelope, receipt="rh-first")],
            [queue_message(envelope, receipt="rh-second")],
        ],
        journal,
    )

    run_fixture(twenty, queue, iterations=2)

    assert len(twenty.patches) == 1
    assert journal == [("patch", "rec-1"), ("delete", "rh-first"), ("delete", "rh-second")]


def test_late_manual_redrive_of_an_older_event_is_a_projection_no_op() -> None:
    """A dead-lettered row, manually redriven after later events already landed, carries a fresh
    `event_id` the in-process deduper has never seen — so the *watermark* check, not the deduper,
    is what must hold. The record must not regress to the redriven event's older state."""
    journal: list[tuple[str, str]] = []
    twenty = FixtureTwenty([board_record()], journal)
    queue = FixtureQueue(
        [
            # Normal delivery advances the board to seq 4 first.
            [queue_message(enrollment_envelope(event_id="evt-4", seq=4, to_state="active"), receipt="rh-4")],
            # A redrive of the dead-lettered seq-2 row arrives late, with its own distinct event_id
            # — the deduper has no memory of it, so only the watermark guard can catch it.
            [
                queue_message(
                    enrollment_envelope(event_id="evt-2-redrive", seq=2, to_state="paused"),
                    receipt="rh-2-redrive",
                )
            ],
        ],
        journal,
    )

    run_fixture(twenty, queue, iterations=2)

    assert len(twenty.patches) == 1  # the redrive never wrote
    assert twenty.records["rec-1"]["lifecycleStatus"] == "ACTIVE"
    assert twenty.records["rec-1"]["projectionSeq"] == 4
    # The redrive still consumes cleanly — it is a no-op, not a failure held on the queue.
    assert journal[-1] == ("delete", "rh-2-redrive")


def test_watermark_survives_process_restart_after_in_process_dedupe_is_lost() -> None:
    """`run()` starts a fresh `InMemoryDeduper` every call — the same reset a crash-and-restart
    produces. A second `run()` against the same board, redelivering an event the first run already
    applied, has no in-process memory of it and must rely on the watermark alone."""
    journal: list[tuple[str, str]] = []
    envelope = enrollment_envelope(event_id="evt-7", seq=7, to_state="active")
    twenty = FixtureTwenty([board_record()], journal)

    # First process: applies once, then "crashes" (loop exits, deduper discarded).
    first_run_queue = FixtureQueue([[queue_message(envelope, receipt="rh-before-restart")]], journal)
    run_fixture(twenty, first_run_queue, iterations=1)
    assert len(twenty.patches) == 1

    # Restart: a brand-new consumer process, fresh deduper, redelivered the very same message.
    second_run_queue = FixtureQueue([[queue_message(envelope, receipt="rh-after-restart")]], journal)
    run_fixture(twenty, second_run_queue, iterations=1)

    # Still exactly one write — the watermark, not the (now-forgotten) in-process dedupe, caught it.
    assert len(twenty.patches) == 1
    assert journal == [
        ("patch", "rec-1"),
        ("delete", "rh-before-restart"),
        ("delete", "rh-after-restart"),
    ]


def test_reorder_and_duplicates_on_independent_subjects_do_not_interfere() -> None:
    """Two subjects' events interleaved out of order: each subject's watermark is independent, so
    one subject's reorder cannot stall or corrupt the other's projected state."""
    journal: list[tuple[str, str]] = []
    twenty = FixtureTwenty(
        [board_record("rec-1", subject="pt-0001"), board_record("rec-2", subject="pt-0002")], journal
    )
    queue = FixtureQueue(
        [
            [
                queue_message(
                    enrollment_envelope(subject="pt-0002", event_id="evt-b2", seq=2, to_state="active"),
                    receipt="rh-b2",
                ),
                queue_message(
                    enrollment_envelope(subject="pt-0001", event_id="evt-a1", seq=1, to_state="pending"),
                    receipt="rh-a1",
                ),
            ],
            [
                queue_message(
                    enrollment_envelope(subject="pt-0001", event_id="evt-a1-dup", seq=1, to_state="pending"),
                    receipt="rh-a1-dup",
                ),
                queue_message(
                    enrollment_envelope(subject="pt-0002", event_id="evt-b1-late", seq=1, to_state="paused"),
                    receipt="rh-b1-late",
                ),
            ],
        ],
        journal,
    )

    run_fixture(twenty, queue, iterations=2)

    assert twenty.records["rec-1"]["projectionSeq"] == 1
    assert twenty.records["rec-1"]["lifecycleStatus"] == "PENDING"
    assert twenty.records["rec-2"]["projectionSeq"] == 2
    assert twenty.records["rec-2"]["lifecycleStatus"] == "ACTIVE"
    # One real write per subject: the duplicate and the late-lower-seq event were both no-ops.
    written_records = [record_id for record_id, _ in twenty.patches]
    assert written_records.count("rec-1") == 1
    assert written_records.count("rec-2") == 1
