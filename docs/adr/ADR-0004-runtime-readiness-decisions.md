# ADR-0004: Runtime Readiness Decisions (D14–D18)

- **Status**: Accepted
- **Date**: 2026-08-06

One ADR for five decisions, deliberately: these are the runtime-readiness register rows
(`design/delivery/pulse-runtime-readiness.md` §5) that close together at one exec session, and
two of them ratify behavior that already shipped. Splitting them would manufacture four
cross-references for one sitting's worth of decisions. If any single decision is amended later,
the supersession flips that decision's subsection, not the document.

## Context

The spec-first process deferred runtime questions while the ledger core was built. Phase 2 has
now shipped its three spec-determined changes (`s12-verdict-relay`, `s13-schedules`,
`s14-identity` — archived 2026-08-05/06), and the four remaining Phase 2 changes are gate-held
on exactly these decisions: `twenty-kanban-webhook-ingress` needs D15, `catalog-authority`
needs D18 (and `producer-ingress-policy` needs `catalog-authority`), and deployment/ops work
needs D14 and D17. Meanwhile two rows — D16 and D17 — describe mechanisms that
`pulse-ledger-core` and its siblings already implemented and test in CI, so the register is
lagging the code. The session's job is two genuine choices (D14, D15), one already-recorded
governance decision to ratify (D18), and two rubber-stamps of running behavior (D16, D17).

## Decisions

### D14 — Deployment target

**We will deploy PULSE services on Snowpark Container Services (SPCS), subject to one
timeboxed spike.** Default-deny egress, data-adjacent compute, and one fewer network boundary
between the command API and Snowflake Postgres. The named precondition: a one-day spike proving
SPCS service networking can terminate the Twenty webhook path with acceptable latency. Spike
fails → EKS on DuploCloud, without reopening this ADR (the fallback is part of the decision).
Deciders: Tal + Ford.

### D15 — Command API authentication

**We will authenticate the Twenty webhook path with shared-secret HMAC request signing
(quarterly rotation, secret in the platform secret store, never in workflow config), and every
internal writer with its own per-service credential.** Attribution is authentication: a writer
can declare events only as itself, and a body-supplied `actor` is rejected as a spoof — this is
already how `pulse_ledger.auth` behaves (S1.1 task 3.4) and how all three shipped writers
authenticate (`verdict-relay`, `reconciliation`, identity service — credential names in config,
values from the environment). mTLS is the named upgrade path once everything co-locates in
SPCS. What actually remains open for the session: sign-off from a **named compliance owner**
(the §3.1 role-fill) on the webhook posture and the Customer.io carrier-STOP interaction (D9).
Deciders: Tal + compliance owner.

### D16 — Command idempotency (ratifies shipped behavior)

**We will keep client-supplied idempotency keys, unique-constrained in the ledger:**
`{writer_id}:{sha256(subject, command_type, payload, logical_time)}`; a replay returns the
original commit result and never a second event. Shipped and tested end to end:
`pulse_core.idempotency.derive_idempotency_key`, `pulse_ledger.idempotency.commit_idempotent`,
and the HTTP wiring (DNA-801, PR #104, accepted-if-present at the boundary with mandatory-key
tightening tracked on DNA-801). Execution added one refinement worth ratifying with it: writers
that resolve on a triggering event derive **two** keys — the wire key (`submit_command`'s own
`datetime`-based derivation, which protects the ledger) and an audit key (`event_id` logical
time, attached to evidence) — recorded in `s14-identity` design decision 5. Key retention:
ledger lifetime. Decider: Ford; Tal sign-off.

### D17 — Outbox relay semantics (ratifies shipped behavior)

**We will keep at-least-once delivery with per-subject ordering, exponential backoff, five
attempts, then DLQ with a depth-≥1 alarm; redrive is an operator runbook action, never
automatic.** Shipped as `pulse_ledger.relay` (S1.1 task 4.4, PR #83): per-subject order from
the outbox sequence, consumers deduplicate on event id, lag gauge in place. Lag budget
p99 < 30 s outbox-to-backbone, driven by the heal-back UX promise. Decider: Ford; Tal sign-off.

### D18 — Catalog system of record

**We will home released catalog versions in Snowflake; edits stay in git; approval is the git
PR flow; merge to main triggers the release job that writes the immutable `catalog_version`
rows.** No hand edits in Snowflake, ever. Breaking releases (state removed, ValueSet narrowed,
transition legality changed) require a migration note and consumer checklist in the release PR;
CI enforces the four-surface drift check per the object model §7. This was recorded in
runtime-readiness §4 — the session ratifies it into the register, which unblocks
`catalog-authority` and, through it, `producer-ingress-policy`. Owner: Ford; Tal sign-off.

## Consequences

- The last four Phase 2 changes become proposable the day this is accepted — D15 unblocks
  `twenty-kanban-webhook-ingress`, D18 unblocks `catalog-authority` →
  `producer-ingress-policy`, and `customerio-consent-ingress` waits only on the export
  mechanism confirmation that rides with the compliance-owner role-fill.
- D14 commits infra work to the SPCS path (`pulse-spcs-deployment`) after one spike; an EKS
  reversal after real SPCS investment would cost the deployment scaffold, which is why the
  spike gates the close.
- D15 makes credential provisioning a real operational surface: per-service secrets, quarterly
  webhook rotation, and a compliance owner who must exist by name — the decision creates
  ongoing work, not just a setting.
- D16/D17 ratification forecloses server-derived keys and exactly-once delivery ambitions;
  consumers must stay idempotent upserts forever. That constraint is already load-bearing in
  every shipped consumer, so the cost is zero today and grows only if someone later wants a
  non-idempotent consumer — which this ADR says no to.
- D18 puts catalog reads under the same BAA/access-control/audit surface as the data, at the
  price of a release job and a breaking-change ceremony that every catalog edit now pays.

## Alternatives considered

- **D14 — EKS on DuploCloud first**: known quantity, existing tooling; rejected as the default
  because it adds a network boundary between the command API and Snowflake Postgres and forfeits
  default-deny egress. Survives as the named fallback if the spike fails.
- **D15 — single shared API token**: simplest to provision; rejected because it destroys actor
  attribution (single-writer violation) and makes rotation a big-bang event. **mTLS now**:
  strongest posture; rejected as premature until SPCS co-location makes it nearly free.
- **D16 — server-derived keys**: no client work; rejected because the server cannot distinguish
  a retry from a genuinely repeated fact — only the writer knows its logical time (ADR-0003
  records the same reasoning; this row exists to close the register, not reopen the design).
- **D17 — exactly-once delivery**: not honestly available on EventBridge; pretending otherwise
  moves the dedup problem into the broker where it can't be audited. **Automatic DLQ redrive**:
  rejected as an outage loop on poison events.
- **D18 — git as sole system of record**: simplest; rejected because consumers (dbt tests,
  Twenty codegen, verdict criteria) read from the warehouse, and a catalog outside Snowflake
  sits outside the BAA/audit surface that governs the data it describes. **Snowflake-native
  editing**: rejected because hand edits bypass PR review and the generative contract.

---

**The log is append-only.** A decision that no longer holds gets a new ADR and a status flip on
the old one — never an edit. The point is the history, not the current state; the current state
is the code.
