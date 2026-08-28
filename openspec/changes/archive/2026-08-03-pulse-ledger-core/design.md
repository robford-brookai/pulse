# Design — pulse-ledger-core

## Context

See proposal.md — Why. Constraints that shape the design:

- Object model v0.7 (`design/migration/rpc-object-model-assessment.md`) is doctrine: six subject
  types with their own grains, invariants I1–I9, plus I10 (bitemporality) from the backfill plan.
- The v1 platform docs disagree with v0.7 in two places this change must resolve: the envelope
  spec accepts-and-flags illegal transitions (we reject at write time), and the state-catalog v1
  grain is `patient × program` (we adopt the six-subject model). Both v1 docs get superseded
  notes in 10.x-style doc tasks.
- Runtime decisions already made: D14 SPCS target (EKS fallback), D15 per-service creds + HMAC for
  the Twenty path, D16 idempotency, D17 outbox semantics, D18 catalog releases live in Snowflake.
- Downstream S1.2–S1.4 work orders consume named surfaces ("confirm path" markers); this change
  pins those names.
- The distribution layer is done: EventBridge bus, catalog-generated addressing, LocalStack local
  stack, per-queue DLQs (see `openspec/specs/event-transport` and `event-delivery`).

## Goals / Non-Goals

**Goals:**

- One ledger schema that survives backfill (bitemporal, evidence class, epoch) with zero
  migrations between S1.1 and BF-x.
- One write path where legality, idempotency, and attribution are structural, not conventions.
- Pin the names downstream orders left open (client path, read endpoints, quarantine table,
  handler signature, cursor facility).

**Non-Goals:**

- No projection into Twenty (S2), no verdict computation (warehouse), no scheduling (S1.3), no
  matcher logic (S1.4), no genesis/backfill loader (BF-3) — only the schema and API affordances
  they need.
- No probabilistic anything; no PHI in fixtures or logs (Synthea/synthetic only until C1).
- Not deciding SPCS vs EKS (D14 spike is separate); the service must run identically on either.

## Decisions

1. **Store: Postgres (Snowflake Postgres per runtime readiness §2.1), one schema `ledger`.**
   Tables: `events` (append-only, `event_id` UUIDv7 PK, subject_type, subject_key, event_type,
   `effective_at`, `recorded_at` server-set, actor fields, `rule_version`, `evidence_class`
   default `E0`, `epoch` default `declared`, `correlation_id`, `causation_id`, `reverses_event_id`
   nullable, `payload` JSONB), `current_state` (one row per subject, updated in-transaction),
   `idempotency_keys` (key PK → event_id, kept forever per D16), `outbox` (event_id, subject_key,
   per-subject `seq`, attempts, published_at), `writer_state` (writer_id, cursor JSONB),
   `review_queue` (subject ref, hold fact ref, candidate set, pending flag, and
   `resolution_event_id` — a row leaves the queue only by naming the resolution that drained it).

   Two further tables serve the identity lookups `ledger-read` requires, added by migration 0003:
   `external_identifiers` (PK `(system, value)` — the uniqueness rule *is* the primary key, so an
   identifier resolves to at most one person by construction; append-only for the service role, and
   rebinding is a `merge_person` declaration rather than an UPDATE) and `person_match_keys` (the
   composite the deterministic matcher falls back to, stored as a **sha256 digest only** — the
   readable composite is last name + DOB + sex + first-initial, which is PHI, and a `[0-9a-f]{64}`
   check constraint is what keeps it out of the ledger by construction). Eight tables, not six.

   `external_identifiers` is a **registry, not a state-bearing subject**: `person` is absent from the
   catalog's `TRANSITIONS` and from `events.subject_type`'s check constraint, so an attachment is a
   registry row carrying its actor attribution, not a ledger event. This matches the object model
   (`design/migration/rpc-object-model-assessment.md`: ExternalIdentifier is a registry child,
   state-bearing: no). Making every attachment an event instead would require adding `person` as a
   subject type in both the catalog and the check constraint — a spec-level decision, not an
   implementation one, and deliberately not taken here.

   Alembic sequence separate from ocean's (`packages/pulse-ledger/infra/postgres/`), avoiding the
   3.0-style collision lane entirely. Within this sequence, revision ids are unique and single-headed
   by gate: `tests/test_migration_graph.py` holds that invariant, because alembic itself only warns
   on a duplicate revision id and then silently drops one of the two migrations.
   *Alternative rejected:* events in Snowflake directly — write-path latency (p99 < 500 ms) and
   transactional co-commit rule it out; Snowflake stays the verification/analytics layer.
2. **Transport: HTTP + JSON service (`packages/pulse-ledger`), client SDK `packages/pulse-core`
   (`pulse_core/client.py` — this pins the S1.2–S1.4 "confirm path" marker).** REST over gRPC
   because the Twenty webhook path (D8 heal-back) and HMAC signing are HTTP-native, and every
   internal writer is Python. Endpoints: `POST /commands` (single), `POST /commands:batch`
   (backfill mode, same validation), `GET /state?subject_type=&state=` (current-state read),
   `GET /identity/candidates`, `PUT/GET /writers/{writer_id}/cursor`, `GET /review-queue`.
3. **Immutability enforced in the store, not just convention:** REVOKE UPDATE/DELETE on
   `events` from the service role; correction is `reverses_event_id`. This is what keeps
   `Q_EVENT_MUTATIONS` empty by construction.
4. **Legality data comes from the catalog's generated surface** (S0.2 machinery; Appendix C seed
   until then): the generator emits Python transition tables + Pydantic command types into
   `pulse_core.generated`, versioned by `catalog_version`, and the service refuses to boot if its
   generated tables' version disagrees with the catalog release it's configured for (D18).
   Trinary verdict enum with mandatory-reason-on-indeterminate is generated, not hand-written.
5. **`effective_at` is the canonical name; `occurred_at` is accepted as an input alias** at the
   API boundary for envelope compatibility and normalized on write. Resolves the unreconciled
   naming between the envelope spec and I10.
6. **Response classification is part of the client contract:** `committed | replayed | rejected
   (with catalog reason) | transient` — mapped from HTTP status + body by `pulse_core`, so S1.2's
   declarer never parses raw responses. Consumer convention: `pulse_core.consume(handler)`
   wrapping SQS receive/process/delete with `event_id` dedupe — same shape the converted ocean
   consumers use.
7. **Outbox relay is a worker in the same package** publishing through the shared
   `EventBridgePublisher` from `packages/ocean/libs/ocean-broker` — reusing the archived change's
   publisher, addressing catalog, and DLQ conventions rather than inventing a second publisher.
8. **Auth:** per-writer bearer credentials resolved server-side to `writer_id` = `actor`; the
   body's actor field is ignored for authenticated internal writers (spoof attempt → rejected in
   strict mode, logged always). HMAC verification middleware exists but only the Twenty webhook
   route uses it (D8/D15); that route ships disabled until S2.

## Risks / Trade-offs

- **Catalog machinery (S0.2) is not fully landed** → the generator consumes Appendix C's seed
  until the catalog file is authoritative; the seed's retirement clause makes this a documented,
  temporary indirection rather than a fork.
- **Two alembic sequences in one repo** (ocean's and the ledger's) → acceptable; they live in
  different packages with different lanes, and the serial-lane rule from the archived change
  applies per-sequence.
- **Postgres single-writer is a scaling ceiling** → fine at PRM volume by orders of magnitude;
  the outbox isolates consumers from it, and the SLO (p99 < 500 ms commit) is measured from day
  one.
- **Rejecting at write time can strand legitimate late corrections** → mitigated by bitemporal
  backdating (legal transitions with past `effective_at`) and reversal events; the backfill
  vocabulary handles the genuinely unsequenceable.
- **PHI**: the ledger is a PHI store by design once C1 clears; until then all environments run
  synthetic data only, and error messages/logs carry subject keys, never demographics — a
  security-review item on every PR touching handlers or logging.
