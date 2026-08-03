# Tasks — ocean-eventbridge-migration

Annotation format, read by `task dispatch` and checked by G_MECE:
`[model | deps | lane | wave]`, with `serial:` carrying its justification where set.
`deps` names task numbers in this file; `—` means no dependency. The bracketed ID after each task
number is its Linear issue — DNA sub-issues of parent **DNA-733**, CCC issues for `destructive_ops`. Default model is `sonnet`
(`routing.default`), stated explicitly on every task per `model_declared_or_default`.

Paths are relative to `packages/ocean/` from task 1.3 onward.

**Out-of-lane tasks are marked `lane: destructive_ops`.** Those are excluded from `dispatch`,
`execute`, and `merge` — they run on the Open Engine queue (team CCC) as operator runbooks with
agent-prepared scripts, G_APPROVAL mandatory. They appear here so the plan is complete, not so they
can be dispatched. `task dispatch` must not emit work orders for them.

---

## 1. Wave 0 — absorption

- [x] 1.1 [CCC-15] Rotate every credential in the source repo's tracked `.env`, and record the rotation as
      the import precondition. Blocks 1.2.
      `[model: sonnet | deps: — | lane: destructive_ops | wave: 0]`
      Out of lane: touches live credentials, no reviewable diff.
- [x] 1.2 [DNA-734] Import `robford-brookai/ocean` at `7bc9d2c` to `packages/ocean` via `git-filter-repo`
      with the ADR §6.1 path allowlist and `--to-subdirectory-filter`. Pure move — no file content
      changes in this commit.
      `[model: opus | deps: 1.1 | lane: repo_change | wave: 0]`
      `serial: workspace_roots` — creates a workspace package and edits the root workspace manifest.
      Model `opus`: history correctness is weakly verifiable by test; a wrong rewrite is expensive
      to detect and expensive to undo.
      **This task writes no application code, so "tests first" does not apply to it** — the
      generic requirement is satisfied by the post-conditions below, which are the whole
      verification. Do not invent unit tests for a git operation.
      **Source:** `~/Repos/ocean`, which matches remote `main` at `7bc9d2c` and is authoritative
      (ADR §9.2). Do NOT use `~/Repos/brookai/ocean` — that clone is abandoned. The credential
      rotation this depends on (1.1) is complete.
      Run against a scratch clone, never the source working tree:
      `git clone ~/Repos/ocean /tmp/ocean-import && cd /tmp/ocean-import`
      `git filter-repo --path services/ --path libs/ --path infra/ --path tests/`
      `  --path scripts/ --path docs/ --path .github/ --path pyproject.toml --path uv.lock`
      `  --path Taskfile.yml --path pyrightconfig.json --path main.py --path README.md`
      `  --path .python-version --path .markdownlint.json --to-subdirectory-filter packages/ocean`
      Then graft the rewritten history into this repo and commit the move alone.
      Post-conditions, all of which must hold before the commit stands:
      `git ls-files packages/ocean | grep -cE '^packages/ocean/\.(repos|planning|gsd|claude|vscode|bg-shell)/'` is 0
      `git ls-files packages/ocean | grep -cE '(^|/)(\.env|agents\.md|CLAUDE\.md|\.gitignore|logs/)$'` is 0
      `git log --oneline -- packages/ocean | wc -l` is greater than 1 — history preserved, not squashed
      `git log --all --diff-filter=A --name-only | grep -c '/\.env$'` is 0
      The monorepo's own `AGENTS.md`, `CLAUDE.md` and `.gitignore` are unmodified by this commit.
- [x] 1.3 [DNA-735] Bring `packages/ocean` under the monorepo's **formatter and linter**, plus uv
      workspace membership, in a commit separate from 1.2.
      `[model: sonnet | deps: 1.2 | lane: repo_change | wave: 0]`
      `serial: workspace_roots` — edits root tool configuration.
      **Lint only. Typecheck and test are task 1.4** — see below for why that split exists, and do
      not widen this one to swallow them.
      Adopting the formatter reformats ocean's tree wholesale (~330 files). That is expected and
      unavoidable if ruff is to cover the package, but it must be **its own commit**, separate
      from the configuration change, and its SHA added to `.git-blame-ignore-revs` — otherwise it
      erases blame on history 1.2 existed to preserve.
      **Declared scope must equal executed scope.** A variable that lists `packages/ocean` while
      the command hardcodes `src` is a false claim about what CI checks. If a target cannot cover
      ocean yet, say so in `Taskfile.yml` with the reason; do not leave the variable implying it
      does. This is a review-reject.
      Done when: `task lint` checks every Python file under `packages/ocean` and passes; the
      typecheck and test targets state plainly that ocean is out of scope and why.
- [x] 1.4 [DNA-779] Bring `packages/ocean` under **mypy and pytest**.
      `[model: opus | deps: 1.3 | lane: repo_change | wave: 0]`
      `serial: workspace_roots` — edits root tool configuration.
      Split from 1.3 because this is real work, not configuration. Ocean's tests need Postgres and
      Kafka: 18 test modules fail collection without them, and 56 tests collect cleanly. Its libs
      have unresolved import errors under mypy.
      The first attempt at 1.3 met a combined "conformance" goal by pointing mypy at `src` and
      pytest at `tests` while the variables claimed ocean was included — a green gate covering 0
      of 339 ocean files. That is the failure mode this split exists to prevent, so narrowing the
      gate is not an available answer here either.
      Likely shape: mark service-dependent tests with a marker CI deselects, get the 56
      collectable tests running, and resolve or explicitly ignore the mypy import errors per
      module with a reason. Coverage floor for ocean is a decision to make in this task, not an
      assumption to inherit.
      Done when: mypy covers `packages/ocean` (or every exclusion is per-module with a stated
      reason), and ocean's collectable tests run in `task test`.

## 2. Wave 1 — the two contracts

- [x] 2.1 [DNA-736] Establish the topic → `(source, detail-type)` mapping as one generated surface: a source
      table for the eleven live domains, emitting both publisher addressing and Terraform rule
      patterns. Test: every live domain has exactly one entry, `warehouse-dlq` has none, and every
      emitted rule pattern round-trips against the table without the local stack running.
      `[model: sonnet | deps: 1.3 | lane: repo_change | wave: 1]`
      `serial: catalog_generated_surfaces` — a generated contract both producers and rules derive
      from; concurrent edits would let the two surfaces drift.
- [x] 2.2 [DNA-737] Replace `libs/ocean-broker`'s Kafka config builders with `EventBridgePublisher`:
      `publish(detail_type, event, key)` resolving addressing from 2.1, envelope carried whole in
      `detail`, `key` carried as an envelope field, and the Postgres `failed_webhooks` fallback on
      publish failure. Test: envelope round-trips field-for-field; `event_type` is not promoted to
      `detail-type`; bus failure writes `failed_webhooks` and does not raise.
      `[model: sonnet | deps: 2.1 | lane: repo_change | wave: 1]`
      `serial: workspace_roots` — every publish site depends on this library's surface.

## 3. Wave 2a — sequence guards (land before conversion, on the current transport)

A guard is transport-independent and harmless under ordered delivery, so these land before the
consumers are converted. Each task ships an out-of-order test: deliver the entity's events in
reverse, assert final state equals in-order final state. Per `event-delivery`, a guard MUST compare
an event-time field — a processing-time comparison is a review-reject.

Every guard below needs an event-time column, and OCEAN has **one** alembic sequence at
`infra/postgres/versions/`. Four guard tasks in four worktrees off `main` would each write their
own `0019` — four files, one revision number, four heads at merge. 3.0 lands that schema change
once, up front; the guards then rebase onto it and stay parallel. Added 2026-08-02 after 3.2
raised the collision mid-flight; the original plan declared 3.1–3.5 `parallel: yes` and missed it.

- [x] 3.0 [DNA-780] Add `last_event_at TIMESTAMPTZ NULL` to `interactions`, `device_associations`, `signals`
      and `slack_messages` in a single migration `0019`. Nullable on purpose: a pre-migration row
      has no known event time, and `IS NULL OR … < EXCLUDED…` then treats it as overwritable. No
      `now()` default — a processing-time default is the bug this wave removes. The value stored is
      the envelope's `timestamp` (`BaseEvent.timestamp`), never `completed_at`.
      `[model: sonnet | deps: 1.3 | lane: repo_change | wave: 2a]`
      `serial: alembic_sequence` — the only task in this wave that may touch
      `infra/postgres/versions/`. Blocks 3.1–3.5.
- [x] 3.1 [DNA-738] `graph-projection/src/handlers/outcomes.py:44` and `:103` — replace the unguarded
      `DO UPDATE SET outcome = …` pairs with an event-time sequence guard. Note `completed_at` is
      written as `:now` (processing time) and MUST NOT be the guard column; add an event-time
      column if none exists. This is the audit's worst case: today a completed call can be
      silently rewritten to missed.
      `[model: opus | deps: 3.0 | lane: repo_change | wave: 2a]`
      Model `opus`: concurrency judgement, and the obvious fix is the wrong one.
- [x] 3.2 [DNA-739] `graph-projection/src/handlers/interactions.py:36` and `:72` — replace the
      `last_event_id IS DISTINCT FROM` predicate with a sequence guard. Dedup is not ordering.
      `[model: opus | deps: 3.0 | lane: repo_change | wave: 2a]`
- [x] 3.3 [DNA-740] `graph-projection/src/handlers/logistics.py:125` (`device_associations`) — same
      dedup-only predicate, same replacement.
      `[model: opus | deps: 3.0 | lane: repo_change | wave: 2a]`
- [x] 3.4 [DNA-741] `graph-projection/src/handlers/signals.py:59` — add a guard to the unguarded
      `DO UPDATE SET anomalous = true`. Monotonic in effect today; guarded for uniformity so the
      audit's verdict holds by construction rather than by argument.
      `[model: sonnet | deps: 3.0 | lane: repo_change | wave: 2a]`
- [x] 3.5 [DNA-742] Add a sequence column to `slack-bot`'s stored message record and guard `chat_update` on
      it, so a stale update is dropped rather than applied. Test: out-of-order ticket lifecycle
      (`created` → `updated` → `resolved`) leaves the same terminal Slack text as in-order.
      `[model: opus | deps: 3.0 | lane: repo_change | wave: 2a]`
      Model `opus`: the effect leaves the system and is not undoable by a later event.
- [x] 3.6 [DNA-743] Re-confirm `control-plane`'s ordering verdict per handler in `EVENT_HANDLERS` and record
      the evidence. Any handler found order-dependent gets the 3.1 treatment as a new task under
      this group.
      `[model: opus | deps: 1.3 | lane: repo_change | wave: 2a]`
      Exploratory — `fan_out: exploratory_only` applies here and nowhere else in this change.

3.7–3.9 are the tasks 3.6 was allowed to create. Its evidence is
`packages/ocean/docs/ordering-verdict-control-plane.md`, backed by 25 tests in
`services/control-plane/tests/test_ordering_verdicts.py`, three of them `xfail(strict=True)` — one
per finding, so each of these tasks has a failing test waiting for it. The D3 audit's
"order-tolerant, per handler" verdict for `control-plane` does not hold.

- [x] 3.7 `control-plane/src/handlers/tickets.py:167`/`:205` — `handle_ticket_updated` reads the
      current status and writes the new one with only `is_valid_transition` between them, which is
      a legality check, not a sequence guard. Reversed `in_progress`/`resolved` leaves a resolved
      ticket at `in_progress`, silently; `waiting`↔`in_progress` are both legal, so within the
      working states the terminal status is simply whichever event was processed last. Apply 3.1's
      treatment. `tickets.updated_at` is `datetime.now()` (Caveat A) and MUST NOT be the guard
      column — add an event-time column populated from the envelope `timestamp`.
      **Same task, second defect:** on resolution the handler calls `build_outcome_event(...,
      timestamp=now.isoformat())` at `:280` — processing time, where the other four outcome relays
      pass the source event's `timestamp` through untouched. That single line poisons the field
      3.1's guard compares, for exactly the events that reach `graph-projection` from here. Fix
      both or neither.
      `[model: opus | deps: 3.0, 5.4 | lane: repo_change | wave: 3]`
      `serial: alembic_sequence` — needs a new revision on the shared sequence.
- [x] 3.8 `handle_rma_requested` and `handle_return_status_update` each read a row the event being
      processed did not write, and `return` when it is missing — after which the consumer commits
      and the message is gone. That is a lost effect, not a stale write, and no
      `ticket.rma.failed` is emitted, so nothing downstream observes it. **Not the 3.1 treatment:**
      a sequence guard does not address a precondition that has not arrived. Leave the message for
      redelivery — raise, or park it explicitly — without creating a silent infinite retry. Must be
      designed against the DLQ and redrive behaviour from 6.3, which is why it depends on it.
      `return.updated` was already live-hazardous under Kafka: it arrives on `ocean.logistics` from
      a connector while the `returns` row is written by control-plane itself.
      **Widened by 3.7, 2026-08-02.** A third path belongs here: `handle_ticket_updated` drops an
      early-arriving `resolved` because the legality check rejects the transition from `open`. 3.7
      guarded the status write and proved a guard cannot fix that case — it is a precondition that
      has not arrived, not a stale write, so control-plane's verdict stays Order-dependent until
      this task lands. 3.7 left it pinned as a characterisation test; make that test pass.
      `[model: opus | deps: 5.4, 6.3 | lane: repo_change | wave: 4]`
- [x] 3.9 Break the `ticket.created` echo cycle. `handle_ticket_created` publishes `ticket.created`,
      control-plane subscribes to that domain, and `EVENT_HANDLERS["ticket.created"]` routes it
      straight back into the same handler — minting a fresh `uuid4` and a fresh `human_id` each
      pass, so one requested ticket becomes an unbounded stream of tickets. Control-plane is the
      only publisher of `ticket.created`; every other service sends `ticket.create.requested`
      (`linear-connector/src/normalizer.py:67`, `slack-bot/src/bolt_app.py:789`), so that
      `EVENT_HANDLERS` key has no legitimate producer and is the mistake it looks like.
      **This must land before 9.1 provisions the real rules**, or the cycle is encoded into the new
      transport with a live bus behind it. Not an ordering property — found in the same wiring.
      `[model: opus | deps: 5.4 | lane: repo_change | wave: 3]`
      Blocks 9.1.

## 4. Wave 2b — publish-site conversions

Thirteen sites, two shapes. A `services/*/src/producer.py` glob finds only 7 of them. One task per
site, each swapping its transport code for `EventBridgePublisher` and keeping its payload
construction unchanged. Each test asserts the site emits through the shared publisher and that its
failure path writes `failed_webhooks`.

Keyed connector publishers (~~already had the `failed_webhooks` fallback — preserve it~~):

**Correction, 2026-08-02.** That parenthetical is false and was believed by the plan, not checked.
4.1 and 4.2 both found the fallback was *dead code*: `producer.py` accepted a `db_session_maker`
and `main.py` never passed one, so a publish failure dropped the event silently. Both wired it from
`DATABASE_URL`. Verify rather than assume on 4.3, 4.5 and 4.6 — do not "preserve" a fallback
without first confirming it was ever reachable. 4.10 found the mirror of this on the unkeyed side:
inheriting the fallback is not free either, since a service with no Postgres wiring at all needs a
session maker, deps, and compose env added before it has anywhere to dead-letter to.

- [x] 4.1 [DNA-744] `services/github-connector/src/producer.py` `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2b]`
- [x] 4.2 [DNA-745] `services/hubspot-connector/src/producer.py` `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2b]`
- [x] 4.3 [DNA-746] `services/impilo-connector/src/producer.py` `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2b]`
- [x] 4.4 [DNA-747] `services/pocar-connector/src/producer.py` `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2b]`
- [x] 4.5 [DNA-748] `services/zcc-connector/src/producer.py` `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2b]`
- [x] 4.6 [DNA-749] `services/mongodb-connector/src/publisher.py` `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2b]`

Unkeyed publishers (gain the `failed_webhooks` fallback by inheritance — a strict improvement, not
scope creep; call it out in the HANDOFF):

- [x] 4.7 [DNA-750] `services/control-plane/src/producer.py` `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2b]`
- [x] 4.8 [DNA-751] `services/linear-connector/src/producer.py` `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2b]`
- [x] 4.9 [DNA-752] `services/agent-worker/src/publisher.py` `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2b]`
- [x] 4.10 [DNA-753] `services/call-simulator/src/publisher.py` `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2b]`
- [x] 4.11 [DNA-754] `services/sim-driver/src/publisher.py` `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2b]`
- [x] 4.12 [DNA-755] `services/slack-bot/src/publisher.py` `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2b]`
- [x] 4.13 [DNA-756] `services/warehouse-sync/src/main.py` — inline `Producer` used for dead-letter writes.
      Removed rather than converted: its role passes to the queue DLQ in 7.2.
      `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2b]`
- [x] 4.14 [DNA-781] Bring the converted services into `task test`. `TESTED_PATHS` is
      `tests packages/ocean/libs` — ocean's 16 services are excluded (honestly declared, per 1.3
      and DNA-779). Every wave-2b task therefore writes tests that CI never runs: their green
      `task check` is truthful about what it covers and says nothing about the conversion. Until
      this lands, wave 2b is unverified by CI.
      `[model: opus | deps: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 4.12, 4.13 | lane: repo_change | wave: 2b]`
      `serial: workspace_roots` — edits `Taskfile.yml`, which thirteen parallel branches would
      collide on. Raised independently by 4.1, 4.2 and 4.10; deliberately deferred out of each of
      them for exactly that reason.
      Done when converted services' tests run in `task test` and the suite is green, or each
      exclusion that remains is per-service with a stated reason.
      Also fold in the de-duplication those tasks flagged: `_TOPIC_PREFIX` and `domain_for_topic`
      were copied verbatim into every converted service. Hoist one copy into `ocean_broker.catalog`
      and delete the rest.

## 5. Wave 2c — consumer conversions

Seven consumers. A `services/*/src/consumer.py` glob finds only 6; `warehouse-sync` holds an inline
`AIOConsumer`. Each task swaps subscribe/poll/commit for receive/process/delete, leaving process
shape, Dockerfile, and EKS deployment unchanged. Each records its ordering verdict in the HANDOFF.

- [x] 5.1 [DNA-757] `services/event-store/src/consumer.py` — verdict order-tolerant (append-only,
      `ON CONFLICT (event_id) DO NOTHING`).
      `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2c]`
- [x] 5.2 [DNA-758] `services/agent-worker/src/consumer.py` — verdict order-tolerant (single event type, one
      source). Its cross-replica `claimed_tasks` duplicate hazard predates this change; note it in
      the HANDOFF, do not fix it here.
      `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2c]`
- [x] 5.3 [DNA-759] `services/call-simulator/src/consumer.py` — verdict order-tolerant (single topic, single
      dispatch per approval).
      `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2c]`
- [x] 5.4 [DNA-760] `services/control-plane/src/consumer.py` — verdict per 3.6.
      `[model: sonnet | deps: 2.2, 3.6 | lane: repo_change | wave: 2c]`
- [x] 5.5 [DNA-761] `services/graph-projection/src/consumer.py` — convert only; all guard work landed in
      3.1–3.4.
      `[model: sonnet | deps: 2.2, 3.1, 3.2, 3.3, 3.4 | lane: repo_change | wave: 2c]`
- [x] 5.6 [DNA-762] `services/slack-bot/src/consumer.py` — convert only; guard landed in 3.5.
      `[model: sonnet | deps: 2.2, 3.5 | lane: repo_change | wave: 2c]`
- [x] 5.7 [DNA-763] `services/warehouse-sync/src/main.py` — inline `AIOConsumer` to SQS receive/delete.
      `[model: sonnet | deps: 2.2, 4.13 | lane: repo_change | wave: 2c]`
- [x] 5.8 Subscribe `event-store` to **all eleven** live domains. It takes 9 today — `tickets` and
      `patient-state` are missing — while its own docstring claims "all Ocean topics". 6.2 found
      this and correctly mirrored the code rather than widening it, because widening is a decision,
      not a transcription. **The decision is made: widen it** (Ford, 2026-08-02). An append-only
      event store that silently omits two domains is not an event store, and `patient-state` is the
      worst one to lose — 6.2 also found it has no subscriber at all besides `warehouse-sync`.
      Change `CONSUMER_DOMAINS["event-store"]` to `LIVE_DOMAINS`, regenerate
      `infra/terraform/generated/event_catalog.auto.tfvars.json`, and widen the consumer's own
      subscription to match. Correct the docstring, or make it true.
      Test: `event-store`'s rule pattern matches every live domain, and the generated tfvars
      round-trips against the table. Assert the two previously-missing domains explicitly by name,
      so a future narrowing fails loudly rather than silently.
      `[model: sonnet | deps: 5.1, 6.2 | lane: repo_change | wave: 4]`
      `serial: catalog_generated_surfaces` — edits the catalog both producers and rules derive
      from.
- [x] 5.9 Give `warehouse-sync` a MECE test suite. It is the only converted service with **zero**
      tests, and 5.7 changed real semantics without any: the flush moved from `INSERT` to a `MERGE`
      on `data:event_id`, making duplicate-safety a property the Kafka loop never had. That
      property is currently asserted nowhere.
      Cover, mutually exclusive and collectively exhaustive over the service's behaviour: receive/
      flush/delete ordering (nothing deleted before Snowflake commits), batch accumulation and the
      10s window, duplicate redelivery yielding no second row, out-of-order delivery yielding
      identical table contents, failed-batch redrive, cursor handling on the failure path, and
      shutdown with a partial batch. State the taxonomy explicitly in the test module so a future
      reader can see which cell each test occupies and which cells are empty.
      **Rider — stepwise execution and a run log.** The suite must be runnable a stage at a time
      rather than all-or-nothing, and must leave a durable record of what it did. Concretely: a
      pytest marker per MECE category so `-m <category>` runs exactly that stage; ordered stage
      identifiers so a run can resume from a named stage after a failure; and a per-run log written
      to a path the invocation names, recording for each stage its identifier, outcome, duration,
      and the batch/cursor state it observed. The log is the artifact — future runs are meant to be
      diffed against earlier ones, so keep it stable and free of wall-clock and random identifiers,
      the same normalisation discipline 8.1 applies.
      No PHI in the log, and synthetic fixtures only.
      `[model: opus | deps: 5.7, 4.14 | lane: repo_change | wave: 2c]`
      Model `opus`: choosing the taxonomy is the work; a suite that is merely a pile of tests
      satisfies the letter and not the point.

## 6. Wave 3 — infrastructure

- [x] 6.1 [DNA-764] Delete `infra/terraform/modules/msk-ocean/` and add the EventBridge bus.
      `[model: sonnet | deps: 2.1 | lane: repo_change | wave: 3]`
- [x] 6.2 [DNA-765] Add one rule and one SQS queue per consumer, patterns generated from 2.1. Test: each
      rule's pattern matches exactly its consumer's domain set.
      `[model: sonnet | deps: 6.1 | lane: repo_change | wave: 3]`
- [x] 6.3 [DNA-766] Add a DLQ and redrive policy per queue, with dead-letter volume exposed to monitoring
      per consumer. This is where ADR §1.4's DLQ-with-monitor stops being an assumption.
      `[model: sonnet | deps: 6.2 | lane: repo_change | wave: 3]`
- [x] 6.4 [DNA-767] Add the bus archive with retention. This is where ADR §4.6's replay stops being an
      assumption. Retention value per design Open Questions — any value 30–90 days satisfies the
      spec.
      `[model: sonnet | deps: 6.1 | lane: repo_change | wave: 3]`
- [x] 6.5 [DNA-768] Replace `redpanda`, `redpanda-console` and `redpanda-init` in `infra/docker-compose.yml`
      with LocalStack, and replace `infra/redpanda/topics.sh` with idempotent bus/rule/queue
      creation driven by 2.1's table. Test: re-running against an existing stack leaves it
      unchanged.
      `[model: sonnet | deps: 2.1, 6.2 | lane: repo_change | wave: 3]`
- [x] 6.6 [DNA-769] Remove `confluent_kafka` from every package manifest, lockfile **and Dockerfile**;
      add the AWS client dependency. Test: no source file outside the shared publisher references a
      bus client.
      **Scope widened 2026-08-02 to Dockerfiles, which are the deployment-breaking half.** 5.6
      found `slack-bot`'s Dockerfile still pinning `confluent-kafka==2.13.2` while installing
      neither `ocean-broker` nor `boto3` — that image cannot start as built, which is worse than a
      stale manifest and is invisible to every test we have. `agent-worker` and `call-simulator`
      share the gap, and 5.7/5.5 both noted the "Dockerfile unchanged" line in §5 is not literally
      achievable because several services pin deps inline. Sweep every service.
      Second test, and the one that would have caught this: for each service, the set of
      distributions its Dockerfile installs must satisfy the imports its `src/` actually makes.
      A Dockerfile that installs a bus client nothing imports, or omits one something does, fails.
      `[model: sonnet | deps: 4.13, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7 | lane: repo_change | wave: 3]`
      `serial: workspace_roots` — touches the workspace lockfile.
      **Dependency corrected 2026-08-02.** It read `4.13, 5.7`, which the graph considered
      satisfied while `control-plane`, `graph-projection` and `slack-bot` still imported
      `confluent_kafka` in their consumers — 5.4, 5.5 and 5.6. Its own stated test could not have
      passed, and because it is serial it was holding the whole remaining wave behind a task that
      was not yet runnable. It now depends on all of wave 2c.

- [x] 6.7 Make the LocalStack stack actually run. 8.2 was the first end-to-end execution of the
      committed local path and found **every SQS consumer dies silently with `NoRegionError`**:
      `infra/docker-compose.yml` sets `AWS_REGION`, and botocore 1.40 reads `AWS_DEFAULT_REGION`.
      8.2 worked around it in its own run config to get the comparison done; the durable fix is
      6.5's territory and was never in its scope.
      "Silently" is the important word — the consumer process stays up and `/health` keeps
      answering, so nothing observes that no event is ever consumed. Fix the env var, and add a
      smoke assertion that a published event actually reaches its consumer through the local stack,
      so this cannot regress into the same silence.
      `[model: sonnet | deps: 6.5, 8.2 | lane: repo_change | wave: 5]`

## 7. Wave 4 — warehouse path

- [x] 7.1 [DNA-770] Delete `infra/redpanda/connect.yaml` and the `ocean.warehouse-dlq` topic; move warehouse
      delivery onto the `warehouse-sync` queue from 6.2.
      `[model: sonnet | deps: 5.7, 6.2 | lane: repo_change | wave: 4]`
- [x] 7.2 [DNA-771] Point warehouse dead-lettering at the `warehouse-sync` queue's DLQ. Test: a repeatedly
      failing event lands there and is observable like any other consumer's.
      `[model: sonnet | deps: 7.1, 6.3 | lane: repo_change | wave: 4]`
- [x] 7.3 [DNA-772] Assert warehouse append semantics: out-of-order delivery yields identical table contents,
      and redelivery creates no duplicate row.
      `[model: sonnet | deps: 7.1 | lane: repo_change | wave: 4]`

## 8. Wave 4 — equivalence gate

- [x] 8.1 [DNA-773] Build the equivalence harness: capture graph tables and `audit_log` after a
      `call-simulator` + `sim-driver` run, normalized for wall-clock and random identifiers, and
      diff two runs.
      `[model: opus | deps: 6.5 | lane: repo_change | wave: 4]`
      Model `opus`: choosing what to normalize is the whole difficulty — normalize too much and the
      gate proves nothing.
- [x] 8.2 [DNA-774] Run the harness against the Kafka path and the LocalStack path and record the comparison.
      This result gates 9.2.
      `[model: sonnet | deps: 8.1, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 7.1 | lane: repo_change | wave: 4]`

## 9. Post-merge — destructive ops (out of lane)

Not dispatched. Open Engine queue (team CCC), operator runbooks with agent-prepared scripts,
G_APPROVAL comment required before each. Run after merge and verification.

- [x] 9.1 [CCC-16] `terraform apply` — provision bus, rules, queues, DLQs, archive.
      `[model: sonnet | deps: 3.9, 6.4, 8.2 | lane: destructive_ops | wave: post-merge]`
      3.9 was a hard gate, not a nicety: until the `ticket.created` echo cycle was broken, applying
      the control-plane rule would have encoded an unbounded ticket-minting loop into a live bus.
      **Released 2026-08-02** — 3.9 landed in #56, removing both self-consumed keys
      (`ticket.updated` echoed the same way; control-plane is the only publisher of either).
- [x] 9.2 [CCC-17] Tear down MSK Serverless. Gated on 8.2 passing — after this there is no transport
      rollback, only forward recovery via archive replay.
      `[model: sonnet | deps: 9.1, 8.2 | lane: destructive_ops | wave: post-merge]`
- [x] 9.3 [CCC-18] Archive `robford-brookai/ocean` read-only with ADR §7's supersession notice as its final
      commit and a README pointing at `packages/ocean`.
      `[model: fable | deps: 9.2 | lane: destructive_ops | wave: post-merge]`

## 10. Wave 4 — documentation

- [x] 10.1 [DNA-775] Record the absorption as an ADR in `docs/adr/`, and update
      `docs/contracts/publishes.md` and `consumes.md` for the transport change.
      `[model: fable | deps: 8.2 | lane: repo_change | wave: 4]`
- [x] 10.2 [DNA-776] Tick ADR §10 action items 3 and 6 (DNA-695 extended with the §6.1 absorption steps) and
      close §9.1 V5 — the shared publisher from 2.2 resolves it.
      `[model: fable | deps: 2.2, 10.1 | lane: repo_change | wave: 4]`
      `serial: openspec_main_specs` — doc-updater owns spec-adjacent files per `AGENTS.md`.
