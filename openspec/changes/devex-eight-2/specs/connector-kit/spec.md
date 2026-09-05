# connector-kit

## MODIFIED Requirements

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
