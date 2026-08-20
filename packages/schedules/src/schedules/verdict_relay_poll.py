"""Verdict-relay poll job (task 3.1, spec verdict-relay-trigger): the schedules-package entry
that approximates "run after every mart refresh" with a frequent scheduled poll rather than a
cross-repo trigger (billing-state design decision 6).

`run_verdict_relay_poll_job` is a thin wrapper over `verdict_relay.run.run_relay`: it prints the
run's `RunReceipt` as one JSON line — the schedules-package-native receipt contract
`run_month_open_job` / `run_consent_sweep_job` already follow (design decision 6: "Receipts are
structured (JSON to stdout)") — and returns the run's own exit code. Because declaration is
idempotent (D16), the cursor is durable, and stale rows skip against the watermark
(verdict_relay design decisions 2-3), a poll that finds nothing new past the cursor is already a
no-op run: zero declarations, an all-zero-count receipt, exit zero (spec: "A no-op poll exits
clean"); an immediate rerun right after a completed batch is all replays and stale-skips with zero
new events (spec: "An extra run after a completed run changes nothing"). Both are `run_relay`'s
own semantics — this module adds no new run behavior, only the schedules-package entry point.

`run_relay` already logs the service's own structured, no-PHI records; this job's printed receipt
carries the same seven counts and the failure detail (row keys only, never a credential or a
verdict value), so nothing here can leak more than `run_relay` already guards against.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import TextIO

from verdict_relay.declarer import Declarer
from verdict_relay.mart_reader import MartReader
from verdict_relay.run import run_relay


def run_verdict_relay_poll_job(reader: MartReader, declarer: Declarer, *, stream: TextIO) -> int:
    """Run one verdict-relay poll, print its receipt as JSON, and return the process exit code."""
    receipt = run_relay(reader, declarer)
    print(json.dumps(asdict(receipt)), file=stream)
    return 0 if receipt.succeeded else 1
