## Purpose

Defines what an invalid drag produces: a structured rejection receipt naming the violated
transition and catalog version, a comment posted back on the Twenty card, and the PHI limits on
both. The heal-back write (moving the card back) is explicitly out of scope — Phase 3's
`twenty-projection` completes it.

## ADDED Requirements

### Requirement: An illegal drag produces a rejection receipt

A mapped drag whose target state is an illegal transition per the catalog SHALL be rejected with
no ledger write, and the webhook response SHALL be a rejection receipt carrying the violated
transition (from-state, to-state), the catalog's reason, the catalog version consulted, and the
card reference — sufficient for the Demo 2 assertion ("invalid drag → rejection receipt") and for
an operator to reconstruct the rejection without the payload. The response status SHALL be a
success to Twenty: Twenty cannot act on an error status, and a retry storm of a rejected drag
helps no one — the receipt and the comment are the feedback channel.

#### Scenario: Illegal transition yields a receipt and no event

- **GIVEN** a subject whose current state does not permit the dragged-to column
- **WHEN** a validly signed drag to that column arrives
- **THEN** no event is written and the response is a rejection receipt naming the from-state,
  to-state, catalog reason, and catalog version

### Requirement: A rejection posts a comment on the card

Every rejection receipt SHALL produce a comment on the originating Twenty card via the outbound
comment adapter, telling the user who dragged it why the move did not take: the attempted
transition, the catalog reason, and that the state of record is unchanged. The comment SHALL
carry only states, the coded reason, and catalog version — never record fields, names, or any
payload content.

#### Scenario: The comment names the transition and reason, nothing else

- **GIVEN** a rejected drag
- **WHEN** the comment is posted
- **THEN** the adapter is invoked once with the card reference and a body containing the
  from-state, to-state, and catalog reason, and containing no demographic or payload field

#### Scenario: A comment failure never loses the receipt

- **GIVEN** a rejected drag
- **WHEN** the comment post fails after its retries
- **THEN** the rejection receipt is still returned and the failure is logged with the card
  reference only — a broken comment channel degrades feedback, never rejection correctness

### Requirement: Nothing that leaves the process carries payload content

Receipts, comments, and every log line on the webhook path SHALL be free of webhook payload
content: card drags concern patient records, so the payload is presumed PHI. Logs SHALL name at
most route, disposition, subject key, states, reason, and Twenty record ID. This SHALL hold on
every failure path — rejection, unmapped record, comment failure, handler crash — not only the
happy path.

#### Scenario: A declaration-build failure returns a sanitised 500

- **GIVEN** a mapped drag whose declaration build raises (malformed mapped fields)
- **WHEN** the route handles the failure
- **THEN** the response is a sanitised 500 and the log carries card ref, disposition, and
  exception type name only — never `str(exc)`, whose message quotes the offending field's value
  from a PHI-bearing payload (execution finding, task 3.2: the bearer routes' 422 handler body
  is exactly that string, so this route never lets a declaration error reach it)

#### Scenario: No fixture payload content in logs or receipts across failure paths

- **GIVEN** synthetic drag fixtures carrying recognizable fake demographics
- **WHEN** every disposition is exercised — commit, no-op, unmapped, rejection, comment failure,
  malformed payload
- **THEN** no captured log line, receipt, or comment body contains any fixture demographic string
