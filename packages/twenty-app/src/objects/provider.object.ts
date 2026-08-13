/**
 * Provider — registry anchor for a clinician. Carries no catalog-backed state at v1: the
 * catalog has no provider dimension, so `lifecycleStatus` is a model-fixed vocabulary the
 * generator still emits (`provider.lifecycleStatus` in `generated/options.ts`) rather than a
 * literal written here. Contract events stay lookup-miss no-ops until the catalog grows a
 * provider dimension.
 */

import { PROVIDER_LIFECYCLE_STATUS_OPTIONS } from "../../generated/options";
import { defineObject, FieldType, RelationType } from "../define";
import { uid } from "../uid-map";

export const PROVIDER = defineObject({
  universalIdentifier: uid("provider"),
  nameSingular: "provider",
  namePlural: "providers",
  labelSingular: "Provider",
  labelPlural: "Providers",
  icon: "IconStethoscope",
  description:
    "Registry anchor for a clinician. Carries no catalog-backed state at v1.",
  fields: [
    {
      universalIdentifier: uid("provider.name"),
      name: "name",
      type: FieldType.FULL_NAME,
      label: "Name",
    },
    {
      universalIdentifier: uid("provider.sfdcId"),
      name: "sfdcId",
      type: FieldType.TEXT,
      label: "Salesforce ID",
      description: "External ID, system `sfdc`.",
    },
    {
      universalIdentifier: uid("provider.npi"),
      name: "npi",
      type: FieldType.TEXT,
      label: "NPI",
      description: "External ID, system `npi`.",
    },
    {
      universalIdentifier: uid("provider.lifecycleStatus"),
      name: "lifecycleStatus",
      type: FieldType.SELECT,
      label: "Lifecycle Status",
      description:
        "v1 literal vocabulary; extend with the catalog when it carries a provider dimension.",
      options: PROVIDER_LIFECYCLE_STATUS_OPTIONS,
    },
    {
      universalIdentifier: uid("provider.lifecycleStatusAsOf"),
      name: "lifecycleStatusAsOf",
      type: FieldType.DATE_TIME,
      label: "Lifecycle Status As Of",
      description:
        "Last-writer-wins guard for lifecycleStatus: the `occurredAt` of the event that set it.",
    },
    {
      universalIdentifier: uid("provider.domainEvents"),
      name: "domainEvents",
      type: FieldType.RELATION,
      label: "Domain Events",
      relation: {
        type: RelationType.ONE_TO_MANY,
        targetObject: "domainEvent",
        inverseField: "provider",
      },
    },
  ],
});

export default PROVIDER;
