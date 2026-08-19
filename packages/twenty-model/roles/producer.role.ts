/**
 * Producer — the single MCP write path. Creates DomainEvent rows and nothing else.
 *
 * `canReadObjectRecords: false` is deliberate: a producer appends events and never queries the
 * log, so the write path holds no read capability over anyone's history.
 *
 * Twenty has no create-without-update permission — `canUpdateObjectRecords` covers both — so
 * the append-only guarantee this role used to state as `canCreate` without `canUpdate` is now
 * held by policy and the Snowflake mutation audit, not by the permission model (HANDOFF.md).
 *
 * The default export is the inline call: the CLI's manifest builder detects entities
 * syntactically, and the const-then-default form is invisible to it.
 */

import { defineRole } from "twenty-sdk/define";
import { uid } from "../../twenty-app/src/uid-map";

export default defineRole({
  // Minted 2026-08-17 (task 6.4); see staff.role.ts for why not uid-map.json.
  universalIdentifier: "55cfe51a-26e7-4c82-8f86-651e37856f99",
  label: "Event Producer",
  description:
    "The single MCP write path. Creates DomainEvent rows and nothing else.",
  canBeAssignedToUsers: false,
  canBeAssignedToAgents: false,
  canBeAssignedToApiKeys: true,
  objectPermissions: [
    {
      objectUniversalIdentifier: uid("domainEvent"),
      canReadObjectRecords: false,
      canUpdateObjectRecords: true,
      canSoftDeleteObjectRecords: false,
      canDestroyObjectRecords: false,
    },
  ],
  fieldPermissions: [],
});
