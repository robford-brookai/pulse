terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

# -----------------------------------------------------------------------------
# Schedule triggers (task 5.1, design D8, D14)
# -----------------------------------------------------------------------------
# D14 chose the platform scheduler (SPCS job / EventBridge Scheduler) as the
# clock-driven trigger; this module wires the EventBridge Scheduler side —
# `aws_scheduler_schedule`, not the older `aws_cloudwatch_event_rule` (that
# resource has no schedule-only expression validation and no per-schedule
# retry/flexible-window knobs). One schedule per entry in `var.schedules`,
# whose keys and cadences come from
# `generated/schedule_catalog.auto.tfvars.json`, never hand-written here —
# same separation `eventbridge-ocean` keeps between its module and
# `generated/event_catalog.auto.tfvars.json`.
#
# Every schedule targets the same CLI runner (`var.target_arn`, the SPCS job
# or ECS task definition running `schedules.cli`, decided at deploy time —
# design's Open Questions) and differs only in the subcommand appended to the
# container override, so `each.value.target_subcommand` is the one thing that
# ties a schedule to "month-open" vs "consent-sweep" in `schedules/cli.py`.
#
# Applying this — creating `var.target_arn` and `var.role_arn`'s target — is a
# deploy step outside this change (design Migration Plan: "pre-production,
# additive only ... no live schedulers until the infra config is applied").
#
# A dedicated schedule group rather than AWS's built-in `default` group, for
# the same reason `eventbridge-ocean` dedicates a bus: `aws_scheduler_schedule`
# takes no `tags` argument at all (unlike the event bus and rule resources),
# so the group is the only place these two schedules can carry `var.tags`.
# -----------------------------------------------------------------------------

resource "aws_scheduler_schedule_group" "schedules" {
  name = var.schedule_group_name
  tags = var.tags
}

resource "aws_scheduler_schedule" "job" {
  for_each = var.schedules

  name                = "schedules-${each.key}"
  description         = each.value.description
  schedule_expression = each.value.cron_expression
  group_name          = aws_scheduler_schedule_group.schedules.name

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = var.target_arn
    role_arn = var.role_arn

    # The CLI runner's container override: `python -m schedules.cli <subcommand>`
    # (spec: "each trigger targets the corresponding CLI subcommand"). No
    # `--dry-run` here — that flag is the offline path task 4.2 exercises
    # against fixtures, never the scheduled one.
    input = jsonencode({
      containerOverrides = [
        {
          command = ["python", "-m", "schedules.cli", each.value.target_subcommand]
        }
      ]
    })

    retry_policy {
      maximum_retry_attempts       = each.value.maximum_retry_attempts
      maximum_event_age_in_seconds = each.value.maximum_event_age_in_seconds
    }
  }
}
