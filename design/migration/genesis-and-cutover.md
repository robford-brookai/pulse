# Genesis and Cutover — section for `DNA-SPEC-DECLARED-STATE-PRM`

**Status:** Draft v0.1 for PRD fold — 2026-07-31 | **Author:** Ford | **Sign-off:** Tal
**Gate update folded in:** Snowflake Postgres is covered under the existing Snowflake Business Associate Agreement (BAA). The C1 gate is **cleared** — production Protected Health Information (PHI) may enter the Twenty database and the PULSE ledger. Synthea synthetic data remains the standard for dev and staging environments (see the environments plan), but it is no longer a production blocker.

---

## 0. TL;DR

The ledger needs a day zero. Every §5.2 state machine defines transitions, but thousands of existing patients hold in-flight referrals, active enrollments, granted consents, and open billing months in POCAR, Billy, and Customer.io today. Genesis is a one-time, warehouse-adjudicated declaration of initial state for every live object, written through the command API with actor = `migration` and full source provenance — never a bulk table load behind the API's back. Cutover is shadow-read first, then a single authoritative-write flip per object family, POCAR demoted to read-only mirror at the flip. Contradictions between source systems are resolved by versioned adjudication rules computed in the warehouse (the referee pattern), and unresolvable conflicts land in the quarantine review queue rather than silently picking a winner. Acceptance: after genesis, funnel and cohort reads over the ledger reproduce the current book of business within stated tolerances, and P1 handles all net-new referrals natively.

## 1. Genesis event design

- **One mechanism, no exceptions.** Initial states enter through the PULSE command API as `genesis` commands — a sanctioned command type that asserts a starting state without requiring a legal predecessor transition. Actor = `migration:<run_id>`, provenance = {source_system, source_key, extracted_at, adjudication_rule_version}. The single-writer rule holds on day zero exactly because day zero is when it is most tempting to break it.
- **Genesis is per-object, not per-patient.** Each live grain gets its own genesis event: Person (identity + ExternalIdentifiers), open Referrals, Consents in `granted`, CommunicationConsent recorded state from the Customer.io suppression export, active and on-hold Enrollments, the current month's open BillingEpisodes, Coverage facts, ProviderAffiliations, active Contracts. Historical closed objects do **not** get genesis events in v1 — history before day zero lives in the warehouse (Bronze/Silver), and the ledger's history begins at genesis. This is a declared scope cut, recorded in the register (G-1 below).
- **Trinary discipline applies at genesis.** A patient whose source state cannot be evaluated genesis-lands as `indeterminate(insufficient_data)` on the relevant verdict, not as a guessed state. Unknown and no stay distinct from the first event onward.

## 2. Adjudication — the referee rules

The warehouse computes a candidate initial state per object from all sources before any genesis command fires. Where sources agree, adjudication is trivial. Where they disagree, versioned rules decide:

| Conflict class | Rule (v1) |
|---|---|
| POCAR enrollment status vs Billy billing activity | Billing activity in the current or prior month wins for `active` — money is the strongest signal of service delivery |
| Consent recorded in POCAR, absent in document store | Genesis as `granted` only with evidence_ref present. Otherwise quarantine — consent is the most audited artifact and gets no benefit of the doubt |
| Customer.io suppression vs any other opt-in record | Customer.io wins unconditionally (D9 — it is the system of record) |
| Duplicate Person candidates across MRNs | Deterministic identity rules (S1.4) resolve. Ambiguous matches quarantine, and dependent objects' genesis defers until identity resolves |
| Contradiction not covered by a rule | Quarantine review queue, human disposition, disposition recorded as the rule for the next run |

Rules are versioned (`genesis_rule_version`), computed in dbt, and every genesis event carries the rule version that produced it — the same I3 posture as production verdicts. A re-run with amended rules produces a diff report, not silent mutation.

## 3. Cutover sequencing

| Phase | What happens | Exit criterion |
|---|---|---|
| **P0 — Shadow read** | Genesis runs into a production ledger. POCAR remains the operational system. Nightly reconciliation compares ledger state vs source state and reports drift | Drift < agreed tolerance for 10 consecutive business days, per object family |
| **P1 — New-intake flip** | All net-new referrals flow through the P1 pipeline into the ledger natively. Existing patients still update via a source-change relay (POCAR change events replayed as attributed commands, actor = `pocar-relay`) | 100% of new referrals ledger-native for one full billing month |
| **P2 — Authoritative flip, per family** | Care teams work Referral and Enrollment in Twenty. POCAR writes stop for the flipped family and POCAR becomes read-only for it. Flips are per object family, in order: Referral → Consent → Enrollment → BillingEpisode | Flip date declared per family, one calendar week apart minimum, rollback = re-enable the relay |
| **P3 — POCAR demotion** | POCAR read-only across the board, retained as a historical mirror until the strangler migration retires it | Zero POCAR writes for 30 days |

**No sustained dual-write.** The relay pattern (source events replayed as commands) replaces dual-writing — one authoritative writer per family at all times, which is the single-writer rule applied to the migration itself.

## 4. Acceptance

Genesis is done when: (a) every live object in the in-scope families has exactly one genesis event with provenance, (b) ledger-derived funnel counts match the warehouse's referee counts within tolerance (target: exact for Enrollment and BillingEpisode, ±1% for pre-enrollment funnel states pending G-2), (c) the quarantine queue is drained to zero or every remaining row has a named owner and a disposition date, and (d) a full genesis re-run against frozen source snapshots is byte-identical — determinism is the regression test.

## 5. Register additions

| ID | Decision | Status | Owner |
|---|---|---|---|
| G-1 | Historical closed objects excluded from genesis — pre-day-zero history is warehouse-only | Recommended | Tal |
| G-2 | Drift tolerance per object family for the shadow-read exit | Open — needs Ethan for billing, Luke for funnel | Ethan + Luke |
| G-3 | Per-family flip dates | Open — set after P0 exit | Ford + Tal |
| C1 | ~~Synthetic data until Snowflake Postgres BAA~~ **Cleared 2026-07-31** — Snowflake Postgres confirmed covered under the existing Snowflake BAA. Synthea remains the non-production standard | Resolved | Ford |
