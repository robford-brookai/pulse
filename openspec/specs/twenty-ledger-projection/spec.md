# twenty-ledger-projection Specification

## Purpose
The ledger-fed board projection: every committed ledger event for a board subject upserts the
Twenty record through the live-verified core REST surface, monotonically on
`(subject_id, ledger_seq)`, so the board is a view of the ledger rather than a parallel store.
## Requirements
### Requirement: The projection consumes the ledger feed, never the ledger database

The projection SHALL consume committed events exclusively from its SQS queue via
`pulse_core.consume` — event-id dedupe, delete-after-success — and SHALL write Twenty
exclusively through the core REST API with the pinned conventions (flat relation columns,
UPPER_SNAKE-encoded SELECT values). It SHALL hold no ledger database credential.

#### Scenario: An event applies from the queue alone

- **GIVEN** a committed enrollment event on the projection's queue (fixture transport)
- **WHEN** the consumer processes it
- **THEN** the Twenty record's status, as-of stamp, and watermark are written through the REST
  surface, and the message is deleted only after the write succeeds

#### Scenario: An EventBridge-wrapped delivery applies the same as a bare envelope

- **GIVEN** a queue message whose body is the EventBridge delivery shape — the committed
  envelope riding whole inside a `detail` key — rather than the bare envelope
- **WHEN** the consumer processes it
- **THEN** the envelope is unwrapped from `detail` and applies exactly as a bare-body message
  does (the real relay → bus → rule → queue path wraps every delivery this way; verified live
  2026-08-21, receipt on issue #252)

#### Scenario: A redelivered message applies nothing twice

- **GIVEN** the same queue message delivered twice
- **WHEN** both deliveries process
- **THEN** the second is deduplicated on event id and produces no second write

#### Scenario: The projection holds no ledger credential

- **GIVEN** the projection package and its environment surface
- **WHEN** its imports and required env vars are inspected
- **THEN** no ledger database driver is imported and no ledger DSN or writer token is read —
  the package can render state but can never mint or mutate ledger events

### Requirement: Apply is monotonic on the ledger sequence

Each projected record SHALL carry the ledger sequence of the last applied event as a watermark.
An event whose sequence is at or below the record's watermark SHALL be a logged no-op — never a
write, never an error — so reordering and replay cannot regress board state.

#### Scenario: A late event never regresses the board

- **GIVEN** a record whose watermark is sequence N
- **WHEN** an event with sequence ≤ N arrives
- **THEN** no field is written and the no-op is logged with subject and sequences only

#### Scenario: Watermarks are per subject

- **GIVEN** two subjects with interleaved events
- **WHEN** both apply
- **THEN** each record's watermark reflects only its own subject's latest applied sequence

### Requirement: An applied event writes the full board state

An apply SHALL write the subject's complete board state — status, its as-of stamp, and the
watermark — not a delta, so any out-of-band drift on the card (an illegal drag, a manual edit)
converges to the state of record on the subject's next event.

#### Scenario: Drift converges on the next event

- **GIVEN** a card whose status was moved out of band and disagrees with the ledger
- **WHEN** the subject's next event applies
- **THEN** the card carries the ledger's status and stamps, and the drift is gone

### Requirement: Unresolvable subjects park without failing

An event whose subject resolves to no Twenty record SHALL be parked — logged with identifiers
only and surfaced as a counted metric — and SHALL NOT crash the consumer or block the queue.

#### Scenario: An orphan event parks cleanly

- **GIVEN** an event for a subject with no board record
- **WHEN** the consumer processes it
- **THEN** processing completes, the orphan count increments, and the log line carries the
  subject key and event id only

### Requirement: Nothing that leaves the process carries payload content

Logs, metrics, receipts, and error paths SHALL carry identifiers, states, sequences, and reason
codes only — never event payload values, names, or demographics. Every test runs under disabled
sockets against fixture transports.

#### Scenario: A failed write logs no payload

- **GIVEN** a REST write that fails with a response body containing a synthetic record value
- **WHEN** the failure is logged and retried
- **THEN** no log line or metric carries any part of the body's record value
