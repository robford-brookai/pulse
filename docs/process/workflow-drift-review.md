# Workflow Drift Review — Thread Documents vs WORKFLOW.md v2

**Status:** Complete, 2026-08-01 | **Author:** Ford (recorded by Claude)
**Scope:** Every document produced or referenced in this planning thread, audited against WORKFLOW.md v2 and the repo-ade dispatch template. Corrected documents are revised in place with change-log entries. Read-only project documents get dispositions here for Ford to fold.

## Disposition table

| Document | Drift found | Disposition |
|---|---|---|
| `WORKFLOW.md` v2 | — (the standard) | Add to project, and to repo-ade as the live workflow |
| `repo-ade-dispatch-template.md` | None — authored against v2 | Add to project, and to repo-ade as `templates/` + `docs/dispatch.md` |
| `pulse-ledger-backfill-plan.md` | §7 framed execution as "sequential Open Engine orders, same shape as the OCEAN batch." DNA-695 named as a prerequisite | **Corrected in v0.4:** §7 reframed to lane-mapped dispatch with a per-order lane table (BF-3 is the cleanest Orca candidate, BF-2/BF-4/BF-5 loads are operational + G_APPROVAL, BF-1 git surgery is destructive_ops). DNA-695 superseded by the repo-ade bootstrap. Doctrine, stages, evidence classes, register untouched |
| `bf0-mongo-archaeology-agent-batch.md` | Heavy — entire wrapper was Open Engine: rob-claude titles, `agent-instructions` label, Agent Todo/Review statuses, HUMAN HOLD tokens, DNA-695 dependency, Open Engine operator setup | **Rewritten as v2:** BF-0a is OpenSpec change `bf0a-archaeology-access` (repo_change lane, routed opus per the pattern-inheritance rubric row), BF-0b is an operational-discovery session outside Orca with the standing no-prod-creds-in-worktrees rule, statuses mapped to Linear sub-issues, G_HARDENING added to operator setup. Task bodies, PHI rules, and verification commands unchanged |
| `ocean-absorption-agent-batch.md` (project file, read-only) | Full Open Engine format throughout: titles, labels, statuses, AGENT HUMAN HOLD / AGENT FAILED / AGENT BLOCKED tokens, one-claim-per-run sequencing, skill "Allowed local sources" setup | **Content survives, wrapper retires.** OCN-0 through OCN-7 are git surgery and repo administration — destructive_ops lane by rule, so they were never Orca work and the change is vocabulary, not substance: approval comments move to Linear sub-issues, HOLD/FAILED tokens become Blocked-with-comment, the two hard gates (OCN-2 force-push, OCN-7 archive) become G_APPROVAL instances, OCN-5 (conformance) alone converts to a repo_change OpenSpec change. Note: the batch predates the TIDE absorption decision — when TIDE absorbs (backfill plan BF-1), it reruns this same playbook, so update once and reuse twice. Ford revises at next pass; not blocking |
| `rpc-object-model-assessment.md` (project file, read-only) | Light — §8 says register writes are "queued behind connector approval configuration," §10 seeds "the S0.2 catalog work order," and the agent-queue title convention appears in memory-era references | **Doctrine unaffected.** Fold at next revision: S0.2 and S1.1 become OpenSpec changes in the repo-ade-born PULSE repo (their five-field bodies map onto proposal/tasks nearly verbatim), the D-register lands as Linear comments on the relevant parent issues per WORKFLOW receipts, and §8.1's confirmation receipts become sub-issue comment links. The catalog-as-generative-contract mechanism (§7) is reinforced, not changed — WORKFLOW v2 uses the identical source-of-truth-plus-projections pattern |
| v1 `WORKFLOW.md` (uploaded) | Superseded wholesale | Replaced by v2; keep nothing separate — v2's §5 records the delta |

## Cross-cutting corrections applied

1. **Open Engine vocabulary retired** everywhere Claude-authored: no rob-claude titles, no `agent-instructions` label, no Agent-prefixed statuses or HOLD tokens. Replacement vocabulary: Linear sub-issue statuses, Blocked-with-comment, G_APPROVAL comments.
2. **DNA-695 superseded** — the repo-ade bootstrap is the birth ritual for PULSE. Rob-repo remains birth-only history; running it on a repo-ade child would be the never-rerun violation. The open-agent-engine and rob-repo skills need supersession notes (operator task, not a document edit).
3. **Lane assignment is now stated, never implied** — every order in every batch names its lane, because dispatch shunts by rule and the docs must agree with the shunt.
4. **Routing declared where execution is specified** — BF-0a carries `model/max/attempts` per the template; the OCEAN/BF runbook-lane items don't route because runbooks aren't dispatched.

## Not drift, deliberately

The backfill plan's doctrine (derived-then-declared, evidence classes, bitemporal I10, two-stage seed/history), the object model's entire catalog and invariants, and all verification command bodies are workflow-independent and were not touched. The workflow governs *how work moves*, not *what is true* — keeping that boundary clean is what made this review a wrapper edit instead of a rewrite.

## Add to project

Four files: `WORKFLOW.md` (v2), `repo-ade-dispatch-template.md`, `pulse-ledger-backfill-plan.md` (v0.4), `bf0-mongo-archaeology-agent-batch.md` (v2), plus this memo. The two existing project files (`ocean-absorption-agent-batch.md`, `rpc-object-model-assessment.md`) stay as-is until Ford's revision pass per the dispositions above.
