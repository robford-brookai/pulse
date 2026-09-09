# DevEx audit evidence: pulse, 2026-09-08

> Corrections applied (QA 2026-09-08): C-1 (friction points 1 and 2 relocated to the first-commit
> stage, journey table red-gate row moved after the commit row, the "happy path fails" and
> "step 3" claims in Steps 2 and 4 rewritten), C-3 (230 s TTHW withdrawn; an independent fresh
> clone at the same sha measured 163 s, `test` at 120.6 s against this report's 187 s, matching the
> tracked ledger's 117-122 s range — tier unchanged, Competitive), C-5 (`__all__` corrected 27 to
> 28, `cat10_devex.py` corrected "roughly 30" to 58 `def test_`, shell scaffold gates corrected two
> to three, and the ledger count annotated as taken after this run's own gate appended rows — the
> tracked file holds 81 records, 48 timing), C-6 (Step 7's owner criterion corrected: `README.md`
> names neither a person nor a channel; the requirement is unmet, not met via `CONTRIBUTING.md`),
> C-9 (pre-commit hook tally corrected nine passed to 8 Passed, 3 Skipped). Not deleted: the
> original readings are struck through in place and the corrected readings follow, per
> `2026-09-05b-devex-audit-evidence.md`'s precedent of correcting rather than removing evidence.

Task A of the three-agent audit protocol (`docs/process/devex-audit/task-a.md`). Evidence only.
No scores are assigned here; scoring is Task B's job and the boomerang comparison against prior
runs is Task C's job, not mine.

- Repo under audit: `/Users/Rob.Ford/Repos/robford-brookai/pulse` at
  `f851ae0bd036c0f067514b4c57b10df7e956b669` on `main`.
- Methodology: the frozen rubric at `docs/process/devex-audit/rubric.md`, applied with its
  internal-repo interpretation as written.
- Persona: a competent engineer joining the team whose first job is to build a new connector for
  **zendesk**.
- Fresh clone used for every timing:
  `/private/tmp/claude-502/-Users-Rob-Ford-orca-workspaces-pulse-main/c093199d-084e-4ad5-aec0-137fe24b5e5d/scratchpad/devex-audit-2026-09-08/pulse`,
  pinned to the audited sha (`git rev-parse HEAD` returns `f851ae0bd036c0f067514b4c57b10df7e956b669`).
- Every observation is tagged TESTED (I ran it), PARTIAL (I ran part of it), or INFERRED
  (reasoned from files, not run).

---

## Step 0. Target discovery

### What I did

```bash
ls -la                                    # top-level surfaces
task                                      # the default target's grouped listing
task -l | grep -c '^\* '                  # target count
find docs -name '*.md' | wc -l
find design -name '*.md' | wc -l
git ls-tree -d --name-only HEAD packages
ls openspec/specs | wc -l
ls tests/scaffold/cat*
```

### What I observed

Developer-facing surface inventory, all TESTED:

| Surface | Count / location | Note |
| --- | --- | --- |
| Task targets | 69, from `task -l` | grouped by numbered area in `Taskfile.yml`, `--sort none` |
| Packages | 15 under `packages/` after my scaffold, 14 at HEAD | 12 Python, 2 TypeScript at HEAD |
| Docs pages | 44 markdown under `docs/` | plus a built `site/` tree and `docs/architecture.html` |
| Runbooks | 18 under `docs/runbooks/` | one per operable service or drill |
| ADRs | 7 under `docs/adr/` including the template | append-only per CLAUDE.md |
| Design docs | 24 under `design/` | platform, migration, delivery |
| OpenSpec specs | 51 under `openspec/specs/` | baseline written only by archiving |
| Scaffold gates | 11 files, `cat1` through `cat10` | ~~`cat4` and one other are shell scripts~~ **corrected (QA C-5): `cat2`, `cat4` and `cat7` are shell scripts (three, not two)** |
| Templates | `templates/connector/` (20 files, base plus an `direction/inbound/` overlay) and `templates/HANDOFF.md` | |
| Scaffolding commands | `task connector:new`, `task new-repo` | |
| Root contracts | `README.md` (22 KB), `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md`, `WORKFLOW.md` (38 KB) | |
| GitHub surfaces | `CODEOWNERS`, `PULL_REQUEST_TEMPLATE.md`, two issue templates, 6 workflows | |

The connector-relevant subset a newcomer must find: `docs/connectors/authoring.md` (421 lines),
`packages/pulse-core/src/pulse_core/connector/` (the kit: `rows.py`, `declare.py`, `consume.py`),
`openspec/specs/connector-kit/spec.md`, `openspec/specs/connectors/pulse-standard-connector-spec.md`,
`packages/billing-connector` (outbound reference), `packages/consent-ingress` (inbound reference),
`templates/connector/`, `scripts/connector_new.py`, `docs/runbooks/billing-connector.md`,
`packages/pulse-core/CHANGELOG.md`.

### Friction

Nothing here. The surface is discoverable from the repo root without external context.

### What a 10/10 looks like for this repo

The inventory above is already close to it. The remaining gap is that the surface is large enough
(69 targets, 44 doc pages, 51 specs) that a newcomer needs a stated entry point per role.
`docs/index.md` provides one for the connector role; there is no equivalent for an operator or a
spec author.

---

## Step 1. Getting started

### What I did

Every timing below was taken with nothing else of mine running: no parallel gate, no second clone,
no background job. Timings are wall clock to the second.

```bash
du -sh ~/.cache/uv                  # cache warmth, taken before the clone
/usr/bin/time -p git clone https://github.com/robford-brookai/pulse.git pulse
task install
task check
```

### What I observed

**Cache warmth, TESTED.** `~/.cache/uv` held **26 GB** before the clone. `node_modules/` did not
exist in the clone and `task check` ran `npm ci` itself. Every uv number below is a warm-cache
number and is not what a genuinely cold machine would see.

**Prerequisite check, TESTED.** Every tool the README's Prerequisites section names was already
installed on this machine:

```
uv         uv 0.12.8 (Homebrew 2026-08-31 aarch64-apple-darwin)
task       3.53.1
node       v26.8.1
docker     Docker version 29.7.2, build a7dcaa6
gh         gh version 2.100.0
openspec   1.7.0
openlore   2.1.7
java       openjdk 17.0.16
```

`.nvmrc` pins `22` and the README says "Node.js 22 (required for OpenSpec and Twenty)". The machine
ran Node 26.8.1 and the whole gate passed anyway. The pin is documentation, not enforcement
(TESTED: `task check` green on Node 26).

**Stage timings, TESTED.**

| Stage | Command | Elapsed |
| --- | --- | --- |
| Clone | `git clone https://github.com/robford-brookai/pulse.git pulse` | **2.35 s** (`/usr/bin/time -p`, real) |
| Install | `task install` | **3 s** |
| Gate | `task check` (rc=0) | **225 s** |
| **TTHW total** | clone to a green `task check` | ~~**230 s = 3 min 50 s**~~ **withdrawn (QA C-3)** |

**Correction (QA C-3).** This run's 230 s does not reproduce. An independent fresh clone at the
same sha, on the same machine, measured 163 s (`test` at 120.6 s against this report's 187 s),
matching the tracked ledger's 117-122 s range for `test`. This report's own journey table (below)
says "nothing else of mine running" for these timings; that claim and the 230 s figure cannot both
be right, and the number should not be quoted as a benchmark. Read TTHW as **163 s cold, about
140 s warm**.

Against the rubric's TTHW benchmarks, both this report's original figure and the corrected one land
in the **Competitive** tier (2-5 min); no tier conclusion changes.

**Per-target breakdown inside `task check`, TESTED**, read from the rows `scripts/devex/timing.py`
appended to `.planning/devex/loop.jsonl` during my run:

```
{"target": "lint",             "seconds": 1.498,   "rc": 0}
{"target": "typecheck",        "seconds": 26.81,   "rc": 0}
{"target": "test",             "seconds": 186.989, "rc": 0}
{"target": "twenty:validate",  "seconds": 0.201,   "rc": 0}
{"target": "twenty:test",      "seconds": 7.08,    "rc": 0}
{"target": "workflow:lint",    "seconds": 0.107,   "rc": 0}
{"target": "docs:lock-guard",  "seconds": 0.06,    "rc": 0}
{"target": "docs:build",       "seconds": 1.321,   "rc": 0}
```

`test` is 83 percent of the gate. Everything else together is 37 seconds.

A second `task check` later in the session, with `node_modules/` and the pytest caches warm, took
**48 s** with `test` at ~37 s. That second number was taken after other work in the same clone, so
it is context for iteration speed, not a benchmark.

**Points where I had to read a doc, guess, or hit an error:**

1. Read `README.md` lines 181-245 to learn the two commands. TESTED. No guessing: the section is
   titled "Running and verifying it" and the Quickstart is directly under Prerequisites.
2. Did not need `bootstrap.sh`, `CLAUDE.md`, or `CONTRIBUTING.md` to reach green. TESTED.
3. No error, no prompt, no credential, no `.env` file was needed for a green gate. TESTED.
4. `docs/index.md` gives the same two commands under "Getting started" and adds a one-line
   redirect for connector authors, so either front door works. TESTED.

**A green gate does not leave a clean tree, TESTED.** Immediately after `task check` returned 0,
in an otherwise untouched clone:

```
$ git status --short
 M .planning/devex/loop.jsonl
```

`scripts/devex/timing.py` appends a timing row to a tracked file on every gate run. The newcomer's
first `git status` after their first green build shows a modified file they did not touch and
cannot explain.

**No summary line, TESTED.** `task check` ends with the last sub-target's raw output. In my run
that was the Material for MkDocs vendor banner about MkDocs 2.0, printed in red:

```
 │  ⚠  Warning from the Material for MkDocs team
 │  × All plugins will stop working ...
INFO    -  Documentation built in 0.68 seconds
```

There is no "check passed, 8 targets, 225 s" line. A newcomer reads red text at the end of a green
run and has to check `$?` to know they succeeded.

### Friction

- The gate dirties a tracked file (`.planning/devex/loop.jsonl`) on every run.
- The gate's last line on success is a third-party deprecation warning in red.
- 225 s is a long first feedback loop, and 187 s of it is one `pytest` invocation with no
  progressive output beyond dots.
- The Node pin is stated in two places and enforced in none.

### What a 10/10 looks like for this repo

Clone to green in under 120 s; a one-line green summary naming the targets run and the elapsed
time; a gate that leaves `git status` empty; and the Node pin either enforced by the gate or
removed from the README so it stops being a claim nobody checks.

---

## Step 2. API/CLI/SDK ergonomics, connector-focused

### What I did

Walked the persona's path for a zendesk connector using only what the repo says, and ran every
command it names.

```bash
grep -n '^#\{1,4\} ' docs/connectors/authoring.md
sed -n '1,80p' packages/pulse-core/src/pulse_core/connector/__init__.py
uv run python scripts/connector_new.py --name zendesk-connector --direction inbound --print-registrations
task connector:new NAME=zendesk-connector DIRECTION=inbound
task install
uv run pytest packages/zendesk-connector/tests -q --no-cov
uv run pyright -p packages/zendesk-connector
task check
```

### What I observed

**Files and docs read before I could act, TESTED.** Four:

1. `README.md` "Connectors" section (lines 97-112), which names the kit path and links the guide.
2. `docs/connectors/authoring.md`, sections 1 through 5 and 7 (about 250 of its 421 lines).
3. `packages/pulse-core/src/pulse_core/connector/__init__.py` to see the exported surface.
4. The rendered `packages/zendesk-connector/README.md` after scaffolding.

**Concepts I had to learn before writing a line, TESTED**, all named in section 1 and 2 of the
guide: direction (inbound versus outbound), row source, page validation, pinned contract columns,
durable cursor, idempotency key derivation, response classification
(`committed | replayed | rejected | transient`), receipt counts, the one-credential rule, and the
socket block. Nine concepts. That is a real ramp, but the guide introduces them in the order the
build needs them rather than as a glossary.

**A scaffold command exists, TESTED.**

```
* connector:new: Scaffold a connector package (NAME, DIRECTION=outbound|inbound) from templates/connector/ and register it at every site
```

The dry run is honest about what it will write:

```bash
$ uv run python scripts/connector_new.py --name zendesk-connector --direction inbound --print-registrations
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -75,6 +75,7 @@
+    "packages/zendesk-connector",
...
--- a/Taskfile.yml
@@ -159,6 +159,7 @@
+      - uv run pyright -p packages/zendesk-connector
```

It ran in under a second and wrote nothing. That is a genuine escape hatch: an author can see the
whole registration diff before committing to it.

**The real scaffold, TESTED, 1 second.** It rendered 12 files and printed a Next line:

```
Rendered zendesk-connector (zendesk_connector), inbound, into .../packages/zendesk-connector:
  README.md, pyproject.toml, src/zendesk_connector/{__init__,config,py.typed,receipts,service}.py,
  tests/{conftest,factories,test_config,test_receipts,test_service}.py

Registered zendesk-connector at 2 site(s):
  Taskfile.yml
  pyproject.toml

Next: uv sync --all-packages
```

**All nine documented registration sites were actually applied, TESTED.** I checked each one:

```
pyproject.toml:78    "packages/zendesk-connector",              # site 1, workspace members
pyproject.toml:96    zendesk-connector = { workspace = true }   # site 2, uv.sources
pyproject.toml:214   "packages/zendesk-connector/tests/**" = ["S101"]   # the ruff per-file-ignore
Taskfile.yml:19      LINT_PATHS   ... packages/zendesk-connector          # site 3
Taskfile.yml:162     - uv run pyright -p packages/zendesk-connector      # site 4
Taskfile.yml:35      TESTED_PATHS ... packages/zendesk-connector/tests   # site 5
Taskfile.yml:48      COV_PATHS    ... --cov=packages/zendesk-connector/src  # site 6
Taskfile.yml:499     # zendesk-connector:image:    (commented stub)      # site 7
Taskfile.yml:509     # zendesk-connector:deploy:   (commented stub)      # site 8
```

Sites 7 and 8 land as commented stubs, which is exactly what section 7 of the guide says they may
do. The tool's own "2 site(s)" is a count of files touched, not of the nine sites, and reads as a
contradiction of the guide next to it.

**How far I got, TESTED.** From `task connector:new` to a green package: **25 seconds** total
(1 s scaffold, 8 s `task install`, 16 s pytest).

```
$ uv run pytest packages/zendesk-connector/tests -q --no-cov
........................................                                 [100%]
40 passed in 14.60s

$ uv run pyright -p packages/zendesk-connector
0 errors, 0 warnings, 0 informations
```

Forty passing tests and a clean pyright-strict pass, out of the box, before I wrote any zendesk
code. The rendered `service.py` is 324 lines with the kit loop already wired; the rendered README
names the four seams to replace (`CONTRACT_COLUMNS`, `SourceRow`, `build_row_source`,
`_declaration`).

**Correction (QA C-1).** ~~Then the documented happy path fails, TESTED.~~ It does not: run exactly
as the guide's section 3 describes, unstaged, `task check` returns rc=0, 3042 passed. The failure
below arrives one step later, at the connector author's **first commit** of the scaffolded package,
because the gate this section describes reads `git ls-files`, not the filesystem
(`_tracked_packages()` at `cat8_docs_consistency.py:705`). Section 3 of the guide says:

```bash
task connector:new NAME=my-connector
task install          # resolve the workspace with the new member
task check            # the rendered package ships one green test
```

I ran exactly that, unstaged, and it is green: rc=0, 3042 passed. Staging the new package
(`git add packages/zendesk-connector Taskfile.yml pyproject.toml`) and re-running `task check`
returned **rc=201**:

```
= 1 failed, 3041 passed, 30 skipped, 9 deselected, 8 xfailed, 11 warnings in 37.00s =
FAILED tests/scaffold/cat8_docs_consistency.py::test_readme_package_count_matches_the_tree
E       AssertionError: README claims 14 packages, tree has 15
E       assert 14 == 15
```

The scaffold registers the package at nine sites and does not update the one hand-maintained
sentence in `README.md` that a scaffold gate asserts against
(`README.md:117`, "Fourteen packages live under `packages/`. Twelve are Python").

**The obvious fix does not work either, TESTED.** I edited the sentence to "Fifteen packages live
under `packages/`. Thirteen are Python" and re-ran the gate:

```
E       assert None is not None
tests/scaffold/cat8_docs_consistency.py:733: AssertionError
```

Line 733 is `assert total_claimed is not None, f"unrecognized package count word: ..."`. The gate's
word map is a literal dict of only the words used so far:

```python
NUMBER_WORDS = {
    "twelve": 12, "fourteen": 14, "twenty": 20,
    "twenty-two": 22, "twenty-three": 23, "twenty-four": 24,
}
```

So a connector author adding the fifteenth package must edit a **scaffold gate** in
`tests/scaffold/` to make their scaffolded package pass CI. That is the last file in the repo a
connector author would expect to open, and nothing in `docs/connectors/authoring.md` mentions it.
(I reverted both edits; the audited repo is untouched.)

**Kit surface versus the spec and the reference, TESTED.**
`pulse_core.connector.__all__` exports ~~27~~ **28 (corrected, QA C-5)** names across three
modules. Cross-checking:

- `openspec/specs/connector-kit/spec.md` describes exactly those three areas (inbound read
  contract, declare pipeline, outbound consume loop) and carries a `## Deprecations` table
  (currently `_none yet_`).
- `tests/scaffold/cat10_devex.py::test_connector_kit_all_names_resolve` asserts every `__all__`
  name resolves, so the advertised surface cannot rot silently.
- The rendered inbound package imports only from `pulse_core.connector`, not from submodules,
  which is what the CHANGELOG names as the supported surface.

**`task` help text, TESTED.** All 69 descriptions are one line, name their required variables, and
state their cost. Examples from the actual output:

```
* connector:new:  Scaffold a connector package (NAME, DIRECTION=outbound|inbound) ...
* verify:         Full local gate — check plus drift and spec validation (needs CHANGE)
* demo:3:         Demo 3 ... the live kanban round trip against dev Twenty (needs dev credentials)
* twenty:deploy:  Replay the validated Twenty artifact against TARGET (dev|staging|prod; needs that target's credential)
```

Every target that needs credentials, Docker, Java, or a variable says so in its one-line
description. Naming is consistent `area:verb` (`twenty:*`, `demo:*`, `spec:*`, `lore:*`,
`ledger:*`). The default target is ordered by when you reach it rather than alphabetically, and
says so.

**Prior-art hint did not fire, TESTED.** The guide says `connector:new` names an existing
`packages/ocean/services/` directory whose name starts with NAME. `packages/ocean/services/` holds
16 connectors including `hubspot-connector`, `linear-connector`, `github-connector`, and
`zcc-connector`, but none starting with `zendesk`, so nothing printed. Correct behavior; worth
noting that the check is a prefix match, so a differently-named prior integration would be missed.

### Friction

- **Corrected (QA C-1).** ~~The documented three-command path ends red.~~ The documented
  three-command path is green (rc=0, 3042 passed). A connector author's **first commit** of the
  scaffolded package turns the gate red on a docs-consistency check, because that gate reads
  `git ls-files`, not the filesystem.
- Fixing it correctly requires editing `tests/scaffold/cat8_docs_consistency.py`.
- The rendered `packages/zendesk-connector/README.md` claims `TYPED_PATHS` was one of the sites
  applied. It was not, and the guide is explicit that a pyright-strict package never joins
  `TYPED_PATHS`. The rendered README contradicts the guide.
- The commented `zendesk-connector:image` stub references
  `packages/zendesk-connector/Dockerfile`, which the scaffold does not render. `billing-connector`
  has one; a scaffolded connector does not. The author who uncomments the stub hits a missing file.
- "Registered ... at 2 site(s)" next to a guide section titled "all nine sites" reads as a
  contradiction.

### What a 10/10 looks like for this repo

`task connector:new NAME=zendesk-connector DIRECTION=inbound && task install && task check` ends
green, with no follow-up edit anywhere in the repo. The package count sentence is generated or the
gate reads the number rather than a word. The scaffold renders a Dockerfile stub alongside the
commented deploy stanzas that reference it. The rendered README lists the sites that were actually
touched.

---

## Step 3. Error messages

I triggered thirteen realistic mistakes. Each is TESTED. "Problem / cause / fix" is scored against
the rubric's error-message empathy pattern.

**E1. Flag syntax instead of a go-task variable.**

```bash
$ task dispatch --change=zendesk
Usage: task [flags...] [task...]
Runs the specified task(s). Falls back to the "default" task ...
```

Problem: implied only. Cause: not stated. Fix: not stated. go-task dumps its own usage banner and
never says that this repo's targets take `CHANGE=<id>`. This is the single worst error surface I
hit, and `CLAUDE.md` documents the trap, which means it is known and recurring.

**E2. A CHANGE-taking target with no CHANGE.**

```bash
$ task verify
task: CHANGE is required, e.g. task verify CHANGE=<change-id>
task: Failed to run task "verify": task: precondition not met
```

Problem, cause and fix, with a copy-pasteable example. Best-in-class for this repo.

**E3. Scaffold with no NAME.**

```bash
$ task connector:new
task: Task "connector:new" cancelled because it is missing required variables: NAME
```

Problem and cause. No example of the correct invocation, unlike E2.

**E4. Missing environment for a connector.**

```
ConfigError: zendesk-connector configuration is unusable:
  - ZENDESK_CONNECTOR_SOURCE_TABLE is unset — the fully qualified relation to page
  - ZENDESK_CONNECTOR_LEDGER_BASE_URL is unset — the command-API base URL
  - ZENDESK_CONNECTOR_TOKEN is unset — this connector's ledger writer token
```

Every missing variable at once, each with what it is for. Problem, cause and fix. No secret value
is read or echoed. This is exactly what section 4 of the guide promises, and the scaffold ships it
working rather than as advice.

**E5. Invalid value rather than missing.**

```
ConfigError: zendesk-connector configuration is unusable:
  - ZENDESK_CONNECTOR_STALE_AFTER_SECONDS='banana' is not an integer — whole seconds
```

Names the variable, the offending value, the expected type and the unit. Problem, cause, fix.

**E6. A failing lint gate.**

```
$ task lint     # after adding a badly formatted file
unformatted: File would be reformatted
 --> packages/zendesk-connector/src/zendesk_connector/_probe.py:2:1
1 | import os
  - x=1
2 + x = 1
1 file would be reformatted, 725 files already formatted
task: Failed to run task "lint": exit status 1
```

Problem and cause with an exact diff. **No fix.** `task fmt` exists and applies this automatically,
and neither ruff nor the task wrapper mentions it.

**E7. Running a gate from the wrong directory.**

```bash
$ cd packages/zendesk-connector && task lint
... All checks passed!
$ cd packages/zendesk-connector && uv run pytest tests -q
40 passed in 0.83s
```

No error at all. go-task walks up to the Taskfile and uv resolves the workspace root, so a gate run
from a package directory just works. This is a non-obvious win worth keeping.

**E8. A drift check on a fresh clone.**

```bash
$ task lore:drift
[error] No openlore configuration found. Run "openlore init" first.
task: Failed to run task "lore:drift": exit status 1
```

Problem, cause and fix, but the fix names the raw tool (`openlore init`) rather than this repo's
own target (`task lore:init`), which is what section 8 item 6 of the authoring guide tells the
author to run.

**E9. A mistyped change id.**

```bash
$ task spec:validate CHANGE=zendesk
Unknown item 'zendesk'. Did you mean: command-api, ledger-read, month-open, connector-kit, event-delivery?
```

Problem, cause and a suggestion list. Third-party (openspec), but the newcomer does not care whose
error it is.

**E10. Dispatching a change that does not exist.**

```bash
$ task dispatch CHANGE=zendesk-connector
Error: openspec/changes/zendesk-connector/tasks.md not found
task: Failed to run task "dispatch": exit status 1
```

Problem and cause with an exact path. No fix and no list of the changes that do exist, which
`task spec:status` could supply.

**E11. An invalid DIRECTION.**

```
connector_new.py: error: argument --direction: invalid choice: 'sideways' (choose from outbound, inbound)
```

Problem, cause, and the valid set. argparse doing its job.

**E12. Scaffolding a name that already exists.**

```
error: destination already exists: .../packages/zendesk-connector (pass --force to overwrite)
```

Problem, cause and fix in one line, and it refuses to clobber by default.

**E13. The failing scaffold gate from Step 2.**

```
E       AssertionError: README claims 14 packages, tree has 15
```

Problem and cause, both numbers named. No fix: it does not say which sentence in `README.md`, nor
that `NUMBER_WORDS` in the gate itself also needs the new word. A newcomer has to read the gate's
source to get unstuck, and then the second failure (`assert None is not None`) is worse than the
first.

**Tally.** Problem + cause + fix: E2, E4, E5, E8 (partly), E9, E11, E12. Problem + cause only: E3,
E6, E10, E13. Effectively nothing useful: E1.

### Friction

- E1 is a known trap with a documented workaround in `CLAUDE.md` and no guardrail in the tooling.
- E6 and E13 are the two errors a connector author is most likely to meet, and neither names its
  fix.
- E13's second-order failure sends the author into `tests/scaffold/`.

### What a 10/10 looks like for this repo

Every failing target ends with the one command that fixes it: lint failure prints `run: task fmt`;
the package-count gate prints `README.md:117 says "Fourteen"; the tree has 15`; a flag-style
invocation is caught by a wrapper that prints `this repo's targets take CHANGE=<id>, not --change`.
`task lore:drift` names `task lore:init`, not `openlore init`.

---

## Step 4. Documentation

### What I did

```bash
grep -rl "authoring" mkdocs.yml README.md AGENTS.md CONTRIBUTING.md
grep -n "connector" mkdocs.yml
sed -n '1,40p' docs/index.md
grep -n '^#\{1,4\} ' docs/connectors/authoring.md
task docs:build            # mkdocs build -s, inside task check
ls openspec/changes | grep -v archive
```

### What I observed

**Findability, TESTED.** The connector guide is reachable from four independent entry points:
`README.md` (the "Connectors" section links it in prose), `CONTRIBUTING.md`'s owner section,
`docs/index.md`'s "Getting started" (an explicit redirect: "Building a connector? ... Start at
Authoring a connector instead of reading this site end to end"), and `mkdocs.yml:37` nav
(`Authoring: connectors/authoring.md`). A grep for the obvious phrase lands on it from any of them.

**Currency, TESTED.** `mkdocs build -s` passes with zero warnings of its own. The only red output is
the Material for MkDocs vendor banner about MkDocs 2.0, which is not this repo's content.
`docs:lock-guard` additionally fails if the lock drifted or contains an mkdocs-successor fork.
`tests/scaffold/cat10_devex.py::test_every_docs_page_is_in_nav` means an orphan page cannot land.

Two stale claims, both TESTED:

1. `README.md:31` says "`devex-eight-4` is the change currently in flight." Two changes are in
   flight: `ls openspec/changes` returns `devex-eight-4` and `reconciliation-sweeps`. The repo's own
   `CLAUDE.md` states that two changes can be in flight at once, so the README's singular is wrong
   by the repo's own rule.
2. `README.md:117`'s package count, covered in Step 2.

**The persona's questions, in order, TESTED.** `docs/connectors/authoring.md` answers all eight, in
the asked order, one section each:

| Persona question | Section | Answered |
| --- | --- | --- |
| What is a connector here | 1. What a connector is here | Yes |
| What do I import | 2. What to import | Yes, with the kit's exported names |
| How do I scaffold | 3. How to scaffold, plus "Which direction" | Yes, with the command and the rendered tree |
| How do I configure | 4. How to configure | Yes, with the one-credential rule and the collect-all-problems rule |
| How do I test offline | 5. How to test offline | Yes, socket block plus fixtures |
| How do I register the package | 7. How to register the package — all nine sites | Yes, per site |
| How do I ship it | 8. How to ship it | Yes, mapped onto WORKFLOW.md |
| Who do I ask | 9. Who to ask | Yes, named owner plus an eight-row lookup table |

Section 6 ("What is enforced, before you get to CI") and section 10 ("How the kit changes") sit
between them, and the PHI section closes. This is the strongest single document in the repo: the
question order matches the build order, and every answer names a file, a command, or a person.

Section 9's lookup table is unusually good, because it routes by question rather than by artifact:

```
| Why did CI fail on something local passed? | docs/ci-lessons.md |
| What changed in the kit since I last synced? | packages/pulse-core/CHANGELOG.md |
```

### Friction

- **Corrected (QA C-1).** ~~The guide tells the truth about everything except the outcome of its
  own step 3 (`task check` green), which is the claim a newcomer tests first.~~ Step 3's claim is
  true: `task check` is green as the guide describes. The gate turns red one step later, at the
  connector author's first commit of the scaffolded package.
- Two hand-maintained counts in `README.md` are asserted by gates, so prose that drifts turns into
  a red build rather than a stale sentence. The gate for one of them exists; the in-flight-change
  sentence has no gate and is currently wrong.

### What a 10/10 looks like for this repo

The authoring guide as it stands, plus a note that the first commit of a scaffolded package needs
a `README.md` package-count edit, plus a short "your first hour" strip at the top: the four
commands, the expected wall-clock for each, and what green looks like.
Counted prose in `README.md` is generated rather than asserted.

---

## Step 5. Upgrade path

### What I did

```bash
cat .ade-template-version
task template:diff
head -40 packages/pulse-core/CHANGELOG.md
grep -n "## Deprecations" -A 12 openspec/specs/connector-kit/spec.md
ls docs/adr/ ; ls openspec/changes/archive | wc -l
```

### What I observed

**Template sync, TESTED.** `.ade-template-version` holds
`a1de595b8591691a624d67d60efaa20d73641967`. `task template:diff` fetches the template and reports:

```
Template changes a1de595b..775551bc (infrastructure paths only):
Rewriting package name repo_ade -> pkg_pulse.

 Taskfile.yml                    |   60 +
 bootstrap.sh                    |   11
 scripts/checkoff_tasks.py       |  168 +++
 scripts/collect_handoffs.py     |  103 ++
 scripts/dispatch_tasks.py       |  551 +++++++++++
 scripts/linear_sync.py          |  534 +++++++++++
 scripts/workflow.py             |  437 +++++++++
 tests/scaffold/cat5_glue_logic.py | 1011 +++++++++++++++++
 ... (15 paths)
```

The mechanism works and states its own scope ("infrastructure paths only", never README/CLAUDE/src).
The repo is a substantial distance behind its template, which the command surfaces honestly rather
than hiding. Whether that drift matters is Task B's call.

**Kit changelog, TESTED.** `packages/pulse-core/CHANGELOG.md` exists, in Keep a Changelog style, and
states its own contract in the header: "Each entry that touches `pulse_core.connector` carries a
**Connector authors** line naming the concrete effect on a connector build against the kit — read
it before `uv sync` pulls in a new version." The `0.1.0` baseline entry documents all three kit
modules and states which import path is the supported surface.

The `[Unreleased]` section currently contains exactly one entry: the CHANGELOG itself. The file
openly records why it starts where it does ("This file starts with the devex-eight-2 audit ...
'Upgrade Path' finding: no CHANGELOG, no deprecation machinery"). So the machinery exists and has
not yet been exercised by a real kit change. TESTED for existence, INFERRED for whether it holds
under pressure: no kit change has landed since it was created.

**Deprecation policy, TESTED.** `openspec/specs/connector-kit/spec.md:140` carries a normative
policy: a retiring name stays exported and working for one release, raises `DeprecationWarning`
naming its replacement, is announced in the CHANGELOG in the PR that starts the grace window, and is
listed in a table until removal. The table reads `| _none yet_ | | | |`. Removing a name must delete
its row in the same PR. `tests/scaffold/cat10_devex.py::test_kit_has_changelog_and_deprecation_policy`
gates the existence of both.

`packages/pulse-core/pyproject.toml:3` is `version = "0.1.0"`. There is no release tagging or
version bump visible for the kit, so "one release" is currently an unbound unit. INFERRED.

**How a connector author absorbs a kit change, TESTED as documented, INFERRED as practiced.**
Section 10 of the guide is explicit and honest: "The kit reaches every connector on the next
`uv sync` — nothing prompts you to go read anything." It names the two places carrying the signal
(CHANGELOG, deprecation table) and says checking both is part of pulling an upgrade. It closes with
a genuine escape hatch: if a release drops a name without either naming it first, that is a kit
defect and there is an issue template for it (`.github/ISSUE_TEMPLATE/connector-kit-defect.yml`).

The gap it admits is real. A workspace connector picks up kit changes silently at `uv sync` time,
with no version constraint to pin against (`pulse-core = { workspace = true }`), no deprecation
warning yet emitted by any code, and no automated check that the author read anything.

**ADR discipline, TESTED.** Seven ADRs, `ADR-0000` a template, `0001` through `0006` real, numbered
sequentially. `CLAUDE.md` states the rule (append-only; a superseded decision gets a status flip and
a new ADR). None of the six is currently superseded, so the flip mechanism is unexercised. INFERRED.

**Spec archiving, TESTED.** 24 archived changes under `openspec/changes/archive/`, 51 accumulated
specs under `openspec/specs/`, and `CLAUDE.md` states that the baseline is written only by
archiving. `task spec:archive` and `task verify CHANGE=<id>` are the mechanisms.

### Friction

- The kit ships to connectors on `uv sync` with nothing enforcing that the author read the
  CHANGELOG. This is documented, not solved.
- "One release" is the unit of the grace window, and the kit has no releases.
- The template is meaningfully behind and nothing surfaces that except running `task template:diff`
  by hand.

### What a 10/10 looks like for this repo

A kit change that removes or renames a name makes every connector's `task check` print the
CHANGELOG line for that change once. The deprecation table has been exercised at least once end to
end. `task template:diff` runs as an advisory line inside some routine target so drift is seen
rather than sought.

---

## Step 6. Developer environment

### What I did

```bash
for t in uv task node docker gh openspec openlore java; do command -v $t && $t --version; done
grep -n 'requires-python' pyproject.toml packages/zendesk-connector/pyproject.toml
cat .python-version .nvmrc .editorconfig ; ls .vscode/ ; cat .vscode/extensions.json
ls .git/hooks/pre-commit
git add packages/zendesk-connector Taskfile.yml pyproject.toml && git commit -m "..."
cat .env.example
```

### What I observed

**Toolchain requirements and pins, TESTED.**

| Pin | Value | Enforced? |
| --- | --- | --- |
| `.python-version` | `3.14` | Yes, uv honors it; the gate ran on 3.14.3 |
| `pyproject.toml` `requires-python` | `>=3.10,<4.0` (root and the scaffolded package alike) | Yes, by uv resolution |
| `.nvmrc` | `22` | No. The gate passed on Node 26.8.1 |
| Docker, Java, gh, openspec, openlore | named in README Prerequisites | Not needed for `task check`, correctly stated as such |

The README is explicit that `task check` needs no Java, and names the one target that does
(`task synthea:regen`). That is the right shape: prerequisites separated by which of them the
default path actually requires.

**Editor support, TESTED.** `.vscode/extensions.json` recommends ruff, python, mypy-type-checker,
editorconfig and yaml. `.editorconfig` sets charset, line endings, final newline, trailing
whitespace, 2-space default and 4-space Python with a 120 column limit. `cat10_devex.py::test_editor_and_runtime_pins_exist`
gates their presence. No settings.json, so nothing pins the interpreter path to `.venv` for a
newcomer's editor; INFERRED that a newcomer would have to select the interpreter by hand.

**Pre-commit hooks after the documented install, TESTED.** `task install` ends with
`uv run pre-commit install` and prints `pre-commit installed at .git/hooks/pre-commit`. The hook
file exists after the documented two commands, with no extra step. I then made a real commit of the
scaffolded connector in the fresh clone:

```
check for merge conflicts................................................Passed
check toml...............................................................Passed
check yaml...............................................................Passed
fix end of files.........................................................Passed
trim trailing whitespace.................................................Passed
ruff check...............................................................Passed
ruff format..............................................................Passed
openlore drift.......................................(no files to check)Skipped
[detached HEAD d5114a9] test: scaffolded zendesk connector
 14 files changed, 1221 insertions(+), 3 deletions(-)
```

The first commit in a fresh clone succeeds. `openlore drift` skipped because no spec files were
staged, which is why the missing `.openlore/` (Step 3, E8) did not block the commit. A connector
author whose change does touch a spec file would hit it.

**Local versus CI parity, TESTED.** `.github/workflows/main.yml`'s quality job runs exactly
`task check`, and `tests/scaffold/cat4_ci_contract.py` gates that every `run:` command resolves to a
defined Taskfile target or a tool some step installs. The claim "green locally means green in CI" is
structurally enforced rather than asserted. My local `task check` was green at HEAD and red only for
the change I had made, which is the behavior the contract promises.

**`.env.example`, TESTED.** Two variables, neither of them a connector's:

```
ORCA_WORKTREES_DIR=
# ANTHROPIC_API_KEY=
```

A connector author who runs `Config.from_env({})` learns they need
`ZENDESK_CONNECTOR_SOURCE_TABLE`, `ZENDESK_CONNECTOR_LEDGER_BASE_URL` and
`ZENDESK_CONNECTOR_TOKEN`. None of that shape appears in `.env.example`, and there is no
`.env.example` fragment rendered into the scaffolded package. The error message is the only place
the variable set is written down for a running connector.

### Friction

- `.nvmrc` and the README both claim Node 22 and nothing checks it.
- `.env.example` does not carry the variable shape any connector needs, so the runtime error is the
  documentation.
- No `.vscode/settings.json` pointing at `.venv`.

### What a 10/10 looks like for this repo

`task install` fails fast on a wrong Node major with the pinned version named. The scaffold appends
its three variables to `.env.example` (names only, no values) as part of its nine-site registration.
`.vscode/settings.json` selects the workspace interpreter so a newcomer's editor resolves imports on
first open.

---

## Step 7. Community and ecosystem, internal-repo interpretation

The rubric's internal-repo interpretation is the standard applied here: a named owner per area in
`CODEOWNERS`, a channel or person named in `README.md`, issue and PR templates, and evidence that
someone other than the owner has landed a connector.

### What I did

```bash
cat CONTRIBUTING.md ; cat .github/CODEOWNERS ; find .github -type f
git log --format='%an' -- packages/billing-connector packages/consent-ingress packages/verdict-relay | sort | uniq -c
grep -rlo "DNA-[0-9]" openspec/changes/archive/*/tasks.md | wc -l ; ls openspec/changes/archive | wc -l
ls work_orders handoffs
```

### What I observed

**A named owner, TESTED.**

```
# Pulse code owners
* @robford-brookai

# The connector kit every connector depends on
packages/pulse-core/src/pulse_core/connector/ @robford-brookai
```

Two rules, one owner. The kit gets its own line, which signals that it is a reviewed boundary, but
it names the same person as the catch-all, so it does not distribute review.

**A person to ask, TESTED, corrected (QA C-6).** ~~Met via `CONTRIBUTING.md` and
`docs/connectors/authoring.md`.~~ Both files name the owner: "**Owner: Rob Ford**
([@robford-brookai]) — ask directly on Slack; there is no dedicated channel yet." But the rubric's
internal-repo interpretation asks for a person or channel named in `README.md` specifically, and
`README.md` names neither. This criterion is **not met**: the repo's own
`cat10_devex.py::test_repo_names_an_owner_and_a_place_to_ask` gates the `CONTRIBUTING.md`/
`authoring.md` wording, not `README.md`, and is an open finding
(`test_readme_names_the_owner_and_the_channel_above_the_fold`). The absence of a channel is stated
rather than left to be discovered, which is the honest form, but it is stated in the wrong file for
this criterion.

**Templates, TESTED.** `.github/PULL_REQUEST_TEMPLATE.md` (gated by
`test_pr_template_names_task_check`), and two issue templates that map onto real workflows:
`attended-run.yml` (for the destructive and prod-touching work `WORKFLOW.md` keeps out of
worktrees) and `connector-kit-defect.yml` (the escape hatch section 10 of the guide points at).
Both are unusually specific to how this repo actually works.

**Someone other than the owner landing a connector, TESTED and absent.**

```bash
$ git log --format='%an' -- packages/billing-connector packages/consent-ingress packages/verdict-relay | sort | uniq -c
  43 Rob Ford
```

Forty-three commits across the three connector packages, one author. The rubric says this cannot be
manufactured, and it has not been: there is no evidence any human other than the owner has landed a
connector on this kit. This is a property of a single-maintainer repo, not a defect in its docs.

**Handoffs and work orders, TESTED.** `handoffs/` holds 24 change directories and `work_orders/`
holds 8, both the tracked receipt trees `WORKFLOW.md` and `CLAUDE.md` describe. `templates/HANDOFF.md`
is the per-worktree contract `AGENTS.md` binds agents to.

**Linear linkage, TESTED.** 16 of the 24 archived changes carry `DNA-nnn` id tokens in their
`tasks.md`. Neither in-flight change (`devex-eight-4`, `reconciliation-sweeps`) carries any yet.
`task linear:sync CHANGE=<id> APPLY=1` is the mechanism that writes them, and
`task workflow:lint:linear` validates team, project and status against the live API. The linkage is
real and mechanized, applied to about two thirds of the archive.

### Friction

- One owner for everything means the kit boundary has no second reviewer.
- No channel, which the docs state plainly rather than hide.
- No external-contributor evidence to point at.

### What a 10/10 looks like for this repo

A second named owner on `packages/pulse-core/src/pulse_core/connector/` so kit changes get review
from someone who is not the author. A named channel in `README.md` above the fold. One connector in
the tree whose commits carry a second author's name.

---

## Step 8. DX measurement

Per the audit protocol I read the repo's own DX machinery here as a newcomer who found it would,
and did not use it to steer Steps 0 through 7. Those steps were complete before I ran anything in
this section.

### What I did

```bash
ls scripts/devex/
grep -n "def test_" tests/scaffold/cat10_devex.py
task devex:check
python3 -c "...count kinds and dates in .planning/devex/loop.jsonl..."
```

### What I observed

**The repo does measure its own DX, TESTED.** Three mechanisms:

1. **Gate durations.** `scripts/devex/timing.py` wraps every sub-target inside `task check` and
   appends `{"date", "kind": "timing", "target", "seconds", "rc"}` to
   `.planning/devex/loop.jsonl`. This is how I obtained the per-target breakdown in Step 1 without
   instrumenting anything myself.
2. **A findings gate.** `tests/scaffold/cat10_devex.py` is a scaffold gate carrying ~~roughly 30~~
   **58 (corrected, QA C-5)** named `def test_` tests that assert DX properties as behavior rather
   than as prose. A sample of what it holds the
   repo to: `test_connector_authoring_guide_exists_and_is_in_nav`,
   `test_connector_kit_all_names_resolve`,
   `test_billing_config_reports_all_missing_variables_at_once`,
   `test_billing_config_names_variable_on_invalid_value`,
   `test_install_installs_pre_commit_hooks`, `test_readme_states_prerequisites`,
   `test_repo_names_an_owner_and_a_place_to_ask`, `test_issue_and_pr_templates_exist`,
   `test_kit_has_changelog_and_deprecation_policy`, `test_editor_and_runtime_pins_exist`,
   `test_verify_without_change_fails_fast`, `test_connector_new_supports_inbound_direction`,
   `test_docs_index_is_a_front_door`. Several of these are the mechanized form of findings from
   earlier audits, which means a fixed finding cannot silently regress.
3. **An open-findings metric.** `task devex:check` runs `scripts/devex/check.py`, which emits
   `METRIC devex_open_findings=<n>` and writes a per-run JSON. On my run it printed
   `METRIC devex_open_findings=7`.

**Ledger contents, TESTED, corrected (QA C-5).** ~~`.planning/devex/loop.jsonl` holds 89 records
... 56 `timing`~~. The tracked file holds **81 records, 48 `timing`**, 28 `pr`, 4 `audit`,
1 `reopen`, across four dates (2026-09-02, 09-04, 09-05, 09-08). This report's original 89/56 count
was taken in my own clone after this run's own `task check` had already appended its 8 `timing`
rows to the tracked file (81 + 8 = 89, 48 + 8 = 56); it should have been read as a property of my
run, not of the repo. So the repo tracks gate durations, PRs per change, audit runs, and reopened
findings, over a six-day window.

**What is not measured, TESTED by absence.** Nothing in `loop.jsonl` records onboarding time. There
are no clone, install, or TTHW records: `timing` rows exist only for sub-targets of `task check`,
which starts after install. The end-to-end 230 s number in Step 1 is one I had to measure by hand.
Drift is checked (`openlore drift` as a pre-commit hook and inside `task verify`) but not recorded
into the ledger as a metric.

**Corroboration.** `task devex:check` printed seven open finding names. Two of them
(`test_a_green_gate_leaves_the_tree_clean_and_summarises_itself`,
`test_env_example_carries_the_variables_the_tooling_demands`) describe conditions I had already
observed independently in Steps 1 and 6 before running this command. I am recording that as
corroboration of my evidence, not as its source. I did not read `.planning/devex/*-check.json` or
any prior audit report.

### Friction

- The two numbers a newcomer feels most (clone-to-green, and time from scaffold to a green gate)
  are the two the ledger does not carry.
- The measurement machinery writes to a tracked file during the gate, which is itself the Step 1
  clean-tree friction.

### What a 10/10 looks like for this repo

A `timing` row for the whole onboarding arc, written by a target that measures clone, install and
gate as one number, so TTHW is a tracked series rather than something an auditor recreates by hand.
The ledger written to an ignored path, or committed deliberately by a separate target, so a green
gate leaves a clean tree.

---

## Connector author journey

Elapsed is cumulative wall clock from `git clone`, for the tested rows. Every timing was taken with
nothing else of mine running. Reading time is my own and is marked as an estimate.

| Elapsed | Action | Outcome | Stuck points | Tag |
| --- | --- | --- | --- | --- |
| 0:00 | `git clone https://github.com/robford-brookai/pulse.git` | 2.35 s, succeeded | none | TESTED |
| 0:02 | Read `README.md` Prerequisites and Quickstart (lines 181-245) | Two commands identified | none | TESTED |
| ~3:00 | Verify prerequisites installed (uv, task, node, docker, gh, openspec, openlore) | All present; Node is 26 against a `22` pin, nothing complains | Pin is unenforced | TESTED |
| 3:05 | `task install` | 3 s, rc=0, pre-commit hook installed | Warm 26 GB uv cache; a cold machine will be slower | TESTED |
| 6:50 | `task check` | 225 s, rc=0. ~~**TTHW = 230 s from clone**~~ **withdrawn (QA C-3), see Step 1** | `test` is 187 s of it; last line on success is a red vendor warning; `git status` now shows a modified `.planning/devex/loop.jsonl` | TESTED |
| ~7:00 | Read `README.md` "Connectors" section, follow the link | Lands on `docs/connectors/authoring.md` | none | TESTED |
| ~25:00 | Read `docs/connectors/authoring.md` sections 1-5 and 7 (about 250 lines), plus the kit's `__init__.py` | Nine concepts learned; direction chosen (inbound: zendesk is a source to page) | Reading time is the single largest cost in this journey | TESTED (reading time estimated) |
| 25:05 | `uv run python scripts/connector_new.py --name zendesk-connector --direction inbound --print-registrations` | Full registration diff shown, nothing written | none; this is a real escape hatch | TESTED |
| 25:06 | `task connector:new NAME=zendesk-connector DIRECTION=inbound` | 1 s. 12 files rendered, all nine sites registered | Output says "2 site(s)" where the guide says nine; a Dockerfile the deploy stub references is not rendered | TESTED |
| 25:14 | `task install` | 8 s, workspace resolved with the new member | none | TESTED |
| 25:30 | `uv run pytest packages/zendesk-connector/tests -q` | 40 passed in 14.6 s | none | TESTED |
| 25:35 | `uv run pyright -p packages/zendesk-connector` | 0 errors, strict mode | none | TESTED |
| 26:23 | `task check`, as the guide's step 3 instructs, package unstaged | **rc=0, GREEN.** 3042 passed | none | TESTED, corrected (QA C-1) |
| 26:30 | `git add packages/zendesk-connector Taskfile.yml pyproject.toml`, re-run `task check` | **rc=201, RED (moved here, QA C-1).** `cat8_docs_consistency.py::test_readme_package_count_matches_the_tree`: "README claims 14 packages, tree has 15" | The gate reads `git ls-files`, so the first commit of the scaffolded package turns it red, not the unstaged run | TESTED |
| 26:40 | Edit `README.md:117` to "Fifteen ... Thirteen", re-run the gate | **Still red.** `assert None is not None`. `NUMBER_WORDS` in the gate has no "fifteen" or "thirteen" | Fix requires editing `tests/scaffold/cat8_docs_consistency.py`; the guide never mentions it | TESTED |
| ~27:00 | `git commit` the scaffolded package in the fresh clone | Succeeded. ~~9 hooks passed~~ **corrected (QA C-9): 8 Passed, 3 Skipped**, `openlore drift` skipped (no spec files staged) | A change that stages a spec file would hit the missing `.openlore/`, fixed by `task lore:init` | TESTED |
| n/a | Write `CONTRACT_COLUMNS`, `SourceRow`, `build_row_source` and `_declaration` for the real Zendesk API | Not performed | The four seams are named in the rendered README and in section 3; the shape is clear | INFERRED |
| n/a | Configure the three environment variables for a real run | Not performed | The variable set exists only in `config.py` and the runtime error; `.env.example` carries none of it | INFERRED |
| n/a | Register as a producer in `docs/contracts/publishes.md` and write `docs/runbooks/zendesk-connector.md` | Not performed | Section 8 names both, with `billing-connector` as the model | INFERRED |
| n/a | Open an OpenSpec change, dispatch, ship through `WORKFLOW.md` | Not performed | Section 8 maps it step by step | INFERRED |
| n/a | Uncomment the `zendesk-connector:image` stanza and build the image | Not performed | Would fail: `packages/zendesk-connector/Dockerfile` does not exist | INFERRED |

**Headline numbers, TESTED, corrected (QA C-1, C-3).** Clone to a green gate:
~~230 s (3 min 50 s)~~ **withdrawn — see the Step 1 correction; read 163 s cold, ~140 s warm**.
Scaffold command to a green package: **25 s**. Scaffold command to a green *repo gate*: **reached,
unstaged (rc=0, 3042 passed)**; the gate turns red one step later, at the first commit of the
scaffolded package, and staying green from there requires editing a scaffold gate's source.

---

## Top 10 friction points

Ordered by impact on a connector author specifically.

1. **Corrected (QA C-1). A connector author's first commit of the scaffolded package turns the
   gate red**, not the documented three-command path itself: `task connector:new` → `task install`
   → `task check` is green (rc=0, 3042 passed) unstaged; `git add`-ing the package and re-running
   `task check` returns rc=201 on `test_readme_package_count_matches_the_tree`. The correct fix is
   inside `tests/scaffold/cat8_docs_consistency.py`. TESTED.
2. **The obvious fix for that failure also fails**, because `NUMBER_WORDS` in
   `tests/scaffold/cat8_docs_consistency.py` has no word for the new count. A connector author's
   second troubleshooting step lands them inside a scaffold gate. TESTED.
3. **A lint failure never names `task fmt`.** The most frequent failure in the loop, and the
   one-command fix exists and is unmentioned by the error. TESTED.
4. **A green gate leaves a dirty tree.** `.planning/devex/loop.jsonl` is modified by every
   `task check`, so the newcomer's first `git status` after their first green build is confusing.
   TESTED.
5. **`.env.example` carries none of the variables a connector needs.** The runtime `ConfigError` is
   the only place the required variable set is written down. TESTED.
6. **Flag-style invocation produces go-task's usage banner and nothing else.** `task dispatch
   --change=x` never says the repo's targets take `CHANGE=<id>`. Known and documented in
   `CLAUDE.md`, unguarded in the tooling. TESTED.
7. **The rendered package README contradicts the guide**, claiming `TYPED_PATHS` was among the sites
   applied when a pyright-strict package never joins it. The first file a new author reads is wrong
   about what just happened. TESTED.
8. **The deploy stub references a Dockerfile the scaffold does not render.**
   `packages/zendesk-connector/Dockerfile` is named by the commented `:image` stanza and does not
   exist; `billing-connector` has one. TESTED.
9. **The kit reaches every connector silently on `uv sync`.** The guide states this openly, and the
   CHANGELOG plus deprecation table are the only signal. No version pin, no emitted warning, no
   check that anyone read anything. The machinery is new and has not been exercised by a real kit
   change. TESTED for the mechanism, INFERRED for its behavior under a real change.
10. **`task check` gives no green summary and 187 of its 225 seconds are one silent pytest run.**
    Success ends with a red third-party MkDocs banner. TESTED.

Two further items just below the line: `.nvmrc`'s Node 22 pin is unenforced (the whole gate passed
on Node 26), and `README.md:31` says one change is in flight while two are.

---

## Method notes and limits

**What I ran.** Every command quoted in this report was executed. Timings in Step 1 and the journey
table were taken in the fresh clone at
`/private/tmp/claude-502/.../scratchpad/devex-audit-2026-09-08/pulse`, pinned to
`f851ae0bd036c0f067514b4c57b10df7e956b669`, with nothing else of mine running.

**Cache warmth.** `~/.cache/uv` held 26 GB before the clone, so `task install`'s 3 s and the
resolution parts of `task check` are warm-cache numbers. `node_modules/` was absent and `npm ci` ran
inside the 225 s gate. A genuinely cold machine would be slower; how much is not measured here.

**Contended numbers.** One number in this report was taken under contention: the second `task check`
(48 s) ran after other work in the same clone, with pytest and node caches warm. It is quoted only
as context for iteration speed, and is flagged at the point of use. No benchmark in this report
depends on it.

**Read-only discipline.** No tracked file in
`/Users/Rob.Ford/Repos/robford-brookai/pulse` was modified. The only file I wrote there is this
report. All scaffolding, edits, probes and the one test commit happened in the throwaway clone, and
the two edits I made there (`README.md`, a probe file) were reverted immediately after measurement.

**Blindness.** I read no file matching `.planning/reports/*devex*` and no
`.planning/devex/*-check.json`. Steps 0 through 7 were complete before I opened anything under
`scripts/devex/`, `tests/scaffold/cat10_devex.py`, or `.planning/devex/loop.jsonl`, all of which the
protocol permits for Step 8. Running `task devex:check` in Step 8 printed the names of seven open
findings; two of them describe conditions I had already recorded independently in Steps 1 and 6. I
have marked that as corroboration and have not used it to add, remove, or reorder any finding.

**Coordinator note.** Main moved by one merge (#430) after dispatch. Both the repo under audit and
my clone are pinned to the audited sha; #430's content is not in scope.

**What I did not do.** I did not write the Zendesk-specific declare logic, configure a real
credential, build a container image, or ship a change through `WORKFLOW.md`. Those rows in the
journey table are tagged INFERRED. I did not run `task test:all`, the demos, or any live target: the
demos need Docker or dev credentials and are excluded from `task check` by design. No live network
call to a production system was made, and no PHI appears in this report or in anything I ran.

**Not in scope for this task.** No numeric score appears here. Scoring against the rubric is Task
B's job, and the boomerang comparison against prior audit runs is Task C's.
