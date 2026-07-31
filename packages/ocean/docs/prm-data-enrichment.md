# PRM Data Enrichment: Derived State vs Explicit State

**Type:** Problem-framing spec (pre-decision)
**Source:** Chat session 2026-07-26 — retrieval of prior discussion on data enrichment as state vs explicit-state patient relationship management (PRM)
**Status:** Draft. The originating conversation ("Headless CRM for patient enrollment") could not be retrieved. This document captures everything recoverable so the design discussion can restart without it.

---

## Problem Statement

Patient enrollment and relationship state at Brook is currently **derived**: warehouse models enrich raw operational signals (tracking snapshots, call dispositions, activation events) into funnel state after the fact. The alternative pattern is an **explicit-state PRM** — a headless CRM layer that owns enrollment state transitions as first-class events, with the warehouse consuming rather than inferring them.

The choice is unresolved. The prior conversation that framed it ("Headless CRM for patient enrollment") is not retrievable from chat search — it likely lives inside a Claude Project or predates the search index. Meanwhile, live production symptoms (status disagreements across systems, patients missing from onboarding views) suggest the cost of derived-only state is already being paid.

## The Two Architectures

**Option A — Enrichment as state (current pattern).** Operational systems emit raw signals. dbt models derive patient state (`is_churned`, `is_lost`, funnel stage) from snapshots and event ordering. State is a query result, reconstructable but never authoritative, and sensitive to snapshot strategy and prompt/query phrasing.

**Option B — Explicit-state PRM (headless CRM).** A dedicated service owns the patient-relationship state machine. Enrollment, activation, disenrollment, and re-entry are explicit transitions with timestamps and actors. The warehouse ingests transitions as facts. State is authoritative at the source, and derivation is reserved for analytics, not for answering "what is this patient's status right now."

The tension mirrors the event-sourcing distinction already articulated in OCEAN: the event backbone records *what happened*, the operational graph answers *what is the current state*. Option B makes the PRM the writer of that current state rather than a reconstruction of it.

## Retrievable Prior Art

Provenance is marked. Recommendations are not decisions.

- **OCEAN architecture paper** — Event backbone vs Operational Data Graph. "Events are facts, tasks are derived." Closest existing framing of the derived-vs-explicit tension, at the platform level rather than PRM-specific.
- **Data infrastructure execution plan, Q9 (cohort state-change schema)** — Two designs were tabled: SCD Type 2 on the patient funnel state table vs a daily snapshot table. A week-2 spike and week-3 decision were *planned*. Outcome unknown — verify before reuse.
- **Data infrastructure execution plan, Q1 (eligibility re-evaluation)** — *Recommended default* (not confirmed as decided): keep patients in the eligible pool with an explicit state flag naming the rule they fail, so rule relaxation becomes a filter change rather than re-ingestion. This is an explicit-state pattern already proposed inside the derived architecture.
- **SIG_CIO_LEADS_DAILY_TRACKING investigation** — Demonstrated the fragility of derived state: one-word prompt changes ("leads" vs "patients") flipped snapshot strategy and changed counts (2,243 / 2,259 / 2,284 / 2,125). Root cause was business-definition ambiguity that explicit state would pin down.
- **Warehouse skill, entity disambiguation** — Enrollee vs active patient vs member is a mandatory clarification because the populations differ materially. Symptom of state living in definitions rather than in a system of record.
- **Disambiguation:** `prm_*` models in the tide-forecast repo (`prm_connect_rates`, `prm_activate_rates`, ...) are *parameter* models. They are unrelated to patient relationship management. Do not conflate.

## Live Evidence the Problem Costs Something

- **PAI-539** (Linear, updated 2026-07-23): New patients not appearing on onboarding dashboard.
- **In Clinic Activation issue** (Linear, Feb–Mar 2026): Status shows Not Enrolled for APCM after patient enrollment — direct cross-system state disagreement.
- **Data Platform Prioritized Patient List** (Notion, updated 2026-07-23): Names identity and enrollment — enrollment dates, status (active/disenrolled/pending), onboarding — as a prioritized platform data domain.

## Goals (of resolving the decision)

1. One authoritative answer to "what is this patient's enrollment status right now," identical across POP, dashboards, and warehouse.
2. State transitions carry timestamp and actor, enabling point-in-time reconstruction without snapshot archaeology.
3. Rule changes (eligibility relaxation, definition updates) become filter or config changes, not re-derivations.
4. Cortex Analyst / NL query results stop varying with phrasing for status questions.

## Non-Goals

- **Deciding the architecture in this document.** This is framing, not the decision. The decision needs the missing conversation's content or a fresh design session.
- **Reconstructing the Headless CRM conversation from memory.** Nothing here is invented from it. Only retrievable material is cited.
- **Specifying the build.** No schema, service, or migration design until Option A vs B (or a hybrid) is chosen.
- **Replacing OCEAN.** Any PRM layer must compose with the event backbone, not compete with it.

## Open Questions

**Blocking:**

1. Locate or reconstruct the "Headless CRM for patient enrollment" conversation. If project-scoped, open it in that project and export the relevant sections. *(Owner: Rob)*
2. What was the Q9 spike outcome — SCD2, daily snapshot, neither? *(Owner: DNA team / Rob)*
3. Where would explicit state live — inside POP, a new service, or Snowflake-native (Streams/Tasks over transition tables)? *(Owner: Engineering + DNA)*

**Non-blocking:**

4. Which state fields are authoritative-at-source today vs derived (enrollment date, activation, disenrollment, NIN, re-entry)? Inventory before design. *(Owner: DNA)*
5. Does the Q1 state-flag recommendation ship regardless of the A/B decision? It is compatible with both. *(Owner: Product + DNA)*
6. HIPAA surface: does an explicit PRM layer change the PHI boundary vs warehouse-only derivation? *(Owner: Compliance)*

## Next Steps

1. Retrieve the source conversation (Open Question 1). Paste relevant sections into a follow-up session or attach to this doc.
2. Confirm Q9 spike status.
3. If the source is unrecoverable within a week, run a fresh design session from this document plus OCEAN — the groundwork here is sufficient to restart cold.

## Chat Provenance

Session 2026-07-26. Four conversation searches (enrichment/state, PRM/CRM lifecycle, headless CRM enrollment, headless/state machine/POCAR) returned adjacent material but not the source conversation. Search scope covers only non-project chats. One connected-tools search surfaced the Linear and Notion evidence above.
