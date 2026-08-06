# Proposal — s13-schedules

## Why

Two ledger obligations are clock-driven, not event-driven, and today nothing fires them: at month
start every active or on-hold Enrollment must get a BillingEpisode opened (object model §5.2), and
CommunicationConsent must be continuously reconciled against Customer.io, which D9 makes the
authority for consent conflicts. S1.1 (`pulse-ledger-core`, archived 2026-08-03) shipped everything
these jobs consume — the command API client, `open_billing_episode` and
`record_communication_consent` command types, D16 idempotency, and the current-state read surface —
so S1.3 on the program roadmap is unblocked and parallel-safe with S1.2/S1.4.

## What Changes

- **New package `packages/schedules`**: two thin clock-driven declarers with identical operational
  shape, one workspace member.
- **Month-open job**: enumerates active/on-hold Enrollments via the ledger's own read surface —
  `pulse_ledger.reads.enumerate_state(conn, subject_type, states)` over the co-committed
  `ledger.current_state` rows, a library read against ledger Postgres, never the warehouse —
  so month-open never depends on projection freshness. Issues one `open_billing_episode` per
  enrollment × current month with D16 idempotency keys, making the job safely re-runnable any day
  of the month (already-open episodes classify as replays). Zero enrollments enumerated is a hard
  failure, never a success with count 0. Requested states are catalog-validated: a typo is a
  rejection, never an empty result set.
- **D9 consent reconciliation sweep**: parses the delivered Customer.io suppression export (CSV,
  fixture-pinned format), diffs against ledger CommunicationConsent current state, and declares
  corrections with actor = `reconciliation` and export-row provenance. Customer.io wins every
  conflict — D9. Unparseable rows are counted and attached to the drift receipt, never dropped.
- **One CLI, two subcommands**, each with `--dry-run` printing the would-declare set with no API
  calls.
- **Scheduler wiring as IaC config** in `packages/schedules/infra/`, per D14 (SPCS job /
  EventBridge Scheduler): month-open at 00:30 on the 1st with a same-day retry window, sweep daily.
- **Runbooks**: `docs/runbooks/month-open.md` (missed-month-open page procedure, billing incident
  severity per ops plan §1.5) and `docs/runbooks/consent-sweep.md` (drift-spike procedure).

## Capabilities

### New Capabilities

- `month-open`: the month-start BillingEpisode opener — ledger-read enumeration, per-enrollment
  idempotent declaration, the zero-enrollment hard-failure invariant, and its receipt
  (opened / replayed / failed).
- `consent-reconciliation`: the D9 sweep — suppression-export parsing, diff against ledger consent
  state with Customer.io as authority, corrections declared as `reconciliation`, and the drift
  receipt (agreements, corrections, unparseable rows).
- `schedule-execution`: the shared operational shape — one CLI with two subcommands, offline
  `--dry-run` on both, and the IaC schedule definitions that wire the platform scheduler to the
  entrypoints.

### Modified Capabilities

_None. `ledger-read` already specifies the current-state enumeration month-open consumes ("Month-open
enumerates from the ledger" scenario) and `command-api` already specifies idempotent replay; this
change adds consumers of those surfaces, not changes to them._

## Impact

- New package under `packages/` (`schedules`), workspace member with the established conventions
  (uv, ruff, pyright/mypy, pytest, coverage floor 85, `--disable-socket`).
- Depends on S1.1 surfaces only: `pulse_core.client.PulseCoreClient.submit_command`,
  `pulse_core.idempotency.derive_idempotency_key`, `pulse_core.generated` command types,
  `pulse_ledger.reads.enumerate_state`. No new ledger endpoints, no schema changes.
- Auth per D15: the two jobs run under their service credentials (names in config, values from the
  environment, never in code or fixtures); sweep corrections attribute to the `reconciliation`
  actor.
- Out of scope (follow-on orders): BillingEpisode qualification verdicts (warehouse computes,
  S1.2 declares); live Customer.io API pull of the export (v1 consumes a delivered export file
  path — the `customerio-consent-ingress` change picks this up once the export mechanism is
  confirmed); genesis backfill runs (genesis has its own work orders).
- PHI: synthetic fixtures only; receipts and logs carry subject keys and counts, never
  demographics or contact details from the export.
- Rollback: pre-production, no live schedulers until the infra config is applied — reverting is
  removing the package and its schedule definitions; no data migration exists.
