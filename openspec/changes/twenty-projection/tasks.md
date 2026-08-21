# Tasks — twenty-projection

Annotation format, read by `task dispatch` and checked by G_MECE:
`[model | deps | lane | wave]`, with `serial:` carrying its justification where set. `deps`
names task numbers in this file; `—` means no dependency. Linear ids get bracketed in after
`task linear:sync`. Default model is `sonnet`, stated explicitly on every task.

Every task ships its tests in the same commit (tests first per `AGENTS.md`). `task check` stays
green, offline and credential-free at every step — every consumer/writer test runs under
`--disable-socket` with fixture transports on both the queue and REST sides. Synthetic data
only; no PHI in fixtures, logs, receipts, or golden files. Specs are owned by the doc-updater:
write proposed spec changes to `HANDOFF.md`, never edit `openspec/specs/`.

**Live wave gate.** Wave 3 touches the dev instance and the served command API. Both exist
(twenty-dev-instance archived 2026-08-18); the gate is execution discipline, not provisioning:
4.1 is `operational_discovery` and runs from the operator queue with a G_APPROVAL comment,
never a worktree.

---

## 1. Wave 0 — model and scaffold

- [x] 1.1 Scaffold `packages/twenty-projection` as a workspace member: package layout
      (`src/twenty_projection/`, `tests/`), pyproject wired into the uv workspace, a
      placeholder test collecting under `task check`, and Taskfile target
      `projection:consume` requiring `TARGET` (credentialed, out of `check` — the reachability
      test asserts it, same posture as `twenty:deploy`).
      Test: placeholder collects and passes; `task check` green and unchanged otherwise;
      reachability test extended.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0]`
      `serial: workspace_roots` — edits `Taskfile.yml` and root workspace config.

- [x] 1.2 Watermark field in the model: add `projectionSeq` (NUMBER, nullable — null means
      never projected) to `patientProgram` in `pulse_core.twenty_model`, mint its UID into
      `uid-map.json`, regenerate `generated/` and the artifact. No SELECT options change; the
      encoding bijectivity gate and golden files re-render.
      Tests: golden files updated; UID-map completeness green (no orphans, no missing);
      byte-identical double-render; artifact validation green in `task check`.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0]`
      `serial: catalog_generated_surfaces` — regenerates the generated surfaces and the
      artifact; the standing serial lane owns this file pair.

## 2. Wave 1 — the consumer and the seam

- [x] 2.1 Projection apply core, `twenty_projection.apply` — the write path only: given a
      committed enrollment event and a REST transport, resolve the subject to its board record
      (canonical identifiers, never guessed — the denormalized
      `canonicalPatientId`/`programCode` columns), enforce the monotonic watermark guard
      (`ledger_seq` at or below `projectionSeq` is a logged no-op), and write the full board
      state — encoded status, as-of from the event's effective time, watermark — in one PATCH.
      Unresolvable-subject and failure-path handling is task 2.2's scope; here they raise
      typed errors only.
      Tests (fixture transport): apply writes all three fields encoded; at-watermark and
      below-watermark no-op without a write (spec: "A late event never regresses the board");
      per-subject watermarks (spec: "Watermarks are per subject"); drift converges (spec:
      "Drift converges on the next event").
      `[model: opus | deps: 1.2 | lane: repo_change | wave: 1]`
      Opus: the monotonic-apply and full-state-write semantics are the projection's whole
      correctness story; a wrong guard silently corrupts board state and only surfaces at
      reconciliation.

- [x] 2.2 Orphan parking and payload-free failure handling around the apply core: an
      unresolvable subject parks with a counted metric and an identifiers-only log line; a
      failed REST write retries then surfaces with no payload content in any log or metric.
      Tests: orphan parks without crashing or blocking (spec: "An orphan event parks
      cleanly"); failure logging carries no payload value against a scripted body containing
      a synthetic record value (spec: "A failed write logs no payload").
      `[model: sonnet | deps: 2.1 | lane: repo_change | wave: 1]`

- [x] 2.3 Consumer loop, `twenty_projection.consumer` + `task projection:consume TARGET=dev`:
      wire `pulse_core.consume` (event-id dedupe, delete-after-success) to the apply core,
      filter to board-relevant event subjects, resolve env
      (`PULSE_TWENTY_<TARGET>_URL/_TOKEN`, `SQS_QUEUE_URL`) with named startup errors, no
      ledger DSN or writer token anywhere in the package.
      Tests: fixture queue drives apply; delete only after success (spec: "An event applies
      from the queue alone"); duplicate delivery deduped (spec: "A redelivered message applies
      nothing twice"); no ledger driver import and no ledger env var read (spec: "The
      projection holds no ledger credential"); a missing env var fails startup by name.
      `[model: sonnet | deps: 2.1, 2.2 | lane: repo_change | wave: 1]`

- [x] 2.4 Echo suppression in the drag mapping: `NoOp("echo_of_record")` when the payload's
      target state equals the state of record (encoded comparison), added to
      `pulse_ledger.twenty.mapping` and threaded through the route's disposition log.
      Tests: echo yields noop with the new reason and posts nothing (spec: "An echo of the
      state of record is a noop"); a genuine drag to a *different* state still maps to exactly
      one command (regression pin); the disposition vocabulary doc line updated.
      `[model: sonnet | deps: — | lane: repo_change | wave: 1]`

## 3. Wave 2 — heal-back and wiring

- [x] 3.1 Heal-back on rejection: on a `rejected` disposition, the webhook route restores the
      card's status field to the state of record through the projection writer — synchronous
      best-effort, attributed to the projection identity, degrading exactly like the rejection
      note (failure logs the card ref only, receipt always returned). The echo-loop
      integration proof is task 3.2's scope.
      Tests (scripted transports): rejection triggers one heal PATCH carrying the encoded
      state of record (spec: "The card snaps back after an illegal drag"); heal failure never
      loses the receipt or blocks the response (spec: "A broken heal channel still rejects
      cleanly").
      `[model: opus | deps: 2.1, 2.4 | lane: repo_change | wave: 2]`
      Opus: the heal write sits inside the webhook response path; a blocking or throwing heal
      breaks rejection correctness, the one property the route must never lose.

- [x] 3.2 Echo-loop termination proof: an integration test driving the full bounce — heal
      write fires the `.updated` webhook payload back through signature verification and the
      mapping — asserting the loop terminates in one bounce with no command, no note, and no
      second heal.
      Tests: the heal's own webhook echo terminates as `echo_of_record` (spec: "A heal write's
      echo is a noop"); a counter proves exactly one heal PATCH per rejection across the
      bounce.
      `[model: opus | deps: 2.4, 3.1 | lane: repo_change | wave: 2]`
      Opus: the heal/echo interaction is a feedback loop through a live webhook; getting the
      termination guarantee wrong spams every rejected card with notes forever.

- [x] 3.3 Contracts and docs: `docs/contracts/publishes.md` gains the projection's consumed
      queue + written surface row; `docs/runbooks/twenty-webhook.md` §Heal-back boundary
      rewritten from "expected until the heal-back write ships" to the shipped behavior;
      `docs/runbooks/twenty-projection.md` (new) covers running the consumer, the watermark
      semantics, orphan triage, and rollback (stop the consumer); `mkdocs.yml` nav entry.
      Tests: `mkdocs build -s` green; the doc-presence gate names the runbook and the
      publishes row.
      `[model: sonnet | deps: 2.3, 3.2 | lane: repo_change | wave: 2]`
      `serial: openspec_main_specs` — this task owns both single shared files every
      registering change edits: `docs/contracts/publishes.md` AND the root `mkdocs.yml` nav.
      Neither may be edited by a parallel task in any concurrently open change.

## 4. Wave 3 — live verification (operator lane)

- [x] 4.1 Live heal-back verification on dev (**narrowed** — see 4.2/4.3 for what moved out):
      re-apply the artifact (watermark field lands, idempotent read-back), then drag a card
      illegally and watch it snap back within the D17 budget with a rejection note and a
      terminated echo. Receipt (identifiers, states, timings — no payload values) on the
      tracking issue.
      **Done 2026-08-20, receipts on issue #252**: artifact read-back `ok: true` / 0 missing /
      re-apply all no-ops; card `392dae45` rejected `pending_start -> on_hold` at
      `catalog_version 1.1.0`, healed back in **0.37 s**, and the heal write's own webhook
      returned from the live Twenty server as `disposition=noop reason=echo_of_record` — the
      loop-termination guarantee (2.4/3.2) holding against real software.
      Legs (a) convergence and (c) drift moved to **4.2**: dev has no `ocean` bus, no
      projection queue, and no outbox relay deployment, so the consumer has nothing to consume.
      The automated receipt moved to **4.3**: demo3's steps 7–8 are obsolete now that Twenty's
      real webhook commits first and echo suppression answers the demo's own delivery `noop`.
      `[model: sonnet | deps: 1.1, 3.2, 3.3 | lane: operational_discovery | wave: 3]`
      Gate: G_APPROVAL comment from Rob on the tracking issue (given); operator queue, never a
      worktree.

- [ ] 4.2 Provision the ledger's distribution path on dev, then finish 4.1's deferred legs.
      Discovered by 4.1: `pulse-ledger-api` is the tenant's only pulse workload — there is no
      outbox relay deployment, no `ocean` EventBridge bus (only `default`), and no projection
      SQS queue, so no committed event ever reaches a consumer. Provision, in this order: the
      relay as a second deployment off the same image (`python -m pulse_ledger.relay_worker`,
      the Dockerfile's documented second command) with `DATABASE_URL` and
      `OCEAN_EVENT_BUS_NAME`; the `ocean` bus; a rule matching `source = "ocean"` targeting a
      new projection queue; and the queue's access policy. Then run
      `task projection:consume TARGET=dev` and close 4.1's remaining legs: (a) drive a
      committed event and watch status, as-of, and watermark converge, and (c) inject
      out-of-band drift and watch it converge on the subject's next event, both inside the
      ADR-0004 D17 budget.
      Verify: relay lag gauge visible; a committed event observed converging end to end; the
      receipt (ids, states, sequences, timings) on the tracking issue.
      `[model: sonnet | deps: 4.1 | lane: destructive_ops | wave: 4]`
      Gate: G_APPROVAL — provisions tenant infrastructure; operator queue, never a worktree.

- [ ] 4.3 Rework demo3's steps 7–8 for the live-webhook world. 4.1 found the demo systemically
      broken rather than card-diverged (reproduced on a fresh `--card-index`): the script
      PATCHes the card and then delivers the webhook body itself, but with Twenty's real
      webhook live **Twenty's delivery commits first**, and echo suppression (task 2.4) answers
      the script's own delivery `noop reason=echo_of_record` where it used to answer `replayed`.
      Step 8 compounds it — the replay proof needs an `event_id` only the committing delivery
      returns, and that delivery is now Twenty's, whose response the demo never sees.
      Rework so the demo asserts the same two properties against the real path: the drag's
      `effective_at` equals the record's own stamp (not the wall clock), and a redelivery
      produces no second event. Options the task should weigh and record: read the committed
      event id back from a disposition receipt rather than the delivery response; or drive the
      drag through Twenty only and assert via a follow-up delivery that must answer `replayed`.
      Accepting `echo_of_record` as a pass is NOT acceptable — it would assert nothing.
      Tests: the smoke-parse contract still holds; new unit coverage for whichever discovery
      path is chosen, offline against fixture transports.
      `[model: opus | deps: — | lane: repo_change | wave: 4]`
      Opus: the demo is the change's own acceptance instrument — an assertion that passes
      without proving the property is worse than a failing one.
