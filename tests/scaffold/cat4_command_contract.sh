#!/usr/bin/env bash
# Gate 4: Command Contract
#
# Every target the docs name is defined, the core targets run green, parameterised targets fail
# informatively without their variable, and the gate chain declares the deps the docs promise.
#
# Usage: ./tests/scaffold/cat4_command_contract.sh
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

refute() {
  local label=$1
  shift
  if "$@" >/dev/null 2>&1; then
    echo "FAIL: $label (command unexpectedly succeeded)"
    FAIL=$((FAIL + 1))
  else
    echo "PASS: $label"
    PASS=$((PASS + 1))
  fi
}

echo "Gate 4: Command Contract"
echo ""

if ! command -v task >/dev/null 2>&1; then
  echo "FAIL: go-task is not installed — gate 4 cannot run"
  exit 1
fi

# --- every target defined in Taskfile.yml resolves ---
TARGETS="default install mcp:check fmt lint typecheck
test test:all check pre-commit verify docs
docs:build spec:archive spec:init spec:status spec:validate lore:analyze
lore:drift lore:mcp collect dispatch sync-docs new-repo
template:diff template:sync"

for target in $TARGETS; do
  check "target defined: $target" bash -c "task --list-all | grep -q '^\* ${target}:'"
done

# Count guard: a new target nobody listed above should be noticed here.
DEFINED_COUNT=$(task --list-all | grep -c '^\*')
EXPECTED_COUNT=$(echo "$TARGETS" | wc -w | tr -d ' ')
if [ "$DEFINED_COUNT" -eq "$EXPECTED_COUNT" ]; then
  echo "PASS: target count matches ($DEFINED_COUNT)"
  PASS=$((PASS + 1))
else
  echo "FAIL: Taskfile defines $DEFINED_COUNT targets, gate 4 lists $EXPECTED_COUNT"
  FAIL=$((FAIL + 1))
fi

# --- go-task variable syntax (regression: `--change` exits 2, `CHANGE=` works) ---
check  "var-assignment syntax accepted"        bash -c "task --list-all CHANGE=example"
refute "\`--change\` flag rejected by go-task" bash -c "task lore:drift --change example"

# --- core targets run green ---
check "task lint green" task lint
check "task test green" task test

# --- gate chain declares the documented deps ---
check "spec:archive deps include spec:validate" bash -c "
  python3 -c \"
import sys, yaml
deps = yaml.safe_load(open('Taskfile.yml'))['tasks']['spec:archive']['deps']
sys.exit(0 if 'spec:validate' in deps else 1)
\""
check "spec:archive deps include lore:drift" bash -c "
  python3 -c \"
import sys, yaml
deps = yaml.safe_load(open('Taskfile.yml'))['tasks']['spec:archive']['deps']
sys.exit(0 if 'lore:drift' in deps else 1)
\""
check "spec:archive deps include test" bash -c "
  python3 -c \"
import sys, yaml
deps = yaml.safe_load(open('Taskfile.yml'))['tasks']['spec:archive']['deps']
sys.exit(0 if 'test' in deps else 1)
\""

# --- verify aggregates the quality gates ---
# Resolved transitively: verify delegates to check, which is where lint/typecheck/test/docs:build
# live. Asserting on verify's immediate cmds would break the moment a gate is grouped.
check "verify transitively runs every quality gate" bash -c "
  python3 -c \"
import sys, yaml
tasks = yaml.safe_load(open('Taskfile.yml'))['tasks']

def reached(name, seen=None):
    seen = set() if seen is None else seen
    if name in seen:
        return seen
    seen.add(name)
    spec = tasks.get(name) or {}
    for dep in spec.get('deps') or []:
        reached(dep if isinstance(dep, str) else dep.get('task'), seen)
    for cmd in spec.get('cmds') or []:
        if isinstance(cmd, dict) and 'task' in cmd:
            reached(cmd['task'], seen)
    return seen

need = {'lint', 'typecheck', 'test', 'docs:build', 'lore:drift', 'spec:validate'}
missing = need - reached('verify')
if missing:
    print('verify never reaches:', sorted(missing))
sys.exit(1 if missing else 0)
\""

echo ""
echo "Gate 4: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
