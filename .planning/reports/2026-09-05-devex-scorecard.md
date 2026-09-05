# DevEx scorecard: pulse @ 11622da

Corrections from `.planning/reports/2026-09-05-devex-audit-qa.md` applied 2026-09-05 (B3, B4, B5, B7): the
TTHW anchor is restated on QA's uncontended 117 s; Community carries the prior-QA caveat; the +0.9
composite delta is partly a slice-derivation method change and the prior 5.8 predates its own QA-corrected
dimension 8, so it is not a clean improvement figure; two line references fixed. No score moved.


Date: 2026-09-05
Repo under audit: `/Users/Rob.Ford/Repos/robford-brookai/pulse`, scored at `11622da` (main).
Working HEAD at scoring time was `208be59`, a ledger-row and handoffs commit on top of `11622da`;
`git merge-base --is-ancestor 11622da HEAD` confirms the audited commit is an ancestor and nothing
between them touches a scored surface.

Inputs:

- Evidence: `.planning/reports/2026-09-05-devex-audit-evidence.md` (Task A), read in full.
- Rubric: `docs/process/devex-audit/rubric.md` (frozen excerpt, internal-repo interpretation
  applied as written).

Blindness held. I opened no prior scorecard, no prior evidence report, and no
`.planning/devex/*-check.json`. Under the task's dimension-8 allowance I read
`tests/scaffold/cat10_devex.py`, `scripts/devex/check.py`, and the field shape and line count of
`.planning/devex/loop.jsonl`; I read no score values out of any ledger row. Boomerang comparison
against prior runs is Task C's job, not this one's.

Method. Every dimension below was spot-checked against at least two pieces of Task A's evidence by
opening the cited file or re-running the cited command in the repo itself. Where a claim could only
be established by a wall-clock measurement, I verified its structural cause in the tree rather than
re-running the timing, and said so. Six claims did not survive the check and are listed under
"Evidence disputes". Scores reflect what I verified, not what was asserted.

---

## Headline

| Number | Value |
| --- | --- |
| **Connector author DX (weighted composite)** | **6.7 / 10** |
| **Overall DX (unweighted mean of eight dimensions)** | **6.5 / 10** |

The shape of this repo's DX is unusually lopsided, and both headline numbers hide it. The moment a
connector author reaches `task connector:new` is genuinely best-in-class: one command, 918 lines, 35
green tests in under five seconds, eight of nine registrations applied for you. The moment they hit
their first runtime failure, or type `task verify` without a `CHANGE`, or run `task check` on a
laptop with commit signing on, the repo drops two full tiers. Designed surfaces here are excellent;
undesigned surfaces are raw. The distance between them is the finding.

---

## Scorecard

| # | Dimension | Score | Confidence | Method | Evidence pointer |
| --- | --- | --- | --- | --- | --- |
| 1 | Getting Started (TTHW) | **6** | High | Verified the structural cause of the gate failure in-tree; accepted Task A's stopwatch numbers | `tests/scaffold/cat5_glue_logic.py:937`, `cat9_golden_workflow.py:458`, `README.md` Quickstart, `README.md:294` |
| 2 | API / CLI / SDK ergonomics | **7** | High | Re-read the templates, `scripts/connector_new.py`, and `Taskfile.yml` `typecheck`; re-rendered two packages out-of-tree | `scripts/connector_new.py:334-337`, `templates/connector/pyproject.toml.tmpl:21-23,40-42`, `templates/.../service.py.tmpl:172-180` |
| 3 | Error messages | **5** | High | Read `ConfigError` in the template, `LedgerCursorStore` in the kit, and the `verify` / `CHANGE` wiring | `templates/.../config.py.tmpl:54-60`, `packages/pulse-core/src/pulse_core/connector/rows.py:229-233`, `Taskfile.yml:49` and the `verify` target |
| 4 | Documentation | **8** | High | Read `authoring.md` §2 end to end, re-ran the findability grep, opened both spec paths | `docs/connectors/authoring.md` §2, `docs/index.md:34-37`, `CONTRIBUTING.md:5`, `design/platform/pulse-standard-connector-spec.md` |
| 5 | Upgrade path | **7** | Medium-high | Read the CHANGELOG contract, the spec's Deprecations section, and `template_sync.sh`; the "unexercised" judgment is inference | `packages/pulse-core/CHANGELOG.md:1-16`, `openspec/specs/connector-kit/spec.md:85+`, `scripts/template_sync.sh:18` |
| 6 | Developer environment | **7** | High | Read the pins, `.vscode/`, the CI `quality` job, and the parity gate | `.python-version`, `.nvmrc`, `.vscode/extensions.json`, `.github/workflows/main.yml:50`, `tests/scaffold/cat4_command_contract.py` |
| 7 | Community & ecosystem | **5** | High | Read `CODEOWNERS`, the issue-template dir, and grepped the producer registry | `.github/CODEOWNERS`, `.github/ISSUE_TEMPLATE/attended-run.yml`, `docs/contracts/producer-registry.md:27-29` QA note (B4): one of the two points over the prior 3 is the prior QA's recommended correction to 4, not a repo improvement; only #386 lies behind the other. |
| 8 | DX measurement | **7** | High | Read `cat10_devex.py`, `scripts/devex/check.py`, and counted live `@open_finding` markers | `tests/scaffold/cat10_devex.py:4-5,42,87`, `scripts/devex/check.py:34-43,99`, `.planning/devex/loop.jsonl` |

Overall DX = (6 + 7 + 5 + 8 + 7 + 7 + 5 + 7) / 8 = 52 / 8 = **6.5**.

### Dimension notes

**1. Getting Started - 6.** TTHW is 166 s warm under contention (QA B3: 117 s uncontended, the Champion band) and unbounded on a stock machine with commit signing on
(120-300 s), not Champion. Two commands from one document, no environment variable, no lookup:
that part is very good. Three things hold it at 6 rather than 7. The gate is not hermetic against
the developer's global git config, and I confirmed the cause directly: both `_git` helpers pin
`user.email` and `user.name` and nothing else, and both pass `capture_output=True, check=True`, so
git's actual stderr is swallowed and the developer sees `returned non-zero exit status 128` with no
cause. Commit signing is the org norm here, so this is not an edge case; it is a first-day
session-loss for a typical new hire. Second, the documented first path is incomplete: `bootstrap.sh`
appears in `README.md` only at line 294 in a discussion of scaffold gates, never in Quickstart, and
`task lore:init` appears only in `docs/connectors/authoring.md:311`, item 6 of step 8 of a 376-line
guide. Third, the cold-cache number is unmeasured, so 166 s is a floor and nobody knows the real
first-day figure.

**2. API / CLI / SDK ergonomics - 7.** `task connector:new` is the best thing in this repo and the
score would be 8 without two defects that I verified rather than inferred. `scripts/connector_new.py`
lines 334-337 register the new package into `LINT_PATHS`, `TYPED_PATHS`, `TESTED_PATHS` and
`COV_PATHS`; `TYPED_PATHS` is mypy's list. The template it just rendered declares
`[tool.pyright] typeCheckingMode = "strict"` at `pyproject.toml.tmpl:40-42` and carries a comment at
lines 21-23 telling the author to add the package to the `typecheck` target's pyright list. No
pyright line is added. The package's declared type posture is never executed by any gate, and the
`connector:new` desc, which promises to "register it at every site", is untrue about that one site.
Separately, `task lint`'s desc says "read-only", `CONTRIBUTING.md` and `README.md` both repeat it,
and `pyproject.toml:154` sets `fix = true` globally, so `ruff check` writes files. Set against those:
naming is consistently `<area>:<verb>`, every credentialed or destructive target declares itself in
its own desc, and the scaffold ships a socket-blocked conftest, a fixture-driven reader test, a
receipt golden, and a token-redaction test. The last mile is what is missing: `handle_page` is a
counting stub, and the declare path the connector exists for has no worked example.

**3. Error messages - 5.** This dimension is bimodal and the mean is honest. `ConfigError` in the
rendered `config.py` collects every problem in one pass, names each variable with its unit, and never
prints the token value; the class docstring states the design intent. That is a 9 in isolation, short
only a fix line. Everything outside it is undesigned. `LedgerCursorStore.load` at `rows.py:229-233`
calls `raise_for_status()` with no wrapping, so the single most likely first runtime failure - a
wrong ledger URL - surfaces as a raw `httpx.ConnectError` traceback naming neither the URL nor the
variable that supplied it. `Taskfile.yml:49` sets a repo-wide `CHANGE: ""` default that satisfies
`verify`'s own `requires: vars: [CHANGE]`, so the guard never fires and the full gate runs first;
`authoring.md` §8 promises the opposite. And the `cat5` helper discards the stderr that would explain
its own failure. The rubric's bar is problem plus cause plus fix on every error. This repo clears it
on exactly one error class.

**4. Documentation - 8.** Task A's own persona table is the right instrument and I agree with seven
of its eight verdicts. `authoring.md` answers what a connector is, how to scaffold, how to configure,
how to test offline, how to register, how to ship, and who to ask, in the order the persona needs
them, and `mkdocs build -s` keeps link rot from accumulating. Three of four navigational entry points
name the guide by title. I scored this higher than Task A's friction list implies because two of its
three documentation complaints did not survive verification (see disputes D2 and D4). The one real
gap is §2, and it is the blocking one: it lists 14 of the kit's 27 exported names, and its opening
rule - "Import from the package root, not the submodules" - is contradicted by the repo's own
scaffold (`from pulse_core.cursor import validate_cursor`), its own test factory
(`from pulse_core.client import PulseCoreClient`), and both reference connectors. A rule the
reference implementation breaks is worse than no rule.

**5. Upgrade path - 7.** The design here is better than most internal repos manage. The CHANGELOG
header states a binding contract: every entry touching `pulse_core.connector` carries a Connector
authors line naming the concrete effect. `openspec/specs/connector-kit/spec.md` §Deprecations
requires a retiring name to stay exported and working for one release, raise `DeprecationWarning`
naming its replacement, and be announced in the CHANGELOG in the same PR. `authoring.md` §10 gives
the author the read order and the escalation path. `.ade-template-version` pins the template commit
exactly. What holds this at 7 is that none of it has fired yet: the CHANGELOG holds one
process-only `[Unreleased]` entry and the `0.1.0` baseline, the Deprecations table reads
`_none yet_`, and no ADR has been superseded. A contract that has never been exercised is a promise,
not a track record. Compounding it, nothing prompts the read at the moment of `uv sync`; §10 says so
in plain words.

**6. Developer environment - 7.** The structural decision here is the best one in the repo:
`.github/workflows/main.yml`'s quality job runs exactly `task check`, and
`tests/scaffold/cat4_command_contract.py` fails when any workflow `run:` line stops resolving to a
defined target. Parity cannot rot silently. Pins are complete and machine-readable - Python 3.14,
Node 22, `uv.lock`, `package-lock.json`, a checksum-pinned Synthea JAR, the template commit - and
`task docs:lock-guard` runs inside `check`. Hooks install with the documented install. Three holes
keep it off 8. The parity claim covers tool versions and target lists but not ambient git config,
which is the same defect as dimension 1's. `.vscode/` has an `extensions.json` and no
`settings.json`, so the recommended extensions have no interpreter, no format-on-save, and no test
discovery to act on - and the recommended type-checker is `ms-python.mypy-type-checker` while the
newer connector posture is pyright, the mypy/pyright split of dimension 2 resurfacing in the editor.
And coverage data is not namespaced per run, in a repo whose normal operating mode is parallel
agents in worktrees.

**7. Community & ecosystem - 5.** Judged strictly by the rubric's internal-repo interpretation, which
asks for four things. Named owner per area: `CODEOWNERS` is `* @robford-brookai`, one glob for 14
packages, with no distinct entry for `pulse_core/connector/`, the kit every connector depends on.
Person to ask named in the README: yes, and stated identically in three places, honestly including
"there is no dedicated channel yet". Issue and PR templates: a PR template exists; `ISSUE_TEMPLATE/`
holds exactly one form, `attended-run.yml`, and specifically not the kit-defect template that
`authoring.md` §10 instructs the author to file. Evidence that someone other than the owner has
landed a connector: none, and the rubric says this cannot be manufactured. Against that, the
agent-facing contract surface is genuinely strong - `AGENTS.md`, a `WORKFLOW.md` whose YAML block is
linted on every `check`, `handoffs/` receipts per change, `[DNA-nnnn]` tokens written into tasks.md
by `linear:sync`. And one verified self-inconsistency: `authoring.md` §8 requires every connector to
register in `docs/contracts/producer-registry.md`, and `packages/billing-connector` - the guide's own
reference implementation - has no row there.

**8. DX measurement - 7.** The design is unusual and I want to be clear that it is good. One test per
audit finding, `xfail(strict=True)` while the defect is open so the gate stays green,
`scripts/devex/check.py` counting the xfails into `METRIC devex_open_findings`, and the marker
flipping off in the same PR that fixes the defect so the test becomes a permanent regression guard.
The instrument itself is frozen: `digests()` / `freeze()` / `verify()` plus
`test_audit_protocol_is_frozen`, so the rubric cannot be quietly adjusted to flatter a result. The
deterministic gate emits a count and never a score; the LLM audit emits the score and never the
count. Most teams never get here. Two gaps keep it at 7. First, `grep -c "@open_finding"` on
`cat10_devex.py` returns **0** at this HEAD, while this audit verified at least four live defects
(pyright registration, `lint` mutating, the gpgsign hole, `verify` burning the gate). The ratchet
measures findings prior audits recorded, not the repo's live DX; a zero there is easy to misread as
"no open findings exist". Second, nothing records gate durations run to run, nothing separates cold
from warm TTHW, no gate asserts an error names problem-cause-fix, and the metric this repo's persona
actually lives - seconds from `connector:new` to a connector that declares one command - is neither
defined nor collected.

---

## Seven DX Characteristics

| # | Characteristic | Score | Basis |
| --- | --- | --- | --- |
| 1 | Usable | **7** | Two commands to green, one command to a working package, consistent target naming. Held down by a gate that fails on a normal laptop and a `lint` target that writes files while calling itself read-only. |
| 2 | Credible | **6** | The weakest characteristic and the most fixable. Deprecation machinery is well designed and entirely unexercised; three documented behaviors (`lint` read-only, `verify` fails fast, import from the root only) are each contradicted by what the repo actually does. Predictability, not reliability, is the problem. |
| 3 | Findable | **8** | `docs/index.md` short-circuits the site for this exact persona, `CONTRIBUTING.md` line 5 and the README both name the guide, the nav is real, and strict mkdocs prevents link rot. Only a blind grep for the natural phrase misses, and even that hit points at the guide one line down. |
| 4 | Useful | **8** | The kit solves the real problems - durable cursor, page validation, retry with injected sleep and jitter, dedupe, receipt counts - and is explicitly extracted rather than invented. The declare half is unexampled, so it solves most of the problem rather than all of it (Principle 6). |
| 5 | Valuable | **8** | `connector:new` to 35 green registered coverage-counted tests in under five seconds is a real and measurable saving against hand-rolling a package across nine registration sites. |
| 6 | Accessible | **5** | CLI only. One editor partially configured, with the wrong type checker recommended and no `settings.json`. No GUI, no dashboard, nothing for JetBrains or Neovim. The agent-facing surface is excellent and the human-facing surface outside a terminal is thin. |
| 7 | Desirable | **6** | The scaffold is a genuine magical moment and would carry this alone. A 403-second penalty for a one-word typo, six opaque failures from a global git setting, and a green gate that ends on a red vendor banner are the exact opposite feeling, and they arrive first. |

---

## Connector author DX composite

Fixed slices and weights per the audit protocol, so runs stay comparable. Each slice takes the
dimension score named in its basis column.

| Slice | Weight | Dimension used | Score | Weighted |
| --- | --- | --- | --- | --- |
| Kit API ergonomics | 30 | 2. API / CLI / SDK ergonomics | 7 | 30 x 7 / 100 = 2.10 |
| Connector documentation | 20 | 4. Documentation | 8 | 20 x 8 / 100 = 1.60 |
| Getting started to a working connector | 15 | 1. Getting Started | 6 | 15 x 6 / 100 = 0.90 |
| Errors on the connector path | 15 | 3. Error messages | 5 | 15 x 5 / 100 = 0.75 |
| Dev environment for a new package | 10 | 6. Developer environment | 7 | 10 x 7 / 100 = 0.70 |
| Kit upgrade path | 5 | 5. Upgrade path | 7 | 5 x 7 / 100 = 0.35 |
| Ecosystem and support | 3 | 7. Community & ecosystem | 5 | 3 x 5 / 100 = 0.15 |
| Measurement of author experience | 2 | 8. DX measurement | 7 | 2 x 7 / 100 = 0.14 |
| **Total** | **100** | | | **6.69, reported as 6.7** |

Arithmetic: 2.10 + 1.60 + 0.90 + 0.75 + 0.70 + 0.35 + 0.15 + 0.14 = 6.69.

The composite sits slightly above the unweighted mean because the two slices carrying half the weight
(kit ergonomics and connector documentation) are two of the repo's three strongest dimensions. It
would be 7.2 if the error slice alone reached 8.

---

## Gap method: what a 10 looks like, per dimension below 9

Each entry states the 10 first, then the single highest-leverage move toward it. Every 10 below is
set above "defect-free" on purpose: fixing every item in the disputes and fixes sections would land
this repo around 8, not 10.

**1. Getting Started, 6 to 10.** A 10 is: `task check` is provably independent of the developer's
machine - every scaffold gate pins the git config it depends on, and a gate asserts that
independence so it cannot regress. The README's Quickstart is three lines that constitute the entire
first path with nothing else required. `task check` closes with one line per target and its
duration, vendor chatter suppressed, so the last thing on a new hire's screen is a summary of what
just passed. A cold-cache TTHW figure sits next to the warm one in `.planning/devex/loop.jsonl`, so
"how long does day one take" has an answer rather than an anecdote. *Highest leverage:* pin
`-c commit.gpgsign=false` in both `_git` helpers and re-raise with `exc.stderr` in the message. It is
a four-line change that converts the repo's most expensive first-day failure into a non-event.

**2. API / CLI / SDK ergonomics, 7 to 10.** A 10 is: `task connector:new` renders a package whose
`handle_page` contains a complete, commented, *running* declare - a `pulse_core.generated` command
built from a fixture row, handed to `submit_with_retry`, its classification counted into
`DeclareCounts` - with a test asserting the second run comes back `replayed`. The author deletes the
fixture and points it at their source; they never reverse-engineer anything. Registration is
complete and correct at all nine sites including pyright. `task lint` never writes a byte, and every
target's desc is exactly what the target does. *Highest leverage:* ship the working declare in the
scaffold. It closes the one place Task A got stuck, and it is the difference between "solves most of
the problem" and Principle 6.

**3. Error messages, 5 to 10.** A 10 is: every error a connector author can reach meets the bar
`ConfigError` already sets, and `ConfigError` itself gains the fix line it is missing. Transport
failures name the URL tried and the environment variable that supplied it. Gate failures print the
underlying tool's stderr. `task verify` with no `CHANGE` fails in under a second. And the bar is
enforced rather than remembered: a `cat10` test asserts that each error path names a problem, a
cause, and a next command, so the standard cannot decay back to a traceback. *Highest leverage:*
wrap `LedgerCursorStore`'s transport failures. It is the first runtime error the author hits and
currently the worst one in the repo.

**4. Documentation, 8 to 10.** A 10 is: §2 covers all 27 kit names plus the three sibling
`pulse_core` modules a real connector touches, one line each on when you need it, and it states the
import rule the reference implementations actually follow instead of one they break. The guide is
generated-checked against `__all__`, so a name added to the kit and not to the guide fails a gate  -
documentation currency becomes structural rather than diligent, which is the step that separates
good docs from Stripe-tier docs. *Highest leverage:* a test that diffs `authoring.md` §2's name list
against `pulse_core.connector.__all__`. It fixes today's gap and prevents its recurrence in one move.

**5. Upgrade path, 7 to 10.** A 10 is: the Connector-authors lines find the author instead of the
author finding them. `task install` prints the `pulse-core` CHANGELOG entries added since the
connector's last recorded sync. A deprecated name emits its `DeprecationWarning` in the author's own
test run, so the grace window is felt rather than read. And the machinery has been exercised at least
once by a real kit change, with the receipt in the ledger, so it is a track record rather than a
policy. *Highest leverage:* run one real kit change through the contract end to end. Nothing else
converts a promise into credibility.

**6. Developer environment, 7 to 10.** A 10 is: cloning and opening the repo in VS Code produces a
working environment with no further configuration - `.venv` interpreter selected, ruff formatting on
save, pytest discovery live, pyright as the recommended checker to match the newer packages. Every
gate is hermetic against ambient state, asserted by a test. `COVERAGE_FILE` is namespaced per run so
two agents in one tree never collide, because parallel worktree agents are this repo's normal mode
and the environment should assume it rather than tolerate it. *Highest leverage:* add
`.vscode/settings.json` and swap the recommended extension to pyright. It is a single small file
that makes the five extensions already recommended actually do something.

**7. Community & ecosystem, 5 to 10.** A 10 is: `CODEOWNERS` names a distinct owner for
`packages/pulse-core/src/pulse_core/connector/`, a `#pulse-connectors` channel is named wherever the
owner currently is, `ISSUE_TEMPLATE/` carries the `connector-kit-defect` form that §10 tells authors
to file, and every connector including the reference one has its `producer-registry.md` row. Above
defect-free: at least one connector in `packages/` was landed end to end by someone other than the
owner, with the handoff receipt to prove it - the rubric is explicit that this cannot be
manufactured, and it is the only evidence that the authoring path works for someone who did not
write it. *Highest leverage:* have a second person land the next connector using only the documented
path, and treat every place they get stuck as a finding.

**8. DX measurement, 7 to 10.** A 10 is: `task check` appends `{target, seconds, rc}` per target to
the ledger on every run, so a gate slowdown appears as a trend rather than a complaint. The TTHW test
records cold and warm arms separately with `UV_CACHE_DIR` pointed at a temp directory for the cold
one. `devex_open_findings` is unambiguous about what a zero means, because the ratchet is seeded
continuously rather than only at audit time. And the ledger carries the metric this persona lives:
seconds from `connector:new` to a connector that declares one command against a fixture ledger.
*Highest leverage:* record per-target durations on every `task check`. It is the measurement that
would have caught this audit's own biggest finding - 161 s green then 394 s with six failures on an
unchanged tree - without anyone having to notice.

---

## Top 10 fixes, ranked by adoption impact over effort

Effort: S under an hour, M a session, L multiple sessions. Principle numbers refer to the rubric's
DX First Principles.

| # | Fix | Effort | Principle | Why it ranks here |
| --- | --- | --- | --- | --- |
| 1 | Pin `-c commit.gpgsign=false` in the `_git` helpers at `cat5_glue_logic.py:937` and `cat9_golden_workflow.py:458`, and re-raise with `exc.stderr` in the message | S | 5 (fight uncertainty) | Highest ratio in the audit. Four lines convert a full lost debugging session on day one, on a setting the developer does not know applies, into nothing at all. Also fixes the worst error message in the repo as a side effect. |
| 2 | Guard `verify` against an empty `CHANGE` before it calls `check` | S | 7 (speed is a feature) | 403 seconds per typo, on a target the docs promise fails fast. A one-line precondition. |
| 3 | Make `--apply-registrations` add `uv run pyright -p packages/<name>` to `typecheck` instead of a `TYPED_PATHS` entry | S | 9 (pit of success) | The scaffold currently renders one posture and registers another, so the package's declared strictness is dead. The pit-of-success failure is that doing everything right still leaves the gate blind. |
| 4 | Make `task lint` genuinely read-only (`ruff check --no-fix`), then fix the template files it was silently repairing | S | 4 (decide for me, let me override) | Three documents state this behavior and the tool does the opposite. It also hides real template defects: I confirmed a rendered package named `papchk` emits two `I001` errors while `zapchk` emits none, because the template's import block is only sorted when the package name sorts after `pulse_core`. The gate was repairing that before judging it. |
| 5 | Ship a complete working declare in the scaffold's `handle_page` plus a replay assertion | M | 6 (show code in context) | The single stuck point in the whole journey, and the half the connector exists for. Hello world that reads nothing and declares nothing is exactly the lie Principle 6 names. |
| 6 | Wrap `LedgerCursorStore` transport failures with the base URL tried and the variable that supplied it | M | 5 (fight uncertainty) | The most likely first runtime failure currently produces a raw `httpx` traceback. `ConfigError` already proves this team can write the good version. |
| 7 | Complete `authoring.md` §2 to all 27 kit names plus `pulse_core.client` / `.generated` / `.cursor`, correct the root-only rule, and add a test diffing the list against `__all__` | S | 3 (learn by doing) | The one blocking documentation gap, and the test makes it stay fixed. Four of the undocumented names are imported by the code the scaffold hands the author. |
| 8 | Rewrite the rendered README's "Next steps" step 1 to state what the scaffold already did | S | 5 (fight uncertainty) | The first document the author reads inside their own new package tells them to redo work already done. Cheap, and it undermines trust in everything else the scaffold says. |
| 9 | Append `{target, seconds, rc}` per target to `.planning/devex/loop.jsonl` on every `task check`, and add a cold-cache arm to the TTHW test | M | 7 (speed is a feature) | Makes gate regressions and the cold/warm gap visible as trends. Would have caught this audit's own largest finding automatically. |
| 10 | Add a `connector-kit-defect` issue template, a per-area `CODEOWNERS` line for `pulse_core/connector/`, and the missing `billing-connector` producer-registry row | S | 5 (fight uncertainty) | Three small edits that close the loop §10 opens: the guide tells authors to file a defect against a form that does not exist, and the reference implementation breaks the registry rule it teaches. |

### Below the cut

Real, verified, and not worth displacing anything above.

- The green `task check` ends on a red-bordered Material for MkDocs vendor banner; the last thing a
  newcomer sees on a passing gate looks like a failure.
- npm `EBADENGINE` noise from a transitive Twenty dependency reads as "my Node version is wrong"
  when the repo's own pins are consistent.
- `bootstrap.sh` and `task lore:init` are fresh-clone prerequisites that appear nowhere on the
  README's documented first path.
- `.vscode/` recommends the mypy extension for a repo whose newer packages are pyright-strict, and
  ships no `settings.json`, so the five recommended extensions have nothing to act on.
- `COVERAGE_FILE` is not namespaced per run, so two concurrent test runs in one clone corrupt shared
  coverage state - relevant because parallel worktree agents are this repo's normal mode, though
  Task A induced the failure deliberately rather than meeting it.
- Nothing marks which six of the 68 task targets a connector author will ever type; a `task
  connector` umbrella target or an area comment would carry it.
- `packages/pulse-core` has no mechanism to surface its CHANGELOG at `uv sync` time; §10 states
  plainly that nothing prompts the read.

---

## Evidence disputes

Six claims in Task A's report did not survive verification, plus one class of claim I accepted
without re-running. Task A's file was not edited.

**D1. Kit export count is 27, not 28; the guide lists 14, not 15.** Task A reports "28 exported
names" and "step 2's copy-paste block lists 15", omitting 12. I counted `__all__` in
`packages/pulse-core/src/pulse_core/connector/__init__.py` directly: 27 names. I counted the names in
`authoring.md` §2's block: 14. So 13 are undocumented, not 12. The direction and the conclusion are
unchanged and the gap is marginally worse than reported. Scored on my counts.

**D2. "Two copies of the standard connector spec" is false, and this materially changed a score.**
Task A cites this as friction in Step 0 and Step 4 and folds it into top-10 finding #9.
`design/platform/pulse-standard-connector-spec.md` is 1117 bytes and contains no spec content. It is
a pointer stub whose entire body names
`openspec/specs/connectors/pulse-standard-connector-spec.md` as the one canonical copy, redirects the
two things that used to live there, and closes with: "Do not re-add spec content here — a second copy
is the defect that `tests/scaffold/cat10_devex.py::test_connector_spec_has_one_canonical_copy` guards
against." I confirmed that test exists at `cat10_devex.py:86`. Task A's stated 10/10 for
documentation - "the standard connector spec lives in exactly one tree with the other path a stub
pointer" - is already implemented, and gated. Removed from the Documentation score.

**D3. `task template:diff` does not reach `repo-ade` over SSH.** Task A concludes that
"`scripts/template_sync.sh` reaches `repo-ade` over **SSH** while the repo itself clones fine over
**HTTPS**" and recommends as a 10/10 that "`task template:diff` works over HTTPS".
`scripts/template_sync.sh:18` reads
`TEMPLATE_URL="${ADE_TEMPLATE_URL:-https://github.com/robford-brookai/repo-ade.git}"`. It already
uses HTTPS. The SSH failure came from the audit machine's own global git configuration:
`git config --global --get-regexp 'url\..*\.insteadof'` returns
`url.gh_robford-brookai:.insteadof https://github.com/`, which rewrites every GitHub HTTPS URL to
SSH before git dials, combined with a locked agent. Environment, not repo. Removed from the Upgrade
path score, and the observation that the requirement is undocumented falls with it.

**D4. The findability finding is overstated.** Task A's grep for "build a connector" returns five
paths, three of which are audit reports and one an OpenSpec proposal. The single remaining hit is the
stub from D2, and the matching line is
`- How to build a connector against the kit, hands-on: `docs/connectors/authoring.md`.` The natural
phrase does not land on the guide directly, but it lands one line away from a pointer to it. Combined
with `docs/index.md:34-37`, `CONTRIBUTING.md:5` and the README all naming the guide, this is a minor
inconvenience rather than a findability failure. Documentation scored 8 rather than 7 as a result.

**D5. The unversioned `pulse-core` dependency is a workspace dependency.**
`templates/connector/pyproject.toml.tmpl` declares `pulse-core = { workspace = true }` under
`[tool.uv.sources]`. Inside a uv workspace the connector always resolves to the in-tree kit, so
there is no external version for a connector to pin against and no drift a constraint could catch.
Task A's underlying point survives in a different form - nothing surfaces a kit change at sync time  -
and I scored that. The pinning half of the finding does not apply.

**D6. The `I001` template defect is real but conditional on the package name, which Task A did not
state.** I reproduced it two ways. Rendering out-of-tree as `papchk` (a name sorting before
`pulse_core`) produces exactly 2 `I001` errors under `ruff check --no-fix --select I`; rendering as
`zapchk` (sorting after) passes cleanly. The template's `{{NAME}}` import line lands on the wrong
side of `pulse_core` only for names alphabetically earlier than it. The defect is genuine and worth
fixing, and Task A's framing implies it is unconditional. Fix #4 above reflects the conditional form.

**D7. Cosmetic.** `README.md` is 360 lines, not "~250" as Task A's Step 0 surface table states. No
bearing on any score.

**Accepted without re-running.** Every wall-clock figure in Task A's report - TTHW of 166 s, the
161 s and 394 s `task check` runs, the 403 s `task verify`, the per-target breakdown, the sub-second
scaffold, the 2874-test count - plus the ten error-case outputs (E1 through E10), the
`coverage.exceptions.DataError`, and the `git commit` signing reproduction. Re-running them needs a
fresh clone and roughly twenty minutes of gate time, and re-running a stopwatch would not make the
numbers more trustworthy. Instead I verified the structural cause of each timing claim that carries a
score: `Taskfile.yml:49`'s `CHANGE: ""` default for the 403 s, both `_git` helpers for the six
failures, `rows.py:229-233` for the raw transport error, `pyproject.toml:154` for the mutating lint.
Every one of those causes is present in the tree as described. If a QA pass wants a single number
re-measured, `task verify` with no `CHANGE` is the cheapest to confirm and the most load-bearing.

**Not exercised by either agent.** The full ship path - an OpenSpec change, `task dispatch`, a
worktree, a PR, `task verify CHANGE=<id>` against a real change, `task collect`, `task checkoff`,
`task spec:archive` - and every live-credential target. Dimensions 5 and 7 carry inference from
artifacts for those stretches, which is why dimension 5's confidence is medium-high rather than high.

No PHI appears in this report. No production network call was made. The only writes performed were
this file and two throwaway package renders inside the session scratchpad; no tracked file in the
audited repo was modified and nothing was committed.
