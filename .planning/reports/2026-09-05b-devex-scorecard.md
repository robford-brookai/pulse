# DevEx scorecard, 2026-09-05b

> Corrected by the coordinator per the QA report (`2026-09-05b-devex-audit-qa.md`, section 7): C-B1 to C-B6 applied (em-dashes removed, dimension-4 pointer fixed below, confidence on 1 and 3 raised, boomerang caveats on 5 and 7, documentation double-count separated, alternate reading for 2 recorded); C-B7 (per-characteristic gap entries) not applied, cosmetic.

Repo: `/Users/Rob.Ford/Repos/robford-brookai/pulse` at `5177d05` on `main`.
Rubric: `docs/process/devex-audit/rubric.md` (frozen), including its internal-repo interpretation.
Input: `.planning/reports/2026-09-05b-devex-audit-evidence.md` (Task A).
Scorer: Task B. Blind to every prior scorecard, QA report, and per-run `.planning/devex/*-check.json`.
Method: every dimension below was spot-checked against at least two pieces of Task A's evidence by
opening the cited file or re-running the cited command. Verification commands and their output are
summarised per row; the two headline defects were reproduced end to end in a throwaway clone at
`5177d05`. No tracked file in the repo under audit was modified.

10 on this rubric means the best-practice bar adapted to an internal platform repo. It does not
mean "no visible defects"; defect-free with no magic is a 7 to 8.

---

## Headline

| Number | Value |
| --- | --- |
| **Connector author DX (weighted composite)** | **5.6 / 10** |
| **Overall DX (unweighted mean of eight dimensions)** | **6.0 / 10** |

The repo's tooling surface is genuinely strong and its golden path is broken. Those two facts are
not in tension: 68 well-named task targets, byte-exact local/CI parity, a real deprecation policy
and a self-measuring DX ratchet sit on top of a `task connector:new` that renders a package failing
the gate its own guide tells the author to run. The composite is dragged down by the 30 percent
slice where the defect lives, not by breadth of neglect.

---

## Scorecard

| # | Dimension | Score | Confidence | Method | Evidence pointer |
| --- | --- | --- | --- | --- | --- |
| 1 | Getting Started (TTHW) | **7** | High | Verified the pins, the Prerequisites section position, the tracked status of the timing ledger, and that `task check` wraps every target in `scripts/devex/timing.py`. Did not re-run the 147s gate in the repo under audit. | Task A step 1; `README.md:182`; `Taskfile.yml:548-551`; `git ls-files .planning/devex/loop.jsonl` |
| 2 | API / CLI / SDK ergonomics | **5** | High | Reproduced both defects in a fresh clone at `5177d05`: combined `--import-mode=importlib` run errors on both directions; `ruff format --diff` reformats the outbound `service.py`. Counted `__all__` (28) against the guide's paste block (26). | Task A step 2; `templates/connector/tests/test_service.py.tmpl:16`; `templates/connector/src/{{NAME}}/service.py.tmpl:135`; `Taskfile.yml:169` |
| 3 | Error messages | **6** | High | Re-ran errors 1, 2, 3 and 5 in the scratch clone; output matched Task A verbatim. Errors 4, 7, 8, 9, 10 taken on Task A's word. | Task A step 3 |
| 4 | Documentation | **7** | High | Re-ran the findability greps and `mkdocs build -s`; read the guide's section 3 and its rendered-tree fence directly and confirmed both halves of the drift. | Task A step 4; `docs/connectors/authoring.md:166-181`, the rendered-tree fence (C-B2) |
| 5 | Upgrade path | **6** | Medium | Read the CHANGELOG header, the `## Deprecations` block with its empty table, `packages/pulse-core/pyproject.toml:3`, the ADR listing and the 20-entry archive. Did not execute `task template:diff`, same limit Task A declared. | Task A step 5; `openspec/specs/connector-kit/spec.md:85-97` |
| 6 | Developer environment | **7** | High | Reproduced the blocked first commit in the fresh clone with hooks installed. Confirmed `.openlore/` is gitignored, the 11 hooks, the pins, `.env.example`, `.vscode/` holding only `extensions.json`, and the six `run:` lines in `main.yml`. | Task A step 6; `.gitignore:227`; `.pre-commit-config.yaml` |
| 7 | Community and ecosystem | **4** | High | Read `CODEOWNERS`, the `.github` tree, `CONTRIBUTING.md`, and ran the author counts. `grep -in "slack\|owner\|channel" README.md` returned nothing at all. | Task A step 7; `git log --format='%an' \| sort \| uniq -c` = 1064 Rob Ford |
| 8 | DX measurement | **6** | High | Ran `task devex:check` (`METRIC devex_open_findings=0`) and `pytest tests/scaffold/cat10_devex.py` (45 passed) while holding a reproduction of three live defects. Read the scaffold test and the tree-diagram regex. | Task A step 8; `tests/scaffold/cat10_devex.py:63-66,331,605` |

**Overall DX** = (7 + 5 + 6 + 7 + 6 + 7 + 4 + 6) / 8 = 48 / 8 = **6.0**.

### Why each score, in one line

- **Getting Started 7.** 152s is Competitive, not Champion, and the first green gate leaves an
  uncommitted diff the newcomer did not author and ends on red-inked vendor text. Nothing blocks;
  everything about the first five minutes is slightly less certain than it should be.
- **API/CLI/SDK 5.** The single most important command in the repo for this persona produces a
  package that fails the repo's own gate, in both directions, name-independently. Around that
  defect sits the best CLI surface in the repo. Acceptable with real friction, not good. Alternate reading
  recorded per QA C-B6: 4, since the documented golden path fails in both directions with no workaround in the repo.
- **Error messages 6.** The messages the repo wrote itself are 9-tier: problem, cause, worked
  example, no secret echoed. The messages it inherited and did not wrap are 3-tier. The blend is
  what a newcomer meets, and the weak ones cluster on week-one failures.
- **Documentation 7.** All eight persona questions answered in order, four entry points, clean
  strict build, grep lands right. One section makes a promise the tooling does not keep, which is a
  credibility defect rather than a coverage defect. The guide's own prose improved (PRs #401, #397); what
  broke the promise underneath it is PR #403's template change, already charged in full to dimension 2 (C-B5).
- **Upgrade path 6.** The policy is written at SHALL strength with an enforcement route and an
  issue template. It has never been exercised, and with `pulse-core` pinned at `0.1.0` behind
  workspace deps, "one release" has no operational meaning yet. Boomerang caveat (C-B4): the one-point
  fall is against a surface with zero relevant commits since `11622da`; scorer re-reading, not a measured decline.
- **Developer environment 7.** Pins, lock enforcement, hooks installed by the documented install,
  and byte-exact CI parity are all strong. One hard stop: the first Python commit on a fresh clone
  fails a hook the newcomer did not configure, with the fix documented at line 349 of the same
  guide the persona is reading.
- **Community and ecosystem 4.** Two of the interpretation's four criteria are met. The README
  names neither owner nor channel, and all 1064 commits have one author, which the rubric names as
  the criterion that cannot be manufactured. Boomerang caveat (C-B4): the one-point fall is against a surface
  whose only commits since `11622da` (PR #396) were improvements; scorer re-reading, not a measured decline.
- **DX measurement 6.** The architecture is 9-tier and rare: a strict-xfail ratchet, per-target
  timing rows, a two-arm TTHW test, and an explicit refusal to emit a 0-10 mechanically. The
  calibration is 4-tier: the headline metric reads zero while three verified defects are live.

---

## Seven DX Characteristics

| # | Characteristic | Score | Confidence | Basis |
| --- | --- | --- | --- | --- |
| 1 | Usable | **5** | High | Scaffold renders 12 files and two registrations in under a second, then the documented next command fails. Install and setup are simple; the first real use is not. |
| 2 | Credible | **5** | High | Local/CI parity is byte-exact and the deprecation policy is real. Against that, a guide that promises a green test and delivers a collection error, and a kit version that has never moved. |
| 3 | Findable | **7** | High | The obvious grep lands on exactly the right two files, four entry points reach the guide, nav is clean under strict build. `lore:init` hides at line 349 and the README names nobody to ask. |
| 4 | Useful | **8** | Medium | The kit exports 28 names proven against three real connectors, covers both directions, and the inbound overlay is a genuine design answer rather than a flag. Solves the actual problem. |
| 5 | Valuable | **7** | Medium | The scaffold plus the nine-site registration plus the ADE id chain (plan, work order, worktree, handoff, Linear) is real leverage. The time it saves is partly given back diagnosing its own output. |
| 6 | Accessible | **6** | Medium | The CLI is uniform and complete and serves humans and agents alike (`AGENTS.md`, `CLAUDE.md`). No GUI, no `.vscode/settings.json`, no editor projection of strong formatting opinions. |
| 7 | Desirable | **4** | High | Nobody outside the author has ever used it. Momentum is not measurable from a single-author history, and the rubric says so. |

---

## Connector author DX composite

Fixed slices and weights, per the audit protocol. Each slice is scored from the evidence for that
slice specifically, not copied wholesale from a dimension row; where a slice tracks a dimension the
dimension is named.

| Slice | Weight | Score | Contribution | Basis |
| --- | --- | --- | --- | --- |
| Kit API ergonomics | 30 | 5 | 5 x 0.30 = **1.50** | Dimension 2. Scaffold red in both directions; strong task surface and coherent 28-name kit around it. |
| Connector documentation | 20 | 7 | 7 x 0.20 = **1.40** | Dimension 4. Complete and findable; step 3 makes a false promise, tree fence drifts. |
| Getting started to a working connector | 15 | 4 | 4 x 0.15 = **0.60** | Clone to green gate is 152s and clean; scaffold to green gate is red. The persona's actual getting-started ends in a hard stop after two prior successes. |
| Errors on the connector path | 15 | 6 | 6 x 0.15 = **0.90** | `Config.from_env` and the NAME validator are the two best messages in the repo. The two errors that actually block a connector author (`ModuleNotFoundError`, the lint failure) name no repo-level fix. |
| Dev environment for a new package | 10 | 7 | 7 x 0.10 = **0.70** | Dimension 6. Pins and parity strong; first Python commit blocked; no connector block in `.env.example`. |
| Kit upgrade path | 5 | 6 | 6 x 0.05 = **0.30** | Dimension 5. Policy written and routed, never exercised, no version to pin. |
| Ecosystem and support | 3 | 4 | 4 x 0.03 = **0.12** | Dimension 7. Purpose-built `connector-kit-defect.yml` and a routing table; no channel, no second author. |
| Measurement of author experience | 2 | 6 | 6 x 0.02 = **0.12** | Dimension 8. Instrumented deliberately; blind to the author's actual blocking defects. |
| **Total** | **100** | | **5.64** | |

1.50 + 1.40 + 0.60 + 0.90 + 0.70 + 0.30 + 0.12 + 0.12 = **5.64**, rounded to **5.6**.

---

## Gap method: what a 10 looks like, and the one change that moves toward it

Every dimension scored below 9. Each "10" below is a bar above defect-free.

**1. Getting Started, 7 to 10.** A 10 is Champion-band and self-explaining: clone to a green gate
in under 120 seconds, the gate printing a one-screen summary of what it ran and how long each
target took instead of 600 lines ending on a vendor warning, and `git status` clean afterwards. The
newcomer's first minute produces a feeling of "that was fast and I know exactly what happened",
which is principle 8's magical moment applied to a build gate.
*Highest-leverage change:* move the timing ledger out of the tracked tree and print its rows as the
gate's closing summary. One change removes the dirty diff, replaces the last screenful, and turns
the instrument into the feedback.

**2. API/CLI/SDK, 5 to 10.** A 10 is `task connector:new NAME=x DIRECTION=either && task install &&
task check` green every time, proven by a gate that renders into a temp tree and runs the real
combined command, plus a scaffold whose closing line names the repo's own next target and whose
rendered package is production-shaped rather than toy-shaped from line one.
*Highest-leverage change:* ship `templates/connector/tests/__init__.py.tmpl` and switch both
`test_service.py.tmpl` files to `from tests.factories import ...`, matching what
`packages/billing-connector` already does correctly.

**3. Error messages, 6 to 10.** A 10 is that every failure a newcomer can hit in week one names the
**task target** that fixes it, never the underlying tool's command, including the failures the repo
inherited. `task lint` failing prints "run `task fmt`". A missing npm global prints the
`npm install -g` line. The flag form prints "use `CHANGE=foo`".
*Highest-leverage change:* wrap the three inherited failures that block week one (`lint`, missing
npm global, `openlore drift`) in a repo-level message that names the target. The repo already
demonstrates the house style in four places; this applies it to the four that matter most.

**4. Documentation, 7 to 10.** A 10 is a guide whose every command block is executed by a gate, so
it structurally cannot promise something the tooling does not deliver, and a single canonical
fresh-clone prerequisite list in `README.md` that every other document links rather than restates.
*Highest-leverage change:* make section 3's three-command block the literal content of a slow gate
test, so the doc and the gate cannot drift.

**5. Upgrade path, 6 to 10.** A 10 is a `pulse-core` version that increments, a `uv sync` that
surfaces "pulse-core 0.1.0 to 0.2.0, see CHANGELOG" in the author's terminal, and a deprecation
table with at least one row that completed the full grace window, so the policy is demonstrated
rather than asserted.
*Highest-leverage change:* cut `0.2.0` on the next kit change and add the CHANGELOG entry with its
Connector authors line, turning "one release" into a real interval.

**6. Developer environment, 7 to 10.** A 10 is that `task install` leaves the clone able to commit
and able to be opened: `task lore:init` runs alongside `pre-commit install`,
`.vscode/settings.json` pins the interpreter and formatter, and `.env.example` carries a commented
connector variable block so the excellent `ConfigError` has a destination.
*Highest-leverage change:* add `task lore:init` to `task install`. It is already idempotent and
already safe on a fresh clone, and it removes the only hard stop in this dimension.

**7. Community and ecosystem, 4 to 10.** A 10 is a two-line "who owns this, where to ask" block
above the fold in `README.md`, a named and linked channel with a searchable archive, `CODEOWNERS`
routing the kit, the Twenty surface and the ledger to different reviewers, and at least one
connector in `packages/` authored by someone else.
*Highest-leverage change:* the README block. It costs minutes, it is what the rubric checks, and it
is the only part of this dimension that a single author can fix alone today.

**8. DX measurement, 6 to 10.** A 10 is a metric that would have caught the three defects in this
report: `cat10_devex.py` renders both directions into a temp tree and runs the real combined gate,
the TTHW test measures clone to a green `task check` in both cache arms, and the tree-diagram check
compares the rendered set to the diagrammed set rather than a hand-written regex over three
filename shapes.
*Highest-leverage change:* replace `test_connector_scaffold_command_exists` with a slow test that
renders and gates. A metric that reports zero while the golden path is red is worse than no metric,
because it is trusted.

**Seven Characteristics gaps, briefly.** Usable reaches 10 when the first real use succeeds, not
just the install. Credible reaches 10 when a kit upgrade has been boring at least once. Findable
reaches 10 when the README answers "who do I ask" without a hop. Useful reaches 10 when the kit has
carried a connector someone else wrote. Valuable reaches 10 when the time the scaffold saves is not
partly returned in diagnosis. Accessible reaches 10 when opening the repo in an editor inherits its
formatting opinions automatically. Desirable reaches 10 when a second person chooses it.

---

## Ranked fixes, adoption impact over effort

Effort: S = under an hour, M = a session, L = multiple sessions. Principle numbers refer to the
rubric's DX First Principles.

| # | Fix | Effort | Principle | Why here |
| --- | --- | --- | --- | --- |
| 1 | Ship `templates/connector/tests/__init__.py.tmpl` and switch both `test_service.py.tmpl` files to `from tests.factories import ...` | S | 1 | Unblocks 100 percent of new connectors in both directions. The correct pattern already exists in `packages/billing-connector`; this is a copy, not a design. |
| 2 | Reformat the outbound `service.py.tmpl` `def run(` signature so `ruff format` is a fixed point | S | 1 | Name-independent unconditional lint failure on the default direction. One line. |
| 3 | Add `task lore:init` to `task install` | S | 1 | Removes the only hard stop between a green gate and a first commit. The target is already idempotent. |
| 4 | Add a two-line owner-and-channel block above the fold in `README.md` | S | 5 | The rubric checks the README specifically; the information already exists in `CONTRIBUTING.md` and can be lifted verbatim. |
| 5 | Replace `test_connector_scaffold_command_exists` with a slow test that renders both directions into a temp tree and runs the real combined gate | M | 5 | Turns `devex_open_findings=0` from a claim about recorded findings into a claim about the path. Prevents fixes 1 and 2 from silently regressing. |
| 6 | Make `task lint` print "run `task fmt`", and wrap the missing-npm-global and `openlore drift` failures to name the repo's targets | M | 5 | Three of the four week-one failures currently point at the wrong command. The repo's own message style is already proven in four places. |
| 7 | Move `scripts/devex/timing.py`'s output out of the tracked tree (or gitignore the ledger and collect it in CI), and print a per-target duration summary as the gate's last screenful | S | 8 | Removes the undocumented dirty diff and replaces a red vendor warning with the one thing the newcomer wants to see. |
| 8 | Add `LedgerCursorStoreError` and `TransientExhaustedError` to the authoring guide's import block | S | 6 | An author who pastes the block gets every constructor and none of the exceptions the retry pipeline raises at them. |
| 9 | Add a commented connector variable block and the `PULSE_TWENTY_DEV_*` pair to `.env.example` | S | 6 | The `ConfigError` is exemplary at naming what is missing and silent on where it goes. |
| 10 | Redefine the repo's TTHW test as clone to a green `task check`, both cache arms | M | 7 | The repo's own onboarding number omits 97 percent of the wall clock a newcomer waits, so the metric cannot detect the regression it exists for. |

**Below the cut**, real but lower leverage or lower certainty:

- `.vscode/settings.json` pinning interpreter, formatter and format-on-save (S, principle 4).
- Suppress or license the Material for MkDocs vendor warning so a green gate does not end in red
  ANSI (S, principle 5); folded into fix 7's summary line if that lands first.
- Cut `pulse-core 0.2.0` so the one-release deprecation window has an operational meaning
  (M, principle 2).
- Widen `cat10_devex.py`'s tree-diagram regex to compare the rendered set against the diagrammed
  set (S, principle 5).
- Stop `consent-ingress` subclassing the kit's `FixtureRowSource` in production source, or rename
  the kit export so the pattern does not read as sanctioned (M, principle 9 territory; principle 4
  as written).
- Add a `commit-msg` hook enforcing the `<type>: <description>` format that `CLAUDE.md` prescribes
  (S, principle 4).
- Make `task spec:validate` with no argument validate the current change rather than print
  openspec's generic usage (S, principle 5).
- Document the Python version story in Prerequisites: `uv` fetches `3.14` per `.python-version`, so
  a pyenv opinion is unnecessary (S, principle 4).
- Enforce the Node pin rather than declaring it, or downgrade the README's "(required)" to match
  reality: the full gate ran green on `v26.8.1` (S, principle 2).
- Make `task dispatch --change=foo` print the `CHANGE=` form instead of go-task's 18-line tutorial
  (M, principle 5); likely needs a wrapper, which is why it sits below fix 6.
- Move `docs/process/devex-audit/task-*.md` out of the searchable product docs tree (S,
  principle 3).
- Update `CLAUDE.md:9`'s "currently a placeholder (`foo.py`)" line, which now undersells 14 packages
  and a shipped kit (S, principle 3).
- Reconcile the four open OpenSpec changes against `CLAUDE.md`'s stated assumption of two, or
  restate the assumption (S, principle 5).

---

## Evidence disputes

Nothing in Task A's report was found to be materially wrong. Every load-bearing claim I re-tested
reproduced. The items below are inaccuracies too small to change a score, and claims I did not
verify and therefore scored at reduced confidence.

**Reproduced independently, at `5177d05`, in a throwaway clone:**

- `uv run pytest packages/pocar/tests packages/labs/tests --import-mode=importlib` errors on both
  `test_service.py` modules with `ModuleNotFoundError: No module named 'factories'`, while
  `uv run pytest packages/labs/tests` alone gives `40 passed`.
- `uv run ruff format --diff packages/pocar/src/pocar/service.py` reports `1 file would be
  reformatted`; the joined `def run(...)` line is exactly 118 characters against `line-length = 120`.
  The inbound overlay's `service.py` is already formatted.
- A first Python commit on a fresh clone with hooks installed fails
  `openlore drift ... [error] No openlore configuration found. Run "openlore init" first.`
- `task devex:check` prints `METRIC devex_open_findings=0` and `pytest tests/scaffold/cat10_devex.py`
  gives `45 passed, 3 deselected`, concurrently with all three defects above being live.
- `len(pulse_core.connector.__all__)` is 28; the guide's paste block lists 26.
- `grep -ril "authoring a connector" docs/` returns exactly `docs/connectors/authoring.md` and
  `docs/index.md`; `grep -ril "scaffold a connector" docs/` returns only
  `docs/process/devex-audit/task-a.md`.
- The guide's rendered-tree fence lists `tests/__init__.py` (not rendered) and omits
  `tests/test_receipts.py` (rendered). Both halves of the drift confirmed.
- `git log --format='%an' | sort | uniq -c` is `1064 Rob Ford`, single author.
- `.planning/devex/loop.jsonl` is tracked (`git ls-files --error-unmatch` succeeds) and
  `Taskfile.yml:548-551` wraps each gate target in `scripts/devex/timing.py`.
- 68 task targets; `.github/workflows/main.yml` has six `run:` lines, the quality job's being
  exactly `task check`.

**Minor inaccuracies in Task A, none score-changing:**

1. `README.md` is **360 lines**, not 267 as stated in step 0's surface table. The related judgement
   ("the connector pointer sits deep in the narrative") is if anything understated: Prerequisites
   begins at line 182.
2. The line-length setting is cited as `pyproject.toml:157`; it is at **line 153**. The value, 120,
   is correct and the 118-character arithmetic holds.
3. Step 7 says `grep -in "slack\|owner\|channel" README.md` "returns only incidental matches". My
   run of that exact pattern returned **zero** matches. The finding is correct and slightly
   stronger than reported.
4. Step 3 is headed "Eight realistic mistakes triggered" and then tabulates and documents **ten**.
   Cosmetic.

**Claims I could not verify, scored at reduced confidence:**

- **The 147s `task check` and the 152s TTHW total.** Re-running the full gate in the repo under
  audit would append rows to the tracked `.planning/devex/loop.jsonl`, which my read-only mandate
  forbids. I verified the mechanism behind the claim (the timing wrapper, the tracked ledger, the
  pins, the parity) but not the wall clock. Dimension 1 was scored Medium confidence for this reason; QA measured 138s independently (same band), so confidence is raised to High (C-B3).
  The Competitive-band placement is not close to the Champion boundary, so a plus or minus 20s error
  does not move the score.
- **The cold-cache arm (7s versus 3s warm).** Not re-measured.
- **Errors 4, 7, 8, 9 and 10** in step 3 (`task dispatch --change=foo`, `task twenty:deploy`,
  missing npm globals, the failing lint gate, `lore:drift` on a fresh clone). I re-ran errors 1, 2,
  3 and 5 and all matched verbatim, which is a strong prior on the rest, but the quoted text for
  those five is Task A's. Dimension 3 was Medium confidence; QA re-triggered errors 4, 7 and 10 verbatim, so confidence is raised to High (C-B3).
- **`task template:diff` and `task template:sync` behaviour.** Task A marked these INFERRED because
  they reach the template remote; I inherited the same constraint. Dimension 5 is Medium confidence
  on the template-sync component and High on the CHANGELOG, deprecation policy and ADR components,
  which I read directly.
- **The claim that 12 files render for `labs`.** I confirmed the scaffold runs in under a second and
  registers at two sites, and I read the rendered `tests/` directory, but I did not count the full
  rendered file set.

**Disagreements of emphasis, not of fact:**

- Task A's step 6 conclusion treats the blocked first commit as the highest-cost item in the
  developer-environment dimension. I agree it is the only hard stop there, but I score dimension 6
  at 7 rather than lower because the surrounding environment work (lock enforcement in the gate,
  hooks installed by the documented install, and byte-exact CI parity) is genuinely strong and
  three of the four other findings in that step are cosmetic.
- Task A presents `devex_open_findings=0` as the load-bearing observation of step 8. I would put it
  more sharply: the number is not merely uninformative, it is actively misleading to anyone who
  reads it as a health signal, which is why fix 5 ranks above fixes 6 through 10 despite costing a
  session rather than an hour.

**PHI.** No protected health information appears in this scorecard. No live system was contacted.
Verification used a throwaway clone; the repo under audit was not modified. Running `task devex:check`
wrote `.planning/devex/2026-09-05-check.json`, that target's normal untracked output.
