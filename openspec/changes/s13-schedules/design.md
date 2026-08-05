# Design — s13-schedules

## Context

See proposal.md — Why. Constraints that shape the design:

- S1.1 is merged and its names are pinned (work order "Shared context", DNA-799): the client is
  `pulse_core.client.PulseCoreClient` with `submit_command(...)` classifying
  `committed | replayed | rejected | transient`; idempotency keys derive client-side via
  `pulse_core.idempotency.derive_idempotency_key` (D16:
  `{writer_id}:{sha256(subject, command_type, payload, logical_time)}`); command types come from
  `pulse_core.generated`.
- The current-state read is a **library read, not HTTP**: S1.1 shipped no `GET /state` route.
  `pulse_ledger.reads.enumerate_state(conn, subject_type, states)` reads the co-committed
  `ledger.current_state` rows over a psycopg connection, catalog-validating the requested states
  (`IllegalTransitionError` on a typo) and paging by `subject_key`.
- D9 makes Customer.io authoritative for consent conflicts; D14 chose the platform scheduler
  (SPCS job / EventBridge Scheduler); D15 gives each writer its own credential, names in config,
  values from the environment.
- Both jobs write through the one command API — no direct ledger inserts; legality, idempotency,
  and attribution are the ledger's, not reimplemented here.
- The `idempotency_key`/`replayed` HTTP wiring gap (DNA-801) blocks S1.2, whose whole job is
  replay classification. It does not block this change's correctness — replays here are an
  accounting distinction on the receipt, and until DNA-801 lands they classify as `committed`
  while the store still guarantees no duplicate events — but receipt tests that assert `replayed`
  counts fake the client at the boundary, so they encode the target contract either way.

## Goals / Non-Goals

**Goals:**

- Two declarers, one operational shape: read an input set, compute the would-declare set, submit
  with idempotency keys, emit a receipt, exit nonzero on any invariant breach or failed
  declaration.
- Fail loudly: zero enrollments is a hard failure; malformed export rows are counted and attached,
  never dropped; a failed declaration fails the run so the scheduler's retry window re-drives it.
- Keep the scheduler out of the code: entrypoints are plain CLIs; the triggers are IaC config.

**Non-Goals:**

- No verdict computation or declaration (S1.2), no relay-run scheduling beyond what S1.2's own
  entrypoint exposes, no genesis backfill runs.
- No live Customer.io pull: v1 consumes a delivered export file path. The follow-on
  (`customerio-consent-ingress`) owns the pull once the export mechanism is confirmed.
- No new ledger surface — no endpoints, no schema, no migrations.

## Decisions

1. **One package, two modules, one CLI.** `packages/schedules` with
   `src/schedules/month_open.py`, `src/schedules/consent_sweep.py`, and `src/schedules/cli.py`
   (two subcommands). Both jobs are thin clock-driven declarers with identical shape — separate
   packages would duplicate the scaffold, receipt model, and infra dir for no isolation benefit.
   *Alternative rejected:* one module per package — the work order pins the single-package layout
   and the jobs share the receipt/dry-run machinery.
2. **Month-open enumerates via `pulse_ledger.reads.enumerate_state`, a Postgres library read.**
   Never the warehouse: month-open must not depend on projection freshness, and the co-committed
   `current_state` rows are the ledger's own truth. This makes `pulse-ledger` a workspace
   dependency of `schedules` (read module only) alongside `pulse-core` (write client). The
   catalog validation inside `enumerate_state` is the "typo is a rejection" behavior — the job
   does not pre-validate state names itself.
3. **Idempotency key grain: enrollment × billing month.** `logical_time` for
   `open_billing_episode` is the billing month as the ISO date string `YYYY-MM-01` (a `str` — of
   `derive_idempotency_key`'s `datetime | str`, the string form carries no wall-clock or timezone
   component to drift between runs), so any re-run within the month — same day, retry window,
   mid-month catch-up — replays; the next month derives a new key. For sweep corrections,
   `logical_time` is the export's as-of date, likewise the ISO date string `YYYY-MM-DD`, so
   re-running the same delivered export replays and a next-day export can legitimately re-correct.
4. **Zero-enrollment invariant checked after enumeration, before any submission.** The failure
   receipt is emitted and the process exits nonzero with no commands declared — a partial run on
   a broken read path would be worse than none.
5. **Sweep diff is set-based over (subject, channel) consent state.** Parse the export
   (fixture-pinned CSV format) into a suppression set; read ledger CommunicationConsent current
   state; corrections are the symmetric difference interpreted with the export as authority (D9).
   Actor is `reconciliation` — its own D15 credential — and every correction's payload carries the
   export row reference (file id + row number) as provenance. Unparseable rows accumulate on the
   receipt and never abort the run.
6. **Receipts are structured (JSON to stdout) and the exit status is the contract.** The
   scheduler and the runbooks key off exit status; the receipt carries the counts (month-open:
   opened / replayed / failed; sweep: agreements / corrections by direction / unparseable). No
   subject demographics in receipts or logs — subject keys and counts only (PHI rule).
7. **`--dry-run` computes the would-declare set and stops before the client.** Dry-run constructs
   the same commands (so it exercises key derivation and payload shape) and prints them instead of
   submitting; fixture inputs substitute the ledger read and the export file. This is what makes
   the Verification block's offline dry-run command work under `--disable-socket`.
8. **Infra config follows the monorepo IaC convention** (`packages/ocean/infra/terraform` is the
   pattern): `packages/schedules/infra/` holds the schedule definitions — month-open at 00:30 on
   the 1st with a same-day retry window, sweep daily — targeting the CLI subcommands per D14.
   Config only; applying it is a deploy step outside this change.
9. **Tests fake at two boundaries.** The command API is faked at the client boundary
   (`PulseCoreClient` substitute returning scripted classifications); the ledger read is faked at
   the `enumerate_state` boundary with recorded fixture responses. No live network anywhere
   (`--disable-socket`); no local Postgres needed — this package owns no schema, so store-level
   behavior is S1.1's tested territory, not re-proven here.

## Risks / Trade-offs

- **[DNA-801: client reports `committed` for replays]** → receipt `replayed` counts are wrong
  against the live API until the wiring gap lands, though no duplicate events are possible.
  Mitigation: tests pin the target classification contract at the fake boundary; the runbook notes
  the accounting caveat until DNA-801 closes.
- **[Fixture-pinned export format drifts from the real Customer.io export]** → the parser rejects
  rows and the drift receipt spikes. Mitigation: unparseable rows are attached, never dropped, and
  the consent-sweep runbook's drift-spike procedure covers exactly this; the follow-on ingress
  change re-pins the format when the mechanism is confirmed.
- **[Direct Postgres read couples schedules to ledger internals]** → accepted deliberately: the
  read module is S1.1's published surface (`docs/contracts/publishes.md`), and freshness
  correctness beats loose coupling for month-open. The coupling is one function.
- **[Retry window re-runs a partially failed month-open]** → safe by design: replays are the
  mechanism, not a hazard. The invariant to watch is key stability — the billing-month
  `logical_time` must not incorporate wall-clock time, which the replay tests pin.
- **[PHI in the suppression export]** → export contents are identifiers/contact data; receipts
  attach row references and parse errors, never raw contact values, and fixtures are synthetic
  only. Flagged for security review on the sweep's receipt/logging paths.

## Migration Plan

Pre-production, additive only: a new workspace member and dormant infra config. No live schedulers
until the infra config is applied in a deploy step outside this change. Rollback is removing the
package and its schedule definitions; no data migration exists.

## Open Questions

- Which D14 backend (SPCS job vs EventBridge Scheduler) the deploy lands on first — the config dir
  carries the chosen pattern per the monorepo convention, and the CLI is identical on either, so
  this can settle at deploy time without changing specs or tasks.
