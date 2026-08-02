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

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}
