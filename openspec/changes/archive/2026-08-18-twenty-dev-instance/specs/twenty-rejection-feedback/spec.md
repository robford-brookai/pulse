## MODIFIED Requirements

### Requirement: A rejection posts a comment on the card

Every rejection receipt SHALL produce a comment on the originating Twenty card via the outbound
comment adapter, telling the user who dragged it why the move did not take: the attempted
transition, the catalog reason, and that the state of record is unchanged. The comment SHALL
carry only states, the coded reason, and catalog version — never record fields, names, or any
payload content.

Live v2.30 carries no `comment` object (falsified 2026-08-17, receipts on issue #223): the
record-attached commentary surface is a **note** bound to the card by a **noteTarget**. The
adapter SHALL post one rejection as two creates — `POST /rest/notes` with the coded reason as
the title and the receipt text as `bodyV2` rich text (`{"markdown": …}`; the live object has no
plain `body` field), then `POST /rest/noteTargets` binding the note by `noteId` plus the
`target`-prefixed custom-object relation column (`targetPatientProgramId`; the bare
`<objectName>Id` convention holds only for stock targets). The adapter seam SHALL carry the
title separately from the body (`card_ref, title, body`) so the coded reason never requires
body parsing.

#### Scenario: The comment names the transition and reason, nothing else

- **GIVEN** a rejected drag
- **WHEN** the comment is posted
- **THEN** the adapter is invoked once with the card reference, a title carrying the coded
  reason, and a body containing the from-state, to-state, and catalog reason, and containing
  no demographic or payload field

#### Scenario: A comment failure never loses the receipt

- **GIVEN** a rejected drag
- **WHEN** the comment post fails after its retries — on either create, including a
  target-after-note failure
- **THEN** the rejection receipt is still returned and the failure is logged with the card
  reference only — a broken comment channel degrades feedback, never rejection correctness

#### Scenario: One rejection is one note bound to the card

- **GIVEN** a rejected drag on a card
- **WHEN** the adapter succeeds
- **THEN** exactly one new note exists and exactly one new noteTarget binds it to that card's
  record, verified live by demo3's assertion 9 (2026-08-18)
