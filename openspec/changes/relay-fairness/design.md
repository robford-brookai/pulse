## Context

See proposal.md. `_SELECT_PENDING_SQL` orders by subject before LIMIT; `relay_once` checks the head backoff after selection and obtains a session advisory lock after reading the batch. Read the entire relay and its tests before changing it. The ledger commit lock uses a separate namespace.

## Goals / Non-Goals

**Goals:** Bound starvation under a finite eligible subject set and demonstrate ordering, retries, and parallel-relay behavior with real Postgres.

**Non-Goals:** A new broker, global ordering, exactly-once delivery, or an undocumented promise that EventBridge preserves subscriber arrival order.

## Decisions

### 1. Fair subject selection, bounded work

Use keyset pagination over subject heads with a worker-owned rotating scan cursor. Examine a bounded
number of subjects and publish a bounded number of rows per acquired subject per pass. A backing-off
head makes that subject ineligible without admitting later rows from it. Advance the scan cursor even
when a lock cannot be acquired; wrap at the end. For a fixed finite set, each continuously eligible
unlocked subject is visited within one complete scan cycle. Restart may reset the ephemeral cursor;
it never resets outbox delivery state. A global LIMIT over alphabetically sorted rows is rejected
because it cannot establish this bound. Do not claim a fixed wall-clock bound under unbounded input.

### 2. Lock then re-read

Select candidate subject identifiers, acquire the existing advisory lock, and read that subject's
current pending head and due rows under the lock. This prevents an old pre-lock snapshot from being
treated as fresh work after another relay has completed it. Duplicate publication remains possible
after an ambiguous transport result; event_id remains the dedupe key.

### 3. Ordering and dead-letter policy

Preserve sequence order among pending non-dead-lettered rows of an acquired subject. A dead-lettered
row is operator-owned; later rows may proceed as today. Redrive of an older row is consequently a late
delivery, and subscriber watermark/replay behavior must be tested. Describe this exception instead of
promising an ordering property the existing redrive policy cannot maintain. Transport reordering is
handled by consumer contracts, not by an in-process publisher lock.

### 4. Data and API surface

No journal migration or HTTP change. Introduce explicit worker scheduling state and validated positive
budgets for subjects examined and rows published per subject. Keep existing relay entry points callable
with defaults; test repeated relay_once calls using shared scheduler state as relay_worker will.
Keep scheduling metadata out of event payloads. Record decisions on 2026-09-10 as proposed; they gate
implementation and the doc-updater's modification of ledger-distribution, not current production.

## Risks / Trade-offs

[Extra head queries] → benchmark and inspect query plans on a skewed synthetic backlog. [Fairness state accidentally discarded each pass] → worker-loop regression test. [Changed ordering prose] → review D17 and preserve the existing manual redrive exception explicitly.

## Migration Plan

Run tests against real Postgres, then a synthetic LocalStack load with two relays. Publish counts, backlog drain behavior and query timing as a versioned receipt. Deploy only through the existing reviewed runtime process. Revert the relay image if latency regresses; do not delete outbox or idempotency rows.
