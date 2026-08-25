# RisingWave on Snowpark Container Services with MongoDB Atlas CDC
## Design Spec and Solution Scaffold — v0.1 (2026-08-18)

**TL;DR** — Deploy RisingWave in single-node mode as a long-running SPCS service, ingest
Atlas change streams through the native `mongodb-cdc` connector over an External Access
Integration, and manage the entire transformation DAG with dbt-risingwave running as an
SPCS job service. The design keeps CDC data (including PHI) inside the Snowflake
governance boundary, reuses the MedGemma SPCS deployment pattern, and sinks curated
marts back to Snowflake-readable storage. One hard platform constraint drives the
topology: SPCS public endpoints are HTTP-only, so the Postgres-wire port (4566) is
reachable only from inside SPCS — dbt therefore runs in-boundary as a job service.

---

## 1.0 Goals and non-goals

### 1.1 Goals
- Stream MongoDB Atlas collections into continuously maintained materialized views
  with second-level freshness, managed entirely as a dbt project.
- Zero new infrastructure outside Snowflake + Atlas. No Kafka, no Connect, no
  Schema Registry, no third VPC.
- Reuse existing SPCS operational patterns: image repository, compute pools,
  External Access Integrations (EAIs), service specs, Langfuse-style log egress.
- Keep PHI inside the existing HIPAA boundary (Snowflake account + Atlas project,
  both under BAA).

### 1.2 Non-goals
- Replacing the Snowflake/dbt batch stack. RisingWave is the hot path only.
- Multi-node RisingWave HA in the pilot. Single-node first, scale-out is a
  documented follow-on (section 8.2).
- Sub-100ms serving. Target is p95 event-to-view under 10 seconds.

---

## 2.0 Architecture

### 2.1 Topology

```
MongoDB Atlas (M10+, replica set)
  │  change streams (TLS 27017, via EAI egress)
  ▼
┌─────────────────────────── SPCS: RW_POOL ────────────────────────────┐
│  service: risingwave_svc (single-node)                               │
│    :4566 pgwire   TCP, non-public  ◄─── dbt job service / SPCS apps  │
│    :5691 console  HTTP, public (Snowflake-authenticated ingress)     │
│    block volume /data  (hummock state + embedded meta)               │
│                                                                      │
│  job service: dbt_rw_runner (dbt-risingwave, on demand / scheduled)  │
└──────────────────────────────────────────────────────────────────────┘
  │  sinks (Iceberg / S3 via EAI)                │ pgwire (in-boundary)
  ▼                                              ▼
Snowflake external tables / Iceberg      Control Room v2 API (SPCS)
```

### 2.2 Key design decisions

| # | Decision | Choice | Rationale |
|---|---|---|---|
| D1 | Ingestion path | Native `mongodb-cdc` connector | Deletes the Kafka/Connect/Schema Registry tier entirely |
| D2 | RisingWave mode | Single-node image, pinned tag | One container, one spec, fits SPCS service model |
| D3 | State store | Block volume, `hummock+fs` local state | No S3 dependency in pilot, snapshot-capable |
| D4 | Meta store | Embedded (SQLite on block volume) | Zero extra services for pilot |
| D5 | dbt execution | SPCS job service over service-to-service TCP | pgwire cannot be a public endpoint (HTTP-only ingress) |
| D6 | Console access | Public HTTP endpoint on :5691 | Snowflake ingress auth gates it for free |
| D7 | Egress control | One EAI for Atlas, one for sink target | Least-privilege, auditable host allowlists |
| D8 | Warm path out | Iceberg/S3 sink → Snowflake external table | Snowflake remains the analytical system of record |

Production posture upgrades (post-pilot): D3 → S3 hummock via EAI, D4 → Postgres
meta backend (Brook already runs Postgres), D2 → dedicated meta/compute/compactor
services. All are config changes, not redesigns.

### 2.3 Assumptions (flagged)
- Atlas cluster is M10 or above (change streams unsupported on free/flex tiers).
- Atlas and the Snowflake account run in the same cloud region (egress cost + latency).
- RisingWave image tag is pinned at deploy time. Container flags below follow the
  documented single-node pattern — verify against `--help` for the pinned tag before
  first push, and record the verified command in this spec.
- Compute pool sizing starts at CPU_X64_M (pilot volume: one collection,
  low-thousands of changes/minute). Resize on evidence.

---

## 3.0 Repository scaffold

```
rw-spcs-pilot/
├── README.md
├── infra/
│   ├── 00_atlas_prep.md              # Atlas-side checklist (section 4.1)
│   ├── 01_snowflake_setup.sql        # roles, db, pools, EAIs, repo, volume
│   ├── 02_secrets.sql                # Atlas URI as Snowflake SECRET
│   ├── risingwave_service.yaml       # SPCS service spec
│   ├── dbt_runner_service.yaml       # SPCS job service spec
│   └── Dockerfile.dbt                # dbt-risingwave runner image
├── dbt/
│   ├── dbt_project.yml
│   ├── profiles/profiles.yml         # host = risingwave_svc DNS name
│   └── models/
│       ├── ingest/
│       │   ├── mongo_device_readings.sql     # table_with_connector
│       │   └── _ingest__models.yml
│       ├── staging/
│       │   ├── stg_device_readings.sql       # jsonb → typed columns
│       │   └── _staging__models.yml          # tests as materialized views
│       ├── marts/
│       │   └── device_health_live.sql        # materialized_view
│       └── sinks/
│           └── snk_device_health_iceberg.sql # sink materialization
├── ops/
│   ├── runbook.md                    # sections 4.0–6.0 of this spec
│   ├── suspend_resume.sql
│   └── monitors.sql                  # lag + state-size checks
└── .github/workflows/
    └── dbt_rw_ci.yml                 # compile + EXECUTE JOB SERVICE on merge
```

Scaffold with `rob-repo` conventions where applicable — this tree lists only the
deployment-specific additions.

---

## 4.0 Deployment runbook

### 4.1 Phase A — MongoDB Atlas preparation

1. Confirm cluster tier M10+ and MongoDB 6.0+.
2. Create a scoped database user for CDC:
   ```javascript
   // Atlas UI → Database Access, or Atlas Admin API
   { user: "rw_cdc", roles: [ { role: "read", db: "brook_app" } ] }
   ```
   Read-only, single database. No cluster-wide roles.
3. Enable pre/post images on each captured collection (exact update documents,
   immune to updateLookup race):
   ```javascript
   db.runCommand({ collMod: "device_readings",
                   changeStreamPreAndPostImages: { enabled: true } })
   ```
4. Set oplog minimum retention window to survive your worst realistic RisingWave
   outage (recommendation: 48h). Atlas → Cluster → Additional Settings → Oplog.
5. Network access: allowlist Snowflake SPCS egress. SPCS egress IPs are not
   static — for the pilot, allow the cloud-provider region block or use Atlas
   Private Endpoint if the Snowflake account supports outbound PrivateLink in
   your region. Record which path was chosen. This is the single largest
   security decision in the deployment — do not ship 0.0.0.0/0 past the pilot.
6. Capture the standard (non-SRV) connection string listing replica set hosts
   explicitly. SRV resolution works through the EAI wildcard, but explicit hosts
   make the network rule auditable:
   `mongodb://shard-00-00.xxxxx.mongodb.net:27017,shard-00-01...` — supply the
   `rw_cdc` user and its password separately, never inline in the URI.

### 4.2 Phase B — Snowflake objects

`infra/01_snowflake_setup.sql`:

```sql
use role accountadmin;

create role if not exists rw_admin;
create database if not exists rw_platform;
create schema if not exists rw_platform.core;
grant ownership on database rw_platform to role rw_admin;

-- image repository
create image repository if not exists rw_platform.core.images;

-- compute pool (pilot sizing)
create compute pool if not exists rw_pool
  min_nodes = 1 max_nodes = 1
  instance_family = cpu_x64_m
  auto_suspend_secs = 0;          -- streaming service must not suspend
grant usage, monitor on compute pool rw_pool to role rw_admin;

-- egress: Atlas
create network rule atlas_egress
  mode = egress type = host_port
  value_list = ('shard-00-00.xxxxx.mongodb.net:27017',
                'shard-00-01.xxxxx.mongodb.net:27017',
                'shard-00-02.xxxxx.mongodb.net:27017');

create external access integration atlas_eai
  allowed_network_rules = (atlas_egress) enabled = true;
grant usage on integration atlas_eai to role rw_admin;

-- secret: connection URI (never in specs or model SQL; user and password
-- supplied out of band, not inline in the connection string)
create secret rw_platform.core.atlas_cdc_uri
  type = generic_string
  secret_string = 'mongodb://shard-00-00.../?authSource=admin';
```

Note `auto_suspend_secs = 0` and its cost consequence: a streaming service is a
standing spend. Section 7.0 quantifies it.

### 4.3 Phase C — image build and push

```bash
# pull, retag, push the pinned single-node image
docker pull risingwavelabs/risingwave:<PINNED_TAG>
docker tag  risingwavelabs/risingwave:<PINNED_TAG> \
  <org>-<acct>.registry.snowflakecomputing.com/rw_platform/core/images/risingwave:<PINNED_TAG>
docker login <org>-<acct>.registry.snowflakecomputing.com
docker push <org>-<acct>.registry.snowflakecomputing.com/rw_platform/core/images/risingwave:<PINNED_TAG>

# dbt runner image
docker build -f infra/Dockerfile.dbt \
  -t <...>/images/dbt-rw:latest . && docker push <...>/images/dbt-rw:latest
```

`infra/Dockerfile.dbt`:

```dockerfile
FROM python:3.12-slim
RUN pip install --no-cache-dir dbt-core dbt-risingwave
WORKDIR /app
COPY dbt/ /app/
ENTRYPOINT ["dbt"]
CMD ["run", "--profiles-dir", "profiles"]
```

### 4.4 Phase D — RisingWave service

`infra/risingwave_service.yaml`:

```yaml
spec:
  containers:
    - name: risingwave
      image: /rw_platform/core/images/risingwave:<PINNED_TAG>
      # single-node launch; verify exact args against the pinned tag
      args: ["single_node", "--store-directory", "/data"]
      env:
        RW_TELEMETRY_ENABLED: "false"
      secrets:
        - snowflakeSecret: rw_platform.core.atlas_cdc_uri
          envVarName: ATLAS_CDC_URI
      volumeMounts:
        - name: state
          mountPath: /data
      resources:
        requests: { cpu: "4", memory: 16Gi }
        limits:   { cpu: "6", memory: 24Gi }
  volumes:
    - name: state
      source: block
      size: 200Gi
  endpoints:
    - name: pgwire
      port: 4566
      protocol: TCP        # non-public by platform rule
    - name: console
      port: 5691
      public: true         # HTTP, gated by Snowflake ingress auth
```

Create and verify:

```sql
create service rw_platform.core.risingwave_svc
  in compute pool rw_pool
  from specification $$ <yaml above> $$
  external_access_integrations = (atlas_eai);

show endpoints in service rw_platform.core.risingwave_svc;
-- console gets an https://... ingress URL; pgwire stays internal
call system$get_service_logs('rw_platform.core.risingwave_svc', 0, 'risingwave', 200);
```

### 4.5 Phase E — dbt runner job service

`infra/dbt_runner_service.yaml`:

```yaml
spec:
  containers:
    - name: dbt
      image: /rw_platform/core/images/dbt-rw:latest
      env:
        RW_HOST: risingwave-svc.core.rw-platform.snowflakecomputing.internal
        RW_PORT: "4566"
        RW_DB: dev
        RW_USER: root
```

`dbt/profiles/profiles.yml`:

```yaml
rw_pilot:
  target: spcs
  outputs:
    spcs:
      type: risingwave
      host: "{{ env_var('RW_HOST') }}"
      port: "{{ env_var('RW_PORT') | int }}"
      user: "{{ env_var('RW_USER') }}"
      password: ""
      dbname: "{{ env_var('RW_DB') }}"
      schema: public
```

Run deploys on demand (or from CI via a Snowflake task):

```sql
execute job service
  in compute pool rw_pool
  name = rw_platform.core.dbt_rw_runner
  from specification $$ <yaml above> $$;
```

Confirm the exact service-to-service DNS name with
`show services` / `desc service` — the pattern is
`<service-name>.<schema>.<database>.snowflakecomputing.internal` and it is the
single value most likely to need adjustment on first run.

### 4.6 Phase F — dbt models

`dbt/models/ingest/mongo_device_readings.sql`:

```sql
{{ config(materialized='table_with_connector') }}
create table {{ this }} (_id varchar primary key, payload jsonb)
include timestamp as commit_ts
with (
    connector = 'mongodb-cdc',
    mongodb.url = '{{ env_var("ATLAS_CDC_URI") }}',
    collection.name = 'brook_app.device_readings'
);
```

`dbt/models/staging/stg_device_readings.sql`:

```sql
{{ config(materialized='materialized_view') }}
select
    _id                                          as reading_id,
    (payload->>'patient_id')::varchar            as patient_id,
    (payload->>'device_type')::varchar           as device_type,
    (payload->>'reading_value')::double precision as reading_value,
    (payload->>'taken_at')::timestamptz          as taken_at,
    commit_ts
from {{ ref('mongo_device_readings') }}
```

`dbt/models/staging/_staging__models.yml` — tests become live monitors:

```yaml
models:
  - name: stg_device_readings
    columns:
      - name: patient_id
        tests:
          - not_null:
              config:
                store_failures: true
                store_failures_as: materialized_view
```

`dbt/models/marts/device_health_live.sql`:

```sql
{{ config(materialized='materialized_view') }}
select
    patient_id,
    device_type,
    count(*)                                   as readings_24h,
    avg(reading_value)                         as avg_value_24h,
    max(taken_at)                              as last_reading_at
from {{ ref('stg_device_readings') }}
where taken_at > now() - interval '24 hours'
group by 1, 2
```

`dbt/models/sinks/snk_device_health_iceberg.sql` — warm path back to Snowflake:

```sql
{{ config(materialized='sink') }}
create sink {{ this }} from {{ ref('device_health_live') }}
with (
    connector = 'iceberg',
    type = 'upsert',
    primary_key = 'patient_id,device_type'
    -- catalog/warehouse params per target; fill from sink EAI setup
);
```

### 4.7 Phase G — verification gates

Run in order. Each gate must pass before the next phase.

```
G1  service logs show single-node ready, console reachable via ingress URL
G2  psql from dbt runner container: select 1 over pgwire       (connectivity)
G3  dbt run creates ingest table; select count(*) grows        (snapshot backfill)
G4  insert a doc in Atlas; visible in stg_ within 10s          (streaming)
G5  update + delete a doc; mart reflects both within 10s       (CDC semantics)
G6  kill + auto-restart service; no re-snapshot, resumes token (durability)
G7  not_null failure view stays empty under 1h of live traffic (quality)
G8  sink target queryable from Snowflake                       (warm path)
```

G6 is the gate that validates the block-volume state decision. If the resume
token does not survive restart, stop and fix state persistence before anything
else — everything downstream depends on it.

---

## 5.0 Security and compliance

- **Data classification.** Change streams replicate full application documents.
  Treat the RisingWave service as PHI-bearing from day one: same access tier as
  the Snowflake schemas holding clinical data, console endpoint granted to the
  DNA team role only.
- **Secrets.** Atlas URI lives in a Snowflake SECRET, injected as env var.
  Never in service specs, model SQL, or the repo. The `env_var()` reference in
  the ingest model resolves inside the container only.
- **Egress least privilege.** Two EAIs total: Atlas hosts, sink target hosts.
  Nothing else. EAI host lists are the auditable record of what this service
  can talk to.
- **Ingress.** The only public surface is the console over Snowflake-
  authenticated HTTPS ingress. pgwire is unreachable from outside the account
  by platform design, not by configuration discipline.
- **BAA scope.** Snowflake and Atlas are both existing covered vendors.
  RisingWave self-hosted inside SPCS adds no new vendor to the BAA matrix —
  that is a primary reason for this topology over RisingWave Cloud.

---

## 6.0 Operations

- **Monitoring.** Console (5691) for DAG lag and barrier latency. Wire the
  three numbers that matter into existing alerting: source lag seconds, state
  size on /data, restart count. `ops/monitors.sql` polls
  `system$get_service_status` plus RisingWave's `rw_catalog` views via the
  runner.
- **Suspend/resume.** The streaming service cannot auto-suspend. For planned
  quiet periods, `alter service ... suspend` — the oplog retention window
  (4.1.4) defines the maximum safe suspension.
- **Upgrades.** Pin tags, never `latest` for RisingWave itself. Upgrade =
  push new tag, alter service spec, verify G6 gate.
- **State growth.** 24h-windowed marts bound state naturally. Unbounded
  aggregations are the state-growth risk — require a retention decision per
  mart at review time.

---

## 7.0 Cost model (pilot, estimate — validate in week 1)

```
Compute pool  CPU_X64_M, 1 node, 24x7      ~730 hrs/mo   (the dominant line)
Block volume  200 GiB                       storage-rate/mo
Egress        Atlas → SPCS (same region)    ~0 if region-matched, else per-GiB
dbt runner    job service, minutes/day      negligible
Console       ingress                       negligible
```

Dated 2026-08-18. The standing compute is the trade against Dynamic Tables'
pay-per-refresh model — the pilot exit review (section 8.1) must compare
actual credit burn against a DT equivalent of the same DAG.

---

## 8.0 Exit criteria and follow-ons

### 8.1 Pilot exit review (2 weeks after G8)
- p95 event-to-mart latency vs. 10s target, measured across 3 load profiles.
- Credit burn vs. Dynamic Tables equivalent (from the DT audit pipeline).
- Operational incidents: restarts, re-snapshots, state anomalies.
- Decision: expand collections, hold, or fall back to DT-only.

### 8.2 Production hardening (only after a positive 8.1)
- State to S3 hummock via EAI, meta to Postgres. Enables multi-node.
- Split single-node into meta/compute/compactor services, min_nodes ≥ 2 pool.
- Atlas Private Endpoint replaces IP allowlisting.
- CI: dbt compile gate + `execute job service` from the merge pipeline.
- Onboard Control Room v2 Intervention Queue as the first real consumer.

---

## 9.0 Open questions

1. Snowflake outbound PrivateLink availability for the account's region and
   edition — determines 4.1.5.
2. Exact single-node launch args for the pinned RisingWave tag (D2 note).
3. Iceberg sink catalog choice: Snowflake-managed Iceberg vs. external Glue.
4. Whether Control Room v2 reads pgwire directly (co-located SPCS service)
   or only the Iceberg warm path — affects freshness SLO for the queue.
