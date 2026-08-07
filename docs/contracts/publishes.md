# Publishes

What this repo exposes to other repos and teams. Anything not listed here is an implementation
detail and may change without notice.

Cross-repo integration happens through this document — a published Snowflake object, an API, or
a released package. **Never integrate by cloning another repo into this one.** A side-clone
couples you to someone else's implementation details and to their refactors.

Record each entry with enough detail that a consumer can depend on it without reading the code:

| Surface | Kind | Stability | Notes |
|---|---|---|---|
| _e.g._ `ANALYTICS.DIM_PATIENT` | Snowflake view | stable | grain: one row per patient; PHI — access via role `ANALYST_PHI` |
| _e.g._ `GET /v1/encounters` | REST API | beta | paginated; contract in `docs/api/encounters.yaml` |

## This repo

pulse publishes the OCEAN event distribution surfaces, absorbed as `packages/ocean`
([ADR-0002](../adr/ADR-0002-ocean-absorption-and-eventbridge-transport.md)). The transport is
**EventBridge**: the former `ocean.<domain>` Kafka topics are retired, and a consumer integrates
by attaching an EventBridge rule and its own SQS queue — never by subscribing to a topic.

| Surface | Kind | Stability | Notes |
|---|---|---|---|
| `ocean` event bus | EventBridge bus | stable | events address as `source = "ocean"`, `detail-type = "<domain>"`; the envelope crosses whole in `detail`, unmodified — `event_type` stays an envelope field, never promoted to `detail-type` |
| Domain catalog | generated mapping | stable | eleven live domains: `signals`, `alerts`, `tasks`, `interactions`, `outcomes`, `patient-state`, `tickets`, `ai-ops`, `audit`, `ops`, `logistics`; source table is `packages/ocean/libs/ocean-broker/src/ocean_broker/catalog.py`, from which publisher addressing and Terraform rule patterns both generate |
| `STREAMLINE.OCEAN_RAW.EVENTS` | Snowflake table | stable | grain: one row per envelope `event_id`; `data` is the envelope as VARIANT, `_topic` records the originating domain; append-only — redelivery never updates or duplicates a row |

### Ledger command and read surfaces (`pulse-ledger-core`, DNA-784)

The ledger's write path is one HTTP command API (`packages/pulse-ledger`), consumed through the
client SDK `packages/pulse-core` ([ADR-0003](../adr/ADR-0003-ledger-core-write-path.md)). Writers
integrate through `pulse_core`, never by writing `ledger.*` tables — the schema REVOKEs
UPDATE/DELETE on `events` and the API is the single writer.

| Surface | Kind | Stability | Notes |
|---|---|---|---|
| `POST /commands` | REST API | beta | single command; write-time catalog legality, rejection carries reason + `catalog_version`; actor derived from the bearer credential, body actor fields rejected (D15) |
| `POST /commands:batch` | REST API | beta | backfill mode, same validation; `backfill_genesis`/`reconstruction_gap` accepted only from the backfill actor |
| `PUT/GET /writers/{writer_id}/cursor` | REST API | beta | durable writer cursors, opaque JSON; a credential may touch only its own `writer_id`; path template in `pulse_core.cursor` |
| `pulse_core` (client SDK) | workspace package | beta | `PulseCoreClient.submit_command` classifies `committed \| replayed \| rejected \| transient`, retries transient only; `consume(handler)` is the SQS consumer convention (`event_id` dedupe, delete-after-success); D16 key derivation in `pulse_core.idempotency` |
| `pulse_ledger.reads` / `.identity` / `.review` | library read surface | beta | in-process reads over the ledger Postgres: `enumerate_state` (co-committed `ledger.current_state`, catalog-validated states), `lookup_identifier`/`find_candidates` (identity, digests only — never demographics), `list_review_queue`/`resolve_review` (`ledger.review_queue` quarantine). No HTTP read routes shipped in S1.1 |

Replay classification is end-to-end (DNA-801): `POST /commands` and `POST /commands:batch` accept
an optional `idempotency_key` body field, thread it to `commit_idempotent`, and every commit
response carries `replayed` — a repeated key returns the original event with `"replayed": true`
and writes nothing. A keyless body still commits as a fresh event.

### Identity matcher (`s14-identity`, DNA-850)

The deterministic identity matcher lives in `packages/identity` and is consumed as a library
entrypoint, independent of `identity.service`'s event-consumption path — genesis adjudication
calls it directly, in batch, with its own harness (spec: "the matcher entrypoint is stable for
genesis"). Quarantine disposition for its `Ambiguous` outcome is
[`docs/runbooks/identity-quarantine.md`](../runbooks/identity-quarantine.md).

| Surface | Kind | Stability | Notes |
|---|---|---|---|
| `identity.matcher.resolve(referral, lookup)` | library entrypoint | stable | pure function — no I/O, no ledger writes; takes a `Referral` (demographics + identifiers) and a `CandidateLookup` port, returns a `Decision` |
| `identity.matcher.Decision` (`Match \| Mint \| Ambiguous`) | typed union | stable | `Match(person_id, evidence)`, `Mint(evidence)`, `Ambiguous(candidates, evidence)`; every decision carries `Evidence(matched_fields, rule_id, candidate_count)` — field names only, never demographic values |
| Rule ids | module constants (string) | stable | `identifier_exact`, `identifier_conflict`, `composite_unique`, `composite_none`, `composite_ambiguous` — the last two quarantine; normalization rules each composite digest depends on are versioned in `packages/identity/docs/matching.md` |
| `identity.matcher.CandidateLookup` | `Protocol` | stable | the read port `resolve` decides against (`lookup_identifier`, `find_candidates`); a caller batching reads (e.g. genesis) brings its own adapter, not the live one wired in `identity.lookup` |

Ambiguity that turns out to be duplicate person records corrects through `merge_person`
(`pulse_core.generated.MergePersonCommand`, S1.1's command) — never a parallel dedup mechanism.

### State catalog (`catalog-authority`, DNA-863–DNA-871)

The authoritative state catalog is the contract for every downstream consumer that must know the
state or command vocabulary — first `producer-ingress-policy`'s CI gate. This is the pin, stated
once: consumers read the surfaces below and nothing else. No consumer parses the retired Appendix
C seed, scrapes the Snowflake rows for CI gating, or reaches into generator internals.
`tests/test_catalog_consumer_contract.py` holds the file and the generated module to the same
version and vocabulary, so reading either one gives the same answer.

| Surface | Kind | Stability | Notes |
|---|---|---|---|
| `catalog/state_catalog.yaml` | versioned YAML file | stable | the authoritative catalog at the repo head: subjects with transition adjacency and ownership, command vocabulary, reason ValueSets, program config; edits land by PR only — never by hand in Snowflake |
| `catalog_version` | semver convention | stable | MAJOR increments exactly on a breaking release — a removed state, a narrowed ValueSet, or a transition legality change in either direction (runtime-readiness §4.3); a breaking release ships `catalog/releases/v<version>-migration.md` with the consumer checklist, enforced in `task check` |
| `pulse_core.generated` | workspace package surface | stable | the programmatic surface, pinned to the file's version: `CATALOG_VERSION`, `SUBJECT_TYPES`, `TRANSITIONS`, `COMMAND_TYPES` |
| Snowflake `catalog` schema | Snowflake schema | stable | the warehouse read surface: insert-only released rows (`STATES`, `TRANSITIONS`, `VALUESET_CODES`, `PROGRAMS`, `VERSIONS`), every row stamped with its version, objects tagged `CATALOG_VERSION`; database name pinned by the first credentialed deploy; release procedure in [`docs/runbooks/catalog-release.md`](../runbooks/catalog-release.md) |

### Offered to PX survey engine (discovery stage, `survey-engine-ingress` planned)

PX (survey engine, owner Max Pengilly) is in discovery; pulse's planned adapter is
`survey-engine-ingress`, sequenced early Phase 3 in `design/delivery/pulse-program-roadmap.md`.
What pulse offers PX now, before any code integrates:

| Surface | Kind | Stability | Notes |
|---|---|---|---|
| Event envelope + state catalog | contract docs | stable | `design/platform/event-envelope-spec.md`, `design/platform/state-catalog.md` — the shape survey responses take as attributed commands/facts on the single write path; PX defines survey payloads against these, never a parallel event schema |
| `s14-identity` matcher | library read surface | beta | PX's cross-surface identity resolution consumes the deterministic matcher `s14-identity` publishes (`pulse_ledger.identity`: `lookup_identifier`/`find_candidates`, digests only — never demographics; full entrypoint contract in the "Identity matcher" section above), not a parallel matcher |

**Consent-model overlap:** PX's open consent-model decision overlaps D9 and
`customerio-consent-ingress` — consent state lives in the ledger's catalog, actor-attributed and
message-provenanced; PX must consume it there, not model consent independently. Survey responses
are patient-reported data: any adapter inherits the full PHI boundary rules (no demographics to
logs, synthetic fixtures only).

Retired with the transport change: the `ocean.<domain>` topics, the `ocean.warehouse-dlq` topic
(each consumer now has its own SQS dead-letter queue), and the Redpanda Connect warehouse sink
(the warehouse path is an ordinary rule-and-queue consumer).

A new `event_type` within an existing domain needs no rule change; a new **domain** is an
addition to the catalog table, regenerated and reviewed here.
