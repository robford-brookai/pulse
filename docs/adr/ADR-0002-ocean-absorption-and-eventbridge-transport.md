# ADR-0002: Absorb OCEAN into PULSE, replacing its Kafka backbone with EventBridge

- **Status**: Accepted
- **Date**: 2026-08-02

## Context

OCEAN is the event distribution system that carried PRM events: producers publish enveloped
events onto a bus, consumers fan out from it, and a warehouse path lands the raw stream in
Snowflake. It lived in `robford-brookai/ocean` — a personal GitHub account, which is the wrong
compliance placement for a HIPAA-scoped system.

Three findings from the 2026-08-01 reconciliation of the adaptation plan
(`design/migration/ocean-to-pulse-adaptation-plan.md`, accepted 2026-08-01) set up the decision:

- **OCEAN has exactly one application, and it is PULSE.** The original framing — OCEAN as
  platform doctrine that PULSE amends — has no platform left under it. PULSE's declarative-state
  model supersedes OCEAN's derive-in-the-graph doctrine outright.
- **The backbone was not what the plan assumed.** The plan named EventBridge as the bus in
  thirteen places; the repo ran Kafka — Redpanda locally, MSK Serverless on AWS. That
  contradiction (reconciliation item V3) blocked sign-off: "keep — the backbone was never the
  problem" described a bus OCEAN did not run.
- **The source tree could not be imported wholesale.** Only 397 of its 1,169 tracked files were
  code; the rest was agent state and side-cloned repositories, including a 305-file `streamline`
  clone — exactly what `docs/contracts/` forbids carrying across a repo boundary.

Keeping Kafka meant either running MSK Serverless at roughly $547/month before the first event
(EventBridge bills $1.00 per million events; break-even sits near 580M events/month, orders of
magnitude above PRM volume) or building per-target DLQ, backoff retry, and archive replay — all
capabilities the plan already assumed and all EventBridge-native.

## Decision

We will absorb OCEAN into this repository as the workspace package `packages/ocean`, and as part
of the same change retire Kafka and move every bus-touching OCEAN service to EventBridge → SQS.

These are one decision, not two: the absorption was blocked on the V3 contradiction, and
absorbing without migrating would have imported a bus the plan had already rejected. Concretely:

- Import via `git-filter-repo` with an explicit path **allowlist** (never an exclusion list),
  preserving the source repository's commit history at the `packages/ocean/` prefix. History
  preservation is the audit posture: each design decision keeps its commit trail inside the
  organization boundary.
- Every credential in the source repo's tracked `.env` is rotated before import; no secret file
  crosses.
- All thirteen publish sites emit through one shared `EventBridgePublisher`
  (`packages/ocean/libs/ocean-broker`), addressing from a single generated topic →
  `(source, detail-type)` catalog that also generates the Terraform rule patterns. Publish
  failure falls back to the Postgres `failed_webhooks` table at every site, including the six
  that had no fallback under Kafka.
- Each of the seven consumers gets one EventBridge rule and one SQS queue with a DLQ and redrive
  policy, and an explicit ordering verdict before conversion — Kafka's per-partition ordering
  does not survive SQS standard queues, so no consumer is converted on an assumption of
  order-tolerance.
- Local dev replaces Redpanda with LocalStack; the warehouse path replaces Redpanda Connect with
  an ordinary rule-and-queue consumer writing `STREAMLINE.OCEAN_RAW.EVENTS`.
- MSK Serverless is torn down and `robford-brookai/ocean` is archived read-only, once the
  Kafka/EventBridge equivalence harness reports the two transports reach identical end states
  (it did: recorded EQUIVALENT, 2026-08-02).

Delivery is the OpenSpec change `ocean-eventbridge-migration` (DNA-733).

## Consequences

Easier: one repo, one toolchain — `task check` now runs every ocean service suite, so CI covers
the absorbed services; the compliance placement problem is resolved by import rather than an org
transfer; DLQ-per-consumer, retry, and archive replay come from the platform instead of being
built; the bus contract is a generated artifact, so a rule cannot match a `detail-type` no
producer emits.

Harder: the change rewrote working non-PULSE services, which the adaptation plan had not
budgeted; the cross-service test tree (`packages/ocean/tests/`) remains outside CI with roughly
60 pre-existing failures; consumers that needed ordering now carry sequence guards that Kafka
gave for free.

Foreclosed: after the MSK teardown there is no transport rollback, only forward recovery via
EventBridge archive replay. The source repository is frozen — improvements land only in
`packages/ocean`. And the bus is a proprietary AWS service: leaving EventBridge later means
another migration of this shape.

## Alternatives considered

**Keep OCEAN as a separate repo consuming published contracts** — rejected: with a single
application there is no second consumer to justify the boundary, the personal-account placement
had to end regardless, and the source tree itself violated the cross-repo rules (side-cloned
repos) that a contract boundary exists to enforce.

**Keep Kafka / run both buses during a window** — rejected: MSK's fixed cost is unjustifiable at
PRM volume, the assumed capabilities (per-target DLQ, backoff retry, archive replay) would all
have to be built, and a dual-bus window doubles the surface where ordering and duplicate bugs
hide. There is one cutover per consumer instead.

**Import without history (squash)** — rejected: rewinding a HIPAA-scoped system's design trail to
a single import commit discards the audit posture the absorption exists to establish.

**Import by exclusion list** — rejected: an exclusion list admits by default anything added to
the source tree after it was written. The allowlist names what may enter; everything else stays
out.
