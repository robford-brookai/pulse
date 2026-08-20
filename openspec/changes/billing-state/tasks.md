# Tasks — billing-state

Annotation format, read by `task dispatch` and checked by G_MECE:
`[model | deps | lane | wave]`, with `serial:` carrying its justification where set. `deps`
names task numbers in this file; `—` means no dependency. Linear ids get bracketed in after
`task linear:sync`. Default model is `sonnet`, stated explicitly on every task.

Every task ships its tests in the same commit (tests first per `AGENTS.md`). `task check` stays
green, offline and credential-free at every step — every relay/ledger test runs under
`--disable-socket` with fixture transports. Synthetic data only; no PHI and no real payer
identifiers in fixtures, logs, receipts, or golden files. Specs are owned by the doc-updater:
write proposed spec changes to `HANDOFF.md`, never edit `openspec/specs/`.

**Entry conditions.** `twenty-projection` is in flight and owns three serial lanes this change
also needs: `catalog_generated_surfaces` (task 1.1 here), `workspace_roots` (task 3.2 here),
and `openspec_main_specs` (task 3.3 here). Those tasks dispatch only after twenty-projection
archives or explicitly hands the lane off. Wave 3 additionally requires the dbt mart to carry
the new verdict-type rows (proposal open question 2) and runs from the operator queue with a
G_APPROVAL comment, never a worktree.

---

## 1. Wave 0 — catalog and schema

- [x] 1.1 Coverage subject in the catalog: add `coverage` (ownership: ledger, transitions per
      design.md §2) to `catalog/state_catalog.yaml`, MINOR bump `catalog_version` to 1.1.0,
      regenerate `pulse_core.generated` via `catalog_gen`, freeze the byte-identical release
      copy `catalog/releases/v1.1.0.yaml` and append its sha256 to `MANIFEST.sha256`
      (append-only).
      Tests: render-drift gate green; generated `SUBJECT_TYPES`/`TRANSITIONS` carry coverage;
      derived initial state is `unverified` (no incoming edge); `task check` green.
      `[model: opus | deps: — | lane: repo_change | wave: 0]`
      `serial: catalog_generated_surfaces` — regenerates the generated surfaces and the release
      artifacts; the standing serial lane owns this file pair. Sequenced behind
      twenty-projection per Entry conditions.
      Opus: the catalog vocabulary is the one irreversible artifact — released versions land as
      immutable Snowflake rows (D18); a wrong state set survives forever.

- [x] 1.2 Alembic migration widening the three subject-type CHECK constraints
      (`ck_events_subject_type`, `ck_current_state_subject_type`,
      `ck_review_queue_subject_type`) to admit `coverage`, in
      `packages/pulse-ledger/infra/postgres/versions/`.
      Tests: a coverage transition validates AND commits (the
      `test_communication_consent_validates_but_cannot_yet_be_committed` pattern, flipped to
      green for coverage) (spec: "A catalog-legal coverage transition commits"); existing six
      subjects unaffected; migration up/down clean.
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 0]`

## 2. Wave 1 — the pairing, the configuration, the receipt

- [x] 2.1 Outcome→transition pairing in `verdict_relay.declarer`: per-verdict-type
      `transition_by_outcome` config schema; on a committed or replayed `declare_verdict`,
      submit a `declare_transition` on the same subject with a D16 key derived from the verdict
      row (replay-safe as a pair; a resumed run completes a half-finished pair); rejected
      transitions counted distinctly, never retried; verdict types without a
      `transition_by_outcome` entry behave exactly as today (verdict only). The declarer's
      counters gain `transitioned` and `transition_rejected`; threading them into the run
      receipt is task 2.4's scope. Tests here use a synthetic configured verdict type — the
      real type entries are task 2.2's scope.
      Tests (fixture transport): pair replays idempotently — rerun is replayed + replayed with
      no new events (spec: "The pair is idempotent as a unit"); death between verdict and
      transition completes the pair on resume (spec: "An interrupted pair completes on
      resume"); rejection at a closed lifecycle boundary counts transition-rejected without
      retry and keeps the verdict (spec: "A verdict against a reported episode keeps the
      verdict, drops the transition"); a type with no pairing entry submits exactly one command
      (spec: "An unpaired verdict type submits no transition").
      `[model: opus | deps: 1.1 | lane: repo_change | wave: 1]`
      Opus: this pairing is the mechanism of continuous billing state — a wrong mapping or a
      non-idempotent pair key writes wrong state that only surfaces at reconciliation.

- [x] 2.2 Verdict-type configuration and fixtures — sole owner of the shipped config entries
      and the fixture corpus: `subject_type_by_verdict` and `transition_by_outcome` entries for
      `billing_eligibility` (→ `billing_episode`), `coverage_eligibility` and
      `benefits_verification` (→ `coverage`); synthetic fixture corpus rows for all three;
      regression pins that an unmapped verdict type still fails before any API call.
      Tests: a positive `billing_eligibility` row commits its verdict and one paired transition
      to `qualified`, both attributed to the relay's identity (spec: "A positive
      billing-eligibility verdict qualifies the episode"); fixture rows carry synthetic
      identifiers only; unmapped-type pin green.
      `[model: sonnet | deps: 2.1 | lane: repo_change | wave: 1]`

- [x] 2.3 Coverage first-declare and enumeration, consuming (never editing) 2.2's config
      entries and fixture corpus: the subject-key convention for patient × payer, the minting
      rule (first verdict for an unseen key transitions from derived initial `unverified`), and
      an `enumerate_state` read proving coverage subjects enumerate from `current_state`.
      Tests: first verdict mints and transitions, second verdict transitions without re-mint
      (spec: "First declare mints and transitions"); enumeration returns coverage subjects by
      state from `current_state` (spec: "Lapsed coverage enumerates from the ledger"); the
      committed transition's `to_state` is coarse-vocabulary-only with QMB/benefit detail
      reachable only via verdict payload and `lineage_ref` (spec: "A verified coverage carries
      its detail in evidence, not state"); no payer identifier appears in any log line,
      asserted against a scripted synthetic payer value (spec: "A failure log carries no payer
      value").
      `[model: sonnet | deps: 1.2, 2.1, 2.2 | lane: repo_change | wave: 1]`

- [x] 2.4 Receipt extension in `verdict_relay.run`: `RunReceipt` and `summary_line()` gain the
      `transitioned` and `transition_rejected` counts wired from the declarer's counters, in
      the exact pinned seven-count form.
      Tests: a fixture mixed batch (paired declare, replay, stale row, verdict rejection,
      transition rejection) produces declared=2 replayed=1 skipped_stale=1 rejected=1
      transitioned=1 transition_rejected=1 failed=0 with the pinned summary line and no log
      line beyond subject keys (spec: "A mixed batch produces a complete receipt").
      `[model: sonnet | deps: 2.1 | lane: repo_change | wave: 1]`

## 3. Wave 2 — trigger, wiring, docs

- [x] 3.1 Production wiring and poll entry: config-constructed Snowflake `RowSource`,
      `LedgerCursorStore`, and service client (resolving the S1.3 deferral in
      `verdict_relay.run`) and a schedules-package poll entry with the no-op-run receipt
      (cursor at watermark → zero declarations, clean exit). No root `Taskfile.yml` edit —
      the task target is 3.2's scope.
      Tests: env resolution fails startup naming the missing variable before any connection
      (spec: "A missing variable fails startup by name"); fixture-driven no-op run emits the
      all-zero receipt and exits zero (spec: "A no-op poll exits clean"); an immediate rerun
      of a just-completed batch is all replays and stale-skips with zero new events, asserted
      at the run level (spec: "An extra run after a completed run changes nothing"); no
      credential value in any log.
      `[model: sonnet | deps: 2.2, 2.4 | lane: repo_change | wave: 2]`

- [ ] 3.2 Credentialed task target: register `task relay:run TARGET=<env>` in the root
      `Taskfile.yml` (credentialed, out of `task check`, `twenty:deploy` posture) and extend
      the reachability gate.
      Tests: `task check` passes offline and credential-free while the reachability test
      asserts `relay:run` is defined (spec: "Check stays offline while the target exists").
      `[model: sonnet | deps: 3.1 | lane: repo_change | wave: 2]`
      `serial: workspace_roots` — edits root `Taskfile.yml`, and nothing else; scoped this
      narrow so unserialized wiring work (3.1) does not wait on the lane. Sequenced behind
      twenty-projection per Entry conditions.

- [ ] 3.3 Contracts and docs: `docs/contracts/publishes.md` gains the new event types on the
      `patient-state` row (or a coverage/billing sub-row per its conventions);
      `docs/contracts/consumes.md` updates the verdict-mart row for the new verdict types;
      `docs/runbooks/billing-state.md` (new) covers the pairing semantics, poll cadence, no-op
      runs, transition-rejected triage, and rollback (stop the poll); `mkdocs.yml` nav entry.
      Tests: `mkdocs build -s` green; doc-presence gate names the runbook and the contract
      rows.
      `[model: sonnet | deps: 3.2 | lane: repo_change | wave: 2]`
      `serial: openspec_main_specs` — owns the shared files every registering change edits
      (`docs/contracts/publishes.md`, root `mkdocs.yml`). Sequenced behind twenty-projection
      per Entry conditions.

## 4. Wave 3 — live verification (operator lane)

- [ ] 4.1 Live declare-back on dev: run the migrated schema and the relay against the real
      mart (once the mart carries the new verdict types — open question 2); verify (a) a
      billing-eligibility row moves its episode to `qualified`/`not_qualified` in
      `current_state` and the transition event lands on the `patient-state` bus; (b) a
      coverage row mints and transitions a coverage subject; (c) an immediate second run is
      all-replays with zero new events (the replay-safety demo); (d) a row against a
      `reported` episode counts transition-rejected without retry. Receipt (subject keys,
      states, counts, wall-clock timings — no payload values, no payer identifiers) to this
      change's Linear parent.
      Verify: a repo-committed verification script exits nonzero on any failed check; its
      output is the receipt.
      `[model: sonnet | deps: 1.2, 2.3, 3.2, 3.3 | lane: operational_discovery | wave: 3]`
      Gate: G_APPROVAL comment from Rob on the tracking issue; operator queue, never a
      worktree.
