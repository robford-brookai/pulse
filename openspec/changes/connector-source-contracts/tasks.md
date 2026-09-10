## 1. Shared source contract

Queued implementation; each task is bounded to max 2h and starts with the named synthetic test. This plan does not implement POCAR/PAP transports or access live data. Future test paths below are relative to `packages/pulse-core/`; the proposal coverage test is `tests/test_connector_source_plan.py` at repository root. No task dispatch occurs here. Dependencies on source discovery are admission evidence, not invented schemas.

- [ ] 1.1 Add versioned manifest validation and unknown-capability readiness failures; test `tests/test_connector_source_manifest.py` (max 2h). [model: sonnet | deps: none | lane: repo_change | wave: 0]
- [ ] 1.2 Add identity namespace/incarnation and merge-hold conformance fixtures; test `tests/test_connector_source_identity.py` (max 2h). [model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]
- [ ] 1.3 Add paginated-source consistency and expired-token conformance fixtures; test `tests/test_connector_source_pagination.py` (max 2h). [model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]
- [ ] 1.4 Add mode-selected change-position, deletion and retention-gap conformance fixtures for polling, CDC and push; test `tests/test_connector_source_change_capture.py` (max 2h). [model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]
- [ ] 1.5 Add snapshot/live observation-identity, missing-history and time-evidence conformance fixtures; test `tests/test_connector_source_handover.py` (max 2h). [model: sonnet | deps: 1.2,1.3,1.4 | lane: repo_change | wave: 2]
- [ ] 1.6 Add adapter budget and bounded-backpressure conformance fixtures using fake clocks; test `tests/test_connector_source_budgets.py` (max 2h). [model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]
- [ ] 1.7 Add source-schema and mapping-version compatibility conformance fixtures; test `tests/test_connector_source_schema.py` (max 2h). [model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]
- [ ] 1.8 Add durable-disposition, lost-acknowledgement and protected-error conformance fixtures using existing kit APIs; test `tests/test_connector_source_recovery.py` (max 2h). [model: sonnet | deps: 1.5,1.6,1.7 | lane: repo_change | wave: 3]
- [ ] 1.9 Add completeness receipt validation and publish the owned source-contract runbook, authoring authority map and separate demo-reader boundary; test `tests/test_connector_source_reconciliation.py` (max 2h). [model: sonnet | deps: 1.8 | lane: repo_change | wave: 4]
