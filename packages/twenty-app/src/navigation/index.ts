/**
 * Sidebar entries. One per view that ops is expected to reach by name rather than by URL.
 *
 * `navigationMenuItems` is its own manifest collection alongside `views`, so the items hang off
 * the application config the same way the views do.
 */

import type { NavigationMenuItemDefinition } from "../define";
import { PATIENT_PROGRAM_BOARD_NAV_ITEM } from "./patient-program-board.nav";

export { PATIENT_PROGRAM_BOARD_NAV_ITEM };

export const ALL_NAVIGATION_MENU_ITEMS: readonly NavigationMenuItemDefinition[] =
  [PATIENT_PROGRAM_BOARD_NAV_ITEM];
