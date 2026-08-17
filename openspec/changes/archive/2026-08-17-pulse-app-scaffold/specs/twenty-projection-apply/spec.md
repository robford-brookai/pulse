## Purpose

`project-domain-event` as versioned, unit-tested code: the logic function that applies a
DomainEvent record to entity state inside Twenty — entity resolution, per-dimension LWW guard,
and the projection lookup — replacing the UI-configured workflow with TypeScript the repo
reviews and tests.

## ADDED Requirements

### Requirement: A domain event applies through resolution, guard, then lookup

On a DomainEvent creation, the handler SHALL (1) resolve the entity by
(`entityRefSystem`, `entityRefId`) crosswalk — patient events additionally resolving
(Patient, `programCode`) to a PatientProgram, creating that row on the first event for the
pair; (2) apply the per-dimension LWW guard; (3) set the status field and its matching
`...AsOf` per the generated projection lookup. The handler SHALL take its client as an
injected boundary so every behavior below is unit-testable without a server.

#### Scenario: First event for a pair creates the PatientProgram row

- **GIVEN** a resolvable patient with no PatientProgram row for program P
- **WHEN** a lifecycle event for (patient, P) is handled
- **THEN** the PatientProgram row is created and its status applied from the lookup

### Requirement: Late events never regress state

For each state dimension independently, the handler SHALL make no state change when the
event's `occurredAt` is at or before the target's `<dimension>StatusAsOf`; the event record
itself remains logged. Qualification events compare against `qualificationStatusAsOf` only,
lifecycle events against `lifecycleStatusAsOf` only — a qualification event SHALL NOT touch
lifecycle fields, and vice versa.

#### Scenario: A late event is a no-op on state

- **GIVEN** a PatientProgram whose `lifecycleStatusAsOf` is T
- **WHEN** a lifecycle event with `occurredAt` ≤ T is handled
- **THEN** `lifecycleStatus` and `lifecycleStatusAsOf` are unchanged and the event record
  still exists

#### Scenario: Dimensions are isolated

- **GIVEN** a PatientProgram with both dimensions populated
- **WHEN** a qualification event is handled
- **THEN** `lifecycleStatus` and `lifecycleStatusAsOf` are unchanged

### Requirement: Unresolved references park as orphans without failing

When entity resolution finds no match, the handler SHALL leave the event's relations empty and
stop — no crash, no state write — so the event surfaces in the orphan view rather than being
lost or misapplied.

#### Scenario: An unresolvable ref stops cleanly

- **GIVEN** a DomainEvent whose (`entityRefSystem`, `entityRefId`) matches no record
- **WHEN** the handler runs
- **THEN** it completes without error, writes no state, and the event's relations remain empty

### Requirement: Unknown event types cannot reach the handler

`eventType` SHALL be constrained to the catalog-generated picklist, so an event type outside
the catalog is rejected at record creation, before the handler runs. The handler SHALL
additionally treat a lookup miss as a logged no-op, never a crash.

#### Scenario: A lookup miss is a no-op

- **GIVEN** an event whose type has no row in the projection lookup
- **WHEN** the handler runs
- **THEN** it completes without error and writes no state

#### Scenario: A resolved event with no lookup row is still bound to its target

- **GIVEN** an event whose type has no row in the projection lookup and whose reference resolves
- **WHEN** the handler runs
- **THEN** the event's relation is set to the resolved target, no status field or `...AsOf` is
  written, and the event does not appear in the orphan view
