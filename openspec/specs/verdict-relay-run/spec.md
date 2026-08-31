# verdict-relay-run Specification

## Purpose
Defines the batch run's observable contract: the read → declare loop's receipt, its structured
logging shape, and the operator documentation for the monitors that watch it.
## Requirements
### Requirement: A run emits a receipt with seven counts

A relay run SHALL execute read → declare and finish by emitting a run receipt with the counts
declared, replayed, skipped-stale, rejected, transitioned, transition-rejected, and failed — as
structured logs tagged `service:verdict-relay`, including a single machine-parsable
(Datadog-parsable) summary line in exactly this form:

```
service=verdict-relay result=<success|failure> declared=N replayed=N skipped_stale=N rejected=N transitioned=N transition_rejected=N failed=N
```

`transitioned` counts committed paired transitions; `transition_rejected` counts paired
transitions the ledger refused (counted, never retried); rows of verdict types with no
`transition_by_outcome` entry contribute to neither. Logs SHALL carry subject keys only, never
demographics or any PHI. `failed` SHALL be 0 or 1: a run either completes with no failure, or
ends on the first row that exhausts transient retries, fails row validation, or violates the
mart contract, and that one row is counted in `failed`. A run that fails SHALL exit nonzero with
`result=failure` and the receipt's other counts reflecting work completed on prior rows before
the failure, so the resumed run picks up from the persisted cursor.

#### Scenario: A mixed batch produces a complete receipt

- **GIVEN** a batch containing a normal paired declare, an idempotent replay, a stale row, an
  illegal-transition verdict rejection, and a paired transition refused at a lifecycle boundary
- **WHEN** the run completes
- **THEN** the receipt reports declared=2, replayed=1, skipped-stale=1, rejected=1,
  transitioned=1, transition_rejected=1, failed=0 as structured logs tagged
  `service:verdict-relay`, with the summary line in the pinned form, and no log line carries
  anything beyond subject keys

### Requirement: Operators have a runbook for the relay monitors

A runbook SHALL document the failure modes and operator actions for the §1.5 monitors on this
service: verdict staleness exceeding 26 hours, and run failure — including how to read the
receipt, how to distinguish rejected from failed, and how a resumed run behaves against the
persisted cursor.

#### Scenario: The runbook covers both monitored failure modes

- **GIVEN** the published runbook
- **WHEN** an operator responds to a staleness > 26 h alert or a run-failure alert
- **THEN** the runbook names the failure mode, the diagnostic reads (receipt counts, summary
  line), and the corrective action, including safe re-run semantics
