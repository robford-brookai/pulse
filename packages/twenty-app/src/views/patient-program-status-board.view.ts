/**
 * Status board — projected patient state at the patient x program grain, both dimensions and
 * both `AsOf` stamps side by side.
 *
 * The `AsOf` columns are visible on purpose: a status with a stale stamp is the shape of a
 * missing event, and the board is where ops sees that before reconciliation does.
 */

import { defineView } from "../define";

export const PATIENT_PROGRAM_STATUS_BOARD_VIEW = defineView({
  name: "patient-program-status-board",
  label: "Program Status Board",
  icon: "IconLayoutKanban",
  objectNameSingular: "patientProgram",
  type: "TABLE",
  visibleFields: [
    "patient",
    "program",
    "lifecycleStatus",
    "lifecycleStatusAsOf",
    "qualificationStatus",
    "qualificationStatusAsOf",
  ],
  filters: [],
  sorts: [{ field: "lifecycleStatusAsOf", direction: "DESC" }],
});

export default PATIENT_PROGRAM_STATUS_BOARD_VIEW;
