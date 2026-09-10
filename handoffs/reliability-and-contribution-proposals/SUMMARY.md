# HANDOFF

**Worktree:** proposal/reliability-and-onboarding
**Task:** File the owner-requested improvement proposals
**Date:** 2026-09-10

## Spec Updates

The doc-updater authored delta specs for `relay-fairness`, `idempotency-integrity`,
`critical-path-verification`, `observability`, `environment-matrix`, and
`connector-first-contribution`. Baseline `openspec/specs/` files are unchanged. Implementation
tasks remain unchecked; these deltas describe proposed behavior, not completed implementation.

## Design Drift

Idempotency conflicts deliberately tighten D16's currently accepted collision semantics; the
ADR amendment and producer compatibility evidence gate rollout. The environment proposal carries
a reviewable pre-proposal-to-pre-dispatch sequencing exception to its seed, retaining Synthea,
runtime-selection and concurrency holds. The delivery plan records that proposed decision.
No current spec gap was silently implemented.

## New Scenarios

Fifty scenarios across six deltas map to task owners in each change's `traceability.json`, covering
fair relay service, authenticated replay, mandatory assurance, recovery, promotion and contribution.

## Notes for Doc-Updater

Reconciliation and M1 retain their outstanding attended receipts and exit criteria. Preserve the
42 closed DevEx findings and frozen audit history; do not restart its numeric loop. The delivery
plan defines evidence for reassessment, not a promised score or readiness certification.
