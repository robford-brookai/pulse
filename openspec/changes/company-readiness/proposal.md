## Why

Company readers need an accurate account of what Pulse ships, how to try it, and who owns operational failures. Current placeholder guidance and historical design assumptions can misrepresent maturity; intended repository exposure and onboarding outcomes have not been verified for this release.

## What Changes

- Refresh README and project-specific guidance with shipped/runnable/proposed/blocked status and one supported synthetic demo path.
- Publish a document authority map and mark historical assumptions as superseded through the doc-updater where specs are involved.
- Record repository sharing/history-review coverage, unresolved findings and intended audience without changing access permissions.
- Reuse the connector-first-contribution fresh-checkout journey and receipts from PR #452 rather than creating another numeric DX audit.
- Record operational owners and bug/contribution routes, with unassigned ownership visible as a readiness gap.

## Capabilities

### New Capabilities

None. This change is documentation, verification receipts and release preparation; it introduces no runtime capability and declares skip_specs.

### Modified Capabilities

None. Contradictions requiring behavioral changes route to their owning OpenSpec changes; this plan does not rewrite baseline contracts.

## Impact

README, project context in CLAUDE.md, documentation index, release/readiness runbook and tracked receipts. Template-owned changes must land upstream before template:sync. No source data access, repository audience change or company announcement is performed by this proposal.

Rollback: revert inaccurate documentation through PR and withdraw an invalid readiness receipt. A security finding is handled through the existing incident/remediation process; do not print secret values or rewrite git history as part of a documentation fix.
