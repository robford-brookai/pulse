output "schedule_arns" {
  description = "Schedule name -> EventBridge Scheduler ARN"
  value       = { for name, schedule in aws_scheduler_schedule.job : name => schedule.arn }
}

output "schedule_names" {
  description = "The full set of schedule names this module declared (task 5.1's cadence set)"
  value       = keys(aws_scheduler_schedule.job)
}
