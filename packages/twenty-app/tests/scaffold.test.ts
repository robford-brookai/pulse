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
    // Two key families, each with its own grammar. The object family is
    // `<object>` / `<object>.<field>` / `<object>.<field>.<option>` in camelCase, except that an
    // option *value* may itself contain a dot: an event-type option is `<subject>.<state>`, so
    // `domainEvent.eventType.referral.received` is a well-formed three-part key with four
    // segments. The view family is `view.<slug>` in kebab-case, optionally followed by
    // `navigation` or by a `<part>.<name>` pair. Keys are composed and looked up whole in both.
    const VIEW_KEY =
      /^view\.[a-z][a-z0-9-]*(\.navigation|\.(field|filter|sort)\.[a-z][A-Za-z0-9]*|\.group\.[a-z][a-z0-9_]*)?$/;

    for (const key of Object.keys(uidMap as Record<string, unknown>)) {
      if (key.startsWith("view.")) {
        expect(key).toMatch(VIEW_KEY);
        continue;
      }
      const [object, field, ...option] = key.split(".");
      expect(object).toMatch(/^[a-z][A-Za-z0-9]*$/);
      if (field !== undefined) {
        expect(field).toMatch(/^[a-z][A-Za-z0-9_]*$/);
      }
      expect(option.length).toBeLessThanOrEqual(2);
      for (const segment of option) {
        expect(segment).toMatch(/^[a-z][A-Za-z0-9_]*$/);
      }
    }
  });

  it("resolves the generated/ directory the catalog generator emits into", () => {
    expect(() =>
      readFileSync(`${packageRoot}generated/.gitkeep`, "utf8"),
    ).not.toThrow();
  });
});
