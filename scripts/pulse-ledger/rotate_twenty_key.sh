#!/usr/bin/env bash
# rotate_twenty_key.sh — rotate the Twenty API key everywhere a target's pulse-ledger stack
# holds it, after the old one was revoked or expired. Run as `task twenty:key:rotate TARGET=dev`.
#
# One key, three homes, all rewritten in one pass so they never drift apart:
#   1. the operator's gitignored env file        — PULSE_TWENTY_DEV_TOKEN  (laptop tooling)
#   2. the Duplo secret pulse-ledger-api-secret  — PULSE_LEDGER_TWENTY_API_TOKEN
#                                                  PULSE_LEDGER_TWENTY_PROJECTION_TOKEN
#   3. the pulse-ledger-api deployment           — restarted; envFrom is read at pod start only
#
# The key is prompted for without echo and validated against the target's Twenty before anything
# is written. Prints key names and status codes only — never a value. The Duplo secret is
# rewritten with every existing key (duploctl secret update replaces the whole set; a partial
# update erases DATABASE_URL and crashloops the API — env-vars process doc §3).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

TARGET="${1:-}"
case "$TARGET" in
  dev)
    DUPLO_TENANT=dev01-brook
    K8S_NAMESPACE=duploservices-dev01-brook
    ENV_FILE=scripts/verdict-env-vars.sh
    ENV_URL_VAR=PULSE_TWENTY_DEV_URL
    ENV_TOKEN_VAR=PULSE_TWENTY_DEV_TOKEN
    ;;
  *)
    echo "rotate_twenty_key: TARGET must be dev (staging/prod have no recorded env file or tenant yet)" >&2
    exit 2
    ;;
esac
DUPLO_HOST="${DUPLO_HOST:-https://duplo.cloud.brook.ai}"
KUBE_CONTEXT="${KUBE_CONTEXT:-duplo-dev01}"
SECRET_NAME=pulse-ledger-api-secret
SECRET_KEYS=(PULSE_LEDGER_TWENTY_API_TOKEN PULSE_LEDGER_TWENTY_PROJECTION_TOKEN)

die() { echo "rotate_twenty_key: $*" >&2; exit 1; }
for tool in duploctl duplo-jit jq kubectl curl python3; do
  command -v "$tool" >/dev/null || die "missing tool: $tool"
done
[[ -f "$ENV_FILE" ]] || die "no env file at $ENV_FILE"

read -rs -p "Paste the new $TARGET Twenty API key, then Enter: " NEW_KEY; echo
[[ ${#NEW_KEY} -gt 40 ]] || die "that does not look like a Twenty API key"

set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a
BASE="${!ENV_URL_VAR%/}"
[[ -n "$BASE" ]] || die "$ENV_URL_VAR is not set in $ENV_FILE"
code=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $NEW_KEY" "$BASE/rest/patientPrograms?limit=1")
[[ "$code" == "200" ]] || die "new key rejected by $BASE: HTTP $code"
echo "new key accepted by $BASE (200)"

TOKEN="$(duplo-jit duplo --host "$DUPLO_HOST" --interactive | python3 -c 'import json,sys; print(json.load(sys.stdin)["DuploToken"])')"
KTOKEN="$(duplo-jit k8s --host "$DUPLO_HOST" --plan nonprod --interactive | jq -r .status.token)"
[[ ${#TOKEN} -gt 100 && ${#KTOKEN} -gt 100 ]] || die "duplo-jit token mint failed"
duplo() { duploctl "$@" --host "$DUPLO_HOST" --tenant "$DUPLO_TENANT" --token "$TOKEN"; }
kube() { kubectl --context "$KUBE_CONTEXT" --token="$KTOKEN" -n "$K8S_NAMESPACE" "$@"; }

# 1. env file — replace the value on the one existing export line, backup kept beside it
cp "$ENV_FILE" "$ENV_FILE.bak.$(date +%Y%m%d%H%M%S)"
NEW_KEY="$NEW_KEY" ENV_TOKEN_VAR="$ENV_TOKEN_VAR" python3 - "$ENV_FILE" <<'PY'
import os, re, sys
path = sys.argv[1]; var = os.environ["ENV_TOKEN_VAR"]; key = os.environ["NEW_KEY"]
text = open(path).read()
new_text, n = re.subn(rf"^(export {var}=).*$", lambda m: m.group(1) + key, text, flags=re.M)
if n != 1:
    sys.exit(f"expected exactly one `export {var}=` line in {path}, found {n}")
open(path, "w").write(new_text)
PY
echo "env file: $ENV_TOKEN_VAR replaced"

# 2. Duplo secret — every existing key, the Twenty keys swapped
SECRET_JSON="$(duplo secret find "$SECRET_NAME" --output json)"
literals=()
while IFS= read -r line; do literals+=(--from-literal "$line"); done < <(
  SECRET_JSON="$SECRET_JSON" NEW_KEY="$NEW_KEY" SECRET_KEYS="${SECRET_KEYS[*]}" python3 -c '
import json, os, sys
doc = json.loads(os.environ["SECRET_JSON"]); doc = doc[0] if isinstance(doc, list) else doc
data = doc["SecretData"]
for key in os.environ["SECRET_KEYS"].split():
    if key not in data:
        sys.exit(f"secret has no key {key}; refusing to add one this script did not expect")
    data[key] = os.environ["NEW_KEY"]
for key, value in sorted(data.items()):
    print(f"{key}={value}")')
echo "secret: rewriting $SECRET_NAME with $(( ${#literals[@]} / 2 )) keys"
duplo secret update "$SECRET_NAME" "${literals[@]}" >/dev/null
duplo secret find "$SECRET_NAME" --output json \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); d=d[0] if isinstance(d,list) else d; print("secret keys after:", sorted(d["SecretData"]))'
unset SECRET_JSON NEW_KEY

# 3. restart the API so the pod reads the new value
kube rollout restart deployment/pulse-ledger-api
kube rollout status deployment/pulse-ledger-api --timeout=180s
echo "done. Any kubectl port-forward to pulse-ledger-api died with the old pod; restart it."
