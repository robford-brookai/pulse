# Tasks — devex-eight-3

Annotation format, read by `task dispatch`:
`[model | deps | lane | wave]`, with `serial:` carrying its justification where set. `deps`
names task numbers in this file; `—` means no dependency. Model is stated explicitly on every task.

Every fix task removes the `xfail` marker of the finding it closes in
`tests/scaffold/cat10_devex.py` so `task devex:check` drops by exactly that finding, and ships its
tests in the same commit. `task check` stays green, offline and credential-free at every step.
Synthetic data only; no PHI. Specs are owned by the doc-updater: write proposed spec changes to
`HANDOFF.md`. Never edit `docs/process/devex-audit/*` in this change. Tasks touching
`Taskfile.yml`, `pyproject.toml` or `.github/` are serial-lane; the coordinator may run
non-Taskfile tasks alongside a serial one when they share no files.

---

## 0. Wave 0 — findings encoded (one PR, coordinator session)

- [ ] 0.1 Ten audit-3 findings as `xfail(strict=True)` tests in `tests/scaffold/cat10_devex.py`,
      including the structural `verify` guard test that replaces the one #380 satisfied without
      fixing the behaviour; change artifacts; `task replan CHANGE=devex-eight-3` green.
      Tests: `task devex:check` prints `METRIC devex_open_findings=10`; `task check` green.
      `[model: opus | deps: — | lane: repo_change | wave: 0]`

## 1. Wave 1 — the S fixes

- [ ] 1.1 Pin `-c commit.gpgsign=false` (and `gpg.format` neutral) in the `_git` helpers of
      `tests/scaffold/cat5_glue_logic.py` and `cat9_golden_workflow.py`; re-raise with `exc.stderr`
      in the message so a sandbox git failure is legible.
      Tests: remove xfail from `test_scaffold_git_helpers_are_hermetic_to_global_signing`; the
      gates pass with `GIT_CONFIG_GLOBAL` pointing at a config that sets `commit.gpgsign=true`.
      `[model: sonnet | deps: — | lane: repo_change | wave: 1]`

- [ ] 1.2 `verify` fails fast on an empty `CHANGE`: a `preconditions` entry that names CHANGE and
      exits before `check` runs; same for any other CHANGE-taking target that the empty default
      lets through.
      Tests: remove xfail from `test_verify_guards_against_empty_change`; the slow behavioural twin
      passes in under 15 s.
      `[model: haiku | deps: — | lane: repo_change | wave: 1 | serial: Taskfile.yml]`

- [ ] 1.3 `scripts/connector_new.py --apply-registrations` adds `uv run pyright -p packages/<name>`
      to `typecheck` instead of a `TYPED_PATHS` entry, matching the rendered pyright-strict posture;
      guide section 7 updated.
      Tests: remove xfail from `test_connector_new_registers_pyright_not_mypy`; cat9 registration
      tests updated.
      `[model: sonnet | deps: — | lane: repo_change | wave: 1]`

- [ ] 1.4 `task lint` is read-only (`ruff check --no-fix`, or `fix = false` in `pyproject.toml`
      with `task fmt` carrying the fixes); fix the name-conditional `I001` in the templates so a
      package sorting before `pulse_core` renders clean.
      Tests: remove xfail from `test_task_lint_is_read_only`; render `papchk` and `zapchk` and run
      `ruff check --no-fix` on both.
      `[model: sonnet | deps: — | lane: repo_change | wave: 1 | serial: pyproject.toml and Taskfile.yml]`

- [ ] 1.5 `docs/connectors/authoring.md` section 2 names every `__all__` export plus
      `pulse_core.client`, `pulse_core.generated` and `pulse_core.cursor`; corrects the root-only
      rule; a test diffs the list against `__all__`.
      Tests: remove xfail from `test_authoring_guide_documents_every_exported_name`.
      `[model: sonnet | deps: — | lane: repo_change | wave: 1]`

- [ ] 1.6 The rendered README's "Next steps" states what the scaffold already did (registration,
      tests) and points at the declare step instead.
      Tests: remove xfail from `test_rendered_readme_next_steps_do_not_redo_registration`; cat9
      goldens regenerated with REGEN=1 and reviewed.
      `[model: haiku | deps: — | lane: repo_change | wave: 1]`

- [ ] 1.7 `.github/CODEOWNERS` per-area line for `packages/pulse-core/src/pulse_core/connector/`;
      `.github/ISSUE_TEMPLATE/connector-kit-defect.yml`; the missing `billing-connector` row in
      `docs/contracts/producer-registry.md`.
      Tests: remove xfail from `test_codeowners_names_the_connector_kit_owner_and_defect_template_exists`.
      `[model: haiku | deps: — | lane: repo_change | wave: 1 | serial: .github]`

## 2. Wave 2 — the M items

- [ ] 2.1 The scaffold's `handle_page` declares: a complete `submit_with_retry` call per valid row
      with a fake command client in the template tests and a replay assertion (a re-delivered page
      declares nothing), in both direction overlays.
      Tests: remove xfail from `test_scaffold_ships_a_working_declare_example`; both goldens
      regenerated and the rendered suites green.
      `[model: opus | deps: 1.3 | lane: repo_change | wave: 2]`

- [ ] 2.2 `LedgerCursorStore` wraps `httpx.TransportError` in a kit error naming the base URL and
      the variable that supplied it; guide section 4 shows the message.
      Tests: remove xfail from `test_cursor_store_transport_errors_name_the_endpoint`; a
      refused-connection test in `packages/pulse-core/tests`.
      `[model: sonnet | deps: — | lane: repo_change | wave: 2]`

- [ ] 2.3 `task check` appends `{date, kind: timing, target, seconds, rc}` rows to
      `.planning/devex/loop.jsonl` via a small wrapper, and the TTHW slow test gains a cold-cache
      arm (`UV_CACHE_DIR` pointed at an empty dir) that records both numbers.
      Tests: remove xfail from `test_check_timings_are_recorded`; the ledger parser in
      `scripts/devex/check.py` accepts the new row shape.
      `[model: sonnet | deps: — | lane: repo_change | wave: 2 | serial: Taskfile.yml]`

## 3. Close-out

- [ ] 3.1 Run `/devex-audit` when `task devex:check` reports 0 open findings; append the ledger
      row; report whether the exit gate holds, else open `devex-eight-4`.
      Tests: ledger row present with `kind: audit`; the three dated reports exist.
      `[model: opus | deps: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.1, 2.2, 2.3 | lane: repo_change | wave: 3]`
