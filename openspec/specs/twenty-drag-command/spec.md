# twenty-drag-command Specification

## Purpose
Defines how a verified Twenty CRUD notification becomes (or deliberately does not become) a
command on the ledger's single write path: drag filtering, canonical subject resolution, the
transition declaration, and idempotency under webhook redelivery.
## Requirements
### Requirement: Only mapped kanban drags become commands

A verified webhook payload SHALL yield a command only when it is a record update on a configured
board mapping whose changed fields include that mapping's status field. Every other notification —
other objects, record creation or deletion, updates not touching the status field — SHALL be
acknowledged as a no-op: success to Twenty (so it is not redelivered), no ledger write. A mapped
drag SHALL yield exactly one transition declaration.

#### Scenario: A status-field update on a mapped board yields one command

- **GIVEN** a verified payload updating a mapped record's status field from one column to another
- **WHEN** it is mapped
- **THEN** exactly one transition declaration is produced, carrying the new column as the target
  state

#### Scenario: A non-drag notification is acknowledged as a no-op

#### Scenario: A malformed body is acknowledged, never redelivered forever

- **GIVEN** a signed webhook request whose body cannot be parsed
- **WHEN** the route processes it
- **THEN** the response is a 200 `malformed` disposition (a non-2xx would make Twenty redeliver
  a permanently unprocessable payload indefinitely), one structured log line carries identifiers
  and codes only, and no command is built (execution finding, task 3.1 — implemented and tested)

- **WHEN** a verified payload arrives for an unmapped object, a create/delete, or an update that
  does not touch the status field
- **THEN** the response is success with a no-op disposition and nothing is written to the ledger

### Requirement: Subjects resolve from canonical identifiers, never guessed

The declared subject SHALL be resolved from the record's canonical identifiers per the Twenty data
model (the canonical spine ID and the board's subject grain — Twenty record IDs are internal and
never a subject key). A payload whose record lacks the canonical identifier SHALL NOT produce a
command or a guess: it SHALL be acknowledged with an unmapped disposition and surfaced in a log
line naming the Twenty record ID and board only — no record fields.

#### Scenario: The canonical identifier resolves the subject

- **GIVEN** a mapped drag whose record carries its canonical identifier
- **WHEN** the subject is resolved
- **THEN** the declaration's subject type and key derive from the board mapping and the canonical
  identifier, not the Twenty record ID

#### Scenario: A record without a canonical identifier is refused, not guessed

- **GIVEN** a mapped drag whose record lacks the canonical identifier
- **WHEN** it is processed
- **THEN** no command is produced, the response carries an unmapped disposition, and the log line
  names only the record ID and board

### Requirement: A valid drag commits on the single write path

A mapped, subject-resolved drag SHALL be declared through the same commit path, catalog
validation, and idempotent-commit semantics as every other writer — no second write path. The
response to Twenty SHALL carry the committed event id.

#### Scenario: A signed synthetic drag commits end to end

- **GIVEN** a subject whose current state makes the dragged-to column a legal transition
- **WHEN** a validly signed synthetic drag arrives
- **THEN** an event commits attributed to the webhook principal and the response carries the
  committed event id

#### Scenario: Webhook redelivery is a replay, not a second event

- **GIVEN** a drag that already committed
- **WHEN** Twenty redelivers the same notification
- **THEN** the original commit result is returned marked as a replay and history contains exactly
  one event (D16)
