# Design: snowflake-projection

## Context

Verified inputs, each checked on 2026-08-25 unless dated otherwise:

- **Live Snowflake state** (metadata-only query via Cortex, connection `default`):
  `STREAMLINE.OCEAN_RAW` exists (created 2026-03-15); its only table `EVENTS` holds 7,286 rows,
  max `_LOADED_AT` **2026-03-18 15:03:32**; columns `DATA` VARIANT, `_LOADED_AT` TIMESTAMP_NTZ
  default `CURRENT_TIMESTAMP()`, `_TOPIC` VARCHAR(100).
- **Consumer code exists, deployment does not.** `packages/ocean/services/warehouse-sync/src/main.py`
  MERGEs batches into `STREAMLINE.OCEAN_RAW.EVENTS` keyed on `data:event_id` (redelivery is a
  no-op by construction) and the baseline `warehouse-event-sync` spec pins rule-and-queue
  transport and uniform DLQ. No warehouse rule, queue, or Duplo service exists on `dev01-brook`.
- **The distribution playbook is proven.** twenty-projection 4.2 provisioned the same leg for
  the Twenty consumer: `ocean` bus (now standing), rule → SQS queue → access policy, consumer
  deployment; `scripts/pulse-ledger/provision_projection_feed.sh` is the one-shot precedent and
  DNA-1192's IAM grants cover `events:PutRule`/queue creation. The relay is live and publishing
  (`pulse-ledger-relay`, receipts on GitHub issue #252).
- **The live envelope authority is the emitter.** The relay publishes EventBridge events with
  `source = "ocean"`, `detail-type = "patient-state"`, and `detail` = the ledger envelope
  (observed live on the 4.2 receipt: `event_id`, `event_type`, `subject_type`, `subject_key`,
  `seq`, `effective_at`, …). `design/platform/event-envelope-spec.md` describes the superseded
  v1 (Twenty-as-store) envelope and MUST NOT be used as the column source.
- **Downstream gates.** `reconciliation-sweeps` blocks on this change; `survey-engine-ingress`'s
  entry metric is a 24h-queryable STG_EVENTS freshness figure (roadmap).

## Decisions

### 1. STG_EVENTS is re-based on the bus landing; the CDC events leg is superseded

**Decided 2026-08-25. Gates: the `snowflake-stg-events` delta, and the supersession note task.**

`STG_EVENTS.EVENTS` is a view over `STREAMLINE.OCEAN_RAW.EVENTS` — the landing the baseline
`warehouse-event-sync` capability owns — not over a `RAW_TWENTY.DOMAIN_EVENT` CDC mirror.

*Alternative rejected — build the CDC leg per `snowflake-landing-spec.md`.* That doc predates
the ledger: it treats Twenty Postgres as the event store. Today Twenty is a projection surface
(twenty-projection), the ledger is the record, and the boundary rule says consumers take the
bus, not another system's database. A CDC mirror of Twenty's event table would project a
projection. The landing spec's events leg gets a supersession note; its entity-CDC and
MART_STATE content is untouched here.

### 2. Feed revival is in-change, on the operator lane

**Decided 2026-08-25. Gates: task 2.1's lane and G_APPROVAL.**

Provisioning (rule, queue, DLQ, access policy, Duplo service for `warehouse-sync`) follows the
4.2 playbook and runs from the operator queue with G_APPROVAL — it mutates tenant
infrastructure and has no reviewable diff beyond the committed service/def files. Deferring
revival to a separate change would leave STG_EVENTS a view over a dead table — the exact
"stated but not real" gap this change exists to close.

### 3. STG_EVENTS ships as committed SQL applied by a task target, not dbt

**Decided 2026-08-25. Gates: tasks 3.1/3.2.**

The view DDL lives in this repo as a committed `.sql` artifact with an idempotent apply target
(the `deploy.sh`/service-JSON pattern: the committed file is the reviewable shape, the script
substitutes nothing secret). dbt is rejected for this object: the dbt estate has no publisher
contract owner (`consumes.md`), and this view IS the publisher contract other repos consume —
it must version with this repo. The catalog's guarded Snowflake release machinery
(`catalog_release`) is scoped to immutable catalog rows (D18) and is deliberately not
generalized here.

### 4. Completeness is a documented watermark, not an implied property

**Decided 2026-08-25. Gates: the publishes.md row, task 3.2.**

The contract states: rows are complete from the feed-revival date forward
(`min_complete_from`, stamped at revival); the 2026-03-18 → revival gap exists and is closed
by `projection-rebuild-drill` (ADR §4.6 authoritative rebuild), which this change explicitly
does not duplicate.

*Alternative rejected — one-off backfill from `prm_event` here.* It rebuilds a projection from
the ledger, which is precisely the drill change's machinery and receipt; doing it twice means
two half-owned rebuild paths.

### 5. Freshness is one pinned query

**Decided 2026-08-25. Gates: task 3.2, survey-engine-ingress's entry gate.**

The contract pins `SELECT TIMESTAMPDIFF('minute', MAX(_LOADED_AT), CURRENT_TIMESTAMP())` on
`OCEAN_RAW.EVENTS` as THE freshness figure. No dashboard, no alerting task in this change —
the sweep/alerting family belongs to `reconciliation-sweeps`.

## Open questions

1. **Envelope fields beyond the observed six.** The relay's full detail payload may carry
   more (actor, lineage, catalog version). Task 3.1 derives the pinned column list from the
   emitting code (`pulse_ledger` outbox → ocean-broker publisher) and the work order requires
   listing every field it finds — the contract pins what the emitter proves, not what any doc
   says.
2. **`_TOPIC` vocabulary.** March-era rows carry pre-ledger topics; post-revival rows carry
   `patient-state`. Whether the view filters to ledger domains or exposes all topics with the
   domain as a column is task 3.1's call, recorded in HANDOFF — default: expose all, no filter,
   consumers filter on `_topic`.

## Risks / Trade-offs

- **Two proofs share one tenant.** billing-state wave 3 (relay declare-back) and this revival
  both exercise the dev bus. Sequencing is by operator-queue ordering; the leg proofs are
  read-only to each other's queues.
- **The gap is visible.** Consumers joining STG_EVENTS before the drill lands see five silent
  months. Mitigated by the watermark being IN the contract row, not a footnote.
- **View cost at growth.** Views are fine at current volume (per the landing spec's own
  materialization note); dynamic tables remain the recorded escape hatch.

## Migration Plan

1. Wave 1 (repo): committed SQL + apply target + offline tests; supersession note; contract
   rows drafted with `min_complete_from` placeholder.
2. Wave 2 (operator, G_APPROVAL): provision rule/queue/DLQ/service, prove event→row and
   redelivery no-op, stamp `min_complete_from`, run the freshness query, receipts on the
   tracking issue.
3. Rollback: delete rule/queue/service (the landing table keeps its rows); revert the SQL
   commit. No ledger-side change exists to roll back.
