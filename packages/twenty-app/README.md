# twenty-app

The Twenty app: the PULSE data model, roles, views, and projection logic declared as
TypeScript in this repo. Stock Twenty server, no fork — see
`design/platform/pulse-app-scaffold.md` for why cloning `twentyhq/twenty` is the contributor
path and not ours.

This is the repo's first TypeScript package. It is deliberately contained: one package,
vitest only, no bundler. Node is pinned in CI as a setup step.

## Two surfaces, two owners

The model reaches a workspace by two different paths, and they are disjoint on purpose.

- **The artifact** — objects, fields, options, and the three real roles — is applied by
  `task twenty:deploy` from `artifact/operations.json`, which this repo generates and validates.
  Its TypeScript sources live in `packages/twenty-model/`, *outside* this package.
- **The packaged app** — views, navigation, the `project-domain-event` logic function, and one
  placeholder default role — is published by `task twenty:app:publish` and installed by the
  server.

They are split because an app cannot adopt entities the workspace already owns: a full-model
install returns `ENTITY_ALREADY_EXISTS` for every object the artifact deployed. A views-only
package installs cleanly, and its views bind to the workspace-owned objects and fields by
`universalIdentifier` — which is why both halves read the same `uid-map.json`.

The split is enforced by the file tree, because that is what the CLI reads: it globs `**/*.ts`
under the app path and publishes every inline `export default defineObject(...)` it finds. So an
object source moved back under `packages/twenty-app/` would rejoin the manifest and break the
install. Two gates hold it — `tests/manifest.test.ts` (what the built manifest carries) and
`tests/test_twenty_app_scaffold.py` (what the tree contains).

## Layout

| Path | Holds |
|---|---|
| `src/views/` | `defineView` — ops-facing saved views |
| `src/navigation/` | `defineNavigationMenuItem` — the sidebar entry for the board |
| `src/logic-functions/` | `defineLogicFunction` — `project-domain-event` |
| `src/roles/` | the placeholder `defineApplicationRole` the SDK requires; grants nothing |
| `src/application-config.ts` | `defineApplication` — identity only |
| `generated/` | `options.ts` and `projection-lookup.ts`, emitted from `state_catalog.yaml` |
| `artifact/` | `operations.json` — the serialized Metadata API operation set |
| `tests/` | vitest unit suite; no server, no network |
| `uid-map.json` | `universalIdentifier` map, checked in, append-only |
| `src/uid-map.ts` | `uid(key)` — the map read as data, erroring on a key it lacks |
| `../twenty-model/` | `defineObject` and the three `defineRole`s — artifact-owned |

Entity detection is syntactic: `export default define*({...})` written inline is an entity, and a
const re-exported as the default is invisible to the CLI. Folder names are convention; the
default-export form is not.

## Kanban columns and the option encoding

Twenty's Metadata API stores SELECT option values UPPER_SNAKE (`ACTIVE`), while the catalog's
vocabulary is lowercase and dotted (`active`, `referral.received`). `generated/options.ts`
carries both — `value` for reasoning, `encodedValue` for anything keyed on a *stored* value. A
kanban view group is exactly that, so every column's `fieldValue` is the encoded form; keyed on
`value`, the columns render and no card can ever land in one.

## `uid-map.json`

A flat object keyed by stable name — `<object>`, `<object>.<field>`,
`<object>.<field>.<option>` — mapping each to its `universalIdentifier`. Two rules make it
work:

- **Append-only.** An existing entry is never changed. A `universalIdentifier` is what
  survives a sync, so rewriting one drops the field and recreates it.
- **The generator never mints.** A key the generator needs but does not find is a
  generation error naming the key. Minting is a reviewed diff, never a side effect of
  running codegen — an auto-minting generator is nondeterministic by construction.

The file is empty until the model definition lands and mints into it.

## Commands

```bash
task twenty:gen                  # regenerate generated/ and the operation-set artifact
task twenty:test                 # vitest unit suite
task twenty:deploy TARGET=dev    # replay the validated artifact against a target
```

`twenty:gen` and the artifact checks join `task check` once CI carries a pinned
`setup-node` step; until then they run on demand.

## Deploying the artifact

`twenty:deploy` (`pulse_core.twenty_deploy`) is the only path by which the artifact reaches
an instance. It validates before it sends, applies idempotently keyed on
`universalIdentifier` — create-if-absent, update-if-drifted, never delete — and prints a
receipt of names, counts, and the artifact's sha256. Promotion is the same file, next target.

Each target reads two environment variables, never anything in code or the artifact:

| Target | URL | Credential |
|---|---|---|
| `dev` | `PULSE_TWENTY_DEV_URL` | `PULSE_TWENTY_DEV_TOKEN` |
| `staging` | `PULSE_TWENTY_STAGING_URL` | `PULSE_TWENTY_STAGING_TOKEN` |
| `prod` | `PULSE_TWENTY_PROD_URL` | `PULSE_TWENTY_PROD_TOKEN` |

An unset variable is an error naming it, never a silent no-op. To see the plan without
sending anything — no credential needed, in which case the plan is computed against an
empty-state assumption:

```bash
uv run python -m pulse_core.twenty_deploy --target dev --dry-run
```

No instance exists yet: the Metadata API request shapes are this repo's pin, verified by
read-back once DNA-909 provisions the dev instance (`docs/contracts/consumes.md`).
