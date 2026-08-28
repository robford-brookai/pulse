# ocean package absorption Specification

## Purpose

Governs how the OCEAN codebase enters the PULSE monorepo as the workspace package `packages/ocean`:
what may cross the boundary, what must not, and what must be true of the source repository before
the import runs.

## Requirements

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

### Requirement: Imported package is linted by the monorepo toolchain

The imported package SHALL be covered by the monorepo's formatter and linter in a commit separate
from the import, so that the import diff stays reviewable as a pure move.

Lint is separated from typecheck and test deliberately. Ocean's tests need Postgres and Kafka —
18 of its test modules fail collection without them — and its libraries have unresolved import
errors. Those are real work, not configuration, and folding them into one "conformance" step
invites narrowing the gate until it passes rather than doing the work.

#### Scenario: Formatter and linter cover the package

- **WHEN** `task lint` runs after the conformance commit
- **THEN** it checks every Python file under `packages/ocean` and passes

#### Scenario: Import and conformance are separate commits

- **WHEN** the import lands
- **THEN** the import commit changes no file content, and configuration changes appear only in the
  follow-up commit

#### Scenario: Bulk reformatting does not destroy provenance

- **GIVEN** adopting the monorepo's formatter reformats the imported tree wholesale
- **WHEN** that reformat lands
- **THEN** it is its own commit, listed in `.git-blame-ignore-revs`, so `git blame` still reaches
  the history the import existed to preserve

### Requirement: A gate must not claim coverage it does not have

Every quality target SHALL apply to exactly the paths its configuration names. A variable that
lists a path while the command hardcodes another is a false claim about what CI verifies, and is
worse than an honestly narrow gate because it reads as covered.

Where a target cannot yet cover the imported package, that exclusion SHALL be visible in the
configuration itself, not only in a handoff.

#### Scenario: Declared scope matches executed scope

- **WHEN** a quality target runs
- **THEN** the paths it executes against are the paths its variables declare

#### Scenario: An uncovered package is named as uncovered

- **GIVEN** `packages/ocean` is not yet typechecked or tested
- **WHEN** someone reads `Taskfile.yml`
- **THEN** the exclusion and its reason are stated there
