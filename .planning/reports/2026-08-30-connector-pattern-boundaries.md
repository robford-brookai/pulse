# Connector Pattern — Code Boundaries (Interview Record)

**TL;DR:** Every external system integrates with Pulse through a connector package hosted in
pulse, built on shared primitives extracted into `pulse-core` from the three integrations that
already work. The seam facing the source system is "whatever that system already emits" — the
connector adapts. The seam facing pulse is the command API for writes and a bus subscription
for reads, one writer credential per connector. Billing is the forcing case and goes first:
rule evaluation moves *into* pulse as an event-driven package because the dbt mart runs
episodically and billing state must be continuous — the mart demotes to
analytics/reconciliation, and the relay's Snowflake read retires only after a full
reconciliation window. Decisions taken in interview with Rob, 2026-08-30.

## 1.0 The three seams

```
source system  <── seam A ──>  connector (in pulse)  <── seam B ──>  pulse core
                                       │
                                  shared kit (seam C)
```

### 1.1 Seam A — source-system <> connector

**Decision: the connector adapts to what the system already emits. No source system is
required to change.** The sanctioned inbound transports, matched to what exists:

| Transport | Precedent | Fits |
|---|---|---|
| Signed webhook push | Twenty kanban ingress | systems that can call out |
| Vendor export landed in the warehouse | Customer.io consent (ADR-0005) | vendors with export products |
| Computed table poll with durable cursor | verdict relay | batch producers |
| API poll | (new) | systems exposing only a query surface — POCAR, ExDash |

Outbound (pulse → system): **EventBridge rule + SQS queue per connector, write-back through
the system's own API** — the twenty-projection pattern: event-id dedupe, delete-after-success,
monotonic per-record watermark, and the connector holds the system credential plus the queue
URL and nothing else (no ledger DSN, no writer token on the outbound half).

### 1.2 Seam B — connector <> pulse

- **Writes:** the command API only, over HTTP, under the connector's own writer credential
  (D15). Actor comes from the credential, never the payload. Idempotency keys derive
  client-side (D16), so every declare is replay-safe.
- **Reads:** bus subscription (committed events), never direct queries against the ledger
  Postgres. A connector that needs current state consumes events and folds its own watermark,
  or waits for pulse's read routes if/when they ship.
- **Receipts:** every run ends in a counted receipt (the seven-count relay receipt is the
  template) — the operator-visible contract.

### 1.3 Seam C — the shared kit

**Decision: extract the proven core into `pulse-core`, refactoring the existing three
integrations onto it as proof the abstraction is real.** Contents, all extracted, none
invented:

- `RowSource` + durable cursor + per-row validation (from consent-ingress / verdict-relay)
- the declare pipeline: idempotency, response classification (committed | replayed |
  rejected | transient), retry-transient-only, receipt counts (from verdict-relay)
- the consume loop: event-id dedupe, delete-after-success, watermark (from twenty-projection
  / `pulse_core.consume`)
- credential posture: one writer id per connector, names in config, values from the
  environment, never in logs

Explicitly rejected: a base-class framework (couples every connector to framework changes)
and conventions-only (drift with no shared code to check against).

## 2.0 Billing — the forcing case

**Decision: `packages/billing` owns event-driven rule evaluation inside pulse.** The reason
is cadence, and it is structural: the dbt mart runs episodically, and no connector polling
frequency can manufacture a verdict the mart has not computed yet. Continuous billing state
requires the evaluation itself to fire when facts arrive.

- Triggers: relevant ledger events (episode opened, coverage changed, consent changed) via
  the package's own bus subscription.
- Output: verdict + paired transition through the command API, same as today's relay pairing,
  under the billing package's own writer credential and `rule_version` lineage.
- **Rules port from data-platform's dbt SQL into pulse code** (`management/models/billing/
  verdict/`). data-platform keeps analytics. The cpt-om producer-registry row (registered as
  a future direct-declarer of `billing_eligibility`) must be reconciled with this decision —
  either cpt-om's logic *is* what gets ported, or its registration changes. Flagged, not
  decided.
- The amount-free boundary (`docs/contracts/billing-boundary.md`) moves with the logic:
  qualification verdicts cross the package seam, dollar amounts never do.

**Cutover gate — decision: a reconciliation window.** Engine and mart run in parallel for an
agreed window (one full billing month proposed), a sweep compares verdicts per subject, and
the diff report must be empty-or-explained before the relay's Snowflake read retires. Same
receipt discipline as the cutover ladder. The mart then stands as analytics and as the
reconciliation reference, not as a write-path dependency.

## 3.0 Customer.io — the bidirectional case

**Decision: one package, both directions, export inbound stands.** `connector-customerio`
absorbs the existing export-driven consent ingress (ADR-0005's no-live-API-pull posture is
unchanged) and adds the outbound half — patient segments and attributes synced from ledger
events so messaging targets current truth. One home, two seams, two credentials (Snowflake
read for the export, Customer.io API for write-back).

## 4.0 Rollout

| Order | System | Why |
|---|---|---|
| 1 | **Billing** (`packages/billing`) | the continuity problem is the forcing function; kit extraction happens here, with consent-ingress / verdict-relay / twenty-projection refactored onto the kit as the proof and the green demo suite as the regression net |
| 2 | **Billy / PAP / ExDash** | the named legacy push-pull systems — each needs a surface inventory first (what it emits, what it must receive) |
| later | **Customer.io outbound** | rides the kit's consume loop once extracted (the planned customerio-projection becomes this connector's outbound half) |
| later | **POCAR** | aligned with the roadmap's pocar-relay and the P3 cutover watch |

## 5.0 Open items this record does not decide

1. **cpt-om vs ported rules** (§2.0) — one owner for qualification logic must be named.
2. **Billy / PAP / ExDash surface inventories** — transports per §1.1 are unknown until each
   system's emit/receive surfaces are catalogued.
3. **Package naming** — `packages/billing` vs `packages/connector-<system>` for pure
   connectors; proposal-time detail.
4. **An ADR is owed**: in-pulse event-driven evaluation supersedes the mart-read relay as the
   verdict write path, the second supersession on this path (relay superseded the Snowpark
   emitter, `design/platform/clinic-rules-engine.md`).

**Next step:** turn this record into an OpenSpec change proposal (`connector-kit` +
`billing-engine`, or one change with two waves) — say the word and it goes through
`opsx:propose` with these decisions as the input.
