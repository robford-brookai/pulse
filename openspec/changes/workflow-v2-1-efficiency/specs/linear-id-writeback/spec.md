# linear-id-writeback — delta

## Purpose

Gives `linear:sync` one sanctioned reverse edge: after creating a sub-issue it writes the
Linear-assigned issue id token into the task's line in tasks.md, eliminating hand-copied ids and
the drift they invite, while every other direction of truth stays file → Linear.

## ADDED Requirements

### Requirement: Sync writes issue ids back to tasks.md
When `linear:sync CHANGE=<id> APPLY=1` creates a sub-issue for a task whose line carries no issue
id, the system SHALL insert the `[<TEAM>-<n>]` token into that task's line in tasks.md, following
the existing annotation convention, and SHALL modify nothing else in the file.

#### Scenario: New task gains its id
- **GIVEN** task 5.10 has no bracketed issue id and sync creates DNA-812 for it
- **WHEN** the apply run completes
- **THEN** the 5.10 line carries `[DNA-812]` and the rest of tasks.md is byte-identical

#### Scenario: Existing id is never rewritten
- **GIVEN** task 3.7 already carries `[DNA-770]`
- **WHEN** sync runs and finds the sub-issue
- **THEN** the line is untouched, even if the Linear issue was moved or renamed

#### Scenario: Dry run writes nothing
- **GIVEN** sync runs without APPLY=1
- **WHEN** it plans a create that would write back an id
- **THEN** the plan output names the pending write-back and tasks.md is unmodified

### Requirement: The reverse edge is id-only
The write-back SHALL be the only mutation `linear:sync` ever makes to repo files. Task titles,
bodies, annotations, checkbox state, and ordering SHALL remain one-directional (file → Linear); a
sub-issue edited by hand in Linear remains drift to be overwritten at next sync.

#### Scenario: Linear-side edits do not flow back
- **GIVEN** someone edits a sub-issue description in Linear
- **WHEN** sync runs with APPLY=1
- **THEN** tasks.md content other than id tokens is unchanged and the sub-issue description is
  overwritten from the file
