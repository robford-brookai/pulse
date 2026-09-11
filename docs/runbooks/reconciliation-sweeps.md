# Runbook: reconciliation-sweeps

Operator actions for the per-family referee sweeps (`packages/schedules`, `schedules.cli
reconcile-sweep`) that generalize S1.3's consent sweep to every catalog family (design.md decisions
1-10). The sweep registry (`schedules.sweep_registry.build_registry`) derives one sweep per family
from its catalog `ownership`: `recorded` families (today, `communication_consent`) keep the
existing `export_diff` sweep unchanged; `ledger` families (`billing_episode`, `consent`,
`contract`, `coverage`, `device`, `enrollment`, `referral`) get `projection_conformance` — a
referee that holds ledger-read, projection-read and warehouse-read credentials only, and never
writes. A divergence it reports is a projection defect, corrected by
`task projection:rebuild`/the landing's replay — never by this sweep.

## Before the first run: apply the fold view

`projection_conformance`'s `LandingReader` reads `STREAMLINE.STG_EVENTS.SUBJECT_CURRENT_STATE`
(`task snowflake:subject-current-state`). Both `STG_EVENTS` views are `ACCOUNTADMIN`-owned, so
neither the warehouse-sync service credential (role `OCEAN_WRITER`, grants scoped to
`STREAMLINE.OCEAN_RAW` only) nor a reader credential (e.g. `DNA_OPS_ROLE`, read-only) can apply
it — the first has no privilege on `STG_EVENTS`, the second can read the schema but has no
`CREATE VIEW` there. Apply it once, before any ledger-family sweep runs, with an operator's
personal key-pair user and `ACCOUNTADMIN`:

```bash
SNOWFLAKE_ACCOUNT=<operator's account> \
SNOWFLAKE_USER=<operator's key-pair user> \
SNOWFLAKE_PRIVATE_KEY_PATH=<path to that user's private key> \
SNOWFLAKE_ROLE=ACCOUNTADMIN \
  task snowflake:subject-current-state
```

Then grant the sweep's reader role read access, once:

```sql
GRANT SELECT ON VIEW STREAMLINE.STG_EVENTS.SUBJECT_CURRENT_STATE TO ROLE DNA_OPS_ROLE;
```

PASS: `show views in schema STREAMLINE.STG_EVENTS` run as `DNA_OPS_ROLE` lists
`SUBJECT_CURRENT_STATE`.

## Attended first run (task 4.1, live execution)

The first run against dev is attended, not scheduled — see the tracking GitHub issue for the
runbook checklist and the eight receipt lines it collects. Before running:

1. Confirm the sweep's credentials are read-only (ledger read, Twenty projection token, warehouse
   read) — no `pulse_core` writer token, no ledger DSN. The credential-posture gate
   (`packages/schedules`' test suite) asserts this in CI; the attended run reconfirms it against
   the actual dev environment before the first command executes.
2. Run each ledger family once: `schedules reconcile-sweep --family <family>` for `billing_episode`,
   `consent`, `contract`, `coverage`, `device`, `enrollment`, `referral` — plus the existing
   `communication_consent` (`export_diff`) sweep, unchanged. Every family produces exactly one
   receipt line on stdout.
3. Post each receipt line verbatim on the tracking issue — it is subject keys (capped at 200,
   true total beside the cap) and counts only, never a payload value or a payer identifier, so it
   is safe to paste as-is.
4. Note the run date as day one of the P0 streak clock for each family (see below).
5. Any family reporting a `missing` spike: cross-check the warehouse-sync liveness probe (#413)
   before treating it as projection drift — a stalled landing produces the same symptom the sweep
   is designed to catch, and the fix there is reviving the feed, not rebuilding a projection that
   was never behind.

`enrollment` registers two consumers: `twenty-board` and, as of `m1-retire-patient-state` task 3.1,
`graph-projection-patients` (`cite_field="ledger_seq"`). Until reconciliation-sweeps task 3.4
lands, the CLI does not build consumers from the registry and every ledger-family run reports
`no_consumers` (design.md decision 11). After 3.4, a consumer whose source is not configured for
the environment is reported `unconfigured` and skipped: dev01-brook hosts no OCEAN graph database,
so `graph-projection-patients` reads `unconfigured` there. Where a graph database exists, a legacy
row (null `ledger_seq`) reports `uncitable` per row, not as a whole-consumer class — the documented
steady state until genesis adopts it, never a divergence to chase. See
`docs/runbooks/m1-patients-projection.md` for the projection's own receipt run.

## Reading a receipt

Every run emits one `Receipt` (`schedules.receipt.receipt_payload`) as a JSON line:

| Field | Meaning |
| --- | --- |
| `date`, `family`, `kind`, `floor`, `snapshot_head` | Which family, which sweep kind (`export_diff` \| `projection_conformance`), the pinned `min_complete_from` floor, and the ledger sequence the run snapshotted at. |
| `no_consumers` | `true` when the family has zero registered consumers — passes, not a divergence (design decision 6). Expected for any ledger family before it is registered against a consumer. |
| `consumers[].agreements` | Rows that matched across the snapshot — no divergence. |
| `consumers[].divergences` | Counted by kind: `state` (fields differ, never values — the receipt names which fields, never what they held), `lag` (the cited `ledger_seq` is older than the head by more than the consumer's freshness budget — 60 s for `twenty-board`, 15 minutes by default for `warehouse-landing`), `missing` (ledger has the subject, the consumer does not), `orphan` (the consumer has the subject, the ledger does not). |
| `consumers[].uncitable` | Rows whose citation is null (a legacy `patients` row before genesis adopts it) — counted, never compared row by row. |
| `consumers[].unconfigured` | A registered consumer whose read source is not configured in this environment (after task 3.4; `graph-projection-patients` on dev01) — named and skipped, never a divergence. |
| `consumers[].in_flight` | Changed after the run's snapshot — never counted as divergence. |
| `consumers[].malformed` | Unparseable rows, counted and never silently dropped. |
| `consumers[].pre_floor` | The subject's whole history is before `min_complete_from` — absent from the warehouse fold view by design, not evidence of loss. |
| `consumers[].subject_keys` | Per outcome kind: up to 200 subject keys plus the true total beside the cap. |
| `tags` | `project:pulse`, `service:schedules`, `family:<name>` — for whichever monitor eventually reads these lines (`observability`, still queued). |

A family's exit code is 0 when rows were compared or when `no_consumers` is true, and 2 only when
consumers are registered but every one of them produced zero classified comparisons (empty read,
connectivity failure, or misconfiguration) — that split is what lets "nothing to compare yet"
(today's steady state before consumers are registered against every family) coexist with "the read
itself failed" as two different, correctly-distinguished outcomes.

## Computing the streak

`schedules.receipt.compute_streak(receipts)` takes any set of a single family's receipts, in any
order, and returns the number of consecutive, unbroken, clean calendar days ending at the most
recent one — a receipt is "clean" when every consumer's `divergences` are all zero (agreement,
`uncitable`, `in_flight`, `malformed`, and `pre_floor` counts do not break a streak; they are not
divergences). The streak breaks on the first non-clean day scanning backward from the most recent,
or on a gap in the calendar — a missing day's receipt is never assumed clean. Ten consecutive clean
daily receipts for a family is the P0 exit signal (design.md decision 8: "a failure or a streak is
per family"); compute it per family, never pooled across families.

## Registering a new consumer

A ledger family with no registered consumer receipts `no_consumers` and passes — this is expected
for a catalog release that adds a family nobody projects yet, not a defect to silence. To register
one:

1. Add a `Consumer` entry in `packages/schedules/src/schedules/consumer_registry.py`'s
   `build_consumers`: a `name`, the `families` it covers, a reader (implementing the same
   read-only interface as `BoardReader`/`LandingReader`/`RowCountReader`), a `cite_field` (the
   column the consumer's rows carry a `ledger_seq`-equivalent under — `None` marks it uncitable,
   reported as a class rather than compared per row), a `freshness_budget_s`, and — for an
   uncitable consumer — the `owning_change` that will eventually retire it (design decision 6).
2. Prefer deriving `families` from the consumer's own source of truth rather than hand-listing
   them, matching `board_families()`'s pattern (reads `twenty_projection.apply`'s registered board
   targets) — a family added there should register here without this module changing by hand.
3. Add the new entry to the registry × consumer matrix golden test (`test_consumer_registry.py`)
   so its wiring is pinned the same way the day-one three are.
4. No schedule catalog change is needed to add a consumer — the seven `reconcile-sweep-<family>`
   schedule entries already run daily against the registry as it stands; a new consumer is picked
   up the next scheduled run.

## PHI posture

Every field a receipt carries is a subject key, a field *name*, or a count — never a payload
value, a payer identifier, or a demographic (design.md decision 7, carried through by a PHI
tripwire test on the conformance core). A receipt or a log line safe to post on the tracking issue
verbatim is the intended posture; if any surface shows more than subject keys and counts, treat it
as a PHI incident and escalate per the security review process before sharing it anywhere.
