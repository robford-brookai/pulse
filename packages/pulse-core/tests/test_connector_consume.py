"""`pulse_core.connector.consume` — the outbound consume-loop contract (task 2.3).

Pins the connector-kit spec scenario this task owns: "A redelivered event applies once". The
in-process `InMemoryDeduper` only protects one run's lifetime (`pulse_core.client`'s own docs),
so the scenario that matters for a *crashed* run is the watermark backstop: a target write-back
guarded by `is_watermark_stale` applies exactly once even when the second delivery lands in a
fresh process with no memory of the first — the twenty-projection pattern generalized.

`consume`/`consume_once`/`InMemoryDeduper`/`ConsumeReport` themselves are exercised in full by
`pulse-core/tests/test_client.py` (unchanged, re-exported from `pulse_core.client` for existing
importers); this file only adds what is new to the kit surface.
"""

from __future__ import annotations

import json
from typing import Any

from pulse_core.connector import ConsumeReport, InMemoryDeduper, consume_once, is_watermark_stale


def _message(receipt: str, event_id: str, seq: int) -> dict[str, Any]:
    return {
        "ReceiptHandle": receipt,
        "Body": json.dumps({"event_id": event_id, "seq": seq}),
    }


class _FakeSqs:
    """One scripted delivery batch; `delete_message` is recorded, never actually removes it."""

    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self._messages = messages
        self.deleted: list[str] = []

    def receive_message(self, **_kwargs: Any) -> dict[str, Any]:
        return {"Messages": list(self._messages)}

    def delete_message(self, *, QueueUrl: str, ReceiptHandle: str) -> None:
        self.deleted.append(ReceiptHandle)


class _WatermarkedTarget:
    """A fake write-back target: one record, one watermark, guarded by `is_watermark_stale`."""

    def __init__(self) -> None:
        self.watermark: int | None = None
        self.writes: list[int] = []

    def apply(self, envelope: dict[str, Any]) -> None:
        seq = envelope["seq"]
        if is_watermark_stale(seq, self.watermark):
            return
        self.writes.append(seq)
        self.watermark = seq


def test_a_redelivered_event_applies_once() -> None:
    """Two deliveries of the same committed event, each processed by a fresh dedupe (a crashed
    and restarted run has no memory of the first pass): the watermark guard still applies the
    write-back exactly once, and both deliveries are deleted as consumed."""
    envelope = _message("rh-1", "evt-dup", seq=5)
    target = _WatermarkedTarget()

    first_pass = _FakeSqs([envelope])
    report_one = consume_once(target.apply, sqs_client=first_pass, queue_url="q", deduper=InMemoryDeduper())

    # Simulate a crash and restart: a brand-new process, brand-new in-memory dedupe, the same
    # message redelivered by the queue.
    second_pass = _FakeSqs([envelope])
    report_two = consume_once(target.apply, sqs_client=second_pass, queue_url="q", deduper=InMemoryDeduper())

    assert report_one == ConsumeReport(processed=1, deduped=0, failed=0)
    assert report_two == ConsumeReport(processed=1, deduped=0, failed=0)
    assert target.writes == [5]
    assert first_pass.deleted == ["rh-1"]
    assert second_pass.deleted == ["rh-1"]


def test_is_watermark_stale_is_inclusive_of_the_boundary() -> None:
    """A sequence at or below the watermark is stale; a `None` watermark means never applied."""
    assert is_watermark_stale(5, None) is False
    assert is_watermark_stale(5, 4) is False
    assert is_watermark_stale(5, 5) is True
    assert is_watermark_stale(5, 6) is True
