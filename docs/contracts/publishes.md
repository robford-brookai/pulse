# Publishes

What this repo exposes to other repos and teams. Anything not listed here is an implementation
detail and may change without notice.

Cross-repo integration happens through this document — a published Snowflake object, an API, or
a released package. **Never integrate by cloning another repo into this one.** A side-clone
couples you to someone else's implementation details and to their refactors.

Record each entry with enough detail that a consumer can depend on it without reading the code:

| Surface | Kind | Stability | Notes |
|---|---|---|---|
| _e.g._ `ANALYTICS.DIM_PATIENT` | Snowflake view | stable | grain: one row per patient; PHI — access via role `ANALYST_PHI` |
| _e.g._ `GET /v1/encounters` | REST API | beta | paginated; contract in `docs/api/encounters.yaml` |

## This repo

pulse publishes the OCEAN event distribution surfaces, absorbed as `packages/ocean`
([ADR-0002](../adr/ADR-0002-ocean-absorption-and-eventbridge-transport.md)). The transport is
**EventBridge**: the former `ocean.<domain>` Kafka topics are retired, and a consumer integrates
by attaching an EventBridge rule and its own SQS queue — never by subscribing to a topic.

| Surface | Kind | Stability | Notes |
|---|---|---|---|
| `ocean` event bus | EventBridge bus | stable | events address as `source = "ocean"`, `detail-type = "<domain>"`; the envelope crosses whole in `detail`, unmodified — `event_type` stays an envelope field, never promoted to `detail-type` |
| Domain catalog | generated mapping | stable | eleven live domains: `signals`, `alerts`, `tasks`, `interactions`, `outcomes`, `patient-state`, `tickets`, `ai-ops`, `audit`, `ops`, `logistics`; source table is `packages/ocean/libs/ocean-broker/src/ocean_broker/catalog.py`, from which publisher addressing and Terraform rule patterns both generate |
| `STREAMLINE.OCEAN_RAW.EVENTS` | Snowflake table | stable | grain: one row per envelope `event_id`; `data` is the envelope as VARIANT, `_topic` records the originating domain; append-only — redelivery never updates or duplicates a row |

### Ledger command and read surfaces (`pulse-ledger-core`, DNA-784)

The ledger's write path is one HTTP command API (`packages/pulse-ledger`), consumed through the
client SDK `packages/pulse-core` ([ADR-0003](../adr/ADR-0003-ledger-core-write-path.md)). Writers
integrate through `pulse_core`, never by writing `ledger.*` tables — the schema REVOKEs
UPDATE/DELETE on `events` and the API is the single writer.

| Surface | Kind | Stability | Notes |
|---|---|---|---|
| `POST /commands` | REST API | beta | single command; write-time catalog legality, rejection carries reason + `catalog_version`; actor derived from the bearer credential, body actor fields rejected (D15) |
| `POST /commands:batch` | REST API | beta | backfill mode, same validation; `backfill_genesis`/`reconstruction_gap` accepted only from the backfill actor |
| `PUT/GET /writers/{writer_id}/cursor` | REST API | beta | durable writer cursors, opaque JSON; a credential may touch only its own `writer_id`; path template in `pulse_core.cursor` |
| `pulse_core` (client SDK) | workspace package | beta | `PulseCoreClient.submit_command` classifies `committed \| replayed \| rejected \| transient`, retries transient only; `consume(handler)` is the SQS consumer convention (`event_id` dedupe, delete-after-success); D16 key derivation in `pulse_core.idempotency` |
| `pulse_ledger.reads` / `.identity` / `.review` | library read surface | beta | in-process reads over the ledger Postgres: `enumerate_state` (co-committed `ledger.current_state`, catalog-validated states), `lookup_identifier`/`find_candidates` (identity, digests only — never demographics), `list_review_queue`/`resolve_review` (`ledger.review_queue` quarantine). No HTTP read routes shipped in S1.1 |

Replay classification is end-to-end (DNA-801): `POST /commands` and `POST /commands:batch` accept
an optional `idempotency_key` body field, thread it to `commit_idempotent`, and every commit
response carries `replayed` — a repeated key returns the original event with `"replayed": true`
and writes nothing. A keyless body still commits as a fresh event.

Retired with the transport change: the `ocean.<domain>` topics, the `ocean.warehouse-dlq` topic
(each consumer now has its own SQS dead-letter queue), and the Redpanda Connect warehouse sink
(the warehouse path is an ordinary rule-and-queue consumer).

A new `event_type` within an existing domain needs no rule change; a new **domain** is an
addition to the catalog table, regenerated and reviewed here.
