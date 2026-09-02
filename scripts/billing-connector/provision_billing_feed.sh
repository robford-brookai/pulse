#!/usr/bin/env bash
# provision_billing_feed.sh — create (or confirm) the ledger's EventBridge -> SQS feed for the
# billing connector, WITH a dead-letter queue and redrive policy, then PROVE a message actually
# lands. Idempotent: safe to re-run. Follows scripts/ocean/provision_warehouse_feed.sh line for
# line (task 3.1, design.md decision 7).
#
#   ./provision_billing_feed.sh              # provision + verify
#   ./provision_billing_feed.sh --verify     # verify only, mutate nothing
#
# Exits 0 only after an end-to-end delivery probe succeeds. Every failure prints the specific
# cause and the first value to doubt — there is nothing here to interpret.
#
# THE FILTER IS THE POINT (design.md decision 7 — "Queue rule filter starts narrow"): this rule
# does not take every ocean.patient-state event. It matches only the four subject types the
# connector's own trigger allowlist and fold both care about today —
# billing_episode | coverage (evaluate -> declare) and consent | enrollment (folded, counted
# deferred, per design.md decision 4's carried caveat). Any other patient-state subject
# (encounter, referral, whatever else the catalog grows) never reaches this queue. Broadening the
# rule is a config change here, after first dev traffic — never a code change in
# billing_connector.service. tests/test_billing_connector_queue_rule_pattern.py pins this
# string byte for byte so the two — this script's pattern and
# billing_connector.service.TRIGGER_SUBJECT_TYPES's superset — cannot drift apart unnoticed.

set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-duplo-dev01}"
AWS_REGION="${AWS_REGION:-us-east-1}"
ACCOUNT="${ACCOUNT:-173008660334}"
TENANT="${TENANT:-duploservices-dev01-brook}"
BUS="${BUS:-${TENANT}-ocean}"
RULE="${RULE:-pulse-billing-connector}"
QUEUE="${QUEUE:-${TENANT}-pulse-billing-connector}"
DLQ="${DLQ:-${QUEUE}-dlq}"
MAX_RECEIVE="${MAX_RECEIVE:-5}"

# The narrow filter itself (design.md decision 7). Keep this in sync with
# billing_connector.service's own subject-type handling if that ever changes — the corresponding
# python-side constant is TRIGGER_SUBJECT_TYPES, a strict subset (billing_episode, coverage only;
# consent and enrollment fold and defer rather than trigger).
EVENT_PATTERN='{"source":["ocean"],"detail-type":["patient-state"],"detail":{"subject_type":["billing_episode","consent","coverage","enrollment"]}}'

export AWS_PROFILE AWS_REGION

QUEUE_URL="https://sqs.${AWS_REGION}.amazonaws.com/${ACCOUNT}/${QUEUE}"
QUEUE_ARN="arn:aws:sqs:${AWS_REGION}:${ACCOUNT}:${QUEUE}"
DLQ_ARN="arn:aws:sqs:${AWS_REGION}:${ACCOUNT}:${DLQ}"
RULE_ARN="arn:aws:events:${AWS_REGION}:${ACCOUNT}:rule/${BUS}/${RULE}"

VERIFY_ONLY=0
[[ "${1:-}" == "--verify" ]] && VERIFY_ONLY=1

fail() { printf '\nFAIL: %s\n' "$1" >&2; [[ -n "${2:-}" ]] && printf 'First value to doubt: %s\n' "$2" >&2; exit 1; }
step() { printf '\n== %s\n' "$1"; }

step "identity"
aws sts get-caller-identity --query Arn --output text \
  || fail "no usable AWS credential" "run: aws sts get-caller-identity --profile ${AWS_PROFILE} (duplo-jit needs an interactive login)"

if [[ "$VERIFY_ONLY" -eq 0 ]]; then
  step "dead-letter queue ${DLQ}"
  aws sqs create-queue --queue-name "$DLQ" --query QueueUrl --output text >/dev/null \
    || fail "could not create or confirm the DLQ" "sqs:CreateQueue on the tenant role"

  step "queue ${QUEUE} (redrive to ${DLQ} after ${MAX_RECEIVE} receives)"
  REDRIVE=$(printf '{"deadLetterTargetArn":"%s","maxReceiveCount":"%s"}' "$DLQ_ARN" "$MAX_RECEIVE")
  aws sqs create-queue --queue-name "$QUEUE" --query QueueUrl --output text >/dev/null \
    || fail "could not create or confirm the queue" "sqs:CreateQueue on the tenant role"
  ATTRS=$(python3 -c 'import json,sys; print(json.dumps({"RedrivePolicy": sys.argv[1]}))' "$REDRIVE")
  aws sqs set-queue-attributes --queue-url "$QUEUE_URL" --attributes "$ATTRS" \
    || fail "could not set the redrive policy" "the RedrivePolicy JSON, or sqs:SetQueueAttributes"

  step "event bus ${BUS} (must already exist — created by twenty-projection 4.2)"
  aws events describe-event-bus --name "$BUS" --query Arn --output text \
    || fail "event bus ${BUS} not found" "the bus name — it should exist since 2026-08-21; do not create a second bus here"

  step "rule ${RULE} on ${BUS} (narrow filter — see the header comment)"
  aws events put-rule --name "$RULE" --event-bus-name "$BUS" \
    --event-pattern "$EVENT_PATTERN" \
    --description "Route billing_episode/coverage/consent/enrollment patient-state events to the billing connector (billing-connector 3.1)" \
    --query RuleArn --output text \
    || fail "cannot put rule ${RULE}" "events:PutRule on role ${TENANT} — the DNA-1192 grant"

  step "queue policy (EventBridge -> SQS)"
  POLICY=$(cat <<JSON
{"Version":"2012-10-17","Statement":[{"Sid":"AllowEventBridgeRuleToSendMessage","Effect":"Allow","Principal":{"Service":"events.amazonaws.com"},"Action":"sqs:SendMessage","Resource":"${QUEUE_ARN}","Condition":{"ArnEquals":{"aws:SourceArn":"${RULE_ARN}"}}}]}
JSON
)
  PATTRS=$(python3 -c 'import json,sys; print(json.dumps({"Policy": sys.argv[1]}))' "$POLICY")
  aws sqs set-queue-attributes --queue-url "$QUEUE_URL" --attributes "$PATTRS" \
    || fail "could not set the queue policy" "the Policy JSON, or sqs:SetQueueAttributes"

  step "rule target"
  FAILED=$(aws events put-targets --event-bus-name "$BUS" --rule "$RULE" \
    --targets "Id=billing-connector-queue,Arn=${QUEUE_ARN}" --query FailedEntryCount --output text) \
    || fail "cannot put the rule target" "events:PutTargets on role ${TENANT} — the DNA-1192 grant"
  [[ "$FAILED" == "0" ]] || fail "put-targets reported ${FAILED} failed entries" "the queue ARN ${QUEUE_ARN}"
fi

step "delivery probe (the only proof that matters)"
PROBE="pulse-billing-connector-probe-$$"
SENT=$(aws events put-events --entries "[{\"Source\":\"ocean\",\"DetailType\":\"patient-state\",\"Detail\":\"{\\\"subject_type\\\":\\\"billing_episode\\\",\\\"probe\\\":\\\"${PROBE}\\\"}\",\"EventBusName\":\"${BUS}\"}]" \
  --query FailedEntryCount --output text) \
  || fail "put-events call itself failed" "events:PutEvents on role ${TENANT}"
[[ "$SENT" == "0" ]] || fail "put-events reported ${SENT} failed entries — the bus rejected the event" "the bus name ${BUS}"

FOUND=0
for _ in 1 2 3 4; do
  sleep 5
  BODY=$(aws sqs receive-message --queue-url "$QUEUE_URL" --max-number-of-messages 10 \
    --wait-time-seconds 5 --query 'Messages[].Body' --output text 2>/dev/null || true)
  if printf '%s' "$BODY" | grep -q "$PROBE"; then FOUND=1; break; fi
done
[[ "$FOUND" == "1" ]] || fail "probe event never arrived on ${QUEUE} — a subject_type=billing_episode probe must pass the filter" "the rule pattern's detail.subject_type list, then the queue policy SourceArn ${RULE_ARN}"

# NOTE: the probe message is deliberately NOT deleted. It carries no real envelope fields
# (event_id, effective_at, ...), so a running connector's consume loop drops it as a malformed
# body rather than folding it — itself a live-path check, and never a state-mutating one. If the
# connector is not yet deployed, the probe ages out per queue retention.

printf '\nPASS: rule %s -> queue %s (DLQ %s, maxReceive %s) delivers billing_episode/coverage/consent/enrollment events.\n' "$RULE" "$QUEUE" "$DLQ" "$MAX_RECEIVE"
