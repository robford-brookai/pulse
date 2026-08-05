# Tasks — s12-verdict-relay

Annotation format, read by `task dispatch` and checked by G_MECE:
`[model | deps | lane | wave]`, with `serial:` carrying its justification where set. `deps` names
task numbers in this file; `—` means no dependency. Linear ids get bracketed in after
`task linear:sync`. Default model is `sonnet`, stated explicitly on every task; `opus` only on the
ordering/idempotency core, where a defect is expensive to retrofit.

**Entry condition (blocks dispatch/EXECUTE, not planning): DNA-801.** The
`idempotency_key`/`replayed` HTTP wiring gap in `pulse_ledger.api` must land before any task here
is enqueued — the declarer's replay classification (2.2 and everything downstream) depends on it.
See proposal.md and design.md Context.

Every task ships its tests in the same commit (tests first per `AGENTS.md`). No live network in
any test (`--disable-socket` posture); the command API is faked at the client boundary and mart
rows come from fixture-backed sources — no live Snowflake anywhere. Fixtures are synthetic only;
no PHI. Done means (work order Verification): `ruff check` + `pyright` clean on
`packages/verdict-relay`, coverage ≥ 85%, the property test passing, a socket-blocked pytest run
green, and `docs/runbooks/verdict-relay.md` present.

Scenario → task coverage (G_MECE bijection): each spec scenario is verified by exactly one task,
named on that task below.

---

## 1. Wave 0 — scaffold

- [x] 1.1 Scaffold `packages/verdict-relay` as a workspace member per the monorepo template:
      pyproject, uv workspace root entry, ruff/pyright/pytest wiring, coverage floor 85%,
      `hypothesis` as a dev dependency of this package only, `TESTED_PATHS` updated honestly.
      Test: package imports and an empty-suite pytest run passes under `--disable-socket`.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0]`
      `serial: workspace_roots` — edits the root workspace manifest and `Taskfile.yml`. Declared
      scope must equal executed scope (the pulse-ledger-core 1.3/1.4 lesson).

## 2. Wave 1 — reader and declarer

- [ ] 2.1 `src/verdict_relay/mart_reader.py`: `RowSource` protocol + fixture-backed source,
      contract validation (missing column / unparseable timestamp fails the run naming the row),
      (subject, `as_of`) ordering, `computed_at` page cursor persisted with the per-subject
      watermark via `pulse_core.cursor` (`cursor_path(writer_id)`, `validate_cursor`) — design
      decisions 2 and 3. Tests: ordered-batch shape; crash/resume from persisted cursor without
      re-reading; contract violation names the row.
      Scenarios: verdict-mart-read "A batch yields subject-grouped, as_of-ordered rows",
      "Crash and resume without re-reading".
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]`
- [ ] 2.2 `src/verdict_relay/declarer.py`: mart row → `declare_verdict` command (actor = service
      identity per D15, carrying `rule_version`, `as_of`, `lineage_ref`), D16 key via
      `pulse_core.idempotency.derive_idempotency_key`, pre-submission validation on the generated
      command type, stale-skip against the cursor watermark, and classification handling —
      committed / replayed / rejected (never retried, ledger reason logged) / transient
      (jittered backoff, 5 attempts, then fail naming the row). Command API faked at the client
      boundary. Tests: replay counted without re-declare; rejection counted with reason, no retry;
      transient exhausts 5 attempts and fails naming the row.
      Scenarios: verdict-declare "A replay is an idempotent hit, not a second declaration",
      "A rejection is counted, logged with the ledger's reason, and never retried",
      "A transient failure retries with backoff then fails the run naming the row".
      `[model: opus | deps: 1.1 | lane: repo_change | wave: 1]`
      Model `opus`: the ordering/idempotency core — the one artifact a retrofit can't cheaply fix
      on the single write path.

## 3. Wave 2 — batch entrypoint

- [ ] 3.1 `src/verdict_relay/run.py`: batch entrypoint, read → declare → receipt; five counts
      (declared, replayed, skipped-stale, rejected, failed) as structured JSON logs tagged
      `service:verdict-relay` with one Datadog-parsable `key=value` summary line; nonzero exit on
      run failure with the receipt reflecting completed work. Tests: mixed-batch receipt counts
      and summary line; log-content assertion that records carry subject keys only (the no-PHI
      lint from design decision 6); failed run exits nonzero.
      Scenario: verdict-relay-run "A mixed batch produces a complete receipt".
      `[model: sonnet | deps: 2.1, 2.2 | lane: repo_change | wave: 2]`

## 4. Wave 3 — fixture corpus and property test

- [ ] 4.1 `tests/fixtures/` recorded mart rows (JSON, synthetic) covering all six work-order
      cases — normal declare, idempotent replay, out-of-order stale run, illegal-transition
      rejection, indeterminate-with-reason, indeterminate-without-reason — plus the fixture-driven
      end-to-end suite over the faked client. Tests: normal declare submits attribution + lineage
      + D16 key and classifies committed; indeterminate-with-reason commits carrying the reason;
      indeterminate-without-reason fails validation with zero API calls (asserted on the fake).
      Scenarios: verdict-declare "A normal declare commits with attribution and lineage",
      "Indeterminate with a reason declares normally",
      "Indeterminate without a reason fails before the API call".
      `[model: sonnet | deps: 3.1 | lane: repo_change | wave: 3]`
- [ ] 4.2 `tests/test_ordering.py`: hypothesis property test — for any shuffled batch of runs per
      subject, declared order is `as_of`-monotonic per subject, every stale row is skipped and
      counted, and no stale row declares or errors. Deterministic profile in CI (fixed seed
      derivation, no deadline flake).
      Scenario: verdict-declare "A shuffled batch declares monotonically and skips stale rows".
      `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 3]`

## 5. Wave 4 — runbook and contract docs

- [ ] 5.1 `docs/runbooks/verdict-relay.md`: failure modes and operator actions for the §1.5
      monitors — staleness > 26 h and run failure — including reading the receipt, rejected vs
      failed, recovery-overlap replay counts (design risk 4), and safe re-run semantics against
      the persisted cursor. Test: docs-consistency check that the runbook exists, mkdocs builds
      strict, and both monitored failure modes are named.
      Scenario: verdict-relay-run "The runbook covers both monitored failure modes".
      `[model: sonnet | deps: 3.1 | lane: repo_change | wave: 4]`
- [ ] 5.2 Contract and supersession docs: add the verdict mart contract to
      `docs/contracts/consumes.md` (per roadmap P5) and a supersession note to
      `design/platform/clinic-rules-engine.md` (Snowpark emitter superseded by this relay on the
      single write path). Test: mkdocs strict build; docs-consistency gate green.
      `[model: sonnet | deps: 4.1, 4.2 | lane: repo_change | wave: 4]`
      `serial: openspec_main_specs` — doc-updater lane, spec-adjacent contract files.
