# Runbook: verdict-relay

Operator actions for the two §1.5 monitors on this service
(`design/delivery/pulse-runtime-readiness.md` §1.5): **verdict staleness > 26 h** and
**run failure**. The relay is the batch that reads the verdict mart and declares each verdict into
the ledger (`packages/verdict-relay`, entrypoint `verdict_relay.run.main`). It runs by the
`verdict-relay-poll` schedules entry, or by hand as `task relay:run TARGET=<env>`.

Since `billing-state`, a registered verdict type also pairs its outcome with a state transition,
which adds two counts to the receipt below. The pairing's own semantics, cadence, and
transition-rejected triage live in [`billing-state.md`](billing-state.md); this runbook stays the
place for the two §1.5 monitors.

## Reading the receipt

Every run ends by emitting a receipt as structured JSON logs tagged `service:verdict-relay`, with
one machine-parsable summary line of `key=value` pairs — this line is the first diagnostic read
for either alert:

```
service=verdict-relay result=success declared=3 replayed=1 skipped_stale=1 rejected=1 transitioned=2 transition_rejected=0 failed=0
```

The seven counts:

| Count | Meaning |
| --- | --- |
| `declared` | New declarations the ledger committed. |
| `replayed` | Idempotent replays — the ledger had already committed this declaration (D16). |
| `skipped_stale` | Rows older than the subject's `as_of` watermark; skipped before submission. |
| `rejected` | The ledger refused the declaration. Counted and logged with the ledger's reason, **never retried**, and the run continues. |
| `transitioned` | Paired transitions the ledger committed (`billing-state`; see [`billing-state.md`](billing-state.md)). |
| `transition_rejected` | Paired transitions the ledger refused. Counted, logged with reason and catalog version, **never retried**; the verdict half stands. |
| `failed` | `1` when the run did not finish (with `result=failure` and a nonzero exit); `0` otherwise. |

A run that fails still emits the receipt — the counts reflect the work completed before the
failure, and the log line preceding the summary names the failing row by its subject key, verdict
type, and timestamps (never verdict content, never demographics; logs carry subject keys only).

## Rejected vs failed

These are different signals and want different responses:

- **`rejected`** is the ledger doing its job: an illegal transition per the catalog rules for
  `declare_verdict`. The row is counted, the ledger's reason and catalog version are logged, the
  row is never retried, and the run exits `0`. A nonzero `rejected` count is not an incident by
  itself — but a *persistently* nonzero one means the mart is producing verdicts the catalog
  refuses, which is a rules/mart drift question for the warehouse workstream, not something a
  re-run fixes.
- **`failed`** means the run itself stopped: a row exhausted the transient retry budget
  (5 attempts with jittered exponential backoff), failed local validation (contract shape, or an
  indeterminate outcome without a reason), or the mart violated its column contract. The run exits
  nonzero, the failed page is **not** committed to the cursor, and a re-run is the corrective
  action once the cause is cleared.

## Failure mode 1: verdict staleness > 26 h

**Monitor:** no successful declare-back in more than 26 hours (the daily verdict cycle plus
slack).

**Diagnose, in order:**

1. **Did a run happen at all?** Search Datadog for `service:verdict-relay` summary lines in the
   window. No lines → the trigger never fired (scheduler outage, or pre-S1.3 wiring absent).
   Escalate to whoever owns the trigger; the relay itself is healthy.
2. **Runs happening but failing?** Summary lines with `result=failure` → this is really failure
   mode 2; follow that section.
3. **Runs succeeding but declaring nothing?** `result=success` with `declared=0` and `replayed=0`:
   - `skipped_stale` high → the mart is re-serving old rows; check whether the upstream dbt run
     produced a fresh mart (`computed_at` newer than the persisted cursor's page position).
   - `rejected` high → the catalog is refusing what the mart produces; rules/mart drift, warehouse
     workstream.
   - all counts zero → the mart has no rows past the cursor; the upstream verdict computation is
     late or empty. The relay is healthy; chase the mart.

**Corrective action:** fix the upstream cause, then re-run (safe — see re-run semantics below).
The staleness clock resets on the next run with a committed or replayed declaration.

## Failure mode 2: run failure

**Monitor:** a run exited nonzero / a summary line with `result=failure` (`failed=1`).

**Diagnose:**

1. Read the receipt: the counts say how far the run got before stopping.
2. Read the failure log line above the summary — it names the failing row (subject key, verdict
   type, `as_of`, `computed_at`) and the cause:
   - **Transient exhaustion** (`failed after 5 transient attempts`) — the command API was
     unreachable or persistently erroring. Check the command API's own §1.5 monitors (error rate,
     latency); once it is healthy, re-run.
   - **Row validation** — the row failed contract-shape or trinary-outcome checks locally (e.g.
     indeterminate without a reason), before any network call. The mart is out of contract; file
     against the warehouse workstream with the named row. A re-run fails on the same row until the
     mart is fixed.
   - **Mart contract violation** — same ownership as row validation: the reader failed fast and
     named the row; the mart must conform before a re-run can pass.

**Corrective action:** clear the cause, then re-run. Do not skip rows by hand — the cursor and
idempotency make the re-run safe, and manual cursor edits are how a subject's verdict regresses.

## Safe re-run semantics

Re-running the relay is always safe; it is the standard recovery for both failure modes.

- The reader pages the mart on `computed_at` and persists its page position, together with the
  per-subject `as_of` watermark map, in one durable cursor save per page. A failed run does not
  commit its failed page.
- A resumed run therefore picks up from the **persisted cursor** and re-reads at most the one
  uncommitted page. Rows on that page that were already declared before the crash are
  D16-idempotent: the ledger answers them as replays.
- **Expect the recovery overlap in the counts** (design risk 4): the first run after a failure
  reports a `replayed` count that includes those re-declared rows. This is bookkeeping, not
  double-declaration — correctness never depends on the cursor being fresh, only the counts do.
  Do not treat an elevated `replayed` on a recovery run as an incident.
- Per-subject `as_of` ordering holds across re-runs: the watermark map skips anything older than
  what was already declared (`skipped_stale`), so a re-run — even against a shuffled or re-served
  mart — can never regress a subject's verdict.

## PHI posture

Relay logs carry subject keys, verdict types, and timestamps only — never demographics, never
verdict content. If any log line in Datadog shows more than that, treat it as a PHI incident:
capture the record's timestamp and logger name, and escalate per the security review process
before sharing the line anywhere.
