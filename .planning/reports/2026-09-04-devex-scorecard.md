# DevEx scorecard - pulse @ b26dee0 - 2026-09-04

Corrections from `.planning/reports/2026-09-04-devex-audit-qa.md` applied 2026-09-04: dimension 8 rescored
6 to 8 (QA 6.1, the blindness rule hid the measurement machinery), Overall DX 5.6 to 5.9; ranked fix #10
and evidence dispute #6 withdrawn in part (QA 6.2); fix #5 names `Jitter` only (QA 6.3); Community
annotated as unresolved between 3 and 5 (QA 6.5). Connector composite 5.8 unchanged.


**Date**: 2026-09-04
**HEAD**: `b26dee0` (`b26dee0d8695f9de0a10eeeed12bb1e23c7851a7`), branch `main`
**Rubric**: `docs/process/devex-audit/rubric.md`, applied as written including the internal-repo
interpretation at the top of that file
**Input**: `.planning/reports/2026-09-04-devex-audit-evidence.md` (Task A), read in full
**Persona carried forward from Task A**: a competent engineer whose first job is a new pocar
connector

**Scoring stance.** A 10 is the best-practice bar the rubric describes, adapted to an internal
platform repo. It is not "no visible defects" - defect-free with no reach beyond it is a 7 to 8.
Every score below 9 gets a gap-method entry stating what a 10 would be here.

**Verification.** Before scoring each dimension I re-opened or re-ran at least two of Task A's
cited pieces of evidence in the tracked repo at `b26dee0` and in this worktree. The Method column
of the scorecard says which. Anything I could not verify is in Evidence disputes and is scored at
low confidence on the verified remainder only.

**Blindness held.** I did not open `tests/scaffold/cat10_devex.py`, `scripts/devex/`,
`.planning/devex/`, `.planning/reports/2026-09-02-devex-scorecard.md`,
`.planning/reports/2026-09-02-devex-audit-qa.md`, or
`.planning/reports/2026-09-02-devex-audit-evidence.md`. The boomerang comparison is Task C's job.

---

## Headline

| Number | Value |
| --- | --- |
| **Connector author DX (weighted composite)** | **5.8 / 10** |
| **Overall DX (unweighted mean of eight dimensions)** | **5.9 / 10** (QA-corrected from 5.6; dimension 8 rescored 6 to 8) |

Read as: a connector author reaches a green gate fast and then hits a wall. The machinery that
gets a package created and registered is genuinely good. The machinery that tells the author what
to write next, keeps the guide honest, and lets the pre-ship gate run is not there yet.

---

## Scorecard

| # | Dimension | Score | Confidence | Method | Evidence |
| --- | --- | --- | --- | --- | --- |
| 1 | Getting Started | 7 | High | Re-ran `task install` (2 s) and `task check` (127 s, rc=0) in this worktree; re-read `README.md:218-232`; opened `docs/index.md` | Task A Step 1; my run 127 s vs Task A's 129 s |
| 2 | API / CLI / SDK ergonomics | 6 | High | Counted `__all__` (26 names, no `Jitter`); grepped submodule imports in `packages/*/src`; read `docs/connectors/authoring.md:30-45,95-120`; listed `templates/connector/` | Task A Step 2 |
| 3 | Error messages | 6 | High | Reproduced E1, E2, E4 and E10 verbatim in this worktree; read `templates/connector/src/{{NAME}}/config.py.tmpl` (ConfigError collect shape) | Task A Step 3 |
| 4 | Documentation | 6 | High | Counted `openspec/changes/archive` (20 vs README's "Twenty-two"); listed `.pre-commit-config.yaml` hook ids (no mypy, vs CONTRIBUTING's claim); read the mkdocs nav | Task A Step 4 |
| 5 | Upgrade path | 5 | High | `packages/pulse-core/pyproject.toml:3` = `0.1.0`; `ls CHANGELOG*` = none; zero deprecation/breaking matches in `openspec/specs/connector-kit/spec.md`; `.ade-template-version` present | Task A Step 5 |
| 6 | Developer environment | 6 | High | No `.nvmrc`/`.editorconfig`/`.vscode`/devcontainer in the tree; `package.json` engines `>=22`; `main.yml` jobs `quality` (`task check`), `tests-and-type-check` (3.10-3.14 matrix, `uv run python -m pytest tests`), `check-docs` | Task A Step 6 |
| 7 | Community and ecosystem | 3 | High | `CODEOWNERS` is two lines, one wildcard; `.github/ISSUE_TEMPLATE/` holds only `attended-run.yml`; PR checklist names `task fmt`/`lint`/`test`, never `task check`; README names no owner and no channel | Task A Step 7 QA note (6.5): fell from 4 across PR #361, which added CODEOWNERS, an issue form, a PR template and a named owner; QA recommends 4 and marks this dimension unresolved between 3 and 5. |
| 8 | DX measurement | 8 (QA-corrected from 6) | High | Read the `devex:check` / `devex:audit` target block in `Taskfile.yml:690-703`; confirmed `ci-health.yml` is `on: workflow_dispatch: {}` only; confirmed no timing instrumentation in `Taskfile.yml` | Task A Step 8; blindness kept me out of `scripts/devex/` and `cat10_devex.py`, hence Medium |

**Overall DX** = (7 + 6 + 6 + 6 + 5 + 6 + 3 + 8) / 8 = 47 / 8 = **5.9** (QA-corrected: dimension 8 is 8, see QA 6.1).

### Getting Started, anchored to the TTHW table

| Measurement | Value | Tier |
| --- | --- | --- |
| Task A, clone to green `task check`, machine time | 133 s | Competitive (120-300 s), 13 s outside Champion |
| Task A, including the README read | ~2 min 53 s | Competitive |
| My independent re-run, warm worktree, `install` + `check` | 129 s (2 s + 127 s) | Competitive |
| Cold-cache TTHW | unmeasured | unknown, certainly worse |

Competitive is the rubric's baseline tier, not the champion tier, and the measured number is a
warm-machine best case. That caps Getting Started at 7 before any friction is counted. The
friction that keeps it from 8: the docs site Home page is an eight-line badge stub with no
Getting Started nav entry, `README.md` is not published to the site at all, and a grep for
"getting started" across `docs/`, `README.md` and `CONTRIBUTING.md` hits only this audit's own
task brief. The quickstart itself is excellent and worked verbatim on both runs.

---

## Seven DX Characteristics

| # | Characteristic | Score | Confidence | Why this number |
| --- | --- | --- | --- | --- |
| 1 | Usable | 6 | High | Two-command install, sub-second scaffold, nine registrations performed for you, green gate on the first try. Against that: the rendered `service.py` is outbound-only with no direction flag, so an inbound author deletes the generated main path immediately. |
| 2 | Credible | 5 | High | Gates are real, deterministic and enforced (credential gate auto-discovers a new package; `cat4` pins the CI contract). Against that: the kit is `0.1.0` with no changelog and no deprecation policy, three doc claims are stale and ungated, and the "green locally means green in CI" sentence is false for the 3.10-3.14 matrix job. |
| 3 | Findable | 4 | High | The best document in the repo is linked from neither `README.md` nor `CONTRIBUTING.md`; `docs/index.md` is a badge stub; "how do I add a connector" and "getting started" grep to nothing useful; and a POCAR connector already in the tree (`packages/ocean/services/pocar-connector`, 15 tracked files) is named by no document a connector author reads. |
| 4 | Useful | 7 | High | The kit solves the real problem and five packages are built on it. The template's `ConfigError` reports every missing and invalid variable at once, by construction, for every connector. The credential-posture gate needs zero registration and runs in 0.19 s. |
| 5 | Valuable | 7 | High | `task connector:new` collapses nine registration sites across two files into one sub-second command with a true dry run that writes nothing. That is measurable friction removal on the exact task this repo exists to make repeatable. |
| 6 | Accessible | 5 | Medium | CLI only, verified on one platform (macOS arm64) by one auditor. No `.editorconfig`, no `.vscode/extensions.json`, no devcontainer, no `.nvmrc` while CI pins node 22 and the audit ran on node 26. `.envrc` is gitignored so a direnv user starts from nothing. Medium confidence: no second platform was tested by anyone. |
| 7 | Desirable | 5 | High | Internally coherent and clearly built by someone who cares. But 947 of 947 real commits are by one author and no connector has been landed by anyone else, so there is no evidence anyone *wants* to use it - only that it works for its author. |

---

## Connector author DX composite

Fixed slices and weights, as specified, so this number is comparable across audits.

| Slice | Weight | Score | Derivation | Points |
| --- | --- | --- | --- | --- |
| Kit API ergonomics | 30 | 6 | Dimension 2 verbatim | 180 |
| Connector documentation | 20 | 6 | Dimension 4 verbatim | 120 |
| Getting started to a working connector | 15 | 6 | Dimension 1 (7) minus 1: the clone-to-green path is clean, but the connector path adds stucks 1-4 (guide unlinked, script invocation not shown, silent prior-art collision, wrong tree diagram) | 90 |
| Errors on the connector path | 15 | 6 | Dimension 3 verbatim; the connector-path subset is E1, E3, E5, E6, E7, E10 - three best-in-class, three that state the problem without the fix | 90 |
| Dev environment for a new package | 10 | 6 | Dimension 6 verbatim; the scaffold copies `requires-python = ">=3.10,<4.0"` into every new package while the local gate runs one interpreter | 60 |
| Kit upgrade path | 5 | 4 | Dimension 5 (5) minus 1: the template half of the upgrade story is strong but does nothing for a connector author; the kit half, which is the author's half, is empty | 20 |
| Ecosystem and support | 3 | 3 | Dimension 7 verbatim | 9 |
| Measurement of author experience | 2 | 4 | Dimension 8 (6) minus 2: `devex_open_findings` measures whether findings are closed, not anything about an author's experience - no TTHW, no time-to-first-connector, no gate timings | 8 |
| **Total** | **100** | | 180 + 120 + 90 + 90 + 60 + 20 + 9 + 8 = **577** | **577** |

**Connector author DX = 577 / 100 = 5.8.**

---

## Gap method

Every dimension scored below 9. Each entry states what a 10 is for this repo (beyond
defect-free) and the single highest-leverage change toward it.

### 1. Getting Started - 7

**A 10 here.** A newcomer who lands on the docs site, not GitHub, reaches a green gate without
ever opening the repo tree: `docs/index.md` states what PULSE is, gives the two quickstart
commands, and names the one next step ("your first connector"). The measured TTHW is under 120 s
on a cold machine, not a warm one, and the repo knows that number because a scheduled job
measures it. Beyond defect-free: the number is *published and defended*, not discovered by an
auditor.

**Highest-leverage change.** Turn `docs/index.md` into the front door: what PULSE is, the two
quickstart commands verbatim, a link to `docs/connectors/authoring.md`, a link to `WORKFLOW.md`,
and a `Getting started` nav entry above `Architecture`.

### 2. API / CLI / SDK ergonomics - 6

**A 10 here.** `task connector:new NAME=pocar DIRECTION=inbound` renders a working row-source
connector, not just an outbound skeleton, and the command refuses to be surprising: it prints
`note: packages/ocean/services/pocar-connector already exists - read it before you start` on a
name collision anywhere in the tree. The root package is the whole supported surface, provably -
`Jitter` is exported, no reference connector imports from a submodule, and a test
enforces that. Beyond defect-free: the scaffold *teaches* the direction the author picked, so
the generated code is the worked example rather than something to delete.

**Highest-leverage change.** Add `DIRECTION` to `scripts/connector_new.py` with an inbound
template variant wired to `RowSource` / `CursorStore` / `validate_page`. Everything else in this
dimension is a one-line fix; this is the one that removes a rewrite.

### 3. Error messages - 6

**A 10 here.** Every message that states a problem also states the fix as a command you can
paste. `task verify` refuses without `CHANGE` the way `connector:new` refuses without `NAME`;
the credential gate ends its assertion with `see docs/connectors/authoring.md#6-what-is-enforced`;
a missing `openspec`/`openlore` is pre-flighted with the npm line rather than surfacing as exit
127; and `task dispatch --change X` is caught by a wrapper that prints `use CHANGE=X` instead of
burying `unknown flag` under go-task's global help. Beyond defect-free: the collect-every-problem
shape that `config.py` already has becomes the house pattern for every gate, not just config.

**Highest-leverage change.** Add `requires: vars: [CHANGE]` to `verify` and a `lore:init` target
(or fold `openlore init --force` into `task install`), so the repo's own pre-ship gate stops
producing an error about something the author did not do.

### 4. Documentation - 6

**A 10 here.** The authoring guide is reachable in one hop from both files GitHub puts in front
of a contributor, its rendered-tree diagram is generated from `templates/connector/` rather than
retyped, and every countable claim in `README.md` and `CONTRIBUTING.md` is either generated or
asserted by a `cat8` gate - so a stale number is a red build, not a reader's problem. Beyond
defect-free: the docs cannot drift, because drift is a test failure.

**Highest-leverage change.** Link `docs/connectors/authoring.md` from `README.md` (the Connectors
section at line ~96) and from `CONTRIBUTING.md`. One line each; it removes the single stuck point
that every connector author hits first.

### 5. Upgrade path - 5

**A 10 here.** A connector author absorbing a kit change reads one file to know what to do:
`packages/pulse-core/CHANGELOG.md`, one entry per surface change, with a `## Deprecations`
section in `openspec/specs/connector-kit/spec.md` stating how long a removed primitive keeps a
shim and how it warns. Section 10 of the authoring guide says "when the kit changes, here is what
you do". Beyond defect-free: a removed primitive emits a deprecation warning that names its
replacement, so upgrades are boring by construction rather than by the accident of single
authorship.

**Highest-leverage change.** Create `packages/pulse-core/CHANGELOG.md` and start it at the next
kit change. The policy section and the guide section follow cheaply once the file exists.

### 6. Developer environment - 6

**A 10 here.** The environment is reproducible from the clone with nothing implicit: `.nvmrc`
pins node to what CI runs, `.editorconfig` and `.vscode/extensions.json` make an editor produce
the same diagnostics `task lint` does, and `task check:matrix` reproduces the 3.10-3.14 CI job
locally so the parity sentence in `README.md` is true without a footnote. Beyond defect-free: the
parity claim is *enforced* - a CI job that `task check` cannot reproduce fails `cat4`.

**Highest-leverage change.** Make the parity claim true or narrow it. Either add a target that
runs the compatibility matrix locally, or amend `README.md:283` to say which job the claim covers.
QA correction (6.2): a new package under `packages/` is invisible to both matrix steps
(`main.yml` runs `pytest tests` and a bare `mypy` over `src`), so no connector-author trap follows;
the gap is that `task check` cannot reproduce the matrix job.

### 7. Community and ecosystem - 3

**A 10 here.** Each area has a named owner in `CODEOWNERS` - the connector kit's directory owned
distinctly from the repo default - `README.md` itself names who to ask and where, issue templates
cover bug and feature alongside `attended-run.yml`, and at least one connector in the tree was
landed by someone other than the repo owner. Beyond defect-free: the last item is the one that
cannot be manufactured, and it is the one that proves the rest of this scorecard.

**Highest-leverage change.** Nothing in the repo moves this score much; the binding constraint is
that 947 of 947 commits are by one author. The cheapest real move is to have a second person land
one connector end to end using only the guide, and treat every place they get stuck as a finding.
The repo-side prerequisite for that is fix #1 (link the guide) and fix #3 (`lore:init`).

### 8. DX measurement - 6

**A 10 here.** The repo measures how long its own experience takes, not only whether findings are
closed: `task check` emits a per-stage duration line into `.planning/devex/timings.jsonl`,
`devex:check` emits `METRIC devex_tthw_seconds` from a scheduled cold-clone job, and
`ci-health.yml` runs on a schedule so CI health is a series rather than a button. Beyond
defect-free: the 89-second test stage is a tracked trend that someone owns, not a fact an auditor
uncovers.

**Highest-leverage change.** Time the stages. `task check` printing and appending per-stage
durations is a small change that converts the repo's single largest DX cost - 89 s of `task test`
inside a 127 s gate - from anecdote into a series.

---

## Ranked fixes

Ranked by adoption impact over effort. Effort: **S** under an hour, **M** a session, **L**
multiple sessions. Principle numbers are the rubric's DX First Principles.

| # | Fix | Effort | Principle | Why here |
| --- | --- | --- | --- | --- |
| 1 | Link `docs/connectors/authoring.md` from `README.md` and `CONTRIBUTING.md` | S | 1 (zero friction at T0) | The best document in the repo, invisible from both files GitHub shows first. One line each. Highest ratio in the audit. |
| 2 | Make `docs/index.md` a real front door with a Getting Started nav entry | S | 1 | A newcomer arriving at the built site currently gets four badges and a tagline. |
| 3 | `task lore:init` (or `openlore init` inside `task install`) plus `requires: vars: [CHANGE]` on `verify` | S | 5 (fight uncertainty) | The guide's step 8.5 tells authors to run a gate that cannot pass on a fresh clone by any documented path, and the error it gives is about the wrong thing. |
| 4 | Collision warning in `connector:new`, plus a "prior art lives in `packages/ocean/services/`" line in the guide | S | 6 (show code in context) | The persona's exact prior work - a POCAR receiver, normalizer and webhook schema, 15 tracked files - is in the tree and named by no document they read. |
| 5 | Export `Jitter` (`Sleeper` already is); settle "root, not submodules" against the reference connectors | S | 4 (decide for me, let me override) | The guide states a rule its own named tiebreaker breaks in two of four modules, and names a primitive that is not exported. Two contradictory signals, nothing enforcing either. |
| 6 | Generate or gate the guide's rendered-tree diagram; ship `tests/test_config.py` and `tests/factories.py` in the template | M | 3 (learn by doing) | Three of four diagrammed test files do not exist, the guide names the `from_env()` test as the one worth writing first, and the template ships no file to hold it - so a new connector enters `COV_PATHS` at 0% on its two largest modules. |
| 7 | `DIRECTION=inbound` template variant | L | 6 | Removes the largest rewrite on the connector path. Large because it needs a second worked example, not just a flag. |
| 8 | `packages/pulse-core/CHANGELOG.md`, a `## Deprecations` section in the kit spec, and section 10 of the guide | M | 5 | The kit reaches every connector on the next `uv sync` with no signal. Masked today by single authorship; it bites on the day fix #7 of the ecosystem story succeeds. |
| 9 | Fix the three stale claims and gate the two countable ones in `cat8` | S | 5 | Archive count (22 vs 20), package count, and a `mypy` pre-commit hook that does not exist. Cheap, and a reader who catches one stops trusting the rest. |
| 10 | `.nvmrc` with `22`, `.editorconfig`, `.vscode/extensions.json`, and either `task check:matrix` or an amended parity sentence | S | 7 (speed is a feature) | `task check` cannot reproduce the tests-and-type-check matrix, so the parity sentence in `README.md:283` and `CLAUDE.md` is imprecise. QA 6.2: the connector-author trap originally claimed here does not exist; demoted to hygiene. |

### Below the cut

Real, verified, and not in the top 10 - each is either low impact for its effort or blocked
behind something above.

- **Narrowable `task test PKG=...`** (M, principle 7). 89 s of the 127 s gate, unnarrowable
  (`Taskfile.yml:154-166` takes no variable). Below the cut only because the guide already gives
  the fast inner loop (`uv run pytest packages/<name>/tests`, 0.13 s), so this bites the commit
  loop, not the edit loop.
- **Per-stage timings and a TTHW metric** (M, principle 7). The right long-run answer for
  dimension 8, but it improves nobody's next hour.
- **Strip change-ids from `task` descriptions** (S, principle 1). `connector:new` ends
  `(devex-eight task 1.4)`; `typecheck`'s description is a list of seven ticket tokens. Noise on
  the newcomer's first screen, but it does not block anything.
- **PR checklist should say `task check`** (S, principle 4). It currently names `task fmt`,
  `task lint` and `task test` - a contributor who ticks all three has still not run
  `twenty:validate`, `twenty:test`, `workflow:lint`, `docs:lock-guard` or `docs:build`.
- **`CODEOWNERS` per area, a who-to-ask line in `README.md`, a bug-report issue template** (S,
  principle 5). Cheap and correct, but with one author they change nothing measurable until a
  second person arrives.
- **`ci-health.yml` on a schedule** (S, principle 5). It is `workflow_dispatch` only, so it
  produces no series.
- **`openlore drift` never fires for `packages/`** (M, principle 5). The hook is scoped
  `^(src/.*\.py|openspec/.*)$`, which excludes every package and every connector. Widening the
  scope needs the docs-only-commit problem the hook comment describes solved first.
- **Name `bootstrap.sh` in the quickstart as "not for you", or drop it from generated repos** (S,
  principle 1). Its error message is good; its presence is a moment of doubt.
- **Move the audit task briefs out of the reader-facing nav; fix `env-vars-retreival.md`** (S,
  principle 1). The mkdocs nav publishes `process/devex-audit/task-a.md`, `task-b.md` and
  `task-c.md` - this audit's own instructions - to the docs site, and one Process entry is
  misspelled in the filename.
- **Credential-gate assertions should link the doc** (S, principle 5). Folded into fix #3's
  spirit but separately cheap: `see docs/connectors/authoring.md#6-what-is-enforced`.

---

## Evidence disputes

Everything material in Task A's report that I re-checked, held. The list below is what I could
not verify, what I would state differently, and two citation slips.

**Verified independently, no dispute** (recorded so Task C can see the overlap): archive count
20 vs README's "Twenty-two"; no `mypy` pre-commit hook vs `CONTRIBUTING.md`'s claim; `__all__` is
26 names and `Jitter` is not among them; submodule imports in `billing-connector` (three sites,
including a test) and `verdict-relay`; `verify` declares no `requires`; `.openlore/` gitignored
at `.gitignore:227` and `task lore:drift` fails with `Run "openlore init" first`; `openlore init
--force` appears only at `bootstrap.sh:177`; `.envrc` gitignored at `.gitignore:144`; the guide's
tree diagram vs `templates/connector/`; the guide unlinked from `README.md`, `CLAUDE.md`,
`AGENTS.md`, `CONTRIBUTING.md` and `docs/index.md`; `docs/index.md` is eight lines of badges;
`CODEOWNERS` is one wildcard; one issue template; the PR checklist omits `task check`; no
`.nvmrc`/`.editorconfig`/`.vscode`/devcontainer; `package.json` engines `>=22`; the three
`main.yml` jobs and the unreproducible matrix; `ci-health.yml` is `workflow_dispatch` only;
`pulse-core` is `0.1.0`, no `CHANGELOG` anywhere, zero deprecation or breaking-change language in
the kit spec; 15 tracked `pocar` files under `packages/ocean/services/`; E1, E2, E4 and E10
reproduced verbatim.

1. **Package count reads as a contradiction between Task A's Step 0 and Step 4.** Step 0's
   inventory table says 15 packages and calls README's "Fourteen" stale; Step 4 correctly explains
   that 14 was right at `b26dee0` and the 15th was Task A's own scaffold. In the tracked tree at
   `b26dee0`, `ls packages | wc -l` is **14** and `README.md:115` is **correct**. I scored the
   package count as an ungated hand-maintained number (a real risk), not as a stale claim. Task A's
   Step 4 table row "14 before my scaffold; hand-maintained, nothing gates it" is the accurate
   phrasing; the Step 0 row is misleading on its own.

2. **The TTHW number is warm-only, and I am scoring it as such.** Task A flags this itself.
   My independent re-run in an already-provisioned worktree gave `task install` 2 s and
   `task check` 127 s (rc=0), within 2 s of Task A's 129 s - which confirms the gate cost but
   confirms nothing about a cold machine, since my run shared the same warm uv cache and
   `node_modules`. **Cold TTHW is unmeasured by both of us.** Getting Started is scored 7 on the
   warm number; a cold measurement could only move it down, and it is the single most valuable
   measurement a follow-up can add.

3. **Two citation line-number slips, both harmless.** Task A cites `pyproject.toml:150` for
   `fail_under = 80`; it is line **148**. Task A cites `Taskfile.yml:566-572` for the `verify`
   target; it is **546-552**. The substance of both claims is correct. Flagged because a scorecard
   reader following the citation lands in the wrong place.

4. **Unverified, scored at reduced confidence: dimension 8.** The blindness constraint blocks
   `scripts/devex/check.py`, `tests/scaffold/cat10_devex.py` and `.planning/devex/`, so I could
   not re-run `task devex:check` or inspect what `devex_open_findings` actually counts. I read
   only the `Taskfile.yml:690-703` comment block and the two target descriptions. I confirmed
   independently what is *absent* (no timing instrumentation in `Taskfile.yml`, `ci-health.yml`
   manual-only), which is what the score turns on. Dimension 8 is Medium confidence for this
   reason and no other.

5. **Unverified, accepted as stated: the E5/E6/E7/E8 outputs and the journey timings.** Those
   required Task A's throwaway clone with a rendered `packages/pocar`, deliberate breakage, and a
   test commit - none of which I would reproduce in a read-only pass on the tracked repo. I
   verified the *mechanism* behind E5 and E6 instead, by reading
   `templates/connector/src/{{NAME}}/config.py.tmpl`: `ConfigError(problems)` collects a list,
   `_resolve_stale_after` appends rather than raising, and all three "is unset" strings quoted in
   E5 are literals in the template. The credential gate
   (`packages/pulse-core/tests/test_connector_credential_gate.py`) exists as cited. I did not
   verify E7's 0.19 s or E8's 0.13 s.

6. **Withdrawn in part after QA (6.2).** The CI trap asserted below does not exist: `main.yml`'s matrix runs `pytest tests` and `mypy` over `src` only, so a new connector package is invisible to both steps. The reproducibility gap stands. Original text follows. Task A files the false parity claim
   as friction point 9 and marks the failing case INFERRED. I did not construct the failing case
   either, but it needs no construction to be a defect: `README.md:283` and `CLAUDE.md` both
   assert "green locally means green in CI" without qualification, and `main.yml:52-74` runs a
   five-interpreter matrix that `task check` cannot reach. The claim is false as written
   regardless of whether anyone has yet tripped it, and the scaffold propagates
   `requires-python = ">=3.10,<4.0"` into every new connector. That is why it is in the top 10
   rather than below the cut.

7. **No disagreement with Task A's four positives.** `connector:new`'s nine-site registration and
   true dry run, the collect-every-problem `ConfigError`, the zero-registration credential gate,
   and the guide answering all eight persona questions in order are all real and all verified
   here. They are what holds dimensions 2, 3 and 4 at 6 rather than lower, and they are the reason
   the composite is 5.8 rather than the low 4s.

**Side effects of my own verification.** Running `task install` in the `devex-audit-2` worktree
re-installed the pre-commit hook into the shared `.git/hooks` (it was already present) and
`task check` wrote a `site/` build directory inside the worktree. Nothing tracked in
`/Users/Rob.Ford/Repos/robford-brookai/pulse` was modified; the only file this task writes there
is this report.
