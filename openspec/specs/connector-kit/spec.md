# connector-kit Specification

## Purpose
The shared primitives every pulse connector stands on — the inbound read contract, the declare
pipeline, the outbound consume loop, and the credential posture — extracted into `pulse-core`
from the three integrations that already work, so the next connector is configuration and
mapping, not re-implementation.
## Requirements
### Requirement: The kit is extracted, not invented

The connector kit's primitives SHALL be extracted from the existing integrations
(consent-ingress, verdict-relay, twenty-projection), and those packages SHALL be refactored
onto the kit in the same change that introduces it — the kit has no behavior that is not
already proven by a shipped integration, and no shipped integration keeps a private copy of a
primitive the kit provides.

#### Scenario: Existing integrations run on the kit

- **GIVEN** the kit landed and the three integrations refactored onto it
- **WHEN** demos 1 through 4 run
- **THEN** every assertion passes unchanged — the refactor is behavior-preserving

### Requirement: Inbound reads follow the row-source and cursor contract

The kit SHALL provide the inbound read contract: a row source yielding validated rows, per-row
validation that fails naming the offending row and column (never a contact or payload value),
and a durable cursor persisted through the ledger's writer-state facility scoped to the
connector's own writer id, so a crashed run resumes without loss or double-processing.

#### Scenario: A malformed row is named, the run survives

- **GIVEN** a page containing one row missing a contract column
- **WHEN** the connector reads it
- **THEN** the row is counted as an error naming its position and column, no payload value is
  logged, and the remaining rows process normally

#### Scenario: A crashed run resumes from the durable cursor

- **GIVEN** a run that persisted its cursor and then died mid-batch
- **WHEN** the next run starts
- **THEN** it resumes from the persisted cursor, and rows already declared classify as replays

### Requirement: Declares go through the shared pipeline

The kit SHALL provide the declare pipeline: client-side idempotency-key derivation (D16),
response classification (committed | replayed | rejected | transient) with retry on transient
only, and a counted receipt emitted at end of run — the operator-visible contract for every
connector run.

#### Scenario: A rerun declares nothing twice

- **GIVEN** a batch fully declared by a prior run
- **WHEN** the same batch is processed again
- **THEN** every submission classifies as replayed, no new event exists, and the receipt
  counts the replays

### Requirement: Outbound consumption follows the consume-loop contract

The kit SHALL provide the outbound consume loop: an EventBridge rule + SQS queue per
connector, event-id dedupe, delete-after-success, and a monotonic per-record watermark for
write-backs into the target system — the twenty-projection pattern generalized.

#### Scenario: A redelivered event applies once

- **GIVEN** a committed event delivered twice by the queue
- **WHEN** the consume loop processes both deliveries
- **THEN** the write-back applies exactly once and the second delivery is deleted as a dedupe
  hit

### Requirement: One connector, one credential, no ledger internals

Each connector SHALL hold exactly one writer credential of its own (actor derived from the
credential, never from payload — D15) plus the target system's credential for write-backs,
and SHALL never hold a ledger database connection: writes go through the command API, reads
through the bus. Credential names live in configuration, values in the environment, and no
credential value SHALL appear in any log, receipt, or error message.

#### Scenario: A connector cannot write ledger tables

- **GIVEN** any connector built on the kit
- **WHEN** its runtime configuration is inspected
- **THEN** it carries no ledger DSN — its only pulse-facing surfaces are the command API and
  its own queue

### Requirement: The kit's public surface is complete and versioned
The package root `pulse_core.connector` SHALL export every primitive the connector authoring guide
names, and `packages/pulse-core` SHALL carry a `CHANGELOG.md` and a Deprecations policy so a
connector author can see what changed before `uv sync` pulls it in.

#### Scenario: Guide-named primitive imports from the root
- **GIVEN** the authoring guide names `Jitter`
- **WHEN** a connector does `from pulse_core.connector import Jitter`
- **THEN** the import succeeds and `Jitter` is listed in `__all__`

#### Scenario: Kit change is announced
- **GIVEN** a change to `pulse_core.connector` that alters a public name
- **WHEN** the change merges
- **THEN** `packages/pulse-core/CHANGELOG.md` has an entry and, if a name is retired, the spec's Deprecations section names it and the replacement

### Requirement: The scaffold covers both directions and knows prior art
`task connector:new NAME=<x>` SHALL accept `DIRECTION=outbound|inbound` (default outbound), render a
working test suite including `tests/test_config.py` and `tests/factories.py`, and SHALL warn when
`<x>` matches a service under `packages/ocean/services/`.

#### Scenario: Inbound render
- **GIVEN** `task connector:new NAME=pocar DIRECTION=inbound`
- **WHEN** the render completes
- **THEN** the package's service module implements the inbound read contract (`RowSource`, `CursorStore`) and its tests pass

#### Scenario: Prior art warning
- **GIVEN** `packages/ocean/services/pocar-connector` exists
- **WHEN** `task connector:new NAME=pocar` runs
- **THEN** the output names that path before rendering and exits 0

### Requirement: The scaffold renders a working declare and registers its own typecheck posture
`task connector:new` SHALL render a `handle_page` that declares through `submit_with_retry` with a
replay assertion in its tests, and its registration diff SHALL add the package to the `typecheck`
target under the posture the rendered `pyproject.toml` declares (pyright strict), not to
`TYPED_PATHS`.

#### Scenario: Rendered connector declares
- **GIVEN** `task connector:new NAME=x`
- **WHEN** the rendered tests run
- **THEN** a fake command client records one declare per valid row and a replayed page produces no second declare

#### Scenario: Typecheck posture matches
- **GIVEN** the rendered `pyproject.toml` sets `[tool.pyright] typeCheckingMode = "strict"`
- **WHEN** `--apply-registrations` runs
- **THEN** `Taskfile.yml`'s `typecheck` target gains `uv run pyright -p packages/x` and `TYPED_PATHS` is unchanged

### Requirement: Cursor-store transport failures are actionable
`LedgerCursorStore` SHALL wrap transport failures in a kit error naming the base URL tried and the
configuration variable that supplied it.

#### Scenario: Ledger unreachable
- **GIVEN** a base URL that refuses connections
- **WHEN** the cursor store loads its cursor
- **THEN** the raised error names the URL and the variable, and no raw `httpx` traceback reaches the operator

### Requirement: The scaffold renders a package that passes the repo's own gate
`task connector:new` SHALL render, in both directions, a package whose test suite runs under
`pytest --import-mode=importlib` in the same process as every other suite in `TESTED_PATHS`, and
whose files are a `ruff format` fixed point at the repo's configured line length.

#### Scenario: Rendered suites run beside the existing connector
- **GIVEN** both directions rendered and `packages/billing-connector/tests` in the same run
- **WHEN** `pytest --import-mode=importlib` collects all three suites in one process
- **THEN** every suite imports its own fixtures and no two test packages collide

#### Scenario: Rendered tree needs no formatting
- **GIVEN** a freshly rendered connector in either direction
- **WHEN** `ruff format --check` runs over it under the repo's `pyproject.toml`
- **THEN** no file would be reformatted

### Requirement: The DevEx gate proves the connector path, not the command listing
The DevEx gate SHALL, before reporting `devex_open_findings`, exercise `task connector:new` by
rendering both directions, applying their registrations, and running the repo's own lint, format
and test gates over the rendered tree.

#### Scenario: A broken scaffold cannot read zero
- **GIVEN** a scaffold whose rendered package fails lint or collection
- **WHEN** the DevEx gate runs
- **THEN** the render-and-gate control fails and the count does not report the path as healthy

## Deprecations

A name `pulse_core.connector` retires SHALL stay exported and working for one release after the
retirement is announced, and SHALL raise `DeprecationWarning` naming its replacement on use. The
announcement SHALL land in `packages/pulse-core/CHANGELOG.md` (a "Connector authors" line under a
`### Deprecated` heading) in the same PR that starts the one-release grace window, and SHALL be
listed here until the grace window closes and the name is removed:

| Deprecated name | Replacement | Announced | Removal |
| --- | --- | --- | --- |
| _none yet_ | | | |

Removing a name SHALL delete its row here in the same PR that removes the export.
