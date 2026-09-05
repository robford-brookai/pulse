# connector-kit

## MODIFIED Requirements

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
