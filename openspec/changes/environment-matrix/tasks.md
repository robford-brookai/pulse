# Tasks — environment-matrix

All implementation boxes are intentionally unchecked. Each repo-change task is a maximum
two-hour implementation slice, writes its named test first, produces one focused commit and
HANDOFF, and passes `task check`. If discovery exceeds that bound, replan before expanding it.
Live tasks are bounded attended sessions with runbook assertions and GitHub receipts, never
worktree jobs. Long loads or observation windows checkpoint between sessions.

**Entry gate:** this proposal is queued. The coordinator must first check the two active change
slots, external prerequisites in design.md, and shared-file serial lanes. `deps` lists only local
task IDs; external prerequisites are deliberate blocking conditions, not fake local task IDs.
No task is dispatched by filing or validating this proposal.

**External prerequisites:** before ANY task dispatch, verified Synthea run on main with repin=false and matching committed manifest, plus a free change slot. Before 2.1, attach the D14 runtime decision receipt or replan the adapter. See design.md decisions 1–2.

## 1. Foundations

- [ ] 1.1 After proposal entry receipts clear, implement environment-map and release-manifest schemas with strict required services/digests/migration/catalog/artifact identities and secret references. Test wrong target, mutable-only tag, missing component and mixed-release rejection.
      Tests: `tests/test_release_manifest.py`.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0]`

- [ ] 1.2 Implement pure tenant/registry/endpoint rendering for current Duplo templates and a dry-run comparison of desired versus actual service/migration identities. Runtime-specific execution stays held on the D14 receipt; fixture tests require no cluster.
      Tests: `tests/test_environment_rendering.py`.
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]`

## 2. Implementation and regression evidence

- [ ] 2.1 After the D14 runtime receipt is attached, repair the approved deploy adapter to push fully qualified digests and update API/relay consistently. Add readiness/deployed-digest/migration checks and explicit partial-failure output; test fake registry/runtime calls and prior-manifest recovery planning.
      Tests: `tests/test_release_deploy_adapter.py`.
      `[model: sonnet | deps: 1.2 | lane: repo_change | wave: 2 | serial: Taskfile.yml and runtime service definition surfaces]`

- [ ] 2.2 Implement successful-workflow artifact selection and checksum/toolchain provenance verification. Reject repin-only, failed/expired/mismatched artifacts and do not auto-repin; use fixture API responses and tiny local synthetic files.
      Tests: `tests/test_staging_artifact_verification.py`.
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]`

- [ ] 2.3 Wire a checkpointed synthetic loader through existing ingress with small offline fixtures and idempotent resume after interruption. Keep the 50k generation outside the inner loop; test repeated loading and wrong-environment refusal.
      Tests: `tests/test_staging_loader_resume.py`.
      `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2]`

## 3. Integration and acceptance

- [ ] 3.1 Compose existing Demo 5 and catalog round-trip fixtures into the staging smoke/rollback runbook and receipt validator. Test family coverage, signed heal-back, freshness, rebuild comparison, manifest parity and incompatible-migration refusal; no production promotion call.
      Tests: `tests/test_staging_release_receipt.py`.
      `[model: sonnet | deps: 2.1, 2.3 | lane: repo_change | wave: 3]`

## 4. Attended validation

- [ ] 4.1 Attend staging deployment/load after seed/D14/ownership prerequisites and runbook PRs merge. Use the verified 50k artifact and immutable release manifest; attach actual digests, migration heads and loader/smoke receipts to a GitHub issue. Pause/resume long loading via checkpoints rather than an unbounded work order.
      Tests: `runbook assertions: target isolation, artifact parity, catalog families, heal-back and freshness`.
      `[model: sonnet | deps: 3.1 | lane: operational_discovery | wave: 4]`

- [ ] 4.2 Attend an application rollback/re-promotion rehearsal on synthetic staging with a schema-compatible prior manifest. Prove rebuild equivalence and link the existing reconciliation clean-cycle/M1 receipts separately; leave production cutover and billing decision to their existing plans.
      Tests: `runbook assertions: previous compatible manifest restored, no journal deletion, replay/rebuild parity`.
      `[model: sonnet | deps: 4.1 | lane: operational_discovery | wave: 5]`

## Plan-validation receipt

Mechanical dependency/wave checks and OpenSpec strict validation run before filing. Scenario-to-task coverage is recorded in `traceability.json` beside this file; every scenario has an owner task and every task has acceptance coverage. The plan validation test checks that mapping, dependency references and cycles. Human semantic review remains the PR review surface; no implementation acceptance is checked off here.
