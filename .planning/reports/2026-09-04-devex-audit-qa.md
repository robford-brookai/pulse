# DevEx audit QA - pulse @ b26dee0 - 2026-09-04

**Date**: 2026-09-04
**HEAD under audit**: `b26dee0` on `main`
**Prior audit**: `.planning/reports/2026-09-02-devex-scorecard.md` at `99d9b7a`
**Inputs reviewed**: `.planning/reports/2026-09-04-devex-audit-evidence.md` (Task A),
`.planning/reports/2026-09-04-devex-scorecard.md` (Task B)
**Contract**: `docs/process/devex-audit/task-a.md`, `task-b.md`, `rubric.md`
**Independent work**: second fresh clone with its own timing, 25 cited commands re-run, 5 errors
re-triggered, `mkdocs build -s`, `CHECKSUMS` verified

---

## TL;DR

**Task A: ACCEPT WITH CORRECTIONS. Task B: ACCEPT WITH CORRECTIONS.**

Both reports are honest and mostly reproducible. Every one of the 25 cited commands I re-ran
matched. My independent fresh clone put time-to-hello-world at 140 seconds against Task A's 133,
the same rubric tier. Nine of Task A's ten friction points reproduce exactly.

Three corrections matter.

1. The blindness rule made Task A and Task B wrong about DX measurement. A TTHW gate and a tracked
   per-PR findings ledger both exist in the files they were forbidden to open. Dimension 8 should
   be **8, not 6**, which moves Overall DX from 5.6 to **5.9**. Neither agent is at fault. The
   contract caused it.
2. Task B raised an INFERRED claim to an asserted top-10 defect without checking the mechanism, and
   the mechanism does not hold. The CI compatibility matrix runs `uv run python -m pytest tests` and
   a bare `uv run mypy` whose config is `files = ["src"]`. Neither touches `packages/`. A new
   connector with 3.12-only syntax does not fail that job.
3. Community and Ecosystem fell from 4 to 3 across an interval in which three merged PRs added a
   CODEOWNERS file, an issue form, a PR template and a named owner. One of the two audits is
   miscalibrated on this dimension by at least two points.

The connector composite of 5.8 and every dimension except 7 and 8 can be relied on as written.

---

## 1.0 Verdicts

| Task | Verdict | Basis |
| --- | --- | --- |
| A (evidence) | **ACCEPT WITH CORRECTIONS** | Full coverage of Steps 0-8 and every named deliverable. Ten errors against a required six. Every re-run matched. Four factual corrections, all minor, listed in 6.0. |
| B (scoring) | **ACCEPT WITH CORRECTIONS** | Full coverage of the six scoring duties. Arithmetic correct throughout. One dimension misscored by 2 through no fault of its own, one asserted defect whose mechanism fails, one boomerang-inconsistent score. |

Neither report is rejected. Neither contains a fabricated command, an invented output, or a
citation to a file that does not exist.

---

## 2.0 Coverage checklist

### 2.1 Task A against `docs/process/devex-audit/task-a.md`

| # | Required | Verdict | Where |
| --- | --- | --- | --- |
| 1 | Step 0 target discovery, boomerang disclaimed as Task C's | PASS | Lines 29-84, disclaimer at lines 3-4 |
| 2 | Step 1 real fresh clone into the scratch dir, timed per stage | PASS | Lines 87-161, stage table at 102-108 |
| 3 | TTHW measured clone to green `task check` | PASS | Line 108, 133 s machine time |
| 4 | Cache warmth noted | PASS | Lines 15-17, 134-139 |
| 5 | Step 2 connector scaffold attempted for the persona system | PASS | Lines 210-238, `task connector:new NAME=pocar` run to a green gate |
| 6 | Files and docs read, concepts learned, counted | PASS | Lines 195-208 |
| 7 | Kit public surface compared with spec and reference imports | PASS | Lines 240-275 |
| 8 | Step 3, at least six mistakes triggered, exact text quoted | PASS (10 quoted) | Lines 368-567, E1 to E11 |
| 9 | Each error rated problem, cause, fix | PASS | Summary table, lines 556-567 |
| 10 | Step 4 findability, currency, `mkdocs build -s` | PASS | Lines 580-621 |
| 11 | Eight persona questions answered in order | PASS | Table at lines 623-637, all eight rows |
| 12 | Step 5 template sync, `.ade-template-version`, ADR, archiving, kit change absorption | PASS | Lines 653-702 |
| 13 | Step 6 toolchain pins, editor support, hooks, local/CI parity | PASS | Lines 713-772 |
| 14 | Step 7 CONTRIBUTING, owners, channels, templates, handoffs, work orders, Linear | PASS | Lines 783-843 |
| 15 | Step 8 does the repo measure its own DX | PARTIAL | Lines 854-899. Complete against what the contract let A read, wrong against the repo. See 6.1. |
| 16 | "What a 10 looks like" per step, no number | PASS | Present for all nine steps. No numeric score anywhere in the file. |
| 17 | Journey table with elapsed, action, outcome, stuck points, INFERRED rows marked | PASS | Lines 916-936, two rows marked INFERRED |
| 18 | Top 10 friction points ordered by connector-author impact | PASS | Lines 944-1004 |
| 19 | Method notes and limits | PASS | Lines 1008-1056, including a volunteered blindness-leak disclosure |
| 20 | TESTED / PARTIAL / INFERRED tags throughout | PASS | Applied per claim, not per section |

**Task A coverage: PASS on 19 of 20, PARTIAL on 1.**

### 2.2 Task B against `docs/process/devex-audit/task-b.md`

| # | Required | Verdict | Where |
| --- | --- | --- | --- |
| 1 | Eight dimensions plus Seven Characteristics scored, confidence stated | PASS | Lines 42-51, 75-83 |
| 2 | Getting Started anchored to the TTHW table | PASS | Lines 55-69 |
| 3 | At least two pieces of evidence spot-checked per dimension | PASS | Method column names two or more for all eight. I re-confirmed a sample. |
| 4 | Unverifiable evidence marked and scored at low confidence | PASS | Disputes 4 and 5, dimension 8 dropped to Medium |
| 5 | Connector composite on the fixed slices and weights, arithmetic shown | PASS | Lines 91-103. Weights are the eight specified. Arithmetic correct. |
| 6 | Overall DX as unweighted mean, one decimal | PASS | Line 53 |
| 7 | Gap method for every score below 9, each 10 exceeding defect-free | PASS with a note | Lines 112-215, all eight dimensions. The Seven Characteristics get no gap entries. The brief is ambiguous there and B's reading is reasonable. |
| 8 | Top 10 fixes ranked by impact over effort, S/M/L, tied to a principle number | PASS | Lines 224-235 |
| 9 | "Below the cut" list | PASS | Lines 237-269 |
| 10 | Evidence disputes section | PASS | Lines 273-351, seven entries plus a verified-no-dispute inventory |
| 11 | Task A's file not edited | PASS | A's file mtime 16:29:40, B's 16:37:57. A's is older than B's completion. |

**Task B coverage: PASS on 11 of 11.**

---

## 3.0 Evidence integrity

Twenty-five cited commands re-run in the tracked repo at `b26dee0` or in my own fresh clone, plus
five deliberately re-triggered errors. Every cited file path opened. **No cited path is missing and
no cited file fails to say what is claimed.**

| # | Command or check | Claimed | Observed | Match |
| --- | --- | --- | --- | --- |
| 1 | Independent fresh clone, clone to green `task check` | A: 133 s machine, Competitive tier | 140 s (clone 2 s, `task install` 3 s, `task check` 135 s, rc=0) | Yes, same tier |
| 2 | Fresh clone HEAD | `b26dee0` | `b26dee0` | Yes |
| 3 | `ls packages \| wc -l` | 14 at `b26dee0` | 14 | Yes |
| 4 | `ls openspec/changes/archive \| wc -l` | 20 vs README's "Twenty-two" | 20, `README.md:28` says "Twenty-two" | Yes |
| 5 | `wc -l docs/index.md` | 8 lines, badge stub | 8 | Yes |
| 6 | `git ls-files \| grep -ci pocar` | 15 | 15 | Yes |
| 7 | `CODEOWNERS` size and content | 39 bytes, two lines, one wildcard | 39 bytes, `* @robford-brookai`, at `.github/CODEOWNERS` | Yes, path was not cited |
| 8 | `.github/ISSUE_TEMPLATE/` contents | only `attended-run.yml` | only `attended-run.yml` | Yes |
| 9 | `packages/pulse-core/pyproject.toml:3` | `version = "0.1.0"` | line 3, `version = "0.1.0"` | Yes |
| 10 | `ls CHANGELOG*` | none anywhere | no matches | Yes |
| 11 | `fail_under` location | A cites `pyproject.toml:150`, B corrects to 148 | line 148 | B is right |
| 12 | `verify` target location | A cites `Taskfile.yml:566-572`, B corrects to 546-552 | 546-552, and it declares no `requires` | B is right, claim holds |
| 13 | `task test` narrowing | `Taskfile.yml:154-166`, no package variable | 154-166, no variable | Yes |
| 14 | `pulse_core.connector.__all__` | 26 names, `Jitter` absent | 26 names, `Jitter` absent, **`Sleeper` present** | Partial, see 6.2 |
| 15 | Submodule imports in reference connectors | 3 sites cited | 3 cited sites confirmed, plus `billing-connector/tests/test_receipts.py:11` and `verdict-relay/declarer.py:67` | Yes, understated |
| 16 | `templates/connector/` contents | 9 `.tmpl` files, no `factories.py` or `test_config.py` | 9 files, exactly as listed | Yes |
| 17 | Guide rendered-tree diagram | `docs/connectors/authoring.md:102-116` promises 4 test files, 3 do not exist | Confirmed verbatim, README.md.tmpl undiagrammed | Yes |
| 18 | Guide "root, not submodules" rule | guide line 37 | Confirmed at lines 36-38 | Yes |
| 19 | `scripts/connector_new.py --help` | no direction flag | `--name --dest --root --template --force --print-registrations --apply-registrations` | Yes |
| 20 | Guide unlinked from README, CLAUDE, AGENTS, CONTRIBUTING, index | no matches for "authoring" | zero matches across all five | Yes |
| 21 | `grep -ril "getting started"` | task-a.md only | task-a.md **and task-b.md** | Understated, immaterial |
| 22 | `.pre-commit-config.yaml` hook ids | 11 ids, no mypy | 11 ids, no mypy, matches the list verbatim | Yes |
| 23 | `openlore-drift` file scope | `.pre-commit-config.yaml:42`, `^(src/.*\.py\|openspec/.*)$` | exact | Yes |
| 24 | `uv run mkdocs build -s` | clean, only the Material 2.0 upstream banner | rc=0, `Documentation built in 0.62 seconds`, banner only | Yes |
| 25 | `main.yml` three jobs | `quality` runs `task check` at line 50, matrix 3.10-3.14, `check-docs` | lines 11/50, 52/56/71/74, 78/96/99 | Yes |
| 26 | `ci-health.yml` trigger | `workflow_dispatch: {}` only, checkout pinned `# v4.0` | exact | Yes |
| 27 | `git log` authorship | 947 commits, one author | 947, one author, 17 in the connector areas | Yes |
| 28 | `.gitignore` lines 144 and 227 | `.envrc`, `.openlore/` | exact | Yes |
| 29 | `.ade-template-version` | `a1de595b...41967` | exact | Yes |
| 30 | `openspec/specs/connector-kit/spec.md` | 83 lines, zero deprecation or version language | 83 lines, zero matches | Yes |
| 31 | Guide section 9, nine paths resolve | 9 of 9 | 9 of 9 exist | Yes |
| 32 | `openlore init --force` write-down sites | A: "the only place is `bootstrap.sh:177`" | also `scripts/orca-worktree-setup.sh:17` and `tests/scaffold/cat7_gates_hooks.sh:94` | No, see 6.3 |

### 3.1 Errors re-triggered

| Error | Claimed text | Observed | Match |
| --- | --- | --- | --- |
| E1 `task connector:new` no NAME | `task: Task "connector:new" cancelled because it is missing required variables: NAME` | identical | Yes |
| E2 positional script arg | argparse usage block, `error: the following arguments are required: --name` | identical | Yes |
| E4 `task dispatch --change` | global help screen, `unknown flag: --change` last | identical, 67 lines of output before the error | Yes |
| E9 missing tool on PATH | `"openspec": executable file not found in $PATH`, exit 127 | identical | Yes |
| E10 fresh clone, `lore:drift` | `[error] No openlore configuration found. Run "openlore init" first.`, and `lore:analyze` fails identically | identical in my own fresh clone, `.openlore/` absent | Yes |

E10's second half, that `task verify` reaches `lore:drift` before anything complains about a
missing `CHANGE`, is confirmed mechanically rather than by a full re-run. `verify` at
`Taskfile.yml:546-552` runs `check`, `workflow:lint:linear`, `lore:drift`, `spec:validate` in that
order, and `spec:validate` is the only one of the four that declares `requires: vars: [CHANGE]`.
It is never reached. The claim holds.

E5, E6, E7, E8 need a rendered `packages/pocar` and deliberate source breakage, which I did not
reproduce under the read-only constraint. Task B verified their mechanism from
`templates/connector/src/{{NAME}}/config.py.tmpl` and I accept that treatment.

### 3.2 Independent TTHW

```
QA fresh clone, /private/tmp/.../scratchpad/audit2/qa-fresh, HEAD b26dee0
clone_seconds=2
task_install_seconds=3   rc=0
task_check_seconds=135   rc=0
TTHW_machine_seconds=140

Task A, same machine, separate clone:  133 s
Delta: 7 s, 5.3 percent
Rubric tier for both: Competitive (120-300 s)
```

Same caveat applies to mine as to Task A's. My clone shared the same warm `~/.cache/uv`. **Cold
TTHW remains unmeasured by all three of us.**

---

## 4.0 Score calibration

Checks applied per score: (a) verifiable evidence cited, (b) consistent with the rubric wording and
the TTHW table, (c) a 10 that exceeds defect-free, (d) fixed weights and correct arithmetic, (e)
overall is the unweighted mean.

| Dim | Score | (a) evidence | (b) rubric fit | (c) 10 exceeds defect-free | QA position |
| --- | --- | --- | --- | --- | --- |
| 1 Getting Started | 7 | Yes, re-verified | Yes. Competitive is the rubric's baseline tier, and 7 is "good, minor gaps". | Yes, "published and defended, not discovered by an auditor" | **Hold 7** |
| 2 API/CLI/SDK | 6 | Yes | Yes. Working scaffold against a wrong diagram, a missing export and a contradicted rule is "acceptable, works with friction". | Yes, the scaffold teaches the direction | **Hold 6** |
| 3 Error messages | 6 | Yes, four re-triggered | Yes. Six of ten state the fix. | Yes, collect-every-problem as the house pattern | **Hold 6** |
| 4 Documentation | 6 | Yes | Yes | Yes, "docs cannot drift because drift is a test failure" | **Hold 6** |
| 5 Upgrade path | 5 | Yes | Yes. Strong for the template, absent for the kit. | Yes, deprecation warnings naming replacements | **Hold 5** |
| 6 Developer environment | 6 | Yes, but one rationale is wrong | Yes, on the surviving evidence | Yes, parity enforced by `cat4` | **Hold 6, rewrite the rationale.** See 6.4. |
| 7 Community and ecosystem | 3 | Yes | Contested. See 4.1. | Yes, a second person landing a connector | **Flagged. Recommend 4 to 5.** |
| 8 DX measurement | 6 | Incomplete through no fault of B | No. See 4.2. | Yes | **Move to 8.** |

### 4.1 Flag: Community and Ecosystem, scored 3

The prior audit scored this dimension **4** with, in its own words, "no `.github/ISSUE_TEMPLATE`, no
`CODEOWNERS`, `CONTRIBUTING.md` is 13 lines, no channel or owner named anywhere". Since then PR
**#361** landed `CODEOWNERS`, an issue form, a PR template and an owner line in `CONTRIBUTING.md`,
which is now 23 lines and names the owner plus the Slack gap. The rubric's internal interpretation
asks for four things. Two moved from absent to partially present. One (a channel or person named in
`README.md`) is still absent. One (someone other than the owner landing a connector) is still
absent and cannot be manufactured.

The evidence moved up and the score moved down. Both numbers cannot be right. Either the prior 4 was
generous or the current 3 is harsh, and the gap between them is at least two points of calibration
drift. My reading of the rubric puts the current state at **4**, possibly 5, because the wildcard
`CODEOWNERS`, the PR template with its explicit PHI checkbox, 17 collected handoff directories and a
written Linear grain are real ecosystem machinery. The binding constraint that justifies staying
below 5 is genuine: 947 of 947 commits by one author.

This is the only score whose movement across the two audits is not explained by the merged history.

### 4.2 Flag: DX Measurement, scored 6, should be 8

Task A concluded "Nothing records TTHW... there is no target, no baseline, and no trend" and
"nothing records a drift count as a metric". Task B scored dimension 8 at 6 on that basis and built
its gap entry around inventing a TTHW metric and a trend file. Both were forbidden from opening
`tests/scaffold/cat10_devex.py`, `scripts/devex/` and `.planning/devex/`. I am not. What is in
there:

- `tests/scaffold/cat10_devex.py:286-302`, `test_tthw_fresh_clone_to_synced_env`, clones the repo,
  runs `uv sync --all-packages`, and prints `TTHW_INSTALL_SECONDS=<n>` with the docstring "for the
  ledger". A TTHW gate exists.
- `.planning/devex/loop.jsonl` is a **tracked** per-PR series carrying `{date, kind, ref, pr, task,
  open_findings}`. A trend exists.
- Each audit finding is a `pytest.mark.xfail(strict=True)` test in `cat10_devex.py`, so a fix that
  regresses turns the gate red and a finding that is silently fixed is reported as
  `fixed_but_still_marked`. `scripts/devex/check.py` emits `devex_open_findings` from that count and
  writes a dated JSON artifact.
- `docs/process/devex-audit/CHECKSUMS` freezes the rubric and all three task briefs. I ran
  `uv run python scripts/devex/check.py --verify-only`: **rc=0, the protocol is unmodified.**

A repo with a checksummed measurement protocol, a strict-xfail gate per open finding, a tracked
per-PR series and a TTHW gate is not "acceptable, works with friction". It is "good, minor gaps",
which is 7 to 8. The remaining gaps are real and keep it off 9: the TTHW gate measures clone plus
`uv sync` rather than clone to a green `task check`, it is `@pytest.mark.slow` so it runs only under
`task test:all`, its number goes to stderr and reaches no file, no `task` target times itself, and
`ci-health.yml` is still manual. **I score dimension 8 at 8.**

Nothing here is a failure by Task A or Task B. Both stated the blindness constraint, both marked the
dimension as limited by it, and Task B explicitly dropped it to Medium confidence "for this reason
and no other". The contract produced the error. The fix belongs in `task-a.md` and `task-b.md`, not
in a correction to either agent.

### 4.3 Arithmetic and weights

| Check | Result |
| --- | --- |
| Composite weights are the eight fixed ones (30/20/15/15/10/5/3/2) | Yes, and identical to the prior audit's, so the two composites are comparable |
| Composite arithmetic | 180+120+90+90+60+20+9+8 = 577. Correct. 577/100 = 5.77, reported 5.8. Correct. |
| Overall is the unweighted mean of the eight dimensions | 7+6+6+6+5+6+3+6 = 45. 45/8 = 5.625, reported 5.6. Correct. |
| Slice derivations traceable to dimension scores | Yes. Five verbatim, three adjusted with a stated reason. |

### 4.4 Corrected numbers

Applying only the dimension 8 move, which is the one correction I hold with confidence:

```
Dimension 8:          6  ->  8
Overall DX:      45/8 = 5.6  ->  47/8 = 5.875 -> 5.9
Composite slice "Measurement of author experience" (weight 2):  4 -> 6
Composite total:      577  ->  581
Connector author DX:  5.77 -> 5.81, both round to 5.8  (UNCHANGED)
```

The headline connector composite of **5.8 survives the correction**. Overall DX moves to **5.9**.
If Community also moves to 4, Overall reaches 6.0 and the composite reaches 5.8 still, since that
slice carries weight 3.

---

## 5.0 Boomerang, 2026-09-02 (`99d9b7a`) to 2026-09-04 (`b26dee0`)

66 commits, 22 merged PRs on `main` across the interval.

### 5.1 Dimensions

| Dimension | Prior | Current | Delta | Merged PRs accounting for it |
| --- | --- | --- | --- | --- |
| Getting Started | 4 | 7 | **+3** | #356 README rewrite, #364 README prerequisites block (1.9), #358 `task install` installs pre-commit hooks (1.5), #360 `bootstrap.sh` refuses to run in a generated repo (1.7). The prior audit named exactly three defects here. All three are fixed by these PRs. |
| API / CLI / SDK | 4 | 6 | +2 | #362 kit exports the declare layer (1.1), #368 connector scaffold template and `connector_new.py` (1.3), #373 `connector:new` applies the eight registrations (1.4) |
| Error messages | 3 | 6 | **+3** | #359 `requires: vars: [CHANGE]` on the nine CHANGE-taking targets (1.6), #365 `Config.from_env()` collects every missing and invalid variable (2.1) |
| Documentation | 3 | 6 | **+3** | #367 connector authoring guide (1.2), #370 PULSE-branded docs site, full nav (2.3), #371 one canonical connector spec (2.2), #374 guide names `task connector:new` and the nine sites |
| Upgrade path | 5 | 5 | 0 | None landed. Correctly flat. |
| Developer environment | 5 | 6 | +1 | #363 pin real action SHAs, replace nonexistent re-run action (1.8) |
| Community and ecosystem | 4 | 3 | **-1** | #361 CODEOWNERS, issue form, PR template, owner in CONTRIBUTING (2.5). **The PR moves the evidence up and the score moved down.** See 4.1. |
| DX measurement | 2 | 6 | **+4** | #357 devex-eight wave 0, findings gate, frozen audit protocol, QA-corrected baseline (0.1, 0.2, 0.3) |
| **Overall DX** | **3.8** | **5.6** | **+1.8** | |

### 5.2 Characteristics and composite

| Item | Prior | Current | Delta | Provenance |
| --- | --- | --- | --- | --- |
| Usable | 3 | 6 | **+3** | #362, #365, #368, #373, #358. The prior audit's "first line of code raises" and "hooks the contributor guide promises do not exist" are both fixed. |
| Credible | 4 | 5 | +1 | #363 (real SHAs), #371 (one canonical spec) |
| Findable | 2 | 4 | +2 | #370 (docs site is PULSE's, full nav), #367 (the guide exists) |
| Useful | 6 | 7 | +1 | #368, #373 |
| Valuable | 5 | 7 | +2 | #368, #373 (nine registrations in one sub-second command) |
| Accessible | 3 | 5 | +2 | #364 (prerequisites stated), #356 |
| Desirable | 3 | 5 | +2 | The above, cumulatively |
| **Connector author DX composite** | **2.4** | **5.8** | **+3.4** | Same fixed weights both audits, so the comparison is valid |

### 5.3 Verdict on the boomerang

**Every dimension and characteristic that rose by 3 or more has merged PRs behind it.** Getting
Started, Error Messages, Documentation, DX Measurement and Usable all trace to named PRs that fix
the exact defects the prior audit cited. There is no rise without provenance, and therefore no
finding against Task B on this axis.

The one anomaly runs the other way: Community and Ecosystem fell one point across a PR that
materially improved it.

---

## 6.0 Required corrections, by severity

### 6.1 High: Task B, dimension 8 is misscored by 2, and the cause is the contract

Dimension 8 should be **8**, moving Overall DX to **5.9**. The connector composite is unchanged at
5.8. Do not treat this as a Task B error. Fix the contract: `task-a.md` and `task-b.md` should
either drop `.planning/devex/loop.jsonl` and the `cat10_devex.py` TTHW gate from the blindness list,
or state plainly that dimension 8 is scored by Task C alone. As written, the blindness rule
guarantees that the one dimension measuring the repo's self-measurement is scored by two agents who
are forbidden from seeing the self-measurement.

### 6.2 High: Task B, fix #10 and dispute #6 assert a CI trap that does not exist

Task B writes that the parity claim "needs no construction to be a defect" and that "a connector
author with 3.12+ syntax and a scaffold-supplied `requires-python = ">=3.10"` passes locally and
fails CI". The mechanism fails on inspection.

```
.github/workflows/main.yml:71   run: uv run python -m pytest tests
.github/workflows/main.yml:74   run: uv run mypy
pyproject.toml:96-97            [tool.mypy]
                                files = ["src"]
```

The matrix job's pytest step collects `tests/` only, which is the scaffold gates and repo-level
tests, not `packages/*/tests`. The mypy step takes no arguments, so it uses `files = ["src"]`, which
is `src/pkg_pulse/`, not `TYPED_PATHS` and not `packages/`. **A new connector package under
`packages/` is invisible to both steps of the compatibility matrix.** The author does not fail CI.

Task A marked this INFERRED and said "I did not construct the failing case". That was the correct
posture. Task B escalated it to an asserted top-10 defect on reasoning alone.

The underlying observation survives: `task check` cannot reproduce the `tests-and-type-check` job,
so "green locally means green in CI" is imprecise as written in `README.md:283` and `CLAUDE.md`.
Dimension 6 stays at 6. Rewrite fix #10's rationale to drop the connector-author trap and keep the
reproducibility gap, and demote its urgency accordingly.

### 6.3 Medium: Task A, three factual corrections

1. **`Sleeper` is exported.** `pulse_core.connector.__all__` contains `Sleeper`. Only `Jitter` is
   missing. Task A's Step 2 states this correctly but its "what a 10 looks like" says "`Jitter` and
   `Sleeper` join `__all__`", and Task B carried the error into ranked fix #5 ("Export `Jitter` and
   `Sleeper`"). Correct both to `Jitter` alone.
2. **`openlore init --force` is written down in three places, not one.** Task A says
   "the only place `openlore init --force` is written down is `bootstrap.sh:177`". It also appears
   at `scripts/orca-worktree-setup.sh:17` and, as `openlore init`, at
   `tests/scaffold/cat7_gates_hooks.sh:94`. The substance holds. No document tells a connector
   author to run it and no `task` target does, so `task verify` still cannot pass on a fresh clone
   by any documented path. Narrow the claim to "no repo document and no task target".
3. **`CODEOWNERS` is cited without a path.** It is `.github/CODEOWNERS`. The contract requires every
   claim to cite a file path. Size and content are exactly as reported.

### 6.4 Medium: Task B, dimension 6's rationale

Dimension 6's score of 6 is right on the surviving evidence, which is real: no `.nvmrc` while CI
pins node 22, no `.editorconfig`, no `.vscode/extensions.json`, no devcontainer, `.envrc` gitignored,
and a CI job `task check` cannot reproduce. Strike the connector-author trap from the reasoning per
6.2. The score does not move.

### 6.5 Low: Task B, Community and Ecosystem needs a boomerang justification

Whatever the final number, the report should say why a dimension fell across a PR that added a
CODEOWNERS file, an issue form, a PR template and a named owner. My recommendation is **4**. If
Task B keeps 3, the reason belongs in the text.

### 6.6 Low: Task A, two understated counts

`grep -ril "getting started"` now hits `task-a.md` and `task-b.md`, not `task-a.md` alone. Submodule
imports of `pulse_core.connector.declare` occur at five non-kit sites, not three (add
`packages/billing-connector/tests/test_receipts.py:11` and
`packages/verdict-relay/src/verdict_relay/declarer.py:67`). Both understate Task A's own case.

### 6.7 Low: PII in Task A's Step 7

Task A quotes `git log --format='%an <%ae>'` output verbatim, which puts a named individual's work
email address in the report. Replace it with the author count and the role, as this QA report does.
No PHI appears in either report.

---

## 7.0 Scope

| Check | Result |
| --- | --- |
| Connectors weighted heaviest in Task A | Yes. Persona is a connector author throughout, Step 2 is connector-focused, the top-10 is explicitly "ordered by impact on connector authors", the journey table is a connector-author journey. |
| Connectors weighted heaviest in Task B | Yes. The connector composite is the headline number and the fixed slices put 50 percent on kit ergonomics plus connector documentation. |
| Same weights as the prior audit, so the composite is comparable | Yes. 30/20/15/15/10/5/3/2 in both. |
| Whole repo still covered, not only connectors | Yes. Both reports score all eight dimensions and the Seven Characteristics repo-wide, and Task A's Step 0 inventories 67 task targets, 42 docs pages, 22 design docs, 48 specs, 15 scaffold gates and 17 handoff directories. |

---

## 8.0 Hygiene

| Check | Result |
| --- | --- |
| PHI in either report | **None.** The one connection string, `postgresql://ledger:pw@db:5432/ledger`, is a synthetic literal Task A wrote to trip the credential gate and discloses itself as such. Config values quoted are variable names, never secrets. |
| PII | One work email address in a quoted `git log` in Task A. See 6.7. |
| Tracked files modified by A or B | **None attributable.** `git status --porcelain` shows one modified tracked file, `.mcp.json`, which adds an MCP server entry, is session environment configuration rather than audit output, and has mtime 15:59:06, before Task A's report at 16:29:40. Not audit-caused, but the working tree is not clean and the coordinator should know. |
| Untracked additions | `2026-09-04-devex-audit-evidence.md` and `2026-09-04-devex-scorecard.md`, as expected, plus `2026-09-02-connector-agent-contract.md` with mtime Sep 2 21:35, pre-existing and unrelated. |
| Commits | **None.** `HEAD` is `b26dee0` and the reflog's most recent entry is the fast-forward pull that set it. Task A's test commit was made inside its throwaway clone and is disclosed. |
| Em-dashes | **Task B: zero. Task A: 8 occurrences, all inside quoted material** (guide prose at lines 251 and 266, a quoted tree diagram at 284, and command or assertion output at 429-431, 444, 456). Quoted output must not be altered, so this is compliant. No authored prose in either report uses one. |
| Emojis | Zero in both. |
| `CHECKSUMS` verifies | **Yes.** `uv run python scripts/devex/check.py --verify-only` returns rc=0. The rubric and all three task briefs are unmodified. |
| Blindness held | Task A discloses two incidental leaks in its Method notes and neither shaped a finding. Task B lists the five files it did not open. I found no evidence in either report that could only have come from an off-limits file. |
| One artifact worth noting | `.planning/devex/2026-09-04-check.json` exists in the tracked repo with mtime 16:06:44, inside Task A's window. It is gitignored (`.gitignore:245`), so no tracked file changed either way. Whether Task A ran `task devex:check` in the tracked repo rather than its clone, or the coordinator ran it during setup, cannot be resolved from the artifact. Low severity, worth a one-line answer from the coordinator. |

---

## 9.0 Trust statement

**Rely on these as written.**

- The **connector author DX composite of 5.8**. It survives every correction in this report,
  including the dimension 8 move, and it uses the same fixed weights as the prior audit, so the
  2.4 to 5.8 comparison is sound.
- **Dimensions 1 through 6**: Getting Started 7, API/CLI/SDK 6, Error Messages 6, Documentation 6,
  Upgrade Path 5, Developer Environment 6. All evidence re-verified. Dimension 6's number is right
  even though one sentence of its rationale is not.
- The **TTHW tier**. Two independent fresh clones, 133 s and 140 s, both Competitive. The tier is
  solid. The **absolute number is warm-cache only** in all three measurements and cold TTHW remains
  unmeasured.
- **Every one of Task A's ten friction points**, with the three narrowings in 6.3 and 6.6. Nothing
  in the top 10 is fabricated or unreproducible.
- The **Seven Characteristics** scores and the **boomerang deltas** for dimensions 1 through 6.
- All arithmetic in Task B: the composite, the overall mean, and every slice derivation.

**Do not rely on these without the correction.**

- **Dimension 8, DX Measurement, at 6.** Use **8**. Consequently use **Overall DX 5.9**, not 5.6.
- **Dimension 7, Community and Ecosystem, at 3.** Treat as unresolved between 3 and 5. It is the one
  score inconsistent with the merged history.
- **Ranked fix #10's rationale and evidence dispute #6.** The CI compatibility trap they describe
  does not exist. The reproducibility gap they rest on does.
- **"Export `Jitter` and `Sleeper`"** in ranked fix #5. Only `Jitter` is missing.
- **Task A's Step 8 conclusion** that the repo records no TTHW, no baseline and no trend. It records
  all three, in files Task A was forbidden to open.

**Next step for the coordinator.** Apply 6.1 and 6.2 to the scorecard, then amend the blindness
lists in `task-a.md` and `task-b.md` and re-freeze `CHECKSUMS`, because the current wording makes
dimension 8 unscoreable by design.
