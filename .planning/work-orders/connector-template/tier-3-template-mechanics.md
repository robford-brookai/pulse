# Work Order: Tier 3 gap analysis — what makes it a template

**Programme**: connector-template (pricing-engine as the reference Pulse API connector)
**Tier**: 3 of 3 — the mechanics that turn one good example into a reusable template
**Lane**: analysis only, no implementation
**Model**: opus (this tier decides how ten other connectors get built and reviewed)
**Repository**: `/Users/Rob.Ford/orca/workspaces/pulse/betta`

## Objective

Produce a gap analysis for the five Tier 3 items below: what exists in this repository today,
what options exist to close each gap, and the level of effort for each.

Tier 1 and Tier 2 make `pricing-engine` a good example. Tier 3 is what makes it a **template**:
the mechanics by which ten more connectors get built by other engineers, reviewed without reading
every line, and kept correct as the platform changes. This is the tier most likely to be skipped
and the one whose absence costs the most, because its absence is only discovered when the tenth
connector is already wrong.

## Why this work exists

Rob Ford, 2026-08-21: "I want the pricing-engine to be the best practice template for developing a
Pulse api connector from the other systems that I can demo to the rest of the engineers without
being laughed at. There are as many as 11 depending on how you count them. I need engineering's
help with developing them all except for the pricing-engine connector."

Read that last clause carefully: **Rob builds the pricing-engine connector; Brook's engineers
build the other ten.** Everything in this tier exists to make that division of labour work.

## What a Pulse API connector is

A connector crosses the pulse boundary in exactly one of two sanctioned directions:

- **In:** through the command API (`POST /commands`, `POST /commands:batch`) under the
  connector's own credential. The API derives the `actor` from the bearer credential; a request
  body carrying `actor_type`, `actor_id`, `actor_authority`, or `producer` is rejected outright.
- **Out:** the consumer attaches its own Amazon EventBridge rule and its own Amazon SQS queue to
  the `ocean` event bus.

A connector never reads another application's datastore and never writes to the pulse Postgres
database directly.

## Scope — the five Tier 3 items

### Item 3.1 — A connector conformance suite

The claim to test: there is a shared test suite that any connector runs against itself to prove it
handles replay, rejection, transient retry, cursor resume, and no-protected-health-information
logging — so reviewing a connector means checking that the suite is green rather than reading
every line.

Analyse specifically:
- Establish whether any shared, reusable test suite pattern exists in this repository today. Look
  at `tests/scaffold/` (which validates repository structure, not library behaviour) and at
  whether any `pytest` fixtures or plugins are shared across packages. Report the mechanism if one
  exists, and state plainly if none does.
- Report the technical options for distributing a shared suite to many packages, with the
  trade-off of each. At minimum consider: a `pytest` plugin published as a workspace package that
  connectors depend on; an importable abstract test base class that a connector subclasses; a
  parametrised suite that takes a connector object as a fixture; and a copied test file kept in
  sync by a gate. State which of these keep working when a connector lives in a different
  repository, because some of the eleven systems may not live here.
- Enumerate the exact behaviours the suite should assert. Ground each one in an existing
  specification requirement or test, with a citation. Start from
  `openspec/specs/command-api/spec.md`, `openspec/specs/verdict-declare/spec.md`, and
  `packages/verdict-relay/tests/`.
- Report how a connector would prove no-protected-health-information logging mechanically. There is
  believed to be an existing test that scripts a synthetic value into a payload and asserts it
  never appears in log output; find it, cite it, and say whether the technique generalises.
- Note the constraint that the suite must run offline and credential-free so it can live inside
  `task check`, and report what that forbids.

### Item 3.2 — An explicit anti-patterns document

The claim to test: the template names what not to do and why, so eleven engineers do not each
make the same four mistakes once.

Analyse specifically:
- For each of these four candidate anti-patterns, find where the repository already enforces or
  documents it, and cite it exactly: publishing catalog-subject state to the event bus instead of
  declaring through the command API; writing rows directly into the pulse Postgres database;
  retrying a `rejected` command response; and putting actor fields in a command request body.
- For each one, report whether it fails loudly (a gate catches it, a test fails, the API returns an
  error) or silently. An anti-pattern that fails silently deserves more prominence in the document
  than one a gate already catches, and your report should say which is which.
- Search the repository for anti-patterns already discovered the hard way that belong on this list.
  Read `docs/ci-lessons.md` in full, and skim archived changes under `openspec/changes/archive/`
  for design decisions recorded as rejected alternatives. Report any that a connector author could
  plausibly hit.
- Recommend where the document lives — a section of the connector README, a page under `docs/`, or
  a dedicated file in the connector package — and justify the choice against how the documentation
  site is structured in `mkdocs.yml`.

### Item 3.3 — A migration story for the seven existing bus-emitting connectors

The claim to test: an engineer who already owns one of the seven existing OCEAN-era connectors
knows whether they must rewrite it, wrap it, or leave it alone — and the answer is defensible.

Analyse specifically:
- Read all seven existing connectors under `packages/ocean/services/` — `github-connector`,
  `hubspot-connector`, `impilo-connector`, `linear-connector`, `mongodb-connector`,
  `pocar-connector`, `zcc-connector` — and characterise what each one actually does today: what it
  reads, what it emits, and to which bus domain. A table with citations is the right format.
- For each, classify whether it touches catalog-subject state (and therefore falls under producer
  policy and must move to the command API) or emits only non-subject facts (and may keep emitting
  to the bus). Ground the classification in `packages/pulse-core/src/pulse_core/producer_policy.py`
  and `packages/ocean/docs/producer-policy.md`, and check
  `packages/ocean/producer-policy-suppressions.yaml` for any recorded adjudications.
- Report what the producer-policy gate does today when it finds a violation — does it fail the
  build, warn, or is it advisory? Cite the enforcement point. This determines whether migration is
  forced or voluntary.
- Recommend a migration posture with options: convert all seven, convert only those touching
  subject state, wrap each in a thin declarer, or leave them and apply the template only to new
  connectors. Give the level of effort for each option at the level of "per connector" rather than
  in aggregate, so the total can be computed once the count is settled.

### Item 3.4 — Scale and backpressure notes

The claim to test: the template answers what happens when the source produces faster than the
command API accepts, and an operator knows what a stuck connector looks like.

Analyse specifically:
- Report the batching facilities that exist: `POST /commands:batch` is documented as a command API
  route — find its implementation and report the maximum batch size, the per-request limits, and
  what a partial failure returns. Cite the route handler and the specification.
- Report the retry and backoff behaviour precisely: the exact maximum attempt count, whether
  backoff is jittered, and what happens when attempts are exhausted. Cite the implementation.
- Report what a durable cursor gives a connector operationally: where cursors are stored, how a
  connector resumes, and what a stuck cursor would look like from the outside. Start from
  `packages/pulse-core/src/pulse_core/cursor.py` and the writer-state routes in
  `openspec/specs/command-api-serving/spec.md`.
- Report any existing published limits worth quoting to a connector author: the EventBridge
  `PutEvents` entry size cap is documented in `docs/contracts/consumes.md`, and there may be
  others. Quote them exactly rather than approximately.
- Recommend the content of a short "scale and limits" section: what numbers to state, and which of
  them are currently unknown and would need measurement.

### Item 3.5 — Green continuous integration on the example, and a catalog-version compatibility answer

The claim to test: the example's own continuous integration is visibly green, and the template
answers what a connector author must do when the state catalog version changes.

Analyse specifically:
- Read `.github/workflows/main.yml` and report exactly what runs. Note the standing constraint
  that this workflow must run exactly `task check`, enforced by
  `tests/scaffold/cat4_ci_contract.py`, and that `openspec` and `openlore` are npm globals that
  continuous integration runners do not have, so they belong in `task verify` rather than
  `task check`. Report what adding a new package costs in that workflow, if anything.
- Report whether a status badge exists in any README today, and what it would take to add one
  scoped to the connector.
- Report how the state catalog is versioned and what a consumer must do on a version change. Read
  `openspec/specs/catalog-versioning/spec.md` and `docs/runbooks/catalog-release.md`, and report
  the exact rule for what makes a release breaking versus additive, and what a breaking release
  requires of consumers.
- Report how a connector obtains its command types: whether it imports generated Pydantic models
  from `pulse_core.generated`, and therefore what happens to a connector at a catalog version bump
  — does it break at import, at runtime, or silently keep working against a stale vocabulary? This
  is the single most important finding in this item, because a connector that silently keeps
  working against a stale vocabulary is the failure mode nobody notices.
- Note that a known live constraint may affect any recommendation involving continuous integration
  spend: the GitHub Actions budget on this account has previously been set to zero dollars and
  silently rejected all workflow runs. Report the current state only if you can verify it;
  otherwise mark it `UNVERIFIED` and move on.

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

    .planning/reports/2026-08-21-connector-template-tier-3-gap-analysis.md

Your tier number is `3`. Do not write any other file. Do not create
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

    ls -1 .planning/reports/2026-08-21-connector-template-tier-3-gap-analysis.md

PASS criterion: that command exits 0, and your report contains one `## Item` section for every
item listed in the Scope section below, each with all six sub-headings filled in.
