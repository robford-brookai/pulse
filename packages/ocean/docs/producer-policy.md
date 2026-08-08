# Producer policy (§4.4)

The one behavioral rule every `packages/ocean` producer schema follows, from
`design/migration/ocean-to-pulse-adaptation-plan.md` §4.4, enforced mechanically by the
producer-ingress-policy CI gate (`tests/test_producer_ingress_policy.py`) on every run of
`task check`.

## The rule

- **If your event asserts a PULSE-subject state transition:** stop emitting it. Issue a command
  to the PULSE API instead (`pulse_core.submit_command`). The ledger validates, commits, and
  emits the event onto the backbone for you — your emit becomes a request.
- **If your event is a non-subject fact** (a reading landed, a call completed, a document
  arrived): keep emitting directly. Nothing changes.

## The classification test

Does the event's payload name a state that lives in the catalog? Then it routes through the
ledger. The catalog is the boundary, mechanically checkable in CI against producer event schemas
— this is exactly what the gate (`pulse_core.producer_policy.classify_source`) does: it extracts
the declared vocabulary of a producer schema (state literals/enums, entity-type declarations,
`event_type` addressing) and flags an element only when it addresses a catalog subject. A bare
word the catalog also uses (`open`, `resolved`, `active`) never flags on its own — only an
element that actually addresses a subject (`referral`, `consent`, `communication_consent`,
`enrollment`, `billing_episode`, `device`, `contract`) does.

## Sanctioned command sources

Per the adaptation plan's existing register (§4.4), these are the systems of record permitted to
issue commands instead of direct emits:

- the Twenty kanban webhook (D8, heal-back on invalid drags)
- Customer.io consent ingress (D9)
- the identity-resolution service (adaptation-plan assessment §5.3)
- the warehouse verdict runner (I3)
- human actors, through attributed tooling

Any other producer that finds itself issuing commands is out of scope for this policy — raise it
before adding a new sanctioned source, don't infer one from a gate failure.

## When the gate is red

1. Read the finding: `<file>:<element> asserts <subject> state(s) <states>` (or `declares
   catalog subject <subject>` when no states are named).
2. Decide which side of the rule the schema is on:
   - **It genuinely asserts subject state** — convert the emit to a command through the ledger
     write path (`pulse_core.submit_command`). This is an ingress-adapter change, not a
     suppression; the non-subject facts the same schema carries keep emitting directly.
   - **It's a name collision** — the vocabulary describes something that isn't a catalog subject
     (an alert status, a ticket status, an unrelated entity) and only coincidentally reuses a
     catalog word. This is the only case eligible for suppression (below).
3. If you're unsure which case you're in, treat it as a genuine assertion. No grandfathering: a
   producer that is actually asserting state does not get to stay green by suppression.

## Suppressions

`packages/ocean/producer-policy-suppressions.yaml` (ships empty) holds adjudicated
name-collision false positives — never exemptions for a genuinely state-asserting producer.

- Each entry names the finding it suppresses (`file`, `element`, `subject`) and carries a
  mandatory `justification`.
- An entry with no justification fails the gate.
- An entry that matches no current finding (stale — the code moved, or the collision was fixed)
  fails the gate, naming the dead entry.
- A suppression affects exactly the finding it names. It never widens to cover a different
  element, subject, or file.

Ingress changes that follow this one (`twenty-kanban-webhook-ingress`,
`customerio-consent-ingress`, and later ones) are born under this gate — no seeded suppressions,
no exemption for being "not converted yet."
