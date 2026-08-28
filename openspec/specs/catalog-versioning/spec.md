# catalog-versioning Specification

## Purpose
Makes every catalog release an immutable, classified version: frozen snapshots, the D18
breaking-change rule, and the migration-note ceremony breaking releases must pay — all enforced
offline in `task check`.
## Requirements
### Requirement: Every release is an immutable snapshot

Every released catalog version SHALL be frozen as a byte-identical snapshot file under
`catalog/releases/`, recorded in an append-only checksum manifest. The check suite SHALL verify
that the head catalog equals the snapshot of its own `catalog_version` and that every past
snapshot still matches its manifest checksum — a rewritten history is a hard failure, offline,
with no credentials or network.

#### Scenario: The head catalog matches its release snapshot

- **WHEN** the check suite runs on a tree whose head catalog and current-version snapshot are
  byte-identical and whose manifest checksums all hold
- **THEN** the snapshot gate passes

#### Scenario: A tampered snapshot fails the gate

- **WHEN** any past snapshot no longer matches its manifest checksum, or the head catalog
  differs from the snapshot bearing its version
- **THEN** the check suite fails naming the version whose history was rewritten

### Requirement: Releases are classified against the breaking-change rule

A release SHALL be classified breaking when, relative to the previous released version, it
removes a state, narrows a ValueSet, or changes a transition's legality (in either direction —
the rule is verbatim from runtime-readiness §4.3). Purely additive releases — new states, new
commands, widened ValueSets, new programs — SHALL classify non-breaking.

#### Scenario: A removed state classifies breaking

- **WHEN** the new version drops a state the previous version declared
- **THEN** the release classifies breaking, naming the removed state

#### Scenario: A narrowed ValueSet classifies breaking

- **WHEN** the new version removes a code from a ValueSet the previous version carried
- **THEN** the release classifies breaking, naming the ValueSet and the removed code

Legality is a property of a `(subject, from, to)` pair both versions can express: an edge whose
endpoint state exists only in the newer version was undefined before, not illegal, so legality
findings are raised only over states both versions declare (execution reconciliation, task 3.1 —
this is what makes "adds states, transitions targeting them" additive rather than breaking).
Removed commands or programs are deliberately NOT breaking under the §4.3 rule.

#### Scenario: A transition legality change classifies breaking

- **WHEN** the new version removes a previously legal transition or adds a previously illegal
  one
- **THEN** the release classifies breaking, naming the transition edge that changed

#### Scenario: An additive release classifies non-breaking

- **WHEN** the new version only adds states, transitions targeting them, ValueSet codes, or
  programs
- **THEN** the release classifies non-breaking

### Requirement: Breaking releases pay the migration ceremony

A breaking release SHALL increment the major version and SHALL ship a migration note in the
release PR containing a consumer checklist — Twenty metadata redeploy, ConceptMap regeneration,
and a rule_version bump if verdict criteria reference the changed codes. The check suite SHALL
fail a breaking release missing either the major bump or the migration note, so the ceremony is
enforced by CI, not convention.

#### Scenario: A breaking release without a migration note fails the check

- **WHEN** the two most recent snapshots diff as breaking and no migration note exists for the
  new version, or the major version did not increment
- **THEN** the check suite fails naming the missing artifact

#### Scenario: An empty migration note fails the check

- **GIVEN** a breaking release whose `v<version>-migration.md` exists but is empty or
  whitespace-only
- **WHEN** the ceremony check runs
- **THEN** it fails naming the note, the same as a missing one — an empty note carries no
  consumer checklist (note prose beyond non-emptiness is reviewed by humans in the release PR,
  never parsed by CI)

#### Scenario: A conformant breaking release passes

- **WHEN** a breaking release increments the major version and ships a migration note carrying
  the consumer checklist
- **THEN** the check suite passes the release
