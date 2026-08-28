#!/usr/bin/env bash
# provision_warehouse_feed.sh — create (or confirm) the ledger's EventBridge → SQS feed for the
# warehouse-sync consumer, WITH a dead-letter queue and redrive policy, then PROVE a message
# actually lands. Idempotent: safe to re-run. (snowflake-projection task 2.1; the sibling of
# scripts/pulse-ledger/provision_projection_feed.sh, which this follows line for line, plus DLQ.)
#
#   ./provision_warehouse_feed.sh              # provision + verify
#   ./provision_warehouse_feed.sh --verify     # verify only, mutate nothing
#
# Exits 0 only after an end-to-end delivery probe succeeds. Every failure prints the specific
# cause and the first value to doubt — there is nothing here to interpret.

set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-duplo-dev01}"
AWS_REGION="${AWS_REGION:-us-east-1}"
ACCOUNT="${ACCOUNT:-173008660334}"
TENANT="${TENANT:-duploservices-dev01-brook}"
BUS="${BUS:-${TENANT}-ocean}"
RULE="${RULE:-pulse-warehouse-sync}"
QUEUE="${QUEUE:-${TENANT}-pulse-warehouse-sync}"
DLQ="${DLQ:-${QUEUE}-dlq}"
MAX_RECEIVE="${MAX_RECEIVE:-5}"

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

  step "rule ${RULE} on ${BUS}"
  aws events put-rule --name "$RULE" --event-bus-name "$BUS" \
    --event-pattern '{"source":["ocean"]}' \
    --description "Route ocean ledger events to the warehouse-sync queue (snowflake-projection 2.1)" \
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
    --targets "Id=warehouse-queue,Arn=${QUEUE_ARN}" --query FailedEntryCount --output text) \
    || fail "cannot put the rule target" "events:PutTargets on role ${TENANT} — the DNA-1192 grant"
  [[ "$FAILED" == "0" ]] || fail "put-targets reported ${FAILED} failed entries" "the queue ARN ${QUEUE_ARN}"
fi

step "delivery probe (the only proof that matters)"
PROBE="pulse-warehouse-probe-$$"
SENT=$(aws events put-events --entries "[{\"Source\":\"ocean\",\"DetailType\":\"patient-state\",\"Detail\":\"{\\\"probe\\\":\\\"${PROBE}\\\"}\",\"EventBusName\":\"${BUS}\"}]" \
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
[[ "$FOUND" == "1" ]] || fail "probe event never arrived on ${QUEUE}" "the rule pattern, then the queue policy SourceArn ${RULE_ARN}"

# NOTE: the probe message is deliberately NOT deleted — the running consumer will read it,
# find no subject_type, and skip it, which is itself a live-path check. If the consumer is not
# yet deployed, the probe ages out per queue retention.

printf '\nPASS: rule %s -> queue %s (DLQ %s, maxReceive %s) delivers.\n' "$RULE" "$QUEUE" "$DLQ" "$MAX_RECEIVE"
