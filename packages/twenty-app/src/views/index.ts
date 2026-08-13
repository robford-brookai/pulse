/**
 * Ops-facing saved views.
 *
 * Views carry no `universalIdentifier`. The UID map is exactly the model-plus-catalog surface
 * the artifact serializes (`uid_map_diff` fails on any key the model never asks for), and the
 * operation set carries objects, fields, relations, and roles only — no view operation exists
 * to key. Views are named, and a view UID gets minted the same reviewed way everything else
 * does on the day the artifact learns to carry them (HANDOFF.md).
 */

import { DOMAIN_EVENT_LOG_VIEW } from "./domain-event-log.view";
import { DOMAIN_EVENT_ORPHANS_VIEW } from "./domain-event-orphans.view";
import { PATIENT_PROGRAM_STATUS_BOARD_VIEW } from "./patient-program-status-board.view";

export {
  DOMAIN_EVENT_LOG_VIEW,
  DOMAIN_EVENT_ORPHANS_VIEW,
  PATIENT_PROGRAM_STATUS_BOARD_VIEW,
};

export const ALL_VIEWS = [
  PATIENT_PROGRAM_STATUS_BOARD_VIEW,
  DOMAIN_EVENT_LOG_VIEW,
  DOMAIN_EVENT_ORPHANS_VIEW,
] as const;
