# Headless PRM + PULSE — Patient Enrollment Status System

**Spec / status capture — 2026-07-22**
Author: Rob Ford (DNA) · Status: Draft · Linear project: [PULSE / Declared-State Funnel](https://linear.app/brook-health/project/pulse-declared-state-funnel-d3ea7b0e45bf) · Founding spec: [Declared-State PRM 26-07-16](https://app.notion.com/p/39fdf47a35be80348bd1fd2d27e09a6b)

---

## TL;DR

Brook's enrollment→activation pipeline currently has no system that *holds* a patient's funnel position. Every consumer infers it retroactively from side effects scattered across Customer.io, Billy, POCAR, and timestamps — the "Enrichment-as-Record" pattern. This makes funnel counts a fresh analysis each time, prevents flow metrics (transitions, dwell time) from existing as data, and forces the ~17-substage taxonomy to conflate true stages with hold and exit reasons.

The fix is one system with three assertions: make the pipeline **identified** (TIDE — done), **declared** (PULSE — the append-only state ledger), and **actionable** (a headless PRM work surface, Twenty, undecided on hosting). A downstream **forecast** consumes the clean declared state. This document is the single reference for that system, its build sequence, and its open decisions.

---

## 1.0 Problem

1.1 **State is derived, not asserted.** No operational system holds funnel position; it is reconstructed analytically (Control Room v2 rebuilds the nine-stage bowtie each time). Derived state is why identity resolution (TIDE) needed a heroic rebuild and why the funnel leaks at handoffs.

1.2 **Flow metrics don't exist as data.** Dwell time, transition rates, and time-in-stage are model outputs to be defended, not columns to be queried.

1.3 **The taxonomy conflates three things.** The current ~17 substages mix true stages, hold reasons, and exit reasons into one flat list, so "where is this patient and why" has no clean answer.

1.4 **No shared surface for humans and agents.** Ops rescues stuck patients through ad-hoc analysis; there is no work-state surface with owner, next action, and SLA per patient — and no attribution trail for agent actions.

---

## 2.0 Goals and non-goals

### 2.1 Goals

- Every patient carries one identity key (TIDE) — **achieved**, match rate 7.5% → 99.95%.
- That key carries an explicitly declared, event-sourced funnel state (PULSE).
- Stage, owner, next action, and dwell time are first-class queryable fields, not derived analytics.
- Transitions and dwell times exist as data with actor attribution.
- Human and agent actors work the funnel through a shared surface; every transition is attributable.
- The activation forecast consumes clean declared state rather than inferred ground truth.

### 2.2 Non-goals

- PULSE is **not** the store of clinical or billing facts. It is the single writer of *funnel state*; clinical event capture is a follow-on PRD on the same rails, not Phase 1.
- The PRM is **not** native FHIR throughout — Brook-native objects with FHIR mapping at the EMR boundary only.
- Twenty is **not** authoritative for any clinical or billing logic — it holds a cached projection.
- **Cleora / Polymarket is out of scope.** It is a separate side quest (see §7.3).

---

## 3.0 System map

The through-line sentence: **make the enrollment→activation pipeline identified, declared, forecastable, visible, and actionable, on a streaming substrate, built by a factory.** Everything below serves that sentence; anything that doesn't is scope drift.

| Layer | Component | Role | State |
|---|---|---|---|
| Identity | TIDE | One key per patient (`BRIDGE_CIO_LEAD`, `DIM_LEAD`, `BRIDGE_PATIENT_SYSTEMS`) | Landed; open over-merge check |
| Declared state | **PULSE** | Append-only transition ledger + versioned state catalog | Spec done; scaffold pending |
| Forecast | Activation Forecasting Model + Projections spec | Predict enrollment/activation from declared state | Unblocked by TIDE; consolidation pending |
| Visibility | Sigma + Ezra | Human dashboards + semantic model | Prod-hardened; DNS cutover in progress |
| Work surface | **Headless PRM (Twenty)** | Owner, next action, SLA per patient; agent inbox | Hosting decision open (§6.0) |
| Ingress | streamline / ZCC | Streaming substrate (webhooks → Snowpipe Streaming) | Groundwork moved |
| Factory | CCC / Open Engine | Autonomous work-order execution | Running |

---

## 4.0 PULSE — the declared-state ledger

**PULSE = Patient Unified Ledger of State and Events.** A FastAPI service that fires real, traceable events — not a logic-only framework.

### 4.1 Architecture

- **Serving store:** RDS Postgres, or Snowflake Postgres (GA 2026-02-24) if the hosting decision keeps the stack inside Snowflake.
- **`prm_event`** — append-only transition ledger. No UPDATE/DELETE anywhere in code or migrations; enforced at the grant level.
- **`prm_current_state`** — current-state projection keyed by aggregate, updated in the same transaction as the event.
- **`prm_outbox`** — transactional outbox; a relay publishes to AWS EventBridge, from which consumers project into Snowflake, Twenty, and Customer.io.
- **Concurrency:** optimistic, via `aggregate_seq` per patient.

### 4.2 Traceability contract

Every event carries: UUIDv7 `event_id`, `correlation_id` (threads one patient journey across systems), `causation_id` (links a command to its resulting events), `actor_type` + `authority` (the human↔agent autonomy ladder), and W3C `traceparent` (APM linkage).

### 4.3 The state catalog

A versioned YAML file is the single definition of stages, holds, and exits. PULSE enforces it at write time; dbt exports it as a seed so definitions are shared, not re-implemented. Collapsing the ~17 substages into ratified stages/holds/exits is human-gated (work order S0.3).

### 4.4 The single-writer rule

All patient funnel state flows through PULSE. Existing apps (PAP, Billy, POCAR) connect first via a **signal adapter on CDC taps**, then migrate to native command-API calls over time. Twenty's stage field is a projection — never authoritative for clinical or billing logic. This is the same single-canonical-model discipline as the `cpt-model.json` fix, applied at system scale.

---

## 5.0 Headless PRM (Twenty) — the work surface

### 5.1 Role

Twenty is demoted from hub to **human operational surface and agent approval inbox**. Tasks are work orders; the activity timeline is a receipt log; stage transitions with actor attribution are the action-to-outcome labels the agent autonomy loop needs to grade trust tiers. Humans supervise agents through a UI they already understand and can override any transition without touching code.

### 5.2 Data minimization (the control that matters most)

Twenty holds the **work-state projection only**: `patient_key`, stage, hold reason, owner, next action, dwell timestamps. Names, DOB, contact, clinical, and claims data stay in PULSE and Snowflake.

This is still PHI — the key is re-linkable and the context is care, so it is not de-identified — but the exfiltration value and breach blast radius collapse to a pseudonymous worklist. Minimum-necessary implemented as architecture does more for exposure than any platform choice.

### 5.3 Why a CRM shape

The funnel is a pipeline-of-people problem — entities, stages, tasks, ownership, activity timeline — the exact shape CRMs commoditized. The expensive part of a bespoke state service is the exception-handling UI nobody budgets; Twenty ships the Kanban escape hatch, so ops rescues stuck patients without new tooling. No per-seat licensing means agent actors are free rows, not paid seats. Self-hosted keeps PHI in-VPC with no SaaS BAA to negotiate.

---

## 6.0 Hosting decision — ADR-0002 (open)

**Question:** host Twenty on Snowpark Container Services (SPCS) or DuploCloud AWS EKS. Primary concern: data exfiltration. Both AWS and Snowflake are on BAAs; HIPAA and SOC2 both apply.

### 6.1 Exfiltration comparison

| Vector | Twenty on SPCS | Twenty on DuploCloud EKS |
|---|---|---|
| npm supply-chain phone-home | Dead by default — no internet without an External Access Integration | Open unless egress NetworkPolicy built and maintained |
| Twenty workflows/webhooks POSTing out | Destination must be an ACCOUNTADMIN-approved network rule | Blocked only by the same DIY firewall |
| Email/calendar sync integrations | Cannot connect unless allowlisted; disable regardless | Same feature risk, softer enforcement |
| Database | Snowflake Postgres in isolated private network, PrivateLink, pg_bouncer | RDS in private subnets — mature, more SGs you own |
| Front door (authed API walk-out) | Snowflake auth gates the endpoint before the container; per-identity key-pair auth + audit | ALB + OIDC you assemble |
| Audit evidence | Trust Center, access history, event tables inside an attested platform | DuploCloud evidence, but you own VPC/SG/NAT/K8s RBAC |

**Structural difference:** on SPCS the failure mode is "someone must approve adding an egress rule"; on EKS it is "someone must remember the firewall exists." SPCS is default-deny egress; EKS is default-allow.

### 6.2 What SPCS costs

Always-on compute pool billed while active (idle nodes included); image pushes to the Snowflake registry and Postgres migrations on every Twenty upgrade, with no Helm/Argo ecosystem; Redis as an ephemeral sidecar.

### 6.3 Verify before committing

1. Confirm Brook is on **Business Critical Edition or higher** (required for PHI) and that **both SPCS and Snowflake Postgres are inside the current BAA/HIPAA attestation scope** — get it in writing from the Snowflake AE; attestations can lag GA.
2. Region match between the Snowflake account and the AWS VPC hosting PULSE, for the PrivateLink egress path.
3. Per-agent Twenty API token scoping with anomalous-read-volume alerting — a leaked authorized token is the residual front-door vector no platform fixes.

---

## 7.0 Forecasting (reframed)

### 7.1 The reframe

The proliferate naming (TIDE, Cleora, Activation Forecasting Model, Projections spec) served to pare down each problem surface, but left the work unfinished. Bringing the forecast names into alignment and finishing is now the goal.

### 7.2 Consolidate

**Activation Forecasting Model** + the **Enrollment & Activation Projections spec (26-07-16)** + any other forecast-related spikes merge into one home. The forecast was deliberately paused on unreliable ground truth; TIDE's match-rate fix unblocks tuning.

### 7.3 Keep separate

**Cleora is a Polymarket side quest** — an expansion of the forecast work into prediction-market applications. It stays out of the Declared-State Funnel and out of the activation-forecast consolidation.

---

## 8.0 Build sequence

```
S0.1 (scaffold)
  ├─► S0.2 (catalog machinery) ─► S0.3 (ratify catalog v1 — SUPERVISED, human-gated)
  └─► S1.1 (ledger schema) ─► S1.2 (command API) ─► S1.3 (EventBridge relay)
                                    └─► S2.x (signal adapter, backfill, drift) gated on S1.2
S4.1 (Dockerfile + DuploCloud/SPCS deploy) — gated on hosting decision §6.0
```

| WO | Scope | Depends on |
|---|---|---|
| **S0.1** | rob-repo bootstrap of `brookai/pulse`; `catalog` + `ledger` packages; spec + ADR-0001; CLAUDE.md hard rules; green CI | none |
| **S0.2** | Catalog machinery — Pydantic schema, loader, validators, dbt seed export. v1 content excluded | S0.1 |
| **S0.3** | Ratify state_catalog v1 — collapse ~17 substages (needs Snowflake inspection + human ratification) | S0.2 |
| **S1.1** | Ledger schema — `prm_event` / `prm_current_state` / `prm_outbox`, Alembic migrations, grant-level append-only proof | S0.1 |
| **S1.2** | Command API — endpoints, idempotency, optimistic concurrency, write-time catalog enforcement | S1.1, S0.2 |
| **S1.3** | Outbox relay → EventBridge | S1.2 |
| **S2.x** | Signal adapter (CDC taps), backfill, drift detector | S1.2 |
| **S4.1** | Container image + deploy manifests | §6.0 decision |

---

## 9.0 Current state (2026-07-22)

- **Repo:** `brookai/pulse` does **not** exist. The 2026-07-18 rob-claude session claimed DNA-695 but died before `gh repo create --push` and posted no receipt.
- **DNA-695:** reset to **Todo** with a stale-claim receipt and a cleanup note (check for a partial local `pulse/` tree before re-running). Process gap logged: a claim with no receipt sat silent 3 days — add a stale-claim sweep (claim + no receipt > 24h → auto-reset) to the queue loop.
- **Linear project:** [PULSE / Declared-State Funnel](https://linear.app/brook-health/project/pulse-declared-state-funnel-d3ea7b0e45bf) created under Data Services, In Progress.
- **S0.2 / S1.1:** drafted in full, **not yet queued** in Linear (pending writes).
- **Forecast consolidation note:** not yet recorded in Linear (pending write).

---

## 10.0 Open decisions

1. **Twenty hosting** (§6.0) — SPCS vs DuploCloud EKS. Blocks S4.1. Needs the three verifications in §6.3.
2. **Forecast-note capture** — comment on the Activation Forecasting Model project, a tracked consolidation issue, or both.
3. **Dependency relations** — set explicit blocked-by on S0.2/S1.1 (→ DNA-695), or keep the dependency map in descriptions only.
4. **PULSE serving store** — RDS Postgres vs Snowflake Postgres, downstream of decision 1.

---

## 11.0 Success metrics / acceptance

- Funnel counts come from a query against `prm_current_state`, not a fresh analysis.
- Dwell time is a queryable column per stage.
- Every handoff transition carries actor attribution (human or agent identity).
- Agent transition acceptance rate is measurable per transition class — the input to the autonomy promotion ladder.
- Twenty holds only the pseudonymous projection; a scan of its schema finds no name/DOB/clinical/claims fields.

---

## 12.0 Risks

- **Split-brain PULSE↔Twenty** — same class of bug as the CPT artifact duplication; the single-writer contract must be enforced in code, not convention.
- **Twenty youth** — fast release cadence, breaking migrations; audit logging likely needs augmentation to meet PHI access-logging requirements (verify before committing).
- **The thin alternative** — a task table plus a `funnel_state` projection inside PULSE captures much of the value at near-zero ops cost. Twenty wins only if ops and agents actually live in the timeline.
- **TIDE over-merge** — confirm the bridge isn't merging distinct records (false positives) before treating ground truth as fully clean.
- **Capacity** — the reporting queue absorbed all completions last window; three of four July OKR milestones defer to the Aug 15 checkpoint. This build competes with that queue for the same capacity.
