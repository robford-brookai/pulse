## Purpose

The relay's production wiring and cadence: how the read → declare loop gets a real Snowflake
row source, a real cursor store, and a real service client from configuration, and how it runs
often enough that declare-back lag tracks mart freshness — resolving the S1.3 deferral.

## ADDED Requirements

### Requirement: Production dependencies construct from configuration

A production relay run SHALL construct its Snowflake `RowSource`, ledger cursor store, and
command API client from configuration and environment — credential names in configuration,
values from the environment, never in code or fixtures. A missing environment variable SHALL
fail startup with an error naming the variable. No credential value SHALL appear in any log,
receipt, or error message.

#### Scenario: A missing variable fails startup by name

- **GIVEN** a relay invocation with one required environment variable unset
- **WHEN** it starts
- **THEN** startup fails naming exactly that variable, before any connection is attempted

### Requirement: The relay runs by a credentialed task target, outside check

The relay SHALL be invocable as `task relay:run TARGET=<env>`. The target requires credentials
and SHALL stay out of `task check`, which remains offline and credential-free; the reachability
gate asserts the target's presence.

#### Scenario: Check stays offline while the target exists

- **GIVEN** the repository with no credentials in the environment
- **WHEN** `task check` runs
- **THEN** it passes without invoking the relay, and the reachability test asserts
  `relay:run` is defined

### Requirement: A scheduled poll approximates run-per-refresh

The relay SHALL run on a scheduled poll (schedules-package entry) rather than a cross-repo
trigger. Because declaration is idempotent (D16), the cursor is durable, and stale rows skip, a
poll that finds no new `computed_at` rows SHALL be a no-op run: zero declarations, a clean
receipt, exit zero. Declare-back lag SHALL therefore be bounded by mart freshness plus one poll
interval.

#### Scenario: A no-op poll exits clean

- **GIVEN** a cursor already at the mart's watermark
- **WHEN** the poll fires
- **THEN** the run declares nothing, emits a receipt with all-zero counts and
  `result=success`, and exits zero

#### Scenario: An extra run after a completed run changes nothing

- **GIVEN** a run that just completed a batch
- **WHEN** the poll fires again immediately
- **THEN** every row is a replay or stale-skip, and no new event exists
