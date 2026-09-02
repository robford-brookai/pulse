#!/usr/bin/env bash
# Stage `task demo:e2e:live`: put every credential the live walk needs into this shell, by name,
# then run the preflight and the demo in the same shell (go-task cannot carry exports between
# `cmds`, so the demo runs from here). docs/runbooks/demo5-end-to-end.md §"Staging the live run".
#
#   1. source scripts/verdict-env-vars.sh (gitignored scratch from the billing-state 4.1 run)
#   2. derive DEMO5_SNOWFLAKE_* from VERDICT_RELAY_SNOWFLAKE_* unless already set
#   3. fetch the two names the scratch file lacks from the Duplo secret `pulse-ledger-api-secret`
#      (tenant dev01-brook): CONSENT_INGRESS_CUSTOMERIO_TOKEN and PULSE_CORE_REPLAY_TOKEN
#   4. run scripts/demo/demo5_preflight.py (image current, schema head, seeded card)
#   5. exec `task demo:e2e:live`
#
# Never prints a secret value: only variable names, key names, and set/MISSING.
# Flags: --no-preflight skips step 4. Env overrides: STAGE_E2E_CONSENT_KEY / STAGE_E2E_REPLAY_KEY
# name the Duplo secret keys to read when the prefix match is wrong or ambiguous.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

DUPLO_HOST="${DUPLO_HOST:-https://duplo.cloud.brook.ai}"
DUPLO_TENANT="${DUPLO_TENANT:-dev01-brook}"
DUPLO_SECRET="${DUPLO_SECRET:-pulse-ledger-api-secret}"
SCRATCH="scripts/verdict-env-vars.sh"
PREFLIGHT=1
for arg in "$@"; do
  case "$arg" in
    --no-preflight) PREFLIGHT=0 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "stage: unknown flag $arg" >&2; exit 2 ;;
  esac
done

# 1. scratch exports
if [[ -f "$SCRATCH" ]]; then
  set +u; # the scratch file may reference unset names
  # shellcheck disable=SC1090
  source "$SCRATCH"
  set -u
  echo "stage: sourced $SCRATCH"
else
  echo "stage: $SCRATCH not found — see docs/process/env-vars-retreival.md; continuing with the current environment" >&2
fi

# 2. derive the demo's own Snowflake reader from the relay's (same account, user, warehouse, key)
export DEMO5_SNOWFLAKE_ACCOUNT="${DEMO5_SNOWFLAKE_ACCOUNT:-${VERDICT_RELAY_SNOWFLAKE_ACCOUNT:-}}"
export DEMO5_SNOWFLAKE_USER="${DEMO5_SNOWFLAKE_USER:-${VERDICT_RELAY_SNOWFLAKE_USER:-}}"
export DEMO5_SNOWFLAKE_WAREHOUSE="${DEMO5_SNOWFLAKE_WAREHOUSE:-${VERDICT_RELAY_SNOWFLAKE_WAREHOUSE:-}}"
if [[ -z "${DEMO5_SNOWFLAKE_PASSWORD:-}" && -z "${DEMO5_SNOWFLAKE_PRIVATE_KEY_PATH:-}" ]]; then
  export DEMO5_SNOWFLAKE_PRIVATE_KEY_PATH="${VERDICT_RELAY_SNOWFLAKE_PRIVATE_KEY_PATH:-}"
fi

# 3. the two names the scratch file lacks, from the Duplo secret (values never echoed)
pick_secret_key() {
  # $1 = secret JSON on stdin, $2 = explicit key or empty, $3 = key prefix to match
  python3 - "$2" "$3" <<'PY'
import json, sys
explicit, prefix = sys.argv[1], sys.argv[2]
doc = json.load(sys.stdin)
data = doc.get("SecretData") if isinstance(doc, dict) else None
if data is None and isinstance(doc, list) and doc:
    data = doc[0].get("SecretData")
data = data or {}
keys = sorted(data)
if explicit:
    chosen = [explicit] if explicit in data else []
else:
    chosen = [k for k in keys if k.startswith(prefix)]
if len(chosen) != 1:
    sys.stderr.write(f"stage: need exactly one key for prefix {prefix!r}, found {chosen or 'none'}; available key names: {keys}\n")
    sys.exit(3)
sys.stdout.write(data[chosen[0]])
PY
}

if [[ -z "${CONSENT_INGRESS_CUSTOMERIO_TOKEN:-}" || -z "${PULSE_CORE_REPLAY_TOKEN:-}" ]]; then
  echo "stage: fetching Duplo secret $DUPLO_SECRET (tenant $DUPLO_TENANT) for the missing writer tokens"
  DUPLO_TOKEN="$(duplo-jit duplo --host "$DUPLO_HOST" --interactive | python3 -c 'import json,sys; print(json.load(sys.stdin)["DuploToken"])')"
  SECRET_JSON="$(duploctl secret find "$DUPLO_SECRET" --host "$DUPLO_HOST" --tenant "$DUPLO_TENANT" --token "$DUPLO_TOKEN" --output json)"
  unset DUPLO_TOKEN
  if [[ -z "${CONSENT_INGRESS_CUSTOMERIO_TOKEN:-}" ]]; then
    CONSENT_INGRESS_CUSTOMERIO_TOKEN="$(printf '%s' "$SECRET_JSON" | pick_secret_key "" "${STAGE_E2E_CONSENT_KEY:-}" "PULSE_LEDGER_WRITER_TOKEN_CUSTOMER")"
    export CONSENT_INGRESS_CUSTOMERIO_TOKEN
    echo "stage: CONSENT_INGRESS_CUSTOMERIO_TOKEN set from the secret"
  fi
  if [[ -z "${PULSE_CORE_REPLAY_TOKEN:-}" ]]; then
    # The history route accepts any writer credential (pulse_ledger.api SUBJECT_HISTORY_PATH);
    # the projection replays under the credential it already writes with.
    PULSE_CORE_REPLAY_TOKEN="$(printf '%s' "$SECRET_JSON" | pick_secret_key "" "${STAGE_E2E_REPLAY_KEY:-}" "PULSE_LEDGER_WRITER_TOKEN_TWENTY")"
    export PULSE_CORE_REPLAY_TOKEN
    echo "stage: PULSE_CORE_REPLAY_TOKEN set from the secret"
  fi
  unset SECRET_JSON
fi
export PULSE_CORE_REPLAY_BASE_URL="${PULSE_CORE_REPLAY_BASE_URL:-${PULSE_LEDGER_API_URL:-}}"

# Report names only.
echo "stage: environment for --live"
for name in DATABASE_URL PULSE_LEDGER_API_URL PULSE_LEDGER_TWENTY_WEBHOOK_SECRET PULSE_TWENTY_DEV_URL PULSE_TWENTY_DEV_TOKEN \
            CONSENT_INGRESS_CUSTOMERIO_TOKEN VERDICT_RELAY_TOKEN PULSE_CORE_REPLAY_TOKEN PULSE_CORE_REPLAY_BASE_URL \
            DEMO5_SNOWFLAKE_ACCOUNT DEMO5_SNOWFLAKE_USER DEMO5_SNOWFLAKE_WAREHOUSE; do
  if [[ -n "${!name:-}" ]]; then echo "  set      $name"; else echo "  MISSING  $name"; fi
done
if [[ -n "${DEMO5_SNOWFLAKE_PASSWORD:-}" || -n "${DEMO5_SNOWFLAKE_PRIVATE_KEY_PATH:-}" ]]; then
  echo "  set      DEMO5_SNOWFLAKE_PASSWORD or DEMO5_SNOWFLAKE_PRIVATE_KEY_PATH"
else
  echo "  MISSING  DEMO5_SNOWFLAKE_PASSWORD or DEMO5_SNOWFLAKE_PRIVATE_KEY_PATH"
fi

# 4. preflight
if [[ "$PREFLIGHT" -eq 1 ]]; then
  uv run python scripts/demo/demo5_preflight.py
fi

# 5. the walk, in this shell
exec task demo:e2e:live
