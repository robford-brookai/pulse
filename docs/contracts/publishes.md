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

Retired with the transport change: the `ocean.<domain>` topics, the `ocean.warehouse-dlq` topic
(each consumer now has its own SQS dead-letter queue), and the Redpanda Connect warehouse sink
(the warehouse path is an ordinary rule-and-queue consumer).

A new `event_type` within an existing domain needs no rule change; a new **domain** is an
addition to the catalog table, regenerated and reviewed here.
