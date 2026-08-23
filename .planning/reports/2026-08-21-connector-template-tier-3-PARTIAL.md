# Connector template — Tier 3 gap analysis (PARTIAL — run halted)

**Status**: INCOMPLETE. The tier 3 run was stopped by the operator part-way through. This file
preserves the one piece of reconnaissance that completed, so a future session does not repeat it.
It is NOT the tier 3 report; the work order at
`.planning/work-orders/connector-template/tier-3-template-mechanics.md` remains unexecuted.

**What is covered here**: Item 3.3's survey of the seven existing connectors, and the enforcement
facts needed by Item 3.2. **Not covered**: Items 3.1 (conformance suite), 3.4 (scale and
backpressure), 3.5 (catalog-version compatibility), the Options/Recommendation/LOE sections for
every item, and the recommendation for 3.3 itself.

**Verification status**: produced by a subagent with file:line citations; NOT independently
re-verified by the coordinator. Treat every claim as needing a spot-check before it is acted on.

---

## Item 3.3 — the seven existing connectors, characterised

Addressing for all seven resolves through
`packages/ocean/libs/ocean-broker/src/ocean_broker/catalog.py:139-154` (`address_for`): `source`
is always `"ocean"`, `detail-type` is exactly the domain string passed to
`publisher.publish(detail_type=...)`. An unknown domain raises `KeyError` before the bus is
touched. There is no per-connector domain-selection logic beyond that string literal.

| Connector | Reads | Emits → domain | Cursor | Direct Postgres writes | Tests |
|---|---|---|---|---|---|
| `github-connector` | GitHub webhooks, HMAC-SHA256 `X-Hub-Signature-256` | `pr.opened`/`pr.merged`/`pr.closed`, `commit.pushed` → `signals`; heartbeat → `ops` | none | none (shared DLQ only) | yes (3 files) |
| `hubspot-connector` | HubSpot batched webhooks, v3 signature + 300s replay window | `contact.created`/`deleted`/`updated` → `signals`; heartbeat → `ops` | none | none (shared DLQ only) | yes (3 files) |
| `impilo-connector` | Webhooks (`Impilo-API-Key`) **and** SQS polling of SNS fan-out, flagged by `SQS_QUEUE_URL` | `signal.received`/`patient.enrolled`/`signal.missing` → `signals`; seven order/kit/device types → `logistics`; heartbeat → `ops` | SQS delete-after-publish (at-least-once ack, not a persisted cursor) | **`audit_log` row per accepted webhook** | yes (4 files + conftest) |
| `linear-connector` | Linear webhooks, HMAC-SHA256 `linear-signature`; gated on an `"ocean"` issue label | `ticket.create.requested` → `tickets`; heartbeat → `ops` | none | none (shared DLQ only) | yes (3 files) |
| `mongodb-connector` | **MongoDB Change Streams (CDC)** — no HTTP receiver; leader election via Postgres `pg_try_advisory_lock` | `patient.feature.changed` → **`patient-state`** | **yes — resume tokens in `cdc_resume_tokens`, upserted after each publish** | `cdc_resume_tokens` + shared DLQ | **NONE — `tests/` directory does not exist** |
| `pocar-connector` | POCAR webhooks, HMAC-SHA256 `X-Pocar-Signature` | `alert.created` → `alerts`; heartbeat → `ops` | none | **`audit_log` row per accepted webhook** | yes (3 files + conftest) |
| `zcc-connector` | Zoom Contact Center webhooks, Zoom v0 signature; handles `endpoint.url_validation` inline | `call.started`/`connected`/`completed`/`missed` → `interactions`; heartbeat → `ops` | none | none; hard-fails at startup if `DATABASE_URL` absent | yes (4 files + conftest) |

### Findings that bear on the migration decision

1. **Only `mongodb-connector` emits to the `patient-state` domain**, the domain the ledger itself
   publishes on. It is also the largest (1157 lines across 6 source files), the only one with a
   real durable cursor, and **the only one with no tests at all** — its `pyproject.toml` declares
   `testpaths = ["tests"]` and pytest dev dependencies, but the directory is absent. If any of the
   seven is a candidate for conversion to a command-API declarer, this is it, and it is
   simultaneously the one with no safety net for the conversion.
2. **Two connectors write directly to Postgres beyond the shared DLQ**: `impilo-connector` and
   `pocar-connector` each insert an `audit_log` row per accepted webhook. Any migration story must
   say whether that persists, moves, or is replaced by ledger evidence.
3. **Two connectors carry explicitly unverified contracts.** `pocar-connector`'s webhook schema is
   annotated "PLACEHOLDER — validate with Brook engineering before production cutover"
   (`schema/pocar_webhook.py:3`). `zcc-connector`'s event-name mapping is flagged "MEDIUM
   confidence", unconfirmed against a live Zoom account (`normalizer.py:3-5,17-18`).
4. **PHI handling is inconsistent across connectors.** `impilo-connector` raises `ValueError` on
   any PHI key match and SHA-256 hashes patient IDs; `hubspot-connector` redacts via
   `PHI_DENY_FIELDS`/`SAFE_PROPERTY_FIELDS`; `pocar-connector` denylists raw payload keys. The
   others do none of this. A template should settle which posture is the house one.
5. **Silent-drop hazard in the shared publisher.** `EventBridgePublisher._handle_failure`
   (`packages/ocean/libs/ocean-broker/src/ocean_broker/publisher.py:137-146`) writes the envelope
   to the Postgres `failed_webhooks` table if a session maker was supplied; **if none was
   supplied, the event is logged and silently dropped** (`publisher.py:143-145`).

---

## Item 3.2 — producer-policy enforcement facts

- **Classification** lives in `packages/pulse-core/src/pulse_core/producer_policy.py`, a pure
  AST scan (no imports of producer code) against `pulse_core.generated.TRANSITIONS`. A finding
  requires subject-addressing: an entity/subject-type value equal to a catalog subject name; an
  event-type whose dot-prefix names a subject and whose remainder names one of that subject's
  states; or a state vocabulary of two or more values that is a subset of exactly one subject's
  states. Single bare words and ambiguous fits are deliberately not flagged.
- **The module never raises, exits, or logs on a violation** — it returns findings; the caller
  decides.
- **The enforcement point is `tests/test_producer_ingress_policy.py`** at the repository root —
  a plain pytest assertion (`assert findings == []` and `assert errors == []`) against the real
  `packages/ocean` tree. That file is inside `TESTED_PATHS` (`Taskfile.yml:31`), consumed by
  `task test` (`Taskfile.yml:140`), which `task check` calls unconditionally
  (`Taskfile.yml:388-399`).
- **Verdict: hard-blocking, not advisory.** A violating producer fails the same command CI runs.
  There is no warn-only mode.
- **`packages/ocean/producer-policy-suppressions.yaml` contains `suppressions: []`** — zero
  recorded adjudications, empty by design.
- `packages/ocean/docs/producer-policy.md` lists five sanctioned command sources (Twenty kanban
  webhook D8, Customer.io consent ingress D9, identity-resolution service, warehouse verdict
  runner I3, human actors via attributed tooling) and states that any other producer issuing
  commands is out of scope — "raise it before adding a new sanctioned source, don't infer one
  from a gate failure."
