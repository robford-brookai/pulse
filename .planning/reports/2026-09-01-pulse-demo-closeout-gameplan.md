# PULSE — Closing Out for Demos: The Seam and the Gameplan

**Date:** 2026-09-01 · **Main:** `e13df9c` · **Active change:** `connector-pattern` (9 of 16
tasks merged)

**TL;DR:** `connector-pattern` is two projects sharing one directory. Waves 0 through 2 built
the connector kit, refactored the three shipped integrations onto it, and scaffolded the billing
engine with its rules ported. That is Pulse work and it is merged. Everything from 3.4 onward
wires the engine to declare, runs a month-long reconciliation window, and retires the relay's
Snowflake read. That is the Billing Connector, and the 3.3 finding proved it: which verdict
types exist is a billing question, not a ledger question. The recommendation is to cut
`connector-pattern` at the seam, archive it this week, seed a `billing-connector` proposal with
the six moved tasks and the three open findings, and spend the freed change slot on one
end-to-end demo that walks a single synthetic patient through every seam Pulse owns. Four
demos each prove one door today. None proves the building.

---

## 1.0 The seam

### 1.1 What stays in Pulse (merged, done)

| Task | What shipped | PR |
|---|---|---|
| 1.1 | cpt-om ownership resolved, producer registry updated | #311 |
| 1.2 | Rule-port map: 72 dbt objects → pulse counterparts or `stays-mart-side` | #315 |
| 2.1–2.3 | `pulse_core.connector`: read contract, declare pipeline, consume loop. Three donors refactored, no forks | #312 #314 #313 |
| 2.4 | Credential-posture gate: one writer credential per connector, no ledger internals | #316 |
| 3.1 | `packages/billing` scaffold, `billing_engine` Postgres schema, shadow-ledger gate | #322 |
| 3.2 | Fact folding: idempotent per-subject fact snapshots from the bus | #324 |
| 3.3 | `billing_eligibility` rule module with lineage gate, 21 mapped unit tests | #323 |

Task 2.5 (wave-1 regression receipt, live execution) is tracked on issue #319 and stays in
Pulse. It is the last receipt the kit needs.

### 1.2 What moves to the Billing Connector

| Task | Why it belongs on the billing leg |
|---|---|
| 3.4 Evaluation → declare | First code that writes billing state. Depends on which verdict types exist, which is finding 1 |
| 3.5 Engine deploy artifacts | Deploys the connector, not the ledger |
| 4.1 Reconciliation sweep | Compares engine to mart. Both sides are billing domain |
| 4.2 Open the window | One billing month on dev, attended |
| 5.1 Cutover | Retires the relay's Snowflake credential |
| 5.2 Docs close-out | ADR for the write-path supersession follows 5.1 |

Plus the three findings from 3.3, which are billing-connector entry gates:

1. **Only one of three rule modules has a dbt source.** Design decision 4 names
   `coverage_eligibility` and `benefits_verification`. The 1.2 map found nothing in the pinned
   scope to port. Writing them would be invented logic.
2. **Staleness has no warehouse source.** The `awaiting_source` rule now takes `facts_stale`
   from the consume-loop watermark, to be wired in 3.4.
3. **The pinned dbt spike files are uncommitted** on a data-platform spike branch. The lineage
   gate's claims point at nothing durable until they land.

Assumption flagged: the Billing Connector stays a Pulse change with `packages/billing` in this
repo, per the 2026-08-30 boundaries record §1.0 ("every external system integrates through a
connector package hosted in pulse"). A separate repo would need a new dependency contract in
`docs/contracts/` and is not recommended.

## 2.0 Closing connector-pattern

Four steps, all tool-run, one PR for you to review.

### 2.1 Replan PR (the decision lands in the artifacts)

Branch, then:

- `design.md`: add decision 9, dated 2026-09-01. "Waves 3–4 and task 3.4 move to the
  `billing-connector` change. Reason: the seam between kit and connector is the seam between
  Pulse and billing. Findings 1–3 from task 3.3 are that change's entry gates."
- `tasks.md`: remove 3.4, 3.5, 4.1, 4.2, 5.1, 5.2. Keep 2.5.
- `proposal.md`: narrow the scope statement and rollback section to match.
- `task replan CHANGE=connector-pattern` green, then PR.

`decision_protocol` in `WORKFLOW.md` requires this. A decision made in chat is not a decision
until the tasks that inherit it can read it.

### 2.2 Delta specs

The change carries four delta spec directories. The doc-updater sorts them:

| Spec | Disposition |
|---|---|
| `connector-kit` | Stays. Archives into the baseline |
| `billing-engine` | Split. Scaffold, fact-fold, and rule-port scenarios stay. Evaluation and declare scenarios move to `billing-connector` |
| `verdict-mart-read` | Moves whole. Every scenario is about retirement behind the reconciliation gate |
| `verdict-reconciliation` | Moves whole |

### 2.3 Run 2.5

Demos 1 and 2 offline now. Demos 3 and 4 attended on dev. Receipts on #319 and committed under
`handoffs/connector-pattern/`. This is also the first dress rehearsal for §4.0.

### 2.4 Archive

`task verify CHANGE=connector-pattern`, then `task spec:archive`. The change slot opens.

## 3.0 Billing Connector proposal seed

Not started this week. Drafted so it is ready when the entry gates clear.

- **Inherits:** the six tasks in §1.2, their delta specs, and `packages/billing` as it stands.
- **Entry gates:** (a) a named owner and dbt source for `coverage_eligibility` and
  `benefits_verification`, or a design amendment reducing decision 4 to one module, (b) the
  dbt spike files committed on a data-platform branch, (c) queue rule filter breadth decided.
- **Linear home:** the existing **Billing** project (DNA and Product teams, In Progress) is the
  natural parent. `task linear:sync` currently targets PULSE / Declared-State Funnel, so the
  proposal needs a project override or a decision to keep it under PULSE.
- **First task:** 3.4 as written, plus a one-line change: evaluate the verdict types the rules
  package registers, not a hardcoded three.

## 4.0 The end-to-end demo

### 4.1 What the four demos prove, and the gap

| Stage | Demo 1 | Demo 2 | Demo 3 | Demo 4 |
|---|---|---|---|---|
| Identity resolution | | offline | | |
| Consent ingress | | runbook only | | |
| Command API, catalog, idempotency | offline | offline | live | live |
| Twenty webhook ingress | | in-process | live | |
| Twenty projection (paint-back) | | | | |
| Snowflake landing (`STG_EVENTS`) | | | | |
| Verdict → billing and coverage state | | | | live |
| Rebuild from the journal | fold check | | | |

Three gaps stand out. No demo touches `twenty-projection`, `consent-ingress`, or
`synthea-seed`, the packages that make the "one truth, many windows" claim visible. No demo
follows one patient across stages. And the roadmap's demo table names Demo 3 as the projection
rebuild drill and Demo 4 as the read redirect, but the shipped `demo3` and `demo4` scripts are
the live kanban drag and the billing declare-back. The table and the scripts disagree.

Smaller drift to fix in passing: demos 3 and 4 have no runbook under `docs/runbooks/`, and no
Taskfile target invokes any demo.

### 4.2 Demo 5 — one patient, every seam

One script, two modes, one receipt. A change named `pulse-demo-closeout`.

**The story (synthetic patient from `synthea-seed`, deterministic seed):**

1. A referral arrives. The identity matcher resolves it: first as a new patient (mint), then a
   second referral with a matching identifier (exact match), then an ambiguous one (quarantine).
2. A Customer.io consent export row lands in the warehouse fixture. `consent-ingress` sweeps
   it. The ledger records consent with actor `customer.io`.
3. The care team drags the patient's card on the Twenty board. The signed webhook commits the
   move. An illegal drag is refused and the card gets one note.
4. A billing verdict arrives from the fixture mart. The relay declares the verdict and the
   paired transition. The coverage subject mints on first sight.
5. **The windows agree.** The Twenty projection paints the board from the ledger. The Snowflake
   landing holds the same events. The independent fold of the journal equals `current_state`.
6. **The drill.** Destroy the Twenty projection. Rebuild it from the journal. Row-identical.
   This closes the roadmap's Demo 3 promise and retires the table drift.

**Two modes:**

| Mode | Stack | Time | Who runs it |
|---|---|---|---|
| Offline | LocalStack, Postgres, fixture mart, fixture consent export, in-process Twenty route | about 5 minutes | any engineer, `task demo:e2e` |
| Live | dev ledger, dev Twenty board, dev Snowflake landing | about 15 minutes | attended, receipts on a GitHub issue |

Same script, one flag. Same assertions. The offline mode is the CI-shaped regression net the
kit refactors were supposed to have. The live mode is what you show.

### 4.3 Task sketch for `pulse-demo-closeout`

Eight tasks, three waves, one live execution. Model tiers per the dispatch rubric.

| # | Task | Wave |
|---|---|---|
| 1.1 | Synthea demo cohort: one pinned patient plus two referral variants, fixture consent row, fixture verdict row. Committed under `scripts/demo/fixtures/` | 0 |
| 1.2 | Roadmap and runbook drift: fix the demo table, add runbooks for demos 3 and 4, add `task demo:1..4` targets | 0 |
| 2.1 | `demo5_end_to_end.py` offline mode, stages 1–5, exits nonzero on any failed assertion | 1 |
| 2.2 | Rebuild drill: destroy and rebuild the Twenty projection, row-identical assertion. Folds the queued `projection-rebuild-drill` change into this one | 1 |
| 2.3 | Live mode flag: dev Twenty, dev Snowflake landing read, same assertions | 1 |
| 3.1 | Runbook `docs/runbooks/demo5-end-to-end.md`, `task demo:e2e`, smoke-parse test in `task check` | 2 |
| 3.2 | Presentation refresh: `2026-08-30-pulse-presentation.md` §3 gains the one-patient story and loses the per-demo framing | 2 |
| 3.3 | Attended live run on dev, receipts on the tracking issue (live execution) | 2 |

Assumption flagged: folding `projection-rebuild-drill` into this change is the recommended
path because the drill is the demo's final act. Keeping it separate costs a second change
cycle for one script section.

## 5.0 Sequence

```
Week of 2026-09-01   replan PR (§2.1) · doc-updater splits specs (§2.2) · run 2.5 (§2.3)
                     archive connector-pattern (§2.4) · billing-connector proposal drafted (§3.0)
Week of 2026-09-08   pulse-demo-closeout proposed and validated · waves 0 and 1 dispatched
Week of 2026-09-15   wave 2 · attended live run · presentation refreshed
```

Counts as of 2026-09-01:

```
connector-pattern tasks merged      9 / 16
tasks moving to billing-connector   6
tasks staying, unfinished           1   (2.5, live execution, issue #319)
packages exercised by no demo       6   (archaeology, consent-ingress, synthea-seed,
                                         twenty-app, twenty-model, twenty-projection)
demos with no runbook               2   (demo3, demo4)
```

## 6.0 Decisions taken (Rob, 2026-09-01)

1. **Cut at 3.4.** Tasks 3.4, 3.5, 4.1, 4.2, 5.1, 5.2 move to `billing-connector`. Waves 0–2
   archive as shipped. 2.5 stays.
2. **Billing Connector is a Pulse change** with `packages/billing` in this repo.
3. **The rebuild drill folds into the demo change** as Demo 5's final act.
4. **Audience: internal engineering, within two weeks.** Offline mode is the star, live mode
   is a bonus, presentation refresh is light.

**Next step:** replan PR for §2.1, then the doc-updater splits the delta specs per §2.2.
