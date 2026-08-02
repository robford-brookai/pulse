terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

# -----------------------------------------------------------------------------
# Event Bus
# -----------------------------------------------------------------------------
# The single OCEAN bus, replacing the MSK Serverless cluster this module was
# swapped in for (task 6.1). Everything that made the Kafka module large — a VPC,
# subnets, a security group, broker ports — has no analogue here: EventBridge is
# a regional AWS service reached over the AWS API, so there is no network to
# place or firewall.
#
# A dedicated bus rather than the account `default` bus, because the default bus
# also carries AWS service events, and the per-consumer rules (task 6.2) are
# written to match OCEAN's `source` alone. `EventBridgePublisher` names this bus
# explicitly for the mirror-image reason: an event put on the default bus is
# accepted and then matched by no rule.
#
# Rules, queues, DLQs and the archive attach to this bus in tasks 6.2–6.4; their
# patterns come from `generated/event_catalog.auto.tfvars.json`, never from here.
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_event_bus" "ocean" {
  name = var.event_bus_name

  tags = merge(var.tags, {
    Name = var.event_bus_name
  })
}
