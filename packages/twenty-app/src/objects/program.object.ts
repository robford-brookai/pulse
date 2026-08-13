/** Program — a care program. Programs are configuration, not schema (I6). */

import { defineObject, FieldType, RelationType } from "../define";
import { uid } from "../uid-map";

export const PROGRAM = defineObject({
  universalIdentifier: uid("program"),
  nameSingular: "program",
  namePlural: "programs",
  labelSingular: "Program",
  labelPlural: "Programs",
  icon: "IconClipboardList",
  description: "A care program. Programs are configuration, not schema (I6).",
  fields: [
    {
      universalIdentifier: uid("program.code"),
      name: "code",
      type: FieldType.TEXT,
      label: "Code",
      description: "Stable program ID carried in the envelope `program` field.",
      isUnique: true,
    },
    {
      universalIdentifier: uid("program.name"),
      name: "name",
      type: FieldType.TEXT,
      label: "Name",
    },
    {
      universalIdentifier: uid("program.patientPrograms"),
      name: "patientPrograms",
      type: FieldType.RELATION,
      label: "Patient Programs",
      relation: {
        type: RelationType.ONE_TO_MANY,
        targetObject: "patientProgram",
        inverseField: "program",
      },
    },
  ],
});

export default PROGRAM;
