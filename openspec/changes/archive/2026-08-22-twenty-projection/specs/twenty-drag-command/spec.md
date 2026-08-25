## MODIFIED Requirements

### Requirement: Only mapped kanban drags become commands

A verified webhook payload SHALL yield a command only when it is a record update on a configured
board mapping whose changed fields include that mapping's status field. Every other notification —
other objects, record creation or deletion, updates not touching the status field — SHALL be
acknowledged as a no-op: success to Twenty (so it is not redelivered), no ledger write. A mapped
drag SHALL yield exactly one transition declaration.

The payload shape a drag is recognized from SHALL be the one Twenty sends:

- The event discriminator SHALL be `eventName`, an object-qualified string of the form
  `{objectNamePlural}.{action}` such as `patientProgram.updated`, rather than a bare
  `record.updated` event type.
- `updatedFields` SHALL be read as a list of field **names**; the field's new value SHALL be read
  from the corresponding key on `record`, because the payload carries no per-field before/after
  pair.
- `record` SHALL be treated as the flat ORM entity — Twenty's `properties.after` — so related
  objects appear as foreign-key scalars rather than nested objects.

The webhook subscription SHALL be registered narrowed to the mapped operations rather than the
default wildcard, so that an unmapped-object no-op is a defensive path rather than the common case.

A status-field update whose target state equals the subject's state of record SHALL be a no-op
disposition with reason `echo_of_record` — never a command, never a rejection, never a note.
This is what terminates the projection loop: a heal-back or projection write fires the same
`.updated` webhook back at the route, and without this rule the catalog's refusal of the
self-transition would post a spurious rejection note on every heal (falsified live 2026-08-18:
no same-state no-op existed, so an echo mapped to a command).

#### Scenario: A status-field update on a mapped board yields one command

- **GIVEN** a verified payload whose `eventName` is the mapped object's `.updated` event, whose
  `updatedFields` names the mapping's status field, and whose `record` carries the new value
- **WHEN** it is mapped
- **THEN** exactly one transition declaration is produced, carrying the new column as the target
  state

#### Scenario: A non-drag notification is acknowledged as a no-op

- **GIVEN** the webhook route is enabled
- **WHEN** a verified payload arrives for an unmapped object, a create/delete, or an update whose
  `updatedFields` does not name the status field
- **THEN** the response is success with a no-op disposition and nothing is written to the ledger

#### Scenario: An echo of the state of record is a noop

- **GIVEN** a verified payload whose `updatedFields` names the status field and whose target
  state equals the subject's state of record
- **WHEN** it is mapped against the state of record
- **THEN** the disposition is `noop` with reason `echo_of_record`, no command is submitted, and
  no note is posted

#### Scenario: A malformed body is acknowledged, never redelivered forever

- **GIVEN** a signed webhook request whose body cannot be parsed
- **WHEN** the route processes it
- **THEN** the response is a 200 `malformed` disposition (a non-2xx would make Twenty redeliver
  a permanently unprocessable payload indefinitely), one structured log line carries identifiers
  and codes only, and no command is built
