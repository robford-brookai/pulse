# PULSE developer experience audit: evidence

Corrections from `.planning/reports/2026-09-02-devex-audit-qa.md` applied 2026-09-04 (TTHW tier,
env-var count, nav count, deep-import wording, T+30:00 row marked INFERRED, grep flags, em-dashes).
Scores were never in this file; findings are unchanged.

Date: 2026-09-02
Repo commit under audit: `99d9b7a` (main, clean)
Methodology: gstack `devex-review` SKILL.md, Steps 0 through 8, with the DX First Principles,
Seven DX Characteristics, Cognitive Patterns, TTHW benchmarks and the gap method applied.
Calibration reference: `plan-devex-review/dx-hall-of-fame.md`, Passes 1 through 8.
Persona: a competent engineer joining the team whose first assignment is to build a new
connector that is not billing.

No numeric scores appear in this report. Scoring is a separate task. Everything below is an
observation with a command, an output, a file reference or a measured time behind it.

Scope note per the skill's Scope Declaration: this repo has no public web surface, no docs
site deployed, no signup flow and no API playground. Every dimension was tested with bash
against a real clone, or marked INFERRED from files. No `browse` tool was used and no
network call reached a production system.

---

## Step 0: Target discovery

### What I did

```bash
git log --oneline -3
ls -la
task --list-all
ls packages/ openspec/specs/ docs/runbooks/ work_orders/ handoffs/
```

### What I observed

Developer-facing surfaces, inventoried:

| Surface | Location | Size |
|---|---|---|
| Entry README | `README.md` | 38 lines |
| Contributor guide | `CONTRIBUTING.md` | 13 lines |
| Agent contract | `AGENTS.md` | 96 lines |
| Session contract | `CLAUDE.md` | 150 lines |
| Workflow definition | `WORKFLOW.md` | 433 lines |
| Command surface | `Taskfile.yml` | 34,196 bytes, 63 targets |
| Bootstrap script | `bootstrap.sh` | 7,930 bytes |
| Docs site source | `docs/` | 36 markdown files |
| Published docs nav | `mkdocs.yml` | 21 nav entries |
| Packages | `packages/` | 14 packages |
| ADRs | `docs/adr/` | 5 ADRs plus a template |
| Runbooks | `docs/runbooks/` | 16 runbooks |
| OpenSpec specs | `openspec/specs/` | 46 spec directories |
| Work orders | `work_orders/` | 5 changes |
| Handoffs | `handoffs/` | 20 changes |
| Ad-hoc reports | `.planning/reports/` | 24 reports |

Connector-specific surfaces:

- `packages/pulse-core/src/pulse_core/connector/`: the kit: `rows.py` (241 lines),
  `consume.py` (192 lines), `declare.py` (120 lines), `__init__.py`.
- `packages/billing-connector/`: the reference connector: 6 source modules, 9 test modules.
- `openspec/specs/connector-kit/spec.md`: 84 lines, 5 requirements.
- `design/platform/pulse-standard-connector-spec.md`: 315 lines.
- `openspec/specs/connectors/pulse-standard-connector-spec.md`: a second, drifted copy.
- `docs/runbooks/billing-connector.md`: 179 lines, operational only.
- `.planning/reports/2026-08-30-connector-pattern-boundaries.md`: 121 lines.
- `.planning/reports/2026-08-21-connector-template-tier-{1,2,3}-gap-analysis.md`: 895, 834
  and 1,468 lines respectively.
- `scripts/billing-connector/provision_billing_feed.sh`: one shell script.

There is no `templates/connector/`, no `task connector:new`, and no document whose title or
purpose is "how to build a connector."

### Boomerang baseline

```bash
grep -rniIl "devex\|developer experience\|TTHW\|DX score" --include='*.md' . \
  | grep -v node_modules | grep -v '^./site/'
```

Output: empty.

```bash
ls ~/.claude/skills/gstack/bin/
# ls: /Users/Rob.Ford/.claude/skills/gstack/bin/: No such file or directory
```

**NO_PRIOR_PLAN_REVIEW.** No prior `plan-devex-review` score exists anywhere in this repo or
in a gstack review store on this machine. This audit is the first baseline. There is nothing
to boomerang against, and the boomerang comparison section of the skill is not applicable.

### Friction

The task surface is discoverable and well described: `task` on its own prints 63 targets
grouped by area with a one-line description each, and the descriptions carry real operational
information ("needs Docker", "needs that target's credential", "needs CHANGE"). This is the
strongest single piece of DX in the repo.

Against that, the persona's specific job has no entry point. Searching the repo for the phrase
a new joiner would search for produces only meta-commentary:

```bash
grep -rniI "new connector\|scaffold a connector\|connector author" --include='*.md' .
```

Every hit is inside a gap-analysis report or a work order describing what someone *should*
write, for example `.planning/reports/2026-08-21-connector-template-tier-2-gap-analysis.md:285`:
"name the exact files and functions a new connector author edits". The instruction to write
the guide exists. The guide does not.

### What a 10 looks like for this repo

`task connector:new NAME=<x>` scaffolds a package that compiles, typechecks, passes the
credential-posture gate and runs its own fixture-backed test suite on the first invocation,
registering itself in every place the workspace requires. `docs/connectors/authoring.md` is in
the mkdocs nav and is the first hit for "connector" in docs search.

---

## Step 1: Getting started audit

### What I did

Real fresh clone into the scratchpad, every stage timed to the second.

```bash
git clone gh_robford-brookai:robford-brookai/pulse.git .../pulse-fresh
bash bootstrap.sh
task
task install
task check
```

### What I observed

```
=== T0 2026-09-03T02:46:45Z ===
### STAGE clone     SECONDS=3    RC=ok
### STAGE bootstrap SECONDS=0    RC=1
### STAGE task-bare SECONDS=0
### STAGE install   SECONDS=2    RC=0
### STAGE check     SECONDS=130  RC=0
```

**TTHW = 135 seconds** from `git clone` to a green `task check`, excluding the failed
bootstrap detour. That is the skill's Competitive tier (2 to 5 min), 15 seconds past the
Champion boundary (under 2 min).

Two caveats that materially qualify that number:

1. The `uv` cache on this machine is 26 GB (`du -sh ~/.cache/uv`). `task install` resolving 200+
   packages in 2 seconds is a warm-cache time. A genuine first-ever machine pays the download
   cost, which this measurement does not capture.
2. `task check` at 130 seconds is a green *repo* gate, not a green *connector*. The persona's
   actual hello world; a connector that declares one event; was never reached. See Step 2.

**Friction 1: `bootstrap.sh` is a trap for the persona.** The README says nothing about it, but
it is the most bootstrap-shaped file at the repo root and `CLAUDE.md` references it twice. A new
engineer runs it. The result:

```
$ bash bootstrap.sh
bootstrap.sh: line 7: 1: Usage: bootstrap.sh <project-name> <package-name> <description>
```

Exit 1. The message is a shell parameter-expansion artifact (`${1:?...}`), so it reads
`line 7: 1:` before the usage string, which parses as noise. Worse, the script is not an
onboarding script at all; it is the template-instantiation script that renames the package
and rewrites the tree (`bootstrap.sh:20`, `OLD_PACKAGE=$(ls src/)`). Running it successfully in
an already-instantiated repo would be destructive. `docs/ci-lessons.md:116` records that this
script once "destroyed the remote it was given". Nothing in the message tells the persona to
stop.

**Friction 2: prerequisites are never stated.** `README.md` line 8 opens with `task install`.
That requires `go-task` and `uv` to already exist on PATH, plus Node 22 and npm for the
`twenty:test` leg of `check`. Searching for prerequisite statements:

```bash
grep -rniIE "prerequisite|you will need|install uv|install go-task|homebrew" \
  README.md CONTRIBUTING.md docs/index.md AGENTS.md
```

The only hit is `README.md:14`, which discusses Java for `synthea:regen`. The four tools the
quickstart actually needs are unstated. A developer without `task` installed gets
`zsh: command not found: task` and no guidance.

**Friction 3: pre-commit hooks are not installed by anything the persona runs.** After a clean
`git clone` and `task install`:

```bash
$ ls -la .git/hooks/pre-commit
ls: .git/hooks/pre-commit: No such file or directory
```

`CONTRIBUTING.md` states as fact that "Pre-commit hooks run `ruff`, `mypy` and `openlore drift`
on every commit." They do not, on a fresh clone. The only place `pre-commit install` is run is
`bootstrap.sh:175`, which the persona must not run. `tests/scaffold/cat7_gates_hooks.sh:49`
knows this and fails with the right instruction, but nothing invokes cat7 (see Step 6).

**Friction 4: no verification checkpoint short of 130 seconds.** There is no `task doctor`, no
smoke target, nothing between `install` and the full 130-second `check`. The first signal the
persona gets that the environment works is over two minutes of output.

### What a 10 looks like for this repo

README opens with a prerequisites block naming `uv`, `go-task`, Node 22 and Docker with the
one-line install for each. `task install` runs `uv sync` *and* `pre-commit install`, then
prints "environment ready, run `task check`". `bootstrap.sh` refuses to run in a repo whose
`.ade-template-version` is already stamped, with the message "this repo is already
instantiated from repo-ade; you want `task install`". A `task doctor` gives a 5-second
green/red on the toolchain.

---

## Step 2: API/CLI/SDK ergonomics: connector focused

### What I did

Attempted to understand and scaffold a new connector using only what the repo states, then
tested the connector kit's public surface directly.

```bash
task --list-all
uv run python -c "from pulse_core.connector import *"
grep -rn "pulse_core" packages/billing-connector/src/
grep -n "billing-connector|billing_connector" pyproject.toml Taskfile.yml
diff design/platform/pulse-standard-connector-spec.md \
     openspec/specs/connectors/pulse-standard-connector-spec.md
```

### What I observed

**No scaffold command exists.** Of 63 `task` targets, the connector-shaped ones are
`billing-connector:image` and `billing-connector:deploy`, both hardcoded to billing. There is
no `connector:new`, no `templates/connector/`, and `task new-repo` creates a whole repo from
the ADE template, not a connector.

**The kit's advertised public API is broken.** `packages/pulse-core/src/pulse_core/connector/__init__.py`
declares an `__all__` of 24 names, four of which are never imported into the module:

```bash
$ uv run python -c "
import pulse_core.connector as c
print([n for n in c.__all__ if not hasattr(c,n)])"
['DEFAULT_BASE_DELAY_SECONDS', 'DEFAULT_MAX_ATTEMPTS', 'DEFAULT_MAX_DELAY_SECONDS', 'submit_with_retry']

$ uv run python -c "from pulse_core.connector import *"
AttributeError: module 'pulse_core.connector' has no attribute 'DEFAULT_BASE_DELAY_SECONDS'
```

The first line of code a connector author writes against the documented public surface raises.
All four names exist in `pulse_core/connector/declare.py` (lines 42, 43, 44, 67); the
`__init__.py` imports `consume` and `rows` but never `declare`. The module docstring even says
"the declare pipeline joins it as it is extracted", which is stale: `declare.py` is there and
shipped.

**The declare layer is reachable only by deep import.** `billing-connector` imports the consume layer from the package root (`service.py:50`) and reaches past the root for the declare layer, which `__init__.py` never exports; that is why the broken names have no user. `billing-connector`
reaches past the package root into the submodule:

```
packages/billing-connector/src/billing_connector/declare.py:34
    from pulse_core.connector.declare import submit_with_retry
packages/billing-connector/src/billing_connector/receipts.py:17
    from pulse_core.connector.declare import DeclareCounts
```

So the one place a new author would copy from teaches the deep-import path, and the shallow
path is broken. Neither is documented as canonical.

**Registration is manual and spread across eight places.** Grepping for the reference
connector's name shows every location a new package must be added by hand:

| # | File | Line | What |
|---|---|---|---|
| 1 | `pyproject.toml` | 73 | workspace members |
| 2 | `pyproject.toml` | 91 | `[tool.uv.sources]` workspace pin |
| 3 | `pyproject.toml` | 211 | ruff per-file-ignores for tests |
| 4 | `Taskfile.yml` | 19 | `LINT_PATHS` |
| 5 | `Taskfile.yml` | 35 | `TESTED_PATHS` |
| 6 | `Taskfile.yml` | 48 | `COV_PATHS` |
| 7 | `Taskfile.yml` | 138 | pyright invocation |
| 8 | `Taskfile.yml` | 426-448 | image and deploy targets |

Miss #4 and lint silently skips the package. Miss #5 and the tests never run in `check`. Miss
#6 and coverage silently excludes it. Three of the eight fail open, which is the opposite of
the Pit of Success pattern.

**Reading volume to reach competence.** The minimum set a persona must read to understand the
connector contract, with no single document covering it:

```
 315  design/platform/pulse-standard-connector-spec.md
  84  openspec/specs/connector-kit/spec.md
 179  docs/runbooks/billing-connector.md
 121  .planning/reports/2026-08-30-connector-pattern-boundaries.md
  96  AGENTS.md
 433  WORKFLOW.md
 150  CLAUDE.md
 241  pulse_core/connector/rows.py
 192  pulse_core/connector/consume.py
 120  pulse_core/connector/declare.py
```

1,931 lines across 10 files, before the three tier gap-analysis reports (3,197 more lines) that
contain the only concrete guidance about what an author edits. Nothing tells the persona this
is the reading order, or that the `.planning/reports/` tier analyses are the richest source.

Concepts to learn before writing the first line: the command API, the D15 actor-from-credential
rule, the D16 idempotency derivation, the four-way response classification (committed,
replayed, rejected, transient), the durable writer-state cursor, the EventBridge-to-SQS consume
loop, the per-record watermark, the state catalog and its versioning, the producer policy
classifier, the credential-posture gate, and the OpenSpec change lifecycle that must wrap all of
it. Eleven concepts, each defined in a different file.

**Spec drift: two copies of the connector spec, neither authoritative.**

```bash
$ diff design/platform/pulse-standard-connector-spec.md \
       openspec/specs/connectors/pulse-standard-connector-spec.md | wc -l
227
```

227 differing lines between the two copies. Neither is marked canonical and neither references
the other.

**Spec versus reference implementation divergence.** `design/platform/pulse-standard-connector-spec.md`
is titled "PAP Reference Implementation" and structures the whole design around a five-stage
anatomy (section 4.0: Tap, Classifier, Mapper, Emitter, Reconciler) with a work breakdown of
eight one-session work orders, CX-1 through CX-8 (section 9.0). The shipped kit implements
none of that vocabulary. `pulse_core.connector` exposes `RowSource` / `CursorStore` /
`validate_page` (inbound), `consume` / `Deduper` (outbound) and `submit_with_retry` (declare).
There is no `Tap`, no `Classifier`, no `Emitter`, no `Reconciler` in the code. The spec
describes a Postgres logical-replication CDC architecture; `billing-connector` is an SQS
consumer over a fact store. A persona who reads the spec first, as its placement in
`openspec/specs/` invites, learns a vocabulary that does not appear in the code they will write.

**`task` help text quality.** Strong. Descriptions state their preconditions inline
("needs CHANGE", "needs Docker", "needs that target's credential", "needs a real Postgres"),
and `task` on its own sorts by workflow order rather than alphabetically. Naming is consistently
`area:verb` (`twenty:deploy`, `ledger:migrate`, `spec:validate`). Two inconsistencies:
`checkoff`, `collect`, `dispatch`, `replan`, `verify` and `sync-docs` are bare verbs in the
same namespace as the areas, and `sync-docs` is hyphenated where everything else is colon
namespaced. The variable-not-flag convention is documented in `CLAUDE.md:49` and verified below.

### What a 10 looks like for this repo

`from pulse_core.connector import *` works. One canonical `docs/connectors/authoring.md`
replaces the ten-file reading set and opens with a working 30-line connector. `task
connector:new NAME=x` writes the package and every one of the eight registrations. The
`design/platform` and `openspec/specs/connectors` copies are collapsed to one, with the shipped
kit's vocabulary, and the PAP-era CX work breakdown is archived rather than presented as the
current plan.

---

## Step 3: Error message audit

Nine mistakes triggered and one inferred (E10), all realistic for the persona. Each is scored against the skill's
formula: what happened + why + how to fix + where to learn more + the actual values.

### E1: flag-style task argument

```bash
$ task dispatch --change=connector-pattern; echo "rc=$?"
Usage: task [flags...] [task...]
...
rc=2
```

Problem: yes, indirectly. Cause: no. Fix: no. The output is go-task's generic usage banner. It
does contain the string `unknown flag`, matching the claim in `CLAUDE.md:49`, but buried below
the banner, which is exactly the TypeScript anti-pattern the skill names: the most actionable
line is not first. A persona who read `CLAUDE.md` recognizes it; one who did not learns nothing
about `CHANGE=`.

### E2: missing required variable

```bash
$ task dispatch
task: [dispatch] uv run python scripts/dispatch_tasks.py --change
usage: dispatch_tasks.py [-h] --change CHANGE [--output OUTPUT] ...
dispatch_tasks.py: error: argument --change: expected one argument
task: Failed to run task "dispatch": exit status 2
```

Problem: yes. Cause: leaked, and misleading; it names the internal script's `--change` flag,
not the `CHANGE=` variable the user must set. Fix: no. The user is told to fix a flag they
never typed. The Taskfile has no `requires:` guard.

### E3: nonexistent change id

```bash
$ task dispatch CHANGE=my-new-connector
Error: openspec/changes/my-new-connector/tasks.md not found
task: Failed to run task "dispatch": exit status 1
```

Problem: yes, with the exact path. Cause: implicit. Fix: no. It does not say how to create a
change (`openspec propose`, or the `openspec-propose` skill) or list the changes that do exist.
Compare Stripe's `resource_missing`, which carries a `doc_url`.

### E4: connector run with no environment

```bash
$ env -i PATH=... uv run python -m billing_connector.service
Traceback (most recent call last):
  ...
  File ".../billing_connector/service.py", line 271, in main
    config = Config.from_env()
  File ".../billing_connector/config.py", line 148, in from_env
    raise MissingConfigVariableError(TOKEN_ENV_VAR)
billing_connector.config.MissingConfigVariableError: required environment variable BILLING_CONNECTOR_TOKEN is not set
```

Problem: yes, and it names the variable. Cause: yes. Fix: no; no statement of where the value
comes from or which credential store holds it. Delivered as an uncaught traceback with six
frames of internals above the one useful line, so the actionable text is last.

Worse, it fails one variable at a time:

```bash
$ env -i ... BILLING_CONNECTOR_TOKEN=x BILLING_CONNECTOR_QUEUE_URL=y \
    uv run python -m billing_connector.service
billing_connector.config.MissingConfigVariableError: required environment variable BILLING_CONNECTOR_LEDGER_BASE_URL is not set
```

Three required variables (raise sites `config.py` lines 148, 152, 156) means up to three edit-rerun cycles
to discover the full set. The skill's Feedback Loops dimension is directly hit.

### E5: bad environment *value* (not missing)

```bash
$ env -i ... BILLING_CONNECTOR_STALE_AFTER=banana uv run python -c \
    "from billing_connector.config import Config; Config.from_env()"
  File ".../config.py", line 159, in from_env
    stale_after = _DEFAULT_STALE_AFTER if stale_after_raw is None else timedelta(seconds=int(stale_after_raw))
ValueError: invalid literal for int() with base 10: 'banana'
```

Problem: partially. Cause: no. Fix: no. This is the worst error in the repo. It does not name
the environment variable, does not say the expected unit is seconds, and surfaces a raw
`int()` failure. The missing-variable path has a custom exception class; the invalid-value path
on the adjacent line has none.

### E6: wrong import from the documented public surface

```bash
$ uv run python -c "from pulse_core.connector import *"
AttributeError: module 'pulse_core.connector' has no attribute 'DEFAULT_BASE_DELAY_SECONDS'
```

Problem: yes. Cause: no; it reads as though the persona asked for something that does not
exist, when in fact the package's own `__all__` promised it. Fix: no. This error actively
misdirects.

### E7: gate run against an archived change

```bash
$ task verify CHANGE=connector-pattern
...
task: [spec:validate] openspec validate connector-pattern
Unknown item 'connector-pattern'. Did you mean: connector-kit, coverage-state, month-open, identity-matching, verdict-relay-run?
task: Failed to run task "verify": task: Failed to run task "spec:validate": exit status 1
```

Problem: yes. Cause: no; the real cause is that `connector-pattern` was archived to
`openspec/changes/archive/2026-09-02-connector-pattern/`, which the message never says. Fix:
attempted, and wrong: the five suggestions are all *spec* names, not *change* names, so
following any of them fails differently. A good "did you mean" that suggests from the wrong
namespace is worse than none.

### E8: gate with the variable omitted entirely

```bash
$ task spec:validate
task: [spec:validate] openspec validate
Nothing to validate. Try one of:
  openspec validate --all
  openspec validate --changes
  openspec validate --specs
  openspec validate <item-name>
```

Problem: yes. Cause: yes. Fix: yes, four concrete alternatives. This is the best error message
encountered, and it comes from `openspec`, a third-party tool, not from this repo. The Taskfile
still passed an empty argument through rather than guarding on `CHANGE`.

### E9: a scaffold gate on a fresh clone

```bash
$ cd .../pulse-fresh && bash tests/scaffold/cat7_gates_hooks.sh; echo "rc=$?"
FAIL: clean commit was blocked, run '.../.venv/bin/pre-commit run --all-files' in the sandbox to see why
PASS: hook ran on commit: ruff-check
PASS: hook ran on commit: ruff-format
PASS: hook ran on commit: openlore-drift
PASS: lint violation blocks the commit
FAIL: drift clean in the bootstrapped sandbox

Gate 7: 17 passed, 4 failed
rc=1
```

Problem: yes, per assertion. Cause: no. Fix: partially; the first FAIL gives a concrete
command to run, which is the right shape. But a freshly cloned repo fails its own gate, and
the message does not say that this is expected on a clone without hooks installed.

### E10: the missing-tool case

```bash
$ which openspec openlore
/opt/homebrew/bin/openspec
/opt/homebrew/bin/openlore
```

Both are present on this machine, so the missing-tool error could not be triggered without
uninstalling them, which the read-only constraint forbids. `docs/contracts/consumes.md` and
`CLAUDE.md:76` record that these are npm globals deliberately kept out of `task check` because
CI runners lack them. INFERRED, not tested: nothing in `task verify` guards on their presence,
so a machine without them gets a bare `command not found` from the shell rather than an
instruction to `npm i -g`.

### Summary

Of ten error scenarios, one (E8) states problem, cause and fix, and it comes from a third-party
tool. Zero contain a documentation link. Four (E4, E5, E6, E9) surface as raw Python tracebacks
or bare assertion output. The repo has one custom exception class in the connector path
(`MissingConfigVariableError`) and it covers exactly one failure mode.

### What a 10 looks like for this repo

Every Taskfile target that needs a variable declares `requires: vars: [CHANGE]`, so E2 and E8
become "task: task 'dispatch' requires variable CHANGE". `Config.from_env()` collects all four
missing or invalid variables and raises once, naming each variable, its expected form, its unit
and the runbook section that supplies the value. E3 lists the changes that do exist. The
`__all__` mismatch in E6 is caught by a test rather than by a developer.

---

## Step 4: Documentation audit

### What I did

```bash
task check          # includes docs:build, i.e. mkdocs build -s
cat mkdocs.yml docs/index.md docs/modules.md
find docs -name '*.md' | wc -l
```

### What I observed

**`mkdocs build -s` is green.** No dead links, no broken references. The strict build passes
inside the 130-second `check`. Link hygiene is genuinely good, and `CLAUDE.md` explains why
(placeholders are inline code, never link syntax).

**The docs site is still the template's.** `mkdocs.yml` lines 1 through 8:

```yaml
site_name: repo-ade
repo_url: https://github.com/robford-brookai/repo-ade
site_url: https://robford-brookai.github.io/repo-ade
site_description: Repository agent development environment scaffold
repo_name: robford-brookai/repo-ade
```

`docs/index.md`, the page a persona lands on, is titled `# repo-ade`, carries four shields.io
badges pointing at the `repo-ade` repository, and its entire body is the sentence "Repository
agent development environment scaffold". Nothing on the docs home page mentions PULSE, the
ledger, or connectors.

`docs/modules.md`, the API reference, is one line:

```
::: pkg_pulse.foo
```

and `mkdocs.yml` scopes mkdocstrings to `paths: ["src/pkg_pulse"]`, the placeholder package. No
API documentation is generated for `pulse_core`, for the connector kit, or for any of the 14
real packages. A persona looking for the kit's API in the docs finds `foo`.

**15 of 36 docs pages are outside the nav.** From the `check` output:

```
INFO - The following pages exist in the docs directory, but are not included in the "nav" configuration:
  - ci-lessons.md
  - mcp-servers.md
  - adr/ADR-0000-template.md ... adr/ADR-0005-customerio-consent-on-the-governed-path.md
  - architecture/README.md
  - process/dispatch-template.md
  - process/env-vars-retreival.md
  - process/workflow-drift-review.md
  - runbooks/demo1-ledger-core.md
  - runbooks/verdict-relay.md
```

All five ADRs are unreachable from the nav, as is every process document. `docs/ci-lessons.md`
is unreachable despite `CLAUDE.md:82` instructing readers to read it before editing a workflow.
Two runbooks are omitted while fourteen siblings are listed, which reads as drift rather than
intent. `docs/process/env-vars-retreival.md` has a spelling error in its filename, so it will
never be found by a search for "retrieval".

**Does the connector documentation answer the persona's questions in order?** Their sequence,
and where each answer lives:

| # | Question | Answered in | Findable from docs site? |
|---|---|---|---|
| 1 | What is a connector? | `design/platform/pulse-standard-connector-spec.md` §1.0 | No, outside `docs/` |
| 2 | What must mine guarantee? | `openspec/specs/connector-kit/spec.md` | No, outside `docs/` |
| 3 | What library do I build on? | `pulse_core/connector/__init__.py` docstring | No, mkdocstrings points at `pkg_pulse` |
| 4 | What do I copy? | `packages/billing-connector/` | No, source only |
| 5 | Where do I register it? | Nowhere; inferred from 8 grep hits | No |
| 6 | How do I test it? | `packages/billing-connector/tests/conftest.py` | No |
| 7 | How do I ship it? | `WORKFLOW.md` plus `AGENTS.md` | No, repo root |
| 8 | How do I operate it? | `docs/runbooks/billing-connector.md` | Yes |

The one connector question the docs site answers is the last one. Questions 1 through 7 are
answered in files outside `docs/`, in a different order than they are asked, and question 5 is
not answered anywhere.

**Currency.** `docs/runbooks/billing-connector.md` is operational throughout: "What this service
is, and is not", "Prerequisites", "Steps", "Start / stop", "Reading the receipt",
"Rebuild-from-bus procedure", "Rollback". It is a good runbook. It is not, and does not claim to
be, an authoring guide, and no authoring guide exists to sit beside it.

### What a 10 looks like for this repo

`mkdocs.yml` names PULSE and points at the pulse repo. `docs/index.md` is a landing page with
three paths: operate a service, build a connector, change the ledger. mkdocstrings generates
`pulse_core` and the connector kit. The nav includes every ADR and every process doc, and the
docs-consistency gate (`cat8`) fails when a page is added outside the nav rather than logging it
at INFO.

---

## Step 5: Upgrade path audit

### What I did

```bash
task template:diff
cat .ade-template-version
ls docs/adr/
ls openspec/changes/archive/ | head
```

### What I observed

**Template sync is the strongest upgrade mechanism in the repo.**

```bash
$ task template:diff
Fetching https://github.com/robford-brookai/repo-ade.git ...
Template changes a1de595b..fc72974b (infrastructure paths only):
Rewriting package name repo_ade -> pkg_pulse.

 Taskfile.yml                            |   38 +
 scripts/checkoff_tasks.py               |  168 +++
 scripts/dispatch_tasks.py               |  551 +++++++++++
 ...
 15 files changed, 2981 insertions(+), 26 deletions(-)

Apply with: task template:sync
```

Problem, scope, diffstat and the exact next command, in one output, with the package rename
handled automatically. This is the Next.js codemod pattern applied to a repo template, and it is
the best DX artifact in the repo. `.ade-template-version` pins the source commit
(`a1de595b8591691a624d67d60efaa20d73641967`), so the diff is exact rather than heuristic.

The caveat is the drift it reveals: 2,981 insertions pending, including changes to
`dispatch_tasks.py` (551 lines) and `cat5_glue_logic.py` (1,011 lines), which are the glue the
ADE workflow runs on. The mechanism is excellent; it has not been exercised recently.

**ADR discipline is real but unpublished.** Five ADRs plus a template, append-only per
`CLAUDE.md`. Every one is outside the mkdocs nav (Step 4), so the decision record exists and is
unreachable from the docs site.

**Spec archiving works and is used.** `openspec/changes/archive/2026-09-02-connector-pattern/`
holds the archived change with its `design.md`. `task spec:archive` merges deltas into
`openspec/specs/`. The lifecycle is coherent.

**How does a connector author absorb a kit change?** There is no answer. There is no CHANGELOG
in the repo, no version on `pulse-core` beyond `0.1.0`, and `[tool.uv.sources] pulse-core =
{ workspace = true }` means every connector tracks the kit at HEAD with no pin. A breaking
change to `RowSource` lands in every connector at the same commit. The kit spec's own
requirement, "the kit has no behavior that is not already proven by a shipped integration",
mitigates this by construction but does not communicate it. Grepping for deprecation machinery
finds nothing: no `DeprecationWarning`, no deprecation policy in any spec.

`.planning/reports/2026-08-21-connector-template-tier-3-gap-analysis.md:1218` records exactly
this: "There is no consumer registry, no notification, and nothing that tells a connector
author" when a change affects them.

### What a 10 looks like for this repo

`pulse-core` carries a CHANGELOG with a "connector authors" section per entry. Kit changes that
alter a connector-facing signature ship with a `DeprecationWarning` for one release and a note
in `docs/connectors/upgrading.md`. `task template:diff` is run on a schedule so the pending
delta never reaches 2,981 lines.

---

## Step 6: Developer environment audit

### What I did

```bash
cat .pre-commit-config.yaml .python-version tox.ini
sed -n '1,60p' .github/workflows/main.yml
ls -a | grep -iE "editorconfig|vscode|idea"
grep -rn "0000000000000000000000000000000000000000" .github/
sed -n '170,180p' Taskfile.yml
```

### What I observed

**Local and CI parity is designed for and enforced.** `.github/workflows/main.yml:50` runs
exactly `task check`, and `tests/scaffold/cat4_ci_contract.py` asserts that every `run:` command
in the workflow resolves to a defined Taskfile target or an installed tool. The comment on that
step records the failure it prevents: "This step previously ran `make check` against a repo with
no Makefile, and every run failed for a week." The contract in `CLAUDE.md` ("green locally means
green in CI") is mechanically true, not aspirational. This is a genuine strength.

**Versions are pinned thoroughly.** Every GitHub Action is pinned to a commit SHA with the
version in a trailing comment. `.python-version` pins 3.14. `uv.lock` is 569 KB and
`task docs:lock-guard` fails if it drifts from `pyproject.toml`. The test matrix covers Python
3.10 through 3.14, five versions, `fail-fast: false`.

**Four GitHub Action pins are all-zeros SHAs.**

```bash
$ grep -rn "0000000000000000000000000000000000000000" .github/
.github/workflows/ci-health.yml:11:  uses: actions/checkout@0000000000000000000000000000000000000000 # v4.0
.github/workflows/auto-heal.yml:16:  uses: actions/checkout@0000000000000000000000000000000000000000 # v4.0
.github/workflows/auto-heal.yml:100: uses: peter-evans/re-run-workflow@0000000000000000000000000000000000000000 # v2.0
.github/workflows/auto-heal.yml:111: uses: actions/github-script@0000000000000000000000000000000000000000 # v7.0
```

Both workflows are unrunnable. `ci-health.yml` is `workflow_dispatch` only and `auto-heal.yml`
is the CI self-repair loop, so neither failure is visible on a normal PR. `cat4_ci_contract.py`
checks that commands resolve to targets; it does not validate action SHAs, so the gate that
exists for exactly this class of problem does not catch it.

**Three scaffold gates run in no automated context.** `CLAUDE.md:88` states "gates 2, 4, 7 are
shell scripts, run directly". `task test:all` is:

```yaml
test:all:
  desc: Run tests including the slow scaffold gates
  cmds:
    - uv run pytest {{.TESTS}} -m "slow or not slow" {{.COV_PATHS}} --cov-report=term-missing
```

pytest only, and pytest collects `cat[0-9]_*.py`, not `.sh`. Grepping `main.yml` for `cat2`,
`cat4`, `cat7` or `.sh` finds only a comment. (`cat4_ci_contract.py` is a separate,
pytest-collected gate and does run; its shell sibling `cat4_command_contract.sh` does not.) So `cat2_toolchain.sh`, `cat4_command_contract.sh` and
`cat7_gates_hooks.sh` are invoked by nothing: not by `check`, not by `test:all` despite its
description, not by CI. E9 above showed cat7 currently failing 4 assertions on a fresh clone
with rc=1, and no automated run would ever surface that.

**No editor or IDE support.** No `.editorconfig`, no `.vscode/`, no `.idea/`, no devcontainer at
the repo root (`.pre-commit-config.yaml` excludes a `.devcontainer/devcontainer.json` that does
not exist). Formatting is enforced by ruff at commit time rather than offered at edit time, so a
new engineer's first commit is likely rewritten by a hook. `CONTRIBUTING.md` warns about this
("A hook that rewrites a file fails the commit by design — re-stage and commit again"), which is
honest but is a workaround for a missing `.editorconfig`.

**Pre-commit hooks not installed on clone**, covered in Step 1, belongs here too: it is the
single highest-leverage one-line fix in the repo.

### What a 10 looks like for this repo

`task install` installs hooks. `task test:all` actually runs the three shell gates its
description promises. A gate validates that every action pin is a 40-hex SHA that resolves.
An `.editorconfig` and a checked-in `.vscode/settings.json` wire ruff and mypy so the first
commit is clean.

---

## Step 7: Community and ecosystem audit

### What I did

```bash
ls .github/ISSUE_TEMPLATE .github/CODEOWNERS .github/PULL_REQUEST_TEMPLATE.md
grep -rniIE "slack|ask in|questions to|contact|discussion" \
  README.md CONTRIBUTING.md AGENTS.md CLAUDE.md docs/index.md
ls work_orders/ handoffs/
```

### What I observed

This is an internal monorepo, so the skill's community dimension maps to internal equivalents.

**The internal ecosystem is unusually strong.** `work_orders/` holds dispatched task files for
5 changes; `handoffs/` holds `SUMMARY.md` receipt records for 20 changes; `WORKFLOW.md` defines
a nine-step graph (propose, validate, sync_linear, dispatch, execute, collect, doc_update,
verify, merge, archive) with four gates and a state-resolution order; `task linear:sync` projects
`tasks.md` into Linear issues and writes `[DNA-nnn]` id tokens back. A new engineer can read the
handoff record for any past change and see what was decided, by whom, and against which commit.
That is better provenance than most open source projects offer.

**There is no "where to ask".**

```bash
$ grep -rniI "slack|ask in|questions to|contact|discussion" \
    README.md CONTRIBUTING.md AGENTS.md CLAUDE.md docs/index.md
README.md:8:task install
CONTRIBUTING.md:4:task install
```

Two false positives on the substring "task in". No Slack channel, no owner, no escalation path
is named in any entry document. `AGENTS.md` has a "When to Stop" section for agents; the human
equivalent does not exist.

**No GitHub collaboration scaffolding.** No `.github/ISSUE_TEMPLATE/`, no
`PULL_REQUEST_TEMPLATE.md`, no `CODEOWNERS`. `CLAUDE.md` states that destructive and
prod-touching tasks "are tracked as GitHub issues and run attended", so issues carry real
workflow weight, and there is no template for them. `CONTRIBUTING.md` is 13 lines and covers
`task install`, `task check`, `task fmt` and hooks. It does not cover branch naming, PR
expectations, review, or who to ask.

**Contribution path for the persona.** `AGENTS.md` is genuinely good as a contract: tests first,
one task equals one commit, never edit spec files, write proposed spec changes to `HANDOFF.md`.
It is written for agents in Orca worktrees. A human engineer joining the team is not addressed by
any document; they are expected to infer their path from the agent contract.

### What a 10 looks like for this repo

`CONTRIBUTING.md` names the Slack channel and the owner for each package area, and states the
branch and PR conventions that `CLAUDE.md` currently holds. `.github/ISSUE_TEMPLATE/` has one
template for the attended-run issues the workflow already depends on. `CODEOWNERS` routes
`packages/pulse-core/src/pulse_core/connector/**` to the kit owner so a connector-affecting
change gets the right reviewer automatically.

---

## Step 8: DX measurement audit

### What I did

```bash
grep -rniIl "devex|developer experience|TTHW|DX score" --include='*.md' .
cat .github/workflows/ci-health.yml .github/scripts/ci_health.sh
ls .github/scripts/
```

### What I observed

**The repo does not measure its own developer experience.** No onboarding time is recorded
anywhere, no gate duration is tracked over time, no drift count is trended, no survey or
feedback mechanism exists. The grep for DX vocabulary returns nothing.

**Two adjacent mechanisms exist and both are partly broken.**

`.github/workflows/ci-health.yml` runs `.github/scripts/ci_health.sh`, which retries `uv sync`
three times and verifies that `pydantic` and `uvicorn` import. That is an environment
reproducibility check, the closest thing to a DX metric here. It is `workflow_dispatch` only,
so it never runs on a schedule, and its `actions/checkout` pin is the all-zeros SHA from Step 6,
so it cannot run at all.

`.github/scripts/aggregate_diagnostics.sh` and `.github/workflows/auto-heal.yml` are a CI
self-repair loop, which is DX-adjacent instrumentation. `auto-heal.yml` carries three all-zeros
action pins and is likewise unrunnable.

**Feedback surfaces that do exist.** `docs/ci-lessons.md` is a written record of failure modes
that no gate can express, with dated entries and root causes, and `CLAUDE.md:82` makes reading
it mandatory before editing a workflow. That is a real learning loop, manually maintained. The
`.planning/reports/2026-08-21-connector-template-tier-{1,2,3}-gap-analysis.md` set is a
deliberate, thorough audit of what a connector author lacks: 3,197 lines of exactly the right
analysis. Neither has produced a metric, a target, or a recurring measurement.

Against the skill's SPACE and DevEx frameworks: none of the five SPACE dimensions is measured.
Of the three DevEx dimensions, Feedback Loops is partially instrumented by CI timing that nobody
reads, Cognitive Load is analyzed in prose in the tier reports but not quantified, and Flow State
is untouched.

### What a 10 looks like for this repo

`task check` records its wall time to an append-only local log so gate duration is trended
rather than felt. A `tests/scaffold/` gate asserts that a fresh clone reaches green in under
N seconds, making TTHW a regression-testable number. The tier gap-analysis findings are
converted into a checklist whose completion percentage is visible. `ci-health.yml` runs nightly
with a working checkout pin.

---

## Connector author journey

Ordered narrative of the persona's path, with elapsed time from `git clone` at T+0. Times
before T+3:00 are measured; times after are the observed cost of the reading and searching I
actually performed, since the persona cannot complete the task at all.

| Time | Action | Outcome |
|---|---|---|
| T+0:00 | `git clone` | Success, 3 seconds |
| T+0:03 | Read `README.md` | Quickstart is `task install` then `task check`. No prerequisites listed. |
| T+0:05 | Sees `bootstrap.sh` at the root, runs it | **Stuck point 1.** `bootstrap.sh: line 7: 1: Usage: ...`, exit 1. Malformed message. The script is the template instantiator and must not be run here; nothing says so. |
| T+0:08 | Falls back to `task` | 63 targets listed with good descriptions. Reassuring. |
| T+0:10 | `task install` | Success in 2 seconds on a warm 26 GB uv cache. |
| T+0:12 | `task check` | Green in 130 seconds. First real confidence signal. |
| T+2:22 | Looks for how to build a connector | **Stuck point 2.** No `task connector:new`. `grep -rniI "new connector"` returns only gap-analysis reports describing the guide that should exist. |
| T+3:00 | Reads `design/platform/pulse-standard-connector-spec.md` | Learns a five-stage anatomy (Tap, Classifier, Mapper, Emitter, Reconciler) and a CX-1..CX-8 work breakdown. |
| T+12:00 | Opens `pulse_core/connector/` to find those stages | **Stuck point 3.** None of that vocabulary exists in the code. The kit is `RowSource`, `CursorStore`, `consume`, `submit_with_retry`. The spec they just read describes a different architecture. |
| T+15:00 | Finds `openspec/specs/connectors/pulse-standard-connector-spec.md` | **Stuck point 4.** A second copy of the same spec, 227 lines different, neither marked canonical. |
| T+18:00 | Reads `openspec/specs/connector-kit/spec.md` | 84 lines, 5 requirements. Finally the right contract, in the right vocabulary. Nothing pointed here first. |
| T+22:00 | Writes the first line: `from pulse_core.connector import *` | **Stuck point 5.** `AttributeError: module 'pulse_core.connector' has no attribute 'DEFAULT_BASE_DELAY_SECONDS'`. The package's own `__all__` promises four names it does not import. |
| T+25:00 | Copies the import style from `billing-connector` instead | Works, via the deep path `from pulse_core.connector.declare import submit_with_retry`. The declare layer is reachable only by deep import; the reference implementation imports the consume layer from the root. |
| T+30:00 | INFERRED, not performed: would create `packages/my-connector/` and run `task check` | Would pass, and mean nothing: the package is in no `LINT_PATHS`, no `TESTED_PATHS`, no `COV_PATHS`. **Stuck point 6.** Three of the eight required registrations fail silently open. |
| T+40:00 | Greps for `billing-connector` to find the registrations | Finds all eight by hand across `pyproject.toml` and `Taskfile.yml`. No document lists them. |
| T+50:00 | Tries to run the reference connector to see the shape | **Stuck point 7.** `MissingConfigVariableError: required environment variable BILLING_CONNECTOR_TOKEN is not set`, as a traceback, one variable at a time, three times. |
| T+55:00 | Sets `BILLING_CONNECTOR_STALE_AFTER` to a guess | **Stuck point 8.** `ValueError: invalid literal for int() with base 10: 'banana'`. No variable name, no unit. |
| T+60:00 | Commits | **Stuck point 9.** No hooks fired: `.git/hooks/pre-commit` does not exist on a fresh clone, contradicting `CONTRIBUTING.md`. CI will catch what the hooks would have. |
| T+65:00 | Tries to open a change through the ADE workflow | `task dispatch CHANGE=my-connector` gives `Error: openspec/changes/my-connector/tasks.md not found`, with no instruction on how to create one. Reads all 433 lines of `WORKFLOW.md`. |

The persona reaches a green `task check` in 2 minutes 15 seconds and does not reach a working
connector at all. The TTHW for the repo's own gate is Competitive tier. The TTHW for the persona's
actual hello world is unbounded, because no path exists.

---

## Top 10 friction points, ordered by impact on connector authors

1. **No connector authoring guide and no scaffold command.** Nothing in the repo tells a new
   engineer how to build a connector. `grep -rniI "new connector\|scaffold a connector\|connector
   author"` returns only gap-analysis reports and work orders describing the guide that should
   exist. There is no `task connector:new`, no `templates/connector/`. Everything below is
   downstream of this. Fixing it converts a multi-day archaeology exercise into a session.

2. **The kit's advertised public API raises on import.**
   `packages/pulse-core/src/pulse_core/connector/__init__.py` lists `submit_with_retry`,
   `DEFAULT_MAX_ATTEMPTS`, `DEFAULT_BASE_DELAY_SECONDS` and `DEFAULT_MAX_DELAY_SECONDS` in
   `__all__` without importing them, so `from pulse_core.connector import *` fails with
   `AttributeError`. The reference connector sidesteps this by deep-importing from
   `pulse_core.connector.declare`, so the broken surface has no user and stays broken. One-line
   fix, plus a test.

3. **Eight manual registrations, three of which fail silently open.** A new connector package
   must be added to `pyproject.toml` (lines 73, 91, 211) and `Taskfile.yml` (lines 19, 35, 48,
   138, 426-448). Omitting `LINT_PATHS`, `TESTED_PATHS` or `COV_PATHS` produces a green
   `task check` that lints nothing, tests nothing and reports no coverage gap. This is the
   opposite of the Pit of Success.

4. **The connector spec describes a different architecture than the kit implements, and exists
   in two drifted copies.** `design/platform/pulse-standard-connector-spec.md` and
   `openspec/specs/connectors/pulse-standard-connector-spec.md` differ by 227 lines, neither is
   marked canonical, and both describe a PAP CDC design (Tap, Classifier, Mapper, Emitter,
   Reconciler; work orders CX-1 through CX-8) whose vocabulary appears nowhere in
   `pulse_core.connector` or in `billing-connector`. A persona who reads the spec first, as its
   placement invites, learns the wrong model.

5. **Connector configuration errors are raw tracebacks, one variable at a time.**
   `Config.from_env()` raises on the first missing variable of three, as an uncaught exception
   with six frames above the useful line, and never says where the value comes from. The
   adjacent invalid-value path (`config.py:159`) is worse: `ValueError: invalid literal for
   int() with base 10: 'banana'` names neither the variable nor the unit. Three edit-rerun cycles
   to discover a three-variable contract.

6. **Pre-commit hooks are not installed by anything the persona runs.** After `git clone` and
   `task install`, `.git/hooks/pre-commit` does not exist, contradicting `CONTRIBUTING.md`. Only
   `bootstrap.sh:175` installs them, and `bootstrap.sh` must not be run in this repo.
   `cat7_gates_hooks.sh` detects it, and nothing runs cat7. Adding `uv run pre-commit install`
   to `task install` is the highest-value one-line change available.

7. **`bootstrap.sh` is a trap with a malformed error.** The most bootstrap-shaped file at the
   repo root is the template instantiator, not the onboarding script. Running it prints
   `bootstrap.sh: line 7: 1: Usage: ...` (a `${1:?}` artifact), and `docs/ci-lessons.md:116`
   records that a successful run once "destroyed the remote it was given". It should refuse to
   run against a repo with a stamped `.ade-template-version` and redirect to `task install`.

8. **The docs site is the template's, and generates API docs for a placeholder.**
   `mkdocs.yml` still reads `site_name: repo-ade` with `repo_url` pointing at the template repo;
   `docs/index.md` is the repo-ade landing page; `docs/modules.md` is `::: pkg_pulse.foo` and
   mkdocstrings is scoped to `src/pkg_pulse`. No API documentation is generated for
   `pulse_core`, for the connector kit, or for any of the 14 real packages. Fifteen of 36 docs
   pages, including all five ADRs, are outside the nav.

9. **Three scaffold gates run in no automated context, and one currently fails.**
   `CLAUDE.md:88` says gates 2, 4 and 7 are shell scripts run directly. `task test:all` is
   pytest-only despite its description, and `main.yml` never invokes them. `cat7_gates_hooks.sh`
   exits 1 with 4 failures on a fresh clone today and no automated run surfaces it. Separately,
   four GitHub Action pins in `ci-health.yml` and `auto-heal.yml` are all-zeros SHAs, so both
   workflows are unrunnable and `cat4_ci_contract.py` does not check pin validity.

10. **Prerequisites and "where to ask" are both unstated.** `README.md` opens with `task
    install`, which needs `go-task`, `uv`, Node 22 and Docker, none of them named. No Slack
    channel, owner, or escalation path appears in `README.md`, `CONTRIBUTING.md`, `AGENTS.md`,
    `CLAUDE.md` or `docs/index.md`, and there is no `CODEOWNERS`, issue template or PR template.
    A blocked engineer has nowhere to go, which multiplies the cost of every item above.

---

## Method notes and limits

- Fresh clone at `/private/tmp/.../scratchpad/pulse-fresh`, logs at `onboard.log` and
  `check.log` in the same directory.
- `task install` timing is warm-cache (26 GB `~/.cache/uv`). A cold-cache figure was not
  measured and would be materially higher.
- `openspec` and `openlore` are installed on this machine, so the missing-tool error class
  (E10) is INFERRED rather than TESTED; uninstalling them would have violated the read-only
  constraint.
- No production system was contacted. Every credentialed target (`demo:3`, `demo:4`,
  `twenty:deploy`, `ledger:deploy`, `projection:*`, `relay:run`, `snowflake:*`) was left
  untouched.
- No tracked file was modified. The only file written is this report.
- No PHI appears in this report. All error output quoted was produced from synthetic or empty
  inputs.
