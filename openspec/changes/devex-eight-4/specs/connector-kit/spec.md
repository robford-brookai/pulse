# connector-kit

## MODIFIED Requirements

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
