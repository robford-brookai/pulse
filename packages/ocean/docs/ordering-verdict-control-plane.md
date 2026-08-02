# Ordering verdict — `control-plane`, per handler

Task 3.6 (DNA-743) of `ocean-eventbridge-migration`. The design audit (D3) recorded
`control-plane` as **order-tolerant, per handler**, with the note "to be re-confirmed per handler
during conversion". This is that re-confirmation, at the tree as of this commit.

**The audit's verdict did not hold when re-confirmed, and holds again now.** Eight of eleven
`EVENT_HANDLERS` entries are natively order-tolerant. Three were order-dependent, in two
different ways, and none of them was fixed by the change's original task list. They were proposed
as new tasks (3.7–3.9) in the HANDOFF that carried this file; 3.7 (sequence guard), 3.8
(precondition raise-for-redelivery) and 3.9 (echo-cycle keys removed) have all since landed, and
the table below reflects the tree after all three.

Every claim below is asserted in
`services/control-plane/tests/test_ordering_verdicts.py`, so the record cannot drift from the code
silently. Claims the code does not yet meet are written there in canonical form and marked
`xfail(strict=True)`, naming the task that makes them pass — when that task lands, the strict
marker turns red until it is removed.

## Verdicts

| Event type | Handler | Verdict | Evidence |
|---|---|---|---|
| `alert.created` | `handle_alert_created` | Order-tolerant | `task_id` is `uuid5(alert_id)`, and the `ON CONFLICT (task_id) DO UPDATE` clause touches only `updated_at` and `last_event_id` — `status`, `priority`, `task_type` and `created_at` are fixed by first arrival. Escalation tracking is `ON CONFLICT … DO NOTHING`. Caveat A. |
| `connector.heartbeat` | `handle_connector_heartbeat` | Order-tolerant | Order-tolerant by erasure: `last_seen` is written as `now()` at processing time and the event's own timestamp is never read, so a stale heartbeat cannot rewind liveness. The single write is the whole effect. Caveat B. |
| `ticket.create.requested` | `handle_ticket_created` | Order-tolerant | Reads no ticket state. Each event writes its own row under a fresh `uuid4`, so no two deliveries contend. Caveat C. |
| `ticket.update.requested` | `handle_ticket_updated` | Order-tolerant | **Findings 1 and 2 — treated (tasks 3.7, 3.8).** The status write carries an event-time guard on `tickets.last_event_at` (migration 0020), closing the working-state races. A legality rejection of an event newer than `last_event_at` — a `resolved` outrunning its `in_progress` — raises `PreconditionNotArrived` for redelivery; an older one is stale and dropped. A missing ticket row also raises. |
| `ticket.rma.requested` | `handle_rma_requested` | Order-tolerant | **Finding 2 — treated (task 3.8).** An absent ticket row raises `PreconditionNotArrived`: the message is redelivered instead of acknowledged with the RMA lost, bounded by 6.3's redrive policy into the per-consumer DLQ. |
| `return.updated` | `handle_return_status_update` | Order-tolerant | **Finding 2 — treated (task 3.8).** Same treatment: a milestone with no `returns` row yet raises for redelivery; a return that never gains a ticket link dead-letters observably rather than vanishing. |
| `fulfillment.updated` | `handle_delivery_notification` | Order-tolerant | Writes nothing. Publishes `delivery.notify` only when `status == "delivered"`, which is a single terminal transition per order. Caveat D. |
| `alert.resolved` | `handle_alert_resolved` | Order-tolerant | Pure relay: no read, no write, one `outcome.recorded` whose id is `uuid5(entity_id, resolution_type)`. |
| `task.completed` | `handle_task_completed` | Order-tolerant | Pure relay, as above. |
| `call.completed` | `handle_call_completed` | Order-tolerant | Pure relay. The competing `completed`/`missed` pair emits the same set of outcomes in either order — the reordering hazard for that pair lives downstream in `graph-projection`, and is task 3.1. |
| `call.missed` | `handle_call_missed` | Order-tolerant | Pure relay, as above. |

The consumer loop itself — `dispatch()` routing by `event_type`, one transaction per message,
commit only after success — introduces no ordering coupling: no handler reads state another
handler in this service wrote within the same delivery.

## Findings

### Finding 1 — `handle_ticket_updated` is order-dependent (task 3.7 — guard landed)

**Status: the sequence guard and the outcome-relay fix shipped with task 3.7.** The status write
is guarded on `tickets.last_event_at`, populated from the envelope `timestamp` (migration 0020);
a stale write updates zero rows and skips escalation removal and every publish, while bridge
links still apply (additive and idempotent). `build_outcome_event` now passes the source event's
`timestamp` through, matching the other four relays. The residue 3.7 could not fix — from
`open`, a `resolved` that arrives before its `in_progress` is rejected by `is_valid_transition`
before the guarded write is attempted — was Finding 2's class, and task 3.8 treated it: the
handler now reads `last_event_at` alongside `status`, drops a rejected event that is stale
(older than `last_event_at`, as the guard would have dropped it), and raises
`PreconditionNotArrived` for a rejected event that is fresh, leaving the message for
redelivery. The verdict is Order-tolerant. The original analysis follows.

`tickets.py:167` reads the current status, `tickets.py:205` writes the new one. The only thing
between them is `is_valid_transition`, which is a legality check, not a sequence guard.

- In-order `in_progress` then `resolved` ends at `resolved`. Reversed, `resolved` is illegal from
  `open` and is dropped, `in_progress` applies, and the ticket ends at `in_progress` — a resolved
  ticket that stays open, silently.
- `waiting → in_progress` and `in_progress → waiting` are both legal, so within the working
  states the state machine offers no protection whatever: the terminal status is simply whichever
  event was processed last.
- One thing it does buy: `resolved` is a sink with no outgoing transitions, so a late earlier
  event cannot resurrect a resolved ticket. The guard is needed for the working states.

Treatment is 3.1's: a monotonic predicate on an event-time field. The `tickets` row has no
event-time column today — `updated_at` is `datetime.now()` at processing time (Caveat A), so
guarding on it would compare arrival order and re-encode the bug the guard exists to remove. A
column must be added and populated from the envelope `timestamp`.

The blast radius reaches Slack: this handler publishes `ticket.updated` and `ticket.resolved`,
which `slack-bot` renders through `chat_update`. Task 3.5 guards the Slack side; without 3.7 the
event stream feeding it is already wrong.

The same task must fix a second defect in the same handler. On resolution it calls
`build_outcome_event(..., timestamp=now.isoformat())` (`tickets.py:280`) — processing time. The
other four outcome relays pass the source event's own `timestamp` through untouched, which is what
gives task 3.1 an event-time field to guard `graph-projection`'s `outcomes` upsert on. The ticket
path alone poisons that field, so 3.1's guard would compare arrival order for exactly the events
that reach it from here.

### Finding 2 — two handlers drop an event whose precondition has not arrived (task 3.8 — resolved)

**Status: task 3.8 landed the raise-for-redelivery treatment.** All three precondition-drop
paths — `handle_rma_requested` with no ticket row, `handle_return_status_update` with no
`returns` row, and `handle_ticket_updated`'s legality rejection of a fresh event (including the
missing-ticket case) — now raise `PreconditionNotArrived`. The consumer leaves the message for
visibility-timeout redelivery, and the retry is bounded and observable, not silent or infinite:
after `maxReceiveCount` receives, the queue's redrive policy (task 6.3) moves the message to the
per-consumer DLQ, whose depth alarm fires on the first message. A stale legality rejection
(event time at or before `tickets.last_event_at`) is still dropped — raising there would spin
every superseded event into the DLQ. The original analysis follows.

`handle_rma_requested` reads the ticket row it was asked to act on; `handle_return_status_update`
reads the `returns` row linking a return to its ticket. Neither row is written by the event being
processed, and both handlers `return` when the row is missing — after which the consumer commits
and the message is gone. Under unordered delivery this is not a duplicate or a stale write; it is
a lost effect. No RMA is created, and no `ticket.rma.failed` is emitted either, so nothing
downstream observes the loss.

A sequence guard does not address this, so this is *not* the 3.1 treatment. The fix is to leave the
message for redelivery when its precondition is absent — raise, or park it explicitly — which
interacts with the DLQ and redrive work in 6.3 and must not be a silent infinite retry.

Under Kafka this was masked by partition ordering only when the two events shared a partition key
on the same topic. It was already a live hazard for `return.updated`, which arrives on
`ocean.logistics` from a connector while the `returns` row is written by control-plane itself.

### Finding 3 — `control-plane` consumes the `ticket.created` it publishes (task 3.9 — resolved)

**Status: task 3.9 removed both self-consumed keys.** `ticket.created` and `ticket.updated` are
no longer in `EVENT_HANDLERS`; control-plane still receives them on its queue (it subscribes to
the `tickets` domain for the `*.requested` forms) and `dispatch()` skips them as unknown types.
`test_no_handler_re_emits_an_event_type_this_consumer_handles` now runs green with its strict
xfail marker removed, and `test_ticket_dispatch.py` pins both keys absent. The original analysis
follows.

Not an ordering property; found in the same wiring. `handle_ticket_created` publishes
`ticket.created` to `ocean.tickets`, control-plane subscribes to `ocean.tickets`, and
`EVENT_HANDLERS["ticket.created"]` routes straight back into `handle_ticket_created`. Each pass
mints a fresh `uuid4` ticket id and a fresh `human_id` from the category sequence, so the cycle
does not converge — one requested ticket becomes an unbounded stream of tickets.

Control-plane is the only publisher of `ticket.created`; the request event other services send is
`ticket.create.requested` (`linear-connector/src/normalizer.py:67`, `slack-bot/src/bolt_app.py:789`).
So the `ticket.created` key in `EVENT_HANDLERS` has no legitimate producer and looks like the
mistake it is. `ticket.updated` echoes the same way but terminates: the echo's payload carries
`status`, not `new_status`, so the transition check rejects it on the next pass.

This must be resolved before task 6.2 writes the EventBridge rule for control-plane, or the rule
pattern will encode the cycle into the new transport.

## Caveats recorded but not raised as tasks

- **A — processing-time bookkeeping in the `tasks` and `tickets` upserts.** Both write
  `updated_at = datetime.now()` and guard with `WHERE … updated_at < EXCLUDED.updated_at`. That
  predicate compares processing time to processing time, so it is always true and guards nothing;
  `last_event_id` consequently records the last event *processed*, not the last event *emitted*.
  Harmless today because only bookkeeping columns are inside the clause, and it is exactly the
  wrong-fix trap D3 warns about for `outcomes.py`. Anyone adding a substantive column to either
  `DO UPDATE SET` inherits a silent corruption.
- **B — `connector_name` follows processing order.** If a connector's reported name changes, the
  stored name is the last one processed. Cosmetic.
- **C — ticket creation is not idempotent.** A redelivered `ticket.create.requested` creates a
  second ticket with a second `human_id`. This is an at-least-once hazard, not an ordering one; it
  predates the migration and gets no worse under EventBridge, but SQS redelivery on visibility
  timeout will make it easier to hit than a Kafka rebalance did.
- **D — `delivery.notify` is re-emitted on redelivery.** Same class as C: a duplicate Slack post,
  not a wrong one.

## How this was verified

`services/control-plane/tests/test_ordering_verdicts.py` — 28 tests, all green (Finding 1's
strict-xfail markers were removed when task 3.7 landed the guard, Finding 3's when task 3.9
removed the echo keys; Finding 2's characterisation tests were rewritten to assert the
raise-for-redelivery treatment when task 3.8 landed it).
The handlers' only state
input is what they read back from `session`, so the tests drive the real handler functions against
a recording session double that models the four rows they actually read, and compare final state
and emitted events between in-order and reversed delivery.

```
cd packages/ocean/services/control-plane
uv run --project ../../../.. --all-packages pytest tests/test_ordering_verdicts.py
```

Keep `--all-packages`. Without it, uv re-resolves the shared workspace venv down to the root
project's own dependency set, which drops `fastmcp` and leaves `task typecheck` red on an
otherwise clean tree until the next `uv sync --all-packages`.

Since task 4.14, `task test` runs every ocean service suite (one pytest process per service), so
these tests are in CI. The ten pre-existing `AsyncMock`-rot failures this note originally
recorded have since been fixed; the control-plane suite is green as of task 3.7.
