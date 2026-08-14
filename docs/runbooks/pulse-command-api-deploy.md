# Runbook: pulse-command-api-deploy

Operator procedure for standing up the pulse-ledger command API on Duplo tenant `dev01-brook`
(EKS cluster `duploinfra-nonprod`, namespace `duploservices-dev01-brook`) — the image (`task
ledger:image`/`ledger:deploy`, S1's serving-layer task), the database bootstrap and migration,
and the Duplo-side service/LB/secret objects (`packages/pulse-ledger/infra/duplo/`,
`scripts/pulse-ledger/deploy.sh`). Everything here is a manual operator action; nothing in this
procedure runs from CI.

## Outstanding prerequisite: the RDS security group

The RDS security group `sg-0f2f6dfad100dd31f` currently admits Postgres (5432) from only the VPN
`/32` and subnets `10.221.0.0/22` and `10.221.4.0/22`. **The EKS node security group is not
admitted.** Until it is added, the command API pod cannot reach the database at all — this is not
a "the app will retry" situation, it is a networking block that must be fixed before step 3 below.
Add the EKS node SG to `sg-0f2f6dfad100dd31f`'s inbound rules on 5432 before proceeding.

## Procedure

### 1. Build and push the image

```bash
task ledger:image TAG=<tag>
task ledger:deploy TAG=<tag> TARGET=dev01-brook
```

Both are credential-needing deploy artifacts, never reachable from `task check`
(`tests/test_ledger_deploy_targets.py`).

### 2. Bootstrap the database (once per environment, before the first migration)

From a host that can reach the RDS instance directly with an admin/superuser credential:

```bash
psql "$RDS_ADMIN_DSN" \
  -v migrator_password="$PULSE_LEDGER_MIGRATOR_PASSWORD" \
  -v app_password="$PULSE_LEDGER_APP_PASSWORD" \
  -f packages/pulse-ledger/infra/postgres/bootstrap_database.sql
```

Creates `pulse_ledger_migrator` (LOGIN, CREATEROLE — owns the database) and `pulse_ledger_app`
(LOGIN, owns nothing), the `pulse_ledger` database, and locks down `PUBLIC`. Idempotent — safe to
re-run. The privilege split (`packages/pulse-ledger/infra/postgres/versions/0001_ledger_schema.py`)
only closes after step 3 runs once: `pulse_ledger_service` — the NOLOGIN group role migration 0001
creates, holding SELECT/INSERT on `ledger.events` with UPDATE/DELETE revoked — does not exist
until then, so the script's tie-in (`GRANT pulse_ledger_service TO pulse_ledger_app`) is a no-op
the first time and takes effect the first time this script is re-run *after* step 3.

### 3. Run migrations — from the in-VPC Orca cloud host, never an init container

```bash
DATABASE_URL="postgresql://pulse_ledger_migrator:$PULSE_LEDGER_MIGRATOR_PASSWORD@<rds-host>/pulse_ledger" \
  task ledger:migrate
```

This runs on the in-VPC Orca cloud host (`.planning/reports/2026-08-13-orca-cloud-host-dev01-brook.md`
— the persistent Duplo host on this same tenant), not as a Kubernetes init container on the API
pod, for one reason worth stating plainly: **an init container would have to carry a DDL-capable
credential (`pulse_ledger_migrator`) into the same pod spec as the API's runtime credential, which
undoes the entire privilege split this deploy exists to enforce.** The command API's pod holds
only `pulse_ledger_app` — LOGIN, owns nothing, no CREATEROLE — for its whole life; the migrator
credential is never material the running service has access to. RDS is private (no route from
outside the VPC), so *something* in-VPC has to run `alembic upgrade head`; that something is a
deliberate, logged operator action from the cloud host, not code that ships in the image.

Re-run step 2's bootstrap script now that `pulse_ledger_service` exists, to grant it to
`pulse_ledger_app`:

```bash
psql "$RDS_ADMIN_DSN" \
  -v migrator_password="$PULSE_LEDGER_MIGRATOR_PASSWORD" \
  -v app_password="$PULSE_LEDGER_APP_PASSWORD" \
  -f packages/pulse-ledger/infra/postgres/bootstrap_database.sql
```

### 4. Prepare the secret env file (never committed)

`scripts/pulse-ledger/deploy.sh` populates the service's own Duplo secret
(`pulse-ledger-api-secret` — never the tenant's shared `brook-flat-env-secret`) from a local
`KEY=VALUE` file whose path you pass as `PULSE_LEDGER_SECRET_ENV_FILE`. This file lives outside
the repository and is never added to git. At minimum it needs:

| Key | Value |
| --- | --- |
| `DATABASE_URL` | Plain `postgresql://pulse_ledger_app:<password>@<rds-host>/pulse_ledger` — **psycopg v3 does not understand a `+driver` suffix** (`api_server.py`'s and `relay_worker.py`'s module docstrings both record this; `psycopg.connect()` on a SQLAlchemy-style DSN fails to connect, not silently misconfigures). |
| `ALEMBIC_DATABASE_URL` | The SQLAlchemy form, `postgresql+psycopg://...` — alembic (`infra/postgres/env.py`) wants this one. Two keys, deliberately, not one plus string surgery at deploy time: the `+driver` footgun is exactly what a "strip this prefix before use" step would reintroduce the first time someone forgets it. |
| `PULSE_LEDGER_WRITER_TOKEN_<WRITER_ID>` | At least one. **`CredentialRegistry.from_env` refuses to build with zero writer tokens present** (`pulse_ledger.auth`) — with none set, the pod crashloops at boot with a traceback that names no missing variable, so this is worth getting right before the first deploy rather than debugging it from pod logs. |
| `PULSE_LEDGER_WRITER_AUTHORITY_<WRITER_ID>` | Optional, per writer. |
| `PULSE_LEDGER_TWENTY_WEBHOOK_SECRET` / `..._SECRET_NEXT` | Required once the webhook route is enabled (`PULSE_LEDGER_TWENTY_WEBHOOK_ENABLED=true`, already set as a plain `Env` value in `command-api.service.json` — it is a switch, not a credential). |
| `PULSE_LEDGER_TWENTY_API_TOKEN` / `PULSE_LEDGER_TWENTY_BASE_URL` | Optional — the rejection-comment adapter stays unwired without them (`api_server.build_comment_poster`); rejections still receipt. |

### 5. Apply the Duplo service, LB config, and secret

```bash
export PULSE_LEDGER_SECRET_ENV_FILE=/path/outside/this/repo/pulse-ledger-secrets.env
scripts/pulse-ledger/deploy.sh <image-ref>
```

`<image-ref>` is the full image reference `task ledger:image`/`ledger:deploy` built and pushed in
step 1. The script mints one Duplo portal token (`duplo-jit`, not `duploctl --interactive`, which
blocks without a TTY) and reuses it for every call, applies
`packages/pulse-ledger/infra/duplo/command-api.service.json` (create-if-absent,
update-if-drifted), exposes the service as an internal ClusterIP via
`command-api.lb.json`'s shape, and creates-or-updates the secret from your env file. See
`packages/pulse-ledger/infra/duplo/README.md` for the shape details — the `OtherDockerConfig` key
casing (`EnvFrom`/`Env` PascalCase, `resources`/`*Probe` camelCase) is the single easiest thing to
get wrong there.

### 6. Verify

Check that the service is 1/1 ready, either in the Duplo UI or:

```bash
duploctl service find pulse-ledger-api --tenant dev01-brook
```

`GET /health` (in-cluster only — see the LB config) answers without a credential and without a
database round-trip; a healthy pod with no database reachability still passes it, so a green
`/health` is liveness only, not proof the migration or the security-group prerequisite landed.
Confirm the latter by submitting one command through the Twenty webhook path and watching it
commit, or by checking pod logs for a connection refusal.

## Governance: this does not close D14

**ADR-0004 records D14 as Snowpark Container Services (SPCS), with EKS on DuploCloud as the named
fallback if a timeboxed spike shows SPCS cannot terminate the Twenty webhook path with acceptable
latency** (`docs/adr/ADR-0004-runtime-readiness-decisions.md`). This runbook deploys to EKS on
DuploCloud. That is a **dev-environment decision** — it gets the command API running somewhere
reachable for development and the Twenty webhook integration work, nothing more — and it does
**not** close D14, does not constitute the spike, and does not abandon SPCS as the intended
production target.

`docs/adr/` is append-only. If SPCS is later abandoned in favor of EKS as the production target,
that is a new ADR with D14's status flipped to superseded — never a quiet consequence of this
runbook having been followed in dev.
