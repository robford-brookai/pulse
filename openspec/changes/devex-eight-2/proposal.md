## Why

The second DevEx audit (2026-09-04 at `b26dee0`, `.planning/reports/2026-09-04-devex-scorecard.md`,
QA-accepted with corrections) scored pulse at overall DX 5.9 and connector-author composite 5.8,
up from 3.8 and 2.4 after `devex-eight` closed all 17 first-audit findings. The exit gate set by Rob
is overall >= 8.0 and connector >= 8.0. Per the loop rule in `docs/process/devex-audit/README.md`,
the new scorecard's ranked fixes become a new change rather than an amendment.

## What Changes

- **Wave 0 (this PR).** The twelve audit-2 findings become `xfail(strict=True)` tests in
  `tests/scaffold/cat10_devex.py`, so `task devex:check` reports `devex_open_findings=12` and each
  fix flips exactly one. No behaviour changes.
- **Wave 1, the S fixes.** Link the authoring guide from README and CONTRIBUTING; make
  `docs/index.md` a real front door; `task lore:init` plus `requires: vars: [CHANGE]` on `verify`;
  a prior-art collision warning in `connector:new`; export `Jitter`; fix the stale README and
  CONTRIBUTING claims and gate them in cat8; `.nvmrc`, `.editorconfig`, `.vscode/extensions.json`;
  PR template names `task check`; task descriptions lose ticket tokens.
- **Wave 2, the M items.** Template ships `tests/test_config.py` and `tests/factories.py` and the
  guide's tree diagram is generated or gated; `packages/pulse-core/CHANGELOG.md` plus a
  Deprecations section in the connector-kit spec (via HANDOFF.md for the doc-updater) and a guide
  section on absorbing kit changes.
- **Wave 3, the L item.** `connector:new --direction inbound`, a second worked template variant.
- **Loop rule unchanged.** A PR merges only if `task check` is green and `devex_open_findings`
  does not rise. At 0, run `/devex-audit` (audit 3); its result decides whether the exit gate
  holds or a `devex-eight-3` follows.

Out of scope: the Community and Ecosystem dimension's binding constraint (every commit is by one
author) cannot be changed by this repo; the frozen protocol files (own PRs only); the Slack channel
name, which only the owner can supply.

## Capabilities

### Modified Capabilities
- `connector-kit`: the kit publishes a changelog and a deprecation policy; the package root exports
  every primitive the authoring guide names; the scaffold supports an inbound direction and warns
  when a name collides with prior art under `packages/ocean/services/`.

## Impact

- **Code**: `tests/scaffold/cat10_devex.py`, `scripts/connector_new.py`, `templates/connector/`,
  `pulse_core/connector/__init__.py`, `Taskfile.yml` (`lore:init`, `verify`, descriptions),
  `tests/scaffold/cat8_docs_consistency.py`.
- **Docs**: `README.md`, `CONTRIBUTING.md`, `docs/index.md`, `docs/connectors/authoring.md`,
  `packages/pulse-core/CHANGELOG.md`, `.github/PULL_REQUEST_TEMPLATE.md`.
- **Environment files**: `.nvmrc`, `.editorconfig`, `.vscode/extensions.json`.
- **Rollback**: every fix is its own PR; reverting one restores its xfail marker and the count
  rises by one, which the ledger records.
