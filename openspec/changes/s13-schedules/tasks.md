# Tasks — s13-schedules

Annotation format, read by `task dispatch` and checked by G_MECE:
`[model | deps | lane | wave]`, with `serial:` carrying its justification where set. `deps` names
task numbers in this file; `—` means no dependency. Linear ids get bracketed in after
`task linear:sync`. Default model is `sonnet`, stated explicitly on every task.

Every task ships its tests in the same commit (tests first per `AGENTS.md`). No live network in
any test (`--disable-socket`); the command API is faked at the `PulseCoreClient` boundary and the
ledger read at the `enumerate_state` boundary — this package owns no schema and needs no Postgres.
Fixtures are synthetic only (PHI rule) and ship with the task that consumes them.

---

## 1. Wave 0 — scaffold

- [ ] 1.1 Scaffold `packages/schedules` as a workspace member: pyproject, uv workspace root,
      ruff/pyright/pytest wiring, coverage floor 85, `--disable-socket` posture, `TESTED_PATHS`
      updated honestly, dependencies on `pulse-core` (client) and `pulse-ledger` (reads module).
      Test: package imports and an empty test module collects under `task check`.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0]`
      `serial: workspace_roots` — edits the root workspace manifest and `Taskfile.yml`.
      Declared scope must equal executed scope (the pulse-ledger-core 1.1 lesson).

## 2. Wave 1 — month-open

- [ ] 2.1 `schedules/month_open.py` core: enumerate active/on-hold Enrollments through the
      `pulse_ledger.reads.enumerate_state` boundary (never the warehouse), build one
      `open_billing_episode` per enrollment × current month with D16 keys, submit through the
      client boundary. Fixtures: recorded enumeration for the normal month. Tests: normal
      month-open declares exactly the active/on-hold set (spec: "Normal month-open"); an unknown
      state name fails the run via the catalog rejection with no commands declared (spec: "A
      state-name typo rejects the run").
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]`
- [ ] 2.2 Month-open re-runnability: `logical_time` = billing month (first-of-month date, no
      wall-clock component), so keys are stable within a month and roll with it. Fixtures: re-run
      and mid-month enumerations. Tests: same-day re-run classifies every declaration `replayed`
      with no second episode (spec: "Re-run replays"); a mid-month run replays existing episodes
      and opens only the newly activated enrollment's (spec: "Mid-month invocation").
      `[model: sonnet | deps: 2.1 | lane: repo_change | wave: 1]`
- [ ] 2.3 Month-open invariant and receipt: empty enumeration → failure receipt, nonzero exit,
      zero commands submitted; receipt reports opened/replayed/failed and any failed declaration
      makes the exit status nonzero (subject keys and counts only, never demographics). Fixtures:
      zero-enrollment case, mixed-outcome case. Tests: zero-enrollment failure (spec:
      "Zero-enrollment failure"); mixed-outcome receipt counts match and exit is nonzero (spec:
      "Receipt reflects the run").
      `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 1]`
      Depends on 2.2, not 2.1: both tasks edit `month_open.py`'s declare/receipt loop, so they
      serialize to avoid a same-wave merge conflict.

## 3. Wave 1 — consent sweep

- [ ] 3.1 `schedules/consent_sweep.py` parse and diff: suppression-export CSV parser
      (fixture-pinned format), set-based diff against ledger CommunicationConsent current state,
      corrections computed in both directions with Customer.io as authority (D9). Fixtures:
      exports with drift in each direction. Tests: opt-out present in export, missing from ledger
      → opt-out correction (spec: "Opt-out missing from the ledger"); ledger opt-out the export
      contradicts → opt-in correction (spec: "Ledger opt-out the export contradicts").
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]`
- [ ] 3.2 Correction declaration: `record_communication_consent` with actor = `reconciliation`
      (its own D15 credential, name from config, value from environment), payload provenance =
      export row reference (file id + row number), D16 `logical_time` = export as-of date. Test:
      a declared correction carries the actor and row reference, and re-running the sweep on the
      same export classifies it `replayed` (spec: "A correction is attributed and traceable").
      `[model: sonnet | deps: 3.1 | lane: repo_change | wave: 1]`
- [ ] 3.3 Drift receipt: agreements / corrections-by-direction / unparseable counts; malformed
      rows accumulate on the receipt with their parse errors and never abort the remaining rows;
      no raw contact values in receipts or logs. Fixtures: fully agreeing export; export with
      malformed rows among valid ones. Tests: full agreement declares nothing and the receipt
      shows all agreements (spec: "Agreements produce no writes"); malformed rows are counted and
      attached while valid rows process (spec: "Malformed rows are counted and attached").
      `[model: sonnet | deps: 3.2 | lane: repo_change | wave: 1]`
      Depends on 3.2, not 3.1: both tasks edit `consent_sweep.py`'s declare/receipt loop, so they
      serialize to avoid a same-wave merge conflict.

## 4. Wave 2 — CLI and dry-run

- [ ] 4.1 `schedules/cli.py`: one entrypoint, subcommands `month-open` and `consent-sweep`, exit
      status as the scheduler contract (nonzero on any failed run, invariant breach, or usage
      error). Tests: each subcommand drives its job through the faked boundaries; unknown
      subcommand and missing required argument exit nonzero with usage help (spec: "Subcommands
      are invocable").
      `[model: sonnet | deps: 2.2, 2.3, 3.2, 3.3 | lane: repo_change | wave: 2]`
- [ ] 4.2 `--dry-run` on both subcommands: build the full would-declare set (exercising key
      derivation and payload shape), print it, stop before the client — no API calls, no sockets.
      Must satisfy the work order's offline check:
      `uv run python -m schedules.cli month-open --dry-run --fixture packages/schedules/tests/fixtures/normal_month.json`.
      Test: dry-run under `--disable-socket` prints the would-declare set, exits zero, and the
      client fake records zero submissions (spec: "Dry-run declares nothing").
      `[model: sonnet | deps: 4.1 | lane: repo_change | wave: 2]`

## 5. Wave 3 — infra and runbooks

- [ ] 5.1 `packages/schedules/infra/` schedule definitions per the monorepo IaC convention
      (`packages/ocean/infra/terraform` pattern) and D14: month-open at 00:30 on the 1st with a
      same-day retry window, sweep daily, each trigger targeting its CLI subcommand. Config only —
      applying it is a deploy step outside this change. Test: a config assertion test parses the
      definitions and checks both cadences and their targets (spec: "Schedule definitions exist
      and match the cadence").
      `[model: sonnet | deps: 4.2 | lane: repo_change | wave: 3]`
- [ ] 5.2 Runbooks: `docs/runbooks/month-open.md` — the missed-month-open page procedure (billing
      incident severity per ops plan §1.5), the zero-enrollment failure meaning, the re-run
      posture, and the DNA-801 replay-accounting caveat; `docs/runbooks/consent-sweep.md` — the
      drift-spike procedure and the malformed-row triage. mkdocs nav entries; placeholders as
      inline code, never link syntax. Gate: `mkdocs build -s` green and the work order's
      `test -f` checks pass.
      `[model: sonnet | deps: 2.3, 3.3 | lane: repo_change | wave: 3]`
