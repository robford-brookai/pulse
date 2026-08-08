# Runbook: catalog-release

Operator procedure for releasing a catalog version to the Snowflake `catalog` schema (D18 /
ADR-0004). A release lands one catalog version as immutable, tagged rows — `STATES`,
`TRANSITIONS`, `VALUESET_CODES`, `PROGRAMS`, and a `VERSIONS` row carrying the version, git
provenance, and the snapshot's sha256 — rendered by `pulse_core.catalog_release` and applied
through the immutability guard in `pulse_core.catalog_release_cli`. The consumer contract these
rows serve is pinned in `docs/contracts/publishes.md`.

## The release procedure

Everything before the deploy step is an ordinary PR; `task check` gates all of it offline.

1. Edit `catalog/state_catalog.yaml` — the only place catalog content changes. Bump
   `catalog_version`: MAJOR exactly when the diff is breaking (a removed state, a narrowed
   ValueSet, a transition legality change in either direction — runtime-readiness §4.3, as
   classified by `pulse_core.catalog_breaking`), MINOR/PATCH for additive changes.
2. Regenerate the programmatic surface: `uv run python -m pulse_core.catalog_gen`. The
   render-equals-committed drift test fails `task check` if you skip this.
3. Freeze the snapshot: copy the head file byte-identical to `catalog/releases/v<version>.yaml`
   and append its sha256 line to `catalog/releases/MANIFEST.sha256`. The manifest is append-only —
   never rewrite an existing line.
4. Breaking release only: add `catalog/releases/v<version>-migration.md` with the consumer
   checklist (Twenty metadata redeploy, ConceptMap regeneration, `rule_version` bump if verdict
   criteria reference the changed codes). The ceremony check in `task check` fails a breaking
   diff that lacks the MAJOR bump or the migration note.
5. Open the PR and merge. On merge to `main` touching `catalog/**`,
   `.github/workflows/catalog-release.yml` runs `task catalog:release APPLY=1` with credentials
   from Actions secrets and applies the newest manifest version from its frozen snapshot.

The apply is idempotent: a version row already present with a matching checksum is a successful
no-op ("already released"), so re-running a deploy never double-writes.

## Manual fallback: `task catalog:release APPLY=1`

The workflow is inert config until its deploy steps exist — the `SNOWFLAKE_*` Actions secrets and
an Actions budget (the account budget is currently $0, which rejects runs; check
`settings/billing/budgets` before trusting a green merge to have deployed). Until then, and
whenever Actions is unavailable, release manually from a clean checkout of the merged `main`:

1. Inspect the plan first — no credentials needed, nothing mutates:

   ```bash
   task catalog:release
   ```

2. Export credentials and apply:

   ```bash
   export SNOWFLAKE_ACCOUNT=... SNOWFLAKE_USER=... SNOWFLAKE_PASSWORD=...
   export SNOWFLAKE_DATABASE=...   # optional; placeholder default until the deploy pins it
   task catalog:release APPLY=1
   ```

`APPLY=1` without credentials exits nonzero naming the missing variables — there is no silent
no-op. The manual path runs the same renderer and the same guard as the workflow, so it is safe
to run even if the workflow later fires for the same version.

## No hand edits, and who can write

Released rows are never edited — not by humans, not by a job. The rendered SQL is
`CREATE ... IF NOT EXISTS` plus INSERTs only; no UPDATE or DELETE exists in the release path, so
"fix it in Snowflake" is structurally unavailable. Every catalog change is an edit to
`catalog/state_catalog.yaml` in git, released as a new version.

The writer-role posture (runtime-readiness §4.2): only the release job's dedicated role holds
INSERT on the `catalog` schema; humans hold SELECT. Object tagging (`CATALOG_VERSION` on the
schema and every table) plus access history answer "who read or changed catalog state". Granting
and enforcing the role is warehouse admin work outside this repo — this runbook records the
posture the admin applies.

## Conflicting-checksum triage

The guard hard-fails **before any write** when the target version's `VERSIONS` row exists with a
checksum different from the frozen snapshot's, naming the version and both checksums
(`ReleaseConflictError`). This means the version was released from content that no longer matches
`catalog/releases/v<version>.yaml` — one side has been rewritten.

1. Recompute the local side: `shasum -a 256 catalog/releases/v<version>.yaml` and compare against
   that version's line in `catalog/releases/MANIFEST.sha256`. A mismatch here means the snapshot
   or manifest was rewritten in git — the snapshot immutability gate in `task check` fails on
   exactly this, so find the commit (`git log -p catalog/releases/`) and revert it. Released
   snapshots are history, not working files.
2. If snapshot and manifest agree, the warehouse row is the rewritten side — someone or something
   wrote the `VERSIONS` row outside the release path. Do not "correct" the row and do not force
   the release. The manifest in git is the record of truth: escalate to the warehouse admin to
   investigate via access history (the writer-role posture makes the writer identifiable) and
   restore the row to the manifest checksum.
3. Never resolve a conflict by rewriting the released version to new content. If the released
   content itself is wrong, ship the fix as the next `catalog_version` through the ordinary
   procedure above.
