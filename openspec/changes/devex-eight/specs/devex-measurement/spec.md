# devex-measurement

## ADDED Requirements

### Requirement: Open findings are counted deterministically and ratchet to zero
The repo SHALL provide `task devex:check`, which runs `tests/scaffold/cat10_devex.py`, prints one
line `METRIC devex_open_findings=<n>` where n is the number of xfail results, and exits nonzero if
any finding test fails outright (a regression) or an xfail-marked test passes (a fixed finding
whose marker was not removed).

#### Scenario: Baseline count
- **GIVEN** the repo at the wave-0 merge commit
- **WHEN** `task devex:check` runs
- **THEN** stdout contains `METRIC devex_open_findings=` followed by the count of xfail tests in cat10 and the exit code is 0

#### Scenario: Regression fails the gate
- **GIVEN** a finding test with no xfail marker
- **WHEN** the defect it guards is reintroduced
- **THEN** `task check` fails on that test and `task devex:check` prints a `REGRESSION` line and exits 1

### Requirement: The audit protocol is frozen by checksum
The files `README.md`, `rubric.md`, `task-a.md`, `task-b.md`, `task-c.md` under
`docs/process/devex-audit/` SHALL be hashed into `docs/process/devex-audit/CHECKSUMS`, and both
`cat10_devex.py` and `scripts/devex/check.py` SHALL fail when any hash differs.

#### Scenario: Protocol edited without refreezing
- **GIVEN** `rubric.md` edited and `CHECKSUMS` unchanged
- **WHEN** `task check` runs
- **THEN** `test_audit_protocol_is_frozen` fails naming the file

#### Scenario: Protocol PR refreezes
- **GIVEN** a protocol change PR
- **WHEN** `uv run python scripts/devex/check.py --freeze` runs
- **THEN** `CHECKSUMS` is rewritten and `--verify-only` exits 0

### Requirement: Only the outer audit produces a 0-10 score
No script or gate in the repo SHALL print a 0-10 DX score. The scorecard produced by the
`/devex-audit` protocol is the only source of `overall` and `connector` values, recorded in
`.planning/devex/loop.jsonl` with the QA verdict.

#### Scenario: Ledger row from an audit
- **GIVEN** a completed `/devex-audit` run with a QA verdict
- **WHEN** the coordinator appends the ledger row
- **THEN** the row has `kind: audit`, `overall`, `connector`, `qa`, and `open_findings` at that HEAD

#### Scenario: Exit gate
- **GIVEN** the latest ledger audit row
- **WHEN** `overall >= 8.0` and `connector >= 8.0` and `qa` is accept or accept-with-corrections
- **THEN** the loop ends and the result is reported as the exit gate holding
