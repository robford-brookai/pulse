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
 */

import { defineRole, type FieldPermission } from "../define";
import { DOMAIN_EVENT } from "../objects/domain-event.object";

const domainEventEnvelopeIsReadOnly: readonly FieldPermission[] =
  DOMAIN_EVENT.fields
    .filter((field) => field.type !== "RELATION")
    .map((field) => ({
      objectNameSingular: DOMAIN_EVENT.nameSingular,
      fieldName: field.name,
      canRead: true,
      canUpdate: false,
    }))
    .toSorted((left, right) => left.fieldName.localeCompare(right.fieldName));

export const APP_ROLE = defineRole({
  name: "app",
  label: "Projection App",
  description:
    "The projection runtime: resolves entities, applies status per the lookup, binds relations.",
  objectPermissions: [
    {
      objectNameSingular: "clinic",
      canRead: true,
      canCreate: true,
      canUpdate: true,
      canDelete: false,
    },
    {
      objectNameSingular: "domainEvent",
      canRead: true,
      canCreate: true,
      canUpdate: true,
      canDelete: false,
    },
    {
      objectNameSingular: "patient",
      canRead: true,
      canCreate: false,
      canUpdate: false,
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
      canCreate: false,
      canUpdate: false,
      canDelete: false,
    },
    {
      objectNameSingular: "provider",
      canRead: true,
      canCreate: true,
      canUpdate: true,
      canDelete: false,
    },
  ],
  fieldPermissions: domainEventEnvelopeIsReadOnly,
});

export default APP_ROLE;
