# Runbook: month-open

Operator actions for the `month-open job success on the 1st` monitor
(`design/delivery/pulse-runtime-readiness.md` §1.5): **a missed month-open is a billing incident,
page severity** (§3.3 — one of only three page-severity conditions in the whole system, alongside
command API down and DLQ depth ≥ 1 for > 15 min). The job is `packages/schedules`'s month-open
declarer (`schedules.month_open`, driven by `schedules.cli month-open`) — it enumerates active and
on-hold Enrollments from the ledger's own current-state read surface and declares one
`open_billing_episode` per enrollment × current month. Scheduling is the infra config in
`packages/schedules/infra/`: 00:30 on the 1st, with a same-day retry window.

## Why this pages

Every active or on-hold Enrollment must get exactly one BillingEpisode opened at month start
(object model §5.2). A missed run is a missed billing cycle for every enrollment it should have
covered — not a data-quality nit, a revenue-affecting incident, which is why it is one of the
system's two page-severity job monitors.

## Reading the receipt

A completed run always produces a `MonthOpenReceipt`, success or failure, with these counts:

| Field | Meaning |
| --- | --- |
| `opened` | Declarations the ledger committed as new BillingEpisodes. |
| `replayed` | Idempotent replays — the ledger already had this enrollment × month's episode open (D16). |
| `failed` | Declarations the client classified `rejected` or `transient` after retry. |
| `failed_subject_keys` | The `billing_episode` subject keys that failed — subject keys and counts only, never demographics (PHI rule). |
| `invariant_breach` | `zero_enrollment` when enumeration returned no rows; `None` otherwise. |

`receipt.ok` is `False` on any failed declaration or an invariant breach — that is the process
exit contract the scheduler's retry window keys off. Receipts are structured JSON to stdout
(design decision 6); no subject demographics ever appear in a receipt or a log line.

## What a missed run means

"Missed" has two shapes, and they call for different responses:

1. **No run happened at all.** The scheduler never fired the trigger, or the trigger fired against
   a dead entrypoint. Check the infra config's trigger definition and the platform scheduler's own
   run history for 00:30 on the 1st. This is a scheduler/infra question, not a code defect in
   `schedules.month_open`.
2. **A run happened and failed.** The receipt's `invariant_breach` or `failed` count is nonzero.
   Diagnose from the receipt itself:
   - `invariant_breach = zero_enrollment` — enumeration returned no rows. An operating clinic
     always has eligible enrollments (spec: "Zero enrollments enumerated is a hard failure"), so
     this means the read path or its configuration is broken, never "nothing to bill this month."
     Check the ledger connection the job used and whether `active`/`on_hold` still resolve against
     the current catalog — an unknown state name fails differently (below), so a zero-count
     failure with no catalog error points at the connection or the enumerated subject type, not a
     typo.
   - A catalog rejection on enumeration (an unknown state name) — this is a configuration bug in
     what states the job was told to enumerate, not an operating invariant. Zero commands are
     declared (spec: "A state-name typo rejects the run"). Fix the configured state names against
     the current catalog version and re-run.
   - `failed > 0` with `opened`/`replayed` also nonzero — a partial run. `failed_subject_keys`
     names which enrollment × month declarations did not commit; check the command API's own
     §1.5 monitors (error rate, latency) for the window the run executed in.

## Re-run posture

Re-running month-open is always safe, same day or any day mid-month — that is the whole point of
the D16 idempotency key being derived from the enrollment and the **billing month**, not wall-clock
time (design decision 3). Concretely:

- A same-day re-run replays every already-open episode; nothing is declared twice (spec: "Re-run
  replays").
- A re-run later in the month — the corrective action after a missed or partially-failed run —
  replays the episodes already open and additionally opens episodes for any enrollment that became
  active or on-hold since the last run (spec: "Mid-month invocation"). The receipt distinguishes
  the two: expect an elevated `replayed` count on a recovery run, and do not treat that by itself
  as a new incident.
- Do not hand-correct anything in the ledger to work around a missed run. The retry is the
  mechanism; a manual insert is how an enrollment's billing history diverges from what the job
  would have declared.

**Corrective action:** clear whatever blocked the original run (scheduler trigger, ledger
connectivity, catalog state names, command API health), then re-run `schedules.cli month-open`
for the affected month. The same-day retry window in the infra config exists so this is usually
automatic; a page means it needs to be triggered by hand.

## Replay accounting

`DNA-801` (the command API's `idempotency_key` / `replayed` HTTP wiring) landed 2026-08-04
(PR #104), so the live `PulseCoreClient` classifies replays as `replayed` and a re-run's receipt
counts are trustworthy. The general caution still stands on any version predating that fix:
an `opened` count that looks too high on a known re-run is an accounting artifact, not evidence
of duplicate episodes — the ledger's commit path guarantees no duplicate BillingEpisode
regardless of receipt counts; confirm against the ledger's own state before escalating.

## PHI posture

Month-open receipts and logs carry `billing_episode` subject keys and counts only — never
enrollment demographics or anything else about the person behind the enrollment. If any log line
in Datadog shows more than that, treat it as a PHI incident: capture the record's timestamp and
logger name, and escalate per the security review process before sharing the line anywhere.
