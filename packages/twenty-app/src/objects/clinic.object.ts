/**
 * Clinic — registry anchor for a referring or participating clinic. Same v1 posture as
 * Provider: no catalog-backed dimension yet, so `lifecycleStatus` carries a model-fixed
 * vocabulary that the generator still owns.
 */

import { CLINIC_LIFECYCLE_STATUS_OPTIONS } from "../../generated/options";
import { defineObject, FieldType, RelationType } from "../define";
import { uid } from "../uid-map";

export const CLINIC = defineObject({
  universalIdentifier: uid("clinic"),
  nameSingular: "clinic",
  namePlural: "clinics",
  labelSingular: "Clinic",
  labelPlural: "Clinics",
  icon: "IconBuildingHospital",
  description:
    "Registry anchor for a referring or participating clinic. Carries no catalog-backed state at v1.",
  fields: [
    {
      universalIdentifier: uid("clinic.name"),
      name: "name",
      type: FieldType.TEXT,
      label: "Name",
    },
    {
      universalIdentifier: uid("clinic.sfdcId"),
      name: "sfdcId",
      type: FieldType.TEXT,
      label: "Salesforce ID",
      description: "External ID, system `sfdc`.",
    },
    {
      universalIdentifier: uid("clinic.lifecycleStatus"),
      name: "lifecycleStatus",
      type: FieldType.SELECT,
      label: "Lifecycle Status",
      description:
        "v1 literal vocabulary; extend with the catalog when it carries a clinic dimension.",
      options: CLINIC_LIFECYCLE_STATUS_OPTIONS,
    },
    {
      universalIdentifier: uid("clinic.lifecycleStatusAsOf"),
      name: "lifecycleStatusAsOf",
      type: FieldType.DATE_TIME,
      label: "Lifecycle Status As Of",
      description:
        "Last-writer-wins guard for lifecycleStatus: the `occurredAt` of the event that set it.",
    },
    {
      universalIdentifier: uid("clinic.domainEvents"),
      name: "domainEvents",
      type: FieldType.RELATION,
      label: "Domain Events",
      relation: {
        type: RelationType.ONE_TO_MANY,
        targetObject: "domainEvent",
        inverseField: "clinic",
      },
    },
  ],
});

export default CLINIC;
