# Tasks — billing-connector

Annotation format, read by `task dispatch`:
`[model | deps | lane | wave]`, with `serial:` carrying its justification where set. `deps`
names task numbers in this file; `—` means no dependency. Linear ids get bracketed in after
`task linear:sync`. Default model is `sonnet`, stated explicitly on every task.

Every task ships its tests in the same commit (tests first per `AGENTS.md`). `task check` stays
green, offline and credential-free at every step — no live network in tests, fixture transports
only. Synthetic data only; no PHI, no real payer identifiers, no monetary values in fixtures,
logs, receipts, or golden files. Specs are owned by the doc-updater: write proposed spec
changes to `HANDOFF.md`, never edit `openspec/specs/`.

**Entry conditions.** Second change in flight alongside `pulse-demo-closeout` (design.md
decision 9): tasks touching workspace roots or `Taskfile.yml` are serial-lane and the
coordinator releases them only when the other change has none in flight. Wave 0 lands four
scaffold PRs in order, each additive, each with a test, none changing behavior. Task 4.1 waits
on the dbt spike files landing in `data-platform` (seed gate 3). Tasks 4.2 and 5.1 are live
execution — GitHub issue + runbook PR + attended run per WORKFLOW v2.2.0 `live_execution` —
never a worktree.

---

## 1. Wave 0 — scaffold, four PRs

- [x] 1.1 Package scaffold: `packages/billing-connector/` with `pyproject.toml` (deps
      `pulse-core`, `billing`, workspace sources; dev group `pytest-socket`, `pyright`),
      `src/billing_connector/__init__.py` (version, one-paragraph module docstring naming the
      spec), `py.typed`; register in the workspace `pyproject.toml` members and in
      `Taskfile.yml` lint, typecheck, and test lists. No import of `pulse_core.connector` yet,
      so the credential gate does not discover it until 1.2.
      Tests: `tests/test_billing_connector_package.py` asserts importable, versioned, typed;
      `uv sync --all-packages` clean from a fresh clone (cat2 gate); `task check` green.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0 | serial: workspace roots and
      Taskfile.yml — coordinator releases alone across both in-flight changes]`

- [x] 1.2 Configuration: `config.py` with `Config` (frozen dataclass): `credential_name`
      (`BILLING_CONNECTOR_TOKEN`), `queue_url`, `ledger_base_url`, `stale_after` (duration,
      default from the dbt model's recency window, dbt source named in the docstring),
      `verdict_types` (read from the registry at startup, not from env); `Config.from_env()`
      raising with the missing variable's name; import `pulse_core.connector` so the
      credential-posture gate discovers the package (spec: "One credential, names in config,
      values from the environment").
      Tests: from_env round-trip with a fake environment; each missing variable names itself;
      no value reachable from `repr`/`str`; the credential gate passes with the package
      discovered; `task check` green.
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 0]`

- [x] 1.3 Code-tree stubs: `evaluate.py` (`Evaluation` dataclass, `evaluate_subject(store,
      registry, config, subject) -> list[Evaluation]`), `declare.py` (`DeclareResult`,
      `declare_pair(client, evaluation) -> DeclareResult`, `idempotency_key(evaluation)`),
      `service.py` (`main(argv) -> int`, `run_batch(...)`), `receipts.py` (`Receipt` extending
      the kit's counted receipt with `evaluated`, `deferred`; `format_line`). Every public
      symbol's docstring names the spec requirement it satisfies; bodies raise
      `NotImplementedError` except `receipts.format_line`, which is implemented against the
      golden. Add `billing.rules.registry` in `packages/billing` (additive): verdict type →
      module, populated with the one shipped module.
      Tests: a spec-coverage test asserts every `### Requirement` in the delta spec is named by
      at least one stub docstring; signature tests via `inspect`; registry equals the lineage
      gate's portable set; `format_line` golden; `task check` green.
      `[model: sonnet | deps: 1.2 | lane: repo_change | wave: 0]`

- [x] 1.4 Test harness: `tests/conftest.py` blocking sockets for every run that collects the
      package (verdict-relay's pattern); `tests/fixtures/` corpus skeleton with one fixture per
      spec scenario as named JSON stubs (fact snapshot in, expected evaluation and receipt
      counts out) and a corpus test that every scenario in the delta spec has a fixture file;
      fixture builders (`make_facts`, `make_stale_facts`, `make_event`) in
      `tests/factories.py`; fake `PulseCoreClient` transport recording submissions.
      Tests: the corpus test; builders produce valid snapshots per the engine's fact schema;
      `--disable-socket` proven by a test that any socket attempt fails; `task check` green.
      `[model: sonnet | deps: 1.3 | lane: repo_change | wave: 0]`

## 2. Wave 1 — behavior, one module per PR

- [ ] 2.1 Evaluation: fill `evaluate.py`. Load the subject's fact snapshot, derive
      `facts_stale` from `updated_at` against `stale_after` (design.md decision 5), run each
      registered rule module, write an `evaluations` row per verdict type with `rule_version`
      and the facts hash (spec: "Staleness comes from the connector's own watermark", "The
      connector evaluates the registered verdict types").
      Tests: fresh vs stale vs no-row fixtures; one registered type → one evaluation; registry
      mismatch halts; unchanged facts produce an identical evaluation (same hash); no monetary
      value in any evaluation row (tripwire).
      `[model: sonnet | deps: 1.4 | lane: repo_change | wave: 1]`

- [ ] 2.2 Declaration: fill `declare.py`. D16 key from `(subject_key, verdict_type,
      rule_version, facts_hash)`; verdict then paired transition through the kit's declare
      pipeline under the connector credential; `indeterminate` declares evidence only; record
      the declared event id on the `evaluations` row (spec: "The connector declares
      attributed, versioned verdict pairs", "No monetary value crosses the seam").
      Tests: replay classifies as replayed with no new event; rejected transition keeps the
      verdict and counts `transition_rejected`; amount-bearing fixture leaks nothing into
      payload, log, or receipt (tripwire); credential never logged.
      `[model: sonnet | deps: 2.1 | lane: repo_change | wave: 1]`

- [ ] 2.3 Service and triggers: fill `service.py`. Kit consume loop on the connector queue;
      episode and coverage subject events trigger evaluate → declare; consent and enrollment
      events fold and count `deferred` (design.md decision 4); receipt line per batch with
      `evaluated=N deferred=N` (spec: "Evaluation is event-driven, never batch-gated", "Every
      run ends in a counted receipt"). Write the fan-out catalog-fact proposal (consent and
      enrollment → episodes) to `HANDOFF.md`.
      Tests: episode-event fixture triggers exactly the affected subject; consent and
      enrollment fixtures evaluate nothing and count deferred; redelivered event evaluates
      once; receipt golden;
      end-to-end via fixture queue with `--disable-socket`.
      `[model: opus | deps: 2.2 | lane: repo_change | wave: 1]`
      Opus: this module decides what triggers a billing verdict — a wrong trigger set writes
      wrong state continuously, and the consent-fan-out proposal is a catalog design call.

## 3. Wave 2 — dev deploy

- [ ] 3.1 [DNA-1280] Deploy artifacts: Duplo service JSON, queue/DLQ/rule provisioning script
      with the narrow filter (design.md decision 7), runbook `docs/runbooks/billing-connector.md`
      (start/stop, receipt reading, rebuild-from-bus procedure). Deploy artifacts never
      reachable from `task check`.
      Tests: reachability gate (deploy targets out of `check`, existing pattern); rule filter
      pattern asserted without the emulator; `mkdocs build -s` green.
      `[model: sonnet | deps: 2.3 | lane: repo_change | wave: 2]`

- [ ] 3.2 Contracts: `docs/contracts/publishes.md` billing-connector producer row on
      `patient-state`; `consumes.md` cross-repo ask for the dbt spike files to land (seed gate
      3); CLAUDE.md `<id>` convention amended to "the change named in the command" (design.md
      decision 9). Via `HANDOFF.md` where a spec is touched.
      Tests: contract-doc gates; cat8 docs consistency; `task check` green.
      `[model: sonnet | deps: 3.1 | lane: repo_change | wave: 2]`

## 4. Wave 3 — reconciliation window

- [ ] 4.1 [DNA-1281] `verdict-reconcile` schedules entry: per-(subject, verdict_type)
      comparison of `evaluations` vs mart rows over matching fact windows; diff report with
      counts and subject keys only; empty-or-explained state machine for entries (spec:
      verdict-reconciliation, all three requirements). Blocked until the dbt spike files land
      in `data-platform` (seed gate 3) — the fixture mart is built from that commit.
      Tests: fixture mart + fixture evaluations produce the golden diff shapes — agree,
      timing-artifact, genuine divergence; PHI tripwire on report output.
      `[model: sonnet | deps: 3.1 | lane: repo_change | wave: 3]`

- [ ] 4.2 Open the window (live execution): GitHub tracking issue + runbook PR; attended start
      of the connector service on dev; both writers live; sweep scheduled; first sweep receipt
      on the issue. Window runs one full billing month.
      Tests (runbook assertions): connector declares on a live episode event without a
      scheduled run; sweep receipt posts; both writers' receipts attributable.
      `[model: sonnet | deps: 3.2, 4.1 | lane: operational_discovery | wave: 3]`

## 5. Wave 4 — cutover (gated on the 4.2 window closing empty-or-explained)

- [ ] 5.1 Cutover runbook PR + attended run: stop the relay poll, retire its Snowflake
      credential, closing sweep report committed as the receipt (spec: verdict-mart-read
      retirement requirement).
      Tests (runbook assertions): no Snowflake credential on the write path; connector-only
      verdicts continue; rollback rehearsed (re-enable poll from config).
      `[model: sonnet | deps: 4.2 | lane: destructive_ops | wave: 4]`

- [ ] 5.2 [DNA-1282] Docs close-out via `HANDOFF.md`: ADR for the write-path supersession,
      `consumes.md` mart row demoted, fonzie dependency-spec gap 1 note updated.
      Tests: `mkdocs build -s`; contract-doc gates; `task check` green.
      `[model: sonnet | deps: 5.1 | lane: repo_change | wave: 4]`
