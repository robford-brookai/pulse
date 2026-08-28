# Inventory: pulse, streamline, ocean — 2026-08-25

Facts verified today: repo sweep (paths cited) + Snowflake metadata-only queries (Cortex,
connection `default`). No row contents read.

## The three names

**pulse** — the program and this repo. The ledger is the record; everything else projects
from it.

- Deployed on `dev01-brook` (AWS 173008660334): `pulse-ledger-api` and `pulse-ledger-relay`
  (one image, two commands; committed Duplo JSON under
  `packages/pulse-ledger/infra/duplo/`), the Twenty projection feed (rule
  `pulse-twenty-projection` → SQS queue, provisioned 2026-08-21), and two EventBridge
  schedules (`month-open`, `consent-sweep`) via `packages/schedules/infra/terraform/`.
- Proven live end to end 2026-08-21: command API → outbox → relay → `ocean` bus → SQS →
  Twenty board (receipts: GitHub issue #252).
- Pulse publishes exactly one bus domain: `patient-state`
  (`pulse_ledger/relay.py: LEDGER_DOMAIN`).
- Packages with NO deploy artifact (library/CLI-run only): `pulse-core`, `verdict-relay`,
  `identity`, `consent-ingress`, `twenty-projection`, `archaeology`, `synthea-seed`,
  `twenty-app/-model`.
- Governance now stated: `docs/contracts/producer-registry.md` (billing-source-boundary,
  archived 2026-08-24) + `publishes.md`/`consumes.md`.

**ocean** — the absorbed event backbone, now `packages/ocean/` (import 2026-08-02,
ADR-0002; old repo `robford-brookai/ocean` archived read-only at tag `pre-absorption`;
MSK and Redpanda torn down).

- Defines the bus: 11 live domains (`ai-ops, alerts, audit, interactions, logistics, ops,
  outcomes, patient-state, signals, tasks, tickets`; `warehouse-dlq` retired) in
  `ocean_broker/catalog.py` → generated tfvars → `eventbridge-ocean` terraform module.
  Only `patient-state` carries pulse traffic today; the other ten are exercised only by
  ocean services.
- 16 services, all with Dockerfiles, **zero with a live deployment**: the only runtime
  manifests are `mongodb-connector`'s stale k8s YAMLs; no Duplo JSON exists anywhere under
  `packages/ocean/`. The terraform module that would create the 7 consumer rule/queue pairs
  is not applied on the tenant (verified for `warehouse-sync` during snowflake-projection
  proposal: no rule, no queue, no service).
- Doctrine already re-assigned (`ocean-to-pulse-adaptation-plan.md` §4.1): connectors become
  ingress adapters; the graph becomes non-authoritative projection; "bus as record" is
  forbidden. The 15 non-warehouse services are dormant code awaiting that repurposing —
  they are not a parallel system.
- `packages/ocean/tests/` is outside CI with ~60 pre-existing failures, and the
  `test_SYNC_03` / `test_DBT_01..09` requirement tests assert against
  `.repos/streamline/...` paths that were deliberately excluded from the import — they
  reference a tree this repo does not contain.

**streamline** — three distinct things sharing one name:

1. **The Snowflake database `STREAMLINE`** — the whole warehouse. 21 schemas, 287 objects.
   The big, active estate is the classic ELT surface: `CIO_RAW` (61M-row PEOPLE, 14.5M
   campaign actions), `HUBSPOT_RAW` (93M engagements), `IMPILO_RAW` (253M readings),
   `ZCC_RAW/CORE`, `SIGMA_RAW`, `RDS_BILLY/MYSQL/PAPI/RESTRICTED` (created 2026-07-24),
   plus `*_ANALYTICS` view layers. The ocean footprint inside it is tiny and stale:
   `OCEAN_RAW.EVENTS` 7,286 rows (newest 2026-03-18), `OCEAN_CORE`/`OCEAN_MARTS` a few
   dozen rows, all March-era.
2. **The repo `brookai/streamline`** — the proven SPCS CDC pipeline (mdba → Snowflake),
   the Snowflake DDL (including the `CREATE SCHEMA ... OCEAN_*` statements), and the dbt
   project that ocean's warehouse model layer (`models/ocean/`) lives in. Registered in
   `consumes.md` as a read-only source pattern; it has no publisher contract owner.
3. **Landing schemas for delivered exports** — `streamline.cio_raw`/`cio_prod`, the seam
   `consent-ingress` reads (ADR-0005).

## The seams that matter

- **pulse → warehouse is one thread, currently cut.** Relay publishes `patient-state`;
  `warehouse-sync` (ocean's one still-load-bearing service) would land it in
  `OCEAN_RAW.EVENTS`; nothing has landed since 2026-03-18 because the consumer was never
  deployed post-absorption. The `snowflake-projection` change (proposed 2026-08-24, at
  validate) revives exactly this leg and states the STG_EVENTS contract on top, with a
  `min_complete_from` watermark; the March–August gap closes later via
  `projection-rebuild-drill`.
- **Warehouse modeling ownership is split across repos.** The DDL and dbt models for
  ocean's Snowflake objects live in `brookai/streamline`; pulse asserts against them via
  tests that can't run here. Any future STG/MART work in pulse (snowflake-projection ships
  committed SQL in-repo by design decision 3) deepens the question of which repo owns the
  warehouse contract — currently answered only object-by-object in `publishes.md`.
- **Ten bus domains and 15 ocean services have no operator.** Nothing consumes or emits on
  them in any deployed workload. They are inert until a change repurposes each per the
  adaptation plan — worth remembering before anyone reads the domain list as live surface
  area.
- **Two stale v1 design docs still describe Twenty-as-event-store**
  (`snowflake-landing-spec.md`, `event-envelope-spec.md`); snowflake-projection task 1.2
  adds the supersession note to the first; the second has none yet.

## One-line answers

- Is pulse live? Yes — ledger, relay, Twenty projection, on dev, proven.
- Is ocean live? Only as the bus definition and one domain; all its services are undeployed
  code inside pulse.
- Is streamline live? The database very much is (the ELT estate); the CDC repo is external
  and untracked here; ocean's slice of the database is stale until snowflake-projection 2.1
  revives the feed.
