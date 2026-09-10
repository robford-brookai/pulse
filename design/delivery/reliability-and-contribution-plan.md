# Reliability and first-contribution improvement plan

**Status:** Proposed, queued for review; no implementation dispatched
**Date:** 2026-09-10
**Source baseline:** `2ed0552928ec8aee8cdfcdce8df2fa51d8346055`

The owner requested actionable OpenSpec proposals following a repository review. The review's
7.5/10 overall and 6.5/10 DevEx ratings were subjective judgments, not reproduced measurements or
new acceptance gates. In particular, the DevEx score understated the value of the 42 closed
findings and the restored scaffold path. This plan preserves those fixes and measures remaining
work by observable outcomes. Filing or completing tasks does not itself earn a numeric rating.

## Proposed changes

Each change contains proposal, design, delta specs, unchecked implementation tasks and
`traceability.json`. Every scenario maps to task owners; live lanes and external prerequisites
are explicit. Baseline specs remain unchanged until normal doc-update/archive.

| Change | Completion evidence | Scope boundary |
|---|---|---|
| `relay-fairness` | Real-Postgres concurrency and synthetic skewed-load evidence demonstrate finite-cycle service, retries and late-redrive correctness | Relay selection/ownership; existing consumer contracts retained |
| `idempotency-integrity` | Valid retries survive; conflicting reuse writes nothing and reveals no prior result; legacy migration and every ingress pass | D16 tightening; compatibility evidence gates enforcement |
| `critical-path-verification` | Mandatory database/transport suites execute; missing prerequisites fail; coverage and exclusions are visible | No blanket legacy rewrite; reachable security defects remain blockers |
| `observability` | Monitors and attended fault receipts show detection, retained work and restored conformance | Reuses probes; no invented owner, new SLO or production paging activation |
| `environment-matrix` | Verified synthetic staging, immutable release parity, actual image/migration identity and rollback receipts | Held on seed/runtime receipts; production/billing cutover separate |
| `connector-first-contribution` | Both directions reach a real first commit with hooks; green check leaves no unrelated diff; independent walkthrough passes | Credits the 42 fixes; no resumed audit loop or cosmetic score chase |

## Existing work retains credit and ownership

| Existing work | Disposition |
|---|---|
| Main CI at the review baseline | Passed; proposal validation is checked separately on this PR |
| Warehouse-sync heartbeat/liveness and token-expiry paths | Implemented; observability verifies deployed behavior instead of reimplementing it |
| `reconciliation-sweeps` | Repo tasks checked; attended first run and clean-cycle evidence remain owned there |
| `m1-retire-patient-state` | Code landed; attended migration/rebuild/conformance proof remains owned there |
| Demo 5/rebuild drill | Prior dev run reported; retain receipts and resolve documentation disagreements before closing release gates |
| Synthea regeneration | Fixes exist; a successful verification matching the committed manifest was not established in this review |
| `devex-eight` through `devex-eight-4` | 42 findings closed, seven carried; history/frozen protocol preserved, loop paused |
| `billing-cutover` seed | Full billing-month window and business decision remain there; neither initiated here |

## Queue and sequencing

These are queued proposals, not six additional executing changes. The two-change limit continues
to apply. Existing active changes keep their slots until the coordinator resolves their state
from tracked artifacts and receipts. Directory presence alone is not permission to dispatch this
queue. Read this plan and each change's external holds before `task dispatch`; the current
dispatcher validates local dependencies, not these cross-change prerequisites.

1. Finish the currently owned attended reconciliation/M1 work when prerequisites permit it.
2. Give the next free slot to `critical-path-verification`; another free slot may take
   `relay-fairness`. Named root/infrastructure edits remain serial.
3. Take `idempotency-integrity` after mandatory database mode is available. Avoid concurrent
   schema/commit edits with relay integration on the same files.
4. `observability` can use a free slot for isolated dev proof. `environment-matrix` waits for
   verified Synthea input, a free slot and D14 runtime evidence. Coordinate shared deploy files.
5. `connector-first-contribution` is bounded contribution work, not the program's critical path.
   Upstream template receipts gate its dependent import. Stop when its outcomes pass.

**Environment seed planning exception proposed:** the owner requested the required proposals
now. This PR brings the seed's plan to review before its entry receipts are verified; it does not
clear those gates. The original pre-proposal checks become pre-dispatch holds for this queued
proposal only. Ordinary PR review is the review surface for that sequencing decision. Runtime
selection, approval policy and execution concurrency remain governed by their existing decisions.

## Acceptance and reassessment

Reassess from one immutable release and its linked evidence. Readiness requires:

- Correctness scenarios for collisions, concurrency, backoff, redrive and migration passing
  against real dependencies, with required cases neither skipped nor uncollected.
- Actual deployed release identity and synthetic staging smoke/rebuild/rollback evidence.
- Failure detection/recovery plus the existing full reconciliation-cycle and M1 live receipts.
  A synthetic one-patient run does not substitute for a full cycle.
- Confirmed dispositions for reachable legacy security debt; an exclusion inventory is not closure.
- A working first-contribution journey and independent walkthrough, with completed fixes credited
  and cosmetic/social dimensions excluded from acceptance.

Monthly production SLO attainment, staffing and production cutover are separate evidence; no
proposal, test count or one-off dev drill is represented as proving them.

## Validation and shipping

Run `openspec validate <change> --strict` and `task replan CHANGE=<change>` for each proposal
(validation only; no work orders). Twelve tests in
`tests/test_reliability_proposal_traceability.py` check scenario/task coverage, dependency graphs,
live lanes and external holds, including after archive. Run `task check` before committing and
watch the ready PR's CI. Planning checks do not complete implementation checkboxes.
