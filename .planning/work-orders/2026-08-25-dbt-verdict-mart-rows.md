# Work Order: produce the verdict mart rows (dbt) — unblocks billing-state 4.1

**For:** the warehouse/dbt workstream (the dbt project lives outside `pulse`, in the
streamline/data-platform estate — `pulse` cannot do this work; it only pins the contract).
**Unblocks:** `billing-state` task 4.1 (live declare-back, DNA-1158) — the last open task of a
9/10 change. Everything on the pulse side is merged, deployed, and approved.
**Contract authority:** `docs/contracts/consumes.md` § "Verdict mart" and
`packages/verdict-relay/src/verdict_relay/mart_reader.py` (`CONTRACT_COLUMNS`) in
`robford-brookai/pulse`. Fixtures showing exact accepted rows:
`packages/verdict-relay/tests/fixtures/*.json`.

## What to build

One Snowflake table or view (dbt-materialized; name and schema are the dbt side's choice — the
relay is pointed at it by environment variables `VERDICT_RELAY_SNOWFLAKE_DATABASE` /
`_SCHEMA` / `_TABLE`, so tell us the fully qualified name when it exists) producing verdict
rows for three verdict types:

| `verdict_type` | Subject it judges | `subject_id` semantics |
|---|---|---|
| `billing_eligibility` | `billing_episode` | the ledger's episode subject key |
| `coverage_eligibility` | `coverage` | the patient × payer coverage subject key |
| `benefits_verification` | `coverage` | the patient × payer coverage subject key |

These three names are load-bearing: they are registered in
`verdict_relay/config.py::SUBJECT_TYPE_BY_VERDICT`, and any other `verdict_type` value fails
row validation before any API call. Do not invent a fourth type without a reviewed pulse-side
edit first.

## The row contract — exact, no deviations

Grain: **one row per `(subject_id, verdict_type, run)`**. Columns, all eight, exactly:

| Column | Type / format | Rules |
|---|---|---|
| `subject_id` | string | The ledger subject key (see table above). For the two coverage types this is the ONLY identifying field — **the contract deliberately carries no payer, member-id, or demographic column, and none may be added**; that convention is what keeps payer identifiers out of relay logs. |
| `verdict_type` | string | One of the three registered values, verbatim. |
| `outcome` | string | `positive` \| `negative` \| `indeterminate`. **This column decides state, not just evidence**: `positive`/`negative` drive a paired `declare_transition` (`billing_eligibility`: → `qualified`/`not_qualified`; both coverage types: → `verified_active`/`verified_inactive`); `indeterminate` declares the verdict and moves nothing. A mislabeled outcome writes wrong billing or coverage state of record. |
| `reason` | string, nullable | Required in practice for `indeterminate` (an undecided verdict without a reason is a review-queue smell); nullable otherwise. |
| `rule_version` | string | The version of the deciding rule set (e.g. `rules-v3` or the dbt project git sha). Attributed onto every committed event — make it real and monotonic per rules change. |
| `as_of` | ISO-8601 timestamp, timezone-aware | Business time the verdict is true. Unparseable ⇒ the whole run fails naming the row. |
| `lineage_ref` | string | Pointer to the evidence the run used (e.g. `dbt-run-2026-08-01T02`). Coverage detail — QMB status, benefit categories, copay figures — belongs here / in evidence, **never as a new column**. |
| `computed_at` | ISO-8601 timestamp, timezone-aware | Run time. The relay's cursor pages on this column — it must be strictly newer for a fresh run's rows, or the relay treats them as already-served. |

A row missing any column, or with an unparseable timestamp, fails the relay run before any
declaration, naming the offending row (`RowValidationError`). Rerun semantics are safe by
construction: re-serving an identical verdict produces a `replayed` (idempotent no-op) on the
pulse side, so a full mart rebuild is harmless.

One more standing rule (state-catalog): rows with `rule_domain: business` and
`billing_investigation` semantics must never blend in the query feeding this mart.

## Where the subject ids come from

The ledger's subject keys reach Snowflake through the warehouse feed:
`STREAMLINE.OCEAN_RAW.EVENTS` (envelope as VARIANT) and, preferably, the typed view
`STREAMLINE.STG_EVENTS.EVENTS` (columns incl. `subject_type`, `subject_key`, `event_type`,
`effective_at` — contract row in pulse `docs/contracts/publishes.md`, merged 2026-08-25).
Source episode and coverage `subject_id`s from there — `subject_type = 'billing_episode'` and
`'coverage'` respectively. **Timing note:** the feed itself is being revived (dead since
2026-03-18; pulse change `snowflake-projection` task 2.1, imminent). Model against
`STG_EVENTS.EVENTS` now; rows will populate the moment the feed is live, and the contract's
`min_complete_from` watermark marks when subject coverage begins.

## Done means

1. The mart object exists and is refreshed by the scheduled dbt run; its fully qualified name
   is communicated back (comment on DNA-1158).
2. It contains at least one row per verdict type with `computed_at` newer than the dbt run
   that produced it, for subjects that exist in `STG_EVENTS.EVENTS`.
3. Acceptance is the relay itself: pulse runs `task relay:run TARGET=dev` twice — the first
   run declares every row (verdict + paired transition committed to the ledger), the second
   returns **all-replays with zero failures**. A persistently nonzero `rejected` count means
   the mart is producing outcomes the catalog refuses (rules/mart drift — comes back to this
   workstream). That two-run proof is billing-state 4.1, and its receipt closes DNA-1158.

## Explicitly out of scope

- Any new column on the contract (especially payer/member identifiers — prohibited).
- A fourth verdict type (requires a reviewed pulse-side registration first).
- The push/trigger seam: the relay polls; no dbt-side invocation of pulse is wanted
  (billing-state design decision 6).
