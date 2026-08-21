#!/usr/bin/env bash
# provision_projection_feed.sh — create (or confirm) the ledger's EventBridge → SQS feed for the
# Twenty projection, then PROVE a message actually lands. Idempotent: safe to re-run.
#
#   ./provision_projection_feed.sh              # provision + verify
#   ./provision_projection_feed.sh --verify     # verify only, mutate nothing
#
# Exits 0 only after an end-to-end delivery probe succeeds. Every failure prints the specific
# cause and the first value to doubt — there is nothing here to interpret.
#
# Why a script and not a runbook: every value below (rule ARN shape, queue policy SourceArn,
# event pattern) is a config surface that accepts a wrong value silently and then fails with the
# same symptom as no config at all. Those must be verified by probe, never by clean-apply.

set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-duplo-dev01}"
AWS_REGION="${AWS_REGION:-us-east-1}"
ACCOUNT="${ACCOUNT:-173008660334}"
TENANT="${TENANT:-duploservices-dev01-brook}"
BUS="${BUS:-${TENANT}-ocean}"
RULE="${RULE:-pulse-twenty-projection}"
QUEUE="${QUEUE:-${TENANT}-pulse-twenty-projection}"

export AWS_PROFILE AWS_REGION

QUEUE_URL="https://sqs.${AWS_REGION}.amazonaws.com/${ACCOUNT}/${QUEUE}"
QUEUE_ARN="arn:aws:sqs:${AWS_REGION}:${ACCOUNT}:${QUEUE}"
RULE_ARN="arn:aws:events:${AWS_REGION}:${ACCOUNT}:rule/${BUS}/${RULE}"

VERIFY_ONLY=0
[[ "${1:-}" == "--verify" ]] && VERIFY_ONLY=1

fail() { printf '\nFAIL: %s\n' "$1" >&2; [[ -n "${2:-}" ]] && printf 'First value to doubt: %s\n' "$2" >&2; exit 1; }
step() { printf '\n== %s\n' "$1"; }

step "identity"
aws sts get-caller-identity --query Arn --output text \
  || fail "no usable AWS credential" "run: aws sts get-caller-identity --profile ${AWS_PROFILE} (duplo-jit needs an interactive login)"

if [[ "$VERIFY_ONLY" -eq 0 ]]; then
  step "queue ${QUEUE}"
  aws sqs create-queue --queue-name "$QUEUE" --query QueueUrl --output text >/dev/null \
    || fail "could not create or confirm the queue" "sqs:CreateQueue on the tenant role"

  step "event bus ${BUS}"
  aws events create-event-bus --name "$BUS" --query EventBusArn --output text 2>/dev/null \
    || aws events describe-event-bus --name "$BUS" --query Arn --output text \
    || fail "cannot create or read event bus ${BUS}" "events:CreateEventBus / events:DescribeEventBus on role ${TENANT} — this is DNA-1192"

  step "rule ${RULE} on ${BUS}"
  aws events put-rule --name "$RULE" --event-bus-name "$BUS" \
    --event-pattern '{"source":["ocean"]}' \
    --description "Route ocean ledger events to the Twenty projection queue (twenty-projection 4.2)" \
    --query RuleArn --output text \
    || fail "cannot put rule ${RULE}" "events:PutRule on role ${TENANT} — this is DNA-1192"

  step "queue policy (EventBridge -> SQS)"
  POLICY=$(cat <<JSON
{"Version":"2012-10-17","Statement":[{"Sid":"AllowEventBridgeRuleToSendMessage","Effect":"Allow","Principal":{"Service":"events.amazonaws.com"},"Action":"sqs:SendMessage","Resource":"${QUEUE_ARN}","Condition":{"ArnEquals":{"aws:SourceArn":"${RULE_ARN}"}}}]}
JSON
)
  aws sqs set-queue-attributes --queue-url "$QUEUE_URL" --attributes "Policy=${POLICY}" \
    || fail "could not set the queue policy" "the Policy JSON, or sqs:SetQueueAttributes"

  step "rule target"
  FAILED=$(aws events put-targets --event-bus-name "$BUS" --rule "$RULE" \
    --targets "Id=projection-queue,Arn=${QUEUE_ARN}" --query FailedEntryCount --output text) \
    || fail "cannot put the rule target" "events:PutTargets on role ${TENANT} — this is DNA-1192"
  [[ "$FAILED" == "0" ]] || fail "put-targets reported ${FAILED} failed entries" "the queue ARN ${QUEUE_ARN}"
fi

step "delivery probe (the only proof that matters)"
PROBE="pulse-probe-$(aws sts get-caller-identity --query Account --output text)-$$"
SENT=$(aws events put-events --entries "[{\"Source\":\"ocean\",\"DetailType\":\"patient-state\",\"Detail\":\"{\\\"probe\\\":\\\"${PROBE}\\\"}\",\"EventBusName\":\"${BUS}\"}]" \
  --query FailedEntryCount --output text) \
  || fail "put-events call itself failed" "events:PutEvents on role ${TENANT}"
[[ "$SENT" == "0" ]] || fail "put-events reported ${SENT} failed entries — the bus rejected the event" "the bus name ${BUS}"

for attempt in 1 2 3; do
  BODY=$(aws sqs receive-message --queue-url "$QUEUE_URL" --wait-time-seconds 10 \
    --max-number-of-messages 10 --query 'Messages[].Body' --output text 2>/dev/null || true)
  if [[ "$BODY" == *"$PROBE"* ]]; then
    printf '\nPASS: probe %s published to bus %s and received on queue %s\n' "$PROBE" "$BUS" "$QUEUE"
    printf 'The feed is live. Next: deploy the relay (python -m pulse_ledger.relay_worker) with OCEAN_EVENT_BUS_NAME=%s\n' "$BUS"
    exit 0
  fi
  printf 'attempt %s: probe not yet received, retrying\n' "$attempt"
done

fail "the bus accepted the event but it never reached the queue — a silent routing or authorization drop" \
     "the queue policy's aws:SourceArn (must be exactly ${RULE_ARN}), then the rule's event pattern {\"source\":[\"ocean\"]}"
