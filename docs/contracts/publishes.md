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
| `STREAMLINE.OCEAN_RAW.EVENTS` | Snowflake table | stable | grain: one row per envelope `event_id`; `data` is the envelope as VARIANT, `_topic` records the originating domain; append-only — redelivery never updates or duplicates a row; fed continuously by the provisioned warehouse-sync consumer |

### STG_EVENTS ledger contract (`snowflake-stg-events`)

The typed, deduplicated view of the ledger's event envelopes: downstream warehouse consumers
read `STG_EVENTS.EVENTS` instead of the raw landing. Committed SQL, not dbt — the view IS this
contract row, so it versions with this repo: `packages/ocean/infra/snowflake/stg_events_events.sql`.
History before `min_complete_from` is incomplete until
`projection-rebuild-drill` closes the pre-revival gap — absence of pre-revival rows reads as
documented, not as data loss.

| Surface | Kind | Stability | Notes |
|---|---|---|---|
| `STREAMLINE.STG_EVENTS.EVENTS` | Snowflake view | beta | grain: one row per envelope `event_id`, earliest arrival wins (`QUALIFY ROW_NUMBER() OVER (PARTITION BY data:event_id ORDER BY _loaded_at ASC) = 1`); no `_topic` filter — consumers filter on `_topic` themselves; columns: `event_id`, `event_type`, `subject_type`, `subject_key`, `seq`, `effective_at`, `occurred_at`, `recorded_at`, `producer`, `schema_version`, `rule_version`, `correlation_id`, `causation_id`, `reverses_event_id`, `actor`, `evidence`, `evidence_class`, `epoch`, `payload`, `key`, `_topic`, `_loaded_at`; freshness query: `SELECT TIMESTAMPDIFF('minute', MAX(_loaded_at), CURRENT_TIMESTAMP()) FROM STREAMLINE.OCEAN_RAW.EVENTS`; `min_complete_from`: `2026-08-26` — rows before this date are absent by design, not by loss; `projection-rebuild-drill` is the change that backfills history and closes the pre-revival gap |

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
| `GET /subjects/{subject_type}/{subject_key}/events` | REST API | beta | one subject's committed events in ledger sequence, as the same envelopes the relay publishes; keyset-paged on `seq`, unknown subject = empty history, unknown subject type = the catalog's 422; the replay surface a projection repaints from without holding a ledger database credential (path template in `pulse_core.history`, client `PulseCoreClient.subject_history`) |
| `pulse_ledger.reads` / `.identity` / `.review` | library read surface | beta | in-process reads over the ledger Postgres: `enumerate_state` (co-committed `ledger.current_state`, catalog-validated states), `lookup_identifier`/`find_candidates` (identity, digests only — never demographics), `list_review_queue`/`resolve_review` (`ledger.review_queue` quarantine). The per-subject history route above is the only HTTP read route; everything else here is in-process |

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

### Twenty kanban webhook ingress (`twenty-kanban-webhook-ingress`, DNA-873–DNA-879)

The D8 kanban drag route: a Twenty card drag becomes an attributed `declare_transition` command on
the ledger's single write path, or a rejection receipt plus a card comment if the catalog refuses
the transition. Runbook: [`docs/runbooks/twenty-webhook.md`](../runbooks/twenty-webhook.md)
(enablement, quarterly dual-secret rotation, disposition log vocabulary, heal-back boundary).

| Surface | Kind | Stability | Notes |
|---|---|---|---|
| `POST /webhooks/twenty` | REST API (webhook) | beta | env-gated (`PULSE_LEDGER_TWENTY_WEBHOOK_ENABLED`); HMAC-signed on Twenty's wire format (`X-Twenty-Webhook-Signature` / `X-Twenty-Webhook-Timestamp`, bare hex HMAC-SHA256 over `{timestamp}:{body}`, millisecond timestamp, 5-minute freshness), dual-secret during quarterly rotation (`PULSE_LEDGER_TWENTY_WEBHOOK_SECRET[_NEXT]`); 401 on auth failure, 200 with a `committed \| replayed \| noop \| unmapped \| rejected \| malformed` disposition body otherwise — no live network in tests, no live Twenty instance exists before Phase 3 |
| Webhook attribution | design contract | stable | actor is the fixed webhook principal (`twenty-webhook`, actor_type `system`), never a payload field (D15); the dragging workspace member travels as evidence provenance only |

### Twenty board projection (`twenty-projection`)

The D8 return path: committed ledger events for board subjects render onto the Twenty board
through `packages/twenty-projection`, so the board is a view of the ledger, never a parallel
store. Operations (running the consumer, watermark semantics, orphan triage, rebuilding a scope,
rollback): [`docs/runbooks/twenty-projection.md`](../runbooks/twenty-projection.md).

| Surface | Kind | Stability | Notes |
|---|---|---|---|
| Projection queue | EventBridge rule + SQS queue (consumed) | beta | the projection is a registered consumer of the `ocean` bus per the rule-and-queue convention above: committed `enrollment` events, consumed via `pulse_core.consume` (event-id dedupe, delete-after-success); the consumer's whole env surface is `PULSE_TWENTY_<TARGET>_URL/_TOKEN` + `SQS_QUEUE_URL` — no ledger DSN, no writer token, so it renders state and can never mint or mutate ledger events |
| `patientProgram.lifecycleStatus` + `lifecycleStatusAsOf` + `projectionSeq` | Twenty board columns (written) | beta | the projection is the owning writer: each applied event writes the full board state (encoded status, as-of from the event's effective time, watermark) in one PATCH, monotonic per record on `projectionSeq` (the last applied ledger sequence; null = never projected); an out-of-band edit is drift that converges on the subject's next event — nothing else may write these columns |

The projection is rebuildable, and that is a published property of it, not a test-only trick:
`task projection:rebuild TARGET=<t> SCOPE=<subject_type>[:<key>] OPERATOR=<who>` repaints the
scope's projected columns from the subject's committed events alone — read through the
per-subject history route above, folded through the same apply handler the consumer uses, diffed
against the current rows, and written only where they differ, ending in a counted receipt. It
never creates or deletes a board record and never touches a row outside its scope, so a subject
with no row is a counted orphan rather than a mint. It consumes two credentials and no database:
the projection's own Twenty token, and the kit's replay credential (`pulse_core.replay`).

The webhook route's heal-back write (a `rejected` drag restores the card to the state of
record) rides the same projection writer but carries the status field alone — a heal has no
ledger sequence in hand and never moves the `projectionSeq` watermark. Its own webhook echo
terminates in the mapping as `noop` reason `echo_of_record`.

### Coverage and billing state (`billing-state`)

Verdicts stop being terminal evidence: for a registered verdict type, the relay follows its
committed `declare_verdict` with a paired `declare_transition` on the same subject, so billing
qualification and insurance coverage become continuously-known ledger state rather than something
each consumer folds out of verdict history. Coverage is a new ledger-owned subject at patient ×
payer grain. Operations (poll cadence, no-op runs, transition-rejected triage, rollback):
[`docs/runbooks/billing-state.md`](../runbooks/billing-state.md).

| Surface | Kind | Stability | Notes |
|---|---|---|---|
| `coverage` subject | ledger subject type | beta | ownership `ledger`, grain one subject per patient × payer, catalog release `1.1.0`; states `unverified → verified_active \| verified_inactive`, `verified_active ⇄ verified_inactive`, either verified state → `lapsed` (re-verifiable), terminal `terminated`. Benefit detail — QMB status, benefit categories, copay — lives in verdict payload and `lineage_ref`, never in the state vocabulary. Admitted by the three subject-type CHECK constraints (`events`, `current_state`, `review_queue`), so a catalog-legal coverage transition commits; enumerable by state through `pulse_ledger.reads.enumerate_state` |
| Paired transition events on `patient-state` | EventBridge events (published) | beta | committed `coverage` and `billing_episode` events cross the `ocean` bus on the existing `patient-state` domain — no new domain, no rule change: a paired declare emits two envelopes for one subject, `event_type` `declare_verdict` then `declare_transition`, both attributed to the relay's service identity `verdict-relay` (D15). New for consumers: `subject_type` `coverage` appears on this domain, and a `declare_transition` on a billing subject may now originate from the relay rather than an operator |
| Registered verdict → transition pairing | design contract | beta | `billing_eligibility` → `billing_episode` (`positive` → `qualified`, `negative` → `not_qualified`); `coverage_eligibility` and `benefits_verification` → `coverage` (`positive` → `verified_active`, `negative` → `verified_inactive`). `indeterminate` maps nowhere — evidence without consequence, verdict only. A verdict type with no `transition_by_outcome` entry behaves exactly as before. The pair's idempotency key derives from the verdict row (D16), so it is replay-safe as a unit; a transition the catalog refuses is counted `transition_rejected` and never retried, and the verdict half stands |

The relay run receipt is the operator-visible contract for this pairing and carries seven counts
in a pinned summary line (`declared`, `replayed`, `skipped_stale`, `rejected`, `transitioned`,
`transition_rejected`, `failed`) — the two new counts are `transitioned` and
`transition_rejected`. The first verdict for an unseen patient × payer key mints the coverage
subject at its derived initial state (`unverified`) and applies the paired transition in the same
run: no registration step, no manual minting.

### Billing connector producer (`billing-connector`)

The in-pulse connector (`packages/billing-connector`) is a second declared producer on
`billing_episode`/`coverage` subjects, alongside the warehouse verdict relay documented above —
event-driven off its own queue, allowlisted to `billing_episode`/`coverage`/`consent`/`enrollment`
subject events (design.md decision 7), and never reading the warehouse to decide a verdict. It
declares the same registered pairing contract (verdict then paired `declare_transition`) under its
own writer credential, so the two producers are attributed separately and arbitrate through
pairing idempotency and per-subject `as_of` monotonicity — never a parallel write path. Dev deploy
only for now (task 3.1); deploy and operations: [`docs/runbooks/billing-connector.md`
](../runbooks/billing-connector.md).

| Surface | Kind | Stability | Notes |
|---|---|---|---|
| Declared verdict + paired transition events (via command API) | EventBridge events (published), same `patient-state` domain as the "Coverage and billing state" row above — no new domain | beta | producer credential name `BILLING_CONNECTOR_TOKEN`, held in config only, never a value, and no ledger database connection string; registered verdict types are read live from `billing.rules.registry`, and the connector refuses to start on a registry/rule-module mismatch; no monetary value ever appears in a payload, state, log line, or receipt |
| Connector receipt | operator-visible counted line, `billing_connector.receipts.Receipt` | beta | extends the kit's `committed`/`replayed`/`rejected` with `evaluated`/`deferred` — `deferred` is every `consent`/`enrollment` event folded into facts with no catalog fact yet linking it to an episode subject (design.md decision 4) |

Reconciliation and cutover: during the parallel-run window both this connector and the mart relay
above declare against the same subjects; a per-subject sweep must close empty-or-explained before
the relay's mart read is retired
(`openspec/changes/billing-connector/specs/verdict-reconciliation/spec.md`). Until that cutover,
this row and "Coverage and billing state" above both stand.

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
