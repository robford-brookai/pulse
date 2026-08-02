## Context

See `proposal.md` — Why. Current state, verified against `robford-brookai/ocean` at `7bc9d2c`:

- **Transport**: Redpanda locally (`infra/redpanda/`), MSK Serverless on AWS
  (`infra/terraform/modules/msk-ocean/`). 12 topics, all created with 3 partitions
  (`infra/redpanda/topics.sh`).
- **Publishing**: no shared emit library. `libs/ocean-broker` exports only `build_producer_config`
  and `build_consumer_config`; each service carries its own `publish()`. Two shapes exist: six
  connectors publish keyed with a Postgres `failed_webhooks` DLQ fallback on `KafkaException`, and
  six services publish unkeyed JSON via a `run_in_executor` wrapper with no DLQ.
- **Consuming**: 7 consumers, all long-running EKS processes with `enable.auto.commit: False` and a
  commit-after-successful-processing loop. That shape maps cleanly onto SQS receive → process →
  delete, which is why this migration is a poll-loop swap rather than a rearchitecture.
- **Ordering today**: Kafka gives per-partition ordering. Only the six connector publishers pass a
  key, so only their topics have a meaningful partition assignment; the other six publish unkeyed
  and are already effectively unordered across three partitions.

That last point matters more than it first appears, and §Decisions D3 turns on it.

## Goals / Non-Goals

**Goals:**

- One transport. No dual-bus period, no compatibility shim, no `if TRANSPORT ==` branch surviving
  the change.
- A generated topic → `(source, detail-type)` contract that producers and rules both derive from,
  so a rule can never drift from what a producer emits.
- An explicit, evidence-backed ordering verdict per consumer, recorded before that consumer is
  converted.
- Behavioral equivalence provable by the existing simulators, not by inspection.

**Non-Goals:**

- Changing what any consumer *means*. Semantics stay fixed so that the LocalStack equivalence gate
  is a real test. ADR §6.2's migration M1 is the counterexample and is excluded for exactly this
  reason.
- Consolidating the two publisher shapes' *call sites*. They converge on one library; their
  per-service payload construction is left alone to keep each conversion reviewable.
- Partition-count or throughput tuning. PRM volume is orders of magnitude below any relevant limit.

## Decisions

### D1 — Topic → (source, detail-type) mapping

`ocean.<domain>` collapses onto EventBridge's two-part addressing as a **constant source with the
domain in detail-type**:

| Kafka topic | `source` | `detail-type` |
|---|---|---|
| `ocean.signals` | `ocean` | `signals` |
| `ocean.alerts` | `ocean` | `alerts` |
| `ocean.tasks` | `ocean` | `tasks` |
| `ocean.interactions` | `ocean` | `interactions` |
| `ocean.outcomes` | `ocean` | `outcomes` |
| `ocean.patient-state` | `ocean` | `patient-state` |
| `ocean.tickets` | `ocean` | `tickets` |
| `ocean.ai-ops` | `ocean` | `ai-ops` |
| `ocean.audit` | `ocean` | `audit` |
| `ocean.ops` | `ocean` | `ops` |
| `ocean.logistics` | `ocean` | `logistics` |
| `ocean.warehouse-dlq` | — | — (retired, see D6) |

Chosen over the alternative of `source = ocean.<domain>` with `detail-type = <event_type>`. That
alternative reads more idiomatic and was rejected on two grounds. First, it makes every rule match
on `source` prefix, and EventBridge patterns do not support prefix matching on `source` without
listing every value — so adding a domain would mean editing every rule. Second, it couples rule
definitions to the `event_type` vocabulary, which the state catalog generates and will keep
changing; `detail-type` must stay stable across catalog revisions. Keeping `event_type` inside
`detail` preserves ADR §4.2's envelope unchanged, which is the point of V9's restatement.

**This is a generated surface.** The mapping is emitted from one source table into both the
publisher's addressing and the Terraform rule patterns. It is `serial_lane_always:
catalog_generated_surfaces` — the task that establishes it runs alone, and nothing downstream
dispatches until it merges.

The envelope itself is unchanged and travels whole in EventBridge `detail`. ADR §4.2 and §4.5 were
always written against an unordered at-least-once bus, so no envelope field moves.

### D2 — One rule, one queue, one consumer

Each of the 7 consumers gets a dedicated rule matched on its `detail-type` set, targeting a
dedicated SQS queue, with a per-queue DLQ and redrive policy. Competing-consumer semantics within a
service come from multiple pollers on the same queue — the same shape a Kafka consumer group gave.

Rejected: one shared queue with client-side filtering (throws away EventBridge's routing and makes
every consumer pay for every event), and Lambda targets (the 7 consumers are long-running EKS
processes holding DB pools; converting them to functions is a rearchitecture this change explicitly
is not).

The `enable.auto.commit: False` + commit-after-success loop becomes receive → process → delete,
with the message left to visibility-timeout expiry on failure. This preserves today's semantics
exactly: both are at-least-once with redelivery on failure.

### D3 — Ordering: sequence guards, not FIFO

**The audit.** Every consumer was read at `7bc9d2c`. Verdicts:

| Consumer | Verdict | Evidence |
|---|---|---|
| `event-store` | **Order-tolerant** | Append-only; `writer.py:48` `ON CONFLICT (event_id) DO NOTHING`. Order cannot affect the result. |
| `warehouse-sync` | **Order-tolerant** | Bulk insert into a raw events table. |
| `agent-worker` | **Order-tolerant** | Handles one event type (`task.created`) from one source; no cross-event lifecycle. Carries a separate at-least-once duplicate hazard (`claimed_tasks` is a per-process set, so competitive claim is not safe across replicas) — that hazard exists on Kafka today and is out of scope. |
| `call-simulator` | **Order-tolerant** | Single topic, single dispatch per approval event. |
| `control-plane` | **Order-tolerant, per handler** | `dispatch()` routes by `event_type` to independent handlers and re-publishes; no handler reads state written by another. To be re-confirmed per handler during conversion. |
| `graph-projection` | **MIXED — not order-tolerant** | See below. |
| `slack-bot` | **ORDER-DEPENDENT** | Drives entity lifecycles (`ticket_created` → `updated` → `resolved`; `rma_created` → `status` → `failed`) via `chat_update` on a stored message ts. A reordered pair leaves the wrong terminal text in Slack, and a Slack side effect is not undone by a later event. |

`graph-projection` is the finding that matters, because the assumption going in was that its
`ON CONFLICT … DO UPDATE` handlers were already order-tolerant. Seven of its twelve upsert sites
are, guarded by a monotonic predicate — `alerts.py:57`, `tasks.py:33`, `logistics.py:43` and `:85`,
`ops.py:33` and `:67`, `tickets.py:39`, `signals.py:31`. Five are not:

- `interactions.py:36` and `:72`, `logistics.py:125` — guarded by
  `last_event_id IS DISTINCT FROM EXCLUDED.last_event_id`. That is **deduplication, not ordering**.
  It suppresses a repeat of the same event and does nothing to stop an older event overwriting a
  newer one.
- `signals.py:59` — unguarded `DO UPDATE SET anomalous = true`. Monotonic in practice (it only ever
  sets true), so harmless, but unguarded by construction rather than by intent.
- `outcomes.py:44` and `:103` — unguarded, and the worst case in the audit. The two sites set
  `outcome = 'completed'` and `outcome = 'missed'` on the same `interaction_id` with no predicate.
  Under reordering a completed call is silently rewritten to missed. Worse, both write
  `completed_at = :now` — wall-clock at processing time, not event time — so adding a naive
  `completed_at <` guard would compare processing order and re-encode the bug.

**Decision: sequence guards in the consumer, not FIFO queues.** For each unguarded or dedup-only
site, add a monotonic predicate on an event-time field carried in the envelope — never on a
processing-time value. Where no such field exists on the row, add one.

FIFO was rejected on a hard platform constraint, verified 2026-08-01: an EventBridge **rule**
targeting an SQS FIFO queue takes a **static** `MessageGroupId` per target, with no expression over
the event body. Every event through that rule lands in one message group, which serializes the
entire consumer — trading a correctness bug for a throughput ceiling and still not giving
per-entity ordering, which is the only ordering anyone actually wants. Achieving dynamic
`MessageGroupId` requires an **EventBridge Pipe** in front of the FIFO queue: an extra hop, extra
cost, and extra failure surface per consumer. (SQS *fair* queues do accept a JSON-path
`MessageGroupId`, but fair queues provide noisy-neighbor isolation on standard queues, not FIFO
ordering — they do not solve this.)

Sequence guards are also the doctrinally correct answer: ADR §4.5 already states that delivery is
unordered and consumers order on `(subject_id, ledger_seq)`. Guarding in the consumer is that rule
applied to the absorbed services.

`slack-bot` is the one consumer a guard does not fully save, because its side effect is external.
Its conversion carries a sequence guard on the stored message record so a stale update is dropped
rather than applied — the update is skipped, not reordered. Losing a late-arriving stale update is
correct; applying it is not.

### D4 — Shared publisher

`libs/ocean-broker` becomes `EventBridgePublisher` with a single `publish(detail_type, event, key)`
entry point that resolves `source` and `detail-type` from the D1 mapping. Both existing shapes
converge on it. The six connectors' Postgres `failed_webhooks` DLQ fallback is **kept** — it
catches publish-side failures, which no amount of bus-side DLQ can, and it survives the transport
change untouched. The six unkeyed publishers gain the same fallback by inheriting the shared
implementation; that is a strict improvement and is called out per task so it is not mistaken for
scope creep.

`key` remains in the signature and travels as an envelope field. It no longer selects a partition,
but it is what the D3 sequence guards group by.

### D5 — LocalStack for local dev

LocalStack replaces `redpanda`, `redpanda-console` and `redpanda-init` in
`infra/docker-compose.yml`. `infra/redpanda/topics.sh` is replaced by a bus/rule/queue creation
script driven by the same D1 mapping table, so local and AWS topology cannot drift.

### D6 — Warehouse path

`infra/redpanda/connect.yaml` (Redpanda Connect → Snowflake, dead-lettering to
`ocean.warehouse-dlq`) is replaced by **an SQS consumer inside `warehouse-sync`**, not by
Firehose → S3 → Snowpipe.

Rationale: `warehouse-sync` already exists, already holds a Snowflake connection, and already
contains a `Producer` for DLQ writes plus an `AIOConsumer` — the Firehose path would introduce two
new AWS services and an S3 staging layer to replace a component that is already running. It also
keeps the dead-letter path in one place (D2's per-queue DLQ) instead of splitting it across a
Firehose error prefix and an SQS DLQ. The `ocean.warehouse-dlq` topic retires with the
`warehouse-sync` queue's own DLQ taking its role.

Revisit if warehouse volume ever makes per-message SQS delivery the cost driver — Firehose batching
wins at high volume, and at PRM volume it does not.

## Risks / Trade-offs

- **A sequence guard is added to a site the audit called order-tolerant, or missed at one it did
  not** → The LocalStack equivalence gate is the backstop, but a simulator run will not naturally
  produce reordering. Each order-dependent conversion ships with a test that delivers its events
  *out of order* and asserts the final state matches in-order delivery. That test is the task's
  definition of done, not the simulator.
- **`outcomes.py`'s `completed_at = :now` invites a wrong fix** → The guard must use an event-time
  field. Called out explicitly in that task's work order; a `completed_at` guard is a review-reject.
- **No dual-bus period means a bad cutover is visible in production** → Waves 0–3 land before MSK
  teardown, so revert restores the Kafka path (proposal — Rollback). Teardown is a separate
  `destructive_ops` item gated on the equivalence run.
- **LocalStack's EventBridge/SQS fidelity is not AWS's** → It validates wiring and consumer logic,
  not IAM, quotas, or delivery-latency behavior. Rule-pattern correctness is additionally asserted
  against the D1 table in a unit test, so a LocalStack quirk cannot mask a wrong pattern.
- **13 publish sites and 7 consumers is a large blast radius for one change** → Waves, one commit
  per site, and per-consumer revertibility. The alternative — splitting into several OpenSpec
  changes — was rejected because a partial migration means a dual bus, which is the state this
  change exists to avoid.
- **The `.env` tracked in the source repo** → Credentials rotate before import (ADR §6.1). A
  history rewrite does not revoke what the source repo's history already exposed, and archiving
  does not either.

## Migration Plan

Waves, gated on dependencies merging. Wave numbering is the dispatch order.

- **Wave 0** (serial, alone) — filtered import to `packages/ocean` per ADR §6.1. Touches workspace
  roots → `serial_lane_always`.
- **Wave 1** (serial) — the D1 mapping table (generated surface, alone), then the shared
  `EventBridgePublisher`. Everything downstream depends on both.
- **Wave 2** (parallel) — 13 publish-site conversions and 7 consumer conversions. Order-dependent
  consumers carry their D3 guard and its out-of-order test in the same commit.
- **Wave 3** — IaC: delete `infra/terraform/modules/msk-ocean/`, add bus, per-consumer rule and
  queue, per-queue DLQ and redrive, archive with retention. LocalStack into
  `infra/docker-compose.yml`.
- **Wave 4** — warehouse path per D6.

Then, outside the Orca lane: the equivalence run, `terraform apply`, MSK teardown, and the source
repo archive — all `destructive_ops`, all behind G_APPROVAL.

Rollback: see `proposal.md` — Rollback.

## Open Questions

- Archive retention period. EventBridge archive covers ADR §4.6's short-horizon convenience replay
  only; the 6-year durable record is `audit_log`. Any value from 30 to 90 days satisfies the
  requirement, so the number can be set at Wave 3 without disturbing specs or tasks.
- Whether `control-plane`'s per-handler re-confirmation (D3) upgrades any handler to
  order-dependent. If one does, it takes the same guard-plus-test treatment as the others — the
  approach and task shape are already defined, only the count changes.

Sources for the FIFO constraint in D3:

- [SqsParameters — Amazon EventBridge API Reference](https://docs.aws.amazon.com/eventbridge/latest/APIReference/API_SqsParameters.html)
- [Set an SQS FIFO queue's message group ID with an EventBridge Pipe — Serverless Land](https://serverlessland.com/patterns/eventbridge-pipes-dynamic-message-group-id)
- [Amazon EventBridge now supports targeting SQS fair queues — AWS](https://aws.amazon.com/about-aws/whats-new/2025/11/amazon-eventbridge-sqs-fair-queue-targets/)
