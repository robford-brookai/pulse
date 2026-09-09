# PULSE — Program Status Report

**Date:** 2026-09-08 · **Repo:** `robford-brookai/pulse` · **Main:** `cd376aa`
**Reporting window:** 2026-08-30 → 2026-09-08. Two arcs: the connector seam cut, the billing
connector and Demo 5 (08-30 → 09-02), then a four-day developer-experience loop (09-02 → 09-05).
Nothing has merged to `main` since 2026-09-05.

---

## TL;DR

**Demo 5 ran live on dev on 2026-09-02 and every stage passed.** One synthetic patient walked
through identity resolution, consent ingress, a signed board drag, a declared verdict, three read
windows that agreed with the ledger, and a destroy-and-rebuild of the Twenty projection with zero
differences. That closes the roadmap's rebuild-drill promise and the first of Phase 3's three exit
criteria. The connector kit shipped and archived. The billing connector is 9 of 13 tasks in and
stops at the reconciliation sweep, which needs dbt spike files that `data-platform` has not
committed. That commit is the critical path to billing cutover.

The last four days of the window went to a developer-experience (DevEx) loop: four audits, three
fix changes, about fifty PRs. The score went 3.8 → 5.9 → 6.5 → 6.0 against a gate of 8.0, and the
final fix wave introduced the defect that pulled the score back down. The scaffold `task
connector:new` renders a package that fails the gate its own guide tells the author to run.

**Recommendation:** make the two small template fixes and add the gate that actually renders a
connector and runs its tests, run one more audit, then stop the loop whatever it says and return
the change slot to Phase 3. Outside the change cycle, three things need attention: the weekly
Synthea regeneration job has failed every run since it was created, the warehouse-sync consumer
still dies silently when its Snowflake token expires, and Linear is three weeks behind the repo.

```
main commits              1066     (784 on 2026-08-30, +282)
merged PRs                406      (~305 on 2026-08-30, ~+100)
changes archived          20       (+2: connector-pattern, pulse-demo-closeout, both 2026-09-02)
changes active            4        billing-connector 9/13 · devex-eight 19/19 · devex-eight-2 13/13 · devex-eight-3 11/12
open PRs                  0
open GitHub issues        1        #319 — connector-pattern 2.5 regression receipt, no receipt posted
task check on main        green    CI at cd376aa, 2026-09-05
Synthea regen (weekly)    red      5 of 5 scheduled runs failed, 2026-08-10 → 2026-09-07
DevEx score               6.0 / 5.6   (overall / connector composite, gate 8.0 / 8.0, 2026-09-05b)
catalog                   1.1.0    unchanged
workflow                  v2.2.0   unchanged
release                   v2.0     unchanged, 2026-08-08
```

---

## 1.0 Phase crosswalk

| Phase | Vehicle | State |
|---|---|---|
| 0 — Absorption | `ocean-eventbridge-migration` | archived |
| 1 — Record | `pulse-ledger-core` | archived, v1.5 |
| 2 — Ingress | seven changes | archived, v2.0 |
| 3 — Projections | 9 archived (this window: `billing-state` 08-30, `connector-pattern` 09-02, `pulse-demo-closeout` 09-02, which absorbed `projection-rebuild-drill`) · `billing-connector` 9/13 · 4 queued (`customerio-projection`, `survey-engine-ingress`, `reconciliation-sweeps`, `m1-retire-patient-state`) | active |
| 4 — Retirement | `dbt-derived-state-retirement`, `odg-read-redirect` | queued |
| Genesis / cutover | `genesis-*`, `pocar-relay`, P0→P3 ladder | queued, calendar-bound tail |
| Off-ladder | `devex-eight`, `devex-eight-2`, `devex-eight-3` | 43/44 tasks, gate not met |

Phase 3's exit (v3.0) has three criteria. One is now met.

| v3.0 criterion (ADR §6) | State |
|---|---|
| Projections rebuild from ledger in a drill | **met 2026-09-02** — Demo 5 stage 6 live on dev, zero differences, receipt on #342 |
| Reconciliation clean over one full cycle | not started — `reconciliation-sweeps` queued and gate-open. `billing-connector` 4.1/4.2 is a one-month reconciliation window, but for billing verdicts only |
| M1 retired — no consumer writes `patients.enrollment_status` | not started — `m1-retire-patient-state` queued and gate-open |

---

## 2.0 Progress since 2026-08-30

| Then (2026-08-30) | Now (2026-09-08) |
|---|---|
| `billing-state` one PR from archive | archived 2026-08-30 |
| `connector-pattern` proposed the same day, 16 tasks | cut at the kit/connector seam on 2026-09-01 (design decision 9). Kit extracted into `pulse_core.connector`, three integrations refactored onto it, `packages/billing` scaffolded with fact folding and the ported `billing_eligibility` rules. Archived 2026-09-02. Six tasks moved to `billing-connector`. Task 2.5 left open on #319 |
| billing connector did not exist | proposed 2026-09-02 and 9 of 13 tasks merged the same day: package, config, evaluate, declare, service with allowlisted triggers, deploy artifacts, contracts. Remaining: 4.1 sweep (blocked), 4.2 window, 5.1 cutover, 5.2 docs |
| four demos, each proving one door | Demo 5 walks one patient through every seam, offline (`task demo:e2e`) and live. 12/12 tasks, archived 2026-09-02, live receipt on #342 |
| `projection-rebuild-drill` queued as its own change | folded into Demo 5 as stage 6, passed live |
| no DevEx measurement | two-tier measurement: strict xfail findings in a `cat10` gate plus a frozen, checksummed audit protocol. Four audits, three fix changes, 43 tasks merged |
| the consent actor was `customer.io` | writer id is `customer-io`: the API derives writer ids from `PULSE_LEDGER_WRITER_TOKEN_<SUFFIX>`, so the dotted name was unspellable (replan, task 2.5 of `pulse-demo-closeout`) |
| Linear in step with the repo | Linear three weeks behind (§6.0 item 6) |

---

## 3.0 Demo 5 — what it proved and what it cost

Two runs against the same committed events, image `1c7f383`, migration head 0005, tenant dev01.

| Run | Command | Stages | Outcome |
|---|---|---|---|
| A, 03:01Z | `task stage:e2e:live -- --no-preflight` | 1–4 passed, 5 failed | warehouse window empty: `pulse-warehouse-sync` had been dead since 2026-08-29 with 25 messages waiting |
| B, 03:50Z | `task stage:e2e:live -- --no-preflight --from-stage=window_agreement` | 5–6 passed | exit 0 |

All three runbook assertions held: six stages live, the rebuild drill reported zero differences,
the rebuilt card was found on the first post-drill read inside the 60 s budget.

Six faults stood between "script merged" and "all stages pass", every one an environment drift,
none a ledger defect:

- The API pod still ran the 2026-08-16 image. Rolled by hand through the tenant ECR.
- Migration 0005 was not applied. Applied through a node-pinned socat relay pod.
- The consent writer credential did not exist and could not, until the writer id changed.
- The dev Twenty API key had been revoked. Rotated (DNA-1304), and `task twenty:key:rotate` now exists.
- The demo card was not seeded on the dev board.
- `pulse-warehouse-sync` had been dead for four days with the pod still `Running`.

Two gaps remain from the run:

- **The receipt file was never committed.** The #342 comment says it landed as
  `handoffs/pulse-demo-closeout/3.3-receipt.md` on PR #353. That file does not exist in the tree,
  and `handoffs/pulse-demo-closeout/SUMMARY.md` links to two task files that also do not exist.
  The receipt lives only as a GitHub comment.
- **Nobody watched it.** The purpose of task 3.3 was to see all six stages run live. The run
  happened in the background across two invocations while the environment was being fixed. The
  runbook gained a §8 on 2026-09-04 with the procedure to sit and watch it on any day, using a
  fresh `--run-id`. It has not been run.

---

## 4.0 The DevEx loop

| Audit | Commit | Overall | Connector | Gate |
|---|---|---|---|---|
| 2026-09-02 | `99d9b7a` | 3.8 | 2.4 | no |
| 2026-09-04 | `b26dee0` | 5.9 | 5.8 | no |
| 2026-09-05 | `11622da` | 6.5 | 6.7 | no |
| 2026-09-05b | `5177d05` | 6.0 | 5.6 | no |

The gate, from `docs/process/devex-audit/README.md`: "Overall DX >= 8.0 and connector-author
composite >= 8.0, on a scorecard the QA agent accepted, from a run of the protocol below with the
frozen specs in this directory unchanged."

### 4.1 What moved

Three fix waves closed 17, then 12, then 10 findings: kit exports repaired, an authoring guide,
`task connector:new` in both directions, hook install, `CHANGE` guards, a CHANGELOG and
deprecation policy, CODEOWNERS and issue templates, per-target timings in the ledger. The
2026-09-02 → 2026-09-05 rise is real and traceable to merged PRs.

### 4.2 Why the last audit fell

PR #403 (`devex-eight-3` task 2.1) left a bare `from factories import` in both rendered test
templates and an outbound `def run(` line that `ruff format` rejects. So the scaffold's own output
fails `task check`. The API/CLI dimension dropped two points on that. Upgrade and Community each
dropped one point with no relevant commits, which the QA agent attributes to scorer drift.

The inner gate did not catch the regression because `devex_open_findings=0` means "no previously
recorded finding is still open", not "the golden path works". No test renders a connector and runs
the real gate against it. The protocol now says so in writing (PR #394), but the gate is unchanged.

### 4.3 Cost

- About 50 PRs across 2026-09-03 → 2026-09-05, roughly half the window's merges.
- Seven of ten `devex-eight-3` wave-1 receipts were reconstructed from worker messages because the
  worktrees were removed before `task collect` ran.
- One manual escalation (DNA-1312, 1Password SSH agent) blocked the coordinator's pushes mid-loop.

### 4.4 Recommendation

Do the three ranked fixes from the 2026-09-05b scorecard, then one audit, then stop the loop.

1. Ship `templates/connector/tests/__init__.py.tmpl` and change the import to
   `from tests.factories import`. The correct pattern already exists in `packages/billing-connector`.
2. Fix the outbound `def run(` signature so `ruff format` is a fixed point.
3. Replace the "scaffold command exists" test with a slow test that renders both directions into a
   temporary tree and runs the combined gate. This is what makes a zero finding count mean something.

Then run `/devex-audit` once and check off 3.1 whatever the number is. The Community dimension is
capped near 3–4 by single authorship, so the mean needs two of the other four dimensions at 9 to
clear 8.0, and the last two audits show diminishing returns inside a ±1 scorer noise band. A 6.x
with a working golden path and a gate that guards it is worth banking. Alternatives, in order:
continue to `devex-eight-4` as the loop rule says (defensible, expensive), or stop now without the
fixes (not recommended, the scaffold is broken today).

---

## 5.0 Billing connector — the critical path

| Task | State | Lane | Blocker |
|---|---|---|---|
| 1.1–3.2 | merged 2026-09-02 | repo change | — |
| 4.1 `verdict-reconcile` sweep (DNA-1281) | open | repo change | dbt spike files uncommitted on a `data-platform` spike branch (seed gate 3, asked 2026-09-02) |
| 4.2 open the window | open | live execution | needs 4.1, a tracking issue and a runbook PR, then an attended start on dev |
| 5.1 cutover | open | destructive ops | needs the window to run one full billing month |
| 5.2 docs close-out (DNA-1282) | open | repo change | follows 5.1 |

The path is serial and the middle of it is a calendar month. If the spike files land this week and
4.2 opens by 2026-09-15, the window closes mid-October and cutover follows. Every week the
`data-platform` commit slips moves cutover a week. Nothing in this repo can shorten it. What can
be done now: open the 4.2 tracking issue and write its runbook PR so the window starts the day 4.1
merges, and verify the warehouse-sync fix (§6.0 item 2) before the window depends on it.

---

## 6.0 Operational notes

1. **Synthea regen has never succeeded.** `.github/workflows/synthea-regen.yml` runs Mondays at
   06:00 UTC and has failed all five runs: 08-10, 08-17, 08-24, 08-31, 09-07. The logs have
   expired, so the cause is unknown. Its artifact is what the `environment-matrix` staging loader
   is meant to consume. A manual dispatch will produce a fresh log.
2. **warehouse-sync still dies silently.** Found dead 2026-08-29 → 09-02 with the pod `Running`
   and the consume loop gone on Snowflake error 390114 (token expiry). PR #296 (2026-08-27,
   DNA-1259) was meant to make the process exit when the consumer dies. Either dev was not running
   that image, or the token-expiry path is not covered. Verify which. Stage 5 of every live demo
   and the billing reconciliation sweep both read `STG_EVENTS.EVENTS`. DNA-1259 sits in Backlog.
3. **The deploy path is manual.** `task ledger:deploy` pushes a bare image name to Docker Hub and
   fails. Live rolls are a hand-tagged ECR push plus `duploctl service update_image`, and the
   image build needs Rosetta in Docker Desktop or `uv` segfaults. Every attended run pays this.
4. **Receipt hygiene.** The Demo 5 receipt file is missing (§3.0). `connector-pattern` was
   archived with 2.5 unchecked and #319 carries no receipt: demos 3 and 4 were never re-run on the
   refactored tree. Demo 5 exercised the same seams live, which is a fair substitute, but the
   task asked for a receipt and the issue is still open.
5. **Two finished changes are not archived.** `devex-eight` (19/19) and `devex-eight-2` (13/13)
   still sit in `openspec/changes/`, so the directory listing overstates the work in flight.
6. **Linear is three weeks behind.** The Pulse 1.0 project's target date was 2026-08-31 and its
   last status update (2026-08-20) reads on track. `billing-state` (DNA-1158) shows In Progress,
   archived 08-30. `connector-pattern` (DNA-1270) and its twelve sub-issues show Todo, archived
   09-02. No parent exists for `billing-connector`, `pulse-demo-closeout`, or the three DevEx
   changes, and `billing-connector` reuses DNA-1280/1281/1282 from its parent. DNA-909 (Twenty
   dev instance) is still In Review though the instance has been live and proven since 08-18.
   Duplicate Todo sub-issues exist for 6.4 (four copies), 6.5 (four) and 6.6 (two).
7. **Carry-over, unverified this window:** `pulse-ledger-relay` was two weeks behind the API
   image on 2026-08-30. The 09-02 run rolled `pulse-ledger-api` only.

---

## 7.0 Open items needing a decision

- **Stop or continue the DevEx loop** after one more audit (§4.4). Recommendation: stop.
- **Who chases `data-platform` for the dbt spike branch** (seed gate 3). It gates billing cutover
  and nothing else in this repo does.
- **Next Phase 3 change.** Recommendation: `reconciliation-sweeps` first, because its exit
  criterion ("clean over one full cycle") is calendar-bound and can run alongside the billing
  window, with `m1-retire-patient-state` in the second slot once the DevEx slot frees.
- **Linear refresh.** One status update with a new target date, close the DNA-1158 and DNA-1270
  trees, sync parents for the four unsynced changes, delete the duplicate sub-issues.
- **Unchanged carry-overs:** the Benefits Investigation Platform → verdict-mart lineage question,
  a publisher contract for `OCEAN_MARTS.OCEAN_VERDICTS`, `Contract.terms.economics_model`
  placement (gates D6), warehouse modeling ownership, the PX timeline for `survey-engine-ingress`
  (now four reports old), and `environment-matrix` and `observability`, both prerequisite to the
  cutover ladder and neither started.

---

## 8.0 What's next

1. Get a Synthea regen log while it is fresh:
   `gh workflow run "Synthea regen"` then `gh run watch`.
2. Archive the two finished DevEx changes:
   `task verify CHANGE=devex-eight` then `task spec:archive CHANGE=devex-eight`, same for `devex-eight-2`.
3. `devex-eight-3`: one small PR with the three fixes in §4.4, `task devex:check` to 0, run
   `/devex-audit`, check off 3.1, verify, archive.
4. `billing-connector`: post the seed gate 3 ask where `data-platform` will see it, and open the
   4.2 tracking issue plus runbook PR now.
5. Confirm the warehouse-sync image on dev carries #296 and cover the 390114 path if it does not.
6. Linear: `task linear:sync CHANGE=billing-connector` in preview first, then the status update
   and the close-outs in item 6 of §6.0.
7. Propose `reconciliation-sweeps`.

---

*Untracked working file under `.planning/reports/`. Follows the structure of
`2026-08-30-program-status.md` for side-by-side comparison. Sources: `openspec/changes/`,
`handoffs/`, `.planning/reports/2026-09-0[2-5]*`, `git log` 2026-08-30 → 2026-09-08, GitHub
issues #319 and #342, GitHub Actions run history, Linear project Pulse 1.0.*
