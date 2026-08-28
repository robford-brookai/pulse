#!/usr/bin/env bash
# idle-stop.sh — shut the host down after a sustained quiet period.
#
# Runs ON the host, every 10 minutes, via orca-idle-stop.timer.
#
# `shutdown -h` STOPS this instance rather than terminating it: the EC2
# attribute instanceInitiatedShutdownBehavior is "stop", and the root volume
# has DeleteOnTermination=true, so a terminate would destroy the disk. Verify
# that attribute is still "stop" before trusting this script on a rebuilt host.
#
# Restart with `duploctl hosts start orca`, or just run tunnel.sh, which starts
# the host for you.

set -euo pipefail

PORT="${ORCA_PORT:-7331}"
IDLE_MINUTES="${IDLE_MINUTES:-120}"   # quiet time before shutdown
CHECK_MINUTES="${CHECK_MINUTES:-10}"  # must match the timer interval
MIN_UPTIME_MINUTES="${MIN_UPTIME_MINUTES:-15}"
STATE=/var/lib/orca-idle-stop.count

log() { logger -t orca-idle-stop "$*"; printf '%s\n' "$*"; }

# ---------------------------------------------------------------------------
# Never shut down a host that just booted. Without this, a host stopped while
# a client was mid-reconnect can power-cycle in a loop.
# ---------------------------------------------------------------------------
uptime_min=$(( $(cut -d. -f1 /proc/uptime) / 60 ))
if (( uptime_min < MIN_UPTIME_MINUTES )); then
  log "uptime ${uptime_min}m below floor ${MIN_UPTIME_MINUTES}m, skipping"
  exit 0
fi

# ---------------------------------------------------------------------------
# Activity signals. ANY of these means the host is in use.
#
# A running agent is the load-bearing one: the whole point of this host is that
# work continues while the laptop sleeps, so an unattended agent must never be
# read as idle just because no client is connected.
# ---------------------------------------------------------------------------
active_reason=""

if pgrep -u ubuntu -f '[c]laude' >/dev/null 2>&1; then
  active_reason="claude agent running"
elif pgrep -u ubuntu -f '[c]odex' >/dev/null 2>&1; then
  active_reason="codex agent running"
elif [[ $(ss -Htn "state established sport = :${PORT}" 2>/dev/null | wc -l) -gt 0 ]]; then
  active_reason="client connected on ${PORT}"
fi

if [[ -n "$active_reason" ]]; then
  echo 0 > "$STATE"
  log "active (${active_reason}), counter reset"
  exit 0
fi

# ---------------------------------------------------------------------------
# Quiet. Accumulate, and stop once the run of quiet checks covers IDLE_MINUTES.
# ---------------------------------------------------------------------------
count=$(cat "$STATE" 2>/dev/null || echo 0)
count=$(( count + 1 ))
echo "$count" > "$STATE"

elapsed=$(( count * CHECK_MINUTES ))
if (( elapsed >= IDLE_MINUTES )); then
  log "idle ${elapsed}m >= ${IDLE_MINUTES}m, stopping host"
  echo 0 > "$STATE"
  /sbin/shutdown -h now "orca-idle-stop: idle ${elapsed}m"
else
  log "idle ${elapsed}m of ${IDLE_MINUTES}m"
fi
