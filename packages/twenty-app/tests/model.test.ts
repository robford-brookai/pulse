import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { OPTIONS_BY_FIELD } from "../generated/options";
import { APPLICATION } from "../src/application-config";
import { ALL_OBJECTS } from "../src/objects";
import { ALL_ROLES } from "../src/roles";
import { UID_MAP } from "../src/uid-map";
import { ALL_VIEWS } from "../src/views";

// Task 3.1's three assertions, in order: every hand-written UID resolves in the map, every
// SELECT field's options come from generated code rather than a literal in the file, and the
// whole model typechecks (`tsc --noEmit`, run by `task twenty:test` before this suite).
//
// The first one is stronger than "resolves": the object files and the UID map are checked to
// cover *the same* surface in both directions. The map is already pinned to the Python model
// plus the catalog (`uid_map_diff`, task 2.1), so equality here is what makes the TypeScript
// model and the artifact one model rather than two that happen to agree today.

const packageRoot = fileURLToPath(new URL("..", import.meta.url));

/** `<object>` / `<object>.<field>` / `<object>.<field>.<option>` for the hand-written model. */
const modelKeys = (): readonly string[] => {
  const keys: string[] = [];
  for (const object of ALL_OBJECTS) {
    keys.push(object.nameSingular);
    for (const field of object.fields) {
      const fieldKey = `${object.nameSingular}.${field.name}`;
      keys.push(fieldKey);
      if (field.type === "SELECT") {
        keys.push(
          ...field.options.map((option) => `${fieldKey}.${option.value}`),
        );
      }
    }
  }
  return keys.toSorted();
};

describe("object files against the UID map", () => {
  it("gives every object the universalIdentifier the map holds for it", () => {
    for (const object of ALL_OBJECTS) {
      expect(object.universalIdentifier, object.nameSingular).toBe(
        UID_MAP[object.nameSingular],
      );
    }
  });

  it("gives every field the universalIdentifier the map holds for it", () => {
    for (const object of ALL_OBJECTS) {
      for (const field of object.fields) {
        const key = `${object.nameSingular}.${field.name}`;
        expect(field.universalIdentifier, key).toBe(UID_MAP[key]);
      }
    }
  });

  it("resolves every SELECT option's universalIdentifier in the map", () => {
    for (const object of ALL_OBJECTS) {
      for (const field of object.fields) {
        if (field.type !== "SELECT") continue;
        for (const option of field.options) {
          const key = `${object.nameSingular}.${field.name}.${option.value}`;
          expect(option.universalIdentifier, key).toBe(UID_MAP[key]);
        }
      }
    }
  });

  it("covers exactly the map's surface — no missing key, no key the model never asks for", () => {
    expect(modelKeys()).toStrictEqual(Object.keys(UID_MAP).toSorted());
  });

  it("mints no identifier of its own: every UID in the model is a value in the map", () => {
    const minted = new Set(Object.values(UID_MAP));
    for (const object of ALL_OBJECTS) {
      expect(minted.has(object.universalIdentifier), object.nameSingular).toBe(
        true,
      );
      for (const field of object.fields) {
        expect(minted.has(field.universalIdentifier), field.name).toBe(true);
      }
    }
  });

  it("names a defined object and a mirrored inverse field on every relation", () => {
    const byName = new Map(
      ALL_OBJECTS.map((object) => [object.nameSingular, object]),
    );
    const mirror = {
      MANY_TO_ONE: "ONE_TO_MANY",
      ONE_TO_MANY: "MANY_TO_ONE",
    } as const;

    for (const object of ALL_OBJECTS) {
      for (const field of object.fields) {
        if (field.type !== "RELATION") continue;
        const where = `${object.nameSingular}.${field.name}`;
        const target = byName.get(field.relation.targetObject);
        expect(
          target,
          `${where} targets ${field.relation.targetObject}`,
        ).toBeDefined();

        const inverse = target?.fields.find(
          (candidate) => candidate.name === field.relation.inverseField,
        );
        expect(inverse?.type, `${where} inverse`).toBe("RELATION");
        if (inverse?.type !== "RELATION") continue;
        expect(inverse.relation, `${where} is mirrored`).toStrictEqual({
          type: mirror[field.relation.type],
          targetObject: object.nameSingular,
          inverseField: field.name,
        });
      }
    }
  });
});

describe("SELECT options come from generated code", () => {
  it("uses the generated array itself for every SELECT field, not a copy of it", () => {
    for (const object of ALL_OBJECTS) {
      for (const field of object.fields) {
        if (field.type !== "SELECT") continue;
        const key = `${object.nameSingular}.${field.name}`;
        // `toBe`, not `toStrictEqual`: an equal-but-separate array is a literal that happens to
        // match today, which is the thing this test exists to keep out of the source.
        expect(field.options, key).toBe(OPTIONS_BY_FIELD[key]);
      }
    }
  });

  it("declares a SELECT field for every generated option set and no other", () => {
    const selectKeys: string[] = [];
    for (const object of ALL_OBJECTS) {
      for (const field of object.fields) {
        if (field.type === "SELECT")
          selectKeys.push(`${object.nameSingular}.${field.name}`);
      }
    }
    expect(selectKeys.toSorted()).toStrictEqual(
      Object.keys(OPTIONS_BY_FIELD).toSorted(),
    );
  });

  it("writes no option literal into a hand-written source file", () => {
    // Read as text: an inline `{ value: "...", label: "..." }` is the exact shape that would
    // pass the identity check above only by being wired somewhere else, so the file itself is
    // the thing under test. `generated/` is excluded — literals are its whole job.
    const sources = [
      "src/application-config.ts",
      "src/define.ts",
      "src/uid-map.ts",
      ...ALL_OBJECTS.map(
        (object) =>
          `src/objects/${object.nameSingular.replace(/([A-Z])/g, "-$1").toLowerCase()}.object.ts`,
      ),
    ];

    for (const source of sources) {
      const text = readFileSync(`${packageRoot}${source}`, "utf8");
      expect(text, source).not.toMatch(/value:\s*["']/);
      expect(text, source).not.toMatch(
        /universalIdentifier:\s*["'][0-9a-f]{8}-/,
      );
    }
  });
});

describe("roles, views, and the application config", () => {
  it("grants producers create-only on DomainEvent and nothing else", () => {
    const producer = ALL_ROLES.find((role) => role.name === "producer");
    expect(producer?.objectPermissions).toStrictEqual([
      {
        objectNameSingular: "domainEvent",
        canRead: false,
        canCreate: true,
        canUpdate: false,
        canDelete: false,
      },
    ]);
  });

  it("grants staff read-without-write on every status field and on DomainEvent", () => {
    const staff = ALL_ROLES.find((role) => role.name === "staff");
    expect(staff).toBeDefined();

    const statusFields: string[] = [];
    for (const object of ALL_OBJECTS) {
      for (const field of object.fields) {
        if (
          !field.name.startsWith("lifecycleStatus") &&
          !field.name.startsWith("qualificationStatus")
        )
          continue;
        statusFields.push(`${object.nameSingular}.${field.name}`);
      }
    }

    for (const key of statusFields) {
      const permission = staff?.fieldPermissions.find(
        (candidate) =>
          `${candidate.objectNameSingular}.${candidate.fieldName}` === key,
      );
      expect(permission, key).toStrictEqual({
        objectNameSingular: key.split(".")[0],
        fieldName: key.split(".")[1],
        canRead: true,
        canUpdate: false,
      });
    }

    const events = staff?.objectPermissions.find(
      (candidate) => candidate.objectNameSingular === "domainEvent",
    );
    expect(events).toStrictEqual({
      objectNameSingular: "domainEvent",
      canRead: true,
      canCreate: false,
      canUpdate: false,
      canDelete: false,
    });
  });

  it("never grants delete on any object in any role", () => {
    for (const role of ALL_ROLES) {
      for (const permission of role.objectPermissions) {
        expect(
          permission.canDelete,
          `${role.name}.${permission.objectNameSingular}`,
        ).toBe(false);
      }
    }
  });

  it("points every view at an object, and every view part at a field on that object", () => {
    // Views address objects and fields by identifier, never by name (`ViewManifestType`), so
    // this walks UUIDs: a view's `objectUniversalIdentifier` has to be an object the model
    // defines, and every field, filter, sort, and kanban group-by has to name a field on that
    // same object. Name-based checking would not have caught a UID pointed at the wrong object.
    const objectByUid = new Map(
      ALL_OBJECTS.map((object) => [object.universalIdentifier, object]),
    );

    for (const view of ALL_VIEWS) {
      const object = objectByUid.get(view.objectUniversalIdentifier);
      expect(object, view.name).toBeDefined();
      if (object === undefined) continue;

      const fieldUids = new Set(
        object.fields.map((field) => field.universalIdentifier),
      );
      const referenced = [
        ...(view.fields ?? []).map(
          (field) => field.fieldMetadataUniversalIdentifier,
        ),
        ...(view.filters ?? []).map(
          (filter) => filter.fieldMetadataUniversalIdentifier,
        ),
        ...(view.sorts ?? []).map(
          (sort) => sort.fieldMetadataUniversalIdentifier,
        ),
        ...(view.mainGroupByFieldMetadataUniversalIdentifier === undefined
          ? []
          : [view.mainGroupByFieldMetadataUniversalIdentifier]),
      ];
      for (const fieldUid of referenced) {
        expect(fieldUids.has(fieldUid), `${view.name}: ${fieldUid}`).toBe(true);
      }
    }

    const names = new Set(ALL_OBJECTS.map((object) => object.nameSingular));
    for (const role of ALL_ROLES) {
      for (const permission of [
        ...role.objectPermissions,
        ...role.fieldPermissions,
      ]) {
        expect(
          names.has(permission.objectNameSingular),
          `${role.name}: ${permission.objectNameSingular}`,
        ).toBe(true);
      }
    }
  });

  it("carries an application config whose default role is a defined role", () => {
    expect(ALL_ROLES.map((role) => role.name)).toContain(
      APPLICATION.defaultRole,
    );
    expect(APPLICATION.objects).toBe(ALL_OBJECTS);
    expect(APPLICATION.roles).toBe(ALL_ROLES);
    expect(APPLICATION.views).toBe(ALL_VIEWS);
  });
});
