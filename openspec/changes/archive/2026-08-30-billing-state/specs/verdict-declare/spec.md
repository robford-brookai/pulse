## ADDED Requirements

### Requirement: A configured verdict type pairs its outcome with a state transition

For verdict types carrying a `transition_by_outcome` configuration entry, the relay SHALL follow
a committed or replayed `declare_verdict` with a `declare_transition` on the same subject,
targeting the state the configuration maps from the verdict's outcome. The transition's
idempotency key SHALL derive from the verdict row under the D16 convention, so the pair is
replay-safe as a unit: a rerun replays both halves, and a run interrupted between the two
completes the pair on resume. A verdict type without a `transition_by_outcome` entry SHALL
behave exactly as before — verdict only, no transition.

Pairing SHALL be per outcome, not per verdict type: a configured type may map some outcomes and
not others, and an outcome with no mapped state SHALL submit no transition. `indeterminate` SHALL
map nowhere for every registered type — an undecided verdict is evidence that the rule could not
decide, and moving state on it would assert a decision the verdict declined to make.

#### Scenario: A positive billing-eligibility verdict qualifies the episode

- **GIVEN** a `billing_eligibility` row with outcome `positive` for an `open` episode
- **WHEN** the relay declares it
- **THEN** the verdict commits and one paired transition commits moving the episode to
  `qualified`, both attributed to the relay's service identity

#### Scenario: The pair is idempotent as a unit

- **GIVEN** a row whose verdict and transition both committed in a prior run
- **WHEN** the row is processed again
- **THEN** both submissions classify as replayed and no new event exists

#### Scenario: An interrupted pair completes on resume

- **GIVEN** a run that committed a row's verdict and died before its transition
- **WHEN** the resumed run processes the row
- **THEN** the verdict replays, the transition commits, and the pair is complete

#### Scenario: An indeterminate outcome declares the verdict and moves no state

- **GIVEN** a row of a registered paired verdict type whose outcome is `indeterminate`, carrying
  a reason
- **WHEN** the relay declares it
- **THEN** the verdict commits and no transition is submitted

#### Scenario: An unpaired verdict type submits no transition

- **GIVEN** a verdict type with a `subject_type_by_verdict` entry but no `transition_by_outcome`
  entry
- **WHEN** a row of that type declares
- **THEN** exactly one command is submitted — the verdict — and no transition follows

### Requirement: A rejected paired transition is counted, never retried

A paired transition the ledger rejects (an illegal edge — e.g. the episode already `reported`)
SHALL be counted as transition-rejected and logged with the ledger's reason and catalog version,
and SHALL never be retried: past the lifecycle boundary, rejection is the correct answer. The
verdict half stands — evidence is never rolled back because its consequence was refused.

#### Scenario: A verdict against a reported episode keeps the verdict, drops the transition

- **GIVEN** a `billing_eligibility` row for an episode already in `reported`
- **WHEN** the relay declares it
- **THEN** the verdict commits, the paired transition is rejected and counted
  transition-rejected with the ledger's reason logged, no retry occurs, and the run continues
