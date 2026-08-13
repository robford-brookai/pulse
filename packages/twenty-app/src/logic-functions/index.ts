/**
 * The app's logic functions. One today — the projection — and the design says so: the
 * projection is the platform's only real logic inside Twenty, and rules that are not projection
 * belong to the clinic rules engine, outside this app.
 */

import { PROJECT_DOMAIN_EVENT } from "./project-domain-event";

export { PROJECT_DOMAIN_EVENT };

export const ALL_LOGIC_FUNCTIONS = [PROJECT_DOMAIN_EVENT] as const;
