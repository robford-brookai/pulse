## Why

The OCEAN absorption ADR (`design/migration/ocean-to-pulse-adaptation-plan.md`) names EventBridge
as the PULSE event backbone in thirteen places. The 2026-08-01 reconciliation against
`robford-brookai/ocean` at `7bc9d2c` found no EventBridge anywhere in the repo: the backbone is
Kafka — Redpanda in local dev, MSK Serverless on AWS via `infra/terraform/modules/msk-ocean/`.
That contradiction (§9 verification item V3) blocked sign-off on the ADR, because §4.1 kept the bus
as "keep — the backbone was never the problem" while describing a bus OCEAN does not run.

Decision (Ford, 2026-08-01, ADR §9.1): retire Kafka entirely and move every bus-touching OCEAN
service to EventBridge, rather than run two buses or keep MSK. Two things decided it. **Cost** —
MSK Serverless bills $0.75/cluster-hour, roughly $547/month before a single event, against
EventBridge's $1.00 per million; break-even sits near 580M events/month, orders of magnitude above
PRM volume. **Capabilities already assumed** — ADR §1.4's per-target DLQ with backoff retry and
§4.6's archive replay are EventBridge-native and absent from OCEAN's Kafka setup, so keeping Kafka
meant building both. Replay was not the decider: it is roughly neutral, and a 6-year durable record
already exists in the append-only `audit_log`.

The decision is made. This change executes it. It is taken knowing it rewrites working non-PULSE
services and adds scope the ADR did not budget.

## What Changes

- **BREAKING** — Kafka is removed as a transport. All 13 publish sites and 7 consumers move to
  EventBridge → SQS. There is one cutover per consumer, not a window with both transports live.
- OCEAN's code is imported into PULSE as workspace package `packages/ocean` **first**, via
  `git-filter-repo` with a path allowlist (ADR §6.1). All refactoring happens in `packages/ocean`,
  never in the source repo.
- A topic → `(source, detail-type)` mapping is fixed for the 12 `ocean.*` topics in
  `infra/redpanda/topics.sh`. This is a generated-surface contract: it pins how every producer
  addresses the bus and how every rule matches.
- `libs/ocean-broker` stops exporting Kafka config builders and becomes a shared
  `EventBridgePublisher`. This closes verification item V5 as a side effect — today there is no
  shared emit library and each service carries a duplicated `publish()`.
- Each consumer gets one EventBridge rule and one SQS queue, with a DLQ and redrive policy per
  queue. Consumer process shape, Dockerfiles, and EKS deployments are unchanged: the poll loop
  swaps `confluent_kafka` subscribe for SQS receive/delete.
- Every consumer receives an explicit **ordering verdict** before conversion. Kafka gave
  per-partition ordering by key; SQS standard queues do not. Order-dependent consumers go SQS FIFO
  or gain a sequence guard. No consumer is converted on an assumption that it is order-tolerant.
- Local dev replaces the three Redpanda containers (`redpanda`, `redpanda-console`,
  `redpanda-init`) and `infra/redpanda/topics.sh` with LocalStack and bus/rule/queue creation.
- An EventBridge archive with retention replaces the absent replay tooling (V8), supplying the
  convenience-replay path ADR §4.6 assumes.
- The warehouse path moves off Redpanda Connect (`infra/redpanda/connect.yaml`, which ships to
  Snowflake with an `ocean.warehouse-dlq` topic). Its replacement is settled in design.

**Not in this change:** the live patient-state derivation in `graph-projection` (ADR §6.2, named
migration M1 — it changes consumer semantics, and this change must not); PULSE's own ledger, outbox
and projection consumers (greenfield, EventBridge by construction); the `workflow:*`,
`workflow:lint` and `linear:sync` Taskfile targets.

## Capabilities

`openspec/specs/` is empty — this is the first change in the repo, so every capability is new.

### New Capabilities

- `ocean-package-absorption`: the filtered import of `robford-brookai/ocean` into
  `packages/ocean` — allowlist contents, history preservation, exclusion of agent state and
  side-clones, and the credential-rotation precondition.
- `event-transport`: the bus-side contract — the topic → `(source, detail-type)` mapping, the
  envelope on the wire, the shared publisher's publish and failure semantics, and the retained
  Postgres `failed_webhooks` DLQ fallback.
- `event-delivery`: the consumer-side contract — one rule and one SQS queue per consumer, the
  per-consumer ordering verdict and what each verdict obliges, idempotency, DLQ and redrive, and
  archive replay.
- `local-event-stack`: LocalStack parity for local dev — what the local stack must provide so a
  simulation run reaches the same state it reaches against AWS.
- `warehouse-event-sync`: delivery of events to Snowflake after Redpanda Connect is removed,
  including dead-letter behavior.

### Modified Capabilities

None — the spec baseline is empty.

## Impact

**Code** (paths relative to `packages/ocean` after import):

- `libs/ocean-broker/src/ocean_broker/config.py` — replaced by the shared publisher.
- 13 publish sites, in two shapes. Seven `services/*/src/producer.py` (control-plane, github-,
  hubspot-, impilo-, linear-, pocar-, zcc-connector), five `services/*/src/publisher.py`
  (agent-worker, call-simulator, mongodb-connector, sim-driver, slack-bot), and one inline
  `Producer` in `services/warehouse-sync/src/main.py`. **A `services/*/src/producer.py` glob finds
  only 7 of the 13** — the rest are named `publisher.py` or are inline.
- 7 consumers. Six `services/*/src/consumer.py` (agent-worker, call-simulator, control-plane,
  event-store, graph-projection, slack-bot) plus an `AIOConsumer` inline in
  `services/warehouse-sync/src/main.py`. **A `services/*/src/consumer.py` glob finds only 6.**
- `infra/terraform/modules/msk-ocean/` — deleted. New bus, rules, queues, DLQs, archive.
- `infra/docker-compose.yml`, `infra/redpanda/topics.sh`, `infra/redpanda/connect.yaml`.

**Dependencies:** `confluent_kafka` removed; `boto3`/`aiobotocore` and LocalStack added.

**Systems:** MSK Serverless torn down. `robford-brookai/ocean` archived read-only with ADR §7's
supersession notice as its final commit.

**Lane split (WORKFLOW.md v2).** The import and all code work are `repo_change` (Orca worktrees).
`terraform apply`, the MSK teardown, and the source-repo archive are `destructive_ops` — no
reviewable diff exists for them. They run on the Open Engine queue (team CCC) as operator runbooks
with agent-prepared scripts, G_APPROVAL mandatory, and are excluded from `dispatch`, `execute`, and
`merge`. They must never enter the DNA dispatch queue.

## Rollback

Rollback is per-consumer and time-boxed, not global. Each consumer conversion is one commit that
swaps its poll loop; reverting that commit restores the Kafka consumer, which is why MSK teardown
is sequenced last and gated separately.

- **Before MSK teardown** (through Wave 3): revert the offending consumer or producer commit. MSK
  and the Redpanda topics still exist, so the reverted service rejoins the Kafka path. Mixed mode
  is degraded, not safe — events published to EventBridge do not reach a reverted Kafka consumer,
  so a revert is a stop-the-line signal, not a steady state.
- **After MSK teardown**: no transport rollback exists. Recovery is forward — fix, redeploy, and
  replay from the EventBridge archive to re-drive the affected consumer. This is why teardown is a
  separate `destructive_ops` item behind G_APPROVAL, executed only after the equivalence gate below
  has passed.
- **Import rollback**: `packages/ocean` arrives as a subtree; reverting the import commit removes
  it. The source repo is not archived until after merge and verification, so it remains the
  fallback until that final `destructive_ops` step runs.

**The gate that makes rollback rarely necessary:** bring up the LocalStack stack, run
`call-simulator` and `sim-driver` against it, and confirm every consumer reaches the same Postgres
state it reaches on Kafka today. The graph tables and `audit_log` after a simulation run must be
indistinguishable between the two transports. Those two simulators are the regression net for the
whole consumer rewrite, and equivalence is a precondition of the teardown approval.
