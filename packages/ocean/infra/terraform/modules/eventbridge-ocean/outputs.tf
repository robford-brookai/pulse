output "event_bus_name" {
  description = "Name of the OCEAN event bus (the value services set as OCEAN_EVENT_BUS_NAME)"
  value       = aws_cloudwatch_event_bus.ocean.name
}

output "event_bus_arn" {
  description = "ARN of the OCEAN event bus (rules and the archive in tasks 6.2-6.4 attach to it)"
  value       = aws_cloudwatch_event_bus.ocean.arn
}

output "publisher_policy_arn" {
  description = "ARN of the IAM policy granting events:PutEvents on this bus"
  value       = aws_iam_policy.publisher.arn
}
