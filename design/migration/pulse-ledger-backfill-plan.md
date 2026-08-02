# PULSE Ledger Backfill — Plan

**Status:** Draft v0.2 — two-stage shape approved (Ford, 07-31), Mongo retention confirmed deep, BF-0 reframed from retention inventory to transition-evidence archaeology | **Deciders:** Ford (author), Tal (sign-off), Ethan (BF-4), Oren (BF-1 horizon)
**Scope:** Reconstructing pre-cutover patient-relationship history into the PULSE ledger so funnel, cohort, and forecasting metrics are meaningful at or shortly after launch, without violating the ban on inferred state. Covers the TIDE→PULSE repo consolidation as it bears on identity backfill.
**Depends on:** `rpc-object-model-assessment.md` v0.7 (catalog, invariants I1–I9, verdict chain), the OCEAN absorption batch (monorepo exists), C1 gate status.

---

## 0. TL;DR

Backfill looks like a doctrinal contradiction — the ledger bans inferred state, and backfill is nothing but inference over side effects in the eleven systems. It is not a contradiction, because I3 already resolved it: **inference is permitted when its output is computed in exactly one place and declared with provenance.** Backfill is a derived verdict about history. It runs as versioned reconstruction rules in the warehouse authority, emits candidate event streams per subject, and commits them through the command API with actor = `backfill:{rule_version}`, evidence lineage to Bronze source rows, and an evidence-class grade on every event. The anti-pattern was never inference — it was scattered, unattributed, read-time reconstruction. Backfill is centralized, attributed, write-once reconstruction. Same move as billability.

**Recommendation: two-stage backfill, decoupled from cutover.** Stage 1 (**Seed**) declares current state as of cutover time T for the whole live population — genesis events, one per open subject, required before forward operation starts. This makes stock metrics (active enrollments, funnel position counts) correct on day one. Stage 2 (**History**) reconstructs pre-T transitions grain by grain behind the seam, landing cohort and flow metrics as it completes. Cutover never waits on Stage 2. Verdicts are not backfilled at all — they are recomputed as-of historical months by the existing engine, which is what I3's re-runnable design was for.

The ledger goes bitemporal to hold this honestly: `effective_at` (when it happened) vs `recorded_at` (when the ledger learned it). Every mart carries an epoch dimension (declared vs reconstructed) and a minimum evidence class, so a cohort chart shows the seam instead of hiding it. TIDE's matcher absorbs into the monorepo and runs first — no event can land without a resolved person key, so identity backfill is the root of the dependency tree. Five decisions are registered (BF-1–BF-5), one of which — the backfill horizon — is Oren's, and it is the same question as his complete-referral-record ask pointed backwards in time.

---

## 1. The doctrinal move: backfill is derived-then-declared

The ban ("declared, not inferred") was always a ban on a *pattern*, stated precisely in I3: scattered, unattributed, read-time reconstruction. Backfill inverts every property of that pattern:

| Property | Enrichment-as-Record (banned) | Backfill (sanctioned) |
|---|---|---|
| Where inference runs | Every consumer, independently | One place — warehouse authority (dbt) |
| When it runs | At read time, forever | At write time, once per rule_version |
| Attribution | None — the inference is invisible | actor = `backfill:{rule_version}`, input lineage per event |
| Reproducibility | Two analysts, two answers | Deterministic re-run from Bronze, versioned |
| Fidelity honesty | Unknown and no conflated | Evidence class graded per event, indeterminate is countable |

So the rule that governs backfill is the rule that governs billability: **computed once, declared with provenance, never re-derived downstream.** Once the reconstructed events are in the ledger, consumers read the ledger. The eleven systems are demoted from "places state lives" to "evidence exhibits" — which is exactly the end state the whole program wants, applied retroactively.

Two invariant amendments make this airtight rather than hand-waved:

- **I3 addendum:** reconstruction of historical transitions is a species of derived verdict whose subject is the past. It obeys every I3 requirement (single computation home, rule_version, lineage, declared to the ledger).
- **I10 (new) — Bitemporal honesty.** Every ledger event carries `effective_at` and `recorded_at`. Forward-declared events have the two nearly equal. Backfilled events have `recorded_at` = load time and `effective_at` in the past. No consumer may treat `recorded_at` as when something happened. This is also what makes the ledger correct about late-arriving forward corrections, so it earns its place independent of backfill.

## 2. Naming: the ledger supersedes TIDE

The TIDE repo merges into the PULSE monorepo (mirror of the OCEAN absorption — same OCN-0→7 shape, second execution of the playbook). With that merge, **TIDE retires as a name.** What was "the TIDE key" is the **person key**, minted and merged by the identity resolution subsystem, which lives as `packages/identity` in the monorepo. This closes one more entry on the naming-proliferation list: TIDE = one key per patient collapses into "PULSE owns identity," and the through-line simplifies to PULSE = truthful identity and state, forecasting predicts it, Sigma surfaces it, Twenty works it.

One migration consequence: every existing document reference to "TIDE key" resolves to "person key" at next revision. No data migration — the key itself is unchanged, only its name and its home repo.

## 3. Evidence classes: grading what history can prove

Reconstructed events are not all equal, and pretending they are would rebuild the conflation §3 of the object-model doc exists to kill (unknown ≠ no). Every backfilled event carries one evidence class:

| Class | Meaning | Example | effective_at treatment |
|---|---|---|---|
| **E0 — Direct** | Source system recorded the transition itself, with timestamp | Customer.io consent event export, Billy verdict rows, POCAR status-change audit rows if they exist | Source timestamp, taken as true |
| **E1 — Corroborated** | Two or more systems independently imply the same transition | Enrollment start implied by both a Billy episode opening and a Customer.io segment entry within the same week | Earliest corroborating timestamp |
| **E2 — Single-source inferred** | One system's side effect implies the transition | Patient appears in an outreach campaign, therefore was cleared at some prior point | Side-effect timestamp, flagged inferred |
| **E3 — Interpolated** | State observed at two points, transition placed inside the interval | Active in a January snapshot, ended in a March snapshot, transition somewhere between | Interval end (conservative), interval bounds recorded on the event |
| **E4 — Genesis** | Subject exists in a state with no reconstructable path to it | Long-tenured enrollment predating every retained export | Synthetic `backfill_genesis(state, as_of)` event, an explicitly declared gap |

E3's convention (interval end) is deliberate: it biases cohort assignment *later*, which understates tenure rather than fabricating precision. E4 is the honesty valve — a genesis event is the ledger saying "history begins here for this subject," which is infinitely better than a fabricated transition chain. Marts can filter or annotate by minimum evidence class per metric (BF-2 pins the floors).

## 4. The legality problem

The command API validates transition legality against the catalog, and real history will contain sequences the catalog forbids — states that no longer exist, transitions the old systems permitted, subjects that teleport because the evidence has holes. Three responses were considered:

- **Relax legality in backfill mode.** Rejected. It poisons the one guarantee the ledger makes and means the reconstructed era obeys weaker semantics than the declared era, silently.
- **Quarantine every illegal sequence for human review.** Correct posture, wrong as the *only* mechanism — the volume could be the whole tail of the population.
- **Genesis re-anchoring plus quarantine (recommended).** When a subject's reconstructed sequence fails to parse as a legal path, the loader truncates to the longest legal suffix, opens it with a `backfill_genesis` event at the last confidently known state, and records the discarded prefix as a `reconstruction_gap` fact with the evidence that could not be sequenced. Subjects whose *current* state cannot be established even at E3 go to the quarantine review queue — same posture as Gate B, human adjudication, countable while pending.

The command API therefore gets a **bulk backfill mode**: same endpoint family, same legality validation, same single-writer guarantee, plus genesis and gap event types that only the backfill actor may emit. Single-writer doctrine holds — backfill is not a second write path, it is the first write path fed by a batch producer.

## 5. Two stages, and why cutover waits for neither history nor perfection

**Stage 1 — Seed (blocks cutover).** As of cutover time T, declare the current state of every live subject: one genesis-or-better event per open Referral, Consent, Enrollment, BillingEpisode, Device, Contract, plus person keys and identifier sets for the full population. Evidence bar: E2 or better for the *state*, E4 acceptable for the *path*. This is small, bounded, and reconcilable — the seed's states must match what the operational systems say at T, verified by the warehouse-as-referee before forward traffic starts. Deliverable of Stage 1: stock metrics correct on day one.

**Stage 2 — History (lands behind the seam).** Reconstruct pre-T transitions per grain, deepest-value-first, each grain shipping independently as its rules mature. Deliverable: flow metrics — cohorts by enrollment start month, conversion rates, time-in-state distributions — with the epoch dimension marking them reconstructed.

The decoupling is the schedule insurance: "metrics meaningful soon" decomposes into "stock metrics at T+0" (cheap, certain) and "cohort history at T+n weeks per grain" (parallel, incremental). If a grain's reconstruction proves ugly, it delays that grain's history, not the launch and not the other grains.

### The Mongo reframe: retention is confirmed, the question is transition evidence

POCAR's Mongo goes back years and is the operational heart — the satellite apps (Billy and PAP on Postgres, ExDash, the MySQL holdout) exist precisely because nobody could build atop it, so every team built a side ledger against its data. Two consequences:

1. **The retention risk dissolves and an interpretability risk replaces it.** "Data goes way far back" and "transition history exists" are different claims. If POCAR overwrote status fields in place — the default Mongo pattern absent deliberate audit collections — then deep retention yields old *records*, not old *transitions*: creations land at E0 off document timestamps, but the path each record took is E2–E3, reconstructed by corroboration. BF-0's central question is therefore: does Mongo journal transitions anywhere (audit collections, versioned documents, status-change subdocuments, oplog depth), or is it a current-state store with a long memory for rows?
2. **The satellite apps invert from liability to evidence.** Each side ledger recorded its slice of the patient journey with its own timestamps — Billy's episodes and time entries, PAP's intake events, ExDash's snapshots. The sprawl that motivated PULSE is also the corroboration corpus that makes E1 reconstruction possible where Mongo only holds end states. The apps are deposed as records and re-hired as witnesses.

Extraction path note: one-time bulk export (mongodump → S3 → Snowflake Bronze), not the Atlas Data API (EOL September 2025) and not the Triggers/EventBridge anti-corruption layer — that pattern is for forward sync, not batch archaeology.

### Grain priority and source evidence map

Ordered by metric value per unit of reconstruction effort. The source column is the hypothesis to verify in BF-0 — it is an inventory task, not settled fact.

| Priority | Grain | Primary evidence sources (hypothesis) | Expected ceiling | Why this rank |
|---|---|---|---|---|
| 1 | Person + identifiers | All eleven systems' identifier sets, POCAR/PAP demographics | E0–E1 | Root of the tree — nothing lands without a person key |
| 2 | Enrollment | POCAR status history (Mongo — audit collections or oplog retention permitting), Billy episode records, Customer.io segment history | E1–E3 | Cohorts = enrollments by start month. This grain *is* the headline metric |
| 3 | CommunicationConsent | Customer.io export | E0 | Cleanest backfill in the set — the SoR keeps its own history (D9), the ledger just records it retroactively. Do it early as the loader's proving ground |
| 4 | Consent | POCAR consent records, document/recording pointers | E0–E2 | Audit value, and G3 made it a funnel stage |
| 5 | Referral | PAP intake records, POCAR referral rows | E2–E3 | Pre-enrollment funnel history — valuable, likely the lossiest. Oren's complete-record ask applies forward first, backward best-effort (BF-1) |
| 6 | Intervention + time facts | Billy time entries, call logs | E0–E1 | Feeds historical BillingEpisode recomputation, append-only so trivially loadable |
| 7 | Coverage, ProviderAffiliation, Contract | Billy eligibility data, rosters, executed contracts | E0–E2 | Facts with periods, no state machines to sequence — low sequencing risk, load when sources are staged |
| 8 | Device | Fulfillment vendor exports | E1–E2 | RPM-only, bounded population |

**Not backfilled at all: the verdict chain and BillingEpisode qualification.** Verdicts are re-runnable by design — once facts and enrollment history exist, the engine recomputes qualification, eligibility, and billability as-of each historical month under a `backfill` rule_version. The one exception is Billy's historical manual BI results, which are facts about what Billy concluded at the time and load as E0 verdict events with actor = `billy_import` — preserving what was decided then, distinct from what the rules would say now. That distinction (decided-then vs computed-now) is itself analytically valuable and comes free from the actor field.

## 6. Reconciliation: the seam must balance

Three referee checks, all warehouse-side, all blocking their respective gates:

1. **Seed reconciliation (blocks cutover).** State-at-T per the seed events = state-at-T per each operational system, per subject. Mismatches are quarantined or resolved before forward traffic.
2. **Seam continuity (blocks Stage 2 grain sign-off).** For every subject, the last reconstructed pre-T state must equal the seed state, or the gap must be an explicit `reconstruction_gap`. No silent teleports across the seam.
3. **Aggregate sanity (blocks metric release per grain).** Reconstructed monthly counts vs whatever trusted historicals exist (Billy episode counts, prior board-deck numbers). Deviations documented, not massaged — where the reconstruction disagrees with a legacy count, the disagreement is a finding about the legacy count as often as about the reconstruction.

## 7. Execution: batch BF-0…BF-6, dispatched per WORKFLOW v2

Execution mechanism updated for the ADE stack (WORKFLOW.md v2): repo work ships as OpenSpec changes dispatched into Orca worktrees per the repo-ade template, prod-data work runs in the operational-discovery lane (controlled sessions, outside Orca until G_HARDENING), and diff-less irreversible actions run as operator runbooks in the destructive-ops lane with G_APPROVAL. Linear keeps the receipts: one parent issue per change, sub-issues per task, approval comments on the sub-issue. Lane assignment per order:

| Order | Lane |
|---|---|
| BF-0a (access package) | repo_change — OpenSpec change, Orca dispatch |
| BF-0b (Mongo archaeology) | operational_discovery — controlled session, report to sub-issue |
| BF-1 (TIDE absorption) | destructive_ops for the git surgery, repo_change for the conformance step |
| BF-2 (identity backfill run) | operational_discovery + G_APPROVAL — committed ledger writes |
| BF-3 (loader + bulk mode) | repo_change — pure code, the cleanest Orca candidate in the batch |
| BF-4 (seed run) | operational + G_APPROVAL + C1 — Synthea rehearsal unconstrained, production gated |
| BF-5 (history, per grain) | split — dbt reconstruction rules are repo_change, committed loads are operational + G_APPROVAL |
| BF-6 (epoch wiring, marts) | repo_change |

| Order | Does | Gate |
|---|---|---|
| **BF-0** | Split per approved execution model: **BF-0a** builds the read-only access package in the PULSE repo (connection pattern inherited from STREAMLINE, auth as secret references only), **BF-0b** runs the Mongo archaeology — inventory, journaling census, **CDC trace** (mechanism, sink, coverage window, gaps — CDC confirmed to exist, its window is the E0 era for Enrollment), evidence-ceiling table per grain. **BF-0c** (satellite stores) blocked on remaining interview items. Elaborated in `bf0-mongo-archaeology-agent-batch.md` | BF-0a: CI + PR review. BF-0b: report review — the CDC window prices Stage 2 |
| **BF-1** | TIDE repo absorption into `packages/identity` (OCN-0→7 pattern rerun: freeze, hygiene scan, scrub, import, conform, archive) | Same gates as OCEAN batch |
| **BF-2** | Identity backfill: resolve full historical population to person keys, merge ledger seeded, identifier sets loaded | Review — match-rate report |
| **BF-3** | Loader + bulk mode: command API backfill endpoints, genesis/gap event types, evidence-class schema, bitemporal columns (I10) | CI |
| **BF-4** | **Seed run** — dress rehearsal on Synthea first, then production population. Seed reconciliation check | **Approval comment before production run. C1 gate: production seed loads PHI into the ledger — blocked until the Snowflake Postgres BAA is executed** |
| **BF-5** | History reconstruction, one sub-order per grain in §5 priority order, each with dbt rules, dry-run parse-rate report, seam continuity check, committed load | Per-grain review — parse rate and quarantine volume |
| **BF-6** | Epoch wiring in marts, evidence-class floors applied per BF-2 decision, aggregate sanity report, metric release notes | Review — this is the "metrics are now meaningful" receipt |

BF-4 is the cutover dependency. BF-5 orders run behind it indefinitely without blocking anything.

## 8. Decision register (this plan)

Numbered BF-n to stay disjoint from the object-model register. Fold into Linear alongside D1–D13 when connector writes clear.

| ID | Decision | Recommendation | Owner |
|---|---|---|---|
| BF-1 | **Backfill horizon** — how far back Stage 2 reaches. Cost scales with depth, fidelity decays with it, and BF-0's retention findings set the hard ceiling | 24 months or retention ceiling, whichever is shorter — covers two annual cohort cycles for the board narrative. Frame to Oren as his complete-referral-record ask applied backwards: forward it is guaranteed by design, backwards it is best-effort with graded evidence | Oren + Tal |
| BF-2 | **Evidence floors per metric** — minimum class a metric counts. Cohort headline at ≤E3? Board metrics at ≤E1? | Cohort and funnel marts count E0–E3 with class as a visible dimension, exclude E4-only subjects from flow metrics (they still count in stocks). Board-facing charts annotate the seam | Ford + Luke (cut-by vocabulary) |
| BF-3 | **Genesis re-anchoring convention** (§4) vs quarantine-everything | Genesis + gap facts, quarantine reserved for current-state-unknowable | Tal |
| BF-4 | **Billy import semantics** — historical BI results as E0 facts (decided-then) vs recomputation only (computed-now) | Both, distinguished by actor — the divergence between them is itself a data-quality finding | Ethan |
| BF-5 | **I10 bitemporal columns** — ledger schema change, touches S1.1 | Adopt in S1.1 before any data lands. Retrofitting bitemporality is the single most expensive schema regret available to us | Ford, fold into S1.1 work order |

## 9. Assumptions and non-goals

**Assumptions (flagged):**

- POCAR's Mongo retention is deep (confirmed 07-31). The open question is transition evidence: whether status changes were journaled or overwritten in place. If overwritten, Enrollment transitions reconstruct at E1 via satellite-app corroboration rather than E0 from Mongo directly — BF-0 settles which.
- BF-1 horizon ceiling is no longer retention-bound. The 24-month recommendation stands on cost/value grounds alone and can extend cheaply if the evidence supports it.
- Customer.io's export surfaces full consent and campaign history, not just current suppression state.
- C1 gate (executed Snowflake Postgres BAA) governs BF-4's production run, exactly as it governs forward PHI. Synthea rehearsals proceed regardless.
- S1.1 (ledger schema) has not shipped — BF-5's I10 columns can land in the original schema rather than as a migration.

**Non-goals:**

- Backfilling telemetry into anything but the warehouse (I8 holds retroactively — historical readings go to Bronze, never near the CRM).
- Reconstructing history for clinics offboarded before the horizon.
- Perfect pre-T funnels. The reconstructed era is honestly graded, visibly seamed, and better than every alternative, which is the standard — not parity with the declared era.

## 10. Next action

Approve the two-stage shape and the I3/I10 doctrinal amendments, then BF-0 ships first — the retention inventory is the only order whose findings can reprice the plan, so it runs before anything else is elaborated to full work-order format. BF-5 for BF-1 (TIDE absorption) can be generated mechanically from the OCEAN batch once approved.

---

## Change log

**v0.4 (2026-08-01):** Drift correction against WORKFLOW.md v2 — §7 execution reframed from Open Engine orders to lane-mapped dispatch (repo_change via OpenSpec/Orca, operational_discovery for prod reads and committed loads, destructive_ops for git surgery), with per-order lane assignments. Dependency on DNA-695 superseded by the repo-ade bootstrap. No changes to doctrine, stages, evidence classes, or the register.

**v0.3 (2026-07-31):** BF-0 interview partially answered — CDC confirmed on the Mongo cluster (the transition-evidence question upgrades from "does journaling exist" to "what is CDC's coverage window"), execution model (c) confirmed with STREAMLINE as the connection-pattern source and PULSE repo as the auth home. BF-0 split into BF-0a (access package, PR) / BF-0b (archaeology report, read-only) / BF-0c (satellite stores, blocked on interview items 3–8, 10), elaborated to work-order format in `bf0-mongo-archaeology-agent-batch.md`.

**v0.2 (2026-07-31):** Two-stage shape approved by Ford. Mongo retention confirmed deep — BF-0 reframed from retention inventory to transition-evidence archaeology (journaled vs overwritten-in-place), satellite apps repositioned as corroboration corpus (deposed as records, re-hired as witnesses), bulk-export extraction path pinned (mongodump, not the EOL'd Atlas Data API), BF-1 horizon decoupled from retention.

**v0.1 (2026-07-31):** Initial plan. Derived-then-declared framing for reconstruction, evidence classes E0–E4, bitemporal invariant I10 proposed, two-stage seed/history design with cutover decoupling, genesis re-anchoring for legality failures, BF-0…BF-6 batch sketch, register BF-1–BF-5.
