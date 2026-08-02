output "event_bus_name" {
  description = "Name of the OCEAN event bus (the value services set as OCEAN_EVENT_BUS_NAME)"
  value       = aws_cloudwatch_event_bus.ocean.name
}

output "event_bus_arn" {
  description = "ARN of the OCEAN event bus (rules and the archive in tasks 6.2-6.4 attach to it)"
  value       = aws_cloudwatch_event_bus.ocean.arn
}

output "archive_name" {
  description = "Name of the bus archive (the value passed to start-replay when re-driving a consumer)"
  value       = aws_cloudwatch_event_archive.ocean.name
}

output "publisher_policy_arn" {
  description = "ARN of the IAM policy granting events:PutEvents on this bus"
  value       = aws_iam_policy.publisher.arn
}

output "consumer_queue_urls" {
  description = "Consumer name -> SQS queue URL (the value each service sets as SQS_QUEUE_URL)"
  value       = { for consumer, queue in aws_sqs_queue.consumer : consumer => queue.url }
}

output "consumer_queue_arns" {
  description = "Consumer name -> SQS queue ARN (task 6.3 attaches each queue's DLQ and redrive policy)"
  value       = { for consumer, queue in aws_sqs_queue.consumer : consumer => queue.arn }
}

output "consumer_rule_arns" {
  description = "Consumer name -> EventBridge rule ARN"
  value       = { for consumer, rule in aws_cloudwatch_event_rule.consumer : consumer => rule.arn }
}

output "consumer_dlq_urls" {
  description = "Consumer name -> dead-letter queue URL (where an operator inspects and redrives failed events)"
  value       = { for consumer, queue in aws_sqs_queue.dlq : consumer => queue.url }
}

output "consumer_dlq_arns" {
  description = "Consumer name -> dead-letter queue ARN"
  value       = { for consumer, queue in aws_sqs_queue.dlq : consumer => queue.arn }
}

output "consumer_dlq_alarm_arns" {
  description = "Consumer name -> CloudWatch alarm ARN watching that consumer's DLQ depth"
  value       = { for consumer, alarm in aws_cloudwatch_metric_alarm.dlq : consumer => alarm.arn }
}
