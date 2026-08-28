## Purpose

The D18 release job: merge to main lands the released catalog as immutable, tagged, versioned
rows in a Snowflake `catalog` schema — with git as the only editor, and CI never holding the
credentials.

## ADDED Requirements

### Requirement: A release renders versioned rows for the catalog schema

The release job SHALL render, from a released catalog version, the complete row set for the
`catalog` schema — states, transitions, reason ValueSets, and program config, plus one version
row carrying the release metadata (version, source git identity, content checksum, breaking
classification). Every row SHALL carry the immutable `catalog_version`, writes SHALL be
INSERT-only (no UPDATE or DELETE is ever rendered), and the rendered release SHALL apply
Snowflake object tags marking the catalog objects and the release version. Rendering SHALL be
deterministic: the same catalog version renders byte-identical output.

#### Scenario: A release renders insert-only rows for every catalog surface

- **WHEN** the release job renders a catalog version
- **THEN** the output contains INSERT-only statements for states, transitions, ValueSets,
  programs, and the version row, every row stamped with that `catalog_version`, and contains no
  UPDATE or DELETE

#### Scenario: Catalog objects are tagged with the release version

- **WHEN** the release job renders a catalog version
- **THEN** the output applies the Snowflake object tags marking the catalog objects and the
  released version

### Requirement: A released version is never rewritten

Before writing, the release job SHALL check whether the target `catalog_version` already exists
in the warehouse. An existing version whose recorded checksum matches the release SHALL make the
run a successful no-op (re-runs and catch-ups are safe); an existing version whose checksum
differs SHALL hard-fail before any write — no hand edit, re-release, or job bug may ever change
released rows.

#### Scenario: An identical re-release is a no-op

- **WHEN** the release job runs for a version already present with a matching checksum
- **THEN** it writes nothing and exits successfully, reporting the version as already released

#### Scenario: A conflicting re-release fails before any write

- **WHEN** the release job runs for a version already present with a different checksum
- **THEN** it fails before executing any insert, naming the version and both checksums

### Requirement: The release job is a deploy artifact, never a check step

The release job SHALL be triggered by merge to main touching the catalog and SHALL run only
through the dedicated release entrypoint. Without warehouse credentials the entrypoint SHALL
print the release plan and exit zero; demanding apply without credentials SHALL be an error,
never a silent no-op. `task check` SHALL NOT invoke the release path or require any warehouse
credential — the check contract stays green on a credential-free runner, per the consumes
posture.

#### Scenario: Planning without credentials

- **WHEN** the release entrypoint runs with no warehouse credentials and apply not requested
- **THEN** it prints the rendered release plan and exits zero without any network call

#### Scenario: Apply without credentials is an error

- **WHEN** apply is requested and no warehouse credentials are present
- **THEN** the entrypoint exits nonzero naming the missing credentials, rather than silently
  skipping the release

#### Scenario: The check contract stays credential-free

- **WHEN** `task check` runs on a runner with no warehouse credentials
- **THEN** no step invokes the release path and the suite passes without reaching Snowflake
