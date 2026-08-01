# PULSE App Scaffold — Development and SPCS Deployment

| | |
|---|---|
| **Status** | Draft v1 |
| **Date** | 2026-07-28 |
| **Owner** | Rob Ford, Data |
| **Related** | twenty-data-model.md; claude-code-integration-paths.md; state-catalog.md; twenty-licensing-structure-check.md |

## Decision: do not clone `twentyhq/twenty`

Cloning the monorepo is the *contributor* path — for people patching core. It violates the never-patch-core rule (licensing check §4) and pulls Twenty's build into Brook's maintenance surface.

Twenty v2.0 (April 2026) shipped the **Apps framework**: objects, fields, relations, roles, views, and server-side logic declared as TypeScript in *your own* repo, compiled to a manifest, and synced into a stock Twenty server. First-party config-as-code, no fork.

```bash
npx create-twenty-app pulse
```

## Repo layout

```
pulse-app/                     Twenty app — the data model and projection logic
├── src/
│   ├── application-config.ts  defineApplication — identity, default role
│   ├── roles/                 defineRole — single-writer enforcement
│   ├── objects/               defineObject — Patient, Program, PatientProgram,
│   │                          Provider, Clinic, DomainEvent
│   ├── logic-functions/       defineLogicFunction — project-domain-event
│   └── views/                 defineView — ops-facing saved views
├── tests/                     Vitest, integration against a real server
└── generated/                 state_catalog.yaml → *.object.ts (CI output)

pulse-infra/                   SPCS service spec, image pinning, Snowflake objects
```

Entity detection is AST-based — folder structure is convention, not requirement.

## Data model as code

Each object in twenty-data-model.md becomes a file. `universalIdentifier` is a stable UUID that survives syncs, redeploys, and environments — mint once, never change:

```ts
// src/objects/patient-program.object.ts
import { defineObject, FieldType } from 'twenty-sdk/define';

export default defineObject({
  universalIdentifier: '<stable-uuid>',
  nameSingular: 'patientProgram',
  namePlural: 'patientPrograms',
  labelSingular: 'Patient Program',
  labelPlural: 'Patient Programs',
  icon: 'IconUserHeart',
  fields: [
    {
      universalIdentifier: '<stable-uuid>',
      name: 'lifecycleStatus',
      type: FieldType.SELECT,
      label: 'Lifecycle Status',
      defaultValue: "'registered'",          // literal strings quoted inside the string
      options: [ /* generated from state_catalog.yaml */ ],
    },
    {
      universalIdentifier: '<stable-uuid>',
      name: 'lifecycleStatusAsOf',
      type: FieldType.DATE_TIME,
      label: 'Lifecycle Status As Of',
      isNullable: true,
    },
    // qualificationStatus, qualificationStatusAsOf — same shape
  ],
});
```

Notes that change the data-model doc's assumptions:

1. Base fields (`id`, `createdAt`, `updatedAt`, `createdBy`, `deletedAt`) are added automatically — don't declare them. `createdAt` is `recorded_at`.
2. `RAW_JSON` is a first-class `FieldType` — the "fallback TEXT" caveat on `payload`/`evidence` is unnecessary.
3. `isNullable: false` + `defaultValue` gives real NOT NULL constraints on `canonicalPatientId`, `eventId`, `eventType`.
4. Relations are declared bidirectionally (`MANY_TO_ONE` / `ONE_TO_MANY`); `MORPH_RELATION` exists but keep the three-nullable-relations design — explicit beats polymorphic for the reconciliation SQL.
5. `isNullable` changes apply on every sync, so nullability is editable without a migration script.

## Projection as a logic function, not a UI workflow

`defineLogicFunction` with a `databaseEventTriggerSettings: { eventName: 'domainEvent.created' }` trigger replaces the UI-configured `project-domain-event` workflow:

```ts
export default defineLogicFunction({
  universalIdentifier: '<stable-uuid>',
  name: 'project-domain-event',
  timeoutSeconds: 10,
  handler,                       // resolve entity → LWW guard → apply status
  databaseEventTriggerSettings: { eventName: 'domainEvent.created' },
});
```

Why this matters: the projection is the platform's only real logic, and this makes it **versioned TypeScript with unit tests** rather than clicks in a workflow builder. It resolves the objection raised against putting rules in Twenty workflows — same argument, better answer. `CoreApiClient` is generated from the live schema, so entity lookups are fully typed.

Test cases to write first (Vitest, against a real dev server):

1. Late event (`occurredAt` ≤ `lifecycleStatusAsOf`) → no state change, event still logged.
2. Unresolved `entityRef` → relations empty, no crash, appears in orphan view.
3. Dimension isolation — a qualification event must not touch `lifecycleStatusAsOf`.
4. First event for a (patient, program) pair creates the PatientProgram row.
5. Unknown `eventType` → rejected by picklist before reaching the handler.

## Roles as code

`defineRole` declares object- and field-level permissions in the manifest — the single-writer rule becomes reviewable config rather than admin-panel clicks:

- Producers: create-only on DomainEvent.
- Staff: read/write entities, **read-only** on status fields and DomainEvent.
- App role: whatever the projection function needs, and nothing more (the runtime token is derived from it).

## Generation from the state catalog

`state_catalog.yaml` → CI codegen → `src/objects/*.object.ts` SELECT options + the projection lookup table + dbt seeds. Generate the *options arrays*, not whole files, so hand-written field definitions stay stable. `universalIdentifier`s live in a checked-in map keyed by state name — never regenerated, or every sync recreates fields.

## Dev loop

```bash
yarn twenty dev              # local Twenty in Docker + live sync on save
yarn twenty dev:add object   # scaffold interactively
yarn twenty dev:function:exec -n project-domain-event -p '{...}'
yarn twenty dev:function:logs
yarn twenty dev:typecheck
```

CC drives this as an ordinary TypeScript repo — no metadata-API curl scripts.

## Promotion

```bash
yarn twenty remote:add --url https://<env> --api-key $TWENTY_API_KEY --as staging
yarn twenty remote:use staging
yarn twenty dev:build && yarn twenty app:publish
```

Same manifest installs in dev → staging → prod. `remote:add` is non-interactive for CI. This satisfies the reproducible-environments requirement natively.

**Typed client for other repos**: `yarn twenty dev:generate-client` produces `twenty-client-sdk` from the live schema in *any* project — use it in the signal adapter and the MCP write path so those repos get typed access without duplicating schema knowledge. Client lands in `node_modules`; re-run in `postinstall`/CI.

## SPCS deployment

Deploying **stock Twenty**, not a custom build.

1. **Image**: pull the pinned upstream `twentycrm/twenty` tag, push to the Snowflake image repository. A thin wrapper Dockerfile is acceptable only for CA certs or entrypoint config — **never for source changes**. An image built from patched source is a fork and AGPL §13 obligations attach (licensing check §4).
2. **Service spec**: server container + worker container (upstream compose runs both), readiness probe on the health endpoint, ingress behind Snowflake OAuth per the compliance memo's §164.312(a) mapping.
3. **Secrets**: `APP_SECRET`, DB credentials, `AUTH_MICROSOFT_*` from Snowflake Secrets — never literals in the spec.
4. **Storage**: SPCS containers are ephemeral; file uploads need a block volume or S3-compatible target.
5. **Postgres — the C1 gate**: Snowflake Postgres is preview, so synthetic Synthea data only until GA + written BAA scope confirmation. To avoid blocking the build: run dev/staging against a non-Snowflake managed Postgres, or accept synthetic-only. **Decide before writing the service spec** — it changes the connection string.
6. **App install in a container world**: `app:publish` targets the *running server*, so CI needs network reach to the SPCS ingress, or the app installs as a post-deploy job inside the same service.
7. **Version pinning**: pin the image tag; treat upgrades as deliberate events. Apps declare against a schema, and upstream migrations can land on your objects. Test upgrades against a parallel instance (`yarn twenty` supports one) before promoting.

## Build sequence

1. `npx create-twenty-app pulse` → `yarn twenty dev` → local Twenty running.
2. Hand-write PatientProgram + DomainEvent objects; validate the model against real field types.
3. Write `project-domain-event` as a logic function; Vitest the five cases above.
4. **Then** write the `state_catalog.yaml` → options codegen, once good output is known.
5. Roles, views.
6. SPCS work last — deployment plumbing, and step 2 may still move the model.

## Sources

- [Twenty Apps — Concepts](https://docs.twenty.com/developers/extend/apps/getting-started/concepts)
- [defineObject](https://docs.twenty.com/developers/extend/apps/data/objects)
- [Logic Functions](https://docs.twenty.com/developers/extend/apps/logic/logic-functions)
- [CLI](https://docs.twenty.com/developers/extend/apps/operations/cli)
- [Self-host setup](https://docs.twenty.com/developers/self-host/capabilities/setup)
