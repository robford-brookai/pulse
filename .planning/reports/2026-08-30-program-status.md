# PULSE — Program Status Report

**Date:** 2026-08-30 · **Repo:** `robford-brookai/pulse` · **Main:** `e75fc5f`
**Reporting window:** 2026-08-25 → 2026-08-30 — the window that closed Phase 3's active slate:
`snowflake-projection` and `workflow-v2-1-efficiency` archived, and `billing-state` — the last
change carrying open work — passed its live declare-back on dev and sits one PR merge from
archive.

---

## 1. Headline

**billing-state is done: 25/25 tasks, and the live run proved the whole pairing on dev — a
billing verdict qualified its episode, a coverage verdict minted and transitioned an unseen
patient × payer subject, a rerun changed nothing, and a verdict against a reported episode
counted `transition_rejected` without touching state (receipt on #304, closed).** The archive
PR (#306) is open — its merge empties `openspec/changes/` and makes Phase 3's remaining work a
pure pick-the-next-change decision. The window also shipped WORKFLOW v2.1.0 → v2.2.0, moved the
relay to key-pair JWT ahead of Snowflake's 2026 password ban, and stood up a cross-repo
dependency model for pulse in the fonzie monorepo shell.

| Metric | Value |
|---|---|
| Commits on `main` | 784 total |
| Merged PRs | ~305 (up from ~287 at 2026-08-25) |
| Phases 0–2 | ✅ archived; v2.0 released 2026-08-08 |
| Phase 3 — archived this window | `snowflake-projection` (2026-08-26), `workflow-v2-1-efficiency` (2026-08-27) |
| Phase 3 — `billing-state` | **25/25, live run passed 2026-08-30** — archive on PR #306 |
| Open PRs | 1 — #306 (archive, mechanical) |
| Open changes after #306 | 0 |
| `task check` on `main` | green |
| Catalog | 1.1.0 live on dev (migration 0004 applied 2026-08-30) |
| Workflow | **v2.2.0** — out-of-lane, Open Engine queue, and G_* nomenclature retired (#300) |

---

## 2. Phase crosswalk

| Phase | Vehicle | State |
|---|---|---|
| 0 — Absorption | `ocean-eventbridge-migration` | ✅ archived |
| 1 — Record | `pulse-ledger-core` | ✅ archived, v1.5 |
| 2 — Ingress | seven changes | ✅ archived, v2.0 |
| 3 — Projections | 6 archived · `billing-state` awaiting #306 · 5 queued (`customerio-projection`, `survey-engine-ingress`, `reconciliation-sweeps`, `projection-rebuild-drill`, `m1-retire-patient-state`) | 🔵 active, near-empty in-flight |
| 4 — Retirement | `dbt-derived-state-retirement`, `odg-read-redirect` | queued |
| Genesis/cutover | `genesis-*`, `pocar-relay`, P0→P3 ladder | queued; calendar-bound tail |

Gate movement this window: `reconciliation-sweeps` is now gate-open (`snowflake-projection`
archived). `projection-rebuild-drill`, `m1-retire-patient-state`, and `customerio-projection`
were already open. `survey-engine-ingress` still waits on PX schema validation.

---

## 3. Progress since 2026-08-25

| Then (2026-08-25) | Now (2026-08-30) |
|---|---|
| `billing-state` 9/10, blocked on external dbt mart rows | **Complete.** Mart rows landed; 4.0 (registration commands state-bearing, #297/#298, DNA-1261) and 4.1 (verify script #303, live run 2026-08-30) both closed; archive on #306 |
| `snowflake-projection` 3/4, operator revival queued | **Archived 2026-08-26** — warehouse feed revived, `STG_EVENTS.EVENTS` contract live with `min_complete_from: 2026-08-26` |
| Workflow v2.0.7 | **v2.2.0**: v2.1.0 added replan, `task checkoff`, Linear id write-back (#293); v2.2.0 retired out-of-lane, the Open Engine queue, and G_* gate names — live execution is now GitHub issue + runbook PR + attended run (#300) |
| Relay authenticated to Snowflake by password | **Key-pair JWT** (#301) — the 2026 BCR bars passwords on `TYPE=SERVICE` users; password and key-path config are now mutually exclusive |
| — | Operational fixes: warehouse-sync exits nonzero when its consumer dies (#296, DNA-1259); month-open normalizes `--month` (#295, DNA-1260); one Docker image for all schedules jobs (#292) |
| Cross-repo dependencies undocumented beyond per-object contract rows | **Dependency model drafted** in fonzie (`specs/2026-08-30-pulse-cross-repo-dependencies/plan.md`): every publish/consume edge pinned to `docs/contracts/`, four ownership gaps named |

The live run also caught and fixed a real bug in the verification artifact itself: demo4 shared
one `Declarer` across its four checks, and `DeclarerCounts` never resets, so every receipt after
the first was cumulative — checks 2–4 could never pass. #305 gives each pass a fresh `Declarer`,
matching production wiring. The ledger itself behaved exactly as specified throughout.

---

## 4. The 4.1 live run — what it took and what it taught

Three stacked faults stood between "script merged" and "all four assertions pass," all now
fixed and documented in `docs/process/env-vars-retreival.md`:

1. **Stale writer token** — the API pod predated the minted `VERDICT_RELAY_TOKEN`; `envFrom`
   reads secrets at pod start only. Fix: rollout restart. Trap recorded.
2. **Stale image** — dev ran `b3961ae` (2026-08-16), which predates catalog 1.1.0 and all of
   billing-state's code. Fix: migration 0004 applied via the migrator role, then
   `duploctl service update_image` to `f951d41`. No amd64 build needed — ECR already had it.
3. **The demo4 counts bug** (#305, above).

Access paths verified and recorded for reruns: laptop `kubectl port-forward` works via the
duplo-jit **plan token** (the AWS-role path 401s — the 2026-08-28 "not an option" note was
half-right and is corrected); RDS is reachable only from the API pod's node pool (socat relay
pod, node-pinned); the migrator password — previously unrecorded anywhere — was reset via the
RDS master credential and now lives in the gitignored env file.

---

## 5. Operational notes

- **`pulse-ledger-relay` (outbox publisher) still runs the old image** — it published
  correctly during the live run, but it deploys from the same `pulse-ledger` image and is now
  two weeks behind the API. Cheap hygiene: roll it to `f951d41` at the next touch.
- **Duplo portal tokens expire with the session.** A 401-shaped "Authorization has been denied"
  from duploctl means re-auth (`duplo-jit duplo --interactive` in a real terminal), not missing
  permissions. Cost this window: three round-trips diagnosing an expired cache.
- **An accidental IDE drag moved `scripts/` into `packages/`** mid-session (2026-08-30);
  restored from git with the gitignored secrets file rescued by hand. Untracked files are
  invisible to `git restore` — worth remembering the next time a directory vanishes.
- **The stray-md hook doesn't know fonzie's `specs/` convention** — it blocked the dependency
  spec's `plan.md`. If fonzie sessions become routine, add its spec tree to the allowlist.

---

## 6. Open items needing a human decision

- **Merge #306** — closes billing-state; mechanical.
- **billy → verdict-mart lineage** (fonzie spec gap 3) — confirm the Benefits Investigation
  Platform produces the mart's rows and owns the patient × payer digest derivation.
- **Streamline publisher contract for `OCEAN_MARTS.OCEAN_VERDICTS`** (gap 1) — pulse's fixtures
  are still the only pin on a surface another repo computes.
- **`Contract.terms.economics_model` placement** — unchanged carry-over; gates D6.
- **Warehouse modeling ownership** (pulse committed SQL vs streamline dbt) — unchanged since
  the 2026-08-25 inventory.
- **PX timeline** for `survey-engine-ingress` — three reports old now; re-verify with Max
  Pengilly before sequencing.
- **`environment-matrix` and `observability`** — both still prerequisite to the cutover ladder;
  neither started.

---

## 7. What's next

1. **Merge #306**, then checkoff sweep — Phase 3's in-flight slate is empty.
2. **Pick the next fan-out.** Four changes are gate-open: `projection-rebuild-drill` (carries
   Demo 3 and the write-amplification fix's natural home), `m1-retire-patient-state`,
   `customerio-projection`, and now `reconciliation-sweeps`. The rebuild drill and M1 retire
   are the two that advance the cutover ladder.
3. **Close the fonzie gaps 1 and 3** — a streamline `publishes.md` entry and the billy lineage
   answer make both halves of the relay's most load-bearing contract pinned.
4. **Roll `pulse-ledger-relay` to `f951d41`** at the next dev touch.

---

*Untracked working file under `.planning/reports/`. Follows the structure of
`2026-08-25-program-status.md` for side-by-side comparison.*
