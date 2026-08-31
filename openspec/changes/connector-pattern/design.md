# Design — connector-pattern

## Context

See proposal.md §Why. Current state that shapes the how: three integrations carry private
copies of the same primitives — `consent_ingress.row_source` (RowSource + per-row
validation), `verdict_relay.mart_reader` (durable cursor via `pulse_core.cursor`,
per-subject watermarks), `verdict_relay.declarer` + `run` (declare pipeline, response
classification, seven-count receipt), `pulse_core.consume` + `twenty-projection` (consume
loop, dedupe, monotonic watermark). The standard-connector draft
(`openspec/specs/connectors/pulse-standard-connector-spec.md`) already names the five-stage
anatomy (tap, classifier, identity, mapper, emitter) and proposes a shared core; this change
builds the shared core from what exists rather than from the draft's clean-sheet shapes, and
the draft is revised to point at the kit where they describe the same thing. The billing
rules live today as dbt SQL in `data-platform/management/models/billing/verdict/` plus its
`tests/billing/` assertions.

## Goals / Non-Goals

**Goals**
- One shared implementation of the four primitive groups, in `pulse-core`, extracted — the
  refactored integrations delete their private copies in the same wave.
- A billing engine whose latency contract is event-arrival-bound, with a rule port that is
  reviewable model-by-model against its dbt source.
- A reconciliation mechanism that can attribute every disagreement.

**Non-Goals**
- No new connector instances (Billy/PAP/ExDash/POCAR/Customer.io outbound are later changes).
- No change to the webhook route's placement — inbound *push* transports terminate in the
  API service as today; the kit serves pollers and consumers.
- No generic rules DSL. The port is plain Python per rule set, versioned; a DSL is a later
  decision if a third rule family ever appears.

## Decisions

1. **Kit lives in `pulse_core.connector` (namespace inside the existing package), not a new
   workspace package.** The primitives already depend on pulse-core's client, cursor, and
   idempotency modules; a separate `connector-core` package would immediately circular-import
   or re-export half of pulse-core. Alternative (new package per the standard-connector
   draft) rejected for that coupling; the draft's name survives as the namespace.
2. **Extraction order: read contract first, then declare pipeline, then consume loop.** Each
   step refactors its donor package in the same PR that extracts, so no primitive ever has
   two maintained copies. Alternative (extract all, refactor later) rejected — that is how
   drift between copies starts.
3. **The engine is a schedules-package-style service, not a Lambda.** It consumes its own SQS
   queue (rule on `patient-state` and consent domains), evaluates, declares via
   `PulseCoreClient`. Same deploy shape as `pulse-ledger-relay` (Duplo service, one image).
   Alternative (in-API evaluation) rejected: the API stays a validator, never a producer.
4. **Rule port shape: one module per verdict type** (`billing/rules/billing_eligibility.py`,
   `coverage_eligibility.py`, `benefits_verification.py`), each a pure function
   `(subject facts) -> Verdict`, each carrying `RULE_VERSION = "pulse-<type>-v1"`, each with
   a docstring naming its dbt source model and the mapping of every dbt test to a unit test.
   Facts arrive as a typed snapshot the engine folds from consumed events per subject —
   the engine keeps its own small state store (Postgres schema `billing_engine`, its own
   credential, not the ledger schema) holding per-subject fact snapshots and evaluation
   watermarks.
5. **Data model (engine store)**: `billing_engine.subject_facts(subject_type, subject_key,
   facts jsonb, updated_at, last_event_id)`, `billing_engine.evaluations(subject_type,
   subject_key, verdict_type, rule_version, outcome, as_of, declared_event_id)` — enough to
   make re-evaluation idempotent and the reconciliation sweep attributable. Rebuildable from
   the bus at any time; never a source of truth.
6. **Reconciliation sweep is a schedules entry** (`verdict-reconcile`), reading the mart
   (Snowflake, existing relay credential) and `billing_engine.evaluations`, comparing per
   (subject, verdict_type) on matching fact windows, writing the diff report to the tracking
   issue — counts and subject keys only. Alternative (dbt-side comparison) rejected: the
   sweep must run under pulse's PHI posture and receipt discipline.
7. **API surface**: no new HTTP routes. New producer credential `billing-engine`; new queue
   `ocean-billing-engine` (+DLQ); receipts extend the seven-count line with
   `evaluated=N` for the engine's runs.
8. **cpt-om registration**: the port's rule modules become the registered owner of
   qualification logic *if* Rob confirms cpt-om's logic is what the dbt models encode;
   otherwise cpt-om keeps its direct-declare row and the engine registers as a separate
   producer. Task 1.1 forces this decision before wave 2 starts (it changes
   `producer-registry.md`, not the specs or the task graph).

## Risks / Trade-offs

- [Rule-port divergence on real data shapes] → the reconciliation window is the mitigation
  by design; additionally every dbt test gets a named unit-test counterpart before the
  engine's first live declare.
- [Two writers during the window fighting over state] → per-subject `as_of` monotonicity and
  pair idempotency already arbitrate; the sweep counts every arbitration so silence is
  impossible.
- [Kit refactor destabilizes shipped integrations] → extraction PRs are behavior-preserving
  by gate: demos 1–4 must stay green per wave, and the refactor deletes code, never forks it.
- [Engine state store becomes a shadow ledger] → schema holds fact snapshots and evaluation
  receipts only, rebuildable from the bus; a scaffold-style test pins that no state-of-record
  read ever targets it.
- [Episodic-mart assumption inverted: some rule needs warehouse-only data] → surfaced by the
  port mapping (task-gated); any such rule stays mart-side and its verdict type keeps the
  relay path until a fact-sourcing decision is made — the gate is per verdict type, not
  all-or-nothing.

## Migration Plan

Wave 1 (kit): extract + refactor donors, demos green. Wave 2 (engine): port rules with
mapping doc, stand up service + queue on dev, engine declares under its own credential —
mart relay untouched. Wave 3 (window): one full billing month parallel, sweep runs on
schedule, diffs triaged as they appear. Wave 4 (cutover, gated): relay poll stops, Snowflake
credential retired, ADR + contracts updated. Rollback per proposal.md §Rollback.

## Open Questions

- Queue rule filter breadth for the engine (all `patient-state` + consent vs a narrower
  event-type list) — tunable after first dev traffic, does not change specs or tasks.
- Whether the sweep also back-checks the mart's historical v1 seed rows or only the window —
  decidable when the window opens.
