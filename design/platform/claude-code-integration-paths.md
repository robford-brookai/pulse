# Claude Code Integration Paths — PULSE (Patient Unified Ledger of State & Events)

| | |
|---|---|
| **Status** | Proposed (revised 2026-07-28 for Twenty v2.0 Apps framework) |
| **Date** | 2026-07-28 |
| **Owner** | Rob Ford, Data |
| **Related** | pulse-app-scaffold.md; event-state-platform-solution.md; twenty-licensing-structure-check.md |

## Purpose

Define how Claude Code (CC) builds, operates, and extends the Twenty-based platform. Three paths, ascending setup effort. All respect the never-patch-core rule from the licensing check.

## Path 1 — Twenty Apps framework (recommended)

*Supersedes the metadata-API-script approach previously recommended here. Twenty v2.0's Apps framework is the first-party version of the same idea, and strictly better.*

The platform's data model and projection logic live in **`pulse-app`**, a TypeScript repo scaffolded with `npx create-twenty-app`. Objects, fields, relations, roles, views, and server-side logic functions are declared with `defineObject` / `defineField` / `defineRole` / `defineLogicFunction`, compiled to a manifest, and synced into a **stock, unmodified** Twenty server. Full spec: pulse-app-scaffold.md.

- **Never clone `twentyhq/twenty`** — that is the contributor/fork path and violates the never-patch-core rule.
- CC drives `pulse-app` as an ordinary TypeScript repo: `yarn twenty dev` (live sync), `dev:add` (scaffold), `dev:function:exec` / `dev:function:logs` (run and debug), `dev:typecheck`, Vitest against a real dev server.
- Promotion via remotes: `remote:add --url ... --api-key ...` (CI-friendly), then `dev:build` + `app:publish`. Same manifest installs dev → staging → prod.

### What this buys over raw metadata-API scripts

1. Build-time validation and IDE types instead of untyped JSON payloads.
2. `universalIdentifier`s make entities stable across environments and redeploys.
3. Schema changes carry migration semantics (`isNullable`, `defaultValue` backfill) applied on sync.
4. The projection becomes tested TypeScript (`defineLogicFunction` on `domainEvent.created`), not UI-configured workflow steps.
5. Permissions (`defineRole`) ship as reviewable config — the single-writer rule stops being admin clicks.

### Direct API — still used, narrower role

REST/GraphQL remain the runtime interfaces: producers submit events through them (via the MCP write path, C3), the clinic-rules emitter POSTs through them, and ad-hoc verification queries use them. `yarn twenty dev:generate-client` produces a typed `twenty-client-sdk` for *any* repo — use it in the signal adapter and MCP write path rather than hand-rolling schema knowledge.

## Path 2 — MCP (community-maintained, optional)

No first-party Twenty MCP server exists (as of 2026-07). Community options:

| Server | Notes |
|---|---|
| [mhenry3164/twenty-crm-mcp-server](https://github.com/mhenry3164/twenty-crm-mcp-server) | Most established. Node 18+, API-key auth, dynamic schema discovery incl. custom fields. Updated 2026-03. |
| [jezweb/twenty-mcp](https://github.com/jezweb/twenty-mcp) | Alternative implementation. |
| [OleApp-de/TwentyMCP](https://mcpservers.org/servers/OleApp-de/TwentyMCP) | Alternative implementation. |

Install: `claude mcp add` with instance URL + API key.

Note the distinction from the program's **MCP write path** (control C3): that is Brook's own service, the single attributable channel for programmatic writes. The community servers below are developer convenience for interactive exploration — not the production write path.

### PHI requirements (mandatory before production use)

1. stdio/local execution only — no hosted MCP relays for patient data.
2. Pin the version; review source before deployment (small codebases, ~1 hr audit). Governed by program control C5: pinned audited commit + dependency scanning on deploy and update.
3. Verify custom-object coverage — directory listings emphasize people/companies/tasks/notes; confirm the DomainEvent custom object is reachable.

## Path 3 — Skill/plugin (encode conventions)

Wrap paths 1–2 in a `brook-twenty` skill capturing: envelope spec, event-type registry, projection rules, `pulse-app` conventions (universalIdentifier discipline, codegen boundaries, test cases). Result: any CC session — interactive or headless — operates the platform consistently instead of rediscovering the contract.

Fits the existing work-order pattern: Linear work order → headless CC + `brook-twenty` skill → `pulse-app` PR → CI sync.

## Recommended sequence

1. **Build** with Path 1: `pulse-app` repo, CC executes and verifies against a local dev server.
2. **Stabilize** conventions through the pilot (signal adapter, `patient.enrolled` end-to-end).
3. **Encode** as the `brook-twenty` skill once conventions stop moving.
4. **MCP** only as interactive-exploration convenience; never a build dependency.

No official Twenty CLI for administration exists beyond `yarn twenty`; Path 1 makes one unnecessary.

## Sources

- [Twenty Apps — Concepts](https://docs.twenty.com/developers/extend/apps/getting-started/concepts)
- [defineObject](https://docs.twenty.com/developers/extend/apps/data/objects)
- [Logic Functions](https://docs.twenty.com/developers/extend/apps/logic/logic-functions)
- [Twenty Apps CLI](https://docs.twenty.com/developers/extend/apps/operations/cli)
- [PulseMCP — Twenty CRM MCP server](https://www.pulsemcp.com/servers/twenty-crm)
- [mhenry3164/twenty-crm-mcp-server (GitHub)](https://github.com/mhenry3164/twenty-crm-mcp-server)
- [jezweb/twenty-mcp (GitHub)](https://github.com/jezweb/twenty-mcp)
