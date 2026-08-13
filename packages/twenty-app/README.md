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
| `src/define.ts` | the `define*` surface the app source is written against |
| `src/uid-map.ts` | `uid(key)` — the map read as data, erroring on a key it lacks |

Entity detection is AST-based, so the folder names are convention rather than requirement.

`src/define.ts` stands in for `twenty-sdk/define`, which the scaffold doc's examples import. The
SDK's shape is only provable against a running server and none exists yet (DNA-909), so the types
are declared locally: `tsc --noEmit` still rejects options on a non-SELECT field or a relation
naming a field that is not one, and adopting the SDK later is a change of import path. Views and
the application config carry no `universalIdentifier` — the UID map holds exactly the surface the
artifact serializes, and the operation set has no view or application operation to key.

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
