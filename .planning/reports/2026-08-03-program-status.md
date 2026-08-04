# PULSE — Program Status Report

**Date:** 2026-08-03 · **Repo:** `robford-brookai/pulse` · **Main:** `2a855dc`+
**Reporting window:** 2026-08-02 → 2026-08-03 — the two days in which Phase 0 closed and Phase 1 opened.

**Update (same date, later pass):** Phase 1 has advanced to **14/16** — waves 2 and 3 merged in full,
and wave 4's 4.3 and 5.1 are in. Main is at `3053dd8`, 30 commits ahead of the `2a855dc` this report
was originally pinned to. Only 5.2 (doc pins) and 5.3 (Demo 1) remain, and Demo 1 is what closes
Phase 1 — see §1–§4 below for the refreshed counts, §7 for a drift check and this pass's setbacks,
and §9 for what that changes about next actions.

---

## 1. Headline

**Phase 1 is 14/16 — wave 4 is down to its last two tasks, and 5.3 Demo 1 is what closes Phase 1.**
5.1's fold-equivalence proof merged (#92) and 4.3's `pulse_core` client merged (#93). 5.2 (doc pins,
`serial: openspec_main_specs`) has not been dispatched yet; 5.3 (Demo 1) has a work order and an open
worktree (`task-016`) but no commits or PR yet as of this check.

| Metric | Value |
|---|---|
| Commits on `main` | 347 total · 30 since this report's original `2a855dc` pin |
| Merged PRs | **90** |
| Phase 0 (`ocean-eventbridge-migration`) | **56 / 56 tasks** — archived |
| Phase 1 (`pulse-ledger-core`, S1.1) | **14 / 16 tasks** — only 5.2 and 5.3 remain |
| Open PRs | 0 |
| `task check` on `main` | **green** (as of `3053dd8`) |
| Changes proposed, not started | 2 (`bf0a-archaeology-access`, `synthea-seed`) — unchanged |
| Future changes on the ladder | 25 rows across Phases 2–4 + genesis/ops |

---

## 2. Phase crosswalk

| Phase | S-stages | Vehicle | State |
|---|---|---|---|
| **0 — Absorption** | S0.1 catalog spec, S0.2 catalog machinery | `ocean-eventbridge-migration` (DNA-733) | ✅ **complete**, archived `2026-08-02-…`; five delta specs seeded `openspec/specs/` as the repo's first baseline |
| **1 — Record** | S1.1 ledger schema + command API | `pulse-ledger-core` (DNA-784) | 🔵 **active** — 14/16, wave 4 down to 5.2 + 5.3 |
| 2 — Ingress | S2 + S1.2 verdict-relay, S1.3 schedules, S1.4 identity | 3 sibling changes | queued, gated on S1.1 wave 4 — **the gate is nearly open**: only 5.2 (doc pins) and 5.3 (Demo 1) remain before dispatch can start |
| 3 — Projections | S3 incl. migration M1 | `snowflake-projection`, `reconciliation-sweeps`, … | queued |
| 4 — Retirement | S4 | `odg-read-redirect`, … | queued |

---

## 3. Phase 0 — closed

OCEAN absorbed into the monorepo and its Kafka/MSK transport replaced with EventBridge + per-consumer
SQS. All 56 tasks merged; the three `destructive_ops` runbooks executed post-merge — terraform
applied, MSK Serverless torn down, `robford-brookai/ocean` archived read-only with the ADR §7
supersession notice as its final commit.

Delivered: 13 publish sites and 7 consumers converted; bus, per-consumer rules and queues, DLQs with
depth alarms, and the archive in Terraform; LocalStack replacing Redpanda locally, driven from one
generated catalog; and an equivalence gate that ran the harness against **both live transports** and
returned EQUIVALENT — identical graph tables, 618/618 audit rows, zero at-least-once duplicates, four
line-justified exclusions in a committed report.

### 3.1 The plan was wrong in ways only execution found

The most transferable result of Phase 0. Eight tasks were added mid-flight that the plan did not
contain, and several of its assertions were false:

| Finding | Consequence |
|---|---|
| `TESTED_PATHS` excluded all 16 OCEAN services | Thirteen conversions wrote tests **CI never ran**. Task 4.14 made CI execute them for the first time and found **4 of 14 suites red, 35 failures** |
| A persona `AGENTS.md` was silently dropped by the original import (task 1.2) | Reconstructed from test-pinned values |
| slack-bot never declared `aiohttp` | Container would have died at startup, not merely its tests |
| `failed_webhooks` fallback was **dead code** on every keyed connector | `tasks.md` said "already had the fallback — preserve it". `producer.py` took a `db_session_maker`; `main.py` never passed one |
| Migration `0017` had never applied | Invalid inline partial-unique DDL — the schema chain had never run end-to-end and nothing tested it |
| Five service images could not start | Pinned `confluent-kafka`, installed neither `ocean-broker` nor `boto3` |
| The committed LocalStack path had never run | Every SQS consumer died on `NoRegionError` while `/health` kept answering — compose set `AWS_REGION`, botocore reads `AWS_DEFAULT_REGION` |
| control-plane consumed the `ticket.created` it published | Unbounded ticket-minting loop; had to die before rules reached a live bus |

Two dependency errors and one false claim in `tasks.md` were corrected in place, each annotated with
what was found and when.

---

## 4. Phase 1 — active: `pulse-ledger-core` (S1.1)

**The serial opening is over, and waves 2–3 are fully merged.** 1.2 → 2.1 → 3.1 → 3.2 was
one-at-a-time by dependency; every wave since has landed as fan-outs plus a doc_update ruling PR.
Wave 4 (proof and documentation) is the last wave: 5.1 and 4.3 are merged, 5.2 hasn't been
dispatched, and 5.3 (Demo 1) has an open work order and worktree but no commits yet.

| Wave | Tasks | State |
|---|---|---|
| 0 — schema and scaffold | 1.1, 1.2 | ✅ merged (#70, #72) |
| 1 — generated command surface | 2.1 | ✅ merged (#76, + #77 doc_update) |
| 2 — the write path | 3.1, 3.2, 3.3, 3.4, 3.5 | ✅ **merged in full** (#79, #81, #86, #85, #88, + #87 doc_update) |
| 3 — reads, client, distribution | 4.1, 4.2, 4.3, 4.4, 4.5 | ✅ **merged in full** (#84, #90, #93, #83, #89, + #91 doc_update) |
| 4 — proof and documentation | 5.1 ✅ (#92), 5.2, 5.3 | 1 of 3; 5.2 not dispatched, 5.3 in an open worktree with no commits yet |

### 4.1 What 3.2 landed, and why it matters

`commit_declaration` / `commit_reversal` write the appended event, the co-committed `current_state`,
and the per-subject outbox row **in one transaction**. Two judgement calls worth recording:

- `recorded_at` uses `clock_timestamp()`, **not** the column default — the default is frozen per
  transaction and would collapse the fold's tie-break once 3.3 composes its idempotency insert into
  the same transaction. The worker anticipated the next task's failure mode.
- The ordering rule lives **once**, in a new `fold.py`, so the write path, the reads, and 5.1's
  independent re-derivation cannot disagree. 5.1's entire job is proving a fold equals
  `current_state`; a second copy of the rule would make that proof vacuous.

### 4.2 Wave 4 — down to two tasks, one of them mid-flight

The 3.3/3.4/4.1/4.4 fan-out this section originally described dispatched and merged, as did their
dependents (3.5, 4.2, 4.3, 4.5) and 5.1's fold-equivalence proof. What's left:

| Task | Scope | State |
|---|---|---|
| 5.2 DNA-799 | Pin downstream names: `design/delivery/pulse-s1-work-orders.md` confirm-path markers, ADR entry, `docs/contracts/publishes.md` | Not dispatched. Tagged `serial: openspec_main_specs` in `routing.serial_lane_always` — must release in its own wave per `WORKFLOW.md`, not concurrently with 5.3. Its only dep (5.1) is merged, so it could start now; held because 5.3 is already mid-flight. |
| 5.3 | Demo 1 — `scripts/demo/demo1_ledger_core.sh` + `docs/runbooks/demo1-ledger-core.md`, run against LocalStack | Work order dispatched (`task-016`, worktree open at `robford-brookai/task-016`), but the worktree carries no commits and no PR yet as of this check — still in progress, not done. |

5.3 is the task that **closes Phase 1** once merged. 5.2 is queued to follow in its own wave.

---

## 5. Open items needing a human decision

### 5.1 Raised by 3.2, unsettled by its merge

Three behaviours had no requirement. They are implemented, tested, and written up for ratification
rather than left as silent precedent:

1. **Subjects enter at a catalog entry state** (derived as states with no incoming edge). Chosen over
   "any state is a legal genesis" because `backfill_genesis` exists for arbitrary anchoring and is
   restricted to the backfill actor — letting the forward path do the same would make that
   restriction protect nothing.
2. **The fold treats a reversal as void-marking**, dropping both the reversal and the event it voids.
   The warehouse re-derives state by folding independently, so the two implementations must agree or
   reconciliation reports false drift forever.
3. **Reversing a subject's only surviving fact is refused.** No state to fold back to, and `0001`
   grants no DELETE on `current_state`. "Subject reverts to having no state" needs a schema decision.

Two genuine conflicts, both independently verified:

4. **`communication_consent` validates but cannot be committed.** Migration `0001`'s `SUBJECT_TYPES`
   has six entries; the catalog seed has seven; the specs' six-grain enumeration is a third voice.
   Pinned by a test, not papered over. Needs a schema revision or a spec correction — **from whoever
   records consent first**.
5. **Backdating can strand already-committed successors as illegal, and nothing detects it.** Insert
   `closed`@T1 into `received`@T0 → `resolved`@T3 and the T3 event now departs from a terminal state.
   The commit path does not re-validate successors; the fold does not care; it commits. The design
   register treats backdating as the *mitigation* for late corrections without acknowledging it can
   itself produce an incoherent sequence.

### 5.2 Standing decision register (unchanged this window)

D4 catalog→Twenty generator · D14 SPCS vs EKS · D15–D18 auth / idempotency / outbox / catalog SoR ·
G-1 historical closed objects · G-2 drift tolerance · G-3 per-family flip dates · BF-D1 backfill
horizon · BF-D2 evidence floors · BF-D3 genesis re-anchoring · BF-D4 Billy import semantics · plus
five named roles to confirm (quarantine reviewer, compliance owner, verdict steward, on-call,
enablement lead).

---

## 6. Open PRs — update: #53 has merged

| Item | What | Status |
|---|---|---|
| **PR #53** | MkDocs 1.x pinned, fork-pull guard in CI (DNA-782) | **Merged.** No longer open. |
| **Issue #45** | Plan MkDocs upgrade: Material compatibility | Still open, still unclaimed |

There are no open PRs on the repo as of this check.

---

## 7. OpenLore drift check

`openlore drift` run against `main` (2 changed files vs. base): **no spec drift detected** — specs
are in sync with code changes. Caveat worth recording rather than treating as a clean bill of
health: the run reports **0 mapped source files** across the 5 spec domains, so this pass had
nothing to actually diff source against — a true positive would currently look identical to a
true negative until the domain-to-source mapping is populated. `G_DRIFT` (blocks `archive`) is
relying on this signal as-is.

### Setbacks and challenges this pass

- **Concurrent sessions landed 4.3 and 5.1 independently, ahead of this session's own dispatch.**
  Both were verified merged (PRs #93, #92) rather than re-executed, so no work was lost this time —
  but it's the same class of risk §7's "Concurrent sessions duplicate serial tasks" row already
  flags for 2.1, now observed again on non-serial tasks. Two sessions running the same change
  concurrently is still an open, unresolved question (§8 action 3 in the prior pass, unchanged).
- **`WORKFLOW.md` and `scripts/linear_sync.py` carry uncommitted local edits** that predate this
  session and have persisted, untouched, across the whole reporting window (a `status_ownership`
  change adding a sync-owned Done write on task checkoff). Left alone rather than guessed at or
  overwritten, per the rule that workflow edits are their own change — but it means the workflow's
  committed source of truth and its working-tree copy have quietly diverged for the duration of
  this pass.
- **No `LINEAR_API_KEY` in this environment.** `task linear:sync CHANGE=pulse-ledger-core --apply`
  degraded to a dry-run plan rather than mutating — DNA-795 (4.3) and DNA-798 (5.1) sub-issues are
  still sitting wherever they were before their tasks merged, not moved to Done. Needs a session
  with credentials to close the loop; the file-side checkoff already happened (`tasks.md`, commit
  `3053dd8`).
- **5.3 (Demo 1) is slower than the rest of wave 4.** Dispatched into a fresh worktree same as 5.1
  and 4.3 were, but as of this check it still carries no commits — worth watching rather than
  re-dispatching prematurely, since a stalled worktree and a genuinely long-running task look
  identical from the outside until one of them ships.

---

## 8. Delivery mechanics — what is working, what to watch

### Working

- **Gate-before-feature tasks pay for themselves.** 4.14 (make CI run the suites) found 35 failures
  no prior green check could see. 3.0 (one migration up front) prevented four conflicting `0019`s.
  The equivalence harness (8.1) was built before 8.2 needed it.
- **The dispatch gates catch real errors.** `G_MECE`'s wave check rejected mislabelled waves with
  *"the graph is the truth; fix the label or fix the deps"* — the labels were wrong. `G_HARDENING`
  blocked dispatch when Orca's default agent args turned permissions off repo-wide.
- **Agents reporting what the work order got wrong** produced more value than the code in several
  cases. Every row in §3.1 came from that field.

### To watch

| Risk | Evidence | Mitigation |
|---|---|---|
| **Concurrent sessions duplicate serial tasks** | Two agents independently implemented 2.1 with incompatible designs (~800 lines discarded); the task was declared `serial` precisely so its output could not fork | Decide whether two sessions keep running S1.1 — serial tasks are where they collide |
| **Shared `refs/stash` across worktrees** | Destroyed one task's work on 08-02; a second agent attempted the same on 08-03 despite the rule being recorded | Absolute ban now in every work-order brief, with the `git diff > patch` substitute spelled out |
| **Worktree lineage stacking** | 3.1's worktree was created as a child of the merged 2.1 worktree | Pass `--no-parent` for independent tasks |
| **Green CI ≠ verified work** | Phase 0's entire 2b wave | 4.14-class gates; the new `filterwarnings` gate makes leaked OS resources fail the run |
| **Uncommitted workflow drift** | `WORKFLOW.md` / `scripts/linear_sync.py` carry unstaged edits that outlived this entire reporting window (§7) | Land or discard as its own reviewed change; don't let dispatch decisions rely on the dirty copy |
| **Linear writes blocked without credentials** | No `LINEAR_API_KEY` this pass; DNA-795/DNA-798 sub-issues weren't moved to Done despite their tasks merging (§7) | Run `linear:sync --apply` from a credentialed session before the gap widens further |

---

## 9. Recommended next actions

The fan-out this section originally recommended already happened and merged; #53 is merged too.
What's left to close Phase 1, and what opens once it does:

1. **Let 5.3 (Demo 1) land.** It's the task that closes Phase 1 — confirm the `task-016` worktree
   produces a green `task check`-adjacent LocalStack run and ships a PR.
2. **Dispatch 5.2 in its own wave** once 5.3 clears (or independently, since its only dep is 5.1,
   already merged — but not concurrently with 5.3, per its `serial: openspec_main_specs` tag).
3. **Rule on 3.2's five open items** (§5.1) — still unruled-on. Items 4 and 5 are correctness
   questions, not style — item 4 blocks anyone recording communication consent; item 5 is a
   silent-incoherence class.
4. **Prepare to open Phase 2** once wave 4 fully closes: the three sibling changes (S2, S1.2, S1.3,
   S1.4) gated on S1.1 wave 4 become dispatchable the moment 5.2 and 5.3 both merge — decide
   sequencing and dispatch order for that fan-out now rather than after Phase 1 closes.

---

*Untracked working file under `.planning/reports/`. Task 5.2 is the natural owner of a refreshed
roadmap snapshot if this should become a tracked artifact.*
