# Handoff Summary: relay-fairness

Collected 3 handoff(s).

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

## Doc-Updater Instructions

1. For each spec-relevant update inlined above, edit the corresponding file in:
   `openspec/changes/relay-fairness/specs/`
2. Run `openspec validate relay-fairness` to check format.
3. Run `openlore drift` to check for new drift.
4. Ignore implementation details — only apply plan-relevant changes.
5. A `## Design Drift` section above means flag for human review.
