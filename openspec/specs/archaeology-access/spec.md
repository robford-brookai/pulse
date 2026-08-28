# archaeology-access Specification

## Purpose
Provides the single read-only access seam to the legacy Mongo cluster for backfill archaeology:
credentialed by reference, write-refusing, and receipt-producing, so discovery can run without
prod credentials ever entering a worktree or the repo.
## Requirements
### Requirement: Connections are built from secret references only

The client factory SHALL build its connection exclusively from environment variables that
reference the platform secret store. No literal credential, connection string, or secret value
SHALL exist in the repository — source, tests, fixtures, or docs — and a repository-wide
credential-material check SHALL enforce this.

#### Scenario: Missing env vars fail fast with names

- **GIVEN** an environment without the documented variables set
- **WHEN** the factory is invoked
- **THEN** it raises before any network attempt, naming the missing variable names (never
  values)

#### Scenario: Credential material cannot land in the tree

- **WHEN** the credential-material check runs over the repository
- **THEN** it finds no `mongodb+srv://` connection string carrying an `@` credential segment and
  no secret value, and exits zero

### Requirement: The client is read-only by construction

The factory SHALL produce a client suitable only for reads, and SHALL refuse to construct when
the resolved database user detectably holds write roles. Enforcement of read-only rests on the
Atlas role; the refusal is defense in depth, not the control.

#### Scenario: Write-role user is refused

- **GIVEN** credentials resolving to a user with a detectable write role
- **WHEN** the factory constructs the client
- **THEN** construction fails with a reason naming the offending role, and no client is returned

### Requirement: Smoke access produces a receipt

A CLI (`python -m archaeology.smoke --list-collections`) SHALL verify access by listing
collection names only, and its exit status SHALL serve as the access receipt for the discovery
session. It SHALL emit no field values and no documents.

#### Scenario: Successful smoke run

- **GIVEN** valid read-only credentials in the environment
- **WHEN** the smoke CLI runs with `--list-collections`
- **THEN** it prints collection names only and exits zero

#### Scenario: No live network in tests

- **WHEN** the package's test suite runs socket-blocked
- **THEN** every test passes with the Mongo client faked at the driver boundary
