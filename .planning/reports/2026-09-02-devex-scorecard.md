# PULSE developer experience audit, scorecard

Corrections from `.planning/reports/2026-09-02-devex-audit-qa.md` applied 2026-09-04 (TTHW tier
Competitive, 21 nav entries and 15 off-nav pages, nine CHANGE-taking targets, Upgrade Path confidence
High). No score moved.

Date: 2026-09-02
Repo under audit: commit `99d9b7a` on main
Input: `.planning/reports/2026-09-02-devex-audit-evidence.md` (Task A), read in full
Rubric: gstack `devex-review` SKILL.md, "DX Scoring Rubric (0-10 calibration)", "TTHW
Benchmarks", "The Seven DX Characteristics", "DX First Principles"
Calibration: `plan-devex-review/dx-hall-of-fame.md`, Passes 1 through 8
Persona: a competent engineer joining the team whose first job is to build a connector that is
not billing

Every score below was set after re-opening at least two of the files Task A cites, or re-running
the command it quotes. Verification results are in "Evidence disputes" at the end.

---

## Headline

**Connector author DX: 2.4 / 10.**

A new engineer can get a green `task check` in about two minutes and cannot get a working
connector at all. The first line of code they write against the kit's documented public surface
raises `AttributeError`, the spec that their reading path leads them to describes an
architecture the shipped code does not implement, and three of the eight registrations a new
package needs fail silently open, so a package that is wired to nothing still passes the gate.

**Overall repo DX: 3.8 / 10.**

The repo's own machinery scores far better than its connector surface. Local and CI parity is
mechanically enforced, `task` prints 63 well-described targets in workflow order, and
`task template:diff` is a genuinely best-in-class upgrade artifact. None of that is reachable by
someone whose job is to add a connector.

---

## Scorecard

| Dimension | Score | Confidence | Method | Evidence pointer |
|---|---|---|---|---|
| Getting Started | 4 / 10 | Medium | TESTED | TTHW to green gate 135s (Task A Step 1); persona's real hello world unreachable; `bash bootstrap.sh` still exits 1 with `bootstrap.sh: line 7: 1: Usage: ...` |
| API / CLI / SDK Ergonomics | 4 / 10 | High | TESTED | `task` surface strong; `[n for n in c.__all__ if not hasattr(c,n)]` returns 4 names; 8 registration sites across `pyproject.toml` 73/91/211 and `Taskfile.yml` 19/35/48/138/438-460 |
| Error Messages | 3 / 10 | High | TESTED | 1 of 10 scenarios states problem, cause and fix, and it comes from third-party `openspec`; zero doc links; all 9 CHANGE-taking targets lack `requires:` |
| Documentation | 3 / 10 | High | TESTED | `mkdocs.yml:1` is `site_name: repo-ade`; `docs/modules.md` is `::: pkg_pulse.foo`; 36 docs pages, 21 nav entries |
| Upgrade Path | 5 / 10 | High | PARTIAL | `task template:diff` prints scope, diffstat and next command; no CHANGELOG, no `pulse-core` pin, no deprecation machinery |
| Developer Environment | 5 / 10 | High | TESTED | `main.yml:50` runs exactly `task check` and `cat4_ci_contract.py` enforces it; 4 all-zeros action SHAs; `.git/hooks/pre-commit` absent after clone |
| Community & Ecosystem | 4 / 10 | High | TESTED | 20 handoff records and a 9-step `WORKFLOW.md`; no `.github/ISSUE_TEMPLATE`, no `CODEOWNERS`, `CONTRIBUTING.md` is 13 lines, no channel or owner named anywhere |
| DX Measurement | 2 / 10 | High | TESTED | grep for DX vocabulary returns nothing; `ci-health.yml` is dispatch-only and has an all-zeros checkout pin |
| **TTHW, repo gate** | **135s (Competitive)** | Medium | TESTED | Task A Step 1, warm 26 GB uv cache, single sample |
| **TTHW, connector hello world** | **unbounded (Red Flag)** | High | TESTED | No scaffold, no authoring guide, kit star-import raises |
| **Overall DX** | **3.8 / 10** | | | Unweighted mean of the eight dimensions |

Confidence is Medium where the number rests on a measurement I did not reproduce (the clone
timing). High elsewhere; the QA pass reproduced `task template:diff` verbatim, so Upgrade Path is High.

---

## The Seven DX Characteristics

| # | Characteristic | Score | Why |
|---|---|---|---|
| 1 | Usable | 3 / 10 | `task install` in seconds and 63 self-describing targets are real usability. Against that, the kit's first line of code raises, three registrations fail open, and hooks the contributor guide promises do not exist on a clone. |
| 2 | Credible | 4 / 10 | Every action pinned to a SHA, `uv.lock` drift-guarded, a 5-version matrix, archived changes that merge into a baseline. Four of those pins are all zeros so two workflows cannot run, `CONTRIBUTING.md` states hooks run when they do not, `__all__` promises four names it does not import, and the connector spec exists in two copies differing by 227 lines. Predictability is broken in four separate places. |
| 3 | Findable | 2 / 10 | The docs site is still the template's, generates API docs for `pkg_pulse.foo`, and leaves 15 of 36 pages including all five ADRs out of the nav. The richest connector guidance in the repo is 3,197 lines of gap analysis buried in `.planning/reports/`. One process page is named `env-vars-retreival.md`, so it will never be found by a search for "retrieval". Nothing names a person or channel to ask. |
| 4 | Useful | 6 / 10 | The kit solves real problems and `billing-connector` ships against it. `task template:diff`, the handoff records and the work-order dispatch all do genuine work. The score is capped because the useful parts are reachable only by whoever built them. |
| 5 | Valuable | 5 / 10 | "Green locally means green in CI" is mechanically true and saves real time. Twenty changes of provenance in `handoffs/` is better decision history than most projects keep. The connector kit's value is unrealized for any author but its own. |
| 6 | Accessible | 3 / 10 | CLI only, with no `.editorconfig`, no `.vscode/`, no devcontainer, so formatting is enforced at commit rather than offered at edit. Prerequisites are unstated, so a machine without `go-task` gets `command not found` and no guidance. The binding contracts (`AGENTS.md`, `CLAUDE.md`) address agents; no document addresses a human joiner. |
| 7 | Desirable | 3 / 10 | Two moments in the repo are genuinely good: `task` on its own, and `task template:diff` printing scope plus diffstat plus the exact next command. Everything a connector author touches in their first hour is either a trap, a lie, or absent. |

---

## Connector author DX composite

Score: **2.4 / 10**.

The task brief weights connectors heaviest because that is where engineers will spend their
time. I scored a connector-specific slice of each dimension rather than reusing the repo-wide
number, then weighted by how much of a connector author's first week each slice consumes.

| Slice | Score | Weight | Contribution | Basis |
|---|---|---|---|---|
| Kit API ergonomics | 2 | 30% | 0.60 | Star-import raises; reference connector deep-imports instead; no scaffold; 8 manual registrations, 3 failing open |
| Connector documentation | 2 | 20% | 0.40 | 1 of the persona's 8 questions answered on the docs site; 227-line spec drift; spec vocabulary absent from the code |
| Getting started to a working connector | 2 | 15% | 0.30 | Environment green in 135s, connector hello world never reached |
| Errors on the connector path | 3 | 15% | 0.45 | Raw tracebacks, one variable at a time, no unit and no source named |
| Dev environment for a new package | 4 | 10% | 0.40 | CI parity strong, registrations fail open, hooks absent |
| Kit upgrade path | 3 | 5% | 0.15 | No CHANGELOG, no pin, no deprecation, no consumer registry |
| Ecosystem and support | 4 | 3% | 0.12 | Strong handoff provenance, nobody to ask |
| Measurement of author experience | 1 | 2% | 0.02 | 3,197 lines of gap analysis, zero metrics, findings unimplemented |
| **Composite** | | **100%** | **2.44** | |

Weighting rationale: the author writes code against the kit before they read anything else, so
kit ergonomics carries the largest share. Documentation is next because it is the only thing
that can substitute for a scaffold. Getting started and errors are equal at 15% each: the
environment is a one-time cost, error quality is paid on every iteration. Upgrade path,
ecosystem and measurement are small because they bite after the first connector ships, not
during it.

A 2 on the rubric means "Broken. Developers abandon after first attempt." That is the correct
reading of the evidence. The persona in Task A's journey table hits nine distinct stuck points
and never produces a connector.

---

## Gap method

Every dimension scored below 9. Each entry states what a 10 looks like for this repo and the
single highest-leverage change toward it.

### Getting Started, 4 to 10

A 10: `README.md` opens with the four prerequisites (`uv`, `go-task`, Node 22, Docker) and their
one-line installs. `task install` runs `uv sync` and `pre-commit install`, then prints
"environment ready". `bootstrap.sh` refuses to run against a repo with a stamped
`.ade-template-version` and points at `task install`. `task doctor` gives a five-second
green or red. A new engineer reaches a running connector, not just a green gate.

Highest leverage: add `uv run pre-commit install` to `task install`. One line, and it removes
the gap between what `CONTRIBUTING.md` claims and what a clone does.

### API / CLI / SDK Ergonomics, 4 to 10

A 10: `from pulse_core.connector import *` works. `task connector:new NAME=x` writes a package
that compiles, typechecks and runs its own fixture-backed tests on first invocation, and
performs all eight registrations itself. `billing-connector` imports from the package root, so
the canonical surface has a user and cannot silently rot.

Highest leverage: import `declare` in
`packages/pulse-core/src/pulse_core/connector/__init__.py` and add a test asserting every name
in `__all__` resolves. The scaffold is the larger win but the broken import is the one that
fires in minute one.

### Error Messages, 3 to 10

A 10: every error names the problem, the cause, the fix and where to read more, with the actual
value that caused it, in the Stripe `doc_url` shape from Pass 3. `Config.from_env()` collects
every missing or malformed variable and raises once, naming each variable, its unit and the
runbook section that supplies it.

Highest leverage: add `requires: vars: [CHANGE]` to the nine ADE targets. The Taskfile already
uses `requires:` on 16 credentialed targets, so this is a consistency fix, not a new capability,
and it converts the two worst repo-authored messages (E2 and E8) into
`task: task "dispatch" requires variable CHANGE`.

### Documentation, 3 to 10

A 10: `mkdocs.yml` names PULSE and points at the pulse repo. `docs/index.md` offers three paths:
operate a service, build a connector, change the ledger. mkdocstrings generates `pulse_core` and
the connector kit. Every ADR and process page is in the nav, and `cat8` fails the build when a
page is added outside it rather than logging at INFO.

Highest leverage: repoint mkdocstrings from `src/pkg_pulse` to `packages/pulse-core/src` and
replace `docs/modules.md`. Today the only API reference the docs site produces is for a
placeholder named `foo`.

### Upgrade Path, 5 to 10

A 10: `pulse-core` carries a CHANGELOG with a "connector authors" section per entry. A change to
a connector-facing signature ships with a `DeprecationWarning` for one release plus a note in
`docs/connectors/upgrading.md`. `task template:diff` runs on a schedule so the pending delta
never reaches 2,981 lines.

Highest leverage: a `CHANGELOG.md` in `packages/pulse-core` with a connector-facing section.
Nothing today tells a connector author that a kit change affects them.

### Developer Environment, 5 to 10

A 10: `task install` installs hooks. `task test:all` runs the three shell gates its description
promises. A gate asserts every GitHub Action pin is 40 hex characters. An `.editorconfig` and a
checked-in `.vscode/settings.json` wire ruff and mypy so a first commit is clean before the hook
sees it.

Highest leverage: fix the four all-zeros SHAs and add a pin-validity assertion to
`cat4_ci_contract.py`. Two workflows, including the CI self-repair loop, currently cannot run at
all, and the gate that exists for this class of problem does not check it.

### Community & Ecosystem, 4 to 10

A 10: `CONTRIBUTING.md` names the channel and the owner per package area and states the branch
and PR conventions that `CLAUDE.md` holds today. `.github/ISSUE_TEMPLATE/` carries a template for
the attended-run issues the workflow already depends on. `CODEOWNERS` routes
`packages/pulse-core/src/pulse_core/connector/**` to the kit owner.

Highest leverage: add `CODEOWNERS`. It is the only one of these that changes behavior
automatically rather than relying on someone reading it.

### DX Measurement, 2 to 10

A 10: `task check` appends its wall time to a local log so gate duration is trended rather than
felt. A `tests/scaffold/` gate asserts a fresh clone reaches green under N seconds, making TTHW
regression-testable. The tier gap-analysis findings become a checklist with a visible completion
percentage. `ci-health.yml` runs nightly with a working pin.

Highest leverage: convert the three tier gap-analysis reports into a single tracked checklist.
3,197 lines of correct analysis exist and have produced no change; a checklist is the cheapest
mechanism that makes the gap visible.

---

## Top 10 fixes, ranked by adoption impact over effort

Effort: S is under an hour, M is a session, L is multiple sessions. The principle number refers
to the skill's DX First Principles.

| # | Fix | Effort | Principle | Why it ranks here |
|---|---|---|---|---|
| 1 | Add `uv run pre-commit install` to `task install` | S | 5, Fight uncertainty | One line. Closes the gap between `CONTRIBUTING.md` and reality, and makes a joiner's first commit behave as documented. |
| 2 | Import `declare` in the connector `__init__.py`, add a test that every `__all__` name resolves | S | 1, Zero friction at T0 | One line plus one test. Removes the first error a connector author will ever see. |
| 3 | `requires: vars: [CHANGE]` on `dispatch`, `checkoff`, `collect`, `replan`, `spec:validate`, `spec:archive`, `spec:status`, `sync-docs`, `linear:sync` | S | 5, Fight uncertainty | The pattern already exists on 16 targets. Fixes the two worst repo-authored error messages. |
| 4 | Make `bootstrap.sh` refuse to run when `.ade-template-version` is stamped, and print "run `task install`" | S | 1, Zero friction at T0 | Removes the trap at T+0:05. `docs/ci-lessons.md:116` records that a successful run once destroyed a remote. |
| 5 | Prerequisites block in `README.md`: `uv`, `go-task`, Node 22, Docker, with install lines | S | 1, Zero friction at T0 | The quickstart's very first command needs two tools it never names. |
| 6 | Replace the four all-zeros action SHAs; assert 40-hex pins in `cat4_ci_contract.py` | S | 5, Fight uncertainty | Two workflows are dead, including the CI self-repair loop, and nothing surfaces it. |
| 7 | `Config.from_env()` collects all missing and malformed variables, raises once, names each variable, its unit and its source | M | 5, Fight uncertainty; 6, Show code in context | Turns three edit-rerun cycles into one, and gives the invalid-value path the custom exception the missing-value path already has. |
| 8 | Collapse the two connector spec copies into one canonical document written in the shipped kit's vocabulary; archive the PAP CX-1..CX-8 breakdown | M | 4, Decide for me; 6, Show code in context | A persona who reads the spec first learns Tap, Classifier, Mapper, Emitter and Reconciler, none of which exist in the code they will write. |
| 9 | Retitle the docs site to PULSE, point mkdocstrings at `pulse_core`, sweep the nav, make `cat8` fail on off-nav pages | M | 3, Learn by doing | The docs site currently documents a placeholder function named `foo` and hides all five ADRs. |
| 10 | `task connector:new NAME=x` plus `docs/connectors/authoring.md`, with all eight registrations performed by the scaffold | L | 2, Incremental steps; 3, Learn by doing; 8, Create magical moments | Highest absolute impact in the audit. Ranked tenth only because it is the only L on this list. |

Ranking by ratio puts the one-hour fixes first, which is the right sequencing for the next
working day. It should not obscure the finding: fix 10 is the item this audit exists to
surface, and fixes 1 through 9 make a new connector author's life bearable without ever making
it possible. Schedule 10 regardless of where the ratio places it.

Below the cut, in order: make `task test:all` run `cat2_toolchain.sh`, `cat4_command_contract.sh`
and `cat7_gates_hooks.sh` as its description promises (S); add `CODEOWNERS` and a
`.github/ISSUE_TEMPLATE/` for attended runs (S); add `task doctor` (S); append `task check` wall
time to a local trend log (S); add a `packages/pulse-core/CHANGELOG.md` with a connector-facing
section (M).

---

## Evidence disputes

Five items in Task A's report that I could not verify, or verified differently. None changes a
score by more than a fraction of a point, and none invalidates a finding.

1. **"Repo commit under audit: `99d9b7a` (main, clean)".** The commit is right; the tree is not
   clean. `git status --porcelain` at scoring time shows four modified tracked files, and
   `git diff Taskfile.yml` shows a new `twenty:key:rotate` target that did not exist when Task A
   ran. This is concurrent work on the same checkout, not a Task A error. Every command I
   re-ran reproduced Task A's output verbatim, so no finding is affected. Worth noting that
   `twenty:key:rotate` uses `requires: vars: [TARGET]`, which strengthens fix 3.

2. **"Four required environment variables (`config.py` lines 49, 53, 57, 62)".** Only three are
   required. `packages/billing-connector/src/billing_connector/config.py` raises
   `MissingConfigVariableError` at lines 148, 152 and 156; `BILLING_CONNECTOR_STALE_AFTER` at
   line 159 falls back to `_DEFAULT_STALE_AFTER` when unset. The edit-rerun loop is three cycles,
   not four. E5's severity stands unchanged: the optional variable's invalid-value path still
   raises a bare `ValueError: invalid literal for int() with base 10: 'banana'` naming neither
   the variable nor the unit, on the line immediately below three custom exceptions.

3. **"The Taskfile has no `requires:` guard".** True of `dispatch` and of all eight CHANGE-taking
   targets, and I confirmed it. But `Taskfile.yml` uses `requires:` on 16 targets, every one of
   them credentialed or deploy-shaped. The defect is inconsistency, not absence, which makes the
   fix cheaper than Task A implies and raises its ranking.

4. **"Entry README `README.md`, 41 lines".** `wc -l README.md` returns 38. Trivial, recorded for
   completeness.

5. **Two measurements I did not reproduce.** The 135-second TTHW is a single warm-cache sample,
   as Task A itself states, and I did not re-clone to confirm it; Getting Started is scored
   Medium confidence for that reason. `task template:diff` was not repeated here, but the QA pass
   reproduced the 2,981-insertion figure verbatim, so Upgrade Path is High confidence.
   `.ade-template-version` does hold
   `a1de595b8591691a624d67d60efaa20d73641967` as reported. E10, the missing-tool error class,
   remains INFERRED for the same read-only reason Task A gives.

No PHI appears in this report. No production system was contacted. No tracked file was modified
by this task; the only file written is this one.
