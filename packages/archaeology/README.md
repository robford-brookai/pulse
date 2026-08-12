# archaeology

Read-only access seam to the legacy Mongo cluster (BF-0a). Every backfill discovery and
extraction flow goes through this package — BF-0b's discovery session first, the BF-5 bulk
extraction later.

## Inherited connection pattern

The connection posture is inherited from `brookai/streamline`'s Mongo CDC service, at
`repos/dacorom/mongo-stream/src/config.py` and `repos/dacorom/mongo-stream/src/watcher.py` in
that repo — not invented here:

- driver: sync `pymongo` (`>=4.8`), `MongoClient`;
- bounded network waits so a black-holed Atlas connection raises instead of wedging:
  `serverSelectionTimeoutMS` 30000, `connectTimeoutMS` 20000, `socketTimeoutMS` 600000
  (streamline's defaults, env-tunable here as there);
- TLS on by default (Atlas);
- env-sourced configuration that fails fast naming the missing variable names.

Divergences are deliberate and recorded in `docs/contracts/consumes.md`: credentials arrive as a
secret-store reference (never a literal connection string), and `retryWrites` is off because this
seam never writes.

## Hard precondition: read-only Atlas role

The database user this package connects as MUST be provisioned by the operator with a
**read-only Atlas role** (BF-0 operator setup item 4). That role is the control. The factory's
write-role refusal — construction fails when `connectionStatus` shows the resolved user holding a
write role — is defense in depth, not the control: on deployments where role detection is not
permitted, construction proceeds and the Atlas role is all that stands between this seam and a
write. Do not point these variables at any user that can write.

## Env var interface (BF-0a -> BF-0b)

These names are the interface the BF-0b discovery session consumes. Values live in the DuploCloud
secret store and the operator's session environment — never in this repo.

| Variable | Required | Meaning |
|---|---|---|
| `ARCHAEOLOGY_MONGO_HOST` | yes | cluster host (no scheme, no credentials) |
| `ARCHAEOLOGY_MONGO_USER` | yes | the read-only database user |
| `ARCHAEOLOGY_MONGO_PASSWORD_REF` | yes | secret-store reference, `env:NAME` or `file:PATH` — a literal value is refused |
| `ARCHAEOLOGY_MONGO_DB` | no | database to smoke against (default `prod`, streamline's default) |
| `ARCHAEOLOGY_MONGO_TLS` | no | `true`/`false` (default `true`) |
| `ARCHAEOLOGY_MONGO_SERVER_SELECTION_TIMEOUT_MS` | no | default `30000` (streamline) |
| `ARCHAEOLOGY_MONGO_CONNECT_TIMEOUT_MS` | no | default `20000` (streamline) |
| `ARCHAEOLOGY_MONGO_SOCKET_TIMEOUT_MS` | no | default `600000` (streamline) |

Missing required variables fail fast, naming every missing name (never a value) in one raise.

## Smoke receipt

```bash
python -m archaeology.smoke --list-collections
```

Prints collection names only — no field values, no documents — and its **exit status is the
access receipt** BF-0b requires: `0` means the seam works end to end. Any credential material in
the tree is caught by the repository-wide gate in `tests/test_credential_gate.py`, which runs in
`task test`.

## Bulk-extraction seam (BF-5)

Nothing in this package is throwaway: the same client factory becomes the bulk-extraction seam
when BF-5 lands the Stage 2 ledger backfill. Extraction code belongs here, behind the same
read-only, env-var-credentialed construction — not in a new connection path.
