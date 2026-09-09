# Handoff Summary: reconciliation-sweeps

Collected 2 handoff(s).

## reconciliation-sweeps-task-006

## Spec Updates

None. Implementation matches `specs/reconciliation-sweeps/spec.md` and design.md decision 8
as written — no drift found.

### Added Requirements

None.

### Modified Requirements

None.

### Removed Requirements

None.

## Design Drift

None.

## New Scenarios

None.

## reconciliation-sweeps-task-008

## Spec Updates

None — this task is itself the doc-updater pass for the change: `docs/contracts/publishes.md`,
`docs/contracts/consumes.md`, `design/delivery/pulse-program-roadmap.md`, and
`docs/runbooks/reconciliation-sweeps.md` are edited directly (none of these are `openspec/specs/`
files), per the task's own instruction. No `openspec/` file was touched.

### Added Requirements

None.

### Modified Requirements

None.

### Removed Requirements

None.

## Design Drift

None found. Prior tasks (1.2, 2.1, 3.1, 3.2) each noted a "proposed publishes.md row written to
HANDOFF.md" in their commit messages, but no `handoffs/reconciliation-sweeps/` directory exists
yet (nothing has been collected for this change), and each of those worktrees' own `HANDOFF.md` is
untracked and gone with the worktree. This task re-derived the correct `publishes.md`/`consumes.md`
content directly from the shipped code (`subject_current_state.sql`, `receipt.py`,
`sweep_registry.py`, `consumer_registry.py`, `cli.py`) and design.md decisions 3, 5, 6, 7 rather
than from those lost proposals — a future `task collect` for this change will find nothing to fold
in from tasks 1.2/2.1/3.1/3.2 on the docs front.

## New Scenarios

None.

## Doc-Updater Instructions

1. For each spec-relevant update inlined above, edit the corresponding file in:
   `openspec/changes/reconciliation-sweeps/specs/`
2. Run `openspec validate reconciliation-sweeps` to check format.
3. Run `openlore drift` to check for new drift.
4. Ignore implementation details — only apply plan-relevant changes.
5. A `## Design Drift` section above means flag for human review.
