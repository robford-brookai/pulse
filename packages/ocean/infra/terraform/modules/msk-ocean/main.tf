terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

# -----------------------------------------------------------------------------
# Security Group
# -----------------------------------------------------------------------------

resource "aws_security_group" "msk" {
  name_prefix = "${var.cluster_name}-msk-ocean-"
  description = "Security group for MSK Serverless cluster ${var.cluster_name}"
  vpc_id      = var.vpc_id

  tags = merge(var.tags, {
    Name = "${var.cluster_name}-msk-ocean"
  })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group_rule" "msk_ingress_iam" {
  for_each = toset(var.allowed_security_group_ids)

  type                     = "ingress"
  from_port                = 9098
  to_port                  = 9098
  protocol                 = "tcp"
  source_security_group_id = each.value
  security_group_id        = aws_security_group.msk.id
  description              = "IAM auth from ${each.value}"
}

resource "aws_security_group_rule" "msk_egress_all" {
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.msk.id
  description       = "Allow all outbound"
}

# -----------------------------------------------------------------------------
# MSK Serverless Cluster
# -----------------------------------------------------------------------------

resource "aws_msk_serverless_cluster" "main" {
  cluster_name = var.cluster_name

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = [aws_security_group.msk.id]
  }

  client_authentication {
    sasl {
      iam {
        enabled = true
      }
    }
  }

  tags = var.tags
}
