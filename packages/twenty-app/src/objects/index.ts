/**
 * The workspace's custom objects. Core Twenty objects are never modified
 * (`design/platform/twenty-data-model.md`, preamble).
 *
 * Ordered as the model definition orders them (`pulse_core.twenty_model.TWENTY_MODEL`), so the
 * two readings of the model line up when a reviewer puts them side by side.
 */

import { CLINIC } from "./clinic.object";
import { DOMAIN_EVENT } from "./domain-event.object";
import { PATIENT_PROGRAM } from "./patient-program.object";
import { PATIENT } from "./patient.object";
import { PROGRAM } from "./program.object";
import { PROVIDER } from "./provider.object";

export { CLINIC, DOMAIN_EVENT, PATIENT, PATIENT_PROGRAM, PROGRAM, PROVIDER };

export const ALL_OBJECTS = [
  PATIENT,
  PROGRAM,
  PATIENT_PROGRAM,
  PROVIDER,
  CLINIC,
  DOMAIN_EVENT,
] as const;
