# DevEx audit QA: pulse @ 11622da

Date: 2026-09-05
Repo under audit: `/Users/Rob.Ford/Repos/robford-brookai/pulse` at `11622da` (main).
Working HEAD at QA time: `208be59` (ledger row plus collected handoffs on top of `11622da`;
`11622da` is an ancestor and nothing between them touches a scored surface).

Inputs reviewed:

- Task A evidence: `.planning/reports/2026-09-05-devex-audit-evidence.md` (1149 lines)
- Task B scorecard: `.planning/reports/2026-09-05-devex-scorecard.md` (409 lines)
- Prior scorecard: `.planning/reports/2026-09-04-devex-scorecard.md` (at `b26dee0`)
- Contract: `docs/process/devex-audit/task-a.md`, `task-b.md`, `rubric.md`

Independent work performed for this QA: a second fresh clone of the repo from GitHub into
`/private/tmp/.../scratchpad/audit3/qa-fresh`, checked out at `11622da`, with its own stage
timings; 21 of Task A's cited commands re-run; 8 of the 10 error cases re-triggered; `mkdocs
build -s` re-run; every cited file path opened; `CHECKSUMS` verified.

---

## Verdicts

| Task | Verdict |
| --- | --- |
| **Task A (evidence)** | **ACCEPT WITH CORRECTIONS** |
| **Task B (scorecard)** | **ACCEPT** |

Task A's coverage is complete against its spec and its evidence reproduces: every command I
re-ran produced the output it quoted, and my independent clone reproduced its headline finding
(six `cat5_glue_logic` failures from global `commit.gpgsign`) exactly, test name for test name.
Six factual errors sit on top of that good work: two miscounts, one false claim that the standard
connector spec is duplicated, one false claim that `template_sync.sh` uses SSH, one defect framed
as unconditional that is name-conditional, and a wall-clock set inflated two to four times by
contention Task A created itself. Task B caught five of the six independently and scored around
them, which is the protocol working as designed.

Task B is accepted as written. Its arithmetic is correct, its weights are the fixed ones, its
overall is the unweighted mean, its blindness held, and all seven of its evidence disputes
survived my re-verification. Two scores are one point generous in my reading and neither moves by
enough to require a correction. No score in either report is one I would move by two or more
points.

---

## 1. Coverage checklist

### Task A against `task-a.md`

| Requirement | Status | Where |
| --- | --- | --- |
| Steps 0-8, one section each | PASS | evidence L18, L76, L204, L445, L564, L646, L728, L813, L910 |
| Persona is a non-billing connector (`pap`) | PASS | L7-8 |
| States the boomerang is Task C's job | PASS | L10-11 |
| Step 0 surface inventory | PASS | L34-48, 13-row table |
| Step 1 real fresh clone, timed to the second per stage | PASS | L93-98, four-row stage table |
| Cache warmth noted | PASS | L100-105, `~/.cache/uv` 26 GB called out |
| Step 2 connector scaffold attempt | PASS | L212-221, three renderings (in-tree, out-of-tree inbound and outbound) |
| Step 2 counts files read, concepts learned, stuck point | PASS | L394-414, 2 before / 4 after, ~15 concepts |
| Step 2 compares kit surface to guide and to reference imports | PASS | L343-371 |
| Step 3 at least 6 triggered errors, exact text | PASS | 10 cases E1-E10 at L453-464 plus E-cat5 |
| Step 3 problem / cause / fix judged per error | PASS | L453-464 table columns |
| Step 4 eight persona questions answered in order | PASS | L580-589, all eight rows present |
| Step 4 currency and `mkdocs build -s` | PASS | L594-606 |
| Step 5 template sync, `.ade-template-version`, ADR, archiving | PASS | L660-712 |
| Step 6 toolchain pins, editor, hooks, local/CI parity | PASS | L742-797 |
| Step 7 internal-repo interpretation, all four asks | PASS | L815-891 |
| Step 8 DX measurement | PASS | L910-1008 |
| Journey table with INFERRED rows marked | PASS | L1016-1038; five INFERRED rows marked |
| Top 10 friction points, ordered by connector-author impact | PASS | L1045-1092 plus a below-the-cut list |
| Method notes and limits | PASS | L1105-1149 |
| TESTED / PARTIAL / INFERRED tags throughout | PASS | used consistently |
| Every claim cites path, command plus output, or a timing | PARTIAL | four claims cite nothing checkable and four are wrong on the facts; see section 2 |
| No em-dashes | PARTIAL | 18 occurrences; 15 inside quoted output, 3 in Task A's own prose (L540, L618, L676) |
| No emoji | PASS | the single non-ASCII glyph is the warning sign inside a quoted mkdocs banner |
| Read-only, no commit | PASS | see section 6 |

### Task B against `task-b.md`

| Requirement | Status | Where |
| --- | --- | --- |
| Eight dimensions scored 0-10 with confidence | PASS | scorecard L44-53 |
| Seven DX Characteristics scored | PASS | L162-172 |
| Getting Started anchored to the TTHW table | PASS | L57-58, names the Competitive band explicitly |
| At least two pieces of Task A evidence spot-checked per dimension | PASS | Method column names them per row; I re-checked every one |
| Unverifiable evidence marked and scored at low confidence | PASS | disputes D1-D7 plus a named "accepted without re-running" class |
| Connector composite with the fixed weights, arithmetic shown | PASS | L186-201; weights 30/20/15/15/10/5/3/2 as specified |
| Overall = unweighted mean, one decimal | PASS | L55, 52/8 = 6.5 |
| Gap method for every score below 9, each 10 above defect-free | PASS | L214-268, eight entries, each states the 10 first |
| Top 10 fixes ranked, S/M/L effort, tied to a numbered principle | PASS | L273-286 |
| Below the cut list | PASS | L288-303 |
| Evidence disputes section | PASS | L307-403 |
| Header with date, HEAD, inputs, rubric path | PASS | L3-15 |
| Blindness declared and held | PASS | L17-21; verified, see section 6 |
| Did not edit Task A's file | PASS | verified by mtime and content |
| No em-dashes | PARTIAL | one, inside a quotation of a repo file |
| No emoji | PASS | none |

Nothing in either contract is unaddressed. The two PARTIALs on Task A are the factual errors and
the prose em-dashes, both corrected below.

---

## 2. Evidence re-run

21 commands re-run. Repo commands in `/Users/Rob.Ford/Repos/robford-brookai/pulse` at `208be59`
with `11622da` content on every path checked; timed stages in the independent clone.

| # | Command | Task A claimed | I observed | Match |
| --- | --- | --- | --- | --- |
| 1 | `git clone https://github.com/robford-brookai/pulse.git` (fresh, timed) | 2 s, 26 MB tree | 1 s, 26 MB tree | YES |
| 2 | `task install` on the fresh clone | 3 s, ends `pre-commit installed at .git/hooks/pre-commit` | 3 s, same final line | YES |
| 3 | `task check` on the fresh clone, stock git config | 6 failures, `6 failed, 2874 passed, 30 skipped, 6 deselected` | identical: same six `cat5_glue_logic` test names, `6 failed, 2874 passed, 30 skipped, 6 deselected` | YES |
| 4 | `task check` under `GIT_CONFIG_GLOBAL=/dev/null` | green, rc 0, 161 s (and 102 s on a later run) | green, rc 0, **113 s** | YES on result, timing differs |
| 5 | TTHW, clone to green `task check` | 166 s, Competitive tier | **117 s**, Champion tier by the same table | NO, see correction A6 |
| 6 | `task verify` with no CHANGE | rc 201 after **403 s**, never reached `spec:validate` | rc 201 after **102 s**, failed at `lore:drift`, never reached `spec:validate` | YES on the defect, NO on magnitude |
| 7 | `task connector:new` (no NAME) | `cancelled because it is missing required variables: NAME` | verbatim identical | YES |
| 8 | `task connector:new --name=pap` | go-task usage dump, `unknown flag: --name` on the last line | verbatim identical, message on the last line | YES |
| 9 | `connector_new.py --direction sideways` | `invalid choice: 'sideways' (choose from outbound, inbound)` | verbatim identical | YES |
| 10 | `task dispatch CHANGE=no-such-change` | `Error: openspec/changes/no-such-change/tasks.md not found` | verbatim identical | YES |
| 11 | `task check` from `packages/` | runs normally, go-task walks up | confirmed, root Taskfile resolved | YES |
| 12 | `Config.from_env({})` on the rendered package | three-line `ConfigError`, every variable named with its unit, token value absent | verbatim identical (rendered as `papchk`) | YES |
| 13 | `PAGE_SIZE=x STALE_AFTER_SECONDS=x` | two-line `ConfigError`, both variables, both units | verbatim identical | YES |
| 14 | rendered service against an unreachable ledger | `httpx.ConnectError: [Errno 61] Connection refused`, raw traceback, no URL, no variable | verbatim identical | YES |
| 15 | `mkdocs build -s` | clean, `Documentation built in 0.90 seconds`, only the vendor banner | clean, `built in 0.76 seconds`, red-bordered Material 2.0 banner present | YES |
| 16 | `ruff check --no-fix` on an out-of-tree render | 2 `I001` errors in `tests/test_receipts.py`, `tests/test_service.py` | 2 `I001` errors for `papchk`, **0 for `zapchk`** | YES but conditional, see A5 |
| 17 | `uv run pyright -p packages/<new>` | 0 errors | template declares `typeCheckingMode = "strict"` at `pyproject.toml:40-42`; `connector_new.py:334-337` registers `TYPED_PATHS` only; `Taskfile.yml` `typecheck` has eight pyright lines and gains no ninth | YES, the defect is real |
| 18 | `__all__` in `pulse_core.connector` | 28 names | **27** names, parsed with `ast` | NO, see A1 |
| 19 | `authoring.md` §2 copy-paste block | 15 names | **14** names | NO, see A1 |
| 20 | `grep -in billing docs/contracts/producer-registry.md` | no row for `packages/billing-connector` | confirmed: rows are cpt-om, the pulse billing engine, and Billy; no connector row | YES |
| 21 | `uv run python scripts/devex/check.py --verify-only` | not cited by either report | rc 0, `CHECKSUMS` verifies | PASS |

Cited file paths, all opened: `docs/connectors/authoring.md`, `docs/index.md:34-37`,
`CONTRIBUTING.md:5`, `README.md`, `Taskfile.yml:49` and the `verify`, `lint` and `typecheck`
targets, `pyproject.toml:154`, `tests/scaffold/cat5_glue_logic.py:937,939`,
`tests/scaffold/cat9_golden_workflow.py:458,460`, `tests/scaffold/cat10_devex.py:42,86`,
`scripts/connector_new.py:332-338`, `scripts/template_sync.sh:18`,
`packages/pulse-core/src/pulse_core/connector/rows.py:229-236`,
`packages/pulse-core/CHANGELOG.md`, `openspec/specs/connector-kit/spec.md`,
`design/platform/pulse-standard-connector-spec.md`, `.github/CODEOWNERS`,
`.github/ISSUE_TEMPLATE/`, `docs/contracts/producer-registry.md`, `.planning/devex/loop.jsonl`.
**Every cited path exists.** Three say something other than what was claimed and are corrected
below; the rest match.

Line-number precision: Task A cites `pyproject.toml:156` for `fix = true`, which is at 154. Task B
cites `Taskfile.yml:50` for the `CHANGE: ""` default, which is at 49, and `cat10_devex.py:87` for
`test_connector_spec_has_one_canonical_copy`, whose `def` is at 86. All three are off by one or
two and none changes a conclusion.

### The timing discrepancy, stated plainly

Every wall-clock number in Task A runs two to four times longer than the same measurement on an
otherwise idle machine: green `task check` 161 s versus my 113 s, the pytest suite 394 s versus my
35 s, `task verify` 403 s versus my 102 s, TTHW 166 s versus my 117 s. Task A discloses the cause
itself (L1133-1135: it ran `task check` and `task verify` concurrently in one clone, which also
corrupted shared coverage state). The defects those timings illustrate are all real and all
reproduced. The numbers are not usable as benchmarks.

---

## 3. Score calibration

Checks applied per score: (a) verifiable evidence cited, (b) consistent with the rubric wording and
the TTHW table, (c) the stated 10 exceeds defect-free, (d) composite weights fixed and arithmetic
correct, (e) overall is the unweighted mean.

| # | Dimension | B's score | (a) evidence | (b) rubric fit | (c) 10 above defect-free | QA position |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Getting Started | 6 | Yes, structural cause verified in-tree and reproduced by me | Yes, but the TTHW anchor is wrong (see below) | Yes, asks for a gate proving its own hermeticity | Hold at 6 |
| 2 | API / CLI / SDK ergonomics | 7 | Yes, both defects verified by me independently | Yes, "good, minor gaps" fits a best-in-class scaffold with a dead typecheck registration | Yes, asks for a running declare in the scaffold | Hold at 7 |
| 3 | Error messages | 5 | Yes, all four cited sites confirmed | Yes, "acceptable, works with friction" fits one designed error class and raw tracebacks elsewhere | Yes, asks for an enforcing gate, not just good messages | Hold at 5 |
| 4 | Documentation | 8 | Yes | Marginal, see below | Yes, asks for `__all__`-diffed generation | **7 in my reading; a 1-point disagreement, not a required correction** |
| 5 | Upgrade path | 7 | Yes, CHANGELOG and Deprecations section confirmed present | Yes, and the "unexercised" caveat is correctly stated as the reason it is not 8 | Yes, asks for one real kit change run end to end | Hold at 7 |
| 6 | Developer environment | 7 | Yes, pins, `.vscode/`, and the `cat4` parity gate confirmed | Yes | Yes, asks for hermeticity asserted by a test | Hold at 7 |
| 7 | Community & ecosystem | 5 | Yes, all four rubric asks checked one by one | Marginal, see below | Yes, asks for a second human to land a connector | **4 in my reading; a 1-point disagreement, not a required correction** |
| 8 | DX measurement | 7 | Yes, `@open_finding` count of 0 confirmed by me | Yes | Yes, asks for per-target durations and a cold TTHW arm | Hold at 7 |

**(d) Composite.** Weights are 30/20/15/15/10/5/3/2, exactly the fixed set in `task-b.md`, summing
to 100. Arithmetic recomputed: 2.10 + 1.60 + 0.90 + 0.75 + 0.70 + 0.35 + 0.15 + 0.14 = 6.69,
reported as 6.7. **Correct.**

**(e) Overall.** (6 + 7 + 5 + 8 + 7 + 7 + 5 + 7) = 52; 52 / 8 = 6.5. **Correct, and unweighted.**

**Scores I would move by 2 or more points: none.** Both disagreements below are one point.

**Dimension 1, the TTHW anchor is wrong but the score is not.** Task B anchors Getting Started in
the Competitive band using Task A's 166 s. My uncontended clone measured 117 s, which is Champion
by the same table. The anchor should say so. The score should not change, for a reason Task B
already gives and my clone confirms: on a stock developer machine with `commit.gpgsign=true`,
`task check` never goes green at all, so time-to-a-green-gate for a typical new hire here is not
117 s or 166 s, it is unbounded. Fix the anchor sentence, keep the 6.

**Dimension 4, Documentation 8 is one point generous.** Task B raised it from an implied 7 because
disputes D2 and D4 removed two of Task A's three complaints, and both removals are correct. What
remains is not small. §2 lists 14 of 27 exported names; `pulse_core.client`, `pulse_core.generated`
and `pulse_core.cursor` appear nowhere in the guide (I grepped the whole file, not just §2, and the
only hit is the bare class name `PulseCoreClient` in one sentence of prose at §2 line 49); and §2's
opening rule, "Import from the package root, not the submodules", is broken by the scaffold the
same guide tells you to run. Task B calls this "worse than no rule" in its own dimension note and
then scores the set at the top of the "good" band. 7 is the more consistent number. I am recording
this as a disagreement rather than a required correction because the rubric's 7-8 band is wide
enough to hold both readings and because the direction of every other documentation finding is
positive.

**Dimension 7, Community 5 is one point generous and the rise is thinly supported.** The prior
audit scored this 3; its QA recommended 4 and marked the dimension unresolved between 3 and 5.
Between `b26dee0` and `11622da` the only merged change touching this surface is #386 (PR template
names `task check`, Taskfile descriptions drop ticket ids). Against the rubric's four asks: named
owner per area is still one glob for 14 packages, the person to ask is named (met), templates are
partly there but specifically missing the kit-defect form §10 instructs authors to file, and no
second human has landed a connector. Two of four met. 4 fits better than 5. Again a one-point
disagreement, and Task B's reasoning is stated honestly enough that a reader can make the
adjustment themselves.

**Seven Characteristics.** Scored consistently with the dimension scores and with the evidence.
Findable 8 depends on D4 being right, and D4 is right: I re-ran the grep and confirmed the single
non-report hit is the pointer stub, whose matching line names `docs/connectors/authoring.md`
directly. No characteristic score is off by 2 or more.

---

## 4. Boomerang: prior versus current

Prior: `.planning/reports/2026-09-04-devex-scorecard.md` at `b26dee0`, QA corrections applied.
Current: `.planning/reports/2026-09-05-devex-scorecard.md` at `11622da`.

### Dimensions

| # | Dimension | Prior (b26dee0) | Current (11622da) | Delta |
| --- | --- | --- | --- | --- |
| 1 | Getting Started | 7 | 6 | -1 |
| 2 | API / CLI / SDK ergonomics | 6 | 7 | +1 |
| 3 | Error messages | 6 | 5 | -1 |
| 4 | Documentation | 6 | 8 | +2 |
| 5 | Upgrade path | 5 | 7 | +2 |
| 6 | Developer environment | 6 | 7 | +1 |
| 7 | Community & ecosystem | 3 (QA recommended 4) | 5 | +2 (+1 against the QA figure) |
| 8 | DX measurement | 8 (QA-corrected from 6) | 7 | -1 |
| | **Overall (unweighted mean)** | **5.9** | **6.5** | **+0.6** |
| | **Connector author DX composite** | **5.8** | **6.7** | **+0.9** |

### Seven Characteristics

| # | Characteristic | Prior | Current | Delta |
| --- | --- | --- | --- | --- |
| 1 | Usable | 6 | 7 | +1 |
| 2 | Credible | 5 | 6 | +1 |
| 3 | Findable | 4 | 8 | **+4** |
| 4 | Useful | 7 | 8 | +1 |
| 5 | Valuable | 7 | 8 | +1 |
| 6 | Accessible | 5 | 5 | 0 |
| 7 | Desirable | 5 | 6 | +1 |

### Rises of 3 or more, attributed to merged PRs

One: **Findable, 4 to 8.** The prior score's stated basis was that the best document in the repo
was linked from neither `README.md` nor `CONTRIBUTING.md` and that `docs/index.md` was a badge
stub. Both conditions were removed by PRs merged to main between the two audits
(`git log --oneline b26dee0..HEAD`):

- **#382** `docs: link connector authoring guide from README and CONTRIBUTING (1.1)`. I confirmed
  `CONTRIBUTING.md:5` now ends "Building a connector? Start with `docs/connectors/authoring.md`".
- **#379** `docs: docs/index.md becomes the front door (1.2)`. I confirmed `docs/index.md:34-37`
  now interrupts the site tour to send a connector author straight to the guide.
- **#385** `fix: correct stale README/CONTRIBUTING claims and gate them in cat8 (1.6)`. Removes
  the stale-claim half of the prior finding and gates it.

The rise is fully accounted for. No dimension or characteristic rose 3 or more without a merged PR
behind it.

### The other rises, for completeness

- Documentation +2: #379, #382, #385, plus #388 (template ships `test_config.py` and
  `factories.py`) and #389 (connector-kit spec Deprecations section).
- Upgrade path +2: #387 (`pulse-core` CHANGELOG and guide §10) and #389 (Deprecations section).
  Both were empty at `b26dee0` and both exist now; I opened them.
- Developer environment +1: #381 (`.nvmrc`, `.editorconfig`, `.vscode/extensions.json`, parity job
  named).
- Ergonomics +1: #384 (`Jitter` exported, root-import rule settled), #383 (prior-art collision
  warning), #390 (`DIRECTION=inbound` renders a RowSource/CursorStore service).
- **Community & ecosystem +2 is the weakest.** Only #386 touches this surface, and it is a PR
  template wording change. One of the two points is really the prior QA's own recommendation to
  move 3 to 4 being absorbed silently rather than a repo improvement. Recorded as a finding
  against Task B in section 5.

### Two findings against the boomerang itself

**B1. A merged fix did not fix what it claimed.** #380 `feat: task lore:init, require CHANGE on
task verify (1.3)` closed the prior audit's `task verify` finding. Task A re-found it, and I
re-measured it: `task verify` with no `CHANGE` still runs the full gate and fails after 102
seconds, because `Taskfile.yml:49`'s repo-wide `CHANGE: ""` default satisfies the `requires:
vars: [CHANGE]` that #380 added. The ledger row for #380 counts the finding as closed. This is the
most important thing in this QA pass: the ratchet recorded a fix that does not hold.

**B2. The composite delta is partly a method change, not an improvement.** The prior audit derived
four of its eight composite slices by adjusting the dimension score (Getting started 7 minus 1,
Kit upgrade 5 minus 1, Measurement 6 minus 2, Errors verbatim). Task B took all eight slices
verbatim. Applying the prior audit's adjustment style to Task B's dimensions would land the
composite nearer 6.3 than 6.7. Separately, the prior composite of 5.8 was never recomputed after
its own QA raised dimension 8 from 6 to 8 ("Connector composite 5.8 unchanged"), so the 5.8 is
stale against its own corrected inputs. **The +0.9 composite delta should be read as directional,
not arithmetic.** The dimension-level deltas and the overall mean are sound.

---

## 5. Scope

**Connector weighting.** Present and heaviest in both reports. Task A's Top 10 is explicitly
"ordered by impact on a connector author" and its journey table is a connector-author journey.
Task B's headline is the connector composite, with kit ergonomics at 30 and connector
documentation at 20 carrying half the weight. Both satisfy the contract.

**Whole-repo coverage.** Task A's Step 0 inventories all 14 packages (I counted 14), 68 task
targets (I counted 68), five doc trees, the gate suite `cat1..cat10`, CI, hooks, ownership, and the
DX self-measurement machinery. Steps 5 through 8 cover template sync, ADRs, spec archiving, the
toolchain, CI parity, ownership, and the measurement ledger, none of which is connector-specific.
The repo is covered, not just the connector slice.

**Persona rotation held.** `pap` this run, `pocar` last run, neither billing. Comparability across
runs is preserved by the fixed weights, which both audits used.

---

## 6. Hygiene

| Check | Result |
| --- | --- |
| PHI in either report | **None.** Both scan clean; the only data touched by either agent was the scaffold's empty fixtures and synthetic env values (`PAP_TOKEN=x`). Verified by reading both files in full. |
| Commits by A or B | **None.** `git log --oneline 11622da..HEAD` shows one commit, `208be59`, a ledger and handoffs commit that predates both reports and was not made by either agent. |
| Tracked files modified | **One, not attributable to A or B.** `git status --porcelain` shows ` M .mcp.json`. The diff adds a `brook-prod` MCP server entry, which is operator environment configuration unrelated to any audit activity; its mtime (19:37) precedes both report writes and the same server is loaded in this QA session. Flagging it so the coordinator does not sweep it into an audit commit. Nothing else tracked is modified. |
| Untracked files | Three: the two new reports, plus `.planning/reports/2026-09-02-connector-agent-contract.md`, which predates this run. Correct. |
| Task A's file edited by Task B | **No.** Content and mtime confirm Task B did not touch it. |
| Blindness, Task A | **Held.** No `.planning/reports/*devex*` content and no `*-check.json` is quoted or paraphrased anywhere in the evidence report; the three prior-report paths that appear are `grep -l` filename output, which the report itself annotates as unopened. |
| Blindness, Task B | **Held.** No prior score, verdict, or ledger value appears in the scorecard. Its dimension-8 reads stay inside the task's allowance. |
| Em-dashes | **Task A: 3 violations** in its own prose (L540, L618, L676); the other 15 occurrences are inside quoted command output or quoted repo text and are correct to preserve. **Task B: 0 violations**; its single occurrence is inside a quotation of a repo file. |
| Emoji | **None in either report.** Task A's one non-ASCII glyph is the warning sign inside a quoted mkdocs vendor banner. |
| `CHECKSUMS` | **Verifies.** `uv run python scripts/devex/check.py --verify-only` returns rc 0. The frozen rubric and protocol were not altered by this run. |

---

## 7. Required corrections, by severity

### Against Task A

**A1 (high, affects a scored count).** `pulse_core.connector.__all__` exports **27** names, not 28,
and `authoring.md` §2's block lists **14**, not 15. I parsed `__all__` with `ast` and extracted the
block. The undocumented gap is 13 names, not 12. Direction and conclusion unchanged; the numbers in
Step 2, Step 4 and Top-10 item 7 are wrong. Task B already scored on the correct counts.

**A2 (high, a claimed defect that does not exist).** "Two copies of the standard connector spec"
(Step 0 friction, Step 4, Top-10 item 9) is false.
`design/platform/pulse-standard-connector-spec.md` is 1117 bytes of pointer with no spec content;
its closing line names the duplicate-copy defect and the gate that guards it, and
`tests/scaffold/cat10_devex.py::test_connector_spec_has_one_canonical_copy` exists at line 86. Task
A's own stated 10/10 for this ("the standard connector spec lives in exactly one tree with the
other path a stub pointer") is the state the repo is already in.

**A3 (high, a claimed defect that does not exist).** "`scripts/template_sync.sh` reaches `repo-ade`
over SSH while the repo itself clones fine over HTTPS" (Step 5) is false. Line 18 is
`TEMPLATE_URL="${ADE_TEMPLATE_URL:-https://github.com/robford-brookai/repo-ade.git}"`. The SSH
failure is the audit machine's own global rewrite: `git config --global --get-regexp
'url\..*\.insteadof'` returns `url.gh_robford-brookai:.insteadof https://github.com/`, which
rewrote my own first clone attempt to SSH and failed it against the locked agent until I bypassed
it. Environment, not repo. The follow-on recommendation ("`task template:diff` works over HTTPS")
and the "undocumented SSH requirement" friction both fall with it.

**A4 (medium).** Task A's timings are inflated two to four times by contention it created itself
and should not be quoted as benchmarks. See the note at the end of section 2. Task A discloses the
cause but presents the numbers without that caveat attached at the point of use.

**A5 (medium).** The `I001` template defect is **conditional on the package name**. Rendering as
`papchk` (sorting before `pulse_core`) produces exactly 2 `I001` errors under `ruff check --no-fix
--select I`; rendering as `zapchk` produces none. I reproduced both. Task A's framing implies the
templates are unconditionally unsorted. The defect is real and worth fixing; the description is
not precise.

**A6 (medium).** The TTHW figure of 166 s is contended. My independent clone measured 117 s, which
crosses into the Champion band. Any future comparison against this number should use an idle
machine.

**A7 (low).** `README.md` is 360 lines, not "~250" (Step 0 table). `.planning/devex/loop.jsonl`
carries four record shapes across its 30 lines, not two (Step 8). `handoffs/` holds 22 directories,
not "10+". `openspec/specs` holds 50 markdown files, not 49. None bears on a score.

**A8 (low).** Three em-dashes in Task A's own prose (L540, L618, L676). The 15 inside quoted output
are correct as they stand.

**A9 (low).** `pyproject.toml`'s `fix = true` is at line 154, not 156.

### Against Task B

**B3 (medium).** The Getting Started TTHW anchor cites the Competitive band on a contended
measurement. Restate it: 117 s uncontended (Champion by the table), and unbounded on a stock
machine with commit signing on, which is why the score is 6. The score itself is right.

**B4 (medium).** Community & ecosystem rose from a QA-recommended 4 to 5 with only #386 behind it.
Either lower it to 4 or state in the dimension note that one of the two points is the prior QA's
recommended correction rather than a repo improvement.

**B5 (medium).** The composite delta needs the method caveat from B2 attached, and the prior 5.8 is
stale against its own QA-corrected dimension 8. Not Task B's error to have made (the boomerang is
Task C's job) but it must not be read as a clean +0.9.

**B6 (low).** Documentation 8 is one point above where its own dimension note argues. Recorded as a
disagreement, not a demand.

**B7 (low).** `Taskfile.yml:50` should be 49; `cat10_devex.py:87` should be 86.

### Against the repo, surfaced by this QA

**R1 (high).** #380 was recorded as closing the `task verify` fast-fail finding and did not. The
`CHANGE: ""` default at `Taskfile.yml:49` still satisfies `requires`, and the gate still runs to
completion before failing. The ledger says the finding is closed. Task B's ranked fix #2 addresses
the code; the ledger row also needs reopening.

**R2 (medium).** `grep -c "@open_finding" tests/scaffold/cat10_devex.py` returns 0 and
`devex_open_findings` is 0, while this audit verified at least four live defects. Task B flagged
this; I confirmed the count. A zero that means "nothing from a prior audit is still open" reads as
"the repo has no open DX findings", and the two are not the same thing.

---

## 8. Trust statement

**Rely on these as-is:**

- Every finding in Task A's Top 10 except item 9's spec-duplication half. Each one I re-tested
  reproduced, and each one whose cause is structural I confirmed in the tree.
- The six `cat5_glue_logic` failures and their cause. I reproduced them on an independent fresh
  clone of `11622da`, same six test names, same signing error, `6 failed, 2874 passed, 30 skipped,
  6 deselected`, and the identical tree goes green under `GIT_CONFIG_GLOBAL=/dev/null`. This is the
  most solidly established finding in the audit.
- All ten error cases E1 through E10. I re-triggered eight and every one matched verbatim.
- The pyright registration defect. `connector_new.py:334-337`, the template's
  `typeCheckingMode = "strict"`, and the eight-line `typecheck` target that gains no ninth line are
  all exactly as described.
- `task lint` writing files while documented read-only (`pyproject.toml:154`).
- `task verify` running the full gate before failing with no `CHANGE`. Confirmed at 102 s, not the
  claimed 403 s, and confirmed as a live defect despite #380.
- The missing `packages/billing-connector` row in `producer-registry.md`, the single-glob
  `CODEOWNERS`, the single issue template, and the absent `pulse_core.client` / `.generated` /
  `.cursor` documentation. All four confirmed directly.
- Task B's arithmetic: composite 6.69 reported as 6.7, overall 52/8 = 6.5, weights as specified.
  Recomputed and correct.
- All seven of Task B's evidence disputes. I verified each one independently and each holds.
- The dimension-level boomerang deltas and the +0.6 overall movement.
- `CHECKSUMS` verifies; the frozen rubric and protocol were not altered by this run.

**Do not rely on these without the correction:**

- Any wall-clock number in Task A. Contended, two to four times high. Use 117 s TTHW, 113 s green
  `task check`, 102 s no-CHANGE `task verify` from this QA pass.
- The "28 exported names" and "15 documented" counts. Use 27 and 14.
- The "two copies of the standard connector spec" claim. False; already fixed and gated.
- The "template sync needs SSH" claim. False; environment, not repo.
- The unconditional framing of the `I001` template defect. Name-conditional.
- The +0.9 composite delta as an arithmetic improvement. Directional only; see B2.

**Treat as one point soft:** Documentation 8 and Community & ecosystem 5. Neither is wrong enough
to move, and a reader who prefers 7 and 4 would arrive at an overall of 6.3 rather than 6.5.

No PHI appears in this report. No production network call was made. The only writes performed were
this file and three throwaway package renders inside the session scratchpad plus one throwaway
clone; no tracked file in the audited repo was modified by this QA pass and nothing was committed.
