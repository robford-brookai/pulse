## Purpose

Defines how the command API is served as a running process rather than an importable factory: its
entrypoint and liveness surface, how it holds database connections under concurrent requests, and
the credential split that makes it structurally incapable of altering schema or mutating the
append-only ledger.

## ADDED Requirements

### Requirement: The API is served by a dedicated entrypoint that reads configuration at start, not import

The command API SHALL be startable as a process without a wrapper script. Importing the
application module SHALL NOT read the environment, open a connection, or require a database to be
reachable, so that the test suite can import it offline and credential-free.

Configuration SHALL be read when the process starts, and a missing required credential SHALL fail
with a message naming what is absent. In particular, the credential registry refuses to build when
no writer token is configured; that condition SHALL surface as a stated startup error rather than
an unhandled traceback.

#### Scenario: Importing the app requires no database and no environment

- **GIVEN** no database is reachable and no API environment variables are set
- **WHEN** the application module is imported
- **THEN** the import succeeds and no connection is attempted

#### Scenario: Starting without a writer token fails with a named reason

- **GIVEN** no writer token is configured
- **WHEN** the process starts
- **THEN** startup fails with an error naming the missing credential, rather than an unhandled
  traceback

### Requirement: Liveness is separate from the authenticated surface and does not touch the database

The served process SHALL expose a liveness endpoint that requires no authentication, so that the
command API's contract that every route is authenticated is preserved unchanged.

Liveness SHALL report only that the process is running. It SHALL NOT query the database, so that a
transient database outage does not cause healthy processes to be restarted while the outage is
already the problem.

#### Scenario: Liveness answers without a credential

- **WHEN** the liveness endpoint is called with no credential
- **THEN** it returns success

#### Scenario: Liveness stays green while the database is unreachable

- **GIVEN** the database is unreachable
- **WHEN** the liveness endpoint is called
- **THEN** it returns success, because it performs no query

#### Scenario: Command routes remain authenticated

- **WHEN** any command route is called with no credential
- **THEN** it is rejected as unauthenticated

### Requirement: Connections are pooled, never shared across concurrent requests

The served process SHALL obtain database connections from a pool sized independently of request
concurrency. Two requests in flight at once SHALL NOT share a connection, because commits hold a
per-subject lock for the duration of their transaction and a shared connection would serialize or
interleave unrelated work.

#### Scenario: Concurrent commits for distinct subjects do not block on each other

- **GIVEN** two commands for different subjects arrive concurrently
- **WHEN** both are committed
- **THEN** each runs on its own connection and neither waits on the other's per-subject lock

### Requirement: The serving credential cannot alter schema or mutate the ledger

The role the served process authenticates as SHALL hold only the append-only posture the ledger
schema grants — select and insert on the events relation, with update and delete revoked — and
SHALL own no objects.

Schema migration SHALL run as a separate role holding the DDL rights the serving role lacks.
Migration SHALL NOT be performed by the serving process or by an init container sharing its
lifecycle, because either would place a DDL-capable credential in the serving process's
environment and dissolve the split.

#### Scenario: The serving role cannot delete a committed event

- **GIVEN** a process authenticated with the serving role
- **WHEN** it attempts to delete or update a row in the events relation
- **THEN** the database refuses the statement

#### Scenario: The serving role cannot run DDL

- **GIVEN** a process authenticated with the serving role
- **WHEN** it attempts to create or alter a relation
- **THEN** the database refuses the statement

#### Scenario: Migration uses a different credential than serving

- **WHEN** a migration runs
- **THEN** it authenticates as the migrator role, and the serving process's environment never
  carries that credential
