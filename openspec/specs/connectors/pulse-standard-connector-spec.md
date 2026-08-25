# PULSE Standard Connector Specification — PAP Reference Implementation

Version 0.1 draft · 2026-08-19 · Owner: Ford · Sign-off: Tal

## 1.0 TL;DR

A standard connector is the one sanctioned shape by which a source system gets facts into the PULSE ledger. It is not an ETL job and not a sync — it is a command-issuing adapter that converts observed source-system changes into attributed, idempotent commands against the PULSE command API, or (for non-subject facts) into direct backbone emissions. PAP is the first instance and the reference implementation. Every future source connector (Billy, POCAR, Customer.io signals) implements this same contract, generated where possible from the SoR registry. The connector never writes to the ledger tables, never infers state that the catalog computes elsewhere, and is retired one event type at a time as PAP migrates to native command emission. Acceptance is determinism-by-rerun: replaying the same change window twice produces a byte-identical ledger delta of zero.

## 2.0 Scope and non-goals

### 2.1 Scope

- The connector contract: interfaces, envelope fields, classification rules, idempotency derivation, error handling, reconciliation, and retirement criteria that every source connector must satisfy.
- The PAP instance: change data capture (CDC) tap on PAP's Postgres, the PAP event-type inventory, and the PAP-specific mapping and identity resolution path.
- Interaction with backfill (BF stages) and the drift detector.

### 2.2 Non-goals

- Replacing PAP. PAP remains the enrollment application; the connector observes it.
- Reverse writes. The connector is strictly one-directional. Anything flowing back toward PAP is a command to PAP through its own API, out of scope here.
- A general ingestion framework. Warehouse-bound raw data (S3 → Snowpipe) continues on the existing ingestion layer with its provenance columns. This spec covers only the ledger-bound path.
- The catalog content itself. Which PAP transitions map to which catalog states is ratified in `state_catalog.yaml`, not here.

## 3.0 Position in the architecture

The connector sits on the left edge of the settled target architecture: PAP → connector → PULSE command API → one transaction (`prm_event` \+ `prm_current_state` \+ `prm_outbox`) → EventBridge. It is the concrete realization of the signal-adapter lane already decided in the acquisition plan (S2.x) and of the "ingress adapters generated against the SoR registry" mechanism in the OCEAN adaptation plan.

Two invariants govern everything below:

- **Single writer (I2, D3).** The connector holds no ledger credentials beyond command-API access. It cannot INSERT into `prm_event`. Legality of every transition is enforced by PULSE at write time against the versioned catalog.
- **Derived-then-declared (I3).** The connector performs exactly one inference — "this source-row change means this catalog event occurred" — and declares it with full provenance in `evidence`. It computes no verdicts. Anything requiring cross-row or cross-system computation belongs to the warehouse authority.

## 4.0 Connector anatomy

Five stages, each independently testable. Only the tap and the mapper are PAP-specific; the rest is shared library code in the PULSE monorepo (`packages/connector-core`, proposed).

| \# | Stage | Responsibility | PAP instance |
| :---- | :---- | :---- | :---- |
| 1 | Tap | Consume ordered source changes with a durable resume position | Postgres logical replication slot on PAP's database (Debezium-compatible wire format), resume via confirmed LSN |
| 2 | Classifier | Route each change: catalog-state assertion → command lane, non-subject fact → backbone lane, neither → drop with counter | Table-and-column rules versioned in connector config, CI-checked against catalog version (producer-policy test) |
| 3 | Identity | Resolve source identifiers to `patient_key` via `packages/identity` crosswalk | PAP patient ID → crosswalk. Unresolvable → hold queue, never a guessed key |
| 4 | Mapper | Build the command envelope: event type, payload, bitemporal timestamps, evidence, idempotency key | Per-event-type mapping functions, pure and unit-tested against fixture rows |
| 5 | Emitter | POST to the PULSE command API with retry, backoff, and dead-letter queue (DLQ) on permanent failure | Shared emitter, `actor_type = system`, `actor_id = connector:pap` |

### 4.1 Classification rule (producer policy, mechanized)

The single test from the adaptation plan applies verbatim: does the change assert a state that lives in the catalog? If yes, it becomes a command. If it is a non-subject fact (a document arrived, a call completed), it is emitted directly onto the backbone in the standard envelope. If neither, it is dropped and counted. The classifier's rule table is checked in CI against the current catalog version — a catalog bump that orphans a rule fails the build, the drift-fails-CI discipline applied at the connector boundary.

### 4.2 Command envelope contract

Every command the connector issues carries:

```
event_type:       from the mapper, must exist in catalog at rule_version
occurred_at:      source-system time of the change (world time, I10)
recorded_at:      assigned by PULSE at commit (ledger time, I10)
correlation_id:   threaded from prior journey events when resolvable,
                  else minted and registered for the journey
causation_id:     null for observed changes (no causing command exists)
idempotency_key:  see 4.3
actor_type:       system
actor_id:         connector:pap
authority:        null (no human approval in the loop for observed facts)
evidence:         [{ source_system: pap,
                     source_object: <table>,
                     source_pk: <row id>,
                     source_lsn: <wal position>,
                     extracted_at: <tap timestamp> }]
rule_version:     catalog version the classifier ran against
payload:          FHIR datatypes for value objects (I5)
```

`occurred_at` comes from the source row's own timestamp where one exists, else the transaction commit time from the WAL. The gap between the two is a measured quality metric per event type, not silently collapsed.

### 4.3 Idempotency derivation

The key is a deterministic function of source identity, never a random UUID:

```
idempotency_key = sha256(source_system || source_object || source_pk || source_lsn || event_type)
```

This makes replay free. Reprocessing any CDC window — after a crash, a resume-token reset, or a deliberate rerun — produces commands PULSE has already committed, and the unique constraint on `idempotency_key` absorbs them silently. This is the mechanism behind the acceptance criterion in §8.0.

### 4.4 Ordering

Per-patient ordering is preserved by processing the replication stream serially per `patient_key` (partition by resolved key, order by LSN). Cross-patient ordering is not guaranteed and not needed — `aggregate_seq` and `ledger_seq` are the ordering authorities downstream, per the settled consumer rule.

### 4.5 Failure handling

- Transient command-API failures: exponential backoff, at-least-once semantics, idempotency absorbs the duplicates.
- Rejected commands (catalog-illegal transition): DLQ with the full envelope and the API's rejection reason. A rejected transition is signal — either the source did something the catalog forbids, or the catalog is wrong. Both are triage-queue items, never silent drops.
- Identity-unresolvable rows: hold queue with a re-resolution sweep. A crosswalk improvement drains the queue without operator action.
- Tap loss (slot invalidation, WAL gap): connector halts and alarms. It never guesses a resume point. Recovery is a bounded re-snapshot of affected tables through the same idempotent path.

## 5.0 Lifecycle: adapter mode → native mode → retired

The connector exists to be replaced. Per the settled delivery plan, PAP migrates to native command emission one event type at a time.

| Phase | Behavior | Exit criterion |
| :---- | :---- | :---- |
| Adapter | Connector infers the event type from CDC and declares it | Native emission ships for the type |
| Shadow | PAP emits natively, connector still observes, drift detector compares | N days of zero divergence on the type (N proposed: 14\) |
| Retired | Classifier rule for the type flips to drop-with-counter | Rule removal is a config version bump, receipted |

The per-quarter share of native-emitted vs adapter-inferred transitions is already a named success metric. This lifecycle table is how that number moves.

## 6.0 Backfill and drift interaction

- **Backfill (BF stages).** The connector and the backfill migrator share the mapper and the idempotency derivation. History replayed through the backfill path and live changes through the CDC path cannot double-write the same fact, because both derive the same key from the same source identity. This keeps BF doctrinally identical to live ingress — derived once, declared with provenance.
- **Drift detector.** The legacy inference SQL keeps running and alarms on divergence from declared state. For PAP specifically, drift on an event type still in adapter mode indicts the mapper; drift on a type in shadow mode indicts the native emitter. The detector output therefore doubles as the shadow-phase exit evidence.

## 7.0 Deployment and security

- Runs as one worker in the existing signal-adapter slot: same VPC as PULSE, SPCS-compatible packaging per the airgap constraint, no public egress.
- Credentials: a read-only replication role on PAP's database and a command-API service credential scoped to `actor_id = connector:pap`. No warehouse access, no Twenty access, no ledger table grants.
- The connector logs envelope metadata only. Payload contents (which include patient data) appear in the ledger and nowhere in connector logs.

## 8.0 Acceptance criteria

1. **Determinism by rerun.** Replay a fixed 24-hour CDC window twice against a snapshot ledger. Second run commits zero new `prm_event` rows. Byte-level diff of the ledger delta is empty.
2. **Classification coverage.** 100% of changes in the fixture corpus route to exactly one lane (command, backbone, drop). CI fails on any unclassified change type.
3. **Ordering.** For any single patient in the fixture corpus, ledger `aggregate_seq` order matches source LSN order.
4. **Rejection visibility.** An injected catalog-illegal transition lands in the DLQ with the rejection reason within one processing cycle, and increments the alarm counter.
5. **Identity holds.** An injected unresolvable PAP patient ID lands in the hold queue, and drains automatically after a crosswalk row is added — no operator step.
6. **Drift.** Legacy inference vs declared state divergence for connector-covered event types is below the agreed threshold and alarmed above it.

## 9.0 Decision register (draft rows)

| ID | Question | Options | Decider | Status |
| :---- | :---- | :---- | :---- | :---- |
| D-PAP-1 | CDC mechanism on PAP: raw logical replication slot vs Debezium-managed | Slot is fewer moving parts, Debezium buys snapshot tooling and schema-change handling | Ford \+ Surendar | Open |
| D-PAP-2 | PAP event-type inventory v1: which tables/columns map to which catalog states | Output of the ingress adapter catalog inventory work (DNA-913–917) | Ford \+ Sheila | Open |
| D-PAP-3 | Shadow-phase duration N before retiring an adapter rule | 14 days proposed | Ford \+ Tal | Open |
| D-PAP-4 | DLQ and hold-queue retention and escalation SLA | 30 days proposed, alarm at 24h unworked | Ford | Open |

## 10.0 Next steps

1. Ratify D-PAP-1 with Surendar — the tap choice gates everything else.
2. Fold this spec into the PULSE repo as `docs/specs/standard-connector.md` and register ADR rows D-PAP-1 through D-PAP-4.
3. Derive the DNA work orders: `connector-core` package scaffold, PAP tap spike, classifier CI check, fixture corpus, acceptance harness. Each in work-order format for the agent queue.
