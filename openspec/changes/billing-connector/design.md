# Design — billing-connector

## Context

See proposal.md §Why and `design/delivery/billing-connector-seed.md` for what moved and why.
What exists on `main` (2026-09-02): `pulse_core.connector` (row source and cursor, declare
pipeline with D16 keys and response classification, consume loop with dedupe and watermark,
credential-posture gate); `packages/billing` with the `billing_engine` Postgres schema
(`subject_facts`, `evaluations`), an idempotent fact fold on the kit's consume loop, a
`PostgresFactStore`, and one rule module `rules/billing_eligibility.py` (`gate_by_consent`,
`classify_outcome(facts, facts_stale)`, `evaluate_episode`, `RULE_VERSION`) with a lineage
gate; `verdict-relay` as the exemplar connector layout (`config.py`, `declarer.py`, `run.py`,
`production.py`, socket-blocked tests, fixture corpus). The seed's carried caveat: no
ledger-native path from a consent event to the billing episodes it affects.

## Goals / Non-Goals

**Goals**
- A connector package whose every module has one job and one test file, landing in four
  scaffold PRs before any behavior.
- The engine (`packages/billing`) stays a library: facts, store, rules. The connector is the
  only process.
- Every decision the seed's gates asked for is made here, not deferred into tasks.

**Non-Goals**
- No new rule modules. The registry holds what the engine ships.
- No changes to `pulse_core.connector`. If the kit lacks something, that is a `HANDOFF.md`
  note and a kit task, not an in-package fork.
- No production deploy in this change. Dev only; the window runs on dev.

## Decisions

1. **Separate package, engine stays.** `packages/billing-connector` (`billing_connector`)
   depends on `pulse-core` and `billing`, owns config, evaluate, declare, service entry,
   receipts, and deploy artifacts. `packages/billing` gains one additive module,
   `rules/registry.py`, mapping verdict type → module, so the connector never imports a rule
   module by name. Alternative (grow `packages/billing`) rejected: the credential-posture gate
   counts credentials per package, and the engine's store credential plus a writer credential
   in one package is the two-credential shape the gate exists to refuse.
2. **Four scaffold PRs, strictly additive, each with a test.** (a) package and workspace
   wiring; (b) `config.py` with the credential name, queue URL, ledger base URL, staleness
   threshold, a `from_env()` that names the missing variable; (c) code-tree stubs:
   `evaluate.py`, `declare.py`, `service.py`, `receipts.py` with typed signatures, docstrings
   naming the spec requirement each satisfies, bodies raising `NotImplementedError`; (d) test
   harness: socket-blocking `conftest.py`, `tests/fixtures/` corpus skeleton mirroring
   verdict-relay's, golden receipt line, fixture builders for fact snapshots. Alternative (one
   scaffold PR) rejected by Rob: reviewability per seam.
3. **Verdict-type set = the registry.** The connector evaluates whatever
   `billing.rules.registry` lists and halts on mismatch. Today that is one type. Adding a type
   is a reviewed edit to the registry plus a rule module with lineage, never a connector
   change. This closes seed gate 1 by making the set a fact of the rules package rather than a
   number in a design doc.
4. **Consent and enrollment fan-out are deferred behind a catalog fact.** No event, key
   composition, or command payload the connector may read links a `consent` or `enrollment`
   subject to the `billing_episode` subjects it affects (Rob, 2026-09-02: the constraint
   applies to enrollment events as it does to consent), and the Twenty relation and the
   warehouse join are both forbidden on the write path. Wave 1 triggers on `billing_episode`
   and `coverage` subject events only; consent and enrollment events fold into facts and count
   as `deferred`. The fix is a catalog fact: an episode event carrying its patient's consent
   and enrollment references, or a patient-keyed index the fold maintains from episode-open
   events. Task 2.3 writes that proposal to `HANDOFF.md` for the doc-updater and it lands as
   a separate change against the catalog. The episode key's `{enrollment_key}:` prefix is
   evidence for the proposal, not a license to scan on it. Alternative (read the Twenty
   relation) rejected: it is a projection, and projections are windows, not sources. This
   narrows the seed's "A fact arrives, a verdict follows" scenario to episode and coverage
   events until the fact exists.
5. **`facts_stale` derives from the fold watermark.** `facts_stale = now − subject_facts.
   updated_at > BILLING_CONNECTOR_STALE_AFTER` (a duration in config, default the dbt model's
   recency window, recorded in the config docstring with its dbt source). A subject with no
   row evaluates indeterminate with `awaiting_source`. Closes seed gate 2.
6. **Trigger, evaluate, declare are three modules with one direction of dependency.**
   `service.py` runs the kit consume loop on the connector's queue; on each folded change it
   calls `evaluate.evaluate_subject(store, registry, config) -> list[Evaluation]`, which is
   pure over a fact snapshot plus staleness and writes the `evaluations` row; `declare.
   declare_pair(client, evaluation) -> DeclareResult` uses the kit's pipeline with the D16 key
   derived from `(subject_key, verdict_type, rule_version, facts_hash)`. Receipts extend the
   seven-count line with `evaluated=N deferred=N`. Alternative (evaluate inside the fold)
   rejected: the fold is the engine's and must stay pure.
7. **Queue rule filter starts narrow.** Rule matches `patient-state` events whose subject
   type is `billing_episode` or `coverage`, plus `consent` and `enrollment` (for the deferred
   count and the fold). Broadening is a config change after first dev traffic. Closes seed
   gate 4 for the dev deploy.
8. **The dbt spike files are an entry gate for the window, not for scaffold.** Seed gate 3
   (uncommitted dbt files in data-platform) blocks 4.1's fixture mart and the window's
   comparison, not the connector's code. Recorded as the dependency of task 4.1 in tasks.md
   and as a cross-repo ask in `docs/contracts/consumes.md` at 4.1 time.
9. **Two changes in flight, deliberately.** Rob's call 2026-09-02. Tooling takes `CHANGE=`
   explicitly and resolves state per change; the only written assumption is CLAUDE.md's
   "`<id>` is the sole non-archive directory", which the docs close-out task amends to "the
   change named in the command". Serial-lane tasks (workspace roots, `Taskfile.yml`) in this
   change and in `pulse-demo-closeout` must not dispatch in the same wave; the coordinator
   checks before releasing 1.1 here against 1.2 there.
10. **Linear home stays PULSE / Declared-State Funnel.** The moved tasks already carry
    `DNA-1279..1282` ids issued there, and re-homing minted ids by hand is the failure mode
    the seed warned about. The Billing project gets a link from the parent issue, not the
    sub-issues. Alternative (Billing project) deferred until the connector has a production
    deploy to report on.

## Risks / Trade-offs

- [Scaffold stubs drift from the spec before behavior lands] → each stub's docstring names its
  requirement and a test asserts every requirement in the delta spec has a named stub;
  wave 1 tasks replace `NotImplementedError` bodies one module per PR.
- [Registry and lineage gate disagree] → the lineage gate (3.3 of connector-pattern) already
  pins module set; the registry test asserts it equals the gate's portable set.
- [Deferred consent and enrollment events pile up unseen] → `deferred=N` is in every receipt,
  and the window sweep counts subjects whose only pending facts are consent or enrollment.
- [Two writers in the window fight] → pairing idempotency and per-subject `as_of` monotonicity
  arbitrate; the sweep counts every arbitration.
- [Two changes in flight collide on `Taskfile.yml` or workspace `pyproject.toml`] → serial
  lane on both; coordinator releases those tasks alone.

## Migration Plan

Wave 0 scaffold PRs merge in order (a) → (b) → (c) → (d), each green on `task check`. Wave 1
fills the stubs. Wave 2 deploys to dev under the `billing-connector` credential, mart relay
untouched. Wave 3 opens the window (live execution). Wave 4 cuts over (live execution, gated).
Rollback per proposal.md.

## Open Questions

- Whether the sweep also back-checks the mart's historical seed rows or only the window —
  decidable when the window opens, changes no spec or task.
