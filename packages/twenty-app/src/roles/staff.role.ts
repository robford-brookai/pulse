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
 * are archived rather than removed. Twenty has no create-without-update permission: an object's
 * `canUpdateObjectRecords` covers create and update together, so "reads and edits entity
 * records" grants both at once, which is what the old `canCreate`/`canUpdate` pair meant here.
 *
 * `defineApplicationRole`, not `defineRole`: this is the role a newly-provisioned member gets
 * (the SDK's replacement for the config-level `defaultRole`), because staff is the
 * least-capable role a human can hold.
 *
 * The default export is the inline call: the CLI's manifest builder detects entities
 * syntactically, and the const-then-default form is invisible to it.
 */

import { defineApplicationRole } from "twenty-sdk/define";
import { uid } from "../uid-map";

export default defineApplicationRole({
  // Minted 2026-08-17 (task 6.4). Role identifiers live here rather than in uid-map.json
  // because `uid_map_diff` rejects any key the Python model never asks for; moving the role
  // family into the map is proposed in HANDOFF.md.
  universalIdentifier: "c367c6f6-756a-421c-8908-fe6c2ca560b9",
  label: "Ops and Clinical Staff",
  description:
    "Reads and edits entity records; status fields and the event log are read-only.",
  canBeAssignedToUsers: true,
  canBeAssignedToAgents: false,
  canBeAssignedToApiKeys: false,
  objectPermissions: [
    {
      objectUniversalIdentifier: uid("clinic"),
      canReadObjectRecords: true,
      canUpdateObjectRecords: true,
      canSoftDeleteObjectRecords: false,
      canDestroyObjectRecords: false,
    },
    {
      objectUniversalIdentifier: uid("patient"),
      canReadObjectRecords: true,
      canUpdateObjectRecords: true,
      canSoftDeleteObjectRecords: false,
      canDestroyObjectRecords: false,
    },
    {
      objectUniversalIdentifier: uid("patientProgram"),
      canReadObjectRecords: true,
      canUpdateObjectRecords: true,
      canSoftDeleteObjectRecords: false,
      canDestroyObjectRecords: false,
    },
    {
      objectUniversalIdentifier: uid("program"),
      canReadObjectRecords: true,
      canUpdateObjectRecords: true,
      canSoftDeleteObjectRecords: false,
      canDestroyObjectRecords: false,
    },
    {
      objectUniversalIdentifier: uid("provider"),
      canReadObjectRecords: true,
      canUpdateObjectRecords: true,
      canSoftDeleteObjectRecords: false,
      canDestroyObjectRecords: false,
    },
    // Read the log, never write it: the producer role is the only create path.
    {
      objectUniversalIdentifier: uid("domainEvent"),
      canReadObjectRecords: true,
      canUpdateObjectRecords: false,
      canSoftDeleteObjectRecords: false,
      canDestroyObjectRecords: false,
    },
  ],
  fieldPermissions: [
    {
      objectUniversalIdentifier: uid("clinic"),
      fieldUniversalIdentifier: uid("clinic.lifecycleStatus"),
      canReadFieldValue: true,
      canUpdateFieldValue: false,
    },
    {
      objectUniversalIdentifier: uid("clinic"),
      fieldUniversalIdentifier: uid("clinic.lifecycleStatusAsOf"),
      canReadFieldValue: true,
      canUpdateFieldValue: false,
    },
    {
      objectUniversalIdentifier: uid("patientProgram"),
      fieldUniversalIdentifier: uid("patientProgram.lifecycleStatus"),
      canReadFieldValue: true,
      canUpdateFieldValue: false,
    },
    {
      objectUniversalIdentifier: uid("patientProgram"),
      fieldUniversalIdentifier: uid("patientProgram.lifecycleStatusAsOf"),
      canReadFieldValue: true,
      canUpdateFieldValue: false,
    },
    {
      objectUniversalIdentifier: uid("patientProgram"),
      fieldUniversalIdentifier: uid("patientProgram.qualificationStatus"),
      canReadFieldValue: true,
      canUpdateFieldValue: false,
    },
    {
      objectUniversalIdentifier: uid("patientProgram"),
      fieldUniversalIdentifier: uid("patientProgram.qualificationStatusAsOf"),
      canReadFieldValue: true,
      canUpdateFieldValue: false,
    },
    {
      objectUniversalIdentifier: uid("provider"),
      fieldUniversalIdentifier: uid("provider.lifecycleStatus"),
      canReadFieldValue: true,
      canUpdateFieldValue: false,
    },
    {
      objectUniversalIdentifier: uid("provider"),
      fieldUniversalIdentifier: uid("provider.lifecycleStatusAsOf"),
      canReadFieldValue: true,
      canUpdateFieldValue: false,
    },
  ],
});
