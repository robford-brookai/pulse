# G_MECE validation — `customerio-consent-ingress`

Read-only review, worktree at `/Users/Rob.Ford/Repos/pulse`, no edits made.

## 1. `openspec validate --strict`

**PASS** — `openspec validate customerio-consent-ingress --strict` → `Change 'customerio-consent-ingress' is valid`.

## 2. G_MECE — eight checks

1. **Every requirement has a scenario — PASS.** All 7 requirements in
   `specs/customerio-consent-ingress/spec.md` carry ≥1 scenario (8 scenarios total: lines 18, 34,
   49, 63, 70, 82, 95, 108).

2. **Tasks atomic (≤2h) — PASS.** `tasks.md` tasks 1.1–5.1 each scope to one module/file and mirror
   the granularity of the shipped `packages/verdict-relay` and `packages/schedules` precedents
   (`row_source.py`, `declarer.py` split into 3.1/3.2/3.3 specifically to avoid one oversized task).
   No task spans more than one module's worth of work.

3. **Scenario↔task bijection named inline — PASS.** All 8 scenarios map 1:1 to a task, quoted
   verbatim in the task body:
   - "The test suite runs with no live network" → 2.1 (`tasks.md:39`)
   - "A landed row becomes a command", "A declared command is customer.io-attributed and
     traceable", "Ingress and sweep address the same row identically" → 3.1 (`tasks.md:53-59`)
   - "A cursor resume replays its last page", "A full re-run over the same landing replays" → 3.2
     (`tasks.md:72-75`)
   - "A malformed row among valid ones", "A run receipt is safe to attach to logs" → 3.3
     (`tasks.md:87-90`)
   No scenario is claimed twice; none is orphaned.

4. **No scope overlap absent a dep edge — PASS.** `declarer.py` is edited by 3.1/3.2/3.3, each
   depending on its predecessor (`tasks.md:76-78`, `92-93`) with the overlap called out inline as
   the reason for the dep edge, not the wave. `consumes.md` (5.1) and the workspace root (1.1) are
   each flagged `serial:` and touched by exactly one task apiece. Wave-2 tasks 4.1/5.1 share no
   dep edge but touch disjoint files (`cli.py` vs `consumes.md`) — no violation.

5. **Deps explicit + existing — PASS.** Every task states `deps:`; every referenced task number
   (1.1, 2.1, 3.1, 3.2, 3.3) exists in the file. No forward or dangling reference.

6. **Model declared — PASS.** Every task carries `model:` explicitly (sonnet on 1.1/2.1/3.2/3.3/4.1/5.1,
   opus on 3.1).

7. **Serial flags justified — PASS.** `serial: workspace_roots` (1.1, `tasks.md:26`) and
   `serial: consumes_doc` (5.1, `tasks.md:115`) both name the shared file they'd otherwise race on.
   No unjustified serial flag; no missing one — 3.1→3.2→3.3's shared-file case is handled via
   `deps`, not `serial`, correctly (a dep edge inside one wave already serializes).

8. **Bijection / bijection = tasks that need it — PASS** (folded into #3; no separate gap found).

## 3. Change-specific checks

- **`{subject_key}:{channel}` grain, verbatim on both paths — PASS.**
  `consent-reconciliation`'s spec pins `{subject_key}:{channel}` composition, binding on "any other
  producer of `communication_consent` state (e.g. a forward consent ingress)"
  (`openspec/specs/consent-reconciliation/spec.md:50-54`). This change's spec Requirement 3
  (`spec.md:41-54`) and design Decision 3 (`design.md:71-77`) inherit that composition literally,
  and task 3.1 quotes it as binding (`tasks.md:44-46`). `consent_sweep.py`'s own
  `_ledger_key` (`packages/schedules/src/schedules/consent_sweep.py:186-188`) is the same
  `f"{subject_key}:{channel}"` — both paths agree.

- **Actor `customer.io` via per-service credential only, never a payload field — PASS.**
  Spec Requirement 2 (`spec.md:25-32`), design Context (`design.md:18-20`) and task 3.1
  (`tasks.md:49-51`, "this module writes no actor field anywhere") match ADR-0003's D15
  (`docs/adr/ADR-0003-*.md:34-35`, "a body carrying any actor field is rejected outright") and
  ADR-0005 (`docs/adr/ADR-0005-*.md:33`). Consistent with `consent_sweep.py`'s own precedent
  (lines 247-252).

- **D16 idempotency makes a re-read a replay — PASS.** Spec Requirement 4 (`spec.md:56-75`),
  design Decision 4 (`design.md:78-84`), task 3.2 (`tasks.md:65-78`) all key `logical_time` off the
  row's own event identity, never wall-clock — matching D16 (ADR-0003: `{writer_id}:sha256(...,
  logical_time)}`).

- **Package declares via command API only; producer-policy §4.4 claim is honest — PASS.**
  `producer-policy`'s spec scopes the gate to `packages/ocean` producer source only
  (`openspec/specs/producer-policy/spec.md:4,11,49`), confirmed by the existing
  `docs/contracts/consumes.md` gate entry. Design Decision 5 (`design.md:85-89`) and the proposal's
  "No producer-policy exposure" section (`proposal.md:26-29,53-55`) correctly state this package is
  not in the gate's scan scope and carries no catalog-state vocabulary — an accurate claim, not a
  false "stays green" dodge.

- **Snowflake read fixture-faked at a `RowSource`-style boundary, `--disable-socket`, in every
  test — PASS on stated posture**, same pattern as `mart_reader.RowSource`/`FixtureRowSource`
  (`packages/verdict-relay/src/verdict_relay/mart_reader.py:83-92,118-144`). Spec Requirement 7
  (`spec.md:102-112`), tasks.md header (`tasks.md:8-11`), design Decision 6 (`design.md:90-93`).

- **PHI bar — subject keys/channel names only, every PHI exit tested — PARTIAL / gap found.**
  Spec Requirement 6 (`spec.md:89-101`) and task 3.3 (`tasks.md:80-93`) test the receipt/log exit
  at the declarer layer with a synthetic contact-shaped fixture. But task 2.1 (`row_source.py`,
  the layer that performs "per-row contract validation before any row is yielded") has **no**
  malformed-row or PHI-in-error-message test at all — its only fixtures are "a normal page, a page
  split across a cursor boundary" (`tasks.md:37`). If `row_source.py` ever names/logs a rejected
  row the way `mart_reader._name_row` does (`mart_reader.py:196-204`, which only echoes pinned
  identifying columns, not the whole row — safe in that package because none of its
  `CONTRACT_COLUMNS` are contact fields), the equivalent path here is untested. Given the finding
  immediately below (validation-abort vs. count-and-continue is unresolved), this PHI gap and the
  correctness gap are the same underlying hole: it is not settled which module produces the "row
  named by reference, never by raw content" behavior for a malformed `cio_raw`/`cio_prod` row, so
  no task's tests currently cover it.

- **ADR-0005 citation accuracy — PASS.** `streamline.cio_raw`/`cio_prod`, no live API pull in v1,
  cited identically in `proposal.md:3-9`, `design.md:5-7`, and `spec.md` purpose/requirements,
  matching ADR-0005 verbatim (`docs/adr/ADR-0005-*.md:21-25`).

- **Propose receipt's flagged judgment calls — PASS (resolved/honestly open).** No standalone
  receipt file exists in the change folder, but both flagged calls are addressed in the artifacts
  themselves: package naming is resolved with a rejected-alternative rationale (design Decision 1,
  `design.md:54-60`); the placeholder row-contract columns (message/event id and event-timestamp
  field names are not yet pinned literally) are honestly left open, called out in Decision 2's
  rejected-alternative note (`design.md:66-70`) and the Risks section (`design.md:97-100`), with
  task 5.1 assigned to pin the real names in `docs/contracts/consumes.md` once task 2.1's
  `CONTRACT_COLUMNS` exist (`tasks.md:108-113`).

## 4. Finding — validation-abort vs. count-and-continue contradiction (the one real defect)

**FAIL.** Spec Requirement 5, "Malformed landing rows are counted and never dropped silently"
(`spec.md:76-87`), binds: a malformed row is counted and attached to the receipt, the run does
**not** abort, and the remaining rows in the same read **are still declared**.

Design Decision 2 (`design.md:61-70`) and task 2.1 (`tasks.md:31-40`) both specify that
`row_source.py` validates "per-row contract validation before any row is yielded
(`mart_reader._validated`'s shape)" — citing `mart_reader._validated`
(`packages/verdict-relay/src/verdict_relay/mart_reader.py:207-244`) as the reused pattern. But
`mart_reader._validated` **raises `MartContractError` uncaught**, which propagates out of
`MartReader.batches()` (`mart_reader.py:302-314`, `validated = [_validated(index, row) for
index, row in enumerate(raw_page)]` — a single bad row kills the whole page/run, per that module's
own docstring: "fails the run … before any row of its page is yielded — drift … surfaces here, not
as a half-declared batch"). That is the opposite of Requirement 5's binding contract.

The correct existing precedent for "count and never drop, don't abort" is
`consent_sweep.parse_export` (`packages/schedules/src/schedules/consent_sweep.py:142-161`), which
try/excepts each row into `rows`/`errors` and returns both, never raising past a single bad row —
design.md cites this module for the grain/receipt shape (Decision 3) but not for validation
behavior, even though it is the one that actually matches Requirement 5.

Consequence: no task owns the "validate but don't abort" behavior. Task 2.1's own test list has no
malformed-row fixture (`tasks.md:37`, only "a normal page, a page split across a cursor boundary")
— it tests the mart_reader-style path, which is abort-on-bad-row. Task 3.3 has the malformed-row
fixtures and tests (`tasks.md:85-90`), but 3.3 scopes to `declarer.py`, downstream of
`row_source.py` in the read→declare pipeline described by design Decision 2 — if `row_source.py`
raises per `mart_reader`'s shape, `declarer.py` never receives the page to do any counting on, and
3.3's own scenario ("A malformed row among valid ones") becomes unimplementable as designed.

**This must be resolved before dispatch**: either (a) `design.md` Decision 2 is corrected to cite
`consent_sweep.parse_export`'s catch-and-collect shape instead of `mart_reader._validated`'s
raise-and-abort shape, with task 2.1 gaining the malformed-row fixture/test it currently lacks, or
(b) the design explicitly states that `row_source.py` yields raw+error-tagged rows to
`declarer.py`, which does the counting — in which case task 2.1 needs a test asserting it never
raises on a bad row, and the PHI-in-error-reference posture for that yielded error needs its own
test (folding into the PHI gap above).
