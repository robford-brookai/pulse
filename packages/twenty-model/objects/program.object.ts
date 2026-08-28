/**
 * Program — a care program. Programs are configuration, not schema (I6).
 *
 * The default export is the inline `defineObject({...})` call: the CLI's manifest builder
 * detects entities syntactically, and the const-then-default form is invisible to it.
 */

import { defineObject, FieldType, RelationType } from "twenty-sdk/define";
import { uid } from "../../twenty-app/src/uid-map";

export default defineObject({
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
      universalIdentifier: uid("program.patientPrograms"),
      name: "patientPrograms",
      type: FieldType.RELATION,
      label: "Patient Programs",
      relationTargetObjectMetadataUniversalIdentifier: uid("patientProgram"),
      relationTargetFieldMetadataUniversalIdentifier: uid(
        "patientProgram.program",
      ),
      universalSettings: { relationType: RelationType.ONE_TO_MANY },
    },
  ],
});
