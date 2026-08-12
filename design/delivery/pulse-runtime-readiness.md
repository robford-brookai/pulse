# PULSE Runtime Readiness — Operations, Environments, People, Governance

**Status:** Draft v0.1 — 2026-07-31 | **Author:** Ford | **Sign-off:** Tal (ops decisions), compliance owner (§1.2)
**Companions:** `genesis-and-cutover.md` (day zero), `pulse-s1-work-orders.md` (S1.2–S1.4)

---

## 0. TL;DR

Four plans in one document, each closing a runtime gap the spec-first process deferred. Service operations (§1) proposes five decisions for the register — SPCS deployment, HMAC-signed webhook auth, client-supplied idempotency keys, DLQ-with-alarm relay semantics, and a Datadog monitor set with three SLOs. Environments (§2) defines a three-tier promotion path where only prod holds PHI and Synthea generation is a versioned, seeded artifact. People and process (§3) names the roles that currently exist only as nouns in the spec — quarantine reviewer, compliance owner, on-call — and sequences care-team enablement ahead of the P2 flip. Catalog governance (§4) records the decision that the catalog lives in Snowflake and derives the approval workflow from that choice. Every decision lands as a D14–D18 register row so the exec session can close them in one pass.

## 1. PULSE service operations

S1.1 delivers schema. This section covers the service around it.

### 1.1 Deployment target — D14

**Recommendation: Snowpark Container Services (SPCS).** The evaluation favoring SPCS (default-deny egress, data-adjacent compute, one fewer network boundary between the command API and Snowflake Postgres) was never entered in the register — this makes it decidable. EKS on DuploCloud remains the fallback if SPCS service networking cannot terminate the Twenty webhook path with acceptable latency, which is a named spike (one day, timeboxed) before D14 closes. Deciders: Tal + Ford.

### 1.2 Command API authentication — D15

**Recommendation: HMAC request signing for the Twenty webhook path, service-to-service tokens for internal writers.** An unauthenticated command endpoint is a SOC2 finding and a single-writer violation waiting to happen. Twenty workflows can attach a shared-secret HMAC header (rotate quarterly, secret in the platform secret store, never in workflow config). Internal writers (verdict relay, scheduler, identity resolution, pocar-relay) authenticate with per-service credentials so `actor` attribution is enforced by auth, not by convention — a writer can only declare events as itself. mTLS is the upgrade path if everything co-locates in SPCS, where it becomes nearly free. Deciders: Tal + compliance owner.

### 1.3 Command idempotency — D16

**Recommendation: client-supplied idempotency key, unique-constrained in the ledger.** Key = `{writer_id}:{deterministic_hash(subject, command_type, payload, logical_time)}`. Replays return the original commit result (200 with the prior event id), never a second event. This is load-bearing for genesis re-runs, relay replays, and verdict re-declarations — all three are retry-heavy by design. Retention: keys live as long as the ledger, which is append-only anyway. Decider: Ford (mechanism), Tal (sign-off).

### 1.4 Outbox relay semantics — D17

**Recommendation: at-least-once with ordered per-subject delivery, dead-letter queue (DLQ) with alarm, no silent drops.**

| Property | Choice |
|---|---|
| Delivery | At-least-once to EventBridge. Consumers deduplicate on event id — projections are upserts by design |
| Ordering | Per-subject ordering guaranteed by the outbox sequence. Cross-subject ordering not guaranteed and not needed |
| Retry | Exponential backoff, 5 attempts, then DLQ |
| DLQ | EventBridge DLQ per target, Datadog monitor at depth ≥ 1 (a single stuck event is a projection lie in progress) |
| Replay | DLQ redrive is an operator action with a runbook, never automatic — automatic redrive of a poison event is an outage loop |
| Lag budget | Outbox-to-backbone p99 < 30 seconds, driven by the heal-back UX promise |

### 1.5 Observability — Datadog plan

**SLOs (three, no more at launch):**

| SLO | Target | Why this one |
|---|---|---|
| Command API availability | 99.9% monthly | Everything writes through it — it is the availability of the business's memory |
| Command commit latency | p99 < 500 ms | Kanban heal-back and webhook timeouts both hang off this |
| Projection freshness (ledger → Twenty) | p99 < 60 s | The "heals back within seconds" promise, measured |

**Monitor set (launch):** command API error rate and latency (APM), outbox lag and DLQ depth, projection freshness per consumer (Twenty, Customer.io, Snowflake), verdict relay run success and staleness (no successful declare-back in > 26 h fires — the daily verdict cycle plus slack), month-open job success on the 1st (a missed month-open is a billing incident, page severity), reconciliation sweep drift count trend, quarantine queue depth and age. All monitors tag `service:pulse` and route to the on-call rotation (§3.3).

**Instrumentation:** every command carries a trace id propagated to the outbox event and projection writes, so one trace spans webhook → command → ledger → projection. This is the debugging story for "my card moved itself" tickets.

**On-call story:** see §3.3 — ops tooling without a rotation is a dashboard, not an operation.

## 2. Environments and test data

### 2.1 Environment matrix

| | dev | staging | prod |
|---|---|---|---|
| PULSE ledger | Per-developer schema in a shared Snowflake Postgres dev instance | One shared instance, prod-shaped | Production instance |
| Twenty | One shared dev instance (per-dev instances are not worth the operational cost) | One instance, metadata identical to prod | Production instance |
| Data | Synthea, small seed (~500 patients) | Synthea, prod-scale shape (~50k patients), refreshed per release | PHI. Genesis-loaded per the cutover plan |
| Catalog version | Any tagged version | The release candidate version | The released version only |
| Datadog | Traces only | Full monitor set, alarms muted to Slack | Full monitor set, paging |

PHI never leaves prod. There is no "sanitized prod copy" tier — de-identification pipelines are a project in themselves and Synthea makes them unnecessary. The BAA clearing C1 changes what prod may hold, not what lower environments hold.

### 2.2 Synthea as a versioned artifact

Synthetic data is generated, not hand-curated: a `synthea-seed` package in the monorepo pins the Synthea version, module config, and RNG seed, and emits the same population byte-for-byte on every run. Brook-specific fixture overlays (patients engineered to hit specific states: mid-month program switch, contradictory source states for genesis testing, quarantine-bound consent) live as declarative overlay files on top of the generated base. Regenerating staging data is a CI job, not a person's afternoon. The mandatory regression fixtures named in the object model (mid-month-switch conflict, trinary verdict cases) are overlay rows here — one source for test populations.

### 2.3 Promotion path

Catalog release → generated surfaces build in CI (D4's artifact posture — resolved as recommended 2026-08-12, DNA-908) → deploy to staging → staging smoke suite (command round-trips per state machine, kanban heal-back, projection freshness probe) → tagged promotion to prod. The same artifact promotes — nothing is regenerated between staging and prod.

## 3. People and process

### 3.1 Named roles — nouns need people

| Role in the spec | Duty | Fill by |
|---|---|---|
| Quarantine reviewer | Drain Gate B and genesis-adjudication queues, disposition with reason codes | Before genesis P0 — genesis will load the queue on day one |
| Compliance owner (D9, D15) | Validate Customer.io carrier-STOP posture, sign off on webhook auth | Before exec session — D9 is not real until this is a name |
| Verdict rule steward | Owns rule_version releases and the canonical criteria order | Luke (already named in D12) — confirm capacity |
| PULSE on-call | §3.3 rotation | Before P1 flip |
| Care-team enablement lead | §3.2 training and parallel-run | Carin candidate — confirm |

Filling these is an exec-session agenda item, not an engineering task.

### 3.2 Care-team enablement

Sequence, tied to cutover phases: (P0) two care-team members join as design partners reviewing the Twenty kanban views against real workflow. (P1) One-pager ships: what heal-back is, why a card can move itself, what the comment on a healed card means — distributed before anyone sees the behavior, because the first unexplained heal-back is a trust incident. (P1→P2) Two-week parallel-run per pod: work in Twenty, POCAR available read-only for confidence checks, daily 15-minute feedback capture. (P2) Flip per the cutover plan. Training material is generated against the staging Synthea population, so screenshots never contain PHI.

### 3.3 On-call

One rotation covering PULSE and its writers (relay, scheduler, identity resolution). Two severities: **page** (command API down, month-open failed, DLQ depth ≥ 1 for > 15 min) and **Slack** (everything else). Business-hours-only paging until P2 — the system has no patient-facing real-time duty before care teams live in it. Every monitor in §1.5 links a runbook page. Runbooks live in the monorepo `docs/runbooks/`, one per monitor, written as part of S1.2/S1.3 acceptance rather than after the first incident.

### 3.4 Exec session inputs

This document plus the genesis section give the session five closable decisions (D14–D18), three role-fill asks (§3.1), and two confirmations (G-2 tolerance owners). The §8.1 confirmation checkboxes from the object model present as "recommended, pending confirmation" per that section's own rule.

## 4. Catalog governance — with Snowflake

**Decision (recorded): the catalog's system of record is Snowflake.** Implications, so the decision does work:

1. **Storage:** catalog releases land as versioned rows in a `catalog` schema (states, transitions, reason ValueSets, program config), tagged with an immutable `catalog_version`. The git-side source (S0.2 machinery) remains where edits happen — Snowflake is where released versions live and where every consumer reads from, which puts the catalog under the same BAA, access control, and audit surface as the data it governs.
2. **Governance features:** Snowflake object tagging marks catalog objects, access history answers "who read or changed catalog state," and change approval rides the existing git PR flow — merge to main triggers the release job that writes the new version. No hand edits in Snowflake, ever. dbt `accepted_values` tests bind warehouse models to the released version automatically because they read the same tables.
3. **Breaking-change rule:** a release that removes a state, narrows a ValueSet, or changes a transition's legality is breaking. Breaking releases require a migration note in the release PR and a consumer checklist (Twenty metadata redeploy, ConceptMap regeneration, rule_version bump if verdict criteria reference the changed codes). CI enforces the four-surface drift check per §7 of the object model — Snowflake residence does not change the generative contract, it homes it.
4. **Register row D18:** catalog system of record = Snowflake, approval = git PR + release job. Owner: Ford, sign-off Tal.

## 5. Register additions (consolidated)

| ID | Decision | Recommendation | Deciders |
|---|---|---|---|
| D14 | PULSE deployment target | SPCS, EKS fallback, one-day webhook-latency spike first | Tal + Ford |
| D15 | Command API auth | HMAC for Twenty webhook, per-service credentials for internal writers, mTLS upgrade path in SPCS | Tal + compliance owner |
| D16 | Idempotency | Client-supplied keys, unique-constrained, replay returns original result | Ford, Tal sign-off |
| D17 | Outbox semantics | At-least-once, per-subject ordering, 5-retry → DLQ with depth-1 alarm, manual redrive | Ford, Tal sign-off |
| D18 | Catalog system of record | Snowflake, git-PR approval, breaking-change rule per §4.3 | Ford, Tal sign-off |
