## Purpose

Opens one BillingEpisode per active or on-hold Enrollment at month start, reading the ledger's own
state and declaring through the single write path, so billing months never silently fail to open.

## ADDED Requirements

### Requirement: Month-open opens one BillingEpisode per eligible enrollment

The month-open job SHALL enumerate Enrollments in the `active` and `on_hold` states from the
ledger's own current-state read surface — a library read against the ledger store's co-committed
state rows, never the warehouse or any projection — and SHALL declare one `open_billing_episode`
per enrollment × current month through the command API. Requested state names SHALL be
catalog-validated: an unknown state is a rejection of the run, never an empty result set.

#### Scenario: Normal month-open

- **GIVEN** the ledger holds enrollments in `active`, `on_hold`, and `ended`
- **WHEN** month-open runs on the first of the month
- **THEN** exactly the active and on-hold enrollments each get one `open_billing_episode`
  declared for the current month, and ended enrollments get none

#### Scenario: A state-name typo rejects the run

- **GIVEN** a run configured to enumerate a state name absent from the catalog
- **WHEN** month-open enumerates
- **THEN** the run fails with the catalog rejection, and no commands are declared

### Requirement: Month-open is safely re-runnable any day of the month

Each declaration SHALL carry a D16 idempotency key derived from the enrollment and the billing
month, so a re-run — same day or mid-month — replays episodes already open instead of opening
duplicates.

#### Scenario: Re-run replays

- **GIVEN** a completed month-open run for the current month
- **WHEN** the job runs again the same day
- **THEN** every declaration classifies as `replayed`, no second episode is opened, and the
  receipt records the replay count

#### Scenario: Mid-month invocation

- **GIVEN** a month whose episodes were opened on the 1st and one enrollment activated on the 10th
- **WHEN** month-open runs on the 15th
- **THEN** the pre-existing episodes replay, the new enrollment's episode is opened, and the
  receipt distinguishes the two

### Requirement: Zero enrollments enumerated is a hard failure

The job SHALL treat an empty enumeration as a failed run — exiting nonzero and reporting the
invariant breach — never as a success with count 0. An operating clinic always has eligible
enrollments; an empty set means the read path or configuration is broken.

#### Scenario: Zero-enrollment failure

- **GIVEN** an enumeration that returns no enrollments
- **WHEN** month-open runs
- **THEN** the run exits nonzero with a failure receipt naming the invariant, and no commands are
  declared

### Requirement: Month-open emits a receipt

Every run SHALL emit a receipt with the counts of episodes opened, replayed, and failed. A run
with any failed declaration SHALL exit nonzero so the scheduler's retry window re-drives it —
idempotency makes the retry safe.

#### Scenario: Receipt reflects the run

- **GIVEN** a run in which some declarations commit, some replay, and one is rejected
- **WHEN** the run completes
- **THEN** the receipt reports opened, replayed, and failed counts matching the outcomes, and the
  process exit status is nonzero because a declaration failed
