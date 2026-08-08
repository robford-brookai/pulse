# Tasks — customerio-consent-ingress

Annotation format, read by `task dispatch` and checked by G_MECE:
`[model | deps | lane | wave]`, with `serial:` carrying its justification where set. `deps` names
task numbers in this file; `—` means no dependency. Linear ids get bracketed in after
`task linear:sync`. Default model is `sonnet`, stated explicitly on every task.

Every task ships its tests in the same commit (tests first per `AGENTS.md`). No live network in
any test (`--disable-socket`); the Snowflake read is faked at the `RowSource` boundary
(`mart_reader`'s pattern) and the command API is faked at the `PulseCoreClient` boundary
(`consent_sweep`'s pattern) — this package owns no schema and needs no live Snowflake connection.
Fixtures are synthetic only (PHI rule: subject keys and channel names, never contact values) and
ship with the task that consumes them.

---

## 1. Wave 0 — scaffold

- [x] 1.1 [DNA-890] Scaffold `packages/consent-ingress` as a workspace member: pyproject, uv
      workspace root, ruff/pyright/pytest wiring, coverage floor 85, `--disable-socket` posture,
      `TESTED_PATHS` updated honestly, dependencies on `pulse-core` (client, cursor, generated)
      only — no dependency on `pulse-ledger` or `schedules` (design decision 3: the grain
      composition is duplicated, not imported).
      Test: package imports and an empty test module collects under `task check`.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0]`
      `serial: workspace_roots` — edits the root workspace manifest and `Taskfile.yml`.
      Declared scope must equal executed scope (the pulse-ledger-core 1.1 lesson).

## 2. Wave 1 — reader

- [x] 2.1 [DNA-891] `consent_ingress/row_source.py`: `RowSource` protocol reading
      `streamline.cio_raw`/`cio_prod` landing rows, pinned `CONTRACT_COLUMNS` (`subject_key`,
      `channel`, `to_state`, a message/event id, an orderable event timestamp), per-row contract
      validation with `consent_sweep.parse_export`'s catch-and-collect shape (a malformed row
      becomes a counted `RowError` naming row position and column — never a contact value — and
      never aborts the page; corrected at G_MECE from the mart_reader raise-and-abort citation,
      which contradicts Requirement 5), and cursor-based paging through `pulse_core.cursor`
      (`cursor_path`/`validate_cursor`), scoped to this ingress's own writer id.
      `FixtureRowSource` is the only source every test drives.
      Fixtures: a normal page, a page split across a cursor boundary, a page with malformed rows
      among valid ones.
      Tests: a fixture-backed read under `--disable-socket` yields validated rows with no live
      connection attempted (spec: "The test suite runs with no live network"); malformed rows
      are collected as errors while valid rows in the same page still yield, and a caplog +
      error-message scan finds no fixture contact value in any row error (the PHI exit this
      module owns).
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]`

## 3. Wave 1 — declaration

- [x] 3.1 [DNA-892] `consent_ingress/declarer.py` core: compose the ledger subject key as
      `f"{subject_key}:{channel}"` — the exact composition `consent-reconciliation`'s sweep uses
      (binding, `openspec/specs/consent-reconciliation`) — build one
      `RecordCommunicationConsentCommand` per validated row, payload carrying the source row's
      message/event id as provenance, submitted through a `PulseCoreClient` authenticated with
      this ingress's own `customer.io` D15 credential (name in config, value from the
      environment) so the ledger resolves every command's actor to `customer.io` by
      authentication alone (ADR-0003) — this module writes no actor field anywhere.
      Fixtures: rows for two distinct (subject, channel) pairs.
      Tests: a landed row becomes exactly one `record_communication_consent` command with no
      other write path used (spec: "A landed row becomes a command"); the submitted command
      carries the row's message/event id and is authenticated under the `customer.io` credential
      (spec: "A declared command is customer.io-attributed and traceable"); the composed subject
      key for a given (subject, channel) pair matches the key `consent-reconciliation`'s own
      composition function would produce for the same pair (spec: "Ingress and sweep address the
      same row identically").
      `[model: opus | deps: 2.1 | lane: repo_change | wave: 1]`
      Opus: the grain/idempotency declarer core — a composition or key-derivation mistake here
      would silently diverge from the sweep's own state or double-declare consent, and is
      retrofit-expensive to catch after either path ships against it.

- [x] 3.2 [DNA-893] D16 idempotency: derive `logical_time` from the row's own event identity (its
      event timestamp, the same field the cursor pages on) rather than wall-clock read time, so
      `derive_idempotency_key`'s payload hash reproduces identically whenever the same row is
      re-read. Wire this into both re-read paths: a cursor resume that re-fetches its last
      uncommitted page, and a full re-run over a landing with no new rows since.
      Fixtures: a page re-read after a simulated crash before cursor commit; a full second run
      over the same landing with no new rows.
      Tests: a cursor-resume re-read classifies every affected command `replayed` with no consent
      state double-declared (spec: "A cursor resume replays its last page"); a full re-run over
      the same landing classifies every command `replayed` (spec: "A full re-run over the same
      landing replays").
      `[model: sonnet | deps: 3.1 | lane: repo_change | wave: 1]`
      Depends on 3.1, not 2.1: both 3.1 and 3.2 edit `declarer.py`'s command-build path, so they
      serialize to avoid a same-wave merge conflict.

- [ ] 3.3 [DNA-TBD] Run receipt and no-PHI logging: tally declared/replayed/rejected counts and
      malformed-row counts, malformed rows attached to the receipt by row reference (page offset
      plus identifying contract columns) rather than dropped; every receipt and log line carries
      subject keys and channel names only, asserted directly by test — never a contact value
      from `cio_raw`/`cio_prod`.
      Fixtures: a page containing malformed rows among valid ones; a row carrying a synthetic
      contact-identifier-shaped field to prove it never reaches the receipt.
      Tests: a malformed row among valid ones is counted, attached, and does not abort the
      remaining rows (spec: "A malformed row among valid ones"); a run receipt over rows with
      contact identifiers contains no contact value in the receipt or any log line the run
      produced (spec: "A run receipt is safe to attach to logs").
      `[model: sonnet | deps: 3.2 | lane: repo_change | wave: 1]`
      Depends on 3.2, not 3.1: 3.2 and 3.3 both edit `declarer.py`'s declare/receipt loop, so
      they serialize to avoid a same-wave merge conflict.

## 4. Wave 2 — CLI

- [ ] 4.1 [DNA-TBD] `consent_ingress/cli.py`: one entrypoint, `--dry-run` builds the full
      would-declare set from a fixture `RowSource` (exercising key derivation and payload shape)
      and prints it, stopping before the client — no API calls, no sockets — mirroring
      `schedules`/`verdict-relay`'s dry-run shape. Exit status is nonzero on any invariant breach
      or failed declaration, the scheduler contract precedent `schedules.cli` already sets.
      Test: `--dry-run` under `--disable-socket` prints the would-declare set, exits zero, and
      the client fake records zero submissions.
      `[model: sonnet | deps: 3.3 | lane: repo_change | wave: 2]`

## 5. Wave 2 — contract doc

- [ ] 5.1 [DNA-TBD] Register `streamline.cio_raw`/`cio_prod` in `docs/contracts/consumes.md`: a
      new entry naming the pinned row contract (`CONTRACT_COLUMNS` from task 2.1) this ingress
      validates against, alongside the existing verdict-mart entry's format, and cross-linking
      ADR-0005 as the source of the export mechanism.
      Test: `mkdocs build -s` stays green; a doc-presence test asserts the entry names both
      schemas and the pinned column list.
      `[model: sonnet | deps: 2.1 | lane: repo_change | wave: 2]`
      `serial: openspec_main_specs` — doc-updater lane: `docs/contracts/consumes.md` is a
      single shared file every consumer-registering change edits; this task owns the edit for
      this change.
