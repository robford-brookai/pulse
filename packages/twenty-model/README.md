# twenty-model

The artifact-owned half of the Twenty model: the six objects and the three roles, as
`twenty-sdk/define` sources.

These are not published with the app. They are compiled into `artifact/operations.json` by
`task twenty:gen` and applied to a workspace by `task twenty:deploy`, which owns them from then
on. The TypeScript here is what `packages/twenty-app/tests/model.test.ts` checks — relations
mirrored, options generated rather than written, roles granting no delete — so the model has one
reviewable form even though the Python generator is what serializes it.

## Why it is not a directory inside `packages/twenty-app/`

The Twenty CLI derives an app's entity set from the file tree: it globs `**/*.ts` under the app
path and turns every inline `export default defineObject({...})` / `defineRole({...})` into a
manifest entry. An app that declares an object the workspace already owns cannot install — 7.2's
live publish returned 45 `ENTITY_ALREADY_EXISTS` and 40 `FIELD_ALREADY_EXISTS` against a
workspace the artifact had already deployed to.

So the exclusion is the tree. These sources sit one directory up from the app path, where the
CLI's glob does not reach, while `packages/twenty-app/tsconfig.json` still includes them and the
app's vitest suite still imports them. Moving a file back under `packages/twenty-app/` would
silently rejoin the manifest and break the next install; `tests/test_twenty_app_scaffold.py` and
`packages/twenty-app/tests/manifest.test.ts` both refuse it.

| Path | Holds |
|---|---|
| `objects/` | `defineObject` — Patient, Program, PatientProgram, Provider, Clinic, DomainEvent |
| `roles/` | `defineRole` — producer, staff, app: the single-writer rule as config |

Identifiers come from `packages/twenty-app/uid-map.json` through `uid()`, and SELECT options from
`packages/twenty-app/generated/options.ts`. Both are generated surfaces shared with the app, which
is why the import points back into it.
