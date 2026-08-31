"""Outbound consume loop — the kit half every connector's write-back consumer stands on.

Extracted from `pulse_core.client` (design decision 6), where `consume(handler)` already served
one shipped consumer (`identity.service.consume_referrals`) besides the twenty-projection donor
this task refactors — `pulse_core.client` re-exports every name below unchanged so neither
importer's code moves. Two contracts live here (connector-kit spec: "Outbound consumption
follows the consume-loop contract"):

- **The rule+queue convention**: `consume`/`consume_once` wrap SQS receive → handler → delete,
  the EventBridge-rule-to-queue shape every connector's write-back side uses. A message deletes
  only once `handler` returns without raising — a failure is left for the queue's own
  visibility-timeout redelivery — and `event_id` dedupe (`InMemoryDeduper`) means a message
  redelivered within one run's lifetime is deleted without running `handler` again.
- **The monotonic watermark**, generalized from twenty-projection's per-record `projectionSeq`
  check: `is_watermark_stale` is the write-back guard that makes a redelivered event a no-op
  even *across* a crash and restart, when the in-process dedupe above has no memory of the first
  delivery — the correctness backstop the dedupe alone cannot provide.
"""

from __future__ import annotations

import dataclasses
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

ConsumerHandler = Callable[[Mapping[str, object]], None]
Sleeper = Callable[[float], None]


def _default_sleep(seconds: float) -> None:
    time.sleep(seconds)


class Deduper(Protocol):
    """Tracks which `event_id`s this consumer has already run `handler` for."""

    def seen(self, event_id: str) -> bool: ...

    def mark(self, event_id: str) -> None: ...


class InMemoryDeduper:
    """The default `Deduper`: good for one process's lifetime, gone on restart.

    A restart re-runs `handler` for whatever was in flight, which is exactly the at-least-once
    contract `handler` must already tolerate — this dedupe is an optimization against ordinary
    redelivery within one run, not a durability guarantee across runs. `is_watermark_stale`
    below is what a write-back needs for that guarantee.
    """

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def seen(self, event_id: str) -> bool:
        return event_id in self._seen

    def mark(self, event_id: str) -> None:
        self._seen.add(event_id)


def is_watermark_stale(seq: int, watermark: int | None) -> bool:
    """Whether an incoming sequence must not reapply to a target already at or ahead of it.

    `watermark` is the target's own persisted high-water mark for this record (`None` means it
    has never been written). A sequence at or below the watermark is a replay or an out-of-order
    redelivery — the write-back guard every connector's consume loop applies before writing, so a
    crash-and-restart redelivery is a no-op rather than a duplicate write, independent of any
    in-process dedupe.
    """
    return watermark is not None and seq <= watermark


@dataclass(frozen=True)
class ConsumeReport:
    """What one `consume_once` pass did, for logging and tests."""

    processed: int = 0
    deduped: int = 0
    failed: int = 0


def _envelope_from_body(body: object) -> dict[str, object] | None:
    """Extract the event envelope from a parsed SQS message body.

    An EventBridge rule delivers the envelope whole inside `detail`; a body with no `detail` key
    is accepted as a bare envelope so local tooling can send straight to the queue — the same
    convention `agent-worker`'s consumer uses.
    """
    if not isinstance(body, dict):
        return None
    detail = body.get("detail", body)
    return detail if isinstance(detail, dict) else None


def consume_once(
    handler: ConsumerHandler,
    *,
    sqs_client: Any,
    queue_url: str,
    deduper: Deduper,
    max_messages: int = 10,
    wait_time_seconds: int = 20,
) -> ConsumeReport:
    """One receive/process/delete pass against one SQS queue.

    A message is deleted only after `handler` returns without raising: a failure is left for the
    queue's own visibility-timeout redelivery and its DLQ redrive policy, never swallowed here. A
    message whose envelope's `event_id` this deduper has already seen is deleted *without* calling
    `handler` again — the point of the dedupe — and a malformed message (unparseable body, no
    envelope) is dropped rather than retried forever.
    """
    response = sqs_client.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=max_messages,
        WaitTimeSeconds=wait_time_seconds,
    )
    report = ConsumeReport()
    for message in response.get("Messages", []):
        receipt_handle = message.get("ReceiptHandle", "")
        try:
            body = json.loads(message["Body"])
        except (json.JSONDecodeError, KeyError):
            report = dataclasses.replace(report, failed=report.failed + 1)
            continue
        envelope = _envelope_from_body(body)
        if envelope is None:
            report = dataclasses.replace(report, failed=report.failed + 1)
            continue

        event_id = envelope.get("event_id")
        event_id_str = str(event_id) if event_id is not None else None
        if event_id_str is not None and deduper.seen(event_id_str):
            sqs_client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
            report = dataclasses.replace(report, deduped=report.deduped + 1)
            continue

        try:
            handler(envelope)
        except Exception:
            report = dataclasses.replace(report, failed=report.failed + 1)
            continue

        if event_id_str is not None:
            deduper.mark(event_id_str)
        sqs_client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
        report = dataclasses.replace(report, processed=report.processed + 1)
    return report


def consume(
    handler: ConsumerHandler,
    *,
    queue_url: str,
    sqs_client: Any = None,
    deduper: Deduper | None = None,
    max_messages: int = 10,
    wait_time_seconds: int = 20,
    error_backoff_seconds: float = 5.0,
    sleep: Sleeper = _default_sleep,
    iterations: int | None = None,
) -> None:
    """Run `consume_once` in a loop — forever, or `iterations` times for a bounded test run.

    `sqs_client` defaults to a real `boto3` client, imported lazily so importing this module never
    requires `boto3` to be installed; a test always supplies a fake one instead. A pass that raises
    (a transport error `receive_message`/`delete_message` didn't swallow itself) is logged nowhere
    here — the caller's own logging wraps `handler` — and backed off before the next attempt so a
    persistent outage does not spin the loop.
    """
    if sqs_client is None:
        import boto3

        sqs_client = boto3.client("sqs")
    active_deduper = deduper or InMemoryDeduper()

    count = 0
    while iterations is None or count < iterations:
        try:
            consume_once(
                handler,
                sqs_client=sqs_client,
                queue_url=queue_url,
                deduper=active_deduper,
                max_messages=max_messages,
                wait_time_seconds=wait_time_seconds,
            )
        except Exception:
            sleep(error_backoff_seconds)
        count += 1
