import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

// The placeholder suite for task 1.1: it proves the runner collects and passes, and it
// asserts the two things the TypeScript side reads from disk rather than from imports —
// the UID map (minted in task 2.1) and the generated/ directory the catalog generator
// writes options.ts and projection-lookup.ts into (task 2.2). Object files replace this
// with real coverage as they land; the checks here are the ones that stay meaningful
// until then.

const packageRoot = fileURLToPath(new URL("..", import.meta.url));

describe("twenty-app scaffold", () => {
  it("carries a UID map that parses as a flat object keyed by stable name", () => {
    const uidMap: unknown = JSON.parse(
      readFileSync(`${packageRoot}uid-map.json`, "utf8"),
    );

    expect(uidMap).toBeTypeOf("object");
    expect(Array.isArray(uidMap)).toBe(false);
    expect(uidMap).not.toBeNull();
    for (const key of Object.keys(uidMap as Record<string, unknown>)) {
      // `<object>` / `<object>.<field>` / `<object>.<field>.<option>` — camelCase segments.
      expect(key).toMatch(/^[a-z][A-Za-z0-9]*(\.[a-z][A-Za-z0-9_]*){0,2}$/);
    }
  });

  it("resolves the generated/ directory the catalog generator emits into", () => {
    expect(() =>
      readFileSync(`${packageRoot}generated/.gitkeep`, "utf8"),
    ).not.toThrow();
  });
});
