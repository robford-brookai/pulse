# QA of the PULSE devex audit (Tasks A and B)

Date: 2026-09-02
Repo under QA: `/Users/Rob.Ford/Repos/robford-brookai/pulse`, HEAD `99d9b7a` on main
Inputs: `.planning/reports/2026-09-02-devex-audit-evidence.md` (Task A, 1,004 lines) and
`.planning/reports/2026-09-02-devex-scorecard.md` (Task B, 267 lines)
Contract: gstack `devex-review/SKILL.md`, plus the Task A and Task B briefs
Independent fresh clone for this QA: `.../scratchpad/qa-fresh`, logs `qa-onboard.log` and
`qa-check.log`

I re-ran 19 of the cited commands, including a second independent fresh-clone bootstrap, five of
the triggered errors, `task check`, `mkdocs build -s` inside it, `task template:diff` and
`cat7_gates_hooks.sh`. I opened every cited file path.

---

## Verdicts

**Task A (evidence): ACCEPT WITH CORRECTIONS.**
Every material finding reproduces. The fresh-clone timing, all five re-run error scenarios, the
`__all__` defect, the 227-line spec drift, the four all-zeros action SHAs, the cat7 failure count
and the `template:diff` output all matched, several of them verbatim. The corrections are
counting errors (four of them), two quoted commands that cannot produce the output attributed to
them, one journey step asserted as observed that was not performed, and 31 em-dashes against an
explicit no-em-dash constraint. None of them moves a finding.

**Task B (scorecard): ACCEPT WITH CORRECTIONS.**
Every arithmetic operation is correct, the connector weighting is stated and sums to 100 percent,
and the "Evidence disputes" section is genuinely adversarial: it independently caught two of Task
A's errors, including the substantive one. The corrections are one rubric misapplication that
appears in the headline table (TTHW tier), two inherited counting errors it repeated without
rechecking, one claim it inherited that is contradicted by a file it did not open, and a
systematic tendency in the gap method to define "a 10" as "no visible defects", which is a 7-8 on
the skill's own rubric.

No score in either report needs to move by 2 or more points.

---

## 1. Coverage checklist

Skill Steps 0 through 8, plus the Task A brief's named deliverables.

| # | Requirement | Status | Where |
|---|---|---|---|
| S0 | Target discovery, surfaces inventoried | PASS | A:21-70 (surface table, connector surfaces) |
| S0b | Boomerang baseline checked | PASS | A:72-87, `NO_PRIOR_PLAN_REVIEW` stated with both commands |
| S1 | Getting started audit, fresh clone timed | PASS | A:89-175, log at `scratchpad/onboard.log` |
| S2 | API / CLI / SDK ergonomics | PASS | A:177-350, connector-weighted |
| S3 | Error message audit | PASS | A:352-478, ten scenarios against the Elm/Rust/Stripe model |
| S4 | Documentation audit | PASS | A:480-563 |
| S5 | Upgrade path audit | PASS | A:565-627 |
| S6 | Developer environment audit | PASS | A:629-700 |
| S7 | Community and ecosystem audit | PASS | A:702-760 |
| S8 | DX measurement audit | PASS | A:762-812 |
| B1 | Fresh clone timed, stage by stage | PASS | A:117-124; reproduced independently, see 2.1 |
| B2 | Six or more errors triggered and quoted verbatim | PASS | Nine triggered (E1-E9), E10 correctly labelled INFERRED |
| B3 | Connector scaffold attempt | PARTIAL | A:314-325 lists the eight registration sites, correct. But the journey row "T+30:00 Creates `packages/my-connector/` and runs `task check` / Passes, and means nothing" was not performed: A's own method note says "No tracked file was modified. The only file written is this report." The inference is sound (`TESTED_PATHS` is an explicit path list) but it is presented as a measured outcome and is not labelled INFERRED. |
| B4 | Gap-method entries per dimension | PASS | A: "What a 10 looks like for this repo" closes all nine sections; B: a gap section per dimension with a named highest-leverage change. See 3.4 for a calibration caveat. |
| B5 | Connector author journey | PASS | A:814-845, 18 rows, 9 stuck points, elapsed time from T+0 |
| B6 | Top-10 friction list | PASS | A:847-920, explicitly ordered by impact on connector authors |
| B7 | Hall of fame per-pass calibration | PASS | Both cite Passes 1-8. Spot-checked Pass 3: the Stripe `resource_missing` / `doc_url` shape and the "TypeScript buries Did you mean at the bottom" anti-pattern are quoted accurately by both reports. |
| B8 | Skipped sections stay skipped | PASS | No Preamble, Artifacts Sync, Telemetry, Plan Status Footer, Review Readiness Dashboard or `browse` usage in either report. A states the Scope Declaration explicitly at A:14-17. |
| B9 | Scores confined to Task B | PASS | `grep -n "/ 10" A` returns nothing. A's line 11 states the split and holds to it. |

One overstatement worth naming: Task A's Step 3 opens "Ten mistakes triggered". Nine were
triggered; E10 was inferred, which the body says plainly. The section lead contradicts its own
body.

---

## 2. Evidence integrity: re-run table

All commands run from `/Users/Rob.Ford/Repos/robford-brookai/pulse` unless the row says the fresh
clone. "Verbatim" means the output string matched the report character for character.

### 2.1 Timing and gates

| # | Command | Claimed (Task A) | Observed (this QA) | Match |
|---|---|---|---|---|
| 1 | fresh `git clone` + `task install` + `task check` | clone 3s, install 2s, check 130s, TTHW 135s | clone 2s, install 2s, check 125s, total 129s | YES, within 5 percent. Independent second clone, same HEAD `99d9b7a`, `task check` RC=0. |
| 2 | `ls .git/hooks/pre-commit` after clone and `task install` | absent | absent | YES |
| 3 | `bash tests/scaffold/cat7_gates_hooks.sh` on a fresh clone | "Gate 7: 17 passed, 4 failed", rc=1 | "Gate 7: 17 passed, 4 failed" | YES, exact, including the same four failing assertions |
| 4 | `task template:diff` | `a1de595b..fc72974b`, "15 files changed, 2981 insertions(+), 26 deletions(-)", "Apply with: task template:sync" | identical | YES, verbatim |
| 5 | `task check` includes green `mkdocs build -s` | green | green, "Documentation built in 0.64 seconds" | YES |

### 2.2 Triggered errors

| # | Command | Claimed | Observed | Match |
|---|---|---|---|---|
| 6 | `bash bootstrap.sh` | `bootstrap.sh: line 7: 1: Usage: bootstrap.sh <project-name> <package-name> <description>` | identical | YES, verbatim. `bootstrap.sh:7` is the `${1:?...}` expansion, as claimed. |
| 7 | `task dispatch` (E2) | `dispatch_tasks.py: error: argument --change: expected one argument` | identical | YES, verbatim |
| 8 | `task dispatch CHANGE=my-new-connector` (E3) | `Error: openspec/changes/my-new-connector/tasks.md not found` | identical | YES, verbatim |
| 9 | `task spec:validate` (E8) | four `openspec validate` alternatives | identical, plus one line Task A dropped: `Or run in an interactive terminal.` | YES with a trimmed tail. Does not change the finding that E8 is the best message and comes from a third-party tool. |
| 10 | `openspec validate connector-pattern` (E7) | `Unknown item 'connector-pattern'. Did you mean: connector-kit, coverage-state, month-open, identity-matching, verdict-relay-run?` | identical | YES, verbatim. All five suggestions are spec names, confirming A's "suggests from the wrong namespace". |
| 11 | `[n for n in c.__all__ if not hasattr(c,n)]` (E6) | the four `DEFAULT_*` / `submit_with_retry` names | identical, `__all__` length 24 | YES |
| 12 | `from pulse_core.connector import *` | `AttributeError: module 'pulse_core.connector' has no attribute 'DEFAULT_BASE_DELAY_SECONDS'` | identical | YES, verbatim |
| 13 | `Config.from_env()` with empty env (E4) | `MissingConfigVariableError: required environment variable BILLING_CONNECTOR_TOKEN is not set` at `config.py:148` | identical | YES, verbatim |
| 14 | `BILLING_CONNECTOR_STALE_AFTER=banana` (E5) | `ValueError: invalid literal for int() with base 10: 'banana'` at `config.py:159` | identical | YES, verbatim |

### 2.3 Static claims

| # | Check | Claimed | Observed | Match |
|---|---|---|---|---|
| 15 | `grep -rn "0000...0" .github/` | 4 hits in `ci-health.yml` and `auto-heal.yml` | 4 hits, same lines 11 / 16 / 100 / 111 | YES |
| 16 | `diff` of the two connector spec copies | 227 lines | 227 lines | YES. Caveat in 4.3. |
| 17 | `declare.py` constants | lines 42, 43, 44, 67 | lines 42, 43, 44, 67 | YES |
| 18 | Eight registration sites | `pyproject.toml` 73/91/211, `Taskfile.yml` 19/35/48/138/426-448 | 73/91/211 and 19/35/48/138/438-460 | YES. The Taskfile shift is concurrent work adding `twenty:key:rotate` (+12 lines) after Task A ran, not an error. |
| 19 | `mkdocstrings` scope | `paths: ["src/pkg_pulse"]`, `docs/modules.md` is `::: pkg_pulse.foo` | identical | YES |
| 20 | `ci-health.yml` trigger | `workflow_dispatch` only | `workflow_dispatch: {}` only | YES |
| 21 | `task test:all` is pytest-only | pytest-only, no shell gate | confirmed; `main.yml` never names cat2/cat4/cat7 or any `.sh` | YES |
| 22 | `uv` cache size | 26 GB | 26G | YES |
| 23 | Python matrix | 3.10 through 3.14, `fail-fast: false` | identical | YES |
| 24 | `.ade-template-version` | `a1de595b8591691a624d67d60efaa20d73641967` | identical | YES |
| 25 | Kit file line counts | rows 241, consume 192, declare 120 | 241 / 192 / 120 | YES |
| 26 | `connector-kit/spec.md` | 84 lines, 5 requirements | 84 lines, 5 `### Requirement:` headings | YES |
| 27 | Connector `__init__` docstring is stale | "the declare pipeline joins it as it is extracted" while `declare.py` ships | confirmed | YES |
| 28 | `.pre-commit-config.yaml` excludes a nonexistent devcontainer | claimed | `exclude: ^.devcontainer/devcontainer.json` at lines 10 and 12; no `.devcontainer/` | YES |

### 2.4 Cited paths

Every file path cited by either report exists and says what is claimed. Every absence claimed is
real: `templates/connector`, `.github/ISSUE_TEMPLATE`, `.github/CODEOWNERS`,
`.github/PULL_REQUEST_TEMPLATE.md`, `.editorconfig`, `.vscode/`, `.idea/`, `.devcontainer/` are
all absent. `docs/process/env-vars-retreival.md` exists with the misspelling as reported. No
dangling reference found in either report.

### 2.5 Discrepancies found

| # | Report | Claim | Observed | Severity |
|---|---|---|---|---|
| D1 | A, Step 1 Friction 2 | `grep -rniI "prerequisite\|you will need\|..."` (no `-E`, unescaped pipes) yields "the only hit is README.md:14" | The command as printed matches nothing, rc=1. The `-E` variant reproduces the reported behaviour. | Medium. The conclusion is right, the printed command cannot produce it. |
| D2 | A, Step 7 | same pattern, "two false positives on the substring task in" | Same: verbatim command returns rc=1. With `-E` it returns exactly `CONTRIBUTING.md:4` and `README.md:8`. | Medium, same class as D1. |
| D3 | A, Step 2 | "The reference implementation does not use the advertised surface" / "billing-connector reaches past the package root" | `service.py:50` imports `ConsumerHandler, Deduper, InMemoryDeduper, Sleeper, consume_once` from the package root. Only the two declare-layer imports go deep, and only because `__init__.py` does not export `declare`. | Medium. Selective evidence: A quoted the two deep imports and omitted the root import from the same package. The narrower true statement, that the declare surface has no user via the root and therefore stays broken, still supports the finding. |
| D4 | A, Step 3 / journey | "Four required environment variables (`config.py` lines 49, 53, 57, 62)", "four edit-rerun cycles" | Three are required (raises at 148, 152, 156). `BILLING_CONNECTOR_STALE_AFTER` defaults at 159. Three cycles. | Low. Task B caught this independently and stated it correctly. |
| D5 | A, Step 4 | "16 of 36 docs pages are outside the nav" | 15. The `check.log` list Task A quoted has 15 entries; A's own count of 21 nav entries plus 15 equals 36. | Low |
| D6 | A, Step 0 | `README.md` 41 lines | 38 | Low. Task B caught this. |
| D7 | A, Step 0 | `billing-connector` "10 test modules" | 9 `test_*.py` files (12 `.py` including `conftest`, `factories`, `__init__`) | Low |
| D8 | A, Step 3 lead | "Ten mistakes triggered" | Nine triggered, E10 inferred, as A's own body says | Low |
| D9 | A, journey T+30:00 | new package "Passes, and means nothing" presented as observed | Not performed. Sound inference from the explicit path lists, but unlabelled. | Medium, see B3 above. |
| D10 | B, scorecard row | "36 docs pages, 22 nav entries" | 21 nav entries (A had this right) | Low |
| D11 | B, Documentation row and Findable | inherits A's "16 of 36" | 15 | Low |
| D12 | B, fix 3 and Error Messages row | "all 8 CHANGE-taking targets lack `requires:`" | 9 targets take `{{.CHANGE}}`: `dispatch`, `checkoff`, `collect`, `replan`, `linear:sync`, `sync-docs`, `spec:validate`, `spec:archive`, `spec:status`. B's fix list names `verify`, which does not take CHANGE directly, and omits `spec:status` and `sync-docs`. None has `requires:`. | Low |
| D13 | B, dispute 3 | `requires:` is on 16 targets, "every one of them credentialed or deploy-shaped" | 16 confirmed, but `new-repo` (NAME/PKG/DESC) and `synthea:regen` (PROFILE) are neither. The precedent for a plain non-credential `requires:` is therefore stronger than B states, which helps B's own fix 3. | Low, and it favours B's recommendation |
| D14 | B, dispute 1 | "four modified tracked files" at scoring time | Seven at QA time (`.gitignore`, the demo5 report, `Taskfile.yml`, `docs/runbooks/demo5-end-to-end.md`, two demo scripts, one test) | Not an error. Concurrent demo5 work on the same checkout, still moving. B was right to flag it. |

---

## 3. Score calibration

Task B's eight dimension scores, checked for (a) verifiable evidence, (b) rubric and TTHW
consistency, (c) whether 10 means best-in-class, (d) composite arithmetic.

| Dimension | B's score | Evidence verifiable? | Rubric-consistent? | My read | Move |
|---|---|---|---|---|---|
| Getting Started | 4 | Yes: TTHW re-measured at 129s, bootstrap trap reproduced verbatim, hooks absent on my own clone | Rubric 3-4 "Poor, developers complain" fits a quickstart whose first named command needs two unnamed tools and whose most bootstrap-shaped file is a destructive trap | 3 or 4 | No, 1 point at most |
| API / CLI / SDK | 4 | Yes: `__all__` defect and 8 registration sites both reproduced exactly | Fits. The `task` surface is genuinely 7-tier work; the kit surface is 2-tier. A 4 is a fair blend and B says so. | 4 | No |
| Error Messages | 3 | Yes: 5 of 9 errors re-triggered verbatim | Fits 3-4. Arguably 2 given four raw tracebacks and zero doc links, but 3 is defensible because E3 and E8 carry exact paths and alternatives. | 3 | No |
| Documentation | 3 | Yes: `site_name: repo-ade`, `::: pkg_pulse.foo`, off-nav list all reproduced | Fits | 3 | No |
| Upgrade Path | 5 | Yes: I reproduced `template:diff` verbatim, which B had marked Medium confidence for not re-running. That confidence can be raised to High. | Fits 5-6 "works with friction": a best-in-class sync mechanism against no CHANGELOG and no pin | 5 | No |
| Developer Environment | 5 | Yes: CI parity at `main.yml:50`, four all-zeros SHAs, `test:all` pytest-only | Fits | 5 | No |
| Community & Ecosystem | 4 | Yes: all four absences confirmed; 20 handoff records confirmed | Fits | 4 | No |
| DX Measurement | 2 | Yes: the DX-vocabulary grep now returns only these two new reports; `ci-health.yml` dispatch-only with a dead pin | The 1-2 band reads "developers abandon after first attempt", which does not map onto a measurement dimension. B's choice of 2 over 0 is justified by `ci-lessons.md` and `ci_health.sh` existing. Slightly generous against B's own connector-slice score of 1 for the same concept. | 1 or 2 | No |

### 3.1 Arithmetic, all correct

- Connector composite: 0.60 + 0.40 + 0.30 + 0.45 + 0.40 + 0.15 + 0.12 + 0.02 = 2.44, reported as
  2.4. Each contribution equals score times weight. Correct.
- Weights: 30 + 20 + 15 + 15 + 10 + 5 + 3 + 2 = 100 percent. Stated, with a written rationale.
  Correct.
- Overall repo DX: mean(4, 4, 3, 3, 5, 5, 4, 2) = 30 / 8 = 3.75, reported as 3.8 and labelled
  "unweighted mean of the eight dimensions". Correct and correctly labelled.

### 3.2 The one rubric misapplication

Both reports call the measured TTHW "Champion". The skill's table is Champion under 2 minutes,
Competitive 2 to 5 minutes. 135 seconds is 2 minutes 15 seconds. My independent measurement, 129
seconds, is also over the line. **The correct tier is Competitive, not Champion, on both
measurements.**

Task A at least contradicts itself in the same sentence ("inside the skill's Champion tier
(< 2 min) at the boundary, and comfortably Competitive"). Task B carried only the wrong half
forward into the headline scorecard row: `135s (Champion)`. This is the single correction a
reader is most likely to repeat, because it sits in a bolded table row.

### 3.3 Is 10 used as "closest to best practice"?

Mostly yes, and this is the strongest part of Task B's method: every gap entry describes a 10 in
repo-specific terms, as the skill's gap method requires, and names one highest-leverage change.

The exception is level. Several "a 10" definitions describe the absence of defects rather than
best-in-class:

- Documentation: "repoint mkdocstrings, sweep the nav, retitle the site". That produces a correct
  docs site, which on the skill's rubric is a 7-8. A 10 against the Pass 4 standard would add
  working search, copy-paste-complete connector examples, and an information architecture that
  answers the persona's eight questions in the order they are asked, which Task A's own question
  table sets up and Task B's gap entry does not carry through.
- Developer Environment: "fix the four SHAs, add `.editorconfig`, run the shell gates". Again the
  removal of defects.
- Community: "add CODEOWNERS, an issue template, and a channel name". Reaching a 10 on the
  Findable and Accessible characteristics implies something closer to a searchable answer surface,
  not three files.

Getting Started, API ergonomics, Error Messages and Upgrade Path do reach for the real thing
(a scaffold that performs all eight registrations, the Stripe `doc_url` shape, a CHANGELOG with a
connector-authors section). So the pattern is inconsistent rather than absent.

### 3.4 Consistency between the two score systems

The Seven Characteristics table and the eight dimensions are scored independently and do not
contradict each other: Findable 2 sits below Documentation 3, which is right given Findable also
absorbs "nobody to ask". Useful 6 is the only characteristic scored above the highest dimension
score, and its justification ("the useful parts are reachable only by whoever built them") argues
for a lower number than 6. That is a 1-point tension, not a defect.

---

## 4. Scope

**Connectors weighted heaviest: PASS in both.**
Task A devotes Step 2 entirely to the connector surface, adds a connector-specific journey table
with nine stuck points, and states its top-10 list is "ordered by impact on connector authors".
Task B builds an explicit connector composite with published weights and a written rationale, and
leads the report with it (2.4) ahead of the repo number (3.8).

**Whole repo still covered: PASS.**
All nine skill steps are present and several are entirely non-connector: CI pinning and workflow
health, mkdocs and the ADR nav, template sync, the ADE workflow and handoff provenance, DX
measurement. Task A's surface inventory covers all 14 packages, 36 docs pages, 47 spec
directories, 20 handoff records and the full 63-target command surface, not just the connector
slice.

One scope gap worth naming for a future pass, in neither report: of the 14 packages, only
`billing-connector` and `pulse-core` were examined. `ocean`, `twenty-app`, `twenty-projection`
and `verdict-relay` were counted but not opened, and `twenty-app` is the one Node/TypeScript
surface in the repo, so the JS-side developer experience is untested by either report. Neither
report claims otherwise, so this is a limit, not an error.

---

## 5. Hygiene

| Check | Result |
|---|---|
| PHI | None. Every quoted value is a variable name, a path, a count or a synthetic literal (`banana`, `x`, `y`, `my-new-connector`). No patient identifier, no name, no record. PASS. |
| Tracked files modified by the audit | None. `git status --porcelain` shows seven modified tracked files, all belonging to the concurrent demo5 workstream (`.gitignore`, `Taskfile.yml` adding `twenty:key:rotate`, `docs/runbooks/demo5-end-to-end.md`, the demo5 report, two demo scripts, one Twenty test). `git diff --stat` totals 25 insertions across those seven, none in a file either audit touches. PASS. |
| Untracked files added | `.planning/reports/2026-09-02-devex-audit-evidence.md`, `.planning/reports/2026-09-02-devex-scorecard.md`, and this file. Plus `scripts/pulse-ledger/rotate_twenty_key.sh` from the demo5 workstream. PASS for the audit. |
| Tracked files, re-checked at write time | The concurrent demo5 workstream committed while this QA ran. `git status --porcelain` now shows only the three untracked report files and no modified tracked file at all, which confirms the seven modifications above belonged to that workstream and not to either audit. PASS. |
| Commits made | None by any of the three audit tasks. HEAD is still `99d9b7a`, unchanged from the start of both audits, and the fresh clones confirm it. PASS. |
| Network to production | None found. Both audits touched only `github.com` (clone and `template:diff`). Every credentialed target was left alone. PASS. |
| Emojis | Zero in both reports. PASS. |
| Em-dashes | **Task A: 31. FAIL.** Task B: 0. PASS. The Task A brief says "no em-dashes" explicitly. |

---

## 6. Required corrections, ordered by severity

1. **Task B, headline scorecard: change `135s (Champion)` to `135s (Competitive)`.** The skill's
   Champion tier is under 120 seconds. 135s and my independently measured 129s are both
   Competitive. Task A's Step 1 sentence needs the same fix, and it should drop the internal
   contradiction in the same clause.
2. **Task A, Step 2: correct "the reference implementation does not use the advertised surface".**
   `packages/billing-connector/src/billing_connector/service.py:50` imports five names from the
   package root. Restate as: the consume layer is imported from the root, the declare layer is
   deep-imported because `__init__.py` never exports it, which is exactly why the broken names
   have no user.
3. **Task A: mark the T+30:00 journey row as INFERRED.** A new package was never created. The
   inference from `LINT_PATHS` / `TESTED_PATHS` / `COV_PATHS` being explicit path lists is sound
   and I confirmed it, but the row reads as a measurement.
4. **Task A, Step 1 and Step 7: add `-E` to the two greps, or quote the command that actually
   ran.** Both printed commands return nothing as written. The conclusions are correct under the
   `-E` variant, which I ran.
5. **Task A: strip the 31 em-dashes.** Explicit constraint in the brief; Task B complied.
6. **Both: "16 of 36 docs pages outside the nav" is 15 of 36.** 21 in nav plus 15 off-nav equals
   36, which is Task A's own arithmetic. Task B should also correct "22 nav entries" to 21.
7. **Task A, Step 3 and journey: three required environment variables, not four; three edit-rerun
   cycles, not four.** Task B already published this correction; Task A should absorb it. The
   cited lines 49/53/57/62 are the constant declarations, not the raise sites, which are 148, 152,
   156.
8. **Task B, fix 3: nine CHANGE-taking targets, not eight.** Add `spec:status` and `sync-docs`,
   drop `verify` (it delegates and takes no CHANGE of its own).
9. **Task A: "Ten mistakes triggered" should read nine triggered plus one inferred**, matching its
   own body and Method Notes.
10. **Task A: `README.md` is 38 lines, `billing-connector` has 9 test modules.** Cosmetic; Task B
    already noted the README count.
11. **Task B: raise Upgrade Path confidence from Medium to High.** I reproduced `task
    template:diff` verbatim, including the `a1de595b..fc72974b` range and the 2,981-insertion
    figure that B declined to re-run.
12. **Task B, optional: lift the "what a 10 looks like" bar for Documentation, Developer
    Environment and Community.** As written they describe a defect-free 7-8, not the best-in-class
    9-10 the rubric reserves.

---

## 7. Trust statement

**Rely on these as-is.**

- Every finding in Task A's Steps 0 through 8. I re-ran 19 cited commands; the substantive ones
  matched, most of them verbatim. The single highest-risk claim, that a fresh clone reaches a
  green `task check` in about two minutes, reproduced on an independent clone at 129 seconds
  against the claimed 135.
- `cat7_gates_hooks.sh` failing 17-passed / 4-failed on a fresh clone. Reproduced exactly on my
  own clone, which is strong evidence because it is a stateful gate.
- The connector kit's `__all__` defect, the four unresolved names, and the `AttributeError` on
  star import. Reproduced exactly, and the fix is as small as both reports say.
- The eight registration sites, the four all-zeros action SHAs, the 227-line spec diff, the
  `mkdocstrings` placeholder scope, the `workflow_dispatch`-only `ci-health.yml`, and every
  claimed absence (`templates/connector`, `CODEOWNERS`, issue and PR templates, `.editorconfig`,
  `.vscode/`, `.devcontainer/`).
- `task template:diff` at 2,981 pending insertions from `a1de595b..fc72974b`. Verbatim.
- Task B's arithmetic in full: every contribution, the 100 percent weight sum, the 2.44 composite,
  and the 3.75-to-3.8 overall mean. All correct, and the weighting is stated rather than implied.
- All eight dimension scores as ordinal judgements. None is off by 2 or more, and each cites
  something I verified.
- The connector composite of 2.4 and the overall 3.8, read as what they are: an author-weighted
  composite and an unweighted mean, both stated as such.

**Do not rely on these without the correction.**

- The word "Champion" beside 135s, in both reports. The correct tier is Competitive.
- "16 of 36 docs pages outside the nav" (it is 15) and Task B's "22 nav entries" (it is 21).
- "Four required environment variables" and "four edit-rerun cycles" in Task A. It is three and
  three.
- "The reference implementation does not use the advertised surface" as an unqualified statement.
- The T+30:00 journey row, until it is relabelled INFERRED.
- Task A's `README.md` at 41 lines and `billing-connector` at 10 test modules.
- The two greps printed in Task A's Step 1 and Step 7, as commands. Their conclusions hold; the
  commands as written do not run.

**Neither report's ranked action list changes.** Task A's top 10 friction points and Task B's top
10 fixes both survive every correction above, in the order they were published. The one-line fixes
at the head of Task B's list (`pre-commit install` in `task install`, importing `declare` in the
connector `__init__.py`, `requires: vars:` on the CHANGE targets, and replacing the four dead
action pins) are each confirmed by a command I ran in this QA.

---

## Method notes

- Second fresh clone at `.../scratchpad/qa-fresh`, logs `qa-onboard.log` and `qa-check.log`,
  cloned at HEAD `99d9b7a`, the same commit both audits used.
- Task A's own clone and logs (`scratchpad/pulse-fresh`, `onboard.log`, `check.log`) were present
  and were read directly. `onboard.log` matches the report's quoted stage table exactly, and
  `check.log` carries the mkdocs off-nav list the report quotes.
- Network reached only `github.com`, for two clones and one `template:diff`. No production system
  was contacted, no credentialed target was invoked.
- No tracked file was modified and no commit was made by this QA. The only file written is this
  report.
- No PHI appears in this report.
