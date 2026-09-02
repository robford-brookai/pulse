# Duplo service definition — pulse-billing-connector

The billing connector (`python -m billing_connector.service`) as a Duplo service on tenant
`dev01-brook`, following the shapes verified for the pulse-ledger services
(`packages/pulse-ledger/infra/duplo/README.md` — read that first; every casing and quirk note
there applies here). Full deploy procedure: `docs/runbooks/billing-connector.md`.

## `billing-connector.service.json`

- `DockerImage` is the literal placeholder `__BILLING_CONNECTOR_IMAGE__`, substituted at apply
  time (`jq --arg image ... '.DockerImage = $image'`). Build context is the repo root:
  `docker buildx build --platform linux/amd64 -f packages/billing-connector/Dockerfile -t <ecr>/billing-connector:<tag> .`
- **Two credential names in one secret, `pulse-billing-connector-secret`** — deliberately NOT the
  shared `brook-flat-env-secret`. Keys, env-var **names** only (values live in Duplo/k8s, never
  here):
  - `BILLING_CONNECTOR_TOKEN` — this connector's own ledger writer credential
    (`billing_connector.config.TOKEN_ENV_VAR`), the one the credential-posture gate counts.
  - `BILLING_ENGINE_CREDENTIAL` — the engine's own Postgres connection string
    (`billing.consumer.CREDENTIAL_ENV_VAR`), read by `service.main()` to open the
    `billing_engine` fact store the fold and `evaluate_subject` share. Design-drift note from
    2.3 (`handoffs/billing-connector/SUMMARY.md`, PR #346): this is the engine's credential, not
    a second writer credential of the connector's own — the credential-posture gate discovers
    one writer identity here (`billing-connector`), the same posture `billing.consumer`'s own
    package boundary already holds for its side.
- `BILLING_CONNECTOR_QUEUE_URL` and `BILLING_CONNECTOR_LEDGER_BASE_URL` are plain `Env` values —
  addresses, not credentials. `BILLING_CONNECTOR_STALE_AFTER` is omitted: unset lets
  `Config.from_env()` fall back to its documented default (`config.py`'s `_DEFAULT_STALE_AFTER`);
  set it explicitly only once the dbt spike files land and pin a real recency window (seed gate
  3, `config.py`'s module docstring).
- No LB config: the connector serves nothing — it consumes its own SQS queue and declares
  through the command API over HTTP egress. Same posture `warehouse-sync`'s service definition
  documents for its own consumer.
- **Create-time quirk** (same as the relay and warehouse-sync): `duploctl service apply` on a
  not-yet-existing service rejects an object-valued `OtherDockerConfig` — render with
  `jq '.OtherDockerConfig |= tojson'` for the create; updates accept the object form.

Provisioning of the feed this service consumes (rule, queue, DLQ, policy) is
`scripts/billing-connector/provision_billing_feed.sh`; the full operator procedure is
`docs/runbooks/billing-connector.md`.
