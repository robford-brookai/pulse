"""The standalone relay loop's one observable: the `relay_pass` log line.

`run_forever` is glue — `relay_once` in a loop — so the only promise worth pinning is that the
line an operator reads carries the counts *and* the ADR-0004 D17 lag gauge. twenty-projection 4.2
deployed the worker and found the gauge computed but never logged; this pins the fix.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

import pytest
from pulse_ledger import relay_worker
from pulse_ledger.relay import RelayPass


class _StopLoop(Exception):
    """Raised from the stubbed sleep to end run_forever after one pass."""


def _run_one_pass(monkeypatch: pytest.MonkeyPatch, result: RelayPass) -> None:
    async def fake_relay_once(conn: Any, publisher: Any) -> RelayPass:
        return result

    async def stop_sleep(_seconds: float) -> None:
        raise _StopLoop

    monkeypatch.setattr(relay_worker, "relay_once", fake_relay_once)
    monkeypatch.setattr(relay_worker.asyncio, "sleep", stop_sleep)
    monkeypatch.setattr(relay_worker, "default_publisher", lambda: object())
    monkeypatch.setattr(
        relay_worker.psycopg,
        "connect",
        lambda *_args, **_kwargs: contextlib.nullcontext(object()),
    )

    with pytest.raises(_StopLoop):
        asyncio.run(relay_worker.run_forever("postgresql://unused"))


def test_relay_pass_log_line_carries_the_lag_gauge(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="pulse_ledger.relay_worker"):
        _run_one_pass(monkeypatch, RelayPass(published=2, dead_lettered=1, max_lag_seconds=3.5))

    passes = [record for record in caplog.records if record.msg == "relay_pass"]
    assert len(passes) == 1
    record = passes[0]
    assert record.published == 2
    assert record.dead_lettered == 1
    assert record.max_lag_seconds == 3.5


def test_a_quiet_pass_logs_nothing(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="pulse_ledger.relay_worker"):
        _run_one_pass(monkeypatch, RelayPass())

    assert not [record for record in caplog.records if record.msg == "relay_pass"]
