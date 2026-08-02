variable "cluster_name" {
  description = "Name of the MSK Serverless cluster"
  type        = string
  default     = "ocean-streaming"
}

variable "vpc_id" {
  description = "VPC ID where the MSK cluster will be deployed"
  type        = string
}

variable "subnet_ids" {
  description = "List of subnet IDs for the MSK cluster (at least 2 AZs)"
  type        = list(string)
}

variable "allowed_security_group_ids" {
  description = "Security group IDs allowed to connect to MSK on port 9098 (IAM auth)"
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}
