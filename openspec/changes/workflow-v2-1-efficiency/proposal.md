# workflow-v2-1-efficiency

## Why

The first full run of WORKFLOW.md v2 (ocean-eventbridge-migration: 56 tasks, 58 PRs, ~100
commits) surfaced four recurring frictions the workflow does not model. 25 of ~100 commits on
main were hand-typed bookkeeping (`chore: check off X.Y`, `chore: record DNA-nnn ids`), tasks.md
was amended mid-execute at least eight times through a graph edge that does not exist — several
of those direct pushes carried scope decisions, breaching `main_access`'s own conditions — and
three `state_resolution` rules read gitignored, machine-local state, which contradicts "the repo
is the record" and hides the tier-economics receipts the escalation ladder justifies itself with.

## What Changes

- **Automated check-off**: a `task checkoff` glue target flips the tasks.md checkbox for a merged
  PR, derived from the task id in the PR title/commit subject, and commits under the existing
  `main_access` mechanical-update exemption. Dispatch already reads checked boxes to release
  waves (`scripts/dispatch_tasks.py`), so this removes the human latency between a merge and the
  next wave without changing the wave gate.
- **Replan step**: WORKFLOW.md's step graph gains a `replan` step reachable from `execute` —
  amend tasks.md via a small PR, G_MECE re-checked on the delta only, `linear:sync`, back to
  `dispatch`. `state_resolution` gains a matching rule. This legalizes the most common real
  mid-change event and closes the `main_access` breach the current graph forces.
- **Linear id write-back**: `linear:sync` gains one sanctioned reverse edge — after creating a
  sub-issue it may write the `[DNA-nnn]` token into the task's line in tasks.md, and nothing
  else. Files stay canonical for all content; the id is Linear-assigned and was always going to
  be copied by hand otherwise.
- **Tracked state resolution**: `handoffs/<change>/SUMMARY.md` becomes tracked (un-gitignored),
  and the three `state_resolution` rules that read machine-local state (`work_orders/` staleness,
  `SUMMARY.md` absence, worktree existence) are rewritten to derive from tracked surfaces —
  tasks.md checkboxes, the tracked SUMMARY.md, and git branches — so any agent on any clone
  resolves the same step.
- WORKFLOW.md's YAML block, prose, and diagram are updated together (version 2.1.0), and
  `task workflow:lint` continues to pass — the new step and rules are added to all three
  renderings per the correspondence check.

## Capabilities

### New Capabilities

- `task-checkoff`: automated flipping of tasks.md checkboxes from merged PRs, under the
  `main_access` mechanical-update conditions.
- `workflow-replan`: the `replan` step — mid-change tasks.md amendment as a first-class graph
  edge with delta-scoped G_MECE and re-sync.
- `linear-id-writeback`: the single sanctioned reverse edge in `linear:sync`, writing issue-id
  tokens into tasks.md and nothing else.
- `tracked-state-resolution`: `state_resolution` computable from tracked repo state on any clone,
  with `handoffs/<change>/SUMMARY.md` tracked as the receipt record.

### Modified Capabilities

<!-- none — openspec/specs/ baseline is empty; every capability here is new -->

## Impact

- `WORKFLOW.md` — YAML block (steps, state_resolution, sync_linear behavior), prose §3, diagram
  §4, change log. This is a meta-change per `edit_protocol`.
- `scripts/linear_sync.py` — id write-back on create (APPLY runs only).
- `scripts/workflow.py` / `task workflow:lint` — must accept the new step and rules.
- `Taskfile.yml` — new `checkoff` target; `scripts/` gains its glue script.
- `.gitignore` — `handoffs/` narrowed so `SUMMARY.md` is tracked while per-task scratch stays
  ignored.
- `docs/process/dispatch-template.md` — §4 "checking one off is the act that opens the next
  wave" gains the automated path; HANDOFF/SUMMARY tracking note.
- Template-relevant: the checkoff target, the write-back, and the gitignore narrowing belong
  upstream in repo-ade after landing here; this change records that in tasks rather than
  side-editing the template.

Rollback: every piece is additive glue or a doc edit. Reverting the commits restores v2.0.3
behavior — no data migration, no external state beyond Linear issue ids already written, which
are inert if the write-back is removed.
