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

**Known gap — replay classification is not yet end-to-end.** `pulse_ledger.api` does not accept
an `idempotency_key` body field (rejected as unknown) and never echoes `replayed` in the
`POST /commands` response; the app's committer calls `commit_declaration` rather than
`commit_idempotent`. `PulseCoreClient` already sends the D16 key and reads `replayed` (defaulting
`False`), so today every replay classifies as `committed`. The commit path itself
(`pulse_ledger.idempotency.commit_idempotent`) fully supports both. Flagged independently by
tasks 4.3 and 5.3 of `pulse-ledger-core`; tracked as **DNA-801** (see ADR-0003, Consequences).
Do not depend on the `replayed` classification, and do not send `idempotency_key` over HTTP,
until DNA-801 lands.

Retired with the transport change: the `ocean.<domain>` topics, the `ocean.warehouse-dlq` topic
(each consumer now has its own SQS dead-letter queue), and the Redpanda Connect warehouse sink
(the warehouse path is an ordinary rule-and-queue consumer).

A new `event_type` within an existing domain needs no rule change; a new **domain** is an
addition to the catalog table, regenerated and reviewed here.
