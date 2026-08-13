/**
 * Patient — identity and crosswalk only. Patient *state* lives on PatientProgram (grain
 * decision 2026-07-28, `design/platform/twenty-data-model.md`).
 *
 * Base fields (`id`, `createdAt`, `updatedAt`, `createdBy`, `deletedAt`) are added by Twenty
 * and are never declared here (scaffold-doc correction 1).
 */

import { defineObject, FieldType, RelationType } from "../define";
import { uid } from "../uid-map";

export const PATIENT = defineObject({
  universalIdentifier: uid("patient"),
  nameSingular: "patient",
  namePlural: "patients",
  labelSingular: "Patient",
  labelPlural: "Patients",
  icon: "IconUser",
  description:
    "Identity and crosswalk only — patient state lives on PatientProgram (grain decision 2026-07-28).",
  fields: [
    {
      universalIdentifier: uid("patient.canonicalPatientId"),
      name: "canonicalPatientId",
      type: FieldType.TEXT,
      label: "Canonical Patient ID",
      description:
        "DIM_PATIENT_CONFORMED spine ID — the canonical identity (`entity_ref` system `brook`).",
      // Real NOT NULL is `isNullable: false` plus a default (scaffold-doc correction 3).
      isNullable: false,
      isUnique: true,
      defaultValue: "''",
    },
    {
      universalIdentifier: uid("patient.name"),
      name: "name",
      type: FieldType.FULL_NAME,
      label: "Name",
    },
    {
      universalIdentifier: uid("patient.sfdcId"),
      name: "sfdcId",
      type: FieldType.TEXT,
      label: "Salesforce ID",
      description: "External ID, system `sfdc`.",
      isUnique: true,
    },
    {
      universalIdentifier: uid("patient.mrn"),
      name: "mrn",
      type: FieldType.TEXT,
      label: "MRN",
      description: "External ID, system `mrn`.",
    },
    {
      universalIdentifier: uid("patient.appUserId"),
      name: "appUserId",
      type: FieldType.TEXT,
      label: "App User ID",
      description: "External ID, system `app`.",
    },
    {
      universalIdentifier: uid("patient.patientPrograms"),
      name: "patientPrograms",
      type: FieldType.RELATION,
      label: "Patient Programs",
      relation: {
        type: RelationType.ONE_TO_MANY,
        targetObject: "patientProgram",
        inverseField: "patient",
      },
    },
  ],
});

export default PATIENT;
