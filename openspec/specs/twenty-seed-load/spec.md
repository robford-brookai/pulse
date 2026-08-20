# twenty-seed-load Specification

## Purpose
Defines how a synthetic population is loaded into a Twenty instance so a demo has something to
drag: a committed deterministic projection as the source, idempotent upserts keyed on natural
identifiers, and the guarantee that loading never destroys workspace data.
## Requirements
### Requirement: The seed source is a committed deterministic projection, not a live generator run

The population loaded into Twenty SHALL come from a committed, checksummed projection file held in
this repo. Loading SHALL NOT require running a synthetic-data generator, an untracked output tree,
or a Java toolchain, so that the same population is reproducible from a fresh clone.

The projection SHALL carry the canonical spine identifiers the drag path resolves subjects
through, minted deterministically from the generator's own record identifiers so that repeated
derivation yields the same values.

All seeded content SHALL be synthetic. No real patient data SHALL enter the projection, the
loader's logs, or its receipts.

#### Scenario: Seeding from a fresh clone needs no generator

- **GIVEN** a fresh clone with no generator toolchain installed
- **WHEN** the seed loader runs
- **THEN** it loads the committed projection successfully

#### Scenario: The projection is verified before use

- **GIVEN** a projection file whose contents do not match its recorded checksum
- **WHEN** the loader runs
- **THEN** it refuses to load and names the mismatch

### Requirement: Loading is idempotent on natural keys and never deletes

The loader SHALL match existing records by natural key — never by Twenty's internal record
identifiers, which are not stable across instances. For each record it SHALL create when absent
and patch when present and drifted, and it SHALL make no change when present and matching.

The loader SHALL NOT delete records, and SHALL NOT remove workspace content that is absent from
the projection. A record present in the workspace but not in the projection SHALL be left alone.

#### Scenario: A second run changes nothing

- **GIVEN** a workspace already seeded from the projection
- **WHEN** the loader runs again
- **THEN** every record is reported as unchanged and no write is issued

#### Scenario: A drifted field is patched back

- **GIVEN** a seeded record whose field has since been edited in the workspace
- **WHEN** the loader runs
- **THEN** that record is patched back to the projection's value and reported as updated

#### Scenario: Workspace records outside the projection survive

- **GIVEN** a workspace containing a record the projection does not describe
- **WHEN** the loader runs
- **THEN** that record is untouched

### Requirement: Every seeded board record is immediately draggable

Each seeded record that lands on a kanban board SHALL be complete enough for a drag to commit on
arrival — in particular it SHALL carry a non-null status as-of stamp, so that the first drag
resolves an effective time rather than failing.

#### Scenario: The first drag after seeding commits

- **GIVEN** a freshly seeded workspace
- **WHEN** the first card is dragged to a legal column
- **THEN** the drag commits, rather than being refused for a missing effective time

### Requirement: Loading respects instance limits and reports without exposing workspace content

The loader SHALL chunk and pace its writes to stay within the instance's per-call batch size and
request rate limits, rather than relying on the instance to reject excess.

Its receipt SHALL carry object names, counts, and checksums only. Record identifiers, field
values, and response bodies SHALL NOT appear in the receipt or in log lines, so a receipt is safe
to attach to a ticket.

#### Scenario: A large population is loaded within rate limits

- **GIVEN** a projection larger than one batch
- **WHEN** the loader runs
- **THEN** it issues chunked, paced calls and completes without a rate-limit rejection

#### Scenario: A receipt carries no workspace content

- **WHEN** a load completes
- **THEN** its receipt names objects, counts, and checksums, and contains no record identifiers or
  field values
