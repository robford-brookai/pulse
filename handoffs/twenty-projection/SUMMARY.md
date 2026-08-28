# twenty-projection — collection summary

Collected 2026-08-21 at wrap-up. All 12 tasks done; every repo task merged by PR, both
operator-lane tasks receipted on GitHub issue #252. Worktree HANDOFFs were lost before
collect — see `LOST-HANDOFFS-NOTE.md`; the per-task files here are reconstructions from
merged PR bodies.

| Task | What shipped | Evidence |
|---|---|---|
| 1.1 scaffold | `packages/twenty-projection` workspace member | PR #239 |
| 1.2 watermark | `projectionSeq` field on patientProgram | PR #240 |
| 2.1 apply core | monotonic full-state board writes, typed errors | PR #241 |
| 2.2 orphan parking | payload-free failure handling around apply | PR #243 |
| 2.3 consumer loop | SQS → apply, `task projection:consume TARGET=dev` | PR #245 |
| 2.4 echo suppression | `NoOp("echo_of_record")` in the drag mapping | PR #242 |
| 3.1 heal-back | rejected drag restored to state of record | PR #244 |
| 3.2 echo-loop proof | integration test: heal's bounce is one noop | PR #246 |
| 3.3 contracts + docs | publishes.md surfaces, projection runbook, cat8 pin | PR #251 |
| 4.1 live heal-back | card healed in 0.37 s, echo terminated live | issue #252 (2026-08-20 receipt), PR #262 |
| 4.2 distribution path | relay + bus + rule + queue live; converged and settled | issue #252 (final receipt), PRs #264 #265 #266 |
| 4.3 demo3 rework | steps 7–8 rebuilt for the live-webhook world | PR #263, receipt on #252 |

Mid-change fixes that belong to this change's story: PR #255 (twenty-projection installed in
the ledger image + workspace-sibling gate), PR #260 (app reinstall after artifact apply, app
0.1.3), PR #265 (lazily-imported `ocean_broker` declared + the dependency gate hardened
against its own comment), PR #266 (relay Duplo service manifest + the D17 lag gauge actually
logged).

Open findings flagged on DNA-1138 (not applied as spec deltas):
- **Projection write amplification** — a state-changing projection write commits a new event
  via Twenty's webhook; converges but O(backlog) amplification on backfills. Needs its own task.
- **Demo3 genesis alignment** — card indices whose ledger subjects advanced fail alignment;
  the delivery trusts an index rather than discovering a usable card (PR #263 handoff).
