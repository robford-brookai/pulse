## Why

Every integration pulse has shipped (consent-ingress, verdict-relay, the Twenty webhook and
projection) re-implements the same primitives — row sources, durable cursors, declare
pipelines, consume loops — and the next five systems (Billy, PAP, ExDash, POCAR, Customer.io
outbound) would each re-implement them again. Meanwhile billing state advances only when
data-platform's dbt project happens to run: the mart is episodic, so "is this episode
billable, is this coverage active" is discontinuous by construction, and no relay poll cadence
can manufacture a verdict the mart has not computed. Decisions taken in interview 2026-08-30
(`.planning/reports/2026-08-30-connector-pattern-boundaries.md`), building on the standard
connector specification draft (`openspec/specs/connectors/pulse-standard-connector-spec.md`).

## What Changes

- **Connector kit**: extract the proven integration primitives into `pulse-core` — row source
  + durable cursor + per-row validation (inbound), the declare pipeline with idempotency and
  receipt counts, the consume loop with event-id dedupe and watermark (outbound), and the
  one-writer-credential-per-connector posture. The three existing integrations refactor onto
  the kit as proof, with the green demo suite (demos 1–4) as the regression net.
- **Billing engine**: a new `packages/billing` evaluates eligibility and coverage rules
  event-driven — its own bus subscription fires evaluation when relevant ledger facts arrive
  (episode opened, coverage changed, consent changed) and declares verdict + paired transition
  immediately under its own writer credential and `rule_version` lineage. The rule logic ports
  from data-platform's dbt models (`management/models/billing/verdict/`). The engine is a
  producer, not a connector: the standard-connector invariant that connectors compute no
  verdicts stands.
- **Verdict reconciliation**: engine and mart run in parallel for one full billing month; a
  sweep compares verdicts per subject and produces a diff report that must be empty or
  explained before cutover.
- **Mart demotion** (gated on reconciliation): the relay's Snowflake mart read retires; the
  mart remains an analytics/reconciliation surface only. **BREAKING** for the verdict write
  path — the second supersession on it (the relay superseded the Snowpark emitter); an ADR
  records it.
- The amount-free billing boundary (`docs/contracts/billing-boundary.md`) applies at the
  `packages/billing` seam: qualification verdicts cross, monetary values never do.

Out of scope, deliberately: Customer.io outbound, Billy/PAP/ExDash connectors, POCAR — each
is a later change that consumes the kit this change ships. The cpt-om producer-registry row
(registered future direct-declarer of `billing_eligibility`) must be reconciled with the
ported rules — one owner for qualification logic; resolving that registration is a task in
this change, and the decision itself is Rob's.

## Capabilities

### New Capabilities
- `connector-kit`: the shared primitives every connector stands on — inbound row-source /
  cursor / validation contract, declare pipeline with idempotency and counted receipts,
  outbound consume loop with dedupe and watermark, per-connector credential posture.
- `billing-engine`: event-driven billing and coverage rule evaluation inside pulse —
  triggers, rule_version lineage, verdict + paired transition output, continuity contract
  (evaluation fires on facts, never on a batch schedule).
- `verdict-reconciliation`: the parallel-run comparison between engine verdicts and mart
  verdicts — window, per-subject diff, empty-or-explained gate, receipt.

### Modified Capabilities
- `verdict-mart-read`: gains its retirement contract — after the reconciliation gate passes,
  the mart read is decommissioned and the mart is no longer a write-path dependency.

## Impact

- **Code**: `packages/pulse-core` (kit), new `packages/billing`; refactors in
  `packages/consent-ingress`, `packages/verdict-relay`, `packages/twenty-projection`;
  eventual removal of the relay's Snowflake read path.
- **Contracts**: `docs/contracts/consumes.md` (verdict mart row demotes), `publishes.md`
  (billing engine as a new producer on `patient-state`), `producer-registry.md` (cpt-om row
  reconciled), `billing-boundary.md` (seam moves with the logic); new ADR for the write-path
  supersession.
- **Cross-repo**: data-platform keeps its models for analytics and serves as the
  reconciliation reference during the window; coordination recorded in the fonzie dependency
  spec (gap 1's publisher-contract ask softens once the mart is analytics-only).
- **Runtime**: one new bus consumer (rule + queue + DLQ for the engine), one new writer
  credential.

## Rollback

Wave-scoped and cheap until cutover: the kit refactor is behavior-preserving (demos 1–4 are
the gate); the engine runs in parallel with the mart path during the entire reconciliation
window, so rollback before cutover is "stop the engine consumer" with the relay still
declaring exactly as today. After cutover, rollback is re-enabling the relay's poll target
(config, not code — the read path is removed only after a full month of green parallel
receipts).
