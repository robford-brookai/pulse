# Tasks — devex-eight

Annotation format, read by `task dispatch`:
`[model | deps | lane | wave]`, with `serial:` carrying its justification where set. `deps`
names task numbers in this file; `—` means no dependency. Linear ids get bracketed in after
`task linear:sync`. Model is stated explicitly on every task.

Every task ships its tests in the same commit (tests first per `AGENTS.md`), and every fix task
removes the `xfail` marker of the finding it closes in `tests/scaffold/cat10_devex.py` so
`task devex:check` drops by exactly that finding. `task check` stays green, offline and
credential-free at every step. Synthetic data only; no PHI. Specs are owned by the doc-updater:
write proposed spec changes to `HANDOFF.md`, never edit `openspec/specs/`. Never edit
`docs/process/devex-audit/*` in this change.

**Entry conditions.** Second change in flight alongside `billing-connector`: tasks touching
`Taskfile.yml`, `pyproject.toml` workspace roots or `.github/` are serial-lane and the coordinator
releases them only when the other change has none in flight. Wave 0 is one PR from the
coordinator session. Waves 1 and 2 run as Orca worktrees, one per task. Template-owned paths
(`Taskfile.yml`, `bootstrap.sh`, `scripts/`, `tests/scaffold/`, `.github`) are fixed here first;
task 3.1 batches the upstream PR.

---

## 0. Wave 0 — measure before moving (one PR, coordinator session)

- [ ] 0.1 Apply the 12 QA corrections from `.planning/reports/2026-09-02-devex-audit-qa.md` to
      the evidence and scorecard reports; add a corrections note to each; commit the three
      2026-09-02 reports.
      Tests: `grep -c "—"` on the evidence report is at most 1 (the CONTRIBUTING quote);
      the scorecard contains no `Champion`.
      `[model: opus | deps: — | lane: repo_change | wave: 0]`

- [ ] 0.2 Inner tier: `tests/scaffold/cat10_devex.py` with one `xfail(strict=True)` test per
      open finding plus the measurement self-tests; `scripts/devex/check.py` printing
      `METRIC devex_open_findings=<n>`; `pyproject.toml` `python_files` widened to
      `cat[0-9]*_*.py`; Taskfile targets `devex:check` and `devex:audit`; ledger
      `.planning/devex/loop.jsonl` with the baseline row.
      Tests: `task devex:check` exits 0 and prints the METRIC line; `task check` green;
      `test_pytest_collects_two_digit_gate_files` passes.
      `[model: opus | deps: — | lane: repo_change | wave: 0 | serial: Taskfile.yml and
      pyproject.toml — coordinator releases alone across both in-flight changes]`

- [ ] 0.3 Outer tier preserved: `docs/process/devex-audit/{README,rubric,task-a,task-b,task-c}.md`
      frozen by `CHECKSUMS`; `.claude/commands/devex-audit.md`; mkdocs nav entries.
      Tests: `test_audit_protocol_is_frozen` and `test_command_routes_to_runbook` pass;
      `uv run mkdocs build -s` clean.
      `[model: opus | deps: 0.2 | lane: repo_change | wave: 0]`

## 1. Wave 1 — connector composite movers

- [ ] 1.1 Kit exports: import the declare layer in `pulse_core/connector/__init__.py` so every
      `__all__` name resolves; refresh the module docstring (the declare pipeline has landed).
      Tests: remove xfail from `test_connector_kit_all_names_resolve`; add
      `packages/pulse-core/tests/test_connector_exports.py` asserting `from pulse_core.connector
      import *` binds every `__all__` name.
      `[model: sonnet | deps: — | lane: repo_change | wave: 1]`

- [ ] 1.2 Connector authoring guide `docs/connectors/authoring.md`, answering in order: what a
      connector is here, what to import, how to scaffold, how to configure, how to test offline,
      how to register the package (all eight sites, until 1.4 automates them), how to ship
      through the workflow, who to ask. Written in the shipped kit's vocabulary
      (`RowSource`, `CursorStore`, `consume`, `submit_with_retry`), linking the connector-kit
      spec and `billing-connector` as the reference. Add to mkdocs nav.
      Tests: remove xfail from `test_connector_authoring_guide_exists_and_is_in_nav`; cat8-style
      test that every `task` target the guide names exists in `Taskfile.yml`.
      `[model: opus | deps: 1.1 | lane: repo_change | wave: 1]`

- [ ] 1.3 Scaffold: `templates/connector/` (pyproject, `src/<name>/{__init__,config,service,
      receipts}.py`, socket-blocked `tests/conftest.py`, one passing test) and
      `scripts/connector_new.py` rendering it for `NAME` and printing the registration diff it
      will apply.
      Tests: golden render into a tmp dir compared to `tests/scaffold/data/golden-connector/`;
      the rendered package's own test passes under pytest.
      `[model: opus | deps: 1.1 | lane: repo_change | wave: 1]`

- [ ] 1.4 `task connector:new NAME=<x>` target that runs 1.3's script and performs the eight
      registrations (`pyproject.toml` members and sources, `Taskfile.yml` `LINT_PATHS`,
      `TYPED_PATHS`, `TESTED_PATHS`, `COV_PATHS`, image and deploy stanzas as commented stubs).
      Tests: remove xfail from `test_connector_scaffold_command_exists`; a test that after a
      dry-run render every registration site names the new package; `task check` green with a
      scaffolded package present in a tmp copy.
      `[model: sonnet | deps: 1.3 | lane: repo_change | wave: 1 | serial: workspace roots and
      Taskfile.yml — coordinator releases alone across both in-flight changes]`

- [ ] 1.5 `task install` runs `uv run pre-commit install` after `uv sync`.
      Tests: remove xfail from `test_install_installs_pre_commit_hooks`; cat7 hook check passes
      on a fresh clone after `task install` (slow).
      `[model: haiku | deps: — | lane: repo_change | wave: 1 | serial: Taskfile.yml]`

- [ ] 1.6 `requires: vars: [CHANGE]` on `dispatch`, `checkoff`, `collect`, `replan`,
      `spec:validate`, `spec:archive`, `spec:status`, `sync-docs`, `linear:sync`.
      Tests: remove xfail from `test_change_taking_targets_require_change`; cat4 command
      contract still green.
      `[model: haiku | deps: 1.5 | lane: repo_change | wave: 1 | serial: Taskfile.yml]`

- [ ] 1.7 `bootstrap.sh` guard: if `.ade-template-version` exists in the current directory,
      print "This repo is already generated; run `task install`." and exit 2, before `${1:?}`.
      Five lines at the top so template sync conflicts stay small.
      Tests: remove xfail from `test_bootstrap_refuses_generated_repo_and_points_at_task_install`;
      the template path (no stamp) still reaches the usage message.
      `[model: haiku | deps: — | lane: repo_change | wave: 1]`

- [ ] 1.8 Replace the four all-zeros action SHAs in `ci-health.yml` and `auto-heal.yml` with
      the real commit SHAs for the pinned versions; keep the version comments.
      Tests: remove xfail from `test_action_pins_are_real_shas`; `cat4_ci_contract.py` still green.
      `[model: sonnet | deps: — | lane: repo_change | wave: 1 | serial: .github]`

- [ ] 1.9 README `## Prerequisites` block: `uv`, `go-task`, Node 22, Docker, with install lines
      mirroring `tests/scaffold/cat2_toolchain.sh`.
      Tests: remove xfail from `test_readme_states_prerequisites`; cat8 docs consistency green.
      `[model: haiku | deps: — | lane: repo_change | wave: 1]`

## 2. Wave 2 — the M items

- [ ] 2.1 `billing_connector.config.Config.from_env()` collects every missing or invalid
      variable and raises one `ConfigError` naming each variable, its expected type or unit, and
      where the value comes from; the invalid-value path uses the same class.
      Tests: remove xfail from both `test_billing_config_*` tests; package tests for
      one-missing, all-missing, invalid stale_after.
      `[model: sonnet | deps: — | lane: repo_change | wave: 2]`

- [ ] 2.2 One canonical connector spec in the kit's vocabulary: keep
      `openspec/specs/connectors/pulse-standard-connector-spec.md` as canonical, reduce
      `design/platform/pulse-standard-connector-spec.md` to a pointer, move the PAP CX-1..CX-8
      breakdown to `design/migration/`. Spec content changes go to `HANDOFF.md` for the
      doc-updater.
      Tests: remove xfail from `test_connector_spec_has_one_canonical_copy`.
      `[model: opus | deps: 1.2 | lane: repo_change | wave: 2]`

- [ ] 2.3 Docs site: `site_name: PULSE`, repo URLs to pulse, mkdocstrings `paths` covering
      `packages/pulse-core/src`, `docs/modules.md` documenting `pulse_core.connector`, every
      docs page in the nav.
      Tests: remove xfail from `test_docs_site_is_pulse_not_the_template`,
      `test_mkdocstrings_documents_the_connector_kit`, `test_every_docs_page_is_in_nav`;
      `uv run mkdocs build -s` clean.
      `[model: sonnet | deps: 1.2 | lane: repo_change | wave: 2]`

- [ ] 2.4 `task test:all` runs `cat2_toolchain.sh`, `cat4_command_contract.sh` and
      `cat7_gates_hooks.sh` after pytest; fix the four cat7 failures on a fresh clone.
      Tests: remove xfail from `test_test_all_runs_the_shell_gates`; `task test:all` green.
      `[model: sonnet | deps: 1.5 | lane: repo_change | wave: 2 | serial: Taskfile.yml]`

- [ ] 2.5 `.github/CODEOWNERS`, `.github/ISSUE_TEMPLATE/attended-run.md`,
      `.github/PULL_REQUEST_TEMPLATE.md`; `CONTRIBUTING.md` names the owner and the channel to
      ask and states the hook behaviour truthfully.
      Tests: remove xfail from `test_repo_names_an_owner_and_a_place_to_ask` and
      `test_issue_and_pr_templates_exist`.
      `[model: haiku | deps: — | lane: repo_change | wave: 2 | serial: .github]`

## 3. Close-out

- [ ] 3.1 Batched upstream PR to repo-ade, "DX fixes surfaced by pulse audit": 1.5, 1.6, 1.7,
      2.4 and the pin assertion; record the PR URL here.
      Tests: `task template:diff` shows the fixes as no-ops once merged upstream.
      `[model: sonnet | deps: 1.5, 1.6, 1.7, 2.4 | lane: repo_change | wave: 3]`

- [ ] 3.2 Run `/devex-audit` when `task devex:check` reports 0 open findings; append the ledger
      row; open `devex-eight-2` from the new top-10 if the exit gate does not hold.
      Tests: ledger row present with `kind: audit`; the three dated reports exist.
      `[model: opus | deps: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.1, 2.2, 2.3, 2.4, 2.5 | lane: repo_change | wave: 3]`
