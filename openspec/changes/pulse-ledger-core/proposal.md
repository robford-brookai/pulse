# Proposal — pulse-ledger-core

## Why

PULSE's doctrine is "state is declared into the ledger, not derived in the graph" — but no ledger
exists. The transport migration is done (`ocean-eventbridge-migration` archived 2026-08-02;
distribution is stable on EventBridge), and the three S1 services that follow — verdict-relay
(S1.2), schedules (S1.3), identity (S1.4) — are all blocked on the ledger schema and command API
this change delivers. This is ADR Phase 1 "Record" (`design/migration/ocean-to-pulse-adaptation-plan.md`
§6), stage S1.1 on the program roadmap.

## What Changes

- **The append-only ledger schema**: one event row per declared transition or fact, with current
  state co-committed per subject. Bitemporal from day one per BF-5 — `effective_at` and
  `recorded_at` on every event (I10; retrofitting bitemporality is the named "most expensive
  schema regret"). Carries `evidence_class` (E0–E4) and epoch (declared vs reconstructed) columns
  so backfill (BF-x) needs no migration. Immutable; correction is by reversal event (I7).
- **The command API**: single writer to the ledger. Enforces transition legality at write time
  against the versioned state catalog for the six subject types (Referral, Consent, Enrollment,
  BillingEpisode, Device, Contract). **BREAKING with respect to the v1 platform docs**: supersedes
  the accept-and-flag posture of `event-envelope-spec.md` v1 and the flag-only legality of
  `state-catalog.md` v1, and generalizes the envelope's `patient|provider|clinic` entity model to
  subject-type × subject-key grains per object model v0.7.
- **Idempotency (D16)**: client-supplied key `{writer_id}:{sha256(subject, command_type, payload,
  logical_time)}`, unique-constrained; replays return the original commit result, never a second
  event.
- **Auth (D15)**: per-service credentials so `actor` attribution is enforced by auth, not
  convention; HMAC signing reserved for the Twenty webhook path.
- **Outbox relay (D17)**: transactional outbox with per-subject sequence, at-least-once relay to
  the EventBridge bus using the archived change's envelope interop, 5 attempts → DLQ with monitor.
- **Command type definitions generated from the catalog** (the fourth generated surface of §7),
  including the trinary verdict outcome (`positive | negative | indeterminate` + mandatory reason).
- **Client module** `packages/pulse-core` with response classification (committed / replayed /
  rejected / transient), a writer-state (cursor) facility, and a consumer-handler convention safe
  under redelivery.
- **Read APIs**: current-state read (so S1.3 month-open never depends on projection freshness) and
  identity candidate lookup (S1.4), plus the quarantine/review-queue table and `resolution_hold`
  fact.
- **Backfill mode**: same endpoint family and legality validation, plus `backfill_genesis` and
  `reconstruction_gap` event types restricted to the backfill actor.
- **Snowflake landing compatibility**: event rows stay flat-projectable onto the `STG_EVENTS`
  column contract so derived-state reconciliation can referee the ledger.

## Capabilities

### New Capabilities

- `ledger-record`: the append-only, bitemporal event ledger with co-committed current state,
  correction by reversal, evidence class and epoch, and Snowflake flat-projection compatibility.
- `command-api`: the single-writer write path — catalog-versioned transition legality at write
  time, D16 idempotency, D15 actor-by-auth, response classification, backfill mode.
- `ledger-read`: current-state enumeration, identity candidate lookup, writer-state cursors, and
  the quarantine review queue.
- `ledger-distribution`: the transactional outbox and its relay onto the EventBridge backbone —
  per-subject ordering, at-least-once, DLQ with monitor, envelope interop with `event-transport`.

### Modified Capabilities

_None. The four existing capabilities (event-transport, event-delivery, local-event-stack,
warehouse-event-sync, ocean-package-absorption) cover distribution and are unchanged; this change
adds the record they distribute from. The v1 platform design docs it supersedes are design docs,
not specs._

## Impact

- New package(s) under `packages/` (`pulse-core` client; service package per design), workspace
  members with the ocean-eventbridge conventions (uv, ruff, mypy, pytest, coverage floor).
- Unblocks S1.2/S1.3/S1.4; their queued work orders pin paths this change confirms (client module
  path, read endpoints, quarantine table name, consumer handler signature).
- Supersedes: `design/platform/event-envelope-spec.md` v1 ingest posture,
  `design/platform/state-catalog.md` v1 grain and flag-only legality,
  `design/platform/snowflake-landing-spec.md` CDC-from-Twenty path (ledger lands directly).
- Decisions consumed: D1, D5–D9, D12, D13 (resolved); D14–D18 (runtime readiness); D4 remains open
  and only affects promotion posture of generated types.
- Rollback: pre-production throughout — no live writers until S1.2–S1.4 land and the C1 BAA gate
  clears; reverting is deleting the packages and schema, no data migration exists yet.
