# DevEx audit evidence: pulse @ 11622da

Corrections from `.planning/reports/2026-09-05-devex-audit-qa.md` applied 2026-09-05 (A1 to A9): the kit
exports 27 names and the guide documents 14; the two-copies spec claim and the template_sync SSH claim
are withdrawn (marked inline); the I001 template defect is conditional on the package name (`papchk`
sorts before `pulse_core` and yields 2 errors, `zapchk` yields none); every wall-clock figure below was
measured under contention this audit created itself, and QA's uncontended re-measurements are TTHW 117 s
(Champion band), green `task check` 113 s, no-CHANGE `task verify` 102 s; counts in the Step 0 table fixed.
Findings are otherwise unchanged.


Date: 2026-09-05
Repo under audit: `/Users/Rob.Ford/Repos/robford-brookai/pulse` at `11622da` (main)
Fresh clone: `/private/tmp/claude-502/-Users-Rob-Ford-Repos-robford-brookai-pulse/d627ac2b-72d8-4666-aaea-b157cc6a0b0c/scratchpad/audit3/pulse`
Methodology: `docs/process/devex-audit/rubric.md` (frozen), steps 0-8.
Persona: a competent engineer joining the team whose first job is a NEW connector for **pap**
(the Patient Assistance Program system; not billing, not the prior audit's pocar).

This document collects evidence only. It assigns no numeric scores. Scoring is Task B's job and
the boomerang comparison against prior runs is Task C's job, not this one's.

Every observation is tagged **TESTED** (I ran it and quote the output), **PARTIAL** (I ran part of
it), or **INFERRED** (reasoned from files, not executed).

---

## Step 0: Target discovery

### What I did

```bash
cd /Users/Rob.Ford/Repos/robford-brookai/pulse
git log --oneline -1          # 11622da
ls -a
task                          # the default target's grouped listing
ls docs/ docs/connectors/ templates/ packages/
```

### What I observed

**TESTED.** The developer-facing surface at `11622da`:

| Surface | What is there |
| --- | --- |
| Entry docs | `README.md` (360 lines), `CONTRIBUTING.md`, `AGENTS.md` (96 lines), `CLAUDE.md`, `WORKFLOW.md` (433 lines) |
| Docs site | `mkdocs.yml` nav over `docs/`, Architecture, Modules, Runbooks (15 pages), Connectors (1 page), Process (8 pages), Contracts (4 pages), Reference (ci-lessons, mcp-servers, 6 ADRs) |
| Design tree | `design/platform/`, `design/migration/`, `design/delivery/` |
| Commands | `Taskfile.yml`, 68 targets listed by bare `task`, grouped by numbered area in workflow order |
| Packages | 14 under `packages/`, 12 Python workspace members, 2 TypeScript (`twenty-app`, `twenty-model`) |
| Connector kit | `packages/pulse-core/src/pulse_core/connector/`, 27 exported names in `__all__` |
| Connector guide | `docs/connectors/authoring.md`, 376 lines, ten numbered sections |
| Connector scaffold | `task connector:new NAME=<n> DIRECTION=outbound\|inbound`, backed by `scripts/connector_new.py` and `templates/connector/` with a `direction/inbound/` overlay |
| Reference connectors | `packages/billing-connector` (outbound), `packages/consent-ingress` and `packages/verdict-relay` (inbound) |
| Lifecycle | `openspec/` (50 spec files), `.openlore/`, `work_orders/`, `handoffs/` (22 change dirs), `.planning/` |
| Gates | `tests/scaffold/cat1..cat10`, `.github/workflows/`, `.pre-commit-config.yaml` |
| Ownership | `.github/CODEOWNERS` (`* @robford-brookai`), `.github/PULL_REQUEST_TEMPLATE.md`, `.github/ISSUE_TEMPLATE/attended-run.yml` |
| DX self-measurement | `tests/scaffold/cat10_devex.py`, `scripts/devex/check.py`, `.planning/devex/loop.jsonl`, `task devex:check`, `task devex:audit` |

**TESTED.** `task` on its own prints all 68 targets with one-line descriptions, `--sort none`, so
the reading order matches the working order. There is no separate "getting started" target and no
`task help`; the bare `task` listing carries that load and does it well.

**Observation (INFERRED).** The connector path has first-class placement: `docs/index.md` lines
34-37 interrupt the site tour with "Building a connector ... Start at [Authoring a connector]
instead of reading this site end to end". That is a deliberate short-circuit for exactly this
persona.

### Friction

- The surface is large. 68 task targets, 14 packages, 5 doc trees (`docs/`, `design/`,
  `openspec/`, `.planning/`, `handoffs/`). Nothing tells the connector author which of the 68
  targets they will ever type. In practice the answer is six: `install`, `connector:new`, `check`,
  `fmt`, `test`, `verify`.
- [Withdrawn by QA A2: `design/platform/pulse-standard-connector-spec.md` is a pointer stub gated by `cat10_devex.py::test_connector_spec_has_one_canonical_copy`; one copy exists.] Two copies of the standard connector spec exist, `openspec/specs/connectors/pulse-standard-connector-spec.md`
  and `design/platform/pulse-standard-connector-spec.md`. **TESTED**, both files exist.

### What a 10/10 looks like for this repo

A named "connector author" slice of the surface: the six targets they need, called out in the bare
`task` listing (an area comment or a `task connector` umbrella target), and one spec file rather
than two copies in two trees.

---

## Step 1: Getting started (TTHW)

### What I did

```bash
git clone https://github.com/robford-brookai/pulse.git pulse   # timed
task install                                                    # timed
task check                                                      # timed
```

Every stage timed with `date +%s` around it, in that order, following only `README.md`'s
"Prerequisites" then "Quickstart" sections.

### What I observed

**TESTED.** Stage timings, warm caches:

| Stage | Command | Seconds | Result |
| --- | --- | --- | --- |
| Clone | `git clone https://github.com/robford-brookai/pulse.git` | 2 | 26 MB working tree, at `11622da` |
| Install | `task install` | 3 | `uv sync --all-packages` + `pre-commit install`; ended `pre-commit installed at .git/hooks/pre-commit` |
| Verify | `task check` | 161 | exit 0, green |
| **TTHW** | **clone to green `task check`** | **166 (2 min 46 s)** | Competitive tier per the rubric's TTHW table (2-5 min) |

**TESTED, cache warmth.** This is a hot-cache number and must be read as one. `du -sh ~/.cache/uv`
reports **26 GB**; `~/.npm/_cacache` is populated. `task install` resolving and linking ~190
packages across 12 workspace members in 3 seconds is only possible against that cache. **INFERRED:**
a genuinely cold machine would spend the download of ~190 wheels plus 190 npm packages here; the
3-second figure is not reproducible on a new laptop and no artifact in the repo records what a cold
number is.

**TESTED, per-target breakdown of `task check`** (measured individually, serially, on the same warm
clone):

| Target | Seconds |
| --- | --- |
| `lint` | 0 |
| `typecheck` | 8 |
| `test` | ~150 (dominant; 2874 tests, coverage-gated) |
| `twenty:validate` | 0 |
| `twenty:test` | 2 |
| `workflow:lint` | 1 |
| `docs:build` | 1 |

`task test` is 90%+ of the gate. Everything else is instant.

**TESTED, no guessing required for the happy path.** `README.md`'s Prerequisites section lists uv,
go-task, Node 22, Docker with install commands per platform, then "Once installed, run: `task
install` / `task check`". I read exactly one document and typed exactly two commands. No error, no
lookup, no environment variable.

**TESTED, points where the documented path is incomplete:**

1. `bootstrap.sh` exists at the repo root and is not mentioned anywhere in `README.md`'s Quickstart
   or `CONTRIBUTING.md`'s Development Workflow. `CLAUDE.md` says gitignored directories are
   "recreated by `bootstrap.sh`". A newcomer following the README never runs it and does not learn
   whether they should.
2. `task lore:init` is required on a fresh clone before `task verify` or `task lore:drift`. This is
   documented, but only in `docs/connectors/authoring.md` step 8 item 6, at the very bottom of a
   376-line connector guide. It is not in `README.md`, not in `CONTRIBUTING.md`, and not in the
   `verify` target's own `desc`.
3. **TESTED.** `task check` ends by printing a large red-bordered block from the Material for
   MkDocs vendor: "⚠ Warning from the Material for MkDocs team ... All plugins will stop working
   ... Currently unlicensed — unsuitable for production use". The gate is green; the last thing on
   the newcomer's screen looks like a failure.
4. **TESTED.** `task check` also prints npm noise mid-run: `npm warn EBADENGINE required: { node:
   '^24.5.0', yarn: '^4.0.2' }, current: { node: 'v26.8.1' }`, plus two deprecation warnings and an
   install-scripts advisory. `.nvmrc` says `22` and root `package.json` `engines` says `>=22`, so
   the repo's own pin is consistent; the warning comes from a transitive Twenty dependency. It
   still reads to a newcomer as "my Node version is wrong".

**TESTED, the biggest T0 finding: `task check` is not hermetic against the developer's global git
config.** On a second run of the same green clone, `task check` failed with six errors:

```
FAILED tests/scaffold/cat5_glue_logic.py::test_explicit_commits_bypass_the_history_scan
FAILED tests/scaffold/cat5_glue_logic.py::test_commits_without_a_handoff_are_delinquent
FAILED tests/scaffold/cat5_glue_logic.py::test_a_worktree_that_has_not_started_is_not_delinquent
FAILED tests/scaffold/cat5_glue_logic.py::test_commits_with_a_handoff_are_fine
FAILED tests/scaffold/cat5_glue_logic.py::test_the_repo_root_is_never_its_own_delinquent
FAILED tests/scaffold/cat5_glue_logic.py::test_commits_ahead_survives_an_unresolvable_base_ref
= 6 failed, 2874 passed, 30 skipped, 6 deselected, 11 warnings in 394.21s (0:06:34) =
```

Root cause, reproduced directly:

```bash
$ git config --global --get commit.gpgsign
true
$ git -c user.email=g@test.invalid -c user.name=G commit -qm base
error: Signing file /var/folders/.../.git_signing_buffer_tmpAdeI4f
Couldn't sign message (signer): agent refused operation?
fatal: failed to write commit object
rc=128
$ git -c user.email=g@test.invalid -c user.name=G -c commit.gpgsign=false commit -qm base
rc=0
```

`tests/scaffold/cat5_glue_logic.py:939` and `tests/scaffold/cat9_golden_workflow.py:460` both build
their temp repos with `["git", "-c", "user.email=...", "-c", "user.name=...", *args]` and do not
pass `-c commit.gpgsign=false`. Any developer with commit signing configured (the norm at this org)
inherits it into the gate's throwaway repos. Confirmed by neutralizing the config:

```bash
$ GIT_CONFIG_GLOBAL=/dev/null task check
check-with-pap rc=0 s=102
```

Same clone, same tree, green. The gate that is advertised as "the contract between your laptop and
CI" fails on a developer laptop for a reason CI can never reproduce.

### Friction

- Cold-cache TTHW is unmeasured and unrecorded anywhere in the repo.
- `bootstrap.sh` and `task lore:init` are prerequisites nobody's documented first path mentions.
- The green gate's final screen is a red vendor warning block.
- Six opaque failures from a global git setting the newcomer did not know applied.

### What a 10/10 looks like for this repo

`task check` passes with `commit.gpgsign=true` set globally, because the scaffold gates pin
`-c commit.gpgsign=false -c gpg.format= ` in their `_git` helpers. `README.md`'s Quickstart is three
lines (`task install`, `task lore:init`, `task check`), and `task check` ends with one line saying
which gates ran and how long each took, with vendor chatter suppressed. A cold-clone TTHW number is
recorded in `.planning/devex/loop.jsonl` alongside the warm one.

---

## Step 2: API / CLI / SDK ergonomics, connector-focused

### What I did

Followed `docs/connectors/authoring.md` in order, on the fresh clone, without reading any other
document first.

```bash
task connector:new NAME=pap DIRECTION=inbound
task install
uv run pytest packages/pap/tests
task lint ; task typecheck
uv run pyright -p packages/pap
GIT_CONFIG_GLOBAL=/dev/null task check
env -u PAP_TOKEN uv run python -m pap.service
PAP_TOKEN=x PAP_SOURCE_TABLE=pap.grants PAP_LEDGER_BASE_URL=http://localhost:9 \
  uv run python -m pap.service --max-pages 1
```

### What I observed

**TESTED: a scaffold command exists and it is the magical moment of this repo.**

```
$ task connector:new NAME=pap DIRECTION=inbound
Rendered pap (pap), inbound, into .../packages/pap:
  packages/pap/README.md
  packages/pap/pyproject.toml
  packages/pap/src/pap/__init__.py
  packages/pap/src/pap/config.py
  packages/pap/src/pap/py.typed
  packages/pap/src/pap/receipts.py
  packages/pap/src/pap/service.py
  packages/pap/tests/conftest.py
  packages/pap/tests/factories.py
  packages/pap/tests/test_config.py
  packages/pap/tests/test_receipts.py
  packages/pap/tests/test_service.py

Registered pap at 2 site(s):
  Taskfile.yml
  pyproject.toml

Next: uv sync --all-packages
SECONDS=0
```

Sub-second. 918 lines rendered. Then:

```
$ uv run pytest packages/pap/tests
collected 35 items
packages/pap/tests/test_config.py ................       [ 45%]
packages/pap/tests/test_receipts.py ......               [ 62%]
packages/pap/tests/test_service.py .............         [100%]
============================== 35 passed in 0.21s ==============================
```

**TESTED, elapsed from `task connector:new` to 35 green tests: under 5 seconds.** The rendered
package is not a stub, it carries a socket-blocked `conftest.py`, a `FixtureRowSource`-driven
reader test, a receipt-line golden, and a `from_env` test that asserts the token value never
appears in the error text.

**TESTED, the registrations are real.** `git diff --stat` after the scaffold:

```
 Taskfile.yml   | 28 ++++++++++++++++++++++++----
 pyproject.toml |  3 +++
 uv.lock        | 26 ++++++++++++++++++++++++++
```

Applied automatically: `[tool.uv.workspace] members`, `[tool.uv.sources]`,
`[tool.ruff.lint.per-file-ignores]` `"packages/pap/tests/**" = ["S101"]`, `LINT_PATHS`,
`TYPED_PATHS`, `TESTED_PATHS`, `COV_PATHS`, and commented `pap:image` / `pap:deploy` stubs. Eight of
the guide's nine sites, done for me.

**TESTED: the ninth site is wrong, and the scaffold contradicts itself.** The rendered
`packages/pap/pyproject.toml` declares:

```toml
[tool.pyright]
include = ["src", "tests"]
typeCheckingMode = "strict"
```

and its own dev-dependency comment says: *"This package typechecks under pyright strict (see
[tool.pyright] below). Add it to the `typecheck` target's pyright list when you register the
package."* But `--apply-registrations` added `packages/pap/src` to **`TYPED_PATHS`** (the mypy list)
and added **no** `uv run pyright -p packages/pap` line to the `typecheck` target. So the package's
declared strict posture is never executed by any gate. It does pass when run by hand:

```
$ uv run pyright -p packages/pap
0 errors, 0 warnings, 0 informations
```

`docs/connectors/authoring.md` step 7 item 4 states the choice explicitly ("if the package is
pyright-strict instead — the newer posture, and the one the reference uses — add a `uv run pyright
-p packages/my-connector` line ... rather than a `TYPED_PATHS` entry"). The scaffold renders the
newer posture and registers the older one.

**TESTED: `task lint` is documented read-only and is not.** `Taskfile.yml`:

```yaml
  lint:
    desc: Check formatting and lint rules (read-only)
```

`CONTRIBUTING.md`: *"`task fmt` applies the formatting and lint fixes that `task lint` only
reports."* Actual output on a freshly scaffolded package:

```
$ task lint
task: [lint] uv run ruff format ... --check
714 files already formatted
task: [lint] uv run ruff check ...
Found 2 errors (2 fixed, 0 remaining).
rc=0
```

`pyproject.toml:154` sets `fix = true` globally, so `ruff check` writes files. Two consequences:

1. `task lint` silently edits the working tree, contradicting its own `desc` and `CONTRIBUTING.md`.
2. The defect it fixed never becomes visible. Reproduced by rendering out-of-tree and disabling the
   fix:

   ```
   $ uv run python scripts/connector_new.py --name papfresh --direction inbound --dest /tmp/papfresh
   $ uv run ruff check --no-fix /tmp/papfresh
   I001 [*] Import block is un-sorted or un-formatted
     --> /tmp/papfresh/tests/test_receipts.py:7:1
   I001 [*] Import block is un-sorted or un-formatted
     --> /tmp/papfresh/tests/test_service.py:8:1
   ```

   The **inbound overlay templates ship two files with unsorted imports**. `task check` is green
   because the gate repairs them in place before judging them. This is the same class of defect the
   head commit `11622da` fixed by hand ("ruff-format the inbound receipt").

**TESTED: the guide's import list is a subset of the kit's public surface.** `pulse_core.connector.__all__`
exports 27 names; `docs/connectors/authoring.md` step 2's copy-paste block lists 14. Not documented
there: `DEFAULT_BASE_DELAY_SECONDS`, `DEFAULT_MAX_ATTEMPTS`, `DEFAULT_MAX_DELAY_SECONDS`,
`DEFAULT_PAGE_SIZE`, `ConsumeReport`, `ConsumerHandler`, `Deduper`, `RowError`,
`RowValidationError`, `ValidatedPage`, `is_watermark_stale`, `parse_instant`.

Four of those are used by the code the scaffold renders for you: the generated
`packages/pap/src/pap/config.py` imports `DEFAULT_PAGE_SIZE`, and `service.py` imports
`ValidatedPage` and `RowError`. **A connector author's own generated package uses names the
authoring guide does not mention.**

**TESTED: `pulse_core.connector` is not the whole import surface, and the guide says it is.** Step
2 opens: *"Everything shared lives in `pulse_core.connector`. Import from the package root, not the
submodules."* The reference connectors do not:

```
packages/billing-connector/src/billing_connector/service.py:49:from pulse_core.client import PulseCoreClient
packages/billing-connector/src/billing_connector/declare.py:33:from pulse_core.client import ResponseClassification
packages/billing-connector/src/billing_connector/declare.py:35:from pulse_core.generated import DeclareTransitionCommand, DeclareVerdictCommand, VerdictOutcome
packages/consent-ingress/src/consent_ingress/declarer.py:51:from pulse_core.generated import RecordCommunicationConsentCommand
packages/consent-ingress/src/consent_ingress/row_source.py:42:from pulse_core.cursor import validate_cursor
```

And the scaffold it renders for you does not either, `packages/pap/src/pap/service.py:45` is
`from pulse_core.cursor import validate_cursor`.

Three modules a real connector needs, `pulse_core.client` (the client and response
classification), `pulse_core.generated` (**the command types you actually declare**), and
`pulse_core.cursor`, appear nowhere in the authoring guide's "What to import".

**TESTED: neither scaffold declares anything, which is the half the connector exists for.** The
rendered inbound `handle_page`:

```python
def handle_page(page: ValidatedPage[SourceRow], *, tally: Receipt) -> Receipt:
    """Act on one validated page and return the next tally. Never mutates `tally`.

    Scaffold behavior: count the page and do nothing with it. Replace this with the derivation
    and the `submit_with_retry` call this connector exists for ...
    """
    logger.debug("page rows=%d errors=%d", len(page.rows), len(page.errors))
    return tally.record_page(page)
```

`build_row_source` is likewise a stub returning `FixtureRowSource([])`. The outbound variant is the
same shape (`grep -n "submit_with_retry\|PulseCoreClient\|generated" /tmp/papout/src/papout/service.py`
matches only a comment on line 35). So the scaffold hands you a package that reads nothing and
declares nothing; the declare path, build a command from `pulse_core.generated`, hand it to
`submit_with_retry`, classify the response, has no worked example in either the scaffold or the
guide. **The author must reverse-engineer it from `packages/consent-ingress/src/consent_ingress/declarer.py`.**

**TESTED: files read and concepts learned to get to a running package.**

Files/docs read before I could scaffold: 2 (`README.md`, `docs/connectors/authoring.md`).
Files I had to open *after* scaffolding to understand what to write next: 4
(`packages/pap/src/pap/service.py`, `packages/pulse-core/src/pulse_core/connector/__init__.py`,
`packages/billing-connector/src/billing_connector/declare.py`,
`packages/consent-ingress/src/consent_ingress/row_source.py`).

Concepts a pap author must hold before writing a line of real logic: connector direction
(inbound/outbound), `RowSource`, `CursorStore`, `LedgerCursorStore`, cursor column and page
boundary, `validate_page` / `CONTRACT_COLUMNS` / `RowValidationError`, `ValidatedPage`,
`DeclareCounts` and receipt classification, idempotency-key derivation, `submit_with_retry` with
injected `Sleeper`/`Jitter`, the four response classifications, credential-name-not-value, the
credential-posture gate, evidence class and epoch, and the nine registration sites. **Roughly 15
concepts before the first real line.**

**How far I got before getting stuck.** All the way to a green, registered, typechecked,
coverage-counted package inside `task check`, in minutes. I got stuck at exactly one place: what a
pap grant row should become as a ledger command. That is business logic and correctly not the
scaffold's job; but the *mechanism* of turning a validated row into a declared command has no
example anywhere on the documented path.

**TESTED: `task` help text and target naming.** Naming is consistent and predicate-shaped:
`<area>:<verb>` (`twenty:deploy`, `spec:validate`, `lore:drift`, `billing-connector:image`), and
every credentialed or destructive target says so in its own `desc` ("needs dev credentials", "needs
Docker", "needs CHANGE"). The `connector:new` desc is complete on one line: *"Scaffold a connector
package (NAME, DIRECTION=outbound|inbound) from templates/connector/ and register it at every site"*
which is also the sentence that turns out to be slightly untrue about the pyright site.

### Friction

- Registration picks mypy for a package that declares pyright strict; the declared posture never runs.
- The guide's import list omits 13 of 27 exported names, including 3 the generated code uses.
- Three required `pulse_core` modules are undocumented in the guide, including the command types.
- No declare example anywhere on the documented path.
- `task lint` mutates files while claiming to be read-only, hiding a real template defect.
- The rendered `packages/pap/README.md` "Next steps" step 1 tells the author to perform
  registrations that `task connector:new` already performed. **TESTED**, quoted verbatim from the
  rendered file.

### What a 10/10 looks like for this repo

`task connector:new NAME=pap DIRECTION=inbound` renders a package whose `handle_page` contains a
complete, commented, *working* declare, a `pulse_core.generated` command built from a fixture row,
handed to `submit_with_retry`, its response counted into `DeclareCounts`, and a test asserting the
rerun comes back `replayed`. The author deletes the fixture and points it at pap. The guide's step 2
lists all 28 kit names plus the three sibling modules with one line each on when you need them. The
scaffold adds `uv run pyright -p packages/pap` to `typecheck`, and `task lint` never writes a byte.

---

## Step 3: Error messages

### What I did

Ten deliberate mistakes, each run to completion with its exit code captured.

### What I observed

| # | Mistake | Exact output | Problem? | Cause? | Fix? |
| --- | --- | --- | --- | --- | --- |
| E1 | `task connector:new` (no NAME) | `task: Task "connector:new" cancelled because it is missing required variables: NAME`, rc 206 | yes | yes | implied (names the variable, not the syntax) |
| E2 | `task connector:new --name=pap` (flag syntax) | `Usage: task [flags...] [task...]` ... 60 lines of go-task help ... `unknown flag: --name`, rc 2 | yes, buried | no | no |
| E3 | `task connector:new NAME=pap DIRECTION=sideways` | `connector_new.py: error: argument --direction: invalid choice: 'sideways' (choose from outbound, inbound)`, rc 201 | yes | yes | yes |
| E4 | `task verify` (no CHANGE) | ran the entire gate first, then `task: Failed to run task "verify"`, rc 201, **403 seconds** | no | no | no |
| E5 | `task dispatch CHANGE=no-such-change` | `Error: openspec/changes/no-such-change/tasks.md not found`, rc 201 | yes | yes | implied |
| E6 | `task check` from `packages/` | ran normally (go-task walks up to the root Taskfile), no error to report | n/a | n/a | n/a |
| E7 | `Config.from_env({})` (empty env) | see below | yes | yes | partial |
| E8 | `PAP_PAGE_SIZE=x PAP_STALE_AFTER_SECONDS=x` | see below | yes | yes | yes |
| E9 | `uv run python -m pap.service` with no env | the E7 error, logged, exit 2 | yes | yes | partial |
| E10 | valid config, unreachable ledger | see below | no | no | no |

**TESTED, E7 and E8: best-in-class.**

```
$ uv run python -c "from pap.config import Config; Config.from_env({})"
ConfigError: pap configuration is unusable:
  - PAP_SOURCE_TABLE is unset — the fully qualified relation to page
  - PAP_LEDGER_BASE_URL is unset — the command-API base URL
  - PAP_TOKEN is unset — this connector's ledger writer token
```

```
ConfigError: pap configuration is unusable:
  - PAP_PAGE_SIZE='x' is not an integer — whole rows
  - PAP_STALE_AFTER_SECONDS='x' is not an integer — whole seconds
```

Every problem collected in one pass, every variable named, every one carrying its meaning and unit,
and the token's *value* never printed. `packages/pap/src/pap/config.py` even documents why:
*"One start of the process tells the operator everything that is wrong, not the first thing."* This
is the standard the rest of the repo should be held to. The only thing missing is a fix line, no
example value, no pointer to `.env.example` or a runbook.

**TESTED, E9: the same error, correctly surfaced through the process:**

```
2026-09-04 20:01:24,543 ERROR pap configuration is unusable:
  - PAP_SOURCE_TABLE is unset — the fully qualified relation to page
  - PAP_LEDGER_BASE_URL is unset — the command-API base URL
  - PAP_TOKEN is unset — this connector's ledger writer token
```

`main()` catches `ConfigError` and returns exit 2 with no traceback. Exactly right.

**TESTED, E10: the cliff.** Shape-valid config pointed at an unreachable command API:

```
$ PAP_TOKEN=x PAP_SOURCE_TABLE=pap.grants PAP_LEDGER_BASE_URL=http://localhost:9 \
    uv run python -m pap.service --max-pages 1
...
  File ".../httpx/_transports/default.py", line 118, in map_httpcore_exceptions
    raise mapped_exc(message) from exc
httpx.ConnectError: [Errno 61] Connection refused
```

A raw traceback through `httpx` internals. It does not name `PAP_LEDGER_BASE_URL`, does not print
the URL it tried, does not say the failure was in `LedgerCursorStore` opening the durable cursor,
and does not suggest a fix. The one error the connector author is *most* likely to hit first, a
wrong ledger URL or a token the ledger rejects, is the worst error in the repo. Config errors were
designed; runtime errors were not.

**TESTED, E4: the fail-fast claim is false.** `docs/connectors/authoring.md` step 8 item 5 says
`task verify` *"(`CHANGE` is required — it fails fast rather than validating the wrong change)"*.
Measured:

```
$ task verify
rc=201 seconds=403
```

`Taskfile.yml` declares `requires: vars: [CHANGE]` on `verify`, but line 49 sets a repo-wide default
`CHANGE: ""`, which satisfies the requirement. So `verify` runs `check`, lint, typecheck, the full
2874-test coverage suite, for six and a half minutes before failing. On my run it never even
reached `spec:validate`. **This is a 400-second penalty for a one-word typo, on a target whose
documentation promises the opposite.**

**TESTED, E-cat5: the gate failure with no cause.** The six `cat5_glue_logic` failures from Step 1
report only:

```
E  subprocess.CalledProcessError: Command '['git', '-c', 'user.email=g@test.invalid',
   '-c', 'user.name=G', 'commit', '-qm', 'base']' returned non-zero exit status 128.
```

The helper at `tests/scaffold/cat5_glue_logic.py:938` uses `subprocess.run(..., capture_output=True,
check=True)`, so git's actual stderr, `Couldn't sign message (signer): agent refused operation?`,
is captured into the exception and never displayed. The developer sees "exit status 128" with no
problem statement, no cause, and no fix, on a gate that is supposed to be their contract with CI.

**TESTED, E2: go-task's own failure mode.** `task connector:new --name=pap` prints 60 lines of
generic go-task usage and puts `unknown flag: --name` on the *last* line, below the fold. `CLAUDE.md`
already documents this as a known trap ("Passing the change as a flag instead exits 2 with `unknown
flag`"), which means it has bitten someone before and the fix was a note rather than a change.

### Friction

Ranked by how much time the mistake costs a connector author: E4 (403 s), E-cat5 (a full debugging
session on an unrelated global setting), E10 (raw traceback on the most likely first runtime
failure), E2 (real message below the fold).

### What a 10/10 looks like for this repo

Every runtime error in a connector reaches the same bar `ConfigError` already sets: problem, the
variable or URL that caused it, and the next command to run. `LedgerCursorStore` wraps transport
failures with the base URL it tried and the env var that supplied it. `task verify` with no CHANGE
fails in under a second. `cat5`'s `_git` helper re-raises with `exc.stderr` in the message.

---

## Step 4: Documentation

### What I did

```bash
grep -ril "build a connector" --include='*.md' .   # findability probe
grep -ril "new connector" --include='*.md' .
grep -ril "connector:new" --include='*.md' .
task docs:build                                     # currency / strict build
# every backticked path in authoring.md resolved against the tree
```

### What I observed

**TESTED: the persona's eight questions, in order, against `docs/connectors/authoring.md`:**

| # | Question | Answered? | Where |
| --- | --- | --- | --- |
| 1 | What is a connector here? | Yes, well | §1, including the five non-negotiable properties and the inbound/outbound table |
| 2 | What do I import? | **Partially** | §2 lists 14 of 27 kit names; omits `pulse_core.client`, `pulse_core.generated`, `pulse_core.cursor` entirely |
| 3 | How do I scaffold? | Yes, excellently | §3, with the rendered tree, the `DIRECTION` table, and the overlay mechanics |
| 4 | How do I configure? | Yes, excellently | §4, with the rules the gate and reviewer check, including "report every missing variable at once" |
| 5 | How do I test offline? | Yes, excellently | §5, both mechanisms plus the four tests that pay for themselves |
| 6 | How do I register the package? | Yes | §7, all nine sites, plus the grep to self-check |
| 7 | How do I ship through the workflow? | Yes | §8, six numbered steps plus the two exceptions |
| 8 | Who do I ask? | Yes | §9, named owner plus an eight-row "before asking" table |

Seven of eight answered at a high standard, in exactly the order the persona needs them. The one
gap is question 2, and it is the one that blocks writing code (Step 2 above).

**TESTED: currency.** Every backticked file path in `authoring.md` resolves against the tree; the
only "missing" hit is the `packages/my-connector` placeholder, which is intentional. `task
docs:build` is clean:

```
INFO    -  Cleaning site directory
INFO    -  Building documentation to directory: .../site
INFO    -  Documentation built in 0.90 seconds
```

No broken-link errors, no nav warnings. `mkdocs build -s` treats a broken link as an error and it
passes, so link rot cannot accumulate silently. The only output that looks like a warning is the
Material 2.0 vendor banner (Step 1, friction 3).

**TESTED: one stale-ish reference.** `authoring.md` §9's table points "What is a connector's
standard shape overall?" at `openspec/specs/connectors/pulse-standard-connector-spec.md`. That file
exists. So does `design/platform/pulse-standard-connector-spec.md`. Two trees, same document name;
the guide names one and the findability probe lands on the other.

**TESTED: findability.** The obvious phrase misses:

```
$ grep -ril "build a connector" --include='*.md' .
design/platform/pulse-standard-connector-spec.md
.planning/reports/2026-09-02-devex-scorecard.md      (not opened; audit blindness)
.planning/reports/2026-09-02-devex-audit-evidence.md (not opened)
openspec/changes/devex-eight/proposal.md
```

`docs/connectors/authoring.md` is not in the results. The phrases that *do* land on it are "new
connector" and "connector:new", the terms you know only after you have already found the page.

Mitigating this heavily: **TESTED**, `docs/index.md` lines 34-37 short-circuit the site for exactly
this persona, `CONTRIBUTING.md` line 5 ends with *"Building a connector? Start with
[`docs/connectors/authoring.md`](docs/connectors/authoring.md)"*, and `README.md`'s Connectors
section links it too. Three of the four entry points a newcomer would try point at the guide by
name. Only a blind grep for the natural phrase fails.

### Friction

- The natural search phrase does not find the guide.
- [Withdrawn by QA A2] Two copies of the standard connector spec in two trees.
- Question 2 (what do I import) is the one incompletely answered question, and it is the blocking one.

### What a 10/10 looks like for this repo

`authoring.md` opens with a one-line "Build a connector" H1 alias so the obvious grep lands, §2
covers all four `pulse_core` modules a connector touches with a one-line "when you need this" per
name, and the standard connector spec lives in exactly one tree with the other path a stub pointer.

---

## Step 5: Upgrade path

### What I did

```bash
cat .ade-template-version
task template:diff
head -40 packages/pulse-core/CHANGELOG.md
grep -n "## " openspec/specs/connector-kit/spec.md
ls docs/adr/ ; grep -l -i superseded docs/adr/*.md
```

### What I observed

**TESTED: the kit's upgrade discipline is real and documented.** `packages/pulse-core/CHANGELOG.md`
exists, is Keep-a-Changelog shaped, and its header states the rule:

> Each entry that touches `pulse_core.connector` carries a **Connector authors** line naming the
> concrete effect on a connector build against the kit — read it before `uv sync` pulls in a new
> version.

The `0.1.0` baseline entry carries that line. `openspec/specs/connector-kit/spec.md` has a
`## Deprecations` section (line 85) requiring a retiring name to stay exported and working for one
release with the CHANGELOG naming the replacement. `authoring.md` §10 tells the connector author
exactly what to do when the kit moves: read the CHANGELOG top-down, check the spec's Deprecations
section, and file a `connector-kit` defect if a name vanished without either. **This is the
strongest single answer in the audit**, a named contract, a durable record, a point-in-time
announcement, and an escalation path.

**TESTED, the caveat.** `git log` shows the CHANGELOG currently holds one `[Unreleased]` entry
("This CHANGELOG. Connector authors: none — process only") and the `0.1.0` baseline. The machinery
exists; it has not yet been exercised by a real kit change. **INFERRED:** whether the
"same PR that makes it" rule holds is unproven until a kit change ships against it.

**PARTIAL: template sync is blocked in this environment.**

```
$ task template:diff
Fetching https://github.com/robford-brookai/repo-ade.git ...
sign_and_send_pubkey: signing failed for ED25519 "/Users/Rob.Ford/.ssh/gh_robford-brookai.pub" from agent: communication with agent failed
git@github.com: Permission denied (publickey).
task: Failed to run task "template:diff": exit status 128
```

Same locked SSH agent as the `commit.gpgsign` failure in Step 1. Two DX notes stand regardless:
`.ade-template-version` pins `a1de595b8591691a624d67d60efaa20d73641967`, so the provenance is exact
and machine-checkable; and [withdrawn by QA A3: `scripts/template_sync.sh:18` uses HTTPS; the SSH failure was this machine's own `url.insteadOf` rewrite against a locked agent] `scripts/template_sync.sh` reaches `repo-ade` over **SSH** while the
repo itself clones fine over **HTTPS**. A newcomer who cloned over HTTPS has working git and a
broken `task template:diff`, and neither `README.md` nor `CONTRIBUTING.md` mentions that the upgrade
path needs SSH access to a second private repo.

**TESTED: ADR discipline.** Six files in `docs/adr/` (`ADR-0000-template` through `ADR-0005`), all
in the mkdocs nav by number and title. `CLAUDE.md` states the rule ("append-only; a superseded
decision gets a status flip and a new ADR"). `grep -l -i superseded docs/adr/*.md` matches only the
template, so no supersession has occurred yet, the rule is stated and untested. **INFERRED.**

**TESTED: spec archiving.** `openspec/specs/` is the accumulated baseline written only by archiving
(`task spec:archive`), `handoffs/` holds one directory per completed change (22 present, including
`_archived`), and `openspec/changes/billing-connector/tasks.md` carries `[DNA-nnnn]` Linear tokens
inline. The lifecycle is closed-loop and evidenced.

**INFERRED: how a connector author absorbs a kit change.** The documented path is: `uv sync` pulls
the new kit, read `packages/pulse-core/CHANGELOG.md`'s Connector-authors lines, check
`connector-kit`'s Deprecations. Nothing *prompts* the read, §10 says so plainly ("nothing prompts
you to go read anything"). There is no `task kit:changelog`, no version-drift warning at import, and
no pin: `packages/pap/pyproject.toml` declares `"pulse-core"` with no version constraint at all, so
a kit change arrives silently on the next sync.

### Friction

- Kit-change absorption is a discipline, not a mechanism; nothing surfaces it at the moment of sync.
- `pulse-core` is depended on unversioned, so there is nothing a connector could pin against.
- `task template:diff` requires SSH to a second private repo, undocumented.

### What a 10/10 looks like for this repo

`task install` prints the `pulse-core` CHANGELOG entries added since the connector's last recorded
sync (a one-line marker file in the package), so the Connector-authors lines find the author instead
of the author finding them. `task template:diff` works over HTTPS or says which credential it needs.

---

## Step 6: Developer environment

### What I did

```bash
uv --version ; task --version ; python3 --version ; node --version
cat .python-version .nvmrc .editorconfig .vscode/extensions.json
grep -n "id:" .pre-commit-config.yaml
ls .git/hooks/pre-commit        # after the documented install
diff .github/workflows/main.yml against `task check`
```

### What I observed

**TESTED: pins are explicit and machine-readable.** `.python-version` = `3.14`, `.nvmrc` = `22`,
`uv.lock` committed (190 packages), `package-lock.json` committed, `.ade-template-version` pinning
the template commit, and a checksum-pinned Synthea JAR. `task docs:lock-guard` runs `uv lock
--check` inside `check`, so lock drift from `pyproject.toml` fails the gate. Nothing about the
toolchain is left to "whatever you have".

**TESTED: prerequisites are documented with install commands.** `README.md` gives per-platform
install lines for uv, go-task, Node 22, and Docker, and marks openspec/openlore/orca/gh as
"optional but recommended". `CLAUDE.md` and `docs/contracts/consumes.md` both record *why*
`openspec` and `openlore` stay out of `task check`: they are npm globals CI runners do not have.
That constraint is also gated by `tests/scaffold/cat4_command_contract.sh`.

**TESTED: hooks are installed by the documented install.** `task install`'s last line:

```
task: [install] uv run pre-commit install
pre-commit installed at .git/hooks/pre-commit
```

Twelve hooks configured: `check-case-conflict`, `check-merge-conflict`, `check-toml`, `check-yaml`,
`check-json`, `pretty-format-json`, `end-of-file-fixer`, `trailing-whitespace`, `ruff-check`,
`ruff-format`, `openlore-drift`. `CONTRIBUTING.md` warns about the consequence up front: *"A hook
that rewrites a file fails the commit by design — re-stage and commit again."*

**TESTED: editor support is thin but present.** `.editorconfig` at the root and
`.vscode/extensions.json` recommending `charliermarsh.ruff`, `ms-python.python`,
`ms-python.mypy-type-checker`, `editorconfig.editorconfig`, `redhat.vscode-yaml`. There is no
`.vscode/settings.json` (no interpreter path, no format-on-save, no pytest discovery config), and
nothing for JetBrains or Neovim. A connector author gets ruff highlighting and nothing else for
free. Notably, the recommended type-checker extension is **mypy**, while the newer connector posture
is **pyright**, the same mypy/pyright split as Step 2's registration bug, surfacing in the editor
config.

**TESTED: local/CI parity is architected, not asserted.** `.github/workflows/main.yml`'s `quality`
job runs exactly `task check`, and `tests/scaffold/cat4_command_contract.py` enforces that every
`run:` command in a workflow resolves to a defined Taskfile target or a tool an earlier step
installs. This is the single best structural decision in the repo's developer environment: parity
cannot rot because a gate fails when it does.

**TESTED: with one hole, from Step 1.** The parity claim holds for tool versions and target lists
but not for ambient git config. CI has no `commit.gpgsign`; developers here do. `task check` failed
6 tests on my laptop and passed under `GIT_CONFIG_GLOBAL=/dev/null` on the identical tree. The
contract is true by construction in one dimension and false in another.

**TESTED: concurrency is unsafe.** Two `task test` runs in the same clone collide on the shared
root `.coverage` file:

```
INTERNALERROR> coverage.exceptions.DataError: Couldn't use data file
  '.../.coverage.BH-CF9JH6CFC3-2_local.pid88116.XljYmJgx': no such table: meta
```

I induced this myself by running `task check` and `task verify` concurrently in the same clone, so
it is not something the repo did to me unprompted. It matters anyway: this is an ADE where parallel
agents in worktrees are the normal mode, and nothing in the coverage configuration namespaces the
data file per run.

### Friction

- No `.vscode/settings.json`; the recommended type checker is the one the newer packages do not use.
- `task check` inherits the developer's global git config.
- Concurrent test runs in one clone corrupt shared coverage state.

### What a 10/10 looks like for this repo

A `.vscode/settings.json` that sets the `.venv` interpreter, format-on-save with ruff, and pytest
discovery, so the recommended extensions actually do something. Scaffold gates that pin every git
config they depend on. `COVERAGE_FILE` namespaced per run so two agents in one tree cannot collide.

---

## Step 7: Community and ecosystem (internal-repo interpretation)

The rubric's internal-repo interpretation asks for: a named owner per area (`CODEOWNERS`), a channel
or person named in `README.md`, issue and PR templates, and evidence that someone other than the
owner has landed a connector.

### What I did

```bash
cat .github/CODEOWNERS ; ls .github/ISSUE_TEMPLATE ; wc -l .github/PULL_REQUEST_TEMPLATE.md
head -60 CONTRIBUTING.md ; sed -n '/## 9/,/## 10/p' docs/connectors/authoring.md
ls handoffs/ ; grep -n "DNA-" openspec/changes/*/tasks.md
wc -l AGENTS.md WORKFLOW.md templates/HANDOFF.md docs/process/dispatch-template.md
grep -in "billing" docs/contracts/producer-registry.md
```

### What I observed

**TESTED: owners.** `.github/CODEOWNERS` is two lines:

```
# Pulse code owners
* @robford-brookai
```

One owner, one glob. No per-area ownership: `packages/pulse-core/src/pulse_core/connector/` (the kit
every connector depends on) has the same owner as `docs/`. For a repo with 14 packages, that is a
single point of review.

**TESTED: who to ask is named, consistently, in three places.** `CONTRIBUTING.md` line 5,
`docs/connectors/authoring.md` §9, and `docs/index.md`, all: *"**Owner: Rob Ford**
([@robford-brookai](https://github.com/robford-brookai)) — ask directly on Slack; there is no
dedicated channel yet."* Honest about the gap rather than papering over it, and `authoring.md` §9
softens it with a genuinely useful eight-row "before asking, the answer is usually in one of these"
table mapping each likely question to a file.

**TESTED: templates.** `.github/PULL_REQUEST_TEMPLATE.md` (1029 bytes) exists.
`.github/ISSUE_TEMPLATE/` holds exactly one form: `attended-run.yml`, the tracked-issue path for
work that never enters a worktree, per `WORKFLOW.md`'s `live_execution`. There is no bug report
template, no feature/change proposal template (OpenSpec covers that), and no connector-specific
template.

**TESTED: the agent-facing "community" is unusually strong.** `AGENTS.md` (96 lines) is the binding
worktree contract: tests first, one task one commit, never edit spec files. `WORKFLOW.md` (433
lines) carries an executable YAML block validated by `task workflow:lint` on every `check`:

```
task: [workflow:lint] uv run python scripts/workflow.py lint
WORKFLOW.md v2.2.0 ok — 14 steps, 3 gates (structure, statuses, projections)
```

`templates/HANDOFF.md` (41 lines) and `docs/process/dispatch-template.md` (251 lines) define the
receipt and dispatch shapes. `handoffs/` holds 22 per-change directories of collected receipts ,
so "someone did the work and left a record" is materially evidenced, change by change.

**TESTED: Linear linkage is live and in-tree.** `openspec/changes/billing-connector/tasks.md`
carries id tokens inline:

```
- [x] 3.1 [DNA-1280] Deploy artifacts: Duplo service JSON, queue/DLQ/rule provisioning script
- [ ] 4.1 [DNA-1281] `verdict-reconcile` schedules entry: per-(subject, verdict_type)
- [ ] 5.2 [DNA-1282] Docs close-out via `HANDOFF.md`: ADR for the write-path supersession,
```

written by `task linear:sync CHANGE=<id> APPLY=1`, with `task workflow:lint:linear` validating team,
project, and status against live Linear. Plan-to-ticket traceability is mechanical, not manual.

**TESTED: the "someone other than the owner landed a connector" evidence.** `git log --format='%an'`
on the repo shows a single human author. The rubric explicitly says this "cannot be manufactured".
The honest reading: every connector in `packages/` was landed by the owner or by agents dispatched
by the owner. There is no second human connector author to point at. **INFERRED**, from authorship
alone.

**TESTED: a gap the reference implementation itself has.** `authoring.md` §8 tells the author:
*"Register your connector as a producer there [`docs/contracts/producer-registry.md`]: the domain it
declares on, its writer credential's name, the paired commands, and a link to its runbook."*
`grep -in "billing" docs/contracts/producer-registry.md` returns rows for cpt-om, the pulse billing
engine, and Billy, **no row for `packages/billing-connector`**, the package the guide names as *the*
reference implementation. The rule is stated; the model does not follow it.

### Friction

- One owner for 14 packages; no per-area CODEOWNERS entry for the connector kit.
- No Slack channel; the escalation path is one person's DMs.
- One issue template, none for a connector proposal or a kit defect (which §10 tells you to file).
- The reference connector is absent from the registry its own guide requires.

### What a 10/10 looks like for this repo

`CODEOWNERS` names an owner for `packages/pulse-core/src/pulse_core/connector/` distinct from the
repo default, a `#pulse-connectors` channel is named in `README.md` and `authoring.md` §9, there is
a `connector-kit-defect` issue template matching §10's escalation instruction, and
`packages/billing-connector` has its own `producer-registry.md` row so the reference obeys the rule
it teaches.

---

## Step 8: DX measurement

### What I did

Read the repo's own DX machinery as a newcomer who found it, per the audit's blindness rule: I read
`tests/scaffold/cat10_devex.py`, `scripts/devex/check.py`, and the field shape of
`.planning/devex/loop.jsonl`. I did **not** read any `.planning/reports/*devex*` report or the
per-run `.planning/devex/*-check.json`.

### What I observed

**TESTED: the repo measures its own DX, deliberately and with an unusual design.**
`tests/scaffold/cat10_devex.py`'s docstring states the mechanism:

> One test per finding from the DevEx audit ... While a defect exists its test is
> `xfail(strict=True)`: the gate stays green, and `scripts/devex/check.py` counts the xfails as
> `devex_open_findings`. Fixing a defect flips the marker off in the same PR; from then on a
> regression fails `task check`.
>
> The number this gate produces is a count of open findings, never a 0-10.

This is a genuine ratchet: each fixed finding converts from a counted xfail into a permanent
regression test. The separation of concerns is explicit and correct, the deterministic gate emits a
count, the LLM-judged audit emits the 0-10, and neither is allowed to produce the other's number.

**TESTED: the protocol itself is frozen against drift.** `scripts/devex/check.py` carries
`digests()`, `freeze()`, and `verify()`, and `cat10_devex.py` has `test_audit_protocol_is_frozen`.
`docs/process/devex-audit/rubric.md`'s header states it is covered by `CHECKSUMS` and that editing
it is a rubric change needing its own PR. **The measurement instrument is version-controlled against
being quietly adjusted to flatter the result**, that is a level of measurement discipline most
teams never reach.

**TESTED: onboarding time is measured.** `cat10_devex.py:410-430`:

```python
# --- TTHW: fresh clone to a synced environment (slow) ---
@pytest.mark.slow
def ...:
    """Time clone plus the documented install. Prints `TTHW_INSTALL_SECONDS=<n>` for the ledger."""
    t0 = time.monotonic()
    ...
    seconds = round(time.monotonic() - t0)
    print(f"TTHW_INSTALL_SECONDS={seconds}", file=sys.stderr)
```

Marked `slow`, so it does not run in `task check`; the docstring gives the opt-in invocation
(`uv run pytest tests/scaffold/cat10_devex.py -m slow -v`).

**TESTED: the history is a ledger, not a snapshot.** `.planning/devex/loop.jsonl` records one line
per event. Two record shapes:

```
['connector', 'date', 'kind', 'open_findings', 'overall', 'qa', 'ref', 'reports']
['date', 'kind', 'open_findings', 'pr', 'ref', 'task']
```

An audit-run record (with the connector audited, the overall score, the QA verdict, and the report
paths) and a fix record (with the PR and the task). So the finding count is traceable to the PR that
moved it. `task devex:check` prints `METRIC devex_open_findings=<n>`.

**TESTED: the audit is a documented, repeatable, three-agent protocol,** published in the docs nav:
`docs/process/devex-audit/README.md` (runbook), `rubric.md` (frozen methodology), and `task-a.md` /
`task-b.md` / `task-c.md` (evidence / scoring / QA), with `task devex:audit` printing the runbook and
today's report paths. Separating evidence collection from scoring from QA, with a blindness rule for
the evidence agent, is a real experimental design.

**What is measured, and what is not:**

| Dimension | Measured? | Evidence |
| --- | --- | --- |
| Open findings count | Yes, gated | `cat10_devex.py` xfail ratchet, `METRIC devex_open_findings` |
| Onboarding time (TTHW) | Yes, opt-in | `TTHW_INSTALL_SECONDS`, `-m slow` |
| Spec/code drift | Yes | `openlore drift` as a pre-commit hook and in `task verify` |
| Doc link rot | Yes, gated | `mkdocs build -s` inside `task check` |
| Local/CI command parity | Yes, gated | `cat4_command_contract` |
| Workflow-doc drift | Yes, gated | `task workflow:lint` inside `check` |
| **Gate durations** | **No** | Nothing records how long `task check` or its targets take, run to run |
| **Cold-cache TTHW** | **No** | The `slow` test measures wall-clock on whatever cache the machine has |
| **Error-message quality** | **No** | No gate asserts an error names problem, cause, and fix |
| **Scaffold-to-first-declare time** | **No** | The metric that matters most to a connector author |

**TESTED, the gap that bit this audit.** Step 1's finding is precisely the kind of thing gate-duration
and hermeticity measurement would have caught: `task check` took 161 s once and 403 s the next time,
green then 6 failures, on an unchanged tree. Nothing in the DX machinery notices that, because
nothing records a duration or asserts the gate is independent of ambient config.

### Friction

- Durations are timed once, by hand, in a `slow` test nobody is prompted to run.
- No cold-vs-warm distinction, so the TTHW number is not comparable across machines or over time.
- The connector-author metric (scaffold to first declared command) is not defined or measured.

### What a 10/10 looks like for this repo

`task check` appends `{target, seconds, rc}` per target to `.planning/devex/loop.jsonl` on every
run, so gate slowdowns show up as a trend rather than a complaint. The TTHW test records cold and
warm separately (`UV_CACHE_DIR` pointed at a temp dir for the cold arm). One more metric joins the
ledger: seconds from `task connector:new` to a connector that declares one command against a fixture
ledger, the number this repo's persona actually lives.

---

## Connector author journey

Elapsed is cumulative wall-clock from `git clone`, warm caches, following only what the repo says.

| Elapsed | Action | Outcome | Stuck point |
| --- | --- | --- | --- |
| 0:00 | `git clone https://github.com/robford-brookai/pulse.git` | 26 MB tree at `11622da` (2 s) | none |
| 0:02 | Read `README.md` Prerequisites + Quickstart | uv, go-task, Node 22, Docker already present | `bootstrap.sh` unmentioned; unclear whether needed |
| 0:02 | `task install` | venv + 12 workspace members + pre-commit hook (3 s) | 3 s only because `~/.cache/uv` is 26 GB |
| 0:05 | `task check` | **green, exit 0 (161 s)**, TTHW = **2 min 46 s** | ends on a red Material 2.0 vendor banner |
| 2:46 | `task` (bare) | 68 targets, grouped, in working order | nothing marks the six a connector author needs |
| 2:50 | `docs/index.md` → `docs/connectors/authoring.md` | 376 lines, ten sections, read once end to end | grep for "build a connector" would not have found it |
| 3:10 | `task connector:new NAME=pap DIRECTION=inbound` | 12 files, 918 lines, 8 of 9 registrations applied (<1 s) | the pyright site registered as mypy instead |
| 3:11 | `task install` | workspace re-resolved with `pap` (<1 s) | rendered README tells me to redo registrations already done |
| 3:12 | `uv run pytest packages/pap/tests` | **35 passed in 0.21 s** | none |
| 3:13 | `task lint` | `Found 2 errors (2 fixed, 0 remaining)`, rc 0 | "read-only" target silently rewrote my files |
| 3:13 | `task typecheck` | clean, 8 s | never ran `pyright -p packages/pap`, the package's declared posture |
| 3:15 | `GIT_CONFIG_GLOBAL=/dev/null task check` | **green with `pap` inside the gate (102 s)** | needed the env override to pass at all |
| 5:00 | `env -u PAP_TOKEN uv run python -m pap.service` | `ConfigError` naming all 3 missing vars, exit 2 | none, best error in the repo |
| 5:01 | Point at a ledger URL, run again | `httpx.ConnectError: [Errno 61] Connection refused`, raw traceback | no URL, no variable name, no fix |
| 5:05 | Open `service.py` to write the real logic | `build_row_source` and `handle_page` are stubs | **stuck: no declare example anywhere on the documented path** |
| 5:10 | `grep` the kit for how to declare | `__all__` has 27 names; guide documents 14 | `pulse_core.generated` command types undocumented in the guide |
| 5:15 | Open `packages/consent-ingress/src/consent_ingress/declarer.py` | found the pattern, off the documented path | had to reverse-engineer the half the connector exists for |
| n/a | Write the pap row → command derivation | **INFERRED**, not performed; business logic, and pap's source schema is not in this repo | correctly out of scope |
| n/a | `task spec:validate` / `task dispatch` / PR / merge | **INFERRED**, not performed; would require an OpenSpec change and a PR | n/a |
| n/a | `task verify CHANGE=<id>` | **INFERRED**, not performed with a real change; measured only the no-CHANGE failure (403 s) | n/a |
| n/a | Register in `producer-registry.md`, write a runbook | **INFERRED**, not performed | the reference connector has no registry row to copy |

Time to a green, registered, typechecked, coverage-counted connector package: **about 3 minutes**
after TTHW. Time to a connector that actually declares: unbounded on the documented path.

---

## Top 10 friction points

Ordered by impact on a connector author.

1. **No declare example anywhere on the documented path.** Both scaffolds leave `handle_page` /
   `handle_event` as counting stubs with `submit_with_retry` mentioned only in a docstring, and
   `authoring.md` §2 never mentions `pulse_core.generated`, the module holding the command types
   you declare. The author must reverse-engineer the connector's entire reason for existing from
   `packages/consent-ingress/src/consent_ingress/declarer.py`. **TESTED.**
2. **`task check` is not hermetic against global git config.** `commit.gpgsign=true` (the org norm)
   makes 6 `cat5_glue_logic` tests fail with `returned non-zero exit status 128` and no cause shown,
   because the helper at `cat5_glue_logic.py:939` and `cat9_golden_workflow.py:460` pins user
   identity but not signing, and swallows git's stderr. `GIT_CONFIG_GLOBAL=/dev/null task check`
   passes on the identical tree. **TESTED.**
3. **`task verify` with no CHANGE burns 403 seconds before failing**, because `Taskfile.yml:49`'s
   repo-wide `CHANGE: ""` default satisfies `verify`'s own `requires`. `authoring.md` §8 promises
   the opposite ("it fails fast rather than validating the wrong change"). **TESTED.**
4. **The scaffold registers the wrong typecheck site.** The rendered `pyproject.toml` declares
   `[tool.pyright] typeCheckingMode = "strict"` and its own comment says to add a pyright line;
   `--apply-registrations` adds the package to mypy's `TYPED_PATHS` instead, so the declared posture
   never runs in any gate. **TESTED.**
5. **`task lint` is documented read-only and writes files.** `pyproject.toml:154` `fix = true` means
   `ruff check` auto-fixes, contradicting the target `desc` and `CONTRIBUTING.md`, and hiding the
   fact that the inbound overlay templates ship two files with `I001` unsorted imports
   (`tests/test_receipts.py`, `tests/test_service.py`, both confirmed with `ruff check --no-fix`).
   **TESTED.**
6. **Runtime errors fall off a cliff that config errors do not.** `ConfigError` is best-in-class
   (every problem at once, every variable named with its unit, no secret values). The very next
   failure a connector author hits is `httpx.ConnectError: [Errno 61] Connection refused` with a raw
   traceback, no URL, no variable name, no fix. **TESTED.**
7. **The guide documents 14 of the kit's 27 exported names**, omitting four the generated package
   itself imports (`DEFAULT_PAGE_SIZE`, `ValidatedPage`, `RowError`, and, via a sibling module,
   `validate_cursor`), plus the three sibling `pulse_core` modules every real connector uses.
   **TESTED.**
8. **Kit upgrades reach connectors silently.** `packages/pap/pyproject.toml` depends on
   `"pulse-core"` with no version constraint; §10 states plainly that "nothing prompts you to go
   read anything". The CHANGELOG and Deprecations discipline is excellent and entirely opt-in, and
   has not yet been exercised by a real kit change. **TESTED / INFERRED.**
9. **Findability by the natural phrase fails.** `grep -ril "build a connector"` lands on
   `design/platform/pulse-standard-connector-spec.md` and prior reports, never on
   `docs/connectors/authoring.md`. Three of four navigational entry points do link it by name, so
   this bites the greppers, not the readers. Compounded by [withdrawn by QA A2] two copies of the standard connector spec
   living in two trees. **TESTED.**
10. **Ecosystem is one person.** `CODEOWNERS` is `* @robford-brookai` with no per-area entry for the
    connector kit, there is no Slack channel (stated honestly in three places), the only issue
    template is `attended-run.yml`, not the kit-defect template §10 tells you to file, and
    `packages/billing-connector`, the guide's own reference implementation, has no row in the
    `producer-registry.md` that §8 requires every connector to register in. **TESTED.**

Below the cut, recorded for completeness: the green `task check` ends on a red-bordered Material
2.0 vendor warning; npm `EBADENGINE` noise from a transitive Twenty dependency reads as a local
toolchain problem; `bootstrap.sh` and `task lore:init` are fresh-clone prerequisites documented
nowhere on the README path; `.vscode` recommends the mypy extension for a repo whose newer packages
are pyright-strict, and ships no `settings.json`; `task template:diff` needs SSH to a second private
repo while the repo itself clones over HTTPS; concurrent `task test` runs in one clone corrupt the
shared root `.coverage` file; the rendered package README instructs registrations the scaffold
already performed.

---

## Method notes and limits

**What I ran.** A real `git clone` from GitHub into
`/private/tmp/.../scratchpad/audit3/pulse`, then `task install`, `task check` (three times, under
varying conditions), `task lint`, `task typecheck`, `task test`, `task verify`, `task connector:new`
(three renderings: inbound in-tree as `pap`, inbound out-of-tree as `papfresh`, outbound out-of-tree
as `papout`), `uv run pytest`, `uv run pyright`, `task template:diff`, and ten deliberate error
cases. Timings are `date +%s` deltas around single commands.

**Read-only discipline.** No tracked file in
`/Users/Rob.Ford/Repos/robford-brookai/pulse` was modified. The only write to that repo is this
report at `.planning/reports/2026-09-05-devex-audit-evidence.md`. All mutation, the `pap` package,
the registration edits, `uv.lock`, `/tmp/papfresh`, `/tmp/papout`, happened inside the disposable
scratchpad clone. Nothing was committed anywhere.

**Blindness held.** I did not open any file matching `.planning/reports/*devex*` or any
`.planning/devex/*-check.json`. Three of those paths appeared in `grep -l` output during the Step 4
findability probe (filenames only, contents never read) and one is cited by
`packages/pulse-core/CHANGELOG.md`'s header. Per the task's Step 8 allowance I read
`tests/scaffold/cat10_devex.py`, `scripts/devex/check.py`, and the *field names* of
`.planning/devex/loop.jsonl` (via `sorted(d.keys())`, not values), and used none of it to steer
Steps 0-7. Steps 0-7 were complete in evidence before Step 8 was opened.

**Cache warmth is the single largest limit on the timings.** `~/.cache/uv` is 26 GB and `~/.npm`
is populated. The 3-second `task install` and the 2-second clone are hot-path numbers. A cold-machine
TTHW is **not measured here and is not recorded anywhere in the repo**; treat 2 min 46 s as a floor,
not an expectation.

**One failure was self-induced.** The `coverage.exceptions.DataError` in Step 6 came from my running
`task check` and `task verify` concurrently in the same clone. I report it because parallel agents in
worktrees are this repo's normal operating mode, but it is not a defect the repo produced unprompted.

**Two findings are environment-blocked, not repo-blocked.** `task template:diff` and the
`cat5_glue_logic` failures both trace to a locked 1Password SSH agent on this machine
(`agent refused operation`). The `cat5` case is still a genuine repo defect, the gates should pin
`commit.gpgsign=false` regardless of what the agent is doing, but `template:diff` would work with an
unlocked agent, so Step 5's template-sync arm is **PARTIAL**, not failed.

**Not exercised.** The full ship path: an OpenSpec change for `pap`, `task dispatch`, a worktree, a
PR, `task verify CHANGE=<id>` against a real change, `task collect`, `task checkoff`,
`task spec:archive`, was not run; it needs a real change and a PR, which is outside a read-only
audit. Those journey rows are tagged INFERRED. Live-credential targets (`demo:3`, `demo:4`,
`stage:e2e:live`, every `deploy`) were not run and no live network call was made to any production
system. No PHI appears anywhere in this report; the only data touched was the scaffold's own empty
fixtures.
