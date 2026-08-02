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
- [ ] 1.2 [DNA-734] Import `robford-brookai/ocean` at `7bc9d2c` to `packages/ocean` via `git-filter-repo`
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
- [ ] 1.3 [DNA-735] Conform `packages/ocean` to the monorepo toolchain (ruff, mypy, pytest, workspace
      membership) in a commit separate from 1.2. Green `task check` with the package included.
      `[model: sonnet | deps: 1.2 | lane: repo_change | wave: 0]`
      `serial: workspace_roots` — edits root tool configuration.

## 2. Wave 1 — the two contracts

- [ ] 2.1 [DNA-736] Establish the topic → `(source, detail-type)` mapping as one generated surface: a source
      table for the eleven live domains, emitting both publisher addressing and Terraform rule
      patterns. Test: every live domain has exactly one entry, `warehouse-dlq` has none, and every
      emitted rule pattern round-trips against the table without the local stack running.
      `[model: sonnet | deps: 1.3 | lane: repo_change | wave: 1]`
      `serial: catalog_generated_surfaces` — a generated contract both producers and rules derive
      from; concurrent edits would let the two surfaces drift.
- [ ] 2.2 [DNA-737] Replace `libs/ocean-broker`'s Kafka config builders with `EventBridgePublisher`:
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

- [ ] 3.1 [DNA-738] `graph-projection/src/handlers/outcomes.py:44` and `:103` — replace the unguarded
      `DO UPDATE SET outcome = …` pairs with an event-time sequence guard. Note `completed_at` is
      written as `:now` (processing time) and MUST NOT be the guard column; add an event-time
      column if none exists. This is the audit's worst case: today a completed call can be
      silently rewritten to missed.
      `[model: opus | deps: 1.3 | lane: repo_change | wave: 2a]`
      Model `opus`: concurrency judgement, and the obvious fix is the wrong one.
- [ ] 3.2 [DNA-739] `graph-projection/src/handlers/interactions.py:36` and `:72` — replace the
      `last_event_id IS DISTINCT FROM` predicate with a sequence guard. Dedup is not ordering.
      `[model: opus | deps: 1.3 | lane: repo_change | wave: 2a]`
- [ ] 3.3 [DNA-740] `graph-projection/src/handlers/logistics.py:125` (`device_associations`) — same
      dedup-only predicate, same replacement.
      `[model: opus | deps: 1.3 | lane: repo_change | wave: 2a]`
- [ ] 3.4 [DNA-741] `graph-projection/src/handlers/signals.py:59` — add a guard to the unguarded
      `DO UPDATE SET anomalous = true`. Monotonic in effect today; guarded for uniformity so the
      audit's verdict holds by construction rather than by argument.
      `[model: sonnet | deps: 1.3 | lane: repo_change | wave: 2a]`
- [ ] 3.5 [DNA-742] Add a sequence column to `slack-bot`'s stored message record and guard `chat_update` on
      it, so a stale update is dropped rather than applied. Test: out-of-order ticket lifecycle
      (`created` → `updated` → `resolved`) leaves the same terminal Slack text as in-order.
      `[model: opus | deps: 1.3 | lane: repo_change | wave: 2a]`
      Model `opus`: the effect leaves the system and is not undoable by a later event.
- [ ] 3.6 [DNA-743] Re-confirm `control-plane`'s ordering verdict per handler in `EVENT_HANDLERS` and record
      the evidence. Any handler found order-dependent gets the 3.1 treatment as a new task under
      this group.
      `[model: opus | deps: 1.3 | lane: repo_change | wave: 2a]`
      Exploratory — `fan_out: exploratory_only` applies here and nowhere else in this change.

## 4. Wave 2b — publish-site conversions

Thirteen sites, two shapes. A `services/*/src/producer.py` glob finds only 7 of them. One task per
site, each swapping its transport code for `EventBridgePublisher` and keeping its payload
construction unchanged. Each test asserts the site emits through the shared publisher and that its
failure path writes `failed_webhooks`.

Keyed connector publishers (already had the `failed_webhooks` fallback — preserve it):

- [ ] 4.1 [DNA-744] `services/github-connector/src/producer.py` `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2b]`
- [ ] 4.2 [DNA-745] `services/hubspot-connector/src/producer.py` `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2b]`
- [ ] 4.3 [DNA-746] `services/impilo-connector/src/producer.py` `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2b]`
- [ ] 4.4 [DNA-747] `services/pocar-connector/src/producer.py` `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2b]`
- [ ] 4.5 [DNA-748] `services/zcc-connector/src/producer.py` `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2b]`
- [ ] 4.6 [DNA-749] `services/mongodb-connector/src/publisher.py` `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2b]`

Unkeyed publishers (gain the `failed_webhooks` fallback by inheritance — a strict improvement, not
scope creep; call it out in the HANDOFF):

- [ ] 4.7 [DNA-750] `services/control-plane/src/producer.py` `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2b]`
- [ ] 4.8 [DNA-751] `services/linear-connector/src/producer.py` `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2b]`
- [ ] 4.9 [DNA-752] `services/agent-worker/src/publisher.py` `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2b]`
- [ ] 4.10 [DNA-753] `services/call-simulator/src/publisher.py` `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2b]`
- [ ] 4.11 [DNA-754] `services/sim-driver/src/publisher.py` `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2b]`
- [ ] 4.12 [DNA-755] `services/slack-bot/src/publisher.py` `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2b]`
- [ ] 4.13 [DNA-756] `services/warehouse-sync/src/main.py` — inline `Producer` used for dead-letter writes.
      Removed rather than converted: its role passes to the queue DLQ in 7.2.
      `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2b]`

## 5. Wave 2c — consumer conversions

Seven consumers. A `services/*/src/consumer.py` glob finds only 6; `warehouse-sync` holds an inline
`AIOConsumer`. Each task swaps subscribe/poll/commit for receive/process/delete, leaving process
shape, Dockerfile, and EKS deployment unchanged. Each records its ordering verdict in the HANDOFF.

- [ ] 5.1 [DNA-757] `services/event-store/src/consumer.py` — verdict order-tolerant (append-only,
      `ON CONFLICT (event_id) DO NOTHING`).
      `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2c]`
- [ ] 5.2 [DNA-758] `services/agent-worker/src/consumer.py` — verdict order-tolerant (single event type, one
      source). Its cross-replica `claimed_tasks` duplicate hazard predates this change; note it in
      the HANDOFF, do not fix it here.
      `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2c]`
- [ ] 5.3 [DNA-759] `services/call-simulator/src/consumer.py` — verdict order-tolerant (single topic, single
      dispatch per approval).
      `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2c]`
- [ ] 5.4 [DNA-760] `services/control-plane/src/consumer.py` — verdict per 3.6.
      `[model: sonnet | deps: 2.2, 3.6 | lane: repo_change | wave: 2c]`
- [ ] 5.5 [DNA-761] `services/graph-projection/src/consumer.py` — convert only; all guard work landed in
      3.1–3.4.
      `[model: sonnet | deps: 2.2, 3.1, 3.2, 3.3, 3.4 | lane: repo_change | wave: 2c]`
- [ ] 5.6 [DNA-762] `services/slack-bot/src/consumer.py` — convert only; guard landed in 3.5.
      `[model: sonnet | deps: 2.2, 3.5 | lane: repo_change | wave: 2c]`
- [ ] 5.7 [DNA-763] `services/warehouse-sync/src/main.py` — inline `AIOConsumer` to SQS receive/delete.
      `[model: sonnet | deps: 2.2, 4.13 | lane: repo_change | wave: 2c]`

## 6. Wave 3 — infrastructure

- [ ] 6.1 [DNA-764] Delete `infra/terraform/modules/msk-ocean/` and add the EventBridge bus.
      `[model: sonnet | deps: 2.1 | lane: repo_change | wave: 3]`
- [ ] 6.2 [DNA-765] Add one rule and one SQS queue per consumer, patterns generated from 2.1. Test: each
      rule's pattern matches exactly its consumer's domain set.
      `[model: sonnet | deps: 6.1 | lane: repo_change | wave: 3]`
- [ ] 6.3 [DNA-766] Add a DLQ and redrive policy per queue, with dead-letter volume exposed to monitoring
      per consumer. This is where ADR §1.4's DLQ-with-monitor stops being an assumption.
      `[model: sonnet | deps: 6.2 | lane: repo_change | wave: 3]`
- [ ] 6.4 [DNA-767] Add the bus archive with retention. This is where ADR §4.6's replay stops being an
      assumption. Retention value per design Open Questions — any value 30–90 days satisfies the
      spec.
      `[model: sonnet | deps: 6.1 | lane: repo_change | wave: 3]`
- [ ] 6.5 [DNA-768] Replace `redpanda`, `redpanda-console` and `redpanda-init` in `infra/docker-compose.yml`
      with LocalStack, and replace `infra/redpanda/topics.sh` with idempotent bus/rule/queue
      creation driven by 2.1's table. Test: re-running against an existing stack leaves it
      unchanged.
      `[model: sonnet | deps: 2.1, 6.2 | lane: repo_change | wave: 3]`
- [ ] 6.6 [DNA-769] Remove `confluent_kafka` from every package manifest and lockfile; add the AWS client
      dependency. Test: no source file outside the shared publisher references a bus client.
      `[model: sonnet | deps: 4.13, 5.7 | lane: repo_change | wave: 3]`
      `serial: workspace_roots` — touches the workspace lockfile.

## 7. Wave 4 — warehouse path

- [ ] 7.1 [DNA-770] Delete `infra/redpanda/connect.yaml` and the `ocean.warehouse-dlq` topic; move warehouse
      delivery onto the `warehouse-sync` queue from 6.2.
      `[model: sonnet | deps: 5.7, 6.2 | lane: repo_change | wave: 4]`
- [ ] 7.2 [DNA-771] Point warehouse dead-lettering at the `warehouse-sync` queue's DLQ. Test: a repeatedly
      failing event lands there and is observable like any other consumer's.
      `[model: sonnet | deps: 7.1, 6.3 | lane: repo_change | wave: 4]`
- [ ] 7.3 [DNA-772] Assert warehouse append semantics: out-of-order delivery yields identical table contents,
      and redelivery creates no duplicate row.
      `[model: sonnet | deps: 7.1 | lane: repo_change | wave: 4]`

## 8. Equivalence gate

- [ ] 8.1 [DNA-773] Build the equivalence harness: capture graph tables and `audit_log` after a
      `call-simulator` + `sim-driver` run, normalized for wall-clock and random identifiers, and
      diff two runs.
      `[model: opus | deps: 6.5 | lane: repo_change | wave: 4]`
      Model `opus`: choosing what to normalize is the whole difficulty — normalize too much and the
      gate proves nothing.
- [ ] 8.2 [DNA-774] Run the harness against the Kafka path and the LocalStack path and record the comparison.
      This result gates 9.2.
      `[model: sonnet | deps: 8.1, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 7.1 | lane: repo_change | wave: 4]`

## 9. Out of lane — destructive ops

Not dispatched. Open Engine queue (team CCC), operator runbooks with agent-prepared scripts,
G_APPROVAL comment required before each. Run after merge and verification.

- [ ] 9.1 [CCC-16] `terraform apply` — provision bus, rules, queues, DLQs, archive.
      `[model: sonnet | deps: 6.4, 8.2 | lane: destructive_ops | wave: post-merge]`
- [ ] 9.2 [CCC-17] Tear down MSK Serverless. Gated on 8.2 passing — after this there is no transport
      rollback, only forward recovery via archive replay.
      `[model: sonnet | deps: 9.1, 8.2 | lane: destructive_ops | wave: post-merge]`
- [ ] 9.3 [CCC-18] Archive `robford-brookai/ocean` read-only with ADR §7's supersession notice as its final
      commit and a README pointing at `packages/ocean`.
      `[model: fable | deps: 9.2 | lane: destructive_ops | wave: post-merge]`

## 10. Documentation

- [ ] 10.1 [DNA-775] Record the absorption as an ADR in `docs/adr/`, and update
      `docs/contracts/publishes.md` and `consumes.md` for the transport change.
      `[model: fable | deps: 8.2 | lane: repo_change | wave: 4]`
- [ ] 10.2 [DNA-776] Tick ADR §10 action items 3 and 6 (DNA-695 extended with the §6.1 absorption steps) and
      close §9.1 V5 — the shared publisher from 2.2 resolves it.
      `[model: fable | deps: 2.2, 10.1 | lane: repo_change | wave: 4]`
      `serial: openspec_main_specs` — doc-updater owns spec-adjacent files per `AGENTS.md`.
