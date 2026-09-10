## Purpose

Defines observable runtime health, existing service objectives and bounded evidence that operators can detect and recover from service failures.

## ADDED Requirements

### Requirement: Existing SLOs have explicit measurement semantics

Monitoring SHALL implement the existing 99.9 percent monthly availability, command commit latency p99 below 500 ms, and ledger-to-Twenty freshness p99 below 60 s objectives. Each measure SHALL define timestamps, success/failure denominators and no-data behavior. Outbox age SHALL remain a diagnostic sub-budget, not a fourth SLO. Synthetic drills SHALL NOT be presented as monthly production SLO compliance.

#### Scenario: Idle and absent telemetry are distinguishable

- **GIVEN** an idle healthy consumer, missing telemetry and stale telemetry fixtures
- **WHEN** SLO and health signals are evaluated
- **THEN** idle traffic is not a consumer failure, absent/stale signals follow explicit no-data policy, and the three existing SLO calculations retain their documented denominators

### Requirement: Launch monitors have safe environment-specific routing

Monitor definitions SHALL cover API errors/latency, outbox lag/DLQ, consumer freshness, verdict-run staleness over 26 hours, missed month-open, reconciliation drift and quarantine depth/age. Each SHALL include environment, service, project:pulse, severity, owner-role and runbook. DLQ depth at least one SHALL alert, with sustained depth over 15 minutes following runtime-readiness section 3.3 paging policy. Live activation SHALL require verified owner and destination. Staging SHALL use verified non-paging routing, dev SHALL remain traces-only except an attended isolated drill, and production paging SHALL follow the existing pre-P2 business-hours and later cutover policy.

#### Scenario: Monitor definition covers the launch signal set

- **GIVEN** offline launch-monitor fixtures
- **WHEN** configuration is validated
- **THEN** every required signal has its threshold/no-data policy, tags, severity, owner-role and runbook, including DLQ immediate alert and sustained-depth page policy

#### Scenario: Unverified routing blocks activation

- **GIVEN** a monitor lacks a verified owner or destination
- **WHEN** live activation is requested
- **THEN** activation remains blocked while offline definition validation remains possible

#### Scenario: Environment routes follow the cutover policy

- **GIVEN** verified staging and production destinations and a dev environment
- **WHEN** monitor routing is evaluated for each release phase
- **THEN** staging cannot page production, dev remains traces-only outside the attended isolated drill, and production paging respects the existing cutover phase

### Requirement: Bounded recovery drills prove detection and recovery

Attended drills SHALL verify deployed release/probe identity before injecting isolated synthetic consumer token expiry, stopped/wedged consumer, temporary dependency outage or outbox backlog. Each fault family SHALL demonstrate the configured detection window, unhealthy state, signal delivery, retained unacknowledged work, recovery and duplicate suppression, followed by conformance evidence. Shared real credentials SHALL NOT be revoked for drills. Unexpected out-of-scope impact SHALL abort the drill. Existing reconciliation receipts SHALL be referenced rather than duplicated.

#### Scenario: Consumer failure retains work and recovers

- **GIVEN** a verified isolated synthetic consumer and bounded token-expiry or stopped/wedged-worker fault
- **WHEN** an attended fault and recovery drill runs
- **THEN** failure is detected within its configured window, the expected signal arrives, work is not acknowledged early, processing resumes without duplicate effects, and a conformance receipt is linked

#### Scenario: Dependency and backlog faults are bounded

- **GIVEN** a verified synthetic environment and scoped dependency-outage or backlog fault
- **WHEN** the fault is injected and removed in an attended session
- **THEN** detection and recovery evidence are recorded and any unexpected impact outside the test scope aborts the run

### Requirement: Operational receipts preserve identity and privacy

Versioned recovery receipts SHALL contain commit/image digest, environment, probe/fault identifier, timestamps, counts, expected threshold, outcome and evidence link. Telemetry SHALL propagate existing trace/correlation identity through writes and consumes without credentials, raw exception payloads or patient payload values.

#### Scenario: Recovery evidence is attributable and redacted

- **GIVEN** a synthetic fault run with trace identity and deliberately sensitive fixture values
- **WHEN** telemetry and the recovery receipt are emitted
- **THEN** write-to-consume correlation survives, required release/fault evidence is present, and no sensitive fixture values, credentials or raw exception payloads appear
