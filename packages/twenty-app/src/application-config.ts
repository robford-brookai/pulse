/**
 * The app's identity — and only its identity. The SDK derives the entity set from the file
 * tree: every `src/**` file whose default export is an inline `define*({...})` call becomes a
 * manifest entry, so this config carries no `objects`/`roles`/`views` arrays for a reviewer to
 * hold in sync with the files (task 6.4; the arrays it used to carry are deleted, not moved).
 *
 * The default role lives with the role itself: `src/roles/app-default.role.ts` is declared with
 * `defineApplicationRole`, the SDK's replacement for a config-level `defaultRole` name. Since
 * task 6.6 that is a placeholder granting nothing — the roles that grant anything are
 * artifact-owned and deliberately outside this app path (`packages/twenty-model/roles/`).
 *
 * `export default defineApplication({...})` inline, never const-then-default: the CLI's
 * manifest builder detects the config syntactically and the indirect form is invisible to it —
 * 7.2's first live publish failed exactly there.
 */

import { defineApplication } from "twenty-sdk/define";

export default defineApplication({
  // Minted 2026-08-17 (task 6.4). Application identity lives here rather than in uid-map.json
  // because `uid_map_diff` rejects any key the Python model never asks for; moving it into the
  // map is proposed in HANDOFF.md.
  universalIdentifier: "dc3c6b81-e257-4502-bea7-227f1ad366b3",
  displayName: "PULSE",
  description:
    "Patient unified ledger of state and events — the event log and the state it projects.",
});
