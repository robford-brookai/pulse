# Runbook: billing-state

Operator actions for continuous billing and coverage state
(`openspec/changes/billing-state/`): what the verdict → transition pairing does, how often the
poll runs, why a no-op run is the healthy case, how to triage a `transition_rejected` count, and
how to roll back. The mechanism is the existing verdict relay, configuration-extended — nothing
new runs on its own schedule. Contract entries:
[`docs/contracts/publishes.md`](../contracts/publishes.md) §Coverage and billing state and
[`docs/contracts/consumes.md`](../contracts/consumes.md) §Verdict mart.

The relay's own failure modes — the §1.5 monitors (verdict staleness > 26 h, run failure), safe
re-run semantics, the recovery overlap — are unchanged and live in
[`verdict-relay.md`](verdict-relay.md). Read that one for "the run broke"; read this one for "the
state is wrong".

## Pairing semantics

For a verdict type registered in `verdict_relay.config`, a committed **or replayed**
`declare_verdict` is followed by a `declare_transition` on the same subject, targeting the state
the configuration maps from the verdict's outcome:

| Verdict type | Subject | `positive` | `negative` | `indeterminate` |
| --- | --- | --- | --- | --- |
| `billing_eligibility` | `billing_episode` | `qualified` | `not_qualified` | no transition |
| `coverage_eligibility` | `coverage` | `verified_active` | `verified_inactive` | no transition |
| `benefits_verification` | `coverage` | `verified_active` | `verified_inactive` | no transition |

Four properties to trust rather than re-derive:

- **A verdict type with no `transition_by_outcome` entry behaves exactly as it did before.** One
  command, the verdict, no transition. Registration is a reviewed edit to
  `packages/verdict-relay/src/verdict_relay/config.py`; an unregistered type fails row validation
  before any API call.
- **The pair is idempotent as a unit.** The transition's idempotency key derives from the verdict
  row (D16), so a rerun replays both halves and writes nothing, and a run that died between the
  two completes the pair on resume. There is no repair step for a half-written pair — run again.
- **`indeterminate` is evidence without consequence.** The verdict declares, no transition
  follows. This is deliberate: an indeterminate verdict should not move state.
- **The first verdict for an unseen patient × payer key mints the coverage subject** at its
  derived initial state (`unverified`) and applies the transition in the same run — the ledger
  validates that first transition as departing from an implicit `unverified` predecessor, so no
  separate genesis event is written and the subject's history starts with the real transition. No
  registration step and no manual minting: if a coverage subject is missing, the answer is a
  verdict, never a hand-written command.

Coverage states are coarse by design. QMB status, benefit categories, and copay detail live in the
verdict payload and `lineage_ref`. If someone asks for a "QMB" state, the answer is a payload
query against the verdict, not a catalog change.

## Poll cadence

The relay runs by a scheduled poll — the schedules-package entry `verdict-relay-poll` — not a
cross-repo trigger from the dbt run. A manual or scheduled invocation is the same path and the
same receipt:

```bash
task relay:run TARGET=dev   # dev|staging|prod — needs that target's credentials
```

which is `uv run python -m schedules.cli verdict-relay-poll`. Credentialed, so it is never reached
from `task check`, which stays offline and credential-free.

Configuration is env-var names only (`VERDICT_RELAY_*`, pinned in `verdict_relay.production`);
values live in the deploy environment. **The dev mart address is decided** (DNA-1252, mart PR
`Brookai/streamline#20`): `VERDICT_RELAY_SNOWFLAKE_DATABASE=STREAMLINE`,
`VERDICT_RELAY_SNOWFLAKE_SCHEMA=OCEAN_MARTS`, `VERDICT_RELAY_SNOWFLAKE_TABLE=OCEAN_VERDICTS` —
the dbt-materialized verdict mart in the streamline project, publisher-pinned in that repo's
`docs/contracts/publishes.md`. Account/user/warehouse remain per-target credentials; the
Snowflake credential itself is exactly one of `VERDICT_RELAY_SNOWFLAKE_PASSWORD` or
`VERDICT_RELAY_SNOWFLAKE_PRIVATE_KEY_PATH` (both set fails startup naming both). Key-pair JWT
exists because Snowflake's 2026 BCR bars passwords on TYPE=SERVICE users and enforces MFA
enrollment on TYPE=PERSON — a password-only headless reader is no longer provisionable, and the
streamline account's relay reader is a SERVICE key-pair identity. A missing variable fails startup naming exactly that
variable, before any Snowflake or ledger connection is attempted — so a misconfigured deploy tells
you which variable, not "connection refused". No credential value reaches a log, a receipt, or an
error message.

**Declare-back lag is bounded by mart freshness plus one poll interval.** That bound is the whole
reason the cadence is a poll: pick an interval against the mart's refresh, not against the volume
of verdicts. Shortening the interval costs no-op runs, which are free (below); lengthening it adds
directly to how stale billing and coverage state can be.

The interval itself is not yet set. The schedule catalog
(`packages/schedules/infra/terraform/generated/schedule_catalog.auto.tfvars.json`) carries
`month-open` and `consent-sweep` and **no `verdict-relay-poll` entry** — the cadence SLO, and
whether the 26 h verdict-staleness monitor tightens with it, is open question 7 on this change's
proposal. Until that entry lands, a run happens when something invokes `task relay:run` or the
subcommand directly. If declare-back is stale and no receipt lines exist in the window, the first
thing to check is whether anything is scheduled at all — see failure mode 1 in
[`verdict-relay.md`](verdict-relay.md).

## No-op runs are the healthy case

A poll that finds no rows past the cursor declares nothing, emits a receipt with all-zero counts
and `result=success`, and exits zero. Most polls are this. It is not a stuck run and not a missing
trigger.

The receipt carries seven counts, in a pinned single line:

```
service=verdict-relay result=success declared=2 replayed=1 skipped_stale=1 rejected=1 transitioned=1 transition_rejected=1 failed=0
```

The two counts this change added:

| Count | Meaning |
| --- | --- |
| `transitioned` | Paired transitions the ledger committed. |
| `transition_rejected` | Paired transitions the ledger refused. Counted, logged with the ledger's reason and `catalog_version`, **never retried**. |

Rows of verdict types with no `transition_by_outcome` entry contribute to neither. The other five
counts (`declared`, `replayed`, `skipped_stale`, `rejected`, `failed`) mean what
[`verdict-relay.md`](verdict-relay.md) says they mean.

Reading the pair counts:

- `transitioned` well below `declared` — normal if the batch carried unpaired verdict types or
  `indeterminate` outcomes. Suspicious only if the batch was all registered types with decisive
  outcomes.
- `transitioned=0` with `declared>0` on a batch of registered types is the signal that the pairing
  is not firing: check the mart's `verdict_type` spelling against the registered values, and the
  `outcome` vocabulary against the table above.
- An immediate second run after a completed batch is all replays and stale-skips with zero new
  events. Running twice is a safe way to confirm the relay, not a risk.

## Transition-rejected triage

`transition_rejected` is the ledger refusing an illegal edge, and refusal is the correct answer —
past a lifecycle boundary there is nothing to write. The canonical case: a `billing_eligibility`
verdict arriving for an episode already `reported`. The verdict commits, the transition is
refused, the count increments with the ledger's reason and catalog version logged, no retry
happens, and the run continues to the next row.

**The verdict half stands. Evidence is never rolled back because its consequence was refused** —
do not delete or reverse the verdict to "clean up" a rejection.

Triage in order:

1. **Occasional rejections at a closed boundary are expected**, not an incident. A month's mart
   re-serving verdicts for episodes that have since been `reported` produces exactly this. No
   action.
2. **A sustained or rising rate** means the mart and the lifecycle disagree about which subjects
   are still open. Read the logged reasons: they name the refused edge. If the mart is computing
   verdicts for closed episodes, that is a warehouse-workstream scoping question — a re-run cannot
   fix it, because rejection is correct each time.
3. **Rejections whose reason names a state that should be legal** are a catalog question, not a
   mart one. Compare the logged `catalog_version` against the catalog release the relay's
   configuration maps to; a mapped target state that the adjacency does not admit is a
   configuration or catalog defect, filed against this repo.
4. **Never retry by hand, and never widen the catalog to make a rejection go away.** Both write
   state the lifecycle boundary exists to prevent.

Log lines carry subject keys, verdict types, timestamps, reason codes, and the ledger's own
rejection message — never a row's `reason`, `outcome`, or `lineage_ref` value, which is where a
mart could carry a payer or member identifier. A log line showing more than that is a PHI incident:
capture its timestamp and logger name and escalate per the security review process before sharing
it anywhere.

## Rollback

**Stop the poll.** That is the procedure: disable whatever invokes `verdict-relay-poll` and do not
run `task relay:run`. Declaration stops, billing and coverage state stop advancing, and every already-committed event
stays in the ledger. Restarting resumes from the persisted cursor with no backfill step: rows
declared before the stop are D16 replays, rows behind a subject's `as_of` watermark skip, so the
resumed run cannot double-declare or regress a subject.

To stop the transitions but keep the evidence, remove the type's `transition_by_outcome` entry in
`verdict_relay.config` and redeploy — the relay then declares verdicts only, exactly as it did
before this change. Removing the `SUBJECT_TYPE_BY_VERDICT` entry instead is a harder stop: rows of
that type fail validation and the run stops on the first one.

The migration that widened the three subject-type CHECK constraints to admit `coverage` is
additive and stays in place. There is nothing to unwind: with the poll stopped, no coverage
subject is written, and the widened constraint is inert.
