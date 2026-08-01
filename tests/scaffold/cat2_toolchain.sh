#!/usr/bin/env bash
# Gate 2: Toolchain & Environment
#
# Every CLI and dependency the documented bootstrap requires is present and version-compatible.
# The check list IS the README prerequisites section — if you add a prerequisite there, add it
# here (tests/scaffold/cat8_docs_consistency.py enforces the reverse direction).
#
# Usage: ./tests/scaffold/cat2_toolchain.sh
set -uo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$ROOT" || exit 1

PASS=0
FAIL=0

check() {
  local label=$1
  shift
  if "$@" >/dev/null 2>&1; then
    echo "PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $label"
    FAIL=$((FAIL + 1))
  fi
}

echo "Gate 2: Toolchain & Environment"
echo ""

# --- documented prerequisites ---
check "uv installed"        command -v uv
check "task installed"      command -v task
check "openspec installed"  command -v openspec
check "openlore installed"  command -v openlore
check "node installed"      command -v node
check "npm installed"       command -v npm
check "git installed"       command -v git

# README documents "Node.js 20.19+" for OpenSpec.
# shellcheck disable=SC2016  # the inner script must expand in the inner shell, not this one
check "node >= 20.19" bash -c '
  v=$(node -e "process.stdout.write(process.versions.node)")
  major=${v%%.*}
  rest=${v#*.}
  minor=${rest%%.*}
  [ "$major" -gt 20 ] || { [ "$major" -eq 20 ] && [ "$minor" -ge 19 ]; }
'

# Optional per the README — reported, never fatal.
if command -v orca >/dev/null 2>&1; then echo "PASS: orca installed (optional)"; else echo "SKIP: orca not installed (optional)"; fi
if command -v gh >/dev/null 2>&1; then echo "PASS: gh installed (optional)"; else echo "SKIP: gh not installed (optional)"; fi

# --- dependency resolution ---
check "lockfile in sync"        uv lock --check
check "venv syncs from lock"    uv sync --frozen --quiet

# --- dependencies the documented commands need ---
# `task test` passes --cov, which requires pytest-cov.
check "pytest-cov available"    uv run python -c "import pytest_cov"
# The scaffold gates parse YAML directly.
check "pyyaml available"        uv run python -c "import yaml"
# `task lint` runs all three.
check "ruff available"          uv run ruff --version
check "mypy available"          uv run mypy --version
check "pre-commit available"    uv run pre-commit --version
# `task docs` serves MkDocs.
check "mkdocs available"        uv run mkdocs --version

echo ""
echo "Gate 2: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
