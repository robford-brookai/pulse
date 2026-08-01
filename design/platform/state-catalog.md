# PULSE State Catalog — Schema and Generation

| | |
|---|---|
| **Status** | Draft v1 |
| **Date** | 2026-07-28 |
| **Owner** | Rob Ford, Data |
| **Harvested from** | DNA-SPEC-DECLARED-STATE-PRM §3 |
| **Related** | event-envelope-spec.md; twenty-data-model.md; snowflake-landing-spec.md |

## Purpose

One versioned, machine-readable file — `state_catalog.yaml`, in the platform repo — is the single source of truth for states, transitions, and event types. Everything else is generated from it. The stage-rationalization exercise ("which of the ~17 substages are stages, holds, exits") ratifies `state_catalog v1`; every later change is a PR.

The event type registry in event-envelope-spec.md is **derived from this catalog**, not maintained beside it.

## Schema

```yaml
version: 1                     # ratified version; emitted events carry this as rule_version
entity_grains:
  patient_program: patient × program    # per decision 2026-07-28
  provider: provider
  clinic: clinic

states:
  - name: enrolled
    entity: patient_program
    class: stage               # stage | hold | exit
    event_type: patient.enrolled
    definition: >
      Patient consented and enrolled in the program at a participating clinic.
    owner: enrollment-ops
    entry:
      predicate: "consent recorded AND coverage verified"
      rule_domain: business    # business | billing_investigation — never blended
    transitions_to: [activated, hold.awaiting_device, exit.withdrawn]

  - name: hold.awaiting_device
    entity: patient_program
    class: hold                # holds are states, not annotations
    event_type: patient.device-wait-started
    definition: "Enrollment paused pending device shipment/assignment."
    owner: enrollment-ops
    entry:
      predicate: "enrolled AND no active device assignment"
      rule_domain: business
    transitions_to: [enrolled, activated, exit.withdrawn]

  - name: exit.withdrawn
    entity: patient_program
    class: exit                # exits are recordable events with reasons
    event_type: patient.withdrawn
    definition: "Patient left the funnel; reason captured in payload."
    owner: enrollment-ops
    reentry_to: [registered]   # return loops are legal and modeled
```

Rules encoded by the schema:

1. **States only.** Actions (copay rebate, outreach) reference states; they never define them.
2. **Class separates stages from holds from exits** — the conflation that produced "~17 substages that are mostly reasons a patient hasn't moved" is structurally impossible.
3. **`rule_domain` tags every predicate** `business` or `billing_investigation`, so the domains cannot blend at query time.
4. **Every state carries its event type** — one state entry, one noun.verb event, no drift between catalog and registry.
5. **Adjacency is explicit**, including re-entry loops ("call me in 3 months" → marketing).

## Generation targets (two enforcers, one artifact)

```
state_catalog.yaml
  ├─▶ Twenty (metadata API script, CC-executed)
  │     picklist values (event_type, status SELECTs on PatientProgram/Provider/Clinic)
  │     projection lookup rows for the project-domain-event workflow
  ├─▶ dbt seeds
  │     REF_EVENT_REGISTRY (event_type → state_dimension, state_value, entity, class)
  │     REF_VALID_TRANSITIONS (from_state, to_state, dimension)
  └─▶ rendered markdown (human-readable catalog for stakeholders)
```

- **Enforcer 1 (write time)**: the projection workflow applies only catalog-known event types (picklists make unknown types unrepresentable). Transition legality remains flag-only at MVP.
- **Enforcer 2 (verification)**: Snowflake `Q_INVALID_TRANSITIONS` and `Q_UNKNOWN_EVENT_TYPES` read the dbt-seeded tables — the warehouse re-verifies downstream, per the "warehouse is the referee" rule.

One PR updates the catalog; CI regenerates all three targets. Definitions are shareable because they are a versioned file, not tribal SQL.

## Ratification process

1. Snowflake inspection query over existing substage data produces the candidate collapse (stage/hold/exit assignment for each of the ~17).
2. Owning teams confirm definitions and predicates per state.
3. `state_catalog v1` merged = ratified. Registry v1.1 event types (registered/enrolled/activated/qualified/disqualified + provider/clinic) are seeds for this exercise, not its conclusion.

## Versioning

- Catalog version increments on any state/transition/predicate change.
- Emitted events carry the applied version as `rule_version` (envelope field) — every historical event is interpretable against the rules in force when it was written.
- Predicate revisions (e.g., the rolling-30-day hold heuristic) are catalog edits, not schema changes.
