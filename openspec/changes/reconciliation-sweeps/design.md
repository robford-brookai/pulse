## Context

See proposal.md for motivation. What exists: one sweep, `packages/schedules/src/schedules/consent_sweep.py`,
dispatched by `cli.py` and scheduled through the generated
`packages/schedules/infra/terraform/generated/schedule_catalog.auto.tfvars.json`; the
`consent-reconciliation` spec (export wins, actor `reconciliation` by credential, D16 replay-safe
keys, a drift receipt); the STG_EVENTS.EVENTS contract with `min_complete_from: 2026-08-26`
(`openspec/specs/snowflake-stg-events`, pulse-committed SQL at
`packages/ocean/infra/snowflake/stg_events_events.sql`); the Twenty projection keyed on
`(subject_id, ledger_seq)` (`openspec/specs/twenty-ledger-projection`); ADR §4.3 (one authority
per machine) and §4.6 (consumer state must cite a ledger sequence); ADR-0006 (pulse owns SQL over
surfaces pulse produces); catalog 1.1.0 with eight families, one `recorded`, seven `ledger`. The
v1 `MART_STATE.STATE_RECONCILIATION` view in `design/platform/snowflake-landing-spec.md` is a
superseded document whose shape (zero rows is healthy; correct through a new event) still holds.

## Goals / Non-Goals

**Goals:** one registry that gives every family a sweep by construction; a conformance check that
is a referee and never a writer; receipts an operator and a monitor can both read; a first attended
run that starts the P0 streak clock.

**Non-Goals:** correcting a ledger-owned projection (the §4.6 rebuild owns that); retiring
`patients.enrollment_status` (M1); Datadog monitors; the billing verdict window; the legacy
inference sentinel (dropped, decision 9).

## Decisions

1. **Two sweep kinds, derived from catalog ownership, never hand-listed.** `ownership: recorded`
   → `export_diff` (the consent sweep, unchanged); `ownership: ledger` → `projection_conformance`.
   The registry loads from the released `state_catalog.yaml`, so a catalog release that adds a
   family adds a sweep, and an unknown ownership refuses to load rather than silently skipping.
   Alternative rejected: seven more export diffs, which have nothing to diff against, since a
   ledger-owned family has no external system of record.
2. **The referee never writes for ledger-owned families.** A conformance sweep holds ledger read,
   projection read and warehouse read credentials only, and the credential-posture gate is told
   so. A divergence is a projection defect; the remedy is `twenty_projection.rebuild` or the
   landing's replay, both already shipped. Alternative rejected: auto-correcting the projection,
   which makes the sweep a second writer of the very state it polices.
3. **Comparison runs in the package, over readers; the warehouse fold is pulse-committed SQL.**
   Python compares reader outputs (ledger current state, board rows, folded warehouse rows,
   `patients` counts). The fold lives in a new view beside the STG_EVENTS SQL,
   `STREAMLINE.STG_EVENTS.SUBJECT_CURRENT_STATE` (latest landed event per `(subject_type,
   subject_key)` by `seq`, with `_loaded_at`), per ADR-0006. Alternatives: comparing inside
   Snowflake needs ledger state in Snowflake, which only arrives through the landing under test
   (circular); a dbt model in data-platform puts pulse-produced logic in the other repo, which
   ADR-0006 rules out.
4. **One snapshot per run.** The run pins the ledger head per subject at start (the command API's
   per-subject read); changes after the snapshot count as `in_flight`, never as divergence. Each
   consumer carries a freshness budget: 60 s for the board (the §1.5 projection-freshness SLO),
   15 minutes for the landing (configurable). A row whose cited `ledger_seq` is behind the head by
   more than the budget is `lag`.
5. **The history floor is a pinned constant with a test.** `MIN_COMPLETE_FROM = date(2026, 8, 26)`
   in the sweep configuration, asserted equal to the date in `docs/contracts/publishes.md` by a
   test, so the floor cannot drift from the contract silently. Subjects whose history is entirely
   before it are `pre_floor`.
6. **Consumer registry shape.** `Consumer(name, families, reader, cite_field, freshness_budget_s,
   owning_change)`; `cite_field=None` marks an uncitable consumer, reported as a class with its
   row count and `owning_change` (`m1-retire-patient-state` for graph-projection `patients`).
   Entries on day one: `twenty-board` (the families the app projects, read through the
   projection's own read surface), `warehouse-landing` (all families, through the fold view),
   `graph-projection-patients` (`enrollment`, uncitable). A ledger family with zero consumers
   passes with `no_consumers` in its receipt; it is not a divergence.
7. **Receipt shape.** One JSON line per family per run: `date`, `family`, `kind`, `floor`,
   `snapshot_head`, per consumer `agreements`, `divergences` by kind (`state`, `lag`, `missing`,
   `orphan`), `uncitable`, `in_flight`, `malformed`, `pre_floor`, and `subject_keys` by kind
   capped at 200 with the total count beside the cap; tags `project:pulse`,
   `service:schedules`, `family:<name>`. Never a payload value, payer identifier, or demographic.
   The same line is the receipt posted on the tracking issue after an attended run.
8. **Scheduling: one catalog entry per ledger family, daily.** Seven new entries beside
   `consent-sweep`, each `rate(1 day)`, `target_subcommand: reconcile-sweep`, an argument naming
   the family, so a failure or a streak is per family, which is how the P0 exit is written. The
   catalog is a generated surface and a serial lane; queued `billing-cutover`'s `verdict-reconcile`
   entry lands in the same file, never in the same wave. Alternative: one `--all` entry, rejected
   because one family's failure would hide the others' streaks.
9. **The legacy-inference sentinel is dropped.** Legacy-harvest item 4 hung on the signal adapter;
   roadmap P6 superseded that adapter and nothing else triggers the sentinel. Recorded here and in
   the roadmap so it stops being carried as optional.
10. **CLI and exit semantics follow the consent sweep.** `reconcile-sweep --family <name>
    [--dry-run]`; exit 0 when rows were compared (divergences are a receipt, not a failure), exit 2
    when no rows could be compared (configuration, connectivity, an empty read), matching the
    failed-declaration semantics s13 pinned.

## Data model and API surface

- Registry: `Family(name, ownership, sweep_kind)`; `Consumer` as in decision 6.
- Readers: `LedgerStateReader` (command API per-subject read), `BoardReader` (Twenty projection
  read surface), `LandingReader` (the fold view), `RowCountReader` (uncitable consumers),
  `FixtureReader` (tests). All read-only.
- Conformance result: `Comparison(subject_key, consumer, outcome ∈ {agreement, state, lag,
  missing, orphan, uncitable, in_flight, pre_floor, malformed}, fields: tuple[str, ...])`.
- Receipt: decision 7.
- CLI: decision 10. Snowflake view: decision 3.

## Risks / Trade-offs

- [False divergences from normal projection lag] → snapshot plus per-consumer freshness budget;
  `in_flight` and `lag` are distinct kinds so the receipt tells lag from disagreement.
- [The landing dies again and every warehouse subject reads `missing`] → that is the signal the
  sweep exists to produce; the sweep itself bounds its reads with query timeouts and still emits
  a receipt with `malformed`/`missing` counts rather than hanging.
- [Board reads hit Twenty rate limits] → the reader paginates per family and reads only the
  projected fields plus `ledger_seq`.
- [Schedule catalog collides with `billing-cutover`] → serial lane; the coordinator releases 3.1
  alone and never alongside a `verdict-reconcile` entry.
- [A catalog release adds a family nobody projects] → `no_consumers` in the receipt, pass, and a
  runbook step to register the consumer.
- [Two changes in flight collide on the schedules package] → `devex-eight-4` touches
  `tests/scaffold` and `templates/connector` only; no shared files.

## Migration Plan

Wave 0 lands the registry, the fold SQL and the readers (additive, no schedule). Wave 1 lands the
check and the CLI subcommand; `task check` runs it against fixtures. Wave 2 registers consumers,
adds the seven catalog entries, and documents. Wave 3 is the first attended run on dev (live
execution: GitHub issue plus runbook PR), which posts the first receipts and starts the streak
clock. Rollback: remove the catalog entries and re-apply the schedules Terraform; the sweeps wrote
nothing to the ledger.

## Open Questions

- Whether receipts also land in a Snowflake table for the drift-trend monitor, or the log line is
  enough. Decidable in `observability`; changes no spec here.
- Whether `coverage` (patient × payer grain) has any board consumer today. If none, its sweep
  passes with `no_consumers` until one registers; no task changes.
