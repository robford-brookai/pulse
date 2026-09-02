# Tasks — pulse-demo-closeout

Annotation format, read by `task dispatch`:
`[model | deps | lane | wave]`, with `serial:` carrying its justification where set. `deps`
names task numbers in this file; `—` means no dependency. Linear ids get bracketed in after
`task linear:sync`. Default model is `sonnet`, stated explicitly on every task.

Every task ships its tests in the same commit (tests first per `AGENTS.md`). `task check` stays
green, offline and credential-free at every step — demo scripts stay out of `check`; only their
smoke-parse tests run there. Synthetic data only: the pinned Synthea cohort and committed
fixtures, never PHI, never real identifiers. Specs are owned by the doc-updater: write proposed
spec changes to `HANDOFF.md`, never edit `openspec/specs/`.

**Entry conditions.** `connector-pattern` archived (2026-09-02). Demos 1–4 pass on `main` as of
the 2.5 receipt (#319) — if 2.5 has not run when wave 1 dispatches, task 2.1 runs demos 1 and 2
offline as its first step and records the result. Task 3.3 is live execution — GitHub issue +
runbook PR + attended run per WORKFLOW v2.2.0 `live_execution` — never a worktree. Audience and
date per design.md: internal engineering, within two weeks of 2026-09-01.

---

## 1. Wave 0 — fixtures and drift

- [x] 1.1 Demo cohort fixtures: a `synthea-seed` overlay under `scripts/demo/fixtures/` pinning
      one patient with three referral variants (mint, exact match, quarantine), one consent
      export landing row keyed to that patient, and one verdict mart row for the patient's
      episode. Generated once, committed with seed and checksum in a `MANIFEST.md`.
      Tests: the overlay passes the `synthetic-population` overlay validator; a test asserts the
      three fixture files agree on the patient's identifiers; `task check` green.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0]`

- [x] 1.2 Demo drift: rewrite the roadmap's Demo breakpoints table
      (`design/delivery/pulse-program-roadmap.md`) to match shipped scripts (3 live kanban drag,
      4 billing declare-back, 5 end-to-end carrying the rebuild drill; `odg-read-redirect` to a
      Phase 4 row); write `docs/runbooks/demo3-live-kanban-drag.md` and
      `docs/runbooks/demo4-billing-declare-back.md` from the scripts' docstrings; add a
      `demo:` Taskfile area with `demo:1` … `demo:4`, kept out of `check`.
      Tests: the reachability gate proves no `demo:*` target is reachable from `check`; the
      docs-consistency gate (cat8) and `mkdocs build -s` green; `task check` green.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0]`

- [x] 1.3 Per-subject history read: confirm the command API exposes committed events for one
      subject in ledger sequence under the projection's credential (design.md decision 5). If
      it does, document the route in `HANDOFF.md` and stop. If not, add it read-only to
      `pulse-ledger`'s API and a `PulseCoreClient` method, additive.
      Tests: route returns a subject's events in sequence and nothing for an unknown subject;
      a credential without read scope is refused; `task check` green.
      `[model: opus | deps: — | lane: repo_change | wave: 0]`
      Opus: the one place this change may touch the ledger service — the scope call ("return
      committed events for a subject, nothing more") must hold or halt as design drift.

## 2. Wave 1 — the walk, offline

- [x] 2.1 Stage harness: `scripts/demo/demo5_end_to_end.py` with the `Stage` protocol,
      `DemoContext`, offline context builder (compose stack up, fixture landing tables loaded,
      in-process board route), receipt printer, nonzero exit on first failure. Stages 1–4 wired
      by extracting stage functions from demos 1–4 where they exist only inside `main`, with
      each original demo still passing.
      Tests: demos 1 and 2 exit 0 before and after extraction; smoke-parse test for demo5's
      import and argument parser added under `tests/` and run by `check`; a unit test drives the
      harness with two fake stages and asserts stop-on-first-failure and the receipt shape.
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]`

- [x] 2.2 Stage 5, the windows agree: the shape reducer `(subject_type, subject_key, state,
      as_of)` over board rows, landed events, and an independent fold; comparison fails on any
      disagreement and names stage, subject key, and field, never a value.
      Tests: reducer unit tests on each window type; a planted disagreement fails with the
      right message; a PHI tripwire asserts no payload value reaches the receipt or log.
      `[model: sonnet | deps: 2.1 | lane: repo_change | wave: 1]`

- [x] 2.3 Projection rebuild: `twenty_projection.rebuild` with CLI entry
      `rebuild --scope <subject_type>[:<key>]`, reading the subject's committed events via 1.3,
      folding through the existing apply handlers in sequence, diffing against current rows,
      writing only differences, printing a counted receipt (scope, read, written, differences).
      Tests (spec `projection-rebuild`, all five scenarios): destroy-then-rebuild is
      row-identical; rebuild over intact rows writes nothing; a mixed forward/backdated/reversal
      history rebuilds to the live-apply state; rerun is a no-op; out-of-scope rows untouched.
      `[model: opus | deps: 1.3 | lane: repo_change | wave: 1]`
      Opus: the rebuild is the proof that projections are windows — a fold that disagrees with
      live apply on ordering would pass the demo and lie.

- [x] 2.4 Ledger migration admitting `communication_consent`: a new Alembic migration in
      `packages/pulse-ledger/infra/postgres/versions/` extending `SUBJECT_TYPES` so the
      `ck_events_subject_type`, `ck_current_state_subject_type`, and `ck_review_queue_subject_type`
      check constraints admit `communication_consent` (the catalog seed's subject type, distinct
      from the older `consent`), following `0004_admit_coverage_subject.py`. Surfaced by 2.1's
      live run: `record_communication_consent` fails on `ck_events_subject_type` against a real
      migrated Postgres before catalog validation runs (`handoffs/pulse-demo-closeout/task-004.md`).
      Tests: migration up/down clean; a test commits a `record_communication_consent` command
      against a migrated Postgres and reads it back; a gate asserts every subject type in
      `pulse_core.generated.TRANSITIONS` is admitted by the constraints so the next catalog
      release cannot reopen this gap; `task check` green.
      `[model: sonnet | deps: — | lane: repo_change | wave: 1]`

- [x] 2.5 Consent writer id `customer-io`: the command API derives writer ids from
      `PULSE_LEDGER_WRITER_TOKEN_<SUFFIX>` by lowercasing and mapping `_` to `-`, so the
      `customer.io` actor the ingress and its spec name is unspellable and no dev credential could
      ever exist for stage 2 (surfaced by the first `task stage:e2e:live`, issue #342). Rename the
      ingress writer id to `customer-io` (`consent_ingress.declarer.CUSTOMERIO_WRITER_ID` and every
      docstring, `row_source.py`, `cli.py`, `docs/contracts/producer-registry.md`, ADR-0005 note,
      `tests/test_producer_registry.py`); the delta spec in this change already carries the MODIFIED
      requirement. Demo 5's stage 2 asserts the new actor.
      Tests: consent-ingress suite passes with the new id; a test asserts the id round-trips through
      `pulse_ledger.auth`'s suffix mapping (`CUSTOMER_IO` → `customer-io`); producer-registry gate
      green; `task check` green.
      `[model: sonnet | deps: — | lane: repo_change | wave: 1]`

## 3. Wave 2 — the drill, live mode, and the record

- [x] 3.1 Stage 6 and the runbook: wire the rebuild drill as the final stage (capture rows,
      delete scope, run 2.3, assert identical); write `docs/runbooks/demo5-end-to-end.md`; add
      `task demo:e2e` and `task demo:e2e:live`; live context builder (dev ledger URL, `httpx`
      board client as demo3 uses, read-only `STG_EVENTS.EVENTS` reader as the warehouse window)
      behind `--live`, with credential names in config and values from the environment only.
      Tests: offline demo5 exits 0 through stage 6 in a CI-shaped local run, receipt committed
      under `handoffs/pulse-demo-closeout/`; live context builder unit-tested with a fake
      transport; reachability gate holds; `task check` green.
      `[model: sonnet | deps: 2.2, 2.3, 2.4 | lane: repo_change | wave: 2]`

- [x] 3.2 Presentation refresh: `.planning/reports/2026-08-30-pulse-presentation.md` §3 becomes
      the one-patient story (six stages, one paragraph each, the four earlier demos referenced
      as the doors it passes through); §5 updated for the connector-pattern archive and the
      billing-connector seed. Plain language, internal engineering audience.
      Tests: `mkdocs build -s` unaffected (report is under `.planning/`); a reviewer can run
      `task demo:e2e` from the text alone — verified by the runbook cross-reference.
      `[model: sonnet | deps: 3.1 | lane: repo_change | wave: 2]`

- [ ] 3.3 Attended live run (live execution): GitHub tracking issue; `task demo:e2e:live`
      against dev in an attended session; receipt (stage counts, subject keys, wait times, never
      PHI) posted on the issue and committed under `handoffs/pulse-demo-closeout/`.
      Tests (runbook assertions): all six stages pass live; the rebuild drill's receipt shows
      zero differences; the board shows the rebuilt card within the 60 s freshness budget.
      `[model: sonnet | deps: 3.1, 2.5 | lane: operational_discovery | wave: 2]`
