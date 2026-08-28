## Purpose

Defines the single write path into the ledger: catalog-versioned transition legality enforced at
write time, client-supplied idempotency with replay semantics, actor attribution enforced by
authentication, and a restricted backfill mode.

## ADDED Requirements

### Requirement: Transition legality is enforced at write time

The command API SHALL be the only writer to the ledger. A declared transition SHALL be validated
against the versioned state catalog's adjacency (including re-entry loops such as BillingEpisode
`qualified ⇄ not_qualified`) before commit, and an illegal transition SHALL be rejected with the
catalog reason — never accepted-and-flagged. Every committed event SHALL carry the catalog version
in force as `rule_version`.

#### Scenario: Legal transition commits

- **GIVEN** an Enrollment in `active`
- **WHEN** a writer declares `on_hold` with a coded `hold_reason`
- **THEN** the event commits and the response carries the committed event id

#### Scenario: Illegal transition is rejected with the reason

- **GIVEN** a BillingEpisode in `reported`
- **WHEN** a writer declares `qualified`
- **THEN** the command is rejected, no event is written, and the response names the violated
  transition and catalog version

#### Scenario: Verdicts re-run until reported

- **GIVEN** a BillingEpisode in `qualified`
- **WHEN** a re-run declares `not_qualified` with a fresh `rule_version`, `as_of`, and lineage
- **THEN** the transition commits, because `qualified ⇄ not_qualified` is legal until `reported`

### Requirement: Commands are idempotent by client-supplied key

Every command SHALL carry an idempotency key of the form
`{writer_id}:{sha256(subject, command_type, payload, logical_time)}`, unique-constrained in the
ledger for the ledger's lifetime. A replay SHALL return the original commit result (with the prior
event id) and SHALL never produce a second event (D16).

#### Scenario: Retry after timeout is a replay

- **GIVEN** a command that committed but whose response was lost
- **WHEN** the writer retries with the same idempotency key
- **THEN** the API returns the original event id marked as a replay, and history contains exactly
  one event

#### Scenario: Distinct facts never share a key

- **WHEN** the same writer declares the same command type for the same subject at a new
  `logical_time`
- **THEN** the key differs and a second event commits

### Requirement: Actor attribution is enforced by authentication

Each internal writer SHALL authenticate with its own credential, and the API SHALL derive the
event's `actor` from the credential — a writer SHALL NOT be able to declare events as any identity
other than its own (D15). System actors SHALL carry evidence references.

A command body SHALL NOT carry `actor_type`, `actor_id`, `actor_authority`, or `producer` at all,
even when the value agrees with the credential. One rule to state and one rule to test, with no
value-comparison edge cases.

#### Scenario: A writer cannot spoof another actor

- **GIVEN** a request authenticated as `verdict-relay`
- **WHEN** its body claims actor `reconciliation`
- **THEN** the command is rejected, and no event is written

The scenario previously permitted either rejection or a silent correction to `verdict-relay`. Task
3.4 chose rejection: overwriting a body-supplied actor makes a misconfigured producer
indistinguishable from a correct one forever, because the ledger records the corrected value and the
writer never learns. Rejection is the only behaviour a writer can notice.

### Requirement: Command types are generated from the catalog

The command vocabulary (including `declare_transition` — the generic state-transition command
carrying `to_state` and a coded reason — plus `declare_verdict`, `open_billing_episode`,
`record_communication_consent`, `resolve_referral`, `mint_person`, `attach_identifier`,
`merge_person`) SHALL be generated from the state catalog as one of its generated surfaces, and a
command not present in the generated set SHALL be rejected. Verdict outcomes SHALL be trinary
(`positive | negative | indeterminate`) with a mandatory reason on `indeterminate`.

#### Scenario: Unknown command type is rejected

- **WHEN** a writer submits a command type absent from the generated vocabulary
- **THEN** the API rejects it without writing, naming the catalog version consulted

#### Scenario: Indeterminate without reason fails validation

- **WHEN** `declare_verdict` carries outcome `indeterminate` and no reason
- **THEN** the command is rejected before any ledger write

### Requirement: Backfill mode is the same path with a restricted vocabulary

Bulk backfill SHALL use the same endpoint family, legality validation, and single-writer guarantee
as forward writes. The event types `backfill_genesis(state, as_of)` and `reconstruction_gap` SHALL
be accepted only from the backfill actor.

#### Scenario: Backfill-only types are rejected from forward writers

- **WHEN** a writer other than the backfill actor submits `backfill_genesis`
- **THEN** the command is rejected

#### Scenario: Genesis re-anchoring records the gap

- **GIVEN** a subject whose reconstructed prefix is illegal under the catalog
- **WHEN** the backfill actor declares `reconstruction_gap` followed by `backfill_genesis` at the
  last confidently known state
- **THEN** both events commit with the reconstructed epoch and the gap's discarded evidence
  summary is queryable
