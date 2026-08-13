import { defineConfig } from "vitest/config";

// The unit suite runs no server and no network: the `CoreApiClient` the logic-function
// handler receives is faked, and that is the only fake on the TypeScript side
// (openspec/changes/pulse-app-scaffold/design.md, Decision 7). Live-server integration
// arrives in wave 3, marked and gated on the dev instance (DNA-909).
export default defineConfig({
  test: {
    // No globals: every spec imports `describe`/`it`/`expect` explicitly, so a spec reads
    // the same whether or not it is run through this config.
    include: ["tests/**/*.test.ts"],
  },
});
