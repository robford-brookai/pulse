# PULSE Event Envelope Specification

*PULSE: Patient Unified Ledger of State & Events.*

| | |
|---|---|
| **Status** | Draft v1 |
| **Date** | 2026-07-28 |
| **Owner** | Rob Ford, Data |
| **Audience** | Event producers (engineering, partner systems) |
| **Related** | twenty-data-model.md; snowflake-landing-spec.md; state-catalog.md; event-state-platform-solution.md |

This is the contract producers code against. It is platform-independent by design: the same envelope survives if the ingestion layer (currently Twenty) is ever replaced.

## Two vocabularies — do not conflate

| Vocabulary | Example | Source | Consumers |
|---|---|---|---|
| **Domain events** (this spec) | `patient.enrolled` | Producers, via API call | Audit trail, state projection, analytics |
| **CRUD notifications** | `patient.created` | Twenty plumbing, automatic | Webhook subscribers reacting to record changes |

A domain event is a business fact declared by an external actor. A CRUD notification is Twenty reporting a database write. Analytics and producers deal only in domain events.

## Envelope

```json
{
  "event_id": "018f3c2a-7b6e-7c4d-9a1b-2f3e4d5c6b7a",
  "event_type": "patient.enrolled",
  "entity_type": "patient",
  "entity_ref": {"system": "sfdc", "id": "003XX000012345"},
  "program": "diabetes-mgmt",
  "occurred_at": "2026-07-28T14:03:22Z",
  "producer": "enrollment-service",
  "schema_version": 1,
  "rule_version": "state_catalog@1",
  "correlation_id": "018f3c2a-0000-7c4d-9a1b-aaaaaaaaaaaa",
  "causation_id": null,
  "actor": {"type": "system", "id": "signal-adapter/billy", "authority": null},
  "evidence": [{"system": "billy", "ref": "row:8842107"}],
  "payload": {"cohort": "2026-Q3"}
}
```

### Field rules

| Field | Set by | Rules |
|---|---|---|
| `event_id` | Producer | UUID (v7 preferred). Idempotency key: retries MUST reuse the same value. Never reuse across distinct facts. |
| `event_type` | Producer | Must exist in the registry below. Lowercase, `noun.verb-past-tense`, dot-delimited. |
| `entity_type` | Producer | `patient` \| `provider` \| `clinic`. Must agree with the noun in `event_type`. |
| `entity_ref` | Producer | Either a known external system reference (`{"system": ..., "id": ...}`) or the canonical ID (`{"system": "brook", "id": ...}`). **Canonical patient identity = `DIM_PATIENT_CONFORMED` spine ID (TIDE); Twenty never mints patient identity** (write-ownership matrix rule 2). Registered systems: `brook` (spine), `sfdc`, `mrn`, `app`. |
| `program` | Producer | Program ID. **Required for patient events** — patient state grain is patient × program. Absent for provider/clinic events. |
| `occurred_at` | Producer | ISO 8601 UTC. Business time — when the fact became true, not when the call is made. Backdating allowed. |
| `recorded_at` | Server | Ingest time. Producers never send it. |
| `producer` | Server | Derived from the API key, never trusted from the body. |
| `schema_version` | Producer | Integer, currently `1`. Bumped only on breaking envelope changes. |
| `rule_version` | Producer | State catalog version in force (`state_catalog@N`). See state-catalog.md. |
| `correlation_id` | Producer (optional) | UUID tying one patient journey across systems and events. Unbackfillable later — send it from day one where known. |
| `causation_id` | Producer (optional) | `event_id` (or command ID) that directly caused this event. |
| `actor` | Producer (optional) | `{type: human\|agent\|system, id, authority}`. `authority` = approving human where the action required one. Foundation for agent-actor attribution. |
| `evidence` | Producer (optional) | Array of source references (`{system, ref}`) backing the declared fact. Mandatory for signal-adapter events (`actor.type = system`). |
| `payload` | Producer | JSON object. Schema-free at MVP — envelope is validated, payload is not. No PHI beyond what the event type requires. |

## Event type registry — v1.1 (derived from state catalog)

This registry is generated from `state_catalog.yaml` (see state-catalog.md); the table below is the human-readable rendering. Registry v1.1 seeds the catalog ratification exercise — the ratified catalog supersedes it.

| event_type | Entity | Projects to | Payload conventions |
|---|---|---|---|
| `patient.registered` | patient | `lifecycle_status = registered` | `source`, `referral_channel` |
| `patient.enrolled` | patient | `lifecycle_status = enrolled` | `program`, `cohort` |
| `patient.activated` | patient | `lifecycle_status = activated` | `activation_channel` |
| `patient.qualified` | patient | `qualification_status = qualified` | **Enforced schema**: `rule_version`, `criteria_met[]`, `clinic_ref`, `evaluated_at`. Producer: `clinic-rules-engine` only. |
| `patient.disqualified` | patient | `qualification_status = disqualified` | **Enforced schema**: `rule_version`, `criteria_failed[]`, `clinic_ref`, `evaluated_at`. Producer: `clinic-rules-engine` only. |
| `provider.credentialed` | provider | `lifecycle_status = credentialed` | `credential_type`, `expires_at` |
| `clinic.onboarded` | clinic | `lifecycle_status = onboarded` | `go_live_date` |

Derived events (`patient.qualified`/`patient.disqualified`) are emitted only by the clinic rules engine (see clinic-rules-engine.md); other producers must not send them.

### Adding an event type

1. PR against `state_catalog.yaml` (state, class, event type, projection target, payload conventions).
2. CI regenerates Twenty picklist values + projection mapping and the Snowflake dbt seeds.
3. Producers may send once merged. No schema migration, no deploy.

## Transport (current implementation: single MCP write path → Twenty)

Per compliance control C3 (conformance memo 2026-07-23): **all programmatic Twenty writes flow through one MCP service** co-located in the SPCS deployment. Producers do not call Twenty REST directly. Per-actor API keys live in Snowflake Secrets; every mutation is attributable. The logical envelope above is what producers submit to the write path; the REST encoding is the write path's concern.

```bash
curl -X POST "https://twenty.internal.brook/rest/domainEvents" \
  -H "Authorization: Bearer $PRODUCER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "eventId": "018f3c2a-7b6e-7c4d-9a1b-2f3e4d5c6b7a",
    "eventType": "patient.enrolled",
    "entityType": "patient",
    "entityRefSystem": "sfdc",
    "entityRefId": "003XX000012345",
    "occurredAt": "2026-07-28T14:03:22Z",
    "schemaVersion": 1,
    "payload": "{\"program\": \"diabetes-mgmt\", \"cohort\": \"2026-Q3\"}"
  }'
```

Notes:

1. Field names flatten to Twenty's camelCase custom-object fields; `entity_ref` splits into `entityRefSystem` + `entityRefId`. The logical envelope above is canonical; transport encoding may change without a version bump.
2. One API key per producer. Keys identify the producer — never share across systems.
3. Success = HTTP 201 with the created record. Retry on 5xx/timeouts with the same `event_id`.

## Idempotency and ordering

- **Duplicates**: uniqueness of `event_id` is by convention at ingest; enforcement happens downstream (Snowflake dedupe keeps earliest `recorded_at`). Producers retrying with the same `event_id` are safe.
- **Ordering**: state projection is last-write-wins by `occurred_at` (tiebreak `recorded_at`). Out-of-order and late arrivals are accepted and surfaced in the Snowflake quality views, never rejected.
- **Invalid transitions** (e.g., `patient.activated` before `patient.registered`): accepted at ingest, flagged in Snowflake. API-side rejection is deliberately deferred.

## Non-goals (v1)

Payload schema enforcement (except derived events), producer-facing read API for state (use Twenty UI/API directly), event replay tooling, outbound event subscriptions beyond Twenty webhooks.
