# Legacy Harvest Appendix — Designs Held for Later

| | |
|---|---|
| **Status** | Reference — revisit and expand as needed |
| **Date** | 2026-07-28 |
| **Purpose** | Cutting-room-floor designs from the retired legacy docs, preserved so the originals can be trashed. Each entry: what it is, why it didn't enter the PULSE artifact set, and the trigger that should resurrect it. |
| **Naming note** | PULSE (Patient Unified Ledger of State & Events) now names the new platform. The retired source docs below predate and are superseded by the PULSE artifact set. |
| **Sources** | DNA-SPEC-DECLARED-STATE-PRM (2026-07-16); POCAR write-ownership matrix (2026-07-23); compliance conformance memo (2026-07-23) |

## From DNA-SPEC-DECLARED-STATE-PRM

### 1. Custom `prm_event` ledger with grant-level append-only

Full Postgres DDL: `aggregate_key` (patient_key:program_id), `aggregate_seq` with `unique(aggregate_key, aggregate_seq)` for optimistic concurrency, `idempotency_key unique` enforced in-database, UPDATE/DELETE revoked at the grant level.

- **Why cut**: Twenty's ORM owns its tables; grant-level revocation and DB-enforced uniqueness aren't available without patching core. Current design substitutes role policy + `Q_EVENT_MUTATIONS` / Snowflake dedupe.
- **Resurrect when**: the Twenty ingestion leg is outgrown (volume, or an auditor rejects policy-level immutability). This DDL is the drop-in replacement leg — the envelope already carries every column.

### 2. Optimistic concurrency (`aggregate_seq`)

Per-aggregate sequence numbers so concurrent writers can't interleave a patient's journey.

- **Why cut**: meaningless without DB enforcement (see 1); LWW-by-`occurred_at` is the accepted MVP semantics.
- **Resurrect when**: two producers race on the same patient×program in practice — look for `Q_OUT_OF_ORDER` clustering at sub-second gaps.

### 3. Outbox relay — ledger to Snowflake in seconds

Transactional outbox on the ledger, mirrored to Snowflake within seconds.

- **Why cut**: Twenty leg rides CDC (~15 min); accepted as the long pole.
- **Resurrect when**: an operating surface needs sub-minute Twenty-originated state. Pair with entry 1 — the custom leg gets the outbox for free.

### 4. Drift detector — keep the old inference SQL running as an alarm

The legacy state-inference SQL (over Customer.io/Billy/PAP side effects) keeps running after cutover and alarms when inferred state disagrees with declared state.

- **Why cut**: partially harvested — `STATE_RECONCILIATION` compares declared vs. projected, but nothing yet compares declared vs. *legacy-inferred*.
- **Resurrect when**: signal adapter goes live. This is the adapter's acceptance test: inference and declaration should converge, then the inference SQL retires to sentinel duty. Cheap — the SQL already exists.

### 5. The three money queries + flow marts

`fct_status_transitions` (from_state, to_state, dwell_seconds) and `fct_patient_status_daily`; stock, flow (avg/p90 dwell), and cohort-tail queries.

- **Why cut**: landing spec stops at current-state derivation and quality; flow marts are the *consumption* layer for the funnel PRD, which owns those requirements.
- **Resurrect when**: first sig-dash funnel report. These are the first dbt models to build on `STG_EVENTS.EVENTS` — the event grain already supports them unchanged.

### 6. Agent actors and the autonomy ladder

`actor_type = human | agent | system` with `authority` for approving human — the substrate for agentic writers whose autonomy expands gradually.

- **Why cut**: envelope fields harvested (B); the *ladder* (which actions agents may take at which autonomy tier, approval workflows) is policy design, not platform design.
- **Resurrect when**: Cortex agentic layer (P3, workstream 8) starts writing events. The attribution substrate will already be populated.

### 7. Backfill-by-replay

Existing inference SQL replays history into the ledger as system events with synthesized correlation IDs and ordered sequences, giving the March backtest candidate a substrate on day one.

- **Why cut**: folded into the signal-adapter rollout in the solution doc, but the *mechanics* (synthesized `correlation_id`, ordering discipline, `evidence` pointing at source rows) deserve their own spec before execution.
- **Resurrect when**: adapter build starts. Write `signal-adapter.md` as the next artifact at that point; sections 5.1–5.4 of the PRM doc are its outline.

## From the write-ownership matrix

### 8. Phase-gated write-ownership table

One write-owner per entity per phase; ownership flips at cutover, never gradually; no bidirectional sync. The full matrix (Patient/Referral/Provider/Clinic/Deal/Contract/Enrollment/minutes/billing/devices/tickets) with reconciliation tests and cutover triggers.

- **Why cut**: it's the governing program's doc, not this platform's — the artifact set now references its rules (identity spine, C1, C3, D2) where they bind.
- **Note**: the matrix is NOT retired material — it remains the live governing doc. Only listed here because the PULSE artifact set must stay subordinate to it.

### 9. Control Room boundary

Twenty = record-at-a-time UI; Control Room v2 = queue/aggregate UI; agents = cross-cutting. A three-way surface split that prevents the CRM from being bent into a queue tool.

- **Why cut**: P2 concern; no queue surfaces in the MVP.
- **Resurrect when**: someone asks for a work-queue view inside Twenty. The answer is Control Room, not a Twenty view.

### 10. DQ coverage matrix pattern (MECE failure domains)

The beachhead's test taxonomy: freshness/manifest, structural, grain, referential, transformation, identity, enums, volume, denominators, access, golden values — each domain owned by exactly one test type.

- **Why cut**: written for the EHR feed pipeline; the event platform's quality views cover a narrower surface.
- **Resurrect when**: the PULSE test suite formalizes into dbt. Apply the same MECE discipline to event-platform failure domains (the quality views map to about half the taxonomy already). Also the template for any data-product-testing audit.

### 11. Frozen cutpoints / golden values

Closed months frozen as dbt seeds and re-checked on every model change; rate cards seeded and exact-matched against the operational copy.

- **Why cut**: no closed periods exist yet for PULSE.
- **Resurrect when**: first month-end after go-live — freeze headline stock/flow counts as goldens so model changes can't silently rewrite history.

## From the compliance memo

### 12. Small-cell suppression for CRM aggregates

Practice-level aggregates surfaced in Twenty treated as PHI unless a §164.514 de-identification determination says otherwise; suppression below an agreed cell threshold.

- **Why cut**: MVP surfaces record-level state to authorized staff, not aggregates.
- **Resurrect when**: any rollup/aggregate field lands on a Twenty object (e.g., clinic-level enrollment counts). The threshold value is compliance-memo open item 5.

### 13. Pinned-commit policy for third-party code (C5)

Community Twenty MCP server and FHIR converter pinned to audited commits, dependency-scanned on deploy and update.

- **Why cut**: nothing — it's live policy. Recorded here because claude-code-integration-paths.md's "audit the community MCP" caveat is now governed by C5; follow it rather than improvising.

### 14. PrivateLink for the Postgres path

Available if required for transmission security on the Twenty Postgres leg.

- **Why cut**: TLS 1.2+ suffices per the memo's current mapping.
- **Resurrect when**: a client BAA or security review demands private networking for the CDC path.
