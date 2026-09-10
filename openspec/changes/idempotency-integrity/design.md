## Context

Read command-api and ADR-0004 D16 alongside api_server, idempotency.py and pulse_core.idempotency. The SDK key hashes a client logical_time that is not guaranteed to arrive as a separate server field. The current server lookup is global by key and reconstructs a result from the stored event. Existing tests explicitly accept different facts under one key.

## Goals / Non-Goals

**Goals:** Exact retry equivalence, isolation between authenticated writers, explicit collision errors, and migration without losing lifetime key retention.

**Non-Goals:** Requiring the server to recreate the SDK digest from unavailable client-only logical_time, changing event ids, changing valid key spelling, or replacing authentication.

## Decisions

### 1. Binding is checked before replay

Use the authenticated Writer at bearer ingress and the fixed authenticated webhook principal for
Twenty. Persist a versioned request fingerprint in a companion binding table keyed by the existing
idempotency key, alongside writer identity and the referenced event. Keep the existing global key
uniqueness so historical keys are not accidentally released into a new namespace. A key owned by a
different writer is a generic conflict, with no original event/result returned. Do not trust the
text before the colon as authentication. Prefix validation is not necessary for compatibility.

### 2. Fingerprint the accepted semantic request

Define canonical v1 fields at the boundary: command type, subject type/key, normalized effective_at,
accepted event type/state, reason, evidence and caller-controlled payload fields. Normalize UTC aliases
and object-key order; keep list order and semantically distinct values. Exclude the idempotency key,
credentials, server recorded_at/catalog stamp, and transport-only tracing. Enumerate the exact field
map in the implementation contract and tests; a field-set change requires a fingerprint version.
Do not recompute the opaque SDK digest: its client logical_time need not equal effective_at. Do not
log payloads or fingerprints; they can be derived from sensitive values.

### 3. API behavior and concurrent insertion

HTTP single-command mismatch returns 409 with code `idempotency_conflict`, classified as rejected,
never transient. Batch preserves its current envelope/transaction policy and reports a per-item
conflict without exposing the prior result. Twenty keeps 200 plus a rejected disposition, with a
safe reason code. The original command and exact retries retain their success shape. Claim event,
key, and binding atomically; the race-loser path rechecks binding before replay. Do not catch every
exception and return a winner until identity and fingerprint match.

### 4. Legacy keys and stable retry results

Read the original event to establish the authenticated actor and reconstruct only fields the stored
event proves. If the v1 request can be reconstructed completely, create its binding transactionally;
otherwise return a distinct generic `idempotency_legacy_unverifiable` rejection and require a reviewed
reconciliation path. Never guess a fingerprint, drop a key, or replay a different writer's event.
Inventory synthetic legacy cases before rollout and block enforcement release if valid deployed
producer retries would become unverifiable without a migration path. Use a receipt bound to the
original commit's sequence/snapshot rather than a wall-clock cutoff alone when proving replay state;
same-timestamp events and concurrent transaction start times must not change the original result.

### 5. Compatibility and decision record

This is an intentional tightening of the currently tested collision behavior. Proposed 2026-09-10;
approval of the D16 amendment and deployed-producer compatibility evidence gate enforcement rollout.
Stage expand → producer-compatible server/SDK → verified legacy bindings → enforce, with no deletion
of ledger or key history. Existing valid retries are the compatibility acceptance criterion.

## Risks / Trade-offs

[Historical requests cannot be reconstructed] → block rollout on an inventory and explicit reconciliation path. [New 409 retried forever] → SDK and all ingress contract tests before enforcement. [Fingerprint normalization drift] → versioned golden vectors and timezone/key-order tests.

## Migration Plan

Add the companion binding table and restrictive grants first. Test legacy replay, reversals, identical timestamps and two-connection races on an upgraded database. Stage the server and SDK together, run synthetic connector/webhook compatibility checks, then enforce after the inventory gate. Preserve binding data on rollback; a rollback may reopen old collision behavior and must be recorded and bounded rather than called safe by default.
