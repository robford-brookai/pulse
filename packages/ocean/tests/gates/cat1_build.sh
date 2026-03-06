#!/usr/bin/env bash
# Gate 1: Build & Static Analysis
# Usage: cd /path/to/ocean && ./test/cat1_build.sh
# Prereq: uv venv active or uv available in PATH
set -euo pipefail

PASS=0; FAIL=0

check() {
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then
    echo "PASS: $label"; ((PASS++))
  else
    echo "FAIL: $label"; ((FAIL++))
  fi
}

# --- Ruff lint (all service src directories) ---
for svc in event-store pocar-connector graph-projection control-plane slack-bot zcc-connector sim-driver stacte-bridge; do
  check "ruff check services/${svc}/src" bash -c "uv run ruff check services/${svc}/src/"
done

# --- Python import resolution (each service app) ---
check "import: event-store"       bash -c "cd services/event-store && PYTHONPATH=. uv run python -c 'from src.main import app'"
check "import: pocar-connector"   bash -c "cd services/pocar-connector && PYTHONPATH=. uv run python -c 'from src.main import app'"
check "import: graph-projection"  bash -c "cd services/graph-projection && PYTHONPATH=. uv run python -c 'from src.main import app'"
check "import: control-plane"     bash -c "cd services/control-plane && PYTHONPATH=. uv run python -c 'from src.main import app'"
check "import: slack-bot"         bash -c "cd services/slack-bot && PYTHONPATH=. uv run python -c 'from src.main import app'"
check "import: zcc-connector"     bash -c "cd services/zcc-connector && PYTHONPATH=. uv run python -c 'from src.main import app'"
check "import: sim-driver"        bash -c "cd services/sim-driver && PYTHONPATH=. uv run python -c 'from src.main import app'"
check "import: stacte-bridge"     bash -c "cd services/stacte-bridge && PYTHONPATH=. uv run python -c 'from src.main import app'"

# --- Existing test suites ---
check "pytest tests/requirements (54 tests)" bash -c "uv run pytest tests/requirements/ -q --tb=no"
check "pytest services/sim-driver/tests"     bash -c "uv run pytest services/sim-driver/tests/ -q --tb=no"
check "pytest services/stacte-bridge/tests"  bash -c "uv run pytest services/stacte-bridge/tests/ -q --tb=no"

# --- No secrets committed ---
check "no secrets in git log" bash -c "
  git log -p -- '**/.env*' '**/.env' 2>/dev/null |
  grep -qE '^\\+[A-Z_]+=[^$\\{]' && exit 1 || exit 0
"

echo ""
echo "Gate 1: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
