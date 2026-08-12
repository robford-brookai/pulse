## Purpose

The D4 deploy step: the only path by which the Twenty metadata artifact reaches an instance.
Reads a validated artifact, applies it idempotently to a named target, and promotes the same
artifact dev → staging → prod. Live verification is gated on the Twenty dev instance
(DNA-909).

## ADDED Requirements

### Requirement: Only a validated artifact is applied

The deploy step SHALL take an artifact file and a named target, run the artifact validation
before any operation is sent, and refuse to apply an artifact that fails validation. It SHALL
contain no generation logic: the artifact is its complete input.

#### Scenario: An invalid artifact is refused before any operation

- **GIVEN** an artifact file that fails schema validation
- **WHEN** the deploy step runs against any target
- **THEN** it exits nonzero naming the validation failure, and no operation is sent

### Requirement: Apply is idempotent and never deletes

The deploy step SHALL key every operation on `universalIdentifier`: create when absent, update
when drifted, no-op when identical — and SHALL never delete an object, field, or option not
named in the artifact. Re-applying the same artifact to the same target SHALL result in zero
mutating operations.

#### Scenario: Re-apply of the same artifact is all no-ops

- **GIVEN** a target whose state matches an artifact (via a scripted transport fake)
- **WHEN** the deploy step applies that artifact again
- **THEN** the receipt reports zero creates, zero updates, and no delete is ever attempted

### Requirement: Promotion is the same artifact, next target

Target resolution SHALL map a target name to URL and credential from the environment — never
from code or the artifact — so that promoting dev → staging → prod is the identical artifact
file applied to successive targets. The deploy step SHALL record in its receipt the artifact
checksum it applied, making cross-environment identity checkable.

#### Scenario: Two targets, one artifact, matching checksums

- **GIVEN** one artifact applied to two named targets (scripted transports)
- **WHEN** both receipts are compared
- **THEN** both carry the same artifact checksum

### Requirement: Dry-run plans without a socket

`--dry-run` SHALL print the full operation plan (creates/updates/no-ops by name) computed
against the target's fetched state when reachable, or against an empty-state assumption when
invoked offline, and SHALL send no mutating operation. The dry-run used in tests SHALL run
under disabled sockets with a fixture transport.

#### Scenario: Dry-run sends nothing

- **GIVEN** a valid artifact and a fixture transport
- **WHEN** the deploy step runs with `--dry-run` under disabled sockets
- **THEN** the plan prints, exit status is zero, and the transport records zero mutating calls

### Requirement: Receipts carry names and counts, never workspace data

Deploy receipts and error output SHALL carry object/field/option names, operation counts, and
the artifact checksum only. Error paths SHALL NOT echo response bodies, which on a live
workspace could carry record data.

#### Scenario: A failed operation's receipt is safe to attach

- **GIVEN** a scripted transport that fails one operation with a body containing a synthetic
  record value
- **WHEN** the deploy step reports the failure
- **THEN** the receipt and all log output name the operation and status but contain no part of
  the response body's record value

### Requirement: Live dev verification is gated on the dev instance

Applying the artifact to the live dev instance and verifying it by schema read-back — every
artifact operation's target present, identifiers matching the UID map — SHALL occur before any
downstream change consumes the model, and SHALL be dispatched only once the Twenty dev
instance exists (DNA-909). Until then, every test of the deploy step runs against a scripted
transport.

#### Scenario: Read-back matches the artifact

- **GIVEN** the dev instance provisioned per DNA-909 and the artifact applied to it
- **WHEN** the schema is read back through the Metadata API
- **THEN** every object, field, and option in the artifact is present with its mapped
  `universalIdentifier`, and the verification receipt is attached to the change's Linear parent
