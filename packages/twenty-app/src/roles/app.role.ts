/**
 * App — the projection runtime's role, and the identity the `project-domain-event` token is
 * derived from. It holds what the projection needs and nothing more: read the event, resolve
 * the entity, create the PatientProgram row on first contact, write the status pair, bind the
 * relation back onto the event.
 *
 * Patient and Program are read-only to it: the projection never invents an identity or a
 * program, it only pairs ones that already exist. Nothing is deletable.
 *
 * The DomainEvent field permissions are derived from the object rather than listed, because the
 * claim is structural: every envelope field is read-only to the projection, and the relations
 * (`patientProgram`, `provider`, `clinic`) are the only thing it writes back. Adding an
 * envelope field should extend this set without an edit here; adding a relation should not.
 *
 * The default export is the inline call: the CLI's manifest builder detects entities
 * syntactically, and the const-then-default form is invisible to it.
 */

import { defineRole } from "twenty-sdk/define";
import DOMAIN_EVENT from "../objects/domain-event.object";
import { uid } from "../uid-map";

type FieldPermission = NonNullable<
  Parameters<typeof defineRole>[0]["fieldPermissions"]
>[number];

const domainEventEnvelopeIsReadOnly: FieldPermission[] =
  DOMAIN_EVENT.config.fields
    .filter((field) => field.type !== "RELATION")
    .map((field) => ({
      objectUniversalIdentifier: uid("domainEvent"),
      fieldUniversalIdentifier: field.universalIdentifier,
      canReadFieldValue: true,
      canUpdateFieldValue: false,
    }))
    .toSorted((left, right) =>
      left.fieldUniversalIdentifier.localeCompare(
        right.fieldUniversalIdentifier,
      ),
    );

export default defineRole({
  // Minted 2026-08-17 (task 6.4); see staff.role.ts for why not uid-map.json.
  universalIdentifier: "3c526900-d0f2-4190-88ce-575e5784396f",
  label: "Projection App",
  description:
    "The projection runtime: resolves entities, applies status per the lookup, binds relations.",
  canBeAssignedToUsers: false,
  canBeAssignedToAgents: false,
  canBeAssignedToApiKeys: true,
  objectPermissions: [
    {
      objectUniversalIdentifier: uid("clinic"),
      canReadObjectRecords: true,
      canUpdateObjectRecords: true,
      canSoftDeleteObjectRecords: false,
      canDestroyObjectRecords: false,
    },
    {
      objectUniversalIdentifier: uid("domainEvent"),
      canReadObjectRecords: true,
      canUpdateObjectRecords: true,
      canSoftDeleteObjectRecords: false,
      canDestroyObjectRecords: false,
    },
    {
      objectUniversalIdentifier: uid("patient"),
      canReadObjectRecords: true,
      canUpdateObjectRecords: false,
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
      canUpdateObjectRecords: false,
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
  ],
  fieldPermissions: domainEventEnvelopeIsReadOnly,
});
