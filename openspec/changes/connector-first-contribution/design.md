## Context

The September 9 handoff records 42/49 findings closed. Audit 5 corrected its own claim: scaffold-to-green succeeds, first commit is the remaining failure. Several score deductions describe presentation or community dimensions rather than an unusable connector. This proposal does not import that score as a baseline.

## Goals / Non-Goals

**Goals:** Make the supported first contribution succeed and prove it without another rubric loop.

**Non-Goals:** Opening devex-eight-5, clearing cosmetic findings to obtain a number, editing CHECKSUMS or historical scores, demanding a second maintainer, or expanding the tool stack.

## Decisions

### 1. Acceptance is an executable user journey

In isolated clones: documented install → green task check → scaffold inbound/outbound connector →
documented dependency sync → green task check → stage intended files → real git commit with the
repo's production hooks enabled. No --no-verify, staged-file exclusions, disabled drift checks or
manual package-count edits. Exercise both connector directions together to catch namespace collisions.
Use a fixture identity/local repository; no GitHub write is necessary for the automated journey.
Record elapsed time diagnostically with machine/cache/tool versions; no arbitrary speed cutoff.

### 2. Fix only demonstrated blockers

Initialize OpenLore exactly as task lore:init already does, preserve hook policy, derive package/doc
expectations from the actual workspace, and put runtime timings in a gitignored file while retaining
historical audit rows. A green check leaves git diff empty apart from intended connector edits.
Each failing fixture becomes a regression test. Do not rework successful APIs or optimize a number.
Where a previously strict-xfail test now passes, remove only that resolved marker; preserve others.

### 3. Template ownership and bounded execution

Before patching, identify whether each defect originates in rob-ade or a PULSE-specific gate.
Template changes must be implemented upstream and imported by template:sync; do not copy a downstream
fork here. Publish the upstream PR/commit receipt before the dependent sync task dispatches. The
cross-repo work is its own tracked prerequisite with one focused task/commit, not a side-clone inside
PULSE. At most the three demonstrated defect families above are in scope. Newly discovered unrelated
issues receive a separate proposal instead of another audit wave.

### 4. Independent walkthrough and stopping rule

After the automated journey passes, one engineer other than the implementer follows the same guide
in a fresh environment. Record commands, step outcomes, interventions and time; do not invent a
participant or send an invitation while filing. Success is both directions passing and the first
commit landing without undocumented fixes, plus no unrelated tracked-file changes. One walkthrough;
if blocked, reproduce and fix the concrete in-scope defect, then rerun only its failed segment.
Stop when these outcomes hold. Remaining cosmetic findings remain visible, not erased.
Proposed 2026-09-10 following the owner's instruction to improve outcomes without repeating PR thrash.

## Risks / Trade-offs

[Nested full gate becomes expensive] → keep real-clone journey in the explicit slow acceptance target; fast regression cases stay in task check. [Upstream template unavailable] → dependent sync remains blocked with concrete patch/receipt. [Walkthrough participant unavailable] → mark that evidence pending rather than fabricate completion.

## Migration Plan

Reproduce the three defect families, land upstream-owned fixes and PULSE-owned fixes through their proper PRs, import the template update, run both generated paths with hooks, then one attended independent walkthrough. Archive this change when outcomes pass; leave the previous audit loop paused.
