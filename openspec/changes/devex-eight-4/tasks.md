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

- [x] 0.1 Ten audit-4 findings as `xfail(strict=True)` tests in `tests/scaffold/cat10_devex.py`,
      each asserting the behaviour its fix produces against a rendered tree or the repo's own
      output, plus the `slow` render-and-gate control; change artifacts;
      `task replan CHANGE=devex-eight-4` green.
      Tests: `task devex:check` prints `METRIC devex_open_findings=10`; `task check` green.
      `[model: opus | deps: — | lane: repo_change | wave: 0]`

## 1. Wave 1 — the S fixes

- [x] 1.1 The rendered test suites import their fixtures under `--import-mode=importlib` in the
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

## 2. Wave 2 — the M items

- [ ] 2.1 Delete `test_connector_scaffold_command_exists` and let the render-and-gate control carry
      the gate's connector coverage; widen the control if the audit's below-the-cut tree-diagram
      item is cheap to fold in.
      Tests: remove xfail from `test_the_gate_measures_the_golden_path_not_the_command_listing`;
      `task devex:check` still reports the count it should.
      `[model: opus | deps: 1.1, 1.2 | lane: repo_change | wave: 2]`

## 3. Close-out

- [ ] 3.1 Run `/devex-audit` once 1.1, 1.2 and 2.1 are merged and `task devex:check` reports
      exactly the seven paused findings (design.md decision 7); append the ledger row; report the
      scores against the exit gate (overall >= 8.0 and connector >= 8.0). Whatever the result,
      no `devex-eight-5`: the loop pauses.
      Tests: ledger row present with `kind: audit`; the three dated reports exist.
      `[model: opus | deps: 1.1, 1.2, 2.1 | lane: repo_change | wave: 3]`

- [ ] 3.2 Handoff package: `.planning/reports/<date>-devex-handoff.md` carrying the five-audit
      history (scores and refs from `.planning/devex/loop.jsonl`), what each of the four changes
      closed, the seven findings still encoded as strict xfails with their original task text
      copied verbatim from this file at `origin/main` before this replan (former 1.3, 1.4, 1.5,
      1.6, 2.2, 2.3, 2.4), and the exact resume commands; the pause recorded under "Standing
      decisions recorded here" in `design/delivery/pulse-program-roadmap.md`.
      Tests: `task devex:check` reports 7 with no regressions; `mkdocs build -s`; `task check`
      green.
      `[model: sonnet | deps: 3.1 | lane: repo_change | wave: 4]`
