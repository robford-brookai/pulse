# ADR-0003: The ledger is Postgres with one command API that rejects illegal transitions at write time

- **Status**: Accepted
- **Date**: 2026-08-03

## Context

PULSE's doctrine is "state is declared into the ledger, not derived in the graph" — but until the
`pulse-ledger-core` change (DNA-784), no ledger existed. The transport layer was done
(ADR-0002: EventBridge distribution), and the three S1 services that follow — verdict-relay,
schedules, identity — were all blocked on a ledger schema and a command API.

The v1 platform docs (2026-07-28) took positions this change had to resolve:

- `design/platform/event-envelope-spec.md` accepted invalid transitions at ingest and flagged
  them in Snowflake ("API-side rejection is deliberately deferred").
- `design/platform/state-catalog.md` kept legality "flag-only at MVP" and set the patient state
  grain at `patient × program`.
- Object model v0.7 (`design/migration/rpc-object-model-assessment.md`) — six subject types with
  their own grains, invariants I1–I10 — is doctrine, and disagrees with both.

Backfill (BF-x) loomed as the schema-shaping constraint: retrofitting bitemporality was the named
"most expensive schema regret," so the schema had to survive backfill with zero migrations
between S1.1 and BF-x.

## Decision

We will record state in an append-only Postgres schema `ledger` (Snowflake Postgres at runtime),
written only by one HTTP command API (`packages/pulse-ledger`), consumed through one client SDK
(`packages/pulse-core`), with transition legality enforced at write time. Concretely:

- **Write-time rejection, not accept-and-flag.** Every declared transition is validated against
  the catalog's generated adjacency for the six v0.7 subject types; an illegal transition is
  rejected with the catalog reason and the `catalog_version` consulted. This supersedes the v1
  envelope/state-catalog ingest posture (both docs carry supersession notes).
- **Bitemporal, evidence-classed, epoch-stamped from day one.** `effective_at` (canonical;
  `occurred_at` accepted as an input alias) and server-set `recorded_at` on every event, plus
  `evidence_class` (E0–E4) and `epoch` (declared vs reconstructed) — so backfill needs no
  migration. Correction is by reversal event (`reverses_event_id`); immutability is enforced in
  the store by REVOKE UPDATE/DELETE on `events` from the service role, not by convention.
- **Current state is co-committed.** `ledger.current_state` is folded in the same transaction as
  the event, alongside a transactional outbox with a per-subject sequence (D17) relayed to the
  EventBridge bus through the shared `EventBridgePublisher` (5 attempts → DLQ). Clock-driven
  jobs enumerate from `current_state`, never from a projection.
- **Idempotency is client-supplied and permanent (D16).** Key
  `{writer_id}:{sha256(subject, command_type, payload, logical_time)}`, unique-constrained for
  the ledger's lifetime; a replay returns the original event id and never a second event.
- **Attribution is authentication (D15).** Per-writer bearer credentials resolve to
  `writer_id` = actor; a body carrying any actor field is rejected outright — spoofing is a
  noticeable failure, not a silent correction. HMAC middleware exists for the Twenty webhook
  route, which ships disabled until S2.
- **The command vocabulary is generated, not hand-written.** Transition tables and Pydantic
  command types (`pulse_core.generated`) generate from the catalog seed, version-pinned; the
  service refuses to boot on a catalog version mismatch (D18). Verdicts are trinary with a
  mandatory reason on `indeterminate`.
- **Backfill is the same path with a restricted vocabulary.** `POST /commands:batch` runs the
  same validation; `backfill_genesis` and `reconstruction_gap` commit only from the backfill
  actor. Non-state-bearing facts (`resolution_hold`, `reconstruction_gap`) may carry no
  `to_state` and commit without a transition check or state re-fold.
- **Identity lookups are a registry, not events.** `external_identifiers` enforces
  `(system, value)` uniqueness as its primary key; `person_match_keys` stores sha256 digests
  only, with a `[0-9a-f]{64}` check constraint keeping the readable (PHI) composite out of the
  ledger by construction.

Delivery was the OpenSpec change `pulse-ledger-core` (DNA-784), 16 tasks across waves 0–4.

## Consequences

Easier: the three S1 services build against pinned names (`design/delivery/pulse-s1-work-orders.md`);
an illegal transition can never enter the record, so `Q_INVALID_TRANSITIONS` verifies rather than
polices; backfill lands in the same schema and write path it will find at BF-x; a wrong write is
correctable only by a reversal that preserves history.

Harder: every writer must speak the command API — there is no "just insert a row" escape hatch,
by design; legitimate late corrections must arrive as backdated legal transitions or reversals;
the catalog seed (Appendix C) is a documented temporary indirection until the `catalog-authority`
change lands the authoritative `state_catalog.yaml`.

**Known gap, tracked (flagged independently by tasks 4.3 and 5.3):** the HTTP boundary is not yet
wired to the replay semantics the commit path implements. `pulse_ledger.api` rejects an
`idempotency_key` body field as unknown (the app's `Committer` calls `commit_declaration`, not
`commit_idempotent`) and `_commit_response` never echoes `replayed` — so
`pulse_core.client.PulseCoreClient`, which always sends the D16 key and classifies replays from
the response body, currently sees every replay as `committed`. The fix is small and server-side:
accept `idempotency_key` in `coerce_declaration_fields`, thread it to `commit_idempotent`, and add
`"replayed": result.replayed` to the response. Until it lands (tracked as DNA-801 — see
`docs/contracts/publishes.md`), the command surface's replay classification
is not trustworthy end-to-end, and `s12-verdict-relay` must not build on it.

Foreclosed: probabilistic identity matching in the ledger (ambiguity always quarantines to a
human); making identifier attachment an event (that would require `person` as a subject type — a
spec-level decision deliberately not taken); and any second write path.

## Alternatives considered

**Events in Snowflake directly** — rejected: the write path's p99 < 500 ms commit SLO and the
transactional co-commit of event + state + outbox rule it out; Snowflake stays the
verification/analytics layer, fed by the outbox relay.

**Accept-and-flag at ingest (the v1 posture)** — rejected: it makes the ledger a stream to be
adjudicated later rather than a record, and the flagging never converges — the referee finds
violations the writer has long since stopped caring about. Bitemporal backdating and reversal
events cover the legitimate-late-fact cases rejection would otherwise strand.

**gRPC instead of REST** — rejected: the Twenty webhook path (D8) and HMAC signing are
HTTP-native, and every internal writer is Python with an SDK that hides the transport anyway.

**Server-derived idempotency keys** — rejected: only the writer knows its logical time; a
server-derived key cannot distinguish a retry from a genuinely repeated fact (D16).
