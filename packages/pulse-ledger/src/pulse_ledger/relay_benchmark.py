"""Synthetic skewed-backlog benchmark for the relay's fairness pass (relay-fairness 3.1).

Design risk this closes (`design.md`): "[Extra head queries] -> benchmark and inspect query plans
on a skewed synthetic backlog." The spec's own acceptance scenario is
"Synthetic load receipt measures the finite scan bound" (`specs/ledger-distribution/spec.md`): a
recorded finite candidate count N, a subject examination budget B, a per-subject row budget, and a
continuously eligible unlocked target subject that a large early-sorting backlog must not starve.
The receipt this module produces is that scenario's evidence, not a new fairness mechanism —
`relay_fair_pass` (relay.py, tasks 1.1/1.2) is exercised as-is.

Bounded and offline by construction: every row is synthetic (`_declare` builds a `referral`
transition with a `synthetic` payload note), the target database is the same throwaway local
Postgres the rest of this package's tests use, and `_RecordingPublisher` never opens a socket — a
benchmark that touched the real bus would not be reproducible in CI and would not be a *query
plan and scheduling* measurement, which is what this task asks for.

Two workers are simulated as two independent `ScanState` cursors making alternating passes against
the same connection (`run_two_relay_benchmark`) rather than as real concurrent processes: the
concurrency guarantees themselves (lock ownership, stale-snapshot rereads) already have their own
proof in `test_relay_fairness_concurrency.py` (task 2.1). What this benchmark adds is progress
*and* backlog-drain evidence for two schedulers sharing one candidate set, which does not need
real threads to be meaningful and is far less flaky without them.

Run as a script against a scratch database:

    uv run --package pulse-ledger python -m pulse_ledger.relay_benchmark --database-url <dsn>

`--database-url` must point at an already-migrated, disposable database (see
`docs/runbooks/outbox-relay.md`); the benchmark seeds and reads a skewed backlog in it and never
touches the bus. Printed output is one JSON object per line, in the verdict-relay receipt style:
a machine-parsable summary meant to be pasted into HANDOFF.md or a design-review comment, not
committed anywhere durable.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg

from pulse_ledger import relay as relay_module
from pulse_ledger.commit import Declaration, commit_declaration
from pulse_ledger.relay import ScanState, candidate_subjects, pending_rows, relay_fair_pass

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

#: The target's subject key is chosen to sort after every early subject's zero-padded key under
#: plain string ordering (`candidate_subjects`'s `ORDER BY subject_type, subject_key`) — the same
#: sort-order starvation `test_relay_fairness.py` reproduces with `ref-zzz`, generalised to N.
_TARGET_SUBJECT_KEY = "bench-zzzz-target"


@dataclass(frozen=True)
class BenchmarkConfig:
    """The scenario's GIVEN: a recorded finite N, a positive B, a per-subject row budget."""

    #: N — total candidate subjects, the continuously eligible target included.
    n_subjects: int = 12
    #: B — subjects a scan_pass examines per pass (relay_fair_pass's subject_budget).
    subject_budget: int = 3
    #: Rows published per acquired subject per pass (relay_fair_pass's row_budget).
    row_budget: int = 5
    #: Rows seeded on each early-sorting subject — deliberately larger than row_budget so a single
    #: subject's backlog spans more than one visit, without being unbounded.
    early_backlog_rows: int = 4
    #: Rows seeded on the continuously eligible target subject.
    target_rows: int = 1


@dataclass(frozen=True)
class BenchmarkReceipt:
    """The scenario's THEN, recorded rather than merely asserted.

    `as_receipt_line` renders the `key=value` summary the relay runbook and HANDOFF quote —
    the same shape `docs/runbooks/verdict-relay.md` uses for its own receipt.
    """

    n_subjects: int
    subject_budget: int
    row_budget: int
    expected_passes: int
    observed_pass_target_visited: int | None
    target_visited: bool
    baseline_starves_target: bool
    publishes_per_pass: list[int] = field(default_factory=list)
    remaining_after_pass: list[int] = field(default_factory=list)
    published_by_worker: dict[str, int] = field(default_factory=dict)
    query_timing_seconds: dict[str, float] = field(default_factory=dict)
    query_plan_candidate_subjects: Any = None
    query_plan_baseline_limit: Any = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def as_receipt_line(self) -> str:
        fields = {
            "n_subjects": self.n_subjects,
            "subject_budget": self.subject_budget,
            "row_budget": self.row_budget,
            "expected_passes": self.expected_passes,
            "observed_pass_target_visited": self.observed_pass_target_visited,
            "target_visited": self.target_visited,
            "baseline_starves_target": self.baseline_starves_target,
            "backlog_drain": self.remaining_after_pass,
        }
        pairs = " ".join(f"{key}={value}" for key, value in fields.items())
        return f"service=relay-fairness-benchmark {pairs}"


@dataclass
class _RecordingPublisher:
    """A bus that always accepts, synchronously and offline — the benchmark measures scheduling
    and query behavior, not transport latency or failure handling (those are 1.2/2.1's tests)."""

    published: list[dict[str, Any]] = field(default_factory=list)

    async def publish(self, detail_type: str, event: dict[str, Any], key: str | None = None) -> None:
        self.published.append(event)


def _declare(subject_key: str, seq_state: str, effective_at: datetime) -> Declaration:
    return Declaration(
        subject_type="referral",
        subject_key=subject_key,
        event_type=f"referral.{seq_state}",
        to_state=seq_state,
        effective_at=effective_at,
        actor_type="system",
        actor_id="relay-fairness-benchmark",
        producer="pulse-ledger-relay-benchmark",
        payload={"note": "synthetic"},
    )


#: Legal forward transitions for the `referral` state machine, reused across seeded rows so a
#: subject with more than one row is a legal history rather than a single repeated event.
_REFERRAL_STATES = ("received", "resolved", "screened")


def seed_skewed_backlog(conn: psycopg.Connection, config: BenchmarkConfig) -> None:
    """Seed N-1 early-sorting subjects with a backlog, plus one late-sorting, continuously
    eligible, unlocked target subject — the scenario's GIVEN.
    """
    for index in range(config.n_subjects - 1):
        key = f"bench-early-{index:05d}"
        for row in range(min(config.early_backlog_rows, len(_REFERRAL_STATES))):
            commit_declaration(conn, _declare(key, _REFERRAL_STATES[row], T0 + timedelta(hours=row)))
    for row in range(min(config.target_rows, len(_REFERRAL_STATES))):
        commit_declaration(conn, _declare(_TARGET_SUBJECT_KEY, _REFERRAL_STATES[row], T0 + timedelta(hours=row)))


def _explain(conn: psycopg.Connection, sql: str, params: dict[str, Any] | None = None) -> Any:
    """`EXPLAIN (FORMAT JSON)` for one of the relay's own queries, parsed to plain Python data."""
    cursor = conn.execute(f"EXPLAIN (FORMAT JSON) {sql}", params or {})
    (plan,) = cursor.fetchone()  # type: ignore[misc]
    return json.loads(plan) if isinstance(plan, str) else plan


def _remaining_pending(conn: psycopg.Connection) -> int:
    row = conn.execute(
        "SELECT count(*) FROM ledger.outbox WHERE published_at IS NULL AND dead_lettered_at IS NULL"
    ).fetchone()
    return int(row[0])  # type: ignore[index]


def _target_published(publisher: _RecordingPublisher) -> bool:
    return any(event["subject_key"] == _TARGET_SUBJECT_KEY for event in publisher.published)


def run_two_relay_benchmark(conn: psycopg.Connection, config: BenchmarkConfig) -> BenchmarkReceipt:
    """Seed the skewed backlog, record the baseline and the query plans, then run two independent
    fairness-scheduled workers against the same candidate set until a complete scan cycle
    finishes, recording backlog drain and progress each pass — the scenario's WHEN and THEN.
    """
    seed_skewed_backlog(conn, config)

    query_timing: dict[str, float] = {}

    started = time.perf_counter()
    baseline_rows = pending_rows(conn, batch_size=config.row_budget)
    query_timing["baseline_limit_query_seconds"] = time.perf_counter() - started
    baseline_starves_target = _TARGET_SUBJECT_KEY not in {row.subject_key for row in baseline_rows}

    plan_baseline = _explain(conn, relay_module._SELECT_PENDING_SQL, {"batch_size": config.row_budget})
    plan_candidates = _explain(conn, relay_module._SELECT_CANDIDATE_SUBJECTS_SQL)

    subjects = candidate_subjects(conn)
    if len(subjects) != config.n_subjects:
        raise AssertionError(  # noqa: TRY003 — the count mismatch itself is the diagnostic
            f"expected {config.n_subjects} candidate subjects, seeded {len(subjects)}"
        )

    expected_passes = math.ceil(config.n_subjects / config.subject_budget)

    workers = {"relay-a": _RecordingPublisher(), "relay-b": _RecordingPublisher()}
    states = {name: ScanState() for name in workers}

    publishes_per_pass: list[int] = []
    remaining_after_pass: list[int] = []
    observed_pass_target_visited: int | None = None

    fair_pass_started = time.perf_counter()
    for pass_number in range(1, expected_passes + 1):
        published_this_pass = 0
        for name, publisher in workers.items():
            started_target_visited = _target_published(publisher)
            result, states[name] = _run(
                relay_fair_pass(
                    conn,
                    publisher,
                    states[name],
                    subject_budget=config.subject_budget,
                    row_budget=config.row_budget,
                    now=T0,
                )
            )
            published_this_pass += result.published
            if not started_target_visited and _target_published(publisher) and observed_pass_target_visited is None:
                observed_pass_target_visited = pass_number
        publishes_per_pass.append(published_this_pass)
        remaining_after_pass.append(_remaining_pending(conn))
    query_timing["two_relay_scan_cycle_seconds"] = time.perf_counter() - fair_pass_started

    target_visited = any(_target_published(publisher) for publisher in workers.values())

    return BenchmarkReceipt(
        n_subjects=config.n_subjects,
        subject_budget=config.subject_budget,
        row_budget=config.row_budget,
        expected_passes=expected_passes,
        observed_pass_target_visited=observed_pass_target_visited,
        target_visited=target_visited,
        baseline_starves_target=baseline_starves_target,
        publishes_per_pass=publishes_per_pass,
        remaining_after_pass=remaining_after_pass,
        published_by_worker={name: len(publisher.published) for name, publisher in workers.items()},
        query_timing_seconds=query_timing,
        query_plan_candidate_subjects=plan_candidates,
        query_plan_baseline_limit=plan_baseline,
    )


def _run(coro: Any) -> Any:
    """Run one `relay_fair_pass` coroutine to completion — this module's whole call site is sync."""
    return asyncio.run(coro)


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthetic skewed-backlog benchmark for the relay's fairness pass.")
    parser.add_argument(
        "--database-url", required=True, help="A plain postgresql:// DSN to an already-migrated, disposable database."
    )
    parser.add_argument("--n-subjects", type=int, default=BenchmarkConfig.n_subjects)
    parser.add_argument("--subject-budget", type=int, default=BenchmarkConfig.subject_budget)
    parser.add_argument("--row-budget", type=int, default=BenchmarkConfig.row_budget)
    parser.add_argument("--early-backlog-rows", type=int, default=BenchmarkConfig.early_backlog_rows)
    args = parser.parse_args()

    config = BenchmarkConfig(
        n_subjects=args.n_subjects,
        subject_budget=args.subject_budget,
        row_budget=args.row_budget,
        early_backlog_rows=args.early_backlog_rows,
    )
    with psycopg.connect(args.database_url, autocommit=True) as conn:
        receipt = run_two_relay_benchmark(conn, config)
    print(receipt.as_receipt_line())
    print(json.dumps(receipt.as_dict(), default=str))


if __name__ == "__main__":  # pragma: no cover
    main()
