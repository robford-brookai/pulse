# PULSE — the event backbone for the brook.ai analytics platform

Discussion guide for the engineering session, 2026-08-10 · Linear DNA-900 · Prepared 2026-08-09
Audience: Engineering (Andrew, Carin, Eric, Constantine, David, Max) · Author: Rob Ford, Data

## TL;DR

Every one of us has debugged the same incident: two dashboards disagree about how many patients are enrolled, and the argument takes a week because there is no record to appeal to — just competing SQL. PULSE (Patient Unified Ledger of State and Events) exists to make that incident impossible. It is an event backbone, not a new user interface: your systems keep their UIs and their databases, and when something true happens they declare it — one API call — onto an append-only, validated ledger. Analytics, dashboards, and operational screens all become projections of that one record. It runs entirely on the platform we already operate (Snowflake plus AWS under Duplo), adds zero vendors and roughly $200–350 a month, and it is not a proposal on a slide: the ledger and four live event sources shipped as v2.0 on 2026-08-08, on synthetic data, with demos you can watch fail-loudly today. The ask from this meeting is small and specific: endorse the backbone direction, try to break the design, and help pick the first system to declare events natively.

## 1.0 The problem you already know

You have seen this bug. It is not in any one team's code, which is why no one team has fixed it.

- Patient lifecycle state — registered, enrolled, activated, withdrawn — is written by many systems and owned by none. Every consumer re-derives "current state" from side effects, at read time, with its own SQL.
- Two reports, two definitions, two answers. The discrepancy surfaces weeks later in analytics, and there is no audit trail to say which one is right. The argument is unwinnable because the evidence does not exist.
- Status fields get overwritten in place. We can know a patient is enrolled — but not since when, changed by whom, or on what evidence. History is simply gone.
- Every new integration multiplies the mess: one more point-to-point sync with one more private idea of state.

More engineering effort inside any single system cannot fix this, because the defect is between the systems: state is inferred everywhere instead of declared once. That is the whole disease, and it suggests its own cure.

## 2.0 The idea — declare it once, project it everywhere

PULSE is one rule applied ruthlessly:

1. **Systems declare facts as events.** One API call: what happened (`patient.enrolled`), to whom, when, by which actor. Your UI, your database, your workflow — untouched.
2. **The ledger keeps everything and lies about nothing.** Events are append-only, never overwritten. The write path validates every transition against a versioned state catalog — one YAML file, changed only by pull request — and rejects illegal ones with the reason and catalog version. Retries are safe by construction: the same idempotency key returns the original event instead of a duplicate.
3. **Everything else is a projection.** Current state is computed once from the events and pushed out — to Snowflake for analytics, to webhooks for systems that react, to an operations screen for humans. If a projection is ever wrong, you rebuild it from the ledger. The record is permanent; the views are disposable.

That last property is the one worth pausing on. Today, when numbers disagree, we hold a debate. With a ledger, we hold a replay. "Reproducible state" turns every future data dispute from politics into a query.

## 3.0 It runs on what we already run

No new cloud account. No new vendor contract. No PHI leaving the perimeter we already defend.

| Layer | What runs there | New or existing? |
|---|---|---|
| Producers | POCAR, Billy, PAP, Customer.io, the ops board, PX surveys — declaring events or observed by adapters | Existing, unchanged |
| Write path | Command API: validation, idempotency, actor attribution | New, small, in the repo |
| Ledger | Snowflake Postgres — inside the existing Snowflake BAA | Existing perimeter |
| Transport | Outbox relay onto AWS EventBridge/SQS (the OCEAN stack, absorbed) | Existing, AWS under Duplo |
| Analytics | Events and state land in Snowflake automatically; the warehouse independently re-verifies every transition | Existing — Snowflake |
| Ops surface | Twenty (self-hosted open-source CRM) as one read-and-correct projection, on Snowpark Container Services | New container, existing perimeter |

Two sentences to say out loud, because they preempt the two likeliest misreadings:

- **This is not a new UI, and nothing is being replaced.** Twenty is one projection — a screen where operations can see any patient's state and full history. It is about a hundred lines of custom TypeScript against a stock, unforked server. Delete it tomorrow and the ledger, the API, and the Snowflake layer do not notice.
- **The ledger is the record; no CRM is the source of truth.** All writes go through the command API. The projection's status fields are read-only. This is the exact opposite of "adopt a CRM and pray."

## 4.0 This is built, not pitched

The concept has already survived contact with implementation. Everything below runs on synthetic data only (Synthea-generated patients) — a standing compliance gate keeps real patient data out until production controls are signed off.

```
v1.5 — Record   shipped 2026-08-04. Ledger schema, command API, catalog-
                generated validation, idempotency, outbox relay. 16/16 tasks.
v2.0 — Ingress  shipped 2026-08-08. Seven changes, ~80 PRs (#106-#187).
Live sources    4: ops-board webhook (HMAC-signed drag -> attributed command,
                invalid drag -> rejection receipt on the card), Customer.io
                consent ingress, identity matcher (with a quarantine queue --
                ambiguous humans are never auto-merged), verdict relay
                (Snowflake billing verdicts declared back onto the ledger).
Governance      state catalog v1.0.0 is authoritative; a CI gate fails any
                producer schema that names a catalog state. Inference cannot
                quietly creep back in -- the build goes red.
Envelope        low thousands of events/day confirmed; SPCS compute pool
                $175-350/month (2026-07-28 estimate); Twenty is AGPL-3.0,
                self-hosted, unmodified core, $0 license.
```

## 5.0 Watch it work (or fail loudly) — demo menu

Every demo is local, synthetic, and exits nonzero on any failed assertion — they are proofs, not tours.

| Demo | Runtime | The moment that matters |
|---|---|---|
| 1 — Ledger core | ~10 min incl. Docker bring-up | An illegal transition is rejected with the catalog's reason and version. Then: independently folding the raw events reproduces the stored current state, byte for byte, after a history with backdates and reversals |
| 2a — Kanban drag | ~5 min | A signed drag on the ops board becomes an attributed ledger command; an invalid drag bounces with a receipt and a card comment explaining why |
| 2b — Identity matcher | ~5 min | Deterministic person matching, with genuine conflicts routed to quarantine instead of auto-merged |

Recommendation for the meeting: run Demo 1 live. The rejection and the fold-equals-state assertion are the two moments this stops being slideware.

## 6.0 The deal — what it asks, what you get

**The ask is one API call, and even that is negotiable.** A system integrates in one of two ways:

- **Native declaration** — call the command API when a business fact occurs. One endpoint family, per-service credentials, idempotent, attributed.
- **Adapter ingress** — where touching the producer is not worth it yet, an adapter observes what the system already emits (webhooks, exports) and declares on its behalf with full provenance. Customer.io consent runs this way in v2.0 today. Adapters retire one event type at a time as native emission arrives — never a big-bang migration.

**What you get back:**

- One documented API and webhooks, instead of N point-to-point syncs each holding a private copy of state.
- Complete, timestamped, attributed history in Snowflake. Cross-system questions — funnel conversion, time-in-state, cohorts — get one answer instead of a negotiation.
- An immutable audit trail where every write names its actor. Compliance stops being a reconstruction exercise.
- Fewer 2 a.m. arguments. When numbers disagree, the ledger settles it.

## 7.0 The objections you should raise (and the honest answers)

- **"Is this a rewrite of our apps?"** No. Producers keep their stack entirely. The integration is an API call, or nothing at all if an adapter watches instead.
- **"Another service to babysit?"** Containers on Snowpark Container Services inside the Snowflake footprint we already pay for and defend, transport on the AWS stack already under Duplo. Monitors, SLOs, and paging are scheduled before any production traffic — not after the first incident.
- **"What about the years of history?"** A separate, already-designed backfill program reconstructs it from the existing systems with per-event evidence grading — and it explicitly never blocks the forward path. Forward correctness does not wait on archaeology.
- **"What if volume outgrows it?"** Confirmed volume is low thousands of events/day. If that ever changes by orders of magnitude, only the ingestion leg gets replaced — the event format, catalog, and Snowflake layer carry over unchanged.
- **"Why is there a CRM in this picture at all?"** Because a three-person data team should not hand-build and operate a bespoke CRUD UI for ops. Twenty is bounded, unforked, and disposable by design. It is furniture, not foundation.

## 8.0 What I want from this room

1. **Pressure-test the shape.** Single validated write path, append-only ledger, projections everywhere else. Where does it break? What load, failure mode, or workflow does it not survive?
2. **Name the first native declarer.** The best candidate has clean lifecycle semantics and an owner in this room. I have opinions; I would rather hear yours.
3. **Max — PX surveys.** Survey responses as attributed events on this same write path is designed and slotted. What is the realistic PX timeline, and does the schema-validation plan still fit?
4. **Duplo fit.** Anything about the SPCS-plus-EventBridge split that fights how we run services today? Better to hear it now than at deploy time.
5. **Define the easy yes.** What proof would make this a comfortable endorsement for your team — a load test, a schema review, a deeper demo? Name it and it goes on my list.

## 9.0 Next steps

- Code and receipts: https://github.com/robford-brookai/pulse — the v1.5 and v2.0 releases carry the demo outputs; architecture docs live under `design/platform/`.
- Offered follow-up: a one-hour hands-on session — Demo 1 end to end, plus a schema review of the command API — for anyone who wants to kick the tires personally.
- The decision requested today: endorse the event-backbone direction for the brook.ai analytics platform, and name the first native-declaration candidate.
