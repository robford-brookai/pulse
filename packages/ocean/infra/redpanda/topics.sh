#!/usr/bin/env bash
# infra/redpanda/topics.sh — idempotent topic creation for all Ocean topics
# Run after Redpanda is healthy.
set -euo pipefail

REDPANDA_BROKERS="${REDPANDA_BROKERS:-localhost:9092}"

topics=(
  "ocean.signals"
  "ocean.alerts"
  "ocean.tasks"
  "ocean.interactions"
  "ocean.outcomes"
  "ocean.tickets"
  "ocean.ai-ops"
  "ocean.audit"
  "ocean.ops"
  "ocean.logistics"
)

echo "Creating Ocean topics on broker: $REDPANDA_BROKERS"

for topic in "${topics[@]}"; do
  rpk topic create "$topic" \
    --brokers "$REDPANDA_BROKERS" \
    --partitions 3 \
    --replicas 1 \
    --topic-config retention.ms=604800000 \
    --topic-config cleanup.policy=delete \
    2>/dev/null && echo "Created: $topic" || echo "Already exists: $topic"
done

echo "Topic configuration complete."
