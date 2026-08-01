# ADR: Absorbing OCEAN into the PULSE Ledger Foundation

**Status:** Proposed — pending repo reconciliation (§9) and Tal sign-off
**Date:** 2026-07-31 (rev 2 — absorption framing)
**Deciders:** Ford (author), Tal (sign-off).
**Scope:** How the OCEAN pattern and codebase (event backbone + Operational Data Graph, "events are facts, tasks are derived") are absorbed into PULSE (Patient Unified Ledger of State and Events). PULSE is OCEAN's only application — doctrine has shifted wholly to declarative, so OCEAN is not amended for one domain, it is superseded and its code migrates into the PULSE repo as the distribution subsystem. One project, one repo, one doctrine.
**Inputs:** `rpc-object-model-assessment.md` v0.7 (pinned vocabulary §1, invariants I1–I9, spine §4.3), `DNA-SPEC-DECLARED-STATE-PRM`, prior OCEAN/PULSE reconciliation (design-rationale thread, 2026-07-31). The OCEAN repo itself was not readable at authoring time — see §9 for the verification checklist that closes that gap.

---

## 0. TL;DR

OCEAN has exactly one application, and it is PULSE. That fact retires the original framing — OCEAN as platform doctrine that PULSE amends with a patient-state carve-out — because there is no platform left to carve out from. The thinking has shifted wholly to declarative (not inferred), so OCEAN's derive-in-the-graph doctrine is superseded, not amended, and the OCEAN codebase migrates into the PULSE repo as the distribution subsystem once that repo exists (S0.1). What survives is a three-way decomposition of the pattern: **keep** the backbone code as-is in its distribution role (EventBridge relay, archive, replay, fan-out) — it becomes a PULSE workspace package, **repurpose** the Operational Data Graph (ODG) as a read-only projection layer rebuilt from the ledger rather than a derivation layer built from the feed, and **forbid** two OCEAN idioms outright — producers emitting state-bearing events directly onto the bus, and any consumer treating the bus or its archive as the record.

The single sentence that governs everything: **the ledger is the record, the backbone is the feed.** Commands enter the ledger through one writer with transition legality checked against the versioned catalog, current state co-commits with the event, and the outbox publishes an OCEAN-conformant envelope onto the backbone after commit. External systems of record (Customer.io per D9, Zendesk for Case) keep adjudicating their own state — the ledger records their transitions as attributed events and never blocks them. OCEAN's task-derivation motto survives untouched: tasks were always supposed to be derived, and now they derive from declared state instead of reconstructed state.

The plan lands in four phases aligned to the existing S0–S4 delivery sequence, adds a repo-absorption step to Phase 0/1 (history-preserving import of the ocean repo into the PULSE monorepo, then archive the source), produces one doctrinal artifact (the supersession notice, drafted in §7), and carries ten repo-verification items (§9) because the repo was unreadable from this session. Absorption also resolves the compliance placement problem for free: the code leaves the personal `robford-brookai` account by import rather than org transfer. Recommended next action: reconcile §9 against the repo tree, then fold this ADR's §4 contract into `DNA-SPEC-DECLARED-STATE-PRM` alongside the object-model section.

---

## 1. Context

### 1.1 The two artifacts

**OCEAN** is the event architecture originally framed at platform level: an event backbone (records what happened — at-least-once, replayable, many consumers) and an Operational Data Graph (answers current state, derived from backbone facts). Its motto is "events are facts, tasks are derived." Its doctrine, as written, is that state is derived in the graph. As of this ADR, OCEAN has one application — PULSE — and no other adopter is planned. That demotes it from platform doctrine to subsystem, and the demotion is the decision this document executes.

**PULSE** is the Patient Relationship Management (PRM)-scoped declared-state ledger: a command API over an append-only Postgres ledger with a single-writer rule, transition legality enforced at write time against the versioned state catalog, current state co-committed with each event, and an outbox relay to EventBridge with Snowflake, Twenty, and Customer.io as projection consumers.

### 1.2 The tension, named

OCEAN's derive-in-the-graph doctrine is, for patient state specifically, the Enrichment-as-Record anti-pattern promoted one layer up. If patient status is reconstructed by graph consumers from a feed of side-effect events, nothing has changed except where the inference runs. The live production symptoms (status disagreements across systems, patients missing from onboarding views, funnel counts requiring fresh analysis each time) are the cost of that doctrine applied to state that is too load-bearing to be a query result.

The prior reconciliation (2026-07-31 design thread) resolved the conceptual mapping: PULSE promotes patient state from *derived in the graph* to *declared into the backbone*. An earlier revision of this ADR planned a one-paragraph carve-out amendment to the OCEAN paper, per the follow-on the assessment's §8 registers. That plan is withdrawn: with PULSE as OCEAN's sole application, a carve-out that covers the entire application surface is a supersession wearing an amendment's clothes. This ADR does the honest version — supersede the paper (§7), absorb the code (§6), retire the second doctrine. It also lances the naming-proliferation risk already flagged as a finishing hazard: OCEAN stops being a project name and becomes a package name.

### 1.3 Constraints inherited as locked

- Declared, not inferred. Patient state fires real, traceable events into a ledger — never reconstructed from metadata across systems.
- State is given by its system of record (SoR). Exactly one system adjudicates each state. PULSE either owns the machine or records the external SoR's transitions with attribution (the D9 pattern).
- Single-writer rule on the ledger. One authoritative write path, hard constraint.
- Invariants I1–I9 from the object-model assessment, especially I2 (one home per status) and I3 (derived-then-declared verdicts, computed once in the warehouse authority).
- Warehouse as reconciliation referee between operational systems.
- Infrastructure: AWS-DuploCloud EKS for the PULSE service, EventBridge as the relay target, Snowflake + Snowpark Container Services (SPCS) on the projection side, C1 gate (executed Snowflake Postgres Business Associate Agreement) governing production Protected Health Information (PHI) in the Twenty database.

---

## 2. Decision

Two coupled decisions, one topology and one repository.

**Topology:** adopt the **record-versus-feed split**: PULSE ledger as the book of record for the six PULSE subject types (Referral, Consent, Enrollment, BillingEpisode, Device, Contract) plus recorded external state (CommunicationConsent), with the OCEAN backbone retained in the distribution role and the ODG reconstituted as a read-only projection layer. Formalized as (a) an envelope contract extension (§4.2), (b) an SoR registry in the state catalog (§4.3), and (c) a producer policy that converts state-bearing emits into commands (§4.4).

**Repository:** absorb the OCEAN codebase into the PULSE monorepo as the distribution package when the repo is scaffolded (S0.1 / DNA-695), with history preserved, the source repo archived, and the OCEAN paper superseded by a notice pointing here (§7). OCEAN survives as a package name, not a project name. Since PULSE is the sole application, doctrine is singular: declared, not inferred, everywhere.

---

## 3. Options considered

### Option A — PULSE as pure OCEAN consumer (doctrine unchanged)

Producers keep emitting events onto the backbone. PULSE, if it exists at all, is one more graph node deriving patient state from the feed.

| Dimension | Assessment |
|---|---|
| Complexity | Low — nothing changes |
| Declared-state fit | ✗ Fails outright. State remains a reconstruction, now with a new name |
| SoR discipline | ✗ No adjudication point. Two consumers can disagree about a status, violating I2 |
| Transition legality | ✗ Unenforceable — no write-time gate exists on a bus |
| Audit posture | △ Events are attributed but transitions are not validated |

**Pros:** zero migration, no doctrine change.
**Cons:** it is the current failure mode with extra steps. Every design goal of the program is unmet.

### Option B — PULSE ledger replaces the backbone for PRM

The ledger becomes both record and distribution. Consumers read the ledger directly (change data capture or polling), EventBridge exits the PRM picture.

| Dimension | Assessment |
|---|---|
| Complexity | Medium — but couples every consumer to ledger internals |
| Declared-state fit | ✓ Record semantics are correct |
| Distribution | ✗ Loses EventBridge fan-out, archive, replay, cross-account routing. Every consumer needs read credentials into the transactional database |
| Blast radius | ✗ A slow consumer becomes a transactional-database load problem. Read isolation between the record and its consumers disappears |
| Sunk investment | ✗ Discards working, provisioned backbone code (relay, archive, replay, IaC) to rebuild distribution inside the ledger service |

**Pros:** one system, no relay lag, strongest consistency for consumers.
**Cons:** conflates record and feed in the opposite direction — the feed becomes the record's problem. Violates the boring-infrastructure preference for no reason. Note this option is *not* what "absorb OCEAN into the PULSE repo" means: absorption moves the code, not the topology — the bus keeps its job from inside the monorepo.

### Option C — Record-versus-feed split (recommended)

Ledger is the record. Outbox relays committed events onto the backbone in OCEAN-conformant envelopes. Backbone stays exactly what OCEAN built it to be — distribution, at-least-once, replayable, never authoritative. ODG components become projections rebuilt from the ledger.

| Dimension | Assessment |
|---|---|
| Complexity | Medium — outbox relay plus envelope extension, both already scoped in PULSE architecture |
| Declared-state fit | ✓✓ Write-time legality, co-committed state, attributed transitions |
| SoR discipline | ✓✓ One adjudicator per state, external SoRs recorded per D9 |
| Distribution | ✓ Full reuse of backbone infrastructure, archive, replay, existing consumer patterns |
| Platform coherence | ✓ OCEAN envelopes on the OCEAN bus. Consumers cannot tell PRM events changed provenance — they only gained guarantees |

**Pros:** maximal reuse, consumers migrate without code changes to their subscription mechanics, and the codebase moves cleanly — the backbone imports as a self-contained package because its interface (envelopes on a bus) is already the package boundary.
**Cons:** relay lag between commit and publication (bounded, monitored — §4.5), and two replay paths that must be disciplined (§4.6) or the archive quietly becomes a second record.

**Verdict: Option C.** It is the only option where both halves of the existing investment survive — PULSE's guarantees and OCEAN's plumbing — and the only one where absorption is a `git` operation rather than a rewrite.

---

## 4. The adapted pattern

### 4.1 Pattern decomposition — keep, repurpose, forbid

Every element of the OCEAN pattern gets exactly one disposition. This table is the adaptation.

| OCEAN element | Disposition | Rationale |
|---|---|---|
| EventBridge bus, rules, fan-out | **Keep** | Distribution role unchanged. The backbone was never the problem |
| Event archive + replay tooling | **Keep, re-scoped** | Convenience replay for projection rebuilds only. Authoritative rebuilds read the ledger (§4.6) |
| Envelope schema and naming conventions | **Keep, extended** | PULSE events ride the same envelope with a mandatory extension block (§4.2). Existing consumers parse them unchanged |
| Consumer registration / subscription patterns | **Keep** | Twenty projector, Customer.io sync, Snowflake ingestion all subscribe as ordinary OCEAN consumers |
| "Tasks are derived" | **Keep, unchanged** | The half of the motto that was always right. Tasks, work queues, and next-actions derive from declared state instead of reconstructed state — the derivation gets a better input, not a different doctrine |
| Operational Data Graph as current-state answerer | **Repurpose** | Becomes the projection layer: read-only, rebuildable from the ledger, never authoritative. With PULSE as the sole application there is no residual derive-in-the-graph role — the ODG concept fully collapses into "projections" |
| Producer libraries emitting domain events | **Repurpose** | For PULSE subjects, producers become **ingress adapters**: they translate external signals into commands against the PULSE API. The ledger emits the event after commit. For non-subject facts (telemetry, non-catalog activity) direct emits remain legal |
| "Events are facts" for state-bearing events | **Forbid (for PULSE subjects)** | A state transition emitted from a side effect is an unvalidated claim, not a fact. Facts about PULSE-subject state are minted by the ledger and only the ledger |
| Bus or archive as record ("OCEAN event store") | **Forbid** | The named hazard. Any consumer reconstructing PULSE-subject truth from the feed reintroduces enrichment-as-record one layer up |

### 4.2 Envelope contract extension

PULSE events publish in the standard OCEAN envelope so existing routing and consumers keep working, with a mandatory `pulse` extension block in the detail payload:

```
detail:
  pulse:
    subject_type:      enrollment | referral | consent | billing_episode | device | contract | communication_consent
    subject_id:        <ledger subject key>
    person_key:        <TIDE key>            # identity join, never carries state (I1)
    transition:        {from_state, to_state}
    reason:            CodeableConcept        # mandatory where the catalog says so (I4)
    actor:             {type: human|system|model, id, attribution}
    catalog_version:   <semver of the state catalog validating this transition>
    rule_version:      <present iff verdict event, per I3>
    ledger_seq:        <monotonic per subject> # total order authority
    provenance:        {source_system, evidence_ref, ingress_ref}
```

Contract rules:

1. `ledger_seq` is the ordering authority. EventBridge delivery is at-least-once and unordered — consumers deduplicate and order on `(subject_id, ledger_seq)`, never on delivery time.
2. Value objects use FHIR datatypes (I5): reasons are CodeableConcepts, periods are Periods, quantities carry Unified Code for Units of Measure (UCUM) units.
3. The envelope is generated from the state catalog (the fifth generated surface, joining Twenty metadata, FHIR Shorthand, warehouse seeds, and command API types from the assessment's §7). Continuous integration fails on drift between the envelope schema and the catalog version, same as every other surface.
4. Verdict events carry `rule_version` and input lineage, actor type `model` — the derived-then-declared discipline (I3) made visible on the wire.

### 4.3 The SoR registry — "state given by system of record," formalized

The design goal generalizes D9 into catalog metadata. Every state machine in the catalog declares its authority:

| Authority mode | Meaning | Instances |
|---|---|---|
| `pulse` | Ledger owns the machine. Transitions enter only through the command API, legality enforced at write | Referral, Consent, Enrollment, BillingEpisode, Device, Contract |
| `external(system)` | Named external system adjudicates. Ledger records every transition as an attributed event (actor = the system) and never blocks or adjudicates. Reconciliation sweep compares ledger history to the SoR's export and declares corrections (actor = reconciliation) | CommunicationConsent → Customer.io (D9). Case → Zendesk (mirror, no ledger machine) |
| `warehouse` | Verdict machines. Computed once in the warehouse authority (dbt, per D1), declared to the ledger with rule_version and lineage | Qualification, Eligibility, BenefitsVerification, MarketingClearance, BillingEpisode qualified/not_qualified |

Registry rules: exactly one authority per machine (I2 at the system level). Changing an authority is a catalog version bump, reviewed like a schema change. Ingress adapters for `external` machines are generated against the registry, so a new external SoR is configuration plus one adapter — not doctrine.

### 4.4 Producer policy — the migration's sharp edge

The one behavioral change existing OCEAN producers experience:

- **If your event asserts a PULSE-subject state transition:** stop emitting it. Issue a command to the PULSE API instead. The ledger validates, commits, and emits the event onto the backbone for you. Your emit becomes a request.
- **If your event is a non-subject fact** (a reading landed, a call completed, a document arrived): keep emitting directly. Nothing changes.
- **The classification test:** does the event's payload name a state that lives in the catalog? Then it routes through the ledger. The catalog is the boundary, mechanically checkable in CI against producer event schemas.

Sanctioned command sources per the existing register: the Twenty kanban webhook (D8, heal-back on invalid drags), Customer.io consent ingress (D9), the identity-resolution service (§5.3 of the assessment), the warehouse verdict runner (I3), and human actors through attributed tooling.

### 4.5 Delivery semantics

- Ledger → outbox → EventBridge is transactional-outbox: no committed transition is ever unpublished, no uncommitted transition ever publishes. Relay lag is monitored with an alert threshold (target well under the fastest downstream cadence — Twenty projection is the tightest consumer, per the D8 heal-back seconds budget).
- Consumers are idempotent on `(subject_id, ledger_seq)` and tolerate reorder. Projections apply monotonically — a stale event for a subject already past that sequence is dropped, not applied.
- Backbone remains at-least-once. Exactly-once is achieved at the projection, not on the wire — the standard boring answer.

### 4.6 Two replay paths, one rule

- **Authoritative rebuild:** read the ledger. This is the only path that reconstructs truth, and the only path used for a projection bootstrap or a corruption recovery.
- **Convenience replay:** EventBridge archive replay, for re-driving a consumer that missed a window. Legal only when the consumer's idempotency makes the result identical to a ledger rebuild.
- The forbidden third path — treating the archive as the record — is prevented structurally: archive events carry `catalog_version` and `ledger_seq`, and any consumer state that cannot cite a ledger sequence fails the reconciliation sweep.

### 4.7 The adapted picture

```mermaid
flowchart TB
  subgraph SOR["Systems of record"]
    direction LR
    EXT["External SoRs<br/>Customer.io (consent) · Zendesk (case)"]
    ACT["Attributed actors<br/>humans · Twenty drag (D8) · resolution svc"]
    WH1["Warehouse authority<br/>verdict runner (I3)"]
  end
  subgraph PULSE_BOX["PULSE — the record"]
    CMD["Command API<br/>legality vs versioned catalog · SoR registry"]
    LED["Append-only ledger<br/>current state co-committed · ledger_seq"]
    OB["Outbox relay"]
  end
  subgraph OCEAN_BOX["packages/ocean — the feed (backbone code absorbed, role unchanged)"]
    EB["EventBridge bus + archive<br/>at-least-once · replayable · never authoritative"]
  end
  subgraph ODG["Projection layer (former ODG role — read-only)"]
    direction LR
    TW["Twenty"]
    CIO["Customer.io"]
    SF["Snowflake + Sigma"]
    TASKS["Derived tasks / work queues<br/>('tasks are derived' — unchanged)"]
  end
  NP["Non-subject fact producers<br/>(telemetry, activity — unchanged)"]
  EXT -->|"recorded, actor = system"| CMD
  ACT -->|"commands"| CMD
  WH1 -->|"verdicts declared w/ rule_version"| CMD
  CMD --> LED --> OB --> EB
  NP -->|"direct emit stays legal"| EB
  EB -.-> TW & CIO & SF & TASKS
  SF -->|"computes once"| WH1
  LED ==>|"authoritative rebuild only"| ODG
```

Solid arrows are writes and commands, dashed are feed consumption, the double arrow is the bootstrap/recovery path that only ever reads the ledger.

---

## 5. Trade-off analysis

- **Relay lag versus read isolation.** Option C accepts commit-to-publication lag to keep consumers off the transactional database. The lag is bounded, monitored, and already accounted for in the D8 heal-back budget. The alternative (Option B) trades a measured seconds-scale lag for an unmeasured operational coupling.
- **Two replay paths versus one.** Genuine added discipline cost. Mitigated structurally (§4.6) rather than by policy memo.
- **Producer migration friction versus doctrinal purity.** The producer policy (§4.4) is the only change that touches existing code. Scoping it by the catalog boundary keeps the blast radius to producers that were asserting patient state from side effects — which is precisely the population that needed to stop.
- **Superseding doctrine versus maintaining it.** With one application, a standalone OCEAN paper is a second doctrine document guaranteed to drift from the implementation. Superseding it (§7) and moving the code into the PULSE repo makes the implementation and its doctrine co-versioned — one repo, one CI, one place a reviewer looks.
- **Absorption cost versus org-transfer cost.** Absorbing the code via history-preserving import is strictly cheaper than the alternative for the ocean repo (org transfer + rob-repo factory-subset retrofit): the PULSE repo is born conformant by the rob-repo ritual, so the imported package inherits conformance instead of being retrofitted into it. One repo exits the personal-account remediation list without ever entering the retrofit queue.

---

## 6. Adaptation plan — phased, mapped to existing delivery sequence

| Phase | Aligns to | Work | Exit criterion |
|---|---|---|---|
| **0 — Absorption + contracts** | S0.1 repo scaffold (DNA-695) + S0.2 catalog machinery | PULSE repo scaffolded by rob-repo (birth ritual — never rerun on ocean). OCEAN code imported history-preserving (`git subtree add` or `git-filter-repo`, §6.1) as workspace package `packages/ocean`. Source repo archived read-only with a pointer here. OCEAN paper superseded (§7 notice as its final commit). Envelope extension schema emitted as a generated catalog surface. SoR registry fields added to catalog format | Package builds inside PULSE CI. Source repo archived. CI validates envelope ↔ catalog drift |
| **1 — Record** | S1.1 ledger schema | Ledger + outbox implemented per existing work order, emitting OCEAN-conformant envelopes onto the bus provisioned by `packages/ocean` IaC. Single-writer enforced at infrastructure (one service principal holds write) | A synthetic Referral transition round-trips: command → ledger → backbone → Snowflake landing, `ledger_seq` intact |
| **2 — Ingress** | S2 | Producer inventory: every existing OCEAN producer classified by the §4.4 test (repo verification item V6). State-asserting producers converted to ingress adapters. Customer.io consent ingress (D9) and Twenty drag webhook (D8) land here | Zero direct emits of catalog-state events, checked in CI against producer schemas |
| **3 — Projections** | S3 | Twenty, Customer.io, and Snowflake consumers cut to ledger-fed events. Projection fields marked read-only. Reconciliation sweeps live (warehouse referee) with corrections declared, actor = reconciliation | Reconciliation clean over one full cycle. Projections rebuild from ledger in a drill |
| **4 — Retirement** | S4 | Derived-state dbt models for PULSE-subject state either become verdict runners (declared per I3) or are deleted. ODG current-state answers for PRM redirect to projections | No warehouse model answers "what is this patient's status" by inference. Funnel counts read the ledger + verdict chain |

Synthetic Synthea data throughout until the C1 gate (executed BAA) clears, unchanged from the existing plan.

### 6.1 Repo-absorption mechanics

1. **Scaffold first.** PULSE repo is born via rob-repo (Python 3.12 uv-workspace monorepo, CI, pre-commit, ADR log, dark-factory readiness). Rob-repo is a birth ritual only — it never runs against the ocean repo.
2. **Import with history.** `git subtree add --prefix=packages/ocean <ocean-remote> main` (or `git-filter-repo` for a cleaner path rewrite if the ocean tree needs restructuring on the way in). History preservation is the audit posture: every backbone design decision keeps its commit trail inside the org boundary.
3. **Conform in place.** The imported package adopts the monorepo's ruff, pyright, and pytest-per-package configuration in a follow-up commit — conformance by inheritance, not retrofit. This ADR lands in the monorepo's ADR log as the absorption record.
4. **Archive the source.** `robford-brookai/ocean` goes read-only archived with a final README pointing at `packages/ocean` and this ADR. No org transfer needed — the code left the personal account by import. The doctrine of record for a HIPAA-scoped system now lives inside the org boundary.
5. **Name discipline.** OCEAN persists only as the package name for the distribution subsystem (relay, envelope schemas, archive/replay tooling, bus IaC). It is no longer a project, an initiative, or a doctrine. The architectural through-line simplifies to: TIDE = one identity key per patient, PULSE = truthful state for that key (with `packages/ocean` as its distribution subsystem), forecasting layer = predicts future state, Sigma/Ezra = surfaces it, Twenty = works it.

---

## 7. The OCEAN paper supersession notice — final commit to the source repo

An earlier revision drafted a carve-out amendment. Withdrawn — with PULSE as the sole application, the carve-out covers the whole surface, and pretending otherwise leaves a zombie doctrine document. The paper is superseded instead:

> **Superseded (2026-07).** This paper is superseded by the PULSE architecture (see `DNA-SPEC-DECLARED-STATE-PRM` and the absorption ADR in the PULSE repo). PULSE is OCEAN's only application, and its doctrine replaces the derivation doctrine written here: state is *declared into the ledger, not derived in the graph*. Transitions enter through the PULSE command API, which enforces transition legality at write time against a versioned state catalog and co-commits current state with each event in an append-only ledger. The event backbone described in this paper survives intact as PULSE's distribution subsystem (`packages/ocean`): at-least-once, replayable, many consumers, never authoritative — the feed from the record, not the record. Of the original motto, "tasks are derived" stands unchanged, and "events are facts" holds with a sharpened meaning: for catalog state, the ledger mints the fact. The Operational Data Graph concept collapses into PULSE's read-only projection layer. This repository is archived — code and history live at `packages/ocean` in the PULSE monorepo.

---

## 8. Consequences

**Easier:** funnel and cohort counts become ledger reads. Projection rebuilds become drills instead of incidents. Every status disagreement has an adjudicator by construction. Agent-actor attribution (the autonomy-ladder receipts) comes free on every transition. One fewer project name, one fewer repo in the personal account, one doctrine document instead of two, and the backbone code is co-versioned with the ledger that feeds it.

**Harder:** producers lose the freedom to assert state from side effects — deliberately. Two replay paths require the §4.6 discipline. The catalog becomes a harder dependency: envelope, registry, and producer classification all pin to its version. And the backbone loses its independent evolution path — a deliberate cost, since an independently evolving distribution layer with one consumer is coordination overhead purchasing nothing.

**Revisit when:** a genuinely non-PRM domain ever wants event distribution (extract `packages/ocean` back out then, with this ADR as the map — do not pre-build for it), EventBridge relay lag ever pressures the D8 heal-back budget, or the C1 gate clears and production PHI volume changes the outbox sizing math.

---

## 9. Repo verification checklist — assumptions made blind

The OCEAN repo (`robford-brookai/ocean`) is private and was not readable from this session. Every repo-specific claim above is an inference from the pinned doctrine and prior threads. Verify these ten before Phase 0:

| # | Assumption | Verifies against | If wrong |
|---|---|---|---|
| V1 | Repo contains the architecture paper (the amendment target) and it is the doctrine of record | README / docs tree | Amendment lands wherever doctrine actually lives |
| V2 | An envelope schema or event naming convention exists to extend | schemas/ or producer code | §4.2 becomes the v1 convention rather than an extension |
| V3 | EventBridge bus + archive are provisioned as infrastructure-as-code in this repo | IaC directory | Phase 1 outbox targets whatever provisions the bus |
| V4 | An ODG implementation exists (tables, graph store, or models) versus paper-only | repo tree | If paper-only, "repurpose" collapses to "projections are the first ODG" — simpler |
| V5 | Producer libraries or emit helpers exist that PULSE-subject producers currently use | libs/ | Producer policy enforced by convention + CI schema check instead of library change |
| V6 | An enumerable inventory of current producers touching patient state exists or is derivable | repo consumers/producers | Phase 2 starts with a discovery spike |
| V7 | No current-state tables are built directly off the bus (the event-store hazard is latent, not live) | consumer code | Any live instance becomes a named Phase 3 migration with a retirement date |
| V8 | Archive replay tooling exists and is idempotency-safe for the §4.6 convenience path | tooling | Convenience replay deferred, ledger rebuild is the only path initially |
| V9 | Envelope `detail-type` naming can carry catalog-generated types without breaking existing rules | EventBridge rules | Introduce a parallel detail-type family, migrate rules in Phase 3 |
| V10 | Repo lives in the personal `robford-brookai` account (like brook-status-reporter, ringer, tide-forecast) and exits via absorption, not org transfer | GitHub org | If already in brookai org, absorption proceeds identically — only the archive step changes owner |
| V11 | The ocean tree is importable as a single workspace package (self-contained, no path assumptions that fight the monorepo layout) | repo tree | `git-filter-repo` restructure on import instead of plain subtree add |

Absorption removes `ocean` from the org-transfer remediation batch entirely: the code enters the org by import into the born-conformant PULSE repo, and the source archives in place. The remaining personal-account repos (brook-status-reporter, ringer, tide-forecast) still take the transfer + retrofit path.

---

## 10. Action items

1. [ ] Reconcile §9 against the repo — paste `git ls-files` plus the paper/README into this thread, one revision pass follows
2. [ ] Tal: sign off Option C topology and the absorption decision (§2) — the record-versus-feed line and "one repo, one doctrine" are the two load-bearing sentences
3. [ ] Extend the DNA-695 (S0.1) work order with the §6.1 absorption steps — scaffold, subtree import to `packages/ocean`, conform-in-place commit, archive source with the §7 supersession notice as its final commit
4. [ ] Add SoR registry fields and envelope surface to the S0.2 catalog work order — no new project name, OCEAN is now a package name only
5. [ ] Fold §4 (contract + registry + producer policy) into `DNA-SPEC-DECLARED-STATE-PRM` at the PRD merge, adjacent to the object-model section
6. [ ] Queue the Phase 2 producer-inventory spike as a Linear work order once V5/V6 resolve
7. [ ] Strike `ocean` from the org-transfer remediation batch — it exits by absorption
