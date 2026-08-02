#!/usr/bin/env bash
set -euo pipefail

# bootstrap.sh — run after cloning the template
# Usage: ./bootstrap.sh <new-project-name> <package-name> <description>

PROJECT_NAME="${1:?Usage: bootstrap.sh <project-name> <package-name> <description>}"
PACKAGE_NAME="${2:?Missing package name}"
DESCRIPTION="${3:?Missing description}"

# sed -i is not portable: BSD sed (macOS) requires an explicit backup suffix,
# GNU sed treats the next argument as the script. Pick the right form once.
if sed --version >/dev/null 2>&1; then
  SEDI=(sed -i)
else
  SEDI=(sed -i '')
fi

# Detect the old package name from the src/ directory
OLD_PACKAGE=$(ls src/)

echo "Replacing: $OLD_PACKAGE → $PACKAGE_NAME"
echo "Project: $PROJECT_NAME"
echo "Description: $DESCRIPTION"

# Rename package directory
mv "src/$OLD_PACKAGE" "src/$PACKAGE_NAME"

# Find-and-replace across all text files
grep -rl "$OLD_PACKAGE" --include="*.py" --include="*.yml" --include="*.yaml" --include="*.toml" --include="*.md" --include="*.json" --include="*.sh" . | \
  xargs "${SEDI[@]}" "s/$OLD_PACKAGE/$PACKAGE_NAME/g"

# Update pyproject.toml metadata
"${SEDI[@]}" "s/name = \".*\"/name = \"$PROJECT_NAME\"/" pyproject.toml
"${SEDI[@]}" "s/description = \".*\"/description = \"$DESCRIPTION\"/" pyproject.toml

# Update Taskfile APP var
"${SEDI[@]}" "s/APP: .*/APP: $PACKAGE_NAME/" Taskfile.yml

# Update OpenSpec config context
"${SEDI[@]}" "s/Tech stack: .*/Tech stack: Python ($PACKAGE_NAME), uv, ruff, mypy, pytest/" openspec/config.yaml

# Clear template state
rm -rf openspec/changes/ work_orders/ handoffs/ .openlore/

# Template-authoring artifacts. These are about building the template and mean nothing in a
# project generated from it — worse, the package rename rewrites their prose into nonsense.
# new-repo.sh goes too: creating further repos from the template is the template's job, and the
# `new-repo` task already refuses to run once .ade-template-version exists.
rm -rf .planning/ docs/ade-compare.md new-repo.sh

TEMPLATE_REPO="${ADE_TEMPLATE_REPO:-robford-brookai/repo-ade}"

# Replace the template's identity documents with project stubs. README.md, CLAUDE.md and
# CONTRIBUTING.md describe repo-ade — how to build the template, what its gates mean — and the
# package rename cannot fix that, because it substitutes the module name and not the prose. A
# generated repo that says "this is a GitHub template repository" misleads every agent that
# reads it. AGENTS.md, docs/contracts/ and docs/adr/ are kept: those are starting points, not
# claims about this repo's identity.
#
# This is the GitHub-template equivalent of copier's _skip_if_exists, resolved in the only
# direction available to us: overwrite once, at generation, and let the project own them after.

cat > README.md <<README_STUB
# $PROJECT_NAME

$DESCRIPTION

## Quickstart

\`\`\`bash
task install
task check
\`\`\`

Run \`task\` on its own to list every command, grouped by area and in workflow order.

## How this repo is organised

- \`AGENTS.md\` — operating contract for agents working in Orca worktrees. Binding.
- \`CLAUDE.md\` — session contract for Claude Code, including PHI rules.
- \`openspec/\` — change lifecycle: proposal, design, specs, tasks, archive.
- \`docs/contracts/\` — what this repo publishes and consumes. Cross-repo integration goes
  through these, never by cloning another repo into this one.
- \`docs/adr/\` — architecture decisions, append-only.
- \`tests/scaffold/\` — gates that validate the repo's own structure and wiring.

## Template

Generated from [repo-ade](https://github.com/$TEMPLATE_REPO). Pull later template fixes with
\`task template:diff\` and \`task template:sync\`; both leave this file alone.
README_STUB

cat > CLAUDE.md <<CLAUDE_STUB
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

$PROJECT_NAME — $DESCRIPTION

The package lives in \`src/$PACKAGE_NAME/\`.

## Commands

\`\`\`bash
task              # list commands, grouped by area
task check        # lint, typecheck, tests, docs build — exactly what CI runs
task fmt          # apply formatting and fixable lint rules
task test:all     # includes the slow scaffold gates
task pre-commit   # all hooks
\`\`\`

Thin-glue targets take go-task variable syntax: \`task dispatch CHANGE=add-auth\`. Passing the
change as a flag instead exits 2 with \`unknown flag\`.

## Data sensitivity (PHI)

- No PHI in logs, commits, test fixtures, error messages, or docs. Synthetic data only.
- Never send PHI to an external service — web search, third-party APIs, MCP tools, published
  artifacts.
- Flag any code path where PHI could reach a logger or leave the process, even if the current
  inputs are synthetic.

## Conventions

- \`task check\` is the contract between this machine and CI. Green locally means green in CI.
- No live network in tests; CI has no secrets by default.
- Specs are owned by the doc-updater: write proposed changes to \`HANDOFF.md\`, per \`AGENTS.md\`.
- \`docs/adr/\` is append-only; a superseded decision gets a status flip and a new ADR.
CLAUDE_STUB

cat > CONTRIBUTING.md <<CONTRIB_STUB
# Contributing to $PROJECT_NAME

\`\`\`bash
task install
task check      # must pass before every commit; it is what CI runs
\`\`\`

\`task fmt\` applies the formatting and lint fixes that \`task lint\` only reports.

Pre-commit hooks run \`ruff\`, \`mypy\` and \`openlore drift\` on every commit. A hook that rewrites
a file fails the commit by design — re-stage and commit again.

Read \`AGENTS.md\` before making changes as an agent, and \`CLAUDE.md\` for the session contract.
CONTRIB_STUB

echo "Wrote project stubs: README.md, CLAUDE.md, CONTRIBUTING.md"

# openspec/specs/ and openspec/changes/archive/ ship with tracked .gitkeep markers, so a
# template clone does receive them. `openspec/changes/` is deleted just above, though, which
# takes its marker with it — hence the recreate. The openlore-drift hook hard-fails when
# openspec/specs/ is missing, so this is load-bearing either way.
mkdir -p openspec/specs openspec/changes/archive
touch openspec/specs/.gitkeep openspec/changes/archive/.gitkeep

# Record which template commit this repo was generated from. A GitHub template clone shares no
# history with the template, so without this stamp there is no way to tell what the repo is
# level with — and `task template:diff` has no baseline to compare against.
if TEMPLATE_SHA=$(gh api "repos/$TEMPLATE_REPO/commits/main" --jq .sha 2>/dev/null); then
  echo "$TEMPLATE_SHA" > .ade-template-version
  echo "Template version: $TEMPLATE_SHA"
else
  echo "WARN: could not resolve $TEMPLATE_REPO HEAD; .ade-template-version not written."
  echo "      Record it later with: git ls-remote https://github.com/$TEMPLATE_REPO main | cut -f1 > .ade-template-version"
fi

# Re-initialize. `.openlore/` is gitignored, so a repo created from the GitHub
# template never receives a config — `analyze` needs `init` to write one first.
openlore init --force
openlore analyze
uv sync --all-packages
uv run pre-commit install

# Commit the bootstrap. Keep the existing repo and its origin remote — a
# GitHub template expansion already starts with clean history, so re-init'ing
# here would only throw away the remote that `gh repo create --clone` set up.
git add -A
# pre-commit's fixer hooks (end-of-file-fixer, trailing-whitespace) rewrite
# files and fail the first run by design; re-stage their fixes and commit.
git commit -m "Initialize $PROJECT_NAME from ADE template" || {
  git add -A
  git commit -m "Initialize $PROJECT_NAME from ADE template"
}
if git remote get-url origin >/dev/null 2>&1; then
  git push
else
  echo "No origin remote — skipping push."
fi

echo ""
echo "Done. Next steps:"
echo "  openspec init --tools claude  # if not already configured"
echo "  /opsx:propose \"first feature\""
echo "  task -l  # see available tasks"
