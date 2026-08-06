## Purpose

Makes one schema-validated file — the authoritative state catalog at the repo root — the single
source every generated surface derives from, retiring the Appendix C seed per its retirement
clause.

## ADDED Requirements

### Requirement: The authoritative catalog is one schema-validated file

The authoritative state catalog SHALL be a single YAML file at `catalog/state_catalog.yaml`
carrying a semver `catalog_version`, the state-bearing subjects with their explicit transition
adjacency and ownership, the command vocabulary, the reason ValueSets, and the program
configuration. Loading SHALL validate the file against this schema and reject unknown keys,
transitions targeting undeclared states, and commands referencing undeclared subjects or
ValueSets — a malformed catalog SHALL fail naming the violation, never load partially.

#### Scenario: A schema-valid catalog loads

- **WHEN** the authoritative catalog file is loaded
- **THEN** it parses into the validated catalog model, exposing the version, subjects,
  commands, ValueSets, and programs

#### Scenario: A malformed catalog is rejected naming the violation

- **WHEN** a catalog with an unknown key, a transition to an undeclared state, or a non-semver
  version is loaded
- **THEN** loading fails with an error naming the offending entry, and no partial catalog is
  produced

### Requirement: Generated surfaces derive from the authoritative catalog

The command-surface generator SHALL read the authoritative catalog file as its only input, and
the committed generated module SHALL be pinned to the authoritative file's `catalog_version`.
The cutover from the Appendix C seed SHALL be behavior-preserving: the generated transition
tables, command types, and validators are unchanged apart from the version pin and source
provenance.

#### Scenario: The generated module derives from the authoritative catalog

- **WHEN** the generator runs against the authoritative catalog at version `1.0.0`
- **THEN** it emits the committed generated module pinned to `1.0.0`, with transition adjacency
  and command vocabulary identical to what the seed produced

#### Scenario: The Appendix C seed is retired

- **WHEN** the repository is searched after cutover
- **THEN** the seed file is absent and no code or generator path references it — the
  authoritative catalog is the only generator input

### Requirement: The consumer contract is pinned

The catalog SHALL expose exactly one contract for downstream consumers (first:
`producer-ingress-policy`'s CI gate): the authoritative file at `catalog/state_catalog.yaml` at
the repo head; its version as the semver `catalog_version` field, MAJOR incrementing exactly on
breaking releases; and the programmatic surface `pulse_core.generated` (`CATALOG_VERSION`,
`SUBJECT_TYPES`, `TRANSITIONS`, `COMMAND_TYPES`). Consumers SHALL read these and nothing else —
no consumer parses the seed, the Snowflake rows, or generator internals.

#### Scenario: A consumer resolves the contract surfaces

- **GIVEN** a downstream CI gate that must know every catalog state name
- **WHEN** it reads `catalog/state_catalog.yaml` and imports `pulse_core.generated`
- **THEN** both agree on `catalog_version` and the state/command vocabulary, and no other
  surface is required to answer the question
