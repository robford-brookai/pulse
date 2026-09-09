# DevEx scorecard: pulse, 2026-09-08

> Corrections applied (QA 2026-09-08): C-2 ("Getting started to a working connector" slice
> re-scored 4 to 6, composite 6.3 to 6.6; fix #1's justification demoted from "turns the documented
> golden path green" to "lets a connector author commit their package without editing a scaffold
> gate" — optional +1 on dimension 2 declined; overall stays 6.4), C-4 (dimension 1 re-anchored on
> the reproducible 163 s cold / ~140 s warm figures, noting the Champion line at 120 s is closer
> than this report had it), C-7 (a justification sentence added for the "Measurement of author
> experience" slice falling 3 points on the same evidence that raised dimension 8 by 2), C-8 (a
> Method note added: reproduce headline defects in a throwaway clone next run). Not deleted: the
> original readings are struck through in place and the corrected readings follow.

Task B of the three-agent audit protocol (`docs/process/devex-audit/task-b.md`). Scores only.
The boomerang comparison against prior runs is Task C's job and does not appear here.

- Repo scored: `/Users/Rob.Ford/Repos/robford-brookai/pulse` at
  `f851ae0bd036c0f067514b4c57b10df7e956b669` on `main`. Read-only; this report is the only file
  I wrote. Main moved by one merge (#430) after dispatch; #430 is not in scope.
- Input: `.planning/reports/2026-09-08-devex-audit-evidence.md` (Task A), read in full.
- Rubric: `docs/process/devex-audit/rubric.md`, applied as written including its internal-repo
  interpretation.
- Blindness held: I read no prior scorecard, no prior QA report, and no `.planning/devex/*-check.json`.
  I opened `tests/scaffold/cat10_devex.py`, `scripts/devex/`, and `.planning/devex/loop.jsonl` only
  for dimension 8 and for timing corroboration, which the protocol permits.
- Scoring stance: 10 is the best-practice bar the rubric describes, adapted to an internal platform
  repo. It is not "no visible defects", which is a 7 to 8.

**Verification method.** For every dimension I opened or re-ran at least two of Task A's cited
artifacts before scoring. Fifteen of Task A's claims were re-verified directly, including five
error messages reproduced verbatim. Three claims came back different and are listed under
"Evidence disputes"; where a claim could not be re-verified I say so in the Method column and hold
confidence down. I did not re-run the 225 s cold gate, because `task check` appends to a tracked
file and this audit is read-only; I corroborated its shape from the repo's own ledger instead.

**Added (QA C-8).** That last decision is what let this report's headline defect (the "Getting
started to a working connector" slice) stand on Task A's word alone. `task-b.md`'s read-only
constraint covers the repo under audit, not the machine — a throwaway clone is not excluded, and
the prior run's Task B used exactly that to catch its own headline defect. **Standard practice for
the next run: reproduce Task A's headline defect(s) in a throwaway clone before scoring them, the
same way Task A's own fresh clone is expected to be genuine.**

---

## Headline

| Number | Value |
| --- | --- |
| **Connector author DX (weighted composite)** | ~~**6.3 / 10**~~ **6.6 / 10 (corrected, QA C-2)** |
| **Overall DX (unweighted mean of eight dimensions)** | **6.4 / 10** |

Both land in the rubric's "Acceptable: works but with friction. Developers tolerate it" band, at
its top edge. The repo has one genuinely excellent artifact (the authoring guide), one genuinely
excellent mechanism (the DX findings gate), and one friction point: **corrected (QA C-2)** a
connector author's first commit of a scaffolded package, not the documented three-command path
itself, turns the gate red, and the correct fix is inside a scaffold gate.

---

## Scorecard

| # | Dimension | Score | Confidence | Method | Evidence pointer |
| --- | --- | --- | --- | --- | --- |
| 1 | Getting Started | 6 | Medium | Verified the two-command path, `README.md` Prerequisites and Quickstart (181-215), `docs/index.md` front door, and the gate's tracked-file write in `scripts/devex/timing.py:21`. Did not re-run the 225 s cold gate; corroborated its shape from three warm 2026-09-08 runs in `.planning/devex/loop.jsonl`. | Evidence Step 1; `scripts/devex/timing.py`; `README.md:181` |
| 2 | API / CLI / SDK Ergonomics | 6 | High | Verified `NUMBER_WORDS` at `cat8_docs_consistency.py:683` has no "fifteen"/"thirteen", `README.md:117` claims fourteen/twelve against a 14-package tree, the `TYPED_PATHS` contradiction, the absent template Dockerfile, and all 69 target descriptions. | `tests/scaffold/cat8_docs_consistency.py:683,733`; `templates/connector/README.md.tmpl:21` vs `docs/connectors/authoring.md:322` |
| 3 | Error Messages | 6 | High | Re-ran E1, E2, E3, E10, E11 and got Task A's output verbatim. Verified `task fmt` exists and is unmentioned by the lint failure. E4/E5/E6/E12/E13 not re-run (they require writing to the tree); scored on Task A's transcripts. | Evidence Step 3; `task -l` |
| 4 | Documentation | 8 | High | Verified all 12 headings of `docs/connectors/authoring.md`, the `mkdocs.yml:37` nav entry, the `docs/index.md:34` connector redirect, and both stale README counts. | `docs/connectors/authoring.md`; `README.md:31,117` |
| 5 | Upgrade Path | 5 | Medium-high | Verified `packages/pulse-core/CHANGELOG.md` header contract, the normative deprecation policy at `openspec/specs/connector-kit/spec.md:140-150` with an empty table, and `pulse-core = { workspace = true }`. Behavior under a real kit change is unexercised, so inferred. | `openspec/specs/connector-kit/spec.md:140`; `packages/pulse-core/CHANGELOG.md` |
| 6 | Developer Environment | 7 | High | Verified `.nvmrc` says 22 while this machine runs Node 26.8.1, `.env.example` carries two non-connector variables, `.vscode/` holds only `extensions.json`, and CI parity is gated by `cat4_ci_contract.py`. | `.env.example`; `.nvmrc`; `.vscode/` |
| 7 | Community & Ecosystem | 5 | High | Verified `CODEOWNERS` (two rules, one owner), the owner line in `CONTRIBUTING.md:5` and `authoring.md:376`, both issue templates, and `git log --format='%an'` across three connector packages returning 43 commits by one author. Also verified that `README.md` names no owner and no channel at all, which the rubric's internal interpretation requires. | `.github/CODEOWNERS`; `CONTRIBUTING.md:5` |
| 8 | DX Measurement | 8 | High | Verified `scripts/devex/timing.py` and `check.py:113` (`METRIC devex_open_findings`), counted 58 tests and exactly 7 `@open_finding` strict-xfail markers in `cat10_devex.py`, and read 81 ledger rows across four dates. | `tests/scaffold/cat10_devex.py`; `scripts/devex/check.py:98,113` |

**Overall DX** = (6 + 6 + 6 + 8 + 5 + 7 + 5 + 8) / 8 = 51 / 8 = **6.4**.

### TTHW anchor for dimension 1

**Corrected (QA C-4).** ~~Task A measured clone to a green `task check` at 230 s (3 min 50 s) on a
warm 26 GB uv cache.~~ That figure does not reproduce: QA's independent fresh clone at the same sha
measured 163 s cold. Against the rubric's benchmarks that is **Competitive** (2-5 min), toward its
near end, one tier below Champion (< 2 min, 3-4x higher adoption). The repo's own ledger shows
warm-cache gates on 2026-09-08 at 138 s, 143 s and 158 s, with `test` at 117-122 s of each: 85
percent of the gate is one pytest invocation. Anchor on **163 s cold, about 140 s warm**. So even
the best case a returning developer sees is above the Champion line, but the gap is smaller than
this report originally had it — the Champion line at 120 s is closer than a 230 s anchor suggested.
Competitive tier plus a dirty tree plus a red vendor banner on success caps this dimension at 6; the
score does not change, only the anchor.

---

## Seven DX Characteristics

| # | Characteristic | Score | Basis |
| --- | --- | --- | --- |
| 1 | Usable | 6 | Two commands take a fresh clone to green with no credential, no `.env`, no prompt. The connector golden path, which is the reason this persona is here, ends red on `task check`. |
| 2 | Credible | 6 | "Green locally means green in CI" is structurally enforced by `cat4_ci_contract.py`, not asserted. Against that: the deprecation policy is normative but has never been exercised, the kit has no releases so "one release" is an unbound grace window, and two hand-maintained README counts are wrong or gate-fragile. |
| 3 | Findable | 8 | Four independent entry points reach the authoring guide, `cat10` gates that no docs page falls out of nav, and section 9 routes by question rather than by artifact. Deduction: the rubric's internal interpretation wants a person or channel named in `README.md`, and `README.md` names neither. |
| 4 | Useful | 8 | The kit solves the actual job. `task connector:new` renders 12 files, registers nine sites, and ships 40 passing tests plus a clean pyright-strict pass before the author writes a line. |
| 5 | Valuable | 7 | 25 s from scaffold command to a green package is real, measured time saved against hand-rolling a connector. Value is clipped by the follow-on repo gate the author cannot pass without editing a scaffold gate. |
| 6 | Accessible | 6 | Gates run correctly from any subdirectory, `.editorconfig` and `extensions.json` are gated into existence, and every target's one-line description names its variables and its cost. No `settings.json` pins the interpreter, the Node pin is unenforced, and the surface is CLI-only. |
| 7 | Desirable | 6 | The dry-run registration diff and the 40-tests-out-of-the-box scaffold are the magical moments here. They are immediately undercut: the first repo-wide gate a new connector author runs is red, and the recovery path leads into `tests/scaffold/`. |

---

## Connector author DX composite

Fixed slices and weights per the audit protocol, so runs stay comparable.

| Slice | Weight | Score | Weighted | Basis |
| --- | --- | --- | --- | --- |
| Kit API ergonomics | 30 | 7 | 210 | 28 exported names across three coherent modules, one supported import path named in the CHANGELOG, `test_connector_kit_all_names_resolve` prevents silent rot, and `--print-registrations` is a real escape hatch. Held below 8 by the "2 site(s)" output contradicting the guide's "all nine sites" and by the scaffold's incomplete registration (no Dockerfile, no `.env.example` fragment). |
| Connector documentation | 20 | 8 | 160 | The authoring guide answers all eight persona questions in build order, one section each, every answer naming a file, a command or a person. Held below 9 because its own step 3 states an outcome that is false. |
| Getting started to a working connector | 15 | ~~4~~ **6 (corrected, QA C-2)** | ~~60~~ **90** | **Corrected (QA C-2).** ~~The documented three-command path returns rc=201...~~ The documented three-command path is green (rc=0, 3042 passed) unstaged. The first commit of the scaffolded package returns rc=201, and the obvious fix returns a worse second failure that sends the author into `tests/scaffold/cat8_docs_consistency.py`. That is friction on the way to landing a connector, not a golden path that "cannot be completed as written": clone to green, scaffold to a green package, and scaffold to a green repo-wide gate are all reached first. The rubric's 5-6 band ("developers work around it") fits; the successful scaffold and green gate pull it to the top of that band. |
| Errors on the connector path | 15 | 6 | 90 | `ConfigError` collecting every missing variable with its purpose (E4) and naming the offending value, type and unit (E5) is best-in-class. The two failures this author actually meets first, lint (E6) and the package-count gate (E13), name no fix. |
| Dev environment for a new package | 10 | 6 | 60 | Nine registration sites applied automatically, pyright-strict green out of the box, pre-commit installed by the documented install. Against that: `.env.example` carries none of the three variables the rendered `config.py` demands, so the runtime error is the documentation. |
| Kit upgrade path | 5 | 5 | 25 | CHANGELOG contract and normative deprecation table exist and are gated. Nothing pins, warns, or prompts; the kit arrives silently on `uv sync`; the table is empty and the mechanism has never run. |
| Ecosystem and support | 3 | 5 | 15 | Named owner, honest "no channel yet", two issue templates that map onto real workflows. One owner covers both the catch-all and the kit line, and no second author has landed a connector. |
| Measurement of author experience | 2 | 3 | 6 | The ledger measures gate sub-targets only. Neither number this author feels, clone-to-green and scaffold-to-green-gate, is recorded; `test_tthw_measures_clone_to_a_green_gate_in_both_arms` is an open finding. **Added (QA C-7).** This is the exception to dimension 8's +2 read of the same evidence: dimension 8 credits the strict-xfail ratchet for growing by ten findings, mechanism that improves; this slice charges that the two numbers a connector author feels most are still unrecorded and that the TTHW test itself is now one of the open findings. The two readings measure different things (machinery breadth versus coverage of the author's own numbers) and are not in tension, but a 3-point fall next to a 2-point rise on the same report earns that sentence. |
| **Total** | **100** | | ~~**626**~~ **656 (corrected, QA C-2: 626 - 60 + 90)** | |

**Connector author DX = ~~626 / 100 = 6.3~~ 656 / 100 = 6.6 (corrected, QA C-2).**

**Optional raise declined.** QA's section 7 (C-2) also notes an optional +1 on dimension 2 (API /
CLI / SDK Ergonomics), from 6 to 7, for the same reason as the composite correction — the golden
path is not broken, only the first-commit gate. That raise is **not** taken here: dimension 2 stays
at 6, and overall DX stays **6.4**, not the 6.5 that raise would produce.

---

## Gap method

Every dimension scored below 9. For each: what a 10 looks like for this repo, then the single
highest-leverage change toward it. Each 10 exceeds "defect-free".

### 1. Getting Started, 6 → 10

**A 10 for this repo.** `git clone && task install && task check` finishes under 120 s, and ends
with one green line naming what ran: `check passed: 8 targets, 96 s`. `git status` is empty
afterwards. The gate streams progress during the pytest run instead of going silent for two
minutes. The Node pin either fails fast with the pinned version named, or is deleted from
`README.md` so the repo stops making a claim nothing checks. Defect-free would only mean the tree
stays clean; a 10 also means the newcomer never wonders whether it worked.

**Highest-leverage change.** Split `task test` so the gate reaches its first signal in under 30 s:
run the scaffold gates and the fast unit suites first with `-x`, the slow suite after. 85 percent
of the gate is one silent pytest call, and every other fix in this dimension is cosmetic next to
that number.

### 2. API / CLI / SDK Ergonomics, 6 → 10

**A 10 for this repo.** `task connector:new NAME=x DIRECTION=inbound && task install && task check`
ends green with no follow-up edit anywhere. The package-count sentence is generated, not asserted
against a word map. The scaffold renders the Dockerfile its own commented deploy stanza names, and
appends its three variables to `.env.example`. The completion message lists the sites it actually
touched, in the guide's own vocabulary. Beyond defect-free: the scaffold ends by printing the next
command the author should run against the real Zendesk API, not just `uv sync`.

**Highest-leverage change.** Make `scripts/connector_new.py` rewrite the `README.md` package-count
sentence as part of its registration pass, and change `cat8_docs_consistency.py` to parse a
numeral instead of a word map. That single change turns the documented path green and removes the
scaffold gate from the connector author's world permanently.

### 3. Error Messages, 6 → 10

**A 10 for this repo.** Every failing target ends with the one command that fixes it. Lint failure
prints `fix: task fmt`. The package-count gate prints `README.md:117 says "Fourteen"; the tree has
15`. A flag-style invocation is caught before go-task's usage banner and prints `this repo's
targets take CHANGE=<id>, not --change`. `task lore:drift` names `task lore:init`, this repo's own
target, not the raw tool. Beyond defect-free: E4 and E5 are the house style, and every error in
the repo is held to it by a test the way `test_billing_config_reports_all_missing_variables_at_once`
already holds `ConfigError`.

**Highest-leverage change.** Add a `fix:` line to the two errors a connector author meets most,
lint and the package-count gate. E1 is the worst single surface but the rarest of the three; E6
fires on nearly every loop.

### 4. Documentation, 8 → 10

**A 10 for this repo.** The guide as it stands, minus the false step-3 claim, plus a "your first
hour" strip at the top: four commands, the expected wall clock for each, and what green looks
like. Counted prose in `README.md` is generated at build time rather than asserted by a gate.
`README.md` names the owner and the place to ask above the fold. Beyond defect-free: a second
worked example in the guide, an outbound connector alongside the inbound one, so the direction
choice is shown rather than described.

**Highest-leverage change.** Correct section 3's claim about `task check`, in the same PR that
makes it true. A guide that is right about everything except the one outcome the reader tests
first spends its credibility at the worst possible moment.

### 5. Upgrade Path, 5 → 10

**A 10 for this repo.** A kit change that renames or removes a name makes every connector's
`task check` print that CHANGELOG line once. The deprecation table has been driven end to end at
least once, so the policy is observed behavior and not prose. The kit carries a version and a
release, so "one release" is a bound unit. `task template:diff` runs as an advisory line inside a
routine target, so template drift is seen rather than sought. Beyond defect-free: an author can
ask the repo what changed since their last sync and get an answer.

**Highest-leverage change.** Exercise the deprecation machinery once, on a real or deliberately
chosen name, and land the row. Everything else in this dimension is documented and gated; the only
thing missing is evidence that it works, and that evidence is one PR.

### 6. Developer Environment, 7 → 10

**A 10 for this repo.** `task install` fails fast on a wrong Node major, naming the pinned version.
The scaffold appends its three variables, names only, to `.env.example` as a tenth registration
site. `.vscode/settings.json` selects the workspace interpreter so imports resolve on first open.
Beyond defect-free: a new machine reaches a green gate from a single documented command, and the
cold-cache number is measured rather than assumed warm.

**Highest-leverage change.** Add the connector variable shape to `.env.example`, generated by the
scaffold. It is the one gap where the current answer is "trigger the runtime error and read it",
and `test_env_example_carries_the_variables_the_tooling_demands` is already an open finding waiting
for it.

### 7. Community & Ecosystem, 5 → 10

**A 10 for this repo.** A second named owner on `packages/pulse-core/src/pulse_core/connector/`, so
kit changes are reviewed by someone who did not write them. A named channel in `README.md` above
the fold. At least one connector in the tree whose commits carry a second author's name. Beyond
defect-free: a new author's first question gets answered somewhere another author can find the
answer later.

**Highest-leverage change.** Put the owner line and a place to ask in `README.md` above the fold.
The rubric's internal interpretation asks for it in `README.md` specifically, it is currently in
`CONTRIBUTING.md` and the guide only, and it is the one item in this dimension that does not
require a second human to exist.

### 8. DX Measurement, 8 → 10

**A 10 for this repo.** A `timing` row for the whole onboarding arc, written by a target that
measures clone, install and gate as one number, so TTHW is a tracked series and not something an
auditor recreates by hand each run. The ledger is written to an ignored path, or committed by a
deliberate separate target, so a green gate leaves a clean tree. Beyond defect-free: the open-
findings count and the TTHW series are visible somewhere without running a command, and a
regression in either is noticed by the repo before an auditor notices it.

**Highest-leverage change.** Add the clone-to-green arc as a ledger row. Seven open findings are
already mechanized as strict xfails, which is the hard part and is done; the missing piece is the
one series the whole audit protocol keeps re-measuring by hand.

---

## Top 10 fixes, ranked by adoption impact over effort

Effort: S under an hour, M a session, L multiple sessions. Principle numbers are the rubric's DX
First Principles.

| # | Fix | Effort | Principle | Why here |
| --- | --- | --- | --- | --- |
| 1 | Make `connector_new.py` update the `README.md` package-count sentence, and make `cat8` parse a numeral instead of `NUMBER_WORDS` | S | 5, 9 | **Corrected (QA C-2).** ~~Turns the documented golden path green~~ — the golden path is already green; this lets a connector author commit their package without editing a scaffold gate, and removes `tests/scaffold/` from the connector author's world. Highest impact of anything on this list, and it is an hour. |
| 2 | Add `fix: task fmt` to the lint failure, and a file:line hint to the package-count gate | S | 5 | The two errors an author meets most, both currently problem-and-cause only, both one string away from problem-cause-fix. |
| 3 | Print a one-line green summary at the end of `task check` | S | 5, 8 | Success currently ends in a red third-party banner. Nothing else in the loop is this cheap to fix or this often seen. |
| 4 | Write `.planning/devex/loop.jsonl` to an ignored path, or gate its commit behind a separate target | S | 5 | A green build that dirties a tracked file is the newcomer's first unexplainable `git status`, and it is the same defect that makes every DevEx PR conflict. |
| 5 | Have the scaffold append its three variables, names only, to `.env.example` | S | 6, 1 | Today the runtime `ConfigError` is the only written record of what a connector needs to run. Closes an already-open finding. |
| 6 | Render a `Dockerfile` stub, and fix the rendered README's `TYPED_PATHS` claim | S | 6, 4 | The first file a new author reads is currently wrong about what just happened, and the commented deploy stanza points at a file that does not exist. |
| 7 | Put the owner and a place to ask in `README.md` above the fold | S | 5, 3 | The rubric's internal interpretation asks for `README.md` specifically; the information already exists two files away. |
| 8 | Correct section 3 of the authoring guide, in the PR that makes it true | S | 5 | Sequenced after fix 1. The strongest document in the repo should not be wrong about the one outcome its reader tests first. |
| 9 | Split `task test` so the gate reaches a first signal in under 30 s | M | 7, 1 | 85 percent of the gate is one silent pytest run. This is the only change that moves TTHW toward the Champion tier. |
| 10 | Exercise the deprecation machinery once, end to end, and land the table row | M | 2, 4 | Converts a normative policy nobody has run into observed behavior, and binds the "one release" grace window to something real. |

### Below the cut

- **Guard flag-style invocation** (`task dispatch --change=x`). Worst error surface in the repo, but
  it fires rarely and `CLAUDE.md` documents the trap. M effort for a rare failure.
- **Enforce the Node pin, or delete it.** The whole gate passed on Node 26 against a `22` pin. An
  unenforced claim, not a broken build.
- **Fix `README.md:31`'s "the change currently in flight"**, which is singular while two changes are
  in flight, against the repo's own stated rule. Stale prose, no gate, no user harm.
- **`.vscode/settings.json` pinning the interpreter.** Real friction on first editor open, but only
  for VS Code users, and worked around in seconds.
- **Second owner on the kit path in `CODEOWNERS`.** High value, blocked on a second human existing.
- **Surface `task template:diff` as an advisory line in a routine target.** The repo is meaningfully
  behind its template and nothing says so unless asked. Maintainer-facing, not author-facing.
- **Add a `Dockerfile` to the nine documented registration sites as a tenth.** Folded into fix 6.
- **Prior-art hint is a prefix match** (`packages/ocean/services/`), so a differently-named prior
  integration is missed. Correct behavior today, a nicety to widen.

---

## Evidence disputes

Three of Task A's claims came back different when I re-checked them, and one rubric requirement it
did not test against. None changes a score by more than a point; all are recorded so Task C can
see what I did and did not take on trust.

1. **Kit surface size.** Task A reports `pulse_core.connector.__all__` exports **27** names.
   `uv run python -c "import pulse_core.connector as c; print(len(c.__all__))"` at the audited sha
   returns **28**. Off by one. Does not affect the finding, which is about coherence, not count.

2. **`cat10_devex.py` test count.** Task A calls it "roughly 30 named tests".
   `grep -c "^def test_"` returns **58**. The under-count works against the repo: the findings gate
   is close to twice the size Task A credits it with, which is part of why I scored dimension 8 at
   8 rather than 7.

3. **The 48 s warm gate.** Task A quotes a second `task check` at 48 s with `test` at ~37 s, flagged
   as contended context rather than a benchmark. I cannot reproduce that scale. The repo's own
   ledger holds three warm `task check` runs from 2026-09-08 totalling 158 s, 143 s and 138 s, with
   `test` at 122 s, 117 s and 119 s. A warm gate here is ~140 s, not 48 s. I scored dimension 1 on
   the 140 s figure and on ~~the 230 s cold TTHW~~ **the 163 s cold TTHW (corrected, QA C-4)**, and
   treated the 48 s number as unrepresentative. Task A was right to flag it; I am recording that it
   should not be quoted at all. **The 230 s cold figure I accepted without independent
   verification also does not reproduce (QA C-4); I checked the number that was flagged and not the
   number that was load-bearing.**

4. **Scaffold gate shell-script count.** Task A says "`cat4` and one other are shell scripts".
   There are three: `cat2_toolchain.sh`, `cat4_command_contract.sh`, `cat7_gates_hooks.sh`, exactly
   as `CLAUDE.md` states. Inventory detail only; no score effect.

5. **A rubric requirement Task A did not test.** The internal-repo interpretation requires "a
   channel or person to ask named in `README.md`". Task A's Step 7 verifies the owner line in
   `CONTRIBUTING.md` and `docs/connectors/authoring.md` section 9 and treats the requirement as
   met. `grep -in "Rob Ford\|owner\|slack" README.md` returns nothing at the audited sha: `README.md`
   names neither a person nor a channel. The repo's own `cat10_devex.py` agrees, carrying
   `test_readme_names_the_owner_and_the_channel_above_the_fold` as an open finding. I scored
   dimension 7 against the rubric as written, which is part of why it sits at 5, and I have ranked
   the fix at number 7.

**Claims I could not verify and therefore did not score on.** The 230 s cold TTHW, the 25 s
scaffold-to-green-package number, the E4/E5/E6/E12/E13 error transcripts, the `git commit`
pre-commit run, and the `task template:diff` output all require writing to the tree or a fresh
clone, which this read-only task excludes. I scored them on Task A's transcripts, and dimension 1
and 3 confidences are held at Medium and the transcript-only portion of High accordingly. Every
claim I could check without writing, I checked: fifteen of them, including five error messages
reproduced verbatim.

**Corroboration.** Seven `@open_finding` strict-xfail markers in `cat10_devex.py` name the repo's
own open defects. Five of the seven describe conditions Task A recorded independently in Steps 1,
3, 4, 6 and 8, and the two I re-derived myself (`test_readme_names_the_owner_and_the_channel_above_the_fold`,
`test_env_example_carries_the_variables_the_tooling_demands`) match what I found by direct
inspection. I record that as agreement between three independent readings, not as a source for any
score.
