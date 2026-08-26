# Tasks — snowflake-projection

Annotation format, read by `task dispatch` and checked by G_MECE:
`[model | deps | lane | wave]`, with `serial:` carrying its justification where set. `deps`
names task numbers in this file; `—` means no dependency. Linear ids get bracketed in after
`task linear:sync`. Default model is `sonnet`, stated explicitly on every task.

Every task ships its tests in the same commit (tests first per `AGENTS.md`). No live network
in repo-lane tests — Snowflake DDL is tested by parsing the committed SQL and by comparing
against the emitting code, never by connecting; the live proof belongs to the operator task.
Synthetic data only; no PHI anywhere. Specs are owned by the doc-updater: write proposed spec
changes to `HANDOFF.md`, never edit `openspec/specs/`.

**Entry conditions.** None blocking (proposal §Entry conditions). Task 2.1 provisions tenant
infrastructure: operator queue, G_APPROVAL per WORKFLOW v2.0.7 (a human-approved PR carrying
its runbook/artifacts), never a worktree.
No serial lanes are touched.

**Task ↔ scenario bijection** (G_MECE `task_scenario_bijection_covered`):

| Delta spec scenario | Covered by |
|---|---|
| warehouse-event-sync / "A committed ledger event lands as a warehouse row" | 2.1 (live proof) |
| warehouse-event-sync / "Redelivery still produces no second row" | 2.1 (live proof; offline MERGE-dedupe unit coverage already exists in `packages/ocean/tests/unit/test_warehouse_sqs_consumer.py`) |
| warehouse-event-sync / "The freshness figure is queryable after revival" | 2.1 (runs the pinned query), query text pinned by 1.3 |
| snowflake-stg-events / "Duplicate arrivals collapse to one row" | 1.1 (SQL shape test) + 2.1 (live spot-check) |
| snowflake-stg-events / "The columns match the emitter" | 1.1 (emitter-comparison test) |
| snowflake-stg-events / "The published row bounds completeness" | 1.3 (contract row + test), `min_complete_from` stamped by 2.1 |

---

## 1. Wave 1 — the committed shapes

- [x] 1.1 STG_EVENTS view as committed SQL, plus its offline tests. New
      `packages/ocean/infra/snowflake/stg_events_events.sql` (create the directory): a single
      `CREATE OR REPLACE VIEW STREAMLINE.STG_EVENTS.EVENTS AS ...` over
      `STREAMLINE.OCEAN_RAW.EVENTS`, deduping with
      `QUALIFY ROW_NUMBER() OVER (PARTITION BY data:event_id ORDER BY _loaded_at ASC) = 1`,
      typing every envelope field the relay emits. Derive the field list from the emitting
      code — `pulse_ledger`'s outbox/relay path and the ocean-broker publisher — NOT from
      `design/platform/event-envelope-spec.md` (superseded v1). Minimum columns: `event_id`,
      `event_type`, `subject_type`, `subject_key`, `seq`, `effective_at`, `_topic`,
      `_loaded_at`; list every additional emitted field you find, each typed with an explicit
      cast. No topic filter. Add an idempotent apply target `task snowflake:stg-events` in
      `Taskfile.yml` (guard: keep it OUT of `task check` — CI has no Snowflake credentials,
      per `docs/contracts/consumes.md` posture; read `docs/ci-lessons.md` before touching
      `Taskfile.yml`).
      Tests (new `packages/ocean/tests/unit/test_stg_events_sql.py`, offline, parses the
      committed SQL): asserts the QUALIFY dedupe clause is present with `ORDER BY _loaded_at
      ASC`; asserts every minimum column above appears as an output column; asserts the SQL
      contains no `WHERE` on `_topic`; and an emitter-comparison test that imports the
      envelope-building code, collects the emitted field names, and asserts each has a
      matching column in the SQL (failure message names the missing field).
      `[model: sonnet | deps: — | lane: repo_change | wave: 1]`

- [x] 1.2 Supersession note on the stale design leg. In
      `design/platform/snowflake-landing-spec.md`, directly under the `## Pipeline` heading:
      a note that the events leg (Twenty-Postgres CDC → `RAW_TWENTY.DOMAIN_EVENT` →
      STG_EVENTS) is superseded — the ledger is the record, envelopes land via
      `warehouse-event-sync` in `STREAMLINE.OCEAN_RAW.EVENTS`, and STG_EVENTS is defined by
      the `snowflake-stg-events` capability (this change's design.md decision 1). Entity-CDC
      and MART_STATE sections remain as-is. Do not delete or rewrite the leg's text.
      Tests (new `tests/test_landing_spec_superseded.py`): the file contains, within 40 lines
      of the `## Pipeline` heading, the strings `superseded`, `OCEAN_RAW.EVENTS`, and
      `snowflake-stg-events` (case-insensitive for `superseded`).
      `[model: sonnet | deps: — | lane: repo_change | wave: 1]`

- [x] 1.3 Publish the contract rows. In `docs/contracts/publishes.md`: (a) a new
      `STREAMLINE.STG_EVENTS.EVENTS` row — pinned column list (copied from 1.1's SQL), grain
      (one row per envelope `event_id`, earliest arrival wins), the verbatim freshness query
      `SELECT TIMESTAMPDIFF('minute', MAX(_loaded_at), CURRENT_TIMESTAMP()) FROM
      STREAMLINE.OCEAN_RAW.EVENTS`, a `min_complete_from` cell carrying the literal
      placeholder `` `stamped-at-revival` `` (inline code, never a link — `mkdocs build -s`),
      and the sentence naming `projection-rebuild-drill` as the change that closes the
      pre-revival gap; (b) on the existing `STREAMLINE.OCEAN_RAW.EVENTS` row, append the
      freshness expectation ("fed continuously by the provisioned warehouse-sync consumer").
      Tests (new `tests/test_stg_events_contract.py`): publishes.md contains the
      `STG_EVENTS.EVENTS` row; the row (or its adjacent prose) contains `TIMESTAMPDIFF`,
      `min_complete_from`, and `projection-rebuild-drill`; every column named in
      `stg_events_events.sql`'s output list appears in the contract row (parse both files —
      failure names the missing column).
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]`

## 2. Wave 2 — revival and live proof (operator)

- [x] 2.1 Provision the warehouse feed on dev and prove it end to end. From the operator
      queue under G_APPROVAL, per the 4.2 playbook and
      `scripts/pulse-ledger/provision_projection_feed.sh` precedent: (a) EventBridge rule on
      bus `duploservices-dev01-brook-ocean` matching `source = "ocean"`, targeting (b) a new
      SQS queue `duploservices-dev01-brook-pulse-warehouse-sync` with a DLQ and redrive
      policy, plus the queue access policy admitting the rule; (c) the `warehouse-sync`
      consumer (`packages/ocean/services/warehouse-sync`) as a Duplo service off its image —
      committed service JSON under the package's `infra/duplo/` (remember the create-time
      `OtherDockerConfig |= tojson` quirk recorded in
      `packages/pulse-ledger/infra/duplo/README.md`); (d) apply 1.1's view via
      `task snowflake:stg-events`. Then prove: drive one committed ledger event and observe
      its `event_id` as a row in `OCEAN_RAW.EVENTS` and exactly one row in
      `STG_EVENTS.EVENTS`; redeliver the same envelope and observe no second row; run 1.3's
      pinned freshness query and record the minutes figure. Finally: replace the
      `min_complete_from` placeholder in `docs/contracts/publishes.md` with today's date (that
      edit rides this task's PR — it is the one repo artifact this operator task owns).
      Verify: receipt on the tracking issue with every id, ARN, queue URL, row count, and the
      freshness figure spelled out — no ellipses (DNA-1192 lesson).
      `[model: sonnet | deps: 1.1, 1.3 | lane: destructive_ops | wave: 2]`
      Gate: G_APPROVAL — provisions tenant infrastructure; operator queue, never a worktree.
