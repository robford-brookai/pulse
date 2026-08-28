"""MECE test suite for warehouse-sync (task 5.9).

Taxonomy
========
The suite partitions the service's consume-loop behaviour along the axes the
loop actually has: *when it flushes*, *what a flush writes*, *what gets
acknowledged (deleted) and when*, and *what happens when a step fails or the
loop stops*. The cells are mutually exclusive — each test asserts exactly one
cell, marked with exactly one category marker — and collectively exhaustive
over the loop's observable behaviour. Run one stage with ``-m <marker>``;
resume an interrupted run with ``--resume-from=<stage-id>``; record a run
with ``--run-log=<path>`` (see conftest.py).

===============  ============  =====================================================
Stage            Marker        Cell contents
===============  ============  =====================================================
S1-ordering      ordering      Relative order of receive → MERGE commit → SQS
                               delete. Nothing is deleted before Snowflake commits.
S2-batching      batching      What triggers a flush and what doesn't: accumulation
                               across polls, the 10s window, the size threshold,
                               and the no-op cases (empty batch, window not yet due).
S3-duplicates    duplicates    Duplicate *content*: the same event_id arriving twice
                               (across batches or within one) yields exactly one row.
                               This is the property 5.7 introduced by moving the
                               flush from INSERT to MERGE on data:event_id — the
                               Kafka loop never had it, and it was asserted nowhere.
S4-reordering    reordering    Delivery *order*: any permutation of a message set
                               yields identical table contents.
S5-redrive       redrive       A batch the warehouse cannot accept: the flush error
                               propagates, nothing is deleted, redelivery converges,
                               and messages that cannot even parse are left for the
                               queue's redrive policy. Consumer death is surfaced.
S6-cursor        cursor        The SQS cursor (receipt handles) on the failure path:
                               a failed or partially-failed delete is not retried,
                               the loop survives it, and the MERGE makes the
                               resulting redelivery harmless. Deletes are chunked.
S7-shutdown      shutdown      Cancellation with a partial batch: the batch is
                               neither flushed nor deleted (it redelivers), the
                               Snowflake connection closes, an injected SQS client
                               is not closed by the loop.
===============  ============  =====================================================

Deliberately empty cells (stated so a future reader knows they are empty on
purpose, not by omission):

- *Owned-client construction/teardown* — ``_consume_loop`` building its own
  aioboto3 client. aioboto3 is a service-image dependency, not a workspace
  test dependency; the injected-client seam is the tested contract, matching
  every other converted service.
- *HTTP surface* (``/health``, startup wiring) — not consume-loop behaviour;
  one process-level smoke belongs to the compose/deploy layer
  (``task warehouse:smoke``), not this taxonomy.
- *Snowflake connectivity* (``_connect_snowflake``) — exercises the vendor
  driver and key loading, meaningless against a fake; covered by the same
  smoke path.
- *Cursor advance on the flush-failure path* — there is nothing to test: the
  loop re-raises and dies before touching receipts, which is itself asserted
  in S5 (``test_failed_flush_leaves_messages_undeleted``).

All fixture events are synthetic (see ``make_message``); no PHI anywhere,
including the run log.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from types import SimpleNamespace
from typing import Any

import pytest

from .conftest import FakeSnowflakeConnection, make_message

# ---------------------------------------------------------------------------
# S1-ordering — receive/flush/delete ordering
# ---------------------------------------------------------------------------


@pytest.mark.ordering
async def test_delete_happens_only_after_merge_commits(harness, stage_log):
    """The loop's safety spine: SQS delete must strictly follow the MERGE."""
    client = harness.client([
        {"messages": [make_message("evt-001"), make_message("evt-002")], "advance": 11.0},
    ])
    await harness.run_to_shutdown(client)

    ops = [op for op, _ in harness.call_log]
    assert ops == ["receive", "merge", "delete"]
    assert client.deleted == ["rh-evt-001-d0", "rh-evt-002-d0"]
    stage_log.observe(
        call_order=ops,
        deleted_receipts=client.deleted,
        table_rows=sorted(harness.sf.table),
    )


@pytest.mark.ordering
async def test_no_delete_when_merge_fails(harness, stage_log):
    """If Snowflake does not commit, no receipt may be deleted."""
    harness.sf.fail_next_merges = 1
    client = harness.client([{"messages": [make_message("evt-003")], "advance": 11.0}])

    with pytest.raises(RuntimeError, match="synthetic snowflake failure"):
        await harness.run(client)

    assert client.deleted == []
    assert harness.sf.table == {}
    assert ("delete", 1) not in harness.call_log
    stage_log.observe(deleted_receipts=client.deleted, table_rows=sorted(harness.sf.table))


# ---------------------------------------------------------------------------
# S2-batching — accumulation and the 10s window
# ---------------------------------------------------------------------------


@pytest.mark.batching
async def test_batch_accumulates_across_polls_until_window_elapses(harness, stage_log):
    """Messages from successive polls join one batch; one flush covers them all."""
    client = harness.client([
        {"messages": [make_message("evt-010"), make_message("evt-011")], "advance": 3.0},
        {"messages": [make_message("evt-012")], "advance": 3.0},
        {"messages": [], "advance": 5.0},  # 11s elapsed: window due
    ])
    await harness.run_to_shutdown(client)

    assert harness.sf.merge_attempts == 1
    assert sorted(harness.sf.table) == ["evt-010", "evt-011", "evt-012"]
    assert len(client.deleted) == 3
    stage_log.observe(merge_attempts=harness.sf.merge_attempts, batch_size_at_flush=3)


@pytest.mark.batching
async def test_no_flush_before_window_elapses(harness, stage_log):
    """A pending batch younger than BATCH_TIMEOUT_S is held, not flushed."""
    client = harness.client([
        {"messages": [make_message("evt-020")], "advance": 4.0},
        {"messages": [], "advance": 4.0},  # 8s < 10s: still inside the window
    ])
    await harness.run_to_shutdown(client)

    assert harness.sf.merge_attempts == 0
    assert client.deleted == []
    stage_log.observe(merge_attempts=0, pending_batch=1)


@pytest.mark.batching
async def test_size_threshold_flushes_without_waiting_for_window(harness, monkeypatch, stage_log):
    """Reaching BATCH_SIZE flushes immediately, however young the batch is."""
    monkeypatch.setattr(harness.main, "BATCH_SIZE", 3)
    client = harness.client([
        {"messages": [make_message(f"evt-03{i}") for i in range(3)], "advance": 0.0},
    ])
    await harness.run_to_shutdown(client)

    assert harness.sf.merge_attempts == 1
    assert len(harness.sf.table) == 3
    stage_log.observe(merge_attempts=1, batch_size_at_flush=3, window_elapsed=False)


@pytest.mark.batching
async def test_empty_queue_never_flushes(harness, stage_log):
    """An elapsed window with nothing pending triggers no MERGE and no delete."""
    client = harness.client([
        {"messages": [], "advance": 30.0},
        {"messages": [], "advance": 30.0},
    ])
    await harness.run_to_shutdown(client)

    assert harness.sf.merge_attempts == 0
    assert client.deleted == []
    stage_log.observe(merge_attempts=0, pending_batch=0)


# ---------------------------------------------------------------------------
# S3-duplicates — redelivered content yields no second row (the 5.7 property)
# ---------------------------------------------------------------------------


@pytest.mark.duplicates
async def test_redelivery_across_batches_yields_no_second_row(harness, stage_log):
    """A message redelivered after a lost delete merges as a no-op — and its
    receipt is still deleted, so it stops redelivering."""
    client = harness.client([
        {"messages": [make_message("evt-100"), make_message("evt-101")], "advance": 11.0},
        {"messages": [make_message("evt-100", delivery=1), make_message("evt-102")], "advance": 11.0},
    ])
    await harness.run_to_shutdown(client)

    assert sorted(harness.sf.table) == ["evt-100", "evt-101", "evt-102"]
    assert harness.sf.table["evt-100"]["data"]["payload"]["name"] == "fixture-evt-100"
    assert "rh-evt-100-d1" in client.deleted  # the duplicate is acknowledged too
    stage_log.observe(table_rows=sorted(harness.sf.table), deleted_receipts=client.deleted)


@pytest.mark.duplicates
async def test_duplicate_within_a_single_batch_yields_one_row(harness, stage_log):
    """SQS at-least-once can put both deliveries in one batch; the MERGE's
    QUALIFY dedup keeps the statement itself single-row per event_id."""
    client = harness.client([
        {
            "messages": [make_message("evt-110"), make_message("evt-110", delivery=1)],
            "advance": 11.0,
        },
    ])
    await harness.run_to_shutdown(client)

    assert sorted(harness.sf.table) == ["evt-110"]
    assert harness.sf.merge_attempts == 1
    stage_log.observe(table_rows=sorted(harness.sf.table), batch_size_at_flush=2)


@pytest.mark.duplicates
async def test_redelivery_with_mutated_payload_does_not_overwrite(harness, stage_log):
    """Append semantics, the never-update half (task 7.3): the MERGE has no
    WHEN MATCHED clause, so a redelivery whose bytes differ from the original
    — a producer retry after a partial write, a replayed archive — leaves the
    first-committed row untouched rather than silently rewriting history."""
    client = harness.client([
        {"messages": [make_message("evt-120")], "advance": 11.0},
        {"messages": [make_message("evt-120", delivery=1, name="mutated-evt-120")], "advance": 11.0},
    ])
    await harness.run_to_shutdown(client)

    assert sorted(harness.sf.table) == ["evt-120"]
    assert harness.sf.table["evt-120"]["data"]["payload"]["name"] == "fixture-evt-120"
    assert "rh-evt-120-d1" in client.deleted  # the mutated redelivery is still retired
    stage_log.observe(
        table_rows=sorted(harness.sf.table),
        retained_payload=harness.sf.table["evt-120"]["data"]["payload"]["name"],
    )


# ---------------------------------------------------------------------------
# S4-reordering — delivery order does not change table contents
# ---------------------------------------------------------------------------


@pytest.mark.reordering
async def test_reversed_delivery_yields_identical_table_contents(harness, stage_log):
    """The spec's order-tolerance scenario: forward and reverse delivery of
    the same event set produce equal tables."""
    events = [f"evt-20{i}" for i in range(5)]

    client_fwd = harness.client([{"messages": [make_message(e) for e in events], "advance": 11.0}])
    await harness.run_to_shutdown(client_fwd)
    forward_table = dict(harness.sf.table)

    harness.sf.table.clear()
    client_rev = harness.client([{"messages": [make_message(e) for e in reversed(events)], "advance": 11.0}])
    await harness.run_to_shutdown(client_rev)

    assert harness.sf.table == forward_table
    stage_log.observe(table_rows=sorted(harness.sf.table))


@pytest.mark.reordering
async def test_interleaved_redelivery_order_is_immaterial(harness, stage_log):
    """Order tolerance must hold across batches too, with duplicates mixed in:
    {a,b} then {b,a-redelivered} converges to the same two rows."""
    client = harness.client([
        {"messages": [make_message("evt-210"), make_message("evt-211")], "advance": 11.0},
        {"messages": [make_message("evt-211", delivery=1), make_message("evt-210", delivery=1)], "advance": 11.0},
    ])
    await harness.run_to_shutdown(client)

    assert sorted(harness.sf.table) == ["evt-210", "evt-211"]
    stage_log.observe(table_rows=sorted(harness.sf.table))


@pytest.mark.reordering
async def test_every_permutation_across_flush_boundaries_converges(harness, stage_log):
    """Append semantics, the order-tolerance half (task 7.3): the reversed-set
    test above holds order constant *within* one flush; this one exhausts it
    *across* flushes. Every permutation of a three-event set, delivered one
    message per flush cycle, must produce byte-identical table contents —
    commit order is the only thing allowed to vary."""
    events = ["evt-220", "evt-221", "evt-222"]
    reference: dict[str, Any] | None = None

    for perm in itertools.permutations(events):
        harness.sf.table.clear()
        client = harness.client([{"messages": [make_message(e)], "advance": 11.0} for e in perm])
        await harness.run_to_shutdown(client)

        assert sorted(harness.sf.table) == events
        if reference is None:
            reference = dict(harness.sf.table)
        else:
            assert harness.sf.table == reference, f"permutation {perm} diverged"

    stage_log.observe(permutations_checked=6, table_rows=sorted(harness.sf.table))


# ---------------------------------------------------------------------------
# S5-redrive — failed batches redeliver; the path converges
# ---------------------------------------------------------------------------


@pytest.mark.redrive
async def test_failed_flush_leaves_messages_undeleted(harness, stage_log):
    """A batch the warehouse cannot accept propagates its error out of the
    loop with every receipt intact — visibility timeout, then redrive/DLQ,
    is the queue's job, not the service's."""
    harness.sf.fail_next_merges = 1
    client = harness.client([{"messages": [make_message("evt-300"), make_message("evt-301")], "advance": 11.0}])

    with pytest.raises(RuntimeError):
        await harness.run(client)

    assert client.deleted == []
    assert harness.sf.table == {}
    stage_log.observe(deleted_receipts=[], table_rows=[], merge_attempts=harness.sf.merge_attempts)


@pytest.mark.redrive
async def test_redelivery_after_failed_flush_converges(harness, stage_log):
    """The redrive round-trip: flush fails, the consumer restarts, SQS
    redelivers, and the second flush lands exactly one row per event."""
    harness.sf.fail_next_merges = 1
    first = harness.client([{"messages": [make_message("evt-310")], "advance": 11.0}])
    with pytest.raises(RuntimeError):
        await harness.run(first)

    redelivered = harness.client([{"messages": [make_message("evt-310", delivery=1)], "advance": 11.0}])
    await harness.run_to_shutdown(redelivered)

    assert sorted(harness.sf.table) == ["evt-310"]
    assert redelivered.deleted == ["rh-evt-310-d1"]
    stage_log.observe(table_rows=sorted(harness.sf.table), deleted_receipts=redelivered.deleted)


@pytest.mark.redrive
async def test_malformed_message_is_left_for_the_queue_redrive(harness, stage_log):
    """A message that does not parse is neither merged nor deleted — it ages
    into the DLQ via the queue's redrive policy. A well-formed message in the
    same receive still flows."""
    bad = {"ReceiptHandle": "rh-malformed-d0", "Body": "not json at all"}
    missing_detail = {"ReceiptHandle": "rh-nodetail-d0", "Body": json.dumps({"detail-type": "alerts"})}
    client = harness.client([{"messages": [bad, missing_detail, make_message("evt-320")], "advance": 11.0}])
    await harness.run_to_shutdown(client)

    assert sorted(harness.sf.table) == ["evt-320"]
    assert client.deleted == ["rh-evt-320-d0"]
    stage_log.observe(table_rows=sorted(harness.sf.table), deleted_receipts=client.deleted)


@pytest.mark.redrive
async def test_dead_consumer_is_surfaced_not_swallowed(harness, monkeypatch, stage_log):
    """startup() runs the loop as a naked task; _log_consumer_exit is the only
    thing standing between a dead consumer and silence."""
    errors: list[dict[str, Any]] = []
    monkeypatch.setattr(
        harness.main,
        "log",
        SimpleNamespace(error=lambda event, **kw: errors.append({"event": event, **kw})),
    )
    # DNA-1259 made a dead consumer call os._exit(1); unpatched, it takes pytest down with it —
    # the suite dies mid-run with no summary, which is exactly how it failed in CI.
    terminated: list[bool] = []
    monkeypatch.setattr(harness.main, "_terminate_process", lambda: terminated.append(True))

    async def _boom() -> None:
        raise RuntimeError("consumer died")

    task = asyncio.get_running_loop().create_task(_boom())
    with pytest.raises(RuntimeError):
        await task
    harness.main._log_consumer_exit(task)

    assert [e["event"] for e in errors] == ["consumer_exited"]
    assert terminated == [True], "a dead consumer must take the process down (DNA-1259)"

    cancelled = asyncio.get_running_loop().create_task(asyncio.sleep(60))
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    harness.main._log_consumer_exit(cancelled)
    assert terminated == [True], "orderly cancellation is not a death — no exit"

    assert len(errors) == 1  # cancellation is a normal shutdown, not an error
    stage_log.observe(surfaced_errors=[e["event"] for e in errors])


# ---------------------------------------------------------------------------
# S6-cursor — receipt handles on the failure path
# ---------------------------------------------------------------------------


@pytest.mark.cursor
async def test_failed_delete_is_not_retried_and_merge_absorbs_redelivery(harness, stage_log):
    """A delete that throws is logged and abandoned: the loop keeps running,
    the receipts redeliver, and the MERGE makes that redelivery a no-op —
    the second delete then retires the cursor."""
    client = harness.client([
        {"messages": [make_message("evt-400")], "advance": 11.0},
        {"messages": [make_message("evt-400", delivery=1)], "advance": 11.0},
    ])
    client.fail_next_deletes = 1
    await harness.run_to_shutdown(client)

    assert sorted(harness.sf.table) == ["evt-400"]
    assert harness.sf.merge_attempts == 2  # loop survived the failed delete
    assert client.deleted == ["rh-evt-400-d1"]  # only the redelivery was acknowledged
    stage_log.observe(
        table_rows=sorted(harness.sf.table),
        deleted_receipts=client.deleted,
        merge_attempts=harness.sf.merge_attempts,
    )


@pytest.mark.cursor
async def test_partial_delete_failure_does_not_stop_the_loop(harness, stage_log):
    """A batch delete that reports Failed entries is logged, not retried; the
    loop's batch/cursor state resets and the next cycle proceeds normally."""
    client = harness.client([
        {"messages": [make_message("evt-410"), make_message("evt-411")], "advance": 11.0},
        {"messages": [make_message("evt-412")], "advance": 11.0},
    ])
    client.partial_fail_next_deletes = 1
    await harness.run_to_shutdown(client)

    assert sorted(harness.sf.table) == ["evt-410", "evt-411", "evt-412"]
    assert "rh-evt-411-d0" not in client.deleted  # the Failed entry stays on the queue
    assert "rh-evt-412-d0" in client.deleted
    stage_log.observe(table_rows=sorted(harness.sf.table), deleted_receipts=client.deleted)


@pytest.mark.cursor
async def test_deletes_are_chunked_to_the_sqs_batch_limit(harness, monkeypatch, stage_log):
    """SQS caps delete_message_batch at 10 entries; a 25-receipt flush must
    acknowledge its cursor in chunks of 10/10/5."""
    monkeypatch.setattr(harness.main, "BATCH_SIZE", 25)
    messages = [make_message(f"evt-4{i:02d}") for i in range(20, 45)]
    client = harness.client([{"messages": messages, "advance": 0.0}])
    await harness.run_to_shutdown(client)

    assert [len(call) for call in client.delete_calls] == [10, 10, 5]
    assert len(client.deleted) == 25
    stage_log.observe(delete_chunk_sizes=[len(c) for c in client.delete_calls])


# ---------------------------------------------------------------------------
# S7-shutdown — cancellation with a partial batch
# ---------------------------------------------------------------------------


@pytest.mark.shutdown
async def test_shutdown_abandons_partial_batch_to_redelivery(harness, stage_log):
    """Cancellation with messages pending must not flush and must not delete:
    the partial batch redelivers to the next consumer, and the MERGE keeps
    that safe. Deleting here would lose events; flushing here would race the
    shutdown."""
    client = harness.client([{"messages": [make_message("evt-500"), make_message("evt-501")], "advance": 0.0}])
    await harness.run_to_shutdown(client)

    assert harness.sf.merge_attempts == 0
    assert client.deleted == []
    assert harness.sf.table == {}
    stage_log.observe(pending_batch=2, deleted_receipts=[], merge_attempts=0)


@pytest.mark.shutdown
async def test_shutdown_closes_snowflake_but_not_an_injected_client(harness, stage_log):
    """The loop owns the Snowflake connection and must close it; an injected
    SQS client belongs to the caller and must be left open."""
    client = harness.client([])
    await harness.run_to_shutdown(client)

    assert harness.sf.closed is True
    assert client.aexit_called is False
    stage_log.observe(snowflake_closed=True, injected_client_closed=False)


@pytest.mark.shutdown
async def test_shutdown_after_clean_flush_leaves_nothing_pending(harness, stage_log):
    """The boundary case between S1 and S7: cancel arriving right after a
    flush+delete cycle finds an empty batch and loses nothing."""
    client = harness.client([{"messages": [make_message("evt-510")], "advance": 11.0}])
    await harness.run_to_shutdown(client)

    assert sorted(harness.sf.table) == ["evt-510"]
    assert client.deleted == ["rh-evt-510-d0"]
    stage_log.observe(table_rows=sorted(harness.sf.table), pending_batch=0)


# ---------------------------------------------------------------------------
# Guard: the fake's contract matches the real statement
# ---------------------------------------------------------------------------


@pytest.mark.duplicates
async def test_flush_batch_sends_one_param_pair_per_message(harness):
    """Pin the parameterisation: two params per (data, domain) row, JSON first.
    If _flush_batch's SQL or param layout changes shape, this fails before the
    behavioural tests can silently test the wrong statement."""
    sf = FakeSnowflakeConnection()
    await harness.main._flush_batch(
        sf,  # type: ignore[arg-type]
        [(json.dumps({"event_id": "evt-600"}), "alerts"), (json.dumps({"event_id": "evt-601"}), "ops")],
    )
    assert sorted(sf.table) == ["evt-600", "evt-601"]
    assert sf.table["evt-601"]["domain"] == "ops"
