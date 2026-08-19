/**
 * The packaged app's default role — a placeholder that grants nothing.
 *
 * The SDK requires exactly one `defineApplicationRole` in an app: it is the role a
 * newly-provisioned member receives, and a manifest without one does not build. But the roles
 * this system actually uses (staff, producer, app) are applied by `task twenty:deploy` from
 * `artifact/operations.json`, which keys roles by label and mints no identifier a manifest could
 * reference — see `packages/twenty-model/roles/`. An app that also declared them would collide
 * with the artifact's, which is precisely what 7.2's live install proved wholesale (45
 * ENTITY_ALREADY_EXISTS: an app cannot adopt workspace-owned entities).
 *
 * So this role exists to satisfy the SDK and to grant nothing. Every permission list is empty,
 * and it is assignable to nobody: a member who somehow lands on it sees no object rather than
 * quietly gaining one. Granting real access is the artifact's job, and giving this role
 * permissions would put the model in two places at once.
 *
 * The default export is the inline call: the CLI's manifest builder detects entities
 * syntactically, and the const-then-default form is invisible to it.
 */

import { defineApplicationRole } from "twenty-sdk/define";

export default defineApplicationRole({
  // Minted 2026-08-17 (task 6.6), inline for the same reason the other role identifiers are:
  // `uid_map_diff` rejects any key the Python model never asks for, and the model has no notion
  // of an app-owned role. Moving the role family into the map is proposed in HANDOFF.md.
  universalIdentifier: "9c1f7d64-2f4e-4f5a-9b6a-0f4c2d8e7a11",
  label: "PULSE App Default",
  description:
    "Placeholder default role. Grants nothing — access is granted by the deployed artifact's roles.",
  canBeAssignedToUsers: false,
  canBeAssignedToAgents: false,
  canBeAssignedToApiKeys: false,
  objectPermissions: [],
  fieldPermissions: [],
});
