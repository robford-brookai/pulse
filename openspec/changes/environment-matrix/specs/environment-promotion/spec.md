## Purpose

Provides immutable release identity, isolated environment targeting and reproducible synthetic staging and rollback evidence before promotion.

## ADDED Requirements

### Requirement: Execution prerequisites remain held until evidenced

This proposal SHALL NOT release implementation until a successful Synthea verification on main with repin=false matching the committed manifest and a free slot under the two-change execution limit are evidenced. Infrastructure wiring SHALL additionally require the D14 runtime decision receipt. A different authorized runtime SHALL trigger replanning before dispatch; no architecture choice SHALL be inferred from existing dev templates.

#### Scenario: Missing seed or runtime evidence holds execution

- **GIVEN** a filed proposal without the required Synthea verification, free slot or applicable D14 receipt
- **WHEN** implementation or infrastructure wiring is considered
- **THEN** implementation stays held until seed receipts exist and runtime wiring stays held until the D14 decision is evidenced; a re-pin run alone does not clear verification

### Requirement: Promotion uses one immutable complete release identity

A versioned release manifest SHALL identify source commit, per-service immutable image digests, catalog version, migration heads, Twenty artifact checksum, synthetic artifact run/checksum and target-independent build metadata. Environment maps SHALL use credential references without secret values. Deployment preflight SHALL reject mutable-only identity, missing components, mixed manifests and target/credential mismatches. Staging and production SHALL consume the same built artifacts.

#### Scenario: Incomplete or unsafe release target is rejected

- **GIVEN** a manifest or target fixture has a mutable-only image, missing component, mixed identity or credential mismatch
- **WHEN** promotion preflight runs
- **THEN** it fails before rollout and identifies the invalid component without exposing secret values

#### Scenario: Built artifact identity is stable across environments

- **GIVEN** a complete validated release manifest and valid environment maps
- **WHEN** staging and production promotion inputs are derived
- **THEN** the per-service digests and artifact checksums remain unchanged while only authorized environment references differ

### Requirement: Deployment proves actual runtime convergence

Deployment SHALL push fully qualified registry images, update all intended API and relay services, await readiness and compare actual image digests and migration heads with the release manifest. A push alone SHALL NOT report deployment success. Drift, failed readiness or partial rollout SHALL stop promotion and record the previous release identity.

#### Scenario: Partial rollout is a deployment failure

- **GIVEN** a release where the API updates but relay digest or migration identity remains mismatched
- **WHEN** deployment verification runs
- **THEN** deployment fails, promotion stops, and desired/actual identities and the previous manifest are recorded

### Requirement: Synthetic staging proves parity with resumable loading

Staging SHALL consume a successful verified workflow artifact with recorded runner/toolchain and manifest identity for the approximately 50000-patient profile. A 500-patient local fixture SHALL validate the same loading behavior. Loading SHALL checkpoint and resume idempotently through existing APIs. Staging acceptance SHALL cover catalog command round-trips, signed board heal-back, freshness and projection rebuild against the promotion artifact. Twenty build/apply SHALL preserve same-artifact identity.

#### Scenario: Synthetic loading resumes without duplicate effects

- **GIVEN** a verified synthetic artifact and a loader interrupted midway
- **WHEN** loading resumes from its checkpoint using the local fixture or staged profile
- **THEN** previous effects are not duplicated and all expected synthetic subjects are loaded through the supported APIs

#### Scenario: Staging parity covers supported end-to-end behavior

- **GIVEN** staging loaded from the verified artifact and intended release manifest
- **WHEN** round-trip, signed heal-back, freshness and rebuild checks run
- **THEN** catalog families produce expected results, projections reconcile, and actual artifact/release identities match the intended promotion inputs

#### Scenario: Unverified or unavailable synthetic artifacts are rejected

- **GIVEN** artifact fixtures from a failed run, a repin-only run without subsequent repin=false verification, an expired or unavailable workflow artifact, and a checksum that differs from the committed manifest
- **WHEN** staging artifact preflight evaluates each fixture
- **THEN** each fixture is rejected before loading; no local regeneration, silent re-pin or unverified replacement is accepted as the missing successful verification artifact

### Requirement: Rollback respects migration compatibility

Rollout SHALL preflight database compatibility and retain the previous manifest. An attended synthetic rollback rehearsal SHALL reapply the previous compatible manifest and record desired/actual identities, smoke results and timestamps. Irreversible ledger schema/data changes SHALL require forward repair rather than automatic downgrade. Production cutover and existing reconciliation/M1 receipts SHALL remain separate prerequisites.

#### Scenario: Compatible rollback restores verified release

- **GIVEN** a synthetic deployment with a retained previous compatible manifest
- **WHEN** an attended rollback rehearsal reapplies that manifest
- **THEN** all intended services converge to its identities and smoke outcomes and timestamps are recorded

#### Scenario: Incompatible downgrade is refused

- **GIVEN** a release whose database change is incompatible with the previous application/schema
- **WHEN** rollback preflight evaluates the prior manifest
- **THEN** automatic downgrade is refused and forward repair is required without deleting append-only ledger history
