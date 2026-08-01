#!/usr/bin/env bash
set -euo pipefail

# Orca worktree Setup Script. Wired into Project Settings > pulse > Worktree Hooks as
# `bash scripts/orca-worktree-setup.sh` — the logic lives here so it is reviewable and survives a
# re-import, because Orca saves the field itself on one machine only.
#
# .venv/ (.gitignore:145) and .openlore/ (.gitignore:215) are both gitignored, so a fresh worktree
# receives neither. Without the openlore config `openlore analyze` reports "No openlore
# configuration found" and the drift pre-commit hook then fails on any src/ or openspec/ commit —
# the failure class recorded in docs/ci-lessons.md, 2026-07-31.
#
# `pre-commit install` is deliberately absent: worktrees share .git/hooks with the primary
# checkout, whose shim already points at that checkout's .venv.

uv sync
openlore init --force
openlore analyze
