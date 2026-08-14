## Why

Every Twenty-facing surface in this repo — the metadata artifact, the `POST /webhooks/twenty`
ingress, the comment adapter — is written against a contract that has never touched a running
Twenty. `docs/contracts/consumes.md` says so outright: no tag is pinned, because no instance
exists. `pulse-app-scaffold` tasks 4.1 and 4.2 are marked `GATED: DNA-909` and cannot dispatch
until one does.

Reading Twenty's own source (its docs are stale in at least two places) found the pinned contract
wrong in ways that are not cosmetic: the webhook signing scheme differs in six respects, one of
which — millisecond timestamps against a seconds-based freshness window — would reject every
delivery ever sent. A second finding may invalidate the metadata deploy path wholesale. Standing
the instance up is therefore first live contact, not "deploy a server", and surfacing those
mismatches against something real is the point.

## What Changes

- Provision a Twenty dev instance on DuploCloud EKS (tenant `dev01-brook`), with its app database
  on the existing tenant RDS and a dedicated Redis, pinned to `twenty/v2.30.0` + `sdk/v2.30.0`.
- **Probe first, build second.** Before anything is built on top of the instance, establish
  whether `universalIdentifier` round-trips through the Metadata API. It is annotated
  `@HideField()` in Twenty's source, which — if it holds on the pinned version — means
  `pulse_core.twenty_deploy`'s idempotency premise fails and the model must go through
  `app:publish` instead. Everything downstream is gated on that answer.
- **BREAKING** — realign the webhook contract to Twenty's native scheme rather than adding a
  compatibility shim: real header names (`X-Twenty-Webhook-Signature`/`-Timestamp`/`-Nonce`),
  bare hex HMAC over `{timestamp}:{body}` with no version affixes, and millisecond timestamps.
  Any existing caller signing the old way stops verifying.
- Realign drag mapping to the real payload: `eventName` gating rather than `eventType`,
  `updatedFields` as a name list with values read from a flat `record`, flat `workspaceMemberId`,
  and `record.updatedAt` standing in for the per-delivery event id Twenty does not send.
- Add two denormalized TEXT fields (`canonicalPatientId`, `programCode`) to `patientProgram`,
  because the webhook's `record` is the flat ORM entity and nested paths cannot resolve.
- Add a serving layer: a real entrypoint, container image, and a migrator/app role split so the
  API credential physically cannot mutate the ledger or run DDL.
- Add a Twenty seed loader driven by a committed deterministic synthetic projection.
- Reshape the local `define.ts` stand-in to mirror Twenty's real `ViewManifestType`, and add the
  kanban view plus the navigation item without which the board is unreachable.

## Capabilities

### New Capabilities

- `command-api-serving`: how the command API is actually served — process entrypoint, liveness,
  connection pooling, and the database role split that keeps the serving credential incapable of
  DDL or ledger mutation.
- `twenty-seed-load`: loading a deterministic synthetic population into a Twenty instance
  idempotently on natural keys, create-if-absent and patch-if-drifted, never deleting.

### Modified Capabilities

- `twenty-webhook-auth`: the signature scheme itself changes — header names, message construction,
  digest encoding, and timestamp unit. Freshness, dual-secret rotation, and principal attribution
  keep their current requirements; only the wire format they operate on is restated.
- `twenty-drag-command`: the payload shape a drag is recognized from and the identifiers a subject
  resolves through both change, and redelivery idempotency must rest on `record.updatedAt` because
  no per-delivery event id exists.

## Impact

**Code.** `pulse_ledger.auth` (header constants, `sign`, freshness unit), `pulse_ledger.twenty.mapping`
(envelope, flat record, logical time), all nine webhook fixtures under
`packages/pulse-ledger/tests/fixtures/twenty/` re-cut from a captured live delivery, new
`pulse_ledger.api_server` and Dockerfile, new `pulse_core.twenty_seed`, `pulse_core.twenty_model`
gaining view UID keys and the denormalized fields, and `packages/twenty-app` reshaped to
`ViewManifestType` with a new kanban view and navigation item.

**Contracts.** `docs/contracts/consumes.md` gains the pinned Twenty tag and the answer to the
`universalIdentifier` probe — the entry that currently says no instance exists.

**Dependencies.** `twenty-sdk` pinned exactly, which wants node `^24.5.0` and TypeScript `^5.9.3`
against this repo's node `>=22` and `typescript@7.0.2`. The shape change lands before the
dependency change so the two blast radii stay separate.

**Taskfile.** New credentialed targets (`ledger:image`, `ledger:migrate`, `ledger:deploy`,
`twenty:app:build`, `twenty:app:publish`, `twenty:seed`) all stay unreachable from `check`, which
remains offline and credential-free at every step.

**Not settled here.** This provisions dev only. `environment-matrix` and the promotion path are a
later change. ADR-0004's D14 (SPCS as the deployment target) is **not** closed by deploying dev to
EKS; the runbook must say so out loud, because `docs/adr/` is append-only and the roadmap still
lists `pulse-spcs-deployment`. Abandoning SPCS would need a new ADR and a status flip, not a quiet
EKS deploy.

**Rollback.** Every step is reversible without data loss, because the instance is synthetic-only
and the ledger is append-only. The Twenty instance is deleted by removing its EKS workloads and
dropping the `twenty` database; nothing else depends on it. The auth and mapping changes are a
single revert — but note they are a matched pair with the re-cut fixtures, so reverting one
without the other leaves the suite red. Metadata operations never delete, so a failed
`twenty:deploy` leaves the workspace as it was rather than half-torn-down. The RDS security-group
ingress for the EKS node SG and the disabled SSRF guard are the two changes that outlive a
rollback and must be reverted deliberately.

**Risk that reshapes the plan.** If the `universalIdentifier` probe comes back negative, the
in-flight `pulse-app-scaffold` change's `twenty-artifact-deploy` spec is built on a premise that
does not hold, and this change stops to re-plan rather than proceeding to apply the artifact.
