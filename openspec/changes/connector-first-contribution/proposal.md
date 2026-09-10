## Why

The prior DevEx work closed 42 findings and restored the generated connector path. The remaining high-value gap is landing the first contribution without undocumented hook or package-count repairs; another subjective audit loop would obscure those gains and repeat the cost.

## What Changes

- Preserve all shipped connector tooling and closed regression cases; fix only reproducible clone→check→scaffold→check→commit failures.
- Initialize the existing OpenLore prerequisite through the documented install path, remove brittle fixed package-count assumptions and keep successful checks from dirtying tracked timing files.
- Validate both inbound and outbound generated connectors through an actual first commit in isolated clones, with production hooks enabled and no live credentials.
- Use one independent contributor walkthrough as acceptance evidence, with reproducible blockers fixed once; do not resume devex-eight or change its frozen rubric/history.

## Capabilities

### New Capabilities
- `connector-first-contribution`: Behavioral first-commit acceptance with clean checks and an independent walkthrough.

### Modified Capabilities
None.

## Impact

Template-owned fixes go to rob-ade first per CLAUDE.md, then sync by the existing template mechanism; PULSE-owned package/docs gates stay here. Install guidance, timing output and a bounded onboarding runbook are affected. No new score, social/popularity requirement or comprehensive seven-finding cleanup. Rollback reverts the relevant template-sync or PULSE gate commit while retaining the new failing-path regression evidence.

## Planning status and boundaries

Proposed on 2026-09-10 at baseline `2ed0552`; implementation is not started. This is part of the
owner-requested reliability and contribution improvement plan. Review and merge of this planning
PR do not certify any runtime result. Execution keeps the two-change limit and WORKFLOW.md's
wave/serial lanes. The coordinator checks existing `reconciliation-sweeps` and
`m1-retire-patient-state` before releasing another change. No automatic dispatch, deployment,
notification, Linear sync, or cutover is part of filing this proposal. Live tasks use a GitHub
tracking issue and an attended session after their runbook PR merges; no live task is an Orca
work order. All fixtures and receipts are synthetic and contain no credentials or payload values.
