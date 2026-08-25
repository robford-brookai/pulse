# Design: twenty-projection

## Context

Inputs this design is built from, all live-verified during `twenty-dev-instance` (2026-08-17/18,
receipts on issue #223):

- The drag → webhook → command → ledger direction works end to end (nine assertions + a hand
  drag). The reverse direction does not exist: nothing writes ledger state onto the board.
- The heal-back boundary is documented debt (`docs/runbooks/twenty-webhook.md`): a rejected
  card lies until this change ships. Rob hit it twice by hand.
- ADR-0004 D17 sized relay lag (p99 < 30 s outbox-to-backbone) explicitly for the heal-back
  promise; the distribution machinery (outbox → EventBridge → per-consumer SQS,
  `pulse_core.consume` with event-id dedupe) shipped in S1.1 and is the consumption surface.
- The core REST write surface is pinned and live-verified: flat relation columns,
  UPPER_SNAKE-encoded SELECT values, `bodyV2` rich text, `target`-prefixed noteTarget columns.
- Twenty does not push externally-made record mutations to open browser sessions (Rob,
  2026-08-18): heal-back and projection writes are invisible until refresh. Accepted for this
  change; recorded, not solved.
- The mapping has no same-state no-op (verified in `pulse_ledger.twenty.mapping`): a
  projection write would echo into a rejected command plus a note. Echo suppression is
  therefore in-scope, breaking, and load-bearing.

## Decisions

1. **The ledger-fed consumer is a Python service in `packages/twenty-projection`, consuming
   SQS — not the in-Twenty logic function.** The logic function (`twenty-projection-apply`
   baseline) projects DomainEvent records created inside Twenty; its live trigger installation
   is a documented gap, and a server-side function cannot consume the ledger's queue. The two
   are different layers and stay that way: the consumer is the ledger→board path; the function
   remains the in-Twenty registration path. *Alternative rejected:* installing the function's
   trigger and teaching it to poll — inverts the feed architecture and puts ledger consumption
   inside a system we deliberately keep headless.

2. **Monotonicity keys on `ledger_seq`, not timestamps.** The scaffold-era per-dimension LWW
   guard compares `occurredAt`; the ledger's own sequence is strictly ordered per subject and
   immune to clock skew and equal-timestamp ties. The model gains one watermark field per
   projected record (`projectionSeq`, NUMBER) minted through the UID map like every field —
   the `catalog_generated_surfaces` serial lane owns the regeneration. *Alternative rejected:*
   reusing `...StatusAsOf` as the guard — it is a business timestamp (effective time), and
   backdated events would wrongly lose to earlier-applied later-effective ones.

3. **Full-state writes, not deltas.** Every apply writes status + as-of + watermark. This is
   what makes read-only status fields real without trusting Twenty's permission model alone:
   any out-of-band edit is drift that converges on the subject's next event. It also makes the
   consumer idempotent by construction — rewriting the same state is harmless.

4. **Heal-back is rejection-triggered and synchronous-best-effort, inside the webhook route.**
   The route already holds the state of record (it read it to validate the transition), so the
   heal is one REST write with the data in hand — no queue hop, no new service, and the D17
   budget is trivially met for the rejection case. It degrades exactly like the rejection note
   (`CommentPostError` posture): a failed heal never blocks the receipt, and convergence is
   guaranteed anyway by decision 3 on the subject's next event. *Alternative rejected:* a
   ledger-side heal event — the rejected drag wrote no event by design, and minting synthetic
   "heal" events would pollute the ledger with UI corrections.

5. **Echo suppression lives in the mapping, keyed on state equality.** The route compares the
   payload's target state (encoded, per the live SELECT convention) against the state of
   record it already fetched: equal ⇒ `NoOp("echo_of_record")`. This terminates the loop in
   one bounce regardless of who wrote (heal, projection, or a user dragging a card to where it
   already belongs — all three are correctly "nothing to do"). *Alternative rejected:* actor
   discrimination via `updatedBy` — Twenty collapses API-sourced writes to a null
   `workspaceMemberId` (live finding — mapping.py's API-sourced-write note: Twenty collapses the updater to a null `workspaceMemberId`), so the projection is indistinguishable
   from any API writer; state equality is the only reliable discriminator.

6. **The projection holds the Twenty credential and the queue URL, nothing else.** No ledger
   database DSN, no writer token — it cannot mint commands, only render state. Env surface
   mirrors the relay convention (`PULSE_TWENTY_<TARGET>_URL/_TOKEN`, `SQS_QUEUE_URL`); tests
   run under disabled sockets with fixture transports on both sides.

## Risks / Trade-offs

- **[Echo suppression masks a real no-op drag]** → a user dragging a card to its current column
  gets silence instead of feedback. Accepted: that drag changes nothing by definition, and the
  board already renders it in place.
- **[Watermark field is retrofit-expensive]** → minted once through the UID map (mint-once by
  spec); the artifact re-applies as an update to live dev, the path 4.1 proved idempotent.
- **[Refresh-lag UX]** → healed cards do not visibly snap back in open sessions. Recorded
  constraint; the rejection note plus eventual visual convergence is the accepted v1 posture.
- **[Two writers of status fields during cutover]** → the seed loader also writes status. The
  seed is a dev bootstrap, not a production writer; the projection's full-state writes win by
  arrival order, and genesis alignment (flagged on DNA-1019) is the standing design question,
  deliberately not resolved here.

## Migration Plan

Additive. The watermark field lands via artifact re-apply (idempotent, live-verified path).
The consumer starts against dev only; rollback is stopping the consumer — the board simply
stops converging, exactly today's behavior. The echo-suppression mapping change is breaking
for no caller: no producer sends state-confirming updates deliberately today.
