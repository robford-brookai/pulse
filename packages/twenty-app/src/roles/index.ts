/**
 * The single-writer role set: producers create events, the app projects them, staff read the
 * results. Same three roles the artifact's `createRole` operations carry.
 */

import { APP_ROLE } from "./app.role";
import { PRODUCER_ROLE } from "./producer.role";
import { STAFF_ROLE } from "./staff.role";

export { APP_ROLE, PRODUCER_ROLE, STAFF_ROLE };

export const ALL_ROLES = [PRODUCER_ROLE, STAFF_ROLE, APP_ROLE] as const;
