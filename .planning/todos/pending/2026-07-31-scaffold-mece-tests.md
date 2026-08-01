# Materialize the MECE scaffold test suite for repo-ade

## Context

`repo-ade` is a template repo whose product *is* its own structure, tooling wiring, and
documented bootstrap. Nothing currently tests that. Earlier today the bootstrap path broke three
times in a row — GNU-only `sed -i`, `rm -rf .git` destroying the `origin` remote, an undocumented
`openlore init` step, and gitignored/empty directories that a GitHub template expansion cannot
deliver. Each was found by running the bootstrap and watching it fail, one defect per cycle.

This work encodes that failure surface as a test suite so the next defect is caught by
`task test` rather than by a broken downstream repo.

A read-only dry run of the `tests-scaffold-mece` skill (Steps 1–9) is already complete; its
findings are below. This plan covers Step 10 — materializing the tests — plus fixing the defects
the dry run confirmed, so the suite lands green.

## Resolved scaffold profile

| Setting | Value | Source |
|---|---|---|
| Stack | python-uv + go-task 3.52.0 + OpenSpec 1.7.0 + OpenLore 2.1.7 + pre-commit + MkDocs + GH Actions | manifest detection |
| Package | `repo_ade` (dist `repo-ade`) | `pyproject.toml:2,46` |
| `RUN` | `uv run pytest` | `uv.lock` present |
| `TEST_DIR` | `tests/scaffold/` | `testpaths = ["tests"]`, `pyproject.toml:59` |
| `TASK` | `task` | `Taskfile.yml` |
| Targets defined | 17 | `task --list-all` |
| Hook ids | 11 (8 pre-commit-hooks, 2 ruff, 1 local `openlore-drift`) | `.pre-commit-config.yaml` |
| Glue scripts | `scripts/dispatch_tasks.py`, `scripts/collect_handoffs.py` | `scripts/` |
| Existing coverage | `tests/test_foo.py` only — zero scaffold coverage | glob |

## Confirmed defects to fix

All seven verified during the dry run, not inferred. Fix these first so the suite lands green.

| # | Defect | Location | Fix |
|---|---|---|---|
| 1 | README Taskfile snippet is **invalid YAML** — `{{` opens a flow mapping inside a flow sequence, so `yaml.safe_load` raises `expected ',' or ']', but got '{'` | `README.md:116` (block starts :90) | Convert the snippet's `cmds: [...]` inline form to block form, matching the real `Taskfile.yml` |
| 2 | `task <target> --change X` **exits 2** with `unknown flag: --change`. Every documented invocation is broken | `README.md:790,825,847,850` (prose) | Rewrite as `task dispatch CHANGE=add-user-auth` (verified: var-assignment form exits 0) |
| 3 | The **scripts print the same broken form** to the user as their "next step" hint | `scripts/dispatch_tasks.py:151,152`, `scripts/collect_handoffs.py:133` (+ README copies :478,479,625) | Same rewrite, in the f-strings |
| 4 | **`openlore init` is never documented.** §4 jumps to `openlore analyze`, which fails with `No openlore configuration found` on a fresh clone | `README.md:228` (0 mentions of `openlore init` repo-wide) | Add `openlore init` as the first command of §4 |
| 5 | README `.gitignore` snippet ignores only `.openlore/analysis/call-graph.db`; the real file ignores all of `.openlore/` | `README.md:749` vs `.gitignore:215` | Sync snippet to the real `.gitignore` stanza |
| 6 | Target tree promises `.claude/settings.json` for MCP config; repo actually has `.claude/settings.local.json` plus an **undocumented `.mcp.json`** (0 README mentions) | `README.md:246,707` | Document `.mcp.json` in the tree; correct the MCP-config prose |
| 7 | README-embedded script snippets diverged from disk — cosmetic only (ruff reflow at line-length 120, one added `# noqa: S607`), but enough to fail a byte-equality test | `README.md` python blocks vs `scripts/*.py` | Sync snippets to disk verbatim, so Cat 8 can assert byte-equality |

Checked and **clear** — do not "fix" these: `uv run openlore` resolves correctly (2.1.7, uv falls
through to PATH); all 6 configs parse; every documented target is defined; `.git/hooks/pre-commit`
is the framework shim (no ownership conflict); node 26.5.0 ≥ documented 20.19; all 9 prerequisite
CLIs present.

## The 9 gates

Each file asserts against the real values above — no placeholders.

1. **`cat1_structure.py`** — 36 entries parsed from the README target tree, each classified
   `committed` / `generated` / `gitignored`, because a template clone receives only the first
   class. Asserts `git check-ignore` matches `work_orders/`, `handoffs/`, `/HANDOFF.md`; that
   `templates/HANDOFF.md` is **not** ignored; that `src/repo_ade/__init__.py` matches
   `[tool.hatch.build.targets.wheel] packages`; and that no `Makefile`/`justfile` remains. This
   gate is where the empty-dir class (`openspec/specs/`, `openspec/changes/`, `.openlore/analysis/`)
   gets pinned — git cannot carry empty dirs, so `bootstrap.sh` must recreate them.
2. **`cat2_toolchain.sh`** — the 9 prerequisite CLIs, node ≥ 20.19 parsed from README, `uv lock
   --check`, and that `pytest-cov` backs the documented `--cov` flag.
3. **`cat3_config_validity.py`** — `task --list-all` exit 0; `tomllib` on pyproject; `pre-commit
   validate-config`; `.mcp.json` declares the `openlore` server; `openspec/config.yaml` has
   `schema:`; both workflows have `jobs:`; mkdocs parses.
4. **`cat4_command_contract.sh`** — all 17 targets defined; `task lint` and `task test` green;
   `spec:archive` deps are exactly `[spec:validate, lore:drift, test]`; and the regression test for
   defect #2 — `task dispatch CHANGE=x` parses while `task dispatch --change x` exits 2.
5. **`cat5_glue_logic.py`** — unit tests on the real signatures: `parse_tasks(Path) -> list[dict]`
   (milestone attribution, `done` flag from `[x]`/`[X]`, body capture), `emit_work_orders` →
   `task-001.md` with `## Requirements` and the change name, `collect_handoffs` copying only
   worktrees that have a `HANDOFF.md`, `summarize_handoffs` referencing all N.
6. **`cat6_edge_cases.py`** — parametrized: missing `tasks.md` → exit 1 + stderr; empty file →
   `No tasks found` + exit 0; malformed lines (`- not a checkbox`, header-only, `-[ ]` no space)
   never raise; no worktrees → exit 1; absent output dir created; unicode/long titles; re-run
   overwrites deterministically.
7. **`cat7_gates_hooks.sh`** — `git archive HEAD` into a temp sandbox, `git init`, install hooks;
   asserts the framework owns `.git/hooks/pre-commit`, all 11 hook ids fire, a ruff violation
   blocks the commit, and `openlore drift` is clean. Never touches the real repo.
8. **`cat8_docs_consistency.py`** — the gate that caught defects 1, 2, 4, 5, 6, 7. Every README
   yaml/json block parses; every backticked `task <target>` is defined; every AGENTS.md path
   exists; prerequisites cover every CLI any bootstrap step invokes (case-insensitive — README
   writes "Node.js", not `node`); README script snippets byte-equal `scripts/*.py`.
9. **`cat9_golden_workflow.py`** — committed `data/fixture-change/tasks.md` → dispatch → work
   orders byte-equal `data/golden-work-orders/`; determinism across two temp dirs; collect vs
   golden (path-normalized); `REGEN=1` regenerates goldens explicitly. `@pytest.mark.slow`:
   fresh-clone `uv sync --frozen` + `task test`.

Gate order: 1 → 2 → 3 → 4 (‖ 5, 6) → 7 → 8 → 9.

## Files to write

```
tests/scaffold/
├── conftest.py                  ROOT fixture, git-sandbox fixture, slow-marker helpers
├── cat1_structure.py            pytest
├── cat2_toolchain.sh            shell, chmod +x
├── cat3_config_validity.py      pytest
├── cat4_command_contract.sh     shell, chmod +x
├── cat5_glue_logic.py           pytest
├── cat6_edge_cases.py           pytest
├── cat7_gates_hooks.sh          shell, chmod +x
├── cat8_docs_consistency.py     pytest
├── cat9_golden_workflow.py      pytest
└── data/
    ├── fixture-change/tasks.md          milestones, checked + unchecked, body lines
    ├── golden-work-orders/task-00N.md   generated once, then committed
    └── fixture-worktrees/wt{1,2}/       wt1 has HANDOFF.md, wt2 does not
```

## Config changes

- **`pyproject.toml`** — register the `slow` marker and default it off:
  ```toml
  [tool.pytest.ini_options]
  testpaths = ["tests"]
  markers = ["slow: excluded from the default run (sandbox + fresh-clone gates)"]
  addopts = '-m "not slow"'
  ```
- **`pyproject.toml:107`** — `per-file-ignores` is currently `"tests/*" = ["S101"]`. Ruff globs do
  not cross `/`, so this likely misses `tests/scaffold/*.py` and every `assert` would trip `S101`
  under `task lint`. Verify, and broaden to `"tests/**" = ["S101"]` if confirmed. The generated
  files already carry `# noqa: S603, S607` on every `subprocess` call.
- **`Taskfile.yml`** — add `test:all` (`uv run pytest {{.TESTS}} -m "" --cov=...`) so the slow
  gates stay reachable, and reference it from the README quality-gate table.

## Verification

1. `uv run pytest tests/scaffold -v` — all gates pass except those marked slow.
2. `uv run pytest tests/scaffold -m slow -v` — sandbox and fresh-clone gates pass.
3. `./tests/scaffold/cat2_toolchain.sh && ./tests/scaffold/cat4_command_contract.sh && ./tests/scaffold/cat7_gates_hooks.sh` — each prints `PASS:` lines and exits 0.
4. `task lint` — ruff-format, ruff-check, and mypy clean on the new files.
5. `task test` — fast by default; confirm the scaffold gates are collected and the slow ones skipped.
6. `task pre-commit` — all 11 hooks pass on the new files.
7. **Prove the suite catches regressions.** Revert defect #1 in a scratch copy (restore the inline
   `cmds: [...]` form) and confirm `cat8` fails; revert the `openlore init` line and confirm the
   prerequisites test fails. A green suite that cannot go red is not a test suite.
8. **Prove it against a real consumer.** `git push`, then re-run
   `~/repos/repo-ade/new-repo.sh test-project2 test_project2 "Scaffold suite check"` and run
   `task test` inside the generated repo. This is the end-to-end claim: a fresh repo from the
   template passes its own scaffold gates. Delete `test-project2` afterward.

## Out of scope

- `OLD_PACKAGE=$(ls src/)` in `bootstrap.sh:20` breaks silently if `src/` holds more than one
  entry. Cat 1 will assert the single-package layout, which detects the precondition but does not
  harden the script.
- The commit-retry wrapper in `bootstrap.sh` re-runs `git commit` on any failure, so a genuine
  hook failure prints twice. Cosmetic; Cat 7 covers the behavior that matters.
- `src/repo_ade/foo.py` and `tests/test_foo.py` are cookiecutter placeholders. The README tree
  says `src/<package_name>/` generically, so no test asserts on them either way.
