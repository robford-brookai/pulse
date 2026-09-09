# Handoff Summary: pulse-demo-closeout

Collected 2 handoff(s).

## task-008-2-5

## Spec Updates

### Modified Requirements

`customerio-consent-ingress` attribution: the ingress writer id changes from `customer.io` to
`customer-io`. The command API derives writer ids from `PULSE_LEDGER_WRITER_TOKEN_<SUFFIX>` by
lowercasing the suffix and mapping `_` to `-`, so no suffix can ever produce a literal dot —
`customer.io` was unspellable as a writer id and stage 2 of Demo 5 could never authenticate live.
Rob's decision, 2026-09-02 (replan, decision 9): rename the ingress writer id to `customer-io`.

Landed in commit 6f6cb55 (replan, delta spec) and commit 8d30666 (fix: renamed across
`declarer.py`, `row_source.py`, `cli.py` docstrings, the producer registry, ADR-0005 append-only
note, and the demo5 runbook's now-resolved known-gap paragraph; added
`tests/test_customerio_writer_id_roundtrip.py` proving `CUSTOMER_IO` round-trips through
`pulse_ledger.auth`'s suffix mapping to `customer-io`). 3.3 was replanned to depend on 2.5.

## task-011-3-3

## Spec Updates

### Modified Requirements

None beyond the 2.5 writer-id rename this task depended on. No new spec-relevant deltas surfaced
during the live run.

## New Scenarios

**3.3 attended live run receipt — Demo 5, dev, 2026-09-02** (source: GitHub issue #342, third
comment; also referenced by the now-merged PR #353).

All six stages passed live, across two runs against the same committed events (image `1c7f383`,
migration head `0005`, tenant dev01-brook, subject key `brook-fx-demo5-episode-0001`, synthetic
throughout, no PHI):

| Run | Command | Stages | Outcome |
|---|---|---|---|
| A, 03:01Z | `task stage:e2e:live -- --no-preflight` | 1-4 passed, 5 failed | warehouse window empty: `pulse-warehouse-sync` had been dead since 2026-08-29 (DNA-1305) |
| B, 03:50Z | `task stage:e2e:live -- --no-preflight --from-stage=window_agreement` | 5-6 passed | exit 0 |

Per-stage assertion counts and subject keys:

- `identity_resolution` — 5 assertions, subject `brook-fx-demo5-episode-0001`
- `consent_ingress` — 4 assertions, subject `brook-fx-demo5-episode-0001`
- `board_drag` — 10 assertions, subject `demo5-board-brook-fx-demo5-episode-0001`
- `verdict_declare` — 4 assertions, subject `brook-fx-demo5-episode-0001`
- `window_agreement` (run A) — FAILED: window `warehouse` for subject
  `brook-fx-demo5-episode-0001:email`, no state at field `state`
- `window_agreement` (run B) — 10 assertions, subjects `brook-fx-demo5-episode-0001:email`,
  `brook-fx-demo5-episode-0001`, `brook-fx-demo5-episode-0001`
- `rebuild_drill` (run B) — 10 assertions, subject `brook-fx-demo5-episode-0001`

Why two runs: stage 2's consent declaration is idempotent on the fixture row, so a second full
walk against a ledger that already holds it stops with `first sweep expected 1 declared row, got
0`. `--from-stage` (added in PR #353) reran stages 5-6 against run A's already-committed events;
both runs read committed state by subject key.

Runbook assertions for 3.3:

1. All six stages pass live — yes, per the table above.
2. The rebuild drill's receipt shows zero differences — yes: one row repainted, no orphan, one
   row after, every compared field agrees.
3. The rebuilt card shows on the dev board within the 60 s freshness budget — yes, found on the
   first post-drill read.

Found and fixed on the way: stale API image rolled via ECR; migration 0005 applied through a
relay pod; consent writer key minted; dev Twenty API key was revoked and rotated (DNA-1304);
demo5 card seeded; `pulse-warehouse-sync` restarted after a week dead. Tooling fixes landed in
PR #353: real alembic table name in preflight, relay DSN override, `--from-stage`, live warehouse
reader decodes VARIANT payloads and TIMESTAMP_TZ, `task twenty:key:rotate`.

Correction: the GitHub-issue receipt states "Full receipt committed as
`handoffs/pulse-demo-closeout/3.3-receipt.md` on PR #353" — that file was never committed (PR
#353 touched no `handoffs/` path), and `handoffs/` is gitignored except for the tracked
`SUMMARY.md` this task now inlines into. Corrected on issue #342.

## Doc-Updater Instructions

1. For each spec-relevant update inlined above, edit the corresponding file in:
   `openspec/changes/pulse-demo-closeout/specs/`
2. Run `openspec validate pulse-demo-closeout` to check format.
3. Run `openlore drift` to check for new drift.
4. Ignore implementation details — only apply plan-relevant changes.
5. A `## Design Drift` section above means flag for human review.
