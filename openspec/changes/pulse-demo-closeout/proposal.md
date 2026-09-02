## Why

Four demos each prove one door of Pulse: the ledger keeps honest books (1), identity and the
webhook check credentials (2), the board is a live window (3), and verdicts become continuous
state (4). None proves the building. No demo follows one patient across seams, none exercises
`twenty-projection`, `consent-ingress`, or `synthea-seed`, and the roadmap's demo table
(`design/delivery/pulse-program-roadmap.md` §Demo breakpoints) names Demo 3 as the projection
rebuild drill while the shipped `demo3` script is the live kanban drag. With `connector-pattern`
archived (2026-09-02) and the billing engine's declare wiring moved to its own change, the
change slot is free and Pulse needs one demo an engineer can run in five minutes that shows
the whole claim: one truth, many windows, rebuildable from the journal. Decisions taken with Rob
2026-09-01 (`.planning/reports/2026-09-01-pulse-demo-closeout-gameplan.md` §4, §6): internal
engineering audience, within two weeks, offline mode first, the rebuild drill folded in as the
final act.

## What Changes

- **Demo 5, one patient through every seam** — `scripts/demo/demo5_end_to_end.py`, one script,
  one deterministic synthetic patient from `synthea-seed`, six stages in order: referral →
  identity resolution (mint, exact match, quarantine); consent export row → `consent-ingress`
  sweep → attributed consent state; signed kanban drag → commit, illegal drag → rejection plus
  one card note; fixture verdict → relay declare → paired transition and coverage mint; the
  windows agree (Twenty projection painted from the ledger, Snowflake landing holds the same
  events, independent fold equals `current_state`); destroy the Twenty projection and rebuild
  it from the journal, row-identical. Exits nonzero on any failed assertion.
- **Two modes, one script.** Offline: LocalStack, Postgres, fixture mart, fixture consent
  export, in-process Twenty route — the CI-shaped regression net the kit refactor was gated
  on. Live (`--live`): dev ledger, dev Twenty board, dev Snowflake landing — attended, receipts
  on a GitHub issue per WORKFLOW `live_execution`. Same assertions in both modes.
- **The rebuild drill ships here.** The queued `projection-rebuild-drill` change folds into
  this one as Demo 5's stage 6, closing the roadmap's Demo 3 promise; `twenty-projection`
  gains an authoritative rebuild entry point if it lacks one.
- **Demo drift fixed.** The roadmap demo table matches the shipped scripts; demos 3 and 4 get
  runbooks under `docs/runbooks/`; every demo gets a Taskfile target (`task demo:1` … `task
  demo:e2e`); a smoke-parse test keeps Demo 5 importable under `task check` without LocalStack.
- **Presentation refreshed.** The 2026-08-30 plain-language explainer gains the one-patient
  story as its spine, light-touch for the internal audience.

Out of scope, deliberately: the billing engine declaring anything (that is `billing-connector`,
seeded in `design/delivery/billing-connector-seed.md`); Customer.io outbound; a recorded video
or external-audience polish; `odg-read-redirect` (the roadmap's Demo 4 slot stays with Phase 4).

## Capabilities

### New Capabilities
- `end-to-end-demo`: the one-patient walk — stage order, the per-stage assertions, the two
  modes sharing one assertion set, synthetic-only data, nonzero exit on any failure, and the
  receipt shape for the live mode.
- `projection-rebuild`: the drill — a projection destroyed and rebuilt from the journal alone
  is row-identical to the one it replaced, and the rebuild is a first-class command, not a
  test-only trick (ADR §4.6 authoritative rebuild, `design/delivery/pulse-program-roadmap.md`).

### Modified Capabilities
<!-- No existing requirement changes. Demos assert shipped behavior; they do not alter it. -->

## Impact

- **Code**: new `scripts/demo/demo5_end_to_end.py` and `scripts/demo/fixtures/` (pinned
  Synthea cohort, fixture consent row, fixture verdict row); `packages/twenty-projection` gains
  or exposes a rebuild entry point; `Taskfile.yml` gains a `demo:` group kept out of `check`;
  `tests/` gains a smoke-parse test for demo5.
- **Docs**: `docs/runbooks/demo3-live-kanban-drag.md`, `demo4-billing-declare-back.md`,
  `demo5-end-to-end.md`; roadmap demo table corrected; presentation explainer refreshed.
- **Systems touched in live mode**: dev ledger Postgres, dev Twenty board, dev Snowflake
  `STG_EVENTS.EVENTS` read. Read-only against Snowflake; writes only to the dev ledger and dev
  board, under existing credentials named in config, values from the environment.
- **Dependencies**: none new. Demo 5 composes packages that already ship.

## Rollback

Demos and docs only. Rollback is deleting the script and reverting the doc edits. The one
production-code touch, the rebuild entry point in `twenty-projection`, is additive and gated by
its own tests; disabling it removes stage 6 from the demo and nothing else.
