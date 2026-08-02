# Twenty Data Model — PULSE (Patient Unified Ledger of State & Events)

| | |
|---|---|
| **Status** | Draft v1 |
| **Date** | 2026-07-28 |
| **Owner** | Rob Ford, Data |
| **Related** | event-envelope-spec.md; snowflake-landing-spec.md; state-catalog.md; claude-code-integration-paths.md |

All objects below are Twenty custom objects created via the metadata API (config-as-code; see claude-code-integration-paths.md). Core is never modified.

## Objects

### Patient

Identity and crosswalk only — **patient state lives on PatientProgram** (grain decision 2026-07-28). Twenty never mints patient identity: records are created only with a canonical spine ID (write-ownership matrix rule 2; pre-identity referrals are Leads, outside this model).

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | Twenty record ID — internal only, never an `entity_ref`. |
| `canonicalPatientId` | TEXT | **`DIM_PATIENT_CONFORMED` spine ID. The canonical identity** (`entity_ref` system `brook`). Required, unique. |
| `name` | FULL_NAME | Standard. |
| `sfdcId` | TEXT | External ID, `entity_ref` system `sfdc`. Unique by convention. |
| `mrn` | TEXT | External ID, system `mrn`. |
| `appUserId` | TEXT | External ID, system `app`. |
| `patientPrograms` | RELATION (one-to-many) | → PatientProgram. |

### Program

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `code` | TEXT | Stable program ID used in envelope `program` field. Unique. |
| `name` | TEXT | Display. |

### PatientProgram (junction — the patient-state grain)

One row per patient × program. All patient state dimensions live here.

| Field | Type | Notes |
|---|---|---|
| `patient` | RELATION | → Patient. Required. |
| `program` | RELATION | → Program. Required. Pair unique by convention. |
| `lifecycleStatus` | SELECT | Values from state catalog (v1.1 seed: `registered` \| `enrolled` \| `activated`). Projection target. |
| `lifecycleStatusAsOf` | DATE_TIME | LWW guard. |
| `qualificationStatus` | SELECT | `pending` (default) \| `qualified` \| `disqualified`. Set only by `clinic-rules-engine` events. |
| `qualificationStatusAsOf` | DATE_TIME | LWW guard. |
| `domainEvents` | RELATION (one-to-many) | → DomainEvent. |

Program note (write-ownership matrix D2): enrollment's system of record defaults to Mongo through P2. Until D2 resolves, PatientProgram in Twenty is a **projection target only** — populated exclusively by the projection workflow from domain events, never edited directly.

### Provider

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | Canonical. |
| `name` | FULL_NAME | Covers contact1/contact2 analog. |
| `sfdcId` | TEXT | External ID. |
| `npi` | TEXT | External ID, system `npi` (add to envelope registry when first producer needs it). |
| `lifecycleStatus` | SELECT | `credentialed` (v1; extend with catalog). |
| `lifecycleStatusAsOf` | DATE_TIME | LWW guard. |
| `domainEvents` | RELATION | → DomainEvent. |

### Clinic

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | Canonical. |
| `name` | TEXT | Account analog. |
| `sfdcId` | TEXT | External ID. |
| `lifecycleStatus` | SELECT | `onboarded` (v1). |
| `lifecycleStatusAsOf` | DATE_TIME | LWW guard. |
| `domainEvents` | RELATION | → DomainEvent. |

### DomainEvent (API name `domainEvent`, REST plural `domainEvents`)

The append-only event log. Named to avoid collision with Twenty's CRUD-notification vocabulary.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | Twenty-generated record ID (not the idempotency key). |
| `eventId` | TEXT | Producer idempotency key. Unique by convention; deduped in Snowflake. |
| `eventType` | SELECT | Values = state catalog registry. Adding a type = catalog PR. |
| `entityType` | SELECT | `patient` \| `provider` \| `clinic`. |
| `entityRefSystem` | SELECT | `brook` \| `sfdc` \| `mrn` \| `app`. |
| `entityRefId` | TEXT | ID within that system. |
| `programCode` | TEXT | Envelope `program`. Required for patient events. |
| `occurredAt` | DATE_TIME | Business time (producer). |
| `createdAt` | DATE_TIME | Twenty-set = `recorded_at`. |
| `producer` | TEXT | Set by the MCP write path from key identity — not producer-supplied. |
| `schemaVersion` | NUMBER | Currently 1. |
| `ruleVersion` | TEXT | State catalog version applied. |
| `correlationId` | TEXT | Journey ID across systems. Optional. |
| `causationId` | TEXT | Causing event/command. Optional. |
| `actorType` | SELECT | `human` \| `agent` \| `system`. Optional. |
| `actorId` | TEXT | Optional. |
| `authority` | TEXT | Approving human where required. Optional. |
| `evidence` | RAW_JSON | Source references; mandatory when `actorType = system`. |
| `payload` | RAW_JSON (fallback TEXT) | Unvalidated at MVP. |
| `patientProgram` | RELATION (nullable) | → PatientProgram. Target for patient events. |
| `provider` | RELATION (nullable) | → Provider. |
| `clinic` | RELATION (nullable) | → Clinic. |

Twenty has no polymorphic relations: three nullable relations, exactly one populated. Patient events resolve (`entityRefSystem`, `entityRefId`) → Patient via crosswalk, then (Patient, `programCode`) → PatientProgram (created on first event for that pair).

## Immutability policy

DomainEvent records are never updated or deleted. Enforced by policy + Twenty role permissions (producers: create-only on DomainEvent), verified by the Snowflake mutation-audit view (CDC captures updates/deletes if they occur).

## Projection

### Lookup (v1.1)

| eventType | Target object | Field | Value |
|---|---|---|---|
| `patient.registered` | PatientProgram | `lifecycleStatus` | `registered` |
| `patient.enrolled` | PatientProgram | `lifecycleStatus` | `enrolled` |
| `patient.activated` | PatientProgram | `lifecycleStatus` | `activated` |
| `patient.qualified` | PatientProgram | `qualificationStatus` | `qualified` |
| `patient.disqualified` | PatientProgram | `qualificationStatus` | `disqualified` |
| `provider.credentialed` | Provider | `lifecycleStatus` | `credentialed` |
| `clinic.onboarded` | Clinic | `lifecycleStatus` | `onboarded` |

Lookup rows are generated from `state_catalog.yaml` (see state-catalog.md).

### Workflow: `project-domain-event`

Trigger: DomainEvent record created.

1. Resolve entity: match (`entityRefSystem`, `entityRefId`) to Patient/Provider/Clinic; patient events additionally resolve (Patient, `programCode`) → PatientProgram; set the relation.
2. Unresolved ref → leave relations empty (surfaces in Snowflake orphan view); stop.
3. LWW guard, per dimension: if `occurredAt` ≤ target's `<dimension>StatusAsOf`, stop (late event; history intact, state not regressed). Qualification events compare against `qualificationStatusAsOf`, lifecycle events against `lifecycleStatusAsOf`.
4. Apply: set status field per lookup; set the matching `...AsOf = occurredAt`.

### Workflow: `log-registration` (optional)

Trigger: Patient record created directly in UI/API (not via event). Creates a `patient.registered` DomainEvent so manual entries appear in the audit trail. Producer = `twenty-ui`.

## State dimensions

v1.1 = `lifecycleStatus` + `qualificationStatus` on PatientProgram; single `lifecycleStatus` on Provider/Clinic. Adding a dimension = new SELECT + `...AsOf` field pair + catalog rows. No migration.

## Access

| Actor | Mechanism | Permissions |
|---|---|---|
| Event producers | Single MCP write path (C3), per-actor API keys in Snowflake Secrets | Create DomainEvent only. |
| Projection workflows | Twenty workflow runtime | Update entity state fields; create DomainEvent (log-registration). |
| Ops/clinical staff | Microsoft SSO (Entra) | Read/write entities per role; state fields read-only (single-writer rule); read-only DomainEvent. |
| CDC service | Postgres replication user | Read-only on workspace schema. |

## Setup

Entire model provisioned by `setup/` scripts against the metadata API (idempotent, re-runnable). Order: objects → fields → relations → picklist values (from state catalog) → workflows → roles/API keys.
