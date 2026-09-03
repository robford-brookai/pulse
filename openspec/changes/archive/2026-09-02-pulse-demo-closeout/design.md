# Design — pulse-demo-closeout

## Context

See proposal.md §Why. What exists and shapes the approach: four demo scripts under
`scripts/demo/` that each stand up their own harness (`demo1` against the LocalStack + Postgres
compose stack in `packages/ocean/infra/docker-compose.yml`, `demo2` fully in-process on
fixtures, `demo3` against live dev Twenty over `httpx`, `demo4` against the dev Snowflake mart
and dev ledger through `verdict_relay.run`). `synthea-seed` generates a byte-identical
population per profile with declarative overlays (`synthetic-population` spec) but no demo
consumes it. `consent-ingress` has a CLI (`consent_ingress.cli`) that sweeps a landing table.
`twenty-projection` applies events from a queue (`apply.py`, `consumer.py`) with per-subject
watermarks and no rebuild path. `STG_EVENTS.EVENTS` is the published warehouse contract
(`docs/contracts/publishes.md`). The roadmap's demo convention: script under `scripts/demo/`,
runbook under `docs/runbooks/`, nonzero exit on any failed assertion, out of `task check`.

## Goals / Non-Goals

**Goals**
- One script that composes the four existing harnesses rather than reimplementing any stage.
- Offline mode runnable by anyone with Docker in about five minutes, with no credential.
- The rebuild path usable outside the demo, as an operator command with a receipt.

**Non-Goals**
- No new ledger behavior. Every assertion checks shipped behavior. A stage that needs the
  ledger to do something new is a spec defect in this change, not a task.
- No engine declares. Stage 4 uses the relay against a fixture mart, exactly as demo4 does.
- No production or staging targets. Live mode is dev only.

## Decisions

1. **Compose, do not rewrite.** `demo5_end_to_end.py` imports the stage functions the four
   demos already expose (extracting a function where a demo only has a `main`) and orders them
   behind a `Stage` protocol: `setup(ctx)`, `run(ctx) -> StageReceipt`, with the shared
   context carrying the stack handles and the patient's subject keys. Alternative (a fresh
   script per stage) rejected: it forks assertions that must stay identical to the originals.
2. **Transport is a context object, not a branch per stage.** Offline and live differ only in
   how `DemoContext` is built: which database URL, which board client (in-process FastAPI route
   vs `httpx` to dev), which landing tables (SQLite/Postgres fixture vs Snowflake). Stage code
   never checks the mode. Alternative (`if live:` inside stages) rejected: it is how the two
   modes' assertions drift apart.
3. **Fixtures are overlays on the pinned cohort, committed.** `scripts/demo/fixtures/` holds
   the `synthea-seed` overlay for one patient with three referral variants, one consent export
   row, and one verdict mart row, all keyed to that patient. Generated once, committed, with
   the seed and checksum recorded, so the demo never needs Java (`synthetic-population` spec:
   check stays Java-free). Alternative (generate at demo start) rejected for the Java
   dependency and non-determinism across machines.
4. **The rebuild lives in `twenty-projection`, not the demo.** New module `rebuild.py` with a
   CLI entry `twenty-projection rebuild --scope <subject_type>[:<key>]` that reads committed
   events for the scope from the ledger feed's replay source (the same envelope shape the
   consumer applies), folds them through `apply.py`'s existing handlers in sequence, diffs
   against current rows, writes only differences, and prints a counted receipt. The demo's
   stage 6 calls that entry point. Alternative (a demo-only destroy/repaint) rejected: the
   roadmap's Demo 3 promise is an operator drill, and a drill that only exists in a demo is not
   one.
5. **Replay source for the rebuild is the ledger's read route, not the queue.** Queues are
   consumed once. The rebuild reads committed events by subject through `pulse_core`'s client
   against the command API's read surface (`ledger-read` spec), under the projection's existing
   credential. If that route does not yet expose per-subject history, the task adds it as a
   read-only route — the one place this change may touch the ledger service, additive only.
6. **Stage 5 compares shapes, not rows.** Each window is reduced to `(subject_type,
   subject_key, state, as_of)` tuples before comparison, so a board row, a warehouse event
   projection, and a fold compare on the same key. The warehouse check in offline mode reads
   the LocalStack-landed events through the same reducer; in live mode it reads
   `STG_EVENTS.EVENTS` read-only.
7. **Taskfile gets a `demo:` area kept out of `check`.** `task demo:1` … `demo:4`,
   `demo:e2e`, `demo:e2e:live`, placed in a new area between Test and Gate with a comment
   explaining why none is a `check` dependency. The existing reachability gate pattern (deploy
   targets out of `check`) is reused for the demo targets.
8. **Drift fixes ride the same change.** Roadmap demo table rewritten to match shipped
   scripts (Demo 3 live kanban drag, Demo 4 billing declare-back, Demo 5 end-to-end carrying
   the rebuild drill, `odg-read-redirect` moves to a Phase 4 row); runbooks for demos 3 and 4
   written from their script docstrings. Alternative (separate docs change) rejected: the
   table is wrong today and the fix is a page.

9. **The consent writer id is `customer-io` (Rob, 2026-09-02).** The first `task
   stage:e2e:live` found no customer.io writer key in the dev secret and showed none could work:
   `pulse_ledger.auth._writer_id_from_suffix` lowercases `PULSE_LEDGER_WRITER_TOKEN_<SUFFIX>` and
   maps `_` to `-`, so the `customer.io` actor the ingress and the `customerio-consent-ingress`
   spec named was unspellable — stage 2 could never authenticate live. The ingress moves to
   `customer-io`, matching the convention every other writer follows (`verdict-relay`,
   `twenty`, `schedules-month-open`), registered as `PULSE_LEDGER_WRITER_TOKEN_CUSTOMER_IO`.
   Alternative (teach the ledger a dot spelling, e.g. `__`) rejected: one more mapping rule for
   every future writer to know, to preserve a spelling nothing depends on. Task 2.5 carries the
   code; this change's delta spec carries the requirement; the dev credential is minted at 3.3
   (issue #342).

## Risks / Trade-offs

- [demo1 and demo3 stage functions are tangled with their `main`] → extract-and-call in the
  same PR as the stage that needs them, with the original demo still passing (the extraction
  is behavior-preserving by that gate).
- [No per-subject history read route exists] → decision 5's additive route, gated by the
  `ledger-read` spec's existing scenarios plus one new test; if the route needs a design
  decision beyond "return committed events for a subject in sequence", it halts as design
  drift per AGENTS.md.
- [Live mode flakes on dev Twenty latency] → the heal-back and projection freshness budgets
  already exist (60 s); stage 5 polls to that budget, and the receipt records the wait.
- [Fixture cohort drifts from the catalog] → the fixture overlay is validated by the
  `synthetic-population` overlay validator in a test, so a catalog release that invalidates it
  fails `task check`, not the demo.
- [Presentation refresh becomes a rewrite] → scope is the one-patient story replacing §3's
  per-demo framing, nothing else; the audience decision (internal, two weeks) bounds it.

## Migration Plan

Docs and scripts land by ordinary PR per task. The `twenty-projection` rebuild entry point and
any read route are additive; nothing existing changes behavior. Live mode is a live-execution
task: GitHub issue, runbook PR, attended run, receipts on the issue. Rollback per proposal.md.
