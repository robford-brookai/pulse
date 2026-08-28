# PULSE — Program Status Report

**Date:** 2026-08-25 · **Repo:** `robford-brookai/pulse` · **Main:** `f0439748`
**Reporting window:** 2026-08-08 → 2026-08-25 — v2.0 shipped at the window's open; since then
Phase 3 went from untouched to majority-shipped: the whole Twenty projection stack proven live,
the billing boundary stated and archived, the warehouse feed's death discovered and its revival
one operator task from done.

---

## 1. Headline

**Phase 3 (Projections) is past halfway and the live chain is real: command API → outbox →
relay → EventBridge → SQS → consumer → Twenty board, proven end to end on dev with nothing
synthetic in the path (receipts on GitHub issue #252).** Four changes closed this window
(`pulse-app-scaffold`, `twenty-dev-instance`, `twenty-projection`, `billing-source-boundary`),
`billing-state` sits at 9/10 with its approval long since given, and `snowflake-projection`'s
wave 1 merged today — only the operator revival task (2.1) stands between the ledger and a live
warehouse feed. The window also killed a broken process organ: G_APPROVAL now rides a
human-approved PR (WORKFLOW v2.0.7) after the Linear-comment ceremony silently swallowed four
approvals.

| Metric | Value |
|---|---|
| Commits on `main` | 758 total |
| Merged PRs | ~287 (up from ~186 at v2.0) |
| Phases 0–2 | ✅ archived; **v2.0 released 2026-08-08** |
| Phase 3 — `pulse-app-scaffold` | ✅ archived 2026-08-17 (DNA-918) |
| Phase 3 — `twenty-dev-instance` | ✅ archived 2026-08-18 (DNA-1019) |
| Phase 3 — `twenty-projection` | ✅ archived 2026-08-24 (#282, DNA-1138) — full live chain proven |
| Phase 3 — `billing-source-boundary` | ✅ archived 2026-08-24 (#280, DNA-1209) — same-day propose→archive |
| Phase 3 — `billing-state` | **9/10** — only 4.1 (live declare-back) open; blocker is external (dbt mart rows) |
| Phase 3 — `snowflake-projection` | **3/4** — wave 1 merged (#285–#287); 2.1 operator revival queued |
| Open PRs | 0 |
| `task check` on `main` | green (verified in fresh worktrees at every checkoff this window) |
| Live worktrees | 2 (`task-002-2`, `task-003-2` — spent, pending collect) |
| Release ladder | v2.0 shipped; **v3.0 (Phase 3 exit) in progress** |
| Workflow | **v2.0.7** — G_APPROVAL = human-approved PR (#283) |

---

## 2. Phase crosswalk

| Phase | S-stages | Vehicle | State |
|---|---|---|---|
| 0 — Absorption | S0.1, S0.2 | `ocean-eventbridge-migration` | ✅ archived |
| 1 — Record | S1.1 | `pulse-ledger-core` | ✅ archived, v1.5 |
| 2 — Ingress | S2 + S1.2/1.3/1.4 | seven changes | ✅ archived, **v2.0** |
| 3 — Projections | S3 + M1 | 4 archived · `billing-state` 9/10 · `snowflake-projection` 3/4 · 4 queued (`customerio-projection`, `survey-engine-ingress`, `reconciliation-sweeps`, `projection-rebuild-drill`, `m1-retire-patient-state`) | 🔵 active |
| 4 — Retirement | S4 | `dbt-derived-state-retirement`, `odg-read-redirect` | queued |
| Genesis/cutover | — | `genesis-adjudication-rules`, `genesis-seed-run`, `pocar-relay`, P0→P3 ladder | queued; calendar-bound tail (~3–4 months of operational proving once code ships) |

---

## 3. Progress since 2026-08-08

| Then (2026-08-08, v2.0) | Now (2026-08-25) |
|---|---|
| Phase 3 untouched; no Twenty instance | **Twenty stack shipped end to end**: app scaffold + catalog codegen (DNA-918), live dev instance v2.30.0 on EKS with proven kanban round trip (#223), ledger-fed projection with monotonic apply, echo suppression, heal-back (D8 closed) |
| No relay deployed; committed events reached no consumer | **`pulse-ledger-relay` live on dev01-brook** (#265/#266); `ocean` bus + projection rule/queue provisioned (DNA-1192 grants); demo3 rebuilt for the live-webhook world and green (#263) |
| Billing scope undocumented; cpt-om unknown to the repo | **`billing-source-boundary` proposed, executed, and archived in under 48h**: billing-computation-boundary + producer-registry in the baseline; cpt-om registered direction-both, declaring via command API (billing-state OQ3 answered); amount-free tripwires as CI tests |
| `billing-state` proposed | **9/10** — coverage subject (catalog v1.1.0), verdict→transition pairing, production wiring all merged; 4.1 live declare-back waits only on dbt mart verdict rows |
| `OCEAN_RAW.EVENTS` assumed live | **Discovered dead since 2026-03-18** (verified via Cortex metadata); `snowflake-projection` proposed same day — STG_EVENTS SQL + contract row + supersession note all merged (#285–#287), operator revival (2.1) next |
| G_APPROVAL = Linear comment | **v2.0.7: G_APPROVAL = human-approved PR** (#283) after four approvals were silently lost across two tickets |
| Work orders' `model:` field decorative | **Sticky-model defect found and fixed**: spawned workers inherited the last session's model (a Fable worker surfaced in the trees); every worker since launched with `--model` pinned; template fix filed and closed (repo-ade#4) |
| twenty-projection archive assumed done | **Found orphaned uncommitted for 3 days** (peer session died mid-step); completed and merged (#282) |
| Connector design specs untracked | Staged and merged (#281) after a worker fixed the credential-gate hit (illustrative `user:pass@` Mongo URIs) and, in passing, the repo-wide `git fetch` breakage (stray malformed ref file in the shared `.git`) |

Notable PRs: #263–#267 (twenty-projection close), #268/#273–#280 (billing-source-boundary full
lifecycle), #281 (connector specs), #282 (twenty-projection archive), #283 (workflow v2.0.7),
#284–#287 (snowflake-projection propose + wave 1).

---

## 4. `billing-state` — 9/10

All repo-lane work merged: coverage as the seventh ledger subject (catalog 1.1.0, Alembic
CHECK-widening), relay-side verdict→transition pairing (`transition_by_outcome`, D16-keyed pair
replay), production wiring, contracts, runbook. **Remaining: 4.1** — live declare-back on dev,
operator lane. Rob's G_APPROVAL has been on DNA-1158 since 2026-08-21 (under v2.0.7 the gate
reads as satisfied); the real blocker is **open question 2: the dbt mart must carry
`billing_eligibility` / `coverage_eligibility` / `benefits_verification` rows on the pinned
eight-column contract — work this repo cannot do.** OQ3 closed via billing-source-boundary.

## 5. `snowflake-projection` — 3/4

| Task | State |
|---|---|
| 1.1 STG_EVENTS view as committed SQL + offline/emitter-comparison tests | ✅ #285, checked off |
| 1.2 supersession note on the CDC events leg | ✅ #286 merged (checkoff pending) |
| 1.3 STG_EVENTS.EVENTS contract row + freshness query in publishes.md | ✅ #287 merged (checkoff pending) |
| 2.1 revive the feed: rule → queue+DLQ → warehouse-sync Duplo service; live proof; stamp `min_complete_from` | queued — operator lane; **gate = its execution PR** (v2.0.7) |

The contract carries an explicit completeness watermark: complete from revival forward; the
March–August gap closes via `projection-rebuild-drill`, deliberately not duplicated here. Wave 1
executed under Orca orchestration (run `run_9016da8afbea`) with sonnet workers, `worker_done`
lifecycle, and prompt-watch in all mode.

---

## 6. Operational notes

- **The approval-gate failure, in full.** Four `G_APPROVAL` comments were typed and lost — two
  on DNA-1158 (the gated issue; unseen for four days while sessions reported "waiting on Rob"),
  two on DNA-1128 (a Done cyad task; nothing listening). The free-text comment gate had no
  acknowledgment, no wrong-issue rejection, no effect. v2.0.7 makes the PR the gate surface.
- **Model stickiness.** The claude TUI persists the last-selected model per project directory;
  dispatch's printed spawn commands carried no `--model`, so workers inherited whatever the last
  closed session ran — including Fable. Workaround in force (CLI pin on every launch); root fix
  landed in the repo-ade template (issue #4, closed).
- **Prompt-delivery flakiness.** `orca terminal send` with multi-KB work orders truncated twice
  on the same worker (identical fragment both times); file-based delivery (drop `WORKORDER.md`
  in the worktree, send a one-line pointer) is the reliable shape and should become the
  dispatch default alongside the model pin.
- **Shared-`.git` corruption.** A stray malformed ref file (`refs/remotes/origin/main (1)`)
  broke `git fetch` for every worktree; found and removed by the PR-#281 fix worker. Same
  session class also produced the twenty-projection orphaned archive — with concurrent
  orchestrator sessions, re-verify repo state before every action remains the standing rule.
- **Write amplification in the projection loop** (from the 4.2 receipt): a projection write that
  differs from the record fires Twenty's webhook and commits a new event; echo suppression
  catches only the equal-state case. Converges by construction, but on a large backfill it will
  be loud. Owns no task yet — natural home is `projection-rebuild-drill`.
- **HANDOFF fragility again.** Wave-1 billing-source-boundary worktrees were deleted before
  collect; orchestrator-side backups saved all three (and are now taken routinely at each
  merge). The durable fix — tracked HANDOFFs or per-task collect — still has no owner.

---

## 7. Open items needing a human decision

- **`Contract.terms.economics_model` placement** — stays in PULSE or moves out with cpt-om;
  gates D6. Deliberately undecided in billing-source-boundary; deciders named in the D6 record.
- **dbt mart verdict rows** (billing-state OQ2) — external work, the only blocker on 4.1.
- **Warehouse modeling ownership** — ocean's dbt models live in `brookai/streamline`; pulse now
  ships committed SQL of its own; no rule says which repo owns the warehouse contract beyond
  per-object publishes.md rows. Surfaced by the 2026-08-25 inventory
  (`.planning/reports/2026-08-25-pulse-streamline-ocean-inventory.md`).
- **PX timeline** for `survey-engine-ingress` — stated June–July delivery already passed;
  re-verify with Max Pengilly before sequencing (unchanged caution, now two reports old).
- **`environment-matrix` and `observability`** — both prerequisite to the cutover ladder
  (staging leg, monitors + paging before P1/P2); neither started.
- **Quarantine-reviewer role** and the other named roles — still unfilled.

---

## 8. What's next

1. **Check off snowflake-projection 1.2/1.3** (merged today) and author **2.1's execution PR**:
   warehouse-sync Duplo service JSON, rule/queue/DLQ provisioning, runbook with per-step
   pass/fail assertions. One human approval on that PR releases the revival; the live proof
   stamps `min_complete_from` and the receipt lands on the tracking issue.
2. **Close snowflake-projection**: collect → doc_update → verify → archive. That unblocks
   `reconciliation-sweeps` and supplies `survey-engine-ingress`'s gate metric.
3. **Land billing-state 4.1** the moment the dbt mart rows exist — everything else is staged.
4. **Pick the next fan-out**: `projection-rebuild-drill` (carries Demo 3 + the natural home for
   the write-amplification fix and the warehouse backfill) and `m1-retire-patient-state` are
   both gate-open; `customerio-projection` is gate-open with no dependents waiting.
5. **Template hygiene**: pull repo-ade's dispatch fix down via `task template:diff`/`sync` and
   verify the emitted spawn commands pin models and deliver prompts by file; retire the manual
   workarounds.

---

*Untracked working file under `.planning/reports/`. Follows the structure of
`2026-08-06-program-status.md` for side-by-side comparison.*
