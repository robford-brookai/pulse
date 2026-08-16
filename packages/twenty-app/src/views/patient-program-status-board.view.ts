/**
 * Status board — projected patient state at the patient x program grain, both dimensions and
 * both `AsOf` stamps side by side.
 *
 * A TABLE, and deliberately so: the point is the six columns next to each other, which a board
 * cannot show. The `AsOf` columns are visible on purpose — a status with a stale stamp is the
 * shape of a missing event, and this is where ops sees that before reconciliation does. The
 * lifecycle kanban is a separate view, not this one wearing a kanban icon.
 */

import { defineView, ViewSortDirection, ViewType } from "../define";
import { uid } from "../uid-map";

export const PATIENT_PROGRAM_STATUS_BOARD_VIEW = defineView({
  universalIdentifier: uid("view.patient-program-status-board"),
  name: "Program Status Board",
  icon: "IconTable",
  objectUniversalIdentifier: uid("patientProgram"),
  type: ViewType.TABLE,
  position: 0,
  fields: [
    {
      universalIdentifier: uid(
        "view.patient-program-status-board.field.patient",
      ),
      fieldMetadataUniversalIdentifier: uid("patientProgram.patient"),
      position: 0,
      isVisible: true,
    },
    {
      universalIdentifier: uid(
        "view.patient-program-status-board.field.program",
      ),
      fieldMetadataUniversalIdentifier: uid("patientProgram.program"),
      position: 1,
      isVisible: true,
    },
    {
      universalIdentifier: uid(
        "view.patient-program-status-board.field.lifecycleStatus",
      ),
      fieldMetadataUniversalIdentifier: uid("patientProgram.lifecycleStatus"),
      position: 2,
      isVisible: true,
    },
    {
      universalIdentifier: uid(
        "view.patient-program-status-board.field.lifecycleStatusAsOf",
      ),
      fieldMetadataUniversalIdentifier: uid(
        "patientProgram.lifecycleStatusAsOf",
      ),
      position: 3,
      isVisible: true,
    },
    {
      universalIdentifier: uid(
        "view.patient-program-status-board.field.qualificationStatus",
      ),
      fieldMetadataUniversalIdentifier: uid(
        "patientProgram.qualificationStatus",
      ),
      position: 4,
      isVisible: true,
    },
    {
      universalIdentifier: uid(
        "view.patient-program-status-board.field.qualificationStatusAsOf",
      ),
      fieldMetadataUniversalIdentifier: uid(
        "patientProgram.qualificationStatusAsOf",
      ),
      position: 5,
      isVisible: true,
    },
  ],
  filters: [],
  sorts: [
    {
      universalIdentifier: uid(
        "view.patient-program-status-board.sort.lifecycleStatusAsOf",
      ),
      fieldMetadataUniversalIdentifier: uid(
        "patientProgram.lifecycleStatusAsOf",
      ),
      direction: ViewSortDirection.DESC,
    },
  ],
});

export default PATIENT_PROGRAM_STATUS_BOARD_VIEW;
