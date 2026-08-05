## Purpose

Defines the batch run's observable contract: the read → declare loop's receipt, its structured
logging shape, and the operator documentation for the monitors that watch it.

## ADDED Requirements

### Requirement: A run emits a receipt with five counts

A relay run SHALL execute read → declare and finish by emitting a run receipt with the counts
declared, replayed, skipped-stale, rejected, and failed — as structured logs tagged
`service:verdict-relay`, including a single machine-parsable (Datadog-parsable) summary line. Logs
SHALL carry subject keys only, never demographics or any PHI. A run that fails (transient
exhaustion or contract violation) SHALL exit nonzero with the receipt reflecting work completed
before the failure, so the resumed run picks up from the persisted cursor.

#### Scenario: A mixed batch produces a complete receipt

- **GIVEN** a batch containing a normal declare, an idempotent replay, a stale row, and an
  illegal-transition rejection
- **WHEN** the run completes
- **THEN** the receipt reports declared=1, replayed=1, skipped-stale=1, rejected=1, failed=0 as
  structured logs tagged `service:verdict-relay` with one machine-parsable summary line, and no
  log line carries anything beyond subject keys

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
