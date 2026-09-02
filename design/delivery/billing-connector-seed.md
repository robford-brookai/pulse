# Billing Connector — proposal seed

**Status:** Seed, not a proposal · 2026-09-01 · **Source decision:** `connector-pattern`
`design.md` decision 9 · **Inherits:** `packages/billing` as it stands on `main`

---

## 0. TL;DR

`connector-pattern` was cut at the kit/connector seam. The connector kit, the billing engine's
scaffold, its fact fold, and its rule port stay in that change and archive into the baseline.
Everything downstream of them — evaluation-to-declare, deploy artifacts, the reconciliation
window, and cutover — becomes a `billing-connector` change, hosted in this repo with
`packages/billing`. This document is the durable carrier for what moved: the six tasks verbatim,
the entry gates that must clear before the change is proposed, and the delta spec text lifted out
of `connector-pattern`. It records no new decisions. Writing the proposal is a later act.

---

## 1. Why this exists

`connector-pattern` decision 9 (Rob, 2026-09-01) cut the change at the seam between the shared
connector kit and the first connector built on it. Everything from task 3.4 onward writes billing
state and depends on billing-domain answers, and task 3.3 surfaced three of them: only
`billing_eligibility` has a dbt source in the pinned scope (decision 4 had named three modules),
staleness must come from the consume-loop watermark because the engine has no warehouse read, and
the pinned dbt spike files are uncommitted on a `data-platform` branch. Which verdict types exist
is a billing question, not a ledger question — so finishing 3.4 inside `connector-pattern` against
the one module that happens to have a source would fix the verdict-type set by accident of scope
rather than by decision. The six tasks and their delta specs move here instead, and
`connector-pattern` archives with a coherent story: the kit, and an engine that folds facts and
holds ported rules but declares nothing yet.

---

## 2. The moved tasks

Copied verbatim from `openspec/changes/connector-pattern/tasks.md` at `origin/main` (`e13df9c`),
including their annotations. Renumbered for the new change; the original number is in parentheses.
`deps` in the annotations still name the *original* numbers — retarget them when the proposal is
written, not here.

### Wave A — declare and deploy

- [ ] 1.1 (was 3.4) [DNA-1279] Evaluation → declare: on fact-snapshot change, evaluate affected verdict types and
      declare verdict + paired transition through the kit pipeline under the `billing-engine`
      credential; record in `evaluations`; receipts extend with `evaluated=N`
      (specs: "Evaluation is event-driven, never batch-gated", "The engine declares
      attributed, versioned verdict pairs", "No monetary value crosses the seam").
      Tests: consent-arrival fixture triggers exactly the affected episode's evaluation;
      unchanged facts replay; amount-bearing fixture never leaks a monetary value into
      payload/log/receipt (tripwire test).
      `[model: sonnet | deps: 3.2, 3.3 | lane: repo_change | wave: 2]`

- [ ] 1.2 (was 3.5) [DNA-1280] Engine deploy artifacts: Duplo service JSON + queue/DLQ/rule provisioning script +
      runbook `docs/runbooks/billing-engine.md` (start/stop, receipt reading, rebuild-from-bus
      procedure). Deploy artifacts never reachable from `task check`.
      Tests: reachability gate (deploy targets out of `check`, existing pattern);
      `mkdocs build -s` green.
      `[model: sonnet | deps: 3.4 | lane: repo_change | wave: 2]`

### Wave B — window and cutover

- [ ] 2.1 (was 4.1) [DNA-1281] `verdict-reconcile` schedules entry: per-(subject, verdict_type) comparison of
      `evaluations` vs mart rows over matching fact windows; diff report with counts and
      subject keys only; empty-or-explained state machine for entries
      (specs: verdict-reconciliation, all three).
      Tests: fixture mart + fixture evaluations produce the golden diff shapes — agree,
      timing-artifact, genuine divergence; PHI tripwire on report output.
      `[model: sonnet | deps: 3.4 | lane: repo_change | wave: 3]`

- [ ] 2.2 (was 4.2) Open the window (live execution): GitHub tracking issue + runbook PR; attended
      start of the engine service on dev01-brook; both writers live; sweep scheduled; first
      sweep receipt on the issue. Window runs one full billing month.
      Tests (runbook assertions): engine declares on a live consent event without a scheduled
      run; sweep receipt posts; both writers' receipts attributable.
      `[model: sonnet | deps: 3.5, 4.1 | lane: operational_discovery | wave: 3]`

- [ ] 2.3 (was 5.1) Cutover runbook PR + attended run: stop the relay poll, retire its Snowflake
      credential, closing sweep report committed as the receipt
      (specs: verdict-mart-read "The mart read retires behind the reconciliation gate",
      "After retirement, the write path has no warehouse dependency").
      Tests (runbook assertions): no Snowflake credential on the write path; engine-only
      verdicts continue; rollback rehearsed (re-enable poll from config).
      `[model: sonnet | deps: 4.2 | lane: destructive_ops | wave: 4]`

- [ ] 2.4 (was 5.2) [DNA-1282] Docs close-out via `HANDOFF.md`: ADR for the write-path supersession,
      `consumes.md` mart row demoted, `publishes.md` billing-engine producer row,
      fonzie dependency-spec gap 1 note updated.
      Tests: `mkdocs build -s`; contract-doc gates; `task check` green.
      `[model: sonnet | deps: 5.1 | lane: repo_change | wave: 4]`

Note on lanes: 2.2 and 2.3 are `operational_discovery` and `destructive_ops` — live execution per
`WORKFLOW.md`, never a worktree.

---

## 3. Entry gates

Four things must clear before this change is proposed. The first three are the findings task 3.3
recorded in `handoffs/connector-pattern/task-010.md` (that file is per-worktree and gitignored;
quoted here so the findings survive it). The fourth is an open question `connector-pattern`
carried but never needed to answer.

### Gate 1 — the verdict-type set

> **One rule module, not three.** Decision 4 names `billing_eligibility.py`,
> `coverage_eligibility.py` and `benefits_verification.py`. The 1.2 map found that the pinned
> dbt scope contains no source for the latter two: "there is no `coverage_eligibility` /
> `benefits_verification` dbt source in this pinned scope — those two registered types have no
> counterpart here at all, not a gap, just outside what this tree computes." Writing modules
> for them would be invented logic, which is what this task must not produce. Only
> `billing_eligibility` ships. The lineage gate pins that set, so adding either later is a
> deliberate, reviewed edit.

Clears when either a named owner and dbt source exist for `coverage_eligibility` and
`benefits_verification`, or a design amendment reduces decision 4 to the one module.

### Gate 2 — where staleness comes from

> **Staleness is a parameter, not a source read.** The dbt model derives its `awaiting_source`
> reason from source-table recency on the raw Mongo billing collections. The engine never reads
> those, so the ported `classify_outcome` takes `facts_stale` as an input, to be supplied in
> task 3.4 from the engine's own consume-loop watermark (design.md decision 3). The reason
> vocabulary itself (`period_open`, `awaiting_source`) ports unchanged.

Clears when the watermark-to-`facts_stale` derivation is specified — which watermark, which
threshold, and what a subject with no folded events yet evaluates to.

### Gate 3 — a durable dbt source to diff against

> The 1.2 map's prerequisite still stands and is unresolved: the pinned dbt spike files
> (`management/models/billing/verdict/`) exist only as uncommitted local files in
> `data-platform`, on a spike branch. The port was made against that snapshot, faithfully, but
> until those files land as a commit there is nothing durable to diff the port against and no
> way for CI anywhere to detect the source drifting.

Clears when those files land as a commit on a `data-platform` branch.

### Gate 4 — queue rule filter breadth

From `connector-pattern` `design.md` Open Questions:

> Queue rule filter breadth for the engine (all `patient-state` + consent vs a narrower
> event-type list) — tunable after first dev traffic, does not change specs or tasks.

It did not gate `connector-pattern` because the engine there never declares. It gates the first
dev deploy here (task 1.2).

---

## 4. The moved delta spec text

Lifted verbatim from `openspec/changes/connector-pattern/specs/`. `verdict-mart-read` and
`verdict-reconciliation` moved whole and their directories were deleted; `billing-engine` was
split, and the two requirements below are the half that moved. Seed the new change's delta specs
from these; do not re-derive them.

### 4.1 Capability: `billing-engine` (the moved half)

The `billing-engine` capability keeps its scaffold/fact-fold/rule-port requirements in
`connector-pattern`. These two requirements move here.

#### Requirement: Evaluation is event-driven, never batch-gated

The billing engine SHALL subscribe to the ledger's committed events and evaluate the affected
subject's eligibility and coverage rules when a relevant fact arrives (a billing episode
opens, coverage state changes, consent state changes). Declare-back latency SHALL be bounded
by event delivery plus evaluation time — never by any batch schedule. The engine SHALL NOT
read the warehouse to decide a verdict.

##### Scenario: A fact arrives, a verdict follows

- **GIVEN** an open billing episode whose eligibility rules are satisfied except for consent
- **WHEN** the consent event for that patient commits and reaches the engine
- **THEN** the engine evaluates that episode and declares its verdict without waiting for any
  scheduled run

**Carried caveat.** Task 3.4 stopped before implementation on this scenario: the handoff records
that there is no ledger-native way to get from a consent event to the billing episodes it
affects — `billing_episode` subject keys are `{enrollment_key}:{YYYY-MM-DD}`, the `consent`
subject key has no composition function in the repo, and no command payload carries a
cross-reference. The relationship exists only as a Twenty relation or a warehouse join, both of
which the requirement's last sentence forbids. Resolving this is part of gate 1's neighbourhood
and belongs in the new change's design: add the missing fact to the catalog, narrow the
requirement to episode-subject events with consent fan-out deferred, or name an existing event
that carries both sides.

#### Requirement: The engine declares attributed, versioned verdict pairs

Every engine verdict SHALL be declared through the command API under the engine's own writer
credential, carrying the `rule_version` of the rule set that produced it, and SHALL follow
the registered pairing contract: verdict then paired transition, idempotency key derived from
the evaluation (D16) so the pair is replay-safe as a unit, `indeterminate` declaring evidence
with no transition. Monetary values SHALL never appear in a verdict payload, a state, a log,
or a receipt — the amount-free billing boundary applies at the engine's seam.

##### Scenario: Re-evaluating unchanged facts declares nothing new

- **GIVEN** a subject the engine already evaluated, with no new facts
- **WHEN** evaluation runs again for that subject
- **THEN** submissions classify as replayed and no new event exists

##### Scenario: No monetary value crosses the seam

- **GIVEN** a rule evaluation whose inputs include amount-bearing source data
- **WHEN** its verdict is declared and logged
- **THEN** the command payload, the receipt, and every log line carry qualification facts
  only — no monetary value appears anywhere downstream of the engine seam

### 4.2 Capability: `verdict-mart-read` (moved whole)

#### Requirement: The mart read retires behind the reconciliation gate

Once the verdict-reconciliation gate passes (a full billing month's sweep, empty-or-explained),
the relay's mart read SHALL be decommissioned: the scheduled poll stops, the relay's Snowflake
credential is retired, and the mart becomes an analytics and reconciliation surface only —
no pulse write path SHALL depend on it. Until that gate passes, this capability's existing
requirements stand unchanged and the poll keeps running.

##### Scenario: Retirement follows the gate, not the calendar

- **GIVEN** the reconciliation window still open or its diff not yet empty-or-explained
- **WHEN** any change proposes stopping the mart poll
- **THEN** the gate refuses — the poll and its cursor semantics remain in force

##### Scenario: After retirement, the write path has no warehouse dependency

- **GIVEN** the gate passed and the mart read decommissioned
- **WHEN** the verdict write path's runtime configuration is inspected
- **THEN** no Snowflake credential remains on it, and verdicts flow only from the engine's
  event-driven evaluation

### 4.3 Capability: `verdict-reconciliation` (moved whole)

**Purpose.** The proof that the in-pulse billing engine matches the mart it replaces: a
parallel-run window in which both compute verdicts, a per-subject comparison, and an
empty-or-explained diff as the gate the cutover cannot pass without.

#### Requirement: Engine and mart run in parallel for a full billing month

During the reconciliation window — at least one complete billing month — the engine SHALL
declare verdicts on the live path while the mart relay continues declaring exactly as today,
and the ledger SHALL remain consistent under both writers: the pairing idempotency and
per-subject as_of monotonicity rules decide which declaration moves state, and the window
SHALL surface every disagreement rather than letting either writer silently win.

##### Scenario: Both writers, one consistent ledger

- **GIVEN** the engine and the mart relay both active during the window
- **WHEN** both declare verdicts for the same subject
- **THEN** every declaration is attributed to its writer, replays and stale skips are counted
  per writer, and the subject's state of record reflects the pairing rules — never an
  unexplained overwrite

#### Requirement: The reconciliation sweep produces an empty-or-explained diff

A reconciliation sweep SHALL compare, per subject and verdict type, the engine's verdicts
against the mart's for the same facts, and SHALL produce a diff report in which every
disagreement is either absent or carries a written explanation (a timing artifact, a known
rule divergence with a decision record). The sweep's report SHALL carry counts and subject
keys only — never payload values or payer identifiers.

##### Scenario: A divergence is named, not averaged away

- **GIVEN** one subject where the engine says positive and the mart says negative
- **WHEN** the sweep runs
- **THEN** the report names that subject key and verdict type as a disagreement requiring
  explanation, and the window cannot close while it stands unexplained

#### Requirement: Cutover is gated on the reconciliation receipt

The mart read path SHALL NOT be decommissioned until a full window's sweep reports
empty-or-explained, and the closing report SHALL be committed as the receipt on the change's
tracking record — the same receipt discipline as the cutover ladder.

##### Scenario: An unexplained diff blocks the cutover

- **GIVEN** a window whose final sweep carries one unexplained disagreement
- **WHEN** cutover is proposed
- **THEN** the gate fails citing that disagreement, and the relay's mart read keeps running

---

## 5. Linear home — undecided

Two candidates, no decision made here.

- The existing **Billing** project (DNA and Product teams, In Progress) is the natural parent by
  subject matter: every moved task is billing-domain work with billing-domain gates.
- `task linear:sync` currently targets **PULSE / Declared-State Funnel**, which is where every
  other change in this repo lands, and where the `[DNA-nnn]` ids already carried on the moved
  tasks were issued.

Whichever wins, the proposal needs either a project override in the sync config or an explicit
decision to keep the change under PULSE. Decide before `task linear:sync` runs on the new change,
not after — the ids are already minted and re-homing them by hand is the failure mode.
