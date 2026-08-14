/**
 * The app's identity and its default role — the root the object, role, and view definitions
 * hang off (`design/platform/pulse-app-scaffold.md`, repo layout).
 *
 * `staff` is the default role because it is the least-capable one a human can be given: it
 * reads everything and writes only entity records, never a status field and never the event
 * log. `producer` and `app` are machine identities, granted deliberately to a key, never
 * inherited by a person on provisioning.
 *
 * The application carries no `universalIdentifier`: the UID map holds exactly the surface the
 * artifact serializes, and the operation set has no application-level operation to key. Views
 * are the opposite case — Twenty requires an identifier on them, so they declare one and the
 * map has yet to learn the keys (`src/views/index.ts`).
 */

import { defineApplication } from "./define";
import { ALL_LOGIC_FUNCTIONS } from "./logic-functions";
import { ALL_NAVIGATION_MENU_ITEMS } from "./navigation";
import { ALL_OBJECTS } from "./objects";
import { ALL_ROLES, STAFF_ROLE } from "./roles";
import { ALL_VIEWS } from "./views";

export const APPLICATION = defineApplication({
  name: "pulse",
  label: "PULSE",
  description:
    "Patient unified ledger of state and events — the event log and the state it projects.",
  defaultRole: STAFF_ROLE.name,
  objects: ALL_OBJECTS,
  roles: ALL_ROLES,
  views: ALL_VIEWS,
  navigationMenuItems: ALL_NAVIGATION_MENU_ITEMS,
  logicFunctions: ALL_LOGIC_FUNCTIONS,
});

export default APPLICATION;
