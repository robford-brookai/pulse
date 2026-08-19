# Design: billing-state

## Context

Inputs this design is built from:

- **The billing model is already half-paid-for.** `billing_episode` is a catalog subject with
  the full lifecycle (`open → qualified|not_qualified → reported → closed`,
  qualified ⇄ not_qualified re-runnable until `reported`); `month_open` opens one episode per
  active enrollment × month with stable D16 keys; the exclusivity-group rule (at most one
  `qualified` episode per patient × group × month) is designed into the qualification verdict.
- **The declare-back machinery exists but is unfinished in two specific places.** verdict-relay
  ships the mart contract, cursor/watermark, and four-way response handling — but (1) a
  committed `declare_verdict` moves no state: the fold only folds `to_state`-bearing events and
  `pulse_ledger` has no verdict handling, so I3's "derived-then-declared" chain never reaches
  `current_state`; and (2) production wiring is explicitly deferred ("arrives with the
  scheduler trigger (S1.3)") — nothing constructs the Snowflake `RowSource` or runs the relay.
- **Coverage is designed but homeless.** The object model specifies Coverage (patient × payer,
  QMB status, facts) and the verdict chain Qualification → Eligibility → BenefitsVerification →
  MarketingClearance; Billy runs BenefitsVerification manually today, distinguished by
  `rule_version` from a future 270/271 automation. The catalog carries none of it.
- **Broadcast already works.** The outbox relay publishes every ledger event on the
  `patient-state` bus domain (D17 semantics); a new `event_type` inside an existing domain
  needs zero rule or Terraform changes per the event-transport spec.
- **Boundary principle (Rob, 2026-08-19).** The line between pulse and the rest of Brook's apps
  is crossed by connectors only, precisely to prevent point-to-point integrations between apps.
  This is the existing architecture stated as policy: **in** through the command API under the
  connector's own credential; **out** through the bus via the consumer's own rule + SQS queue.
  No app reads another app's store; no app writes pulse's Postgres; apps that need each other's
  facts get them from the ledger's event stream.

## Decisions

### 1. The boundary is the design — apps connect to pulse, never to each other

Every element of this change is placed by the boundary rule:

- The mart's billing verdicts enter through the command API (the relay is the connector,
  credentialed as its own actor).
- Consumers learn billing state from `patient-state` bus events, never by querying the mart or
  the ledger's Postgres.
- **pricing-engine** (Brook app, connector-attached) fits in one of exactly two sanctioned ways,
  flagged as open question 3: feed the Snowflake mart that the relay reads, or declare directly
  through the command API under its own credential (the `customerio-consent-ingress` precedent).
  Both keep pricing-engine ignorant of every other app.

*Alternative rejected — Twenty-native billing object as the store, indirectly writing to the
ledger.* This inverts the projection direction the in-flight `twenty-projection` change exists
to fix ("a UI whose state the ledger corrects only by accident"), creates a second write path
(ADR-0003: no "just insert a row" escape hatch; producer policy: catalog-subject state enters
only via the command API), and is a point-to-point integration between Twenty and billing by
another name. Twenty gets billing state the same way it gets everything: a read-only projected
field, as a follow-up to `twenty-projection`.

### 2. Coverage modeling: option A (new `coverage` subject) recommended; B carried for review

**Option A — `coverage` as the seventh ledger-owned subject.** Patient × payer grain. Coarse
state machine:

```yaml
coverage:
  ownership: ledger
  transitions:
    unverified: [verified_active, verified_inactive]
    verified_active: [verified_inactive, lapsed, terminated]
    verified_inactive: [verified_active, lapsed, terminated]
    lapsed: [verified_active, verified_inactive, terminated]
    terminated: []
```

QMB status, benefit categories, copay detail live in verdict payload and `lineage_ref`, never in
the state vocabulary — states stay coarse and stable; detail stays in evidence. Cost: MINOR
catalog bump 1.0.0 → 1.1.0 (additive per catalog-versioning) plus one Alembic migration widening
the three subject-type CHECK constraints (`ck_events_subject_type`,
`ck_current_state_subject_type`, `ck_review_queue_subject_type`) — a proven, bounded gap:
`test_communication_consent_validates_but_cannot_yet_be_committed` documents exactly this seam.

**Option B — verdicts only, no new subject.** Eligibility/BenefitsVerification verdicts attach
to `enrollment`. Zero catalog/migration cost. But: no `current_state` row, so
`enumerate_state` cannot answer "who has lapsed coverage" (the clock-driven-jobs pattern
requires enumerating from `current_state`, never a projection); no transition events, so every
consumer must fold verdict history itself — the derived-state anti-pattern this program exists
to retire; and verdict grain is per-run, so "continuous state" becomes an inference rather than
a recorded fact.

**Recommendation: A.** The change's stated deliverable — continuous state, enumerable,
broadcast — is definitionally a `current_state` row plus a transition event stream. B does not
avoid A's cost; it distributes it onto every consumer. The verdicts still exist under A
(invariant I3): the subject's transitions cite them via `reason`/`lineage_ref`.

### 3. The verdict→state fold lives in the relay, as an outcome→transition pairing

Today a committed `declare_verdict` is evidence with no consequence. Two placements considered:

- **(i) Relay-side pairing — chosen.** Per-verdict-type configuration gains
  `transition_by_outcome` (e.g. `billing_eligibility: {positive: qualified, negative:
  not_qualified}`). On a committed or replayed verdict, the declarer submits a
  `declare_transition` on the same subject with a D16 key derived from the verdict row — so the
  pair is replay-safe as a unit: a rerun replays both halves; a run that died between the two
  completes the pair on resume. A rejected transition is counted distinctly and never retried —
  once an episode is `reported`, `qualified ⇄ not_qualified` is legally closed and rejection is
  the correct answer, not an error. Ordering is per-subject `as_of`-monotonic already.
- **(ii) Command-API-side fold — rejected.** Teaching the catalog an outcome→state mapping per
  subject and folding on `declare_verdict` commits gives one command instead of two, but
  changes command semantics, the generator, and the fold for every subject — a MAJOR-flavored
  change out of proportion to this need. Recorded as a possible future consolidation once more
  verdict-driven subjects exist.

Partial-failure posture: verdict committed + transition transiently failing fails the run naming
the row; the resumed run replays the verdict (idempotent hit) and completes the transition.
Two events per verdict is the honest shape — evidence and consequence are distinct facts.

### 4. Both halves ride the one existing relay, configuration-extended

Program billing eligibility and coverage are the same machine: new `verdict_type` values on the
**unchanged** pinned eight-column mart contract, new `subject_type_by_verdict` entries
(`billing_eligibility → billing_episode`, `coverage_eligibility → coverage`,
`benefits_verification → coverage`), new `transition_by_outcome` entries. No second relay, no
contract change, no new package. `rule_domain: business | billing_investigation` never blends in
the mart queries feeding the relay (state-catalog rule) — asserted in the mart-side open
question, not enforceable from this repo.

### 5. Broadcast: stay on `patient-state`

Coverage and billing-episode transitions are patient state by any reading. The relay already
publishes all ledger events there; consumers filter on the envelope's `event_type`
(zero-infra per event-transport). A twelfth bus domain would cost the ocean-broker catalog
edit + tfvars regen + Terraform + relay routing change and buy nothing — and per decision 1,
consumers integrate by attaching their own rule + queue regardless.

### 6. Cadence: eager poll on `computed_at`, not a cross-repo trigger

D16 idempotency + the durable cursor + per-subject stale-skip make an extra relay run a
guaranteed no-op (all replays/skips, clean receipt). "After every dbt refresh" is therefore
approximable by a frequent scheduled poll — the schedules-package precedent (`month_open`,
`consent_sweep`) — with the interval an open question (SLO, question 7). A run that finds the
cursor at the watermark declares nothing and exits cleanly.

*Alternatives deferred, both boundary-violating today:* a Snowflake TASK/stream on the mart, or
the dbt repo's CI invoking `task relay:run` — each creates a cross-repo seam with no contract
owner (consumes.md: the dbt side "has no publisher contract of its own yet"). The poll needs
nothing from the dbt side and is strictly forward-compatible with a push trigger later, behind a
`publishes.md`/`consumes.md` pin when that seam gets an owner.

## Risks / Trade-offs

- **Two events per verdict** — more ledger volume and a window where evidence exists without
  consequence. Mitigated by pair-completing resume semantics; accepted as the honest model.
- **Coverage first-declare** — the first verdict for a patient × payer must mint the subject
  (initial state `unverified` is derived: no incoming edge). The minting rule and subject-key
  convention are pinned in the coverage-state delta; identifiers are sha256-digest posture,
  payer identifiers never in logs.
- **Mart must address ledger subject ids** — `billing_episode` ids reach Snowflake via
  `warehouse-event-sync`; coverage rows need the same discipline from day one (open question 6).
- **Exclusivity mid-month flip** — `qualified → not_qualified` may or may not re-open the
  group slot (open question 8); the pairing mechanism is indifferent, the mart's qualification
  logic is not.
- **Poll lag vs freshness** — worst-case declare-back lag is one poll interval on top of mart
  freshness; if the SLO tightens, the poll shortens (no-op runs are cheap) before any push
  trigger is considered.

## Migration Plan

1. Catalog 1.1.0 (coverage subject) → regenerate → freeze release + MANIFEST (wave 0, serial
   `catalog_generated_surfaces`, sequenced behind twenty-projection).
2. Alembic CHECK-widening migration; the named cannot-commit test pattern flips to green for
   `coverage` (wave 0).
3. Relay pairing + config + fixtures, offline under `--disable-socket` (wave 1).
4. Production wiring + poll trigger + `task relay:run` (wave 2, serial `workspace_roots`).
5. Contracts + runbook + nav (wave 2, serial `openspec_main_specs`).
6. Live declare-back on dev: run twice — first run declares, second run all-replays — verify
   episode + coverage transitions land in `current_state` and on the bus (wave 3, operator
   lane, G_APPROVAL).

Rollback at any point: stop the poll (schedules entry) — the ledger keeps what was declared;
correction is by reversal events, never deletion.
