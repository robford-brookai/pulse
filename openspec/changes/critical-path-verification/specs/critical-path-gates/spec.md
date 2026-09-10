## Purpose

Makes critical database and transport verification mandatory and reports precisely what assurance a green repository gate provides.

## ADDED Requirements

### Requirement: Required database verification fails closed

CI SHALL provision a pinned Postgres version and run required migration, atomicity, role, reversal, concurrency and replay suites against real Postgres. Missing server prerequisites, zero critical test collection or a skipped required case SHALL fail the gate. Optional local mode SHALL display its skipped prerequisites explicitly.

#### Scenario: Missing database prerequisite fails required mode

- **GIVEN** a subprocess fixture hides a required Postgres binary
- **WHEN** the critical suite runs in required CI mode
- **THEN** setup fails rather than passing with skipped database tests; optional local mode reports the missing prerequisite visibly

#### Scenario: Empty or skipped critical collection fails

- **GIVEN** a selector collects zero required tests or marks a required case skipped
- **WHEN** the critical gate evaluates suite results
- **THEN** the gate fails and identifies the missing invariant coverage

#### Scenario: Real database invariants produce evidence

- **GIVEN** the pinned Postgres prerequisite is available
- **WHEN** the critical suites execute
- **THEN** migration, atomicity, role, reversal, concurrency and replay cases run against the server and identify its version in the evidence

### Requirement: Transport integration is a distinct required check

The release/PR verification contract SHALL include a separate credential-free integration check using pinned LocalStack images with bounded startup and teardown. The fast task check contract SHALL remain documented separately. A committed workflow SHALL NOT be claimed as an active repository required-check rule without an attended configuration receipt.

#### Scenario: Transport check runs without live credentials

- **GIVEN** the pinned integration environment and synthetic events
- **WHEN** the separate transport check starts and completes or times out
- **THEN** existing relay integration cases exercise the transport, resources are torn down, and failure or timeout makes the check fail

#### Scenario: Required check activation has a receipt

- **GIVEN** the integration workflow passes but repository configuration is unverified
- **WHEN** release readiness is assessed
- **THEN** activation remains pending until an attended GitHub-tracked verification confirms the required check; YAML existence alone is insufficient

### Requirement: Coverage and exclusions state their actual assurance

Verification SHALL enforce independent 80 percent coverage floors for pulse-ledger and pulse-core from the combined coverage result and require named invariant suites independently of line coverage. A reachable-path exclusion inventory SHALL identify each inherited service exclusion, owner and disposition. Confirmed reachable injection or leakage SHALL block readiness until its focused fix merges; deferred non-confirmed risks SHALL have an owner and executable reproducer.

#### Scenario: One package cannot hide another package coverage failure

- **GIVEN** combined coverage exceeds 80 percent but one required package falls below 80 percent
- **WHEN** coverage is evaluated
- **THEN** the package-specific gate fails and reports both package scopes

#### Scenario: Reachable security suppression is accounted for

- **GIVEN** inherited exclusions and security-relevant suppressions on current write or consume paths
- **WHEN** the bounded audit evaluates synthetic reproducers
- **THEN** each finding has reachability, owner and disposition; a confirmed reachable injection or leak blocks readiness until fixed

### Requirement: Verification evidence is machine-readable and safe

Every required verification run SHALL emit JSON or JUnit evidence identifying commit, relevant Python/Postgres/LocalStack versions, suite identifiers, passed/failed/skipped counts and coverage scopes without credentials or payload values.

#### Scenario: Gate receipt distinguishes tested from skipped

- **GIVEN** a verification run with known results and version metadata
- **WHEN** its evidence is generated
- **THEN** the machine-readable receipt reports actual counts, scopes and versions without presenting omitted suites as passed or exposing sensitive values
