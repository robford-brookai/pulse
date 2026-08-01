# MCP Servers

Servers provided by this repo's `.mcp.json`.

## openlore

- **Command**: `openlore mcp` (stdio)
- **Purpose**: Exposes the `orient()` tool. Agents call `orient("<task description>")` before reading files to get relevant functions, call paths, insertion points, and matching spec sections.
- **Credentials**: None. Works from the local `.openlore/` index built by `openlore analyze` (BM25 fallback when no embeddings exist).
- **Prerequisite**: `npm install -g openlore`, then `openlore analyze` at least once in the repo.
