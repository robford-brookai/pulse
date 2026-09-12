"""Task 3.1 — the synthetic skewed-backlog benchmark, and its bounded integration fixture.

Spec scenario (`ledger-distribution/Synthetic load receipt measures the finite scan bound`,
the only scenario `traceability.json` assigns to this task): a recorded finite candidate count N,
a positive subject examination budget B, a bounded per-subject row budget, and a continuously
eligible unlocked target subject that a large early-sorting backlog must not starve. Successive
passes over an unchanged candidate set, run by at least two workers, must visit the target within
`ceil(N / B)` passes, and the receipt records N, B, the row budget, observed passes, publish
counts, backlog-drain behavior and query timing — without claiming any wall-clock bound.

This is an evidence receipt for `relay_fair_pass` (relay.py, tasks 1.1/1.2), not a new fairness
mechanism: every assertion here exercises `pulse_ledger.relay_benchmark`, which itself only calls
already-tested relay code against a synthetic, offline, bounded fixture — no live network, no real
bus, the same throwaway local Postgres every other test in this package uses.
"""

from __future__ import annotations

import math

import psycopg
from pulse_ledger.relay_benchmark import (
    _TARGET_SUBJECT_KEY,
    BenchmarkConfig,
    run_two_relay_benchmark,
    seed_skewed_backlog,
)


def test_seed_skewed_backlog_produces_the_recorded_finite_candidate_set(ledger_db: psycopg.Connection) -> None:
    """N is recorded, not incidental: the fixture seeds exactly the configured candidate count,
    with the target sorting after every early subject."""
    from pulse_ledger.relay import candidate_subjects

    config = BenchmarkConfig(n_subjects=5, subject_budget=2, row_budget=3, early_backlog_rows=2)

    seed_skewed_backlog(ledger_db, config)

    subjects = candidate_subjects(ledger_db)
    assert len(subjects) == config.n_subjects
    assert subjects[-1] == ("referral", _TARGET_SUBJECT_KEY), "the target sorts last, same starvation shape as prod"


def test_baseline_limit_query_starves_the_target(ledger_db: psycopg.Connection) -> None:
    """Before comparing against the fairness pass, the receipt records that the pre-fairness
    baseline (`pending_rows`'s plain `ORDER BY ... LIMIT`) does starve the target — the same
    defect `test_relay_fairness.py` reproduces, restated here as this task's baseline evidence."""
    config = BenchmarkConfig(n_subjects=6, subject_budget=2, row_budget=3, early_backlog_rows=3)

    receipt = run_two_relay_benchmark(ledger_db, config)

    assert receipt.baseline_starves_target is True


def test_two_relay_benchmark_visits_the_target_within_the_ceil_bound(ledger_db: psycopg.Connection) -> None:
    """The scenario's THEN: at least two workers, sharing one unchanged candidate set, visit the
    continuously eligible target within `ceil(N / B)` passes."""
    config = BenchmarkConfig(n_subjects=10, subject_budget=3, row_budget=4, early_backlog_rows=4)
    expected_passes = math.ceil(config.n_subjects / config.subject_budget)

    receipt = run_two_relay_benchmark(ledger_db, config)

    assert receipt.expected_passes == expected_passes
    assert receipt.target_visited is True
    assert receipt.observed_pass_target_visited is not None
    assert receipt.observed_pass_target_visited <= expected_passes
    assert set(receipt.published_by_worker) == {"relay-a", "relay-b"}, "at least two workers ran the fixture"
    assert sum(receipt.published_by_worker.values()) > 0


def test_two_relay_benchmark_drains_the_backlog_across_passes(ledger_db: psycopg.Connection) -> None:
    """Backlog-drain behavior: the pending count is non-increasing pass over pass and strictly
    smaller than what was seeded by the time the scan cycle completes."""
    config = BenchmarkConfig(n_subjects=8, subject_budget=2, row_budget=5, early_backlog_rows=3, target_rows=1)
    total_rows_seeded = (config.n_subjects - 1) * config.early_backlog_rows + config.target_rows

    receipt = run_two_relay_benchmark(ledger_db, config)

    assert len(receipt.remaining_after_pass) == receipt.expected_passes
    for earlier, later in zip(receipt.remaining_after_pass, receipt.remaining_after_pass[1:], strict=False):
        assert later <= earlier, "backlog drain is never allowed to grow pass over pass"
    assert receipt.remaining_after_pass[-1] < total_rows_seeded, "the scan cycle actually drained the seeded backlog"


def test_receipt_records_query_plan_budgets_and_timing_without_a_wallclock_claim(
    ledger_db: psycopg.Connection,
) -> None:
    """The receipt's recorded fields: N, B, the row budget, observed passes, publish counts,
    backlog drain, and query timing/plans — the scenario's evidence bar, not a runtime guarantee."""
    config = BenchmarkConfig(n_subjects=6, subject_budget=2, row_budget=3, early_backlog_rows=2)

    receipt = run_two_relay_benchmark(ledger_db, config)

    assert receipt.n_subjects == config.n_subjects
    assert receipt.subject_budget == config.subject_budget
    assert receipt.row_budget == config.row_budget
    assert len(receipt.publishes_per_pass) == receipt.expected_passes
    assert receipt.query_timing_seconds.keys() == {"baseline_limit_query_seconds", "two_relay_scan_cycle_seconds"}
    assert all(seconds >= 0 for seconds in receipt.query_timing_seconds.values())
    # EXPLAIN (FORMAT JSON) always returns a one-element list wrapping the plan node.
    assert isinstance(receipt.query_plan_candidate_subjects, list)
    assert "Plan" in receipt.query_plan_candidate_subjects[0]
    assert isinstance(receipt.query_plan_baseline_limit, list)
    assert "Plan" in receipt.query_plan_baseline_limit[0]

    line = receipt.as_receipt_line()
    assert line.startswith("service=relay-fairness-benchmark ")
    assert f"n_subjects={config.n_subjects}" in line
