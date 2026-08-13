/**
 * Orphan events — the view the projection's unresolved-reference path writes into.
 *
 * When `(entityRefSystem, entityRefId)` resolves to nothing, the handler leaves all three
 * relations empty and stops: no crash, no state write (`twenty-projection-apply`, "An
 * unresolvable ref stops cleanly"). Those events are not lost, they are here — a crosswalk gap
 * to work, ordered oldest first because the oldest gap is the one blocking the most downstream
 * state.
 */

import { defineView } from "../define";

export const DOMAIN_EVENT_ORPHANS_VIEW = defineView({
  name: "domain-event-orphans",
  label: "Orphan Events",
  icon: "IconUnlink",
  objectNameSingular: "domainEvent",
  type: "TABLE",
  visibleFields: [
    "occurredAt",
    "eventType",
    "entityType",
    "entityRefSystem",
    "entityRefId",
    "programCode",
    "producer",
  ],
  filters: [
    { field: "patientProgram", operand: "isEmpty" },
    { field: "provider", operand: "isEmpty" },
    { field: "clinic", operand: "isEmpty" },
  ],
  sorts: [{ field: "occurredAt", direction: "ASC" }],
});

export default DOMAIN_EVENT_ORPHANS_VIEW;
