# CI and scaffold lessons

One dated entry per failure class actually observed in this repo or one generated from it. Read
this before editing a workflow, `bootstrap.sh`, or `new-repo.sh`.

**A lesson that can be expressed as a gate belongs in `tests/scaffold/`, not here.** This file is
for the residue: judgement calls, and classes a test cannot express. Every entry below names the
gate that now enforces it, or says explicitly that none does.

Fix regressions in this template, never in a generated repo — a generated repo is a copy, and a
fix applied there reaches nobody else.

---

- **2026-08-01 — A tool's own suggestion was documented without checking it applied.** Symptom:
  WORKFLOW.md told a newly generated project to consider `openlore generate` to fill
  `openspec/specs/`. On a fresh scaffold the only code is a placeholder returning its argument,
  so that command would have written specs describing template plumbing into the baseline that
  `orient()` feeds every future agent. Root cause: `openlore analyze` prints *"Spec index skipped
  … run 'openlore generate'"*, and that hint went into the docs unexamined. It is correct advice
  for openlore's typical user — someone adopting an existing codebase — and wrong for ours. The
  supporting premise was also false: drift passes against an empty specs directory (`[ok] No
  changes detected`); the hard failure seen earlier was a *missing* directory, before the
  `.gitkeep` markers, and the two states were conflated. Rule baked in: a tool's remediation hint
  is written for its typical user; verify the precondition holds for yours before documenting it.
  Specs in a greenfield repo come from the first change being archived, never from inference over
  placeholder code. Not gated — asserting "generate is only mentioned in a brownfield context"
  would be fuzzy string-matching that breaks on rewording.

- **2026-08-01 — A malformed API call was misreported as a permissions problem.** Symptom: every
  generated repo printed "branch protection not set — needs an admin token", and the suggested
  remedy was to mint a new token. The token was never the problem: it already had `repo` scope,
  `permissions.admin` was true, and `GET .../branches/main/protection` returned 404 "Branch not
  protected" rather than 403. Root cause: `gh api -f` is `--raw-field`, which sends every value
  as a string, so `-f restrictions=null` sent `"null"` where the API requires JSON null and
  `-f enforce_admins=true` sent `"true"` instead of a boolean. GitHub rejected the body; the
  script guessed at why. Rules baked in: send structured request bodies as JSON via `--input`,
  never as `-f` key=value pairs; and print the API's actual error rather than an assumed cause —
  a wrong diagnosis in an error message costs more than no diagnosis. Confirmed by running the
  corrected call, which succeeded on a private personal-account repo. Not gated: nothing
  exercises `new-repo.sh`'s GitHub-configuration path short of generating a repo.

- **2026-08-01 — Gates that only hold in the template ran in generated repos.** Symptom: three
  separate breakages of the same shape — a generated repo failed on `.ade-template-version`
  being present, then on README-as-spec assertions after the identity docs became stubs, then on
  cat6 shelling out to a `new-repo.sh` that bootstrap had deleted. Root cause: the suite was
  written inside the template, where "the repo" and "the template" are the same thing, and some
  gates assert on the template's own documentation and tooling. Rule baked in: a gate that
  checks the template's contract carries the `template_only` marker in `tests/scaffold/`, keyed
  on the git remote — checking for `.ade-template-version` instead would be circular for the one
  gate that exists to catch a stamp wrongly committed here. Gate 9's fresh-clone smoke cannot
  catch this class, because it clones the *template*; only a real generation does.

- **2026-08-01 — The CI-green check reported a false green.** Symptom: `new-repo.sh` printed "CI
  green on main" for pulse-check1 while that commit's run had failed. Root cause:
  `gh run list --limit 1` returns the most recent run, which moments after generation is the
  repo-creation run from the template's own Initial commit — green regardless of what bootstrap
  produced. Rule baked in: poll for a run whose `headSha` matches the bootstrap commit and watch
  that one. Not gated: nothing tests `new-repo.sh`'s CI-wait path short of generating a repo,
  which is why the fix was verified by generating pulse-check2 and watching it correctly report
  a failure.

- **2026-07-31 — CI ran a task runner the repo does not have.** Symptom: every run from the
  repo's first commit failed in ~25s with `make: *** No rule to make target 'check'`. Seven
  consecutive red runs, inherited by every generated repo. Root cause: `main.yml` was carried
  over from cookiecutter-uv, which uses Make, while this repo standardised on go-task; nothing
  compared the two. Local gates all passed, because they never read the workflow. Rule baked in:
  `task check` is the single contract between local and CI, and CI invokes exactly that target.
  Enforced by `tests/scaffold/cat4_ci_contract.py`, which parses every `run:` block and asserts
  each command resolves to a defined Taskfile target or a tool some step installs.

- **2026-07-31 — `task check` was not actually what CI runs.** Symptom: `check-docs` failed on a
  strict mkdocs build immediately after `task check` passed locally. Root cause: `check` covered
  lint and tests while CI additionally built the docs, so the contract was true by name only.
  Rule baked in: when CI grows a step, it goes into `check` — otherwise the drift the contract
  exists to prevent reappears one step at a time. Not gated: no test asserts that CI's job list
  and `check`'s command list are the same set, only that each command resolves.

- **2026-07-31 — Placeholder link failed a strict docs build.** Symptom: `mkdocs build -s`
  aborted on `docs/adr/ADR-0000-template.md` — `[ADR-XXXX](ADR-XXXX-slug.md)` is a broken link,
  and strict mode treats warnings as errors. Root cause: a template file written for humans, run
  through a build that resolves links. Rule baked in: placeholders in committed docs are inline
  code, never link syntax. Enforced indirectly by `task check` now including `docs:build`.

- **2026-07-31 — Scaffold gates matched no pytest collection pattern.** Symptom: `uv run pytest
  tests` collected 1 test and reported success, with nine gate files present. Root cause: files
  named `cat1_structure.py` match neither `test_*.py` nor `*_test.py`; running them by explicit
  path worked, which is exactly how the gap stayed hidden. Rule baked in: `pyproject.toml`
  widens `python_files` to include `cat[0-9]_*.py`. Enforced by
  `cat3_config_validity.py::test_every_scaffold_gate_is_collectable`.

- **2026-07-31 — Assertions true only in a bootstrapped working copy.** Symptom: the fresh-clone
  gate failed on three assertions that passed locally — `openspec/specs` existing, and every
  AGENTS.md path resolving. Root cause: the gates asserted the state of a *bootstrapped* repo
  against a *fresh clone*, so every generated repo would have failed its first `task test`. Rule
  baked in: a scaffold gate must hold in a clone of the committed tree, not only in a working
  copy that has been bootstrapped. Enforced by
  `cat9_golden_workflow.py::test_fresh_clone_passes_its_own_gates` — the only gate that can
  catch this class, and worth its runtime for exactly that reason.

- **2026-07-31 — Git cannot deliver empty directories or ignored files.** Symptom: two
  consecutive bootstrap failures in a generated repo — `openlore analyze` reporting "No openlore
  configuration found", then the drift hook reporting "No specs found". Root cause:
  `gh repo create --template` copies committed content only, so gitignored `.openlore/` and the
  empty `openspec/specs/` never arrived. Rules baked in: directories that must exist ship a
  tracked `.gitkeep`; anything gitignored is recreated by `bootstrap.sh`. Enforced by
  `cat1_structure.py`, which classifies every path in the README target tree and fails on an
  unclassified one.

- **2026-07-31 — `sed -i` is not portable.** Symptom: `bootstrap.sh` died on macOS with
  `sed: 1: "./mkdocs.yml": invalid command code .`. Root cause: BSD sed requires an explicit
  backup suffix after `-i`; GNU sed treats the next argument as the script. Rule baked in:
  detect the flavour once and reuse it. Not gated: no test runs `bootstrap.sh` end to end on
  both platforms — CI is Linux-only, so this class returns if the detection is removed.

- **2026-07-31 — `bootstrap.sh` destroyed the remote it was given.** Symptom: a generated repo
  had no `origin` after bootstrap, so the first commit had nowhere to push. Root cause: the
  script ran `rm -rf .git && git init` — correct for a local cookiecutter copy, wrong for a
  GitHub template expansion, which already starts with clean history *and* a configured remote.
  Rule baked in: bootstrap commits onto the existing repository. Not gated directly; the
  fresh-clone gate covers the surrounding behaviour.

- **2026-07-31 — Find-and-replace skipped an extension.** Symptom: a generated repo's
  `cat7_gates_hooks.sh` still referenced `src/repo_ade`. Root cause: `bootstrap.sh`'s rename
  covered `.py/.yml/.yaml/.toml/.md/.json` but not `.sh`. Rules baked in: `.sh` added to the
  include list, and the gate derives the package directory from `src/` rather than hardcoding
  it. The general lesson is that any new file type in the template needs checking against that
  include list.

- **2026-07-31 — Unsorted `iterdir()` made output machine-dependent.** Symptom: the collect
  golden listed `task-002` before `task-001`, despite creation order. Root cause:
  `collect_handoffs.py` iterated the worktree directory unsorted, so `SUMMARY.md` ordering
  varied by filesystem — a golden test that would flake across machines. Rule baked in: sort
  before iterating any directory whose order reaches output. Enforced by
  `cat9_golden_workflow.py::test_collect_ordering_is_deterministic`.

- **2026-07-31 — go-task rejects flag-style arguments.** Symptom: every documented
  `task dispatch --change <name>` exited 2 with `unknown flag: --change`, including the hints the
  glue scripts printed for users to copy. Root cause: go-task takes variables as `CHANGE=value`,
  not flags. Rule baked in: variable syntax everywhere. Enforced by
  `cat8_docs_consistency.py`, which checks the docs and both scripts' printed output.
