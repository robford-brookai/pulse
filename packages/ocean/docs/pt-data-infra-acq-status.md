# Patient Data Infrastructure — Acquisition Status Tracking (Spec)

> **Author:** Rob Ford · **Date:** 2026-07-26 · **Status:** Draft for review
> **Companions:** `DNA-SPEC-COHORT-FUNNEL-REQS.md` (funnel PRD) · `DNA-SPEC-DECLARED-STATE-PRM.md` (pattern companion)
>
> **Purpose:** Single reference for the decisions, target architecture, core contracts, and delivery plan for patient acquisition status tracking — from raw S3 landing through Snowflake and MongoDB Atlas to a declared-state ledger operated by humans and agents.

## 1.0 TL;DR

Brook tracks patient acquisition state by inference: Customer.io attributes, Billy rows, and timestamps across ~11 systems, reconstructed per question. The pattern is named **Enrichment-as-Record** and it is the root cause of stock-without-flow reporting, forensic status queries, and untrainable forecasts. The target pattern is **Declared-State PRM** (patient relationship management): state declared once, at the moment of transition, by a single accountable writer, and consumed everywhere else.

The build is a warehouse-spine hybrid centered on **PULSE** (Patient Unified Ledger of State and Events): a small command API over an append-only Postgres ledger, one transaction per transition (event, projection, outbox), relayed to EventBridge and projected to Snowflake within seconds. Humans work in Twenty (open-source CRM, demoted to client). Agents enter as propose-only actors on an autonomy ladder. Stock, flow, and cohort-tail metrics — the funnel PRD's asks — become one-line queries against transactionally true state. First wedge: billing investigation triage. Priorities by decision: time to first value, then low ops burden, so net-new operated components total four small things.

## 2.0 Problem

- Patient status exists only as side effects. "How many patients are pending billing investigation?" requires a fresh analysis each time, with logic that is neither explicit nor shareable. The Salesforce-equivalent one-liner does not exist.
- The patient journey spans ~11 surfaces — HubSpot, Customer.io, PAP, ExDash, Billy, POCAR (MongoDB Atlas), RDS Postgres and MySQL, S3, Snowflake, Sigma — with no single surface, no single key, and no patient-grain trace from S3 landing to POCAR.
- Downstream consequences, in the funnel PRD's language: stock metrics without flow metrics, ~17 substages that are mostly hold or failure reasons ("false hope"), artificial backlog corrupting conversion math, no cohort tails, and a Phase 2 forecast with nothing trustworthy to train on.

Anti-pattern named: **Enrichment-as-Record**. Kin in the literature: shadow state, implicit domain model, accidental system of record.

## 3.0 Goals and non-goals

| Goals | Non-goals |
| --- | --- |
| Declared state: every funnel transition recorded as an event with provenance | Buying a SaaS CRM (BAA surface, PHI duplication, second source of truth) |
| Stock, flow, and cohort tail each answerable in one query | A FHIR server — mapping only, until EMR interop climbs the rankings |
| One operational surface for humans, one command surface for agents | Revenue funnel (ends at activation, per PRD) and post-activation retention |
| Patient-grain traceability from S3 to POCAR | Autonomous agent commits at launch (ladder level L2+ is earned) |
| Foundation for funnel PRD Phase 1 with zero application changes required on day one | Replacing PAP, Billy, or POCAR |

## 4.0 Decision record

| # | Decision | Rationale | Status |
| --- | --- | --- | --- |
| 1 | Pattern: Enrichment-as-Record → Declared-State PRM | Agents cannot act on state they must guess. Inferred vs declared is the axis | Decided |
| 2 | Topology: warehouse-spine hybrid with a dedicated ledger service | "Fires real, traceable events" requires an app-owned write path. Headless PRM service deferred except its ledger core | Decided |
| 3 | Single-writer rule: PULSE owns all patient-state writes | Everything else issues commands or consumes events. Ends multi-writer drift permanently | Decided |
| 4 | Object framework: Brook Patient Object Model, FHIR-mapped | dbt-owned state catalog and event contracts, versioned in-repo. FHIR crosswalk as a seed table (Patient→Patient, Cohort Assertion→Condition, Consent→Consent, Coverage→Coverage) | Decided (interview) |
| 5 | Operator mix: even split human/agent at ~18 months | Real human workspace required now, agents co-equal writers through one command plane | Decided (interview) |
| 6 | Priority ranking: time to first value > low ops burden > EMR interop > agent autonomy | Governs every build-vs-buy and sequencing call below | Decided (interview) |
| 7 | Human surface: Twenty (OSS, AGPL-3.0, Postgres) self-hosted in VPC | Workspace plus agent approval inbox. Client of the ledger, authority of nothing. Replaceable by design | Decided, revisitable |
| 8 | Agent posture: launch propose-only (L1) | Autonomy is promoted per transition class on measured acceptance, not granted at design time | Decided |
| 9 | POCAR seam: event-driven anti-corruption layer via Atlas Database Triggers → EventBridge | Atlas Data API and App Services hit end-of-life 2025-09-30. Reverse path is commands, never writes — POCAR's Mongo stays private | Decided |
| 10 | Wedge: billing investigation triage | Data already flows through Billy, the originating question is its stock metric, one agent exercises the full loop | Proposed default |

## 5.0 Target architecture

```
PAP / Billy ──── native commands ─────┐
POCAR ─ Atlas trigger ► EvB ► adapter ┤
Twenty ───────── human commands ──────┼──► PULSE ─one txn─► event + state + outbox
Agents (MCP) ─── L1 proposals ────────┘                            │ relay
                                                                   ▼
                                                            EventBridge bus
                              ┌────────────────────┬───────────────┴────┐
                              ▼                    ▼                    ▼
                    Firehose ► S3 ► Snowpipe   Twenty sync         Customer.io
                    ► Snowflake ► Sigma        (workspace,         (attributes,
                                               approval inbox)     consumes only)
```

| Layer | Components | Notes |
| --- | --- | --- |
| Ingestion and contracts | S3 landing conventions, provenance columns (`_source_system`, `_source_object`, `_batch_id`, `_extracted_at`, `_loaded_at`), change data capture (Mongo change streams, Postgres logical replication), dbt source tests with freshness SLAs | Provenance stamped at load makes pipeline tracing mechanical |
| Identity | Master patient index (MPI) crosswalk producing `patient_key` | Deterministic matching first. Every downstream join goes through the crosswalk, never raw source IDs |
| State authority | PULSE: command API, catalog validation, one Postgres transaction (event append, current-state projection, outbox row), relay to EventBridge at-least-once | The only writer of patient state |
| Distribution | EventBridge bus, consumers dedupe on `event_id` | One tap, every consumer sees the same history |
| Canonical model (dbt) | `patient_hub`, event spine mirror, `fct_status_transitions`, `fct_patient_status_daily`, semantic marts | dbt stops deriving state and starts testing and aggregating it |
| Serving ports | Sigma (analytical) · Twenty (operational, human) · MCP command tools (agents) · reverse ETL to Customer.io and HubSpot (activation) | Customer.io consumes status, never defines it — the inversion of today |
| Governance | PHI zoning, masking and row-access policies, minimum-necessary projections, append-only enforced by grants | Audit plane = five event columns, not a new system |

## 6.0 Core contracts

### 6.1 State catalog

`state_catalog.yaml`, versioned in the PULSE repo. Per state: name, class (`stage` | `hold` | `exit`), definition, owning team, entry and exit predicates tagged `rule_domain: business | billing_investigation`, and adjacency including return loops ("call me in 3 months" → marketing re-entry). Encodes the funnel PRD's Meeting 2 decisions directly: tracked-reason exits with automatic re-entry, the rolling-30-day hold as a revisable predicate, state separated from unlock actions. Two enforcers, one artifact: PULSE validates at write time, the same file exports as a dbt seed for downstream verification.

### 6.2 Ledger

```sql
create table prm_event (
  event_id        uuid primary key,      -- time-ordered UUIDv7
  aggregate_key   text not null,         -- patient_key:program_id
  aggregate_seq   int  not null,         -- optimistic concurrency
  event_type      text not null,
  schema_version  smallint not null,
  occurred_at     timestamptz not null,  -- world time (backtest axis)
  recorded_at     timestamptz not null default now(),
  correlation_id  uuid not null,         -- one journey across systems
  causation_id    uuid,                  -- command/event that caused this
  idempotency_key text not null unique,
  actor_type      text not null,         -- human | agent | system
  actor_id        text not null,
  authority       text,                  -- approving human, when required
  evidence        jsonb not null default '[]',
  rule_version    text not null,         -- state_catalog version applied
  payload         jsonb not null,
  unique (aggregate_key, aggregate_seq)
);
-- UPDATE and DELETE revoked at the grant level
```

`prm_current_state` is the one-row-per-`patient_key × program` projection maintained in the same transaction. Traceability triple: `correlation_id` threads one patient journey across PAP, Billy, POCAR, and the CRM, `causation_id` chains events to the commands that produced them, and `traceparent` (W3C trace context, carried in payload metadata) ties any warehouse row back to the originating API call in Datadog.

### 6.3 The money queries

Stock is transactionally true at commit:

```sql
select count(*) from prm_current_state
where state = 'BILLING_INVESTIGATION_PENDING';
```

Flow (dwell and movement per transition) and cohort tail (activations by month offset from entry) are specified in companion §4.1 and derive entirely from `prm_event` and `fct_status_transitions`.

## 7.0 Autonomy ladder

| Level | Behavior | Gate |
| --- | --- | --- |
| L0 | Sense only — computes, writes nothing | Default for new agent workflows |
| L1 | Propose — emits command with evidence, human approves in Twenty | Launch posture for all agents |
| L2 | Auto-commit with revert window and sampled review | Trailing acceptance ≥ threshold over N weeks, zero harm-class errors, per transition class |
| L3 | Autonomous, exception-only review | Same gate, sustained. Any harm-class error demotes automatically |

Every event carries `actor_type`, `actor_id`, `authority`, `evidence`, `rule_version`. Autonomy becomes a measured property per transition class, never a design-time grant. Human-only red lines (permanent L1 ceiling) remain to be enumerated.

## 8.0 Delivery plan

| Stage | Scope |
| --- | --- |
| S0 | `state_catalog.yaml` v1 plus MPI crosswalk (deterministic pass, coverage measured) |
| S1 | PULSE service: three tables, command API, catalog validation |
| S2 | Outbox relay, EventBridge bus, Snowpipe projection, the Sigma stock count live |
| S3 | Billy command integration for the billing-investigation wedge, backfill replay of the existing inference SQL |
| S4 | Twenty as client (workspace, approval inbox), agent MCP tool at L1, signal adapter for POCAR |

Interim reality handled by design: the signal adapter converts observed side effects (CDC on PAP and Billy, the POCAR EventBridge tap, Customer.io signals) into `actor_type = system` commands with the source reference as evidence — real ledger rows from day one, no application change gating the first report. The old inference SQL gets two afterlives: backfill migrator (history replayed with synthesized correlation, giving the March backtest its substrate) and drift detector (inference keeps running and alarms on divergence from declared state). Native emission then replaces the adapter one event type at a time.

Net-new operated components: PULSE (one Fargate service, one RDS Postgres), the relay, the signal adapter worker, one Twenty container. Four small things.

## 9.0 Funnel PRD alignment

PRD Phase 1 ("report current state with flow and latency") stands on S0–S2. The stage-rationalization open item becomes "ratify `state_catalog` v1," resolvable now via the Snowflake inspection query on the ~17 substages. The stage/hold/exit taxonomy answers the stakeholder objection on exit semantics: "effectively exited" and "recorded as exited" produce the same operational reality but different numbers, and the PRD is about the numbers. The Customer.io open question inverts — not "is the enrichment data organized well enough" but "which signals route through the adapter vs require native emission." Full merge map: companion §7.0.

## 10.0 Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Twenty immaturity — schema migrations between versions | Pin versions, upgrade against a staging clone, pause sync during migration windows. Twenty is a replaceable client by design |
| Atlas Triggers ride a residual platform after the 2025 App Services cull | Identical change-stream semantics allow a swap to a self-run Fargate tailer with persisted resume tokens, nothing downstream changes |
| Ownership drift — Twenty or Customer.io re-becoming shadow authority | Single-writer rule, field-level ownership in sync jobs, drift detector alarms on divergence |
| Audit gaps in minimal OSS CRM under HIPAA | pgaudit on the backing database, app-level access logs, minimum-necessary field projection in the sync |
| Adapter mis-infers a transition | Evidence-carrying system events are correctable, drift detector catches divergence, native emission retires inference per event type |
| Stage model contested by stakeholders | Data-driven ratification session — classify each substage by observed movement rates, decisions recorded in the catalog |

## 11.0 Open questions

1. Cohort authority: is condition-cohort membership (CHF, COPD, hypertension) derived and recomputable, or clinician-asserted with effective dating? Blocks Brook Patient Object Model v1.
2. Human-only red lines: the permanent L1 ceiling list, named transition by transition.
3. Wedge confirmation and its sense-to-act latency tolerance.
4. Territory: can services and collections stand up adjacent to POCAR in Atlas, or read-only taps only?
5. `state_catalog` v1 ratification session — owner, date, and the inspection-query output as pre-read.
6. Operational-numbers sign-off owner, distinct from spec sign-off (mirrors the PRD's open item).

## 12.0 Success metrics

- The stock query returns transactionally true counts sub-second and matches Sigma within seconds of any transition.
- Dwell (p50/p90) reportable for 100% of catalog transitions from S2 onward.
- Inferred-vs-declared drift below agreed threshold, alarmed, trending to zero as native emission grows.
- Share of transitions native-emitted vs adapter-inferred, rising per quarter.
- L1 proposal acceptance rate tracked from week one — the promotion evidence for the ladder.
- The cohort-tail query answers the Sturdy question: of ~1,000 dropped into Qualified, how many reach each stage, and when.
