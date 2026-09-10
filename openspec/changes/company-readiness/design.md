## Context

See proposal.md. The original six reliability/contribution proposals are in PR #452, unmerged at last verification. Engineering-demo and connector-source-contracts are queued plans, not shipped functionality. CLAUDE.md still describes a placeholder package. The old PAP connector draft and newer kit contain different assumptions.

## Goals / Non-Goals

Make company-facing claims verifiable and navigation usable. Do not change repository visibility, announce a launch, certify absence of all sensitive data, or start a new numeric repository-rating cycle.

## Decisions

Decided 2026-09-10, gating the company readiness receipt:

1. A status matrix cites implementation paths, test/run receipts and limitations separately. Proposed work cannot be called runnable. Company visibility does not require completing the full demo; a demo announcement requires its separate acceptance.
2. Document authority is explicit: archived OpenSpec baseline for requirements, active deltas as proposals until accepted, code/API schemas for implemented surfaces, ADRs for architectural decisions, roadmap for sequencing. Contradictions are recorded for the owning change; old prose is labeled rather than silently treated as current.
3. Reuse connector-first-contribution in PR #452 for the first-contribution journey. This plan owns presentation of its evidence, not another scaffold fix or audit. Receipt links are an external gate for task 2.2; missing evidence leaves readiness incomplete.
4. Sharing review is read-only, attended GitHub-issue work after the runbook merges. Record intended internal audience, actual visibility, accessible refs/history coverage and scanner version/configuration. A shallow scan must not claim full-history coverage. Findings contain locations/categories and remediation references, never secret or PHI values. Missing admin access is explicit incomplete coverage, not a clean result. Access changes and history rewriting require a separately reviewed concrete action.
5. Owner table covers command rejection, identity hold, extraction failure, DLQ, reconciliation and deployment support; record actual accepted teams/roles and escalation routes. Do not invent individuals or send invitations. Unknown owners remain blockers for an operational-readiness claim, not for reading source code.

## Receipt data model and API surface

No new API. A versioned readiness receipt records commit, intended audience, status-evidence links, documentation contradictions, sharing-review scope/outcome, onboarding receipt, owner table, unresolved findings, and separate visibility/demo readiness outcomes. Each outcome is pass/fail/incomplete with reason; no numeric score. Synthetic fixture receipts validate required fields and that incomplete coverage cannot pass.

## Risks / Trade-offs

- Old documentation is useful history → label superseded assumptions and link authoritative replacements.
- Secret scanner misses semantic patient data → combine tool results with scoped manual review, document limits and avoid a blanket safety claim.
- Company visibility expands without review → this work produces evidence only, never changes access or sends announcements.
- Prior DevEx work is duplicated → consume existing proposal outcome and reproduce only a concrete remaining failure.

## Migration Plan

Review this queued plan, then land documentation/runbook tasks. Conduct attended sharing review. Collect first-contribution and ownership evidence, then publish the readiness receipt through PR. Any correction follows ordinary review; keep readiness incomplete until its material findings resolve. All implementation tasks are bounded to two hours; replan larger work instead of silently expanding it.
