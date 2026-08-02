# Twenty PRM — Program Spec

Product: Twenty (open-source CRM) deployed headless as Brook's Patient/Practice Relationship Management system
Status: DRAFT v0.1 · Author: Rob (DNA) · Date: 2026-07-23
Sibling artifacts: `2026-07-23-pocar-migration-write-ownership-matrix.md` (governing doc), `2026-07-23-compliance-conformance-memo.md`, `2026-07-23-cto-proposal-ehr-intake-strangler-program.md`, Linear CCC-8 (P1 elaboration, Open Engine queue)

---

## 1.0 Problem Statement

Brook's operational tooling was custom-built around POCAR (physician portal, MongoDB backend) and has aged into three compounding costs: every clinic EHR feed passes through a **manual upload → transform → cleanse → verify step**, **patient drift** — enrollees sliding out of engagement before CCM/APCM billing thresholds are met — is the exact problem Brook sells against yet is tracked in outdated UI and ad hoc workflows, and **every new integration fights bespoke formats**, so integration cost never amortizes. Left unsolved: manual hours scale linearly with clinics signed, drift leaks the billable CPT completions that are Brook's margin promise, and sales-to-live cycles stay slow.

## 2.0 Solution Overview

Deploy **Twenty headless on Snowpark Container Services** as the commercial system of record, backed by **Snowflake Postgres**, and run a **strangler migration**: build shadow analogs of existing custom software on synthetic data, then replace features one at a time — starting with the manual intake step, then modern read surfaces, then write workflows and agentic ops.

**Architecture invariants:**
- One SPCS service, four containers: twenty-server, twenty-worker, redis, twenty-mcp. MCP reaches Twenty over localhost, holding the API key server-side.
- **Reads never touch the app.** Postgres data mirroring replicates CRM state into Snowflake within seconds — Sigma, dbt, and Cortex Analyst consume mirrored tables and semantic views.
- **Writes have one door.** All programmatic mutations go through the co-located MCP over GraphQL with per-actor attributed keys. Twenty's metadata engine owns its schema — no direct table writes, ever.
- **MongoDB stays the operational backend.** The strangler replaces the UI and workflow layer, not the datastore. Patient activity (monitoring minutes, Zoom, POCAR events) continues to persist in Mongo, mirrored realtime into Snowflake.
- Browser UI exists for occasional admin only, behind Snowflake OAuth ingress (acceptable: internal-only tool).

## 3.0 Goals

1. **Eliminate routine manual PHI handling in intake:** manual touches reduced to exception-only quarantine review within 30 days of P1 cutover.
2. **Make integrations 1:1:** FHIR R4 (US Core) as the canonical Bronze contract, so a new EHR feed is a conversion template, not a pipeline — new-feed onboarding in days, not weeks.
3. **Operationalize drift:** Enrollment state transitions plus Billing Episode shortfalls feed an Intervention queue automatically, replacing manual funnel-watching.
4. **Prove the margin atom:** cleared CPT completions computed in one place (dbt + cpt-model) and rolled to practice-level margin visible in Sigma.
5. **Establish agentic ops safely:** agents act through one attributed write path with human-gated promotion via the Open Engine queue.

## 4.0 Non-Goals

- **Replacing MongoDB** — the datastore is not the problem, the layer above it is. Separate decision if ever.
- **Exposing any surface without Snowflake-authenticated ingress** — no external users, no clinic logins to Twenty.
- **PHI in the CRM before gate C1** — Snowflake Postgres is preview. Synthetic (Synthea) records only until GA plus written BAA confirmation.
- **Patient worklists in Twenty** — record-at-a-time is Twenty, queues and aggregates are Control Room v2, cross-cutting actions are agents. Three competing frontends is how internal platforms die.
- **Big-bang migration** — every cutover is shadow-first with reconciliation proof, and rollback is "stop routing to the new surface."

## 5.0 Users & User Stories

**Intake operator**
- As the intake operator, I want the pipeline to land, convert, and validate clinic feeds automatically so that I review only reason-coded exceptions instead of handling every file.
- As the intake operator, I want quarantined records to carry a reason code so that I can disposition them without re-deriving what failed.

**Growth / BD**
- As a BD lead, I want Referrals as first-class Leads with conversion into Enrollments so that the patient funnel uses native CRM lifecycle semantics.
- As a BD lead, I want Deals and Contracts per practice with the 2026 pricing matrix so that expansion opportunities (adding an APCM line) are tracked like revenue, because they are.

**Care ops / RevOps analyst**
- As an analyst, I want CRM tables mirrored into Snowflake within seconds so that Sigma dashboards and Cortex Analyst answer practice and funnel questions without touching the app.
- As an analyst, I want Billing Episodes computed once in dbt so that margin per practice-month has exactly one source of truth.

**Data engineer**
- As a data engineer, I want new EHR feeds onboarded via conversion templates so that integration work is configuration, not custom pipeline code.
- As a data engineer, I want reconciliation tests across Mongo mirror, Twenty mirror, and warehouse marts so that every cutover is provable instead of hopeful.

**Compliance officer**
- As the compliance officer, I want the audit trail from file checksum to Silver row so that any record's lineage answers in one query.
- As the compliance officer, I want the preview-feature gate enforced in the sync task itself so that PHI cannot reach Twenty by accident.

**Operator (Rob) / agents**
- As the operator, I want work orders queued in the Open Engine (Linear CCC) and executed by rob-claude with receipts so that build work runs headless with human promotion gates.
- As an agent, when a task needs local access outside allowed sources, I want to HUMAN HOLD rather than proceed so that the safety boundary is structural, not behavioral.

## 6.0 Object Model

Standard-object mapping (Rob's canonical assignments):

| Standard | Brook object | Notes |
|---|---|---|
| Contact | **Patient** | Thin roster grain, canonical key from DIM_PATIENT_CONFORMED, never minted by Twenty |
| Lead | **Referral** | The sharpest mapping: lead conversion IS enrollment |
| Contact (2nd type) | **Provider** | Separate object (Twenty lacks record types), NPI + billing supervision |
| Account | **Clinic** | Health-system hierarchy, EHR vendor, BAA status |
| Case | **Zendesk ticket** | One-way inbound projection, no PHI fields mapped (D3) |
| Opportunity | Deal / Program Expansion | New logo or adding a program line |
| Campaign | Practice Outreach | Patient-enrollment campaigns stay operational |

Net-new objects: **Contract** (rate card, gain-share terms), **Payer** (plan × locality reimbursement), **Care Program** (CCM/APCM/RPM/PCM reference + billing rules), **Enrollment** (patient × program × practice — the drift state machine), **Billing Episode** (enrollment × service month — the margin atom, FHIR analog Claim/EOB), **Device Assignment** (16-day transmission compliance), **Intervention** (drift-triggered worklist).

**Grain rule:** patient-identifiable rows live in the warehouse and app layer. Twenty carries the commercial graph plus practice-level rollups with small-cell suppression.

## 7.0 Data Architecture

- **Feeds:** Openflow GetSFTP/FetchSFTP pulls from the existing SFTPGo host — clinics change nothing. Every file is ledgered by checksum before content lands. No SFTP termination inside SPCS (ingress is HTTPS-only).
- **Canonical format:** FHIR R4 + US Core in VARIANT Bronze. Converter at the edge (FHIR-Converter on SPCS, or CareEvolution Orchestrate native app) owns HL7v2/C-CDA/CSV → FHIR, because HL7v2-to-FHIR is n:m — nothing downstream ever sees v2. dbt flattens to conformed Silver.
- **Quality:** Gate A (US Core profile validation, pre-model) and Gate B (dbt-expectations suites, in-model, error blocks + quarantines, warn logs), plus Snowflake Data Metric Functions for continuous monitoring → Datadog. Twelve-domain MECE coverage matrix in the governing doc §4.3.
- **CRM sync:** Twenty → Snowflake free via Postgres mirroring. Snowflake → Twenty (patient projection, rollups) via scheduled task calling the MCP write path.

## 8.0 Requirements

**P0 — cannot ship without:**
- [ ] File-ledger manifest reconciliation proves zero silent file loss (every SFTPGo-listed file accounted for by checksum)
- [ ] FHIR profile validation with reason-coded quarantine — nothing malformed reaches Bronze
- [ ] Silver patient references resolve against DIM_PATIENT_CONFORMED — joins never key on source MRN
- [ ] Masking-policy access tests pass on all Silver PHI columns
- [ ] One write-owner per entity per phase, enforced by the ownership matrix — no bidirectional sync anywhere
- [ ] C1 gate enforced in the sync task: synthetic schema until Snowflake Postgres GA + BAA confirmed

**P1 — fast follow:**
- [ ] Per-clinic volume anomaly alerting (trailing 8-week distribution)
- [ ] Elementary evidence reports rendered per run for compliance review

**P2 — design for, build later:**
- [ ] Cross-surface reconciliation once P2 read surfaces exist
- [ ] Self-serve whitelabeled clinic upload portal (requires Snowflake identities for uploaders — may never clear)

## 9.0 Success Metrics

**Leading (30 days post-P1-cutover):** routine manual intake touches reduced to exception-only, quarantine rate under 5% of resources with 100% reason-coded, feed-to-Silver latency under one hour, file-loss incidents zero by manifest proof.
**Lagging (one quarter):** new clinic feed onboarding in days not weeks, DQ incidents caught by gates rather than downstream consumers, drift interventions triggered automatically from Enrollment/Billing Episode state, reduced workforce exposure to raw PHI (stated affirmatively in compliance review).

## 10.0 Migration & Phasing

| Phase | Ships | Gate |
|---|---|---|
| P0 | Headless Twenty, mirroring, MCP path, synthetic data, commercial objects | — |
| P1 | Upload pipeline + DQ gates (beachhead) | CTO approval. Est. 2–3 working days elapsed, ~12 human hours on task |
| P2 | Warehouse-backed read surfaces, Control Room v2, TIDE features | P1 30-day metrics review, D3 |
| P3 | Write workflows, agentic ops | D1 (Postgres GA/BAA), D2 (enrollment persistence) |
| P4 | Zoom embed, minute capture path | Highest blast radius, deliberately last |

Three rules that keep it from rotting: **one write-owner per entity per phase**, **Twenty never mints patient identity**, **synthetic data until C1 clears**. The reconciliation harness (dbt tests across Mongo mirror, Twenty mirror, warehouse marts) is the cutover proof for every phase.

## 11.0 Program Workstreams

**In:** upload pipeline + DQ (beachhead), FHIR/HL7 layer, Twenty headless + logic functions (computation stays in dbt, workflows trigger only), TIDE/tide-forecast (identity spine is a hard dependency), cpt-model.json decision tree (the Billing Episode rule engine), Control Room v2 (queue UI lane), OCEAN Zoom Contact Center slice (P4), Cortex agentic layer (MCP + Agents + CORPUS_CHUNKS).
**Later:** pan_actuarial (intervention prioritization by patient NPV, post-TIDE), gain-share cohort analysis (margin evidence, P3+).
**Out:** Snowflake spend diagnosis (parallel hygiene track), Sheets integration, BI platform eval.
**Enabler:** DE/DS agent skills system.

## 12.0 Risks

| Risk | Mitigation |
|---|---|
| Preview database anchors a system of record | C1 gate, synthetic-only build, pg_dump exit path to any Postgres host |
| Two writable patient stores drift | One write-owner rule + daily reconciliation alerts |
| OSS upgrade churn (forward-only migrations) | Pinned images, pg_dump before every upgrade, dependency scanning |
| Always-on SPCS cost | Smallest pool, reviewed against retired manual hours at 30 days |
| Scope creep into a POCAR rewrite | Phase gates, non-goals, per-work-order out-of-scope discipline |

## 13.0 Compliance

Six project-specific controls (full memo attached): **C1** preview-feature gate, **C2** CRM PHI boundary with small-cell suppression, **C3** single attributed write path, **C4** quarantine handled as PHI, **C5** third-party code pinned and scanned, **C6** minimum-necessary improvement from automating manual handling. Seven open items route to the Privacy Officer and block the corresponding phase gates by reference.

## 14.0 Execution Infrastructure

Build work runs through the **Open Engine** queue (Linear team CCC, engine v2, canonical at `~/Repos/dna-agent-mail/.claude/skills/open-agent-engine/SKILL.md`): dual runtime (daemon headless + Claude Code manual), exact receipt tokens, one task per run, Slack relay via the dna-agent-mail daemon only. **CCC-8** (P1 elaboration into five work orders) is in flight. Prerequisite before P1 child promotion: bump CCC-4 allowed local sources to include `brook-ehr-intake` — currently only `~/Repos/dna-agent-mail` is permitted, so repo-touching tasks would HUMAN HOLD.

## 15.0 Open Questions

**Blocking:**
- D1 — Snowflake Postgres GA + BAA scope confirmation (Privacy Officer + CTO, gates P3 real-data projection)
- D2 — Enrollment persistence: Twenty-native vs Mongo-persisted with Twenty triggers (Rob + engineering, P3 planning, default Mongo-persisted)
- D3 — Zendesk PHI policy and BAA before any Case field mapping (Privacy Officer, before P2)
- CCC-4 v3 bump adding brook-ehr-intake to allowed sources (Rob, before P1 child promotion)

**Non-blocking:**
- D4 — Provider ownership cutover timing (Rob, P3 planning)
- Quarantine-rate threshold for declaring P1 cutover complete (Rob + intake operator)
- Clinic-facing upload portal: build vs keep SFTP-only (CTO)

## 16.0 Timeline Considerations

P1 estimated at 2–3 working days elapsed with ~12 human hours on task (agent-executed build, human review), followed by the parallel-run reconciliation window. P0 shadow work proceeds concurrently on synthetic data at near-zero marginal cost. P2 starts only after the P1 30-day metrics review. P3/P4 wait on their decision gates. No hard external deadlines — the sequencing constraint is internal proof, not calendar.
