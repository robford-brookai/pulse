# Connector template — Tier 1 gap analysis (the first five minutes)

**Programme**: connector-template (`pricing-engine` as the reference Pulse API connector)
**Tier**: 1 of 3 — what an engineer judges before reading any prose
**Repository**: `/Users/Rob.Ford/orca/workspaces/pulse/betta`
**Date**: 2026-08-21
**Lane**: analysis only; nothing in this report was implemented

## Summary of the four verdicts

| Item | Verdict | Level of effort |
|---|---|---|
| 1.1 Runs in one command, offline, no credentials | The ingredients all exist; no runnable demo exists, and no reusable fake command API exists outside test files | `M` |
| 1.2 Tests that double as the specification | Already exemplary; the convention is established but unenforced and undocumented | `S` |
| 1.3 Full annotations under a strict checker in CI | Already exemplary for a new package; wiring a package into both checkers touches five places and no gate pins them for a non-`pulse-*` package | `S` |
| 1.4 Visible error taxonomy | Classification is centralised and reusable; **retry policy and disposition accounting are re-implemented per connector** | `M` |

The single most consequential finding is in Item 1.4: `pulse_core.client` owns the four-way
classification, but it does **not** own the retry loop, the backoff schedule, the attempt budget,
or the per-outcome counting. Every existing declarer re-implements those, and the two
implementations in the repository already disagree on the attempt budget
(`packages/pulse-core/src/pulse_core/client.py:52` says 4;
`packages/verdict-relay/src/verdict_relay/declarer.py:70` says 5, and deliberately pins the client
to `max_attempts=1` at `packages/verdict-relay/src/verdict_relay/declarer.py:158` so the two do not
multiply). Eleven connectors copying this shape will produce eleven retry policies.

The second most consequential finding is in Item 1.1: there is **no** demo, example-run, or
`pricing-engine` target anywhere in `Taskfile.yml`, and the in-process fake of the command API
exists only as `httpx.MockTransport` handler classes defined inside test modules — no `src/` tree in
the repository ships one. A demo therefore cannot be assembled purely by wiring existing exported
code; a small new module has to exist for it.

---

## Item 1.1 — Runs in one command, offline, with no credentials

### Current state

**No demo or example-run target exists.** `Taskfile.yml` was read in full (528 lines). The string
`demo` does not appear anywhere in it, and no target named `demo`, `example`, `example:run`,
`pricing:demo`, or anything similar is defined. The complete target list, in file order, is:
`default` (`Taskfile.yml:49`), `new-repo` (`Taskfile.yml:57`), `install` (`Taskfile.yml:77`),
`mcp:check` (`Taskfile.yml:82`), `fmt` (`Taskfile.yml:98`), `lint` (`Taskfile.yml:104`),
`twenty:gen` (`Taskfile.yml:110`), `typecheck` (`Taskfile.yml:119`), `test` (`Taskfile.yml:137`),
`test:services` (`Taskfile.yml:151`), `test:all` (`Taskfile.yml:170`), `test:integration`
(`Taskfile.yml:175`), `twenty:test` (`Taskfile.yml:180`), `twenty:validate`
(`Taskfile.yml:195`), `catalog:release` (`Taskfile.yml:205`), `synthea:regen`
(`Taskfile.yml:215`), `twenty:deploy` (`Taskfile.yml:227`), `twenty:verify`
(`Taskfile.yml:239`), `twenty:verify:live` (`Taskfile.yml:251`), `twenty:seed`
(`Taskfile.yml:270`), `twenty:app:build` (`Taskfile.yml:283`), `twenty:app:publish`
(`Taskfile.yml:301`), `ledger:image` (`Taskfile.yml:318`), `ledger:migrate`
(`Taskfile.yml:332`), `ledger:deploy` (`Taskfile.yml:341`), `projection:consume`
(`Taskfile.yml:351`), `relay:run` (`Taskfile.yml:362`), `check` (`Taskfile.yml:388`),
`pre-commit` (`Taskfile.yml:400`), `verify` (`Taskfile.yml:405`), `docs` (`Taskfile.yml:415`),
`docs:build` (`Taskfile.yml:420`), `docs:lock-guard` (`Taskfile.yml:425`), `spec:archive`
(`Taskfile.yml:437`), `spec:init` (`Taskfile.yml:443`), `spec:status` (`Taskfile.yml:448`),
`spec:validate` (`Taskfile.yml:453`), `lore:analyze` (`Taskfile.yml:460`), `lore:drift`
(`Taskfile.yml:465`), `lore:mcp` (`Taskfile.yml:470`), `collect` (`Taskfile.yml:478`),
`dispatch` (`Taskfile.yml:483`), `linear:sync` (`Taskfile.yml:488`), `workflow:lint`
(`Taskfile.yml:495`), `workflow:lint:linear` (`Taskfile.yml:500`), `workflow:show`
(`Taskfile.yml:505`), `sync-docs` (`Taskfile.yml:510`), `template:diff` (`Taskfile.yml:520`),
`template:sync` (`Taskfile.yml:525`).

`task check` is confirmed as the offline, credential-free contract: it runs exactly `lint`,
`typecheck`, `test`, `twenty:validate`, `twenty:test`, `workflow:lint`, `docs:lock-guard`, and
`docs:build` (`Taskfile.yml:388-398`), and `.github/workflows/main.yml:50` runs literally
`task check`. The credentialed targets are excluded by construction and each carries a comment
saying so — `relay:run` at `Taskfile.yml:375-377`, `ledger:deploy` at `Taskfile.yml:344-345`,
`catalog:release` at `Taskfile.yml:210-211`, `twenty:deploy` at `Taskfile.yml:244-245`.

**What already exists that a demo could stand on:**

1. **A committed, named fixture corpus.** `packages/verdict-relay/tests/fixtures/` holds nine
   tracked JSON recordings (confirmed tracked with `git ls-files packages/verdict-relay/tests/fixtures`):
   `benefits_verification_verifies.json`, `billing_eligibility_qualifies.json`,
   `coverage_eligibility_verifies.json`, `idempotent_replay.json`,
   `illegal_transition_rejection.json`, `indeterminate_with_reason.json`,
   `indeterminate_without_reason.json`, `normal_declare.json`, `out_of_order_stale_run.json`.
   Each recording carries the mart rows, the pre-existing watermarks, the scripted API
   classifications, and the expected receipt counts
   (`packages/verdict-relay/tests/test_fixture_corpus.py:1-19`), and each carries a human-readable
   `description` field — for example `packages/verdict-relay/tests/fixtures/illegal_transition_rejection.json`
   reads `"A declaration the ledger rejects as an illegal transition: counted and logged with the
   ledger's reason and catalog version, never retried, and the run continues."`
2. **A fixture row source in `src/`, not in tests.** `verdict_relay.mart_reader.FixtureRowSource`
   is defined at `packages/verdict-relay/src/verdict_relay/mart_reader.py:118`, and
   `consent_ingress.row_source.FixtureRowSource` at
   `packages/consent-ingress/src/consent_ingress/row_source.py:139`. Both are shipped code, not
   test helpers.
3. **A precedent for a one-command offline run.** `consent_ingress.cli` takes a required
   `--landing-fixture <path>` argument (`packages/consent-ingress/src/consent_ingress/cli.py:190-197`)
   and a `--dry-run` flag documented as "Print the would-declare set and exit; no ledger connection,
   no API call, no socket." (`packages/consent-ingress/src/consent_ingress/cli.py:198-202`). The dry
   run uses a `_NullCursorStore` so it never speaks to the ledger's writer-state route either
   (`packages/consent-ingress/src/consent_ingress/cli.py:80-88`). It prints one line of JSON
   (`packages/consent-ingress/src/consent_ingress/cli.py:93`) and always exits zero
   (`packages/consent-ingress/src/consent_ingress/cli.py:123-131`). It is **not** exposed as a
   `Taskfile.yml` target: the string `consent` appears in `Taskfile.yml` only inside the path-list
   variables and comments (`Taskfile.yml:19`, `Taskfile.yml:23`, `Taskfile.yml:31`,
   `Taskfile.yml:41`, `Taskfile.yml:44`, `Taskfile.yml:120`, `Taskfile.yml:123`,
   `Taskfile.yml:131`, `Taskfile.yml:141`, `Taskfile.yml:148`).
4. **A machine-parsable receipt line.** `verdict_relay.run.RunReceipt.summary_line()`
   (`packages/verdict-relay/src/verdict_relay/run.py:92-100`) emits one space-separated
   `key=value` line: `service=<name> result=<success|failure> declared=<n> replayed=<n>
   skipped_stale=<n> rejected=<n> transitioned=<n> transition_rejected=<n> failed=<n>`.
   The scheduled poll prints the receipt as JSON instead
   (`packages/schedules/src/schedules/verdict_relay_poll.py:35`).

**What does not exist:** a fake of the command API that lives outside a test module. Every
in-process fake is an `httpx.MockTransport` handler class defined inside a test file — for example
`ScriptedApi` at `packages/verdict-relay/tests/test_config.py:50` and
`packages/verdict-relay/tests/test_declarer.py:81`, and the `_fake_ledger` helpers at
`packages/verdict-relay/tests/test_mart_reader.py:264-292` and
`packages/consent-ingress/tests/test_row_source.py:286-314`. Searching for `MockTransport` across
`packages/` returns matches in eleven test modules plus two `src/` docstrings that merely *mention*
the pattern (`packages/verdict-relay/src/verdict_relay/mart_reader.py:150`,
`packages/consent-ingress/src/consent_ingress/row_source.py:172`). The transport seam itself is a
real constructor parameter on shipped code — `PulseCoreClient.__init__(..., transport:
httpx.BaseTransport | None = None, ...)` at
`packages/pulse-core/src/pulse_core/client.py:243` — so nothing prevents a shipped fake; there just
is not one.

**The Docker-dependent options, stated explicitly:**

- `packages/ocean/infra/docker-compose.yml` exists (18,713 bytes) and defines 24 services,
  including `localstack`, `localstack-init`, `ledger-postgres`, `ledger-migrate`, `ledger-relay`,
  `postgres`, `migrate`, `hasura`, `event-store`, and `hasura-init`. **Requires a running Docker
  daemon.**
- `task test:integration` (`Taskfile.yml:175-178`) runs `uv run pytest {{.TESTED_PATHS}}
  --import-mode=importlib -m integration`, and the `integration` marker is documented as "needs
  Docker, excluded from the default run" (`pyproject.toml:118-124`, and the Taskfile comment at
  `Taskfile.yml:27-29`). **Requires Docker.**
- `task ledger:image` (`Taskfile.yml:318-330`) runs `docker buildx build`. **Requires Docker.**
- A real local Postgres for the ledger requires `task ledger:migrate` (`Taskfile.yml:332-339`),
  which the target itself describes as needing "a real Postgres". **Requires either Docker or a
  locally installed Postgres.**
- The `httpx.MockTransport` in-process fake and the `FixtureRowSource` path require **no Docker and
  no network at all** — `packages/verdict-relay/tests/conftest.py` blocks sockets for every run that
  collects the package (`packages/verdict-relay/pyproject.toml:26-28` pins `pytest-socket` as the
  dev dependency that enforces it), and the suite passes under that block.

### Gap

There is no single documented command an engineer can run after `git clone` that makes a connector
do visible work. The two candidate paths both fall short: `task check` runs the whole repository's
gates and prints thousands of lines of pytest and coverage output rather than a connector receipt,
and `python -m consent_ingress.cli --landing-fixture <path> --dry-run` never touches the command API
at all, so it demonstrates key derivation but not the committed/replayed/rejected/transient
behaviour that is the point. Closing the gap needs two things that do not exist: a fake command API
in a shipped module rather than in a test file, and a `Taskfile.yml` target that runs the connector
against it and prints a short receipt.

### Options

**Option A — an in-process fake command API shipped in `packages/pricing-engine/src/pricing_engine/`,
driven by a committed scenario file, exposed as `task pricing:demo`.**
What it does: add one module (working name `packages/pricing-engine/src/pricing_engine/fake_api.py`)
holding an `httpx.MockTransport` handler that answers `POST /commands` from a scripted list of
classifications, exactly the `ScriptedApi` shape already proven at
`packages/verdict-relay/tests/test_config.py:50`; add a committed scenario file under
`packages/pricing-engine/demo/` in the recording format already established at
`packages/verdict-relay/tests/fixtures/`; add a `Taskfile.yml` target
`pricing:demo` whose single command is `uv run python -m pricing_engine.demo`.
What it costs: one new module, one committed scenario file, one Taskfile target, and the tests that
cover them (the module counts toward the package's coverage floor, so it must be tested, not merely
shipped).
What it gives up: nothing structural. The fake is production-shaped rather than production code, so
it must be unambiguously named and documented as a fake, or a reader may mistake it for a client
configuration.

**Option B — reuse `task test:integration` and the LocalStack stack at
`packages/ocean/infra/docker-compose.yml`.**
What it does: bring up `localstack`, `ledger-postgres`, `ledger-migrate`, and `ledger-relay`, run
the connector against a real API over a real database, and show a real committed event.
What it costs: a Docker daemon, an `docker compose up` of at least four services, Alembic migrations
via `task ledger:migrate` (`Taskfile.yml:332-339`), and minutes of first-run image pulls.
What it gives up: the "no Docker" property, which is the property that makes the claim credible. It
also gives up determinism — an engineer whose Docker is not running sees an infrastructure error, not
a connector, which is the exact outcome the demo exists to avoid.

**Option C — extend `consent_ingress.cli`'s `--dry-run` posture to `pricing-engine` and stop there.**
What it does: reuse the proven pattern at `packages/consent-ingress/src/consent_ingress/cli.py:104-131`
verbatim — read a fixture, build the would-declare set, print JSON, exit zero.
What it costs: least of the three; one CLI module and one committed fixture.
What it gives up: the demo never calls the command API, so it cannot show any of the four
classifications. Item 1.4 is the template's main teaching job, and this option makes it
undemonstrable in the first five minutes.

### Recommendation

Option A. It is the only option that satisfies both halves of the claim — real command-API
interaction *and* no Docker, no credentials, no network — and the pattern it generalises is already
proven inside eleven test modules, so nothing about it is novel. Option C should be added *as well*,
because a `--dry-run` flag costs almost nothing once the CLI exists, but it cannot substitute for
Option A.

### Level of effort

`M` — one new module plus a committed scenario file plus a `Taskfile.yml` target, with tests written
first because the module lands inside a coverage-floored package.

### Dependencies and risks

Depends on `packages/pricing-engine/` existing as a workspace member first (see Item 1.3 for the
five places that must be edited), so it cannot start before that wiring lands. It also touches
`Taskfile.yml`, which is a shared serial file — any concurrent work adding a target must sequence
around it.

The risk that makes this harder than it looks: `task check`'s runner collects `tests/` and the
per-package test directories listed in `TESTED_PATHS` (`Taskfile.yml:31`), and
`pyproject.toml:126` sets `python_files = ["test_*.py", "cat[0-9]_*.py"]`. A demo module placed
under a path pytest collects, or named to match those patterns, will be executed as part of
`task check` and will either slow it down or fail it. Place the demo under
`packages/pricing-engine/src/pricing_engine/` and its scenario file under
`packages/pricing-engine/demo/`, never under `packages/pricing-engine/tests/`.

If this item fails silently, doubt the socket-blocking assumption first. `pytest-socket` blocks
sockets for the *test* run (`packages/verdict-relay/pyproject.toml:26-28`); it does not run when
`task pricing:demo` invokes the module directly. A demo that accidentally constructs a real
`httpx.Client` — that is, forgets to pass `transport=` — will attempt a real network call and the
absence of a socket block means it will fail with a connection error on a developer machine and may
*succeed* on a machine that happens to have something listening. Assert in the demo's own test that
the client was constructed with a non-`None` `transport`.

Pass criteria for this item: `task pricing:demo` exits 0 on a machine with no Docker daemon
running, with no `PULSE_*` environment variable set, and with networking disabled; its complete
standard output is at most 20 lines; and those lines name each of the four classifications
`committed`, `replayed`, `rejected`, and `transient` at least once.

---

## Item 1.2 — Tests that double as the specification

### Current state

**Test naming is already behavioural, consistently, across every package sampled.** This is a
strength, not a gap.

`packages/verdict-relay/tests/test_declarer.py` groups behaviours into named scenario classes and
names each test as a sentence about behaviour:

- `class TestReplayScenario` (`packages/verdict-relay/tests/test_declarer.py:128`) containing
  `test_replay_counts_and_never_redeclares` (line 131) and
  `test_replay_advances_the_watermark_like_a_commit` (line 142).
- `class TestRejectionScenario` (line 149) containing
  `test_rejection_counts_logs_the_reason_and_never_retries` (line 152) and
  `test_rejection_does_not_advance_the_watermark` (line 169).
- `class TestTransientScenario` (line 176) containing
  `test_transient_exhausts_five_attempts_and_names_the_row` (line 179),
  `test_backoff_is_exponential_and_jitter_scaled` (line 193), and
  `test_transient_then_commit_recovers_within_the_attempt_budget` (line 204).
- `class TestPairedTransition` (line 367) containing, among others,
  `test_a_committed_verdict_pairs_a_committed_transition` (line 370),
  `test_the_pair_is_idempotent_as_a_unit` (line 408),
  `test_an_interrupted_pair_completes_on_resume` (line 426), and
  `test_a_rejected_transition_keeps_the_verdict_and_never_retries` (line 449).

`packages/verdict-relay/tests/test_config.py` is the same style:
`test_every_mapped_to_state_is_in_its_subjects_catalog_vocabulary`
(`packages/verdict-relay/tests/test_config.py:108`),
`test_indeterminate_never_maps_to_a_transition` (line 116),
`test_a_positive_row_commits_the_verdict_and_one_paired_transition_to_qualified` (line 131),
`test_an_unmapped_type_fails_validation_with_zero_api_calls` (line 210),
`test_every_fixture_row_carries_synthetic_identifiers_only` (line 241).

`packages/pulse-ledger/tests/test_commit.py` uses module-level functions rather than scenario
classes, but the same naming discipline:
`test_a_legal_declaration_commits_event_state_and_outbox_together`
(`packages/pulse-ledger/tests/test_commit.py:80`),
`test_an_illegal_transition_is_rejected_before_anything_is_written` (line 225),
`test_a_subject_cannot_enter_the_ledger_part_way_through_its_state_machine` (line 268),
`test_a_catalog_legal_coverage_transition_commits` (line 324) — which is verbatim the example name
the work order offered as the behavioural ideal —
`test_a_backdated_declaration_is_validated_against_the_state_that_held_then` (line 396),
`test_the_phi_bearing_fields_stay_out_of_the_declarations_repr` (line 179), and
`test_a_reversal_references_the_voided_event_preserves_history_and_folds_state_back` (line 501).
No mechanical name of the form `test_commit` or `test_declare_returns_true` was found in any of the
three modules.

**The `(spec: "<scenario name>")` convention is already used in test code, not only in task files.**
The string `spec: "` appears 89 times across `packages/**/*.py`. It appears in test *docstrings* as
the first thing the reader sees:

- `packages/consent-ingress/tests/test_declarer.py:172` — `"""spec: "A landed row becomes a
  command" — one `record_communication_consent` per row`
- `packages/consent-ingress/tests/test_declarer.py:216` — `"""spec: "A declared command is
  customer.io-attributed and traceable" — submitted under this`
- `packages/consent-ingress/tests/test_declarer.py:329` — `"""spec: "A full re-run over the same
  landing replays" — no new rows since the prior run, so`
- `packages/consent-ingress/tests/test_declarer.py:460` — `"""spec: "A cursor resume replays its
  last page" — a crash between a page's declarations and`
- `packages/schedules/tests/test_consent_sweep.py:64` — `"""spec: "Opt-out missing from the
  ledger" — export row suppressing a subject the ledger`
- `packages/schedules/tests/test_consent_sweep.py:211` — `"""spec: "A correction is attributed and
  traceable" — the command's actor is `reconciliation``
- `packages/schedules/tests/test_consent_sweep.py:269` — `"""spec: "Agreements produce no writes" —
  an export that fully agrees with ledger state`

It also appears inline as a trailing parenthetical on an assertion's comment, for example
`packages/schedules/tests/test_month_open.py:207` and
`packages/schedules/tests/test_cli.py:322`, and in `src/` module docstrings — for example
`packages/verdict-relay/src/verdict_relay/declarer.py:69` cites `(spec: verdict-declare, "Response
classifications drive distinct handling")`. Files carrying the convention span
`packages/consent-ingress/`, `packages/schedules/`, `packages/verdict-relay/`,
`packages/pulse-ledger/`, `packages/pulse-core/`, `packages/identity/`,
`packages/twenty-projection/`, `packages/synthea-seed/`, `packages/archaeology/`, and
`packages/ocean/libs/ocean-broker/`.

`packages/verdict-relay/tests/` mostly cites scenarios in the *module* docstring rather than
per-test: `packages/verdict-relay/tests/test_config.py:1-11` names the scenario the module covers
("cover the verdict-declare scenario \"A positive billing-eligibility verdict qualifies the
episode\""), and `packages/verdict-relay/tests/test_fixture_corpus.py:13-15` names three scenarios
at once. `consent-ingress` and `schedules` cite per-test. So the convention exists in two granularities
and is not uniform.

**The enforced coverage floors, verified against the current `Taskfile.yml`.** The four lines the
work order listed are present and unchanged, in the `test` target:

```
uv run coverage report --include="packages/verdict-relay/src/*" --fail-under=85     # Taskfile.yml:145
uv run coverage report --include="packages/schedules/src/*" --fail-under=85         # Taskfile.yml:146
uv run coverage report --include="packages/identity/src/*" --fail-under=90          # Taskfile.yml:147
uv run coverage report --include="packages/consent-ingress/src/*" --fail-under=85   # Taskfile.yml:148
```

The global floor is `fail_under = 80` at `pyproject.toml:144`, under `[tool.coverage.report]`
(`pyproject.toml:140`).

**What floor a new `packages/pricing-engine/` would be held to.** It would be held to 80 — and only
if it is added to `COV_PATHS` (`Taskfile.yml:44`), because the global `fail_under` applies to
whatever coverage measured, and coverage measures only the `--cov=` paths that variable lists. If
`packages/pricing-engine/src` is not added to `COV_PATHS`, the package is measured at nothing and
the 80 floor is vacuously satisfied. To hold it to the same 85 as `verdict-relay` and
`consent-ingress`, a fifth line is required in the `test` target:
`uv run coverage report --include="packages/pricing-engine/src/*" --fail-under=85`.

### Gap

Nothing is missing from the *style* — the existing suites already read as specifications and the
naming bar is met. Two things are missing from the *mechanism*. First, the
`(spec: "<scenario name>")` citation convention is a habit, not a rule: it is applied at module
granularity in `verdict-relay` and per-test granularity in `consent-ingress` and `schedules`, and no
gate, lint rule, or documented convention requires it, so a copied template will drift. Second, a
new package inherits only the vacuous 80 floor unless two separate edits are made
(`COV_PATHS` at `Taskfile.yml:44`, and a new `coverage report --include=` line after
`Taskfile.yml:148`), and nothing fails if only the first is made.

### Options

**Option A — cite the spec scenario per test, in the test's own docstring, using the
`consent-ingress` granularity, and hold `pricing-engine` to an explicit 85 floor.**
What it does: adopt `packages/consent-ingress/tests/test_declarer.py:172`'s exact shape —
`"""spec: "<scenario name>" — <one sentence on what this test asserts>."""` — as the first line of
every test in `packages/pricing-engine/tests/`; add
`uv run coverage report --include="packages/pricing-engine/src/*" --fail-under=85` to the `test`
target after `Taskfile.yml:148`.
What it costs: one Taskfile line, plus writing docstrings that were going to be written anyway.
What it gives up: nothing. It is the strictest granularity already practised in-repo.

**Option B — add a gate that fails the build when a test in `packages/pricing-engine/tests/` has no
`spec: "` citation.**
What it does: a scaffold-style test (the pattern of `tests/test_workspace_scaffold.py`) that parses
the connector's test modules and asserts each test function's docstring contains `spec: "`.
What it costs: one new gate file, plus the ongoing friction that a genuinely non-scenario test — a
property test, a PHI-posture pin — must either invent a scenario name or be exempted by name.
What it gives up: some flexibility, in exchange for the convention surviving eleven copies. Given
that the template's whole purpose is to be copied by people who were not in this conversation, that
trade is probably worth making — but it is a Tier 3 concern (template mechanics), not Tier 1.

**Option C — leave the convention as prose guidance in the connector's own README and rely on
imitation.**
What it does: nothing mechanical.
What it costs: nothing now.
What it gives up: the convention itself, on the third or fourth copy. This is the status quo and it
is why the convention is currently inconsistent between `verdict-relay` and `consent-ingress`.

### Recommendation

Option A for Tier 1, with Option B deferred to Tier 3. Per-test spec citation plus an explicit 85
floor gets the template to the bar with one Taskfile line and zero new concepts; the enforcement
gate is a template-mechanics decision that should be made once for all eleven connectors, not
inside the first one.

### Level of effort

`S` — one mechanical line added to `Taskfile.yml` and a docstring convention copied verbatim from
`packages/consent-ingress/tests/test_declarer.py`, both of which have an existing in-repo pattern.

### Dependencies and risks

Depends on `packages/pricing-engine/` being in `COV_PATHS` (Item 1.3), because the explicit 85 line
reads from the combined run's coverage data — as the comment at `Taskfile.yml:141-144` states, there
is no second test run. A package absent from `COV_PATHS` produces an empty `--include` match, and
`coverage report --include=<pattern that matches nothing>` does not clearly fail as "you forgot to
measure this"; it can report on zero files.

If this item fails silently, doubt the coverage floor first, and verify it the direct way: delete a
test from `packages/pricing-engine/tests/`, run `task test`, and confirm the run exits non-zero
naming `packages/pricing-engine/src/*`. A floor line whose `--include` glob does not match is the
failure mode that looks green forever.

Pass criteria for this item: `task test` exits non-zero when `packages/pricing-engine/src/` coverage
is below 85 percent; and every test function in `packages/pricing-engine/tests/` has a docstring
whose first line contains the substring `spec: "`.

---

## Item 1.3 — Full type annotations under a strict checker, enforced in continuous integration

### Current state

**The `typecheck` target runs two checkers** (`Taskfile.yml:119-133`).

Under mypy, one command: `uv run mypy {{.TYPED_PATHS}}` (`Taskfile.yml:122`). `TYPED_PATHS` is
defined at `Taskfile.yml:25` and its complete value is:

```
src packages/pulse-ledger/src packages/pulse-core/src packages/ocean/libs/ocean-events/src packages/ocean/libs/ocean-broker/src packages/ocean/libs/ocean-connector-mcp/src
```

The mypy configuration is at `pyproject.toml:92-103`: `files = ["src"]` (`pyproject.toml:93`),
`plugins = ["pydantic.mypy"]`, `disallow_untyped_defs = true`, `disallow_any_unimported = true`,
`no_implicit_optional = true`, `check_untyped_defs = true`, `warn_return_any = true`,
`warn_unused_ignores = true`, `show_error_codes = true`. Note that `files` names only `src`; the
`TYPED_PATHS` arguments on the command line are what extend the run to the packages.

Under pyright, seven commands, one per package (`Taskfile.yml:127-133`), in this exact order:

```
uv run pyright -p packages/archaeology
uv run pyright -p packages/verdict-relay
uv run pyright -p packages/schedules
uv run pyright -p packages/identity
uv run pyright -p packages/consent-ingress
uv run pyright -p packages/synthea-seed
uv run pyright -p packages/twenty-projection
```

The work order's description said four packages run under pyright; the current file has seven —
`packages/synthea-seed` and `packages/twenty-projection` are additional to the four named in the
target's own `desc` string at `Taskfile.yml:120`, which is now stale relative to the commands
beneath it.

An important consequence: `packages/pulse-core/src` — the SDK a connector calls into — is checked by
**mypy only** (`Taskfile.yml:25`), not by pyright strict. Every package that pyright-strict-checks is
a *consumer* of that SDK.

**The exact pyright configuration a new package copies.** From
`packages/verdict-relay/pyproject.toml:42-44`, verbatim and complete:

```toml
[tool.pyright]
include = ["src", "tests"]
typeCheckingMode = "strict"
```

Three lines. `pyright` is a dev dependency of the package itself
(`packages/verdict-relay/pyproject.toml:29-31`: `"pyright>=1.1.390"`, with the comment "This package
typechecks under pyright (see `[tool.pyright]` below); `task typecheck` runs it alongside the
workspace mypy pass"), installed by `uv sync --all-packages` (`Taskfile.yml:80`). Note that
`include` covers `tests` as well as `src` — the test suite is strictly typed too, which is why the
suites read as specification-grade code.

**What it costs to add a new package to both checkers — five edits across three files, all of them
required:**

1. `pyproject.toml:61-75`, `[tool.uv.workspace] members` — add `"packages/pricing-engine"`.
2. `pyproject.toml:78-90`, `[tool.uv.sources]` — add `pricing-engine = { workspace = true }`.
3. `Taskfile.yml:19`, `LINT_PATHS` — add `packages/pricing-engine`, or ruff never sees it.
4. `Taskfile.yml:127-133`, the `typecheck` target — add
   `uv run pyright -p packages/pricing-engine`. (Adding it to `TYPED_PATHS` at `Taskfile.yml:25`
   instead would put it under mypy, which is the *weaker* of the two; pyright strict is what the
   item claims.)
5. `Taskfile.yml:31` `TESTED_PATHS` and `Taskfile.yml:44` `COV_PATHS` — add
   `packages/pricing-engine/tests` and `--cov=packages/pricing-engine/src`.

Plus, in the package's own file: `packages/pricing-engine/pyproject.toml` needs the three-line
`[tool.pyright]` block above, a `pyright` dev dependency, `requires-python = ">=3.10,<4.0"` matching
the root (`pyproject.toml:8`, pinned by `tests/test_workspace_scaffold.py:58-66`), a
`[tool.hatch.build.targets.wheel]` `packages = ["src/pricing_engine"]` entry, and
`[tool.pytest.ini_options] testpaths = ["tests"]`.

And one more, easy to miss: `pyproject.toml:192-205`, `[tool.ruff.lint.per-file-ignores]`, needs
`"packages/pricing-engine/tests/**" = ["S101"]`. Without it, as the comment at
`pyproject.toml:194-195` states, "every pytest assert in it would lint-fail" — the `tests/*` pattern
at `pyproject.toml:193` does not reach `packages/*`.

**Whether a gate pins those wirings.** `tests/test_workspace_scaffold.py` exists precisely for this
failure mode — its docstring at `tests/test_workspace_scaffold.py:1-9` says "A package can exist on
disk while every quality gate silently skips it — lint, typecheck, tests, and coverage each have
their own path list in `Taskfile.yml`, and membership in `[tool.uv.workspace]` implies none of
them." It asserts workspace membership (`tests/test_workspace_scaffold.py:39-42`), src layout and
`py.typed` marker (lines 45-55), `requires-python` parity (lines 58-66), `LINT_PATHS` reach (lines
68-71), `TYPED_PATHS` reach (lines 74-77), `TESTED_PATHS` and `COV_PATHS` reach (lines 80-87), and
the ruff `S101` exemption (lines 90-96). **But its `_PACKAGES` constant covers only two packages**
(`tests/test_workspace_scaffold.py:25-28`):

```python
_PACKAGES = {
    "packages/pulse-ledger": "pulse_ledger",
    "packages/pulse-core": "pulse_core",
}
```

So `packages/verdict-relay`, `packages/schedules`, `packages/identity`,
`packages/consent-ingress`, `packages/synthea-seed`, `packages/twenty-projection`, and
`packages/archaeology` are **not** pinned by that gate, and neither would `packages/pricing-engine`
be unless it is added to `_PACKAGES`. Note also that this gate asserts `TYPED_PATHS` reach, which
is the mypy list — a package that goes under pyright instead cannot be added to `_PACKAGES`
unmodified, because `test_typecheck_reaches_pulse_packages`
(`tests/test_workspace_scaffold.py:74-77`) asserts `f"{pkg_dir}/src" in typed_paths`. That
assertion would fail for a pyright-strict package. **This is a real, unresolved wrinkle**: the gate
as written can only pin mypy-checked packages.

**Escape hatches — counted and located.** `packages/verdict-relay/src/` is clean: zero
`# type: ignore`, zero `# pyright: ignore`, and the only `Any` uses are five, all in one file and all
for the untyped Snowflake driver connection —
`packages/verdict-relay/src/verdict_relay/production.py:23` (`from typing import Any`),
`:113` (`def _snowflake_connect(config: ProductionConfig) -> Any:`),
`:140` (`connect: Callable[[ProductionConfig], Any] | None = None,`),
`:144` (`self._connection: Any | None = None`), and
`:146` (`def _ensure_connection(self) -> Any:`).

Across `packages/pulse-core/src`, `packages/verdict-relay/src`, `packages/pulse-ledger/src`,
`packages/consent-ingress/src`, `packages/identity/src`, and `packages/schedules/src`, there are
**sixteen** `# type: ignore` comments, and every one of them is in a mypy-checked package, none in a
pyright-strict one:

- `packages/pulse-core/src/pulse_core/client.py:304` — `# type: ignore[arg-type]`
- `packages/pulse-core/src/pulse_core/catalog_release_cli.py:119` — `# type: ignore[attr-defined]`
- `packages/pulse-ledger/src/pulse_ledger/commit.py:183` and `:310` and `:324`
- `packages/pulse-ledger/src/pulse_ledger/relay.py:206` and `:346`
- `packages/pulse-ledger/src/pulse_ledger/review.py:119`, `:122`, `:125`, `:126`, `:127`, `:173`, `:222`
- `packages/pulse-ledger/src/pulse_ledger/api_server.py:247` — `# type: ignore[assignment]`
- `packages/pulse-ledger/src/pulse_ledger/identity.py:104`

`# pyright: ignore` appears three times in the whole of `packages/`, all in tests and all the same
narrow suppression: `packages/identity/tests/test_matching_docs.py:59`,
`packages/identity/tests/test_normalize.py:195`, and
`packages/identity/tests/test_normalize.py:204`, each `# pyright: ignore[reportPrivateUsage]`.
`packages/consent-ingress/src` and `packages/schedules/src` contain no `Any` at all (the two grep
hits in those trees, `packages/identity/src/identity/normalize.py:55` and
`packages/schedules/src/schedules/cli.py:276`, are the English word "Anything"/"Any" inside a
comment and a `--help` string, not the type).

CI enforcement is real: `.github/workflows/main.yml:50` runs `task check`, and `check`
(`Taskfile.yml:388-398`) runs `typecheck` as its second step.

### Gap

The strictness standard a new connector should meet already exists and is met by
`packages/verdict-relay/` almost perfectly, so the gap is not "we need a strict checker" — it is
that nothing *forces* a new package into it. A `packages/pricing-engine/` that omits the
`uv run pyright -p packages/pricing-engine` line from `Taskfile.yml:127-133` type-checks under
nothing at all, `task check` stays green, and no gate notices, because
`tests/test_workspace_scaffold.py:25-28` covers only `packages/pulse-ledger` and
`packages/pulse-core` and its `TYPED_PATHS` assertion cannot express a pyright-checked package
anyway.

### Options

**Option A — copy `packages/verdict-relay/`'s exact configuration and make all five wiring edits
plus the ruff `S101` entry, without touching any gate.**
What it does: `packages/pricing-engine/pyproject.toml` gets the three-line `[tool.pyright]` block
from `packages/verdict-relay/pyproject.toml:42-44` and the `pyright>=1.1.390` dev dependency; the
five wiring edits above are made.
What it costs: about an hour, entirely mechanical, with an exact in-repo model to copy.
What it gives up: nothing about the strictness itself. It gives up the *guarantee* that a future
edit cannot drop the package out of the checker.

**Option B — Option A plus generalising `tests/test_workspace_scaffold.py` so it pins every
workspace package and accepts either checker.**
What it does: replace the hardcoded `_PACKAGES` dict at `tests/test_workspace_scaffold.py:25-28`
with a derivation from `[tool.uv.workspace] members`, and change
`test_typecheck_reaches_pulse_packages` (`tests/test_workspace_scaffold.py:74-77`) to assert that
each package is reached by *either* `TYPED_PATHS` *or* a `uv run pyright -p <package>` line in the
`typecheck` target.
What it costs: editing a shared gate file that seven currently-unpinned packages would suddenly be
held to, which may surface pre-existing wiring gaps in `packages/ocean/libs/*` and
`packages/archaeology`. That is a discovery, not a defect, but it turns a one-hour task into an
unbounded one.
What it gives up: schedule predictability. This is properly Tier 3 work (template mechanics), and
attempting it inside the first connector risks the connector being blocked on unrelated cleanup.

**Option C — put `packages/pricing-engine/src` in `TYPED_PATHS` and use mypy only.**
What it does: one-word edit to `Taskfile.yml:25`, and no per-package pyright configuration at all.
What it costs: least of the three.
What it gives up: the claim. The item is "strict type checker", and `pyproject.toml:92-103`'s mypy
settings, while strong, are not pyright's `typeCheckingMode = "strict"` — and it would put the
reference connector in the same tier as `packages/pulse-ledger/src`, which carries fourteen of the
repository's sixteen `# type: ignore` comments. The template must not teach the weaker tier.

### Recommendation

Option A, with Option B written up as a Tier 3 item. Copying `packages/verdict-relay/`'s
configuration is a solved problem with an exact model; generalising the scaffold gate is valuable
but is a change to a shared file whose blast radius is seven other packages and belongs in the
template-mechanics tier where it can be done once for all eleven connectors.

### Level of effort

`S` — five mechanical wiring edits plus a three-line `[tool.pyright]` block copied verbatim from
`packages/verdict-relay/pyproject.toml:42-44`, no new concept and an exact in-repo model to follow.

### Dependencies and risks

Nothing must land first. The risk is that the five wiring edits touch two shared serial files
(`pyproject.toml` and `Taskfile.yml`), so this must be sequenced against any concurrent work on
either — the `G_MECE` prose-overlap failure mode applies directly.

If this item fails silently, doubt whether pyright is actually running on the new package, and
verify it the direct way rather than by reading the Taskfile: add a deliberately untyped function to
`packages/pricing-engine/src/pricing_engine/`, run `task typecheck`, and confirm it exits non-zero
naming that file. A missing `uv run pyright -p packages/pricing-engine` line is invisible in a green
run, and so is a `[tool.pyright]` block whose `include` list omits `tests`.

The second thing to doubt: `packages/verdict-relay/pyproject.toml:43` sets
`include = ["src", "tests"]`. Copying only `include = ["src"]` would leave the connector's test
suite — the suite that Item 1.2 makes the specification — unchecked, which is exactly backwards.

Pass criteria for this item: `uv run pyright -p packages/pricing-engine` exits 0 and reports 0
errors and 0 warnings; `packages/pricing-engine/src/` contains zero occurrences of
`# type: ignore`, zero occurrences of `# pyright: ignore`, and zero occurrences of the type `Any`;
and `task typecheck` exits non-zero after an untyped function is added anywhere under
`packages/pricing-engine/src/`.

---

## Item 1.4 — Visible error taxonomy

### Current state

**The four-way classification exists, is centralised, and is named exactly as the work order
paraphrased it.** `packages/pulse-core/src/pulse_core/client.py:57-63`:

```python
class ResponseClassification(str, Enum):
    """The four answers a submitted command can receive (design decision 6)."""

    COMMITTED = "committed"
    REPLAYED = "replayed"
    REJECTED = "rejected"
    TRANSIENT = "transient"
```

The wire values are the strings `"committed"`, `"replayed"`, `"rejected"`, `"transient"`; the member
names are `COMMITTED`, `REPLAYED`, `REJECTED`, `TRANSIENT`.

Classification is a pure function of the HTTP response,
`classify_response(response: httpx.Response) -> CommandResponse`
(`packages/pulse-core/src/pulse_core/client.py:128`). Its rules:

- `_REJECTED_STATUS = frozenset({401, 403, 422})` (`packages/pulse-core/src/pulse_core/client.py:46`)
  → `REJECTED` (lines 136-142).
- `_TRANSIENT_STATUS = frozenset({408, 429, 500, 502, 503, 504})`
  (`packages/pulse-core/src/pulse_core/client.py:50`) → `TRANSIENT` (lines 143-148).
- Any `2xx` → `REPLAYED` if the response body's `replayed` field is truthy, else `COMMITTED`
  (lines 149-161).
- Anything else raises `UnexpectedResponseError`
  (`packages/pulse-core/src/pulse_core/client.py:66-76`, raised at line 162) rather than being
  folded into a guess — the docstring at lines 68-71 states this explicitly.
- An `httpx.TransportError` — a network failure with no status at all — is caught in
  `_post_with_retry` and classified `TRANSIENT` with `status_code=None`
  (`packages/pulse-core/src/pulse_core/client.py:316-321`).

`CommandResponse` (`packages/pulse-core/src/pulse_core/client.py:88-105`) carries
`classification`, `status_code`, `attempts`, `event_id`, `recorded_at`, `rule_version`,
`outbox_seq`, `state`, and `rejection`, plus a convenience property `is_success` that is true for
`COMMITTED` or `REPLAYED` only (lines 102-105).

**Retry and backoff exist in two places, with two different budgets.**

In `pulse_core`: `DEFAULT_MAX_ATTEMPTS = 4`, `DEFAULT_BASE_DELAY_SECONDS = 0.5`,
`DEFAULT_MAX_DELAY_SECONDS = 8.0` (`packages/pulse-core/src/pulse_core/client.py:52-54`). All three
are constructor parameters on `PulseCoreClient.__init__`, so they are constants *and* configurable
(`packages/pulse-core/src/pulse_core/client.py:245-247`). The loop is
`_post_with_retry` (`packages/pulse-core/src/pulse_core/client.py:309-324`): it returns immediately
for any classification that is not `TRANSIENT`, and otherwise sleeps
`_backoff_delay(attempt, base, maximum)` — plain capped exponential, `base * 2**(attempt-1)`, no
jitter (`packages/pulse-core/src/pulse_core/client.py:223-226`) — until `attempt >=
self._max_attempts`, then returns the last transient result with `attempts` set. It never raises on
exhaustion. `max_attempts < 1` raises `ValueError`
(`packages/pulse-core/src/pulse_core/client.py:250-252`).

In `verdict_relay`: `DECLARE_MAX_ATTEMPTS = 5` (`packages/verdict-relay/src/verdict_relay/declarer.py:70`),
`DEFAULT_BASE_DELAY_SECONDS = 0.5`, `DEFAULT_MAX_DELAY_SECONDS = 30.0`
(lines 72-73). Also constants and constructor-configurable
(`packages/verdict-relay/src/verdict_relay/declarer.py:190-194`). Its loop,
`Declarer._submit_with_retry` (`packages/verdict-relay/src/verdict_relay/declarer.py:270-287`),
backs off with **jitter** — `_backoff_delay` returns `min(base * 2**(attempt-1), max) *
self._jitter()` where `jitter` defaults to `random.random`
(`packages/verdict-relay/src/verdict_relay/declarer.py:79-80` and `:289-291`) — and on exhaustion
**raises** `TransientExhaustedError` naming the row
(`packages/verdict-relay/src/verdict_relay/declarer.py:115-121`, raised at line 287), which fails the
run. That is the opposite disposition from `pulse_core`'s silent return.

The two are deliberately prevented from compounding: `verdict_relay.declarer.service_client`
constructs the client with `max_attempts=1`
(`packages/verdict-relay/src/verdict_relay/declarer.py:158`), and the docstring at lines 146-147
gives the reason — "retry policy belongs to the declarer (design decision 4) — a client that also
retried would multiply the attempt budget."

**Only `transient` is retried; `rejected` is never retried.** Verified at two levels. In
`pulse_core`, `_post_with_retry` returns for anything that `is not
ResponseClassification.TRANSIENT` (`packages/pulse-core/src/pulse_core/client.py:322`). In
`verdict_relay`, `_settle` handles `REJECTED` by counting it, logging it, and returning
`RowDisposition.REJECTED` with no further submission
(`packages/verdict-relay/src/verdict_relay/declarer.py:300-310`), and the log message ends with the
literal words "not retried". The behaviour is pinned by
`test_rejection_counts_logs_the_reason_and_never_retries`
(`packages/verdict-relay/tests/test_declarer.py:152`) and
`test_a_rejected_transition_keeps_the_verdict_and_never_retries`
(`packages/verdict-relay/tests/test_declarer.py:449`).

**What a `rejected` response carries — verified, not `UNVERIFIED`.**
`Rejection` (`packages/pulse-core/src/pulse_core/client.py:79-85`) has exactly three fields:
`message: str`, `reason: str | None = None`, `catalog_version: str | None = None`. Its docstring
says "Why a command was rejected, or why a transient attempt failed — never the request body."
`_rejection_from_body` (`packages/pulse-core/src/pulse_core/client.py:115-125`) populates `reason`
and `catalog_version` from the response body's `detail` object, and only when each is a string.

The server side supplies them. `packages/pulse-ledger/src/pulse_ledger/api.py:613-628` is the
`IllegalTransitionError` handler and returns HTTP 422 with:

```python
content={
    "detail": {
        "message": str(exc),
        "reason": exc.reason,
        "catalog_version": exc.catalog_version,
        "subject_type": exc.subject_type,
        "from_state": exc.from_state,
        "to_state": exc.to_state,
    }
}
```

So the ledger's reason and catalog version are both present on the wire, and both are surfaced on
`Rejection`. Note that `subject_type`, `from_state`, and `to_state` are on the wire but are **not**
fields on `Rejection` — they are lost at the SDK boundary and survive only inside
`Rejection.message`. Two other rejection shapes exist: a 401 whose `detail` is a bare string
(`packages/pulse-ledger/src/pulse_ledger/api.py:571-576`), and a 403 whose `detail` is an object
carrying `message`, `event_type`, and `writer_id`
(`packages/pulse-ledger/src/pulse_ledger/api.py:605-610`). `_rejection_from_body` handles the bare
string via its `if detail is not None: return Rejection(message=str(detail))` branch
(`packages/pulse-core/src/pulse_core/client.py:123-124`), so neither shape crashes the client — but
neither carries `reason` or `catalog_version`, so an engineer who logs only `rejection.reason` will
see `None` for an auth rejection.

`verdict_relay` logs all three at `WARNING`
(`packages/verdict-relay/src/verdict_relay/declarer.py:302-308`), and again for a rejected paired
transition (lines 348-355).

**The four classifications are re-projected into a per-connector disposition vocabulary.**
`verdict_relay.declarer.RowDisposition` (`packages/verdict-relay/src/verdict_relay/declarer.py:82-88`)
is a *different* four-member enum — `DECLARED = "declared"`, `REPLAYED = "replayed"`,
`SKIPPED_STALE = "skipped_stale"`, `REJECTED = "rejected"` — and `DeclarerCounts`
(`packages/verdict-relay/src/verdict_relay/declarer.py:91-100`) has six counters: `declared`,
`replayed`, `skipped_stale`, `rejected`, `transitioned`, `transition_rejected`. The mapping from
`ResponseClassification` to `RowDisposition` is hand-written in `_settle`
(`packages/verdict-relay/src/verdict_relay/declarer.py:293-319`), and the counting is hand-written
`dataclasses.replace` calls. None of that lives in `pulse_core`.

### Gap

The classification itself is in exactly the right place — a connector author calls
`PulseCoreClient.submit_command` and gets a `CommandResponse` whose `classification` is one of the
four, with no work and no possibility of getting the status-code mapping wrong. But everything
*downstream* of the classification is per-connector, hand-written code:
the retry loop, the attempt budget, whether backoff has jitter, whether exhaustion raises or
returns, and the vocabulary the outcomes are counted in. The repository already demonstrates the
divergence with a sample size of two — 4 attempts versus 5, jitter versus no jitter, silent return
versus raised `TransientExhaustedError` — and it required a deliberate `max_attempts=1` pin
(`packages/verdict-relay/src/verdict_relay/declarer.py:158`) to stop the two layers from
multiplying. Eleven connectors written this way will produce eleven retry policies and eleven
receipt vocabularies, and the one that gets `max_attempts` wrong in both layers will quietly retry
20 times.

### Options

**Option A — `pricing-engine` calls `PulseCoreClient.submit_command` directly and writes its own
retry loop, copying `verdict_relay.declarer`'s shape.**
What it does: reproduces the proven pattern; the connector owns `PRICING_MAX_ATTEMPTS`, its own
backoff, and its own disposition enum.
What it costs: least new code in `pulse_core` — nothing.
What it gives up: exactly the property the template exists to provide. It would make the reference
implementation the *third* independent retry policy in the repository and would formally bless
copy-paste as the mechanism for the eleven.

**Option B — add a shared `submit_with_policy` helper to `pulse_core` that owns the retry loop, the
exhaustion error, and a canonical disposition/counter vocabulary; have `pricing-engine` call it,
and leave `verdict_relay` alone.**
What it does: one new function (or small class) in
`packages/pulse-core/src/pulse_core/client.py` or a sibling module, taking a command, an attempt
budget, and a jitter/sleep seam, returning the classified outcome and raising a single named
exhaustion error. `pricing-engine` calls it and never writes a `while` loop or a `2 **` expression.
The connector still owns its *domain* dispositions (the equivalent of `skipped_stale`), because
those are genuinely connector-specific.
What it costs: a new module surface in `pulse_core`, tests for it inside a package that is
mypy-checked rather than pyright-strict-checked (see Item 1.3), and a documented decision that
`verdict_relay` and `consent_ingress` are not migrated in this change — so for a while the
repository has both the shared helper and two legacy hand-rolled loops, and a reader must be told
which is the template.
What it gives up: short-term consistency inside the repository, in exchange for consistency across
the eleven connectors that do not exist yet. That is the right direction for the trade.

**Option C — Option B plus migrating `verdict_relay` and `consent_ingress` onto the shared helper in
the same change.**
What it does: leaves exactly one retry policy in the repository.
What it costs: touching two packages that each carry an 85 percent coverage floor
(`Taskfile.yml:145` and `Taskfile.yml:148`) and a full behavioural suite, including tests that pin
the *current* schedule — `test_backoff_is_exponential_and_jitter_scaled`
(`packages/verdict-relay/tests/test_declarer.py:193`) and
`test_transient_exhausts_five_attempts_and_names_the_row` (line 179). Reconciling
`DECLARE_MAX_ATTEMPTS = 5` against `DEFAULT_MAX_ATTEMPTS = 4` is a behaviour change to a production
declarer, not a refactor, and `verdict_relay`'s per-row exhaustion semantics (fail the run naming
the row) is a real requirement that the shared helper must be able to express before this is safe.
What it gives up: schedule. This is the correct end state and the wrong first step.

### Recommendation

Option B. This is the single most important decision in Tier 1: the classification is already
shared, so the only thing standing between the template and eleven divergent retry policies is a
shared retry helper, and adding one is materially cheaper than migrating two production declarers
onto it. Migrating `verdict_relay` and `consent_ingress` should be a follow-up change with its own
proposal, not a precondition of the reference connector.

### Level of effort

`M` — one new module in `packages/pulse-core/` plus its tests written first, and the design decision
about exhaustion semantics has to be made explicitly rather than inherited.

### Dependencies and risks

Depends on nothing landing first, but it does need a decision recorded about whether the shared
helper's exhaustion behaviour is `pulse_core`'s (return the last transient result) or
`verdict_relay`'s (raise a named error). Those are contradictory, both are in production, and the
helper cannot silently pick one — if the choice is not written down, it becomes an eleven-connector
inconsistency by a different route. If that decision needs Rob or an ADR rather than an engineer's
judgement, this item becomes `XL` until it is made.

The second risk: `packages/pulse-core/src` is checked by mypy (`Taskfile.yml:25`), not by pyright
strict, and it holds two of the sixteen `# type: ignore` comments in the repository, one of them
directly in the submission path — `packages/pulse-core/src/pulse_core/client.py:304`,
`payload=body["payload"],  # type: ignore[arg-type]`. A new helper added alongside it inherits the
weaker checker, and the reference connector would then be pointing engineers at a module held to a
lower standard than the connector itself. Either add
`uv run pyright -p packages/pulse-core` to `Taskfile.yml:127-133` (which is a separate, possibly
large, cleanup) or place the helper in the connector package and accept that it is not yet shared —
and say so in the report rather than implying it is.

If this item fails silently, doubt the attempt budget first, and doubt it in the *composed* case
rather than in either layer alone. The failure mode is not "retries do not happen"; it is
"retries happen `client.max_attempts * helper.max_attempts` times". `verdict_relay` avoids it only
because of the deliberate `max_attempts=1` at
`packages/verdict-relay/src/verdict_relay/declarer.py:158`, which is one line in a factory function
and is exactly the kind of line a copy-paste drops. Assert the total submission count against the
fake API, not the loop count inside one layer.

Pass criteria for this item: a test in `packages/pricing-engine/tests/` asserts, against an
`httpx.MockTransport` fake, that a scripted `422` response produces exactly one `POST /commands`
call and a `CommandResponse` whose `classification` is `ResponseClassification.REJECTED`; a second
test asserts that a scripted sequence of five `503` responses produces exactly five
`POST /commands` calls and no sixth; a third asserts that a `2xx` response whose body contains
`"replayed": true` classifies as `ResponseClassification.REPLAYED` and a `2xx` whose body contains
`"replayed": false` classifies as `ResponseClassification.COMMITTED`; and a fourth asserts that a
`422` response whose `detail` object carries `reason` and `catalog_version` yields a
`Rejection` whose `reason` and `catalog_version` are both non-`None`.

---

## Cross-item notes

Two facts worth carrying into Tiers 2 and 3:

1. **`packages/verdict-relay/` is the right thing to copy, and `packages/pulse-ledger/` is not.**
   `verdict-relay` runs under pyright strict with zero `# type: ignore` and zero
   `# pyright: ignore` in its `src/` tree; `pulse-ledger` runs under mypy and carries fourteen of
   the repository's sixteen `# type: ignore` comments. An engineer told to "look at the pulse
   packages" will find both, and the template must name which one.
2. **Three shared serial files are touched by Tier 1 work**: `Taskfile.yml` (target list plus four
   path variables), `pyproject.toml` (workspace members, sources, ruff per-file-ignores), and
   potentially `tests/test_workspace_scaffold.py`. Any parallel dispatch of these items must rule
   those seams to a single worker, per the `G_MECE` prose-overlap lesson.

## Verification

```
ls -1 .planning/reports/2026-08-21-connector-template-tier-1-gap-analysis.md
```

Run from `/Users/Rob.Ford/orca/workspaces/pulse/betta`; exits 0 and prints the path above. This
report contains one `## Item` section for each of the four Tier 1 items — 1.1, 1.2, 1.3, 1.4 — each
with all six sub-headings (`### Current state`, `### Gap`, `### Options`, `### Recommendation`,
`### Level of effort`, `### Dependencies and risks`) filled in.
