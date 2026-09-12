# ADR-0007: Idempotency Keys Bind to an Authenticated Writer and a Canonical Request (amends D16)

- **Status**: Proposed
- **Date**: 2026-09-11
- **Amends**: ADR-0004 D16 — Command idempotency. On acceptance, D16's subsection flips to
  Superseded-in-part and points here; until then D16 stands as written and this document records
  the proposal only.

## Context

D16 ratified the shipped mechanism: a client-supplied idempotency key
`{writer_id}:{sha256(subject, command_type, payload, logical_time)}`, unique-constrained in the
ledger for its lifetime, answered on repeat with the original commit's result and never a second
event (`pulse_core.idempotency.derive_idempotency_key`,
`pulse_ledger.idempotency.commit_idempotent`).

Two things that key's text cannot carry are nonetheless trusted by the lookup, which is global and
by key alone:

- **Who sent the original command.** The text before the colon is client-supplied. D15's rule is
  that attribution is authentication — a writer declares only as itself — but the idempotency path
  never applies it: any authenticated writer that presents another writer's key text is answered
  with that writer's event id, `recorded_at`, sequence and folded state.
- **What they sent.** The digest is the SDK's, over a client-only `logical_time` the server never
  receives as a field. The ledger cannot recompute it, so it cannot check that the request behind a
  repeated key is the request that originally committed. `commit_idempotent`'s concurrency path
  goes further: a race loser whose command *differs* is answered with the winner's result, and
  `test_a_key_reused_for_a_different_fact_is_absorbed_by_the_unique_constraint` asserts that
  behaviour today.

The result is a cross-writer disclosure channel and a silent wrong-answer path for a colliding key,
both reachable by an authenticated but unprivileged writer. The keys are lifetime-retained, so the
exposure does not age out.

## Decision

**We will bind every idempotency key to the authenticated writer that claimed it and to a
versioned canonical fingerprint of the accepted request, and replay only on an exact match of
both.**

1. **Identity comes from the credential.** The bearer `Writer`, the batch route's single
   credential, or the fixed signed-Twenty principal (`pulse_ledger.api.WEBHOOK_WRITER`). The key's
   prefix establishes nothing and is not validated — validating it would break valid producers
   without adding authentication.
2. **Content comes from a canonical request fingerprint, version `v1`.** Computed at the API
   boundary over the accepted semantic request — subject type/key, event type, accepted `to_state`,
   normalised `effective_at`, epoch, evidence class, evidence, evidence bounds, and the
   caller-controlled payload. Normalisation collapses what carries no meaning (equivalent UTC
   spellings, object-key order) and preserves what does (list order, value types, present-vs-absent
   members). `pulse_ledger.request_fingerprint` is the implementation and
   `packages/pulse-ledger/tests/fixtures/request_fingerprint_v1_golden.json` the versioned vectors.
3. **The client's `logical_time` is not reconstructed.** It is hashed into the SDK key and need not
   equal `effective_at`; deriving one server-side would invent a value the client never sent and
   re-key exactly the valid retries this change exists to protect. Excluded with it: the key
   itself, the credential-derived attribution fields, the server's `recorded_at`/`rule_version`/
   `event_id`, and transport-only tracing (`correlation_id`, `causation_id`).
4. **A mismatch is a conflict, never a replay and never a disclosure.** Single-command HTTP returns
   409 `idempotency_conflict`; batch reports a per-item rejected conflict inside its existing
   envelope; signed Twenty ingress keeps 200 with a rejected disposition and a safe code. All
   classify as rejected, never transient. One generic code covers both a different writer and
   different content, so the response cannot be used to probe what a key holds.
5. **Versions are added, never edited.** The `v1` field map is frozen; a field-set change ships a
   `v2` beside it. The version is hashed into the pre-image and stored as the fingerprint's prefix,
   so a digest cannot be relabelled across versions, and a binding written under an older version
   conflicts rather than being re-derived under the current map.
6. **Legacy keys keep their reservation.** No key is released, deleted or re-pointed. A binding is
   derived only from an original event that proves the authenticated actor and every canonical
   field; anything less returns `idempotency_legacy_unverifiable` with no guessed binding and no
   result. Enforcement rollout is gated on an inventory showing that valid deployed-producer
   retries have a verified migration or reconciliation path
   (`docs/idempotency-compatibility-inventory.md`).
7. **Neither fingerprints nor request values are logged.** The fingerprint is derived from `payload`
   and `evidence` — PHI-bearing once C1 clears — so a digest of a small value space is a lookup
   table, not an anonymiser. Binding telemetry carries the key, the writer id, the fingerprint
   version and the event id, and nothing else.

Rollout stages expand → producer-compatible server and SDK → verified legacy bindings → enforce,
with no deletion of ledger or key history at any stage. Existing valid retries returning their
existing shape is the acceptance criterion for every stage.

Decider: Ford; Tal sign-off, alongside the compatibility inventory.

## Consequences

- A key is answerable only by the writer that claimed it, with the request that claimed it. The
  cross-writer disclosure channel closes, and a colliding key becomes a visible rejection instead
  of a wrong answer.
- `test_a_key_reused_for_a_different_fact_is_absorbed_by_the_unique_constraint` is an intentional
  behaviour change, not a regression: the same key with a different fact stops being absorbed and
  starts conflicting. It is rewritten when the commit path changes (task 2.1), not before.
- A companion binding table, its foreign keys and restrictive grants are added by an additive
  migration; the binding, the key claim and the event commit atomically or not at all. Rollback
  preserves binding rows — it re-opens the old collision behaviour, which must be recorded and
  bounded rather than called safe.
- Callers that varied a request between retries of one key — a widened payload, a corrected
  reason — now receive 409 where they previously received the original result. The inventory gate
  exists to find those before enforcement, not after.
- Cost: one more row per keyed command, and a normalisation surface that must be versioned
  carefully. A normalisation change that escapes the golden vectors silently re-keys every deployed
  producer, which is why the vectors are asserted rather than merely generated.

## Alternatives considered

- **Validate the key's `{writer_id}` prefix against the credential**: rejected — it reads as
  authentication without being any, since the prefix is whatever the client typed, and it breaks
  deployed producers whose prefix does not match their credential name while closing nothing.
- **Recompute the SDK digest server-side**: rejected — it needs the client-only `logical_time`, a
  non-goal precisely because guessing it re-keys valid retries.
- **Hash the raw request bytes**: rejected — a reordered JSON object or a `Z` instead of `+00:00`
  would conflict, turning ordinary valid retries into 409s. Compatibility with existing retries is
  the acceptance criterion for the change.
- **Distinguish "different writer" from "different content" in the response**: rejected — the two
  codes together let an authenticated caller probe what a key already holds; the ledger records
  which it was, the response does not.
- **Leave D16 as shipped and document the collision behaviour**: rejected — the exposure is
  reachable by any authenticated writer and the keys are retained for the ledger's lifetime, so
  documenting it neither bounds it nor lets it age out.

---

**The log is append-only.** A decision that no longer holds gets a new ADR and a status flip on
the old one — never an edit. The point is the history, not the current state; the current state
is the code.
