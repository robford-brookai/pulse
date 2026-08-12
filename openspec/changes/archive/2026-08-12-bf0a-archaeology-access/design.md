# Design — bf0a-archaeology-access

## Context

See proposal.md — Why. Constraints: the Mongo connection pattern already exists in
`brookai/streamline` and MUST be inherited (driver, TLS posture, retry config), located by
searching that repo for client construction (`pymongo`, `motor`, connection-string assembly) —
cross-repo inheritance is by reading, not by side-cloning into this repo
(`docs/contracts/consumes.md` gets the entry). HIPAA/SOC2 posture throughout; the operator
provisions the read-only Atlas user and secret-store entries (BF-0 operator setup item 4); this
change defines the env var names BF-0b consumes.

## Goals / Non-Goals

**Goals:** one access seam; refusal-on-write-roles; receipt-producing smoke CLI; env var names
documented as the interface to the operational session.

**Non-Goals:** extraction (BF-0b samples in memory, Stage 2 extracts), satellite-store
connectors (BF-0c), CDC consumers, remediation of findings.

## Decisions

1. **Package `packages/archaeology`**, module `archaeology`, workspace member per the monorepo
   template — sits beside `pulse-ledger`/`pulse-core`, uses the same uv/ruff/mypy/pytest wiring.
2. **Driver follows streamline** — recorded in `docs/contracts/consumes.md` as a consumed
   pattern with the source path cited in the README, so drift from upstream is a documented
   divergence, not an accident.
3. **Write-role detection** via `connectionStatus`/`usersInfo` where the role grants permit it;
   when not detectable, construction proceeds (the Atlas role is the control) and the README
   says so plainly.
4. **Env var names**: `ARCHAEOLOGY_MONGO_HOST`, `ARCHAEOLOGY_MONGO_USER`,
   `ARCHAEOLOGY_MONGO_PASSWORD_REF` (a secret-store reference resolved at runtime), plus TLS
   toggles mirroring streamline. Names are the BF-0a→BF-0b interface and land in the README.

## Risks / Trade-offs

- **Streamline's pattern may not be locatable or may be outdated** → the worktree agent records
  what it found and inherited in HANDOFF.md; a missing pattern is a spec defect returned to
  validate, not an invitation to invent.
- **Write-role detection is best-effort** → stated openly; the control is the Atlas role the
  operator provisions.
