## ADDED Requirements

### Requirement: The mart read retires behind the reconciliation gate

Once the verdict-reconciliation gate passes (a full billing month's sweep, empty-or-explained),
the relay's mart read SHALL be decommissioned: the scheduled poll stops, the relay's Snowflake
credential is retired, and the mart becomes an analytics and reconciliation surface only —
no pulse write path SHALL depend on it. Until that gate passes, this capability's existing
requirements stand unchanged and the poll keeps running.

#### Scenario: Retirement follows the gate, not the calendar

- **GIVEN** the reconciliation window still open or its diff not yet empty-or-explained
- **WHEN** any change proposes stopping the mart poll
- **THEN** the gate refuses — the poll and its cursor semantics remain in force

#### Scenario: After retirement, the write path has no warehouse dependency

- **GIVEN** the gate passed and the mart read decommissioned
- **WHEN** the verdict write path's runtime configuration is inspected
- **THEN** no Snowflake credential remains on it, and verdicts flow only from the engine's
  event-driven evaluation
