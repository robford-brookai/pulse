/**
 * The sidebar entry for the lifecycle board.
 *
 * A view Twenty holds but the navigation never names is reachable only by URL. For the drag
 * surface that is the same as not existing, so the menu item is declared beside the board rather
 * than left to whoever provisions the workspace.
 *
 * It is a separate manifest entity (`navigationMenuItems`, alongside `views`), which is why it
 * carries its own identifier and points at the board's by UUID.
 */

import { defineNavigationMenuItem, NavigationMenuItemType } from "../define";
import { uid } from "../uid-map";
import { PATIENT_PROGRAM_LIFECYCLE_BOARD_UID } from "../views/patient-program-lifecycle-board.view";

export const PATIENT_PROGRAM_BOARD_NAV_ITEM = defineNavigationMenuItem({
  universalIdentifier: uid("view.patient-program-lifecycle-board.navigation"),
  type: NavigationMenuItemType.VIEW,
  name: "Lifecycle Board",
  icon: "IconLayoutKanban",
  position: 0,
  viewUniversalIdentifier: PATIENT_PROGRAM_LIFECYCLE_BOARD_UID,
});

export default PATIENT_PROGRAM_BOARD_NAV_ITEM;
