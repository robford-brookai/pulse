## Purpose

Defines the declare-back contract: how a verdict mart row becomes an attributed, idempotent
`declare_verdict` command on the single write path, the per-subject ordering rule, trinary outcome
validation, and what each command API response classification means for the run.

## ADDED Requirements

### Requirement: A mart row maps to an attributed, idempotent command

Each mart row SHALL be declared as a `declare_verdict` command whose actor is the relay's service
identity (per-service credential, D15 — credential name in configuration, value from the
environment, never in code or fixtures), carrying the row's `rule_version`, `as_of`, and
`lineage_ref`. The idempotency key SHALL follow the D16 convention, derived client-side, so
re-declaring the same row can never commit a second event.

#### Scenario: A normal declare commits with attribution and lineage

- **GIVEN** a valid mart row for a subject with no newer declared verdict
- **WHEN** the relay declares it
- **THEN** the submitted command carries actor = the relay's service identity, the row's
  `rule_version`, `as_of`, and `lineage_ref`, and a D16 idempotency key, and the response
  classifies as committed

### Requirement: The subject type derives from a configuration mapping

The relay SHALL derive the declared command's `subject_type` from the row's `verdict_type` via a
configuration mapping (`subject_type_by_verdict`) — the mart contract carries no `subject_type`
column, and the ledger validates `subject_type` against the catalog. A `verdict_type` absent from
the mapping SHALL fail validation before any API call, and the row SHALL be reported as failed
with the validation error naming the row — the same treatment as indeterminate-without-reason.

#### Scenario: An unmapped verdict type fails before the API call

- **GIVEN** a mart row whose `verdict_type` has no entry in `subject_type_by_verdict`
- **WHEN** the relay processes it
- **THEN** validation fails before any command is submitted, no API call occurs, and the row is
  reported as failed with the validation error

### Requirement: Outcomes are trinary and indeterminate requires a reason

Verdict outcomes SHALL be exactly `positive | negative | indeterminate`, per the catalog-generated
enum. An `indeterminate` outcome without a reason SHALL fail validation before any API call is
attempted, and the row SHALL be reported as failed with the validation error.

#### Scenario: Indeterminate with a reason declares normally

- **GIVEN** a mart row with outcome `indeterminate` and a non-empty `reason`
- **WHEN** the relay declares it
- **THEN** the command commits carrying the reason

#### Scenario: Indeterminate without a reason fails before the API call

- **GIVEN** a mart row with outcome `indeterminate` and no `reason`
- **WHEN** the relay processes it
- **THEN** validation fails before any command is submitted, no API call occurs, and the row is
  reported as failed with the validation error

### Requirement: Per-subject declaration is as_of-monotonic and stale rows are skipped

For each subject, verdicts SHALL be declared in ascending `as_of` order, and the relay SHALL never
declare a verdict older than the subject's latest declared `as_of`. A stale row (an out-of-order
run arriving after a newer verdict was declared) SHALL be skipped and counted, never declared and
never treated as an error.

#### Scenario: A shuffled batch declares monotonically and skips stale rows

- **GIVEN** any shuffled batch of verdict runs across subjects, including runs older than a
  subject's latest declared `as_of`
- **WHEN** the relay processes the batch
- **THEN** the declared order is `as_of`-monotonic per subject, every stale row is skipped and
  counted as skipped-stale, and no stale row produces a declaration or an error

### Requirement: Response classifications drive distinct handling

The relay SHALL handle each command API response classification distinctly: **committed** counts
as declared; **replayed** counts as an idempotent hit and never re-declares; **rejected** (illegal
transition) is counted and logged with the ledger's reason and version, and never retried;
**transient** is retried with backoff up to 5 attempts, after which the run fails identifying the
failing row.

#### Scenario: A replay is an idempotent hit, not a second declaration

- **GIVEN** a row whose idempotency key was already committed
- **WHEN** the relay declares it and the response classifies as replayed
- **THEN** the row counts as replayed, no retry occurs, and the run continues

#### Scenario: A rejection is counted, logged with the ledger's reason, and never retried

- **GIVEN** a row whose declaration the ledger rejects as an illegal transition
- **WHEN** the relay receives the rejected classification
- **THEN** the row counts as rejected, the log carries the ledger's reason, no retry occurs, and
  the run continues

#### Scenario: A transient failure retries with backoff then fails the run naming the row

- **GIVEN** a row whose submission returns transient on every attempt
- **WHEN** the relay retries with backoff
- **THEN** exactly 5 attempts are made, the run fails, and the failure identifies the failing row
