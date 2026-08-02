# -----------------------------------------------------------------------------
# Per-queue DLQs, redrive policies, and depth alarms (task 6.3, design D2)
# -----------------------------------------------------------------------------
# Every consumer queue from consumers.tf gets its own dead-letter queue: an
# event that fails `dlq_max_receive_count` receives moves here instead of being
# retried forever or discarded. One DLQ per consumer keeps failure attribution
# exact — the spec requires dead-letter volume observable *per consumer*.
#
# The redrive policy lives in the standalone `aws_sqs_queue_redrive_policy`
# resource rather than inline on the consumer queue: inlining it while the DLQ's
# allow-policy references the consumer queue would make the two queue resources
# reference each other, a cycle Terraform cannot order. The standalone resources
# break the cycle and leave consumers.tf owning nothing dead-letter-shaped.
#
# The alarm is the "with monitor" half of ADR §1.4's DLQ-with-monitor: depth >= 1
# fires, because a single dead-lettered event means a consumer is failing on a
# live message, not that traffic is noisy. Where the alarm notifies is the
# environment's decision (`dlq_alarm_actions`), not the module's.
# -----------------------------------------------------------------------------

resource "aws_sqs_queue" "dlq" {
  for_each = var.consumer_rule_patterns

  name                      = "${var.event_bus_name}-${each.key}-dlq"
  message_retention_seconds = var.dlq_message_retention_seconds

  tags = merge(var.tags, {
    Name     = "${var.event_bus_name}-${each.key}-dlq"
    Consumer = each.key
  })
}

resource "aws_sqs_queue_redrive_policy" "consumer" {
  for_each = var.consumer_rule_patterns

  queue_url = aws_sqs_queue.consumer[each.key].id

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq[each.key].arn
    maxReceiveCount     = var.dlq_max_receive_count
  })
}

# Only this consumer's own queue may name the DLQ as its dead-letter target;
# no other queue in the account can redrive into it.
resource "aws_sqs_queue_redrive_allow_policy" "dlq" {
  for_each = var.consumer_rule_patterns

  queue_url = aws_sqs_queue.dlq[each.key].id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.consumer[each.key].arn]
  })
}

resource "aws_cloudwatch_metric_alarm" "dlq" {
  for_each = var.consumer_rule_patterns

  alarm_name          = "${var.event_bus_name}-${each.key}-dlq-depth"
  alarm_description   = "Dead-letter volume for the ${each.key} consumer on the ${var.event_bus_name} bus. Any visible message means the consumer failed a live event ${var.dlq_max_receive_count} times."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.dlq[each.key].name
  }

  alarm_actions = var.dlq_alarm_actions
  ok_actions    = var.dlq_alarm_actions

  tags = merge(var.tags, {
    Name     = "${var.event_bus_name}-${each.key}-dlq-depth"
    Consumer = each.key
  })
}
