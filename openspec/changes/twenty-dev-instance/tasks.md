# Tasks — twenty-dev-instance

Annotation format, read by `task dispatch` and checked by G_MECE:
`[model | deps | lane | wave]`, with `serial:` carrying its justification where set. `deps`
names task numbers in this file; `—` means no dependency. Linear ids get bracketed in after
`task linear:sync`. Default model is `sonnet`, stated explicitly on every task.

**Two lanes that never dispatch.** Group 1, plus 3.1, 4.1, 4.2 and 7.2, are `destructive_ops`
or `operational_discovery`: they provision tenant infrastructure, hold a credential shown once,
or read a live instance. `task dispatch` emits no work order for either lane — their runner is
the Open Engine queue. They are listed here because the graph is only honest if the manual steps
are in it.

**The F1 gate.** Task 1.7 asks whether `universalIdentifier` round-trips through the Metadata
API. **Group 3 onward must not start until it is answered and recorded.** A negative answer means
`twenty:deploy` is superseded by `app:publish` for the whole model, and 3.1, 6.1 and 6.3 reshape
— so a wrong guess here is re-work, not a bug. Record the answer either way in `HANDOFF.md` for
`docs/contracts/consumes.md`.

**Group 2 is F1-independent and dispatches now.** The serving layer, the view-manifest reshape,
and the seed loader are offline, touch no live instance, and do not depend on the probe.

Every task ships its tests in the same commit (tests first per `AGENTS.md`). `task check` stays
green, offline and credential-free, at every step; every new credentialed target stays
unreachable from it. Synthetic data only — no PHI in fixtures, captures, logs, or receipts.
Specs are owned by the doc-updater: write proposed spec changes to `HANDOFF.md`, never edit
files under `openspec/specs/`.

---

## 1. Phase A — provision and probe (manual lanes; does not dispatch)

- [x] 1.1 Confirm the five unverified Duplo/AWS facts before any mutating call: the
      AgentPlatform value for EKS-linux, the LbType for ClusterIP, OtherDockerConfig key
      casing, ECR repo creation rights, and RDS SG ingress for the EKS node SG (confirmed
      absent today). Settle in the same pass whether the instance should be a Duplo Service
      through the control plane or raw manifests in the tenant namespace — Duplo reconciliation
      fights resources it does not own, and this is the difference between a stable instance
      and one that reverts. Mint the portal token with `duplo-jit`, never
      `duploctl --interactive`, which blocks without a TTY.
      Verify: each fact recorded with the command that confirmed it; getting one wrong should
      cost a rejected API call, not a broken deploy.
      `[model: sonnet | deps: — | lane: operational_discovery | wave: 0]`

- [x] 1.2 Create the `twenty` database and a least-privilege role on `duplodev01-brook-dev`,
      and add the EKS node SG to the RDS security group on 5432.
      Verify: a psql connection from an in-cluster pod succeeds; the VPN /32 and existing
      subnet rules are unchanged.
      `[model: sonnet | deps: 1.1 | lane: destructive_ops | wave: 1]`

- [x] 1.3 Provision a dedicated Redis, not the shared tenant instance — BullMQ in a shared
      keyspace is a debugging hazard for no saving.
      Verify: reachable from the namespace; the shared instance's keyspace is untouched.
      `[model: sonnet | deps: 1.1 | lane: destructive_ops | wave: 1]`

- [x] 1.4 Deploy `twentycrm/twenty:v2.30.0` server + worker from the upstream manifests with
      the bundled db dropped, keeping server, worker, redis and ingress. Secrets come from the
      Duplo store, never a manifest. Set `OUTBOUND_HTTP_SAFE_MODE_ENABLED=false` — the webhook
      target is a private cluster IP — and record that in the runbook rather than leaving it an
      undocumented env var.
      Verify: `/healthz` green on the server; the worker runs with migrations and cron disabled.
      `[model: sonnet | deps: 1.2, 1.3 | lane: destructive_ops | wave: 2]`

- [x] 1.5 Ingress hostname on the shared ALB. **Admin step** — the tenant role is denied
      `route53:*` and `acm:*`, and the existing certificate covers no name we want. Do not edit
      the listener in a way that disturbs the unrelated tenant services sharing it.
      Verify: the UI loads over HTTPS at the new name; other host-header rules still resolve.
      `[model: sonnet | deps: 1.4 | lane: destructive_ops | wave: 3]`

- [x] 1.6 Create the workspace and an API key (Settings → API & Webhooks). **The key is shown
      once.** Record it and the base URL in the Duplo store as `PULSE_TWENTY_DEV_URL` /
      `PULSE_TWENTY_DEV_TOKEN`.
      Verify: an authenticated REST call succeeds using only the stored values.
      `[model: sonnet | deps: 1.4 | lane: destructive_ops | wave: 3]`

- [x] 1.7 **The F1 gate.** Create an object through the Metadata API supplying a
      `universalIdentifier`, then read it back. Does the UUID round-trip, or is it dropped
      because the field is `@HideField()` on the create input? Record the answer, the pinned
      version it was observed on, and the exact calls, in `HANDOFF.md` for
      `docs/contracts/consumes.md`. **If it does not round-trip, stop and re-plan** — group 3
      onward reshapes around `app:publish`.
      Verify: the recorded answer is reproducible from the written-down calls.
      `[model: sonnet | deps: 1.6 | lane: operational_discovery | wave: 4]`

## 2. Offline workstreams — F1-independent, dispatch now

- [x] 2.1 `packages/pulse-ledger/src/pulse_ledger/api_server.py`: process entrypoint mirroring
      the existing relay/relay-worker split, run as `python -m pulse_ledger.api_server`. Use a
      connection pool, not a shared connection — handlers are async and the committer holds a
      per-subject advisory lock for its transaction. Start the app through a factory so import
      never reads the environment. Put `/health` here rather than in the routed module, keeping
      that module's every-route-authenticated contract intact, and make it liveness-only with no
      query so an RDS blip does not roll pods. Document, do not hide, that the sync committer
      runs on the event loop thread.
      Test: `tests/test_api_server.py` with a fake pool — imports offline with no database,
      `/health` answers unauthenticated, command routes still reject an unauthenticated call,
      and a missing writer token fails startup with a named error. Source is under an 80%
      coverage floor.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0]`

- [x] 2.2 `packages/pulse-ledger/Dockerfile` — one image, two commands, build context the repo
      root because `pulse-core` is a workspace sibling. Build `--platform linux/amd64`
      explicitly: dev machines are arm64 and the nodes are x86. Create the ECR repo (none
      exists) and push.
      Test: the image starts and answers `/health` locally with no database reachable.
      `[model: sonnet | deps: 2.1 | lane: repo_change | wave: 1]`

- [x] 2.3 Role split and migration path: `infra/postgres/bootstrap_database.sql` using psql
      variables and no literals, creating a login role owning nothing that inherits the NOLOGIN
      group role migration 0001 already defines, plus a separate migrator role holding the DDL
      rights the serving role lacks. Migrations run from the in-tenant Orca host — **not** an
      init container, which would hand the API pod a DDL-capable credential and dissolve the
      split. Store both DSNs (`DATABASE_URL` plain, `ALEMBIC_DATABASE_URL` with the driver
      suffix); the `+driver` footgun is already a recorded lesson.
      Test: against a local Postgres, the serving role is refused on `DELETE`/`UPDATE` of an
      event row and on DDL, while the migrator succeeds.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0]`

- [x] 2.4 Reshape `packages/twenty-app/src/define.ts` to mirror Twenty's real
      `ViewManifestType` — offline, no new dependency, nothing published. Update the three
      existing views and `tests/model.test.ts`, which validates views by field name today. A
      half-migrated shape is worse than either end; the point of the stand-in is that adopting
      the SDK later becomes a change of import path. Correct the stale comment in
      `src/views/index.ts` claiming views carry no `universalIdentifier` — that was a
      consequence of the artifact not modelling views, not a fact about Twenty.
      Test: `task twenty:test` green with views asserted by identifier rather than name.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0]`

- [x] 2.5 `pulse_core.twenty_seed` + `task twenty:seed TARGET=dev`, reusing `twenty_deploy`'s
      target resolution and receipt posture verbatim. Source is a committed, checksummed
      deterministic projection at `pulse_core/generated/twenty_seed_dev.json` (~20 patients) —
      not a live generator run, which needs Java, an untracked output tree, and produces no
      canonical spine id. Mint that id deterministically from the generator's record UUID.
      Idempotent on natural keys, create-if-absent, patch-if-drifted, never delete. Chunk and
      pace to the instance's 60-records-per-call and 100-requests-per-minute limits. Every
      board record must land with a non-null status as-of stamp or the first drag is refused.
      Test: offline against a faked client — second run all-unchanged, drifted field patched,
      an unknown workspace record untouched, checksum mismatch refused, and a receipt carrying
      no record ids or field values.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0]`

- [x] 2.6 Reshape `pulse_core.twenty_deploy`'s metadata surface to the endpoints v2.30 actually
      serves, per the DNA-909 provisioning receipt (2026-08-16): `/rest/metadata/relations` and
      `/rest/metadata/roles` do not exist — the router parses those path segments as object ids
      and answers 400 `"'relations' is not a valid UUID"`. Relations apply through the fields
      surface (RELATION-type field payloads); roles live on the `/metadata` GraphQL, not REST.
      Rework `COLLECTIONS`/`read_state`/`send` so the artifact's relation and role operations
      apply through the real surfaces, keeping the create-if-absent/update-if-drifted posture
      keyed on `universalIdentifier` (confirmed round-tripping on v2.30 — F1 positive).
      Test: offline against recorded v2.30 response shapes — a state read that never touches
      `/rest/metadata/relations` or `/roles`, relation ops planned onto the fields surface, role
      ops onto the GraphQL surface, and the existing no-op/idempotency tests still green.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0]`

## 3. Apply the artifact (GATED: F1 probe, task 1.7)

- [x] 3.1 `task twenty:deploy TARGET=dev`, `--dry-run` first. This settles three of this repo's
      guesses at once: whether the relations and roles metadata endpoints exist in the pinned
      shapes, and whether the response envelope is what `twenty_deploy` assumes. Re-apply and
      assert an all-no-op receipt. Attach the receipt — names, counts, checksum only — to the
      Linear parent.
      Verify: two consecutive runs, the second all-no-op; any endpoint-shape correction written
      to `HANDOFF.md`.
      `[model: sonnet | deps: 1.7, 2.6 | lane: operational_discovery | wave: 5]`

## 4. Capture the real delivery (GATED: workspace exists, task 1.6)

- [ ] 4.1 Register a webhook through the metadata GraphQL mutation — there is no manifest
      webhook type, so it cannot ship in the app. Narrow `operations` to the mapped object's
      `.updated` event rather than the default wildcard, which makes the unmapped-object no-op a
      defensive path instead of the common case. Set the client-supplied secret equal to the
      configured webhook secret so quarterly rotation still works through the update mutation.
      Verify: exactly one webhook registered, scoped to the one operation.
      `[model: sonnet | deps: 1.6 | lane: destructive_ops | wave: 4]`

- [ ] 4.2 Point the webhook at a throwaway capture receiver, change a `lifecycleStatus`, and
      record the exact header and body bytes. Commit as a synthetic fixture — this is the
      artifact that retires the pin. Trigger a redelivery and capture that too: whether a retry
      re-signs with a fresh timestamp is what decides if `record.updatedAt` suffices as an
      idempotency source, and that must come from an observation, not from reasoning.
      Verify: committed fixture; the redelivery's `record.updatedAt` matches the original's.
      `[model: sonnet | deps: 4.1 | lane: operational_discovery | wave: 5]`

## 5. Adapt pulse to the real contract (GATED: capture, task 4.2)

- [ ] 5.1 `auth.py`: read Twenty's header names; `sign()` becomes a bare hex HMAC-SHA256 over
      `{timestamp}:{body}` with no version affixes; freshness reads milliseconds. Keep the
      freshness window, constant-time comparison, and dual-secret rotation — sound and
      format-independent. Keep signing the raw request bytes, never a re-serialization of a
      parsed body, so verification survives future middleware.
      Test: re-cut fixtures verify; a millisecond timestamp is inside the window; the retired
      affixed format no longer verifies. Re-cut all nine fixtures under
      `tests/fixtures/twenty/` from 4.2's capture in this same commit — the contract change and
      the fixtures are a matched pair and reverting one alone leaves the suite red.
      `[model: sonnet | deps: 4.2 | lane: repo_change | wave: 6]`

- [ ] 5.2 `mapping.py`: gate on `eventName` ending `.updated`; read `updatedFields` as a name
      list with values from the flat `record`; flat `workspaceMemberId`; `record.updatedAt` as
      logical time in place of the absent event id. Resolve the effective-time question (F3)
      deliberately — a UI drag stamps no as-of field, so derive from the record's own timestamp
      and **refuse** rather than inherit the previous projection's time, which would be a silent
      wrong `effective_at` rather than a failure.
      Test: a genuine second drag is not mistaken for a replay; a record with no establishable
      effective time is refused; a redelivery replays.
      `[model: sonnet | deps: 4.2 | lane: repo_change | wave: 6]`

- [ ] 5.3 Add `canonicalPatientId` and `programCode` as TEXT on `patientProgram` (model change →
      `task twenty:gen` → mint UIDs → validate). Required because the webhook record is flat; the
      alternative, a REST read-back per drag, adds a credential and a failure mode to the hot
      path. Both are pseudonymous identifiers, not PHI. Re-point the mapping's canonical and
      program paths at the denormalized fields.
      Test: subject resolution reads only the payload and issues no outbound call.
      `[model: sonnet | deps: 5.2 | lane: repo_change | wave: 7]`
      `serial: uid_map` — mints into `uid-map.json`; must not share a wave with 6.1.

## 6. The Twenty surface (GATED: F1 answer shapes 6.1 and 6.3)

- [ ] 6.1 Teach `pulse_core.twenty_model` the view UID keys (`view.<name>`,
      `view.<name>.group.<state>`, `view.<name>.field.<field>`), then `task twenty:gen`, then
      mint into `uid-map.json` as a reviewed diff. Order matters: the UID-map check fails on any
      key the model does not ask for, so model keys land first, never the reverse.
      Test: generation is deterministic and the map check passes; a key absent from the model
      still fails.
      `[model: sonnet | deps: 2.4, 5.3 | lane: repo_change | wave: 8]`
      `serial: uid_map` — mints into `uid-map.json`; must not share a wave with 5.3.

- [ ] 6.2 Add the KANBAN view and its `defineNavigationMenuItem` — without the nav item the
      board is unreachable from the sidebar, and for a demo whose point is dragging a card,
      unreachable equals nonexistent. Derive columns from the generated lifecycle-status options
      rather than hand-writing them, so a new catalog state becomes a column with no hand edit.
      Keep the existing table view a table, move the misleading kanban icon to the new board.
      Test: column set equals the catalog's state set, asserted from the generated options.
      `[model: sonnet | deps: 6.1 | lane: repo_change | wave: 9]`

- [ ] 6.3 Adopt `twenty-sdk` pinned exactly, regenerate the lockfile, and add
      `twenty:app:build` / `twenty:app:publish` requiring `TARGET`, both out of `check`. Bump the
      app version on every publish — the server rejects an equal or lower semver. Add the remote
      non-interactively; credentials land in a user config file, so this is a developer/CD step,
      never a check step. Sequenced deliberately after 2.4: the SDK wants node `^24.5.0` and
      TypeScript `^5.9.3` against this repo's node `>=22` and `typescript@7.0.2`, and landing the
      shape change separately keeps a type failure attributable.
      Test: extend the existing reachability test so the new credentialed targets are asserted
      unreachable from `check`; `task check` green.
      `[model: sonnet | deps: 6.2 | lane: repo_change | wave: 10]`

## 7. The round trip (GATED: everything above)

- [ ] 7.1 `scripts/demo/demo3_live_kanban_drag.py`, following the existing demo's conventions —
      `build_arg_parser()`, clean `--help`, nonzero on any failed assertion, out of `check`, with
      a companion smoke test that only checks it parses so CI never needs a server. Asserts, in
      order: UID round-trip; the view exists, is KANBAN, and groups on the right field; column
      parity with the catalog; seed counts and non-null as-of stamps; exactly one webhook for the
      mapped operation; a legal drag commits with `effective_at` equal to the record stamp rather
      than wall clock; a replay produces no second event; an illegal drag returns 200 rejected
      with exactly one card comment and the state of record unchanged. Select the drag target by
      index into a sorted-by-id list, never by name, so no demographic enters the script's memory
      let alone its output.
      Test: the smoke test parses the script in CI without a server.
      `[model: sonnet | deps: 2.5, 5.1, 5.2, 6.2 | lane: repo_change | wave: 10]`

- [ ] 7.2 Set the webhook-enabled flag, point the webhook at the cluster-internal service URL,
      run 7.1 green, then **drag a card by hand in the UI** and confirm the same event lands. The
      script drives the REST path, which fires the same event — but the literal drag is the
      acceptance criterion, and only the hand drag proves the UI path.
      Verify: nine assertions green, then a hand drag producing one correctly-timed event.
      `[model: sonnet | deps: 3.1, 7.1 | lane: operational_discovery | wave: 11]`

- [ ] 7.3 Close the loop in docs: `docs/runbooks/pulse-command-api-deploy.md` and
      `docs/runbooks/twenty-artifact-promotion.md`, both with `mkdocs.yml` nav entries or
      `mkdocs build -s` warns on orphans. The promotion runbook states plainly that this is dev
      only and **ADR-0004 D14 remains open** — `docs/adr/` is append-only and the roadmap still
      lists the SPCS deployment unit, so abandoning SPCS needs a new ADR and a status flip, not a
      quiet EKS deploy. Pin the observed Twenty tag in `docs/contracts/consumes.md`, replacing
      the entry that currently says no instance exists, and record the F1 answer beside it.
      Write the spec deltas for `twenty-webhook-auth` and `twenty-drag-command` to `HANDOFF.md`
      for the doc-updater; never edit `openspec/specs/` directly.
      Test: `task check` green including `docs:build`; `task verify CHANGE=twenty-dev-instance`
      passes.
      `[model: sonnet | deps: 7.2 | lane: repo_change | wave: 12]`
