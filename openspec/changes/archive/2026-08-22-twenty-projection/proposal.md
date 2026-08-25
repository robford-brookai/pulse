# Proposal: twenty-projection

## Why

The drag-to-ledger direction is proven live (twenty-dev-instance, receipts on issue #223), but
the board is still not a projection — it is a UI whose state the ledger corrects only by
accident. Three facts make that concrete, all live-verified 2026-08-17/18:

- A rejected drag leaves the card in the wrong column indefinitely. The kanban-ingress change
  drew this boundary deliberately (`docs/runbooks/twenty-webhook.md` §Heal-back boundary):
  "the card sits in the wrong column until Phase 3's `twenty-projection`". Rob hit it twice by
  hand on 2026-08-18.
- Ledger events that do not originate from a drag — verdict declarations, schedule
  reconciliations, identity merges — never reach the board at all. The board shows what was
  dragged, not the state of record.
- `lifecycleStatusAsOf`/`qualificationStatusAsOf` on live cards still carry seed stamps: no
  process writes ledger state onto Twenty. The in-Twenty logic function
  (`twenty-projection-apply`) covers DomainEvent records created inside Twenty, and its live
  trigger installation is itself a documented gap — it cannot be the ledger-fed path.

ADR-0004 D17 sized the relay lag budget (p99 < 30 s outbox-to-backbone) explicitly "driven by
the heal-back UX promise". The infrastructure that promise assumed is this change.

## What Changes

- **`packages/twenty-projection`** — a ledger-fed consumer: reads the ledger's SQS queue
  through `pulse_core.consume` (event-id dedupe, delete-after-success), projects each
  board-relevant event onto Twenty through the live-verified core REST surface (flat relation
  columns, UPPER_SNAKE SELECT encoding, `target`-prefixed noteTarget columns).
- **Monotonic apply on `(subject_id, ledger_seq)`** — the model gains a per-record projection
  watermark; an event at or below the watermark is a no-op, so redelivery, reordering, and
  replay are all safe. Watermark fields are minted into the artifact (UID map) like every other
  field.
- **Full-state writes** — an applied event writes the subject's complete board state (status,
  as-of, watermark), so any drift on the card — including a user's illegal drag — converges on
  the next event.
- **Heal-back on rejection** — the webhook route's rejected disposition additionally triggers a
  projection write restoring the state of record to the card, closing D8 end to end inside the
  D17 budget. Degrades like the rejection note: a failed heal never loses the receipt.
- **Echo suppression (BREAKING seam, live-verified absent)** — a projection or heal write fires
  `patientProgram.updated` back at the webhook; today that maps to a command, the catalog
  rejects the self-transition, and a spurious rejection note lands on the card. The drag
  mapping gains a same-state no-op (`echo_of_record`): an update whose target state equals the
  state of record is a `noop` disposition, never a command.
- **Read-only status fields, enforced end to end** — the projection identity becomes the only
  sanctioned writer of status fields; staff restriction is already live in the role artifact,
  and the projection's full-state writes make any out-of-band edit self-healing.

## Capabilities

- `twenty-ledger-projection` (new) — the consumer: feed consumption, monotonic apply,
  full-state write, orphan parking, PHI limits.
- `twenty-heal-back` (new) — rejection-triggered restore within the D17 budget, degrade
  posture, echo suppression guarantee.
- `twenty-drag-command` (modified) — the `echo_of_record` no-op scenario.

## Out of scope

- Installing the in-Twenty logic function's live trigger (twenty-sdk app surface) — the
  ledger-fed consumer makes it unnecessary for board state; the function remains the in-Twenty
  path for DomainEvent-record registration.
- Staging/prod promotion (`environment-matrix`), the projection rebuild drill (its own roadmap
  change, which carries the rebuild demo), and any live-update/websocket UX work — the
  refresh-lag constraint is recorded as a design input, not solved here.
- Customer.io and Snowflake projections — sibling roadmap rows with their own changes.

## Entry conditions

- `pulse-app-scaffold` and `twenty-dev-instance` archived (both done — 2026-08-17/18).
- Live wave requires the dev instance and the served command API (both standing).
