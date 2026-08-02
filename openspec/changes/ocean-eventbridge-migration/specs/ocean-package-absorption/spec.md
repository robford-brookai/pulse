## Purpose

Governs how the OCEAN codebase enters the PULSE monorepo as the workspace package `packages/ocean`:
what may cross the boundary, what must not, and what must be true of the source repository before
the import runs.

## ADDED Requirements

### Requirement: Import carries only allowlisted paths

The import SHALL admit paths by explicit allowlist, never by exclusion list. Only `services/`,
`libs/`, `infra/`, `tests/`, `scripts/`, `docs/`, `.github/`, and the root project files
(`pyproject.toml`, `uv.lock`, `Taskfile.yml`, `pyrightconfig.json`, `main.py`, `README.md`,
`.python-version`, `.markdownlint.json`) SHALL appear under `packages/ocean`.

An exclusion list is not acceptable: it admits by default anything added to the source tree after
this specification was written.

#### Scenario: Side-cloned repositories are absent

- **GIVEN** the source tree tracks 309 files under `.repos/`, including a 305-file `streamline`
  clone
- **WHEN** the import completes
- **THEN** `git ls-files packages/ocean` matches no path containing `.repos/`

#### Scenario: Agent state is absent

- **GIVEN** the source tree tracks `.planning/` (289 files), `.gsd/` (132 files), `.claude/`,
  `.vscode/`, `.bg-shell/`, and `logs/`
- **WHEN** the import completes
- **THEN** none of those directories exist under `packages/ocean`

#### Scenario: Superseded root files do not overwrite the monorepo's own

- **GIVEN** the source tree carries its own `agents.md`, `CLAUDE.md`, and `.gitignore`
- **WHEN** the import completes
- **THEN** none of those three files exist under `packages/ocean`, and the monorepo's own
  `AGENTS.md`, `CLAUDE.md`, and `.gitignore` are unmodified

#### Scenario: A path added to the source after this spec does not enter

- **GIVEN** a directory not named in the allowlist exists in the source tree at import time
- **WHEN** the import completes
- **THEN** that directory does not exist under `packages/ocean`

### Requirement: Import preserves commit history for allowlisted paths

The import SHALL preserve the source repository's commit history for every allowlisted path.
History preservation is the audit posture for a HIPAA-scoped system: each backbone design decision
must keep its commit trail inside the organization boundary.

#### Scenario: History is reachable after import

- **WHEN** `git log -- packages/ocean` is run on the monorepo after the import
- **THEN** it returns the source repository's commits for the allowlisted paths, not a single
  squashed import commit

#### Scenario: Files arrive at the package prefix

- **WHEN** the import completes
- **THEN** every imported file's path begins with `packages/ocean/`, and its history is reachable
  at that path without a rename follow

### Requirement: Credentials in the source repository are rotated before import

The source repository tracks a `.env` file. Every credential in it SHALL be rotated before the
import runs.

Rewriting history in the imported copy does not revoke a credential, and archiving the source
repository does not either — the source repository's own history continues to expose whatever was
committed. Excluding `.env` from the allowlist is therefore necessary but not sufficient.

#### Scenario: No secret file reaches the monorepo

- **WHEN** the import completes
- **THEN** no `.env` file exists under `packages/ocean`, and no commit reachable from the imported
  history adds one

#### Scenario: Rotation precedes import

- **GIVEN** credentials in the source `.env` have not been rotated
- **WHEN** the import is attempted
- **THEN** the import is blocked until rotation is confirmed

### Requirement: Imported package conforms to the monorepo toolchain

The imported package SHALL adopt the monorepo's lint, typecheck, and test configuration in a
follow-up commit separate from the import commit, so that the import diff stays reviewable as a
pure move.

#### Scenario: Package builds inside monorepo CI

- **WHEN** `task check` runs after the conformance commit
- **THEN** it passes with `packages/ocean` included

#### Scenario: Import and conformance are separate commits

- **WHEN** the import lands
- **THEN** the import commit changes no file content, and configuration changes appear only in the
  follow-up commit
