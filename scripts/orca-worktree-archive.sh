#!/usr/bin/env bash
set -euo pipefail

# Orca worktree Archive Script. Wired into Project Settings > pulse > Worktree Hooks as
# `bash scripts/orca-worktree-archive.sh`, and runs when a worktree is archived or removed.
#
# AGENTS.md makes HANDOFF.md the channel for spec updates, and `task collect CHANGE=<id>` reads it
# out of live worktrees via `git worktree list`. An archived worktree is gone before collect can
# see it, so preserve the handoff first, then reclaim the venv.

if [ -f HANDOFF.md ]; then
  mkdir -p "$ORCA_ROOT_PATH/handoffs/_archived"
  cp HANDOFF.md "$ORCA_ROOT_PATH/handoffs/_archived/${ORCA_WORKSPACE_NAME}-HANDOFF.md"
  echo "Preserved HANDOFF.md -> handoffs/_archived/${ORCA_WORKSPACE_NAME}-HANDOFF.md"
fi

rm -rf .venv
