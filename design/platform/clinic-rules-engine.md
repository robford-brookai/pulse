# Clinic Rules Engine — `patient.qualified` / `patient.disqualified` (PULSE)

> **Superseded (2026-08-05, `s12-verdict-relay`, roadmap P5).** The Emitter (§3 below) — a
> Snowpark Python stored proc POSTing transition events straight to Twenty — is superseded as the
> verdict write path. `packages/verdict-relay` reads the qualification mart this document's
> Evaluation step (§2) produces and declares each row to the ledger as a `declare_verdict` command
> on the platform's single write path, per D16 idempotency
> (`openspec/changes/s12-verdict-relay/proposal.md`). The qualification mart is now a consumed
> contract, documented in `docs/contracts/consumes.md`. Not breaking — the emitter was never
> built. Rules landing (§1) and evaluation (§2) are unaffected; only the emission leg changes.

| | |
|---|---|
| **Status** | Draft v1 — superseded in part, see note above |
| **Date** | 2026-07-28 |
| **Owner** | Rob Ford, Data |
| **Producer identity** | `clinic-rules-engine` |
| **Related** | event-envelope-spec.md; twenty-data-model.md; snowflake-landing-spec.md |

## Premise

Qualification is the platform's first derived event. Rules ("clinic rules") already exist as modeled documents in MongoDB Atlas, filtering on patient medical condition and insurance coverage / copay / deductible. Rules are therefore **data, not code**: the engine is versioned SQL that joins the patient population against landed rules. No rule authoring, no new service.

## Architecture

```
MongoDB Atlas (clinic_rules) ──streamline──▶ Snowflake RAW_MONGO.CLINIC_RULES (~seconds)
Twenty (patients, events)    ──CDC─────────▶ Snowflake (existing pipeline, ~15 min)
Condition + coverage inputs  ──streamline──▶ Snowflake (if mdba-resident; open item 1)
                                          │
                              stream-triggered task: EVAL_QUALIFICATION (SQL)
                                          │  transition detected?
                                          ▼
                              Snowpark Python proc ──POST──▶ MCP write path → Twenty
                                                              (patient.qualified / .disqualified)
```

Everything runs inside Snowflake: rules land next to patient data; a triggered task evaluates; a Snowpark Python stored procedure with an External Access Integration POSTs transition events through the standard envelope. No new infrastructure.

## Components

### 1. Rules landing — via `streamline`

- Atlas → Snowflake via the proven `streamline` SPCS pipeline (mdba → sf streaming). Light up the `clinic_rules` collection: rule changes land near-instantly, versus waiting on the hourly `py-data` cycle.
- Continuous appends into `RAW_MONGO.CLINIC_RULES`; `STG_RULES.CLINIC_RULES` adds `rule_version` (hash of rule document) and validity window. Rule provenance in emitted events comes from this, regardless of whether Mongo documents carry their own versioning.
- If condition and coverage inputs also live in mdba collections, light those up on `streamline` too — this closes open item 1 with zero new tooling (see Open items).

### 2. Evaluation (versioned SQL, in repo)

- View `MART_QUAL.EVAL_QUALIFICATION`: patient population × active clinic rules → `qualifies` boolean + `criteria_met[]` / `criteria_failed[]` + `rule_version`.
- **Triggered task, not cron**: Snowflake streams on the streamline-fed tables (`CLINIC_RULES`, condition/coverage inputs) and on `RAW_TWENTY.DOMAIN_EVENT`; task runs `WHEN SYSTEM$STREAM_HAS_DATA(...)`. New data → evaluation within minutes; no data → no compute burned.
- **Transition-only emission**: event emitted only where evaluated status ≠ current status. Full-population re-evaluation per run stays cheap at this scale and eliminates per-input trigger plumbing.

### 3. Emitter

- Snowpark Python stored proc, External Access Integration scoped to the Twenty host, per-producer API key (`clinic-rules-engine`) from Snowflake secrets, submitted through the single MCP write path (C3).
- Standard envelope; `event_id` = UUIDv7 minted per transition; retries reuse the `event_id` (idempotent by convention, deduped downstream as usual).
- Reverse dataflow note: this is the platform's first Snowflake → Twenty write path.

### Latency budget (streamline + triggered task)

| Leg | Path | Latency |
|---|---|---|
| Rule/input changes → sf | streamline (SPCS) | ~seconds |
| Twenty domain events → sf | Postgres CDC | ~15 min (long pole) |
| Evaluation | stream-triggered task | ~minutes after data lands |
| Emit → Twenty state | API POST + projection workflow | ~seconds |
| sf → sig-dash / operating surfaces | Sigma queries live; MART views/dynamic tables | = data freshness |

Net: mdba-originated changes reflect in sig-dash in minutes; Twenty-originated events bounded by the CDC leg. If the 15-min CDC leg becomes the complaint, upgrade options in landing-spec order: shorter connector sync → streaming CDC. Do not route around it with direct writes.

## Event definitions (registry v1.1)

| event_type | Projects to | Payload |
|---|---|---|
| `patient.qualified` | `qualificationStatus = qualified` | `rule_version`, `criteria_met[]`, `clinic_ref`, `evaluated_at` |
| `patient.disqualified` | `qualificationStatus = disqualified` | `rule_version`, `criteria_failed[]`, `clinic_ref`, `evaluated_at` |

- State dimension on PatientProgram: `qualificationStatus` (`pending` \| `qualified` \| `disqualified`, default `pending`) + `qualificationStatusAsOf`. Separate from `lifecycleStatus` — qualification can flip while lifecycle stands.
- These two event types get **enforced payload schemas** (first activation of the deferred item): the audit value of a qualification decision depends on `rule_version` and criteria being present and well-formed. Enforced in the emitter (single producer makes this cheap).

## Explainability

Every emitted event carries which rule version fired and which criteria passed/failed. The event log is the qualification audit trail; no separate decision log.

## MongoDB-emits-events option (deferred)

Atlas Triggers/Functions could POST events directly. Assessment: wrong layer for qualification itself — the decision needs patient, condition, and coverage data, which live in Snowflake, not Mongo. Correct future use: emit a **rule-change signal** (`clinic-rule.updated`) to trigger immediate re-evaluation instead of waiting on stream lag. Optional optimization; not MVP.

## Open items

1. **Input landing paths** (blocking, likely resolved by streamline): medical condition and insurance coverage/copay/deductible data must be in Snowflake before rules can evaluate. If these live in mdba collections → light them up on `streamline` (near-instant, proven, zero new tooling). Only inputs outside mdba need a decision: (a) new domain event types with enforced payloads (audit-trail benefit) or (b) `py-data` hourly ELT (accept the hour lag on that input). Confirm which collections hold what.
2. Rule semantics to confirm against actual Mongo documents: per-clinic vs. global rules. Grain is now settled as patient × program (PatientProgram junction, 2026-07-28); confirm whether clinic further partitions qualification within a program or arrives as `clinic_ref` payload context only.
3. Disqualification review: should a disqualified→qualified flip require human confirmation, or is the rule engine authoritative?

## Registry/doc changes applied with this artifact

- event-envelope-spec.md: registry v1.1 adds both event types.
- twenty-data-model.md: `qualificationStatus` dimension on PatientProgram + projection lookup rows.
- snowflake-landing-spec.md: `REF_EVENT_REGISTRY` + `REF_VALID_TRANSITIONS` additions (`pending→qualified`, `pending→disqualified`, `qualified↔disqualified`).
