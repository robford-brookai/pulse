# Tasks — devex-eight-2

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

- [x] 0.1 Twelve audit-2 findings as `xfail(strict=True)` tests in `tests/scaffold/cat10_devex.py`;
      change artifacts; `task replan CHANGE=devex-eight-2` green.
      Tests: `task devex:check` prints `METRIC devex_open_findings=12`; `task check` green.
      `[model: opus | deps: — | lane: repo_change | wave: 0]`

## 1. Wave 1 — the S fixes

- [x] 1.1 Link `docs/connectors/authoring.md` from `README.md` (Connectors section) and
      `CONTRIBUTING.md` (first paragraph).
      Tests: remove xfail from `test_authoring_guide_linked_from_readme_and_contributing`; cat8 green.
      `[model: haiku | deps: — | lane: repo_change | wave: 1]`

- [x] 1.2 `docs/index.md` becomes the front door: what PULSE is, the two-command quickstart, a
      Getting started section that sends connector authors to the guide, and a map of the nav.
      Tests: remove xfail from `test_docs_index_is_a_front_door`; `uv run mkdocs build -s` clean.
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]`

- [x] 1.3 `task lore:init` (runs `openlore init --force` idempotently, documented in the guide's
      ship section) and `requires: vars: [CHANGE]` on `verify`.
      Tests: remove xfail from `test_verify_requires_change_and_lore_init_exists`; cat4 green.
      `[model: haiku | deps: — | lane: repo_change | wave: 1 | serial: Taskfile.yml]`

- [x] 1.4 Prior-art collision warning in `scripts/connector_new.py`: if `packages/ocean/services/`
      has a directory whose name starts with the requested name, print its path and continue; add a
      "prior art" line to the guide's scaffold section.
      Tests: remove xfail from `test_connector_new_warns_about_prior_art`; cat9 golden unchanged.
      `[model: sonnet | deps: — | lane: repo_change | wave: 1]`

- [x] 1.5 Export `Jitter` from `pulse_core.connector`; settle the guide's import rule against the
      reference connectors (root for everything the root exports) and make the reference connectors
      follow it.
      Tests: remove xfail from `test_connector_kit_exports_jitter`; `test_connector_exports.py` extended.
      `[model: sonnet | deps: — | lane: repo_change | wave: 1]`

- [x] 1.6 Fix the stale claims (README archived-change count, package count, CONTRIBUTING's mypy
      hook) and gate the countable ones in `tests/scaffold/cat8_docs_consistency.py`.
      Tests: remove xfail from `test_readme_and_contributing_claims_are_current`.
      `[model: haiku | deps: 1.1 | lane: repo_change | wave: 1]`

- [x] 1.7 `.nvmrc` (`22`), `.editorconfig`, `.vscode/extensions.json`; amend the parity sentence
      in `README.md` and `CLAUDE.md` to name the job `task check` reproduces.
      Tests: remove xfail from `test_editor_and_runtime_pins_exist`; cat8 green.
      `[model: haiku | deps: — | lane: repo_change | wave: 1]`

- [x] 1.8 `.github/PULL_REQUEST_TEMPLATE.md` checklist names `task check`; `Taskfile.yml`
      descriptions lose change-id and ticket tokens (move them into comments).
      Tests: remove xfail from `test_pr_template_names_task_check` and
      `test_task_descriptions_carry_no_change_ids`.
      `[model: haiku | deps: 1.3 | lane: repo_change | wave: 1 | serial: Taskfile.yml and .github]`

## 2. Wave 2 — the M items

- [x] 2.1 Template ships `tests/test_config.py.tmpl` (the `from_env()` test the guide names first)
      and `tests/factories.py.tmpl`; the guide's rendered-tree diagram is generated from the
      template listing or gated by a test that diffs them.
      Tests: remove xfail from `test_template_ships_the_tests_the_guide_diagrams`; cat9 golden
      regenerated with REGEN=1 and reviewed.
      `[model: sonnet | deps: 1.4 | lane: repo_change | wave: 2]`

- [x] 2.2 `packages/pulse-core/CHANGELOG.md` starting at the current version with the audit-era
      changes; proposed `## Deprecations` section for the connector-kit spec written to
      `HANDOFF.md`; guide gains section 10, absorbing a kit change.
      Tests: remove xfail from `test_kit_has_changelog_and_deprecation_policy` once the doc-updater
      applies the spec section; until then the task's own test asserts the CHANGELOG exists.
      `[model: sonnet | deps: 1.5 | lane: repo_change | wave: 2]`

## 3. Wave 3 — the L item

- [x] 3.1 `connector:new` `DIRECTION=inbound`: a second template overlay whose service implements
      `RowSource` and `CursorStore` against the kit's inbound contract, with its own receipts and a
      passing test; outbound stays the default.
      Tests: remove xfail from `test_connector_new_supports_inbound_direction`; cat9 golden for the
      inbound render; `task check` green with both variants scaffolded in a tmp copy.
      `[model: opus | deps: 2.1 | lane: repo_change | wave: 3]`

## 4. Close-out

- [ ] 4.1 Run `/devex-audit` when `task devex:check` reports 0 open findings; append the ledger
      row; report whether the exit gate holds, else open `devex-eight-3`.
      Tests: ledger row present with `kind: audit`; the three dated reports exist.
      `[model: opus | deps: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 2.1, 2.2, 3.1 | lane: repo_change | wave: 4]`
