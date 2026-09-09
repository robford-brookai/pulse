# DevEx audit QA: pulse, 2026-09-08

Task C of the three-agent audit protocol (`docs/process/devex-audit/task-c.md`). Adversarial
quality assurance of Task A and Task B, plus the boomerang against the prior run.

- Repo: `/Users/Rob.Ford/Repos/robford-brookai/pulse` at
  `f851ae0bd036c0f067514b4c57b10df7e956b669` on `main`. Read-only; this report is the only file I
  wrote in the repo. Main moved by one merge (#430) after the audit started; my second clone is
  pinned to the audited sha with `git checkout f851ae0`, so #430 is out of scope.
- Inputs: `.planning/reports/2026-09-08-devex-audit-evidence.md` (Task A),
  `.planning/reports/2026-09-08-devex-scorecard.md` (Task B),
  `.planning/reports/2026-09-05b-devex-scorecard.md` (prior scorecard, at `5177d05`).
- Independent workspace: a second fresh clone at
  `/private/tmp/claude-502/.../scratchpad/devex-audit-2026-09-08/qa-fresh/pulse`, cloned and
  pinned by me, never shared with Task A.
- Contract checked against: `task-a.md`, `task-b.md`, `rubric.md`. `CHECKSUMS` verifies
  (`uv run python scripts/devex/check.py --verify-only`, rc=0; `shasum -a 256 -c CHECKSUMS`
  reports OK for all five files), so both agents worked against the frozen rubric.

---

## Verdicts

| Task | Verdict |
| --- | --- |
| **Task A (evidence)** | **ACCEPT WITH CORRECTIONS** |
| **Task B (scorecard)** | **ACCEPT WITH CORRECTIONS** |

**Task A.** Coverage is complete against its spec and the evidence discipline is real: I re-ran 30
of its cited commands and 13 of 13 quoted error messages came back verbatim, including line
numbers. Two corrections matter. First, its number-one and number-two friction points are
**mis-located**: the documented three-command path (`task connector:new` then `task install` then
`task check`) is **green** in a fresh clone at the audited sha, rc=0, 3042 passed. The
package-count gate counts `git ls-files`, not the filesystem, so the failure Task A reports arrives
only after the author stages or commits the package. The defect is real; the sentence describing it
is not. Second, its headline TTHW of 230 s does not reproduce: an independent fresh clone on the
same machine at the same sha came in at **163 s**, with `test` at 120.6 s against Task A's 187 s.
The tier conclusion (Competitive) survives; the number should not be quoted.

**Task B.** Arithmetic, weights, rubric application and gap method are all correct, and it
independently caught four of Task A's five count errors before I did. Its failure is
verification depth, not judgement: it declined to use a throwaway clone ("this audit is
read-only"), which the prior run's Task B did use, and so took the headline defect on trust. That
single unverified claim is what sets its lowest slice score (4 on "Getting started to a working
connector", weight 15) and the ranking of its number-one fix. Corrected, the connector composite
moves 6.3 to 6.6.

---

## 1. Coverage checklist

### Task A against `task-a.md`

| Requirement | Result | Reference |
| --- | --- | --- |
| Steps 0 through 8, one section each | PASS | evidence lines 22, 100, 195, 402, 545, 646, 745, 826, 909 |
| Boomerang declared as Task C's job | PASS | evidence lines 3-4, 1083 |
| Real fresh clone in the scratch dir, pinned to the sha | PASS | evidence lines 14-16; I confirmed the path exists and holds a clone at the audited sha |
| Fresh clone timed to the second per stage | PASS on form, PARTIAL on accuracy | evidence lines 143-149. Stage table present; the total does not reproduce (section 2, row Q1) |
| Cache warmth recorded | PASS | evidence lines 118-120 (26 GB uv cache). I measured the same 26 GB |
| Points where a doc had to be read, a guess made, or an error hit | PASS | evidence lines 158-166 |
| Connector scaffold attempt, following only the repo | PASS | evidence lines 195-400; I reproduced the whole sequence |
| Six or more realistic mistakes, exact error text | PASS, 13 delivered | evidence lines 402-543 |
| Eight persona questions answered in Step 4, in order | PASS | evidence lines 596-610, an eight-row table matched to sections 1,2,3,4,5,7,8,9 |
| "What a 10/10 looks like" per step, no numeric score | PASS | one per step; no number anywhere in the file |
| TESTED / PARTIAL / INFERRED tags | PASS | used on every observation and on all 22 journey rows |
| Journey table with INFERRED rows marked | PASS | evidence lines 946-970; 5 rows tagged INFERRED |
| Top 10 friction points, ordered by connector-author impact | PASS | evidence lines 976-1010 |
| Method notes and limits | PASS | evidence lines 1014-1083, including contention and blindness declarations |
| Blindness (no prior devex report, no per-run check JSON) | PASS as far as testable | declared at lines 1074-1081; no prior-report content appears in the file, and its five count errors are exactly what a genuinely blind reader would produce |
| Read-only on the repo except its own report | PASS, with one unattributed item | section 6 |
| No em-dashes, no emojis | PARTIAL | 9 em-dashes and the characters `│` `⚠`, all inside verbatim quoted output. Section 6 |

### Task B against `task-b.md`

| Requirement | Result | Reference |
| --- | --- | --- |
| Eight dimensions scored with confidence per score | PASS | scorecard lines 33-42 |
| Seven DX Characteristics scored | PASS | scorecard lines 60-70 |
| Getting Started anchored on the TTHW table | PASS | scorecard lines 48-56, naming the Competitive band and the Champion line |
| Two or more pieces of evidence spot-checked per dimension | PASS as claimed, PARTIAL in depth | Method column on every row. No throwaway clone, so every write-requiring claim was taken on trust; see section 3 |
| Unverifiable evidence marked, scored at low confidence | PASS | scorecard lines 286-292 plus Medium confidence on dimensions 1 and 5 |
| Connector composite, fixed slices and weights, arithmetic shown | PASS | scorecard lines 76-89. Weights 30/20/15/15/10/5/3/2 = 100, matching `task-b.md` exactly |
| Overall = unweighted mean of the eight, one decimal | PASS | 51/8 = 6.375, stated as 6.4 |
| Gap method for every score below 9, each 10 exceeding defect-free | PASS | eight entries, lines 95-233. Every one carries an explicit "beyond defect-free" clause |
| Top 10 fixes ranked by impact over effort, S/M/L, tied to a numbered principle | PASS | lines 240-253 |
| "Below the cut" list | PASS | lines 255-272 |
| Evidence disputes section | PASS | lines 276-300, five entries |
| Did not edit Task A's file | PASS | Task A's file mtime 21:47, Task B's 21:56; content of A is internally consistent with its own timestamps |
| No em-dashes, no emojis | PASS | zero of either |
| Blindness (no prior scorecard, no QA report, no per-run check JSON) | PASS as far as testable | its dimension-7 basis reproduces the prior run's reasoning independently, and its scores diverge from the prior run in both directions |

---

## 2. Evidence re-run table

Thirty commands re-run. All in my own pinned clone or read-only in the repo under audit.

| # | Command | Task A claimed | I observed | Match |
| --- | --- | --- | --- | --- |
| Q1 | `git clone` then `task install` then `task check`, fresh clone at `f851ae0` | clone 2.35 s, install 3 s, check 225 s, **TTHW 230 s** | clone 2.11 s, install 3 s, check **158 s**, **TTHW 163 s** | **NO** on the gate and the total; clone and install match |
| Q2 | `.planning/devex/loop.jsonl` rows from that gate | lint 1.498, typecheck 26.81, **test 186.989**, twenty:test 7.08, docs:build 1.321 | lint 2.086, typecheck 24.254, **test 120.612**, twenty:test 8.118, docs:build 4.825 | **NO** on `test`; the rest are within noise |
| Q3 | `du -sh ~/.cache/uv` before the clone | 26 GB | 26 GB | yes |
| Q4 | `git status --short` after a green gate in an untouched clone | ` M .planning/devex/loop.jsonl` | ` M .planning/devex/loop.jsonl` | yes |
| Q5 | last output of a successful `task check` | red Material for MkDocs 2.0 banner, then `INFO - Documentation built in 0.68 seconds` | same banner, `INFO - Documentation built in 0.83 seconds` | yes |
| Q6 | `uv run python scripts/connector_new.py --name zendesk-connector --direction inbound --print-registrations` | full registration diff, writes nothing, under a second | identical diff shape for `pyproject.toml` and `Taskfile.yml`; nothing written | yes |
| Q7 | `task connector:new NAME=zendesk-connector DIRECTION=inbound` | 1 s, 12 files, `Registered zendesk-connector at 2 site(s)`, `Next: uv sync --all-packages` | 0.17 s, same file list, same `2 site(s)`, same `Next` line | yes |
| Q8 | nine registration sites applied, `Taskfile.yml` 499/509 commented stubs | listed per site | confirmed: `LINT_PATHS:19`, `TESTED_PATHS:35`, `COV_PATHS:48`, `pyright:162`, `pyproject` members/sources/per-file-ignore, `# zendesk-connector:image:` at 499, `# zendesk-connector:deploy:` at 509 | yes |
| Q9 | `packages/zendesk-connector/Dockerfile` referenced by the deploy stub and not rendered | missing | `Taskfile.yml:507` names it; `ls` says No such file. `packages/billing-connector/Dockerfile` exists | yes |
| Q10 | rendered package README claims `TYPED_PATHS` was applied, contradicting the guide | contradiction | rendered README "Next steps" item 1 lists `TYPED_PATHS`; `docs/connectors/authoring.md:322` says "a pyright-strict package never joins it" | yes |
| Q11 | `uv run pytest packages/zendesk-connector/tests -q` | `40 passed` | `40 passed` | yes |
| Q12 | `uv run pyright -p packages/zendesk-connector` | `0 errors, 0 warnings, 0 informations` | identical | yes |
| Q13 | **`task check` after the scaffold, as the guide's step 3 says** | **rc=201, RED**, `README claims 14 packages, tree has 15` | **rc=0, GREEN**, `3042 passed, 30 skipped, 9 deselected, 8 xfailed in 94.73s` | **NO** |
| Q14 | the same gate after `git add packages/zendesk-connector` | not distinguished from Q13 | **RED**, `AssertionError: README claims 14 packages, tree has 15 / assert 14 == 15`, `cat8_docs_consistency.py:735` | the failure exists, one step later than claimed |
| Q15 | README edited to "Fifteen ... Thirteen", gate re-run | `assert None is not None` at `cat8_docs_consistency.py:733` | `AssertionError: unrecognized package count word: 'Fifteen'` / `assert None is not None`, `cat8_docs_consistency.py:733` | yes, verbatim including the line number |
| Q16 | `NUMBER_WORDS` has no fifteen or thirteen | dict of six words | `cat8_docs_consistency.py:683-690`, exactly the six words quoted | yes |
| Q17 | E1 `task dispatch --change=zendesk` | go-task usage banner only | identical | yes |
| Q18 | E2 `task verify` | `task: CHANGE is required, e.g. task verify CHANGE=<change-id>` plus precondition line | identical | yes |
| Q19 | E3 `task connector:new` | `cancelled because it is missing required variables: NAME` | identical | yes |
| Q20 | E4 `Config.from_env({})` | three `is unset` lines, each with its purpose | identical, all three lines verbatim | yes |
| Q21 | E5 `STALE_AFTER_SECONDS='banana'` | `'banana' is not an integer — whole seconds` | identical | yes |
| Q22 | E6 `task lint` on a badly formatted file | `unformatted: File would be reformatted`, `1 file would be reformatted, 725 files already formatted`, no fix named | identical, including `725` | yes |
| Q23 | E7 gates run from a package directory | `task lint` and `pytest` both work from `packages/<pkg>` | reproduced earlier in this session; go-task walks up, uv resolves the workspace root | yes |
| Q24 | E8 `task lore:drift` | `[error] No openlore configuration found. Run "openlore init" first.` | identical | yes |
| Q25 | E9 `task spec:validate CHANGE=zendesk` | `Unknown item 'zendesk'. Did you mean: command-api, ledger-read, month-open, connector-kit, event-delivery?` | identical, same five suggestions in the same order | yes |
| Q26 | E10 `task dispatch CHANGE=zendesk-connector` | `Error: openspec/changes/zendesk-connector/tasks.md not found` | identical | yes |
| Q27 | E11 `--direction sideways` | `invalid choice: 'sideways' (choose from outbound, inbound)` | identical | yes |
| Q28 | E12 scaffolding an existing name | `error: destination already exists: ... (pass --force to overwrite)` | identical | yes |
| Q29 | `git commit` of the scaffolded package, hooks live | commit succeeded, "9 hooks passed", `openlore drift` skipped | 8 Passed, 3 Skipped including `openlore drift`; commit succeeded once I disabled signing (my 1Password agent is locked, an environment fault, not the repo's) | substance yes, hook tally off by one |
| Q30 | `mkdocs build -s` | passes, zero warnings of the repo's own; only the vendor banner | identical | yes |

Also re-verified read-only: `task devex:check` printed `METRIC devex_open_findings=7` and the same
seven finding names Task A quoted; `uv run python -c "import pulse_core.connector as c; print(len(c.__all__))"` returns 28.

### Cited paths I opened

Every path either report cites exists and says what is claimed. Checked individually:
`README.md:31,117,181`, `docs/connectors/authoring.md:302,318-326,376`, `docs/index.md:34`,
`mkdocs.yml:37`, `CONTRIBUTING.md:5`, `.github/CODEOWNERS`, `.github/ISSUE_TEMPLATE/` (both files),
`.github/PULL_REQUEST_TEMPLATE.md`, `.env.example`, `.nvmrc`, `.python-version`, `.editorconfig`,
`.vscode/extensions.json` (and `.vscode/` holding nothing else), `.ade-template-version`,
`packages/pulse-core/CHANGELOG.md`, `packages/pulse-core/pyproject.toml:3`,
`openspec/specs/connector-kit/spec.md:140-152` (the `## Deprecations` policy and the `_none yet_`
row), `tests/scaffold/cat8_docs_consistency.py:683,705-738`, `tests/scaffold/cat10_devex.py`
(the `@open_finding` block at 761), `scripts/devex/timing.py:21`, `scripts/devex/check.py:98,113`,
`templates/connector/README.md.tmpl:21`, `.planning/devex/loop.jsonl`. **No cited path is missing
or misquoted.** Inventory counts all reproduce: 69 task targets, 44 docs pages, 24 design pages,
7 ADRs, 18 runbooks, 51 specs, 24 archived changes, 24 handoff directories, 8 work orders, 16 of
24 archived changes carrying `DNA-` tokens, 20 files under `templates/connector/`, 2 issue
templates, 6 workflows, 14 tracked packages, 43 commits by one author across the three connector
packages.

### The one that matters: what actually turns the gate red

```
scaffold, unstaged      task check -> rc=0, 3042 passed
git add the package     cat8 package-count gate -> FAILED, "README claims 14 packages, tree has 15"
fix the README prose    cat8 package-count gate -> FAILED, "unrecognized package count word: 'Fifteen'"
```

`_tracked_packages()` in `cat8_docs_consistency.py:705` reads `git ls-files -- packages`, and its
own docstring says why: "Tracked, not what `packages/` happens to contain". So a scaffolded package
is invisible to the gate until it is staged. Task A's own transcript corroborates this against its
own ordering: the red gate it quotes reports `test` at 37.00 s, which is a warm re-run, and its
Step 6 shows a `git add packages/zendesk-connector Taskfile.yml pyproject.toml` that the journey
table places *after* the red gate at 26:23. The red gate must have followed the staging.

This changes the shape of the finding, not its existence. The correct statement is: **a connector
author's first commit of a scaffolded package turns the gate red, and the correct fix is inside
`tests/scaffold/cat8_docs_consistency.py`.** That is still a real defect on the path to landing a
connector, and it still cannot be fixed without editing a scaffold gate. But the documented
three-command golden path completes green, the author does get a working package and a green
repo-wide gate first, and no claim that "the documented happy path fails" survives.

---

## 3. Score calibration

Checks applied per score: (a) verifiable evidence cited, (b) consistent with the rubric wording and
the TTHW table, (c) 10 read as best practice rather than defect-free, (d) fixed weights and correct
arithmetic, (e) overall is the unweighted mean.

| # | Dimension | Task B | (a) evidence | (b) rubric fit | (c) 10 bar | My read | Delta |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Getting Started | 6 | Yes, all verifiable; the 230 s anchor is wrong but Task B also anchored on the ledger's ~140 s warm figure, and my independent 163 s sits between them | Competitive band correctly applied; dirty tree and no green summary are real | Yes, "never wonders whether it worked" | 6 | 0 |
| 2 | API / CLI / SDK Ergonomics | 6 | Yes, except the golden-path claim | 6 = "acceptable, works with friction" was set by a golden path that "cannot be completed as written". It can | Yes | **7** | +1 |
| 3 | Error Messages | 6 | Yes; I reproduced all 13, not the 5 Task B managed | Blend of 9-tier own messages and 3-tier inherited ones is fairly weighted | Yes, house style named | 6 | 0 |
| 4 | Documentation | 8 | Yes | Deduction for the false step-3 claim is now the wrong reason (the claim is true), but two stale README counts and the missing owner line are real | Yes, second worked example | 8 | 0 |
| 5 | Upgrade Path | 5 | Yes | Policy at SHALL strength, empty table, no releases, silent `uv sync`. 5 is defensible; 6 is equally defensible and is what the prior run said on the same unchanged surface | 5 | 0 |
| 6 | Developer Environment | 7 | Yes | Pins, parity, hooks installed, against `.env.example` and no `settings.json` | Yes | 7 | 0 |
| 7 | Community & Ecosystem | 5 | Yes; I confirmed `README.md` names neither owner nor channel | Two of the interpretation's four criteria met, and the fourth cannot be manufactured | Yes | 5 | 0 |
| 8 | DX Measurement | 8 | Yes; 58 tests and 7 `@open_finding` markers both confirmed | A strict-xfail ratchet with an honest open count is 8-tier for an internal repo | Yes | 8 | 0 |

**(d) Weights and arithmetic.** Weights are the fixed 30/20/15/15/10/5/3/2 from `task-b.md`,
summing to 100. Recomputed: 7x30=210, 8x20=160, 4x15=60, 6x15=90, 6x10=60, 5x5=25, 5x3=15,
3x2=6. Total 626. 626/100 = 6.26, stated as 6.3. **Correct.**

**(e) Overall.** 6+6+6+8+5+7+5+8 = 51. 51/8 = 6.375, stated as 6.4. Unweighted mean, one decimal.
**Correct.**

**(c) across the board.** Every one of the eight gap-method entries states a 10 that exceeds
defect-free and says so explicitly. This requirement is met without exception.

### Scores I would move by 2 or more

**One, in the composite.** "Getting started to a working connector", weight 15, scored **4** on the
basis that "the documented three-command path returns rc=201, and the obvious fix returns a worse
second failure". The first half is false (Q13). What survives is: clone to green in 163 s, scaffold
to a green package in about 25 s, scaffold to a green repo-wide gate reached, and then a first
commit that goes red with a fix inside a scaffold gate. That is friction on the way to landing, not
a golden path that "cannot be completed as written". The rubric's 4 band is "Poor. Developers
complain. Adoption suffers"; the reproduced experience is the 5-6 band, and the successful scaffold
plus green gate pull it to the top of it. **I would score 6, a move of +2.**

Corrected composite: 626 - 60 + 90 = **656/100 = 6.6**, up from 6.3.

I would also move dimension 2 from 6 to 7 for the same reason, which is a 1-point move and below
the flag threshold. That would make overall 52/8 = **6.5**.

### Task B's own evidence disputes

Four of its five are correct and I confirmed each independently: `__all__` is 28 not 27; `cat10`
holds 58 `def test_` not "roughly 30"; there are three shell gates (`cat2_toolchain.sh`,
`cat4_command_contract.sh`, `cat7_gates_hooks.sh`) not two; and `README.md` names neither a person
nor a channel, so Task A's Step 7 wrongly treated that rubric criterion as met on the strength of
`CONTRIBUTING.md`.

Its fifth dispute, the 48 s warm gate, is right to reject the number and slightly wrong about the
reason. Task B says a warm gate here is about 140 s. My independent fresh-clone gate was 158 s and
the tracked ledger's three 2026-09-08 `test` rows are 122.1, 117.4 and 119.1 s. So ~140 s is the
right figure and Task A's 48 s is unrepresentative, as Task B says. But the same evidence also
invalidates Task A's 225 s, which Task B accepted and used as its cold anchor. Task B checked the
number that was flagged and not the number that was load-bearing.

One dispute Task B did not raise: Task A reports 89 records in `.planning/devex/loop.jsonl` with 56
`timing`; the tracked file holds **81 records, 48 timing**. The difference is exactly the 8 rows one
`task check` appends, so Task A almost certainly counted in its own clone after its first gate run.
Defensible, and it should have said so, because the number reads as a property of the repo.

---

## 4. Boomerang: prior (`5177d05`, 2026-09-05b) versus current (`f851ae0`, 2026-09-08)

### Dimensions

| # | Dimension | Prior | Current | Delta | Merged PR(s) behind the move |
| --- | --- | --- | --- | --- | --- |
| 1 | Getting Started | 7 | 6 | **-1** | None. No relevant commits to `Taskfile.yml`, `scripts/devex/`, `.env.example` or `.nvmrc` bearing on onboarding. Scorer re-reading |
| 2 | API / CLI / SDK Ergonomics | 5 | 6 | **+1** | **#422** (`546895d`, rendered connector suites import fixtures under importlib; templates and both goldens) and **#425** (`2d2d08a`, rendered `def run` signature is a ruff-format fixed point). These are precisely the two defects the prior run scored 5 for |
| 3 | Error Messages | 6 | 6 | 0 | n/a |
| 4 | Documentation | 7 | 8 | **+1** | **#422** touched `docs/connectors/authoring.md` (+8 lines). Partly earned, partly scorer re-reading |
| 5 | Upgrade Path | 6 | 5 | **-1** | None. The only commits to `packages/pulse-core/CHANGELOG.md`, `openspec/specs/connector-kit/spec.md`, `docs/adr` or `.ade-template-version` are archive bookkeeping (`16eadc2`) and an unrelated ADR (`410c2a0`). Scorer re-reading on an unchanged surface |
| 6 | Developer Environment | 7 | 7 | 0 | n/a |
| 7 | Community & Ecosystem | 4 | 5 | **+1** | **None.** `git log 5177d05..f851ae0 -- .github/CODEOWNERS .github/ISSUE_TEMPLATE .github/PULL_REQUEST_TEMPLATE.md CONTRIBUTING.md` is empty, and the README commits in that range are archive counts and a staging-manifest line. The commit-author count is still 43-to-one. Same facts, higher score |
| 8 | DX Measurement | 6 | 8 | **+2** | **#406** (`89f0170`, ten audit-4 findings as `cat10` xfails, +354 lines). Verified at both shas: `cat10` went 48 to 58 `def test_`, and `@open_finding` markers went **0 to 7** |
| | **Overall DX** | **6.0** | **6.4** | **+0.4** | |

### Seven characteristics

| # | Characteristic | Prior | Current | Delta | Behind it |
| --- | --- | --- | --- | --- | --- |
| 1 | Usable | 5 | 6 | +1 | #422, #425 |
| 2 | Credible | 5 | 6 | +1 | #422, #425 |
| 3 | Findable | 7 | 8 | +1 | No PR; scorer re-reading (both runs note the missing README owner line) |
| 4 | Useful | 8 | 8 | 0 | n/a |
| 5 | Valuable | 7 | 7 | 0 | n/a |
| 6 | Accessible | 6 | 6 | 0 | n/a |
| 7 | Desirable | 4 | **6** | **+2** | **None.** Prior basis: "Nobody outside the author has ever used it." That is still true: 43 commits, one author, zero commits to ecosystem surfaces. Current basis substitutes the dry-run diff and the 40-test scaffold, both of which existed at `5177d05` |

### Composite slices

| Slice | Weight | Prior | Current | Delta | Behind it |
| --- | --- | --- | --- | --- | --- |
| Kit API ergonomics | 30 | 5 | 7 | **+2** | #422 and #425. Earned |
| Connector documentation | 20 | 7 | 8 | +1 | #422 (authoring.md) |
| Getting started to a working connector | 15 | 4 | 4 | 0 | Held flat on a claim I could not reproduce (section 3). Should be 6 |
| Errors on the connector path | 15 | 6 | 6 | 0 | n/a |
| Dev environment for a new package | 10 | 7 | 6 | -1 | No PR; scorer re-reading |
| Kit upgrade path | 5 | 6 | 5 | -1 | No PR; scorer re-reading |
| Ecosystem and support | 3 | 4 | 5 | +1 | No PR; scorer re-reading |
| Measurement of author experience | 2 | 6 | **3** | **-3** | No PR made this worse. The machinery **grew** (#406). See below |
| **Composite** | 100 | **5.6** | **6.3** | **+0.7** | |

**No dimension rose 3 or more points**, so the "rise with no PR" test finds no violation at its
stated threshold. Two 2-point rises are fully attributable to merged PRs (#406 for dimension 8,
#422 and #425 for the Kit API slice). Three moves are scorer re-readings on surfaces with no
relevant commits and should not be read as change in the repo: dimension 7 (+1), characteristic 7
Desirable (+2), and the falls on dimensions 1 and 5. This is expected under the protocol, which
keeps Task B blind to prior scores, but a reader comparing runs needs to know which numbers moved
because the repo moved.

**The one internal inconsistency.** Dimension 8 rose +2 and the "Measurement of author experience"
slice fell -3, from the same machinery in the same report. Both are arguable in isolation: the
dimension credits a strict-xfail ratchet that grew by ten findings, and the slice charges that
TTHW and scaffold-to-green are still not recorded and that
`test_tthw_measures_clone_to_a_green_gate_in_both_arms` is now an open finding. But the prior run
scored the slice 6 while its `METRIC devex_open_findings` read 0 with three live defects, which was
the less honest state. A 3-point fall in the direction of the machinery improving needs a sentence
of justification that the scorecard does not give.

---

## 5. Scope

**Connectors weighted heaviest in both reports: PASS.** Task A runs the whole audit in the
connector-author persona, makes Step 2 connector-specific, and orders its top 10 by impact on
connector authors. Task B makes the connector composite the headline, weights Kit API ergonomics at
30 and connector documentation at 20 (half the total between them), and ties every one of its top
fixes back to the connector path.

**Whole repo still covered: PASS with a stated gap.** Task A's Step 0 inventories every
developer-facing surface (69 targets, 44 docs pages, 51 specs, 18 runbooks, 7 ADRs, 24 design
docs, the GitHub surfaces, both scaffolding commands) and Steps 5 through 8 evaluate template sync,
ADR discipline, spec archiving, toolchain pins, CI parity, CODEOWNERS, templates, handoffs, work
orders, Linear linkage and the DX ledger, none of which is connector-specific. Two journeys are
inventoried but not walked: the operator (18 runbooks, the demo targets, `twenty:*`, `ledger:*`) and
the spec author (`openspec` lifecycle end to end). Task A names this itself in Step 0 ("there is no
equivalent for an operator or a spec author") and declares the demos out of scope in its method
notes, which is the honest handling. Neither report claims coverage it does not have.

---

## 6. Hygiene

| Check | Result |
| --- | --- |
| No PHI in either report | **PASS.** `grep -niE "\b(patient|mrn|dob|ssn|[0-9]{3}-[0-9]{2}-[0-9]{4})\b"` returns nothing in either file; no email address appears in either. The only personal identifier is the repo owner's own name and GitHub handle, quoted from `CODEOWNERS` and `CONTRIBUTING.md`, which is public repo metadata, not PHI |
| No commits by either agent | **PASS.** `git log` at `f851ae0` ends at the coordinator's own checkoff commit; neither agent authored anything |
| Only the two new reports are new | **PASS with one item to attribute.** `git status --porcelain` shows ` M .mcp.json`, `A handoffs/reconciliation-sweeps/SUMMARY.md`, and three untracked `.planning/reports/` files, of which `2026-09-02-connector-agent-contract.md` predates this run (mtime 2026-09-02 21:35) |
| No tracked file modified by A or B | **PASS for the audit content, one unattributed change.** `.mcp.json` is modified (mtime 21:39:33), adding a `brook-prod` MCP server block. It is tooling configuration with no bearing on the audit, and the staged `handoffs/reconciliation-sweeps/SUMMARY.md` (mtime 21:38:52) is the coordinator's own standing-order receipt for #429. Neither is audit output and neither report mentions either. I record them rather than charge them: if `.mcp.json` was touched by an audit agent it breaches the read-only rule, and neither report discloses it |
| No em-dashes or emojis in the reports | **Task B PASS** (zero of either). **Task A PARTIAL**: 9 em-dashes and the characters `│` and `⚠`, every one inside verbatim quoted output (the `verify` target description, the four `ConfigError` lines, the guide's own section-7 heading at `authoring.md:302`, the CHANGELOG header, the owner line, and the MkDocs vendor banner). Altering quoted output would be the worse fault. No em-dash appears in Task A's own prose |
| `CHECKSUMS` verifies | **PASS.** `uv run python scripts/devex/check.py --verify-only` rc=0; `shasum -a 256 -c CHECKSUMS` reports OK for `README.md`, `rubric.md`, `task-a.md`, `task-b.md`, `task-c.md`. Both agents worked against the frozen rubric |
| Read-only discipline in the audited repo | **PASS.** All my scaffolding, staging, editing and committing happened in my own throwaway clone. The repo under audit is unchanged except this report |

---

## 7. Required corrections, ordered by severity

**C-1 (Task A, high). Relocate friction points 1 and 2 and the journey rows behind them.** The
documented three-command path is green (rc=0, 3042 passed). The package-count gate reads
`git ls-files`, so the failure requires staging. Rewrite as: "a connector author's first commit of
the scaffolded package turns the gate red, and the correct fix is inside
`tests/scaffold/cat8_docs_consistency.py`." Move the red-gate row in the journey table to after the
commit row, and drop "Then the documented happy path fails" from Step 2. Also drop the claim in
Step 4 that the guide "tells the truth about everything except the outcome of its own step 3": step
3 is now true.

**C-2 (Task B, high). Re-score the "Getting started to a working connector" slice from 4 to 6** and
the composite from 6.3 to **6.6**, and demote fix #1's justification from "turns the documented
golden path green" to "lets a connector author commit their package without editing a scaffold
gate". Optionally raise dimension 2 from 6 to 7, making overall 6.5.

**C-3 (Task A, high). Withdraw the 230 s TTHW.** An independent fresh clone at the same sha on the
same machine measured 163 s, with `test` at 120.6 s against Task A's 187 s, matching the tracked
ledger's 117-122 s range. Both numbers are Competitive tier, so no conclusion changes, but 230 s is
not a benchmark. If Task A's run was contended it should say so; the report asserts the opposite.

**C-4 (Task B, medium). Re-anchor dimension 1 on a reproducible number.** Its own ledger reading
(~140 s warm) was right and was in the report; the 230 s cold figure it also used was not
independently checked. Anchor on 163 s cold and ~140 s warm, and note that the Champion line (120 s)
is closer than the audit has been reporting.

**C-5 (Task A, medium). Fix the three counts Task B caught and the one it did not.**
`pulse_core.connector.__all__` is 28, not 27. `cat10_devex.py` has 58 `def test_`, not "roughly 30".
There are three shell scaffold gates, not two. And say that the 89-record / 56-timing ledger count
was taken in your own clone after a gate run; the tracked file holds 81 and 48.

**C-6 (Task A, medium). Correct Step 7's treatment of the README owner requirement.** The rubric's
internal interpretation asks for a person or channel named in `README.md`. Step 7 verifies
`CONTRIBUTING.md` and `authoring.md` and treats the criterion as met. `README.md` names neither;
the repo's own `test_readme_names_the_owner_and_the_channel_above_the_fold` is an open finding.

**C-7 (Task B, low). Justify or revise the "Measurement of author experience" slice.** A 3-point
fall on machinery that grew by ten mechanized findings, in the same report that raised dimension 8
by 2 points from the same evidence, reads as inconsistent without a sentence saying why the
author-experience slice is the exception.

**C-8 (Task B, low). Reproduce headline defects in a throwaway clone next run.** `task-b.md`'s
read-only constraint covers the repo under audit, not the machine; the prior run's Task B did exactly
this and it is what would have caught C-1. Add it to the Method note as standard practice.

**C-9 (Task A, low). Reconcile the pre-commit hook tally.** The report says nine hooks passed; the
run shows 8 Passed and 3 Skipped. Cosmetic.

**C-10 (coordinator, low). Attribute the `.mcp.json` modification.** A tracked file is modified in
the repo under audit and neither report mentions it. Confirm it came from the session tooling rather
than from an audit agent, and revert or commit it deliberately before the next run.

---

## 8. Trust statement

**Rely on these as-is.**

- Every quoted error message in Task A's Step 3. All thirteen reproduce verbatim, including the
  `725 files already formatted` count and both `cat8_docs_consistency.py` line numbers (733 and
  735). This is the strongest part of the audit.
- Task A's whole Step 0 inventory and every cited file path and line reference in both reports.
  Nothing is missing; nothing is misquoted.
- The scaffold's behavior: 12 files rendered in under a second, nine registration sites applied,
  `2 site(s)` in the output, `40 passed` and pyright-strict clean out of the box, the dry-run
  registration diff, the missing `Dockerfile` that the commented deploy stub names, and the
  rendered README's false `TYPED_PATHS` claim. All reproduced.
- The stale README facts: fourteen/twelve package counts against a 14-package tree,
  `README.md:31`'s singular "the change currently in flight" against two in flight, and `README.md`
  naming neither owner nor channel.
- `mkdocs build -s` clean, `task devex:check` at `devex_open_findings=7` with those seven names,
  58 `cat10` tests, 7 `@open_finding` markers, 28 exported kit names, 81 ledger rows.
- Task B's arithmetic and structure: the fixed weights, the 626 total, the 6.3 composite, the 51/8
  = 6.4 unweighted mean, and eight gap-method entries that each hold 10 above defect-free.
- Six of Task B's eight dimension scores: 1, 3, 4, 5, 6, 7 and 8 all survive adversarial review
  unchanged.

**Do not rely on these without the corrections above.**

- **The 230 s TTHW.** Use 163 s cold and about 140 s warm. Tier unchanged (Competitive).
- **"The documented happy path fails" / "the documented three-command path ends red."** It does not.
  The failure arrives at the first commit.
- **The "Getting started to a working connector" slice score of 4 and the 6.3 composite.** Read 6
  and **6.6**.
- **Task B's fix #1 at rank 1.** The fix is still correct and still cheap; its justification is not
  "turns the golden path green".
- **Task A's counts of 27 kit names, "roughly 30" cat10 tests, two shell gates, and 89 ledger
  records.** Read 28, 58, three, and 81.
- **Any cross-run reading of dimension 7, characteristic 7, or the falls on dimensions 1 and 5.**
  Those moved because the scorer read the same evidence differently, not because the repo changed.
  The moves that are genuinely earned are dimension 8 (+2, PR #406) and the Kit API slice (+2,
  PRs #422 and #425).

**Bottom line for a reader who wants one number.** Overall DX **6.4** stands, or **6.5** if
dimension 2 takes the +1 it has earned. The connector composite should read **6.6**, not 6.3. The
repo's connector golden path works; what does not work is landing the result of it without editing
a scaffold gate.
