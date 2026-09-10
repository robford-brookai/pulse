## MODIFIED Requirements

### Requirement: Commands are idempotent by client-supplied key

Every command SHALL carry an idempotency key of the form
`{writer_id}:{sha256(subject, command_type, payload, logical_time)}`, unique-constrained in the
ledger for the ledger's lifetime. An exact retry by the same authenticated writer SHALL return the original commit result (with the
prior event id) and SHALL never produce a second event. Before replay, the API SHALL verify the
key binding to authenticated writer identity and a versioned canonical accepted-request fingerprint.
Client-supplied key prefixes SHALL NOT establish authenticated identity. Different writer identity
or semantically different accepted request content under an existing key SHALL be rejected without
writing a second event or disclosing the original result (amendment to D16).

#### Scenario: Retry after timeout is a replay

- **GIVEN** a command that committed but whose response was lost
- **WHEN** the writer retries with the same idempotency key
- **THEN** the API returns the original event id marked as a replay, and history contains exactly
  one event

#### Scenario: Distinct facts never share a key

- **GIVEN** an already committed command
- **WHEN** the same writer declares the same command type for the same subject at a new
  `logical_time`
- **THEN** the key differs and a second event commits

#### Scenario: Mismatched key reuse is rejected

- **GIVEN** an existing key binding
- **WHEN** the same writer changes accepted semantic content or another authenticated writer reuses the key
- **THEN** single-command HTTP returns 409 with idempotency_conflict, no second event is written, and the original event/result is not disclosed

#### Scenario: Canonical exact retry remains compatible

- **GIVEN** an accepted command whose object field order or equivalent UTC spelling differs on retry
- **WHEN** the same writer retries with the original key
- **THEN** the original result is replayed; list order and semantically different values remain distinguishable, and client-only logical_time need not be reconstructed from effective_at

#### Scenario: Concurrent binding claim is atomic

- **GIVEN** two connections submit the same key with equal or conflicting requests
- **WHEN** their transactions race or one transaction rolls back
- **THEN** at most one event/key/binding commits; a loser replays only a matching authenticated binding, conflicts otherwise, and rollback leaves no partial binding

#### Scenario: Original result survives later corrections

- **GIVEN** an event is followed by same-timestamp events, reversal or correction
- **WHEN** its authenticated writer retries the identical original request
- **THEN** the original event id and original commit result are replayed using the original sequence/snapshot, unaffected by later history

## ADDED Requirements

### Requirement: All ingress paths classify idempotency conflicts consistently

Batch ingress SHALL preserve its envelope and transaction policy while returning a per-item rejected conflict without the original result. Signed Twenty ingress SHALL preserve HTTP 200 with a rejected disposition and safe conflict code. SDK clients SHALL classify idempotency conflicts as rejected rather than transient. Valid retries SHALL retain their existing success shape.

#### Scenario: Batch and Twenty conflicts do not cause transient retries

- **GIVEN** matching and conflicting retries through batch and signed Twenty ingress
- **WHEN** the requests are handled and their receipts classified
- **THEN** batch exposes a rejected per-item conflict, Twenty returns 200 with rejected disposition, no prior result leaks, and SDK handling does not classify the conflict as transient

### Requirement: Legacy keys retain integrity during migration

Legacy keys SHALL remain reserved for the ledger lifetime. The system SHALL derive binding only from an original event proving authenticated actor and all required canonical fields. Unverifiable legacy requests SHALL receive idempotency_legacy_unverifiable without a guessed binding or result disclosure. Enforcement rollout SHALL be blocked until valid deployed producer retries have a verified migration or reconciliation path. Binding records SHALL be retained through rollback; request values and fingerprints SHALL NOT appear in logs.

#### Scenario: Provable legacy retry is bound safely

- **GIVEN** a legacy key whose original actor and complete canonical request are provable
- **WHEN** the authenticated writer submits an exact retry after additive migration
- **THEN** the binding is established transactionally and the original result is replayed without releasing or replacing the key

#### Scenario: Unverifiable legacy retry blocks unsafe rollout

- **GIVEN** a legacy event cannot prove all canonical fields required for a deployed producer retry
- **WHEN** migration verification or replay is attempted
- **THEN** the request receives the generic legacy-unverifiable rejection, no binding is guessed, and enforcement remains blocked until a reviewed compatibility path exists

#### Scenario: Fingerprint versions and telemetry preserve integrity

- **GIVEN** canonical request golden vectors and sensitive request fields
- **WHEN** fingerprint versions are tested and request handling emits telemetry
- **THEN** semantic field-set changes require a new version and no payload-derived fingerprint, credentials or request payload values are logged
