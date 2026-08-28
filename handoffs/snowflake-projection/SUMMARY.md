# Handoff Summary: snowflake-projection

Collected 4 handoff(s) — none from live worktrees: the three worker worktrees were deleted and
the orchestrator's scratchpad backups were purged with the session tmp dir before collect ran,
so task-001/002/003 are **reconstructed from their merged PR bodies** (#285, #286, #287 — the
billing-state reconstruction precedent), and task-004-operator is the operator session's own
receipt for 2.1 (executed under the PR-#288 gate, closed by #289). The HANDOFF-durability gap
strikes again; the durable fix (tracked HANDOFFs or collect-at-merge) still has no owner.

## Files

- [task-001.md](handoffs/snowflake-projection/task-001.md) — 1.1 STG_EVENTS SQL + tests (PR #285)
- [task-002.md](handoffs/snowflake-projection/task-002.md) — 1.2 supersession note (PR #286)
- [task-003.md](handoffs/snowflake-projection/task-003.md) — 1.3 contract rows (PR #287)
- [task-004-operator.md](handoffs/snowflake-projection/task-004-operator.md) — 2.1 revival receipt (#288/#289)

## Doc-Updater Instructions

1. Read each handoff file above.
2. For each spec-relevant update, edit the corresponding file in:
   `openspec/changes/snowflake-projection/specs/`
3. Run `openspec validate snowflake-projection` to check format.
4. Run `openlore drift` to check for new drift.
5. Ignore implementation details — only apply plan-relevant changes.
6. If a handoff contains `## Design Drift`, flag for human review.
