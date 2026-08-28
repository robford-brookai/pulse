# Work Order: Tier 2 gap analysis — craft

**Programme**: connector-template (pricing-engine as the reference Pulse API connector)
**Tier**: 2 of 3 — the craft an engineer notices on the second read
**Lane**: analysis only, no implementation
**Model**: sonnet
**Repository**: `/Users/Rob.Ford/orca/workspaces/pulse/betta`

## Objective

Produce a gap analysis for the five Tier 2 items below: what exists in this repository today,
what options exist to close each gap, and the level of effort for each. Tier 1 decides whether an
engineer keeps reading; Tier 2 decides whether they respect what they read.

## Why this work exists

Rob Ford, 2026-08-21: "I want the pricing-engine to be the best practice template for developing a
Pulse api connector from the other systems that I can demo to the rest of the engineers without
being laughed at. There are as many as 11 depending on how you count them. I need engineering's
help with developing them all except for the pricing-engine connector."

`pricing-engine` is therefore the **reference implementation** other Brook engineers will copy,
and its audience is people looking for reasons to dismiss PULSE.

## What a Pulse API connector is

A connector crosses the pulse boundary in exactly one of two sanctioned directions:

- **In:** through the command API (`POST /commands`, `POST /commands:batch`) under the
  connector's own credential. The API derives the `actor` from the bearer credential; a request
  body carrying `actor_type`, `actor_id`, `actor_authority`, or `producer` is rejected outright.
- **Out:** the consumer attaches its own Amazon EventBridge rule and its own Amazon SQS queue to
  the `ocean` event bus.

A connector never reads another application's datastore and never writes to the pulse Postgres
database directly.

## Worked precedents to read before you start

- `packages/verdict-relay/` — closest in shape to a connector. Read
  `packages/verdict-relay/src/verdict_relay/mart_reader.py`,
  `packages/verdict-relay/src/verdict_relay/run.py`, and
  `packages/verdict-relay/src/verdict_relay/production.py`.
- `packages/consent-ingress/` — the Customer.io consent ingress.
- `packages/archaeology/src/archaeology/client.py` — the secret-reference credential pattern.
- `CLAUDE.md` at the repository root — the house conventions, including the rule that comments are
  minimal and names are self-documenting.

## Scope — the five Tier 2 items

### Item 2.1 — Comments that explain why, not what

The claim to test: the connector's comments encode constraints a reader cannot see in the code,
and never narrate what the code plainly does.

Analyse specifically:
- Characterise the existing comment style with at least four cited examples of load-bearing
  comments — comments that record a constraint, a rejected alternative, or a footgun. Strong
  candidates to inspect: `packages/verdict-relay/src/verdict_relay/production.py`,
  `packages/pulse-ledger/src/pulse_ledger/fold.py`,
  `packages/pulse-core/src/pulse_core/idempotency.py`, and `catalog/state_catalog.yaml`.
- Report whether any linter or gate currently enforces anything about comments or docstrings, and
  cite the configuration if so. Read `pyproject.toml` for the `[tool.ruff]` section and report
  which rule sets are enabled by exact rule code.
- Two known constraints that belong in a connector's comments, for you to verify and cite exactly
  rather than take from me: first, that `psycopg` version 3 rejects a database URL carrying a
  `+driver` suffix, documented somewhere under `docs/runbooks/`; second, that the writer identity
  is part of the idempotency key, so changing it re-declares everything. Confirm both against the
  repository and give the citation, or mark `UNVERIFIED`.
- Recommend whether comment discipline should be a review standard, a documented rule in the
  connector's own contributing notes, or an automated gate. Say what an automated gate could
  realistically check, given that "why not what" is not mechanically decidable.

### Item 2.2 — A README with a diagram and a five-minute path

The claim to test: a reader who lands on `packages/pricing-engine/README.md` learns what it does,
sees the data flow as a picture, runs it, and knows exactly which lines to change for their own
source system.

Analyse specifically:
- Survey existing package-level README files and report which packages have one, with paths. State
  plainly whether a house pattern exists or whether each is bespoke.
- Report how documentation is published: read `mkdocs.yml` for the navigation structure, and state
  whether package README files are included in the documentation site or live only in the
  repository tree. Note that `mkdocs build -s` treats a broken link as an error, and that
  placeholders in committed documentation must be inline code rather than link syntax.
- Diagram options: establish whether Mermaid diagrams render in this repository's documentation
  site as configured, by citing `mkdocs.yml` configuration. Report the alternatives — a committed
  scalable vector graphic file, a Mermaid fenced block, or ASCII art — with the trade-off of each.
- Recommend the exact section list for the connector README, including where the "change this for
  your system" markers live. Be concrete: name the sections.

### Item 2.3 — Structural conformity

The claim to test: the connector looks like every other package in the workspace, so copying it
teaches the house style rather than a bespoke one.

Analyse specifically:
- Document the canonical package layout by inspecting at least three existing packages. Report the
  exact directory structure, the `pyproject.toml` shape, and how a package is registered as a
  workspace member. Cite the root `pyproject.toml` section that lists workspace members.
- Report every place a new package name must be added for the full gate set to cover it. Search
  `Taskfile.yml` and `tests/scaffold/` and enumerate them with file and line. This list is the
  practical cost of adding any connector, so it must be complete rather than representative.
- Report what `tests/scaffold/cat1_*.py` through `tests/scaffold/cat9_*.py` assert about repository
  structure that a new package could violate. Name the gates by file and what each would catch.
- Note the naming constraint that scaffold gate files must match the `cat[0-9]_*.py` pattern
  configured by `python_files` in `pyproject.toml`, and report whether any similar naming
  constraint applies to package test files.

### Item 2.4 — Observability: structured logs and a receipt

The claim to test: an operator can tell from the logs whether a connector run worked, without
reading source code, and there is exactly one machine-parsable summary line per run.

Analyse specifically:
- Report the existing receipt convention exactly. The verdict relay emits a single summary line;
  find it, quote the exact current format string with all field names, and cite the file and line.
  Note that this format was changed recently from five counts to seven, so verify against the code
  rather than any documentation that may lag.
- Report how structured logging is done: which library, what the tagging convention is (a
  `service:<name>` tag is believed to be used — verify and cite), and whether log levels are used
  consistently.
- Report the no-protected-health-information logging posture and how it is tested. There is
  believed to be a test asserting that a failure log carries no payload value; find it and cite
  it, or mark `UNVERIFIED`.
- Recommend what a connector's receipt line should contain, given that a connector's counts differ
  from a relay's. Propose the exact field list.

### Item 2.5 — Configuration from the environment, failing loudly by name

The claim to test: every required setting comes from an environment variable, a missing one names
itself and stops the process before any network connection is attempted, and no credential value
is ever printed.

Analyse specifically:
- Read `packages/verdict-relay/src/verdict_relay/production.py` and report exactly how
  `resolve_production_config` validates, the exact list of required environment variable names,
  and whether the failure names the first missing variable or all of them.
- Read `packages/archaeology/src/archaeology/client.py` and report the secret-reference pattern in
  full: the exact environment variable names, the reference forms it accepts, and the exact
  exception class names raised. Then read `openspec/specs/archaeology-access/spec.md` and quote
  the binding requirement about credentials never appearing literally in source, tests, fixtures,
  or documentation.
- Report which of the two patterns a new connector should follow — direct environment values as
  the verdict relay does, or secret references as the archaeology package does — and what governs
  the choice. Note the governance line in `docs/process/dispatch-template.md` about secrets
  resolving at runtime from the DuploCloud store.
- Report whether a repository-wide credential-material check exists that a new package would be
  subject to, and cite it.

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

    .planning/reports/2026-08-21-connector-template-tier-2-gap-analysis.md

Your tier number is `2`. Do not write any other file. Do not create
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

    ls -1 .planning/reports/2026-08-21-connector-template-tier-2-gap-analysis.md

PASS criterion: that command exits 0, and your report contains one `## Item` section for every
item listed in the Scope section below, each with all six sub-headings filled in.
