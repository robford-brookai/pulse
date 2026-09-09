## Why

The third DevEx audit (2026-09-05 at `11622da`, `.planning/reports/2026-09-05-devex-scorecard.md`,
QA-accepted) scored pulse at overall DX 6.5 and connector-author composite 6.7, up from 5.9 and
5.8 after `devex-eight-2` closed all twelve second-audit findings. The exit gate is overall >= 8.0
and connector >= 8.0. The profile is lopsided: `task connector:new` is best-in-class, while the
error path, the ecosystem story and the getting-started gate sit two tiers below it. The QA also
found that PR #380 did not close the `task verify` fast-fail finding: the Taskfile's empty
`CHANGE` default satisfies `requires:`, so the gate still runs to completion before failing.

## What Changes

- **Wave 0 (this PR).** Ten audit-3 findings become `xfail(strict=True)` tests in
  `tests/scaffold/cat10_devex.py`, including a structural test for the `verify` guard that the
  earlier test missed, so `task devex:check` reports `devex_open_findings=10`.
- **Wave 1, the S fixes.** Pin `commit.gpgsign=false` in the scaffold git helpers so a global
  signing config cannot fail `task check`; guard `verify` against an empty `CHANGE`; register the
  scaffold's pyright posture instead of a `TYPED_PATHS` entry; make `task lint` read-only and fix
  the template files it was silently repairing (the name-conditional `I001`); document every kit
  export in the guide with a test diffing it against `__all__`; fix the rendered README's next
  steps; per-area CODEOWNERS and a connector-kit-defect issue template.
- **Wave 2, the M items.** A complete working declare in the scaffold's `handle_page` with a
  replay assertion; `LedgerCursorStore` transport failures wrapped with the endpoint and the
  variable that supplied it; per-target `task check` timings appended to the ledger and a
  cold-cache arm for the TTHW test.
- **Loop rule unchanged.** At 0 open findings, run `/devex-audit` (audit 4).

Out of scope: the frozen protocol files (own PR: uncontended timing rule and the meaning of a zero
count, both from this QA); the Community dimension's single-author constraint; the Notion link for
"who to ask", which the owner supplies.

## Capabilities

### Modified Capabilities
- `connector-kit`: the scaffold's rendered service declares through the kit and registers the
  package's own typecheck posture; cursor-store transport errors name the endpoint and the
  configuration that selected it.

## Impact

- **Code**: `tests/scaffold/cat10_devex.py`, `cat5_glue_logic.py`, `cat9_golden_workflow.py`,
  `Taskfile.yml` (`verify` precondition, `lint`, `check` timing hook), `scripts/connector_new.py`,
  `templates/connector/**`, `pulse_core/connector/rows.py`, `pyproject.toml` (`ruff.fix`).
- **Docs**: `docs/connectors/authoring.md`, template README, `.github/CODEOWNERS`,
  `.github/ISSUE_TEMPLATE/connector-kit-defect.yml`.
- **Rollback**: every fix is its own PR; reverting one restores its xfail marker.
