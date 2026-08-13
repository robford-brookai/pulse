/**
 * Staff — ops and clinical users. Reads and edits entity records; every status field and the
 * whole event log are read-only.
 *
 * This is the single-writer rule as reviewable config: state changes reach a status field only
 * by way of an event and the projection function, never by a staff edit. The field list is
 * written out rather than derived from a name prefix so that adding a status field is a
 * decision someone makes here, and so `tests/model.test.ts` checks a claim instead of
 * restating a derivation.
 *
 * No role grants delete on anything — DomainEvent is append-only by policy, and entity records
 * are archived rather than removed.
 */

import { defineRole } from "../define";

export const STAFF_ROLE = defineRole({
  name: "staff",
  label: "Ops and Clinical Staff",
  description:
    "Reads and edits entity records; status fields and the event log are read-only.",
  objectPermissions: [
    {
      objectNameSingular: "clinic",
      canRead: true,
      canCreate: true,
      canUpdate: true,
      canDelete: false,
    },
    {
      objectNameSingular: "patient",
      canRead: true,
      canCreate: true,
      canUpdate: true,
      canDelete: false,
    },
    {
      objectNameSingular: "patientProgram",
      canRead: true,
      canCreate: true,
      canUpdate: true,
      canDelete: false,
    },
    {
      objectNameSingular: "program",
      canRead: true,
      canCreate: true,
      canUpdate: true,
      canDelete: false,
    },
    {
      objectNameSingular: "provider",
      canRead: true,
      canCreate: true,
      canUpdate: true,
      canDelete: false,
    },
    // Read the log, never write it: the producer role is the only create path.
    {
      objectNameSingular: "domainEvent",
      canRead: true,
      canCreate: false,
      canUpdate: false,
      canDelete: false,
    },
  ],
  fieldPermissions: [
    {
      objectNameSingular: "clinic",
      fieldName: "lifecycleStatus",
      canRead: true,
      canUpdate: false,
    },
    {
      objectNameSingular: "clinic",
      fieldName: "lifecycleStatusAsOf",
      canRead: true,
      canUpdate: false,
    },
    {
      objectNameSingular: "patientProgram",
      fieldName: "lifecycleStatus",
      canRead: true,
      canUpdate: false,
    },
    {
      objectNameSingular: "patientProgram",
      fieldName: "lifecycleStatusAsOf",
      canRead: true,
      canUpdate: false,
    },
    {
      objectNameSingular: "patientProgram",
      fieldName: "qualificationStatus",
      canRead: true,
      canUpdate: false,
    },
    {
      objectNameSingular: "patientProgram",
      fieldName: "qualificationStatusAsOf",
      canRead: true,
      canUpdate: false,
    },
    {
      objectNameSingular: "provider",
      fieldName: "lifecycleStatus",
      canRead: true,
      canUpdate: false,
    },
    {
      objectNameSingular: "provider",
      fieldName: "lifecycleStatusAsOf",
      canRead: true,
      canUpdate: false,
    },
  ],
});

export default STAFF_ROLE;
