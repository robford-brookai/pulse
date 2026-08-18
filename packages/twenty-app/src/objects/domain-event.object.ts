/**
 * DomainEvent — the append-only event log. Never updated, never deleted (immutability policy;
 * enforced by the role set in `src/roles/`, verified by the Snowflake mutation-audit view).
 *
 * `recorded_at` in the data-model doc is Twenty's base `createdAt` and is therefore not
 * declared. `evidence` and `payload` are `RAW_JSON` with no TEXT fallback (scaffold-doc
 * correction 2). Twenty has no polymorphic relation: the event carries three nullable
 * relations with exactly one populated, and none populated is the orphan case
 * (`src/views/domain-event-orphans.view.ts`).
 *
 * The default export is the inline `defineObject({...})` call: the CLI's manifest builder
 * detects entities syntactically, and the const-then-default form is invisible to it.
 */

import {
  DOMAIN_EVENT_ACTOR_TYPE_OPTIONS,
  DOMAIN_EVENT_ENTITY_REF_SYSTEM_OPTIONS,
  DOMAIN_EVENT_ENTITY_TYPE_OPTIONS,
  DOMAIN_EVENT_EVENT_TYPE_OPTIONS,
} from "../../generated/options";
import { defineObject, FieldType, RelationType } from "twenty-sdk/define";
import { uid } from "../uid-map";

export default defineObject({
  universalIdentifier: uid("domainEvent"),
  nameSingular: "domainEvent",
  namePlural: "domainEvents",
  labelSingular: "Domain Event",
  labelPlural: "Domain Events",
  icon: "IconHistory",
  description:
    "The append-only event log. Never updated, never deleted (immutability policy).",
  fields: [
    {
      universalIdentifier: uid("domainEvent.eventId"),
      name: "eventId",
      type: FieldType.TEXT,
      label: "Event ID",
      description:
        "Producer idempotency key. Unique by convention; deduped in Snowflake.",
      isNullable: false,
      isUnique: true,
      defaultValue: "''",
    },
    {
      universalIdentifier: uid("domainEvent.eventType"),
      name: "eventType",
      type: FieldType.SELECT,
      label: "Event Type",
      description:
        "Catalog-derived `<subject>.<state>` registry. Adding a type is a catalog PR.",
      isNullable: false,
      // A NOT NULL SELECT needs a default it can backfill with; every write supplies its own
      // event type, so this value is a constraint artifact and never a meaningful state.
      defaultValue: "'referral.received'",
      options: DOMAIN_EVENT_EVENT_TYPE_OPTIONS,
    },
    {
      universalIdentifier: uid("domainEvent.entityType"),
      name: "entityType",
      type: FieldType.SELECT,
      label: "Entity Type",
      description: "Must agree with the noun in `eventType`.",
      options: DOMAIN_EVENT_ENTITY_TYPE_OPTIONS,
    },
    {
      universalIdentifier: uid("domainEvent.entityRefSystem"),
      name: "entityRefSystem",
      type: FieldType.SELECT,
      label: "Entity Ref System",
      description: "The identifier system `entityRefId` is expressed in.",
      options: DOMAIN_EVENT_ENTITY_REF_SYSTEM_OPTIONS,
    },
    {
      universalIdentifier: uid("domainEvent.entityRefId"),
      name: "entityRefId",
      type: FieldType.TEXT,
      label: "Entity Ref ID",
      description: "ID within `entityRefSystem`.",
    },
    {
      universalIdentifier: uid("domainEvent.programCode"),
      name: "programCode",
      type: FieldType.TEXT,
      label: "Program Code",
      description: "Envelope `program`; required for patient events.",
    },
    {
      universalIdentifier: uid("domainEvent.occurredAt"),
      name: "occurredAt",
      type: FieldType.DATE_TIME,
      label: "Occurred At",
      description: "Business time, set by the producer.",
    },
    {
      universalIdentifier: uid("domainEvent.producer"),
      name: "producer",
      type: FieldType.TEXT,
      label: "Producer",
      description:
        "Set by the write path from key identity, never producer-supplied.",
    },
    {
      universalIdentifier: uid("domainEvent.schemaVersion"),
      name: "schemaVersion",
      type: FieldType.NUMBER,
      label: "Schema Version",
    },
    {
      universalIdentifier: uid("domainEvent.ruleVersion"),
      name: "ruleVersion",
      type: FieldType.TEXT,
      label: "Rule Version",
      description: "The `catalog_version` in force when the event was written.",
    },
    {
      universalIdentifier: uid("domainEvent.correlationId"),
      name: "correlationId",
      type: FieldType.TEXT,
      label: "Correlation ID",
      description: "Journey ID across systems.",
    },
    {
      universalIdentifier: uid("domainEvent.causationId"),
      name: "causationId",
      type: FieldType.TEXT,
      label: "Causation ID",
      description: "The causing event or command.",
    },
    {
      universalIdentifier: uid("domainEvent.actorType"),
      name: "actorType",
      type: FieldType.SELECT,
      label: "Actor Type",
      options: DOMAIN_EVENT_ACTOR_TYPE_OPTIONS,
    },
    {
      universalIdentifier: uid("domainEvent.actorId"),
      name: "actorId",
      type: FieldType.TEXT,
      label: "Actor ID",
    },
    {
      universalIdentifier: uid("domainEvent.authority"),
      name: "authority",
      type: FieldType.TEXT,
      label: "Authority",
      description: "Approving human, where one is required.",
    },
    {
      universalIdentifier: uid("domainEvent.evidence"),
      name: "evidence",
      type: FieldType.RAW_JSON,
      label: "Evidence",
      description: "Source references; mandatory when `actorType` is `system`.",
    },
    {
      universalIdentifier: uid("domainEvent.payload"),
      name: "payload",
      type: FieldType.RAW_JSON,
      label: "Payload",
      description: "Unvalidated at MVP.",
    },
    {
      universalIdentifier: uid("domainEvent.patientProgram"),
      name: "patientProgram",
      type: FieldType.RELATION,
      label: "Patient Program",
      description:
        "Target for patient events; empty when the ref does not resolve (orphan view).",
      relationTargetObjectMetadataUniversalIdentifier: uid("patientProgram"),
      relationTargetFieldMetadataUniversalIdentifier: uid(
        "patientProgram.domainEvents",
      ),
      universalSettings: {
        relationType: RelationType.MANY_TO_ONE,
        joinColumnName: "patientProgramId",
      },
    },
    {
      universalIdentifier: uid("domainEvent.provider"),
      name: "provider",
      type: FieldType.RELATION,
      label: "Provider",
      relationTargetObjectMetadataUniversalIdentifier: uid("provider"),
      relationTargetFieldMetadataUniversalIdentifier: uid(
        "provider.domainEvents",
      ),
      universalSettings: {
        relationType: RelationType.MANY_TO_ONE,
        joinColumnName: "providerId",
      },
    },
    {
      universalIdentifier: uid("domainEvent.clinic"),
      name: "clinic",
      type: FieldType.RELATION,
      label: "Clinic",
      relationTargetObjectMetadataUniversalIdentifier: uid("clinic"),
      relationTargetFieldMetadataUniversalIdentifier: uid(
        "clinic.domainEvents",
      ),
      universalSettings: {
        relationType: RelationType.MANY_TO_ONE,
        joinColumnName: "clinicId",
      },
    },
  ],
});
