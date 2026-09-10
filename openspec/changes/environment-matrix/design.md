## Context

Read environment-matrix-seed.md, runtime-readiness §2, ADR-0004 D14 and the existing Duplo JSON. The seed originally requires a green Synthea workflow and a free change slot before proposal creation. Neither is presumed verified in this review.

## Goals / Non-Goals

**Goals:** A release can be identified, reproduced, deployed and rolled back without manual image retagging or drift between API and relay.

**Non-Goals:** Running production cutover, resetting shared environments, duplicating billing-cutover, choosing SPCS versus Duplo without the D14 receipt, or claiming local JVM output is universally byte-identical.

## Decisions

### 1. Planning exception, execution holds preserved

The owner explicitly requested the required proposals on 2026-09-10. This files the seed's plan for
review before its two entry receipts are verified; it does not assert those gates cleared. Record
that narrow planning exception in the seed/roadmap. All implementation dispatch stays held until
a successful Synthea verification run on main (repin=false, matching committed manifest) is linked
and one of the two execution slots is free. A re-pin run alone is not a verification receipt.
If generation is still broken, file the smallest failure-log-backed fix; do not silently re-pin.

### 2. Runtime selection remains D14's decision

Offline configuration and manifest validation can be defined now. Before infrastructure wiring,
attach the D14 spike/fallback receipt that authorizes the target runtime. Current Duplo templates
are the implemented dev path, not evidence that an SPCS decision was superseded. If the receipt
requires a different adapter, replan the wiring tasks before dispatch; do not deploy a guessed
architecture. No resource identifier or secret value is invented in a checked-in environment map.

### 3. Release manifest is the unit of promotion

Define a versioned JSON schema: source commit, service→image digest map, catalog version, migration
heads, Twenty artifact checksum, synthetic artifact run id/checksum, and target-independent build
metadata. Environment maps contain tenant/registry/endpoint identifiers and secret references, never
secret values. Build once, resolve digests, then use the same manifest for staging and production.
Reject mutable-only tags, mixed manifests, missing components and target/credential mismatches.
The ledger deploy target must push the fully qualified registry image, update API and relay, await
readiness and compare actual digests/migration heads; a docker push alone is not success.

### 4. Synthetic staging and parity

Consume only a successful verified workflow's artifact from its recorded runner/toolchain and
manifest. The staged population is synthetic (~50k profile), and the loader checkpoints/idempotently
resumes through existing APIs. A 500-patient local fixture validates the same code without a long
generation in task check. Cover command round-trips for catalog families, signed board heal-back,
freshness, projection rebuild and failure midway through loading. Preserve the existing same-artifact
Twenty build/apply split. Verify staging metadata against the promotion artifact, not against an
assumed production instance. Drift aborts promotion.

### 5. Rollback and evidence

Preflight migration compatibility before rolling any service; mixed digest/readiness failure is a
failed deployment with previous release manifest recorded. Reapply the previous compatible manifest
in an attended synthetic rehearsal. Do not downgrade append-only ledger data automatically. Receipt
records desired/actual identities, migration compatibility, smoke outcomes, rollback outcome and
operator timestamps. Existing reconciliation clean-cycle and M1 live receipts remain separate gates.

## Risks / Trade-offs

[Synthea has no successful verification] → dispatch remains held and failure is investigated separately. [Runtime decision receipt missing] → wiring held; no implicit switch. [Partial rollout] → compare every service digest and abort promotion. [Schema cannot roll back] → compatibility preflight and forward repair.

## Migration Plan

Verify seed prerequisites and D14 receipt. Land manifest/config tooling and tests, then runtime-specific wiring after receipt review. In an attended session provision staging using existing ownership, verify synthetic artifact, load and smoke, rehearse rollback, and attach evidence. Production promotion is a later attended release/cutover act, never an automatic result of proposal merge.
