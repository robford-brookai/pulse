# Runbook: twenty-projection

Operator actions for the ledger-fed Twenty board projection
(`openspec/changes/twenty-projection/`, `packages/twenty-projection`): running the consumer,
what the watermark means, triaging parked orphans, and rollback. The projection is the D8
return path — every committed ledger event for a board subject upserts its Twenty record, so
the board is a view of the ledger, never a parallel store. Contract entry:
[`docs/contracts/publishes.md`](../contracts/publishes.md) §Twenty board projection.

## Running the consumer

```bash
task projection:consume TARGET=dev   # dev|staging|prod
```

Credentialed and long-running, so it is never reached from `task check`. The environment
surface is exactly three variables — deliberately nothing else:

| Variable | Purpose |
| --- | --- |
| `PULSE_TWENTY_<TARGET>_URL` | The Twenty instance's base URL (the `twenty:deploy` convention). |
| `PULSE_TWENTY_<TARGET>_TOKEN` | Bearer token for the Twenty core REST API. |
| `SQS_QUEUE_URL` | The projection's own queue, fed by its EventBridge rule on the `ocean` bus. |

A missing or empty variable fails startup as a `ConsumerStartupError` naming every absent
variable (exit code 2) — never a consumer that runs against nothing. There is **no ledger DSN
and no writer token**: the projection holds the Twenty credential and the queue URL only, so it
can render state but can never mint or mutate ledger events.

The loop is `pulse_core.consume` — event-id dedupe, delete-after-success — onto the apply core.
A non-board subject is a logged skip whose message still deletes; a board-relevant event writes
the record's full state (encoded status, as-of from the event's effective time, watermark) in
one PATCH. Failed writes retry what retrying can fix (5xx, transport failures; capped
exponential backoff, 4 attempts), then surface and leave the message for redelivery. Every log
line and metric carries identifiers, states, sequences, and reason codes only — never a payload
value.

## Watermark semantics

Each projected record carries `projectionSeq`: the ledger sequence of the last applied event
for that subject, `null` meaning never projected. Apply is monotonic on it — an event whose
sequence is at or below the record's watermark is a logged no-op, never a write, never an
error — so redelivery, reordering, and replay cannot regress board state, and watermarks are
per subject by construction.

Two consequences worth trusting rather than "fixing":

- **A run of `projection no-op` lines is healthy**, not stuck — it is redelivery or replay
  being absorbed. The guard keys on the ledger's own sequence, not timestamps, so backdated
  events order correctly.
- **Out-of-band drift self-heals.** A card status edited by hand (or an illegal drag whose
  heal write failed) converges on the subject's next event, because every apply writes the
  full board state, not a delta. Do not hand-correct a drifted card's watermark; at most
  correct the status and let the next event settle it.

The heal-back write ([`twenty-webhook.md`](twenty-webhook.md) §Heal-back boundary) patches the
status field alone and never moves the watermark — a heal has no ledger sequence in hand.

## Orphan triage

An event whose subject resolves to no board record (the denormalized
`canonicalPatientId`/`programCode` columns match nothing) is **parked**: the
`orphans_parked` counter increments, one log line records the subject key and event id only,
and the message deletes — an orphan never crashes the consumer or blocks the queue.

A parked event is dropped from the projection's point of view. That is safe, not lossy: once
the record exists, the subject's next event writes the full current state. Triage:

1. **Occasional orphans** usually mean the board record had not been created yet when the
   event arrived. Confirm the record exists now; the next event converges it. If the subject
   is long-lived and quiet, drive convergence by hand: create/fix the record, then wait for
   (or trigger) the subject's next ledger event.
2. **A sustained orphan rate** means the record-creation path (seed, registration) and the
   event feed disagree about identifiers. Compare the parked subject keys against the board's
   `canonicalPatientId` values — the fix is the record's key columns, never the events.
3. **`AmbiguousSubjectError` in the logs** is different and worse: more than one record
   matches a subject's key columns, a data fault the consumer surfaces rather than picking a
   winner. Deduplicate the records; the message redelivers and applies once the match is
   unique.

## Rollback

Stop the consumer. That is the whole procedure: the projection writes only board state, so
stopping it means the board stops converging — exactly the pre-projection behavior — while
every committed event remains in the ledger and stays queued or redelivers per the queue's
retention. Restarting resumes convergence with no backfill step: watermarks make replay
harmless and full-state writes make the latest event sufficient.

There is no migration to unwind. The watermark field (`projectionSeq`) is additive model
surface and stays inert while the consumer is down.
