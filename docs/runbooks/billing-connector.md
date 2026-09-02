# Runbook: billing-connector

Operator actions for the billing connector (`packages/billing-connector`, entrypoint
`billing_connector.service.main`): provisioning the feed, starting and stopping the dev deploy,
reading the receipt, and rebuilding a subject's evaluations from the ledger's own bus when the
engine's fact store falls behind or is suspect. Dev only (task 3.1) — no production deploy in
this change.

**Gate (WORKFLOW v2.2.0):** the PR carrying this runbook, the service JSON
(`packages/billing-connector/infra/duplo/billing-connector.service.json`), and the provisioning
script IS the G_APPROVAL surface. A human approving or merging that PR releases this procedure.
Execution happens once, after approval; the receipt lands on the tracking issue.

## What this service is, and is not

One process, one credential set, no HTTP surface: it consumes its own SQS queue
(`BILLING_CONNECTOR_QUEUE_URL`), folds every delivered event into the engine's `billing_engine`
Postgres store, evaluates the registered verdict types for `billing_episode`/`coverage` subjects,
and declares through the ledger's command API under its own writer credential
(`BILLING_CONNECTOR_TOKEN`). It holds no ledger database connection string — reads come off the
bus, writes go through the command API. `consent`/`enrollment` events fold into facts and count
`deferred`; they never trigger a declaration (`billing_connector.service.TRIGGER_SUBJECT_TYPES`,
design.md decision 4).

## Prerequisites

- AWS credential: `AWS_PROFILE=duplo-dev01` (duplo-jit session). PASS: `aws sts
  get-caller-identity --query Arn --output text` prints the tenant role ARN.
- Duplo portal token mintable: `duplo-jit duplo --host https://duplo.cloud.brook.ai
  --interactive` returns JSON with `DuploToken` (established pattern:
  `scripts/pulse-ledger/deploy.sh`).
- The connector's own ledger writer credential (`BILLING_CONNECTOR_TOKEN`'s value) and the
  engine's own Postgres credential (`BILLING_ENGINE_CREDENTIAL`'s value,
  `billing.consumer.CREDENTIAL_ENV_VAR`) — both vaulted, neither ever in this repo, a log, or a
  shell history file.

## Steps

1. **Provision the feed** (rule + queue + DLQ + policy, idempotent, self-proving — the narrow
   filter is design.md decision 7, see the script's header comment):

   ```bash
   AWS_PROFILE=duplo-dev01 ./scripts/billing-connector/provision_billing_feed.sh
   ```

   PASS: the script exits 0 printing `PASS: rule pulse-billing-connector -> queue
   duploservices-dev01-brook-pulse-billing-connector (DLQ ..., maxReceive 5) delivers
   billing_episode/coverage/consent/enrollment events.`
   FAIL: the script names the failing step and the first value to doubt.

2. **Build and push the image** (build context is the repo root):

   ```bash
   TAG=$(git rev-parse --short HEAD)
   aws ecr describe-repositories --repository-names billing-connector >/dev/null 2>&1 \
     || aws ecr create-repository --repository-name billing-connector >/dev/null
   aws ecr get-login-password | docker login --username AWS --password-stdin 173008660334.dkr.ecr.us-east-1.amazonaws.com
   task billing-connector:image TAG="${TAG}"
   docker tag billing-connector:${TAG} 173008660334.dkr.ecr.us-east-1.amazonaws.com/billing-connector:${TAG}
   docker push 173008660334.dkr.ecr.us-east-1.amazonaws.com/billing-connector:${TAG}
   ```

   PASS: `docker push` prints the digest. Then verify imports before deploying (cheaper than a
   crash loop): `docker run --rm --entrypoint python
   173008660334.dkr.ecr.us-east-1.amazonaws.com/billing-connector:${TAG} -c "import
   billing_connector.service; print('IMPORT OK')"` prints `IMPORT OK`.

3. **Create the secret** `pulse-billing-connector-secret` in namespace
   `duploservices-dev01-brook`, keys `BILLING_CONNECTOR_TOKEN` and `BILLING_ENGINE_CREDENTIAL`
   (values from the vaulted credentials — see the service README for what each name is).

   PASS: `kubectl -n duploservices-dev01-brook get secret pulse-billing-connector-secret -o
   jsonpath='{.data}' | python3 -c "import json,sys;
   print(sorted(json.load(sys.stdin).keys()))"` prints exactly `['BILLING_CONNECTOR_TOKEN',
   'BILLING_ENGINE_CREDENTIAL']`.

4. **Apply the Duplo service** (create-time `tojson` quirk applies — see the service README):

   ```bash
   TOKEN=$(duplo-jit duplo --host https://duplo.cloud.brook.ai --interactive 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["DuploToken"])')
   jq --arg image "173008660334.dkr.ecr.us-east-1.amazonaws.com/billing-connector:${TAG}" \
      '.DockerImage = $image | .OtherDockerConfig |= tojson' \
      packages/billing-connector/infra/duplo/billing-connector.service.json > /tmp/bc-rendered.json
   duploctl service apply --file /tmp/bc-rendered.json
   ```

   PASS: `{"message": "Successfully created service 'pulse-billing-connector'"}` (or updated),
   then within ~60s `kubectl -n duploservices-dev01-brook get pods | grep billing-connector`
   shows a `Running` pod.

## Start / stop

- **Start**: apply the service (step 4). `Replicas: 1` in the committed JSON — one consumer,
  since the engine's fact store has no concurrent-writer story beyond the connector's own
  per-subject idempotency.
- **Stop**: `duploctl service update pulse-billing-connector --replicas 0` (or delete the
  service). Messages already in flight redeliver per the queue's visibility timeout; nothing is
  lost — `store.apply_event`'s fold and the command API's D16 idempotency both make redelivery
  safe (`run_batch`'s "the fold found nothing new" disposition).
- **Restart on a bad deploy**: re-apply the previous `TAG`'s rendered JSON. Stateless besides the
  in-flight consume pass, which the queue's own redelivery covers.

## Reading the receipt

Every consume pass ends in one structured log line (`billing_connector.receipts.Receipt.
format_line`):

```
service=billing-connector committed=3 replayed=1 rejected=0 evaluated=4 deferred=2
```

| Count | Meaning |
| --- | --- |
| `committed` | New verdict/transition pairs the ledger committed this pass. |
| `replayed` | Idempotent replays — the ledger had already committed this declaration (D16). |
| `rejected` | A paired transition the ledger refused; the verdict half still commits (spec: "A rejected transition keeps its evidence"). Counted and logged with the ledger's reason, never retried. |
| `evaluated` | Evaluations produced this pass — one per registered verdict type applying to a triggering subject (`billing_episode`/`coverage`). |
| `deferred` | Events folded into facts but evaluated against nothing — `consent`/`enrollment`, or any subject type outside the trigger allowlist (design.md decision 4). |

A pass with `evaluated=0` on a `coverage` event is healthy, not a bug: the registry may list no
coverage-subject verdict type yet (`run_batch`'s docstring, disposition 3). A persistently
nonzero `deferred` count with no matching rise in `evaluated` once the consent/enrollment →
episode catalog fact lands (the fan-out proposal in 2.3's `HANDOFF.md`) is the signal that fact
never arrived — a catalog gap, not a connector bug.

## Rebuild-from-bus procedure

The engine's `billing_engine` fact store (and the `evaluations` rows the connector writes) is
derived entirely from the ledger's committed events — it holds no fact the bus does not also
carry. If it is suspect (a bad migration, a manual row edit, a restore from an older snapshot),
repaint one subject by replaying its committed history through the same handler the live consume
loop uses, exactly as `twenty_projection.rebuild` repaints a board row from the ledger's replay
route (`pulse_core.replay`) rather than trusting anything local.

There is no dedicated CLI for this today (unlike `task projection:rebuild`) — the connector's own
process is small enough that the replay is a short, auditable script an operator runs by hand,
against the target's credentials:

```python
import os

from billing.store import PostgresFactStore
from pulse_core.client import PulseCoreClient
from pulse_core.replay import replay_client_from_env

import psycopg
from billing_connector.config import Config
from billing_connector.service import WRITER_ID, resolve_registry, run_batch

config = Config.from_env()
registry = resolve_registry()
conn = psycopg.connect(os.environ["BILLING_ENGINE_CREDENTIAL"])
store = PostgresFactStore(conn)

replay = replay_client_from_env(writer_id=WRITER_ID)  # PULSE_CORE_BASE_URL / PULSE_CORE_REPLAY_TOKEN
history = replay.subject_history("billing_episode", "<subject-key>")  # or "coverage"

with PulseCoreClient(
    config.ledger_base_url, writer_id=WRITER_ID, token=os.environ[config.credential_name]
) as client:
    for envelope in history:
        receipt = run_batch(store, config, client, envelope, registry=registry)
        print(receipt.format_line())
```

PASS: the final receipt line's `evaluated` count matches the subject's registered verdict types,
and re-running the same replay produces an all-`replayed` receipt (the fold and D16 idempotency
both make the replay safe to run twice). Every event replays in ledger sequence
(`subject_history`'s own guarantee), so `run_batch` never sees an event out of order — the same
ordering the live queue delivers under, just read from the journal instead of the bus. This never
touches the queue or the DLQ; it is a read of the ledger's replay route and a re-drive of the
connector's own pure handler, safe to run against a live deploy without double-declaring anything.

## Rollback

Re-point the Duplo service at the previous image `TAG` (step 4 with the prior tag) or scale to
`Replicas: 0`. The feed (rule/queue/DLQ) is left in place — provisioning is idempotent and safe
to leave provisioned with no consumer running; messages accumulate on the queue and redeliver
once a consumer resumes, up to the queue's retention window.
