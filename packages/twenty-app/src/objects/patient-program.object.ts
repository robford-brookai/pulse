/**
 * PatientProgram — one row per patient x program, the patient-state grain and the only
 * projection target (D2). `project-domain-event` writes the status pairs here; staff read them
 * (see `src/roles/staff.role.ts`).
 *
 * Each dimension carries its own `<field>AsOf` guard. One pair per dimension is what makes the
 * LWW guard per-dimension rather than per-row: a qualification event never touches
 * `lifecycleStatusAsOf`.
 *
 * The default export is the inline `defineObject({...})` call: the CLI's manifest builder
 * detects entities syntactically, and the const-then-default form is invisible to it.
 */

import {
  PATIENT_PROGRAM_LIFECYCLE_STATUS_OPTIONS,
  PATIENT_PROGRAM_QUALIFICATION_STATUS_OPTIONS,
} from "../../generated/options";
import { defineObject, FieldType, RelationType } from "twenty-sdk/define";
import { uid } from "../uid-map";

export default defineObject({
  universalIdentifier: uid("patientProgram"),
  nameSingular: "patientProgram",
  namePlural: "patientPrograms",
  labelSingular: "Patient Program",
  labelPlural: "Patient Programs",
  icon: "IconUserHeart",
  description:
    "One row per patient x program — the patient-state grain. A projection target only (D2).",
  fields: [
    {
      universalIdentifier: uid("patientProgram.patient"),
      name: "patient",
      type: FieldType.RELATION,
      label: "Patient",
      // A required relation is enforced by the foreign key; Twenty has no literal default for
      // one, so `isNullable: false` stands alone here.
      isNullable: false,
      relationTargetObjectMetadataUniversalIdentifier: uid("patient"),
      relationTargetFieldMetadataUniversalIdentifier: uid(
        "patient.patientPrograms",
      ),
      universalSettings: {
        relationType: RelationType.MANY_TO_ONE,
        joinColumnName: "patientId",
      },
    },
    {
      universalIdentifier: uid("patientProgram.program"),
      name: "program",
      type: FieldType.RELATION,
      label: "Program",
      isNullable: false,
      relationTargetObjectMetadataUniversalIdentifier: uid("program"),
      relationTargetFieldMetadataUniversalIdentifier: uid(
        "program.patientPrograms",
      ),
      universalSettings: {
        relationType: RelationType.MANY_TO_ONE,
        joinColumnName: "programId",
      },
    },
    // Denormalized for the webhook path, and only for it. A Twenty webhook delivers
    // `properties.after` — the flat ORM entity — so a relation arrives as `patientId` /
    // `programId`, a foreign key, never a nested `patient` or `program` object. Without these two
    // columns a consumer has to read the record back over REST per delivery, which puts a
    // credential and a network failure on the hot path. Both values are pseudonymous identifiers:
    // a spine ID and a program code, never anything that identifies a person.
    {
      universalIdentifier: uid("patientProgram.canonicalPatientId"),
      name: "canonicalPatientId",
      type: FieldType.TEXT,
      label: "Canonical Patient ID",
      description:
        "Denormalized copy of `patient.canonicalPatientId`, so a webhook delivery resolves without a read-back.",
    },
    {
      universalIdentifier: uid("patientProgram.programCode"),
      name: "programCode",
      type: FieldType.TEXT,
      label: "Program Code",
      description:
        "Denormalized copy of `program.code`, so a webhook delivery resolves without a read-back.",
    },
    {
      universalIdentifier: uid("patientProgram.lifecycleStatus"),
      name: "lifecycleStatus",
      type: FieldType.SELECT,
      label: "Lifecycle Status",
      description:
        "Enrollment state at the patient x program grain. Options from the `enrollment` catalog subject.",
      defaultValue: "'pending_start'",
      options: PATIENT_PROGRAM_LIFECYCLE_STATUS_OPTIONS,
    },
    {
      universalIdentifier: uid("patientProgram.lifecycleStatusAsOf"),
      name: "lifecycleStatusAsOf",
      type: FieldType.DATE_TIME,
      label: "Lifecycle Status As Of",
      description:
        "Last-writer-wins guard for lifecycleStatus: the `occurredAt` of the event that set it.",
    },
    {
      universalIdentifier: uid("patientProgram.qualificationStatus"),
      name: "qualificationStatus",
      type: FieldType.SELECT,
      label: "Qualification Status",
      description:
        "Billing qualification. Options from the `billing_episode` catalog subject; set only by clinic-rules-engine events.",
      defaultValue: "'open'",
      options: PATIENT_PROGRAM_QUALIFICATION_STATUS_OPTIONS,
    },
    {
      universalIdentifier: uid("patientProgram.qualificationStatusAsOf"),
      name: "qualificationStatusAsOf",
      type: FieldType.DATE_TIME,
      label: "Qualification Status As Of",
      description:
        "Last-writer-wins guard for qualificationStatus: the `occurredAt` of the event that set it.",
    },
    {
      universalIdentifier: uid("patientProgram.domainEvents"),
      name: "domainEvents",
      type: FieldType.RELATION,
      label: "Domain Events",
      relationTargetObjectMetadataUniversalIdentifier: uid("domainEvent"),
      relationTargetFieldMetadataUniversalIdentifier: uid(
        "domainEvent.patientProgram",
      ),
      universalSettings: { relationType: RelationType.ONE_TO_MANY },
    },
  ],
});
