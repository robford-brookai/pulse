variable "event_bus_name" {
  description = "Name of the OCEAN EventBridge bus. Must match OCEAN_EVENT_BUS_NAME in every publishing service."
  type        = string
  default     = "ocean"
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}
