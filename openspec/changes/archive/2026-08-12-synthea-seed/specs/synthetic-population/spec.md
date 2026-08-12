## Purpose

Defines the deterministic synthetic population every non-production tier and rehearsal consumes:
byte-identical regeneration receipted by manifest, with declarative overlays that engineer the
specific patient states the object model and genesis testing require.

## ADDED Requirements

### Requirement: Generation is byte-identical and receipted

The package SHALL pin the Synthea version, module configuration, and RNG seed such that two
generations from the same pin emit byte-identical populations, verified by a committed checksum
manifest. A generation whose output diverges from the manifest SHALL fail loudly.

#### Scenario: Two consecutive generations match

- **GIVEN** the pinned version, config, and seed
- **WHEN** generation runs twice
- **THEN** both outputs verify against the same checksum manifest with zero differences

#### Scenario: Drift is a failure, not a refresh

- **GIVEN** an output that no longer matches the manifest (e.g. an unpinned dependency moved)
- **WHEN** manifest verification runs
- **THEN** it exits nonzero naming the diverging files; the manifest is only updated by an
  explicit re-pin

### Requirement: Engineered fixtures are declarative overlays

Brook-specific fixtures SHALL be declarative overlay files applied on top of the generated base
— never hand-edits to generated output. The overlay set SHALL include at minimum: a mid-month
program switch within one exclusivity group, trinary verdict cases including `indeterminate`
with its mandatory reason, contradictory source states for genesis adjudication, and a
quarantine-bound consent case.

#### Scenario: Overlays apply deterministically

- **WHEN** the overlay set is applied to the generated base twice
- **THEN** both results are identical, and each named fixture patient is present with its
  engineered state

#### Scenario: Overlay validation rejects malformed fixtures

- **GIVEN** an overlay file referencing a patient or state that does not validate
- **WHEN** overlay application runs
- **THEN** it fails naming the file and reason, applying nothing partially

### Requirement: Regeneration is a task, never part of the check gate

Regeneration SHALL be invokable as a Taskfile target, and any CI workflow that regenerates
SHALL call that target on a schedule or dispatch — never inside `task check`. The package's unit
tests SHALL cover overlay application and manifest verification without running generation.

#### Scenario: Check stays Java-free

- **WHEN** `task check` runs on a machine without Java or Synthea installed
- **THEN** it passes, exercising only overlay and manifest logic

#### Scenario: Staging regen is invocable on demand

- **WHEN** the regen workflow is dispatched
- **THEN** it runs the Taskfile target, verifies the manifest, and publishes the population
  artifact for the staging tier
