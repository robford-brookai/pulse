/**
 * Lifecycle board — enrollment state as columns, one card per patient x program.
 *
 * The board is the drag surface: moving a card is a `lifecycleStatus` write, which Twenty
 * delivers as a webhook the ledger turns into an event. That is why `canonicalPatientId` and
 * `programCode` are denormalized onto the object (see `packages/twenty-model/objects/patient-program.object.ts`) —
 * the delivery carries the flat entity, so the drag has to resolve to a patient and a program
 * without a read-back.
 *
 * The columns are derived, not written. `PATIENT_PROGRAM_LIFECYCLE_STATUS_OPTIONS` is generated
 * from the `enrollment` catalog subject and already carries a `position` per option, so a state
 * ratified into the catalog becomes a column on the next `task twenty:gen` with no edit here. The
 * one thing a hand-written column list would add is the chance of a `fieldValue` that is not a
 * catalog state, which is exactly the bug this derivation cannot have.
 *
 * The default export is the inline `defineView({...})` call: the CLI's manifest builder detects
 * entities syntactically, and the const-then-default form is invisible to it.
 */

import { PATIENT_PROGRAM_LIFECYCLE_STATUS_OPTIONS } from "../../generated/options";
import {
  defineView,
  ViewSortDirection,
  ViewType,
  type ViewGroupManifest,
} from "twenty-sdk/define";
import { uid } from "../uid-map";

/**
 * One column per option, in the generated order. `position` is re-derived from the index rather
 * than copied from the option: a view group's position orders columns on this board, while an
 * option's position orders the picklist — they agree today and are not the same number.
 *
 * `fieldValue` is `encodedValue`, not `value`: a view group matches the value the server *stores*,
 * and `twenty_deploy` re-encodes every option UPPER_SNAKE at the wire, so a column keyed `active`
 * against a stored `ACTIVE` is a column no card can ever enter. Demo3's assertion 3 found exactly
 * that on the live board. The UID key stays on `value` — it is a stable name, not a wire value,
 * and re-keying it would recreate every column.
 */
const lifecycleGroups = (): ViewGroupManifest[] =>
  PATIENT_PROGRAM_LIFECYCLE_STATUS_OPTIONS.map((option, index) => ({
    universalIdentifier: uid(
      `view.patient-program-lifecycle-board.group.${option.value}`,
    ),
    fieldValue: option.encodedValue,
    position: index,
    isVisible: true,
  }));

export default defineView({
  universalIdentifier: uid("view.patient-program-lifecycle-board"),
  name: "Lifecycle Board",
  icon: "IconLayoutKanban",
  objectUniversalIdentifier: uid("patientProgram"),
  type: ViewType.KANBAN,
  position: 1,
  mainGroupByFieldMetadataUniversalIdentifier: uid(
    "patientProgram.lifecycleStatus",
  ),
  // Every enrollment state stays a column even when it is empty: a board that hides `ended`
  // until something lands there reads as a board that has no such state.
  shouldHideEmptyGroups: false,
  groups: lifecycleGroups(),
  fields: [
    {
      universalIdentifier: uid(
        "view.patient-program-lifecycle-board.field.patient",
      ),
      fieldMetadataUniversalIdentifier: uid("patientProgram.patient"),
      position: 0,
      isVisible: true,
    },
    {
      universalIdentifier: uid(
        "view.patient-program-lifecycle-board.field.program",
      ),
      fieldMetadataUniversalIdentifier: uid("patientProgram.program"),
      position: 1,
      isVisible: true,
    },
    {
      universalIdentifier: uid(
        "view.patient-program-lifecycle-board.field.lifecycleStatus",
      ),
      fieldMetadataUniversalIdentifier: uid("patientProgram.lifecycleStatus"),
      position: 2,
      // The group-by field is the column itself; repeating it on the card is noise.
      isVisible: false,
    },
    {
      universalIdentifier: uid(
        "view.patient-program-lifecycle-board.field.lifecycleStatusAsOf",
      ),
      fieldMetadataUniversalIdentifier: uid(
        "patientProgram.lifecycleStatusAsOf",
      ),
      position: 3,
      isVisible: true,
    },
    {
      universalIdentifier: uid(
        "view.patient-program-lifecycle-board.field.qualificationStatus",
      ),
      fieldMetadataUniversalIdentifier: uid(
        "patientProgram.qualificationStatus",
      ),
      position: 4,
      isVisible: true,
    },
  ],
  filters: [],
  sorts: [
    {
      universalIdentifier: uid(
        "view.patient-program-lifecycle-board.sort.lifecycleStatusAsOf",
      ),
      fieldMetadataUniversalIdentifier: uid(
        "patientProgram.lifecycleStatusAsOf",
      ),
      direction: ViewSortDirection.DESC,
    },
  ],
});
