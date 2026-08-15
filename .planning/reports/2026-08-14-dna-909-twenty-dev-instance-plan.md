# DNA-909 — Provision the Twenty dev instance and prove a kanban drag round-trip

> **Provenance.** Authored on the Mac as `~/.claude/plans/jaunty-forging-allen.md` and moved
> here by paste (scp was blocked on `authorized_keys`). Terminal wrapping damaged several
> section headings in transit — `Verification`, `Risks`, `Change lifecycle`, and the
> `Governance note` heading were reconstructed, and risk items 3 and 8 lost their numbers.
> Body text is otherwise verbatim. **The Mac copy is authoritative** until someone
> re-transfers it cleanly.

## Context

v3.0 "Projections" (Phase 3) is gated on a Twenty dev instance. `pulse-app-scaffold` wave 3
(tasks 4.1, 4.2) is marked `GATED: DNA-909` and cannot dispatch until one exists. Everything
Twenty-facing in this repo — the 51-operation metadata artifact, the `POST /webhooks/twenty`
ingress, the comment adapter — is written against a pinned but never live-verified contract.
`docs/contracts/consumes.md` says so outright: "no tag is pinned here yet, because no instance
exists."

So this is first live contact, not "stand up a server." Exploration against Twenty's own
source (not its docs, which are stale in at least two places) found that the pins are wrong in
more ways than expected — including one that may invalidate `twenty_deploy` entirely. Surfacing
those is the actual value of this ticket.

Decisions taken (Rob, this session):

- Host on DuploCloud EKS, tenant `dev01-brook`.
- Twenty's app database on the existing tenant RDS `duplodev01-brook-dev`.
- Scope is the full literal drag, including the missing pieces.
- Fix the webhook mismatch by adapting pulse to Twenty's native scheme — no compat flag, no
  translating adapter.
- Capture a real delivery before writing mapping code.

Non-goal: this does not settle Twenty's production hosting
(`packages/ocean/docs/headless-prm-pt-enroll-status.md` §6.0 — SPCS default-deny egress vs EKS
default-allow). Dev-on-EKS is sanctioned by `design/platform/pulse-app-scaffold.md:151`, which
permits "a non-Snowflake managed Postgres" for synthetic-only tiers.

---

## Findings

### F1 — `universalIdentifier` may not be settable through the Metadata API (highest consequence)

In `twenty-server/.../object-metadata/dtos/create-object.input.ts`, `universalIdentifier` is
annotated `@HideField()` — not exposed on the GraphQL metadata schema, and the REST metadata
API wraps those same resolvers. It appears to be populated by the app-sync path, not by API
clients.

If that holds on the pinned version, `pulse_core.twenty_deploy`'s central premise fails:
the artifact's UUIDs are silently dropped on create, and the second run creates duplicates
instead of no-ops. The whole "idempotent, keyed on `universalIdentifier`" design would be
superseded by `app:publish` for the entire model.

This is the first thing to probe on the fresh instance, before building anything on top of
it. Everything downstream reshapes around the answer.

### F2 — The webhook contract is wrong in six ways

Ground truth: `twenty-server/.../webhook/jobs/call-webhook.job.ts`,
`transform-event-batch-to-webhook-events.ts`, `transform-event-to-webhook-event.ts`.

```js
headers['X-Twenty-Webhook-Timestamp'] = Date.now().toString();   // MILLISECONDS
headers['X-Twenty-Webhook-Signature'] = crypto.createHmac('sha256', secret)
  .update(`${timestamp}:${JSON.stringify(payload)}`).digest('hex');
headers['X-Twenty-Webhook-Nonce'] = crypto.randomBytes(16).toString('hex');
```

| pulse expects | Twenty sends | Pin |
|---|---|---|
| `X-Pulse-Signature` / `X-Pulse-Timestamp` | `X-Twenty-Webhook-Signature` / `-Timestamp` / `-Nonce` | `auth.py:68-69` |
| `"v1=" + HMAC(secret, b"v1:{ts}:" + body)` | `HMAC(secret, "{ts}:{body}")` hex, no affixes | `auth.py:293-296` |
| timestamp in seconds | timestamp in milliseconds | `auth.py _is_fresh` |
| `eventType == "record.updated"` | `eventName == "patientProgram.updated"` | `mapping.py:56` |
| `updatedFields[].name/.after` | `updatedFields: string[]`; value in `record.<field>` | `mapping.py:279-294` |
| `eventId` → D16 idempotency key | no per-delivery event id exists | `mapping.py` |
| `workspaceMember.id` | flat `workspaceMemberId` | `mapping.py` |

The milliseconds one is quietly fatal on its own: every delivery would fail the 5-minute
freshness window by ~55,000 years.

Twenty's signing is fixed in server code with no configuration hook, so pulse must adapt.

Two consequences that are more than renames:

- **No idempotency source.** `webhookId` is per-webhook, `eventDate` per-batch, and the nonce is
  regenerated per attempt — the opposite of an idempotency key. Best available is
  `record.updatedAt`: stable across a redelivery of one write, distinct for a genuine re-drag.
- **`record` is flat** — it is `properties.after`, the ORM entity, carrying `patientId` /
  `programId` FKs, not nested `patient` / `program` objects. So
  `canonical_key_path = ("patient","canonicalPatientId")` cannot resolve.

### F3 — A UI drag cannot produce a correct `effective_at`

Dragging a card updates `lifecycleStatus` only. Nothing stamps `lifecycleStatusAsOf`, so
`effective_at` would be the previous projection's timestamp — a silent correctness bug in the
ledger, not a crash. Needs either a logic function stamping the field on
`patientProgram.updated`, or `mapping.py` falling back to `record.updatedAt`.

### F4 — Views are a real manifest type, and the local stand-in is nothing like it

`twenty-shared/src/application/viewManifestType.ts`, with a working example at
`twenty-apps/internal/twenty-partners/.../deals-board.view.ts`. `ViewType` includes
`TABLE | LIST | KANBAN | CALENDAR`. Grouping is `mainGroupByFieldMetadataUniversalIdentifier`.
Objects and fields are referenced by UUID, never by name, and every view, view field,
filter, sort, and group carries its own `universalIdentifier`.

This contradicts the comment in `packages/twenty-app/src/views/index.ts` ("Views carry no
`universalIdentifier`") — that is a consequence of `operations.json` not modelling views, not a
fact about Twenty.

A view is also unreachable from the sidebar without a `defineNavigationMenuItem` of type `VIEW`.
For a demo whose whole point is dragging a card, unreachable equals nonexistent.

### F5 — Three pieces the round-trip needs do not exist

1. **No serving layer.** `create_app` (`api.py:629`) is a factory; no entrypoint, no Dockerfile,
   no manifest, no `[project.scripts]`.
2. **No kanban view.** All three views are `type: "TABLE"`, including
   `patient-program-status-board.view.ts:16` despite its kanban icon.
3. **No Twenty seed loader.** `packages/synthea-seed/` targets Snowflake/ledger tiers only.

Plus: `packages/twenty-app/src/define.ts` is a local stand-in and `package.json` carries no
`twenty-sdk` and no CLI, so `yarn twenty app:publish` — the only route for views and logic
functions, which the artifact does not contain — is not wired up.

### F6 — Infra facts (verified live, read-only)

- AWS `173008660334`, `us-east-1`, EKS `duploinfra-nonprod`, namespace `duploservices-dev01-brook`.
- Shared internet-facing ALB `k8s-duploser-dev01bro-7039abd165`, HTTPS:443, host-header routing.
  ACM cert covers `careportal-dev.brook.health`, `dev.brook.ai`, `sms.brook.ai` — none of the
  names we would want.
- RDS `duplodev01-brook-dev`: Postgres 16.13, `db.t3.small`, private, master `postgres`,
  SG `sg-0f2f6dfad100dd31f`. Ingress on 5432 today allows only a VPN /32 and the two public
  subnets `10.221.0.0/22`, `10.221.4.0/22` — the EKS node SG is not admitted; this must be
  added.
- Valkey 8.x ElastiCache exists in dev01. No pulse/twenty/ledger ECR repo exists yet.
- Tenant role is read-only for EC2 writes; `route53:*` and `acm:*` are denied.
- `duploctl` needs `duplo-jit duplo --host https://duplo.cloud.brook.ai --interactive`,
  which needs a real terminal — the harness has no TTY and caps foreground commands at 120s.

### F7 — What Twenty needs to run

Upstream `packages/twenty-docker/`: server (`:3000`, `/healthz`), worker
(`yarn worker:prod`, migrations and cron disabled), db = plain `postgres:16` (so RDS
16.13 works with no exotic extensions), and redis (BullMQ). Env: `PG_DATABASE_URL`,
`SERVER_URL`, `REDIS_URL`, `ENCRYPTION_KEY`, `STORAGE_TYPE`.

Upstream ships k8s manifests and a Helm chart (`k8s/manifests/deployment-{server,worker,db,redis}.yaml`,
`ingress.yaml`, services, PV/PVCs). The EKS deploy is configuration, not
hand-written manifests: start upstream, drop db, keep server + worker + redis + ingress.

Pin: latest release is `twenty/v2.30.0` (2026-08-11) with a matching `sdk/v2.30.0`. Pin
both together. (Upstream `main` is ahead at sdk 2.32.0 — pin to the release, not to main.)

SSRF guard: `OUTBOUND_HTTP_SAFE_MODE_ENABLED` blocks webhook targets resolving to private
IPs. Since the command API is cluster-internal (below), this must be disabled on dev.

> **Open:** whether Duplo wants this as a Duplo Service through its control plane or as raw
> manifests in the tenant namespace. Duplo reconciliation can fight resources it does not own.
> Settle before applying — it is the difference between a stable instance and one that reverts.

---

## Target topology

```
              shared ALB (host-header, HTTPS:443)
                          │
                          ▼
 EKS duploinfra-nonprod ── twenty-server (:3000) ── twenty-worker
  ns duploservices-           │                          │
     dev01-brook              ├────────────┬─────────────┘
                              ▼            ▼
                        redis (dedicated)  RDS duplodev01-brook-dev
                                             ├── db `twenty`
                                             └── db `pulse_ledger_dev`
                          ▲
                          │ ClusterIP, in-cluster only
                pulse-ledger-api (:8000)
```

The command API is internal-only. Twenty reaches
`http://pulse-ledger-api.duploservices-dev01-brook.svc.cluster.local:8000/webhooks/twenty`.
It is HMAC-authed, holds no PHI in dev, and nothing outside the cluster calls it — so no ALB
rule, no hostname, no cert. That keeps Route53/ACM off the critical path for everything but
Twenty's own UI, and avoids touching a listener several unrelated tenant services depend on.

Note the webhook route answers 200 to a broad class of non-authenticated-looking traffic by
design (so Twenty stops redelivering); that is a further reason not to face it at the internet.
Cost is that you cannot curl it from a laptop — use a port-forward from the operator seam.

---

## Plan

### Phase A — provision, then probe F1 before anything else

1. Mint a portal token in a real terminal: `duplo-jit duplo --host https://duplo.cloud.brook.ai --interactive`.
2. Confirm the five unverified Duplo/AWS facts (below, Risks 7). Fifteen minutes; saves an afternoon.
3. Create database `twenty` + least-privilege role on `duplodev01-brook-dev`; add the EKS node
   SG to the RDS SG on 5432.
4. Provision dedicated Redis (not the shared `duplo-dev01-brook-ai-001` — BullMQ in a shared
   keyspace is a debugging hazard for no saving).
5. Deploy `twentycrm/twenty:v2.30.0` server + worker from upstream manifests minus db.
   Secrets from the Duplo store, never in a manifest.
6. Ingress hostname on the shared ALB. Admin step — tenant role is denied `route53:*`/`acm:*`.
7. Create the workspace and an API key (Settings → API & Webhooks; shown once). Record as
   `PULSE_TWENTY_DEV_URL` / `PULSE_TWENTY_DEV_TOKEN` in the Duplo store.
8. **Probe F1**: `createObject` with a `universalIdentifier`, then read back. Does the UUID
   round-trip? Record the answer in `HANDOFF.md` for `docs/contracts/consumes.md`.
   If no — stop and re-plan. `twenty_deploy` is superseded by `app:publish` for the whole
   model and steps 10-12 reshape.

### Phase B — apply the artifact and read back (task 4.1)

9. `task twenty:deploy TARGET=dev`, `--dry-run` first. Settles whether `/rest/metadata/roles`
   and `/rest/metadata/relations` exist in the pinned shapes and whether the envelope is
   `{"data": [...]}` — all three are this repo's guesses. Re-apply; assert an all-no-op receipt.
   Attach the receipt (names, counts, checksum) to the Linear parent.

### Phase C — capture a real delivery before writing mapping code

10. Register a webhook via the metadata GraphQL mutation (there is no `defineWebhook` in the
    apps framework, so it cannot ship in the manifest):
    `createWebhook(input: {targetUrl, operations: ["patientProgram.updated"], secret})` against
    `POST /metadata`. Narrowing operations from the default `["*.*"]` makes
    `NOOP_UNMAPPED_OBJECT` a dead path rather than the common case. The secret is
    client-supplied — set it equal to `PULSE_LEDGER_TWENTY_WEBHOOK_SECRET`; D15 rotation still
    works via `updateWebhook`.
11. Point it at a throwaway capture receiver; change a `lifecycleStatus`; record exact header
    and body bytes. Commit as a synthetic fixture — it becomes the reference that retires the
    pin, and all nine fixtures under `packages/pulse-ledger/tests/fixtures/twenty/` get re-cut
    from it.

### Phase D — adapt pulse to Twenty's real contract

12. `auth.py`: rename header constants; `sign()` becomes
    `hmac.new(secret, f"{ts}:".encode() + body, sha256).hexdigest()` with no affixes; `_is_fresh`
    reads milliseconds. Keep `SIGNATURE_FRESHNESS`, `compare_digest`, and dual-secret
    rotation — those are sound and format-independent.
    Keep signing the raw request bytes, never a re-serialization of a parsed body
    (`verify_signature` already takes bytes; this must survive any future middleware).
13. `mapping.py`: gate on `eventName.endswith(".updated")`; `updatedFields` as a name list with
    the value read from `record[status_field]`; `workspaceMemberId` flat; `record.updatedAt` as
    `logical_time` in place of the absent `eventId`; re-point `canonical_key_path`/`program_path`
    at denormalized flat fields.
14. Add `canonicalPatientId` and `programCode` as TEXT fields on `patientProgram` (model
    change → `task twenty:gen` → mint UIDs → validate). Required because webhook records are
    flat (F2). Both are pseudonymous identifiers, not PHI. The alternative — a REST read-back
    per drag — adds a credential and a failure mode to the hot path.
15. Resolve F3: stamp `lifecycleStatusAsOf` via a logic function, or fall back to
    `record.updatedAt`. Pick one deliberately; the failure mode is a wrong `effective_at`, which
    is silent.
16. Spec deltas for `twenty-webhook-auth` and `twenty-drag-command` into `HANDOFF.md`.
    Never edit spec files directly (`AGENTS.md`).

> The archived `twenty-kanban-webhook-ingress` design never named what produces
> `X-Pulse-Signature` — it assumed a signed delivery arrives. F2 answers it: Twenty's own sender
> signs, in its own fixed format. So no logic-function signing shim is needed and none should
> be built. `scripts/demo/demo2_kanban_drag.py` already constructs signed drags and updates
> alongside `auth.py`.

### Phase E — serving layer

17. `packages/pulse-ledger/src/pulse_ledger/api_server.py` — mirrors the existing
    `relay.py`/`relay_worker.py` split; run as `python -m pulse_ledger.api_server`.
    - Real committer is `idempotency.commit_idempotent`, falling through to
      `commit.commit_declaration` when the key is None — the `Committer` alias (`api.py:99`)
      makes it optional (D16 accepted-if-present, ADR-0004 / DNA-801).
    - Connection **pool**, not a shared connection: handlers are `async def`, call the committer
      synchronously, and `commit_declaration` holds a per-subject advisory lock for the
      transaction. Needs `psycopg[binary,pool]`.
    - `uvicorn.run(..., factory=True)` so import never reads the environment — tests then need
      no DB. `uvicorn` in a `serve` extra, since identity/verdict-relay/schedules import
      `pulse-ledger` as a library.
    - `/health` lives here, not in `api.py`, preserving that module's every-route-authenticated
      contract. Liveness only — no `SELECT 1`, so an RDS blip does not roll pods.
    - Document, don't hide: the sync committer runs on the event loop thread. Fine at dev
      volume; `anyio.to_thread.run_sync` is the later fix.
18. `packages/pulse-ledger/Dockerfile` — one image, two commands; context is the repo root
    (`pulse-core` is a workspace sibling). Build `--platform linux/amd64` explicitly: dev
    machines are arm64, nodes are x86. Push to a new ECR repo (none exists).
19. Privileges fall out of migration 0001 and are worth honouring exactly.
    `0001_ledger_schema.py` already creates NOLOGIN group role `pulse_ledger_service` with the
    append-only posture — SELECT, INSERT on `ledger.events`, UPDATE/DELETE revoked. So
    create a login role owning nothing and `GRANT pulse_ledger_service TO pulse_ledger_app`. It
    then physically cannot mutate the ledger or DDL.
    - Migrations run as a separate `pulse_ledger_migrator` (needs CREATE SCHEMA and the
      CREATE ROLE block at `0001:191-201`) — not an init container, which would hand the API
      pod a DDL-capable credential and undo the split.
    - Run from the existing Orca cloud host (in-tenant VPC, repo cloned, reachable over SSM).
      RDS is private so something in-VPC must; this avoids inventing a bastion and makes
      migration a deliberate operator action with a runbook.
    - Store two DSN keys: `DATABASE_URL` (plain `postgresql://`, psycopg v3) and
      `ALEMBIC_DATABASE_URL` (`postgresql+psycopg://`). The `+driver` footgun is already a
      recorded lesson (`relay_worker.py:3-5`).
    - `CredentialRegistry.from_env` refuses to build with no writer tokens — at least one
      `PULSE_LEDGER_WRITER_TOKEN_*` must exist or the pod crashloops with an unhelpful
      traceback. Put that in the runbook.

### Phase F — the Twenty surface

20. Reshape `src/define.ts` to mirror `ViewManifestType` exactly — offline, no new
    dependency, nothing published. Update the three existing views and
    `packages/twenty-app/tests/model.test.ts` (which validates views by field name today).
    A half-migrated shape is worse than either end: the point of the stand-in is that adopting
    the real SDK becomes a change of import path.
21. Teach `pulse_core.twenty_model` view UID keys (`view.<name>`, `view.<name>.group.<state>`,
    `view.<name>.field.<field>`), then `task twenty:gen`, then mint into `uid-map.json` as a
    reviewed diff. Order matters — `check_uid_map` fails on any key the model does not ask
    for, so model keys first, never the reverse.
22. Add the KANBAN view + `defineNavigationMenuItem`. Derive columns from
    `PATIENT_PROGRAM_LIFECYCLE_STATUS_OPTIONS` in `generated/options.ts` rather than
    hand-writing them, so a new catalog state becomes a column with no hand edit. Keep the
    existing table view as a table (it genuinely is one); move the misleading `IconLayoutKanban`
    to the new board and give the table `IconTable`.
23. Adopt `twenty-sdk` pinned exactly (`test_dev_toolchain_is_pinned_exactly`), regenerate
    `package-lock.json`, add `twenty:app:build` / `twenty:app:publish` with
    `requires: vars: [TARGET]`, both out of `check`. Bump `packages/twenty-app/package.json`
    version on every publish — the server rejects an equal or lower semver with
    `VERSION_ALREADY_EXISTS`. Add the remote non-interactively via
    `yarn twenty remote:add --url ... --api-key ...`; credentials land in `~/.twenty/config.json`,
    so it is a developer/CD step, never a `check` step.
24. `pulse_core.twenty_seed` (`task twenty:seed TARGET=dev`) — reuses `twenty_deploy`'s Target
    resolution and receipt posture verbatim. Creates clinic → provider → patient → program →
    patientProgram over the core REST API (`/rest/{namePlural}`), relations as FK ids.
    Idempotent on natural keys (`canonicalPatientId`, `program.code`, `clinic.sfdcId`,
    `(patientId, programId)`), never on Twenty record ids; create-if-absent, patch-if-drifted,
    never delete. Chunk and pace — batch caps at 60 records/call, instance rate-limits at
    100 req/min. Every `patientProgram` must land with a non-null `lifecycleStatusAsOf` or the
    first drag hits `MalformedPayloadError`.
    - Identities come from a committed deterministic projection
      (`pulse_core/generated/twenty_seed_dev.json`, ~20 patients, checksummed like the synthea
      manifests), not from a live Synthea run: `synthea-seed` emits into an untracked `output/`
      tree that needs Java and a 500-patient run, and produces no `canonicalPatientId` (that is
      identity-resolution's output). `canonicalPatientId` is minted deterministically from the
      Synthea patient UUID. Loader then needs no Java, no untracked tree, and is synthetic-only
      by construction.

### Phase G — the round-trip

25. Set `PULSE_LEDGER_TWENTY_WEBHOOK_ENABLED`; point the webhook at the cluster-internal URL;
    disable `OUTBOUND_HTTP_SAFE_MODE_ENABLED` on dev (it blocks private-IP targets).
26. `scripts/demo/demo3_live_kanban_drag.py`, following `demo2_kanban_drag.py`'s convention
    (`build_arg_parser()`, clean `--help`, nonzero on any failed assertion, out of `check`, with
    a companion smoke test that only checks it parses so CI never needs a server). Asserts, in
    order: UID round-trip; view exists and is KANBAN grouped on the right field; column parity
    with the catalog's state set; seed counts and non-null `lifecycleStatusAsOf`; exactly one
    webhook registered for `patientProgram.updated`; a legal drag commits with `effective_at`
    equal to the record stamp, not wall clock; a replay produces no second event; an illegal
    drag returns 200 rejected with exactly one card comment and the state of record unchanged.
    - Select the drag target by index into a sorted-by-id list, never by name, so no
      demographic enters the script's memory let alone its output.
27. Then drag a card by hand in the UI and confirm the same event lands. The script drives
    the REST path, which fires the same event — but the literal drag is the acceptance criterion.
28. Receipt to DNA-909; unblock DNA-928/929.

---

## Files and targets

```
packages/pulse-ledger/
  Dockerfile                                  NEW
  src/pulse_ledger/api_server.py              NEW  entrypoint
  src/pulse_ledger/auth.py                    EDIT F2 — headers, hex, ms
  src/pulse_ledger/twenty/mapping.py          EDIT F2/F3 — envelope, flat record, updatedAt
  tests/fixtures/twenty/*                     RECUT from the Phase C capture
  tests/test_api_server.py                    NEW  fake pool; src is under an 80% cov floor
  infra/postgres/bootstrap_database.sql       NEW  psql vars, no literals
  infra/duplo/command-api.{service,lb}.json   NEW  ClusterIP, internal
packages/twenty-app/
  src/define.ts                               EDIT to ViewManifestType
  src/views/patient-program-lifecycle-board.view.ts   NEW  KANBAN
  src/navigation/patient-program-board.nav.ts NEW  or the board is unreachable
  package.json                                EDIT twenty-sdk, pinned exactly
packages/pulse-core/src/pulse_core/
  twenty_model.py                             EDIT view UID keys + denormalized fields
  twenty_seed.py                              NEW  seed loader
  generated/twenty_seed_dev.json              NEW  committed synthetic projection
scripts/pulse-ledger/deploy.sh                NEW
scripts/demo/demo3_live_kanban_drag.py        NEW
docs/runbooks/pulse-command-api-deploy.md     NEW  + mkdocs.yml nav entry
docs/runbooks/twenty-artifact-promotion.md    NEW  task 4.2's deliverable
tests/test_ledger_deploy_targets.py           NEW  pins the credential-free check contract
```

New Taskfile targets beside `catalog:release` / `twenty:deploy`, all unreachable from
`check`: `ledger:image`, `ledger:migrate`, `ledger:deploy`, `twenty:app:build`,
`twenty:app:publish`, `twenty:seed`. Extend
`test_credentialed_twenty_targets_stay_out_of_check` and model
`tests/test_ledger_deploy_targets.py` on `tests/test_catalog_release_deploy.py`, which already
computes the reachability set.

Gates checked: no new workflow, so `cat4_ci_contract.py` is unaffected; cat8's README/Taskfile
test is `@template_only`, but any `task ...` written into README or AGENTS must resolve; new
runbooks need `mkdocs.yml` nav entries or `mkdocs build -s` warns on orphans.

`scripts/pulse-ledger/deploy.sh` mints its token with `duplo-jit`, not
`duploctl --interactive` — the latter blocks without a TTY and dies under any agent harness.
That lesson is recorded; inherit it rather than relearn it.

---

## Change lifecycle

Far past a mechanical update, so this goes through OpenSpec as a new change (working name
`twenty-dev-instance`) carrying delta specs for `twenty-webhook-auth` and `twenty-drag-command`
plus the new serving-layer and seed-loader capabilities. `environment-matrix` stays a separate,
later change — this provisions dev only and does not build the promotion path.

## Verification

- `task check` green throughout — offline and credential-free at every step.
- Phase A: the F1 UID probe, recorded either way.
- Phase B: two consecutive `twenty:deploy` runs, second all-no-op, receipts attached.
- Phase C: committed capture fixture; new auth/mapping unit tests run against it offline.
- Phase G: `demo3_live_kanban_drag.py` green on all nine assertions, then a hand drag.
- Receipts carry names, counts, checksums, catalog version and event counts only — no record
  ids, field values, or response bodies, matching `twenty_deploy`'s posture.
- PHI: synthetic by construction. Confirm no capture fixture, log line, or receipt carries
  workspace record content.

## Risks

1. **F1 — `universalIdentifier` not settable.** Highest consequence; could supersede
   `twenty_deploy` wholesale. Probed first, before anything is built on it. Bounded only because
   nothing has applied the artifact anywhere yet.
2. `createRelation` / `createRole` endpoint shapes in `twenty_deploy.py`'s `COLLECTIONS` map
   are unverified guesses, as is the `{"data": [...]}` envelope.
3. `POST /rest/comments` is a second unverified pin and will likely need the same
   reconciliation as the webhook.
4. **Idempotency without an event id.** Whether Twenty retries, and whether a retry re-signs with
   a fresh timestamp, determines whether `record.updatedAt` suffices. Get this from a real
   redelivery, not from reasoning.
5. **Toolchain collision.** `twenty-sdk` wants node `^24.5.0` and TypeScript `^5.9.3`; the repo
   pins node `>=22` and `typescript@7.0.2`. Two TS majors in one lockfile is survivable, but
   `tsc --noEmit` at 7.x against 5.x-oriented `.d.ts` is the most likely place `twenty:test`
   goes red. Mitigate by importing types only at first and keeping `define.ts` as a
   re-export shim — and by sequencing the shape change (step 20) before the dependency change
   (step 23), so the two blast radii stay separate.
6. **Disabling the SSRF guard** is required for a cluster-internal target. It is a dev-only,
   synthetic-only instance, but the guard exists for a reason — record it in the runbook rather
   than leaving it as an undocumented env var.
7. **Five unverified Duplo/AWS facts** — AgentPlatform value for EKS-linux, LbType for
   ClusterIP, OtherDockerConfig key casing, ECR repo creation, and RDS SG ingress for the EKS
   node SG (confirmed absent today). Each is a one-look confirmation; getting them wrong is a
   rejected API call, not a broken deploy.
8. `db.t3.small` shared RDS hosting Twenty + worker + ledger. Fine at ~20-500 synthetic
   patients; watch it.
9. Duplo reconciliation may fight raw manifests it does not own.
10. **Manual/admin steps** — interactive Duplo token, DNS/cert, the once-shown API key. These sit
    inside DNA-909, itself the manual-intervention ticket, so they are steps here rather than
    new escalations.

## Governance note — D14 stays open

`docs/adr/ADR-0004-runtime-readiness-decisions.md` records D14 as SPCS, with "EKS on
DuploCloud" as the named fallback contingent on a latency spike that is still an open roadmap
unit. This plan deploys to EKS. Defensible as a dev-environment decision that does not close
D14 — but it must be said out loud, because `docs/adr/` is append-only and the roadmap still
lists `pulse-spcs-deployment` as the deployment unit.

Cheapest honest option: a paragraph in the new runbook stating this is dev only and D14 remains
open. If the intent is actually to abandon SPCS, that needs a new ADR and a status flip on
ADR-0004 — not a quiet EKS deploy.
