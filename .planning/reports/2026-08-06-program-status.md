# PULSE — Program Status Report

**Date:** 2026-08-06 · **Repo:** `robford-brookai/pulse` · **Main:** `d4845d5a`
**Reporting window:** 2026-08-03 → 2026-08-06 — Phase 1 archived and released, `s12-verdict-relay`
shipped its full lifecycle, and `s13-schedules`/`s14-identity` ran to near-completion.

---

## 1. Headline

**Phase 2 is in flight on two fronts: `s13-schedules` at 9/11, `s14-identity` at 5/11, both
converging on their wrap-up waves.** `s12-verdict-relay` closed its entire lifecycle since the
last report — 8/8 tasks, doc_update, archive — and the roadmap was refreshed to reflect it. Four
Phase 2 siblings (`catalog-authority`, `twenty-kanban-webhook-ingress`,
`customerio-consent-ingress`, `producer-ingress-policy`) remain gate-held on decisions D15–D18
and the export mechanism, unchanged from the prior report.

| Metric | Value |
|---|---|
| Commits on `main` | 415 total · 68 since the 2026-08-03 report's `3053dd8` pin |
| Merged PRs | **126** (up from 90) |
| Phase 0 (`ocean-eventbridge-migration`) | 56/56 — archived |
| Phase 1 (`pulse-ledger-core`, S1.1) | 16/16 — archived `2026-08-03-pulse-ledger-core`; v1.5 shipped |
| Phase 2 — `s12-verdict-relay` | ✅ **8/8, archived** `2026-08-05-s12-verdict-relay` |
| Phase 2 — `s13-schedules` | **9/11** — only 4.2 (dry-run) and 5.1 (infra schedule defs) open |
| Phase 2 — `s14-identity` | **5/11** — wave 3 (4.1–4.3 resolver/quarantine/service) and wave 4 (5.1–5.3) open |
| Open PRs | 0 |
| `task check` on `main` | green as of last local run; CI re-verification pending (§6) |
| Live worktrees | 5 (`s13-task-008/009/011`, `s14-task-005/006`) |
| Release ladder | v1.5 shipped; **v2.0 (Phase 2) — midterm, in progress** |

---

## 2. Phase crosswalk

| Phase | S-stages | Vehicle | State |
|---|---|---|---|
| 0 — Absorption | S0.1, S0.2 | `ocean-eventbridge-migration` | ✅ archived |
| 1 — Record | S1.1 | `pulse-ledger-core` | ✅ archived, v1.5 shipped |
| 2 — Ingress | S2, S1.2/S1.3/S1.4 | `s12-verdict-relay` ✅ archived; `s13-schedules` 9/11; `s14-identity` 5/11; four siblings gate-held | 🔵 active |
| 3 — Projections | S3 + M1 | `snowflake-projection`, `survey-engine-ingress`, … | queued |
| 4 — Retirement | S4 | `odg-read-redirect`, … | queued |

---

## 3. Progress since 2026-08-03

The 2026-08-03 report closed with Phase 1 at 14/16 and Demo 1 still mid-flight in an open
worktree. Since then:

| Then (2026-08-03) | Now (2026-08-06) |
|---|---|
| Phase 1 at 14/16, 5.2/5.3 outstanding | Phase 1 **16/16, archived**; v1.5 released |
| DNA-801 idempotency gap flagged as a known limitation | **Closed** — PR #104 wired the HTTP path to idempotent commit; stale "known gap" prose deleted from `docs/contracts/publishes.md` and `pulse_core/client.py` |
| Phase 2 siblings not yet proposed | **#105** proposed `s12-verdict-relay`, `s13-schedules`, `s14-identity` together, G_MECE-validated |
| — | `s12-verdict-relay` ran its **full lifecycle**: scaffold → mart reader → declarer → batch entrypoint → property tests → fixture corpus → runbook → mart contract doc (#106–#113), doc_update (#114), archived via #115 |
| Roadmap last updated pre-Phase-2 | **#116** refreshed `design/delivery/pulse-program-roadmap.md` — crosswalk, phase tables, release ladder now current as of s12 shipping |
| `s13-schedules`, `s14-identity` not yet dispatched | Both dispatched and executing: #117–#130 (scaffolds, month-open core, consent-sweep parser, normalization core, matcher, CLI, runbooks) |
| No PX / survey-engine contract entry | `docs/contracts/publishes.md` gained the **"Offered to PX survey engine"** section — event envelope + state catalog and the `s14-identity` matcher offered as stable/planned contracts ahead of `survey-engine-ingress` |
| No roadmap row for survey ingestion | Roadmap added the `survey-engine-ingress` row (early Phase 3, gated on Phase 2 exit + PX schema validation) |
| No standing kickoff/wrap-up procedure | `/change-kickoff` and `/change-wrapup` skills added — codify the propose→dispatch and collect→archive→cleanup tails that had been ad hoc |

Notable individual PRs in the window: #99 (archive `pulse-ledger-core`), #100 (release ladder),
#104 (DNA-801 fix), #105 (Phase 2 intake), #106–#115 (s12 full lifecycle), #116 (roadmap
refresh), #117–#130 (s13/s14 execution).

---

## 4. `s13-schedules` — 9/11

| Wave | Tasks | State |
|---|---|---|
| 0 — scaffold | 1.1 | ✅ (#117) |
| 1 — month-open | 2.1, 2.2, 2.3 | ✅ (#120, #122, #125) |
| 1 — consent sweep | 3.1, 3.2, 3.3 | ✅ (#119, #121, #126) |
| 2 — CLI and dry-run | 4.1 ✅ (#130), 4.2 open | 1 of 2 |
| 3 — infra and runbooks | 5.1 open, 5.2 ✅ (#129) | 1 of 2 |

Remaining: **4.2** (`--dry-run` on both subcommands, deps on 4.1 which is merged) and **5.1**
(`packages/schedules/infra/` schedule definitions, deps on 4.2). Both are unblocked in sequence —
4.2 can dispatch now, 5.1 follows.

Delivered so far: month-open enumerates active/on-hold enrollments through
`pulse_ledger.reads.enumerate_state` and declares `open_billing_episode` with D16 keys stable
within a billing month; consent sweep parses suppression-export CSVs and diffs against ledger
`CommunicationConsent` state with Customer.io as authority (D9), attributing corrections to actor
`reconciliation`; the CLI (#130) wires both jobs to a single exit-status contract. Runbooks
(#129) cover the missed-month-open procedure and the drift-spike/malformed-row triage.

---

## 5. `s14-identity` — 5/11

| Wave | Tasks | State |
|---|---|---|
| 0 — scaffold | 1.1 | ✅ (#118) |
| 1 — normalization and fixtures | 2.1, 2.2 | ✅ (#124, #123) |
| 2 — matcher core | 3.1, 3.2 | ✅ (#127, #128) |
| 3 — resolver and service | 4.1, 4.2, 4.3 | open |
| 4 — proof and documentation | 5.1, 5.2, 5.3 | open |

Delivered so far: `identity/normalize.py` (opus-modeled — a wrong composite is the
retrofit-expensive defect) with a documented v1 rule table and the PHI boundary (digest-only
public exit, no demographic holder survives past normalization); `identity/matcher.py`'s
two-tier deterministic match (exact identifier short-circuit, composite trichotomy
Mint/Match/Ambiguous, no scoring or thresholds); `identity/lookup.py`, the live adapter over
`pulse_ledger.identity.lookup_identifier`/`find_candidates` transmitting only the sha256 digest.

Remaining chain: **4.1** resolver (decisions → commands, D16 idempotency keys) → **4.2**
quarantine path (`resolution_hold` + pseudonymous queue row) → **4.3** service entrypoint
(composition root, `pulse_core.client.consume`) → **5.1** determinism property test → **5.2**
quarantine runbook + `docs/contracts/publishes.md` matcher registration → **5.3** verification
wrap. `handoffs/s14-identity/` cites 3.1's `identifier_conflict` proposal as an open spec-gap
flag for the doc_update pass to review, not auto-apply.

---

## 6. Operational notes

### GitHub Actions outage, 2026-08-06

Every CI run since roughly mid-afternoon 2026-08-06 sits `queued` with no `conclusion` —
confirmed on PR #130 (`quality`, `tests-and-type-check` ×4, `check-docs` all `QUEUED`) and via
`gh run list`, which shows a run of queued jobs stretching back through the s13/s14 merges.
githubstatus.com's other components report operational; this reads as an Actions-specific
outage, not a repo or workflow misconfiguration. Merges through this window (#125–#130)
proceeded on **local `task check` green plus the `main_access`/admin-merge precedent** already
established for #99 and #115 — not on a green CI run, since none has completed. CI
re-verification of this window's merges is pending Actions recovery; nothing merged carries an
unreviewed decision (all mechanical checkoffs or single-task PRs per the existing workflow
rules).

### Distinct from the DNA-801-era CI-queue false alarm

This is not the same failure class as the earlier `gh-actions-budget-zero` incident
(2026-08-04ish window): that one was a **$0 Actions spending budget** on the personal account
silently rejecting jobs before a runner started (jobs completed in 2–3s, `runner_id: 0`,
misleading "payment failed" error). Today's runs are genuinely `queued`, not instantly rejected
— consistent with a platform-side Actions outage rather than a billing block. Worth keeping the
two failure signatures separate: instant-fail-with-runner_id-0 means check billing budgets;
queued-and-stuck means check githubstatus.com before assuming a repo problem.

### s12's lost-handoffs lesson, now enforced

`s12-verdict-relay`'s worktrees were deleted before `task collect` ran, destroying HANDOFF.md
for tasks 1.1/2.1/4.1 (gitignored, unrecoverable) — only `handoffs/s12-verdict-relay/`'s
task-007 file survived. That incident is now encoded directly in the `change-wrapup` skill's
Phase 1: **"collect BEFORE any worktree is touched"**, with the s12 incident cited by name as
the reason. Applied today: harvest-before-delete ran for **11 worktrees** across the two active
changes — 7 files under `handoffs/s13-schedules/` (tasks 001–007) and 4 under
`handoffs/s14-identity/` (tasks 001–004) — before any of those worktrees were removed. Five
worktrees remain live (`s13-task-008/009/011`, `s14-task-005/006`) for the tasks still in
flight.

---

## 7. Open items needing a human decision

Unchanged from 2026-08-03's standing register, plus one addition surfaced by `s14-identity`'s
handoffs:

- **D4** catalog→Twenty generator (artifact vs live-apply)
- **D14** SPCS vs EKS
- **D15–D18** auth / idempotency / outbox / catalog SoR — recommended, close at exec session;
  gate `twenty-kanban-webhook-ingress` (D15) and `catalog-authority` (D18)
- **G-1/G-2/G-3** — historical closed objects, drift tolerance, per-family flip dates
- **BF-D1–BF-D4** — backfill horizon, evidence floors, genesis re-anchoring, Billy import
  semantics
- Five named roles still unconfirmed (quarantine reviewer, compliance owner, verdict steward,
  on-call, enablement lead)
- **New:** `s14-identity` task 3.1's handoff proposes an `identifier_conflict` decision type
  (a candidate lookup returning contradictory identifiers for the same system/value pair) that
  the spec did not name — flagged for the doc_update pass rather than implemented ad hoc; it is
  a design-drift flag, not yet a ruling.
- PX's stated June–July delivery target for `survey-engine-ingress` has already passed (it is
  now August); the roadmap flags re-verifying the timeline with Max Pengilly before sequencing
  anything against it. Unchanged caution from the refreshed roadmap, not new this window.

---

## 8. What's next

1. **Close `s13-schedules`.** Dispatch 4.2 (`--dry-run`, unblocked now that 4.1 is merged), then
   5.1 (infra schedule defs, deps on 4.2). Both remaining, no serial lane involved.
2. **Advance `s14-identity`'s wave 3→4 chain.** 4.1 (resolver) → 4.2 (quarantine) → 4.3 (service,
   the composition root) → 5.1 (determinism proof) → 5.2 (runbook + contract, `serial:
   openspec_main_specs`) → 5.3 (verification wrap). 5.2's serial tag means it cannot ship
   concurrently with another doc-updater-lane task.
3. **Wrap up both changes once their task lists close**: `task collect` (already ahead of
   schedule per §6) → doc_update, reviewing the `identifier_conflict` flag and any others
   surfaced in `handoffs/s13-schedules/` and `handoffs/s14-identity/` → `task verify` → G_DRIFT-
   gated archive → roadmap/contract refresh → dispatch the next changes.
4. **Take the four gate-held changes to the exec session.** `catalog-authority` (D18),
   `twenty-kanban-webhook-ingress` (D15), `customerio-consent-ingress` (export mechanism), and
   `producer-ingress-policy` (needs `catalog-authority` first) all need D15–D18 and the export-
   mechanism decision closed before they can be proposed. This is the same open item as
   2026-08-03's report — unchanged, now the main blocker to Phase 2's remaining sibling fan-out.
5. **Re-verify CI once GitHub Actions recovers.** Confirm the queued runs from #121–#130
   eventually post a real conclusion; if any comes back red, treat it the same as any other
   post-merge CI failure (redispatch, never hand-edit worktree output).

---

*Untracked working file under `.planning/reports/`. Follows the structure of
`.planning/reports/2026-08-03-program-status.md` for side-by-side comparison.*
