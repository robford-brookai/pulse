# -----------------------------------------------------------------------------
# Bus archive (task 6.4)
# -----------------------------------------------------------------------------
# The convenience-replay window ADR §4.6 assumes. A consumer that missed events
# is re-driven by starting an EventBridge replay against this archive for the
# missed window; its idempotency guard makes the result identical to never
# having missed it.
#
# Retention is deliberately bounded: with `retention_days` omitted the archive
# keeps events forever, which would make it a second durable record. It is not
# the record — the append-only `audit_log` is. Any value from 30 to 90 days
# satisfies the spec (design, Open Questions); the variable enforces that window.
#
# No `event_pattern`: the bus is dedicated to OCEAN, so everything on it belongs
# in the replay window. Filtering is the per-consumer rules' job (task 6.2).
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_event_archive" "ocean" {
  name             = "${var.event_bus_name}-archive"
  description      = "Bounded convenience-replay archive for the ${var.event_bus_name} bus. Not the durable record; that is audit_log."
  event_source_arn = aws_cloudwatch_event_bus.ocean.arn
  retention_days   = var.archive_retention_days
}
