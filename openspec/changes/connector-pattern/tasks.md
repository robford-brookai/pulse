# Tasks — connector-pattern

Annotation format, read by `task dispatch`:
`[model | deps | lane | wave]`, with `serial:` carrying its justification where set. `deps`
names task numbers in this file; `—` means no dependency. Linear ids get bracketed in after
`task linear:sync`. Default model is `sonnet`, stated explicitly on every task.

Every task ships its tests in the same commit (tests first per `AGENTS.md`). `task check` stays
green, offline and credential-free at every step — no live network in tests, fixture transports
only. Synthetic data only; no PHI, no real payer identifiers, no monetary values in fixtures,
logs, receipts, or golden files. Specs are owned by the doc-updater: write proposed spec
changes to `HANDOFF.md`, never edit `openspec/specs/`.

**Entry conditions.** No other change is in flight. Wave 0 task 1.1 resolves the cpt-om
ownership question with Rob before wave 2 dispatches. Task 2.5 runs as live execution — GitHub
issue + runbook PR + attended run per WORKFLOW v2.2.0 `live_execution` — never a worktree.

**Scope cut, 2026-09-01 (design.md decision 9).** This change ends at the connector kit and the
billing engine's scaffold, fact fold, and rule port. Evaluation-to-declare, deploy, the
reconciliation window, and cutover (formerly 3.4, 3.5, 4.1, 4.2, 5.1, 5.2) move to the
`billing-connector` change, whose entry gates are the findings recorded in
`handoffs/connector-pattern/task-010.md`.

---

## 1. Wave 0 — decisions and mapping

- [x] 1.1 Resolve cpt-om ownership (design.md decision 8): confirm with Rob whether the dbt
      verdict models encode the cpt-om revenue model's qualification logic. Amend
      `docs/contracts/producer-registry.md` accordingly (engine row added; cpt-om row updated
      or confirmed) and record the answer in `HANDOFF.md` for the doc-updater.
      Tests: producer-registry table parses (existing contract-doc gates); `task check` green.
      `[model: opus | deps: — | lane: operational_discovery | wave: 0]`
      Opus: this is a business-logic ownership call surfaced to a human — the task's output is
      a decision record, and a wrong registration misattributes every future verdict.

- [x] 1.2 [DNA-1271] Rule-port mapping document: for each dbt model and test under
      `data-platform/management/models/billing/verdict/` and `tests/billing/`, name its pulse
      counterpart (module, function, unit test) in `packages/billing/docs/rule-port-map.md`.
      Any rule needing warehouse-only facts is flagged `stays-mart-side` with the missing fact
      named (design.md risk 5).
      Tests: a repo test asserts every dbt object in the pinned list appears exactly once in
      the map; `task check` green.
      `[model: opus | deps: — | lane: repo_change | wave: 0]`
      Opus: the map decides what the engine computes — an omission here becomes a silent
      verdict gap.

## 2. Wave 1 — the connector kit, extracted

- [x] 2.1 [DNA-1272] Extract the inbound read contract into `pulse_core.connector`: `RowSource` protocol,
      per-row validation (error naming position and column, never a value), durable cursor via
      `pulse_core.cursor` scoped to a writer id. Refactor `consent_ingress.row_source` and
      `verdict_relay.mart_reader` onto it, deleting their private copies.
      Tests: donors' existing suites pass unchanged; new kit unit tests for the contract
      (spec: "A malformed row is named, the run survives", "A crashed run resumes from the
      durable cursor"); `task check` green.
      `[model: sonnet | deps: — | lane: repo_change | wave: 1]`

- [x] 2.2 [DNA-1273] Extract the declare pipeline into `pulse_core.connector`: D16 key derivation,
      response classification, retry-transient-only, counted receipt. Refactor
      `verdict_relay.declarer`/`run` onto it, preserving the seven-count receipt line
      byte-identically.
      Tests: relay suite passes unchanged; golden receipt-line test; kit unit test for
      (spec: "A rerun declares nothing twice"); `task check` green.
      `[model: sonnet | deps: 2.1 | lane: repo_change | wave: 1]`

- [x] 2.3 [DNA-1274] Extract the consume loop into `pulse_core.connector`: rule+queue convention,
      event-id dedupe, delete-after-success, monotonic watermark. Refactor twenty-projection's
      consumer onto it.
      Tests: projection suite passes unchanged; kit unit test for (spec: "A redelivered event
      applies once"); `task check` green.
      `[model: sonnet | deps: 2.1 | lane: repo_change | wave: 1]`

- [x] 2.4 [DNA-1275] Credential-posture gate: a scaffold-style test asserting every package under the
      connector convention holds exactly one writer credential name, no ledger DSN, and no
      credential value reachable by any log call (spec: "One connector, one credential, no
      ledger internals"). Revise `openspec/specs/connectors/pulse-standard-connector-spec.md`
      §4's `packages/connector-core (proposed)` note to point at `pulse_core.connector` — via
      `HANDOFF.md` for the doc-updater.
      Tests: the gate itself, red against a planted violation fixture, green on the tree.
      `[model: sonnet | deps: 2.1, 2.2, 2.3 | lane: repo_change | wave: 1]`

- [ ] 2.5 Wave-1 regression receipt: demos 1–4 run green on the refactored tree (1 and 2
      offline here; 3 and 4 in the next attended session, receipts to the tracking issue).
      Tests: demo1/demo2 exit 0 in CI-shaped local run; receipt committed under
      `handoffs/connector-pattern/`.
      `[model: haiku | deps: 2.1, 2.2, 2.3, 2.4 | lane: operational_discovery | wave: 1]`

## 3. Wave 2 — the billing engine (scaffold, fact fold, rule port)

- [x] 3.1 [DNA-1276] `packages/billing` scaffold on the kit: package layout, `billing_engine` Postgres
      schema migration (`subject_facts`, `evaluations` per design.md decision 5) under its own
      role/credential, and the shadow-ledger gate — a test pinning that no state-of-record
      read targets this schema.
      Tests: migration up/down clean; shadow-ledger gate red on a planted read, green on tree.
      `[model: sonnet | deps: 2.4 | lane: repo_change | wave: 2]`

- [x] 3.2 [DNA-1277] Fact folding: the engine's consume loop (kit) subscribes to `patient-state` and
      consent events, folds per-subject fact snapshots into `subject_facts` idempotently
      (event-id high-water per subject).
      Tests: redelivery folds once; out-of-order events fold by effective time; fixture-driven,
      `--disable-socket`.
      `[model: sonnet | deps: 3.1 | lane: repo_change | wave: 2]`

- [x] 3.3 [DNA-1278] Rule port per the 1.2 map: one pure module per verdict type with
      `RULE_VERSION = "pulse-<type>-v1"`, every dbt test mapped to a named unit test
      (spec: "Rules are ported with lineage, not re-imagined"). `stays-mart-side` rules
      excluded and documented.
      Tests: the mapped unit suite; a gate asserting each rule module's docstring names its
      dbt source and every mapped dbt test exists as a test function.
      `[model: opus | deps: 1.2, 3.1 | lane: repo_change | wave: 2]`
      Opus: the port is the correctness core of the whole change — a mistranslated predicate
      writes wrong billing state continuously.
