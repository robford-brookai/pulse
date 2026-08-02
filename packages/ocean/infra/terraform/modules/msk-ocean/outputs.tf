output "cluster_arn" {
  description = "ARN of the MSK Serverless cluster"
  value       = aws_msk_serverless_cluster.main.arn
}

output "bootstrap_brokers_sasl_iam" {
  description = "Bootstrap brokers connection string for IAM authentication"
  value       = aws_msk_serverless_cluster.main.bootstrap_brokers_sasl_iam
}

output "security_group_id" {
  description = "Security group ID attached to the MSK cluster"
  value       = aws_security_group.msk.id
}

output "cluster_name" {
  description = "Name of the MSK Serverless cluster (used in IAM policy ARN construction)"
  value       = aws_msk_serverless_cluster.main.cluster_name
}

output "connector_policy_arn" {
  description = "ARN of the IAM policy granting mongodb-connector Kafka permissions"
  value       = aws_iam_policy.connector.arn
}
