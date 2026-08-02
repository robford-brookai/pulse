# Ordering verdict — `control-plane`, per handler

Task 3.6 (DNA-743) of `ocean-eventbridge-migration`. The design audit (D3) recorded
`control-plane` as **order-tolerant, per handler**, with the note "to be re-confirmed per handler
during conversion". This is that re-confirmation, at the tree as of this commit.

**The audit's verdict does not hold in full.** Eleven of thirteen `EVENT_HANDLERS` entries are
order-tolerant. Three are order-dependent, in two different ways, and none of them is fixed by the
change's existing task list. They are proposed as new tasks in the HANDOFF that carries this file.

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
| `ticket.created` | `handle_ticket_created` | Order-tolerant | Same handler, same reasoning — but this key should not exist at all: see Finding 3. |
| `ticket.update.requested` | `handle_ticket_updated` | Order-dependent | **Finding 1 — guard landed (task 3.7).** The status write now carries an event-time guard on `tickets.last_event_at` (migration 0020), which closes the working-state races. What remains is a precondition drop, Finding 2's class: a `resolved` that outruns its `in_progress` is rejected by the legality check and lost. |
| `ticket.updated` | `handle_ticket_updated` | Order-dependent | Same handler. Reached only by control-plane's own echo, which carries no `new_status` and is therefore dropped — but the verdict follows the handler, not the path. |
| `ticket.rma.requested` | `handle_rma_requested` | Order-dependent | **Finding 2.** Returns silently when its ticket row is absent; the message is then acknowledged and the RMA is lost. |
| `return.updated` | `handle_return_status_update` | Order-dependent | **Finding 2.** Same shape: no `returns` row yet means no `ticket.rma.status` is ever emitted for that milestone. |
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
`timestamp` through, matching the other four relays. What 3.7 does **not** fix is the
precondition drop: from `open`, a `resolved` that arrives before its `in_progress` is rejected
by `is_valid_transition` before the guarded write is attempted, and the resolution is lost —
Finding 2's class, needing 3.8's park-or-redeliver treatment, which is why the verdict stays
Order-dependent. The original analysis follows.

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

### Finding 2 — two handlers drop an event whose precondition has not arrived (proposed task 3.8)

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

### Finding 3 — `control-plane` consumes the `ticket.created` it publishes (proposed task 3.9)

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

`services/control-plane/tests/test_ordering_verdicts.py` — 26 tests: 25 green, 1
`xfail(strict=True)` (Finding 3; Findings 1's markers were removed when task 3.7 landed the
guard, and Finding 2's residual case is pinned as a passing characterisation test). The
handlers' only state
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
