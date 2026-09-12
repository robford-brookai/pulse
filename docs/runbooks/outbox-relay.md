# Runbook: outbox-relay

Operator actions for `pulse_ledger.relay` — the outbox relay that publishes committed ledger
events to the EventBridge backbone (`design/delivery/pulse-runtime-readiness.md` §1.4, decision
D17). Runs as the `ledger-relay` compose service, entrypoint `pulse_ledger.relay_worker.main`
(`python -m pulse_ledger.relay_worker`), looping `relay_fair_pass` (relay-fairness 1.1/1.2) over
`DATABASE_URL` at a fixed poll interval. This is the DLQ-depth and outbox-lag half of the two
monitors the relay contributes to §1.5; the per-run declare-back staleness monitor belongs to
[`verdict-relay.md`](verdict-relay.md), a different service reading a different mart.

## Reading the receipt

Each pass that published or dead-lettered anything logs one structured line tagged
`service:ledger-relay` (`relay_worker.py`):

```
relay_pass published=4 dead_lettered=0 max_lag_seconds=2.7
```

`max_lag_seconds` is `outbox_lag_seconds` at the moment of that pass's last publish — the age of
the oldest row still waiting, which is what the p99 < 30 s outbox-to-backbone figure is stated
over. It is a **sub-budget of the projection-freshness SLO** (ledger → Twenty, p99 < 60 s), not a
fourth SLO of its own (design decision 2026-09-08); do not open a new incident purely on this
number crossing 30 s once — check it against the end-to-end freshness monitor first.

## Failure mode: DLQ depth ≥ 1

**Monitor:** `dead_letter_depth(conn)` — rows that exhausted all five attempts.

**Diagnose:**

1. Read the dead-lettered row's `last_error` column (`ledger.outbox`) — the transport's own
   message, truncated to 1000 chars. It never contains the envelope or payload.
2. Check whether the cause is cleared (bus outage resolved, downstream schema fixed, whatever
   `last_error` names).
3. **Redrive is a manual runbook action, never automatic** (spec: "only manual runbook redrive can
   retry the dead-lettered row"). Call `pulse_ledger.relay.redrive(conn, event_id)` for the named
   row once the cause is cleared. It resets `attempts` to zero and clears the dead-letter marker —
   the row rejoins the claim index and is picked up by the next fair pass.
4. A redriven row can be a late delivery relative to rows published normally in the meantime: the
   spec's ordering guarantee is publication order, not subscriber arrival order, and consumers
   dedupe on `event_id` and hold their own watermark/replay contract regardless (see the
   `ledger-distribution` spec's "Transport reorder and late redrive preserve projection
   correctness" scenario, relay-fairness 2.2).

**Never:** hand-edit `published_at` or `seq` to work around a stuck row. The DLQ marker and
`redrive` are the only sanctioned path; anything else invalidates the per-subject ordering
guarantee for rows that come after it.

## Failure mode: outbox lag approaching 30 s

**Diagnose:**

1. Confirm whether this is broad (every subject's lag is elevated — a bus-side slowdown or a
   relay process not running) or narrow (one hot subject's backlog is simply larger than its
   per-pass row budget, which is expected and self-correcting — the subject is revisited every
   scan cycle, not starved).
2. If narrow, no action: the fairness pass guarantees every eligible unlocked subject is visited
   within a bounded number of passes regardless of how large one subject's backlog is (see below).
   The relay working through a big backlog is not the same failure as a subject being starved.
3. If broad, check the relay process is actually running and check DLQ depth first — a poison row
   that has not yet dead-lettered can still be inside its backoff window, consuming attempts
   without freeing its subject.

## Fairness: what "no starvation" means operationally

`relay_fair_pass` bounds two things per pass: how many candidate subjects it examines
(`subject_budget`, default `DEFAULT_SUBJECT_BUDGET = 20`) and how many rows it publishes per
acquired subject (`row_budget`, default `DEFAULT_ROW_BUDGET = 20`). Neither bound is a promise
about wall-clock time under unbounded arrivals — it is a promise about **passes**: over
`ceil(N / subject_budget)` passes, where `N` is the count of subjects with at least one pending
row, every one of them is examined at least once, locked and backing-off subjects included. A
locked or backing-off subject never consumes another subject's turn; it is simply revisited on its
own next turn, same as an oversized backlog is.

### Benchmark evidence (relay-fairness 3.1)

`pulse_ledger.relay_benchmark` is a synthetic, offline, bounded benchmark that seeds a skewed
backlog (`N - 1` early-sorting subjects with a backlog, one continuously eligible late-sorting
target) and runs it through two independent fairness-scheduled workers sharing one candidate set.
It records, per the spec's own acceptance scenario:

- the pre-fairness baseline (`pending_rows`'s plain `ORDER BY ... LIMIT`) starving the target,
  reproducing the defect this task-005 receipt exists to close;
- the pass at which the target is first published, always within `ceil(N / subject_budget)`;
- backlog drain (pending-row count) after every pass;
- publish counts per worker, per pass;
- `EXPLAIN (FORMAT JSON)` for both the candidate-subject query and the old `LIMIT` query, against
  the seeded skew;
- wall-clock timing for the baseline query and the full two-relay scan cycle — reported for
  reference only; the scenario makes no wall-clock claim, only a bounded-pass one.

Run it against a scratch, already-migrated, disposable database (never a shared or prod one — it
writes synthetic rows and never touches the bus):

```sh
uv run --package pulse-ledger python -m pulse_ledger.relay_benchmark \
  --database-url postgresql://localhost/scratch_db \
  --n-subjects 20 --subject-budget 5 --row-budget 10
```

It prints one `service=relay-fairness-benchmark ...` receipt line (paste into a HANDOFF or design
review) followed by the full JSON receipt (add its query-plan fields to a design review when
investigating a scheduling regression). There is no `task` target for this yet — it is invoked
directly as a `uv run` module rather than through `Taskfile.yml` while a `.github`/`Taskfile.yml`
serial lane is held by another change; see this task's `HANDOFF.md` for the proposed target.

The equivalent fixture lives in
`packages/pulse-ledger/tests/integration/test_relay_fairness_load.py` and runs under `task test`
like every other suite in this package — it is what CI proves on every PR, not merely a
point-in-time benchmark run.

## PHI posture

Relay logs and the dead-letter `last_error` column carry `event_id`, subject type/key, and the
transport's own message only — never the envelope, `payload`, or `evidence`. The benchmark seeds
only synthetic `referral` transitions with a literal `{"note": "synthetic"}` payload; it must never
be pointed at a database holding real ledger data.
