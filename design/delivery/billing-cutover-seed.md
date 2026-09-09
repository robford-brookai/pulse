# Billing Cutover — proposal seed

**Status:** Seed, not a proposal · 2026-09-08 · **Source decision:** `billing-connector`
`design.md` decision 11 · **Inherits:** `packages/billing-connector` and `packages/billing` as they
stand on `main` at archive

---

## 0. TL;DR

`billing-connector` was cut at task 3.2 on 2026-09-08. The connector (package, configuration,
evaluate, declare, service, deploy artifacts, contracts) stays in that change and archives. The
reconciliation window and the cutover that retires the relay's Snowflake mart read become a
`billing-cutover` change, queued until its entry gates clear. No production billing cutover is
planned at this time (Rob, 2026-09-08). This document is the durable carrier for what moved: the
four tasks verbatim, the entry gates, and the delta spec text lifted out of `billing-connector`.
It records the deferral decision and nothing else. Writing the proposal is a later act.

---

## 1. Why this exists

The connector can evaluate and declare, but proving it matches the mart it would replace takes a
calendar month of parallel running on dev (one full billing month), and retiring the relay's mart
read is a **BREAKING** change to the verdict write path that needs a decision to take it. Neither
is wanted now. Leaving the four tasks open inside `billing-connector` would hold a change slot
indefinitely for work nobody has scheduled, and the sweep (former 4.1) is blocked on a commit in
another repo regardless. The same seam move `connector-pattern` made with decision 9 applies here:
archive the connector as shipped, carry the window and cutover forward on their own gates.

---

## 2. The moved tasks

Copied verbatim from `openspec/changes/billing-connector/tasks.md` at `main` (`9423af9`), with
their annotations and Linear id tokens. Numbers are the originals; renumber when the proposal is
written, not here. `deps` still name `billing-connector` task numbers (3.1, 3.2), which will be
archived: retarget them to this change's own tasks or to "entry" when proposing.

## 4. Wave 3 — reconciliation window

- [ ] 4.1 [DNA-1281] `verdict-reconcile` schedules entry: per-(subject, verdict_type)
      comparison of `evaluations` vs mart rows over matching fact windows; diff report with
      counts and subject keys only; empty-or-explained state machine for entries (spec:
      verdict-reconciliation, all three requirements). Blocked until the dbt spike files land
      in `data-platform` (seed gate 3) — the fixture mart is built from that commit.
      Tests: fixture mart + fixture evaluations produce the golden diff shapes — agree,
      timing-artifact, genuine divergence; PHI tripwire on report output.
      `[model: sonnet | deps: 3.1 | lane: repo_change | wave: 3]`

- [ ] 4.2 Open the window (live execution): GitHub tracking issue + runbook PR; attended start
      of the connector service on dev; both writers live; sweep scheduled; first sweep receipt
      on the issue. Window runs one full billing month.
      Tests (runbook assertions): connector declares on a live episode event without a
      scheduled run; sweep receipt posts; both writers' receipts attributable.
      `[model: sonnet | deps: 3.2, 4.1 | lane: operational_discovery | wave: 3]`

## 5. Wave 4 — cutover (gated on the 4.2 window closing empty-or-explained)

- [ ] 5.1 Cutover runbook PR + attended run: stop the relay poll, retire its Snowflake
      credential, closing sweep report committed as the receipt (spec: verdict-mart-read
      retirement requirement).
      Tests (runbook assertions): no Snowflake credential on the write path; connector-only
      verdicts continue; rollback rehearsed (re-enable poll from config).
      `[model: sonnet | deps: 4.2 | lane: destructive_ops | wave: 4]`

- [ ] 5.2 [DNA-1282] Docs close-out via `HANDOFF.md`: ADR for the write-path supersession,
      `consumes.md` mart row demoted, fonzie dependency-spec gap 1 note updated.
      Tests: `mkdocs build -s`; contract-doc gates; `task check` green.
      `[model: sonnet | deps: 5.1 | lane: repo_change | wave: 4]`

Note on lanes: 4.2 is `operational_discovery` and 5.1 is `destructive_ops`. Both are live execution
per `WORKFLOW.md` (GitHub issue + runbook PR + attended run), never a worktree.

---

## 3. Entry gates

Three things must clear before this change is proposed.

### Gate 1 — a durable dbt source to diff against (seed gate 3, carried)

The dbt spike files (`management/models/billing/verdict/` in `brookai/data-platform`) were still
uncommitted on a spike branch when the ask was recorded on 2026-09-02
(`docs/contracts/consumes.md`, "Cross-repo ask"). The sweep's fixture mart is built from that
commit. Clears when the branch lands on `data-platform` main and the path can be cited.

### Gate 2 — a cutover decision

On 2026-09-08 the decision was: no production billing cutover at this time. Clears when that
decision is reversed and recorded here with a date and the deciding owner. Until then the relay's
mart read stays on the write path and `docs/contracts/consumes.md`'s verdict mart row stands
undemoted.

### Gate 3 — serial-lane coordination with `reconciliation-sweeps`

Task 4.1 adds a `verdict-reconcile` entry to the generated schedule catalog
(`packages/schedules/infra/terraform/generated/schedule_catalog.auto.tfvars.json`). The queued
`reconciliation-sweeps` change extends the same file. Whichever is proposed second must name the
other in its serial-lane annotations, and the two must never dispatch a catalog-touching task in
the same wave.

### Carried open question

Whether the sweep also back-checks the mart's historical seed rows or only the window. Decidable
when the window opens; changes no spec or task.

---

## 4. The moved delta spec text

Lifted verbatim from `openspec/changes/billing-connector/specs/` on 2026-09-08 and demoted one
heading level. `verdict-reconciliation` moved whole (a new capability). `verdict-mart-read`'s
retirement requirement moved (a modification of the existing baseline capability). Both directories
were deleted from the change. Seed the new change's delta specs from these; do not re-derive them.

### 4.1 Capability: `verdict-reconciliation` (moved whole, ADDED)

### Purpose

The proof that the in-pulse billing connector matches the mart it replaces: a parallel-run
window in which both compute verdicts, a per-subject comparison, and an empty-or-explained
diff as the gate the cutover cannot pass without.

### ADDED Requirements

#### Requirement: Connector and mart run in parallel for a full billing month
During the reconciliation window, at least one complete billing month, the connector SHALL
declare verdicts on the live path while the mart relay continues declaring exactly as today,
and the ledger SHALL remain consistent under both writers: the pairing idempotency and
per-subject `as_of` monotonicity rules decide which declaration moves state, and the window
SHALL surface every disagreement rather than letting either writer silently win.

##### Scenario: Both writers, one consistent ledger
- **GIVEN** the connector and the mart relay both active during the window
- **WHEN** both declare verdicts for the same subject
- **THEN** every declaration is attributed to its writer, replays and stale skips are counted
  per writer, and the subject's state of record reflects the pairing rules, never an
  unexplained overwrite

#### Requirement: The reconciliation sweep produces an empty-or-explained diff
A reconciliation sweep SHALL compare, per subject and verdict type, the connector's verdicts
against the mart's for the same facts, and SHALL produce a diff report in which every
disagreement is either absent or carries a written explanation (a timing artifact, a known
rule divergence with a decision record). The report SHALL carry counts and subject keys only,
never payload values or payer identifiers.

##### Scenario: A divergence is named, not averaged away
- **GIVEN** one subject where the connector says positive and the mart says negative
- **WHEN** the sweep runs
- **THEN** the report names that subject key and verdict type as a disagreement requiring
  explanation, and the window cannot close while it stands unexplained

#### Requirement: Cutover is gated on the reconciliation receipt
The mart read path SHALL NOT be decommissioned until a full window's sweep reports
empty-or-explained, and the closing report SHALL be committed as the receipt on the change's
tracking record.

##### Scenario: An unexplained diff blocks the cutover
- **GIVEN** a window whose final sweep carries one unexplained disagreement
- **WHEN** cutover is proposed
- **THEN** the gate fails citing that disagreement, and the relay's mart read keeps running

### 4.2 Capability: `verdict-mart-read` (retirement requirement, MODIFIED)

### ADDED Requirements

#### Requirement: The mart read retires behind the reconciliation gate
Once the verdict-reconciliation gate passes (a full billing month's sweep, empty-or-explained),
the relay's mart read SHALL be decommissioned: the scheduled poll stops, the relay's Snowflake
credential is retired, and the mart becomes an analytics and reconciliation surface only. No
pulse write path SHALL depend on it. Until that gate passes, this capability's existing
requirements stand unchanged and the poll keeps running.

##### Scenario: Retirement follows the gate, not the calendar
- **GIVEN** the reconciliation window still open or its diff not yet empty-or-explained
- **WHEN** any change proposes stopping the mart poll
- **THEN** the gate refuses and the poll and its cursor semantics remain in force

##### Scenario: After retirement, the write path has no warehouse dependency
- **GIVEN** the gate passed and the mart read decommissioned
- **WHEN** the verdict write path's runtime configuration is inspected
- **THEN** no Snowflake credential remains on it, and verdicts flow only from the connector's
  event-driven evaluation

---

## 5. Linear home

Team DNA, project Pulse 1.0, parent `[CHANGE] billing-cutover` in Backlog. The two minted ids
carried on the moved tasks, DNA-1281 (4.1) and DNA-1282 (5.2), stay as they are and are reparented
under that parent; they are not re-minted (`billing-connector` design.md decision 10). Tasks 4.2 and
5.1 are live execution and never get Linear sub-issues; they are tracked as GitHub issues when the
change is proposed.
