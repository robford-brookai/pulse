# Proposal — bf0a-archaeology-access

## Why

BF-0b — the Mongo archaeology session that prices the entire backfill Stage 2 by establishing the
CDC coverage window and per-grain evidence ceilings — cannot run until a read-only access seam
exists. BF-0a is that seam, and it is gate-free today: the only diff-producing work in the BF-0
batch (`design/migration/bf0-mongo-archaeology-agent-batch.md`), deliberately built so none of
the tooling is throwaway — the same package later becomes the bulk-extraction seam for BF-5.

## What Changes

- New workspace package `packages/archaeology`: a **read-only** Mongo client factory that builds
  its connection from env-var references to the DuploCloud secret store (never literal
  credentials, never a committed connection string), inheriting the connection pattern from
  `brookai/streamline` (driver choice, TLS posture, retry config) rather than inventing one.
- The factory refuses to construct if the resolved user has write roles, where detectable —
  read-only is enforced at the Atlas role level; the refusal is defense in depth.
- A smoke CLI (`python -m archaeology.smoke --list-collections`) whose exit status is BF-0b's
  access receipt. Collection names only — no field values, no documents.
- A README recording the hard precondition (read-only Atlas role provisioned by the operator,
  env var names defined here and consumed by BF-0b) and the future bulk-extraction-seam note.
- A credential-material gate: no `mongodb+srv://…@` or secret material anywhere in the tree.

## Capabilities

### New Capabilities

- `archaeology-access`: read-only, env-var-credentialed access to the legacy Mongo cluster —
  the single seam all backfill discovery and extraction flows through.

### Modified Capabilities

_None._

## Impact

- New workspace member; edits root workspace manifest (serial: workspace_roots).
- Unblocks BF-0b (operational-discovery session, outside Orca), which fills the evidence-ceiling
  table gating BF-5 scope.
- No PHI anywhere in this change: tests are socket-blocked, fixtures synthetic, the smoke CLI
  emits names only.
- Rollback: delete the package; nothing depends on it until BF-0b runs.
