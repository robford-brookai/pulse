# Shared context — connector-template gap analysis work orders

Every tier work order in this directory repeats the context it needs, so each agent can work from
its own file alone. This file is the single source those repeats are copied from; if you are an
agent, you were given your tier file and do not need this one.

## Why this work exists

Rob Ford, 2026-08-21: "I want the pricing-engine to be the best practice template for developing a
Pulse api connector from the other systems that I can demo to the rest of the engineers without
being laughed at. There are as many as 11 depending on how you count them. I need engineering's
help with developing them all except for the pricing-engine connector."

So `pricing-engine` is not a one-off integration. It is the **reference implementation** other
Brook engineers will copy, and its audience is people looking for reasons to dismiss PULSE. The
bar is "exemplary and legible", not "works".

## What a Pulse API connector is

A connector crosses the pulse boundary in exactly one of two sanctioned directions:

- **In:** through the command API (`POST /commands`, `POST /commands:batch`) under the
  connector's own credential. The API derives the `actor` from the bearer credential; a request
  body carrying `actor_type`, `actor_id`, `actor_authority`, or `producer` is rejected outright.
- **Out:** the consumer attaches its own Amazon EventBridge rule and its own Amazon SQS queue to
  the `ocean` event bus.

A connector never reads another application's datastore and never writes to the pulse Postgres
database directly.

**The distinction this template must teach.** The seven services in
`packages/ocean/services/` whose directory names end in `-connector` are OCEAN-era publishers that
emit to the EventBridge bus. They are `github-connector`, `hubspot-connector`, `impilo-connector`,
`linear-connector`, `mongodb-connector`, `pocar-connector`, and `zcc-connector`. A **Pulse API
connector** declares through the command API instead, because producer policy forbids a producer
publishing catalog-subject state to the bus (enforced by an offline CI gate implemented at
`packages/pulse-core/src/pulse_core/producer_policy.py`). The template is therefore the pattern
for converting a bus-emitting service into a ledger declarer, or writing a new declarer.

## Worked precedents already in the repository

- `packages/verdict-relay/` — reads a mart, declares verdicts and paired state transitions.
  Closest in shape to what a connector does.
- `packages/consent-ingress/` — the Customer.io consent ingress; spec at
  `openspec/specs/customerio-consent-ingress/spec.md`.
- `packages/pulse-core/` — the client SDK: `submit_command`, idempotency key derivation, durable
  writer cursors, and Pydantic command types generated from the state catalog.

## The tiers

Tier 1 is what engineers judge in the first five minutes. Tier 2 is craft. Tier 3 is what makes
the artifact a reusable template rather than one nice file. One work order per tier:

- `tier-1-first-five-minutes.md`
- `tier-2-craft.md`
- `tier-3-template-mechanics.md`
