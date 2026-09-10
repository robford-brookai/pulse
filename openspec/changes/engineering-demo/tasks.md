# Tasks — engineering-demo

Queued proposal; no implementation boxes are complete. Every repo task is a maximum two-hour slice, writes the named test first, and produces one commit and HANDOFF. Replan if discovery expands a slice. External entry gates: reviewed connector-source-contracts manifest/conformance contract before 1.1; two active-change slots, reviewed source contracts, and exact owning task/PR for shared relay/genesis work (design decision 2); no duplicate loader or relay. Live lanes are attended GitHub-issue work after runbook merge, never Linear work orders. Long runs checkpoint between bounded sessions.

- [ ] 1.1 Verify source/API contract metadata from Fonzie references; write the attended discovery runbook and a mapping-manifest validator that refuses absent grain, identity, provenance or API routes. Record owning tasks for pocar-relay and genesis shared work before dispatch.
      Tests: `test_demo_contract_manifest.py`.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0]`

- [ ] 1.2 Execute the merged discovery runbook for POCAR and PAP in an attended session; record a metadata-only mapping for one family per source, evidence limitations and exact API routes on the GitHub receipt. Block and replan any unsupported family.
      Tests: `runbook assertions: both source contracts and read-only access`.
      `[model: sonnet | deps: 1.1 | lane: operational_discovery | wave: 1]`

- [ ] 2.1 Implement the verified POCAR family mapper using the connector kit with synthetic contract fixtures, identity/quarantine behavior and source provenance; register the ingress with the producer registry.
      Tests: `test_demo_pocar_mapping.py`.
      `[model: sonnet | deps: 1.2 | lane: repo_change | wave: 2 | serial: shared registry, model or demo command surfaces]`

- [ ] 2.2 Implement the verified PAP family mapper using the same kit, with synthetic contract fixtures, identity/quarantine behavior and provenance; update its producer registry row.
      Tests: `test_demo_pap_mapping.py`.
      `[model: sonnet | deps: 2.1 | lane: repo_change | wave: 3 | serial: shared registry, model or demo command surfaces]`

- [ ] 2.3 Wire bounded read-only extraction for both verified families to their mappers, with stable snapshot/version markers and paging; prove extraction overlap accounting using fake source clients. Reuse archaeology for Mongo.
      Tests: `test_demo_source_extraction.py`.
      `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 4]`

- [ ] 2.4 Add executable command/state/history API round trips for both adapters, appended transition preservation, exact retry and conflicting-key assertions. Replan a missing API contract instead of bypassing it.
      Tests: `test_demo_api_roundtrip.py`.
      `[model: sonnet | deps: 2.3 | lane: repo_change | wave: 5]`

- [ ] 3.1 Implement the shared batch manifest and durable row-checkpoint seam for current-state hydration through the API, including uncertain acknowledgements and restart reconciliation; reuse the genesis owner implementation where present.
      Tests: `test_demo_batch_resume.py`.
      `[model: sonnet | deps: 2.4 | lane: repo_change | wave: 6]`

- [ ] 3.2 Wire the evidenced historical batch phase to versioned adjudication outputs; test effective/recorded time, unsupported-history quarantine and preservation of current state. Publish any dbt dependency by owning-repo contract.
      Tests: `test_demo_history_batch.py`.
      `[model: sonnet | deps: 3.1 | lane: repo_change | wave: 7]`

- [ ] 4.1 Add the verified Twenty object/relationship/state/key-event mapping for both families and provenance links, using existing model provisioning seams; snapshot the expected model for contract tests.
      Tests: `test_demo_twenty_model.py`.
      `[model: sonnet | deps: 2.4 | lane: repo_change | wave: 6 | serial: shared registry, model or demo command surfaces]`

- [ ] 4.2 Extend the existing projector for those mappings and prove duplicate/late delivery, freshness visibility, API agreement and projection-only rebuild without modifying ledger history.
      Tests: `test_demo_twenty_rebuild.py`.
      `[model: sonnet | deps: 4.1 | lane: repo_change | wave: 7]`

- [ ] 5.1 Define disposable target manifests and preflight ownership checks across database, Twenty, warehouse and delivery resources; replace hardcoded shared demo targets with explicit isolated target configuration.
      Tests: `test_demo_target_isolation.py`.
      `[model: sonnet | deps: 3.2, 4.2 | lane: repo_change | wave: 8 | serial: shared registry, model or demo command surfaces]`

- [ ] 5.2 Implement demo-only producer fencing and reset with dry-run target preview, refusal before mutation, full-graph zero assertions and protection against delayed old-run delivery.
      Tests: `test_demo_reset.py`.
      `[model: sonnet | deps: 5.1 | lane: repo_change | wave: 9]`

- [ ] 5.3 Add the runnable stage runner and fresh reload assertions, reusing Demo5 transport/assertion seams; preserve existing commands and fail nonzero on unmet assertions.
      Tests: `test_demo_stage_runner.py`.
      `[model: sonnet | deps: 5.2 | lane: repo_change | wave: 10 | serial: shared registry, model or demo command surfaces]`

- [ ] 6.1 Add the presenter walkthrough and correlated detail/cohort views with measured counts, throughput, retries, quarantine, lag and reconciliation. Show actual API requests/responses and Twenty event lineage using synthetic data.
      Tests: `test_demo_presentation.py`.
      `[model: sonnet | deps: 5.3 | lane: repo_change | wave: 11]`

- [ ] 6.2 Write the real-data rehearsal and reset runbook with bounded cohort selection, approved-boundary preflight, failure/bug receipt schema and synthetic-versus-real outcome fields.
      Tests: `test_demo_rehearsal_receipt.py`.
      `[model: sonnet | deps: 6.1 | lane: repo_change | wave: 12]`

- [ ] 6.3 Run synthetic acceptance from a clean disposable environment; capture each stage including induced failure, batch resume, projection rebuild and reset/reload. Record regressions with reproducing tests and rerun failed stages before acceptance.
      Tests: `test_demo_acceptance.py`.
      `[model: sonnet | deps: 6.2 | lane: repo_change | wave: 13]`

- [ ] 7.1 Conduct the attended bounded real-data rehearsal after its runbook merges, tracking a GitHub issue and aggregate receipt; test both source API paths, historical batch evidence and projection agreement.
      Tests: `runbook assertions: real-source acceptance and no PHI in shared receipts`.
      `[model: sonnet | deps: 6.3 | lane: operational_discovery | wave: 14]`

- [ ] 7.2 Conduct the attended demo-only reset and reload against the reviewed exact target manifest; record zero counts, old-run fencing and reload agreement on its GitHub issue.
      Tests: `runbook assertions: full-graph zero and fresh reload`.
      `[model: sonnet | deps: 7.1 | lane: destructive_ops | wave: 15]`
