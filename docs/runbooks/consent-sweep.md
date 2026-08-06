# Runbook: consent-sweep

Operator actions for the `reconciliation sweep drift count trend` monitor
(`design/delivery/pulse-runtime-readiness.md` §1.5) — Slack severity (§3.3): this is not one of the
system's page-severity conditions, so it routes to the on-call rotation's Slack channel, not a
page. The sweep is `packages/schedules`'s D9 reconciliation declarer (`schedules.consent_sweep`,
driven by `schedules.cli consent-sweep`) — it parses a delivered Customer.io suppression export,
diffs it against ledger CommunicationConsent current state, and declares a
`record_communication_consent` correction for every disagreement, in both directions. Customer.io
is authoritative for every conflict (D9) — the ledger is never treated as authoritative over the
export. Scheduling is the infra config in `packages/schedules/infra/`: daily.

## Reading the receipt

Every run produces a `DriftReceipt`:

| Field | Meaning |
| --- | --- |
| `agreements` | Rows that parsed and matched ledger state — no correction, no write. |
| `opt_out_corrections` | Export suppresses a subject the ledger shows consented — an opt-out correction was declared. |
| `opt_in_corrections` | Ledger shows a subject opted out that the export does not suppress — an opt-in correction was declared. |
| `unparseable` | Rows that failed to parse — counted, never dropped. |
| `parse_errors` | One `ExportParseError` per unparseable row, naming the row number and which of the three tracked columns (`subject_key`, `channel`, `suppressed`) failed — never a raw contact value. |

`total_corrections` (`opt_out_corrections + opt_in_corrections`) is the count the drift-trend
monitor watches. Receipts are structured JSON to stdout (design decision 6); no raw contact values
or subject demographics ever appear in a receipt or a log line — subject keys and counts only.

## Drift-spike procedure

A spike in `total_corrections` (or in either direction alone) against the trend means the ledger
and Customer.io disagreed on more subjects than usual. Diagnose in this order:

1. **Which direction spiked?** `opt_out_corrections` spiking means the export is suppressing
   subjects the ledger had not yet caught up on — check whether an upstream webhook or ingestion
   gap (the D9 export mechanism, not this sweep) delayed opt-out events from reaching the ledger
   between runs. `opt_in_corrections` spiking means the ledger held opt-outs the newest export no
   longer confirms — check whether the delivered export itself is stale or truncated (fewer rows
   than the prior run, or a date gap) before assuming every one of those corrections is correct.
2. **Is the export itself suspect?** Compare this run's row count and `unparseable` count against
   the prior run. A format drift in the delivered export (Customer.io changed a column, a
   delivery truncated mid-file) inflates both `unparseable` and, once truncation trims real rows
   out, the correction counts on both sides. This is the fixture-pinned-format risk called out in
   design.md's risk list — the parser rejects rows and the drift receipt spikes; the
   `customerio-consent-ingress` follow-on change re-pins the format once the export mechanism is
   confirmed. Until then, a suspected format change is a manual check of the delivered file against
   the fixture-pinned CSV shape, not a code fix in this sweep.
3. **Is this a one-time reconciliation, not ongoing drift?** A single elevated run after a known
   gap (a missed sweep day, a delayed export delivery) is expected — the sweep catches up in one
   run and the trend should return to baseline the next day. Persistent elevation across multiple
   runs is the signal to escalate: it means something upstream is continuously producing
   disagreement, not a one-time catch-up.

**Corrective action:** if the export itself is the problem (stale, truncated, format-drifted),
escalate to whoever owns the Customer.io export delivery — re-running the sweep against the same
bad export reproduces the same spike. If the export is sound and the spike is a one-time
catch-up, no action is needed beyond confirming the next run's counts return to baseline.

## Malformed-row triage

`unparseable` rows never abort the sweep — every valid row in the same export still gets
processed, and the receipt's `parse_errors` attaches every malformed row's error so none is
dropped without a trace (spec: "Malformed rows are counted and attached"). Triage:

1. Read `parse_errors` for the run: each entry names a row number and which tracked column
   (`subject_key`, `channel`, `suppressed`) failed to parse — never the row's raw contact value,
   so this is safe to read and share as-is.
2. A handful of malformed rows scattered through an otherwise-clean export is usually a
   data-quality artifact in the source system generating the export — not this sweep's concern to
   fix, but worth flagging to whoever owns that source if the same subject keeps recurring.
3. A large or total spike in `unparseable` — most or all rows in the export failing the same
   column — means the export's format itself drifted from the fixture-pinned CSV shape the parser
   expects. Treat this the same as the drift-spike procedure's step 2: a manual check of the
   delivered file's columns against the pinned format, escalated to the export's owner, not a
   parser change made reactively against one bad delivery.
4. Malformed rows are never silently retried as-is — the same file re-parsed produces the same
   errors. The corrective action is fixing the source export (or, if the pinned format is genuinely
   out of date, updating the parser deliberately through the `customerio-consent-ingress` follow-on
   change), then re-running the sweep against a corrected delivery.

## Re-run posture

Re-running the sweep against the same delivered export is safe and idempotent: the D16
`logical_time` for a correction is the export's own as-of date, so re-running the same export
replays its corrections rather than double-declaring (spec: "A correction is attributed and
traceable"). A later, corrected export for the same or a new as-of date can legitimately re-correct
subjects the earlier run got wrong.

## PHI posture

Sweep receipts and logs carry subject keys, channels, and counts only — never raw contact values
(the export's suppression column contents) or any other demographic. `ExportParseError` is built to
be safe to attach whole to a receipt for exactly this reason. If any log line in Datadog shows more
than that, treat it as a PHI incident: capture the record's timestamp and logger name, and escalate
per the security review process before sharing the line anywhere.
