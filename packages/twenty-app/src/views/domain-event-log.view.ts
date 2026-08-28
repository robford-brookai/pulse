/**
 * Event log — the append-only ledger, newest first. The read-side counterpart to the producer
 * role: staff can see every event and change none of them.
 *
 * Ordered by `occurredAt` (business time, set by the producer) rather than Twenty's `createdAt`
 * (recording time): a backfilled event lands in the ledger where it happened, not where it
 * arrived.
 */

import { defineView, ViewSortDirection, ViewType } from "twenty-sdk/define";
import { uid } from "../uid-map";

export default defineView({
  universalIdentifier: uid("view.domain-event-log"),
  name: "Event Log",
  icon: "IconHistory",
  objectUniversalIdentifier: uid("domainEvent"),
  type: ViewType.TABLE,
  position: 1,
  fields: [
    {
      universalIdentifier: uid("view.domain-event-log.field.occurredAt"),
      fieldMetadataUniversalIdentifier: uid("domainEvent.occurredAt"),
      position: 0,
      isVisible: true,
    },
    {
      universalIdentifier: uid("view.domain-event-log.field.eventType"),
      fieldMetadataUniversalIdentifier: uid("domainEvent.eventType"),
      position: 1,
      isVisible: true,
    },
    {
      universalIdentifier: uid("view.domain-event-log.field.entityType"),
      fieldMetadataUniversalIdentifier: uid("domainEvent.entityType"),
      position: 2,
      isVisible: true,
    },
    {
      universalIdentifier: uid(
        "view.domain-event-log.field.entityRefId",
      ),
      fieldMetadataUniversalIdentifier: uid("domainEvent.entityRefId"),
      position: 3,
      isVisible: true,
    },
    {
      universalIdentifier: uid(
        "view.domain-event-log.field.programCode",
      ),
      fieldMetadataUniversalIdentifier: uid("domainEvent.programCode"),
      position: 4,
      isVisible: true,
    },
    {
      universalIdentifier: uid("view.domain-event-log.field.producer"),
      fieldMetadataUniversalIdentifier: uid("domainEvent.producer"),
      position: 5,
      isVisible: true,
    },
    {
      universalIdentifier: uid("view.domain-event-log.field.actorType"),
      fieldMetadataUniversalIdentifier: uid("domainEvent.actorType"),
      position: 6,
      isVisible: true,
    },
  ],
  filters: [],
  sorts: [
    {
      universalIdentifier: uid("view.domain-event-log.sort.occurredAt"),
      fieldMetadataUniversalIdentifier: uid("domainEvent.occurredAt"),
      direction: ViewSortDirection.DESC,
    },
  ],
});
