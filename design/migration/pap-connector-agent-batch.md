# PAP Connector Agent Batch — CX-1 through CX-8

Version 0.1 draft · 2026-08-19 · Owner: Ford · Sign-off: Tal

The connector contract itself lives in `openspec/specs/connectors/pulse-standard-connector-spec.md`
— the canonical spec, written in the vocabulary of the shipped kit (`pulse_core.connector`).
Section references below (§4.2, §4.4, §4.5, §7.0, §8.0) point into that spec. This file holds only
the PAP-specific work breakdown: the one-session work orders that stand up the reference
implementation, and the decisions that gate them.

Package paths in the orders below are as drafted in 2026-08 (`packages/connector-core`,
`packages/connector-pap`). The kit shipped as `pulse_core.connector`; read the canonical spec for
current module names before claiming an order.

## Work breakdown — one-session work orders

Dependency map: `CX-1 -> {CX-2, CX-3, CX-4, CX-5}; CX-2 -> CX-6; {CX-3, CX-4} -> CX-6; CX-5 independent after CX-1; CX-6 -> CX-7; CX-7 -> CX-8`. CX-2 through CX-5 are parallel-claimable once CX-1 merges. CX-3 is additionally gated on decision D-PAP-1 (human, not queue).

Each order below is sized to one Claude Code session, one package boundary, tests included. All live in the `brookai/pulse` monorepo. Every session reads CLAUDE.md first.

### CX-1 — Scaffold connector-core package

**Context.** Package: `packages/connector-core`. Depends on: nothing in this batch — uses the existing uv-workspace layout and the ledger types already in `packages/ledger` (envelope fields per §4.2). Read CLAUDE.md and the workspace `pyproject.toml` dependency-group conventions first.

**Task.**
1. `packages/connector-core/pyproject.toml` — workspace member, deps: pydantic, existing ledger types package.
2. `packages/connector-core/src/connector_core/envelope.py` — Pydantic `CommandEnvelope` matching §4.2 field-for-field, `occurred_at`/`recorded_at` bitemporal semantics documented in field descriptions.
3. `packages/connector-core/src/connector_core/idempotency.py` — `derive_key(source_system, source_object, source_pk, source_lsn, event_type) -> str` implementing the §4.3 sha256 derivation, pure function.
4. `packages/connector-core/src/connector_core/lanes.py` — `Lane` enum (COMMAND, BACKBONE, DROP) and `ClassificationResult` type.
5. `tests/` — property-based test (hypothesis) proving `derive_key` determinism and injectivity across field permutations, envelope round-trip serialization test with golden JSON fixture in `tests/fixtures/envelope_v1.json`.

**Out of scope.** Classifier rule loading (CX-2). Any HTTP emitter code (CX-4). CDC tap (CX-3).

**Verification.**
```
uv run pytest packages/connector-core --cov=connector_core --cov-fail-under=90
uv run ruff check packages/connector-core && uv run pyright packages/connector-core
```

**Done means.** CI green on PR, coverage ≥90%, golden envelope fixture committed, key derivation property tests pass.

### CX-2 — Classifier with catalog-drift CI check

**Context.** Package: `packages/connector-core` (module `classifier.py`). Depends on: CX-1 (Lane enum, envelope types), `packages/catalog` (catalog loader, version accessor — existing from S0.2). The classification rule is §4.1: catalog-state assertion → COMMAND, non-subject fact → BACKBONE, else DROP. Rules are declarative config, not code.

**Task.**
1. `packages/connector-core/src/connector_core/rules_schema.py` — Pydantic schema for a connector rule file: source table, column predicates, target lane, target event type (COMMAND lane only), catalog version pin.
2. `packages/connector-core/src/connector_core/classifier.py` — `classify(change, rules) -> ClassificationResult`, pure, with per-lane counters exposed as a plain dict for the worker to export.
3. `packages/connector-core/src/connector_core/drift_check.py` — CLI (`python -m connector_core.drift_check <rules_file>`) exiting nonzero if any rule references an event type absent from the loaded catalog version, per §4.1.
4. `.github/workflows/` — add the drift check to the existing CI workflow as a step (edit, do not create a new workflow file).
5. `tests/` — fixture rules file + fixture catalog, table-driven tests covering all three lanes, an unclassified-change failure case, and a drift-check exit-code test invoking the CLI via subprocess.

**Out of scope.** The actual PAP rule inventory content (CX-5, and gated on D-PAP-2). Tap integration (CX-3).

**Verification.**
```
uv run pytest packages/connector-core --cov=connector_core --cov-fail-under=90
uv run python -m connector_core.drift_check tests/fixtures/rules_valid.yaml
uv run python -m connector_core.drift_check tests/fixtures/rules_orphaned.yaml; test $? -ne 0
uv run ruff check packages/connector-core && uv run pyright packages/connector-core
```

**Done means.** CI green, drift check wired into workflow, orphaned-rule fixture proven to fail with nonzero exit.

### CX-3 — PAP CDC tap (gated on D-PAP-1)

**Context.** Package: `packages/connector-pap` (new workspace member). Depends on: CX-1 (types), decision D-PAP-1 resolved — this order assumes the raw-logical-replication-slot answer; if D-PAP-1 lands on Debezium, the dispatcher swaps this order for its Debezium variant before claiming. No live PAP database exists in CI: all tests run against recorded WAL-message fixtures.

**Task.**
1. `packages/connector-pap/src/connector_pap/tap.py` — logical replication consumer (psycopg3, `START_REPLICATION`), yielding typed `SourceChange` records, persisting confirmed LSN to a supplied checkpoint store interface.
2. `packages/connector-pap/src/connector_pap/checkpoint.py` — checkpoint store protocol + Postgres-table implementation, halt-and-alarm on slot invalidation per §4.5 (raise a typed `TapLost` exception, never auto-resume).
3. `packages/connector-pap/src/connector_pap/partitioner.py` — per-patient serial ordering: partition by resolved key, order by LSN, per §4.4.
4. `tests/fixtures/wal/` — recorded pgoutput message fixtures (insert, update, transaction boundary, slot-invalidation error).
5. `tests/` — replay fixtures through tap + partitioner, assert per-key LSN ordering, assert `TapLost` on the invalidation fixture, socket-blocking autouse fixture proving no live network in the test run.

**Out of scope.** Mapping to envelopes (CX-5). Emitting to the API (CX-4). Snapshot/re-snapshot tooling (follow-on order, file under BF batch).

**Verification.**
```
uv run pytest packages/connector-pap --cov=connector_pap --cov-fail-under=85
uv run ruff check packages/connector-pap && uv run pyright packages/connector-pap
```

**Done means.** CI green, all tests offline against WAL fixtures, ordering and halt behavior proven by named tests.

### CX-4 — Emitter with retry, DLQ, and hold queue

**Context.** Package: `packages/connector-core` (modules `emitter.py`, `queues.py`). Depends on: CX-1 (envelope). The command API contract is the existing PULSE endpoint from S1.2 — request/response shapes are in `packages/ledger` API types; do not re-declare them. Failure semantics per §4.5: transient → backoff retry, catalog-rejection → DLQ with reason, identity-unresolvable → hold queue with re-resolution sweep.

**Task.**
1. `packages/connector-core/src/connector_core/emitter.py` — async HTTP emitter (httpx), exponential backoff with jitter, at-least-once, distinguishes transient (5xx, timeout) from rejection (422 with catalog reason).
2. `packages/connector-core/src/connector_core/queues.py` — DLQ and hold-queue writers on Postgres tables (`connector_dlq`, `connector_hold`), full envelope + reason, plus `sweep_holds(resolver)` that re-attempts identity resolution and drains per acceptance criterion 5.
3. `packages/connector-core/src/connector_core/metrics.py` — counters: emitted, retried, dead-lettered, held, drained.
4. `tests/fixtures/api/` — recorded response cassettes (respx): success, 500-then-success, 422-rejection, timeout.
5. `tests/` — cassette-driven emitter tests, DLQ round-trip test, hold-drain test where a resolver stub flips from miss to hit, socket-blocking fixture.

**Out of scope.** Alerting/alarm wiring to Datadog (operational follow-on, not this batch). Retention/escalation policy values (D-PAP-4 — implement as config with placeholder-free defaults of 30d/24h, flagged in PR description).

**Verification.**
```
uv run pytest packages/connector-core --cov=connector_core --cov-fail-under=90
uv run ruff check packages/connector-core && uv run pyright packages/connector-core
```

**Done means.** CI green, no live network in tests, DLQ and hold-drain behaviors proven by named tests.

### CX-5 — PAP mapper and fixture corpus

**Context.** Package: `packages/connector-pap` (module `mapper.py`). Depends on: CX-1 (envelope, idempotency), D-PAP-2 for the real event-type inventory — this order builds the mapper mechanism plus mappings for the two already-ratified enrollment transitions only (named in the catalog at time of claim; read `state_catalog.yaml` for current version). Identity resolution calls `packages/identity` crosswalk interface — inject it, do not import concretely.

**Task.**
1. `packages/connector-pap/src/connector_pap/mapper.py` — per-event-type pure mapping functions `SourceChange -> CommandEnvelope`, registry dict keyed by (table, event type), `occurred_at` sourced from row timestamp with WAL-commit-time fallback and a gap metric per §4.2.
2. `packages/connector-pap/src/connector_pap/identity.py` — resolver adapter over `packages/identity` crosswalk, returning resolved key or a typed `Unresolved` sentinel routed to hold queue.
3. `tests/fixtures/corpus/` — the fixture corpus of acceptance criterion 2: one recorded source row per mapped event type plus one unmappable row, JSON, checked in.
4. `tests/` — golden-file tests: each corpus row maps to a byte-stable envelope (golden JSONs committed), idempotency keys stable across two mapper invocations, gap metric asserted on the fallback-timestamp fixture.

**Out of scope.** Additional event types beyond the ratified two (post-D-PAP-2 orders). Tap plumbing (CX-3). Emission (CX-4).

**Verification.**
```
uv run pytest packages/connector-pap --cov=connector_pap --cov-fail-under=85
uv run ruff check packages/connector-pap && uv run pyright packages/connector-pap
```

**Done means.** CI green, golden envelopes committed and stable, corpus covers every mapped type plus the drop case.

### CX-6 — Worker assembly and determinism harness

**Context.** Package: `packages/connector-pap` (module `worker.py`) plus `tests/acceptance/`. Depends on: CX-2 (classifier), CX-3 (tap), CX-4 (emitter), CX-5 (mapper). This is the wiring order: it composes existing pieces and must add no new business logic. The acceptance harness implements §8.0 criterion 1 against a dockerized ledger (compose file already in repo for S1.x integration tests — reuse it).

**Task.**
1. `packages/connector-pap/src/connector_pap/worker.py` — composition: tap → partitioner → classifier → identity → mapper → emitter, config-driven, structured logging of envelope metadata only (no payload contents, per §7.0).
2. `packages/connector-pap/src/connector_pap/config.py` — single Pydantic settings object, env-sourced, no secrets in code.
3. `tests/acceptance/test_rerun_determinism.py` — replays the CX-5 fixture corpus through the full worker against the compose ledger twice, asserts second-run `prm_event` insert count == 0 and ledger-delta diff empty (criterion 1).
4. `tests/acceptance/test_rejection_dlq.py` — injects the catalog-illegal fixture, asserts DLQ row with reason within one cycle (criterion 4).
5. `tests/acceptance/test_ordering.py` — asserts `aggregate_seq` order matches LSN order for the multi-event fixture patient (criterion 3).

**Out of scope.** Deployment manifests (CX-7). Any mapper or classifier changes — patch those in their own packages via follow-up orders if the harness exposes defects.

**Verification.**
```
docker compose -f docker/compose.test.yaml up -d && uv run pytest tests/acceptance -m connector
uv run pytest packages/connector-pap --cov=connector_pap --cov-fail-under=85
uv run ruff check packages/connector-pap && uv run pyright packages/connector-pap
```

**Done means.** Acceptance criteria 1, 3, 4 pass as named executable tests against the dockerized ledger, CI green.

### CX-7 — Container image and SPCS deploy manifest

**Context.** Package: `docker/` + `deploy/`. Depends on: CX-6 (working worker entrypoint). Airgap constraints apply: SPCS-only, pinned toolchain image, `--private` publish, no public egress at runtime. Read the existing PULSE service Dockerfile for the base-image and pinning conventions and match them exactly.

**Task.**
1. `docker/Dockerfile.connector-pap` — multi-stage, pinned base, uv-locked install, non-root user, worker entrypoint.
2. `deploy/spcs/connector-pap.yaml` — SPCS service spec: compute pool sizing (smallest, single instance), secrets refs for the replication role and command-API credential per §7.0, no External Access Integration.
3. `docs/runbooks/connector-pap.md` — start, stop, checkpoint inspection, slot-invalidation recovery procedure (the halt-and-alarm path from §4.5), DLQ triage steps.
4. `.github/workflows/` — image build + private registry push job (edit existing release workflow).

**Out of scope.** The actual production deploy execution (human-gated, destructive_ops lane). Datadog dashboards (operational follow-on).

**Verification.**
```
docker build -f docker/Dockerfile.connector-pap -t connector-pap:ci .
docker run --rm connector-pap:ci python -c "import connector_pap.worker"
uv run python -m yaml deploy/spcs/connector-pap.yaml
```

**Done means.** Image builds and imports cleanly in CI, manifest parses, runbook committed, push job green on a tag build.

### CX-8 — Drift detector wiring for connector-covered types

**Context.** Repo: `data-platform/management` (dbt), not the pulse monorepo — one repo, one session, per the sizing rule. Depends on: CX-6 live in a staging window producing declared rows. The legacy inference SQL already exists; this order compares it to declared state for the PAP-mapped event types only (§6.0) and emits divergence counts. Confirm dbt execution location first (`profiles.yml`, Dockerfile, or workflow file — known open item).

**Task.**
1. `models/drift/drift_pap_connector.sql` — inference-vs-declared comparison per event type, divergence count and sample keys, materialized as a table.
2. `models/drift/schema.yml` — dbt test: divergence count ≤ threshold var (`drift_threshold_pap`, default 0), so a breach fails the dbt build.
3. `analyses/drift_pap_readme.md` — interpretation guide: adapter-mode drift indicts the mapper, shadow-mode drift indicts the native emitter, per §6.0.

**Out of scope.** Alarm routing to Datadog/Slack (operational follow-on). Backfill comparison models (BF batch).

**Verification.**
```
dbt build --select drift_pap_connector
dbt test --select drift_pap_connector
```

**Done means.** Model builds, threshold test wired so drift breach fails the build, readme committed.

## Decision register (draft rows)

These rows gate the orders above. The canonical spec carries the same register; it is repeated here
because the orders name the IDs.

| ID | Question | Options | Decider | Status |
|---|---|---|---|---|
| D-PAP-1 | CDC mechanism on PAP: raw logical replication slot vs Debezium-managed | Slot is fewer moving parts, Debezium buys snapshot tooling and schema-change handling | Ford + Surendar | Open |
| D-PAP-2 | PAP event-type inventory v1: which tables/columns map to which catalog states | Output of the ingress adapter catalog inventory work (DNA-913–917) | Ford + Sheila | Open |
| D-PAP-3 | Shadow-phase duration N before retiring an adapter rule | 14 days proposed | Ford + Tal | Open |
| D-PAP-4 | DLQ and hold-queue retention and escalation SLA | 30 days proposed, alarm at 24h unworked | Ford | Open |

## Next steps

1. Ratify D-PAP-1 with Surendar — it gates CX-3 and nothing else, so CX-1, CX-2, and CX-4 are
   queueable today.
2. Register ADR rows D-PAP-1 through D-PAP-4 under `docs/adr/`.
3. Queue CX-1 through CX-8 as DNA sub-issues under the PULSE / Declared-State Funnel project with
   the dependency edges above.
