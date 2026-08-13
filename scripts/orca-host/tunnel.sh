#!/usr/bin/env bash
# tunnel.sh — forward the Orca runtime port from the cloud host to this Mac.
#
#   ./tunnel.sh          # foreground, Ctrl+C to stop
#   ./tunnel.sh --bg     # detached, writes a pidfile
#   ./tunnel.sh --stop   # kill a detached tunnel
#
# Run this after each wake. The host keeps running while the Mac sleeps, but the
# forward does not survive it.

set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-duplo-dev01}"
AWS_REGION="${AWS_REGION:-us-east-1}"
HOST_NAME="${HOST_NAME:-duploservices-dev01-brook-orca}"
PORT="${PORT:-7331}"
PIDFILE="${TMPDIR:-/tmp}/orca-tunnel.pid"

export AWS_PROFILE AWS_REGION

die() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

if [[ "${1:-}" == "--stop" ]]; then
  [[ -f "$PIDFILE" ]] || die "no pidfile at $PIDFILE"
  # Kill the supervisor FIRST. Killing the session first would just make the
  # supervisor reconnect it a few seconds later.
  kill "$(cat "$PIDFILE")" 2>/dev/null || true
  rm -f "$PIDFILE"
  # Then the orphaned session. Matched on our own port so a tunnel to some other
  # port survives.
  pkill -f "localPortNumber.*${PORT}" 2>/dev/null || true
  echo "tunnel stopped"
  exit 0
fi

command -v session-manager-plugin >/dev/null \
  || die "session-manager-plugin missing. Install it in a terminal (needs sudo):
       brew install --cask session-manager-plugin"

# Resolve the instance by Name tag, and start it through Duplo if idle-stop has
# powered it down. EC2 reads are permitted to the tenant role even though every
# mutating call is not, which is why the start goes through duploctl.
#
# Re-run on every reconnect: the host may have been stopped while the tunnel was
# down.
ensure_running() {
  read -r instance_id instance_state <<<"$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=${HOST_NAME}" \
              "Name=instance-state-name,Values=running,stopped,stopping" \
    --query 'Reservations[].Instances[].[InstanceId,State.Name]' --output text | head -1)"

  [[ -n "$instance_id" && "$instance_id" != "None" ]] \
    || die "no instance tagged Name=${HOST_NAME}"

  # More than one match is an ambiguous target, not a usable default.
  [[ "$(wc -w <<<"$instance_id")" -eq 1 ]] \
    || die "multiple instances match Name=${HOST_NAME}: $instance_id"

  [[ "$instance_state" == "running" ]] && return 0

  echo "host is ${instance_state}, starting it"
  command -v duploctl >/dev/null || die "duploctl needed to start a stopped host"
  command -v duplo-jit >/dev/null || die "duplo-jit needed to mint a portal token"

  # Mint the token with duplo-jit and pass it explicitly. duploctl's own
  # --interactive blocks without a TTY, so it fails under any non-interactive
  # caller — a launchd agent, a background job, or an agent harness. duplo-jit
  # completes silently against a live portal session.
  local tok
  tok=$(duplo-jit duplo --host "${DUPLO_HOST:?set DUPLO_HOST}" --interactive 2>/dev/null \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["DuploToken"])' 2>/dev/null) \
    || die "could not mint a Duplo portal token. Run once in a terminal:
       duplo-jit duplo --host ${DUPLO_HOST} --interactive"
  [[ -n "$tok" ]] || die "empty Duplo portal token"

  duploctl --host "$DUPLO_HOST" --tenant dev01-brook --token "$tok" \
    hosts start "${HOST_NAME#duploservices-dev01-brook-}" >/dev/null \
    || die "could not start ${HOST_NAME}"

  echo -n "waiting for SSM"
  local ping=""
  for _ in $(seq 1 60); do
    ping=$(aws ssm describe-instance-information \
      --filters "Key=InstanceIds,Values=${instance_id}" \
      --query 'InstanceInformationList[].PingStatus' --output text 2>/dev/null)
    [[ "$ping" == "Online" ]] && { echo " online"; return 0; }
    echo -n "."; sleep 10
  done
  die "host started but SSM never came online"
}

ensure_running
echo "forwarding localhost:${PORT} -> ${instance_id}:${PORT}"

start() {
  aws ssm start-session \
    --target "$instance_id" \
    --document-name AWS-StartPortForwardingSession \
    --parameters "{\"portNumber\":[\"${PORT}\"],\"localPortNumber\":[\"${PORT}\"]}"
}

# Session Manager terminates a session on its own inactivity timeout, and a
# laptop sleep or network change drops it too. None of those are errors, and the
# host keeps working throughout — only the desktop's view of it goes away. So
# reconnect rather than exiting, and re-check the host each time in case
# idle-stop powered it down while we were disconnected.
supervise() {
  local delay=5
  while true; do
    ensure_running
    start || true
    echo "tunnel closed, reconnecting in ${delay}s (Ctrl+C to stop)"
    sleep "$delay"
  done
}

if [[ "${1:-}" == "--bg" ]]; then
  # nohup + disown, not a bare `&`. A plain background job stays a child of the
  # invoking shell and dies with it — which is exactly how an earlier supervisor
  # was silently reaped, leaving the host to idle-stop with nobody connected.
  LOG="${TMPDIR:-/tmp}/orca-tunnel.log"
  nohup "$0" --supervise >"$LOG" 2>&1 &
  pid=$!
  disown "$pid" 2>/dev/null || true
  echo "$pid" > "$PIDFILE"
  sleep 2
  ps -p "$pid" >/dev/null 2>&1 \
    || die "supervisor exited immediately, see $LOG"
  echo "detached, pid ${pid}, log ${LOG}"
else
  supervise
fi
