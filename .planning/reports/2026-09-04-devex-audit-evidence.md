# DevEx audit evidence - pulse @ b26dee0 - 2026-09-04

Corrections from `.planning/reports/2026-09-04-devex-audit-qa.md` applied 2026-09-04 (QA 6.3, 6.6, 6.7 and
the Step 8 note from 6.1): only `Jitter` is missing from `__all__`; the `openlore init` claim narrowed;
`.github/CODEOWNERS` path; a quoted email address removed; Step 8's measurement conclusion annotated.


Evidence collection only. No scores are assigned here; scoring is Task B's job and the boomerang
comparison against the prior audit is Task C's job.

**Methodology**: `docs/process/devex-audit/rubric.md` (DX First Principles, Seven DX
Characteristics, Cognitive Patterns, Scoring Rubric, TTHW Benchmarks) plus the internal-repo
interpretation stated at the top of that file.

**Persona**: a competent engineer joining the team whose first job is to build a new connector for
**pocar** (the POCAR backend system; not billing). Every step below is walked in that persona.

**Environment**: macOS 25.6.0 (darwin, arm64). uv 0.12.8, go-task 3.53.1, node v26.8.1,
Python 3.14.7, Docker 29.7.2, openspec / openlore / gh all on PATH. `~/.cache/uv` was 26 GB before
the run - **the uv cache was warm**, so every install timing below is a best case, not a cold-start
number.

**Fresh clone**: `git clone https://github.com/robford-brookai/pulse.git` into
`/private/tmp/claude-502/.../scratchpad/audit2/pulse`, HEAD `b26dee0`, verified matching the audit
commit. All commands in this report were run in that clone unless a path says otherwise. The
tracked tree at `/Users/Rob.Ford/Repos/robford-brookai/pulse` was not modified; the only file this
audit writes there is this report.

**Tags**: TESTED = I ran it and quote the output. PARTIAL = I ran part of it. INFERRED = reasoned
from files read, not executed.

---

## Step 0 - Target discovery

### What I did

```bash
ls -a; ls docs/ design/; task                      # the default grouped listing
task -l | grep -c '^\* '; ls packages | wc -l
find docs -name '*.md' | wc -l; find design -name '*.md' | wc -l
find openspec/specs -name 'spec.md' | wc -l; ls tests/scaffold | wc -l
find templates -type f
```

### What I observed (TESTED)

Developer-facing surface inventory at `b26dee0`:

| Surface | Count | Notes |
| --- | --- | --- |
| `task` targets | 67 | `task` on its own prints them grouped by area in workflow order |
| Packages under `packages/` | 15 | 13 Python workspace members, `twenty-app` + `twenty-model` TypeScript. README says "Fourteen packages"; the 15th is the `pocar` package this audit scaffolded |
| Root-level entry docs | 5 | `README.md`, `CLAUDE.md`, `AGENTS.md` (96 lines), `CONTRIBUTING.md` (23 lines), `WORKFLOW.md` (433 lines) |
| `docs/` markdown | 42 | includes 17 runbooks, 6 ADRs, 4 contracts, 1 connector guide |
| `design/` markdown | 22 | platform / migration / delivery |
| OpenSpec capability specs | 48 | `openspec/specs/*/spec.md` |
| Scaffold gate files | 15 | `tests/scaffold/`, `cat1`..`cat10` plus shell gates and data |
| Templates | 10 files | `templates/connector/` (9 `.tmpl` files) + `templates/HANDOFF.md` |
| Collected handoff dirs | 17 | `handoffs/<change>/` |
| Archived OpenSpec changes | 20 | `openspec/changes/archive/`; 2 in flight (`billing-connector`, `devex-eight`) |

Scaffolding for the persona's job exists and is discoverable from the task list:

```
* connector:new: Scaffold a connector package (NAME) from templates/connector/ and register it at
  every site (devex-eight task 1.4)
```

`work_orders/` is absent in a fresh clone (generated, gitignored) - consistent with README.

### Friction

- `task`'s help text leaks internal change ids into the newcomer's first screen: `connector:new`
  ends `(devex-eight task 1.4)`; `typecheck` reads `mypy on TYPED_PATHS (DNA-779), pyright on
  verdict-relay (s12), schedules (s13), identity (s14), consent-ingress (S1.1 task 1.1),
  archaeology (bf0a), billing-connector (billing-connector task 1.1)`. None of those tokens means
  anything on day one, and `typecheck`'s description is longer than the description of what it
  does. TESTED.
- README's package count ("Fourteen packages live under `packages/`") is a hand-maintained number.
  It was correct at `b26dee0` before my scaffold; nothing gates it. INFERRED.

### What a 10 looks like here

The default `task` listing is already the right idea - grouped, ordered by when you reach it. A 10
strips every change-id from the `desc` field (they belong in the YAML comment above the target,
where several already are), and adds one line at the top of the listing pointing at the connector
guide, because "add a connector" is the single most common first job in this repo.

---

## Step 1 - Getting started (TTHW)

### What I did

Real fresh clone, then exactly the documented quickstart from `README.md` lines 223-228
(`task install`, `task check`). Nothing else, no guessing.

```bash
time git clone https://github.com/robford-brookai/pulse.git .../audit2/pulse
cd .../audit2/pulse && time task install
time task check
```

### What I observed (TESTED)

| Stage | Wall clock | Outcome |
| --- | --- | --- |
| `git clone` (HTTPS, 26 MB working tree) | **2.04 s** | HEAD `b26dee0`, matches the audit commit |
| Read `README.md` to find the quickstart | ~40 s (359 lines; quickstart is at line 223) | Found on first read, no ambiguity |
| `task install` | **2 s** | rc=0. Runs `uv sync --all-packages` then `uv run pre-commit install`; ends `pre-commit installed at .git/hooks/pre-commit` |
| `task check` | **129 s** | rc=0 green, first attempt, zero errors |
| **TTHW (clone → green `task check`)** | **~2 min 53 s** including the README read; **133 s** of machine time | **Competitive** tier (2-5 min) on the rubric's TTHW table |

Zero points where I had to guess, read a second doc, or recover from an error. The quickstart is
two commands and both worked verbatim.

`task check`'s stages, from the run log (`grep '^task: \[' `):
lint (ruff format --check, ruff check) → typecheck (mypy on TYPED_PATHS, 8 separate
`pyright -p <pkg>` invocations) → test (one pytest over 14 test roots with coverage, then four
per-package `coverage report --fail-under` calls, then `test:services`) → twenty:validate →
twenty:test (`[ -d node_modules ] || npm ci`, then typecheck + vitest) → workflow:lint →
docs:lock-guard → docs:build.

Warm per-target timings measured afterwards in the same clone:

```
task lint            ->  155 ms
task workflow:lint   ->  149 ms
task twenty:validate ->  204 ms
task docs:build      ->  1262 ms
task typecheck       ->  7752 ms
task test            ->  89 s
```

`task test` is 89 s of the 98 s a warm `task check` costs. `task test` takes no narrowing variable
(`Taskfile.yml:154-166`) - it always runs all 14 test roots plus every ocean service suite.

### Cache warmth

The 2 s `task install` is not a cold number. `~/.cache/uv` held 26 GB of wheels before the clone.
A genuinely cold machine pays the download of ~190 resolved packages plus `npm ci` for the Twenty
workspace. I did not clear the cache to measure the cold path, so **cold TTHW is unmeasured**
(see Method notes).

### Friction

- **`bootstrap.sh` sits at the repo root and the quickstart never mentions it.** README names it
  only at line 293, as a thing likely to break a scaffold gate. A newcomer who runs it gets
  `This repo is already generated; run \`task install\`.` and exit 2 - a good error, but the file's
  presence is a moment of doubt the quickstart could have removed. TESTED.
- **The docs site's Home page is a dead end.** `docs/index.md` is 8 lines: four shields.io badges
  and the one-line tagline. `mkdocs.yml`'s nav has no "Getting started" entry, and `README.md` -
  the actual onboarding document - is not published to the site at all. A newcomer who lands on
  the built docs rather than the GitHub repo gets nothing. TESTED.
- Grepping for the phrases a newcomer types finds no landing page:
  `grep -ril "getting started" docs/ README.md CONTRIBUTING.md` → only
  `docs/process/devex-audit/task-a.md`; `"onboarding"` → same single file (this audit's own task
  brief). TESTED.

### What a 10 looks like here

Same two commands, unchanged - they are already the good part. A 10 adds `docs/index.md` as a real
landing page (what PULSE is, the two quickstart commands, "your first connector" pointing at
`docs/connectors/authoring.md`, "how work ships" pointing at `WORKFLOW.md`), and either deletes
`bootstrap.sh` from generated repos or names it in the quickstart as "not for you".

---

## Step 2 - API/CLI/SDK ergonomics, connector-focused

### What I did

Attempted to understand and scaffold a pocar connector using only what the repo tells me.

```bash
grep -rn "connectors/authoring" . --include="*.md" --include="*.yml" --include="*.py"
cat docs/connectors/authoring.md
uv run python -c "from pulse_core.connector import (CursorStore, RowSource, ...)"
uv run python -c "import pulse_core.connector as c; print(sorted(c.__all__))"
uv run python scripts/connector_new.py --name pocar --print-registrations
task connector:new NAME=pocar
task install && task check
```

### Path to the guide (TESTED)

`docs/connectors/authoring.md` (321 lines) is the answer, and it is **not linked from README or
CONTRIBUTING**. `grep -n "authoring" README.md CLAUDE.md AGENTS.md docs/index.md` → no matches.
The only inbound references are:

- `mkdocs.yml:36` - nav entry `Connectors > Authoring`
- `design/platform/pulse-standard-connector-spec.md:17`
- `scripts/connector_new.py:253` (a comment)
- `tests/scaffold/cat8_docs_consistency.py:609` and `cat10_devex.py:69`

So the persona finds it by browsing the docs site nav or by grepping for "connector" - not from
either of the two documents GitHub puts in front of a new contributor.

### Files and docs read before I could act (TESTED)

| # | Artifact | Why |
| --- | --- | --- |
| 1 | `README.md` (359 lines) | quickstart, the Connectors section at line 96 |
| 2 | `docs/connectors/authoring.md` (321 lines) | the whole job |
| 3 | `task` listing | to find `connector:new` |
| 4 | `templates/connector/` file list | to check the guide's tree claim |

Four artifacts, of which one (the guide) is sufficient on its own. **Concepts to learn before the
first line of code**: connector shape (one process, no HTTP surface), inbound vs outbound
direction, the kit's twelve named primitives, credential-name-not-value, receipts as counts, the
nine registration sites, the socket-block test posture, the OpenSpec/HANDOFF ship path. Eight
concepts, and the guide sequences all eight in the order they are needed.

### The scaffold command (TESTED)

`task connector:new NAME=pocar` completed in **under 1 second**:

```
Rendered pocar (pocar) into .../packages/pocar:
  packages/pocar/README.md
  packages/pocar/pyproject.toml
  packages/pocar/src/pocar/{__init__,config,py.typed,receipts,service}.py
  packages/pocar/tests/{conftest,test_receipts}.py

Registered pocar at 2 site(s):
  Taskfile.yml
  pyproject.toml

Next: uv sync --all-packages
```

`--print-registrations` is a true dry run: it printed a unified diff of all nine edits
(`[tool.uv.workspace] members`, `[tool.uv.sources]`, `[tool.ruff.lint.per-file-ignores]`,
`LINT_PATHS`, `TYPED_PATHS`, `TESTED_PATHS`, `COV_PATHS`, and commented `pocar:image` /
`pocar:deploy` stanzas) and `git status --short` afterwards was **empty**. TESTED.

After the scaffold: `task install` (1 s) then `task check` → **rc=0 in 98 s**. The rendered package
lints, typechecks, tests, and is covered on the first try. `packages/pocar/tests/test_receipts.py`
contributed 3 passing tests.

**How far I got**: all the way through registration and a green gate, without getting stuck, in
under three minutes of machine time. This is the strongest part of the repo's DX.

### Public surface vs the spec vs the reference (TESTED)

- `pulse_core.connector.__all__` exports **26 names**. The guide's import block (section 2) names
  12 of them; the exact block imports cleanly (`IMPORT OK`).
- `openspec/specs/connector-kit/spec.md` (83 lines) names **zero code symbols** - it is
  behaviour-level requirements ("The kit is extracted, not invented", "Inbound reads follow the
  row-source and cursor contract"). So there is no spec-side enumeration of the public surface to
  compare against; the guide's list is the only one, and nothing gates the guide's list against
  `__all__`. `packages/pulse-core/tests/test_connector_exports.py` checks only that a star-import
  binds every `__all__` name.
- **The reference implementation contradicts the guide's import rule.** The guide says (line 37):
  "Import from the package root, not the submodules — the root is the supported surface." The
  reference `packages/billing-connector` imports from submodules in two of four modules:

  ```
  packages/billing-connector/src/billing_connector/declare.py:34:
      from pulse_core.connector.declare import submit_with_retry
  packages/billing-connector/src/billing_connector/receipts.py:17:
      from pulse_core.connector.declare import DeclareCounts
  packages/verdict-relay/src/verdict_relay/declarer.py:66:
      from pulse_core.connector.declare import DeclareCounts, Jitter, Sleeper, submit_with_retry
  ```

  The guide also says "when this page is ambiguous, that package is the answer", so the persona
  gets two contradictory signals and nothing enforces either. TESTED.
- **The root surface is genuinely incomplete.** `Jitter` is used by `verdict-relay` and is named
  in the guide's own section 5 ("`submit_with_retry` takes `sleep` and `jitter` callables — pin
  them and the backoff schedule is deterministic"), but it is not exported:

  ```
  >>> from pulse_core.connector import Jitter
  ImportError: cannot import name 'Jitter' from 'pulse_core.connector'
  ```

  A connector author who follows section 5's advice must go around the surface the guide told them
  was the only supported one. TESTED.

### The guide's rendered-tree diagram does not match what ships (TESTED)

`docs/connectors/authoring.md:102-116` claims the scaffold renders:

```
└── tests/
    ├── __init__.py
    ├── conftest.py                # the socket block — see step 5
    ├── factories.py               # fakes at the httpx boundary
    └── test_config.py
```

`templates/connector/` contains `tests/conftest.py.tmpl` and `tests/test_receipts.py.tmpl` only.
The actual render produced `tests/conftest.py`, `tests/test_receipts.py`, and a
`packages/pocar/README.md` the diagram does not mention. **Three of four listed test files do not
exist; one rendered file and the package README are unlisted.** `cat8_docs_consistency.py` has six
gates on this guide (task targets defined, go-task var syntax, kit vocabulary, all registration
sites, spec/reference citation, offline posture) and none of them compares the diagram to
`templates/connector/`. TESTED.

Downstream of that: the guide's section 5 lists "`from_env()` with an empty environment names
every missing variable" as a test that pays for itself immediately, and the template ships no
`test_config.py` to hold it. Coverage of the fresh package reflects this:

```
packages/pocar/src/pocar/config.py     49  49    0%   13-102
packages/pocar/src/pocar/service.py    33  33    0%   13-83
packages/pocar/src/pocar/receipts.py   10   0  100%
```

A brand-new connector joins `COV_PATHS` at 0% on its two largest modules and `task check` still
passes, because the repo floor is a global `fail_under = 80` (`pyproject.toml:150`) that a tiny
package cannot move. INFERRED for what happens once the package grows.

### The scaffold renders one direction only (TESTED)

The guide's section 1 states two directions, inbound and outbound, and lists different kit surfaces
for each. `scripts/connector_new.py`'s full argument surface is
`--name --dest --root --template --force --print-registrations --apply-registrations` - there is no
direction flag. The rendered `service.py` is outbound-only: it imports `consume` and wires an SQS
consume loop. An inbound pocar connector (page the POCAR backend, validate rows, declare) has to
delete and rewrite `service.py` against `RowSource` / `CursorStore` / `validate_page`, which the
template does not demonstrate anywhere.

### A pocar connector already exists in this repo, and nothing said so (TESTED)

```bash
$ git ls-files | grep -i pocar | wc -l
15
packages/ocean/services/pocar-connector/Dockerfile
packages/ocean/services/pocar-connector/src/{main,receiver,normalizer,heartbeat}.py
packages/ocean/services/pocar-connector/src/schema/pocar_webhook.py
packages/ocean/services/pocar-connector/tests/{conftest,test_normalizer,test_publishing,test_receiver}.py
packages/ocean/tests/unit/test_pocar_normalizer.py
```

The absorbed legacy tree already carries a POCAR connector - a webhook receiver with a normalizer
and a schema. `task connector:new NAME=pocar` created `packages/pocar` beside it with no warning,
and no document (README, the authoring guide, `docs/contracts/producer-registry.md`) tells a new
connector author to look in `packages/ocean/services/` for prior art on the system they are
integrating. For this persona that is the single highest-impact miss in the repo: the prior art for
their exact task is in the tree and invisible.

### What the guide gets right, verified

Every path named in section 9's "who to ask" table resolves: `openspec/specs/connector-kit/spec.md`,
`packages/billing-connector`, `packages/consent-ingress`, `packages/verdict-relay`,
`docs/ci-lessons.md`, `WORKFLOW.md`, `AGENTS.md`,
`openspec/specs/connectors/pulse-standard-connector-spec.md`,
`docs/runbooks/billing-connector.md`. Nine for nine. TESTED.

### `task` help text and target naming

Naming is consistent and predictable: `<area>:<verb>` throughout (`twenty:deploy`, `spec:validate`,
`lore:drift`, `billing-connector:image`). The scaffold's generated deploy stanzas follow the same
convention (`pocar:image`, `pocar:deploy`), so a connector author's targets look like everyone
else's without being told. The one inconsistency is guardrails: `connector:new` declares
`requires: vars: [NAME]` and refuses to run without it, while `verify` says "(needs CHANGE)" in its
`desc` and declares no `requires` (`Taskfile.yml:566-572`) - see Step 3.

### What a 10 looks like here

`task connector:new NAME=pocar DIRECTION=inbound` renders the row-source variant, and the command
prints `note: packages/ocean/services/pocar-connector already exists - see it before you start`
when the name collides with anything in the tree. The guide's tree diagram is generated from
`templates/connector/` (or gated by cat8), `Jitter` joins `__all__` (`Sleeper` already does), and either the
reference connector's submodule imports are lifted to the root or the guide stops claiming the root
is the only supported surface.

---

## Step 3 - Error messages

Nine realistic mistakes, triggered deliberately. Verdict columns: does the message state the
**problem**, the **cause**, and the **fix**?

### E1 - `task connector:new` with no NAME (TESTED)

```
task: Task "connector:new" cancelled because it is missing required variables: NAME
```

Problem yes. Cause yes (names the variable). Fix no - it never shows `NAME=<value>`, which matters
because go-task's variable syntax is exactly what newcomers get wrong (see E2, E4).

### E2 - `scripts/connector_new.py pocar` (positional, as the guide's prose implies) (TESTED)

The guide says "`scripts/connector_new.py` is what the target runs; `--print-registrations` shows
the diff it will apply without writing anything" without showing an invocation, so a positional
name is the natural first try:

```
usage: connector_new.py [-h] --name NAME [--dest DEST] [--root ROOT]
                        [--template TEMPLATE] [--force]
                        [--print-registrations] [--apply-registrations]
connector_new.py: error: the following arguments are required: --name
```

Problem yes, cause yes, fix yes (the usage line is the fix). Standard argparse, adequate.

### E3 - `task connector:new NAME=pocar` when the package exists (TESTED)

```
error: destination already exists: .../packages/pocar (pass --force to overwrite)
task: Failed to run task "connector:new": exit status 2
```

Problem, cause, and fix, in one line. This is the best error in the repo.

### E4 - flag-style task argument, the trap `CLAUDE.md` warns about (TESTED)

```bash
$ task dispatch --change billing-connector
```

go-task dumps its **entire global help screen** (every flag from `-C` to `-y`), and the actual
error is the last line under all of it:

```
  -y, --yes                         Assume "yes" as answer to all prompts.
unknown flag: --change
```

Problem stated (buried). Cause not stated. Fix not stated - nothing says "use `CHANGE=...`". This
is a documented repo trap (`CLAUDE.md`: "Passing the change as a flag instead exits 2 with
`unknown flag`"), and the newcomer meeting it has not read `CLAUDE.md`. It is also upstream
go-task behaviour, so the repo's lever is a wrapper or a `desc` that shows the form.

### E5 - connector config with an empty environment (TESTED)

```
pocar configuration is unusable:
  - POCAR_QUEUE_URL is unset — the inbound SQS queue URL
  - POCAR_LEDGER_BASE_URL is unset — the command-API base URL
  - POCAR_TOKEN is unset — this connector's ledger writer token
```

Problem, cause, and fix, for **all three at once** rather than one per process start. This is baked
into the template (`packages/pocar/src/pocar/config.py`, `ConfigError(problems)` plus the
`_resolve_stale_after(raw, problems)` collect-don't-raise helper shape), so every connector gets it
without being told. Best-in-class; the rubric's "Fight uncertainty" principle, satisfied by
construction.

### E6 - connector config with an invalid value (TESTED)

```
pocar configuration is unusable:
  - POCAR_STALE_AFTER_SECONDS='banana' is not an integer — whole seconds
```

Problem, cause, fix (names the variable, the bad value, and the expected unit). No secret is ever
echoed - the token variable is checked for presence and never read.

### E7 - credential-posture violation (a second credential name plus a DSN literal) (TESTED)

Appended to `packages/pocar/src/pocar/config.py`, then
`uv run pytest packages/pulse-core/tests/test_connector_credential_gate.py -q`:

```
E  AssertionError: pocar declares ['POCAR_ADMIN_TOKEN', 'POCAR_TOKEN'] — want exactly one credential name
E  AssertionError: pocar reaches ledger internals: ['packages/pocar/src/pocar/config.py: postgresql://ledger:pw@db:5432/ledger']
2 failed, 26 passed in 0.19s
```

The gate **auto-discovered the new package with zero registration** (any package whose `src/` tree
imports `pulse_core.connector` is in scope) and ran in 0.19 s. Problem yes, cause yes (names the
file and the offending literal). Fix no - it does not say why one credential is the rule or point
at ADR-0003 / the authoring guide, so the author has to search for the reason. Minor note: the
message echoes the connection-string literal back into test output; harmless with a synthetic DSN,
but it is a code path that prints a credential-shaped string.

### E8 - a failing test in the new connector (TESTED)

```
    def test_deliberate_failure() -> None:
>       assert 1 == 2
E       assert 1 == 2
packages/pocar/tests/test_receipts.py:39: AssertionError
FAILED packages/pocar/tests/test_receipts.py::test_deliberate_failure
1 failed, 3 passed in 0.13s
```

Stock pytest, 0.13 s for the package-scoped run. Fast enough that the inner loop the guide
prescribes (`uv run pytest packages/my-connector/tests`) is genuinely tight.

### E9 - a required tool missing from PATH (TESTED)

```
$ env PATH=<shim> task spec:validate
task: [spec:validate] openspec validate
"openspec": executable file not found in $PATH
task: Failed to run task "spec:validate": exit status 127

$ env PATH=<shim> task lore:drift
"openlore": executable file not found in $PATH
task: Failed to run task "lore:drift": exit status 127
```

Problem yes, cause yes, fix no - neither says `npm install -g @fission-ai/openspec openlore`. Made
worse by README listing both under **"Optional but recommended"** (line 214) while
`docs/connectors/authoring.md` step 8.5 tells a connector author to run `task verify CHANGE=<id>`,
which requires both.

### E10 - `task verify` in a fresh clone (TESTED, and the worst result of the audit)

```bash
$ task verify
task: [lore:drift] openlore drift

Spec Drift Detection

[error] No openlore configuration found. Run "openlore init" first.
task: Failed to run task "verify": task: Failed to run task "lore:drift": exit status 1
```

Two defects in one command:

1. **`verify` never complains about the missing `CHANGE`.** Its `desc` says "(needs CHANGE)" but
   `Taskfile.yml:566-572` declares no `requires: vars: [CHANGE]`, unlike `connector:new`. It runs
   `check`, `workflow:lint:linear`, `lore:drift`, `spec:validate` and fails on whichever breaks
   first, with a message about none of them being what you got wrong.
2. **`.openlore/` is gitignored (`.gitignore:227`) and absent from a fresh clone**, and no task
   target creates it - `task lore:analyze` fails identically:

   ```
   task: [lore:analyze] openlore analyze
   [error] No openlore configuration found. Run "openlore init" first.
   ```

   The tool's suggested fix (`openlore init`) is correct but appears in no repo document; no repo document or `task` target tells an author to run `openlore init --force`; it is written down only in `bootstrap.sh:177`, `scripts/orca-worktree-setup.sh:17` and `tests/scaffold/cat7_gates_hooks.sh:94`, which refuses to run on a
   generated repo. So the gate the connector authoring guide tells authors to run **cannot succeed
   on a fresh clone by any documented path**.

Mitigating, and checked: this does not break the first commit. The `openlore-drift` pre-commit hook
is scoped `files: ^(src/.*\.py|openspec/.*)$` (`.pre-commit-config.yaml:42`), so a commit under
`packages/` skips it:

```
openlore drift.......................................(no files to check)Skipped
[main 5ef96a3] feat: scaffold pocar connector
 12 files changed, 403 insertions(+), 4 deletions(-)
```

That scoping has a second consequence worth naming: **drift detection never fires for `packages/`**,
which is where all 15 packages and every connector live. INFERRED from the hook's `files` regex.

### E11 - gate run from the wrong directory (TESTED, and it is a non-event)

```bash
$ cd packages/pocar && task check
... INFO - Documentation built in 0.67 seconds
```

go-task walks up to the root `Taskfile.yml` and every path resolves against the repo root. No
error, no wrong-directory failure mode. Positive finding.

### Summary

| # | Mistake | Problem | Cause | Fix |
| --- | --- | --- | --- | --- |
| E1 | `connector:new` no NAME | yes | yes | no |
| E2 | script positional arg | yes | yes | yes |
| E3 | scaffold name exists | yes | yes | yes |
| E4 | `--change` flag form | buried | no | no |
| E5 | empty connector env | yes | yes | yes (all at once) |
| E6 | invalid config value | yes | yes | yes |
| E7 | credential-gate violation | yes | yes | no |
| E8 | failing test | yes | yes | n/a |
| E9 | missing openspec/openlore | yes | yes | no |
| E10 | `task verify` fresh clone | wrong problem | no | wrong fix |

### What a 10 looks like here

Every message that states a problem also states the fix as a runnable command. Concretely:
`verify` gains `requires: vars: [CHANGE]`; a `lore:init` target (or `task install` doing it) makes
`openlore init --force && openlore analyze` a documented, run-once step; the credential gate's
assertion messages end with `see docs/connectors/authoring.md#6-what-is-enforced`; and the missing
`openspec`/`openlore` case is pre-flighted by a `task` target that prints the npm install line
rather than letting exit 127 through.

---

## Step 4 - Documentation

### What I did

```bash
uv run mkdocs build -s                                  # strict build
for q in "how do I add a connector" connector scaffold "getting started" quickstart onboarding; do
  grep -ril "$q" docs/ README.md CONTRIBUTING.md; done
sed -n '/^nav:/,/^plugins:/p' mkdocs.yml
git ls-files | grep -i pocar          # currency check against README claims
ls openspec/changes/archive | wc -l   # currency check
grep -n "id:" .pre-commit-config.yaml # currency check against CONTRIBUTING
```

### Currency (TESTED)

`mkdocs build -s` is **clean** - zero broken links, zero warnings beyond the upstream
Material-for-MkDocs 2.0 banner, which is not a repo defect. `docs/lock-guard` additionally pins the
docs toolchain (`uv lock --check` plus a grep guard against mkdocs-successor forks).

Three stale claims found, none of them gated:

| Claim | Where | Reality (TESTED) |
| --- | --- | --- |
| "Twenty-two changes have been archived" | `README.md:28` | `ls openspec/changes/archive` → **20** |
| "Fourteen packages live under `packages/`" | `README.md:115` | 14 before my scaffold; hand-maintained, nothing gates it |
| "Pre-commit hooks run `ruff`, `mypy` and `openlore drift`" | `CONTRIBUTING.md:17` | `.pre-commit-config.yaml` hook ids are `check-case-conflict, check-merge-conflict, check-toml, check-yaml, check-json, pretty-format-json, end-of-file-fixer, trailing-whitespace, ruff-check, ruff-format, openlore-drift`. **There is no mypy hook.** |

### Findability (TESTED)

- `grep -ril "how do I add a connector" docs/ README.md CONTRIBUTING.md` → **nothing**.
- `grep -ril "getting started"` → `docs/process/devex-audit/task-a.md` only (this audit's brief).
- `grep -ril "onboarding"` → same single file.
- `grep -ril "connector"` → `docs/modules.md`, `docs/architecture.html`,
  `docs/connectors/authoring.md`. The right document is in the top three for the obvious word, so a
  grep for "connector" lands correctly; a grep for the question a newcomer actually asks does not.
- The mkdocs nav has one `Connectors > Authoring` entry, which is the correct place, but Home is
  the 8-line badge stub and there is no Getting Started section.
- Neither `README.md` nor `CONTRIBUTING.md` links to the authoring guide - the two files GitHub
  surfaces first.
- The nav publishes this audit's own task briefs (`process/devex-audit/task-a.md`, `task-b.md`,
  `task-c.md`) to the docs site, which is process exhaust in a reader-facing nav.

### Does the connector guide answer the persona's questions, in order? (TESTED)

| # | Question | Section | Answered |
| --- | --- | --- | --- |
| 1 | What is a connector here? | 1 | Yes - shape, five invariants, inbound/outbound table |
| 2 | What do I import? | 2 | Yes - a copy-paste block, verified to import cleanly. Gap: `Jitter` is named in prose but not exported; the rule "root, not submodules" is contradicted by the reference |
| 3 | How do I scaffold? | 3 | Yes - three commands, all verified working. Gap: the rendered tree diagram is wrong (Step 2) |
| 4 | How do I configure? | 4 | Yes - the frozen-dataclass pattern, and the template implements every rule it states |
| 5 | How do I test offline? | 5 | Yes - socket block plus four named injection seams, plus the four tests worth writing first. Gap: the template ships none of those four |
| 6 | How do I register the package? | 7 | Yes - nine sites, two files, plus the grep to confirm none is missing. `task connector:new` performs all nine |
| 7 | How do I ship through the workflow? | 8 | Yes - five steps, plus the two exceptions (cross-repo contract, prod-touching runbook) |
| 8 | Who do I ask? | 9 | Yes - named owner, and a seven-row "before asking" table whose nine paths all resolve |

**The guide answers all eight, in exactly the persona's order.** That is unusual and it is the
repo's strongest document. Its defects are all local: one wrong diagram, one contradicted import
rule, one missing export, and no inbound example.

Section 6 ("What is enforced, before you get to CI") deserves separate credit: it tells the author
that the credential gate discovers their package automatically, and I verified that it does (E7).
"There is nothing to register for this. Import the kit and you are in scope, which is the point."

### What a 10 looks like here

`docs/index.md` becomes a real front door with a Getting Started section; `README.md` line ~99 and
`CONTRIBUTING.md` both link to the authoring guide by name; the three stale claims are either
generated or gated by `cat8` (the archive count and package count are both one-line `assert` gates);
and the audit task briefs move out of the reader-facing nav.

---

## Step 5 - Upgrade path

### What I did

```bash
cat .ade-template-version; task template:diff
ls docs/adr/; ls openspec/changes/archive | wc -l
grep -rn -i "deprecat\|breaking\|version" openspec/specs/connector-kit/spec.md
grep -n "^version" packages/pulse-core/pyproject.toml; ls CHANGELOG*
```

### What I observed

**Template sync (TESTED).** `.ade-template-version` holds
`a1de595b8591691a624d67d60efaa20d73641967`. `task template:diff` ran in 3 s and printed a real
diffstat against the template - `15 files changed, 2981 insertions(+), 26 deletions(-)`, covering
`scripts/dispatch_tasks.py`, `scripts/linear_sync.py`, `scripts/workflow.py`, five scaffold gates
and four golden fixtures - ending with `Apply with: task template:sync`. Problem, scope, and fix,
in one command. This is the upgrade story done well, and `CLAUDE.md` states the discipline
("Fix a template-level bug in the template, not here") plus the exclusions (README, CLAUDE.md,
`src/`).

**ADR discipline (TESTED).** Six ADRs including `ADR-0000-template.md`, all in the mkdocs nav,
append-only by convention (`CLAUDE.md`: "a superseded decision gets a status flip and a new ADR").

**Spec archiving (TESTED).** 20 archived changes under `openspec/changes/archive/`, each date-
prefixed (`2026-09-02-connector-pattern`). 48 accumulated capability specs. `task spec:archive` is
the only writer of `openspec/specs/`. The mechanism is real and used.

**How a connector author absorbs a kit change: nothing tells them. (TESTED)**

- `packages/pulse-core/pyproject.toml:3` → `version = "0.1.0"`. The kit every connector depends on
  has never been versioned. Workspace members resolve it as `{ workspace = true }`, so a kit change
  reaches every connector on the next `uv sync` with no signal at all.
- `grep -rn -i "deprecat\|breaking\|version" openspec/specs/connector-kit/spec.md` → **no matches**.
  The kit's own spec says nothing about how it changes.
- No `CHANGELOG` exists anywhere in the repo (`ls CHANGELOG*` → no matches).
- No migration guide: `grep -rn -il "changelog\|migration guide" docs/ packages/pulse-core/` matches
  only `docs/process/devex-audit/rubric.md` (the word appears in the rubric text).
- `docs/connectors/authoring.md` has no upgrade section. Its only forward-looking statement is
  section 2's "If the kit is missing a primitive you need... propose extracting it once a second
  connector wants it" - which covers additions, not removals or signature changes.

The rubric's internal interpretation says "'Credible' includes deprecation and upgrade discipline
for the connector kit specifically". Measured against that sentence, the repo has strong upgrade
discipline for the **template** and none for the **kit**.

Mitigating (INFERRED): the kit is a workspace-internal dependency in a monorepo with one author, so
a breaking kit change and its consumers land in the same commit and `task check` catches the break
immediately. The absence bites the moment a second person owns a connector, not before.

### What a 10 looks like here

`packages/pulse-core/CHANGELOG.md` with one entry per kit-surface change, a `## Deprecations`
section in `openspec/specs/connector-kit/spec.md` stating the policy (how long a removed primitive
keeps a shim, how it warns), and a section 10 in the authoring guide: "when the kit changes, here is
what you do".

---

## Step 6 - Developer environment

### What I did

```bash
cat .python-version; grep -n requires-python pyproject.toml packages/pocar/pyproject.toml
cat .nvmrc; grep -n -A3 '"engines"' package.json
ls -a | grep -iE "vscode|editorconfig|idea"; cat .env.example
grep -nE "^  [a-z0-9-]+:|run:|node-version|python-version" .github/workflows/main.yml
```

### What I observed (TESTED)

**Toolchain pins.**

| Thing | Pin | Where |
| --- | --- | --- |
| Python (local) | `3.14` | `.python-version` |
| Python (support range) | `>=3.10,<4.0` | `pyproject.toml:8`, and the scaffold copies it into `packages/pocar/pyproject.toml:5` |
| Python (CI matrix) | 3.10, 3.11, 3.12, 3.13, 3.14 | `main.yml:56` |
| Node | `>=22` (`package.json` engines), CI pins `'22'` (`main.yml:43`) | **no `.nvmrc`** |
| uv, go-task | not pinned locally; CI installs a pinned uv via `./.github/actions/setup-python-env` | |
| GitHub Actions | SHA-pinned with version comments in `main.yml` | but `ci-health.yml` pins `actions/checkout@...# v4.0` while `main.yml` pins `# v7.0.1` |

I ran the whole audit on **node v26.8.1** against a repo whose engines say `>=22` and whose CI runs
22. `task check`'s Twenty suite passed anyway (67 tests, 2.13 s), so the drift is currently benign -
but nothing pins it and nothing warns.

**Editor support: none committed.** No `.vscode/`, no `.editorconfig`, no devcontainer, no
recommended-extensions file. Ruff, mypy and pyright configuration all live in `pyproject.toml`, so
an editor that reads those works; nothing tells a newcomer which extensions produce the same
diagnostics `task lint` does.

**Pre-commit hooks after the documented install: present and working.** `task install` ends with
`pre-commit installed at .git/hooks/pre-commit`, and my test commit ran 11 hooks in ~1 s, all
passing or correctly skipped. No extra step required. This is a good default.

**`.env.example` is 10 lines** and documents exactly two variables (`ORCA_WORKTREES_DIR` and a
commented `ANTHROPIC_API_KEY`), both about the ADE tooling. It says nothing about connector runtime
variables. Defensible - each connector's `config.py` is self-documenting by design - but it means
the file is not the place a newcomer looks to learn what a running connector needs.

**`.envrc` is gitignored** (`.gitignore:144`) and absent from a fresh clone, so a direnv user gets
no starting point.

**Local vs CI parity (TESTED, and the claim is narrower than stated).** `main.yml` has three jobs:

- `quality` → `run: task check` (line 50). The contract holds exactly, and `cat4_ci_contract.py`
  gates it.
- `tests-and-type-check` → a 3.10-3.14 matrix running `uv run python -m pytest tests` and
  `uv run mypy` (lines 71, 74). **`task check` cannot reproduce this locally** - it runs one
  interpreter, the one in `.python-version` (3.14).
- `check-docs` → `task docs:lock-guard` and `task docs:build`, both of which `task check` already
  runs.

So "green locally means green in CI" (`README.md:283`, `CLAUDE.md`) is true for the `quality` job
and for docs, and **not** true for the Python compatibility matrix. A connector author who writes
3.12+ syntax passes locally and fails CI on 3.10 - with `requires-python = ">=3.10"` copied into
their package by the scaffold, this is a live trap, not a theoretical one. INFERRED (I did not
construct the failing case).

### What a 10 looks like here

`.nvmrc` with `22`; a committed `.editorconfig` and a minimal `.vscode/extensions.json` naming ruff
and pyright; `task check:matrix` (or a documented `tox`/`uv run -p 3.10` line - `tox.ini` and
`tox-uv` are already installed) so the compatibility job is reproducible; and the parity sentence in
README amended to say which job it covers.

---

## Step 7 - Community and ecosystem (internal-repo interpretation)

The rubric's internal interpretation asks for: a named owner per area (`CODEOWNERS`), a channel or
person named in `README.md`, issue and PR templates, and evidence that someone other than the owner
has landed a connector.

### What I observed (TESTED)

**`.github/CODEOWNERS`** - 39 bytes, two lines:

```
# Pulse code owners
* @robford-brookai
```

One wildcard. No per-area owner, so `packages/pulse-core/src/pulse_core/connector/` (the kit every
connector depends on) has no owner distinct from the repo default.

**Owner and channel.** `CONTRIBUTING.md` (23 lines) names the owner and states the gap honestly:
"Ask the owner directly on Slack; a dedicated channel has not been named yet."
`docs/connectors/authoring.md:293` repeats it verbatim. `README.md` names **no** owner and **no**
channel - it never mentions who to ask. So the rubric's "a channel or person to ask named in
`README.md`" is not satisfied; it is satisfied one hop away, in two other files.

**Templates.** `.github/PULL_REQUEST_TEMPLATE.md` exists (37 lines: type-of-change, testing,
checklist including an explicit "I have not added any PHI or sensitive data" item - good for a
healthcare repo). `.github/ISSUE_TEMPLATE/` holds exactly one template, `attended-run.yml`, which
matches `WORKFLOW.md`'s live-execution path. There is no bug or feature-request template.

The PR checklist says "I have run `task fmt` and `task lint`" and "I have run `task test`", but not
`task check` - which is the actual contract with CI and the thing every other document tells you to
run. A contributor who ticks all three boxes has still not run `twenty:validate`, `twenty:test`,
`workflow:lint`, `docs:lock-guard` or `docs:build`.

**Handoffs and work orders.** `handoffs/` holds 17 collected `<change>/SUMMARY.md` receipt
directories - a real, used trail. `templates/HANDOFF.md` opens with an explicit content rule
("receipts and spec-relevant deltas ONLY... no credentials, and no PHI, ever. A HANDOFF carrying
any of those is a review-reject"). `work_orders/` is generated and absent from a fresh clone, as
documented.

**Linear linkage.** `WORKFLOW.md:23` defines the grain precisely: "One OpenSpec change = one Linear
parent issue = one directory of dispatched work orders. One task = one Linear sub-issue = one
work-order file = one Orca worktree = one commit... the file is canonical and the sync is
one-directional." `task linear:sync` implements it, plan-only unless `APPLY=1`. Live-execution work
routes to GitHub issues instead, matching the `attended-run.yml` template. The model is coherent and
written down.

**Has anyone other than the owner landed a connector? No. (TESTED)**

```bash
$ git log --format='%an <%ae>' | sort | uniq -c | sort -rn
 947 (the repo owner; name and address withheld)
   1 t <a@b>                        # my own test commit in the audit clone

$ git log --format='%an' -- packages/billing-connector packages/pulse-core/src/pulse_core/connector | sort | uniq -c
  17 Rob Ford
```

947 of 947 real commits by one author. Zero connectors landed by anyone else. The rubric says this
"cannot be manufactured", and it has not been.

### What a 10 looks like here

`CODEOWNERS` with a line for `packages/pulse-core/src/pulse_core/connector/` and one per package
area; a "Who to ask" line in `README.md` itself; a bug-report issue template alongside
`attended-run.yml`; and the PR checklist's three separate commands replaced by the one that is
actually the contract, `task check`. The "someone else landed a connector" evidence is a hiring and
delegation outcome, not a repo edit.

---

## Step 8 - DX measurement

### What I did

```bash
task devex:check
head -25 .github/workflows/ci-health.yml
grep -n -i "time\|duration\|elapsed" Taskfile.yml
```

Per the blindness constraint I did **not** open `tests/scaffold/cat10_devex.py`, `scripts/devex/`,
`.planning/devex/`, or any prior `.planning/reports/*devex*` file. What follows is observed from
command behaviour and from surfaces I was permitted to read.

### What I observed (TESTED)

**The repo does measure one DX metric, and emits it in a machine-readable form:**

```
$ task devex:check
task: [devex:check] uv run python scripts/devex/check.py
wrote .planning/devex/2026-09-04-check.json
METRIC devex_open_findings=0
```

A named metric, a dated JSON artifact, and a task target that anyone can run. There is a second
target, `devex:audit`, described as "Print the DevEx audit runbook and today's report paths (the
audit itself runs via /devex-audit)", and a frozen rubric under `docs/process/devex-audit/` with a
`CHECKSUMS` file - so the measurement protocol itself is version-controlled and tamper-evident. That
is more DX self-measurement than most repos have.

**What is not measured:**

- **Onboarding time.** Nothing records TTHW. The 133 s figure in Step 1 exists only because this
  audit measured it by hand; there is no target, no baseline, and no trend.
  QA correction (2026-09-04, QA report 6.1): the repo does record all three, in files the
  blindness rule forbade this audit to open: a TTHW gate in `tests/scaffold/cat10_devex.py`, the
  2026-09-02 baseline and a per-PR trend in `.planning/devex/loop.jsonl`.
- **Gate durations.** `grep -n -i "time\|duration\|elapsed" Taskfile.yml` returns only two comment
  lines about deploy-time invocations. No target times itself. `task check` at 129 s cold / 98 s
  warm, with `task test` at 89 s of it, is a number nobody in the repo is tracking.
- **Drift over time.** `openlore drift` is a pass/fail pre-commit hook scoped to
  `^(src/.*\.py|openspec/.*)$`; nothing records a drift count as a metric, and the scope excludes
  `packages/` entirely.
- **CI health as a trend.** `.github/workflows/ci-health.yml` exists but is
  `on: workflow_dispatch: {}` only - manual, never scheduled, so it produces no series.

So: the repo measures **whether its DX findings are closed** (a lagging quality signal) and not
**how long anything takes** (the leading experience signal the rubric's TTHW table is built on).

### What a 10 looks like here

`task check` prints a per-stage duration line and appends it to `.planning/devex/timings.jsonl`, so
the 89 s test stage is visible as a trend rather than a thing an auditor discovers. `devex:check`
emits `METRIC devex_tthw_seconds` from a scheduled cold-clone job (the `cat9` golden fresh-clone
gate already does the hard part - it just does not time itself), and `ci-health.yml` runs on a
schedule so CI health is a series.

---

## Connector author journey

Elapsed is cumulative wall clock from the start of the fresh clone, machine time only (it excludes
my reading time except where a row says otherwise). Every row is TESTED unless marked.

| Elapsed | Action | Outcome | Stuck point |
| --- | --- | --- | --- |
| 0:00 | `git clone https://github.com/robford-brookai/pulse.git` | 2.04 s, 26 MB, HEAD `b26dee0` | none |
| 0:02 | Read `README.md` to find how to start (~40 s reading) | Quickstart at line 223: `task install`, `task check` | none |
| 0:42 | `task install` | rc=0 in 2 s; venv + 190 packages + pre-commit hook installed | warm uv cache - cold path unmeasured |
| 0:44 | `task check` | **rc=0 green in 129 s, first attempt** | none. TTHW ≈ 2 min 53 s incl. reading |
| 2:53 | Look for "how do I add a connector" | `grep -ril "how do I add a connector"` → nothing; README's Connectors section (line 96) links the kit source but not the guide | **Stuck 1**: neither README nor CONTRIBUTING links `docs/connectors/authoring.md` |
| 2:55 | Find the guide via `task` listing / mkdocs nav | `docs/connectors/authoring.md`, 321 lines, answers all eight questions in order | none once found |
| 3:00 | Read the guide (~6 min reading) | Import block, scaffold command, nine registration sites, ship path | none |
| 9:00 | `uv run python scripts/connector_new.py pocar --print-registrations` | argparse error: `--name` is required | **Stuck 2**: the guide names the script and the flag but shows no invocation |
| 9:01 | `... --name pocar --print-registrations` | Unified diff of all nine registrations; `git status` empty afterwards | none - true dry run |
| 9:02 | `task connector:new NAME=pocar` | 9 files rendered, 9 sites registered across 2 files, <1 s | **Stuck 3**: `packages/ocean/services/pocar-connector` already exists (15 tracked files) and nothing said so |
| 9:03 | Compare rendered tree to the guide's diagram | Guide lists `tests/__init__.py`, `factories.py`, `test_config.py`; none exist. `README.md` rendered but undiagrammed | **Stuck 4**: diagram is wrong, and no gate covers it |
| 9:04 | `task install` | rc=0 in 1 s | none |
| 9:05 | `task check` | **rc=0 green in 98 s** with the new package linted, typechecked, tested, covered | none |
| 10:43 | `git commit` the scaffold | 11 pre-commit hooks, ~1 s, `openlore drift` correctly skipped | none |
| 10:44 | Decide what to write: pocar is an inbound source | Template `service.py` is outbound-only (`consume` loop); no inbound variant | **Stuck 5**: must delete and rewrite `service.py` against `RowSource`/`CursorStore` with no worked example |
| 10:45 | Follow the guide's "import from the root" rule | `from pulse_core.connector import Jitter` → `ImportError`; the reference connector itself imports from `pulse_core.connector.declare` | **Stuck 6**: guide's rule contradicted by the reference and by the export list |
| 10:46 | `task verify` before shipping (guide step 8.5) | `[error] No openlore configuration found. Run "openlore init" first.` - and no complaint about the missing `CHANGE` | **Stuck 7**: the documented pre-ship gate cannot pass on a fresh clone by any documented path |
| - | Write the OpenSpec change, dispatch, HANDOFF, PR, merge | INFERRED - not performed. `WORKFLOW.md` (433 lines) and `AGENTS.md` (96 lines) define it; 17 collected handoff directories show it is used in practice |
| - | Ship a real inbound pocar integration | INFERRED - not performed. Requires POCAR credentials and a live source; out of scope under the no-live-network constraint |

**Time to a green gate with a registered, CI-visible new connector package: about 10 minutes**,
of which ~7 is reading and ~3 is machine time. Time to a *useful* pocar connector: unmeasured, and
gated by Stuck 5 and Stuck 6.

---

## Top 10 friction points, ordered by impact on connector authors

1. **The prior POCAR connector is invisible.** `packages/ocean/services/pocar-connector` (15
   tracked files: receiver, normalizer, webhook schema, four test modules) already exists.
   `task connector:new NAME=pocar` created `packages/pocar` beside it silently, and no document -
   README, the authoring guide, `docs/contracts/producer-registry.md` - points a new connector
   author at `packages/ocean/services/` for prior art on the system they are integrating. The
   persona's exact prior work is in the tree and unfindable. TESTED.
2. **The scaffold renders outbound only.** `scripts/connector_new.py` has no direction flag, and
   the rendered `service.py` wires an SQS `consume` loop. The guide's own section 1 says inbound is
   one of two equal directions, and lists `RowSource`, `CursorStore`, `validate_page`,
   `submit_with_retry` as its surface - none of which the template demonstrates. An inbound author
   throws away the generated `service.py` and works from `packages/consent-ingress` by imitation.
   TESTED.
3. **`task verify` cannot pass on a fresh clone.** `.openlore/` is gitignored and absent; no task
   target creates it; `task lore:analyze` fails identically; the tool's suggested `openlore init`
   appears in no repo document. The authoring guide's step 8.5 tells connector authors to run this
   gate. Compounded by `verify` declaring no `requires: vars: [CHANGE]` despite "(needs CHANGE)" in
   its description, so the error you get is about none of what you did wrong. TESTED.
4. **The authoring guide is not linked from README or CONTRIBUTING.** The single best document in
   the repo, reachable only through the mkdocs nav, a grep for "connector", or
   `design/platform/pulse-standard-connector-spec.md:17`. The two files GitHub shows a new
   contributor first both miss it. TESTED.
5. **The guide's rendered-tree diagram is wrong.** It promises `tests/__init__.py`,
   `tests/factories.py`, `tests/test_config.py`; the template ships `tests/conftest.py` and
   `tests/test_receipts.py` and an undiagrammed `README.md`. The guide's section 5 then names
   `from_env()`-with-empty-environment as a test worth writing first and ships no file to hold it,
   leaving a new connector in `COV_PATHS` at 0% on `config.py` and `service.py`. Six `cat8` gates
   cover this guide and none covers the diagram. TESTED.
6. **"Import from the root" is contradicted by the reference and by the export list.**
   `packages/billing-connector` - which the guide names as the tiebreaker when the page is
   ambiguous - imports from `pulse_core.connector.declare` in two of four modules, as does
   `verdict-relay`. `Jitter`, named in the guide's own section 5 prose, is not in `__all__`. Nothing
   enforces the rule. TESTED.
7. **No deprecation or upgrade discipline for the kit.** `pulse-core` is version `0.1.0` with no
   changelog, no migration guide, and no `## Deprecations` section in
   `openspec/specs/connector-kit/spec.md`. A kit change reaches every connector on the next
   `uv sync` with no signal. Currently masked by single-authorship; it bites the moment a second
   person owns a connector. TESTED.
8. **`task test` is 89 s and cannot be narrowed.** It is 89 of the 98 s a warm `task check` costs,
   and `Taskfile.yml:154-166` takes no package variable. The guide does give the fast inner loop
   (`uv run pytest packages/my-connector/tests`, 0.13 s), so this bites on the pre-commit loop
   rather than the edit loop - but every commit costs a minute and a half. TESTED.
9. **Local/CI parity is narrower than the docs claim.** README and CLAUDE both say green locally
   means green in CI. True for the `quality` job; false for `tests-and-type-check`, a 3.10-3.14
   matrix `task check` cannot reproduce - and the scaffold copies `requires-python = ">=3.10,<4.0"`
   into every new connector. Also: no `.nvmrc` while CI pins node 22 (I ran node 26 throughout).
   TESTED / INFERRED for the failing case.
10. **Errors that state the problem but not the fix.** `connector:new` with no NAME never shows
    `NAME=<value>`; the credential gate names the violation but not the reason or the doc;
    `openspec`/`openlore` missing gives exit 127 with no install line, while README lists both as
    "Optional but recommended"; and `task dispatch --change X` buries `unknown flag: --change`
    under go-task's entire global help screen. TESTED.

Named separately because they are the counterweight and Task B should weigh them: the four things
this repo does better than most. (a) `task connector:new` performs all nine registrations and
`--print-registrations` is a true dry run that writes nothing. (b) The template's `ConfigError`
collects and reports **every** missing and invalid variable at once, so no connector has to
rediscover that. (c) The credential-posture gate discovers a new package with zero registration and
runs in 0.19 s. (d) `docs/connectors/authoring.md` answers all eight of the persona's questions in
the persona's order, and every one of the nine paths in its "who to ask" table resolves.

---

## Method notes and limits

**What I ran.** Every timing in this report is wall clock from `date +%s` around a single
invocation on this machine, in the fresh clone at `b26dee0`. Commands and outputs are quoted, not
paraphrased. Where I did not run something, the row or claim is marked INFERRED.

**Cache warmth is the biggest caveat on the TTHW number.** `~/.cache/uv` held 26 GB before the run
and `node_modules` was populated by `npm ci` inside the first `task check`. The 2 s `task install`
and the 129 s first `task check` are warm-machine best cases. I did not clear the caches, so
**cold-start TTHW is unmeasured** and is certainly worse - the download of ~190 Python packages plus
an npm install. A cold run is the single most valuable measurement a follow-up could add.

**Single machine, single platform.** macOS arm64 only. Nothing here says how the quickstart behaves
on Linux, on a machine without Homebrew, or without Docker installed. The README's prerequisite list
covers those platforms; I did not verify any of them.

**Non-persona tooling was already installed.** `openspec`, `openlore`, `gh`, `task`, `uv`, `node`
and Docker were all on PATH before I started, so I did not experience the prerequisite-install
stage. I simulated the missing-tool case with a PATH shim (E9) rather than by uninstalling.

**Blindness held, with one leak.** I did not open `tests/scaffold/cat10_devex.py`,
`scripts/devex/`, `.planning/devex/`, or any `.planning/reports/*devex*` file. Two unavoidable
incidental exposures: (1) `task`'s default listing names `devex:check` and `devex:audit`, and
`task devex:check`'s output line `METRIC devex_open_findings=0` is quoted in Step 8; (2) a repo-wide
`grep -rn "connectors/authoring"` printed three matching *lines* from
`.planning/reports/2026-09-02-devex-scorecard.md` and `.planning/reports/2026-09-02-devex-audit-evidence.md`
in its results. I did not open either file, and I have not used those lines to shape any finding
here. Task C should treat this note as the disclosure.

**Repo mutation.** The tracked repo at `/Users/Rob.Ford/Repos/robford-brookai/pulse` was not
modified; the only file this audit writes there is this report. All scaffolding, deliberate
breakage, the test commit, and `task devex:check`'s JSON artifact happened inside the throwaway
clone at `/private/tmp/claude-502/.../scratchpad/audit2/pulse`. Deliberate breakages (E7's second
credential name and DSN literal, E8's failing assertion) were reverted immediately after their
output was captured.

**No PHI, no live network, no production systems.** Every command was local. The only network call
was the `git clone` from GitHub. The one connection-string literal that appears in this report
(`postgresql://ledger:pw@db:5432/ledger`) is a synthetic string I wrote to trip the credential gate.

**Not covered.** I did not run `task test:all` (the slow sandbox and fresh-clone gates), any demo
(`demo:1` through `demo:e2e` need Docker/LocalStack or dev credentials), `task twenty:deploy` or any
other credentialed target, or a full OpenSpec change cycle end to end. The final two rows of the
journey table are INFERRED for that reason.

**No scores.** Per Task A's brief, this report assigns no numbers and makes no comparison to any
prior audit. Each step ends with a "what a 10 looks like for THIS repo" paragraph as the gap-method
input Task B needs; converting those into scores is Task B's job, and the boomerang comparison is
Task C's.
