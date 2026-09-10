## Why

Pulse needs a repeatable Engineering demonstration that exposes real integration defects and proves its append-only ledger through API requests, operational projections, and batch recovery. A single synthetic golden patient does not establish that POCAR and PAP can hydrate the platform or that a demo can return to zero safely.

## What Changes

- Select POCAR as the primary connector and PAP as the second; discover their source contracts using their MCP metadata and approved read-only access before implementing one bounded event family per source.
- Demonstrate create commands and reads of state/history via Pulse APIs for both sources, with immutable original events and appended transitions/corrections.
- Model Twenty objects, relationships, state fields, and key-event views from the verified connector mappings.
- Add resumable batch hydration and a separate evidence-backed historical backfill path through the command API.
- Extend the existing end-to-end demo with record detail, cohort operations, fault recovery, projection reconstruction, and isolated demo-only reset/reload.
- Provide a synthetic runnable Engineering presentation and an attended real-data rehearsal using the same adapters inside the approved data boundary.

## Capabilities

### New Capabilities

- `engineering-demo`: Source discovery, connector/API demonstrations, Twenty projection, batch ledger hydration, presentation, and demo reset acceptance.

### Modified Capabilities

None. Existing ledger immutability, authorization, connector, identity and projection contracts remain binding; a discovered incompatibility requires a targeted replan before implementation.

## Impact

Reuse `pulse_core.connector`, `packages/archaeology`, `scripts/demo/demo5_end_to_end.py`, the command/read APIs and existing Twenty projector. Update producer-registry rows with each new ingress. Coordinate shared implementation with the queued pocar-relay, genesis-adjudication-rules and genesis-seed-run roadmap work; do not build competing loaders or reconstruction rules. This PR proposes work only and does not claim connectors or live access exist here.

Rollback: stop demo producers and retain redacted failure receipts; abandon only the manifest-owned disposable target after fencing delivery. Never mutate source systems or erase the authoritative ledger. Existing demo commands remain supported until the replacement passes acceptance.
