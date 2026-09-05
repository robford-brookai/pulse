# DevEx audit QA, 2026-09-05b

Repo: `/Users/Rob.Ford/Repos/robford-brookai/pulse` at `5177d05` on `main`.
Rubric and contract: `docs/process/devex-audit/{rubric,task-a,task-b}.md` (frozen).

Inputs reviewed:

- Task A: `.planning/reports/2026-09-05b-devex-audit-evidence.md` (1125 lines)
- Task B: `.planning/reports/2026-09-05b-devex-scorecard.md` (314 lines)
- Prior scorecard for the boomerang: `.planning/reports/2026-09-05-devex-scorecard.md` (audited at `11622da`)

Method: adversarial. I re-ran 30 of Task A's cited commands, including a second independent fresh
clone timed end to end into
`/private/tmp/claude-502/-Users-Rob-Ford-Repos-robford-brookai-pulse/f762ace5-5258-40cf-9a29-e153b5d3a69c/scratchpad/audit4/scratch/qa-fresh`,
seven triggered errors, `mkdocs build -s`, both scaffold directions to a red gate, and the blocked
first commit. I opened every file path cited by either report. Nothing in the repo under audit was
written by me except this file.

---

## Verdicts

| Task | Verdict |
| --- | --- |
| **Task A (evidence)** | **ACCEPT WITH CORRECTIONS** |
| **Task B (scorecard)** | **ACCEPT WITH CORRECTIONS** |

Task A's work is strong. Every load-bearing finding reproduced independently, in some cases more
exactly than Task A itself recorded. Six factual slips need correcting, one of which is a
self-description of the audit's own footprint that is not true of the tree the audit left behind.

Task B's arithmetic, weights and method are correct and its scores are defensible from the evidence
in front of it. It violates the writing contract (four em-dashes in its own prose), carries one
mis-citation, and, as the boomerang shows, moved three dimensions downward against repo surfaces
that received zero commits since the prior audit. That last item is scorer drift rather than a
measured change, and it is the single thing that most limits comparability across runs.

---

## 1. Coverage checklist

Against the Task A spec (Steps 0 through 8 plus the required closing sections).

| Requirement | Verdict | Where |
| --- | --- | --- |
| Step 0 target discovery, developer-facing surface inventory | PASS | A:27-96 |
| Step 0 states boomerang is Task C's job | PASS | A:7-8 |
| Step 1 real fresh clone into scratch, timed per stage | PASS | A:100-125 |
| Step 1 cache warmth, both arms measured | PASS | A:127-140 |
| Step 1 idle-machine declaration | PASS | A:102-104, A:1085-1088 |
| Step 2 connector scaffold attempted, both directions | PASS | A:176-330 |
| Step 2 files and docs read, concepts counted | PASS | A:207-212 |
| Step 2 kit surface vs spec vs reference connector imports | PASS | A:290-317 |
| Step 3 at least 6 realistic mistakes, exact text | PASS (10 triggered) | A:340-472 |
| Step 3 each judged on problem / cause / fix | PASS | A:342-353 |
| Step 4 eight persona questions answered in the specified order | PASS | A:530-546 |
| Step 4 findability, currency, `mkdocs build -s` | PASS | A:504-527 |
| Step 5 template sync, `.ade-template-version`, ADR, archiving | PASS | A:591-640 |
| Step 6 toolchain pins, editor, hooks, local vs CI parity | PASS | A:672-760 |
| Step 7 internal-repo interpretation, all four criteria | PASS | A:766-846 |
| Step 8 DX measurement, three surfaces | PASS | A:852-940 |
| "What a 10/10 looks like" per step, no numeric score | PASS | one per step, 0 through 8 |
| TESTED / PARTIAL / INFERRED tag on every observation | PASS | throughout |
| Connector author journey table, INFERRED rows marked | PASS | A:948-975 |
| Top 10 friction points ordered by connector-author impact | PASS | A:983-1043 |
| Method notes and limits | PASS | A:1083-1125 |
| No numeric score assigned | PASS | verified by inspection |

Against the Task B spec.

| Requirement | Verdict | Where |
| --- | --- | --- |
| Eight dimensions scored with confidence and method | PASS | B:29-40 |
| Seven DX Characteristics scored | PASS | B:63-73 |
| Two evidence spot-checks per dimension before scoring | PASS | B:29-40 method column, B:262-284 |
| Getting Started anchored on the TTHW table | PASS | B:44-46 |
| Composite uses the fixed slices and weights | PASS | B:79-91, weights sum to 100 |
| Composite arithmetic shown | PASS | B:91-93 |
| Overall = unweighted mean of eight, one decimal | PASS | B:42 |
| Gap method for every score below 9, each 10 above defect-free | PASS | B:99-160 |
| Top 10 fixes ranked, effort tier, principle number | PASS | B:167-180 |
| "Below the cut" list | PASS | B:182-206 |
| Evidence disputes section | PASS | B:258-312 |
| Writing: no em-dashes, no emojis | **FAIL** | B:209, 226, 304, 305 |
| Gap method for the Seven Characteristics | PARTIAL | B:162-166, one clause each rather than a change per gap |
| Did not edit Task A's file | PASS | `git status --porcelain` shows A untracked and unmodified since write |

---

## 2. Evidence re-run table

All re-runs at `5177d05`. Destructive steps ran in my own fresh clone, never in the repo under audit.

| # | Command | Task A claimed | I observed | Match |
| --- | --- | --- | --- | --- |
| 1 | `git clone https://github.com/robford-brookai/pulse.git` | 2s, clean at `5177d05` | 2s, `5177d05` | yes |
| 2 | `task install` on the fresh clone | 3s, rc=0, `pre-commit installed at .git/hooks/pre-commit` | 3s, rc=0, same final line | yes |
| 3 | `task check` on the fresh clone | 147s, rc=0 | **133s**, rc=0 | within variance, same band |
| 4 | TTHW clone to green gate | **152s**, Competitive band | **138s**, Competitive band | yes, band identical |
| 5 | pytest summary inside the gate | `2893 passed, 30 skipped, 8 deselected, 11 warnings` | identical counts (33.03s vs 47.71s) | yes |
| 6 | coverage line | `Total coverage: 97.42%` | `97.42%` | yes |
| 7 | Twenty vitest suite | 67 tests | `Tests 67 passed (67)` | yes |
| 8 | `git status --short` after the gate | ` M .planning/devex/loop.jsonl` | identical | yes |
| 9 | `git diff --stat` after the gate | text says "1 insertion(+)", bar shows 8 | **8 insertions** | **no, see C-A1** |
| 10 | `task connector:new NAME=labs DIRECTION=inbound` | under 1s, 12 files, 2 registration sites | under 1s, **12 files** counted, 2 sites | yes |
| 11 | `task check` after the inbound scaffold | `rc=201`, `ModuleNotFoundError: No module named 'factories'` | `rc=201`, identical error and task chain | yes |
| 12 | `uv run pytest packages/labs/tests -q` | `40 passed` | `40 passed in 0.84s` | yes |
| 13 | `uv run pytest packages/pocar/tests -q` | `22 passed` | `22 passed in 0.71s` | yes |
| 14 | combined run with `--import-mode=importlib` | 2 collection errors, both `test_service.py` | identical, `2 errors in 0.36s` | yes |
| 15 | `uv run ruff format --diff packages/pocar/src/pocar/service.py` | `1 file would be reformatted`, joined line 118 chars | identical diff; joined line at `service.py:135` measures **118** | yes |
| 16 | `task lint` with an outbound scaffold present | unconditional failure | rc=201, `1 file would be reformatted, 723 files already formatted` | yes |
| 17 | `grep -rn "^from factories" templates/connector/` | two hits, `:16` and `:17` | identical hits and line numbers | yes |
| 18 | `packages/billing-connector/tests/__init__.py` exists, template ships none | as claimed | confirmed; template `tests/` holds 5 `.tmpl` files, no `__init__.py.tmpl` | yes |
| 19 | `uv run mkdocs build -s` | zero WARNING or ERROR lines, 0.85s | **zero** matches for `WARNING\|ERROR`, built in 1.00s | yes |
| 20 | `grep -ril "authoring a connector" docs/` | `docs/index.md`, `docs/connectors/authoring.md` | identical, nothing else | yes |
| 21 | `grep -ril "scaffold a connector" docs/` | `docs/process/devex-audit/task-a.md` | identical | yes |
| 22 | `len(pulse_core.connector.__all__)` | 28, guide's paste block lists 26 | 28 and 26; the two absent are exactly `LedgerCursorStoreError` and `TransientExhaustedError`; `block - __all__` is empty | yes |
| 23 | guide rendered-tree fence drift | lists `tests/__init__.py`, omits `test_receipts.py` | confirmed, fence at `docs/connectors/authoring.md:166-181` | yes |
| 24 | error 1, `task connector:new` no NAME | `cancelled because it is missing required variables: NAME` | verbatim | yes |
| 25 | error 2, `task verify` no CHANGE | `CHANGE is required, e.g. task verify CHANGE=<change-id>` | verbatim, plus the precondition line | yes |
| 26 | error 3, `task dispatch CHANGE=no-such-change` | `Error: openspec/changes/no-such-change/tasks.md not found` | verbatim | yes |
| 27 | error 4, `task dispatch --change=foo` | go-task usage tutorial, no mention of `CHANGE=` | verbatim, 18 lines, `hello` example present | yes |
| 28 | error 5, `task connector:new NAME=Bad_Name/x` | `error: NAME='Bad_Name/x' is not a usable package name...` | verbatim | yes |
| 29 | error 7, `task twenty:deploy TARGET=dev` | `target 'dev' is not configured — set: PULSE_TWENTY_DEV_URL, PULSE_TWENTY_DEV_TOKEN` | verbatim | yes |
| 30 | error 10, `task lore:drift` on a fresh clone | `[error] No openlore configuration found. Run "openlore init" first.` | verbatim | yes |
| 31 | first Python commit on a fresh clone | blocked by `openlore drift` hook, same message | blocked, `- hook id: openlore-drift`, `- exit code: 1`, same message | yes |
| 32 | `task devex:check` | `METRIC devex_open_findings=0` | identical, with all three defects reproducible | yes |
| 33 | `uv run pytest tests/scaffold/cat10_devex.py -q` | `45 passed, 3 deselected` | `45 passed, 3 deselected in 0.42s` | yes |
| 34 | `git log --format='%an <%ae>' \| sort \| uniq -c` | `1064 Rob Ford` | identical, single author | yes |
| 35 | task target count | 68 in both listings | 68 and 68 | yes |
| 36 | `.env.example` carries no connector variables | as claimed | 0 matches for `TOKEN\|LEDGER_BASE_URL\|SOURCE_TABLE\|PULSE_TWENTY` | yes |
| 37 | `.vscode/` holds only `extensions.json` | as claimed | confirmed | yes |
| 38 | `consent-ingress` subclasses the kit fixture in production source | `row_source.py:41,96` | confirmed at exactly 41 and 96 | yes |
| 39 | guide promises "the rendered package ships one green test" | step 3 | `docs/connectors/authoring.md:133` | yes |
| 40 | four OpenSpec changes open | as claimed | `billing-connector`, `devex-eight`, `devex-eight-2`, `devex-eight-3` | yes |
| 41 | pins: `.python-version` 3.14, `.nvmrc` 22, `requires-python >=3.10,<4.0`, pulse-core `0.1.0` | as claimed | all four exact | yes |
| 42 | `README.md` line count | **267** | **360** | **no, see C-A2** |
| 43 | `line-length = 120` location | `pyproject.toml:157` | `pyproject.toml:153` | **no, see C-A3** |
| 44 | `grep -in "slack\|owner\|channel" README.md` | "returns only incidental matches" | **zero matches**, rc=1 | **no, see C-A4** |
| 45 | `.planning/devex/loop.jsonl` row count "at HEAD" | 48 | **40 at HEAD**, 48 in the dirty working tree | **no, see C-A5** |

Every file path cited by either report exists and says what is claimed. No dead citation was found
in Task A. One mis-citation was found in Task B (C-B2 below).

Task B's five self-declared unverifiable claims are now verified by me and all reproduce: the
147s/152s timings (within band), the cold-cache arm's direction, errors 4, 7 and 10, and the 12-file
render count. Task B's dimension 1 and dimension 3 Medium confidence ratings can be raised to High
on that basis.

---

## 3. Score calibration

Checks applied per score: (a) verifiable evidence cited, (b) consistent with the rubric wording and
the TTHW table, (c) 10 read as best practice rather than defect-free, (d) fixed weights and correct
arithmetic, (e) overall is the unweighted mean.

**Arithmetic, checked independently.** Overall: 7+5+6+7+6+7+4+6 = 48; 48/8 = **6.0**. Correct.
Composite weights 30+20+15+15+10+5+3+2 = **100**, matching the protocol exactly. Contributions
1.50+1.40+0.60+0.90+0.70+0.30+0.12+0.12 = **5.64**, rounded **5.6**. Correct. Point (e) holds.
Point (c) holds: B states the 10-versus-defect-free rule at B:11-12 and every gap entry clears it.

| # | Dimension | B score | (a) evidence verifiable | (b) rubric consistent | My read | Move of 2+? |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Getting Started | 7 | yes, and I re-measured the timing B could not | yes, 138s to 152s is Competitive, nothing blocks, friction is cosmetic | 7, arguably 8 | no |
| 2 | API / CLI / SDK | 5 | yes, both defects reproduced by me | borderline. The documented golden path fails outright, which reads closer to the rubric's 3-4 "developers complain" than to 5-6 "works but with friction" | 4 or 5 | no, one point generous |
| 3 | Error messages | 6 | yes, all seven I re-triggered are verbatim | yes, the blend of strong house messages and raw inherited ones is a fair 6 | 6 | no |
| 4 | Documentation | 7 | yes | yes, though see the double-count note below | 7 | no |
| 5 | Upgrade path | 6 | yes | yes as an absolute judgement; **not defensible as a move**, see boomerang | 6 or 7 | no |
| 6 | Developer environment | 7 | yes, blocked commit reproduced | yes | 7 | no |
| 7 | Community and ecosystem | 4 | yes, README grep returns zero | yes as an absolute judgement; **not defensible as a move**, see boomerang | 4 or 5 | no |
| 8 | DX measurement | 6 | yes | yes | 6 | no |

**No score I would move by 2 or more points.** The scorecard is calibrated within one point
throughout, which is the tightest agreement of any QA pass I can attest to from this evidence.

Three calibration notes that do not move a score but bear on comparability:

1. **Double-counting the same defect across dimensions 2 and 4.** The false "ships one green test"
   promise at `docs/connectors/authoring.md:133` is a template defect. B charges it in dimension 2
   (correctly) and again in dimension 4 as the reason Documentation fell from 8 to 7. The guide's
   prose did not regress; the tooling underneath it did. A reader comparing runs will read a
   documentation regression that did not occur.

2. **Dimension 2 is the one place I would argue for a lower number.** `task connector:new` is the
   single command this persona exists to run, and its documented three-command sequence is red in
   both directions, name-independently, with no workaround stated anywhere in the repo. The rubric's
   5-6 band is "developers tolerate it"; a newcomer here cannot proceed without cross-reading the
   reference connector, which Task A measured at roughly 15 minutes. I would accept 5 given the
   surrounding CLI quality, and I record that 4 is equally defensible.

3. **Seven Characteristics carry no gap-method entries of their own**, only a one-clause summary at
   B:162-166. The Task B contract says "for every score below 9"; seven of the seven are below 9.
   PARTIAL rather than FAIL, since each clause does name a bar above defect-free.

---

## 4. Boomerang: prior (`11622da`) versus current (`5177d05`)

Prior scorecard: `.planning/reports/2026-09-05-devex-scorecard.md`. 51 commits separate the two
audited trees (`git rev-list --count 11622da..HEAD`).

### Eight dimensions

| # | Dimension | Prior | Current | Delta |
| --- | --- | --- | --- | --- |
| 1 | Getting Started | 6 | 7 | **+1** |
| 2 | API / CLI / SDK ergonomics | 7 | 5 | **-2** |
| 3 | Error messages | 5 | 6 | **+1** |
| 4 | Documentation | 8 | 7 | -1 |
| 5 | Upgrade path | 7 | 6 | -1 |
| 6 | Developer environment | 7 | 7 | 0 |
| 7 | Community and ecosystem | 5 | 4 | -1 |
| 8 | DX measurement | 7 | 6 | -1 |
| | **Overall (unweighted mean)** | **6.5** | **6.0** | **-0.5** |

### Seven characteristics

| # | Characteristic | Prior | Current | Delta |
| --- | --- | --- | --- | --- |
| 1 | Usable | 7 | 5 | **-2** |
| 2 | Credible | 6 | 5 | -1 |
| 3 | Findable | 8 | 7 | -1 |
| 4 | Useful | 8 | 8 | 0 |
| 5 | Valuable | 8 | 7 | -1 |
| 6 | Accessible | 5 | 6 | **+1** |
| 7 | Desirable | 6 | 4 | **-2** |

### Composite

| Number | Prior | Current | Delta |
| --- | --- | --- | --- |
| Connector author DX (weighted composite) | 6.7 | 5.6 | **-1.1** |

### Required check: dimensions that rose 3 or more points

**None.** The largest rise in either table is +1 (Getting Started, Error messages, Accessible). The
required "a rise with no PR behind it is a finding against Task B" check therefore returns an empty
set, and Task B is clear on it.

Both +1 dimension rises do have merged PRs behind them, which I verified:

- **Getting Started 6 to 7.** The prior audit's two Getting Started blockers were the gate failing
  on a laptop with commit signing on, and `task verify` with an empty `CHANGE`. Both were fixed and
  merged: `92b9e8d` (#399) "pin commit.gpgsign=false in scaffold git helpers (1.1)" and `f0cbcf5`
  (#395) "task verify fails fast on empty CHANGE (1.2)". My fresh clone reached a green gate with no
  intervention, which is the improvement.
- **Error messages 5 to 6.** `e546a26` (#398) "LedgerCursorStore wraps transport errors naming base
  URL and its variable (2.2)" and `f0cbcf5` (#395), whose `CHANGE is required, e.g. task verify
  CHANGE=<change-id>` message I re-triggered verbatim and which Task A cites as one of the two
  exemplars.
- **Accessible 5 to 6** is the one rise with **no repo change behind it**. `.vscode/` and
  `.env.example` received zero commits since `11622da` (`git log 11622da..HEAD -- .vscode
  .env.example` is empty), and both audits record the same facts: `extensions.json` only, no
  `settings.json`. This is a +1 of scorer drift, below the +3 threshold the contract sets, recorded
  for completeness rather than as a finding.

### The -2 that matters, and it is fully attributable

The API/CLI/SDK drop from 7 to 5, and with it Usable -2 and the composite -1.1, is a **real
regression introduced by a merged PR since the prior audit**, not scorer drift. Both of Task A's
headline defects trace to one commit:

```
$ git log --oneline 11622da..HEAD -- "templates/connector/src/{{NAME}}/service.py.tmpl"
e77704d feat: the scaffold declares through submit_with_retry in both directions (2.1)

$ git ls-tree 11622da templates/connector/tests/
conftest.py.tmpl  factories.py.tmpl  test_config.py.tmpl  test_receipts.py.tmpl
```

- `templates/connector/tests/test_service.py.tmpl` **did not exist at `11622da`**. It was created by
  `e77704d`, merged as `a28984d` (**PR #403**), carrying `from factories import FakeCommandTransport`.
- The inbound overlay's `test_service.py.tmpl` existed at `11622da` and imported no `factories` at
  all (I read the blob). The same commit `e77704d` added the bare import there too.
- The outbound `def run(...)` signature at `11622da` was a single 92-character line. `e77704d` added
  the `client: PulseCoreClient` parameter and hand-wrapped the result, producing the 118-character
  joined line that `ruff format` now rewrites.

So **PR #403 is the sole cause of both headline defects**, and it landed with a green `task check`
because `cat10_devex.py` asserts only that the scaffold target and template directory exist. Task
A's finding 4 and Task B's fix 5 are, on this evidence, not merely theoretical: the missing gate has
already let one regression through in the interval between two audits.

Similarly, Task A's Step 1 friction 1 (the gate dirtying a tracked file) is new since `11622da`:
`scripts/devex/timing.py` was added by `1f50285`, merged as `eda7f70` (**PR #404**). The prior audit
could not have seen it.

### Falls with no repo change behind them

Not part of the required check, which covers rises only, but the symmetric case is what most limits
run-to-run comparability, so I record it.

| Dimension | Delta | Commits touching the scored surface since `11622da` | Assessment |
| --- | --- | --- | --- |
| 5 Upgrade path | -1 | `packages/pulse-core/CHANGELOG.md`: **0**. `openspec/specs/connector-kit/spec.md`: **0**. `docs/adr/`: **0**. | **Scorer drift.** Nothing in this dimension changed. Both audits describe the same policy, the same empty deprecation table, the same `0.1.0`. |
| 7 Community and ecosystem | -1 | `.github/CODEOWNERS`: **1** (`709d9bb`, #396, adds the connector-kit line). `.github/ISSUE_TEMPLATE/`: **1** (same PR, adds `connector-kit-defect.yml`). `README.md`: **0**. `CONTRIBUTING.md`: **0**. | **Scorer drift, and in the wrong direction.** The only merged change to this dimension improved it. The prior scorecard also flags that its own 5 included a QA-recommended correction, which makes the two numbers doubly incomparable. |
| 8 DX measurement | -1 | `tests/scaffold/cat10_devex.py`: 21 commits, `scripts/devex/`: new timing ledger. | **Partly drift.** The machinery grew. B's reason for the fall (a zero metric read as a health signal) was already stated in the repo's own protocol commit `9dc5e5e` before the prior audit scored it 7. Defensible as a re-read, not as a measured decline. |
| 4 Documentation | -1 | `docs/connectors/authoring.md`: 7 commits, all improvements (#401 names every kit export, #397 fixes the rendered README next steps). | **Defensible but double-counted.** The guide improved; what made section 3 false was PR #403's template change, already charged to dimension 2. |

Net reading of the boomerang: of the -0.5 overall, **-2 on one dimension is a genuine, PR-attributable
regression**, +2 across two dimensions is genuine PR-attributable improvement, and roughly -3 points
spread over dimensions 4, 5, 7 and 8 is re-reading rather than change. The composite's -1.1 is
therefore an overstatement of how much worse the repo actually got, and the API/CLI -2 is an
understatement of how significant a single merged PR was.

---

## 5. Scope

| Check | Verdict | Basis |
| --- | --- | --- |
| Connectors weighted heaviest in Task B | PASS | Kit API 30 plus Connector documentation 20 is 50 percent of the composite; the composite is the headline, stated first at B:19 |
| Connectors weighted heaviest in Task A | PASS | The persona frames every step; Steps 2, 3 and 4 are explicitly connector-scoped; the Top 10 is ordered by connector-author impact |
| Whole repo still covered | PASS with one gap | Steps 0, 5, 6, 7 and 8 cover the ADE workflow, template sync, ADRs, spec archiving, CI parity, CODEOWNERS, handoffs, work orders, Linear linkage and the DX ratchet, none of which is connector-specific |
| Gap | | Neither report assesses the DX of the two TypeScript packages (`twenty-app`, `twenty-model`) beyond noting the vitest suite runs in the gate. `task twenty:*` targets appear only as error-message subjects. A developer whose first job is a Twenty change is not modelled in either run. |

The prior audit had the same gap, so it does not affect the boomerang. Recording it so a future run
can widen scope deliberately rather than by accident.

---

## 6. Hygiene

| Check | Result |
| --- | --- |
| PHI in either report | **None.** Grep for MRN, SSN, DOB, patient-name and SSN-shaped patterns returns nothing. All connector names (`labs`, `pocar`) are synthetic; all quoted config values are variable names, never values. |
| Tracked file modified by A or B | **One tracked file is dirty**, see C-A5. `.mcp.json` is also modified but is session tooling config, unrelated to the audit and dated `01:59:03`, before either report was written. |
| `git status --porcelain` shows only the two new reports as new | **PASS.** The only untracked additions in `.planning/reports/` are `2026-09-05b-devex-audit-evidence.md` and `2026-09-05b-devex-scorecard.md`, plus `2026-09-02-connector-agent-contract.md`, which predates this audit. |
| Commits made | **None.** `HEAD` is still `5177d05`. |
| Em-dashes in Task A's own prose | **PASS.** All 12 occurrences are inside quoted repo docs or quoted command output (A:56, 151, 307, 308, 430, 438-440, 448, 612, 654, 741). None is authored prose. |
| Em-dashes in Task B's own prose | **FAIL.** Four, all authored: B:209, B:226, B:304, B:305. |
| Emojis | **PASS both.** The single non-ASCII glyph is the `⚠` inside the quoted Material for MkDocs vendor banner at A:150. |
| `CHECKSUMS` verifies | **PASS.** `uv run python scripts/devex/check.py --verify-only` exits 0 with no output. The frozen rubric and task files are unmodified. |

---

## 7. Required corrections, ordered by severity

### Task A

**C-A1 (highest). Correct the repo-footprint claim, or correct the row count.**
Task A's Method notes state "The repo under audit was not modified" (A:1113) and "This report is the
only file I created in the repo" (A:1117). The working tree at `5177d05` carries 8 uncommitted rows
in the tracked file `.planning/devex/loop.jsonl`, and one of them,
`{"date": "2026-09-05", "kind": "timing", "target": "docs:build", "seconds": 1.936, "rc": 0}`, is the
exact row Task A quotes as its sample at A:915. Its mtime is `02:01:26`, inside the audit window
(Task A's report was written at `02:16:07`). I cannot attribute the write to Task A with certainty,
since the coordinator also runs `task check` on main, but the statement is not true of the tree Task
A left behind and the quoted row could only have been read from the dirty file. Restate as: "one
tracked file, `.planning/devex/loop.jsonl`, carries uncommitted gate-timing rows; running `task check`
anywhere in this repo appends them, which is finding 9."

**C-A2. `README.md` is 360 lines, not 267** (A:33). Already caught by Task B. Prerequisites begins at
`README.md:182`, which strengthens rather than weakens the associated judgement.

**C-A3. The line-length setting is at `pyproject.toml:153`, not `:157`** (A:280). Value 120 correct;
the 118-character arithmetic holds and I re-measured it.

**C-A4. The README owner grep returns zero matches, not "only incidental matches"** (A:820). The
finding is correct and understated.

**C-A5. `.planning/devex/loop.jsonl` holds 40 rows at HEAD, not 48** (A:911). 48 is the working-tree
count including the 8 uncommitted rows. Same root cause as C-A1.

**C-A6. Step 1's `git diff --stat` quote is internally inconsistent** (A:135-138): the bar shows
`8 ++++++++` and the summary line reads "1 insertion(+)". The true value is 8 insertions, which is
what Task A's own Top 10 item 9 says. Fix the quoted summary line.

**C-A7 (cosmetic). Step 3's heading says "Eight realistic mistakes triggered"** (A:340) and then
tabulates and documents ten. Already caught by Task B.

**C-A8 (cosmetic). The Step 2 scaffold output block is reformatted, not verbatim** (A:190-200). The
real output prints one absolute path per line; Task A condenses to `src/labs/{...}` brace notation.
No content is invented, but the block reads as a quote. Label it as abridged.

**C-A9 (cosmetic). "the gate's final screenful"** (A:145-152). The red vendor block is followed by
three mkdocs `INFO` lines. The finding stands; "final screenful" should be "the last substantive
block before three INFO lines".

### Task B

**C-B1 (highest). Remove the four em-dashes from authored prose**: B:209, B:226, B:304, B:305. The
Task B contract says "plain, no em-dashes, no emojis". This is the only outright contract violation
in either report.

**C-B2. Fix the dimension 4 evidence pointer.** B:34 cites "`docs/connectors/authoring.md:349` and
its `text` fence". Line 349 is step 8 item 6 (the `task lore:init` line, which belongs to dimension 6).
The rendered-tree fence is at `docs/connectors/authoring.md:166-181`. Related: B:143 describes the
`lore:init` fix as documented "349 lines into a different guide"; it is the same guide the persona
is reading, at line 349.

**C-B3. Raise the confidence on dimensions 1 and 3 from Medium to High**, or restate them. All five
claims B listed as unverifiable are now verified in this QA pass: the TTHW timings (I measured 138s
against A's 152s, same band), the cold-cache direction, and errors 4, 7 and 10 (verbatim). The
12-file render count is also confirmed at exactly 12.

**C-B4. Attach the boomerang caveat to dimensions 5 and 7.** Both fell one point against surfaces
that received zero relevant commits since `11622da` (Upgrade path: zero commits to the CHANGELOG,
the connector-kit spec, or `docs/adr/`; Community: the only commits, in PR #396, were improvements).
Neither fall is a measured decline and neither should be read as one. This is the correction with
the largest effect on cross-run comparability.

**C-B5. Separate the documentation double-count.** Documentation fell 8 to 7 because section 3's
promise is false, but what falsified it is PR #403's template change, already charged in full to
dimension 2. State the guide's own prose as improved (PRs #401, #397) and the promise as broken
underneath it.

**C-B6 (optional, judgement). Consider 4 for dimension 2**, or record 4 as the alternate reading.
The rubric's 5-6 band is "works but with friction"; the documented golden path does not work in
either direction and no workaround appears anywhere in the repo.

**C-B7 (cosmetic). Give each of the Seven Characteristics its own gap entry**, not a single clause
in a shared paragraph (B:162-166).

### Neither task, for the coordinator

**C-X1. PR #403 shipped both headline defects.** `templates/connector/tests/test_service.py.tmpl` was
created by that PR with a bare `from factories import ...`, and the same PR hand-wrapped the outbound
`def run(...)` into a line `ruff format` rejects. The scaffold was not broken at `11622da`. Task B's
ranked fixes 1 and 2 are therefore reverts of a two-week-old change, not longstanding debt, and fix 5
(a gate that renders and gates) is the control that would have blocked #403.

---

## 8. Trust statement

**Rely on these as they stand:**

- Every one of Task A's ten Top 10 friction points. I reproduced items 1, 2, 3, 4, 5, 8, 9 and 10
  end to end and confirmed items 6 and 7 verbatim from the triggered errors.
- Every exact error text quoted in Task A Step 3. Seven of ten re-triggered verbatim, including the
  three Task B could not verify.
- All of Task A's file-and-line citations except `pyproject.toml:157` (read 153) and the README line
  count (read 360). Every other path exists and says what is claimed.
- Task B's arithmetic in full: overall 6.0, composite 5.64 rounded to 5.6, weights summing to 100,
  the mean unweighted. Recomputed independently.
- The TTHW band. Task A's 152s and my independent 138s both sit in the rubric's Competitive band with
  wide margin on both boundaries; the band does not depend on which number you take.
- `devex_open_findings=0`, `45 passed, 3 deselected`, `2893 passed`, `97.42%` coverage, 68 targets,
  1064 single-author commits, `__all__` = 28 against a 26-name paste block, `mkdocs build -s` clean.
- The eight dimension scores, to within one point. I would move nothing by 2 or more.

**Treat with the stated caveat:**

- **The composite delta of -1.1 and the overall delta of -0.5.** Roughly -2 of the movement is a real,
  PR-attributable regression (PR #403) and roughly -3 spread across dimensions 4, 5, 7 and 8 is
  re-reading rather than repo change. The direction of travel on the connector path is real; the
  magnitude of the composite drop is not a clean measurement.
- **Dimensions 5 and 7 as trend points.** Both fell against surfaces with no relevant commits. Use
  their absolute values, not their deltas.
- **The Seven Characteristics deltas.** Same drift exposure as the dimensions they derive from, plus
  Accessible's +1 against zero commits.

**Do not rely on:**

- **Task A's statement that the repo under audit was unmodified.** One tracked file, the timing
  ledger, is dirty in the working tree, and the row Task A quotes comes from that dirty state.
- **"48 rows at HEAD"** for `.planning/devex/loop.jsonl`. HEAD carries 40.
- **Any Getting Started or Documentation comparison across audits 3 and 4 that treats the boomerang
  as a like-for-like measurement**, until C-B4 and C-B5 are applied.

**PHI.** No protected health information appears in this report. No live system was contacted. All
destructive verification ran in a throwaway clone under the session scratch directory. The repo under
audit was not written to by me except for this file, and no commit was made.
