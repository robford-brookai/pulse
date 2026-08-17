import { defineConfig } from "vitest/config";

// The live suite: the only TypeScript here that opens a socket. It is a separate config, not a
// flag on the unit one, so `task check` cannot reach it by accident — `vitest.config.ts` includes
// `tests/**` and nothing else, and a live suite that could be collected by the default runner
// would make CI depend on a credential and a server (docs/ci-lessons.md).
//
// One file, one worker, cases in declaration order: the five cases build on each other's state on
// a real server, so parallelism would have them racing for the same pair row.
export default defineConfig({
  test: {
    include: ["live/**/*.live.test.ts"],
    fileParallelism: false,
    sequence: { concurrent: false },
    // A live call crossing the network is slower than an in-memory fake by orders of magnitude;
    // each case sets its own timeout too, and this is the floor under the hooks.
    hookTimeout: 120_000,
    testTimeout: 60_000,
  },
});
