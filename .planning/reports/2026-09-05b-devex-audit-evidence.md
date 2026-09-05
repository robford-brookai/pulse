# DevEx audit evidence, 2026-09-05b

> Corrected by the coordinator per the QA report (`2026-09-05b-devex-audit-qa.md`, section 7): C-A1 to C-A9 applied (repo-footprint claim, README line count, pyproject line, owner grep, ledger row count, diff summary, mistake count, abridged block label, screenful wording).

Repo: `/Users/Rob.Ford/Repos/robford-brookai/pulse` at `5177d05` on `main`.
Methodology: `docs/process/devex-audit/rubric.md` (frozen), audit steps 0 through 8.
Persona: a competent engineer joining the team whose first job is a new **labs** connector.

Evidence only. No scores are assigned here; scoring is Task B's job and the boomerang comparison
against prior audits is Task C's job, not this document's.

Every observation is tagged **TESTED** (I ran it and quote the output), **PARTIAL** (I ran part of
it), or **INFERRED** (reasoned from the tree, not run).

Machine: darwin 25.6.0, arm64. Toolchain present before the audit started: `uv 0.12.8`,
`task 3.53.1`, `node v26.8.1`, `npm 11.19.0`, `docker 29.7.2`, `gh 2.98.0`, `openspec 1.7.0`,
`openlore 2.1.7`, `openjdk 17.0.16`. Ambient `~/.cache/uv` was 26G (warm). **TESTED.**

Scratch clone: `/private/tmp/claude-502/-Users-Rob-Ford-Repos-robford-brookai-pulse/f762ace5-5258-40cf-9a29-e153b5d3a69c/scratchpad/audit4/scratch/pulse`.
No tracked file in the repo under audit was modified. All destructive experiments ran in the
scratch clone and were reset with `git reset --hard 5177d05`.

---

## Step 0. Target discovery

### What I did

```bash
ls -a
task                       # the default listing
task -l                    # the alphabetical listing
find .github -type f
ls docs/ design/ packages/ templates/ scripts/
```

### What I observed

**Developer-facing surfaces, TESTED unless noted.**

| Surface | What is there |
| --- | --- |
| Entry docs | `README.md` (360 lines, with Prerequisites + Quickstart), `CONTRIBUTING.md` (24 lines), `CLAUDE.md`, `AGENTS.md`, `WORKFLOW.md` |
| Docs site | `mkdocs.yml` with a nav; `docs/index.md`, `docs/connectors/authoring.md`, `docs/adr/` (6 files), `docs/contracts/`, `docs/runbooks/`, `docs/process/`, `docs/ci-lessons.md`, `docs/mcp-servers.md` |
| Design tree | `design/platform/`, `design/migration/`, `design/delivery/` |
| Task targets | 68 targets. `task` and `task -l` both list 68; the default target groups them by area, `-l` is alphabetical |
| Packages | 14 under `packages/` (12 Python workspace members, `twenty-app` and `twenty-model` TypeScript) |
| Templates | `templates/connector/` (20 `.tmpl` files, including a `direction/inbound/` overlay), `templates/HANDOFF.md` |
| Scaffolding | `task connector:new NAME=<n> DIRECTION=outbound|inbound` backed by `scripts/connector_new.py`; `task new-repo` for a whole new repo from this template |
| Glue scripts | `scripts/dispatch_tasks.py`, `scripts/collect_handoffs.py`, `scripts/workflow.py`, `scripts/connector_new.py`, `scripts/devex/{check,timing}.py`, `scripts/demo/` |
| Gates | `tests/scaffold/cat1..cat10` (`cat10_devex.py` is the DX ratchet) |
| Repo hygiene | `.github/CODEOWNERS`, `.github/PULL_REQUEST_TEMPLATE.md`, two issue templates (`attended-run.yml`, `connector-kit-defect.yml`), 6 workflows |
| Spec surface | `openspec/specs/` baseline plus 4 active changes: `billing-connector`, `devex-eight`, `devex-eight-2`, `devex-eight-3` |

Two entry points name the connector path explicitly, which matters for the persona.
`docs/index.md:34-35`:

> Building a connector — a package that moves facts between an external system and the ledger?
> Start at [Authoring a connector](connectors/authoring.md) instead of reading this site

`README.md` links `docs/connectors/authoring.md` from its Connectors subsection. **TESTED.**

`CLAUDE.md:9` says "The package lives in `src/pkg_pulse/`. It is currently a placeholder
(`foo.py`): the substance of this repo today is the agent development environment (ADE) scaffold".
`ls src/pkg_pulse/` confirms `foo.py` exists, so the sentence is literally true, but it now
undersells a tree with 14 packages and a shipped connector kit. **TESTED**, low impact.

### Friction

- Four OpenSpec changes are open at once. `CLAUDE.md` states the design assumption as "two changes
  can be in flight at once". A newcomer running `task spec:status` meets four. **TESTED.**

### What a 10/10 looks like for this repo

A newcomer lands on `README.md`, sees a one-line "Building a connector? Start here" pointer above
the fold rather than 130 lines into the architecture narrative, and every surface they will touch
in week one is reachable in two clicks from it.

---

## Step 1. Getting started (TTHW)

### What I did

Real fresh clone from the remote, then exactly the README's documented quickstart. Each stage
timed to the second with `date +%s` around it. **Nothing else was running**: no parallel gate, no
second clone, no background job of mine. The numbers below are idle-machine numbers.

```bash
git clone https://github.com/robford-brookai/pulse.git pulse
task install
task check
```

### What I observed

| Stage | Command | Elapsed | Result |
| --- | --- | --- | --- |
| Clone | `git clone https://github.com/robford-brookai/pulse.git` | **2s** (`real 2.15`) | clean, at `5177d05` |
| Install | `task install` | **3s** | `rc=0`, ends `pre-commit installed at .git/hooks/pre-commit` |
| Gate | `task check` | **147s** | `rc=0`, green |
| **TTHW total** | clone to a green `task check` | **152s (2m32s)** | green on the first attempt |

**TESTED.** 2m32s puts this in the rubric's **Competitive** band (2 to 5 min), one band below
Champion.

**Cache warmth matters and I measured both arms.** The 3s install was against a 26G warm
`~/.cache/uv`. I then measured the cold arm on a second fresh clone with `UV_CACHE_DIR` pointed at
an empty directory:

```bash
git clone -q https://github.com/robford-brookai/pulse.git cold
UV_CACHE_DIR=$PWD/../pulse-cold-cache UV_NO_PROGRESS=1 uv sync --all-packages
# COLD uv sync = 7s
```

**TESTED.** Cold cache costs 4 extra seconds on this machine and this network. Install is not the
bottleneck in either arm; `task check` is 97% of TTHW.

Inside the 147s gate, the dominant cost is the test suite:

```
========= 2893 passed, 30 skipped, 8 deselected, 11 warnings in 47.71s =========
Required test coverage of 80.0% reached. Total coverage: 97.42%
```

plus `task test:services`, whose slowest single suite is 42.51s, and the Twenty vitest suite
(67 tests, 2.53s). **TESTED.**

**I did not need to read a doc beyond `README.md`, guess, or hit an error to reach green.** The
Prerequisites section and the Quickstart were sufficient and correct for the happy path.

### Friction

1. **`task check` leaves the working tree dirty on a fresh clone.** **TESTED.**

   ```
   $ git status --short
    M .planning/devex/loop.jsonl
   $ git diff --stat
    .planning/devex/loop.jsonl | 8 ++++++++
    1 file changed, 8 insertions(+)
   ```

   `.planning/devex/loop.jsonl` is a tracked file and `scripts/devex/timing.py` appends a row per
   gate target. The newcomer's very first action after the documented quickstart produces an
   uncommitted diff they did not author and were not warned about. Nothing in `README.md`,
   `CONTRIBUTING.md`, or `docs/connectors/authoring.md` mentions it.

2. **The gate's own output ends on a red-inked scare block.** `task check` succeeds (`rc=0`) but
   its last substantive block, before three mkdocs `INFO` lines, is the Material for MkDocs vendor warning rendered in ANSI red:
   "⚠ Warning from the Material for MkDocs team ... All plugins will stop working ... Currently
   unlicensed — unsuitable for production use". A newcomer reading their first green gate sees red
   text about an unlicensed dependency as the last thing on screen. **TESTED.**

3. **Prerequisites never name a Python version.** `.python-version` pins `3.14`; `pyproject.toml`
   declares `requires-python = ">=3.10,<4.0"`. The README's Prerequisites list covers uv, go-task,
   Node 22, Docker, and optionally openspec/openlore/orca/gh, but no Python. It works because `uv`
   fetches the interpreter, which is the right default; it is undocumented, so a newcomer with an
   opinion about pyenv does not know they can skip it. **TESTED.**

4. **The Node pin is not enforced.** `.nvmrc` says `22`, README says "Node.js 22 (required)". I
   ran the whole gate green on `node v26.8.1`. The pin is advisory only. **TESTED.**

### What a 10/10 looks like for this repo

Clone to green in under two minutes, with `task check` printing a one-line summary of what it ran
and how long each target took instead of 600 lines of raw tool output ending on a vendor warning;
and a green gate that leaves `git status` clean.

---

## Step 2. API/CLI/SDK ergonomics, connector-focused

### What I did

Followed only what the repo tells you: `docs/connectors/authoring.md` (414 lines), then the
scaffold command, then the documented verification.

```bash
task connector:new NAME=labs DIRECTION=inbound
task install
task check
```

and separately, for the default direction:

```bash
task connector:new NAME=pocar          # DIRECTION defaults to outbound
```

### What I observed

**A scaffold command exists and it is good.** `task connector:new NAME=labs DIRECTION=inbound`
completed in **under 1 second**, rendered 12 files, and applied registrations at both sites:

Abridged: the real output prints one absolute path per line; the brace notation below condenses it.

```
Rendered labs (labs), inbound, into .../packages/labs:
  README.md  pyproject.toml
  src/labs/{__init__,config,py.typed,receipts,service}.py
  tests/{conftest,factories,test_config,test_receipts,test_service}.py

Registered labs at 2 site(s):
  Taskfile.yml
  pyproject.toml

Next: uv sync --all-packages
```

**TESTED.** The registration actually took: `task check`'s subsequent lint, typecheck, test and
coverage lines all name `packages/labs`, e.g.
`uv run pyright -p packages/labs` and `--cov=packages/labs/src`.

**Documents and files read to get this far: 2** (`README.md`, `docs/connectors/authoring.md`).
**Concepts learned before writing a line: 5** (the fixed connector shape, the two directions, the
kit's root-only import rule, credential-name-not-value configuration, the nine registration
sites). That is a genuinely gentle ramp for a system this size.

**Then the documented golden path fails.**

`docs/connectors/authoring.md` step 3 promises:

> ```bash
> task connector:new NAME=my-connector
> task install          # resolve the workspace with the new member
> task check            # the rendered package ships one green test
> ```

`task check` after the scaffold returned **`rc=201`**:

```
collected 2956 items / 1 error / 8 deselected / 2948 selected
==================================== ERRORS ====================================
_____________ ERROR collecting packages/labs/tests/test_service.py _____________
ImportError while importing test module '.../packages/labs/tests/test_service.py'.
Traceback:
packages/labs/tests/test_service.py:17: in <module>
    from factories import FakeCommandTransport
E   ModuleNotFoundError: No module named 'factories'
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
task: Failed to run task "test": exit status 2
task: Failed to run task "check": exit status 201
```

**TESTED.** Root cause, confirmed by reading the templates and the reference connector:

```bash
$ grep -rn "^from factories\|^from tests.factories" templates/connector/
templates/connector/tests/test_service.py.tmpl:16:from factories import FakeCommandTransport
templates/connector/direction/inbound/tests/test_service.py.tmpl:17:from factories import FakeCommandTransport

$ grep -rn "factories" packages/billing-connector/tests/test_service.py
packages/billing-connector/tests/test_service.py:41:from tests.factories import FakeCommandTransport, ...

$ ls packages/billing-connector/tests/__init__.py packages/labs/tests/__init__.py
packages/billing-connector/tests/__init__.py
ls: packages/labs/tests/__init__.py: No such file or directory
```

The reference connector uses `from tests.factories import ...` and ships `tests/__init__.py`. The
template uses a bare `from factories import ...` and ships no `tests/__init__.py`. The bare import
resolves under a per-package invocation and does not resolve in `task test`'s combined run, which
passes `--import-mode=importlib`.

**Both directions are affected**, and the failure is invisible to the doc's own per-package
verification:

```bash
$ uv run pytest packages/labs/tests -q            # the doc's step-5 command
40 passed in 0.31s
$ uv run pytest packages/pocar/tests -q           # outbound
22 passed in 0.16s
$ uv run pytest packages/pocar/tests packages/labs/tests --import-mode=importlib -q
ERROR packages/pocar/tests/test_service.py
ERROR packages/labs/tests/test_service.py
!!!!!!!!!!!!!!!!!!! Interrupted: 2 errors during collection !!!!!!!!!!!!!!!!!!!
```

**TESTED.** This is precisely the "green locally, red in CI" shape that `docs/ci-lessons.md` exists
to prevent, reproduced by the repo's own scaffold on its own documented commands.

**The default direction additionally fails lint, unconditionally.** `task connector:new NAME=pocar`
(no `DIRECTION`, so outbound) renders a `service.py` that this repo's ruff reformats:

```
$ uv run ruff format --diff packages/pocar/src/pocar/service.py
-def run(
-    config: Config, *, client: PulseCoreClient, sqs_client: Any = None, iterations: int | None = None
-) -> Receipt:
+def run(config: Config, *, client: PulseCoreClient, sqs_client: Any = None, iterations: int | None = None) -> Receipt:
1 file would be reformatted
```

**TESTED.** `pyproject.toml:153` sets `line-length = 120`; the joined line is 118 characters and
contains no connector name, so this reproduces for **every** outbound scaffold regardless of name.
The inbound overlay replaces `service.py`, which is why `packages/labs` passed lint and
`packages/pocar` did not.

Net: `task connector:new` → `task install` → `task check` is red on two independent counts for the
default direction and one for inbound. The connector author's first gate run after using the
repo's own scaffold is a failure they did not cause.

**`task` help text and target naming.** 68 targets, every one carrying a one-line description, and
the default listing is grouped by area in workflow order rather than alphabetically. Naming is
consistent `area:verb` (`twenty:deploy`, `ledger:migrate`, `spec:validate`, `lore:drift`), and the
descriptions state prerequisites inline, e.g.

```
* demo:e2e:  Demo 5 — one patient, six stages, offline (needs Docker/LocalStack; docs/runbooks/demo5-end-to-end.md)
* verify:    Full local gate — check plus drift and spec validation (needs CHANGE)
```

**TESTED.** This is the strongest single surface in the repo. One naming inconsistency: the
scaffold's closing line says `Next: uv sync --all-packages`, naming the raw command where every
other surface names the target (`task install`). **TESTED.**

**Kit public surface vs. the spec vs. the reference connector.**

```bash
$ uv run python -c "import pulse_core.connector as c; print(len(c.__all__))"
28
```

The authoring guide's copy-paste import block lists **26 of those 28** names with an inline comment
each. The two omitted are `LedgerCursorStoreError` and `TransientExhaustedError`, both exception
types, both named in the guide's surrounding prose but absent from the block a reader will actually
paste. **TESTED.** So a connector author who pastes the block gets every constructor and protocol
and none of the exceptions they need to catch.

Nothing in the doc is missing from `__all__` (`doc - __all__` is empty), so the guide does not
promise a name the kit does not export. **TESTED.**

The reference connectors' imports match the documented rule. `billing-connector` and
`consent-ingress` import from `pulse_core.connector` root only, and reach `pulse_core.client`,
`pulse_core.generated` and `pulse_core.cursor` directly, exactly as the guide's "two more modules"
paragraph describes. **TESTED.**

One pattern the persona will copy and probably should not:
`packages/consent-ingress/src/consent_ingress/row_source.py:41,96` imports the kit's
**test** fixture into production source and subclasses it:

```python
from pulse_core.connector import FixtureRowSource as _KitFixtureRowSource
...
class FixtureRowSource(_KitFixtureRowSource):
```

The guide presents `FixtureRowSource` as "the `RowSource` every test drives". A newcomer told to
treat `consent-ingress` as the inbound reference will read this as sanctioned. **TESTED.**

**Small drift between the guide's rendered-tree diagram and what renders.** The guide's `text`
fence lists `tests/__init__.py` (not rendered) and omits `tests/test_receipts.py` (rendered).
**TESTED.** The missing `__init__.py` is the same defect as the import failure above, so the guide
is describing the tree that would have worked.

### Friction

Ordered by how hard it stops a connector author: the red `task check` after scaffolding; the
unconditional outbound lint failure; the exceptions missing from the import block; the
`uv sync` / `task install` naming split; the fixture-in-production pattern in the inbound
reference.

### What a 10/10 looks like for this repo

`task connector:new NAME=labs DIRECTION=inbound && task install && task check` is green, every
time, for both directions, and a scaffold gate proves it by rendering into a temp tree and running
the real combined gate command against it rather than asserting the target exists.

---

## Step 3. Error messages

Ten realistic mistakes triggered. Each is judged on the rubric's three-part test: does it state
the **problem**, the **cause**, and the **fix**?

| # | Mistake | Problem | Cause | Fix |
| --- | --- | --- | --- | --- |
| 1 | `task connector:new` (no NAME) | yes | yes | no |
| 2 | `task verify` (no CHANGE) | yes | yes | **yes** |
| 3 | `task dispatch CHANGE=no-such-change` | yes | yes | no |
| 4 | `task dispatch --change=foo` (flag form) | **no** | no | no |
| 5 | `task connector:new NAME=Bad_Name/x` | yes | yes | **yes** |
| 6 | `Config.from_env({})` on the scaffolded connector | yes | yes | **yes** |
| 7 | `task twenty:deploy TARGET=dev`, no credentials | yes | yes | **yes** |
| 8 | `openspec`/`openlore` missing from `PATH` | yes | yes | no |
| 9 | Failing lint gate | yes | yes | no |
| 10 | `task lore:drift` on a fresh clone | yes | yes | partial |

**Exact text, all TESTED.**

**1. Missing required variable.**
```
task: Task "connector:new" cancelled because it is missing required variables: NAME
```
Names the variable. Does not show the form (`NAME=labs`) or mention `DIRECTION`. go-task's message,
not the repo's.

**2. Missing CHANGE, with the fix in the message.**
```
task: CHANGE is required, e.g. task verify CHANGE=<change-id>
task: Failed to run task "verify": task: precondition not met
```
This is the repo's own `preconditions:` text and it is the right shape: problem, and a copy-paste
example. **Contrast with #1**: the repo writes better messages than the ones it inherits.

**3. Nonexistent change.**
```
Error: openspec/changes/no-such-change/tasks.md not found
```
States the path it looked for, which is most of the cause. Does not suggest `task spec:status` or
list what changes do exist, both of which are one line away.

**4. The flag form, which `CLAUDE.md` explicitly warns about.**
```
Usage: task [flags...] [task...]

Runs the specified task(s). Falls back to the "default" task if no task name
was specified, or lists all tasks if an unknown task name was specified.

Example: 'task hello' with the following 'Taskfile.yml' file will generate an
'output.txt' file with the content "hello".
[... 12 more lines of a generic tutorial ...]
```
**The worst error in the repo.** It does not name `--change`, does not say the flag form is
unsupported, does not mention `CHANGE=`, and buries the signal under a tutorial about a
hypothetical `hello` task. `CLAUDE.md` documents this trap in prose ("Passing the change as a flag
instead exits 2 with `unknown flag`") because the tool cannot.

**5. Bad package name, an exemplar.**
```
error: NAME='Bad_Name/x' is not a usable package name. Use lowercase words separated by hyphens,
starting with a letter — for example `claims-connector`.
```
Problem, cause, rule, and a worked example, in one sentence. This is what the rest should look
like.

**6. Bad connector config, the other exemplar.**
```
ConfigError: labs configuration is unusable:
  - LABS_SOURCE_TABLE is unset — the fully qualified relation to page
  - LABS_LEDGER_BASE_URL is unset — the command-API base URL
  - LABS_TOKEN is unset — this connector's ledger writer token
```
Every missing variable at once (the guide's step-4 rule, honoured by the template), each with a
purpose gloss, and no value read or echoed. The only thing missing is where to put them
(`.env`, and `.env.example` does not carry these keys).

**7. Missing credentials.**
```
target 'dev' is not configured — set: PULSE_TWENTY_DEV_URL, PULSE_TWENTY_DEV_TOKEN
```
Names both variables. Does not name the file they belong in.

**8. Missing npm-global tool.** With `openspec` and `openlore` off `PATH`:
```
task: [spec:validate] openspec validate
"openspec": executable file not found in $PATH
task: Failed to run task "spec:validate": exit status 127

task: [lore:drift] openlore drift
"openlore": executable file not found in $PATH
task: Failed to run task "lore:drift": exit status 127
```
A bare shell message. The install command exists in `README.md`
(`npm install -g @fission-ai/openspec openlore`) and the error does not mention it. These are the
two tools the README marks "optional but recommended", so a newcomer is more likely than not to be
missing them at this moment.

**9. Failing lint gate.**
```
unformatted: File would be reformatted
 --> src/pkg_pulse/_broken.py:2:1
  |
1 | import os
  - def f( x ):
  -   return x
2 +
3 +
4 + def f(x):
5 +     return x
  |
2 files would be reformatted, 704 files already formatted
task: Failed to run task "lint": exit status 1
```
Excellent problem statement (file, line, exact diff). **The fix is never named.** `task fmt` exists
and applies exactly this; the message does not say so, and neither does `task lint`'s own
description in the listing beyond "read-only". `CONTRIBUTING.md` says it, one context switch away.

**10. Drift on a fresh clone.**
```
[error] No openlore configuration found. Run "openlore init" first.
```
Names a fix, but the tool's fix, not the repo's. The repo's target is `task lore:init`, which is
idempotent and safe. A newcomer runs the raw command and gets a subtly different result. See
Step 6, where this same message blocks their first commit.

### Friction

The repo's own hand-written messages (#2, #5, #6, #7) are consistently strong: problem, cause, and
usually a worked example. Every weak message is one the repo inherited and did not wrap: go-task's
missing-variable and usage output, ruff's silence about `task fmt`, the shell's `not found in
$PATH`, openlore's raw-command advice.

### What a 10/10 looks like for this repo

Every failure a newcomer can hit in week one names the **task target** that fixes it, not the
underlying tool's command. `task lint` failing prints "run `task fmt`". A missing npm global prints
the `npm install -g` line from the README. `task dispatch --change=foo` prints "use
`CHANGE=foo`, not `--change`".

---

## Step 4. Documentation

### What I did

```bash
grep -ril "authoring a connector" docs/
grep -ril "scaffold a connector" docs/
uv run mkdocs build -s
grep -n -i connector mkdocs.yml docs/index.md
```
Then read `docs/connectors/authoring.md` end to end against the persona's eight questions.

### What I observed

**Findability. TESTED.** A grep for the obvious phrase lands on the right two files and nothing
else:

```
$ grep -ril "authoring a connector" docs/
docs/index.md
docs/connectors/authoring.md
```

The page is in the mkdocs nav (`mkdocs.yml:35-36`, `Connectors > Authoring:
connectors/authoring.md`), linked from `docs/index.md:34`, from `README.md`'s Connectors section,
and from `CONTRIBUTING.md`'s Owner paragraph. Four independent entry points reach it.

**Currency. TESTED.**
```
$ uv run mkdocs build -s
INFO -  Documentation built in 0.85 seconds
```
Zero `WARNING` or `ERROR` lines. Strict build is clean, meaning no broken internal link and no
orphaned nav entry.

**The persona's eight questions, in the order the audit specifies.** The guide answers all eight,
in that exact order, in ten numbered sections:

| Question | Section | Answered |
| --- | --- | --- |
| What is a connector here | 1 | yes, including the two directions and a table of references |
| What do I import | 2 | yes, 26 of 28 exported names with per-name comments |
| How do I scaffold | 3 | yes, with the direction table and the rendered tree |
| How do I configure | 4 | yes, with the credential-name-not-value rule and five review rules |
| How do I test offline | 5 | yes, both mechanisms, four seams, and which tests to write first |
| How do I register the package | 7 | yes, all nine sites named individually, with a grep to self-check |
| How do I ship through the workflow | 8 | yes, six steps plus the two exceptions |
| Who do I ask | 9 | yes, named owner plus an eight-row "before asking" table |

**PARTIAL** on "how do I scaffold": the section is complete and correct in intent, and the command
it documents produces a package that fails the gate the same section tells you to run (Step 2).

Section 6 ("what is enforced, before you get to CI") is the strongest piece of writing in the repo:
it tells the author that importing the kit auto-enrolls them in three gates and that there is
nothing to register for it, which is the Pit of Success stated out loud.

### Friction

1. **The rendered-tree diagram drifts from what renders** (Step 2): lists `tests/__init__.py` that
   is not rendered, omits `tests/test_receipts.py` that is. **TESTED.**
2. **Section 3's green-test promise is false.** "the rendered package ships one green test" under
   `task check`. **TESTED**, it does not.
3. **`task lore:init` appears only here**, at section 8 step 6, 380 lines into a connector guide.
   It is a fresh-clone prerequisite for committing at all (Step 6), and it is in neither the README
   quickstart nor `CONTRIBUTING.md`. `grep -c "lore:init"` returns `0` for both. **TESTED.**
4. **The audit's own task files ship inside `docs/`.** `grep -ril "scaffold a connector" docs/`
   returns `docs/process/devex-audit/task-a.md`, i.e. the audit instructions are in the searchable
   docs tree alongside the product docs. **TESTED**, low impact.

### What a 10/10 looks like for this repo

The authoring guide's step 3 is executable and verified by a gate, so it can never make a promise
the scaffold does not keep; and the fresh-clone prerequisite list is in exactly one place
(`README.md`) that every other doc links to, rather than distributed across three files by topic.

---

## Step 5. Upgrade path

### What I did

```bash
cat .ade-template-version
head -40 packages/pulse-core/CHANGELOG.md
grep -n -A8 "## Deprecations" openspec/specs/connector-kit/spec.md
ls docs/adr/ ; ls openspec/changes/archive | wc -l
```

### What I observed

**Template sync. TESTED.** `.ade-template-version` stamps
`a1de595b8591691a624d67d60efaa20d73641967`. `task template:diff` and `task template:sync` both
exist with descriptions naming the exclusion ("never README/CLAUDE/src"). The mechanism is
declared in `README.md`, `CLAUDE.md`, and the task listing. I did not execute `template:diff`
(it reaches the template remote). **INFERRED** that it works from three consistent declarations
plus the version stamp being a real commit SHA.

**Kit changelog discipline. TESTED.** `packages/pulse-core/CHANGELOG.md` exists, is Keep a
Changelog style, and carries a convention the guide relies on:

> Each entry that touches `pulse_core.connector` carries a **Connector authors** line naming the
> concrete effect on a connector build against the kit — read it before `uv sync` pulls in a new
> version.

It has an `[Unreleased]` section and a `[0.1.0]` baseline that folds in everything the kit shipped
before the changelog existed. The `0.1.0` entry does carry a `Connector authors:` line.

**Deprecation machinery. TESTED.** `openspec/specs/connector-kit/spec.md:85-93` defines a real
policy, not an aspiration:

> A name `pulse_core.connector` retires SHALL stay exported and working for one release after the
> retirement is announced, and SHALL raise `DeprecationWarning` naming its replacement on use. The
> announcement SHALL land in `packages/pulse-core/CHANGELOG.md` (a "Connector authors" line under a
> `### Deprecated` heading) in the same PR that starts the one-release grace window, and SHALL be
> listed here until the grace window closes and the name is removed

followed by a `| Deprecated name | Replacement | Announced | Removal |` table. The table is
currently empty, which is honest: nothing has been deprecated yet.

The guide's section 10 tells the connector author exactly what to do with all of this: check the
CHANGELOG and the spec's Deprecations section as part of pulling a kit upgrade, and file a
`connector-kit` defect if a name disappears without either naming it first. There is a matching
issue template, `.github/ISSUE_TEMPLATE/connector-kit-defect.yml`. **TESTED.** The loop closes.

**ADR discipline. TESTED.** `docs/adr/` holds 6 files: a template plus ADR-0001 through ADR-0005,
sequentially numbered, one decision each. `CLAUDE.md` states the rule: "append-only; a superseded
decision gets a status flip and a new ADR". The authoring guide cites ADR-0003 by number for the
attribution rule, so ADRs are load-bearing rather than decorative.

**Spec archiving. TESTED.** 20 archived changes under `openspec/changes/archive/`, and
`openspec/specs/` is described as write-only-by-archiving in both `CLAUDE.md` and `AGENTS.md`.
`task spec:archive` exists.

### Friction

1. **The kit version never moves.** `packages/pulse-core/pyproject.toml:3` is `version = "0.1.0"`
   and the CHANGELOG's only released section is `[0.1.0]`. Since every connector consumes
   pulse-core as `{ workspace = true }`, there is no version number for a connector author to pin,
   compare, or reason about. "One release" in the deprecation policy has no operational meaning yet
   because no second release exists. **TESTED.** The policy is written; the versioning that would
   make it enforceable is not.

2. **Nothing prompts the author to read the CHANGELOG.** The guide's section 10 says so explicitly
   and correctly: "The kit reaches every connector on the next `uv sync` — nothing prompts you to go
   read anything." That is an accurate statement of a gap, not a fix for it. **TESTED.**

3. **The CHANGELOG's own header cites a prior audit report by path** and quotes one of its
   findings. Noted in Method notes below as a blindness caveat.

### What a 10/10 looks like for this repo

`pulse-core` carries a real version that increments, `uv sync` surfaces "pulse-core 0.1.0 → 0.2.0,
see CHANGELOG" in the connector author's terminal, and the deprecation table has at least one row
that went through the full grace window so the policy is proven rather than asserted.

---

## Step 6. Developer environment

### What I did

```bash
cat .python-version .nvmrc ; grep -n requires-python pyproject.toml
ls -a .vscode .editorconfig ; head -12 .env.example
ls .git/hooks/ | grep -v sample ; grep -n "id:" .pre-commit-config.yaml
grep -n "run:" .github/workflows/main.yml
# then: a real first commit on the fresh clone
```

### What I observed

**Toolchain pins. TESTED.**

| File | Value |
| --- | --- |
| `.python-version` | `3.14` |
| `pyproject.toml` | `requires-python = ">=3.10,<4.0"` |
| `.nvmrc` | `22` |
| `.ade-template-version` | `a1de595…` |
| `packages/pulse-core/pyproject.toml` | `version = "0.1.0"` |
| `uv.lock` | present, guarded by `task docs:lock-guard` (`uv lock --check`) |

The lock is enforced in `task check` (`docs:lock-guard` runs `uv lock --check` and additionally
greps the lock for mkdocs-successor forks). **TESTED**, that ran green in my gate.

**Editor support is thin. TESTED.** `.editorconfig` exists. `.vscode/` contains exactly one file,
`extensions.json`. There is no `settings.json`, so nothing pins the interpreter, the formatter, or
format-on-save for a newcomer opening the repo in VS Code. The repo has strong opinions about
formatting (ruff, `line-length = 120`) and does not project any of them into the editor.

**Pre-commit hooks are installed by the documented install. TESTED.** `task install`'s last line is
`pre-commit installed at .git/hooks/pre-commit`, and `ls .git/hooks/` on the fresh clone shows
`pre-commit` as the only non-sample hook. Eleven hooks are configured: `check-case-conflict`,
`check-merge-conflict`, `check-toml`, `check-yaml`, `check-json`, `pretty-format-json`,
`end-of-file-fixer`, `trailing-whitespace`, `ruff-check`, `ruff-format`, `openlore-drift`.

No `commit-msg` hook, though `CLAUDE.md` and `global-rules` prescribe a
`<type>: <description>` commit format. **TESTED**, format is convention-enforced only.

**The newcomer's first Python commit is blocked. TESTED.** This is the second broken golden path.
On the fresh clone, after exactly the documented `task install` + `task check`:

```bash
$ printf '"""Scratch."""\n\n\ndef f() -> int:\n    """Doc."""\n    return 1\n' > src/pkg_pulse/_scratch.py
$ git add src/pkg_pulse/_scratch.py && git commit -m "test: py commit on fresh clone"
check for case conflicts.................................................Passed
[...]
ruff check...............................................................Passed
ruff format..............................................................Passed
openlore drift...........................................................Failed
- hook id: openlore-drift
- exit code: 1

Spec Drift Detection

[error] No openlore configuration found. Run "openlore init" first.
```

`.openlore/` is gitignored and therefore absent from a fresh clone. The `openlore-drift` pre-commit
hook is file-scoped, so a docs-only commit passes (I confirmed: a `.md`-only commit reports
`openlore drift ... (no files to check) Skipped` and succeeds), but any commit touching Python
fails. A connector author's first commit touches Python by definition.

The fix, `task lore:init`, is documented once, at `docs/connectors/authoring.md` step 8.6, and is
in neither `README.md` nor `CONTRIBUTING.md` (`grep -c "lore:init"` returns `0` for both). The
error names the raw tool command instead. **TESTED.**

`CONTRIBUTING.md` describes the hooks but not this prerequisite:

> Pre-commit hooks run `ruff` and `openlore drift` on every commit. A hook that rewrites a file
> fails the commit by design — re-stage and commit again.

**Local vs CI parity. TESTED.** `.github/workflows/main.yml` has six `run:` lines. The `quality`
job's is exactly `run: task check`, which is the contract `CLAUDE.md` and `README.md` both claim.
The other `run:` lines are `uv run python -m pytest tests`, `uv run mypy`, `task docs:lock-guard`,
`task docs:build`, all either subsets of `check` or defined Taskfile targets, which is what
`cat4_ci_contract.py` enforces. Parity holds. The strongest structural property in the repo: my
local `task check` was green and the gate is byte-for-byte what CI runs.

**`.env.example`. TESTED.** Present, gitignore-aware, leads with "Never put PHI or real credentials
in either file", and documents `ORCA_WORKTREES_DIR` and `ANTHROPIC_API_KEY` with a note on which
openlore subcommands need the key. It carries **no connector variables**: not the
`PULSE_TWENTY_DEV_*` pair that `task twenty:deploy` demands by name, and no worked example of the
`<CONNECTOR>_TOKEN` / `<CONNECTOR>_LEDGER_BASE_URL` / `<CONNECTOR>_SOURCE_TABLE` shape the scaffold
generates. The `Config.from_env` error names the variables; nothing tells the author which file to
put them in.

### Friction

The blocked first commit is the highest-cost item here: it arrives after the newcomer has already
succeeded twice (install, check) and it fails on a hook they did not configure, with advice
pointing at a raw command rather than the repo's own idempotent target.

### What a 10/10 looks like for this repo

`task install` leaves the clone able to commit: it runs `task lore:init` (already idempotent and
already safe on a fresh clone) alongside `pre-commit install`, so the `openlore-drift` hook has
what it needs from minute three. `.vscode/settings.json` pins the interpreter and the formatter.
`.env.example` carries a commented block of the connector variable shape.

---

## Step 7. Community and ecosystem (internal-repo interpretation)

The rubric's internal-repo interpretation asks for four things: a named owner per area
(`CODEOWNERS`), a channel or person to ask **named in `README.md`**, issue and PR templates, and
evidence that someone other than the owner has landed a connector.

### What I did

```bash
cat .github/CODEOWNERS ; find .github -type f
cat CONTRIBUTING.md ; grep -in "slack\|ask\|owner\|channel" README.md
git log --format='%an <%ae>' | sort | uniq -c | sort -rn
git log --format='%an' -- packages/billing-connector packages/consent-ingress \
    packages/verdict-relay packages/pulse-core/src/pulse_core/connector | sort | uniq -c
grep -rn "DNA-" openspec/changes/billing-connector/tasks.md
```

### What I observed

**`CODEOWNERS` exists, with two rules. TESTED.**
```
# Pulse code owners
* @robford-brookai

# The connector kit every connector depends on
packages/pulse-core/src/pulse_core/connector/ @robford-brookai
```
A per-area rule exists for exactly the area that matters to the persona (the kit), which is the
right instinct. Both rules name the same person, so "a named owner per area" is met structurally
and not yet in substance.

**Templates. TESTED.** `.github/PULL_REQUEST_TEMPLATE.md` plus two issue templates:
`attended-run.yml` (the prod-touching path `WORKFLOW.md` defines) and `connector-kit-defect.yml`
(the escalation route the authoring guide's section 10 tells a connector author to use). The
connector-kit template is a real, purpose-built path for this persona, not a generic bug form.

**Owner and channel. TESTED.** `CONTRIBUTING.md` names both the owner and the connector entry
point in its first paragraph:

> **Owner: Rob Ford** (GitHub [@robford-brookai](https://github.com/robford-brookai)). Ask the
> owner directly on Slack; a dedicated channel has not been named yet. Building a connector? Start
> with [`docs/connectors/authoring.md`](docs/connectors/authoring.md).

`docs/connectors/authoring.md` section 9 repeats it and adds an eight-row "before asking" table
routing each likely question to a specific file. That table is the best help-surface in the repo.

**`README.md` names neither a person nor a channel.** `grep -in "slack\|owner\|channel"` on
`README.md` returns zero matches (QA re-ran the grep: no output at all). The rubric asks for this in `README.md` specifically. **TESTED.**
The information exists one hop away in two places; it is not where the rubric looks, and not where
a newcomer looks first.

The absence of a dedicated channel is stated rather than hidden, in both places. That is honest,
and it is still a gap: "ask the owner on Slack" does not scale past one person and gives a
newcomer no archive to search before interrupting.

**Someone other than the owner landing a connector: no evidence, and none can be manufactured.
TESTED.**
```
$ git log --format='%an <%ae>' | sort | uniq -c | sort -rn
1064 Rob Ford <rob.ford@brook.ai>
$ git log --format='%an' -- packages/billing-connector packages/consent-ingress \
      packages/verdict-relay packages/pulse-core/src/pulse_core/connector | sort | uniq -c
  44 Rob Ford
```
Every one of the repo's 1064 commits, and all 44 commits touching a connector package or the kit,
carry a single author. The rubric flags this dimension as the one that cannot be faked, so I record
it as a fact with no interpretation: the connector path has never been walked by anyone but its
author. Every conclusion in this report about how a newcomer experiences that path is a simulation
of an event that has not occurred.

**Handoffs, work orders, and Linear linkage. TESTED.** `handoffs/` holds collected `HANDOFF.md`
receipts per change and `templates/HANDOFF.md` is the form. `work_orders/` is generated by
`task dispatch`. Linear ids are projected into `tasks.md` by `task linear:sync` and are visible in
the live change:
```
openspec/changes/billing-connector/tasks.md:111:- [x] 3.1 [DNA-1280] Deploy artifacts: ...
openspec/changes/billing-connector/tasks.md:128:- [ ] 4.1 [DNA-1281] `verdict-reconcile` schedules entry: ...
```
So a task in a plan, a work order, a worktree, a handoff, and a Linear issue are all
cross-referenced by a stable id. For an internal repo this is the ecosystem, and it is real.

### Friction

The gap between what `CONTRIBUTING.md` knows and what `README.md` says. A newcomer who reads only
the README, the common case, never learns who to ask.

### What a 10/10 looks like for this repo

`README.md` carries a two-line "Who owns this / where to ask" block above the fold, a named channel
exists and is linked, `CODEOWNERS` routes the kit, the Twenty surface, and the ledger to different
reviewers, and at least one connector in `packages/` was authored by someone other than Rob.

---

## Step 8. DX measurement

The audit's blindness rule permits reading this machinery as a newcomer who found it would. I did
not use any of it to steer Steps 0 through 7; every finding above was reached first and checked
against this section afterwards.

### What I did

```bash
ls -la scripts/devex/ ; head -60 tests/scaffold/cat10_devex.py
task devex:check
uv run pytest tests/scaffold/cat10_devex.py -q
tail -3 .planning/devex/loop.jsonl ; wc -l .planning/devex/loop.jsonl
sed -n '60,75p;320,340p;595,645p' tests/scaffold/cat10_devex.py
```

### What I observed

**The repo measures its own DX, deliberately and with a stated theory. TESTED.**
`tests/scaffold/cat10_devex.py`'s docstring:

> One test per finding from the DevEx audit [...]. While a defect exists its test is
> `xfail(strict=True)`: the gate stays green, and `scripts/devex/check.py` counts the xfails as
> `devex_open_findings`. Fixing a defect flips the marker off in the same PR; from then on a
> regression fails `task check`.
>
> The number this gate produces is a count of open findings, never a 0-10.

That separation, a mechanical ratchet for regressions and an LLM-judged audit for the 0-10, is the
right architecture, and the `xfail(strict=True)` choice is well made: it makes a fix that does not
actually fix fail loudly.

**Three measurement surfaces exist:**

1. **Findings ratchet.** `task devex:check`:
   ```
   wrote .planning/devex/2026-09-05-check.json
   METRIC devex_open_findings=0
   ```
   and `uv run pytest tests/scaffold/cat10_devex.py -q` gives `45 passed, 3 deselected`. **TESTED.**

2. **Gate durations.** `task check` wraps every target in
   `uv run python scripts/devex/timing.py <target> -- task <target>` and appends one JSON row per
   target to `.planning/devex/loop.jsonl` (40 rows at HEAD; 48 in the working tree with the 8 uncommitted rows):
   ```json
   {"date": "2026-09-05", "kind": "timing", "target": "docs:build", "seconds": 1.936, "rc": 0}
   ```
   **TESTED.** Gate duration regression is genuinely observable over time.

3. **Onboarding time.** `test_tthw_fresh_clone_to_synced_env` is `@pytest.mark.slow`, clones the
   repo twice and prints `TTHW_INSTALL_SECONDS_WARM` and `TTHW_INSTALL_SECONDS_COLD`, with a
   docstring that has internalised a prior lesson: "Audit 3's timings were only valid measured
   idle; this test already runs alone, so both arms stay comparable." **TESTED.** Measuring both
   cache arms is exactly right and matches what I did independently in Step 1.

**Drift** is measured by `openlore drift`, wired as both a pre-commit hook and part of
`task verify`. **TESTED.**

### Friction

**`devex_open_findings=0` is true and the golden path is red.** This is the load-bearing
observation of Step 8. Every one of the 45 gate tests passes, the metric reports zero open
findings, and `task connector:new` → `task install` → `task check` fails (Step 2). The gate does
not catch it because of what it asserts:

```python
def test_connector_scaffold_command_exists():
    """`task connector:new NAME=x` exists and a template tree backs it."""
    assert "connector:new" in TARGETS
    assert (ROOT / "templates/connector").is_dir()
```

**TESTED.** It checks that the scaffold is *present*, never that it *works*. Nothing in
`cat10_devex.py` renders a connector and runs a gate against it. A zero count here means "no
previously-recorded finding has regressed", which is a different and much weaker claim than "the
connector author's path is green".

The same shape appears in the tree-diagram test at line 331:
```python
diagrammed = set(re.findall(r"(test_[a-z_]+\.py|factories\.py|conftest\.py)", tree_diagram.group(1)))
```
The regex extracts only `test_*.py`, `factories.py` and `conftest.py` from the guide's fence, so it
structurally cannot see either half of the drift I found in Step 2: the diagrammed-but-unshipped
`tests/__init__.py`, or the shipped-but-undiagrammed `tests/test_receipts.py`. **TESTED.**

Two smaller measurement gaps:

- **The repo's TTHW is not the audit's TTHW.** `test_tthw_fresh_clone_to_synced_env` times clone
  plus `uv sync --all-packages`, i.e. 2s + 3s warm on my machine. The audit's definition is clone
  to a **green `task check`**, which is 152s. The repo's own number omits 97% of the wall clock a
  newcomer actually waits. **TESTED.**
- **`task check` writes to a tracked file to record its own timings** (Step 1), so the measurement
  instrument dirties the tree it measures. **TESTED.**

### What a 10/10 looks like for this repo

`cat10_devex.py` contains one slow test that renders both connector directions into a temp tree,
runs the real combined gate command against them, and asserts green, so a scaffold that produces a
red package is a failing gate rather than a zero count. The TTHW test measures clone to green
`task check` in both cache arms. `scripts/devex/timing.py` writes outside the tracked tree, or
`.planning/devex/loop.jsonl` is gitignored and collected by CI.

---

## Connector author journey

Elapsed is cumulative wall clock from `t=0` at the moment of clone, measured on an idle machine
with a warm uv cache. Rows I did not perform are marked INFERRED.

| Elapsed | Action | Outcome | Stuck point |
| --- | --- | --- | --- |
| 0:00 | `git clone https://github.com/robford-brookai/pulse.git` | 2s, clean at `5177d05` | none. TESTED |
| 0:02 | Read `README.md` Prerequisites; confirm uv, task, node, docker, gh present | all present | Python version never stated; Node pin advisory only. TESTED |
| 0:02 | `task install` | 3s, `rc=0`, pre-commit installed | none. TESTED |
| 0:05 | `task check` | 147s, `rc=0`, green | 600 lines of raw output ending on a red MkDocs vendor warning. TESTED |
| 2:32 | `git status` | `M .planning/devex/loop.jsonl` | the gate dirtied a tracked file, undocumented. TESTED |
| 2:33 | Find the connector path: `README.md` → `docs/connectors/authoring.md` | 4 entry points reach it | none. TESTED |
| 2:35 | Read `docs/connectors/authoring.md`, 414 lines, all 8 questions answered in order | 2 docs read, 5 concepts learned | none. TESTED |
| 2:50 | `task connector:new NAME=labs DIRECTION=inbound` | <1s, 12 files, 2 registration sites | closing line says `uv sync --all-packages`, not `task install`. TESTED |
| 2:51 | `task install` | 0s | none. TESTED |
| 2:51 | `task check` (the guide's step 3, "ships one green test") | **`rc=201`, RED** | `ModuleNotFoundError: No module named 'factories'`. **Hard stop.** TESTED |
| 2:53 | `uv run pytest packages/labs/tests -q` (the guide's step 5) | `40 passed in 0.31s` | the per-package command passes, so the author cannot tell what is wrong. TESTED |
| 3:00+ | Diagnose: compare template to `packages/billing-connector` | template uses `from factories`, reference uses `from tests.factories` and ships `tests/__init__.py` | ~15 min of cross-reading to find a two-line template defect. TESTED |
| n/a | Same path with the **default** direction (`task connector:new NAME=pocar`) | additionally **fails `task lint`** | rendered `service.py:135` is 118 chars unwrapped against `line-length = 120`; reproduces for every outbound scaffold. TESTED |
| n/a | Write the connector's real logic against the kit | n/a | INFERRED. Kit surface is 28 names, guide's paste block covers 26; the 2 omitted are the exception types you must catch |
| n/a | Configure it: `Config.from_env({})` on an empty env | names all 3 missing vars at once with a purpose gloss each | best error in the repo; does not say which file to put them in, and `.env.example` has no connector block. TESTED |
| n/a | First commit of the new connector | **BLOCKED** by `openlore drift` pre-commit hook: `No openlore configuration found` | `.openlore/` is gitignored; fix (`task lore:init`) is documented only at authoring.md step 8.6, and the error names the raw `openlore init`. TESTED |
| n/a | Register at the nine sites | `task connector:new` already did 2 files; the guide names all nine for review | none. TESTED |
| n/a | Open an OpenSpec change, dispatch, worktree, handoff, Linear id | n/a | INFERRED from `WORKFLOW.md`, `tasks.md` `[DNA-nnnn]` tokens, `handoffs/`, and the task listing. Not executed |
| n/a | Ship: ready PR, drive CI green, human merges | n/a | INFERRED. Local/CI parity is structurally sound (`main.yml` runs exactly `task check`), so green local should mean green CI |
| n/a | Absorb a kit change | n/a | INFERRED. CHANGELOG + spec Deprecations exist; nothing prompts you to read them, and pulse-core has never left `0.1.0` |

**Two hard stops on the documented golden path**, both after the newcomer has already succeeded
twice, and both caused by repo artifacts rather than anything the author did.

---

## Top 10 friction points

Ordered by impact on a connector author.

1. **The scaffold produces a package that fails `task check`, in both directions.**
   `from factories import FakeCommandTransport` in `templates/connector/tests/test_service.py.tmpl:16`
   and `templates/connector/direction/inbound/tests/test_service.py.tmpl:17`, with no
   `tests/__init__.py.tmpl`, against `task test`'s `--import-mode=importlib`. The reference
   connector does it correctly (`from tests.factories`, plus `tests/__init__.py`). The guide
   promises "the rendered package ships one green test". It does not. TESTED.

2. **The default direction additionally fails `task lint`, unconditionally.**
   `templates/connector/src/{{NAME}}/service.py.tmpl`'s `def run(...)` is pre-wrapped at 118
   characters against `line-length = 120`, so ruff joins it. Name-independent; every outbound
   scaffold is red. TESTED.

3. **The newcomer's first Python commit is blocked.** The `openlore-drift` pre-commit hook fails on
   a fresh clone because `.openlore/` is gitignored. `task lore:init` is the fix and appears only
   at `docs/connectors/authoring.md` step 8.6; `grep -c "lore:init"` is `0` in both `README.md` and
   `CONTRIBUTING.md`. TESTED.

4. **The DX gate reports `devex_open_findings=0` while items 1 through 3 are live.**
   `test_connector_scaffold_command_exists` asserts the target exists and the template directory
   exists; nothing renders a connector and runs a gate against it. A zero count means "no recorded
   finding regressed", not "the path is green". TESTED.

5. **The per-package test command the guide gives you hides the failure.**
   `uv run pytest packages/labs/tests` passes (`40 passed`) while `task check` fails on the same
   files. Green locally, red in the combined run: the exact shape `docs/ci-lessons.md` exists to
   prevent. TESTED.

6. **Errors name the underlying tool's fix, not the repo's target.** `task lint` failing never
   mentions `task fmt`. A missing npm global gives a bare
   `"openspec": executable file not found in $PATH` with no `npm install -g` line. `openlore drift`
   says `Run "openlore init" first` where the repo's idempotent target is `task lore:init`.
   TESTED.

7. **`task dispatch --change=foo` prints 18 lines of go-task tutorial** and never mentions
   `--change`, `CHANGE=`, or that the flag form is unsupported. `CLAUDE.md` documents the trap in
   prose because the tool cannot. TESTED.

8. **`README.md` names no owner and no channel.** `CONTRIBUTING.md` and the authoring guide both
   do; the README, which is what a newcomer reads first and what the rubric checks, does not.
   TESTED.

9. **`task check` dirties a tracked file on a fresh clone**, appending 8 rows to
   `.planning/devex/loop.jsonl`. Undocumented anywhere the newcomer will read. TESTED.

10. **Connector environment variables have no home.** `Config.from_env` names every missing
    variable perfectly; `.env.example` carries no connector block and no `PULSE_TWENTY_DEV_*`
    entry, so the author is told what is missing and not where to put it. TESTED.

**Below the cut**, recorded for completeness: the guide's import block omits the two exception
types (`LedgerCursorStoreError`, `TransientExhaustedError`); the guide's rendered-tree fence drifts
from what renders in both directions; `consent-ingress` subclasses the kit's test fixture in
production source; `pulse-core` has never left `0.1.0` so the one-release deprecation policy has no
operational meaning; `.vscode/` has `extensions.json` and no `settings.json`; the green gate's last
screenful is a red vendor warning; `task spec:validate` with no argument prints openspec's generic
"Nothing to validate" usage rather than validating the current change as its description promises;
four OpenSpec changes are open against `CLAUDE.md`'s stated assumption of two.

---

## Method notes and limits

**What was measured, and how.** All timings in Step 1 were taken on an idle machine: no parallel
gate, no second clone, no background job of mine. No number in this report was measured under
contention, so no number needs the contention caveat. Timings use `date +%s` around the command and
are therefore accurate to ±1s.

**Cache warmth.** The primary TTHW (152s) was measured against a 26G warm `~/.cache/uv`, which is
what a repeat contributor sees. I measured the cold arm separately (`UV_CACHE_DIR` at an empty
directory): `uv sync --all-packages` took 7s cold versus 3s warm, so the cold-cache TTHW on this
machine and network is approximately 156s. Both arms are on arm64 macOS with fast broadband and
prebuilt wheels; a Linux CI runner compiling from source would differ.

**Blindness.** I read no file matching `.planning/reports/*devex*` and no
`.planning/devex/*-check.json`. Per the audit's explicit permission I read
`tests/scaffold/cat10_devex.py`, `scripts/devex/`, and `.planning/devex/loop.jsonl` for Step 8, and
only after Steps 0 through 7 were complete; none of it was used to steer those steps.

Two unavoidable leaks, disclosed: `packages/pulse-core/CHANGELOG.md`'s header cites
`.planning/reports/2026-09-02-devex-scorecard.md` by path and quotes one finding from it ("Upgrade
Path finding: no CHANGELOG, no deprecation machinery"), and `tests/scaffold/cat10_devex.py`'s
docstring cites the same report and its "Top 10 fixes" structure. I read neither report. I saw
those two sentences in files I was directed to read, and I reached items 1 through 3 of my Top 10
independently, by running the commands, before opening either file.

**What I did not do.**
- Did not execute `task template:diff` or `task template:sync` (they reach the template remote).
  Step 5's template findings are INFERRED from `.ade-template-version`, the target definitions, and
  three consistent prose declarations.
- Did not run any demo. `demo:1`, `demo:2`, and `demo:e2e` need Docker and LocalStack; `demo:3`,
  `demo:4`, and `stage:e2e:live` need dev credentials and would be live network calls, which the
  audit constraints forbid.
- Did not walk the full ADE change lifecycle (propose → dispatch → worktree → collect → verify →
  archive) for a connector. Doing so would create OpenSpec changes, Orca worktrees, and Linear
  issues, which exceeds this audit's read-only mandate. Those journey rows are marked INFERRED.
- Did not write connector business logic against the kit. I evaluated the kit's surface by
  comparing `pulse_core.connector.__all__` against the guide's import block and against what the
  reference connectors actually import, not by building against it.

**Repo state.** One tracked file, `.planning/devex/loop.jsonl`, carries uncommitted gate-timing rows; running `task check` anywhere in this repo appends them, which is finding 9 (QA C-A1). Everything destructive ran in the scratch
clone at
`/private/tmp/claude-502/-Users-Rob-Ford-Repos-robford-brookai-pulse/f762ace5-5258-40cf-9a29-e153b5d3a69c/scratchpad/audit4/scratch/pulse`,
which was reset with `git reset --hard 5177d05` after each experiment. Running `task devex:check`
in the repo under audit wrote `.planning/devex/2026-09-05-check.json`, which is that target's
normal untracked output and not a tracked-file edit. This report is the only file I authored in the
repo; the ledger rows are appended by `task check`, and the sample row quoted in Step 8 was read from that dirty working-tree state.

**Simulation caveat.** All 1064 commits in this repo have a single author, and all 44 commits
touching a connector package or the kit have that same author. No one other than the owner has
walked the connector path. Everything above is one careful reading of that path by an auditor who
had the repo's own documentation and nothing else, not a record of a real newcomer's experience.

**Scoring.** No 0-10 appears in this document by design. Scoring is Task B's. The boomerang
comparison against prior audits is Task C's.

**PHI.** No protected health information appears in this report. No live system was contacted. The
scaffolded `labs` and `pocar` packages contain only template-rendered synthetic content and were
deleted.
