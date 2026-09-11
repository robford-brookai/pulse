"""The standalone relay loop's observables: the `relay_pass` log line and scan-state threading.

`run_forever` is glue — `relay_fair_pass` (relay-fairness 1.2) in a loop — so the promises worth
pinning are that the line an operator reads carries the counts *and* the ADR-0004 D17 lag gauge
(twenty-projection 4.2 deployed the worker and found the gauge computed but never logged; this
pins the fix), and that the `ScanState` a pass returns is what the *next* pass receives — a
fairness scan whose cursor gets discarded and restarted at the front every pass could never
complete a scan cycle, which is exactly the risk design.md calls out for this wiring.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

import pytest
from pulse_ledger import relay_worker
from pulse_ledger.relay import RelayPass, ScanState


class _StopLoop(Exception):
    """Raised from the stubbed sleep to end run_forever after one pass."""


def _run_one_pass(monkeypatch: pytest.MonkeyPatch, result: RelayPass) -> None:
    async def fake_relay_fair_pass(conn: Any, publisher: Any, state: ScanState) -> tuple[RelayPass, ScanState]:
        return result, state

    async def stop_sleep(_seconds: float) -> None:
        raise _StopLoop

    monkeypatch.setattr(relay_worker, "relay_fair_pass", fake_relay_fair_pass)
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


def test_scan_state_survives_from_one_pass_into_the_next(monkeypatch: pytest.MonkeyPatch) -> None:
    """A worker-loop regression test for design.md's named risk: fairness state discarded per pass.

    If `run_forever` rebuilt a fresh `ScanState()` each iteration instead of threading the one
    `relay_fair_pass` returned, every pass would resume at the front of the candidate set and a
    scan could never complete a cycle — this pins that it does not.
    """
    seen_states: list[ScanState] = []
    advanced = ScanState(cursor=("referral", "ref-a"))

    calls = 0

    async def fake_relay_fair_pass(conn: Any, publisher: Any, state: ScanState) -> tuple[RelayPass, ScanState]:
        nonlocal calls
        seen_states.append(state)
        calls += 1
        return RelayPass(), advanced

    async def stop_after_two(_seconds: float) -> None:
        if calls >= 2:
            raise _StopLoop

    monkeypatch.setattr(relay_worker, "relay_fair_pass", fake_relay_fair_pass)
    monkeypatch.setattr(relay_worker.asyncio, "sleep", stop_after_two)
    monkeypatch.setattr(relay_worker, "default_publisher", lambda: object())
    monkeypatch.setattr(
        relay_worker.psycopg,
        "connect",
        lambda *_args, **_kwargs: contextlib.nullcontext(object()),
    )

    with pytest.raises(_StopLoop):
        asyncio.run(relay_worker.run_forever("postgresql://unused"))

    assert seen_states[0] == ScanState(), "the first pass starts from a fresh cursor"
    assert seen_states[1] == advanced, "the second pass resumed from what the first pass returned"
