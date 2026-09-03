# Demo 5 — attended live run on dev (pulse-demo-closeout 3.3)

**Date:** 2026-09-02 · **Tracking issue:** #342 · **Main:** `41ad18d` · **Runbook:**
`docs/runbooks/demo5-end-to-end.md` §Running it live, §Staging the live run

**Revised 2026-09-02 evening from the run itself.** Steps 1 to 4 are written as they actually
worked, not as first planned. Run state at the last edit: steps 1 to 4 done and verified,
preflight green, stages 1 to 4 passed, stage 5 blocked on the warehouse feed (see §5a), rerun
pending. Tooling fixes the run needed are in PR #353.

**TL;DR:** One command runs the walk, `task stage:e2e:live`, but dev has to catch up with today's
merges first. The API pod predates the history route (#331), migration 0005 (#336), and the
`customer-io` writer (#352), and the dev secret has no consent writer key yet. Do the five
preparation steps in order, verify each, then run the walk and post the receipt on #342.
Everything below names credentials by variable or key name only. Never paste a value anywhere.

---

## 0. Before you start

- You are on `main` at `41ad18d` or later, `uv sync --all-packages` done.
- `scripts/verdict-env-vars.sh` exists (gitignored) and still holds the billing-state exports.
- 1Password is unlocked so `duplo-jit` can mint a session; a browser may open once.
- Docker is running, with "Use Rosetta for x86_64/amd64 emulation" on (Settings, General).
- `kubectl` has the `duplo-dev01` context. The AWS role is not mapped in that cluster; every
  kubectl call below carries the Duplo **k8s plan token**:

  ```bash
  KTOKEN=$(duplo-jit k8s --host https://duplo.cloud.brook.ai --plan nonprod --interactive | jq -r .status.token)
  k() { kubectl --context duplo-dev01 --token="$KTOKEN" -n duploservices-dev01-brook "$@"; }
  ```

  Define `k` as a function, not an alias: zsh parses a pasted block before running it, so an
  alias defined on line 1 is unknown on line 2.
- Two port-forwards stay open for the whole run, each in its own terminal, both via `k`:
  the API on 18000 (step 1) and the Postgres relay on 15432 (step 2). A port-forward to a
  Service pins one pod and dies when that pod is replaced; every restart below kills the API
  forward, so restart it afterwards.

## 1. Put dev on today's ledger image

The pod on dev01-brook ran an image from 2026-08-16 at the billing-state run. Stage 6 needs the
per-subject history route, stage 2 needs migration 0005 and the `customer-io` writer id.

Docker Desktop must have "Use Rosetta for x86_64/amd64 emulation" on (Settings, General). Under
plain QEMU the `uv` binary in the Dockerfile segfaults at step 5 with exit code 139.

The image goes to the tenant's ECR, account 173008660334, repository `pulse-ledger`, through the
`duplo-dev01` AWS profile (its `credential_process` is `duplo-jit`). `task ledger:deploy` is a stub
that pushes the bare `pulse-ledger:$TAG` name to Docker Hub and fails with `insufficient_scope`;
do not use it. Tag and push by hand:

```bash
TAG=$(git rev-parse --short HEAD)
ECR=173008660334.dkr.ecr.us-east-1.amazonaws.com
task ledger:image TAG=$TAG
aws ecr get-login-password --profile duplo-dev01 \
  | docker login --username AWS --password-stdin "$ECR"
docker tag pulse-ledger:$TAG "$ECR/pulse-ledger:$TAG"
docker push "$ECR/pulse-ledger:$TAG"          # PASS: prints the digest
```

Then re-point the `pulse-ledger-api` service (tenant dev01-brook) at the pushed reference, the
same way the 2026-08-28 roll to `f951d41` was done:

```bash
TOKEN="$(duplo-jit duplo --host https://duplo.cloud.brook.ai --interactive \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["DuploToken"])')"
duploctl service update_image pulse-ledger-api "$ECR/pulse-ledger:$TAG" \
  --host https://duplo.cloud.brook.ai --tenant dev01-brook --token "$TOKEN"
```

`packages/pulse-ledger/infra/duplo/command-api.service.json` is the service definition; the image
field is the only thing that changes.

**Verify:** the API is a ClusterIP; the laptop reaches it only through a port-forward. In its
own terminal:

```bash
k port-forward svc/pulse-ledger-api 18000:8000
```

Then the history route is served. Any status but 404 means the new image is up.

```bash
source scripts/verdict-env-vars.sh
curl -s -o /dev/null -w '%{http_code}\n' "$PULSE_LEDGER_API_URL/health"      # 200
curl -s -o /dev/null -w '%{http_code}\n' "$PULSE_LEDGER_API_URL/subjects/preflight/preflight/events"
# 401 or 200 = new image; 404 = still the old pod; 000 = the port-forward is not running
```

## 2. Apply migration 0005

RDS is private: reachable only from the node pool the API pod runs on. Relay through a socat
pod pinned to that node, then port-forward the pod. In its own terminal:

```bash
NODE=$(k get pods -o wide | awk '/^pulse-ledger-api/{print $7; exit}')
k run pg-relay --image=alpine/socat --restart=Never \
  --overrides="{\"spec\":{\"nodeName\":\"$NODE\"}}" \
  -- tcp-listen:5432,fork,reuseaddr tcp-connect:duplodev01-brook-dev.ckbkusse4i01.us-east-1.rds.amazonaws.com:5432
k wait --for=condition=Ready pod/pg-relay --timeout=60s
k port-forward pod/pg-relay 15432:5432
```

Use the migrator DSN, not the app DSN (privilege split, env-vars process doc §5). The migrator
password is in the scratch file as `PULSE_LEDGER_MIGRATOR_PASSWORD`.

```bash
source scripts/verdict-env-vars.sh
DATABASE_URL="postgresql://pulse_ledger_migrator:${PULSE_LEDGER_MIGRATOR_PASSWORD}@localhost:15432/pulse_ledger" \
  task ledger:migrate
```

**Verify:** the version table is `alembic_version_pulse_ledger` (set in `env.py`), not the
Alembic default:

```bash
uv run python -c "import os,psycopg; print(psycopg.connect(os.environ['DATABASE_URL']).execute('select version_num from alembic_version_pulse_ledger').fetchone())"
# ('0005',)
```

The preflight's `ledger-schema` check reads that table with the **app** role, which cannot see
it by default. Once per database, with the migrator DSN:
`GRANT SELECT ON public.alembic_version_pulse_ledger TO pulse_ledger_app`. Done on dev
2026-09-02; the durable home for that grant is an open decision on PR #353.

When the run is over: stop the forward and `k delete pod pg-relay`.

## 3. Mint the consent writer credential

The API registers writers from `PULSE_LEDGER_WRITER_TOKEN_<SUFFIX>`; the suffix `CUSTOMER_IO`
becomes the writer id `customer-io`, which the ingress now uses (#352).

Do it as one script so the value never touches a clipboard, a file, or a log. The shape, which
`scripts/pulse-ledger/rotate_twenty_key.sh` (PR #353) follows for the Twenty key and which the
2026-09-02 run used for this one:

1. Mint the value: `python3 -c 'import secrets; print(secrets.token_hex(32))'` into a variable.
2. Get a Duplo portal token with `duplo-jit duplo --host https://duplo.cloud.brook.ai
   --interactive` (cached after the first browser login) and read the current secret with
   `duploctl secret find pulse-ledger-api-secret ... --output json`.
3. Refuse if `PULSE_LEDGER_WRITER_TOKEN_CUSTOMER_IO` already exists. Otherwise run
   `duploctl secret update pulse-ledger-api-secret --from-literal KEY=VALUE ...` with **every
   existing key plus the new one**. `update` replaces the whole set; a partial update erases
   `DATABASE_URL` and crashloops the API (env-vars process doc §3).
4. Restart: `k rollout restart deployment/pulse-ledger-api` then `k rollout status ...`. The
   secret is read at pod start. This kills the API port-forward; start it again.

The staging script in step 5 reads the token back from the Duplo secret by key prefix, so
nothing is written to the env file.

**Verify:** `duploctl secret find` lists the key name (10 keys on dev after this step). Then the
API must recognise the credential:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $NEW" \
  "$PULSE_LEDGER_API_URL/subjects/preflight/preflight/events"
# 422 = registered writer (the fake subject type is rejected after auth); 401 = unknown credential
# — pod not restarted yet or wrong key name; 000 = port-forward down
```

## 4. Seed the demo card on dev Twenty

Stage 3 drags a card that must already exist: a `patientPrograms` record with
`canonicalPatientId = brook-fx-demo5-episode-0001` and `programCode = demo5`. The committed
Twenty seed (`task twenty:seed TARGET=dev`) does not include it.

First make sure the dev Twenty key works at all: a `403 This API Key is revoked` on any REST
call means the key was revoked in Twenty. Create a new one there (Settings, APIs & Webhooks,
shown once) and run `task twenty:key:rotate TARGET=dev` (PR #353), which rewrites the env file,
both Duplo secret keys, and restarts the API.

The object has no `status` field; the lifecycle select is `lifecycleStatus` with upper-case
options. Create it in the dev Twenty UI (Patient Programs, new record) or via REST:

```bash
source scripts/verdict-env-vars.sh
uv run python - <<'PY'
import httpx, os
base, tok = os.environ["PULSE_TWENTY_DEV_URL"].rstrip("/"), os.environ["PULSE_TWENTY_DEV_TOKEN"]
h = {"Authorization": f"Bearer {tok}"}
q = httpx.get(f"{base}/rest/patientPrograms", headers=h,
              params={"filter": 'canonicalPatientId[eq]:"brook-fx-demo5-episode-0001"'}, timeout=30)
rows = q.json()["data"]["patientPrograms"]
if not any(r.get("programCode") == "demo5" for r in rows):
    r = httpx.post(f"{base}/rest/patientPrograms", headers=h, timeout=30,
                   json={"name": "Demo 5 fixture", "canonicalPatientId": "brook-fx-demo5-episode-0001",
                         "programCode": "demo5", "lifecycleStatus": "PENDING_START"})
    print(r.status_code)   # 201
PY
```

**Verify:** the preflight's `seeded-card` check in step 5 passes.

## 5. Stage the environment and preflight

The env file's `DATABASE_URL` names the private RDS host. Hand the staging script the relay DSN
from step 2 instead (override added in PR #353):

```bash
source scripts/verdict-env-vars.sh
export STAGE_E2E_DATABASE_URL="$(python3 -c "import os,urllib.parse as u; p=u.urlsplit(os.environ['DATABASE_URL']); print(u.urlunsplit((p.scheme, f'{p.username}:{p.password}@localhost:15432', p.path, p.query, p.fragment)))")"
task stage:e2e:live
```

This sources the scratch file, derives `DEMO5_SNOWFLAKE_*`, pulls the two missing tokens from
the Duplo secret by key prefix (`PULSE_LEDGER_WRITER_TOKEN_CUSTOMER_IO`, `PULSE_LEDGER_WRITER_TOKEN_TWENTY`),
prints `set` / `MISSING` per variable name, and runs the three preflight checks:

| Check | Passes when | If it fails |
|---|---|---|
| `api-image` | history route answers anything but 404 | step 1 not rolled |
| `ledger-schema` | `alembic_version_pulse_ledger` is `0005` | step 2 |
| `seeded-card` | the demo5 record exists on dev Twenty | step 4 |

Every failure is named in one run. Fix, rerun. It stops before any stage runs until all three
pass. Once they have passed for the day, `task stage:e2e:live -- --no-preflight` skips them.

### 5a. The warehouse feed must be alive before stage 5

Stage 5 reads `STREAMLINE.STG_EVENTS.EVENTS` once, with no wait, seconds after the relay
publishes. Anything landing late or not at all fails it. Check before the walk:

```bash
AWS_PROFILE=duplo-dev01 aws sqs get-queue-attributes \
  --queue-url "$(AWS_PROFILE=duplo-dev01 aws sqs get-queue-url --queue-name duploservices-dev01-brook-pulse-warehouse-sync --query QueueUrl --output text)" \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible --output text
k logs deploy/pulse-warehouse-sync --tail=5
```

A backlog with nothing in flight and a log that ends in `consumer_closed` means the consumer
died silently (Snowflake 390114 token expiry, DNA-1305). `k rollout restart
deployment/pulse-warehouse-sync`, wait for the backlog to reach 0, then run the walk. The
2026-09-02 run found it dead since 2026-08-29 with 25 messages waiting.

## 6. The walk

The same command continues straight into `demo:e2e:live` once preflight passes. Expected:

- Six stage headers in order, each ending `ok: <n> assertion(s), subjects=[...]`.
- `=== Demo 5: all stages passed ===`, exit 0.
- A receipt block: one JSON line per stage with `stage`, `assertion_count`, `subject_keys`.

Runbook assertions for 3.3, in the receipt or observable right after:

1. All six stages pass live.
2. The rebuild drill's receipt reports zero differences.
3. The rebuilt card shows on the dev board within the 60 s freshness budget.

A failed stage prints `FAILED at stage '<name>': <what went wrong>` and stops. Nothing later
runs. The message names stage, subject key, and field, never a value.

**A second full walk on the same day fails at stage 2** with `first sweep expected 1 declared
row, got 0`: the consent declaration is idempotent on the fixture row, and the dev ledger already
holds it from the first walk. The fixture subject is walked once per ledger. To finish a walk
that stopped after stage 4 (as the 2026-09-02 run did, on the warehouse feed), run the remaining
stages against the events already committed and say so in the receipt:

```bash
task stage:e2e:live -- --no-preflight --from-stage=window_agreement
```

`--from-stage` (PR #353) takes any stage name; stages 5 and 6 read committed state by subject
key and need nothing from the earlier stages' in-process receipts.

## 7. Record the receipt

1. Paste the receipt block (stage names, counts, subject keys, wait times) as a comment on #342.
   No payload values, no credential values, nothing resembling PHI. The data is synthetic.
2. Tell me it's posted. I commit it as `handoffs/pulse-demo-closeout/3.3-receipt.md` by PR,
   check off 3.3, run `task verify`, and archive the change.

## If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `stage: need exactly one key for prefix 'PULSE_LEDGER_WRITER_TOKEN_CUSTOMER'` | step 3 not done | mint and add the key |
| `api-image` 404 | old pod | step 1, then restart |
| `ledger:image` exit 139, `qemu: uncaught target signal 11` at step 5 | QEMU emulation, `uv` segfaults | enable Rosetta in Docker Desktop, rebuild |
| `docker push` `insufficient_scope: authorization failed` to `docker.io/library` | `task ledger:deploy` pushes the bare name | ECR login, tag, push per step 1 |
| stage 2 `CheckViolation ... ck_events_subject_type` | migration 0005 missing | step 2 |
| stage 2 401 on every declare | key added but pod not restarted, or wrong key name | restart; the name must be exactly `PULSE_LEDGER_WRITER_TOKEN_CUSTOMER_IO` |
| stage 3 cannot find the card | step 4 | seed the record |
| stage 6 rebuild differences ≠ 0 | projection consumer on dev lagging | wait 60 s, rerun with `--no-preflight` |
| `ledger-schema` `InsufficientPrivilege` | app role cannot read the migrator-owned version table | `GRANT SELECT ON public.alembic_version_pulse_ledger TO pulse_ledger_app` via the migrator DSN (done on dev 2026-09-02; durable home still to decide) |
| stage 5 `window 'warehouse' ... no state at field 'state'` | nothing landing in `STG_EVENTS.EVENTS`: `pulse-warehouse-sync` consume loop died on Snowflake 390114 token expiry and the pod stayed Running | check SQS depth (`duploservices-dev01-brook-pulse-warehouse-sync`), `kubectl rollout restart deployment/pulse-warehouse-sync`, wait for the backlog to drain, rerun |
| dev Twenty `403 This API Key is revoked` everywhere | one key in three homes, revoked in Twenty | `task twenty:key:rotate TARGET=dev` |
| stage 4 / stage 5 Postgres connect timeout from the laptop | env file DSN names the private RDS host | relay pod + `STAGE_E2E_DATABASE_URL` with a `localhost:15432` DSN (step 2) |
| `duploctl` JSON decode error | stale `stage_e2e_live.sh` | `git pull`; fixed in #350 |

Rollback is not needed for the walk itself: it writes only synthetic subjects to the dev ledger
and dev board. Reverting step 1 is re-pointing the service at the previous tag; step 3's key can
stay.
