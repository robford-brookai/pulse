# Demo 5 — attended live run on dev (pulse-demo-closeout 3.3)

**Date:** 2026-09-02 · **Tracking issue:** #342 · **Main:** `41ad18d` · **Runbook:**
`docs/runbooks/demo5-end-to-end.md` §Running it live, §Staging the live run

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
- Docker is running (only needed if you build the image yourself in step 1).

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

**Verify:** the history route is served. Any status but 404 means the new image is up.

```bash
source scripts/verdict-env-vars.sh
curl -s -o /dev/null -w '%{http_code}\n' "$PULSE_LEDGER_API_URL/subjects/preflight/preflight/events"
# 401 or 200 = new image; 404 = still the old pod
```

## 2. Apply migration 0005

Use the migrator DSN, not the app DSN (privilege split, env-vars process doc §5). The migrator
password is in the scratch file as `PULSE_LEDGER_MIGRATOR_PASSWORD`; the host is the app DSN's.

```bash
DATABASE_URL="postgresql://pulse_ledger_migrator:${PULSE_LEDGER_MIGRATOR_PASSWORD}@<host from DATABASE_URL>/pulse_ledger" \
  task ledger:migrate
```

**Verify:** `SELECT version_num FROM alembic_version;` returns `0005`. The preflight in step 6
checks this too.

## 3. Mint the consent writer credential

The API registers writers from `PULSE_LEDGER_WRITER_TOKEN_<SUFFIX>`; the suffix `CUSTOMER_IO`
becomes the writer id `customer-io`, which the ingress now uses (#352).

1. Mint: `python3 -c 'import secrets; print(secrets.token_hex(32))'`
2. Get a Duplo session and read the current secret (values stay in your terminal, never in a file):

   ```bash
   TOKEN="$(duplo-jit duplo --host https://duplo.cloud.brook.ai --interactive \
     | python3 -c 'import json,sys; print(json.load(sys.stdin)["DuploToken"])')"
   duploctl secret find pulse-ledger-api-secret \
     --host https://duplo.cloud.brook.ai --tenant dev01-brook --token "$TOKEN" --output json
   ```

3. Update the secret with **every existing key plus** `PULSE_LEDGER_WRITER_TOKEN_CUSTOMER_IO`.
   `duploctl secret update` replaces the whole set; updating with only the new key erases
   `DATABASE_URL` and crashloops the API (env-vars process doc §3).
4. Restart the `pulse-ledger-api` service in the Duplo portal. The secret is read at pod start.

**Verify:** re-run `duploctl secret find ...` and confirm the key name is listed. Then check the
API rejects the new token cleanly rather than 404ing:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer <the minted value, from your clipboard>" \
  "$PULSE_LEDGER_API_URL/subjects/preflight/preflight/events"
# 200 = registered writer; 401 = pod not restarted yet or key name wrong
```

## 4. Seed the demo card on dev Twenty

Stage 3 drags a card that must already exist: a `patientPrograms` record with
`canonicalPatientId = brook-fx-demo5-episode-0001` and `programCode = demo5`. The committed
Twenty seed (`task twenty:seed TARGET=dev`) does not include it.

Create it in the dev Twenty UI (Patient Programs → new record, those two fields, status
`pending_start`), or via the REST API:

```bash
uv run python - <<'PY'
import httpx, os
base, tok = os.environ["PULSE_TWENTY_DEV_URL"].rstrip("/"), os.environ["PULSE_TWENTY_DEV_TOKEN"]
r = httpx.post(f"{base}/rest/patientPrograms", headers={"Authorization": f"Bearer {tok}"},
               json={"canonicalPatientId": "brook-fx-demo5-episode-0001", "programCode": "demo5"}, timeout=30)
print(r.status_code)
PY
```

**Verify:** the preflight's `seeded-card` check in step 6 passes.

## 5. Stage the environment and preflight

```bash
task stage:e2e:live
```

This sources the scratch file, derives `DEMO5_SNOWFLAKE_*`, pulls the two missing tokens from
the Duplo secret by key prefix (`PULSE_LEDGER_WRITER_TOKEN_CUSTOMER_IO`, `PULSE_LEDGER_WRITER_TOKEN_TWENTY`),
prints `set` / `MISSING` per variable name, and runs the three preflight checks:

| Check | Passes when | If it fails |
|---|---|---|
| `api-image` | history route answers anything but 404 | step 1 not rolled |
| `ledger-schema` | `alembic_version` is `0005` | step 2 |
| `seeded-card` | the demo5 record exists on dev Twenty | step 4 |

Every failure is named in one run. Fix, rerun. It stops before any stage runs until all three
pass. Once they have passed for the day, `task stage:e2e:live -- --no-preflight` skips them.

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
| `duploctl` JSON decode error | stale `stage_e2e_live.sh` | `git pull`; fixed in #350 |

Rollback is not needed for the walk itself: it writes only synthetic subjects to the dev ledger
and dev board. Reverting step 1 is re-pointing the service at the previous tag; step 3's key can
stay.
