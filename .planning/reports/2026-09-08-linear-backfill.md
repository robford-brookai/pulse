# Linear backfill — Pulse 1.0, 2026-09-08

Backfilled the Linear project "Pulse 1.0" (team DNA) against three weeks of merged `pulse` repo
history. Evidence gathered from a read-only worktree at `origin/main` (`fb01666`), `gh pr view`,
`gh issue view`, and the repo's `openspec/changes/archive/`, `handoffs/`, and `.planning/reports/`
trees. `task linear:sync` was never run — see GitHub issue #416 for why it can't do this job
today.

Every mutation below was made with the `mcp__claude_ai_Linear__*` tools, team `DNA`, project
`Pulse 1.0` passed explicitly.

## 1. Three-week backfill — known moves

| Issue | Field | From | To | Evidence |
|---|---|---|---|---|
| DNA-909 | comment | — | evidence added | Already Done when checked (`completedAt` 2026-09-08T19:46:52Z, moved before this session started). Archive `openspec/changes/archive/2026-08-18-twenty-dev-instance/` (all tasks checked); live since 2026-08-18 per the 2026-08-16 provisioning receipt already on the issue. |
| DNA-1260 | state | Backlog | Done | PR #295, `fix(schedules): month-open normalizes --month to the first of the month (DNA-1260)`, merged 2026-08-28 |
| DNA-1261 | state | Backlog | Done | PR #298 (`open_billing_episode` state-bearing) + PR #297 (registration commands state-bearing), `billing-state` task 4.0, merged 2026-08-28 |
| DNA-1259 | state | Backlog | In Progress | PR #296 (merged 2026-08-28) fixed the original report; program status report (2026-09-08) found the consumer dead again 2026-08-29→09-02 on Snowflake error 390114. Follow-up PR #413 (open) adds reconnect + liveness probe. Comment links #413, leaves In Progress pending merge + dev-image confirmation |
| DNA-1263 | — | Backlog | left, no evidence | No commit, PR, or archived-change task references DNA-1263 or `resolve_referral`'s state-bearing commit path. Comment added noting this |
| DNA-1106 | state, parent | Todo | Done, parent DNA-1019 | Task 6.4 checked `[x]` in `openspec/changes/archive/2026-08-18-twenty-dev-instance/tasks.md`. Survivor of 4 duplicate copies |
| DNA-1118, DNA-1120, DNA-1123 | state | Todo | Duplicate (of DNA-1106) | Duplicate copies of task 6.4 |
| DNA-1107 | state, parent | Todo | Done, parent DNA-1019 | Task 6.5 checked. Survivor of 4 duplicate copies |
| DNA-1119, DNA-1121, DNA-1124 | state | Todo | Duplicate (of DNA-1107) | Duplicate copies of task 6.5 |
| DNA-1122 | state, parent | Todo | Done, parent DNA-1019 | Task 6.6 checked. Survivor of 2 duplicate copies |
| DNA-1125 | state | Todo | Duplicate (of DNA-1122) | Duplicate copy of task 6.6 |
| DNA-1126 | state, parent | Todo | Done, parent DNA-1019 | Task 6.7 checked. No duplicates |
| DNA-1033 | state | Todo | Done | Task 7.3 checked. No duplicates |

## 2. Parent issues created

All in project Pulse 1.0, team DNA, title `[CHANGE] <id>`, no sub-issues attached:

| Issue | Title | State |
|---|---|---|
| DNA-1334 | `[CHANGE] devex-eight` | Done |
| DNA-1335 | `[CHANGE] devex-eight-2` | Done |
| DNA-1336 | `[CHANGE] devex-eight-3` | Done |
| DNA-1337 | `[CHANGE] devex-eight-4` | In Progress |
| DNA-1338 | `[CHANGE] pulse-demo-closeout` | Done |
| DNA-1339 | `[CHANGE] billing-connector` | In Progress (PR #415, archiving, was open at time of writing) |
| DNA-1340 | `[CHANGE] billing-cutover` | Backlog |

Descriptions carry: outcome paragraph, task count from the archive's `tasks.md`, links to the
archive path and `handoffs/<id>/SUMMARY.md`, and (for the DevEx parents) the audit ledger rows
from `.planning/devex/loop.jsonl`. `billing-cutover`'s description carries the seed doc's TL;DR
and entry gates from `design/delivery/billing-cutover-seed.md`.

## 3. billing-state (DNA-1158) wrap

Confirmed: all 9 children of DNA-1158 (DNA-1159 through DNA-1167) already Done. No stragglers —
no changes made.

## 4. DNA-1270 tree (connector-pattern)

| Issue | Task | State | Evidence |
|---|---|---|---|
| DNA-1270 | `[CHANGE] connector-pattern` (parent) | Done | Archived `openspec/changes/archive/2026-09-02-connector-pattern/`, all 10 tasks checked including 2.5 (closed today via PR #407, receipt on issue #319, now closed) |
| DNA-1271 | 1.2 | Done | PR #315, redone as PR #317, merged 2026-09-01 |
| DNA-1272 | 2.1 | Done | PR #312, merged 2026-08-31 |
| DNA-1273 | 2.2 | Done | PR #314, merged 2026-08-31 |
| DNA-1274 | 2.3 | Done | PR #313, merged 2026-08-31 |
| DNA-1275 | 2.4 | Done | PR #316, merged 2026-09-01 |
| DNA-1276 | 3.1 | Done | PR #322, merged 2026-09-02 |
| DNA-1277 | 3.2 | Done | PR #324, merged 2026-09-02 |
| DNA-1278 | 3.3 | Done | PR #323, merged 2026-09-02 |
| DNA-1279 | 3.4 | Done | Shipped as billing-connector 2.1/2.2, PR #344, #345, merged 2026-09-02 (task cut to billing-connector at design decision 9) |
| DNA-1280 | 3.5 | Done, reparented to DNA-1339 (`[CHANGE] billing-connector`) | Shipped as billing-connector 3.1, PR #347, merged 2026-09-02 |
| DNA-1281 | 4.1 | Backlog, reparented to DNA-1340 (`[CHANGE] billing-cutover`) | Moved out of billing-connector at task 3.2 (design decision 11, 2026-09-08); comment names `design/delivery/billing-cutover-seed.md` |
| DNA-1282 | 5.2 | Backlog, reparented to DNA-1340 (`[CHANGE] billing-cutover`) | Same move; comment names the seed doc and 2026-09-08 |

## 5. Project status update

Posted on Pulse 1.0, health **at risk**: summarized the 2026-09-08 program status report's TL;DR
(Demo 5 passed live; billing connector shipped and cut with no cutover planned; DevEx loop pausing
after one more audit at 6.0/5.6 vs an 8.0 gate) and noted the target date (2026-08-31) has passed
and needs a new date from the project owner. Target date not set.

URL: https://linear.app/brook-health/project/pulse-10-d3ea7b0e45bf/activity#project-update-b7a57946

## 6. GitHub issue filed

`robford-brookai/pulse#416` — `linear_sync.py: cannot sync archived changes; parentless
sub-issues; complete_sub previews as ORPHAN`. Four verified defects, cited by file and line:

1. `main()` (`scripts/linear_sync.py:489`) bypasses `resolve_tasks_md()` (`scripts/linear_sync.py:87`),
   so it cannot find `tasks.md` for an archived change.
2. `apply_plan()` (`scripts/linear_sync.py:388-406`) sets `parentId` on a `create_sub` op only from
   the `parent_id` local, which is populated only inside the `create_parent` branch — a sub-issue
   created when the parent already exists gets no `parentId` at all.
3. `_render_op()` (`scripts/linear_sync.py:353-360`) has branches for `create_parent`, `create_sub`,
   `update_sub`, `heal_status` — `complete_sub` (a real op, `scripts/linear_sync.py:253`, applied at
   `scripts/linear_sync.py:454-455`) falls through to the `ORPHAN` line meant for issues no longer
   in `tasks.md`.
4. `WORKFLOW.md:222-223` says sync "never write[s] any started or completed status", but
   `complete_sub` sets `stateId` to `ctx["done_state_id"]` — the docs and the script disagree.

## Left, no evidence (untouched)

Issues in Pulse 1.0 with no status not Done/Canceled/Duplicate, and no repo evidence of a fix or
move, so left exactly as found:

- DNA-1263 (resolve_referral non-state-bearing) — no fix found, comment added
- DNA-1256 (Snowflake credential + repo secrets for dbt-ocean-refresh) — manual-intervention item, no repo change addresses it
- DNA-1189 (partner value-case fields in backfill scope) — no repo change addresses it
- DNA-910 (read-only Atlas role + DuploCloud secrets, BF-0a) — manual-intervention item, untouched
- DNA-911 (SNOWFLAKE_* Actions secrets for catalog:release) — manual-intervention item, untouched
- DNA-1157, DNA-1156 (Pulse standard data connector / dbt cdc connector spikes) — no repo change addresses them

## Counts

- Issues moved to Done: 15 (DNA-1260, 1261, 1106, 1107, 1122, 1126, 1033, 1270-1278 minus duplicates handled below, 1279, 1280 — see table above for the full list)
- Issues moved to In Progress: 2 (DNA-1259, and parent DNA-1339 `billing-connector`)
- Issues moved to Duplicate: 7 (DNA-1118, 1120, 1123, 1119, 1121, 1124, 1125)
- Issues reparented without a state change: 2 (DNA-1281, DNA-1282 — set to Backlog under new parent DNA-1340)
- Parent issues created: 7 (DNA-1334 through DNA-1340)
- Comments added: 24
- Project status updates posted: 1
- GitHub issues filed: 1 (#416)
- Left, no evidence: 6 (listed above)
