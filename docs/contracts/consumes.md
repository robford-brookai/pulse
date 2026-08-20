# Consumes

What this repo reads from elsewhere. Each entry should link the publisher's `publishes.md` so a
breaking change upstream is traceable to the consumers it affects.

**Never satisfy a dependency by cloning the producing repo into this one.** Consume a published
surface — a Snowflake object, an API, or a released package.

| Dependency | Kind | Publisher contract | Breakage risk |
|---|---|---|---|
| _e.g._ `RAW.ZCC_CONTACTS` | Snowflake table | `zcc-ingest/docs/contracts/publishes.md` | schema drift on upstream vendor change |

## This repo

### Verdict mart (dbt, Snowflake)

`packages/verdict-relay` reads the verdict mart the dbt project computes in Snowflake and declares
each row to the ledger as a `declare_verdict` command
(`openspec/changes/s12-verdict-relay/specs/verdict-mart-read/spec.md`). Per roadmap P5
(`design/delivery/pulse-program-roadmap.md`), this relay supersedes the clinic-rules-engine
Snowpark emitter as the verdict write path — see the supersession note in
`design/platform/clinic-rules-engine.md`.

| Dependency | Kind | Source | Breakage risk |
|---|---|---|---|
| Verdict mart | dbt-computed Snowflake table(s) | fixture-pinned contract: one row per `(subject_id, verdict_type, run)`, columns `subject_id, verdict_type, outcome, reason, rule_version, as_of, lineage_ref, computed_at` | a row missing a contract column or carrying an unparseable `as_of`/`computed_at` fails the run before any declaration, naming the offending row; the dbt side has no publisher contract of its own yet — this repo's fixtures are the only pinned shape |

The relay pages on `computed_at` and persists its cursor through the ledger's writer-state
facility (`pulse_core.cursor`), scoped to its own writer id — so schema drift on the mart is caught
at read time, never silently skipped by resuming past a bad page.

### Customer.io consent export (`customerio-consent-ingress`, DNA-891)

`packages/consent-ingress` reads the Customer.io consent export landed in Snowflake, database
`streamline`, schemas `cio_raw` (raw landing) and `cio_prod` (modeled) — the export mechanism
confirmed in [ADR-0005](../adr/ADR-0005-customerio-consent-on-the-governed-path.md). Same posture
as the verdict mart entry above: a fixture-pinned row contract, no live Snowflake connection in
tests (`FixtureRowSource` is the only source every test drives), per-row validation that catches
and collects malformed rows rather than aborting the run.

| Dependency | Kind | Source | Breakage risk |
|---|---|---|---|
| `streamline.cio_raw` | Snowflake schema, raw landing | Customer.io export, delivered — no live Customer.io API pull in v1 ([ADR-0005](../adr/ADR-0005-customerio-consent-on-the-governed-path.md)) | schema drift on the vendor export becomes a counted `RowError` naming the row's page offset and offending column, never a contact value, and never aborts the page |
| `streamline.cio_prod` | Snowflake schema, modeled | Customer.io export, delivered — no live Customer.io API pull in v1 ([ADR-0005](../adr/ADR-0005-customerio-consent-on-the-governed-path.md)) | same as above; this ingress reads whichever schema its `RowSource` is configured against |
| `CONTRACT_COLUMNS` (pinned row contract) | fixture-pinned column set: `subject_key`, `channel`, `to_state`, `message_id`, `event_time` | `packages/consent-ingress/src/consent_ingress/row_source.py` | a row missing a contract column, or an `event_time` that fails to parse as a timezone-aware timestamp, is the only reason a row fails validation |

### Mongo connection pattern (`bf0a-archaeology-access`)

`packages/archaeology` inherits its Mongo connection posture from `brookai/streamline`'s CDC
service rather than inventing one — the driver choice (sync `pymongo>=4.8` `MongoClient`), the
bounded-timeout posture (`serverSelectionTimeoutMS`/`connectTimeoutMS`/`socketTimeoutMS`,
streamline's defaults), TLS-on-by-default (Atlas), and fail-fast env-sourced config. This is a
consumed *pattern*, read from source, never a side-clone: any drift from upstream is a documented
divergence in the package README, not an accident. Two divergences are deliberate: credentials
arrive as a secret-store reference (never a literal connection string), and `retryWrites` is off
because the seam is read-only by charter.

| Dependency | Kind | Source | Breakage risk |
|---|---|---|---|
| Mongo client construction pattern | source pattern (read, not imported) | `brookai/streamline`, `repos/dacorom/mongo-stream/src/config.py` and `src/watcher.py` | upstream changing its driver or timeout posture silently strands this copy — re-read the cited paths when streamline's CDC service changes; streamline publishes no contract for this surface, so the citation is the only pin |

### Event transport (runtime)

With the Kafka → EventBridge migration
([ADR-0002](../adr/ADR-0002-ocean-absorption-and-eventbridge-transport.md)), the absorbed OCEAN
services in `packages/ocean` consume AWS messaging primitives instead of a broker:

| Dependency | Kind | Source | Breakage risk |
|---|---|---|---|
| EventBridge `ocean` bus | AWS managed bus | `boto3` / `aiobotocore`; bus name via `OCEAN_EVENT_BUS_NAME` | PutEvents entry cap (256 KB) rejects oversized envelopes; missing bus name would route to the account `default` bus, so it is never left unset |
| SQS consumer queues | AWS managed queues | one queue per consumer, URL via `SQS_QUEUE_URL` | standard queues do not preserve order — order-dependent consumers carry a sequence guard keyed on the envelope key |
| LocalStack | local dev container | `packages/ocean/infra/docker-compose.yml` | local-only stand-in for the two rows above; provides bus, rules, queues, DLQs |
| Postgres `failed_webhooks` | table (publish DLQ fallback) | ocean's own Postgres | a publisher constructed without a `db_session_maker` logs failures without durably queuing them |

`confluent-kafka` and the Redpanda containers are removed. None of these is reached by
`task check` — no live network in tests; the LocalStack stack exists for local simulation runs.

### Twenty rejection-commentary API (`twenty-kanban-webhook-ingress`, DNA-878)

`pulse_ledger.twenty.client` attaches a rejection note back to the Twenty card via Twenty's REST
API — the one outbound surface the D8 kanban route introduces (rejection-commentary creates only,
no other verb). The original `POST /rest/comments` pin was **falsified live** (7.2's assertion-9
run, 2026-08-17): v2.30 has no `comment` object. The record-attached commentary surface is a
`note` plus a `noteTarget` binding it to the record by the flat relation column
(`targetPatientProgramId` — custom-object targets take the `target` prefix, live-verified 2026-08-18) — task 6.7. The two
create-response shapes follow the live-verified `create` + capitalized-singular convention but
have not yet been individually exercised live; every test runs against synthetic responses at the
HTTP boundary, `--disable-socket`. A shape drift surfaces as a typed `CommentPostError` at the
client boundary, never as a silent misread.

| Dependency | Kind | Source | Breakage risk |
|---|---|---|---|
| `POST /rest/notes` + `POST /rest/noteTargets` | REST API (creates live-verified 2026-08-18: `note` carries no `body` field — rich text is `bodyV2` created as `{"markdown": …}`, server-converted to blocknote; target binds via the flat `<objectName>Id` column) | Twenty; bearer token via `PULSE_LEDGER_TWENTY_API_TOKEN` | create-shape drift surfaces as `CommentPostError` on the rejection-feedback leg, which degrades feedback and never rejection correctness; re-verified by demo3's assertion 9 |

### Twenty Metadata API (`pulse-app-scaffold`, DNA-908)

`pulse_core.twenty_metadata` serializes the Twenty workspace model — objects, fields, relations,
SELECT options, roles — as a set of Metadata API operations, committed at
`packages/twenty-app/artifact/operations.json`, and `pulse_core.twenty_deploy` applies that
artifact to an instance. D4 (DNA-908, 2026-08-12) decided the split: build ≠ publish, and the same
artifact promotes dev → staging → prod. So the consumed surface is the **operation-set shape**, not
a live instance — CI builds and validates the artifact with no server reachable
(`task twenty:validate`, `--disable-socket`).

The artifact pins its own shape with two version keys, and nothing else stands in for them:
`artifactVersion` (`1`) is the operation-set schema this repo serializes against, and
`catalogVersion` (`1.1.0`) is the state-catalog release whose dimensions became SELECT options in
that render. A change to either is a deliberate re-render, caught by the staleness check in
`task check`, never a silent drift.

The server-side half of the pin is the image: SPCS deploys the pinned upstream `twentycrm/twenty`
tag, never a build from patched source (`design/platform/pulse-app-scaffold.md` §SPCS deployment —
an image built from patched source is a fork, and AGPL §13 obligations attach). The dev instance
(DNA-909, provisioned 2026-08-16) runs upstream **v2.30.0**, and every live-verified claim below
is pinned to that version. Upstream migrations can land on app-declared objects, so a tag bump is
a deliberate event verified against a parallel instance, not a routine upgrade.

**The F1 answer (twenty-dev-instance 1.7): positive.** A `universalIdentifier` supplied on a
Metadata API create **round-trips** — it is stored and read back unchanged, not dropped by the
create input — observed on v2.30.0 (2026-08-16) and reconfirmed at full-artifact scale by the
49-operation read-back below. F1 is what makes the promotion model above tenable at all:
create-if-absent keying and cross-environment identity both rest on the artifact's
`universalIdentifier`s surviving the create. A tag bump re-answers F1 before anything else.

| Dependency | Kind | Source | Breakage risk |
|---|---|---|---|
| Metadata API operation set | serialized artifact, pinned in this repo (`packages/twenty-app/artifact/operations.json`, keys `artifactVersion` / `catalogVersion`) | Twenty; shape decided by D4 / DNA-908 | **live-verified against dev (v2.30.0, 2026-08-17)**: all 49 operations read back under their mapped `universalIdentifier`s, immediate re-apply all no-ops — a shape drift upstream surfaces as a failed apply, not as bad data, because validate-before-apply refuses anything the schema rejects |
| `twentycrm/twenty` image tag | pinned container image (SPCS) | upstream release, pinned in the SPCS service spec — dev runs v2.30.0 (DNA-909) | an unpinned or bumped tag changes the server-side Metadata API shape under a fixed artifact; upgrades are tested against a parallel instance before promoting |

Ground truth is the read-back verification (`pulse_core.twenty_verify`, `task twenty:verify
TARGET=dev`): every artifact operation's target present with its mapped `universalIdentifier`,
then an all-no-op re-apply. It passed against dev on 2026-08-17 (pulse-app-scaffold 4.1, receipt
checksum `4a47b973…` on DNA-918) and re-runs on any tag bump before promoting.

### Twenty core REST API (`pulse-app-scaffold` 4.2, live-verified v2.30.0)

`packages/twenty-app/src/live/rest-core-api.ts` (the live `CoreApiClient` behind
`project-domain-event`) and `pulse_core.twenty_seed` consume Twenty's core record surface:
`GET/POST /rest/<plural>`, `PATCH`/`DELETE /rest/<plural>/<id>`. The pinned shape, confirmed by
the 4.2 live run rather than assumed: relation columns write and read **flat** (`patientId`,
never nested `{"patient": {"id": …}}` — the nested form is a 400); `filter=<field>[eq]:<value>`
is comma-joined AND with no quoting (the client refuses values containing `,` `:` `[` `]` rather
than escaping); SELECT values are stored UPPER_SNAKE-encoded (`referral.received` →
`REFERRAL_RECEIVED`, see the `twenty-artifact-deploy` spec).

| Dependency | Kind | Source | Breakage risk |
|---|---|---|---|
| core REST record surface | REST API, live-verified against dev v2.30.0 (2026-08-17) | Twenty; bearer token per target environment | grammar and relation-column drift surfaces at the client boundary (refused values, 400s), never as silent misreads; re-verified by `task twenty:verify:live TARGET=dev` on any tag bump |
| view read surface | metadata GraphQL `getViews` on `/metadata`, live-verified v2.30.0 (2026-08-17, `twenty-dev-instance` 6.5) — there is no `getCoreViews` on `/graphql`, and the live `View` type carries no `universalIdentifier`, so boards match on (object id, type, name) | Twenty; bearer token per target environment | a surface drift fails demo3's assertion 2 by name, never a silent mismatch; the unit suite pins the query shape offline |

### Producer-policy gate (`producer-ingress-policy`, DNA-885–DNA-888)

`tests/test_producer_ingress_policy.py` classifies `packages/ocean` producer source against the
state catalog contract published in the "State catalog" entry of `publishes.md`. The gate reads
exactly the pinned surfaces — nothing else: not the retired Appendix C seed, not the Snowflake
`catalog` schema rows, not `catalog_gen`/`catalog_release` internals. Policy and procedure are
documented at `packages/ocean/docs/producer-policy.md`.

| Dependency | Kind | Source | Breakage risk |
|---|---|---|---|
| `catalog/state_catalog.yaml` | versioned YAML file, repo head | this repo, `catalog-authority` | a catalog release narrowing or removing a state can turn an existing ocean vocabulary red — intended per §4.4, the failure names the exact collision |
| `pulse_core.generated` (`TRANSITIONS`) | workspace package surface | this repo, `catalog-authority` | the classifier takes `transitions` as an injectable argument, defaulting to this surface; a signature change to `TRANSITIONS` breaks the gate at import time, not silently |

### Toolchain

pulse consumes four external tools, inherited from the repo-ade template. None is vendored; each
is installed independently and pinned only where a gate depends on its behaviour.

| Dependency | Kind | Source | Breakage risk |
|---|---|---|---|
| OpenSpec | npm global CLI | `@fission-ai/openspec` | change lifecycle commands; `spec:archive` gate |
| OpenLore | npm global CLI + MCP server | `openlore` | `openlore drift` is a pre-commit hook; `orient()` for agents |
| Orca ADE | desktop app + CLI | onorca.dev | worktree execution; `dispatch_tasks.py` prints its commands |
| go-task | task runner | brew / taskfile.dev | every documented command; CI invokes `task check` |
| Linear CLI | CLI, **optional** | linear.app | only `workflow:lint:linear`; absent means that check skips, never fails |
| Linear GraphQL API | HTTPS API, **optional** | `api.linear.app/graphql` via `LINEAR_API_KEY` | only `linear:sync`; absent means it plans without mutating |

Both Linear entries are optional, and neither is ever reached by `task check`.

`workflow:lint:linear` verifies WORKFLOW.md's declared team, project and status set against the
live workspace, printing `SKIPPED` and exiting 0 when the client is missing. A gate that fails
because a machine lacks an optional tool teaches people to ignore it; one that answers and
disagrees is a hard failure.

`linear:sync` talks to the GraphQL API directly over stdlib `urllib` — deliberately no HTTP
dependency, so the workspace lockfile stays untouched. Without `LINEAR_API_KEY` it prints the plan
it would apply and exits 0; `APPLY=1` without a key is an error rather than a silent no-op.

Python dependencies are declared in `pyproject.toml` and locked in `uv.lock`; that lockfile, not
this table, is the source of truth for them.

Because OpenSpec and OpenLore are npm globals that CI runners do not install, they must stay out
of `task check`. `tests/scaffold/cat4_ci_contract.py` enforces this.
