## Why

Phase 3's exit criterion (ADR §6) reads "reconciliation clean over one full cycle", and the only
sweep pulse runs today is the D9 consent export diff. Every other projection of the ledger, the
Twenty board, the warehouse landing, graph-projection's `patients` table, is a copy nothing checks
after it is written. Demo 5 (2026-09-02) proved the windows agree for one subject once, and found
the warehouse feed dead for four days on the way. The cutover ladder also needs this instrument:
P0 exits on "drift below tolerance for ten consecutive business days per family", a number no
component produces yet. Gate open since `snowflake-projection` archived 2026-08-26.

## What Changes

- **A sweep registry in `packages/schedules`**, one entry per catalog family, keyed off
  `catalog/state_catalog.yaml` ownership. The registry names the sweep kind per family: an
  export diff for `ownership: recorded` families (the existing consent sweep is that entry), a
  projection-conformance sweep for `ownership: ledger` families. Seven of the eight families are
  ledger-owned, so "generalizing the consent sweep" is a second kind of check, not seven more
  export diffs: a ledger-owned family has no external system of record to defer to.
- **Projection conformance**: for each registered consumer of a ledger-owned family, compare the
  consumer's projected state with the ledger's current state per `(subject_type, subject_key)`,
  and require every projected row to cite the `ledger_seq` it was applied from (ADR §4.6). A
  divergence or an uncitable row is reported, never corrected: for a ledger-owned family the
  ledger is the record and the remedy is the §4.6 rebuild, so the sweep is a referee, not a
  second writer. Registered consumers on entry: the Twenty board (`twenty-projection`, keyed on
  `(subject_id, ledger_seq)`) and the warehouse landing (`STG_EVENTS.EVENTS` folded per subject).
  graph-projection's `patients` table registers as a consumer that cannot cite a ledger sequence
  and is reported as such on every run: that report is the hand-off to `m1-retire-patient-state`.
- **A history floor.** No sweep asserts divergence for events before the STG_EVENTS contract's
  `min_complete_from` (2026-08-26); every receipt states the lower bound it swept from.
- **Warehouse-side comparison as pulse-committed SQL**, beside the STG_EVENTS view, per
  ADR-0006 (pulse owns SQL over surfaces pulse produces). The v1 `STATE_RECONCILIATION` view in
  `design/platform/snowflake-landing-spec.md` supplies the shape (zero rows is healthy, correct
  through a new event, never a state edit), not the implementation: its entity vocabulary is v1.
- **Schedule catalog entries** per sweep in the generated
  `packages/schedules/infra/terraform/generated/schedule_catalog.auto.tfvars.json`, daily, on the
  existing schedules image and CLI. The catalog is a generated surface and a serial lane; the
  queued `billing-cutover` change's `verdict-reconcile` entry lands in the same file and never in
  the same wave.
- **Receipts** carry per-family counts (agreements, divergences, uncitable rows, unparseable
  rows) and subject keys only, never payload values, as one Datadog-parsable line tagged
  `project:pulse`, so the drift trend the observability plan names can be read from logs until
  a monitor exists. Ten consecutive clean receipts per family is the P0 exit's evidence.
- **The legacy-inference drift sentinel is dropped.** Legacy-harvest item 4 hung on the signal
  adapter, which roadmap position P6 superseded; a sentinel comparing declared state to legacy
  inference has no live trigger and no owner. Recorded so it stops being carried as "optional".

Out of scope: correcting a ledger-owned family's divergence (that is `twenty_projection.rebuild`
and ADR §4.6); retiring `patients.enrollment_status` (`m1-retire-patient-state`, which this
change's uncitable-consumer report feeds); Datadog monitors and paging (`observability`); the
billing verdict window (`billing-cutover`).

## Capabilities

### New Capabilities
- `reconciliation-sweeps`: the per-family sweep framework: a registry keyed off catalog
  ownership that maps each family to a sweep kind and its consumers, daily scheduled execution
  on the schedules CLI, the referee posture (corrections only for recorded families, reports only
  for ledger-owned ones), the history floor, and the receipt shape.
- `projection-conformance`: the check a ledger-owned family gets: projected state equals ledger
  current state per subject, every projected row cites its `ledger_seq`, divergences and
  uncitable rows are named by subject key, and consumers that cannot cite at all are reported as
  a class.

### Modified Capabilities
- (none) The `consent-reconciliation` requirements stand unchanged; the consent sweep becomes the
  registry's `recorded`-family entry without its behavior changing.

## Impact

- **Code**: `packages/schedules` gains `sweep_registry.py`, `projection_conformance.py`, a
  `reconcile-sweep --family <name>` CLI subcommand, fixtures and tests; pulse-committed Snowflake
  SQL for the per-subject fold-and-compare view beside the STG_EVENTS view; a read-only Twenty
  board reader (the projection's own read surface, no writes); schedule catalog entries and their
  Terraform (generated surface, serial lane).
- **Contracts**: `docs/contracts/publishes.md` gains the receipt line as an operator-visible
  surface and the comparison view as a pulse-owned warehouse object; `consumes.md` cites the
  STG_EVENTS `min_complete_from` floor as the sweep's dependency.
- **Runtime**: new daily jobs on the existing schedules deployment with read-only credentials
  (ledger read, Twenty read, Snowflake read). No new ledger writer credential: ledger-owned
  sweeps never declare. The consent sweep keeps its `reconciliation` writer credential.
- **Cross-change**: `m1-retire-patient-state` consumes the uncitable-consumer report;
  `billing-cutover` shares the schedule catalog file; `observability` consumes the receipt line.
- **Rollback**: remove the schedule catalog entries and redeploy the schedules Terraform; the new
  sweeps write nothing to the ledger, so there is no state to unwind. The consent sweep is
  untouched by this change.
