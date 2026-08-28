# task-checkoff — delta

## Purpose

Automates the load-bearing bookkeeping between a merged task PR and the next wave release:
flipping the task's checkbox in the change's tasks.md, so wave gating no longer waits on a
hand-typed commit.

## ADDED Requirements

### Requirement: Check-off derives from the merged PR
The system SHALL provide a `task checkoff CHANGE=<id>` target that flips unchecked tasks.md
checkboxes to checked for every task whose PR has merged to main, identifying tasks by the task
id carried in the merge's commit subject (the `(X.Y[, DNA-nnn])` convention).

#### Scenario: Merged task gets checked
- **GIVEN** task 3.7 is unchecked in tasks.md and a commit on main carries `(3.7` in its subject
- **WHEN** `task checkoff CHANGE=<id>` runs
- **THEN** the 3.7 checkbox is flipped to `[x]` and no other line of tasks.md changes

#### Scenario: Unmerged task is untouched
- **GIVEN** task 4.2 is unchecked and no commit on main references it
- **WHEN** `task checkoff CHANGE=<id>` runs
- **THEN** the 4.2 checkbox remains unchecked

#### Scenario: Ambiguous or unknown task id fails loudly
- **GIVEN** a main commit subject references a task id not present in tasks.md
- **WHEN** `task checkoff CHANGE=<id>` runs
- **THEN** the tool reports the unmatched id and exits nonzero without writing anything

### Requirement: Check-off accepts explicit commits
The system SHALL accept one or more explicit commit refs (`--commit <sha>`, `COMMIT_SHA` via the
task target) and record only those commits' subjects, bypassing the history scan; unknown-id
refusal applies unchanged.

#### Scenario: Coordinator records the PR it just saw merge
- **GIVEN** merge commit `abc1234` carries `(3.2, DNA-801)` in its subject
- **WHEN** `checkoff --change <id> --commit abc1234` runs
- **THEN** only task 3.2's checkbox flips, regardless of what else history holds

### Requirement: Check-off prints the pre-filled next step
On flipping any boxes, the system SHALL print the exact follow-up commands with the change id
filled in (commit-and-push path, then `task dispatch CHANGE=<id>` for the wave that just opened),
so a coordinator agent needs no command construction.

#### Scenario: Output is copy-runnable
- **GIVEN** checkoff flips 3.2
- **WHEN** it reports
- **THEN** the output contains `task dispatch CHANGE=<id>` with the literal change id

### Requirement: Check-off commits under main_access conditions
The checkoff commit SHALL satisfy every `main_access` direct-push condition: `task check` green
first, the commit touches only tasks.md checkbox state, one focused commit, and a message that
names the merged PRs it records and says it bypassed review as a mechanical state update.

#### Scenario: Commit is mechanical only
- **GIVEN** checkoff has checkboxes to flip
- **WHEN** it commits
- **THEN** the diff contains only `[ ]` → `[x]` changes and the message lists the source PRs

#### Scenario: Nothing to record
- **GIVEN** every merged task is already checked
- **WHEN** `task checkoff CHANGE=<id>` runs
- **THEN** it reports "nothing to check off" and creates no commit

### Requirement: Wave gating is unchanged
Dispatch SHALL continue to read checked boxes as the sole wave-release signal; checkoff is a
producer of that state, not a new gate.

#### Scenario: Checkoff opens the next wave
- **GIVEN** wave N's last task merges and checkoff flips its box
- **WHEN** `task dispatch CHANGE=<id>` runs
- **THEN** wave N+1's eligible tasks are released exactly as if the box had been checked by hand
