# workflow-replan — delta

## Purpose

Makes mid-change plan amendment a first-class step in the WORKFLOW.md graph, so adding, widening,
or re-wiring tasks during execute happens through a reviewed, gated edge instead of ad-hoc direct
pushes that carry scope decisions.

## ADDED Requirements

### Requirement: The step graph defines replan
The WORKFLOW.md YAML block SHALL define a `replan` step reachable from `execute`, whose behavior
is: amend tasks.md via a pull request, re-check G_MECE over the amended and newly added tasks
only, then proceed to `sync_linear` and `dispatch`. The prose and diagram projections SHALL name
the step, and `task workflow:lint` SHALL pass.

#### Scenario: New tasks discovered mid-execute
- **GIVEN** a change is at execute and implementation reveals two missing tasks
- **WHEN** the tasks are added to tasks.md through a replan PR and G_MECE holds on the delta
- **THEN** the change proceeds through sync_linear and dispatch, and existing in-flight tasks are
  unaffected

#### Scenario: Amendment failing G_MECE does not dispatch
- **GIVEN** a replan PR adds a task with a dependency on a task id that does not exist
- **WHEN** G_MECE is checked on the delta
- **THEN** the amendment is rejected back to replan and no work order is emitted for it

### Requirement: The delta G_MECE check is tool-run
The system SHALL provide `task replan CHANGE=<id>` running the mechanical G_MECE assertions over
tasks.md (lanes known, deps resolve, serial flags justified, waves monotonic, spec validation)
and printing the pre-filled follow-up commands on pass. No gate in the replan path SHALL require
a human comment — G_APPROVAL remains the only comment-gated check, and only on tasks tagged
destructive or prod-touching.

#### Scenario: Agent validates an amendment without human gate work
- **GIVEN** an agent has amended tasks.md on a replan branch
- **WHEN** `task replan CHANGE=<id>` runs and passes
- **THEN** the output names the PR as the next step, and no human comment is requested anywhere

#### Scenario: A broken amendment fails with the defect named
- **GIVEN** an amendment adds a task depending on a task id that does not exist
- **WHEN** `task replan CHANGE=<id>` runs
- **THEN** it exits nonzero naming the dangling dependency

### Requirement: Plan amendments carry review
A tasks.md edit that adds a task, widens a task's scope, or changes a dependency edge SHALL reach
main by pull request; the `main_access` direct-push exemption SHALL apply only to checkbox state
and other decision-free mechanical updates.

#### Scenario: Scope widening is a PR
- **GIVEN** task 3.8 needs its scope widened to cover a newly found path
- **WHEN** the amendment is made
- **THEN** it arrives as a replan PR, not a direct push

### Requirement: State resolution recognizes replan
The `state_resolution` order SHALL resolve a change to `replan` when tasks.md has amendments not
yet reflected in Linear sub-issues or work orders, before resolving to `execute`.

#### Scenario: Agent lands after an amendment merges
- **GIVEN** a replan PR merged and `linear:sync` has not run since
- **WHEN** an agent computes the current step
- **THEN** the resolution is sync_linear/dispatch for the delta, not a bare execute
