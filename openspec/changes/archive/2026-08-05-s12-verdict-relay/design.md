# Design — s12-verdict-relay

## Context

See proposal.md — Why. Constraints that shape the design:

- S1.1 is merged and its names are pinned (`design/delivery/pulse-s1-work-orders.md`, shared
  context): `pulse_core.client.PulseCoreClient.submit_command` classifying
  `committed | replayed | rejected | transient`, `pulse_core.idempotency.derive_idempotency_key`
  (D16), `pulse_core.cursor` (`CURSOR_PATH_TEMPLATE`, `cursor_path(writer_id)`,
  `validate_cursor`; a writer may touch only its own credential's cursor), and the
  catalog-generated `declare_verdict` command type with the trinary outcome enum
  (`pulse_core.generated`).
- **Entry condition — DNA-801 gates EXECUTE/dispatch, not this proposal.** `pulse_ledger.api`
  currently rejects an `idempotency_key` body field as unknown and never echoes `replayed`, so
  `PulseCoreClient` classifies every replay as `committed` (the commit path
  `pulse_ledger.idempotency.commit_idempotent` supports both; see `docs/contracts/publishes.md`
  and ADR-0003 Consequences). The declarer's replay classification depends on that wiring, so
  this change SHALL NOT be dispatched for execution before DNA-801 lands. Planning artifacts are
  unaffected — nothing in the specs or tasks changes when it lands.
- Mart contract (fixture-pinned here, consumed contract in `docs/contracts/consumes.md`): one row
  per (subject, verdict_type, run); columns `subject_id, verdict_type, outcome, reason,
  rule_version, as_of, lineage_ref, computed_at`. The dbt side is the warehouse workstream.
- No live network in any test (`--disable-socket`); command API faked at the client boundary; no
  live Snowflake. Auth per D15: credential name in config, value from the environment.
- This supersedes the clinic-rules-engine Snowpark emitter (P5): verdicts reach the ledger through
  this relay on the single write path, not from inside Snowflake.

## Goals / Non-Goals

**Goals:**

- One resumable batch path where per-subject `as_of` ordering and D16 idempotency are structural —
  a rerun, a crash, or a shuffled mart can never double-declare or regress a subject's verdict.
- Every run accountable: five receipt counts, one machine-parsable summary line, subject keys only
  in logs.
- The package is inert infrastructure until scheduled — S1.3 owns triggering; this package exposes
  the entrypoint only.

**Non-Goals:**

- No verdict computation, no dbt models, no mart DDL — the mart is an input contract.
- No scheduling, no daemon, no service loop (S1.3).
- No projection of verdict flags into Twenty (S2).
- No new ledger-side behavior: `command-api`, `ledger-read`, and `ledger-record` are consumed
  as-is.

## Decisions

1. **Package layout:** `packages/verdict-relay`, workspace member per the monorepo template —
   `src/verdict_relay/{mart_reader.py, declarer.py, run.py}`, `tests/` with `fixtures/` (recorded
   mart rows, JSON, synthetic only). Toolchain: uv, ruff, pyright, pytest, coverage ≥ 85%, per
   this change's S1.2 work-order verification block. *Correction (drift review, 2026-08-05):* an
   earlier revision claimed this matched the S1.1 packages' posture; S1.1 actually runs mypy at an
   80% floor (PR #106), so pyright/85% is deliberately stricter here, not parity.
2. **The reader is source-abstracted:** `mart_reader` iterates a `RowSource` protocol yielding
   contract rows; the Snowflake implementation is a thin, config-driven adapter (connection
   parameters from the environment, D15 pattern), and every test drives the protocol with
   fixture-backed sources. *Alternative rejected:* mocking the Snowflake connector — couples tests
   to driver internals and violates the fake-at-the-boundary rule the S1.1 suites established.
3. **Stale detection is a cursor-carried watermark, not a ledger read-back.** The ordering rule
   needs each subject's latest declared `as_of`. S1.1's read surface has no per-subject verdict
   lookup (it exposes state enumeration, identity candidates, cursors, review queue), so the
   relay keeps a per-subject `as_of` high-water mark inside its writer cursor JSON, updated only
   after a committed or replayed declaration, persisted with the `computed_at` page cursor in one
   `PUT`. Values stay JSON-native (`validate_cursor`); the cursor is the relay's own
   (`cursor_path(writer_id)`), which D15 already scopes to its credential. *Alternative rejected:*
   adding a `GET /verdicts/latest` read to the ledger — a cross-package spec change S1.2 does not
   own, and the watermark is derivable from the relay's own committed history anyway. Crash
   between commit and cursor `PUT` re-declares at most one page, which D16 classifies as replays —
   correctness never depends on the watermark being fresh, only counts do.
4. **Retry policy lives in the declarer and keys off classification only:** transient → backoff
   (exponential, jittered), 5 attempts, then the run fails naming the row; rejected → never
   retried, counted, logged with the ledger's reason; replayed → counted, continue. The declarer
   never parses raw HTTP — classification is `pulse_core`'s contract (S1.1 design decision 6).
5. **Validation before submission:** contract-shape and trinary-outcome checks (indeterminate
   requires reason) run on the generated Pydantic command type before any client call, so an
   invalid row fails locally with no network attempt — this is what makes the
   indeterminate-without-reason fixture testable under `--disable-socket`.
6. **Receipt = structured logs, no new sink:** stdlib logging with a JSON formatter, every record
   tagged `service:verdict-relay`, one summary line with the five counts in `key=value` form
   (Datadog-parsable). Subject keys only; a lint-level test asserts no demographic field name ever
   reaches a log call. *Alternative rejected:* a receipt table in the ledger — the ledger records
   subject state, not writer telemetry, and Datadog is the operational surface per §1.5.
7. **Property test with hypothesis** (dev dependency, this package only): for any shuffled batch
   of runs per subject, declared order is `as_of`-monotonic per subject and stale rows are
   skipped — this is the one place a defect is expensive to retrofit, and it is also why the
   declarer task carries model `opus`.

## Risks / Trade-offs

- **[DNA-801 slips]** → the dispatch gate holds this change in planning; no partial execute where
  the declarer ships with replay-blind classification. The gate is recorded here, in proposal.md,
  and as the tasks.md preamble entry condition.
- **[Watermark map grows with subject count]** → JSON cursor carries one timestamp per subject
  ever declared; at PRM volume this is small, and the reader may compact entries older than the
  mart's retention horizon without correctness impact (D16 catches any resulting re-declare as a
  replay).
- **[Fixture-pinned mart drifts from the real dbt mart]** → the contract lands in
  `docs/contracts/consumes.md`; the warehouse workstream owns conformance, and the reader's
  contract validation fails fast and names the row on drift.
- **[Crash between commit and cursor persist inflates replay counts]** → accepted; correctness is
  D16's, and the runbook documents that a resumed run's `replayed` count includes the recovery
  overlap.
- **PHI**: mart rows carry subject keys and verdict fields, no demographics — but the mart is
  warehouse data, so fixtures are synthetic by construction, logs carry subject keys only, and any
  handler or logging edit gets the security-review pass the S1.1 change established.

## Migration Plan

Pre-production, additive: a new package with no consumers and no scheduler wiring (S1.3 triggers
it later). Deploy is a merge; rollback is reverting the package and the two doc notes
(`consumes.md` entry, P5 supersession). No data migration; an interrupted or reverted rollout
leaves only idempotent declarations the next run classifies as replays.
