# DevEx loop handoff — paused after audit 5

Rob's call, 2026-09-08 (`openspec/changes/devex-eight-4/design.md` decision 7). The loop pauses
here: `devex-eight` through `devex-eight-4` closed 42 of 49 encoded findings and returned the
connector golden path to green; the seven findings below stay encoded as strict xfails and wait
for a change that resumes the loop. No `devex-eight-5` exists yet — resuming means proposing one,
seeded from this document.

## Five-audit history

Scores and refs are `kind: audit` rows in `.planning/devex/loop.jsonl`.

| # | Date | Ref | Overall | Connector | Open findings | QA | Reports |
|---|---|---|---|---|---|---|---|
| 1 | 2026-09-02 | `99d9b7a` | 3.8 | 2.4 | 17 | accept-with-corrections | `.planning/reports/2026-09-02-devex-*` |
| 2 | 2026-09-04 | `b26dee0` | 5.9 | 5.8 | 0 | accept-with-corrections | `.planning/reports/2026-09-04-devex-*` |
| 3 | 2026-09-05 | `11622da` | 6.5 | 6.7 | 0 | accept-with-corrections | `.planning/reports/2026-09-05-devex-*` |
| 4 | 2026-09-05 (suffix b) | `5177d05` | 6.0 | 5.6 | 0 | accept-with-corrections | `.planning/reports/2026-09-05b-devex-*` |
| 5 | 2026-09-08 | `f851ae0` | 6.4 | 6.6 | 7 | accept-with-corrections | `.planning/reports/2026-09-08-devex-*` |

Exit gate (`docs/process/devex-audit/README.md`): overall >= 8.0 and connector >= 8.0. Not met at
any audit. Audit 4's `open_findings=0` while three defects were live on the connector golden path —
the gate's connector coverage asserted a task target existed, not that it worked (QA C-X1,
`devex-eight-4` proposal.md); audit 5 is the first to report a nonzero count by design, since the
protocol's "run at 0" rule did not anticipate a pause with findings still open.

Audits 2–4 moved the score inside a ±1 scorer-noise band (5.9 → 6.5 → 6.0) while the Community
dimension is capped near 4 by single authorship (no second committer exists to change that), so
clearing 8.0 needs two other dimensions at 9 — against a cost of about fifty PRs across three
changes and three days. That arithmetic, not a specific failure, is why decision 7 pauses the loop
rather than opening a sixth audit.

## What each change closed

- **`devex-eight`** (archived `2026-09-08-devex-eight`) — audit 1, 17 findings, overall 3.8 →
  connector 2.4. Wave 0 built the inner tier (`task devex:check`, `cat10_devex.py`,
  `.planning/devex/loop.jsonl`) and the frozen outer protocol under `docs/process/devex-audit/`.
  Wave 1: kit `__all__` exports; the connector authoring guide; `templates/connector/` and
  `task connector:new NAME=` performing all eight registrations; `task install` installing
  pre-commit hooks; `requires: vars: [CHANGE]` on the nine CHANGE-taking targets; `bootstrap.sh`
  refusing to run in a generated repo; real action SHAs; README prerequisites. Wave 2: one message
  from `Config.from_env()` naming every missing/invalid variable; one canonical connector spec;
  the docs site retitled with mkdocstrings on `pulse_core`; `task test:all` running the three shell
  gates; CODEOWNERS, issue/PR templates, a named owner and channel.
- **`devex-eight-2`** (archived `2026-09-08-devex-eight-2`) — audit 2, 12 findings, 5.9/5.8 →
  6.5/6.7. S fixes: authoring guide linked from README/CONTRIBUTING; `docs/index.md` a real front
  door; `task lore:init` plus the `verify` CHANGE guard; a prior-art collision warning in
  `connector:new`; `Jitter` exported; stale README/CONTRIBUTING claims fixed and gated;
  `.nvmrc`/`.editorconfig`/`.vscode/extensions.json`; PR template names `task check`; task
  descriptions lose ticket tokens. M items: template ships `tests/test_config.py` and
  `tests/factories.py`; the guide's tree diagram generated or gated; kit CHANGELOG and a
  deprecation-policy section. L item: `connector:new --direction inbound`.
- **`devex-eight-3`** (archived `2026-09-08-devex-eight-3`) — audit 3, 10 findings, 6.5/6.7 (this
  change started from that score; audit 4 later found it had fallen to 6.0/5.6, see below). S
  fixes: `commit.gpgsign=false` pinned in the scaffold's git helpers; `verify` guarded against an
  empty `CHANGE`; scaffold pyright posture registered instead of a `TYPED_PATHS` entry;
  `task lint` made read-only; every kit export documented in the guide with a diff test against
  `__all__`; rendered README next steps fixed; per-area CODEOWNERS and a connector-kit-defect issue
  template. M items: a complete working `declare` example with a replay assertion;
  `LedgerCursorStore` transport failures wrapped with endpoint and source variable; per-target
  `task check` timings appended to the ledger; a cold-cache TTHW arm. This change's task 2.1
  (PR #403) is also the source of audit 4's regression: a bare `from factories` import and a
  118-character `def run(` signature that shipped while `devex_open_findings` read 0, because no
  finding test rendered a connector and ran the real gate.
- **`devex-eight-4`** (this change, `openspec/changes/devex-eight-4`) — audit 4, formally 10
  findings encoded but scoped down to 3 by decision 7 partway through (2026-09-08); 6.0/5.6 → the
  audit-5 line above. Task 1.1 reverted the `from factories` regression: rendered suites now import
  under `--import-mode=importlib` alongside `packages/billing-connector/tests`, verified two
  directions at once rather than one (a second top-level `tests` package collides with
  `billing-connector`'s inside pytest's plugin manager). Task 1.2 made the rendered tree a
  `ruff format` fixed point in both directions and dropped the `slow` render-and-gate control's
  xfail. Task 2.1 deleted `test_connector_scaffold_command_exists` (asserted a target exists, not
  that it works) and let the render-and-gate control carry connector coverage. Task 3.1 ran audit 5
  and recorded the ledger row above. This document is task 3.2.

## The seven findings still open

Encoded as `xfail(strict=True)` in `tests/scaffold/cat10_devex.py`; `task devex:check` reports
`METRIC devex_open_findings=7` with no regressions as of this handoff. Task text below is copied
verbatim from `openspec/changes/devex-eight-4/tasks.md` at `origin/main` commit `992a787`, before
decision 7's replan — former task numbers in this change, not final numbers for whatever change
resumes them.

- **(former 1.3)** `task install` runs `task lore:init` alongside `pre-commit install`, so a fresh
  clone can make its first Python commit through the `openlore-drift` hook; `CONTRIBUTING.md`
  states it once.
  Tests: remove xfail from `test_documented_install_leaves_the_clone_able_to_commit_python`.
  `[model: haiku | deps: — | lane: repo_change | wave: 1 | serial: Taskfile.yml]`

- **(former 1.4)** A two-line owner-and-channel block in `README.md`'s first 40 lines, lifted from
  `CONTRIBUTING.md` — who owns this, where to ask.
  Tests: remove xfail from `test_readme_names_the_owner_and_the_channel_above_the_fold`;
  `test_readme_and_contributing_claims_are_current` stays green.
  `[model: haiku | deps: — | lane: repo_change | wave: 1]`

- **(former 1.5)** `docs/connectors/authoring.md`'s `from pulse_core.connector import (...)` paste
  block carries `TransientExhaustedError` and `LedgerCursorStoreError`, with the one-line glosses
  the block's other entries have.
  Tests: remove xfail from `test_guide_import_block_carries_the_errors_the_pipeline_raises`;
  `test_authoring_guide_documents_every_exported_name` stays green.
  `[model: haiku | deps: — | lane: repo_change | wave: 1]`

- **(former 1.6)** `.env.example` gains a commented connector block covering every `{{UPPER}}_*`
  variable the scaffold's `config.py.tmpl` generates, and the `PULSE_TWENTY_DEV_URL` /
  `PULSE_TWENTY_DEV_TOKEN` pair `task twenty:deploy TARGET=dev` demands. Placeholder values
  only — the file's own first line forbids real credentials, and no PHI.
  Tests: remove xfail from `test_env_example_carries_the_variables_the_tooling_demands`.
  `[model: haiku | deps: — | lane: repo_change | wave: 1]`

- **(former 2.2)** Week-one failures name the repo's own target: a failing `task lint` prints "run
  `task fmt`", and `spec:validate` and `lore:drift` name the `npm install -g` line from
  `README.md` when their npm global is missing. A wrapper in `scripts/devex/` is the obvious
  shape; a `preconditions:` entry works for the npm globals.
  Tests: remove xfail from `test_week_one_failures_name_the_repos_own_target`; the lint probe
  overrides `LINT_PATHS` to a scratch file, so nothing in the tree is touched.
  `[model: sonnet | deps: — | lane: repo_change | wave: 2 | serial: Taskfile.yml]`

- **(former 2.3)** `scripts/devex/timing.py` appends to a gitignored file instead of the tracked
  `.planning/devex/loop.jsonl`, whose `audit` rows stay tracked;
  `scripts/devex/check.py`'s `read_timings()` follows it; `task check`'s last command prints a
  per-target duration summary, so a green gate ends on its own numbers rather than the
  Material for MkDocs vendor warning.
  Tests: remove xfail from `test_a_green_gate_leaves_the_tree_clean_and_summarises_itself`;
  `test_ledger_exists_with_a_baseline_row` and `test_check_timings_are_recorded` stay green.
  `[model: sonnet | deps: — | lane: repo_change | wave: 2 | serial: Taskfile.yml]`

- **(former 2.4)** The TTHW test measures clone to a green `task check`, warm and cold cache, and
  reports `TTHW_TOTAL_SECONDS_WARM` and `TTHW_TOTAL_SECONDS_COLD`. It runs `task check` in the
  cloned tree, never in the repo under test, and stays `slow`. Audit-3's lesson holds: the numbers
  are valid only measured idle.
  Tests: remove xfail from `test_tthw_measures_clone_to_a_green_gate_in_both_arms`; both arms
  print their totals to the ledger.
  `[model: opus | deps: 2.3 | lane: repo_change | wave: 2]`

Note: `scripts/devex/timing.py` (former 2.3's own change) already appends `kind: timing` rows to
`.planning/devex/loop.jsonl` today — those rows are what this handoff's history table reads
around, filtered out by `read_timings()`. Whoever resumes former 2.3 should confirm on resume
whether the gitignored-file move still describes the current state or the finding text needs
updating first.

## Resume commands

1. Confirm nothing regressed since this handoff: `task devex:check` (expect
   `METRIC devex_open_findings=7`, no `REGRESSION` lines — run `uv sync --all-packages` first if
   the venv reports `ModuleNotFoundError` for a workspace package; a plain `uv sync` skips the
   workspace members `task devex:check` imports).
2. Propose the resuming change (via the `openspec-propose` skill / `/opsx:propose`), naming it for
   its place in the sequence (`devex-eight-5` unless a later change has claimed that name) and
   seeding wave 0 with the seven finding texts above, renumbered — they need no new xfail tests,
   only a wave/task/model assignment, since the tests already exist and are already open.
3. `openspec change validate <name> --strict`
4. `task replan CHANGE=<name>`
5. `task dispatch CHANGE=<name>`
6. Once every wave merges and `task devex:check` reports 0: run `/devex-audit` per
   `docs/process/devex-audit/README.md` (audit 6), append the ledger row, and re-evaluate the exit
   gate before deciding whether to pause again.

## Pause recorded

`design/delivery/pulse-program-roadmap.md`, "Standing decisions recorded here" — see that file for
the entry this handoff backs.
