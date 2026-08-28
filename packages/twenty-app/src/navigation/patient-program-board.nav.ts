/**
 * The sidebar entry for the lifecycle board.
 *
 * A view Twenty holds but the navigation never names is reachable only by URL. For the drag
 * surface that is the same as not existing, so the menu item is declared beside the board rather
 * than left to whoever provisions the workspace.
 *
 * It is a separate manifest entity (`navigationMenuItems`, alongside `views`), which is why it
 * carries its own identifier and points at the board's by UUID.
 *
 * The default export is the inline call: the CLI's manifest builder detects entities
 * syntactically, and the const-then-default form is invisible to it.
 */

import {
  defineNavigationMenuItem,
  NavigationMenuItemType,
} from "twenty-sdk/define";
import { uid } from "../uid-map";

export default defineNavigationMenuItem({
  universalIdentifier: uid("view.patient-program-lifecycle-board.navigation"),
  type: NavigationMenuItemType.VIEW,
  name: "Lifecycle Board",
  icon: "IconLayoutKanban",
  position: 0,
  viewUniversalIdentifier: uid("view.patient-program-lifecycle-board"),
});
