# Duplo service definitions — pulse-ledger command API

Shapes verified against the live tenant `dev01-brook` (AWS `173008660334`, `us-east-1`, EKS
cluster `duploinfra-nonprod`, namespace `duploservices-dev01-brook`) while authoring this change.
Full deploy procedure: `docs/runbooks/pulse-command-api-deploy.md`.

## `command-api.service.json`

The `ReplicationController` body `duploctl service apply --file` idempotently creates or updates
(create-if-absent, update-if-drifted — the same posture `task twenty:deploy` already documents for
its own artifact).

- `AgentPlatform: 7` is EKS-linux — 25 of the tenant's 26 services already run on it.
- `DockerImage` is the literal placeholder `__PULSE_LEDGER_IMAGE__`. `scripts/pulse-ledger/deploy.sh`
  substitutes the real `<ECR repo>:<tag>` (the tag `task ledger:image TAG=...` built) before
  applying — the committed file never names an image digest or tag, both of which change every
  deploy and neither of which belongs in git history for a mutable service.
- `OtherDockerConfig`'s key casing is mixed, verified on the tenant's `identity` service, and is
  the single easiest thing to get wrong here:
  - **PascalCase**: `EnvFrom`, `Env`, `Volumes`, `VolumesMounts` (this service uses neither
    volume key — it is stateless).
  - **camelCase**: `resources`, `startupProbe`, `livenessProbe`, `readinessProbe`, `lifecycle`.
  - `EnvFrom`'s nested `secretRef` is camelCase *inside* the PascalCase key —
    `"EnvFrom": [{"secretRef": {"name": "..."}}]`, copied verbatim from `identity`.
- **Its own secret**, `pulse-ledger-api-secret` — deliberately NOT the shared
  `brook-flat-env-secret` several tenant services mount wholesale. A credential blast radius of
  one pod is the point; see the runbook for what goes in it (env var *names* only — never here).
- `PULSE_LEDGER_TWENTY_WEBHOOK_ENABLED` is a non-secret switch and sits in plain `Env`, committed,
  because it is not a credential — everything with a value that IS one goes in the secret,
  referenced by name only through `EnvFrom`.
- `readinessProbe`/`livenessProbe` and `resources` are the exact nested shapes observed on
  `identity`, copied verbatim rather than re-derived.

## `command-api.lb.json`

There is no file-driven `duploctl` command for an `LBConfiguration` — only the flag-based
`duploctl service expose`, which the deploy script drives from this file's fields (`jq` extracts
them; `LbType: 3` maps back to the CLI's `--lb-type k8clusterip`). The file exists anyway as the
single committed source of truth for the shape, in the same wire-level terms Duplo's
`LBConfigurationUpdate` endpoint accepts, so a reviewer can see the whole exposure decision as a
diff instead of reading it out of a shell script's flags.

**Internal only, deliberately**: `LbType: 3` (`k8clusterip`) and `IsInternal: true` — ClusterIP, no
ALB rule, no hostname, no certificate, no internet-facing listener. Twenty reaches this service
in-cluster at `http://pulse-ledger-api.duploservices-dev01-brook.svc.cluster.local:8000/webhooks/twenty`.
That path is HMAC-authenticated (`pulse_ledger.auth.TwentyWebhookConfig`), holds no PHI in dev, and
nothing outside the cluster calls it — there is no reason for this LB config to ever gain a public
listener, and adding one silently would be a networking regression, not a feature.
`IsInternal: true` is supported today: the tenant's `sftp` service already runs with it.
