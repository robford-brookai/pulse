# tracked-state-resolution — delta

## Purpose

Makes the workflow's "where are we" computation true on any clone: `state_resolution` rules read
tracked repo state instead of gitignored machine-local files, and the collect step's SUMMARY.md —
the tier-economics receipt record — enters the repo instead of vanishing with the workstation.

## ADDED Requirements

### Requirement: SUMMARY.md is tracked
`handoffs/<change>/SUMMARY.md` SHALL be tracked in git. Per-task HANDOFF scratch under
`handoffs/` MAY remain ignored, but the collected summary — receipts, tier history, verification
results — SHALL be part of the committed record of the change.

#### Scenario: Collect output survives the workstation
- **GIVEN** `task collect CHANGE=<id>` has produced `handoffs/<id>/SUMMARY.md`
- **WHEN** the change's collect commit merges and the repo is cloned fresh elsewhere
- **THEN** SUMMARY.md is present in the clone with its receipt content intact

#### Scenario: No PHI in the tracked record
- **GIVEN** a HANDOFF contains operational detail from a prod-touching lane
- **WHEN** collect aggregates it into SUMMARY.md
- **THEN** the tracked summary contains receipts and spec deltas only — synthetic or structural
  content, never patient data

### Requirement: State resolution reads tracked surfaces only
Every rule in the `state_resolution` order SHALL be computable from tracked repo state (tasks.md
annotations and checkboxes, `handoffs/<id>/SUMMARY.md`, `openspec/changes/<id>/` contents, git
branches and history). No rule SHALL depend on the presence, absence, or staleness of gitignored
paths.

#### Scenario: Fresh clone resolves the same step
- **GIVEN** a change mid-execute with three tasks merged and checked
- **WHEN** an agent on a fresh clone and an agent on the original workstation each compute the
  step
- **THEN** both resolve to the same step

#### Scenario: Collect state is readable from the record
- **GIVEN** every task in the change is checked and `handoffs/<id>/SUMMARY.md` is absent from the
  tracked tree
- **WHEN** an agent computes the step
- **THEN** the resolution is collect, on any machine

### Requirement: Worktree cleanup is not a resolution input
The merge → archive transition SHALL be derivable from tracked state (all sub-tasks checked,
verify green, change folder present); local worktree existence MAY be reported as hygiene (H7)
but SHALL NOT gate step resolution.

#### Scenario: Spent worktrees on another machine do not park the change
- **GIVEN** all tasks merged and verified, but a workstation still holds spent worktrees
- **WHEN** an agent elsewhere computes the step
- **THEN** the change resolves to archive, and worktree deletion is flagged as H7 hygiene on the
  machine that owns them
