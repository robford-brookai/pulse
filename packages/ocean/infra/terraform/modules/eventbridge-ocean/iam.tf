# -----------------------------------------------------------------------------
# IAM Policy: publisher permissions
# -----------------------------------------------------------------------------
# Replaces the `kafka-cluster:*` connector policy the MSK module emitted. As
# there, the policy is OUTPUT but NOT attached to a role: attachment happens in
# the environment config, once the EKS service account role ARN is known.
#
# One policy covers all thirteen publish sites because they all address the same
# bus through the same shared publisher; `source` and `detail-type` are not
# resource-level permissions in EventBridge, so a per-domain split would not
# narrow anything. Consumers need no policy here — they read SQS queues, whose
# permissions land with the queues in task 6.2.
# -----------------------------------------------------------------------------

resource "aws_iam_policy" "publisher" {
  name        = "${var.event_bus_name}-eventbridge-publisher"
  description = "PutEvents permission on the OCEAN EventBridge bus"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "PutOceanEvents"
        Effect = "Allow"
        Action = [
          "events:PutEvents",
        ]
        Resource = aws_cloudwatch_event_bus.ocean.arn
      },
    ]
  })

  tags = var.tags
}
