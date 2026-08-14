#!/usr/bin/env bash
# deploy.sh — apply the pulse-ledger command API's Duplo service, LB config, and secret to
# tenant dev01-brook. Repo-only artifacts, applied here; this script never stores a credential
# and never mints more than one Duplo portal token per run.
#
#   scripts/pulse-ledger/deploy.sh <image-ref>
#
# <image-ref> is the full image reference `task ledger:image TAG=...` (or `ledger:deploy`) built
# and pushed — this script does not build or push an image; that is the Taskfile's job
# (`task ledger:image`, `task ledger:deploy`). This script only applies the Duplo-side objects
# in packages/pulse-ledger/infra/duplo/.
#
# Secret values (DATABASE_URL, PULSE_LEDGER_WRITER_TOKEN_*, etc.) are never arguments, env vars
# read directly by this script, or literals anywhere in this repo. They come from a local
# KEY=VALUE file the operator prepares OUTSIDE this checkout, whose path is passed as
# PULSE_LEDGER_SECRET_ENV_FILE — see docs/runbooks/pulse-command-api-deploy.md for exactly which
# keys that file must hold.
#
# Full procedure, including the database bootstrap and migration steps this script does not
# perform: docs/runbooks/pulse-command-api-deploy.md.

set -euo pipefail

die() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

DUPLO_HOST="${DUPLO_HOST:-https://duplo.cloud.brook.ai}"
DUPLO_TENANT="${DUPLO_TENANT:-dev01-brook}"
SERVICE_NAME="pulse-ledger-api"
SECRET_NAME="pulse-ledger-api-secret"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DUPLO_DIR="${REPO_ROOT}/packages/pulse-ledger/infra/duplo"
SERVICE_TEMPLATE="${DUPLO_DIR}/command-api.service.json"
LB_TEMPLATE="${DUPLO_DIR}/command-api.lb.json"

IMAGE_REF="${1:-}"
[[ -n "$IMAGE_REF" ]] || die "usage: $0 <image-ref>  (e.g. the image 'task ledger:image TAG=...' built)"

for tool in duploctl duplo-jit jq python3; do
  command -v "$tool" >/dev/null || die "$tool is required and not on PATH"
done
[[ -f "$SERVICE_TEMPLATE" ]] || die "missing $SERVICE_TEMPLATE"
[[ -f "$LB_TEMPLATE" ]] || die "missing $LB_TEMPLATE"

# Mint the portal token ONCE. duplo-jit, not `duploctl --interactive`: the latter opens its own
# blocking OAuth flow that needs a TTY and hangs under any agent harness or unattended job, where
# duplo-jit completes silently against an already-authenticated portal session
# (scripts/orca-host/tunnel.sh established this exact pattern for the same tenant).
# Duplo portal tokens expire quickly, so this is the only mint in the whole run — every duploctl
# call below reuses it explicitly via --token rather than re-minting.
TOKEN="$(duplo-jit duplo --host "$DUPLO_HOST" --interactive 2>/dev/null \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["DuploToken"])' 2>/dev/null)" \
  || die "could not mint a Duplo portal token. Run once in a terminal:
       duplo-jit duplo --host ${DUPLO_HOST} --interactive"
[[ -n "$TOKEN" ]] || die "empty Duplo portal token"

duplo() { duploctl "$@" --host "$DUPLO_HOST" --tenant "$DUPLO_TENANT" --token "$TOKEN"; }

# Fetch state once and work from it, rather than re-querying per step against a token that may
# not outlive a long apply. Absence is expected on a first deploy, not a failure.
EXISTING="$(duplo service find "$SERVICE_NAME" -o json 2>/dev/null || true)"
if [[ -n "$EXISTING" ]]; then
  echo "found existing service '${SERVICE_NAME}'; applying as an update"
else
  echo "no existing service '${SERVICE_NAME}'; applying as a create"
fi

# --- Secret: ensure it exists, own it, never let it hold a value this script hardcodes ---
SECRET_ENV_FILE="${PULSE_LEDGER_SECRET_ENV_FILE:-}"
[[ -n "$SECRET_ENV_FILE" ]] || die "set PULSE_LEDGER_SECRET_ENV_FILE to a local KEY=VALUE file (never committed) — see docs/runbooks/pulse-command-api-deploy.md"
[[ -f "$SECRET_ENV_FILE" ]] || die "no such file: $SECRET_ENV_FILE"

secret_literals=()
while IFS='=' read -r key value; do
  [[ -z "$key" || "$key" == \#* ]] && continue
  secret_literals+=(--from-literal "${key}=${value}")
done <"$SECRET_ENV_FILE"
[[ "${#secret_literals[@]}" -gt 0 ]] || die "$SECRET_ENV_FILE has no KEY=VALUE lines"

if duplo secret find "$SECRET_NAME" >/dev/null 2>&1; then
  duplo secret update "$SECRET_NAME" "${secret_literals[@]}" >/dev/null
  echo "updated secret '${SECRET_NAME}'"
else
  duplo secret create "$SECRET_NAME" "${secret_literals[@]}" >/dev/null
  echo "created secret '${SECRET_NAME}'"
fi

# --- Service: substitute the image placeholder, then apply idempotently ---
RENDERED_SERVICE="$(mktemp)"
trap 'rm -f "$RENDERED_SERVICE"' EXIT
jq --arg image "$IMAGE_REF" '.DockerImage = $image' "$SERVICE_TEMPLATE" >"$RENDERED_SERVICE"

duplo service apply --file "$RENDERED_SERVICE"
echo "applied service '${SERVICE_NAME}' (image ${IMAGE_REF})"

# --- LB config: no file-driven duploctl command exists for this object, only the flag-based
# `service expose` — drive it from the committed file so the shape stays reviewable as a diff
# rather than living only in this script's flags (packages/pulse-ledger/infra/duplo/README.md).
lb_port="$(jq -r '.Port' "$LB_TEMPLATE")"
lb_protocol="$(jq -r '.Protocol' "$LB_TEMPLATE")"
lb_type_num="$(jq -r '.LbType' "$LB_TEMPLATE")"
lb_internal="$(jq -r '.IsInternal' "$LB_TEMPLATE")"

[[ "$lb_type_num" == "3" ]] || die "command-api.lb.json LbType changed to ${lb_type_num}; update the --lb-type mapping in this script before applying"
[[ "$lb_internal" == "true" ]] || die "command-api.lb.json IsInternal is not true — this service must never gain a public listener; refusing to apply"

duplo service expose "$SERVICE_NAME" \
  --lb-type k8clusterip \
  --container-port "$lb_port" \
  --protocol "$lb_protocol" \
  --visibility private
echo "applied lb config for '${SERVICE_NAME}' (internal ClusterIP, port ${lb_port})"

echo "done. Migrations are a separate operator action — see docs/runbooks/pulse-command-api-deploy.md."
