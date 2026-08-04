# Proposal — s12-verdict-relay

## Why

dbt computes verdict marts in Snowflake, but nothing carries those verdicts back into the ledger —
the I3 loop is open, and Phase 2's exit ("all four sanctioned command sources live") names the
verdict relay as one of the four. S1.1 (`pulse-ledger-core`) is merged and pinned every name this
component consumes (client module, `declare_verdict` command type, D16 idempotency, cursor
facility), so the S1.2 work order (`design/delivery/pulse-s1-work-orders.md`) is buildable now.

**Entry condition (blocks EXECUTE, not this proposal): DNA-801.** The HTTP path is not yet wired
to D16 replay semantics — `pulse_ledger.api` rejects an `idempotency_key` body field as unknown
and never echoes `replayed`, so `PulseCoreClient` classifies every replay as `committed`. The
declarer's replay classification is its whole job, so this change SHALL NOT be dispatched/enqueued
for execution before DNA-801 lands. Proposal, specs, design, and tasks may proceed; the gate is on
dispatch.

## What Changes

- **New package `packages/verdict-relay`**: a batch writer that reads verdict mart rows
  (fixture-pinned contract: one row per (subject, verdict_type, run), columns `subject_id,
  verdict_type, outcome, reason, rule_version, as_of, lineage_ref, computed_at`) and declares each
  as an attributed `declare_verdict` command through `pulse_core.client.PulseCoreClient`.
- **Cursor-based, resumable reads**: ordered (subject, as_of), cursor on `computed_at`, persisted
  via S1.1's writer-state facility (`pulse_core.cursor`), so a crashed run resumes without
  re-reading.
- **Ordering and idempotency as the core contract**: per subject, declare in `as_of` order; never
  declare a verdict older than the subject's latest declared `as_of` — stale runs are skipped and
  counted, not errored. Idempotency keys per D16 via `pulse_core.idempotency`.
- **Response classification handling**: committed, replayed (idempotent hit), rejected (illegal
  transition — counted and logged with the ledger's reason, never retried), transient (retried
  with backoff, 5 attempts, then the run fails naming the failing row).
- **Trinary outcome validation**: `positive | negative | indeterminate` with mandatory reason on
  `indeterminate`, failing before any API call.
- **Batch entrypoint + run receipt**: read → declare → receipt (declared, replayed, skipped-stale,
  rejected, failed) as structured logs tagged `service:verdict-relay` with a Datadog-parsable
  summary line. Entrypoint only — scheduling is S1.3.
- **Runbook** `docs/runbooks/verdict-relay.md` for the §1.5 monitors (staleness > 26 h, run
  failure).
- **Supersedes P5**: the clinic-rules-engine Snowpark emitter (`design/platform/
  clinic-rules-engine.md`) is superseded as the verdict write path; the qualification mart becomes
  a consumed contract in `docs/contracts/consumes.md`. Not BREAKING — the emitter was never built.

## Capabilities

### New Capabilities

- `verdict-mart-read`: cursor-based reading of the verdict mart contract — (subject, as_of)
  ordering, `computed_at` cursor persisted through the writer-state facility, crash/resume without
  re-reading.
- `verdict-declare`: mapping mart rows to `declare_verdict` commands — D16 idempotency keys,
  per-subject `as_of`-monotonic ordering with stale-skip, trinary outcome validation, and the
  four-way response classification handling (committed / replayed / rejected / transient).
- `verdict-relay-run`: the batch run itself — the read → declare loop, the run receipt with its
  five counts as structured logs, failure semantics, and the operator runbook for the §1.5
  monitors.

### Modified Capabilities

_None. `command-api`, `ledger-read`, and `ledger-record` are consumed as-is — this change adds a
writer on the existing single write path and changes no ledger-side requirement. The superseded
Snowpark emitter is a design doc (P5), not a spec._

## Impact

- New workspace member `packages/verdict-relay` (uv, ruff, pyright, pytest, coverage ≥ 85%,
  `--disable-socket` posture; command API faked at the client boundary — no live Snowflake or API
  calls in any test).
- Consumes from S1.1: `pulse_core.client.PulseCoreClient.submit_command`,
  `pulse_core.idempotency.derive_idempotency_key`, `pulse_core.cursor`
  (`CURSOR_PATH_TEMPLATE` / `cursor_path` / `validate_cursor`; a writer may touch only its own
  credential's cursor), `pulse_core.generated` verdict command type and trinary enum.
- Auth per D15: the relay's per-service credential name in config, value from the environment,
  never in code or fixtures. Synthetic data only in fixtures — no PHI anywhere.
- Doc updates: `docs/contracts/consumes.md` gains the verdict mart contract; supersession note on
  `design/platform/clinic-rules-engine.md` (P5); `docs/runbooks/verdict-relay.md` added.
- Out of scope: computing verdicts or any dbt models (mart contract is an input), scheduling of
  relay runs (S1.3), projection of verdict flags into Twenty (S2).
- Rollback: pre-production, no consumers of the receipt yet — reverting is deleting the package
  and the doc notes; no data migration exists, and idempotency means a partially-run relay left no
  state that a rerun cannot reconcile.
