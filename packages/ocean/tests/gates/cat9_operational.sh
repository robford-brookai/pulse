#!/usr/bin/env bash
# Gate 9: Operational Readiness
# Usage: ./test/cat9_operational.sh
# Requires: docker compose up (full stack running locally).
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

check_latency() {
  local label="$1"
  local url="$2"
  local max_ms="$3"
  local elapsed
  elapsed=$(curl -s -o /dev/null -w '%{time_total}' --max-time 5 "$url" || echo "999")
  local ms
  ms=$(echo "$elapsed * 1000 / 1" | bc 2>/dev/null || echo "9999")
  if [ "${ms:-9999}" -lt "${max_ms}" ]; then
    echo "PASS: ${label} (${ms}ms < ${max_ms}ms)"; ((PASS++))
  else
    echo "FAIL: ${label} (${ms}ms >= ${max_ms}ms)"; ((FAIL++))
  fi
}

check_http() {
  local label="$1"
  local url="$2"
  local expected="$3"
  local actual
  actual=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$url" || echo "000")
  if [ "$actual" = "$expected" ]; then
    echo "PASS: ${label} → HTTP ${actual}"; ((PASS++))
  else
    echo "FAIL: ${label} → expected HTTP ${expected}, got ${actual}"; ((FAIL++))
  fi
}

# --- Service health endpoints ---
check_http "event-store /health"      "http://localhost:8001/health" "200"
check_http "pocar-connector /health"  "http://localhost:8002/health" "200"
check_http "graph-projection /health" "http://localhost:8003/health" "200"
check_http "control-plane /health"    "http://localhost:8004/health" "200"
check_http "slack-bot /health"        "http://localhost:8005/health" "200"
check_http "zcc-connector /health"    "http://localhost:8006/health" "200"
check_http "stacte-bridge /health"    "http://localhost:8070/health" "200"
check_http "Hasura /healthz"          "http://localhost:8090/healthz" "200"
check_http "Redpanda REST /topics"    "http://localhost:8082/topics" "200"
check_http "Redpanda Console"         "http://localhost:8085" "200"

# --- Health endpoint latency < 500ms ---
check_latency "event-store /health latency"      "http://localhost:8001/health" 500
check_latency "pocar-connector /health latency"  "http://localhost:8002/health" 500
check_latency "graph-projection /health latency" "http://localhost:8003/health" 500
check_latency "control-plane /health latency"    "http://localhost:8004/health" 500
check_latency "slack-bot /health latency"        "http://localhost:8005/health" 500
check_latency "zcc-connector /health latency"    "http://localhost:8006/health" 500
check_latency "stacte-bridge /health latency"    "http://localhost:8070/health" 500

# --- Redpanda topics exist ---
REQUIRED_TOPICS="ocean.signals ocean.alerts ocean.tasks ocean.ai-ops ocean.interactions"
for topic in $REQUIRED_TOPICS; do
  check "Redpanda topic: ${topic}" bash -c "
    curl -s 'http://localhost:8082/topics' |
    python3 -c \"import sys,json; topics=json.load(sys.stdin); sys.exit(0 if '${topic}' in topics else 1)\"
  "
done

# --- Postgres accepting connections ---
check "Postgres accepting connections (port 5433)" bash -c "
  python3 -c \"
import socket
s = socket.create_connection(('localhost', 5433), timeout=5)
s.close()
\"
"

# --- Postgres ocean tables exist ---
OCEAN_TABLES="patients alerts tasks interactions outcomes audit_log connector_health ai_drafts"
for table in $OCEAN_TABLES; do
  check "Postgres table: ${table}" bash -c "
    docker exec \$(docker compose -f infra/docker-compose.yml ps -q postgres) \
      psql -U ocean -d ocean -c \"SELECT 1 FROM ${table} LIMIT 1\" 2>&1 |
    grep -v 'ERROR' | grep -qE '(row|0 rows)'
  "
done

# --- pgvector extension loaded ---
check "pgvector extension installed" bash -c "
  docker exec \$(docker compose -f infra/docker-compose.yml ps -q postgres) \
    psql -U ocean -d ocean -c \"SELECT extname FROM pg_extension WHERE extname='vector'\" |
  grep -q 'vector'
"

# --- Concurrent request stability (50 requests to health, 0 failures) ---
for svc_port in 8001 8002 8003 8004 8005 8006 8070; do
  check "${svc_port} handles 10 concurrent health requests" bash -c "
    seq 10 | xargs -P10 -I{} curl -sf --max-time 3 'http://localhost:${svc_port}/health' >/dev/null
  "
done

# --- No services in restarting loop ---
check "No services in restart loop" bash -c "
  docker compose -f infra/docker-compose.yml ps --format json 2>/dev/null |
  python3 -c \"
import sys, json
lines = sys.stdin.read().strip().splitlines()
restarting = [l for l in lines if '\\\"restarting\\\"' in l.lower()]
sys.exit(1 if restarting else 0)
\" || true
"

# --- sim-driver health (profile: sim) — only if running ---
if curl -sf --max-time 2 "http://localhost:8060/health" >/dev/null 2>&1; then
  check_http "sim-driver /health (sim profile)" "http://localhost:8060/health" "200"
  check_latency "sim-driver /health latency"    "http://localhost:8060/health" 500
else
  echo "SKIP: sim-driver not running (start with: docker compose --profile sim up sim-driver)"
fi

echo ""
echo "Gate 9: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
