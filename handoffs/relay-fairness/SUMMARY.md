# Handoff Summary: relay-fairness

Collected 4 handoff(s).

## relay-fairness-task-001

### Added Requirements

None — this task adds the scan primitives the "Independent ready subjects receive bounded fair
service" requirement (`openspec/changes/relay-fairness/specs/ledger-distribution/spec.md`) already
describes. No wording change needed.

### Modified Requirements

None.

### Removed Requirements

None.

## Design Drift

None. `pulse_ledger.relay` gained `candidate_subjects()`, `ScanState`, `SubjectStatus`,
`ScanResult`, and `scan_pass()` as pure additions alongside the existing `pending_rows()` /
`relay_once()` — nothing about `relay_once`'s current selection or `relay_worker.py` changed in
this task; wiring the scan into selection is task 1.2.

## New Scenarios

None beyond what `traceability.json` already maps to this task's two spec scenarios ("Skewed
backlog cannot starve an independent subject", "Locked and backing-off heads do not monopolize
scans").

## relay-fairness-task-002

### Added Requirements

None — this task implements the "Publication uses current state under subject ownership" ADDED
requirement and its "Concurrent relays recheck completed rows" scenario, already present in
`specs/ledger-distribution/spec.md`, and wires the 1.1 fairness scan into publication.

### Modified Requirements

None.

### Removed Requirements

None.

## Design Drift

None. Followed design.md decision 1 (fair subject selection, per-subject row budget) and decision 2
(lock then re-read) as written.

## New Scenarios

None beyond what's already in the spec; the tests added here (`test_relay_fairness.py`) exercise
existing scenarios rather than proposing new ones.

## relay-fairness-task-003

## Spec Updates

None. Task 2.1 is regression evidence: the retry, dead-letter and manual-redrive policy the
`ledger-distribution` spec already states is now proved to hold on the fair-pass publication path
(`relay_fair_pass` / `_relay_locked_subject`), not only on `relay_once`'s grouping path. No
production code changed — `relay.py` needed no fix for the proof.

### Added Requirements

None.

### Modified Requirements

None.

### Removed Requirements

None.

## Design Drift

None found. Two behaviours worth recording as confirmed rather than corrected, because both are
consequences of the design that the spec text does not spell out:

1. **Two guards, not one, keep a backing-off head from being bypassed.** The scan's eligibility
   probe skips a subject whose *head* is inside its retry window, so that subject is never selected.
   A row that backs off *behind* a due head is invisible to that probe, and there only the
   per-subject publication stop (first row inside its window ends the subject for the pass) holds
   the ordering. Both are now pinned by tests; a change to either alone would leave the scenario
   "the backed-off head is not bypassed" only half-enforced.
2. **The scan's probe opens a genuine window.** `scan_pass` decides eligibility for every selected
   subject up front and releases each probe lock immediately, so a subject free at probe time can
   be owned by another relay by the time the pass reaches it. The publish acquisition's
   not-acquired branch is what prevents a second concurrent delivery there — it is load-bearing,
   not defensive.

## New Scenarios

The scenarios below are already covered by the change's existing requirements; they are offered as
optional sharpening of "Locked and backing-off heads do not monopolize scans" and "Concurrent
relays recheck completed rows", not as gaps.

- **A row inside its retry window is not overtaken within a pass**
  - GIVEN a subject whose head is due and whose later row is still inside its retry window
  - WHEN a worker publishes that subject under its lock
  - THEN publication stops at the waiting row and no later row of the subject is published ahead of
    it; both follow once the window has passed

- **A subject taken between the eligibility probe and the publish is deferred**
  - GIVEN a worker's scan found a subject eligible and another relay acquired that subject before
    the first worker's publish acquisition
  - WHEN the first worker reaches that subject in the same pass
  - THEN it does not publish on the strength of the stale probe; the subject is deferred and the row
    is delivered exactly once

## relay-fairness-task-004

### Added Requirements

None — no gap found. The existing "Consumers dedupe on `event_id`" and "manual redrive SHALL
be treated as a possible late delivery by consumers" language in the MODIFIED requirement
already covers what this task proved.

### Modified Requirements

None.

### Removed Requirements

None.

## Design Drift

None. `packages/twenty-projection` already implements the two-mechanism contract the spec
requires, and no production code changed to make the new tests pass.

## New Scenarios

Consider promoting this task's fixture-level proof into the spec's scenario list under
"Transport reorder and late redrive preserve projection correctness" (currently one GIVEN/WHEN/
THEN at the requirement level, with the mechanism left implicit):

- **GIVEN** a fixed reorder within one subject (a higher `seq` delivered before lower ones)
  **WHEN** the lower-`seq` events arrive after **THEN** the record converges on the highest
  `seq` only, and the lower-`seq` deliveries are no-ops, never overwrites.
- **GIVEN** the same `event_id` redelivered inside one consumer run **WHEN** it is processed
  **THEN** the in-process deduper (`pulse_core.connector.InMemoryDeduper`) is what suppresses
  the second apply — no second write is attempted at all.
- **GIVEN** a manually redriven dead-lettered row, carrying an `event_id` the consumer has
  never seen, arriving after a later `seq` has already landed **WHEN** it is processed **THEN**
  the *watermark* check (`is_watermark_stale` against the board's `projectionSeq`), not the
  deduper, is what makes it a no-op — the deduper has no memory of a redrive's event id.
- **GIVEN** a consumer process restart (a fresh in-process deduper, same board state) **WHEN**
  an already-applied event is redelivered **THEN** the watermark alone (not the deduper) still
  prevents a second write — proving the two mechanisms are independent, not one relying on
  the other.

## Doc-Updater Instructions

1. For each spec-relevant update inlined above, edit the corresponding file in:
   `openspec/changes/relay-fairness/specs/`
2. Run `openspec validate relay-fairness` to check format.
3. Run `openlore drift` to check for new drift.
4. Ignore implementation details — only apply plan-relevant changes.
5. A `## Design Drift` section above means flag for human review.
