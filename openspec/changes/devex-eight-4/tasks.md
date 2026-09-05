# Tasks — devex-eight-4

Annotation format, read by `task dispatch`:
`[model | deps | lane | wave]`, with `serial:` carrying its justification where set. `deps`
names task numbers in this file; `—` means no dependency. Model is stated explicitly on every task.

Every fix task removes the `xfail` marker of the finding it closes in
`tests/scaffold/cat10_devex.py` so `task devex:check` drops by exactly that finding, and ships its
tests in the same commit. `task check` stays green, offline and credential-free at every step.
Synthetic data only; no PHI. Specs are owned by the doc-updater: write proposed spec changes to
`HANDOFF.md`. Never edit `docs/process/devex-audit/*` in this change (frozen, CHECKSUMS). Tasks
touching `Taskfile.yml`, `pyproject.toml` or `.github/` are serial-lane; the coordinator may run
non-Taskfile tasks alongside a serial one when they share no files.

---

## 0. Wave 0 — findings encoded (one PR, coordinator session)

- [ ] 0.1 Ten audit-4 findings as `xfail(strict=True)` tests in `tests/scaffold/cat10_devex.py`,
      each asserting the behaviour its fix produces against a rendered tree or the repo's own
      output, plus the `slow` render-and-gate control; change artifacts;
      `task replan CHANGE=devex-eight-4` green.
      Tests: `task devex:check` prints `METRIC devex_open_findings=10`; `task check` green.
      `[model: opus | deps: — | lane: repo_change | wave: 0]`

## 1. Wave 1 — the S fixes

- [ ] 1.1 The rendered test suites import their fixtures under `--import-mode=importlib` in the
      repo's combined run. Do **not** copy `packages/billing-connector`'s `tests/__init__.py`
      wholesale: verified in a scratch tree, a second top-level `tests` package collides with it
      inside pytest's plugin manager as soon as both are in `TESTED_PATHS`. The measured shape is
      no `tests/__init__.py` and a relative `from .factories import ...` in both direction
      overlays (194 passed across billing-connector plus both rendered directions); design.md
      decision 2 has the reproduction. Update the guide's rendered-tree fence if the file set
      moves.
      Tests: remove xfail from `test_rendered_connector_suites_run_under_the_repos_import_mode`;
      cat9 goldens regenerated with REGEN=1 and reviewed.
      `[model: opus | deps: — | lane: repo_change | wave: 1]`

- [ ] 1.2 The rendered tree is a `ruff format` fixed point in both directions: split the outbound
      `def run(` signature (118 characters against `line-length = 120`) so the formatter leaves it
      alone, and check the whole rendered tree rather than that one line. Then remove the `slow`
      control's xfail marker too — with 1.1 landed it passes, and a strict xfail that starts
      passing fails `task test:all`.
      Tests: remove xfail from `test_rendered_connector_is_a_ruff_format_fixed_point` and from
      `test_rendered_connectors_pass_the_real_gate`; cat9 goldens regenerated.
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]`

- [ ] 1.3 `task install` runs `task lore:init` alongside `pre-commit install`, so a fresh clone can
      make its first Python commit through the `openlore-drift` hook; `CONTRIBUTING.md` states it
      once.
      Tests: remove xfail from `test_documented_install_leaves_the_clone_able_to_commit_python`.
      `[model: haiku | deps: — | lane: repo_change | wave: 1 | serial: Taskfile.yml]`

- [ ] 1.4 A two-line owner-and-channel block in `README.md`'s first 40 lines, lifted from
      `CONTRIBUTING.md` — who owns this, where to ask.
      Tests: remove xfail from `test_readme_names_the_owner_and_the_channel_above_the_fold`;
      `test_readme_and_contributing_claims_are_current` stays green.
      `[model: haiku | deps: — | lane: repo_change | wave: 1]`

- [ ] 1.5 `docs/connectors/authoring.md`'s `from pulse_core.connector import (...)` paste block
      carries `TransientExhaustedError` and `LedgerCursorStoreError`, with the one-line glosses the
      block's other entries have.
      Tests: remove xfail from `test_guide_import_block_carries_the_errors_the_pipeline_raises`;
      `test_authoring_guide_documents_every_exported_name` stays green.
      `[model: haiku | deps: — | lane: repo_change | wave: 1]`

- [ ] 1.6 `.env.example` gains a commented connector block covering every `{{UPPER}}_*` variable
      the scaffold's `config.py.tmpl` generates, and the `PULSE_TWENTY_DEV_URL` /
      `PULSE_TWENTY_DEV_TOKEN` pair `task twenty:deploy TARGET=dev` demands. Placeholder values
      only — the file's own first line forbids real credentials, and no PHI.
      Tests: remove xfail from `test_env_example_carries_the_variables_the_tooling_demands`.
      `[model: haiku | deps: — | lane: repo_change | wave: 1]`

## 2. Wave 2 — the M items

- [ ] 2.1 Delete `test_connector_scaffold_command_exists` and let the render-and-gate control carry
      the gate's connector coverage; widen the control if the audit's below-the-cut tree-diagram
      item is cheap to fold in.
      Tests: remove xfail from `test_the_gate_measures_the_golden_path_not_the_command_listing`;
      `task devex:check` still reports the count it should.
      `[model: opus | deps: 1.1, 1.2 | lane: repo_change | wave: 2]`

- [ ] 2.2 Week-one failures name the repo's own target: a failing `task lint` prints "run
      `task fmt`", and `spec:validate` and `lore:drift` name the `npm install -g` line from
      `README.md` when their npm global is missing. A wrapper in `scripts/devex/` is the obvious
      shape; a `preconditions:` entry works for the npm globals.
      Tests: remove xfail from `test_week_one_failures_name_the_repos_own_target`; the lint probe
      overrides `LINT_PATHS` to a scratch file, so nothing in the tree is touched.
      `[model: sonnet | deps: — | lane: repo_change | wave: 2 | serial: Taskfile.yml]`

- [ ] 2.3 `scripts/devex/timing.py` appends to a gitignored file instead of the tracked
      `.planning/devex/loop.jsonl`, whose `audit` rows stay tracked;
      `scripts/devex/check.py`'s `read_timings()` follows it; `task check`'s last command prints a
      per-target duration summary, so a green gate ends on its own numbers rather than the
      Material for MkDocs vendor warning.
      Tests: remove xfail from `test_a_green_gate_leaves_the_tree_clean_and_summarises_itself`;
      `test_ledger_exists_with_a_baseline_row` and `test_check_timings_are_recorded` stay green.
      `[model: sonnet | deps: — | lane: repo_change | wave: 2 | serial: Taskfile.yml]`

- [ ] 2.4 The TTHW test measures clone to a green `task check`, warm and cold cache, and reports
      `TTHW_TOTAL_SECONDS_WARM` and `TTHW_TOTAL_SECONDS_COLD`. It runs `task check` in the cloned
      tree, never in the repo under test, and stays `slow`. Audit-3's lesson holds: the numbers are
      valid only measured idle.
      Tests: remove xfail from `test_tthw_measures_clone_to_a_green_gate_in_both_arms`; both arms
      print their totals to the ledger.
      `[model: opus | deps: 2.3 | lane: repo_change | wave: 2]`

## 3. Close-out

- [ ] 3.1 Run `/devex-audit` when `task devex:check` reports 0 open findings; append the ledger
      row; report whether the exit gate holds (overall >= 8.0 and connector >= 8.0), else open
      `devex-eight-5`.
      Tests: ledger row present with `kind: audit`; the three dated reports exist.
      `[model: opus | deps: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4 | lane: repo_change | wave: 3]`
