# 8.2 (DNA-774) — Kafka vs EventBridge equivalence comparison

**Verdict: EQUIVALENT** (`diff-report.txt`, harness exit 0). Every scenario-driven
row — 50 patients, 66 signals, 50 alerts, 50 tasks, 50 interactions, 150 outcomes,
50 escalation-state rows, and all 618 scenario-driven `audit_log` rows — is
identical across the two transports after removing only noise-by-construction.
This is the equivalence gate for 9.2 (MSK teardown).

## What was compared

Two runs of `services/sim-driver/scenarios/smoke_test.yaml` (50 patients, all
CRITICAL), captured with `scripts/equivalence_harness.py` at the same commit:

| side | tree | transport | capture |
|------|------|-----------|---------|
| A (`kafka`) | scratch clone at `8ef0d4b` (last all-Kafka commit, wave 0 complete) | Redpanda/Kafka, `ocean.*` topics | `captures/kafka.json` (1096 rows) |
| B (`eventbridge`) | this branch (post-migration) | LocalStack EventBridge + SQS | `captures/eventbridge.json` (1104 rows) |

Both stacks ran from `infra/docker-compose.yml` of their tree plus a run
override (`runconfig/override-kafka.yml`, `runconfig/override-eventbridge.yml`).
The comparison is therefore the **full migration delta** (transport swap plus the
wave 2–3 consumer rewrites), not a transport-only A/B: no tree exists that
differs from `main` in transport alone. That is the delta the gate protects.

## Determinism pinning (constraint 2 of the 8.1 handoff)

`runconfig/AGENTS-pinned.md` was mounted over `/app/AGENTS.md` in agent-worker on
both sides: a single eligible persona with `call_answer_rate: 1.0`,
`missed_call_retry_count: 0`, `outreach_approve_rate: 1.0`,
`claim_delay_seconds: [0, 0]`. This pins all three stochastic branches
(call-simulator's unseeded `random.random()` answer roll, agent-worker's
approve-rate gate, and the random persona claim race that would otherwise make
`tasks.assigned_to` differ run-to-run). `ANTHROPIC_API_KEY` was forced empty so
agent-worker's decision pipeline took the deterministic severity fallback
(CRITICAL → approve) instead of live Haiku calls; `ESCALATION_ENABLED=false`
removed wall-clock-timeout escalations the gate does not compare.

## Exclusions, each justified (constraint 1: no normalization into vacuity)

1. `audit_log.detail.topic` — records the transport address itself
   (`ocean.signals` vs `signals`). It is the one field that *must* differ; the
   harness deliberately refuses to normalize it (8.1), so it is excluded here
   explicitly and visibly.
2. `signals.last_event_at`, `interactions.last_event_at` — columns added by
   migration 0019 (this change, wave 2a); they do not exist in the `8ef0d4b`
   schema. Schema evolution, not transport behavior. (`tickets.last_event_at`
   from 0020 would be the same case, but both runs produced zero ticket rows,
   so no exclusion was needed or made.)
3. `audit_log` rows with `detail.event_type=connector.heartbeat` (12 in A,
   20 in B) — connectors emit one heartbeat per wall-clock interval, so the
   count measures stack uptime at capture time, not transport semantics; they
   kept arriving after the pipeline had quiesced. Excluded via the harness's
   `--ignore-audit-event` flag, which drops them from the raw capture and
   records the exclusion in the report.

Nothing else was excluded. In particular every deterministic identifier
(sim-driver sha256 ids, control-plane uuid5 task ids — 966 preserved UUIDs per
side) compared verbatim, and all 618 remaining audit rows matched one-to-one by
event type: signal.received 66, alert.created 50, task.created/completed 50/50,
ai.recommendation/approved 50/50, call.started/connected/completed 50/50/50,
outcome.recorded 100, graph_upsert 50, scenario bookends 2.

## At-least-once duplicates (constraint 3)

None observed in this run: after excluding heartbeats, audit row counts are
exactly 618/618 with no surplus rows on the SQS side. The harness would have
surfaced a redelivered event as an extra `audit_log` row (`event.ingested` is
appended per delivery, and `audit_id` is fresh per write); the gate passing
here does **not** prove duplicates cannot occur, only that this run had none.
A future duplicate is a finding to interpret, not to normalize away.

## Warnings in the report (expected, explained)

The 2×2 "indistinguishable outcomes rows" warnings: graph-projection writes 50
`call_completed` and 50 `task_resolved` outcome rows with `patient_id: ""` and
`interaction_id: null` — identical after normalization except for their random
ids, so token pairing among them is arbitrary. They compare as equal multisets,
so the gate is unaffected; the harness flags the tie honestly. (That
graph-projection drops patient/interaction linkage on these rows looks like a
projection defect worth its own ticket — it is identical on both transports.)

## Defects found and worked around to obtain the captures

Recorded here because they change what "the Kafka path" and "the LocalStack
path" mean in practice; run-level fixes live in `runconfig/`, none touch owned
files:

1. **The committed LocalStack path had never run end-to-end.** botocore 1.40.x
   resolves the default client region from `AWS_DEFAULT_REGION`; the compose
   env sets only `AWS_REGION`. Publishers survive (ocean-broker passes
   `region_name` explicitly) but `localstack-init` and **every SQS consumer**
   build region-less clients and die at startup with `NoRegionError` —
   silently, as fire-and-forget asyncio tasks. Queues fill, nothing consumes,
   the graph stays empty. Fixed for the run via `AWS_DEFAULT_REGION` in the
   override; owner: 6.5 / a follow-up (see HANDOFF).
2. **The pre-migration tree cannot boot from scratch.** Migration 0017 at
   `8ef0d4b` uses `UNIQUE(alert_id) WHERE (active)` inline, which is not valid
   Postgres; it was repaired during this change (`cb801f9`, folded into 3.0).
   The repaired 0017 was copied into the scratch clone.
3. **`packages/ocean/AGENTS.md` does not exist at `8ef0d4b`** (lost in the
   OCEAN absorption, reconstructed by 4.14), so the old agent-worker image
   cannot even build. The pinned roster doubles as the fix.
4. Harness gaps found by the first live run, fixed in this task's commit with
   tests: pgvector `embedding` columns (migration 0006) were unclassified and
   made capture raise; the blind sort key erased already-mapped UUIDs, making
   per-call audit rows tie and pair fresh tokens arbitrarily (false
   NOT EQUIVALENT); no row-level exclusion existed for uptime-driven audit
   events (`--ignore-audit-event` added, recorded in the report).

## Reproducing

```bash
# EventBridge side (this tree):
export PINNED_AGENTS_MD=$PWD/docs/equivalence/runconfig/AGENTS-pinned.md
docker compose -p ocean-eb -f infra/docker-compose.yml \
  -f docs/equivalence/runconfig/override-eventbridge.yml --profile sim up -d
curl -X POST localhost:8060/simulate -H 'Content-Type: application/json' -d '{"scenario": "smoke_test"}'
# wait for /health active_scenarios to empty and audit_log count to stabilize, then:
uv run python scripts/equivalence_harness.py capture \
  --scenario services/sim-driver/scenarios/smoke_test.yaml \
  --label eventbridge --out eventbridge.json \
  --psql-cmd "docker compose -p ocean-eb -f infra/docker-compose.yml exec -T postgres psql -U ocean -d ocean"

# Kafka side: scratch clone at 8ef0d4b + runconfig/override-kafka.yml (see its
# header for the two file injections), same simulate/capture flow, then:
uv run python scripts/equivalence_harness.py diff kafka.json eventbridge.json \
  --ignore audit_log.detail.topic \
  --ignore signals.last_event_at \
  --ignore interactions.last_event_at \
  --ignore-audit-event connector.heartbeat
```
