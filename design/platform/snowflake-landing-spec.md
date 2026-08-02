# Snowflake Landing Specification — PULSE (Patient Unified Ledger of State & Events)

| | |
|---|---|
| **Status** | Draft v1 |
| **Date** | 2026-07-28 |
| **Owner** | Rob Ford, Data |
| **Related** | event-envelope-spec.md; twenty-data-model.md; state-catalog.md |

Snowflake is the analytical and verification layer: complete event history, independently derived state, and the quality checks deliberately kept out of the ingest path (dedupe, transition validation, orphan detection).

## Pipeline

Twenty Postgres (workspace schema: `domainEvent`, `patient`, `patientProgram`, `provider`, `clinic` tables) → CDC → Snowflake.

- **Tool**: Fivetran or Airbyte, Postgres logical-replication connector, read-only replication user (per data-model access table). Choose whichever is already in the stack; no new tooling for this alone.
- **Capture mode**: soft-mutation capture on (updates/deletes recorded, not overwritten) — required by the mutation audit below.
- **Frequency**: 15-minute sync. Volume (low thousands/day) is negligible at any frequency.

### Freshness tiers (context: `py-data` hourly is too slow for operating surfaces)

| Source | Path | Freshness |
|---|---|---|
| mdba collections (clinic rules, condition/coverage inputs) | `streamline` (proven SPCS pipeline, mdba → sf) | ~seconds |
| Twenty Postgres (events, entities) | CDC connector | ~15 min |
| Other sources | `py-data` ELT | ~hourly |

Rule of thumb: anything feeding qualification or an operating surface (sig-dash) that already lives in mdba goes on `streamline`; Twenty data rides CDC; `py-data` hourly is acceptable only for non-operational inputs. Sigma queries Snowflake live, so dashboard freshness equals the slowest contributing source — keep sig-dash marts on streamline/CDC-fed tables. If the 15-min CDC leg becomes the bottleneck, shorten connector sync first, streaming CDC second.

## Layers

```
RAW_TWENTY   -- CDC mirror, untouched
STG_EVENTS   -- typed, deduped, conformed
MART_STATE   -- derived state, reconciliation, quality views
```

### RAW_TWENTY

Connector-managed mirror of the workspace tables plus CDC metadata columns (`_synced_at`, `_deleted`). Never queried directly by consumers.

### STG_EVENTS.EVENTS

```sql
CREATE OR REPLACE VIEW STG_EVENTS.EVENTS AS
SELECT
    event_id,
    event_type,
    entity_type,
    entity_ref_system,
    entity_ref_id,
    coalesce(canonical_patient_id, provider_id, clinic_id) AS entity_id,  -- spine ID for patients
    program_code,
    occurred_at,
    created_at            AS recorded_at,
    producer,
    schema_version,
    rule_version,
    correlation_id,
    causation_id,
    actor_type, actor_id, authority,
    try_parse_json(evidence) AS evidence,
    try_parse_json(payload)  AS payload
FROM RAW_TWENTY.DOMAIN_EVENT
WHERE NOT _deleted
QUALIFY row_number() OVER (
    PARTITION BY event_id
    ORDER BY created_at ASC          -- dedupe: keep earliest arrival
) = 1;
```

Entity dimension views (`STG_EVENTS.PATIENTS`, `STG_EVENTS.PATIENT_PROGRAMS`, etc.) conform the entity tables analogously.

### MART_STATE

**Derived state** — the independent fold over events, computed with the same LWW rule as the Twenty projection:

```sql
CREATE OR REPLACE VIEW MART_STATE.ENTITY_STATE_DERIVED AS
SELECT
    e.entity_type,
    e.entity_id,                       -- canonical spine ID for patients
    e.program_code,                    -- null for provider/clinic
    r.state_dimension,                 -- lifecycle_status | qualification_status
    r.state_value,
    e.occurred_at AS status_as_of,
    e.event_id    AS from_event
FROM STG_EVENTS.EVENTS e
JOIN MART_STATE.REF_EVENT_REGISTRY r ON r.event_type = e.event_type
WHERE e.entity_id IS NOT NULL
QUALIFY row_number() OVER (
    -- patient grain is patient × program; program_code null-safe for provider/clinic
    PARTITION BY e.entity_type, e.entity_id, e.program_code, r.state_dimension
    ORDER BY e.occurred_at DESC, e.recorded_at DESC
) = 1;
```

**Reconciliation** — derived state vs. what Twenty shows:

```sql
CREATE OR REPLACE VIEW MART_STATE.STATE_RECONCILIATION AS
SELECT d.entity_type, d.entity_id, d.program_code, d.state_dimension,
       d.state_value          AS derived_status,
       t.state_value          AS twenty_status,
       d.status_as_of, t.status_as_of AS twenty_status_as_of
FROM MART_STATE.ENTITY_STATE_DERIVED d
JOIN STG_EVENTS.ALL_ENTITY_STATES t
  USING (entity_type, entity_id, program_code, state_dimension)
WHERE NOT equal_null(d.state_value, t.state_value);
```

Zero rows = healthy. Nonzero = projection workflow bug or manual state edit in the UI; investigate, then correct via a new event, not a state edit.

## Quality views (all in MART_STATE)

| View | Flags | Rule |
|---|---|---|
| `Q_DUPLICATE_EVENTS` | Same `event_id`, >1 arrival | Informational; STG already dedupes. |
| `Q_INVALID_TRANSITIONS` | Sequence violates transition table | Join event pairs per entity and dimension against `REF_VALID_TRANSITIONS` (seeded: lifecycle registered→enrolled→activated, provider/clinic single-step; qualification pending→qualified, pending→disqualified, qualified↔disqualified). Feeds the analysis that will define enforcement. |
| `Q_OUT_OF_ORDER` | `occurred_at` order ≠ `recorded_at` order per entity | Late/backdated arrivals; expected occasionally. |
| `Q_UNKNOWN_EVENT_TYPES` | `event_type` not in `REF_EVENT_REGISTRY` | Should be impossible via picklist; catches drift. |
| `Q_ORPHAN_EVENTS` | All three entity relations null | Unresolved `entity_ref` at ingest; needs registry fix + event re-link. |
| `Q_EVENT_MUTATIONS` | Update/delete CDC records on DOMAIN_EVENT | Must be empty — immutability policy violation. |

`REF_EVENT_REGISTRY` and `REF_VALID_TRANSITIONS` are **dbt seeds generated from `state_catalog.yaml`** (see state-catalog.md) — one catalog PR regenerates both plus the Twenty picklists/lookup. Per the migration program's regime, quality views graduate to dbt tests with Datadog alerting as the dbt project stands up; the view definitions here are the test logic.

## Materialization and cost

Views throughout at MVP volume (low thousands of events/day). If reconciliation queries ever feel slow, convert MART_STATE to dynamic tables with 1-hour target lag. Storage is megabytes; compute fits existing warehouse spend. No dedicated warehouse.

## Alerting (minimal)

Daily task: if `STATE_RECONCILIATION`, `Q_EVENT_MUTATIONS`, or `Q_ORPHAN_EVENTS` is nonempty → notification (email/Slack via existing alerting). Everything else is reviewed ad hoc.

## Non-goals (v1)

Streaming ingest for the Twenty leg (Snowpipe/Kafka), event replay from Snowflake back into Twenty (except the clinic-rules emitter), row-level PHI masking beyond existing account policies.
