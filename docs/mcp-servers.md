# MCP Servers

Servers provided by this repo's `.mcp.json`.

## openlore

- **Command**: `openlore mcp` (stdio)
- **Purpose**: Exposes the `orient()` tool. Agents call `orient("<task description>")` before reading files to get relevant functions, call paths, insertion points, and matching spec sections.
- **Credentials**: None. Works from the local `.openlore/` index built by `openlore analyze` (BM25 fallback when no embeddings exist).
- **Prerequisite**: `npm install -g openlore`, then `openlore analyze` at least once in the repo.

## twenty

- **URL**: `https://twenty-dev.cloud.brook.ai/mcp` (streamable HTTP)
- **Purpose**: Twenty CRM data model — the dev-tenant Twenty instance.
- **Credentials**: `Authorization: Bearer ${TWENTY_MCP_TOKEN}` — set `TWENTY_MCP_TOKEN` in the environment; never a literal token in `.mcp.json`.
