# Declared Patient State × Enrollment Forecast — Gap Analysis & Week Plan

> **Author:** Rob Ford · **Date:** 2026-07-26 · **Status:** Working summary of the exec-thread gap analysis for the 2-part PRD (`DNA-SPEC-COHORT-FUNNEL-REQS` + `DNA-SPEC-DECLARED-STATE-PRM`) · **Audience:** Rob, Data team
> **Purpose:** Record what Oren's data-hygiene questions cover and miss in the PRD, the edits that close the gaps, the scoping decisions that need Oren/Tal ratification, the week's sequence, and the paste-ready thread reply. Nothing here changes build scope.

## 1.0 TL;DR

Tal's explicit ask — map Oren's three questions against the PRD — is the critical path, and the analysis is done. Q1 (record per referral name) is partial: the ledger design covers it but the funnel boundary reads post-qualification. Q2 (trace every action) is partial: transitions are fully captured, non-transition actions are not. Q3 (every change, timestamped, including EMR) is fully covered inside funnel scope but Oren's framing exceeds that scope. Four edits close all three gaps with zero change to build scope. Strategic asset: Oren independently argued the companion's §2.3 dependency claim — "fix the record first" *is* the Declared-State thesis — so the reply converts CEO attention into the prioritization Tal conditioned. Plan of record: post the coverage reply in-thread, book the 30-minute Oren/Tal session, fold the edits (half-day timebox), ship one merged PRD, and let the board pivot with Alex and Carin absorb remaining capacity.

## 2.0 Trigger — the exec thread

### 2.1 Oren's three questions (data hygiene)

1. Do we create a record for every single name received as referral (the QIE list)?
2. From that point on, do we trace every action taken on that record (outreach volume, outreach forms, BI investigation)?
3. Does every record contain every change thereafter, with timestamp — including EMR-sourced changes (provider, medication, condition) and everything Brook traces?

His test question: QIE entry to activation latency, by cohort. His conclusion: if the record is not well maintained, fixing it comes first.

### 2.2 Tal's three asks

1. Send the Ezra insights feedback.
2. Gap analysis: what of Oren's message is and is not in the Enrollment & Activation Projections spec (26-07-16).
3. Board pivot: work with Alex and Carin on care-team-change data depth. Be ready to shift planned work this week.

Tal's prioritization condition: one PRD covering Luke, Gregg, and Oren gets prioritized with the Data team. Committed share timing: this week.

## 3.0 Today-state answer

Honest answers to Oren's three, today: (1) partially, (2) no, (3) no. Patient state is inferred after the fact from Customer.io attributes, Billy rows, and timestamps across four systems. No system owns the record. This is the Enrichment-as-Record diagnosis verbatim — the companion spec exists because the answers are currently no. Oren's "fix the record first" is the companion §2.3 dependency claim in his own words.

## 4.0 Coverage map — Oren's questions vs the PRD

| Oren's question | PRD as written | Gap | Closing edit |
| --- | --- | --- | --- |
| 1. Record for every referral name (QIE list) | Ledger record per `patient_key × program` via the MPI crosswalk (S0), backfill included. Funnel boundary reads "cohort drop-in (Qualified / POP)" | Record opening not pinned to QIE list receipt. Raw names that never qualify or resolve are unaddressed | Open the record at referral receipt. Add `referral.received` as the first event type and a never-qualified exit state |
| 2. Trace every action (outreach volume, forms, BI touches) | Every transition carries actor, evidence, dual timestamps. The state-vs-action separation (companion §3) deliberately keeps actions out of the catalog | Attempts and touches that do not change state are not ledger content, yet Phase 2's attempt-band [FLAG]s require exactly that data | Add an `activity` event class: non-transition, no catalog validation, emitted by the same adapter. Converts attempt-band and pass-rate assumptions into measured priors (companion §6 already promises this) |
| 3. Every change thereafter, timestamped — incl. EMR (provider, medication, condition) | Fully covered for funnel lifecycle: append-only enforced at grant level, `occurred_at` vs `recorded_at`, `rule_version` stamping | Oren and Tal's "complete longitudinal patient record" is a superset of enrollment→activation. Clinical/EMR deltas and post-activation are explicit non-goals | Add an extension-path subsection: same ledger rails, wider event taxonomy, clinical events as a follow-on PRD. Get Oren to bless the sequencing explicitly or approval stalls on implied scope |

Oren's test question — QIE entry to activation, by cohort — is the cohort-tail money query in companion §4.1. Once the boundary edit lands, it answers his question exactly as phrased.

## 5.0 Edits before the share (all P0, zero scope change)

1. **Boundary.** Record opens at referral receipt. Touches PRD Funnel model row and the companion §4 cohort query's entry event.
2. **Event taxonomy.** Two classes: `transition` (catalog-validated) and `activity` (attempts, touches). Touches companion §4 and §5, plus one Deliverables row.
3. **Record-coverage guarantee.** Three sentences answering Oren's questions in order, appended to the companion §8 nudge paragraph: one record per name via the crosswalk, every transition and touch appended with dual timestamps, append-only enforced by the database.
4. **Non-goals forward pointer.** Clinical/EMR change events and post-activation history are the same mechanism with more event types, sequenced as a separate PRD on this foundation. This answers Tal's "right foundation" line directly.
5. **Execute the companion §7 merge map now.** The shared artifact must be one self-contained PRD covering Luke, Gregg, and Oren — Tal's prioritization condition.

## 6.0 Scoping decisions for the 30-minute Oren/Tal session

These are Oren's to ratify. Recommendations attached:

1. **Record-opening boundary.** Recommend QIE receipt for every raw name, including names that never resolve or qualify. Confirms Q1 by design.
2. **Activity-event granularity floor.** Recommend attempts and BI touches in the ledger. High-volume marketing telemetry (opens, clicks) stays in Customer.io analytics.
3. **Clinical/EMR extension sequencing.** Recommend acknowledged-in-PRD as an extension path, scoped as a separate follow-on PRD. This is the expectation-management core of the meeting — without explicit blessing, Q3 reads as in-scope and the PRD balloons or stalls.

## 7.0 Sequence (plan of record from the session)

1. **Day 1 (Mon 07-20).** Send Tal the Ezra insights feedback (his item 1, minutes to unblock). Post the coverage reply in-thread (§8.0). Send Oren and Tal a 30-minute invite for Tue/Wed — Oren asked for early-week scheduling.
2. **Tue–Wed.** Fold edits 1–5. Timebox to a half day total — the gap analysis is done, so the PRD critical path is short.
3. **Thu 07-23.** Share the merged PRD, closing Tal's "later this week" commitment.
4. **Remaining capacity.** Board pivot with Alex and Carin per Tal's third message. The Declared-State record story may feed the board narrative, but the explicit board ask is care-team dashboard depth — do not volunteer scope.

## 8.0 Draft thread reply (paste-ready)

> @oren ran your three questions against the PRD before Thursday's share. Straight answer on where we are today first: (1) partially, (2) no, (3) no. Patient state today is inferred after the fact from Customer.io attributes, Billy rows, and timestamps spread across four systems. No system owns the record. That inference gap is the root cause of the analysis-time problem you named, and the PRD's data-foundation layer exists to fix exactly that. Your "fix the record first" is the design thesis of the spec.
>
> What the PRD commits to, mapped to your three:
>
> **1. A record for every referral name.** Every name on the QIE list opens a ledger record at receipt, resolved to one patient identity through the patient crosswalk. Names that never qualify still exist and carry a tracked exit reason, queryable forever. I'm tightening the boundary language so record-at-receipt is explicit. The identity substrate is already proven — the lead-match rebuild moved resolution from ~7.5% to ~99.95%.
>
> **2. Every action traced.** Every stage transition is recorded with actor, evidence, and timestamp, append-only. I'm extending the event set to also capture actions that don't change stage — outreach attempts by channel, BI touches — so attempt counts are measured rather than reconstructed from side effects.
>
> **3. Every change thereafter, timestamped.** For the referral-to-activation lifecycle, yes: dual timestamps (when it happened vs when we learned it), append-only enforced at the database level, every rule version stamped. EMR-sourced clinical changes (provider, medication, condition) and post-activation history run on the same rails with additional event types. I've sequenced those as the follow-on workstream so this build stays shippable — the foundation is designed to carry them.
>
> Your example question — how long from QIE entry to activation, by cohort — is one of the three queries the ledger answers on day one.
>
> Three scoping calls are worth 30 minutes with you and Tal before I finalize: where the record opens, how granular the action trail goes, and sequencing of the clinical-record extension. Invite coming for Tue/Wed.

## 9.0 Open verification

- Confirm the ~7.5% → ~99.95% lead-match stat maps to the S0 crosswalk scope before it lands in front of Oren. It comes from the funnel identity-resolution rebuild (BRIDGE_CIO_LEAD / DIM_LEAD), so it should hold, but it is a CEO-facing number.
- Ezra insights feedback content: separate item, not covered in this summary.
