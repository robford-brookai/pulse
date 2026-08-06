variable "schedules" {
  description = "Schedule name -> cadence/target definition. Generated from schedule_catalog.auto.tfvars.json; never hand-written, deliberately without a fallback value."
  type = map(object({
    cron_expression              = string
    description                  = string
    target_subcommand            = string
    maximum_retry_attempts       = number
    maximum_event_age_in_seconds = number
  }))
}

variable "target_arn" {
  description = "ARN of the CLI runner (SPCS job or ECS task definition) every schedule invokes, differing only by the container override command. Decided at deploy time (design Open Questions); this module never creates it."
  type        = string
}

variable "role_arn" {
  description = "ARN of the IAM role EventBridge Scheduler assumes to invoke target_arn. Not created here — attachment happens once the runner's own role is known, the same deferral eventbridge-ocean's iam.tf documents for its publisher policy."
  type        = string
}

variable "schedule_group_name" {
  description = "EventBridge Scheduler group these schedules belong to."
  type        = string
  default     = "default"
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}
