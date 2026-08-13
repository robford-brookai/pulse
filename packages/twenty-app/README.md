# twenty-app

The Twenty app: the PULSE data model, roles, views, and projection logic declared as
TypeScript in this repo and compiled into a serialized Metadata API operation set. Stock
Twenty server, no fork — see `design/platform/pulse-app-scaffold.md` for why cloning
`twentyhq/twenty` is the contributor path and not ours.

This is the repo's first TypeScript package. It is deliberately contained: one package,
vitest only, no bundler, no publishing. Node is pinned in CI as a setup step.

## Layout

| Path | Holds |
|---|---|
| `src/objects/` | `defineObject` — Patient, Program, PatientProgram, Provider, Clinic, DomainEvent |
| `src/roles/` | `defineRole` — single-writer enforcement |
| `src/logic-functions/` | `defineLogicFunction` — `project-domain-event` |
| `src/views/` | `defineView` — ops-facing saved views |
| `generated/` | `options.ts` and `projection-lookup.ts`, emitted from `state_catalog.yaml` |
| `tests/` | vitest unit suite; no server, no network |
| `uid-map.json` | `universalIdentifier` map, checked in, append-only |

Entity detection is AST-based, so the folder names are convention rather than requirement.

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
