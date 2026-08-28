# Connector Template Gap Analysis — Tier 2 (Craft)

**Programme**: connector-template (pricing-engine as the reference Pulse API connector)
**Tier**: 2 of 3 — the craft an engineer notices on the second read
**Lane**: analysis only, no implementation
**Repository**: `/Users/Rob.Ford/orca/workspaces/pulse/betta`
**Prepared**: 2026-08-22

This report covers the five Tier 2 items in the work order at
`.planning/work-orders/connector-template/tier-2-craft.md`: comments, README/diagram, structural
conformity, observability, and configuration-from-environment. Every claim carries a
`path/to/file:LINE` citation against this repository as it stands on branch
`robford-brookai/billing-state-proposal`. A claim I could not verify is labelled `UNVERIFIED`.

---

## Item 2.1 — Comments that explain why, not what

### Current state

The worked precedents named in the work order do carry load-bearing comments — comments that
record a constraint, a rejected alternative, or a footgun rather than narrating what the next line
of code plainly does. Four cited examples:

1. `packages/verdict-relay/src/verdict_relay/production.py:5` through
   `packages/verdict-relay/src/verdict_relay/production.py:9` — the module docstring states why
   `resolve_production_config` reads every required variable in a fixed order before any
   connection is attempted: "a single missing variable fails startup naming exactly that variable
   … rather than surfacing later as a Snowflake or ledger connection error." This is a rejected
   alternative (fail lazily, at first use) made explicit.
2. `packages/verdict-relay/src/verdict_relay/production.py:11` through
   `packages/verdict-relay/src/verdict_relay/production.py:14` — records that the Snowflake driver
   is imported lazily inside `_snowflake_connect`, and names the consequence: "importing this
   module, constructing a `SnowflakeRowSource` with a fake `connect`, or running any test against
   `FixtureRowSource` never requires the driver installed." This is a constraint a reader cannot
   see from the import statement alone.
3. `packages/verdict-relay/src/verdict_relay/production.py:192` through
   `packages/verdict-relay/src/verdict_relay/production.py:194` — `# max_attempts=1: retry policy
   belongs to the Declarer (declarer.py design decision 4); a client that also retried would
   multiply the attempt budget, exactly what service_client already pins for the same reason.`
   This is a footgun: a reader who "fixes" the client to retry would silently multiply the retry
   budget the declarer already owns.
4. `packages/pulse-core/src/pulse_core/idempotency.py:11` through
   `packages/pulse-core/src/pulse_core/idempotency.py:21` — three numbered design choices for why
   the idempotency pre-image is a JSON document (not concatenated text), canonically serialised,
   and restricted to JSON-native payload values, each with the specific failure it prevents
   (`sha256("referral" + "a:b" + ...)` cannot distinguish `subject_key="a:b"` from
   `subject_type="referral:a"`, at `packages/pulse-core/src/pulse_core/idempotency.py:11`).
5. `packages/pulse-ledger/src/pulse_ledger/fold.py:15` through
   `packages/pulse-ledger/src/pulse_ledger/fold.py:19` — records why `to_state` lives in the
   event's `payload` rather than a column of its own, and names the exact site to change if that
   ever changes: "`TO_STATE_KEY` names it in one place, so a later schema revision promoting it to
   a column has one call site to change."
6. `catalog/state_catalog.yaml:34` through `catalog/state_catalog.yaml:36` and
   `catalog/state_catalog.yaml:55` through `catalog/state_catalog.yaml:57` — record a ratified
   business decision with its date ("Ratified 2026-08-03 (doc_update, pulse-ledger-core)") rather
   than describing the YAML structure itself.

**Linter/gate enforcement of comments or docstrings**: nothing enforces comment content or
presence. The `[tool.ruff.lint]` `select` list at `pyproject.toml:153` through `pyproject.toml:184`
enables exactly these rule-code prefixes: `YTT`, `S`, `B`, `A`, `C4`, `T10`, `SIM`, `I`, `C90`, `E`,
`W`, `F`, `PGH`, `UP`, `RUF`, `TRY`. Ruff's docstring rule set is `D` (pydocstyle); it does not
appear in this list, so no docstring-presence or docstring-content rule is active anywhere in this
repository. There is no separate comment linter configured elsewhere in `pyproject.toml` or
`Taskfile.yml`.

**The two named constraints**, verified:

- **psycopg v3 rejects a `+driver` suffix**: confirmed at
  `docs/runbooks/pulse-command-api-deploy.md:100` — "`DATABASE_URL` | Plain
  `postgresql://pulse_ledger_app:<password>@<rds-host>/pulse_ledger` — **psycopg v3 does not
  understand a `+driver` suffix** (`api_server.py`'s and `relay_worker.py`'s module docstrings both
  record this; `psycopg.connect()` on a SQLAlchemy-style DSN fails to connect, not silently
  misconfigures)." The same runbook line also records a second, related decision at
  `docs/runbooks/pulse-command-api-deploy.md:101`: a distinct `ALEMBIC_DATABASE_URL` key carries
  the `postgresql+psycopg://` form for Alembic, kept as two keys deliberately rather than one key
  plus prefix-stripping, because "the `+driver` footgun is exactly what a 'strip this prefix before
  use' step would reintroduce the first time someone forgets it."
- **Writer identity is part of the idempotency key**: confirmed at
  `packages/pulse-core/src/pulse_core/idempotency.py:3` — "The key is
  `{writer_id}:{sha256(subject, command_type, payload, logical_time)}`" — and at
  `packages/pulse-core/src/pulse_core/idempotency.py:97` through
  `packages/pulse-core/src/pulse_core/idempotency.py:108`, where `derive_idempotency_key` prefixes
  every derived key with the caller's `writer_id`. Because the key's first half is the writer id
  verbatim, changing a connector's writer id changes the key of every fact it has ever declared,
  which the ledger's unique constraint treats as a first-time declaration rather than a repeat —
  in the work order's words, it "re-declares everything." This is stated as design intent in
  `packages/verdict-relay/src/verdict_relay/production.py:29` through
  `packages/verdict-relay/src/verdict_relay/production.py:33`: "This relay's own D15 writer
  identity … A design-time constant, not configuration: every deploy of this relay is this one
  writer."

**One discrepancy to flag**: the work order's "Worked precedents" section cites "`CLAUDE.md` at
the repository root — the house conventions, including the rule that comments are minimal and
names are self-documenting" as an existing house convention. I read the full file at
`/Users/Rob.Ford/orca/workspaces/pulse/betta/CLAUDE.md` (126 lines) and grepped it, `AGENTS.md`,
`docs/process/dispatch-template.md`, and `docs/ci-lessons.md` for the words "comment" and
"self-document" — none of those four files contains any such rule. **UNVERIFIED as a repository
convention**: the "minimal comments, self-documenting names" instruction exists in the operator's
personal global Claude Code configuration (outside this repository, not committed here), not in
this repository's own `CLAUDE.md`. The comment style actually practiced in this repository (the
six examples above) is the opposite of minimal — it is deliberately dense, "why not what" prose,
which is a stronger and more specific convention than "minimal" would suggest. A connector README
or contributing note that cites this repository's `CLAUDE.md` for comment style would be citing a
document that does not say what it is claimed to say.

### Gap

`pricing-engine` does not exist yet as a package, so it has zero comments of any kind. The gap is
not "improve existing comments" but "establish, from a blank file, the same why-not-what discipline
demonstrated in `production.py`, `idempotency.py`, and `fold.py,`" with no automated check to catch
a regression into what-comments, and no written rule inside the connector's own tree that a copying
engineer would see before writing their first comment.

### Options

1. **Review standard only** (a line in the PR review checklist or `docs/ci-lessons.md`-style
   residue doc): costs nothing to build, catches nothing automatically, relies entirely on the
   reviewer having read the precedent files. Consistent with how the existing precedent packages
   themselves reached this quality — no gate produced `production.py`'s comments, a human writing
   with the pattern in view did.
2. **A documented rule in the connector's own contributing notes** (e.g., a "Comment discipline"
   section in `packages/pricing-engine/README.md` or a `packages/pricing-engine/CONTRIBUTING.md`,
   quoting one or two of the load-bearing examples above as the pattern to copy): costs one
   paragraph and zero new tooling, is visible to exactly the audience that matters (an engineer
   about to copy this package), but is still unenforced — a later PR can add narrating comments
   and nothing objects.
3. **An automated gate**: given that "why not what" is not mechanically decidable (a linter cannot
   tell a comment that explains a constraint from one that restates the line below it), the only
   things a gate could realistically check are proxies, not the property itself: (a) a minimum
   module-docstring length or presence per public module (crude, and easy to satisfy with padding
   that adds no information), (b) a ban on comments that are near-duplicates of the identifier or
   statement they annotate (a heuristic, not a semantic check, and prone to false positives on
   short clarifying comments), (c) a required cross-reference token (e.g., every comment mentioning
   a footgun must cite a spec/ADR/runbook path) — enforceable by regex, but only catches the
   presence of a citation, not whether the comment actually explains anything. All three proxies
   are cheap to defeat and would add ongoing false-positive noise to a repository that currently
   has zero such gates.

### Recommendation

Option 2 — a documented rule in the connector's own README or contributing notes, quoting the
precedent examples verbatim, rather than a repository-wide automated gate. The property the work
order is testing ("why not what") is explicitly non-mechanical by the work order's own framing;
spending effort on option 3's proxies would buy false confidence rather than the actual discipline,
and this repository's existing quality (all six cited examples) was produced by human judgment
against a visible precedent, not by a gate.

### Level of effort

`S` — writing the comment-discipline paragraph and selecting the two or three quoted precedent
examples is one file, mechanical, and the pattern to copy already exists in-repo; no new
dependency or concept is introduced.

### Dependencies and risks

Depends on `packages/pricing-engine/README.md` (Item 2.2) existing as the place to put the rule,
or on a decision to instead put it in a separate `CONTRIBUTING.md` — that placement decision should
be made once, not per-connector, since ten more connectors are coming. The risk that could make
this fail silently: a reviewer skims the "why not what" rule once at connector creation and never
re-applies it on later PRs to the same package, since nothing re-checks it. If this discipline
degrades, the first value to doubt is whether the connector's comments still cite the constraint
(a runbook path, a spec name, a rejected alternative) rather than merely being present — presence
is trivially satisfiable and proves nothing on its own.

---

## Item 2.2 — A README with a diagram and a five-minute path

### Current state

**Which packages have a README today**, established by searching `packages/*/README.md`:

- `packages/archaeology/README.md` exists.
- `packages/ocean/README.md` exists.
- `packages/twenty-app/README.md` exists.
- `packages/twenty-model/README.md` exists.
- `packages/consent-ingress`, `packages/identity`, `packages/pulse-core`, `packages/pulse-ledger`,
  `packages/schedules`, `packages/synthea-seed`, `packages/twenty-projection`, and
  `packages/verdict-relay` — the package closest in shape to a connector, per the work order's own
  "Worked precedents" section — have **no** `README.md` under their package root. This was
  established by running `find packages -maxdepth 2 -iname "README.md"` against the full
  `packages/` tree and cross-checking the result against `find packages -maxdepth 1 -mindepth 1
  -type d`, which lists all twelve top-level package directories.

**No house pattern exists.** Four of twelve packages have a README at all, and of those four,
`packages/archaeology/README.md` is structured prose (inherited-pattern section, a hard
precondition callout, an environment-variable table) with no diagram of any kind — I read the full
file and it contains zero fenced diagram blocks and zero embedded images. Each existing README is
bespoke to its package rather than following a shared template; there is no
`templates/PACKAGE_README.md` or equivalent scaffold in this repository (searched `templates/` at
the repository root, which contains only `templates/HANDOFF.md` per `CLAUDE.md:63` through
`CLAUDE.md:64`).

**How documentation is published**: `mkdocs.yml:10` through `mkdocs.yml:24` defines the entire
navigation tree: `Home` (`index.md`), `Architecture` (`architecture.html`), `Modules`
(`modules.md`), and nine `Runbooks` pages under `docs/runbooks/`. No package-level `README.md`
file — not `packages/archaeology/README.md`, not any other — appears anywhere in this `nav:` block.
Package README files therefore live only in the repository tree today; they are not part of the
built documentation site (`mkdocs build -s`, the strict build `task check` runs, only processes
what `nav:` and the `mkdocstrings` handler at `mkdocs.yml:27` through `mkdocs.yml:30` reach, and
that handler's `paths:` is `["src/pkg_pulse"]` only — no `packages/` path is configured for
`mkdocstrings` either).

**Diagram rendering**: Mermaid does **not** render in this repository's documentation site as
currently configured. Rendering a ```` ```mermaid ```` fenced block through `mkdocs-material`
requires `pymdownx.superfences` configured with a custom fence for the `mermaid` language (the
documented mkdocs-material mechanism). The `markdown_extensions:` block at `mkdocs.yml:60` through
`mkdocs.yml:64` lists exactly two extensions — `toc` (with `permalink: true`) and
`pymdownx.arithmatex` (for math, not diagrams) — and does **not** list `pymdownx.superfences` at
all. A ```` ```mermaid ```` fence committed today would build as an inert, unstyled code block, not
a diagram, under `mkdocs build -s`. Two design documents already use Mermaid —
`design/migration/rpc-object-model-assessment.md` and
`design/migration/ocean-to-pulse-adaptation-plan.md`, found by `grep -rl mermaid design/` — but
neither file is reachable from this reasoning either way, because `design/` is not part of the
`mkdocs.yml` `nav:` tree at all; those two files are read as raw Markdown in the git tree, never
built by `mkdocs`.

The alternatives, with trade-offs:

- **A committed scalable vector graphic (SVG) file**, referenced by `![...](diagram.svg)`: renders
  correctly in the built site and in the raw GitHub/GitLab file view with no `mkdocs.yml` change,
  but is not text-diffable — a reviewer cannot read what changed in a PR without opening the file,
  and it must be hand-edited or regenerated by an external tool (not committed to this repo) rather
  than edited alongside the code.
- **A Mermaid fenced block**: text-diffable and edited in the same PR as the code, but does not
  render as a diagram today (see above) unless `pymdownx.superfences` is added to `mkdocs.yml`,
  which is a one-line repository-wide change to a shared config file, not a per-connector change —
  and per `cat1_structure.py` and the docs-consistency gate `cat8_docs_consistency.py`, any change
  to `mkdocs.yml` should be checked against `task check`'s `docs` step (see `Taskfile.yml`'s docs
  area) before it is assumed safe.
- **ASCII art**: renders identically everywhere (terminal, raw file view, built site, GitHub) with
  zero tooling dependency, but is the least legible for anything beyond a handful of boxes and
  arrows, and is the most tedious to keep in sync by hand as the diagram grows.

### Gap

`packages/pricing-engine/README.md` does not exist. Even setting aside pricing-engine, there is no
existing README in this workspace — including the ones in the four packages that have one — that
combines a rendered data-flow diagram with a runnable quickstart, so there is no in-repo README to
copy wholesale; the connector's README has to be written from a section list, not lifted from a
precedent file.

### Options

1. **ASCII art diagram, inline in the README, no `mkdocs.yml` change**: zero new dependency, works
   in every rendering context including a raw `cat` of the file, and matches the fact that
   `design/` documents using Mermaid are already excluded from the built site — so choosing an
   approach that needs no build-time support is consistent with what already exists. Cost: someone
   maintains the ASCII by hand as the flow changes.
2. **Mermaid fence plus a `pymdownx.superfences` addition to `mkdocs.yml`**: gives every future
   connector README (and the two existing `design/` documents, if they are ever added to `nav:`) a
   real rendered diagram, and keeps the diagram source text-diffable in code review. Cost: this is
   a shared-file change (`mkdocs.yml`) that affects the whole repository's doc build, so it should
   land once, deliberately, ahead of or alongside the first connector README — not be treated as
   part of "write one README."
3. **Committed SVG**: highest visual polish with zero `mkdocs.yml` change, but not diffable and
   needs an external tool this repository does not currently invoke anywhere (no `dot`, `mermaid-
   cli`, or similar is referenced in `Taskfile.yml`), so it would be the first such dependency.

### Recommendation

Option 2 — add `pymdownx.superfences` to `mkdocs.yml` once, then use Mermaid fences in the
connector README. It is the only option that is both diffable in review and renders as a real
picture in the published site, and the one-line config addition benefits every future connector
README (there are as many as eleven, per the work order's "Why this work exists" section) rather
than being redone per package. Do this as its own small, explicit change — not silently inside the
first connector's PR — since it touches a file every package's docs build depends on.

**Recommended README section list** for `packages/pricing-engine/README.md`, concrete:

1. `# pricing-engine` — one-sentence description of what the connector does and which direction it
   crosses the pulse boundary (command API in, per the work order's "What a Pulse API connector
   is" section).
2. `## Data flow` — the Mermaid diagram: source system to connector to `POST /commands` /
   `POST /commands:batch`, showing the connector's own credential and that no `actor_type`,
   `actor_id`, `actor_authority`, or `producer` field is ever sent in the request body.
3. `## Quickstart` — the exact commands to run it locally against a fixture, mirroring
   `README.md:7` through `README.md:10`'s repository-level pattern (`task install`, `task check`),
   plus whatever `task`-scoped target the connector itself registers.
4. `## Configuration` — the environment variable table (see Item 2.5 for the exact pattern to
   follow), each row naming the variable, whether it is required, and its meaning — no values,
   consistent with `packages/archaeology/README.md`'s existing table format.
5. `## Adapting this connector for your source system` — the "change this for your system"
   markers: name the exact files and functions a new connector author edits (the row-source
   fetch implementation, the field-mapping/declaration logic, and the environment variable
   names), each marked inline as a placeholder using inline code per this repository's own rule
   at `CLAUDE.md:98` through `CLAUDE.md:99` — "Placeholders in committed documentation must be
   inline code, never link syntax" — because `mkdocs build -s` treats a broken link as an error.
6. `## Observability` — what the receipt line looks like and where structured logs are tagged (see
   Item 2.4), so an operator reading the README knows what "it worked" looks like before ever
   running it.
7. `## Testing` — how to run this package's own test suite (`uv run pytest packages/pricing-
   engine/tests/`) and what the coverage floor is, following the per-package floor pattern set at
   `Taskfile.yml:145` through `Taskfile.yml:148`.

### Level of effort

`M` — the README content itself is one file and mechanical once the section list above is fixed,
but the `pymdownx.superfences` addition to `mkdocs.yml` plus verifying `mkdocs build -s` still
passes strictly (no broken links, correctly fenced diagram) touches a shared config file and needs
a documentation-build gate to be re-run, which is more than a single-file, no-new-concept change.

### Dependencies and risks

The `mkdocs.yml` change should land before or alongside the first connector README, not be
improvised inside that PR, because it affects every package's doc build and needs its own review.
Risk: `mkdocs build -s` is strict about broken links (`CLAUDE.md:98` through `CLAUDE.md:99`), so a
placeholder path or an incorrectly closed Mermaid fence can turn a documentation change into a red
`task check`; the value to doubt first if the doc build fails silently in a warning-tolerant runner
is whether `-s` (strict) is actually the flag in use, since a non-strict build would hide exactly
this class of error.

---

## Item 2.3 — Structural conformity

### Current state

**Canonical package layout**, established by inspecting `packages/verdict-relay/`,
`packages/archaeology/`, and `packages/consent-ingress/` directly (directory listings and full
`pyproject.toml` reads):

- `packages/<name>/pyproject.toml` — a `[project]` table with `name`, `version`, `description`,
  `requires-python = ">=3.10,<4.0"`, and `dependencies`; a `[tool.uv.sources]` table only when the
  package depends on another workspace package (`packages/verdict-relay/pyproject.toml:16` through
  `packages/verdict-relay/pyproject.toml:17`, and `packages/consent-ingress/pyproject.toml:18`
  through `packages/consent-ingress/pyproject.toml:19`, both pinning `pulse-core = { workspace =
  true }`; `packages/archaeology/pyproject.toml` has no such table because it depends on nothing
  in-workspace); a `[dependency-groups]` `dev` list (each of the three includes
  `pytest-socket>=0.7.0` to enforce no live network, and `pyright>=1.1.390` for per-package strict
  type checking); `[build-system]` = `hatchling`; `[tool.hatch.build.targets.wheel]` `packages =
  ["src/<import_name>"]`; `[tool.pytest.ini_options]` `testpaths = ["tests"]`; and
  `[tool.pyright]` `include = ["src", "tests"]`, `typeCheckingMode = "strict"`.
- `packages/<name>/src/<import_name>/` — the importable package, with `__init__.py` and a
  `py.typed` marker file present in every one of the three inspected packages
  (`packages/verdict-relay/src/verdict_relay/py.typed`,
  `packages/archaeology/src/archaeology/py.typed`,
  `packages/consent-ingress/src/consent_ingress/py.typed`).
- `packages/<name>/tests/` — a flat `test_*.py` layout plus a `conftest.py`; `verdict-relay` and
  `archaeology` additionally carry a `tests/fixtures/` (verdict-relay) directory of JSON fixture
  files.
- Package registration: the root `pyproject.toml`'s `[tool.uv.workspace]` table, at
  `pyproject.toml:61` through `pyproject.toml:76`, lists every workspace member by path (twelve
  entries today: `packages/archaeology`, `packages/pulse-ledger`, `packages/pulse-core`,
  `packages/verdict-relay`, `packages/schedules`, `packages/identity`, `packages/consent-ingress`,
  `packages/synthea-seed`, `packages/twenty-projection`, `packages/ocean`,
  `packages/ocean/libs/ocean-events`, `packages/ocean/libs/ocean-broker`,
  `packages/ocean/libs/ocean-connector-mcp`), and the paired `[tool.uv.sources]` table at
  `pyproject.toml:78` through `pyproject.toml:90` maps each package name to `{ workspace = true }`.
  A new connector must appear in both tables, by exact package name, or `uv sync` will not resolve
  it as a workspace member.

**Every place a new package name must be added for the full gate set to cover it**, enumerated by
searching `Taskfile.yml` and `tests/scaffold/` for existing package names (`verdict-relay`,
`archaeology`, `consent-ingress`, etc.) as a proxy for what a new connector name would also need to
be added to:

1. `pyproject.toml:62` through `pyproject.toml:76` — `[tool.uv.workspace]` `members` list.
2. `pyproject.toml:79` through `pyproject.toml:90` — `[tool.uv.sources]` mapping.
3. `Taskfile.yml:19` — `LINT_PATHS` variable: `src tests packages/archaeology packages/pulse-ledger
   packages/pulse-core packages/verdict-relay packages/schedules packages/identity
   packages/consent-ingress packages/synthea-seed packages/twenty-projection packages/ocean`. A new
   connector's `src` and `tests` directories must be appended here or `task lint` never sees them.
4. `Taskfile.yml:31` — `TESTED_PATHS` variable, the equivalent list for `task test`
   (`tests packages/archaeology/tests packages/pulse-ledger/tests packages/pulse-core/tests
   packages/verdict-relay/tests packages/schedules/tests packages/identity/tests
   packages/consent-ingress/tests packages/synthea-seed/tests packages/twenty-projection/tests
   packages/ocean/libs`).
5. `Taskfile.yml:44` — `COV_PATHS` variable, the `--cov=` flags passed to `task test`:
   `--cov=src/pkg_pulse --cov=packages/archaeology/src --cov=packages/pulse-ledger/src
   --cov=packages/pulse-core/src --cov=packages/verdict-relay/src --cov=packages/schedules/src
   --cov=packages/identity/src --cov=packages/consent-ingress/src --cov=packages/synthea-seed/src
   --cov=packages/twenty-projection/src --cov=packages/ocean/libs/ocean-events/src
   --cov=packages/ocean/libs/ocean-broker/src`. A connector's `src/` must be added here to be
   measured for coverage at all.
6. `Taskfile.yml:127` through `Taskfile.yml:133` — the `typecheck` task's explicit
   `uv run pyright -p packages/<name>` invocation lines, one per package that typechecks under
   pyright strict rather than the root `mypy` pass (currently `packages/archaeology`,
   `packages/verdict-relay`, `packages/schedules`, `packages/identity`,
   `packages/consent-ingress`, `packages/synthea-seed`, `packages/twenty-projection`). A connector
   following the verdict-relay/archaeology pattern needs its own line added here.
7. `Taskfile.yml:145` through `Taskfile.yml:148` — the `test` task's per-package coverage-floor
   enforcement lines, e.g. `uv run coverage report --include="packages/verdict-relay/src/*"
   --fail-under=85`. A connector that wants its own enforced floor (rather than only the workspace
   default `fail_under = 80` at `pyproject.toml:144`) needs its own line here.
8. `tests/scaffold/cat8_docs_consistency.py:546` — an existing gate that asserts
   `"verdict_relay/config.py" in consumes`, i.e. checks that `docs/contracts/consumes.md` cites the
   specific module where verdict-relay registers its verdict types. This is package-specific, not
   generic; it demonstrates that `cat8_docs_consistency.py` may need a symmetrical new assertion
   added for a connector that registers comparable contract-facing configuration, though nothing
   in the gate as written today generically covers "any new package."
9. `mkdocs.yml` — no current line references any package by name (the `mkdocstrings` handler's
   `paths:` at `mkdocs.yml:30` is `["src/pkg_pulse"]` only), so a connector is not implicitly
   covered by the documentation build unless it is added there or its README is added to `nav:`
   (see Item 2.2).

This list is presented as complete rather than representative, per the work order's instruction,
based on an exhaustive grep of `Taskfile.yml` and every file under `tests/scaffold/` for the six
existing non-`ocean`, non-`pulse-core`/`pulse-ledger` package names. `packages/ocean` and its three
sub-packages are excluded from several of the lists above (e.g., `TYPED_PATHS`, some `pyright`
lines) because ocean typechecks and covers differently — see
`pyproject.toml:210` through `pyproject.toml:225` for ocean's dedicated ruff exemptions, which is a
further, ocean-specific registration surface a *generic* new connector should not need to touch.

**What `cat1_structure.py` through `cat9_golden_workflow.py` assert that a new package could
violate**, named by file (the nine gates' summary is stated at `CLAUDE.md:78` through
`CLAUDE.md:80`: "structure → toolchain → config → command/CI contract → glue logic → edge cases →
hooks → docs consistency → golden end-to-end"):

- `tests/scaffold/cat1_structure.py` — asserts (among other things) that the package layout
  declared in `[tool.hatch.build.targets.wheel].packages` matches what actually exists on disk
  (`tests/scaffold/cat1_structure.py:141` through `tests/scaffold/cat1_structure.py:144`,
  `test_package_layout_matches_manifest`), and that every declared package ships a `py.typed`
  marker (`tests/scaffold/cat1_structure.py:148` through `tests/scaffold/cat1_structure.py:151`,
  `test_package_ships_a_pep561_marker`). A connector added to `[tool.hatch.build...]` without a
  `py.typed` file, or with a path that does not exist, fails this gate. It also asserts
  `test_single_source_package` (`tests/scaffold/cat1_structure.py:165` through
  `tests/scaffold/cat1_structure.py:168`) for the top-level `src/` (not per-connector), and that
  every path the root `README.md`'s target-tree fence promises actually exists and is git-tracked
  (`tests/scaffold/cat1_structure.py:100` through `tests/scaffold/cat1_structure.py:105`) — so
  adding a connector to the README's target tree without creating the matching files/directories
  fails this gate too.
- `tests/scaffold/cat2_toolchain.sh` — a shell script gate; not read in full for this report, but
  by its position in the "toolchain" stage of the pipeline it is the gate most likely to catch a
  new package whose declared tool versions or lockfile state disagree with the workspace.
- `tests/scaffold/cat3_config_validity.py` — the "config" stage; likely to catch a connector's
  `pyproject.toml` if it is malformed or omits a required table, though this was not traced line by
  line for this report.
- `tests/scaffold/cat4_ci_contract.py` and `tests/scaffold/cat4_command_contract.sh` — assert that
  every `run:` command in `.github/workflows/main.yml` resolves to a defined Taskfile target or an
  installed tool (`CLAUDE.md:87` through `CLAUDE.md:88`). A connector that needs a new CI step not
  wired through `task check` would fail this gate by construction.
- `tests/scaffold/cat5_glue_logic.py` — the largest gate file (37,689 bytes) covering
  `scripts/dispatch_tasks.py` / `scripts/collect_handoffs.py` glue logic; not established to touch
  per-package registration directly, but is the most likely gate to break on any structural change
  to how work orders or handoffs reference packages by name.
- `tests/scaffold/cat6_edge_cases.py` — edge-case coverage of the scaffold itself.
- `tests/scaffold/cat7_gates_hooks.sh` — pre-commit hook wiring, including `openlore drift`
  (`CLAUDE.md:58`).
- `tests/scaffold/cat8_docs_consistency.py` — asserts cross-references between code and docs stay
  true, including the verdict-relay/`consumes.md` example at
  `tests/scaffold/cat8_docs_consistency.py:546` cited above, and an `artifact_path` reference for
  `packages/twenty-app/artifact/operations.json` at
  `tests/scaffold/cat8_docs_consistency.py:310`. A connector that documents itself inconsistently
  with its own code risks tripping a similarly-shaped assertion once one is added for it.
- `tests/scaffold/cat9_golden_workflow.py` — golden end-to-end workflow validation; not traced
  line-by-line for this report, but by its position last in the pipeline it is the gate most
  likely to exercise a full `propose → … → archive` cycle against whatever packages exist.

**Naming constraint on scaffold gate files**: confirmed at `pyproject.toml:126` —
`python_files = ["test_*.py", "cat[0-9]_*.py"]` inside `[tool.pytest.ini_options]`, with the
comment at `pyproject.toml:123` through `pyproject.toml:125` explaining why: "the scaffold gates
are named `cat1_structure.py` .. `cat9_golden_workflow.py` so the filename states which gate it is.
Without this they match no default pattern and are silently skipped by `task test` and CI." **No
equivalent constraint applies to package test files.** Each of the three inspected packages' own
`[tool.pytest.ini_options]` (`packages/verdict-relay/pyproject.toml:39` through
`packages/verdict-relay/pyproject.toml:40`, `packages/archaeology/pyproject.toml:33` through
`packages/archaeology/pyproject.toml:34`, `packages/consent-ingress/pyproject.toml:39` through
`packages/consent-ingress/pyproject.toml:40`) sets only `testpaths = ["tests"]` with no
`python_files` override, so package tests rely on pytest's ordinary default collection pattern
(`test_*.py` / `*_test.py`), which is what every existing package's test files already follow
(e.g., `packages/verdict-relay/tests/test_declarer.py`,
`packages/archaeology/tests/test_client.py`). A connector's tests need no special filename pattern
beyond that default.

### Gap

`pricing-engine` does not exist as a package, so none of the nine registration points above are
populated for it, and none of the nine scaffold gates has ever run against it. The gap is the full
checklist above, applied once, plus (per item 8) a judgment call on whether `cat8_docs_consistency`
needs a new connector-specific assertion mirroring the verdict-relay one, which the existing gate
set does not generically provide.

### Options

1. **Copy `packages/verdict-relay/` wholesale as the starting point, then rename**: lowest
   mechanical cost since every file in the earlier "canonical package layout" list already exists
   in the right shape (pyproject.toml table set, `py.typed`, `tests/` layout), and it is the
   package the work order itself names as closest in shape to a connector. Cost: verdict-relay is
   a *relay* (Snowflake mart → ledger), not a *connector* in the strict "external system → command
   API" sense the work order defines; copying it means immediately deleting or rewriting the
   Snowflake-specific `mart_reader.py` and `production.py` machinery, which risks leaving stale
   Snowflake-shaped comments or naming behind if the rename pass is incomplete.
2. **Copy `packages/consent-ingress/` instead**: it is already a forward-declaring ingress
   package (Customer.io → `record_communication_consent` commands) rather than a mart-reading
   relay, which is structurally closer to what most of the eleven prospective connectors will look
   like (an external system posting commands, not a warehouse read). Cost: it is a narrower
   precedent (one command type, one subject) than verdict-relay's multi-outcome declarer, so some
   of pricing-engine's own logic (whatever `pricing-engine` actually needs to declare) will still
   be written from scratch rather than adapted.
3. **Write a `packages/pricing-engine/` from the checklist above with no single copy-source**:
   avoids carrying over any package-specific naming or comments that a copy-then-rename pass might
   miss, but is strictly more work than option 1 or 2 for no additional correctness, since the
   checklist above was itself derived from these existing packages.

### Recommendation

Option 2 — start from `packages/consent-ingress/`'s shape, not `packages/verdict-relay/`'s,
despite the work order naming verdict-relay as the closest precedent. Verdict-relay's core job is
reading a Snowflake mart and declaring verdicts from it; a connector as the work order defines it
("crosses the pulse boundary … through the command API under the connector's own credential")
is structurally the *ingress* half of what verdict-relay does, and consent-ingress is a real,
tested, in-repo example of exactly that half, without the Snowflake-mart machinery a strict
external-system connector will not need. Use verdict-relay only for the pieces the work order
separately calls out — the credential/configuration pattern (Item 2.5) and the receipt/logging
pattern (Item 2.4) — both of which consent-ingress also implements but which verdict-relay's
`production.py` documents most explicitly.

### Level of effort

`L` — this is a new package: it must be added to the root `[tool.uv.workspace]` and
`[tool.uv.sources]` tables, to five separate `Taskfile.yml` variables/task blocks, and it will be
exercised by all nine `tests/scaffold/cat*` gates for the first time, at least one of which
(`cat8_docs_consistency.py`) may need a new assertion written for it — this is exactly the "new
package, new gate, or touches a shared/serial file that other work must sequence around" case the
level-of-effort scale names for `L`.

### Dependencies and risks

Every one of the nine Taskfile/scaffold registration points above must land in the same change,
or `task check` will not actually cover the new package end-to-end even though the package exists
(e.g., forgetting `COV_PATHS` means the package is never measured for coverage, which fails
silently — `task test` still exits 0). Because `Taskfile.yml`'s `LINT_PATHS`, `TESTED_PATHS`, and
`COV_PATHS` are shared variables that every other package's gate run also depends on, this is a
serial file other in-flight work must sequence around, consistent with the `L` label's own
definition. If this item fails silently, the value to doubt first is whether `COV_PATHS` was
actually updated — a missing coverage flag produces a fully green `task check` with the new
connector completely unmeasured, which is the quietest possible failure mode here.

---

## Item 2.4 — Observability: structured logs and a receipt

### Current state

**The receipt convention, verified against code rather than any lagging documentation**: the
verdict relay's single summary line is built by `RunReceipt.summary_line()` at
`packages/verdict-relay/src/verdict_relay/run.py:92` through
`packages/verdict-relay/src/verdict_relay/run.py:100`. The exact current format string, quoted in
full:

```
service={SERVICE} result={result} declared={self.declared} replayed={self.replayed} skipped_stale={self.skipped_stale} rejected={self.rejected} transitioned={self.transitioned} transition_rejected={self.transition_rejected} failed={self.failed}
```

That is nine `key=value` pairs: `service`, `result`, and the seven counts named in the module
docstring at `packages/verdict-relay/src/verdict_relay/run.py:6` through
`packages/verdict-relay/src/verdict_relay/run.py:7` — "declared, replayed, skipped-stale, rejected,
transitioned, transition-rejected, failed." This confirms the work order's note that the format
changed from five counts to seven: the current code carries seven distinct count fields
(`declared`, `replayed`, `skipped_stale`, `rejected`, `transitioned`, `transition_rejected`,
`failed`), verified directly against `run.py`, not against any document that might lag it.

**Structured logging**: stdlib `logging`, not a third-party structured-logging library. The
formatter is `ServiceJsonFormatter` at `packages/verdict-relay/src/verdict_relay/run.py:46` through
`packages/verdict-relay/src/verdict_relay/run.py:56`, which emits one JSON object per line with
keys `timestamp`, `level`, `logger`, `message`, and `service`. The tagging convention is **not**
literally a colon-form `service:<name>` string tag — it is a JSON object field named `"service"`
whose value is the constant `SERVICE = "verdict-relay"` (`packages/verdict-relay/src/verdict_relay/
run.py:38`), so every structured log record carries `"service": "verdict-relay"` as a JSON
key/value pair, and the one non-JSON summary line carries the equivalent information as the
`service=verdict-relay` `key=value` token quoted above. The module docstring's own description at
`packages/verdict-relay/src/verdict_relay/run.py:10` through
`packages/verdict-relay/src/verdict_relay/run.py:11` calls this "every record tagged
`service:verdict-relay`" using a colon in prose, but the actual emitted artifact (both the JSON
records and the `key=value` summary line) uses `=` / JSON key-value pairs, not a literal colon-
separated tag string. **Verified with a caveat**: the *concept* (every record and the summary line
identify the emitting service by name) is confirmed; the *literal punctuation* `service:<name>` as
a searchable substring is not what appears in the emitted text — `service=` and `"service":` are.
Log levels are used consistently within `run.py`: `logger.exception` on a `DeclarerError` or
`MartContractError` (`packages/verdict-relay/src/verdict_relay/run.py:134`), `logger.info` for the
summary line itself (`packages/verdict-relay/src/verdict_relay/run.py:147`), and
`configure_logging` pins the package logger to `logging.INFO`
(`packages/verdict-relay/src/verdict_relay/run.py:69`).

**No-PHI logging posture, tested**: confirmed. `packages/verdict-relay/tests/test_run.py:260`
through `packages/verdict-relay/tests/test_run.py:276` defines
`test_log_records_carry_subject_keys_only`, which runs a mixed-outcome batch through `run_relay`,
lower-cases the captured log stream, asserts the subject-key marker `"episode-"` is present (rows
are legitimately named by subject key), then asserts none of a list of demographic marker strings
(a `DEMOGRAPHIC_MARKERS` tuple ending in `"mrn"`, `"zip_code"` as shown at
`packages/verdict-relay/tests/test_run.py:255` through
`packages/verdict-relay/tests/test_run.py:257`) and none of the three outcome values (`"positive"`,
`"negative"`, `"indeterminate"`, `OUTCOME_VALUES` at
`packages/verdict-relay/tests/test_run.py:258`) appear anywhere in the log output. Two further
tests reinforce the same posture for a specific rejection path:
`packages/verdict-relay/tests/test_coverage_first_declare.py:99` and
`packages/verdict-relay/tests/test_coverage_first_declare.py:117`, both named
`test_a_rejected_..._logs_the_subject_key_and_never_the_payer_value`. This is not `UNVERIFIED` — it
is directly confirmed by test code.

### Gap

`pricing-engine` has no receipt, no structured-log formatter, and no PHI-safety test, because it
does not exist. Beyond simply not existing, the gap that matters for craft is that a connector's
natural counts are not the relay's seven — a connector posting commands to the ledger does not
have "replayed" or "transition_rejected" concepts in the same shape a mart-reading relay does; a
receipt field list copied verbatim from `run.py` would carry fields that do not mean anything for
a connector and omit at least one a connector needs (a distinct "duplicate/idempotent-replay"
count driven by the command API's own 409-style response, which is a different mechanism than the
relay's watermark-based replay detection).

### Options

1. **Copy the relay's exact seven-field receipt verbatim**: minimal effort, immediately consistent
   with the one existing precedent, but several fields (`transitioned`, `transition_rejected`) are
   specific to the relay's paired-transition declaration logic and would be meaningless or always-
   zero for a connector that only ever submits new commands.
2. **Derive a connector-specific field list from what a connector's command submission can
   actually produce**: `service`, `result`, `submitted` (commands attempted), `accepted` (2xx from
   the command API), `duplicate` (the command API's idempotent-replay response, per D16), `rejected`
   (validation or business-rule rejection from the API), `failed` (transport/unexpected error,
   ending the run). This costs writing and testing one new `RunReceipt`-equivalent dataclass and
   its `summary_line()`, mirroring `run.py:73` through `run.py:100`'s pattern exactly, but with
   connector-true field names. It gives up nothing the relay's version has, because none of the
   relay's paired-transition fields apply to a plain command-submitting connector.
3. **A generic, subject-agnostic receipt shared by every future connector** (a small shared helper
   in `pulse-core` that any connector imports rather than each connector defining its own
   dataclass): highest long-term consistency across the eleven prospective connectors, but is a
   `pulse-core` API design decision that affects every future connector at once — more than this
   one work order's scope, and risky to get right before a second real connector exists to
   validate the abstraction against.

### Recommendation

Option 2 for `pricing-engine` specifically, with option 3 flagged as a follow-up once a second
connector exists to confirm the field list generalises. Designing a shared abstraction (option 3)
from a single instance risks guessing wrong about which fields are truly universal versus specific
to pricing-engine's own source system.

**Proposed exact field list** for a connector's receipt, following `run.py`'s `key=value`
summary-line pattern exactly: `service=<connector-name> result=<success|failure>
submitted=<int> accepted=<int> duplicate=<int> rejected=<int> failed=<int>`.

### Level of effort

`M` — this needs a new module (a `RunReceipt`-equivalent dataclass plus a `ServiceJsonFormatter`-
equivalent, both closely modeled on existing, working code in `run.py`) with tests written first,
per this repository's stated TDD convention, but it is not a new package or a new gate — it is one
new module inside the connector package. Half a day to a day, mirroring existing code rather than
inventing a new logging approach.

### Dependencies and risks

Depends on Item 2.5's configuration work landing first, since the receipt's `result` field depends
on knowing the connector's actual failure modes, which in turn depend on which environment
variables and command-API responses the connector's own configuration and submission path can
produce. Risk: `run.py`'s own module docstring at `packages/verdict-relay/src/verdict_relay/
run.py:9` through `packages/verdict-relay/src/verdict_relay/run.py:12` states the no-PHI posture
explicitly ("Log content is subject keys, verdict types, and timestamps only — never
demographics, never outcome values") — a connector's receipt design should state the equivalent
posture explicitly for its own domain before writing the field list, because "never outcome
values" for a verdict relay and "never payer identifiers" for a pricing-engine connector are not
the same rule and a copy-paste of the relay's docstring language would be wrong for a different
domain. If this fails silently, the value to doubt first is whether the connector's own PHI-safety
test (the equivalent of `test_log_records_carry_subject_keys_only`) actually enumerates the right
domain-specific demographic markers for its own source system, since a copied `DEMOGRAPHIC_MARKERS`
tuple from `test_run.py:255` through `test_run.py:257` may not list the fields a pricing-engine
payload actually carries.

---

## Item 2.5 — Configuration from the environment, failing loudly by name

### Current state

**`resolve_production_config`** (`packages/verdict-relay/src/verdict_relay/production.py:86`
through `packages/verdict-relay/src/verdict_relay/production.py:110`): reads a fixed tuple of nine
required environment variable names, in a pinned order, before constructing any dependency. The
exact list, quoted in full from `packages/verdict-relay/src/verdict_relay/production.py:38` through
`packages/verdict-relay/src/verdict_relay/production.py:46`: `VERDICT_RELAY_PULSE_CORE_BASE_URL`,
`VERDICT_RELAY_TOKEN`, `VERDICT_RELAY_SNOWFLAKE_ACCOUNT`, `VERDICT_RELAY_SNOWFLAKE_USER`,
`VERDICT_RELAY_SNOWFLAKE_PASSWORD`, `VERDICT_RELAY_SNOWFLAKE_WAREHOUSE`,
`VERDICT_RELAY_SNOWFLAKE_DATABASE`, `VERDICT_RELAY_SNOWFLAKE_SCHEMA`,
`VERDICT_RELAY_SNOWFLAKE_TABLE`. The failure mode is **first-missing-only, not all-missing**: the
loop at `packages/verdict-relay/src/verdict_relay/production.py:94` through
`packages/verdict-relay/src/verdict_relay/production.py:98` iterates `_REQUIRED_ENV_VARS` in the
pinned order and raises `MissingProductionVariableError(name)` on the first `None` it finds,
without checking the rest. The comment at
`packages/verdict-relay/src/verdict_relay/production.py:48` through
`packages/verdict-relay/src/verdict_relay/production.py:49` states this is deliberate: "Read in
exactly this order — the first missing variable is the one startup names … so this order is what
a misconfigured deploy sees." `MissingProductionVariableError` (`packages/verdict-relay/
src/verdict_relay/production.py:63` through `packages/verdict-relay/src/verdict_relay/
production.py:68`) names the variable, never a value, in its message.

**`archaeology/client.py`'s secret-reference pattern**, in full: the exact environment variable
names are `ARCHAEOLOGY_MONGO_HOST`, `ARCHAEOLOGY_MONGO_USER`, `ARCHAEOLOGY_MONGO_PASSWORD_REF`,
`ARCHAEOLOGY_MONGO_DB`, `ARCHAEOLOGY_MONGO_TLS`, `ARCHAEOLOGY_MONGO_SERVER_SELECTION_TIMEOUT_MS`,
`ARCHAEOLOGY_MONGO_CONNECT_TIMEOUT_MS`, `ARCHAEOLOGY_MONGO_SOCKET_TIMEOUT_MS`
(`packages/archaeology/src/archaeology/client.py:39` through
`packages/archaeology/src/archaeology/client.py:46`), of which only the first three are required
(`REQUIRED_ENV_VARS` at `packages/archaeology/src/archaeology/client.py:49`). Unlike verdict-relay,
`ArchaeologyConfig.from_env` (`packages/archaeology/src/archaeology/client.py:172` through
`packages/archaeology/src/archaeology/client.py:181`) collects **every** missing required variable
into one tuple and raises once, naming the whole set — the opposite failure-reporting choice from
verdict-relay's first-only, and the code's own docstring at
`packages/archaeology/src/archaeology/client.py:173` through
`packages/archaeology/src/archaeology/client.py:177` states why: "an operator fixes the whole set
at once instead of replaying failures." The reference forms accepted for the password are exactly
two, checked at `packages/archaeology/src/archaeology/client.py:196` through
`packages/archaeology/src/archaeology/client.py:214`: `env:NAME` (resolves from another named
environment variable) and `file:PATH` (resolves by reading a file's stripped text content); any
other form, including a bare literal, raises. The exact exception class names raised by this
module: `ArchaeologyError` (base, `packages/archaeology/src/archaeology/client.py:86` through
`packages/archaeology/src/archaeology/client.py:87`), `MissingEnvVarsError`
(`packages/archaeology/src/archaeology/client.py:90` through
`packages/archaeology/src/archaeology/client.py:95`), `SecretRefError` (base for reference
problems, `packages/archaeology/src/archaeology/client.py:98` through
`packages/archaeology/src/archaeology/client.py:104`), `SecretRefUnsetError`
(`packages/archaeology/src/archaeology/client.py:107` through
`packages/archaeology/src/archaeology/client.py:111`), `SecretRefFileMissingError`
(`packages/archaeology/src/archaeology/client.py:114` through
`packages/archaeology/src/archaeology/client.py:118`), `SecretRefFormError`
(`packages/archaeology/src/archaeology/client.py:121` through
`packages/archaeology/src/archaeology/client.py:128`), `InvalidEnvValueError`
(`packages/archaeology/src/archaeology/client.py:131` through
`packages/archaeology/src/archaeology/client.py:135`), and `WriteRoleRefusedError`
(`packages/archaeology/src/archaeology/client.py:138` through
`packages/archaeology/src/archaeology/client.py:146`).

`openspec/specs/archaeology-access/spec.md:10` through `openspec/specs/archaeology-access/
spec.md:13` states the binding requirement, quoted in full: "The client factory SHALL build its
connection exclusively from environment variables that reference the platform secret store. No
literal credential, connection string, or secret value SHALL exist in the repository — source,
tests, fixtures, or docs — and a repository-wide credential-material check SHALL enforce this."

**Which of the two patterns a new connector should follow**: `docs/process/dispatch-template.md:
183` states the governing line directly, in a table row labeled `H5 | Credential isolation`: "No
prod credentials in worktree env or Orca config. Secrets resolve at runtime from the DuploCloud
store via the archaeology-package pattern. BF-0b-class prod reads stay outside Orca until H1–H4
hold." This names the archaeology (secret-reference) pattern, not the verdict-relay (direct
environment value) pattern, as the governing convention for how secrets resolve at runtime — the
verdict-relay pattern predates this row and reads a plaintext value directly from an environment
variable the deploy environment sets (`VERDICT_RELAY_SNOWFLAKE_PASSWORD`, a literal password value
in an environment variable, not a reference), which is a different, and by this governance line's
own statement, non-preferred posture for a new connector's own credential handling.

**Repository-wide credential-material check**: confirmed to exist, but narrower in scope than "any
credential" — it is Mongo-URI-specific. `packages/archaeology/tests/test_credential_gate.py:1`
through `packages/archaeology/tests/test_credential_gate.py:54` implements
`test_no_credential_bearing_mongo_uri_anywhere_in_the_tree`, which runs `git ls-files` to enumerate
every git-tracked file in the repository (`packages/archaeology/tests/test_credential_gate.py:24`
through `packages/archaeology/tests/test_credential_gate.py:33`, `_tracked_files`), and asserts
none of them matches a regular expression for a `mongodb://` or `mongodb+srv://` URI carrying a
`user:password@` credential segment (`packages/archaeology/tests/test_credential_gate.py:21`).
This check is genuinely repository-wide in reach (every tracked file, not just
`packages/archaeology/`), and is wired into `task test` because it lives under
`packages/archaeology/tests/`, which `Taskfile.yml:31`'s `TESTED_PATHS` includes. **It would not
catch a leaked plaintext PostgreSQL password, an AWS access key, or any credential shape other
than a Mongo connection URI** — its regex at
`packages/archaeology/tests/test_credential_gate.py:21` is specific to the `mongodb`/`mongodb+srv`
scheme. There is no broader, generic secret-scanning gate elsewhere in this repository (searched
`Taskfile.yml` and `tests/scaffold/` for "credential", "secret scan", and similar terms with no
match beyond this one Mongo-specific test).

### Gap

`pricing-engine` has no configuration module at all. Beyond that, this repository currently
embodies two different conventions for the same problem (verdict-relay's direct-plaintext-env-var
pattern versus archaeology's secret-reference pattern) with an explicit governance statement
(`docs/process/dispatch-template.md:183`) favoring the reference pattern for how secrets resolve
at runtime, but with the repository's own closest-precedent connector-shaped package
(verdict-relay) still built the older way. A new connector copying the "closest precedent" without
reading the governance line would copy the wrong one.

### Options

1. **Follow the verdict-relay direct-environment-value pattern**: least new code (one dataclass,
   one required-vars tuple, one fail-first-missing loop, directly copyable from
   `production.py:86` through `production.py:110`), but every credential value (a plaintext
   password or bearer token) is read straight from the process environment with no secret-store
   indirection, which `docs/process/dispatch-template.md:183`'s H5 row indicates is not the
   governed pattern going forward.
2. **Follow the archaeology secret-reference pattern**: matches the explicit governance line, and
   gives a connector the same defense the archaeology-access spec requirement gives Mongo access —
   no literal secret value ever needs to sit in a plain environment variable that a process listing
   or a misconfigured log line could expose directly, only a *reference* (`env:NAME` or
   `file:PATH`) does. Costs one extra indirection layer (`_resolve_secret_ref`,
   `packages/archaeology/src/archaeology/client.py:196` through
   `packages/archaeology/src/archaeology/client.py:214`) that verdict-relay's simpler pattern does
   not need, and one more exception-class hierarchy to write and test.
3. **A hybrid**: direct environment values for genuinely non-secret configuration (base URLs,
   table names, timeouts — matching verdict-relay's approach for those specific fields) and secret
   references only for the credential fields (matching archaeology's approach for the password/
   token fields specifically). This is in fact closer to what a careful reading of both existing
   examples already does in spirit — verdict-relay's own non-secret fields (`SNOWFLAKE_ACCOUNT`,
   `SNOWFLAKE_WAREHOUSE`, etc.) are not secrets and do not need reference indirection either — but
   no existing package demonstrates this exact hybrid split explicitly, so it would be a documented
   choice made for pricing-engine specifically rather than a copy of a working precedent.

### Recommendation

Option 3, justified by option 2's spec requirement and the H5 governance line, but scoped
precisely: apply secret-reference indirection (`env:NAME` / `file:PATH`, following
`packages/archaeology/src/archaeology/client.py:196` through
`packages/archaeology/src/archaeology/client.py:214` exactly) only to the connector's own
credential fields (an API key, token, or password equivalent), and plain, directly-read
environment values (following `production.py`'s pattern) for every non-secret configuration value
(base URLs, resource identifiers, timeouts). This is the option that actually satisfies
`docs/process/dispatch-template.md:183`'s stated governance for "secrets" specifically, without
introducing reference indirection for values that are not secrets and gain nothing from it.

### Level of effort

`S` — both patterns already exist, fully implemented and tested, in-repo (`production.py`'s direct-
value pattern and `client.py`'s reference-resolution pattern); building the hybrid is copying two
existing, working code shapes into one new module and writing tests against the copy, not
inventing new logic. One or two files, mechanical.

### Dependencies and risks

Depends on knowing pricing-engine's actual credential shape (a single API key versus a full
username/password pair) before the field list can be finalized — that is a fact about the pricing-
engine source system this analysis cannot supply and must come from whoever owns that
integration. Risk: `packages/archaeology/tests/test_credential_gate.py`'s regex is Mongo-URI-
specific (confirmed above), so it will not catch a pricing-engine credential leaked in a different
shape (a bearer token in a fixture file, an API key embedded in a committed `.env.example`, or a
Postgres-style DSN with an embedded password) — a connector following this pattern needs either its
own equivalent credential-gate test or an extension to the existing one broadened past Mongo URIs;
neither exists today. If this fails silently, the value to doubt first is whether "no credential in
the repo" is actually enforced for pricing-engine's specific secret shape, or only appears enforced
because the one existing gate happens to run and pass while checking for the wrong pattern.

---

## Verification

Command run to confirm this report exists at the required path:

```
ls -1 .planning/reports/2026-08-21-connector-template-tier-2-gap-analysis.md
```
