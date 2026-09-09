# Runbook — warehouse-sync revival (snowflake-projection 2.1)

Revive the ledger → Snowflake feed: provision the EventBridge → SQS leg, deploy the
`warehouse-sync` consumer as a Duplo service, apply the STG_EVENTS view, and prove the chain
end to end. One operator session, dev tenant only (`dev01-brook`, AWS `173008660334`,
`us-east-1`). Every step carries its own PASS/FAIL assertion — run them in order; a FAIL stops
the run at that step.

**Gate (WORKFLOW v2.0.7):** the PR carrying this runbook, the service JSON
(`packages/ocean/services/warehouse-sync/infra/duplo/warehouse-sync.service.json`), and the
provisioning script IS the G_APPROVAL surface. A human approving or merging that PR releases
this procedure. Execution happens once, after approval; the receipt lands on the tracking
issue (DNA-1246), and the `min_complete_from` stamp in `docs/contracts/publishes.md` rides the
same PR before it merges.

## Prerequisites

- AWS credential: `AWS_PROFILE=duplo-dev01` (duplo-jit session). PASS: `aws sts
  get-caller-identity --query Arn --output text` prints the tenant role ARN.
- Duplo portal token mintable: `duplo-jit duplo --host https://duplo.cloud.brook.ai
  --interactive` returns JSON with `DuploToken` (established pattern:
  `scripts/pulse-ledger/deploy.sh`).
- A Snowflake service credential for the writer: account locator, user, and an unencrypted
  PKCS8 private key whose public half is registered on that user, with INSERT/MERGE on
  `STREAMLINE.OCEAN_RAW.EVENTS` and CREATE VIEW on `STREAMLINE.STG_EVENTS` (or the view is
  applied by a separately privileged operator in step 6). **Key material never enters the
  repo, a log, or a shell history file** — export it into the environment from wherever it is
  vaulted.

## Steps

1. **Provision the feed** (rule + queue + DLQ + policy, idempotent, self-proving):

   ```bash
   AWS_PROFILE=duplo-dev01 ./scripts/ocean/provision_warehouse_feed.sh
   ```

   PASS: the script exits 0 printing `PASS: rule pulse-warehouse-sync -> queue
   duploservices-dev01-brook-pulse-warehouse-sync (DLQ ..., maxReceive 5) delivers.`
   FAIL: the script names the failing step and the first value to doubt.

2. **Build and push the image** (build context is `packages/ocean/`):

   ```bash
   cd packages/ocean
   TAG=$(git rev-parse --short HEAD)
   aws ecr describe-repositories --repository-names warehouse-sync >/dev/null 2>&1 \
     || aws ecr create-repository --repository-name warehouse-sync >/dev/null
   aws ecr get-login-password | docker login --username AWS --password-stdin 173008660334.dkr.ecr.us-east-1.amazonaws.com
   docker build -f services/warehouse-sync/Dockerfile -t 173008660334.dkr.ecr.us-east-1.amazonaws.com/warehouse-sync:${TAG} .
   docker push 173008660334.dkr.ecr.us-east-1.amazonaws.com/warehouse-sync:${TAG}
   ```

   PASS: `docker push` prints the digest. Then verify imports before deploying (cheaper than a
   crash loop): `docker run --rm --entrypoint python
   173008660334.dkr.ecr.us-east-1.amazonaws.com/warehouse-sync:${TAG} -c "import src.main;
   print('IMPORT OK')"` prints `IMPORT OK`.

3. **Create the secret** `pulse-warehouse-sync-secret` in namespace
   `duploservices-dev01-brook`, keys `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`,
   `SNOWFLAKE_PRIVATE_KEY_PEM` (values from the vaulted credential; the PEM is the whole file
   as one value).

   PASS: `kubectl -n duploservices-dev01-brook get secret pulse-warehouse-sync-secret -o
   jsonpath='{.data}' | python3 -c "import json,sys;
   print(sorted(json.load(sys.stdin).keys()))"` prints exactly `['SNOWFLAKE_ACCOUNT',
   'SNOWFLAKE_PRIVATE_KEY_PEM', 'SNOWFLAKE_USER']`.

4. **Apply the Duplo service** (create-time `tojson` quirk applies — see the service README):

   ```bash
   TOKEN=$(duplo-jit duplo --host https://duplo.cloud.brook.ai --interactive 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["DuploToken"])')
   jq --arg image "173008660334.dkr.ecr.us-east-1.amazonaws.com/warehouse-sync:${TAG}" \
      '.DockerImage = $image | .OtherDockerConfig |= tojson' \
      packages/ocean/services/warehouse-sync/infra/duplo/warehouse-sync.service.json > /tmp/ws-rendered.json
   duploctl service apply --file /tmp/ws-rendered.json
   ```

   PASS: `{"message": "Successfully created service 'pulse-warehouse-sync'"}` (or updated),
   then within ~60s `kubectl -n duploservices-dev01-brook get pods | grep warehouse-sync`
   shows `1/1 Running`, and the pod log contains `consumer_started` with the queue URL.
   FAIL: pod log contains `consumer_exited` — read its error before touching anything else.

5. **Prove the running image is the one that survives a token expiry.** The two liveness fixes
   landed separately: PR #296 (`5129d4f`) made a *dying* consumer exit nonzero, and this PR adds
   the reconnect and the real `/health`. A pod running an image built before either merge has
   the old failure mode however healthy it looks, so read the tag off the pod and place it
   against both merge commits before believing any other PASS below.

   ```bash
   RUNNING=$(kubectl -n duploservices-dev01-brook get pods -l app=pulse-warehouse-sync \
     -o jsonpath='{.items[0].spec.containers[0].image}')
   echo "running: ${RUNNING}"
   git merge-base --is-ancestor 5129d4f "${RUNNING##*:}" && echo "has #296 (exit-on-death)"
   git merge-base --is-ancestor <this-PR-merge-sha> "${RUNNING##*:}" && echo "has DNA-1305 (reconnect + probes)"
   ```

   PASS: both `git merge-base --is-ancestor` checks exit 0 (the tag is a short SHA on `main`
   that descends from both merges), **and** the pod spec carries the probes:
   `kubectl -n duploservices-dev01-brook get pod -l app=pulse-warehouse-sync -o
   jsonpath='{.items[0].spec.containers[0].livenessProbe.httpGet.path}'` prints `/health`.
   FAIL, either check: the deployed image predates a fix — rebuild and re-apply (steps 2 and 4)
   before diagnosing anything else. A tag that is not a commit on `main` (a local build, a
   hand-typed tag) is also a FAIL: it cannot be placed, so it cannot be trusted.

6. **Health semantics — what a green probe now asserts.** `/health` is no longer a static ok.
   It reports the consume loop's heartbeat, which the loop stamps on every iteration including
   idle polls, and returns 503 when that heartbeat is older than `HEALTH_STALE_AFTER_S`
   (default 30s) or when the consumer task has finished. Liveness tolerates 6 failures at 10s,
   so a wedged pod is restarted within roughly 90s of going quiet.

   PASS: `kubectl -n duploservices-dev01-brook exec deploy/pulse-warehouse-sync -- \
   python -c "import urllib.request,json; print(json.load(urllib.request.urlopen('http://localhost:8008/health')))"`
   prints `status: ok` with a `heartbeat_age_s` in single-digit seconds — an idle queue included,
   which is the point. A 503 with `reason: heartbeat_stale` means the loop has stopped turning
   and the probe is about to restart the pod; read the logs before it does.

7. **Apply the STG_EVENTS view**: `task snowflake:stg-events` (the target 1.1 shipped).
   PASS: the target exits 0; `SELECT COUNT(*) FROM STREAMLINE.INFORMATION_SCHEMA.VIEWS WHERE
   TABLE_SCHEMA='STG_EVENTS' AND TABLE_NAME='EVENTS'` returns 1.

8. **Live proof — one committed event lands, once.** Drive one committed ledger event (any
   legal drag on the dev Twenty board, or a `declare_transition` via the command API), note
   its `event_id`, then:

   - PASS (landing): within ~2 minutes, `SELECT COUNT(*) FROM STREAMLINE.OCEAN_RAW.EVENTS
     WHERE data:event_id = '<event_id>'` returns **1**, and the same query against
     `STREAMLINE.STG_EVENTS.EVENTS` (column `event_id`) returns **1**.
   - **Redelivery no-dup**: re-send the same envelope onto the bus (`aws events put-events`
     with the identical detail). PASS: both counts above still return **1**.
   - **Freshness**: `SELECT TIMESTAMPDIFF('minute', MAX(_loaded_at), CURRENT_TIMESTAMP())
     FROM STREAMLINE.OCEAN_RAW.EVENTS` returns a single-digit number of minutes. Record it.

9. **Stamp the watermark**: replace the `` `stamped-at-revival` `` placeholder in
   `docs/contracts/publishes.md` with today's date, commit onto this runbook's PR branch.

10. **Receipt** on DNA-1246: rule ARN, queue URL + ARN, DLQ URL, service name + image tag +
    pod name, the running-image verdict from step 5, the proven `event_id`, both row counts
    before/after redelivery, and the freshness figure — every value spelled out, no ellipses.

## Diagnostic signatures

Read the pod log and the restart count together; the pair names the failure, and one alone
never does.

| Log | Restarts | Reading |
| --- | --- | --- |
| `consumer_started`, then nothing, pod `1/1 Running` | 0 | **Old wedge.** The image predates DNA-1305: the loop is blocked inside a Snowflake call, the task never completes, so nothing exits and nothing probes it. Confirm with step 5; the fix is to deploy, not to restart. |
| `consumer_closed` with no `consumer_exited` | 0 | Same wedge one step later — the loop left, `finally` ran, and the process stayed up serving a static-green `/health`. Only on pre-DNA-1305 images. |
| `health_stale`, then a restart | ≥1 | **Working as designed.** The heartbeat aged past `HEALTH_STALE_AFTER_S` and liveness restarted the pod. Look for what stalled it; the service recovered on its own. |
| `snowflake_token_expired` then `snowflake_reconnected`, batch merges continue | 0 | **Working as designed.** A session token lapsed and the loop reconnected and retried the batch. Nothing to do. |
| `consumer_exited` with errno 390114 | ≥1 | Two consecutive expiries: the fresh session was already invalid. Suspect the credential itself — key rotated, user disabled, clock skew — not the loop. |
| `consumer_exited` with any other error | ≥1 | A real Snowflake or process fault. The batch was not deleted and redelivers; read the error before redeploying. |
| `sqs_receive_failed` repeating, no merges | 0 | A genuine transport fault (the arm is now narrowed to botocore errors). Check the queue URL, the tenant role, and network egress. |

## Rollback

`aws events remove-targets --event-bus-name duploservices-dev01-brook-ocean --rule
pulse-warehouse-sync --ids warehouse-queue && aws events delete-rule --event-bus-name
duploservices-dev01-brook-ocean --name pulse-warehouse-sync`, delete the Duplo service
`pulse-warehouse-sync`, leave the queues (they drain and idle at zero cost). The landing table
keeps every row it received; nothing ledger-side changed.
