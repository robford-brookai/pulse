# Tasks — pulse-ledger-core

Annotation format, read by `task dispatch` and checked by G_MECE:
`[model | deps | lane | wave]`, with `serial:` carrying its justification where set. `deps` names
task numbers in this file; `—` means no dependency. Linear ids get bracketed in after
`task linear:sync`. Default model is `sonnet`, stated explicitly on every task.

Every task ships its tests in the same commit (tests first per `AGENTS.md`). No live network in
any test (`--disable-socket` posture); the command API is faked at the client boundary in
downstream-facing tests and exercised against a local Postgres in service tests.

---

## 1. Wave 0 — schema and scaffold

- [x] 1.1 [DNA-785] Scaffold `packages/pulse-ledger` and `packages/pulse-core` as workspace members
      (pyproject, uv workspace roots, ruff/mypy/pytest wiring, `TESTED_PATHS` updated honestly).
      `[model: sonnet | deps: — | lane: repo_change | wave: 0]`
      `serial: workspace_roots` — edits root workspace manifest and `Taskfile.yml`.
      Declared scope must equal executed scope (the 1.3/1.4 lesson from the archived change).
- [x] 1.2 [DNA-786] The `ledger` schema, alembic sequence `0001`: `events` (bitemporal, evidence_class,
      epoch, reverses_event_id), `current_state`, `idempotency_keys`, `outbox` (per-subject seq),
      `writer_state`, `review_queue` — per design decision 1. REVOKE UPDATE/DELETE on `events`
      from the service role. Tests: migration up/down; the revoke holds (update attempt fails);
      co-commit constraint shape.
      `[model: opus | deps: 1.1 | lane: repo_change | wave: 0]`
      `serial: alembic_sequence` — the only task that may create this package's
      `infra/postgres/versions/`. Model `opus`: the schema is the one artifact retrofit can't fix
      (BF-5).

## 2. Wave 1 — generated command surface

- [x] 2.1 [DNA-787] Catalog → command-type generator: transition tables + Pydantic command types
      (`pulse_core.generated`), from the Appendix C seed until S0.2's catalog file is
      authoritative; version-pinned to `catalog_version`, trinary verdict enum with
      mandatory-reason-on-indeterminate. Test: generated adjacency round-trips the seed; unknown
      command type absent; indeterminate-without-reason fails model validation.
      `[model: opus | deps: 1.1 | lane: repo_change | wave: 1]`
      `serial: catalog_generated_surfaces` — one generated contract, producers and validator both
      derive from it.

## 3. Wave 2 — the write path

- [x] 3.1 [DNA-788] Command validation core: legality against the generated adjacency for all six subject
      types (incl. `qualified ⇄ not_qualified` re-entry and reported-freeze), rejection carries
      catalog reason + version. Tests: one legal/illegal pair per subject type; boot refuses on
      catalog version mismatch.
      `[model: opus | deps: 1.2, 2.1 | lane: repo_change | wave: 2]`
- [x] 3.2 [DNA-789] Commit path: event + current_state + outbox in one transaction; server-set
      `recorded_at`; `effective_at` canonical with `occurred_at` alias; correction by reversal.
      Tests: atomicity (no partial write on injected failure); backdate fold order; reversal
      references and preserves history.
      `[model: opus | deps: 3.1 | lane: repo_change | wave: 2]`
- [ ] 3.3 [DNA-790] Idempotency: D16 key derivation helper in `pulse_core`, unique constraint handling,
      replay returns original event id. Tests: replay-after-timeout yields one event; distinct
      logical_time yields two.
      `[model: sonnet | deps: 3.2 | lane: repo_change | wave: 2]`
- [ ] 3.4 [DNA-791] Auth and attribution: per-writer bearer credentials → `writer_id` = actor; body-actor
      spoof rejected; HMAC middleware present, Twenty route disabled. Tests: spoof attempt;
      credential names from env, never fixtures.
      `[model: opus | deps: 3.2 | lane: repo_change | wave: 2]`
      Model `opus`: security boundary; PHI-adjacent logging reviewed here.
- [ ] 3.5 [DNA-792] Backfill mode: `POST /commands:batch`, `backfill_genesis` and `reconstruction_gap`
      restricted to the backfill actor, evidence_class/epoch stamping. Tests: forward writer
      rejected on backfill types; gap + genesis sequence commits with reconstructed epoch.
      `[model: sonnet | deps: 3.3, 3.4 | lane: repo_change | wave: 2]`

## 4. Wave 3 — reads, client, distribution

- [ ] 4.1 [DNA-793] Read APIs: current-state enumeration (subject_type × state), identity candidate lookup
      with (system, value) uniqueness enforcement, review-queue listing. Tests: month-open
      enumeration case; duplicate attach rejected naming the holder; quarantine pending/drained.
      `[model: sonnet | deps: 3.2 | lane: repo_change | wave: 3]`
- [ ] 4.2 [DNA-794] Writer-state cursors: `PUT/GET /writers/{writer_id}/cursor` + `pulse_core` accessors.
      Test: crash/resume round-trip.
      `[model: sonnet | deps: 3.4 | lane: repo_change | wave: 3]`
- [ ] 4.3 [DNA-795] `pulse_core` client: command submission with response classification
      (committed/replayed/rejected/transient), retry/backoff on transient only, and the
      `consume(handler)` convention (SQS receive/process/delete, event_id dedupe). Tests: each
      classification mapped; handler safe under redelivery.
      `[model: sonnet | deps: 3.3, 3.5 | lane: repo_change | wave: 3]`
- [ ] 4.4 [DNA-796] Outbox relay worker through `ocean-broker`'s `EventBridgePublisher`: per-subject
      sequence order, 5 attempts → DLQ, lag metric. Tests: order across retry; poison row
      dead-letters and relay continues; no publish without commit.
      `[model: opus | deps: 3.2 | lane: repo_change | wave: 3]`
- [ ] 4.5 [DNA-797] LocalStack wiring: ledger Postgres + relay + bus in `infra/docker-compose` extension of
      the existing local stack; idempotent bring-up. Test: committed event observable on a
      LocalStack queue.
      `[model: sonnet | deps: 4.4 | lane: repo_change | wave: 3]`

## 5. Wave 4 — proof and documentation

- [ ] 5.1 [DNA-798] End-to-end fold equivalence: commit a mixed history (forward, backdated, reversal,
      backfill) for each subject type; independently fold events and assert equality with
      `current_state`; flat-projection columns present for the STG_EVENTS contract.
      `[model: opus | deps: 3.5, 4.1, 4.4 | lane: repo_change | wave: 4]`
- [ ] 5.2 [DNA-799] Pin the downstream names: update `design/delivery/pulse-s1-work-orders.md` "confirm
      path" markers (client path, read endpoints, quarantine table, cursor facility, handler
      signature) and the roadmap's queued-changes row; supersession notes on the two v1 platform
      docs (envelope ingest posture, state-catalog grain/legality). ADR entry in `docs/adr/`;
      `docs/contracts/publishes.md` for the read/command surfaces.
      `[model: fable | deps: 5.1 | lane: repo_change | wave: 4]`
      `serial: openspec_main_specs` — doc-updater lane, spec-adjacent files.
- [ ] 5.3 Demo 1 — the Phase 1 breakpoint demo, per the roadmap's demo convention: a runnable
      script at `scripts/demo/demo1_ledger_core.sh` (or `.py`) plus runbook
      `docs/runbooks/demo1-ledger-core.md`. Against LocalStack: a legal command commits and
      lands on the queue; an illegal command rejects with catalog reason + version; a replay
      returns the original event id (exactly one event); the independent fold equals
      `current_state` (wraps the 5.1 harness). Script exits nonzero on any failed assertion;
      receipt (script output) attaches to DNA-784 before archive. Not part of `task check`
      (needs LocalStack); a smoke-parse test may cover it.
      `[model: sonnet | deps: 5.1 | lane: repo_change | wave: 4]`
