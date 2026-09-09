## Why

The fourth DevEx audit (2026-09-05b at `5177d05`, `.planning/reports/2026-09-05b-devex-scorecard.md`,
QA-accepted with corrections) scored pulse at overall DX 6.0 and connector-author composite 5.6,
down from 6.5 and 6.7 at `11622da`. The exit gate is overall >= 8.0 and connector >= 8.0.

The fall is not breadth of neglect. It is one PR: `devex-eight-3` task 2.1 (PR #403) shipped two
defects onto the connector golden path. The rendered test suites import `from factories`, which
raises `ModuleNotFoundError` under the `--import-mode=importlib` that `task test` uses, in both
directions and independently of the connector's name; and the outbound `def run(` signature joins
to 118 characters against `line-length = 120`, which `ruff format` then splits back out, so
`task lint` fails on a file the author never touched. `task connector:new` renders a package that
fails the repo's own gate.

The QA's coordinator note C-X1 names why nothing caught it: `devex_open_findings` read 0
throughout, because no finding test rendered a connector and ran the real gate. The gate's
connector coverage was `test_connector_scaffold_command_exists`, which asserts that a task target
and a template directory exist. Both held while the command they name was broken. A metric that
reports zero while the golden path is red is worse than no metric, because it is trusted.

## What Changes

- **Wave 0 (this PR).** Ten audit-4 findings become `xfail(strict=True)` tests in
  `tests/scaffold/cat10_devex.py`, each asserting the behaviour its fix produces against a
  rendered tree or the repo's own output, so `task devex:check` reports
  `devex_open_findings=10`. A `slow` control renders both directions, registers them and runs the
  gate's own lint, format and test constituents.
- **Wave 1, the S fixes.** Revert #403's two defects — the rendered suites must import under
  `importlib` alongside `packages/billing-connector/tests`, and the rendered tree must be a
  `ruff format` fixed point. The other four S fixes (`task lore:init` inside `task install`, the
  README owner block, the kit's error types in the guide's paste block, the `.env.example`
  variables) left this change on 2026-09-08 (design.md decision 7); their findings stay encoded.
- **Wave 2.** Replace `test_connector_scaffold_command_exists` with the render-and-gate control.
  The other three M items (lint and npm-global messages, the timing ledger move, the TTHW
  redefinition) left with decision 7; their findings stay encoded.
- **Loop paused (decision 7, 2026-09-08).** Audit 5 runs once the three fixes merge, with seven
  findings still open by design; its scores are recorded and the loop pauses with a handoff
  package. No `devex-eight-5`.

Out of scope: the frozen protocol files (`docs/process/devex-audit/*`, CHECKSUMS); the Community
dimension's single-author constraint, which no PR can close; the items below the audit's cut.

## Capabilities

### Modified Capabilities
- `connector-kit`: what `task connector:new` renders passes the repo's combined test run and its
  formatter unchanged, and the DevEx gate proves that by rendering and gating rather than by
  asserting the command exists.

## Impact

- **Code**: `tests/scaffold/cat10_devex.py`, `templates/connector/**`.
- **Docs**: `docs/connectors/authoring.md` (rendered-tree fence), the handoff report under
  `.planning/reports/`, `design/delivery/pulse-program-roadmap.md` (the pause).
- **Rollback**: every fix is its own PR; reverting one restores its xfail marker.
