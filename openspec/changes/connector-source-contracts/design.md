## Context

See proposal.md for motivation. `openspec/specs/connector-kit/spec.md` is the shipped kit contract: row sources, durable cursors, command submission, bus consumption, one writer credential and no ledger DSN. The older `openspec/specs/connectors/pulse-standard-connector-spec.md` is a draft with PAP-first CDC, WAL-derived identity, payload-filled DLQs, payload actor fields and a legacy drift sentinel. Those assumptions are not a universal source contract and must not override shipped credential-derived actor policy or current roadmap decisions.

## Goals / Non-Goals

**Goals:** Make source limitations executable acceptance inputs; share synthetic conformance cases with the POCAR/PAP demo; preserve existing public API behavior.

**Non-Goals:** Building either production adapter, selecting unverified source collections, enabling live access, changing ledger authorization, inventing historical transitions, or implementing Twenty's source-specific model here.

## Decisions

Decided 2026-09-10; these choices gate new POCAR/PAP adapter acceptance.

1. Add a versioned manifest alongside each future adapter and validate it before extraction. It records source/owner, extraction mode, source schema and mapping versions, identity namespace and incarnation, pagination ordering and consistency, cursor/watermark/token expiry, deletion handling, history availability, time provenance, retry/rate/concurrency budgets, credential references, protected hold retention, reconciliation thresholds and runbook owner. Capability evidence is a reference and review status, never source payload. Unknown guarantees block the relevant mode rather than silently taking defaults. A freeform README alone is insufficient to enforce this.
2. Support polling, CDC and push independently. Offline protocol fixtures test each supported mode; an adapter is not required to implement all three. Source engineering repairs missing identifiers, API ordering, deletion feeds or event hooks only when required by the chosen mode. Pulse owns pull scheduling, extraction, mapping and command submission. Discovery through Fonzie/MCP does not establish a bulk extraction transport or certify source permissions.
3. Reuse the kit's existing submission and writer-state surfaces. Extend the adapter conformance surface additively: manifest validation, synthetic source pages/change positions, expected commands and counted outcomes. Do not redesign retry primitives or add connector state/history privileges. A separate demo client uses independently scoped state/history API access; connectors continue command writes and bus reads.
4. Use a declared source observation identity and version, with canonical serialization and a documented collision domain. Snapshot rows often lack log positions: either a shared event identity exists or the adapter must prove a cut boundary and reconcile overlap. Never invent WAL positions to fit the old draft. New mapping versions require an explicit replay/migration decision so a rerun cannot quietly produce different commands under the same key.
5. Checkpoints represent durable disposition of every preceding observation, not simply the last fetched page. A protected hold may permit advancement only if replay metadata and ownership are durable. A command timeout can mean committed; retry the same key before progression. Raw error payloads cannot enter public logs or plan receipts.
6. Reconciliation compares distinct source observations with disjoint accepted, replayed, held, rejected and explicitly excluded outcomes; submission attempts are separate counters. Record lag and unexplained discrepancies with thresholds and named ownership. Synthetic fixtures must deliberately fail a receipt to prove it is a gate.

## Data Model and API Surface

The manifest is versioned configuration, not a new ledger entity. Checkpoint metadata binds source identity, extraction boundary, mapping version and durable disposition; sensitive recovery data remains in the approved store. Contract tests exercise existing command API clients with fake transports and source protocol fixtures. This proposal introduces no public endpoint or credential. A future new writer/ingress must update `docs/contracts/producer-registry.md` in the same implementation change.

## Risks / Trade-offs

- Sources cannot provide complete history → mark coverage and gaps; limit supported claims and use genesis evidence instead of invented history.
- Timestamp polling misses edits/deletes → require overlap, stable tie-breakers and deletion accounting or declare the mode unsupported.
- Stronger validation disrupts existing adapters → introduce opt-in conformance, publish migration guidance, and gate new adapters first; do not break public kit APIs.
- Source data in error paths → synthetic sentinel tests verify safe diagnostics and protected recovery boundaries.

## Migration Plan

Implement the manifest and offline conformance suite first, then adopt them in the engineering demo's POCAR/PAP mappings. Task 1.9 publishes an authoring authority map: shipped kit remains binding; this new capability becomes binding when implemented and archived; the PAP draft remains historical guidance only where compatible. Baseline spec edits occur through doc-update/archive, not by silently changing that draft during proposal creation. No currently shipped behavior is claimed to satisfy the proposed contract without conformance evidence.

Rollback disables the new adapter or restores a compatible mapping/configuration version while retaining checkpoints and receipts. It never truncates the authoritative ledger or advances past an unaccounted source position. Any live validation belongs to an attended operational issue after its runbook PR is reviewed.
