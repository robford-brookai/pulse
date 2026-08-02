# -----------------------------------------------------------------------------
# Per-consumer rules and queues (task 6.2, design D2)
# -----------------------------------------------------------------------------
# One rule, one queue, one consumer. Every resource fans out over
# `var.consumer_rule_patterns`, whose keys are the seven consumers and whose
# values are pre-serialised EventBridge patterns generated from
# `ocean_broker.catalog` (task 2.1) into
# `generated/event_catalog.auto.tfvars.json`. Nothing here writes a pattern by
# hand — `event_pattern` passes the generated string straight through, so the
# rule cannot drift from what the publisher emits.
#
# Standard queues, not FIFO: design D3 rejected FIFO on a platform constraint
# and puts ordering in consumer-side sequence guards instead. Competing
# consumers within a service are multiple pollers on the same queue.
#
# DLQs and redrive policies attach to these queues in task 6.3. Consumers need
# no IAM policy here for the same reason the publisher policy is not attached
# to a role (see iam.tf): queue-read permissions land with the environment
# config, once the EKS service account role ARNs are known.
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "consumer" {
  for_each = var.consumer_rule_patterns

  name           = "${var.event_bus_name}-${each.key}"
  event_bus_name = aws_cloudwatch_event_bus.ocean.name
  event_pattern  = each.value

  tags = merge(var.tags, {
    Name     = "${var.event_bus_name}-${each.key}"
    Consumer = each.key
  })
}

resource "aws_sqs_queue" "consumer" {
  for_each = var.consumer_rule_patterns

  name = "${var.event_bus_name}-${each.key}"

  tags = merge(var.tags, {
    Name     = "${var.event_bus_name}-${each.key}"
    Consumer = each.key
  })
}

resource "aws_cloudwatch_event_target" "consumer" {
  for_each = var.consumer_rule_patterns

  rule           = aws_cloudwatch_event_rule.consumer[each.key].name
  event_bus_name = aws_cloudwatch_event_bus.ocean.name
  target_id      = "${var.event_bus_name}-${each.key}-queue"
  arn            = aws_sqs_queue.consumer[each.key].arn
}

# EventBridge delivers to SQS via the queue's resource policy, not an IAM role.
# Scoped to this consumer's own rule so no other rule — and nothing else in the
# account — can write into its queue.
resource "aws_sqs_queue_policy" "consumer" {
  for_each = var.consumer_rule_patterns

  queue_url = aws_sqs_queue.consumer[each.key].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowEventBridgeSendMessage"
        Effect = "Allow"
        Principal = {
          Service = "events.amazonaws.com"
        }
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.consumer[each.key].arn
        Condition = {
          ArnEquals = {
            "aws:SourceArn" = aws_cloudwatch_event_rule.consumer[each.key].arn
          }
        }
      },
    ]
  })
}
