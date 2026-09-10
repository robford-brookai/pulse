## Why

The connector kit provides durable submission primitives, but source extraction guarantees remain implicit or tied to the old PAP CDC draft. POCAR and PAP implementations need a shared, testable source contract before hydration and history replay can be trusted.

## What Changes

- Add a versioned source capability manifest and conformance suite covering extraction, identity, recovery, provenance, resource budgets, and reconciliation.
- Support polling, CDC, and push as alternatives with explicit guarantees and capability gaps.
- Separate Pulse-owned extraction and command submission from source-owned interface repairs and demo-client state/history reads.
- Establish safe adoption without changing existing public kit APIs or granting connectors ledger read/database access.

## Capabilities

### New Capabilities

- `connector-source-contracts`: Observable and testable guarantees required of a source adapter and its operational handoff.

### Modified Capabilities

None. The connector-kit requirements remain in force; this adds a source-boundary contract.

## Impact

Future work affects `pulse_core.connector`, source manifests, connector authoring documentation, and synthetic conformance tests. POCAR/PAP mappings and Twenty modeling belong to the engineering demo change. No source access, credential creation, or deployment occurs in this proposal. Adoption is additive; rollback disables a new adapter, retains its durable checkpoints and receipts, and resumes only with a compatible mapping version rather than rewinding the ledger.
