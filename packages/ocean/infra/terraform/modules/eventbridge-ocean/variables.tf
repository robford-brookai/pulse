variable "event_bus_name" {
  description = "Name of the OCEAN EventBridge bus. Must match OCEAN_EVENT_BUS_NAME in every publishing service."
  type        = string
  default     = "ocean"
}

variable "archive_retention_days" {
  description = "Days the bus archive retains events for convenience replay. Bounded by design: 30-90 days (design Open Questions); the durable record is audit_log, not this archive."
  type        = number
  default     = 90

  validation {
    condition     = var.archive_retention_days >= 30 && var.archive_retention_days <= 90
    error_message = "archive_retention_days must be between 30 and 90; the archive is a replay window, not the durable record."
  }
}

variable "consumer_rule_patterns" {
  description = "Consumer name -> serialised EventBridge event pattern. Generated from ocean_broker.catalog into generated/event_catalog.auto.tfvars.json; never hand-written, deliberately without a fallback value."
  type        = map(string)
}

variable "dlq_max_receive_count" {
  description = "Receives a message survives before the redrive policy moves it to the consumer's DLQ. Keeps redelivery-on-failure semantics with a bound: not discarded, not retried forever."
  type        = number
  default     = 5

  validation {
    condition     = var.dlq_max_receive_count >= 1 && var.dlq_max_receive_count <= 1000
    error_message = "dlq_max_receive_count must be between 1 and 1000, per SQS redrive policy limits."
  }
}

variable "dlq_message_retention_seconds" {
  description = "Seconds a dead-lettered message is retained for inspection and redrive. Defaults to the SQS maximum of 14 days — a DLQ message is evidence of a failing consumer, kept as long as SQS allows."
  type        = number
  default     = 1209600

  validation {
    condition     = var.dlq_message_retention_seconds >= 60 && var.dlq_message_retention_seconds <= 1209600
    error_message = "dlq_message_retention_seconds must be between 60 and 1209600 (14 days), per SQS limits."
  }
}

variable "dlq_alarm_actions" {
  description = "ARNs (SNS topics) the per-consumer DLQ depth alarms notify. Empty by default: the alarm and its state exist regardless; where it routes is the environment's decision, not the module's."
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}
