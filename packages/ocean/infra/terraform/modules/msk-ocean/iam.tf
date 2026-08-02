data "aws_caller_identity" "current" {}

# -----------------------------------------------------------------------------
# IAM Policy: mongodb-connector producer+consumer permissions
# -----------------------------------------------------------------------------
# This policy is OUTPUT but NOT attached to a role here.
# Attachment happens in the environment config (S04) when the EKS service
# account role ARN is known.
# -----------------------------------------------------------------------------

resource "aws_iam_policy" "connector" {
  name        = "${var.cluster_name}-mongodb-connector"
  description = "Kafka permissions for the Ocean mongodb-connector on MSK Serverless"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "MSKClusterConnect"
        Effect = "Allow"
        Action = [
          "kafka-cluster:Connect",
        ]
        Resource = aws_msk_serverless_cluster.main.arn
      },
      {
        Sid    = "MSKTopicAccess"
        Effect = "Allow"
        Action = [
          "kafka-cluster:CreateTopic",
          "kafka-cluster:WriteData",
          "kafka-cluster:ReadData",
          "kafka-cluster:DescribeTopic",
          "kafka-cluster:AlterTopic",
        ]
        Resource = "arn:aws:kafka:*:${data.aws_caller_identity.current.account_id}:topic/${var.cluster_name}/*"
      },
      {
        Sid    = "MSKGroupAccess"
        Effect = "Allow"
        Action = [
          "kafka-cluster:DescribeGroup",
          "kafka-cluster:AlterGroup",
        ]
        Resource = "arn:aws:kafka:*:${data.aws_caller_identity.current.account_id}:group/${var.cluster_name}/*"
      },
    ]
  })

  tags = var.tags
}
