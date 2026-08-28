# Proposal: snowflake-projection

## Why

Three facts, the first verified live against Snowflake on 2026-08-25 (metadata only):

- **The warehouse landing exists but the feed is dead.** `STREAMLINE.OCEAN_RAW.EVENTS` has the
  published shape (`DATA` VARIANT, `_TOPIC`, `_LOADED_AT`) and 7,286 rows — the newest loaded
  **2026-03-18**, five months ago. The `warehouse-event-sync` capability is in the baseline and
  its consumer code ships in `packages/ocean/services/warehouse-sync/`, but no rule, queue, or
  deployment exists on the tenant: every ledger event published on the `ocean` bus since the
  relay went live (2026-08-21, twenty-projection 4.2) has missed the warehouse. The March rows
  are pre-ledger traffic.
- **Two queued changes gate on this one.** `reconciliation-sweeps` depends on
  `snowflake-projection` outright, and `survey-engine-ingress`'s 24h-queryable warehouse metric
  is the STG_EVENTS contract (roadmap, queued-changes table).
- **The design doc for this layer predates the ledger.** `design/platform/snowflake-landing-spec.md`
  builds STG_EVENTS from a Twenty-Postgres CDC mirror — the v1 architecture in which Twenty was
  the event store. The shipped system is the pulse ledger with the outbox relay publishing
  envelopes to the `ocean` bus, and the baseline `warehouse-event-sync` spec mandates the
  warehouse consumes like any other consumer: its own rule and queue. Nobody has restated
  STG_EVENTS on top of the real landing.

## What Changes

- **Revive the warehouse feed on dev.** Provision the missing distribution leg per the existing
  playbook (twenty-projection 4.2, `scripts/pulse-ledger/provision_projection_feed.sh`
  precedent): an EventBridge rule on the `duploservices-dev01-brook-ocean` bus targeting a new
  warehouse SQS queue with DLQ, and the `warehouse-sync` consumer as a Duplo deployment. Prove
  it end to end: a committed ledger event appears as a row in `OCEAN_RAW.EVENTS`, a redelivery
  produces no second row (the MERGE path already keyed on `data:event_id`).
- **State the STG_EVENTS ledger contract on the real landing.** A committed
  `STG_EVENTS.EVENTS` view over `OCEAN_RAW.EVENTS`: one row per `event_id` (deduped, earliest
  arrival wins), envelope fields typed out of the VARIANT — at minimum `event_id`,
  `event_type`, `subject_type`, `subject_key`, `seq`, `effective_at`, plus `_topic` and
  `_loaded_at` passthrough — with the authoritative column list derived from what
  `pulse_ledger`'s relay actually publishes, not from the superseded v1 envelope doc.
- **Publish the contract.** `docs/contracts/publishes.md` gains the `STG_EVENTS.EVENTS` row:
  pinned columns, grain, the dedupe rule, the freshness expectation, and an explicit
  **completeness watermark** — complete from the feed-revival date forward; the March–August
  gap is closed by `projection-rebuild-drill` (ADR §4.6's authoritative rebuild), not here.
- **Make freshness queryable.** The contract documents the one-line lag query
  (`max(_loaded_at)` age) that is `survey-engine-ingress`'s gate metric, and the smoke
  assertion checks it after revival.
- **Mark the stale design doc.** `snowflake-landing-spec.md`'s Twenty-CDC events leg gets a
  supersession note pointing at this change's design.md; the entity-CDC and MART_STATE
  material stays untouched (it belongs to later changes).

## Capabilities

- `warehouse-event-sync` (modified) — the baseline capability gains the deployment reality:
  the consumer runs as a provisioned workload with its own rule, queue, and DLQ, and a
  freshness expectation.
- `snowflake-stg-events` (new) — the STG_EVENTS.EVENTS contract: columns, grain, dedupe,
  completeness watermark, and the freshness query.

## Out of scope

- **Historical backfill of the March–August gap.** The ledger holds every event;
  authoritative rebuild of a projection from the ledger is exactly `projection-rebuild-drill`
  (ADR §4.6), and doing a one-off partial backfill here would duplicate that machinery. The
  contract's completeness watermark makes the gap explicit instead of hidden.
- **MART_STATE: derived state, reconciliation, and quality views.** That is
  `reconciliation-sweeps`' scope, per the roadmap dependency direction.
- **Twenty entity CDC** (`RAW_TWENTY`, dimension views) and any dbt migration of these
  objects — the dbt estate has no publisher contract owner yet (`consumes.md`).
- **Production wiring.** Dev only, same posture as every projection change so far.

## Entry conditions

- None blocking. The `ocean` bus exists (created during twenty-projection 4.2), the IAM grants
  from DNA-1192 cover rule/queue creation, and the relay is live and publishing. `billing-state`
  wave 3 runs from the operator queue and shares no serial lane with this change.
