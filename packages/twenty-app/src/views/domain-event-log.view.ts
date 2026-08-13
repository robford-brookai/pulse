/**
 * Event log — the append-only ledger, newest first. The read-side counterpart to the producer
 * role: staff can see every event and change none of them.
 *
 * Ordered by `occurredAt` (business time, set by the producer) rather than Twenty's `createdAt`
 * (recording time): a backfilled event lands in the ledger where it happened, not where it
 * arrived.
 */

import { defineView } from "../define";

export const DOMAIN_EVENT_LOG_VIEW = defineView({
  name: "domain-event-log",
  label: "Event Log",
  icon: "IconHistory",
  objectNameSingular: "domainEvent",
  type: "TABLE",
  visibleFields: [
    "occurredAt",
    "eventType",
    "entityType",
    "entityRefId",
    "programCode",
    "producer",
    "actorType",
  ],
  filters: [],
  sorts: [{ field: "occurredAt", direction: "DESC" }],
});

export default DOMAIN_EVENT_LOG_VIEW;
