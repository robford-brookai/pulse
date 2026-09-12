# Runbook: idempotency enforcement rollout (ADR-0007)

Attended operator actions for the D16 amendment — binding every idempotency key to the
authenticated writer and to a canonical request v1 fingerprint
(`docs/adr/ADR-0007-idempotency-writer-binding.md`). This page covers one bounded rehearsal against
a **synthetic dev** dataset and the gate that stands between that rehearsal and any enforcement
flip. It is `idempotency-integrity` task 4.1's checklist.

**This runbook does not enable enforcement.** The rehearsal proves that valid existing retries
still replay and that a changed request conflicts, on a database carrying a synthetic copy of
pre-binding rows. Enabling enforcement anywhere is a separate, later decision that requires the
rollout gate in `docs/idempotency-compatibility-inventory.md` to be clear — including two approvals
this rehearsal cannot give itself (ADR-0007 Accepted, and the D16 status flip).

Nothing here runs against production, and nothing here runs in a worktree job: every step is an
attended session with a human present, and its receipts go on the tracking GitHub issue.

## What "enforcement" means here

`commit_idempotent` binds and checks only when it is passed a `writer`. The deployed service
passes none (`pulse_ledger.api_server`), so today every key behaves exactly as D16 shipped: bound
to nothing, replayed on the key's text alone. "Enforcement" is the change that starts passing the
resolved principal. The stages, from design §5 and ADR-0007:

1. **Expand** — the binding table, its foreign keys and grants ship (migration `0006`). Additive;
   nothing reads the table yet. *Done when the change merges.*
2. **Producer-compatible server and SDK** — the three ingresses carry a conflict and the SDK
   classifies it `rejected` (task 3.1), deployed everywhere before any key can produce one.
3. **Verified legacy bindings** — the inventory run below, and a reconciliation path recorded for
   anything it cannot prove.
4. **Enforce** — the service passes its principal. Gated on all of the above.

The rehearsal below belongs to stage 3. Running it early is safe; skipping it is what is not.

## Preflight: is the gate clear?

Run this first, every time, and paste its output on the tracking issue:

```bash
uv run pytest packages/pulse-core/tests/test_idempotency_conflict_contract.py::TestRolloutPreflight \
  --import-mode=importlib -q
```

It reads `docs/idempotency-compatibility-inventory.md` and answers three questions mechanically:
every producer that can declare has a row, the table speaks the vocabulary the page defines, and
whether any row is at `unknown` or `fix-required`.

PASS for the rehearsal: the suite is green. Green currently includes
`test_an_unknown_row_blocks_enforcement` — **the gate is closed, and that is the expected state**
until the attended run decides the dispositions. The rehearsal is what produces the evidence to
decide them; it is not blocked by the gate being closed. An enforcement flip is.

## The rehearsal

### 1. Build the dataset

A copy of the dev ledger's **pre-binding** rows, or a synthetic set built to the same shape:
keys claimed before migration `0006`, with their events. Never production data, and never a fresh
schema — a fresh schema has no legacy keys, which is the one thing this rehearsal is for.

PASS: `select count(*) from ledger.idempotency_keys` is non-zero and
`select count(*) from ledger.idempotency_bindings` is zero before step 2.

### 2. Take the inventory

```python
from pulse_ledger.legacy_binding import inventory_legacy_keys

inventory = inventory_legacy_keys(conn)
print(inventory.total_keys)
for row in inventory.rows:
    print(row.producer, row.keys, row.disposition.value, row.reasons)
print(inventory.enforcement_blocked, inventory.blocking_reasons())
```

The output is producer ids, counts and reason *names* — no request values and no fingerprints, by
construction — so it is safe to paste on the issue verbatim.

PASS: every producer in the dataset appears; each row's disposition and reasons are recorded.
Transcribe them into the inventory page's "request reconstructible" column and disposition, one PR,
with this run's issue comment as the evidence cell.

### 3. Old producer, exact retry

With the service configured to pass its principal **in this dev environment only**, replay a
command a pre-binding producer already committed — same writer, same request, same key.

PASS: HTTP 200 with `"replayed": true` and the **original** event id.
PASS: `select count(*) from ledger.events where ...` for that subject is unchanged.
PASS: the key now has exactly one binding row.

### 4. Changed request, same key

Resubmit that key with one canonical field changed — the cheapest is `evidence`, which sits outside
the D16 key, so the SDK re-derives the same key (see "The fields outside the key" in the inventory).

PASS: HTTP 409, body `{"detail": {"message": ..., "reason": "idempotency_conflict"}}` and nothing
else — no event id, no result, no fingerprint, no writer of record.
PASS: the event count for that subject is **unchanged**. A conflict writes zero rows.
PASS: the binding row still points at the original event.

### 5. Unverifiable legacy key

Pick a key the step-2 inventory classified `fix-required`, and retry it as its own writer.

PASS: HTTP 409 with reason `idempotency_legacy_unverifiable` — distinct from step 4's code.
PASS: the key is still present and still claimed; no binding row was written for it.

### 6. Webhook retry

Redeliver one signed Twenty drag twice, byte-identical.

PASS: both deliveries are HTTP 200, the second reports the same event id, and the card's history
holds one event.
PASS: a delivery whose mapped `to_state` differs under the same key answers 200 with
`{"disposition": "rejected", "reason": "idempotency_conflict"}` — never a 4xx, which Twenty reads
as "deliver again".

### 7. Retained counts

PASS: `select count(*) from ledger.events` equals the count taken before step 3. The whole
rehearsal is retries and conflicts; it commits nothing new.

### 8. Stand back down

Return the dev service to passing no principal, so dev matches the deployed configuration until the
enforcement decision is actually made.

PASS: a repeat of step 4 replays instead of conflicting.

## Receipts

On the tracking GitHub issue, one comment per numbered step: the command, the PASS lines, and the
step-2 inventory output. Counts, reason codes, producer ids, key digests and event ids only — never
a payload value, an evidence body or a fingerprint. A fingerprint is derived from `payload` and
`evidence`, so a digest of a small value space is a lookup table, not an anonymiser
(ADR-0007 decision 7).

## Before enforcement, separately from this rehearsal

Every one of these, recorded on the inventory page:

1. No inventory row at `unknown` or `fix-required`.
2. A reviewed reconciliation path for every producer whose keys are not fully reconstructible.
3. ADR-0007 **Accepted**, by its deciders — a `Proposed` ADR is a proposal, not an approval.
4. ADR-0004's D16 subsection flipped to Superseded-in-part, pointing at ADR-0007.
5. Stage 2 deployed everywhere: no producer can receive a 409 from a build whose SDK still treats
   it as transient.

## Rollback

Stop passing the principal. Binding rows are retained — never dropped, never re-pointed — so the
rollback is a configuration change and the bindings stay valid for a later re-enable.

A rollback re-opens the pre-amendment collision behaviour: a key reused by another authenticated
writer, or with a changed request, is once again answered with the original writer's result. That
is a disclosure channel, which is why a rollback is **bounded and recorded on the rollout issue
with a date it ends**, and never described as safe by default.
