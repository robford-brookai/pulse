# Retrieving the verdict-relay environment variables (dev target)

**Status:** Live — recorded from the 2026-08-28 first-run provisioning session | **Author:** Ford (recorded by Cline)
**Scope:** How to assemble the environment for `task relay:run TARGET=dev`
(= `uv run python -m schedules.cli verdict-relay-poll`). Variable *names* are pinned in
`packages/verdict-relay/src/verdict_relay/production.py`; values live outside this repo by
design (D15 posture) and nothing below records a value — only which store holds it and the
command that retrieves it. The same shape applies to staging/prod once those targets exist:
only the store contents change, never the variable names.

## The environment surface

| Variable | Source | Section |
|---|---|---|
| `VERDICT_RELAY_PULSE_CORE_BASE_URL` | Not stored anywhere — derived from the cluster (internal ClusterIP by design) | §4 |
| `VERDICT_RELAY_TOKEN` | Duplo secret `pulse-ledger-api-secret`, tenant `dev01-brook` (key `PULSE_LEDGER_WRITER_TOKEN_VERDICT_RELAY`) | §3 |
| `VERDICT_RELAY_SNOWFLAKE_ACCOUNT` | 1Password, item `SNOWFLAKE_ACCOUNT`, custom field `account` | §2 |
| `VERDICT_RELAY_SNOWFLAKE_USER` | 1Password, item `Snowflake`, field `username` | §2 |
| `VERDICT_RELAY_SNOWFLAKE_PASSWORD` | 1Password, item `Snowflake`, field `password` | §2 |
| `VERDICT_RELAY_SNOWFLAKE_WAREHOUSE` | Decided: `COMPUTE_WH` (streamline `snowflake/ddl/18_verdict_relay_reader.sql` grants it; fallback `PROD_WH_OPS` when running under the operator's personal role) | §2 |
| `VERDICT_RELAY_SNOWFLAKE_DATABASE` | Decided constant: `STREAMLINE` (DNA-1252; `docs/runbooks/billing-state.md`) | §1 |
| `VERDICT_RELAY_SNOWFLAKE_SCHEMA` | Decided constant: `OCEAN_MARTS` | §1 |
| `VERDICT_RELAY_SNOWFLAKE_TABLE` | Decided constant: `OCEAN_VERDICTS` | §1 |
| `DATABASE_URL` (dev ledger Postgres) | Same Duplo secret, key `DATABASE_URL` — not consumed by the poll itself (the relay is HTTP-only); for `month-open`/`consent-sweep` and psql inspection | §5 |

There is **no `VERDICT_RELAY_SNOWFLAKE_PRIVATE_KEY_PATH`**: the production wiring is
password-only (`production._snowflake_connect`). Keypair auth is proposed (branch
`feat/verdict-relay-keypair-auth`) but not landed; until it is, supply exactly one of the
two Snowflake secrets — the password — never both.

## 1. Decided constants — no retrieval

The dev mart address is decided, not a credential (`docs/runbooks/billing-state.md`,
DNA-1252, mart PR `Brookai/streamline#20`): `STREAMLINE` / `OCEAN_MARTS` /
`OCEAN_VERDICTS`. Export them verbatim.

## 2. Snowflake credential — 1Password

Prerequisite: `op` signed in (`op whoami`).

```bash
op item get SNOWFLAKE_ACCOUNT --fields account --reveal   # account locator
op item get Snowflake --fields username,password --reveal # user + password
```

Facts recorded 2026-08-28, so the next session does not rediscover them:

- The `SNOWFLAKE_ACCOUNT` item's standard `username`/`password` fields are **empty** — the
  locator lives in the *custom* field labelled `account`. Do not read the standard fields.
- The item `Snowflake` (Jan 2026) carries the operator's personal Snowflake login for the
  same account. It works for the mart read; it is not the scoped identity below.
- **Scoped reader identity:** streamline provisions `VERDICT_RELAY_DEV_SVC`
  (`streamline/snowflake/ddl/18_verdict_relay_reader.sql`) — password-auth (the account's
  BCR forbids passwords on TYPE=SERVICE users, and the relay wiring is password-only),
  `DEFAULT_WAREHOUSE = COMPUTE_WH`, read-only on the mart. Its password is set out-of-band
  (`ALTER USER ... SET PASSWORD`) and is recorded in no vault item as of 2026-08-28. To
  stop using the personal credential: set that password, add it to the `SNOWFLAKE_ACCOUNT`
  item, and switch `VERDICT_RELAY_SNOWFLAKE_USER`/`_PASSWORD` to it.
- Warehouse choice: `COMPUTE_WH` is the documented mart warehouse. When running under the
  operator's personal role, a `USAGE on COMPUTE_WH` refusal means export
  `PROD_WH_OPS` instead.

Never `export` these from a command line that lands in shell history; write them to a
chmod-600 file and `set -a; source` it (§6).

## 3. Writer token — Duplo secret `pulse-ledger-api-secret`

The relay's `VERDICT_RELAY_TOKEN` must equal the command API's registry entry
`PULSE_LEDGER_WRITER_TOKEN_VERDICT_RELAY` (D15: the API resolves the token to the writer id
`verdict-relay`; `packages/pulse-ledger/src/pulse_ledger/auth.py`). One value, two ends;
retrieve it from the deploy end:

```bash
TOKEN="$(duplo-jit duplo --host https://duplo.cloud.brook.ai --interactive \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["DuploToken"])')"
duploctl secret find pulse-ledger-api-secret \
  --host https://duplo.cloud.brook.ai --tenant dev01-brook --token "$TOKEN" --output json
# → .SecretData.PULSE_LEDGER_WRITER_TOKEN_VERDICT_RELAY
```

**First-run provisioning** (the key did not exist before 2026-08-28; it does now): mint
with `python3 -c 'import secrets; print(secrets.token_hex(32))'` and update the secret with
**all** keys — `duploctl secret update` replaces the whole set, so pass every existing key
plus the new one; updating with only the new key erases `DATABASE_URL` and crashloops the
API. Then **restart the service** (Duplo portal, or any redeploy): env from the secret is
injected at pod start, so a secret update is inert until a restart.

**The trap this creates:** a poll run before the token is live gets 401 on every
declaration, which the client classifies `rejected` — and rejected rows **advance the
cursor**, burning mart rows permanently. Verify the token is live (§4 health check, then a
one-row expectation) before running the poll against a fresh registry.

## 4. Base URL — derived, never stored

`packages/pulse-ledger/infra/duplo/command-api.lb.json` pins the API as an internal
ClusterIP with no public listener — there is no URL to retrieve. Options, best first:

1. **In-cluster:** `http://pulse-ledger-api.duploservices-dev01-brook.svc.cluster.local:8000`
2. **From the VPC** (the Orca host `i-0e0d5170c240c9b9d`,
   `.planning/reports/2026-08-13-orca-cloud-host-dev01-brook.md`): the pod IP, port 8000 —
   `GET https://duplo.cloud.brook.ai/subscriptions/<tenantid>/getpods` with the Duplo
   portal token, entry `pulse-ledger-api` → `Interfaces[0].IpAddress`. **The pod IP changes
   on every redeploy** — re-retrieve after any deploy.
3. **kubectl port-forward from the laptop — works, but only via the plan token.** The
   `duplo-dev01` duplo-jit AWS role authenticates at STS but is not mapped in the cluster's
   auth (`aws eks get-token` → 401 at API discovery; verified 2026-08-28). The **k8s plan
   token** is mapped (`duplo-admin-user` service account):

   ```bash
   TOKEN=$(duplo-jit k8s --host https://duplo.cloud.brook.ai --plan nonprod --interactive | jq -r .status.token)
   kubectl --token="$TOKEN" port-forward -n duploservices-dev01-brook svc/pulse-ledger-api 18000:8000
   ```

   The 2026-08-30 task-4.1 attended run ran entirely over this (API + a socat relay pod for
   RDS). One trap: a socat relay pod reaches RDS only from the node pool the API pod runs on —
   pin with `--overrides '{"spec":{"nodeName":...}}'` or the connect times out.

Credential-free health check: `GET <base>/health` (liveness only, per
`docs/runbooks/pulse-command-api-deploy.md` §6).

## 5. `DATABASE_URL` — dev ledger Postgres

Same Duplo secret, key `DATABASE_URL` (§3 commands): the `pulse_ledger_app` DSN on the
tenant's private RDS (reachable from the VPC only). The verdict-relay poll never reads it —
the cursor persists through the API's writer-cursor endpoint — but `month-open`,
`consent-sweep`, and ad-hoc psql inspection want it.

The **migrator** DSN is deliberately not here (privilege split):
`postgresql://pulse_ledger_migrator:<password>@<same host>/pulse_ledger`, where the
password is operator-provided at deploy time (`docs/runbooks/pulse-command-api-deploy.md`
§3). The original was never recorded; on 2026-08-30 it was reset via the RDS master
credential (`ALTER ROLE pulse_ledger_migrator PASSWORD ...`, Duplo portal → RDS →
`duplodev01-brook-dev` for the master login) and now lives in the gitignored
`scripts/verdict-env-vars.sh` as `PULSE_LEDGER_MIGRATOR_PASSWORD`. Migration 0004
(billing-state's `coverage` constraint widening) was applied with it that day.

## 6. Assembly and run

Stage values in a chmod-700 scratch directory with one chmod-600 file per store
(the 2026-08-28 session used `/tmp/relay-run/`): `snowflake.env`, `verdict_relay_token`,
`pulse-ledger-secrets.env`. Then, from the Orca host (the only place the base URL is
reachable), with the repo at `/home/ubuntu/workspace/pulse` and deps synced (`uv sync`):

```bash
set -a
source /tmp/relay-run/relay.env    # the nine VERDICT_RELAY_* exports
set +a
PATH=/home/ubuntu/.local/bin:$PATH uv run python -m schedules.cli verdict-relay-poll
```

Pre-flight: `resolve_production_config` fails startup naming the first missing variable —
an incomplete env never reaches a connection. A cursor already at the mart's watermark is
an all-zero receipt and exit 0, so a re-run is always safe **except** for the §3 trap
(unregistered token burns rows as `rejected`).

## Failure-mode quick reference

| Symptom | Cause | Fix |
|---|---|---|
| `MissingProductionVariableError: ... X is not set` | export missing | the table above |
| 401 / every declaration `rejected` | token not in the API's live env | §3: secret key present **and** pod restarted since |
| Snowflake `USAGE on warehouse` refusal | personal role lacks the granted warehouse | `PROD_WH_OPS` fallback (§2) |
| coverage rows fail commit (constraint) | billing-state migration not applied | §5: migrator DSN + `task ledger:migrate` |
| base URL unreachable from laptop | by design (internal ClusterIP) | run from the Orca host (§4) |
| stale pod IP after a deploy | pod recreated | re-retrieve from `getpods` (§4) |
