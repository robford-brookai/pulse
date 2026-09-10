## Context

The main quality job runs task check. Postgres tests use local server binaries and a Unix socket; Docker-marked tests require a separate invocation. `Taskfile.yml` names inherited service omissions. Read docs/ci-lessons.md before implementation.

## Goals / Non-Goals

**Goals:** Make critical assurance visible and mandatory without duplicating full suites or introducing credentialed tests.

**Non-Goals:** Claiming all inherited Ocean debt is resolved, setting an arbitrary total test-count target, or treating line coverage as proof of correctness.

## Decisions

### 1. Mandatory versus optional environments

Introduce an explicit required-Postgres test mode used by CI. Missing initdb/pg_ctl/postgres is a
setup error in that mode; local optional runs retain a visible skip summary. Pin/provision the server
version in CI instead of relying on runner-image contents. Record server version and run the actual
migration, atomicity, role, reversal, concurrency and replay tests. A suite selector that collects
zero critical tests or skips a required case fails. Test the missing-binary path with subprocess
fixtures; do not require uninstalling the host database to exercise it.

### 2. Transport gate without live credentials

Use the existing Docker/LocalStack integration as a separate required release/PR check with pinned
images, bounded startup and teardown. Keep the documented `task check`/quality-job contract unchanged
for the fast gate; describe the additional integration check explicitly. Where repository ruleset
configuration is necessary, create an attended GitHub tracking issue after the artifact PR merges;
do not claim a branch protection rule was configured by committing YAML.

### 3. Coverage and debt accounting

Read one combined coverage result, enforce independent 80% floors for pulse-ledger and pulse-core,
and require named invariant suites regardless of coverage. Inventory excluded Ocean paths, whether
they are reachable in the current PULSE runtime, their owner and disposition. Audit S608 and the
other security-relevant suppressions on reachable paths using synthetic regression cases. Any
confirmed reachable injection/leak blocks readiness until its focused fix merges; a list of debt
alone is not closure. Do not broaden this change into reformatting the legacy tree.

### 4. Evidence surface

Emit JSON/JUnit metadata containing commit, Python/Postgres/LocalStack versions, suite identifiers,
passed/failed/skipped counts and coverage scopes. No elapsed-time marketing score. Code/config tests
exercise collection and missing-prerequisite failures, not merely the presence of a YAML string.
Proposed 2026-09-10; these decisions gate the new verification artifacts.

## Risks / Trade-offs

[Additional CI cost] → reuse existing integration cases and run one pinned database version for invariant tests. [Required-check configuration differs from YAML] → separate attended verification receipt. [Broad suppression audit expands] → limit to reachable critical paths and file atomic repro-backed follow-ups.

## Migration Plan

Add and test required mode, then wire CI. Prove a deliberately missing prerequisite and zero collection fail in a fixture workflow. Observe the new check green before changing branch rules in an attended session. Retain historical evidence artifacts. Revert faulty wiring with an explicit gate-unavailable status, never waive the invariant.
