# Work Order: Tier 1 gap analysis — the first five minutes

**Programme**: connector-template (pricing-engine as the reference Pulse API connector)
**Tier**: 1 of 3 — what an engineer judges before reading any prose
**Lane**: analysis only, no implementation
**Model**: opus (this tier decides whether the template is credible at all)
**Repository**: `/Users/Rob.Ford/orca/workspaces/pulse/betta`

## Objective

Produce a gap analysis for the four Tier 1 items below: what exists in this repository today,
what options exist to close each gap, and the level of effort for each. This tier is the one that
decides whether Brook's engineers take the template seriously, so accuracy matters more than
optimism — if something is missing, say it is missing.

## Why this work exists

Rob Ford, 2026-08-21: "I want the pricing-engine to be the best practice template for developing a
Pulse api connector from the other systems that I can demo to the rest of the engineers without
being laughed at. There are as many as 11 depending on how you count them. I need engineering's
help with developing them all except for the pricing-engine connector."

`pricing-engine` is therefore the **reference implementation** other Brook engineers will copy,
and its audience is people looking for reasons to dismiss PULSE. The bar is "exemplary and
legible", not "works".

## What a Pulse API connector is

A connector crosses the pulse boundary in exactly one of two sanctioned directions:

- **In:** through the command API (`POST /commands`, `POST /commands:batch`) under the
  connector's own credential. The API derives the `actor` from the bearer credential; a request
  body carrying `actor_type`, `actor_id`, `actor_authority`, or `producer` is rejected outright.
- **Out:** the consumer attaches its own Amazon EventBridge rule and its own Amazon SQS queue to
  the `ocean` event bus.

A connector never reads another application's datastore and never writes to the pulse Postgres
database directly.

**The distinction the template must teach.** The seven services in `packages/ocean/services/`
whose names end in `-connector` — `github-connector`, `hubspot-connector`, `impilo-connector`,
`linear-connector`, `mongodb-connector`, `pocar-connector`, `zcc-connector` — are OCEAN-era
publishers that emit to the EventBridge bus. A **Pulse API connector** declares through the
command API instead, because producer policy forbids a producer publishing catalog-subject state
to the bus (offline CI gate at `packages/pulse-core/src/pulse_core/producer_policy.py`).

## Worked precedents to read before you start

- `packages/verdict-relay/` — reads a mart, declares verdicts and paired state transitions;
  closest in shape to a connector. Start with
  `packages/verdict-relay/src/verdict_relay/declarer.py`,
  `packages/verdict-relay/src/verdict_relay/run.py`, and
  `packages/verdict-relay/src/verdict_relay/production.py`.
- `packages/consent-ingress/` — the Customer.io consent ingress.
- `packages/pulse-core/` — the client SDK: `submit_command`, idempotency key derivation at
  `packages/pulse-core/src/pulse_core/idempotency.py`, durable writer cursors, and Pydantic
  command types generated from the state catalog.

## Scope — the four Tier 1 items

### Item 1.1 — Runs in one command, offline, with no credentials

The claim to test: an engineer can run `git clone`, then a single documented command, and see the
connector do real work against a fake backend — with no VPN, no Amazon Web Services credentials,
no Snowflake account, and no secrets file.

Analyse specifically:
- Is there any existing demo or example-run target in `Taskfile.yml`? Read the whole file; the
  target list is grouped by area. Note that `task check` is the offline, credential-free contract
  and that credentialed targets such as `task relay:run TARGET=<env>` and
  `task ledger:deploy TAG=<tag> TARGET=<env>` are deliberately excluded from it.
- What would a `pricing-engine` demo actually run against? Options to weigh include an in-process
  fake of the command API, the existing fixture-transport pattern used in verdict-relay's tests,
  the LocalStack-based local event stack at `packages/ocean/infra/docker-compose.yml`, and a real
  local Postgres. State which of these require Docker and which do not, because a demo that needs
  Docker running is materially weaker than one that does not.
- How is the command API's own test double constructed today, if at all? Search
  `packages/pulse-ledger/tests/` and `packages/verdict-relay/tests/` for the transport fakes.
- What exactly would the one command print? A demo whose output is a wall of log lines is worse
  than one that prints a short, obviously-correct receipt.

### Item 1.2 — Tests that double as the specification

The claim to test: an engineer can read the connector's test suite and learn the contract from it
faster than from prose, and the test names read as behaviours rather than as function names.

Analyse specifically:
- Sample the existing test suites and characterise their naming style with citations. Read at
  minimum `packages/verdict-relay/tests/test_config.py`,
  `packages/verdict-relay/tests/test_declarer.py` if it exists, and
  `packages/pulse-ledger/tests/test_commit.py`. Report whether names are behavioural
  (for example `test_a_catalog_legal_coverage_transition_commits`) or mechanical.
- The repository already ties tests to specification scenarios: OpenSpec change task lists cite
  scenarios inline as `(spec: "<scenario name>")`. Establish whether that convention is used in
  test code itself, in docstrings, or only in task files, and whether it could be surfaced in the
  connector's tests as the teaching mechanism.
- What is the enforced coverage floor a new package would inherit or need? The `test` target in
  `Taskfile.yml` currently enforces these four per-package floors, in addition to the global
  `fail_under` configured in `pyproject.toml`:

      uv run coverage report --include="packages/verdict-relay/src/*" --fail-under=85
      uv run coverage report --include="packages/schedules/src/*" --fail-under=85
      uv run coverage report --include="packages/identity/src/*" --fail-under=90
      uv run coverage report --include="packages/consent-ingress/src/*" --fail-under=85

  Confirm those four lines against `Taskfile.yml` (they were read on 2026-08-21 and may have
  changed), report the global `fail_under` value from `pyproject.toml`, and state what floor a new
  `packages/pricing-engine/` package would be held to and whether adding it requires a new line.

### Item 1.3 — Full type annotations under a strict checker, enforced in continuous integration

The claim to test: the connector is fully annotated and a strict type checker proves it on every
push, with no escape hatches.

Analyse specifically:
- Read the `typecheck` target in `Taskfile.yml`. Report exactly which packages run under
  `uv run pyright -p <path>` and which run under `uv run mypy` on the `TYPED_PATHS` variable, and
  where `TYPED_PATHS` is defined.
- Read `packages/verdict-relay/pyproject.toml` and report the exact pyright configuration a new
  package would copy to get the same strictness.
- Establish what it costs to add a new package to both checkers: is it a one-line addition to
  `Taskfile.yml`, a `pyproject.toml` section, a workspace member entry, or all three? Cite the
  files.
- Report whether any existing package uses `Any`, `type: ignore`, or `pyright: ignore` escapes,
  and if so how many and where — an example that copies an escape-riddled package teaches the
  escape.

### Item 1.4 — Visible error taxonomy

The claim to test: the connector shows explicitly that a command API response is one of four
kinds — committed, replayed, rejected, transient — and that only `transient` is retried while
`rejected` is never retried.

Analyse specifically:
- Find where this four-way classification is implemented today and cite it. Start with
  `packages/pulse-core/src/pulse_core/` and `packages/verdict-relay/src/verdict_relay/declarer.py`.
  Report the exact names of the four outcomes as they appear in code, not as I have paraphrased
  them here.
- Report how retry and backoff are implemented, including the exact maximum attempt count, and
  whether that count is a constant, configurable, or both.
- Establish whether an engineer copying the connector would get this handling by calling into
  `pulse_core`, or whether they would have to re-implement the classification themselves. This is
  the single most important finding in this item: if the taxonomy is re-implemented per connector,
  eleven connectors will get it wrong eleven different ways, and the template's main job is to
  prevent that.
- Report what a `rejected` response carries (the ledger's reason and catalog version are believed
  to be included — verify and cite, or mark `UNVERIFIED`).

## Level-of-effort scale (use these exact labels — the three tier reports are compared side by side)

| Label | Meaning | Rough size |
|---|---|---|
| `XS` | One file, no new dependency, no new concept | under 1 hour |
| `S` | One or two files, mechanical, pattern already exists in-repo to copy | 1–3 hours |
| `M` | Several files or one new module, needs tests written first | half a day to a day |
| `L` | New package, new gate, or touches a shared/serial file that other work must sequence around | 1–3 days |
| `XL` | Needs a decision from Rob, an ADR, or work in another repository before it can start | unbounded until unblocked |

State the label AND the reasoning in one sentence. A label with no reasoning is not usable.

## Output — write exactly one file

Write your report to this exact path, creating parent directories if needed:

    .planning/reports/2026-08-21-connector-template-tier-1-gap-analysis.md

Your tier number is `1`. Do not write any other file. Do not create
a pull request. Do not modify any file outside that one report path.

## Required structure for every item in your tier

Use this exact heading structure per item so the three reports can be read together:

    ## Item <tier>.<n> — <item name>

    ### Current state
    What exists in the repository today, with `path/to/file.py:LINE` evidence for every claim.
    If nothing exists, write "Nothing exists" and say what you searched to establish that.

    ### Gap
    The specific difference between current state and what the item requires. One paragraph.

    ### Options
    Two or three concrete implementation options. For each: what it does, what it costs, what it
    gives up. If there is genuinely only one sensible option, say so and explain why the
    alternatives are worse rather than inventing filler.

    ### Recommendation
    Which option, and the reason in one or two sentences.

    ### Level of effort
    The label from the scale above, plus the one-sentence reasoning.

    ### Dependencies and risks
    What must land first, what could make this harder than it looks, and — if the item could fail
    silently — which value or assumption to doubt first.

## Rules for this analysis

1. **Analysis only. Implement nothing.** Do not write source code, do not add tests, do not edit
   `Taskfile.yml`, do not touch `openspec/`. The single report file is your entire output.
2. **Every factual claim carries a `path/to/file:LINE` citation.** A claim you could not verify
   must be labelled `UNVERIFIED` in the text. An unverified value in a handoff is a debugging
   session waiting to happen.
3. **No shorthand.** Write every file path, command, environment variable name, and pass
   criterion out in full. No `...` elisions, no implied prefixes, no "and the usual flags". The
   person executing from your report was not in this conversation and cannot reconstruct intent.
4. **Pass criteria are assertions, not descriptions.** Write "`task check` exits 0 and
   `packages/pricing-engine/tests/` reports at least one passing test" — not "tests should pass".
5. **Synthetic data only.** No protected health information and no real patient, payer, or member
   identifiers in any example you write into the report.
6. **Read before asserting.** The repository is the authority, not your assumptions about how
   Python projects usually work.

## Verification before you finish

Run this exact command and confirm it prints your report path:

    ls -1 .planning/reports/2026-08-21-connector-template-tier-1-gap-analysis.md

PASS criterion: that command exits 0, and your report contains one `## Item` section for every
item listed in the Scope section below, each with all six sub-headings filled in.
