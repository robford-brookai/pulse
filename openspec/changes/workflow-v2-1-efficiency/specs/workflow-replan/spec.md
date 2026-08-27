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
