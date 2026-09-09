# Duplo service definition — pulse-warehouse-sync

The `warehouse-sync` consumer (OCEAN bus events → `STREAMLINE.OCEAN_RAW.EVENTS`) as a Duplo
service on tenant `dev01-brook`, following the shapes verified for the pulse-ledger services
(`packages/pulse-ledger/infra/duplo/README.md` — read that first; every casing and quirk note
there applies here).

## `warehouse-sync.service.json`

- `DockerImage` is the literal placeholder `__WAREHOUSE_SYNC_IMAGE__`, substituted at apply
  time (`jq --arg image ... '.DockerImage = $image'`). Build context is `packages/ocean/`:
  `docker build -f services/warehouse-sync/Dockerfile -t <ecr>/warehouse-sync:<tag> .`
- **Its own secret**, `pulse-warehouse-sync-secret` — never the shared flat secret. Keys, all
  env-var names only (values live in Duplo/k8s): `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`,
  `SNOWFLAKE_PRIVATE_KEY_PEM` (the unencrypted PKCS8 PEM, whole file as one value).
- **The private key reaches the connector as a file via a command wrapper, not a volume.**
  `main.py` reads `SNOWFLAKE_PRIVATE_KEY_PATH` as a file path; rather than introduce an
  unverified Duplo volume-mount shape, the service command writes `$SNOWFLAKE_PRIVATE_KEY_PEM`
  to `/tmp/sf.pem` (umask 077), unsets the env var, and execs uvicorn. One pod, one file,
  0600, gone with the pod. If a verified Duplo secret-volume shape lands later, switching to
  it is a drop-in (`SNOWFLAKE_PRIVATE_KEY_PATH` just points at the mount).
- `SQS_QUEUE_URL` is a plain `Env` value — a queue URL is an address, not a credential.
- Warehouse (`OCEAN_WH`), database (`STREAMLINE`), and schema (`OCEAN_RAW`) are hardcoded in
  `src/main.py` by design — the MERGE target is the published contract, not configuration.
- No LB config: the service serves only its own `/health` on 8008 in-cluster; the consumer is
  a background task started by the app's startup hook.
- **`livenessProbe` and `readinessProbe` on `/health`:8008**, the command-api shapes. `/health`
  is not a static ok — it reports the consume loop's heartbeat and returns 503 when that
  heartbeat is older than `HEALTH_STALE_AFTER_S` (default 30s, six long-poll cycles) or when
  the consumer task has finished. Liveness tolerates 6 failures at 10s (a 60s window), so a
  wedged pod restarts inside roughly 90s instead of sitting `1/1 Running` behind a backing-up
  queue (DNA-1259, DNA-1305). Readiness shares the same endpoint deliberately: the service
  takes no ingress, so readiness only gates rollout completion, and a pod that is up but not
  consuming should not read as ready either. Raising `HEALTH_STALE_AFTER_S` above the liveness
  window (`periodSeconds x failureThreshold`) re-opens the blind spot — a test asserts it stays
  under.
- **Create-time quirk** (same as the relay): `duploctl service apply` on a not-yet-existing
  service rejects an object-valued `OtherDockerConfig` — render with
  `jq '.OtherDockerConfig |= tojson'` for the create; updates accept the object form.

Provisioning of the feed this service consumes (rule, queue, DLQ, policy) is
`scripts/ocean/provision_warehouse_feed.sh`; the full operator procedure is
`docs/runbooks/warehouse-sync-revival.md`.
