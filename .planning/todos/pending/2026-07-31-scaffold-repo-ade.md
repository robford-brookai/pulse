# Scaffold repo-ade from its README

## Context

`~/Repos/repo-ade` (github.com/robford-brookai/repo-ade, branch `main`, one commit) contains only `README.md`, which documents a full bootstrap procedure for an agent-development-environment template: cookiecutter-uv baseline + Taskfile + OpenSpec + OpenLore + AGENTS.md + thin-glue scripts. The task is to execute that bootstrap in-place so the repo becomes the working template it describes.

Confirmed decisions:
- License: **Not open source** (private Brookai template)
- Extras: **deptry yes**; Dockerfile, devcontainer, codecov **no**
- Baseline per README: **src layout, GitHub Actions, MkDocs, mypy, no PyPI publish**
- Names: project `repo-ade`, package `repo_ade`, author Rob Ford <rob.ford@brook.ai>, GitHub handle `robford-brookai`

Tooling present: uv 0.11.28, node v26.5.0, go-task, orca, gh. Missing: `openspec`, `openlore` (npm globals — install in step 0).

## Steps

### 0. Install missing prerequisites
```bash
npm install -g @fission-ai/openspec@latest openlore
```
Verify with `openspec --version` and `openlore --version`.

### 1. Generate cookiecutter-uv baseline (README step 1)
Cookiecutter creates a new directory, so generate into the scratchpad and copy into the repo root:
```bash
uvx cookiecutter https://github.com/fpgmaas/cookiecutter-uv.git --no-input \
  author="Rob Ford" email="rob.ford@brook.ai" author_github_handle="robford-brookai" \
  project_name="repo-ade" project_description="Repository agent development environment scaffold" \
  layout="src" include_github_actions="y" publish_to_pypi="n" deptry="y" \
  docs_tool="mkdocs" codecov="n" dockerfile="n" devcontainer="n" \
  type_checker="mypy" open_source_license="Not open source" \
  --output-dir <scratchpad>
```
Then `cp -R` contents (including dotfiles) into `/Users/Rob.Ford/Repos/repo-ade/`, **excluding the generated README.md** — the existing README (the scaffold guide) stays canonical. Remove the generated `Makefile` (Taskfile replaces it). Run `uv sync`, then commit: `chore: initial scaffold from cookiecutter-uv`.

### 2. Add Taskfile.yml (README step 2)
Verbatim from README lines 90–184 with adjustments for the src layout:
- `vars: APP: repo_ade`, plus lint/format paths pointed at `src` and `tests` (package lives at `src/repo_ade`)
- `test` target: `uv run pytest tests --cov=src --cov-config=pyproject.toml --cov-report=term-missing` (align with the coverage config cookiecutter-uv writes to pyproject.toml)
- All other targets (spec:*, lore:*, dispatch, collect, sync-docs, verify) verbatim.

### 3. Initialize OpenSpec (README step 3)
```bash
openspec init --tools claude
```
Then edit `openspec/config.yaml` with the context/rules block from README lines 202–223 (tech stack, Given/When/Then rules, 2-hour task chunks).

### 4. Initialize OpenLore (README step 4)
```bash
openlore analyze
openlore drift --install-hook
openlore drift   # verify
```
Skip `openlore generate` (needs an LLM API key).

Hook caution: cookiecutter-uv ships `.pre-commit-config.yaml`, and `uv run pre-commit install` writes `.git/hooks/pre-commit`. If `openlore drift --install-hook` overwrites that same hook file, instead add openlore drift as a `repo: local` hook entry in `.pre-commit-config.yaml` and re-run `pre-commit install`. Decide by inspecting `.git/hooks/pre-commit` after each install.

MCP config deviation from README: the README puts an `mcpServers` block in `.claude/settings.json`, but Claude Code reads project MCP servers from `.mcp.json`. Per my global MCP rules: create committed `.mcp.json` with the `openlore` stdio server (`openlore mcp`) and a `.mcp-servers.md` documenting it. Do not add an `mcpServers` key to settings.json.

### 5. Add AGENTS.md (README step 5)
Verbatim content from README lines 263–317.

### 6. Add thin-glue scripts (README step 6)
- `scripts/dispatch_tasks.py` — verbatim from README lines 323–483
- `scripts/collect_handoffs.py` — verbatim from README lines 488–631
- `templates/HANDOFF.md` — verbatim from README lines 636–671

### 7. .gitignore additions (README lines 743–753)
Append: `work_orders/`, `handoffs/`, `.openlore/analysis/call-graph.db`, `HANDOFF.md`.

### 8. Validation (README step 7)
```bash
openspec --version && openspec list --specs
openlore drift
task -l
uv run pre-commit install
uv run pre-commit run --all-files
task test
task lint
```
Fix anything that fails (formatting from pre-commit is expected on first run — re-stage and re-run until clean).

### 9. Final commit
`chore: add OpenSpec, OpenLore, AGENTS.md, and thin-glue scripts`
(Do not push unless asked.)

## Files created (target tree per README lines 700–739)
`Taskfile.yml`, `AGENTS.md`, `.mcp.json`, `.mcp-servers.md`, `scripts/dispatch_tasks.py`, `scripts/collect_handoffs.py`, `templates/HANDOFF.md`, `openspec/` (config.yaml, changes/, specs/), `.openlore/`, `.claude/commands/opsx/`, plus the cookiecutter-uv baseline (`pyproject.toml`, `src/repo_ade/`, `tests/`, `docs/`, `.github/workflows/`, `.pre-commit-config.yaml`, `uv.lock`).

## Verification
- `task verify` skips `spec:validate` gracefully or is run without `--change` only where valid — run `task lint`, `task test`, `task lore:drift` individually since no OpenSpec change exists yet.
- `git status` clean after final commit; two new commits on `main`.
- `openspec list --specs` runs without error; `.claude/commands/opsx/` slash commands exist.
- Pre-commit hook fires on commit and includes drift check.

## Known deviations from README (intentional)
1. MCP config in `.mcp.json` (+ `.mcp-servers.md`), not `.claude/settings.json` — settings.json `mcpServers` is not read by Claude Code, and global rules require project-scope `.mcp.json`.
2. Taskfile lint/test paths adapted for src layout (README's `{{.APP}}` assumes flat layout).
3. Existing README.md preserved; cookiecutter's generated README discarded.
