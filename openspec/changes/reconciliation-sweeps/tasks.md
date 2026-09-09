# Tasks — reconciliation-sweeps

Annotation format, read by `task dispatch`:
`[model | deps | lane | wave]`, with `serial:` carrying its justification where set. `deps`
names task numbers in this file; `—` means no dependency. Linear ids get bracketed in after
`task linear:sync`. Default model is `sonnet`, stated explicitly on every task.

Every task ships its tests in the same commit (tests first per `AGENTS.md`). `task check` stays
green, offline and credential-free at every step: fixture readers only, no live Snowflake, Twenty
or ledger in tests. Synthetic data only; no PHI, no real payer identifiers, no payload values in
receipts, logs or golden files. Specs are owned by the doc-updater: write proposed spec changes to
`HANDOFF.md`, never edit `openspec/specs/`.

**Entry conditions.** Second change in flight alongside `devex-eight-4`, which touches
`tests/scaffold/` and `templates/connector/` only; no shared files. The schedule catalog
(`packages/schedules/infra/terraform/generated/schedule_catalog.auto.tfvars.json`) is a generated
surface and a serial lane, shared with the queued `billing-cutover` change: 3.1 releases alone.
Task 4.1 is live execution (GitHub issue + runbook PR + attended run per WORKFLOW v2.2.0
`live_execution`), never a worktree.

---

## 1. Wave 0 — registry and readers

- [x] 1.1 Sweep registry derived from the catalog: `packages/schedules/src/schedules/sweep_registry.py`
      loads the released `catalog/state_catalog.yaml`, maps `ownership: recorded` →
      `export_diff` and `ownership: ledger` → `projection_conformance`, refuses any other value
      naming the family, and exposes `Family`/`Consumer` types (design.md decisions 1 and 6).
      Tests: recorded → export_diff; ledger → projection_conformance; unknown ownership refused
      with the family name; registry family set equals the catalog's; a `Consumer` with
      `cite_field=None` is uncitable.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0]`

- [ ] 1.2 Warehouse fold as pulse-committed SQL: `packages/ocean/infra/snowflake/subject_current_state.sql`
      defines `STREAMLINE.STG_EVENTS.SUBJECT_CURRENT_STATE` (latest landed event per
      `(subject_type, subject_key)` by `seq`, carrying `_loaded_at`, bounded below by
      `min_complete_from`), in the style of `stg_events_events.sql`; proposed `publishes.md` row
      to `HANDOFF.md` (design.md decision 3, ADR-0006).
      Tests: SQL text test asserting the floor predicate, the fold window and the column set;
      a fixture-driven fold test over a small landed-events table in the offline Snowflake
      stand-in used by `snowflake-projection`'s tests.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0 | serial: pulse-owned warehouse SQL beside stg_events_events.sql, one published surface]`

- [x] 1.3 Read-only readers: `LedgerStateReader` (command API per-subject read, snapshot head),
      `BoardReader` (the Twenty projection's read surface, projected fields plus `ledger_seq`,
      paginated per family), `LandingReader` (the fold view), `RowCountReader` (uncitable
      consumers), `FixtureReader`; socket-blocked tests; no writer credential anywhere.
      Tests: each reader against fixtures; the credential-posture gate counts the sweep's
      credentials as read-only; a reader that returns unparseable rows yields them as
      `malformed`, never raises past the row.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0]`

## 2. Wave 1 — the check

- [ ] 2.1 Projection conformance core: `packages/schedules/src/schedules/projection_conformance.py`
      takes a snapshot, compares per `(subject_type, subject_key)`, classifies every pair as
      `agreement | state | lag | missing | orphan | uncitable | in_flight | pre_floor | malformed`,
      names differing fields never values, applies per-consumer freshness budgets and the pinned
      `MIN_COMPLETE_FROM` floor (design.md decisions 4 and 5). Pure functions over reader outputs.
      Tests: one golden fixture per outcome kind (spec `projection-conformance`, every scenario);
      the floor constant equals the date in `docs/contracts/publishes.md`; an uncitable consumer
      is reported as a class with row count and owning change and never compared per row;
      a PHI tripwire asserts no value field reaches any result.
      `[model: opus | deps: 1.1, 1.3 | lane: repo_change | wave: 1]`
      Opus because the classifier decides what counts as drift; a wrong rule reports false
      divergences every day for every family.

- [ ] 2.2 Receipt and CLI: `Receipt` per design.md decision 7 (JSON line, tags, subject-key cap
      200 with totals), `reconcile-sweep --family <name> [--dry-run]` subcommand in `cli.py` with
      exit 0 when rows were compared and 2 when none could be, the consent sweep dispatched
      through the registry as the `communication_consent` entry with its existing tests untouched
      (design.md decision 10).
      Tests: receipt golden for a clean run and a divergent run; exit codes; the cap; ten
      synthetic daily receipts yield a computable streak; `test_consent_sweep.py` and
      `test_cli.py` stay green.
      `[model: sonnet | deps: 1.1, 2.1 | lane: repo_change | wave: 1]`

## 3. Wave 2 — wiring and docs

- [ ] 3.1 Schedule catalog: seven `reconcile-sweep-<family>` entries (`rate(1 day)`,
      `target_subcommand: reconcile-sweep`, family argument) in the generated catalog and their
      Terraform module instances; `test_infra_schedules.py` extended to assert one entry per
      ledger family and none for the recorded one (design.md decision 8).
      Tests: catalog ↔ registry parity test; Terraform render test as the existing entries have.
      `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2 | serial: schedule_catalog.auto.tfvars.json is a generated surface shared with queued billing-cutover]`

- [ ] 3.2 Consumer registration: `twenty-board` (the families the app projects, budget 60 s),
      `warehouse-landing` (all families, budget 15 min, configurable), `graph-projection-patients`
      (`enrollment`, uncitable, owning change `m1-retire-patient-state`); a ledger family with no
      consumers receipts `no_consumers` and passes (design.md decision 6).
      Tests: registry × consumer matrix golden; the uncitable entry names its owning change;
      `no_consumers` path.
      `[model: sonnet | deps: 1.3, 2.1 | lane: repo_change | wave: 2]`

- [ ] 3.3 Docs via `HANDOFF.md` where a spec or contract is touched: `publishes.md` receipt line
      and fold-view rows; `consumes.md` STG_EVENTS floor dependency; roadmap row updated and the
      legacy-inference sentinel recorded as dropped (design.md decision 9);
      `docs/runbooks/reconciliation-sweeps.md` (attended first run, reading a receipt, computing
      the streak, registering a new consumer); mkdocs nav.
      Tests: `mkdocs build -s`; cat8 docs gates; `task check` green.
      `[model: haiku | deps: 2.2 | lane: repo_change | wave: 2]`

## 4. Wave 3 — first run

- [ ] 4.1 First attended run on dev (live execution): GitHub tracking issue; each ledger family's
      sweep run once against dev with read-only credentials; the eight receipt lines posted on the
      issue (subject keys and counts only); the P0 streak clock noted as started; any `missing`
      spike cross-checked against the warehouse-sync liveness probe (#413).
      Tests (runbook assertions): every family produces exactly one receipt; `patients` is
      reported as uncitable with a count; no command reaches the command API during the run.
      `[model: sonnet | deps: 3.1, 3.2, 3.3 | lane: operational_discovery | wave: 3]`
