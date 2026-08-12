## Purpose

The D4 artifact (DNA-908): the Twenty workspace model — objects, fields, relations, SELECT
options, roles, and the projection lookup — generated from `state_catalog.yaml` plus a
checked-in model definition into a serialized Metadata API operation set, built and validated
in CI, and never applied by the generator itself.

## ADDED Requirements

### Requirement: The generator emits a serialized Metadata API operation set from the catalog

The catalog→Twenty metadata generator SHALL read `state_catalog.yaml` through the established
catalog load path and emit (a) SELECT options arrays and the projection lookup table into
`packages/twenty-app/generated/`, and (b) the serialized Metadata API operation set artifact
expressing the full workspace model of `design/platform/twenty-data-model.md` — objects,
fields, relations, picklist options, and roles. It SHALL generate options arrays and the
operation set, never whole hand-written object files, and it SHALL NOT open any network
connection: generation is a pure file transformation.

#### Scenario: A catalog state becomes a SELECT option everywhere at once

- **GIVEN** a state in `state_catalog.yaml` for a dimension the model carries
- **WHEN** the generator runs
- **THEN** the state appears as an option in the generated options array, in the operation
  set's corresponding picklist operation, and in the projection lookup table, all from the
  single run

#### Scenario: Generation is offline

- **GIVEN** a test environment with sockets disabled
- **WHEN** the generator runs against the committed catalog
- **THEN** it completes with no connection attempted

### Requirement: The artifact is deterministic and CI-validated

The artifact SHALL be byte-identical across repeated runs over the same inputs, and CI
(`task check`) SHALL validate it: schema-valid operation set, regeneration matches the
committed artifact, generated options equal the catalog's states for each mapped dimension,
and the TypeScript options surface and the artifact carry identical option sets. A mismatch
SHALL fail the check.

#### Scenario: Re-render is byte-identical

- **GIVEN** the committed catalog, model definition, and UID map
- **WHEN** the generator runs twice
- **THEN** both outputs are byte-identical

#### Scenario: A drifted committed artifact fails CI

- **GIVEN** a committed artifact that no longer matches what the generator produces from the
  committed inputs
- **WHEN** `task check` runs
- **THEN** the artifact check fails, naming the artifact as stale

### Requirement: universalIdentifiers are minted once and never regenerated

Every object, field, and option `universalIdentifier` SHALL come from a checked-in map keyed
by stable name. The generator SHALL fail with an error naming the missing key when the map
lacks an identifier it needs — it SHALL NOT mint one. Existing map entries are append-only:
regeneration SHALL never change an existing identifier.

#### Scenario: A missing UID is a generation error, not a mint

- **GIVEN** a catalog state with no entry in the UID map
- **WHEN** the generator runs
- **THEN** generation fails with an error naming the missing key, and the map is unchanged

#### Scenario: Regeneration preserves every existing identifier

- **GIVEN** a committed artifact and UID map
- **WHEN** the generator re-runs after an unrelated catalog edit
- **THEN** every identifier present before the run is byte-identical after it

### Requirement: The model encodes single-writer roles

The operation set SHALL declare roles such that producers hold create-only permission on
DomainEvent, staff roles hold read-only permission on status fields and DomainEvent, and the
app (projection) role holds only what the projection function needs. Status fields SHALL NOT
be writable by any staff role in the generated model.

#### Scenario: Staff cannot write a status field

- **GIVEN** the generated operation set
- **WHEN** its role operations are inspected for any staff role
- **THEN** every status field grants read without write, and DomainEvent grants read without
  create, update, or delete

### Requirement: The generator never applies

The generator SHALL have no code path that communicates with a Twenty instance. Applying the
artifact is exclusively the deploy step's job (see `twenty-artifact-deploy`).

#### Scenario: No live-apply path exists

- **GIVEN** the generator module and its CLI surface
- **WHEN** invoked with any supported arguments under disabled sockets
- **THEN** it completes or fails on file I/O alone, with no connection attempted
