/**
 * Orphan events — the view the projection's unresolved-reference path writes into.
 *
 * When `(entityRefSystem, entityRefId)` resolves to nothing, the handler leaves all three
 * relations empty and stops: no crash, no state write (`twenty-projection-apply`, "An
 * unresolvable ref stops cleanly"). Those events are not lost, they are here — a crosswalk gap
 * to work, ordered oldest first because the oldest gap is the one blocking the most downstream
 * state.
 */

import {
  defineView,
  ViewFilterOperand,
  ViewSortDirection,
  ViewType,
} from "../define";
import { uid } from "../uid-map";

export const DOMAIN_EVENT_ORPHANS_VIEW = defineView({
  universalIdentifier: uid("view.domain-event-orphans"),
  name: "Orphan Events",
  icon: "IconUnlink",
  objectUniversalIdentifier: uid("domainEvent"),
  type: ViewType.TABLE,
  position: 2,
  fields: [
    {
      universalIdentifier: uid(
        "view.domain-event-orphans.field.occurredAt",
      ),
      fieldMetadataUniversalIdentifier: uid("domainEvent.occurredAt"),
      position: 0,
      isVisible: true,
    },
    {
      universalIdentifier: uid(
        "view.domain-event-orphans.field.eventType",
      ),
      fieldMetadataUniversalIdentifier: uid("domainEvent.eventType"),
      position: 1,
      isVisible: true,
    },
    {
      universalIdentifier: uid(
        "view.domain-event-orphans.field.entityType",
      ),
      fieldMetadataUniversalIdentifier: uid("domainEvent.entityType"),
      position: 2,
      isVisible: true,
    },
    {
      universalIdentifier: uid(
        "view.domain-event-orphans.field.entityRefSystem",
      ),
      fieldMetadataUniversalIdentifier: uid("domainEvent.entityRefSystem"),
      position: 3,
      isVisible: true,
    },
    {
      universalIdentifier: uid(
        "view.domain-event-orphans.field.entityRefId",
      ),
      fieldMetadataUniversalIdentifier: uid("domainEvent.entityRefId"),
      position: 4,
      isVisible: true,
    },
    {
      universalIdentifier: uid(
        "view.domain-event-orphans.field.programCode",
      ),
      fieldMetadataUniversalIdentifier: uid("domainEvent.programCode"),
      position: 5,
      isVisible: true,
    },
    {
      universalIdentifier: uid(
        "view.domain-event-orphans.field.producer",
      ),
      fieldMetadataUniversalIdentifier: uid("domainEvent.producer"),
      position: 6,
      isVisible: true,
    },
  ],
  // All three empty at once, which is what "unresolvable" means: the handler resolves the ref to
  // one of the three, so an event missing every one of them resolved to nothing.
  filters: [
    {
      universalIdentifier: uid(
        "view.domain-event-orphans.filter.patientProgram",
      ),
      fieldMetadataUniversalIdentifier: uid("domainEvent.patientProgram"),
      operand: ViewFilterOperand.IS_EMPTY,
      value: "",
    },
    {
      universalIdentifier: uid(
        "view.domain-event-orphans.filter.provider",
      ),
      fieldMetadataUniversalIdentifier: uid("domainEvent.provider"),
      operand: ViewFilterOperand.IS_EMPTY,
      value: "",
    },
    {
      universalIdentifier: uid(
        "view.domain-event-orphans.filter.clinic",
      ),
      fieldMetadataUniversalIdentifier: uid("domainEvent.clinic"),
      operand: ViewFilterOperand.IS_EMPTY,
      value: "",
    },
  ],
  sorts: [
    {
      universalIdentifier: uid(
        "view.domain-event-orphans.sort.occurredAt",
      ),
      fieldMetadataUniversalIdentifier: uid("domainEvent.occurredAt"),
      direction: ViewSortDirection.ASC,
    },
  ],
});

export default DOMAIN_EVENT_ORPHANS_VIEW;
