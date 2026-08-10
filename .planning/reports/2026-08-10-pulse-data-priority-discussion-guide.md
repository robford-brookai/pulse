# PULSE data priority — discussion guide, meeting 2026-08-10

Linear: DNA-900 · Prepared 2026-08-09 · Ground truth: `design/delivery/pulse-program-roadmap.md`, `design/migration/pulse-ledger-backfill-plan.md`, `openspec/changes/`

## TL;DR

Phase 2 (Ingress) shipped as v2.0 on 2026-08-08 — all seven changes archived, all four sanctioned command sources live. The program now faces three competing data queues: Phase 3 projections (forward read surfaces), genesis and cutover prerequisites, and backfill history (BF-5, eight grains). The recommendation: run BF-0b archaeology and `environment-matrix` in parallel this week, because each one prices a different queue — BF-0b's CDC-window finding sets the evidence ceiling for every backfill grain, and the Twenty dev instance gates all of Phase 3. Ratify the backfill grain order as written, take the 24-month horizon (BF-D1), and defer nothing else that has an owner in the room. Four registered decisions have owners attending and can close in this meeting: BF-D1 (Oren + Tal), BF-D2 (Ford + Luke), BF-D3 (Tal), BF-D4 (Ethan).

## 1.0 Where the program stands (as of 2026-08-09)

- v2.0 tagged 2026-08-08 on PR #187. Phase 2 complete: 7/7 changes archived between 2026-08-05 and 2026-08-08.
- Live command sources: kanban webhook, Customer.io consent ingress, identity service, verdict relay. The producer-ingress CI gate (no producer schema names a catalog state) is in `task check`.
- Open changes right now: `synthea-seed` (4/4 tasks executed, awaiting collect → verify → archive) and `bf0a-archaeology-access` (proposed, 0/2 tasks started).
- Next release rung: v3.0 — Projections. Gate: Twenty dev instance (`environment-matrix`) plus decision D4 (catalog→Twenty generator, artifact vs live-apply).

```
Phase 2 close:        v2.0, 2026-08-08, PR #187
Changes archived:     7/7 (2026-08-05 → 2026-08-08)
Open changes:         synthea-seed (4/4 executed), bf0a-archaeology-access (0/2)
Phase 3 gate:         Twenty dev instance + D4 — neither cleared
Backfill horizon rec: 24 months (two annual cohort cycles)
Estimated SPCS cost:  $175–350/month compute pool (2026-07-28 estimate)
```

## 2.0 The question this meeting answers

"Data priority" decomposes into three queues that compete for the same small team. They are not interchangeable — each delivers a different kind of metric truth.

| Queue | Delivers | Blocked on | First visible win |
|---|---|---|---|
| Phase 3 projections | Forward read surfaces — Twenty screens, Snowflake STG_EVENTS, Customer.io sync | Twenty dev instance, D4 | Ops sees live patient state in the CRM |
| Genesis + cutover | Stock metrics correct at cutover day one — one seed event per live subject | `synthea-seed` archive, quarantine-reviewer role, genesis adjudication rules | Funnel position counts trusted |
| Backfill history (BF-5) | Flow metrics — cohorts by start month, conversion, time-in-state | BF-0b evidence ceilings, BF-D1 horizon, BF-1/BF-2 identity | Board-grade cohort charts with a visible seam |

The scheduling insight from the backfill plan holds: cutover never waits on Stage 2 history. So the queues are parallel by design, and the meeting's job is to pick what the team touches first within each, not to rank the queues against each other.

## 3.0 Decisions to close in the room

### 3.1 Registered decisions with owners attending

| ID | Decision | Recommendation on the table | Owner |
|---|---|---|---|
| BF-D1 | Backfill horizon — how far back Stage 2 reaches | 24 months or the retention ceiling, whichever is shorter. Covers two annual cohort cycles. Frame for Oren: this is the complete-referral-record ask pointed backwards — guaranteed forward, best-effort with graded evidence backward | Oren + Tal |
| BF-D2 | Evidence floors per metric — the minimum evidence class a metric counts | Cohort and funnel marts count E0–E3 with class as a visible dimension. E4-only subjects count in stocks, not flows. Board charts annotate the seam | Ford + Luke |
| BF-D3 | Genesis re-anchoring vs quarantine-everything for illegal historical sequences | Genesis + gap facts. Quarantine reserved for current-state-unknowable | Tal |
| BF-D4 | Billy import semantics — historical billing-investigation results | Both: E0 facts (decided-then, actor `billy_import`) and recomputation (computed-now). The divergence between them is itself a data-quality finding | Ethan |

### 3.2 Grain priority — ratify or reorder

The backfill plan §5 orders the eight grains by metric value per unit of reconstruction effort. Proposed for ratification as-is:

| Priority | Grain | Expected evidence ceiling | Why this rank |
|---|---|---|---|
| 1 | Person + identifiers | E0–E1 | Root of the tree — nothing lands without a person key |
| 2 | Enrollment | E1–E3 | Cohorts are enrollments by start month. This grain is the headline metric |
| 3 | CommunicationConsent | E0 | Cleanest in the set — Customer.io keeps its own history. Early proving ground for the loader |
| 4 | Consent | E0–E2 | Audit value, and a funnel stage since G3 |
| 5 | Referral | E2–E3 | Pre-enrollment funnel — valuable, likely the lossiest |
| 6 | Intervention + time facts | E0–E1 | Feeds historical billing recomputation, append-only |
| 7 | Coverage, ProviderAffiliation, Contract | E0–E2 | Facts with periods, no state machines — low risk |
| 8 | Device | E1–E2 | Remote-monitoring only, bounded population |

One caveat to state aloud: the evidence-ceiling column is hypothesis until BF-0b reports. If the Mongo change-data-capture window turns out shallow, Enrollment drops from possible E0 to corroborated E1 via the satellite apps, and the cost of rank 2 rises. That is why BF-0b runs before any grain is elaborated.

### 3.3 Phase 3 sequencing — what unblocks the most

- `environment-matrix` is the single gate in front of all of Phase 3 (the Twenty dev instance) and it consumes `synthea-seed`, which is executed and one archive step from done. Propose it this week.
- D4 (catalog→Twenty generator: artifact vs live-apply) is Ford's call and gates `pulse-app-scaffold`, the first Phase 3 change. It can close in this meeting or by end of week.
- `snowflake-projection` and `customerio-projection` are gate-free once Phase 2 exited — they need no Twenty instance and can start ahead of the app scaffold if the team wants a Phase 3 change moving immediately.
- Caution on `survey-engine-ingress`: the PX dependency carries a stated June–July delivery target that has already passed. Re-verify with Max Pengilly before sequencing anything against it.

### 3.4 Roles and follow-ups that touch data priority

- Quarantine reviewer must be named before genesis P0 — genesis is on the critical path to every stock metric.
- Standing flags riding parent issues: program entry_gate/exclusivity fills owed by billing (DNA-862), board-vocabulary reconciliation and the patient×program grain question (DNA-872), mandatory idempotency-key tightening (DNA-801), SNOWFLAKE_* deploy secrets and database pin for `task catalog:release` (DNA-862).
- G-2 (drift tolerance per family, Ethan + Luke) is not urgent today but gates cutover P0 exit — worth a calendar owner now.

## 4.0 Recommended priority order

Assumption, flagged: team capacity stays at current level and no new external dependency lands this week.

1. Archive `synthea-seed` (mechanical — collect, verify, archive) and dispatch `bf0a-archaeology-access` (2 tasks, gate-free). Both are this-week items regardless of anything decided above.
2. Run BF-0b archaeology as soon as BF-0a merges and Mongo read-only credentials exist. Its CDC-window finding is the only result that can reprice the backfill plan, so it precedes any grain elaboration.
3. Propose `environment-matrix` to clear the Phase 3 gate, with D4 decided alongside.
4. Start `snowflake-projection` as the first Phase 3 change — gate-free, and it lands the warehouse read contract that reconciliation sweeps and the funnel marts build on.
5. Sequence BF-1/BF-2 (identity absorption and backfill run) behind the BF-0b report, in grain order.

## 5.0 Suggested agenda (60 minutes)

| Time | Item | Outcome |
|---|---|---|
| 0:00–0:05 | Phase 2 close and v2.0 recap | shared baseline |
| 0:05–0:20 | BF-D1 horizon + grain-order ratification | two closed decisions |
| 0:20–0:35 | BF-D2 floors, BF-D3 re-anchoring, BF-D4 Billy semantics | three closed decisions |
| 0:35–0:50 | Phase 3 sequencing, D4, PX timeline | first Phase 3 change picked |
| 0:50–1:00 | Roles (quarantine reviewer), standing flags, next check-in | owners named |

Pre-reads, in order of value: `design/migration/pulse-ledger-backfill-plan.md` §5 and §8, `design/delivery/pulse-program-roadmap.md` release ladder, `.planning/reports/2026-08-08-project-status.md`.
