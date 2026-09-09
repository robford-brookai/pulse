## Why

`connector-pattern` archived on 2026-09-02 with the connector kit, a billing engine that folds
facts and holds one ported rule module, and nothing that declares. Billing state on the ledger
still advances only when the warehouse mart happens to run. The six tasks that close that gap
(evaluate → declare, deploy, the reconciliation window, cutover) and their delta specs were
moved to `design/delivery/billing-connector-seed.md` by decision 9, together with four entry
gates. This change picks that leg up as the first connector built on the kit, in its own
package, and starts with small scaffold PRs so each seam (package, configuration, code tree,
test harness) is reviewable on its own before any behavior lands. Decisions taken with Rob
2026-09-02: new `packages/billing-connector` with the engine staying in `packages/billing`;
proposed now as a deliberate second change in flight alongside `pulse-demo-closeout`.

## What Changes

- **New package `packages/billing-connector`** on `pulse_core.connector`: the outbound half of
  billing. It consumes the engine's fact-snapshot changes, evaluates the rule modules the
  engine registers, and declares verdict plus paired transition through the kit's declare
  pipeline under one writer credential. It imports `packages/billing` for facts, store, and
  rules and owns none of them.
- **Scaffold first, in four PRs**: package and workspace wiring; configuration (credential
  name, queue, ledger base URL, staleness threshold — names in config, values from the
  environment); code-tree stubs with typed signatures mapped to spec requirements; test harness
  (socket-blocked conftest, fixture corpus, receipt golden). Each is its own child worktree
  and PR, each ships a test, none changes ledger behavior.
- **Evaluation → declare** (the moved 3.4), split in two: evaluation writes `evaluations`
  receipts from fact snapshots; declaration submits the pair through the kit with D16 keys and
  extends the receipt line with `evaluated=N`. Staleness comes from the consume-loop watermark.
- **Deploy artifacts** (the moved 3.5): Duplo service JSON, queue/DLQ/rule provisioning,
  runbook. Never reachable from `task check`.
- **Reconciliation window and cutover** (the moved 4.1, 4.2, 5.1, 5.2): moved out again on
  2026-09-08 to the queued `billing-cutover` change (design.md decision 11). No production
  billing cutover is planned at this time. The relay's mart read keeps running, and this change
  ends with the connector deploy-ready on dev.
- **Scope narrowed on entry**: the connector evaluates the verdict types the rules package
  registers (today one, `billing_eligibility`), and its first triggers are episode-subject and
  coverage-subject events. Consent and enrollment fan-out to episodes is gated on a catalog
  fact that does not exist yet (see design.md decision 4).

Out of scope: adding `coverage_eligibility` or `benefits_verification` rules (no dbt source in
the pinned scope; gate 1 in the seed); any warehouse read on the write path; other connectors.

## Capabilities

### New Capabilities
- `billing-connector`: the connector's behavior contract — event-driven evaluation with
  bounded latency, attributed and versioned verdict pairs, staleness from the watermark, one
  credential and no ledger internals, receipts, and the amount-free boundary at its seam.

Moved to `billing-cutover` on 2026-09-08 (design.md decision 11): `verdict-reconciliation`
(new) and the `verdict-mart-read` retirement requirement (modified). Their text is carried in
`design/delivery/billing-cutover-seed.md` §4.

## Impact

- **Code**: new `packages/billing-connector`; `packages/billing` gains a registry of rule
  modules if it lacks one (additive); workspace `pyproject.toml` and `Taskfile.yml` lint,
  typecheck, and test lists; the credential-posture gate discovers the new package.
- **Contracts**: `publishes.md` (billing-connector as producer on `patient-state`),
  `consumes.md` (mart row unchanged; its demotion moves with the cutover), `producer-registry.md` (engine row already
  present from 1.1 of connector-pattern), `billing-boundary.md` (seam moves with the logic);
  the write-path ADR moves with the cutover.
- **Runtime**: one new bus consumer (rule, queue, DLQ), one new writer credential
  `billing-connector`. Dev deploy only; the window and cutover moved to `billing-cutover`.
- **Workflow**: two changes in flight until `pulse-demo-closeout` archives. `task` commands
  take `CHANGE=` explicitly, and state resolution is per change, so tooling is unaffected; the
  `<id>` convention in CLAUDE.md is the one place the assumption is written.

## Rollback

Scaffold PRs are additive and removable package by package. Before cutover, rollback is "stop
the connector consumer" with the relay declaring exactly as today. Cutover, and its rollback, live in
`billing-cutover` (decision 11).
