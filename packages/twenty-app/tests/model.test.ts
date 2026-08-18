import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { FieldType } from "twenty-sdk/define";
import { describe, expect, it } from "vitest";

import {
  OPTIONS_BY_FIELD,
  PATIENT_PROGRAM_LIFECYCLE_STATUS_OPTIONS,
} from "../generated/options";
import APPLICATION from "../src/application-config";
import PROJECT_DOMAIN_EVENT from "../src/logic-functions/project-domain-event";
import PATIENT_PROGRAM_BOARD_NAV_ITEM from "../src/navigation/patient-program-board.nav";
import CLINIC from "../src/objects/clinic.object";
import DOMAIN_EVENT from "../src/objects/domain-event.object";
import PATIENT_PROGRAM from "../src/objects/patient-program.object";
import PATIENT from "../src/objects/patient.object";
import PROGRAM from "../src/objects/program.object";
import PROVIDER from "../src/objects/provider.object";
import APP_ROLE from "../src/roles/app.role";
import PRODUCER_ROLE from "../src/roles/producer.role";
import STAFF_ROLE from "../src/roles/staff.role";
import { UID_MAP } from "../src/uid-map";
import DOMAIN_EVENT_LOG_VIEW from "../src/views/domain-event-log.view";
import DOMAIN_EVENT_ORPHANS_VIEW from "../src/views/domain-event-orphans.view";
import PATIENT_PROGRAM_LIFECYCLE_BOARD_VIEW from "../src/views/patient-program-lifecycle-board.view";
import PATIENT_PROGRAM_STATUS_BOARD_VIEW from "../src/views/patient-program-status-board.view";

// Task 3.1's three assertions, in order: every hand-written UID resolves in the map, every
// SELECT field's options come from generated code rather than a literal in the file, and the
// whole model typechecks (`tsc --noEmit`, run by `task twenty:test` before this suite).
//
// Since task 6.4 the entities are real `twenty-sdk/define` results — `{ success, config,
// errors }` — so the suite walks `.config` and additionally pins what the SDK's validation
// says, plus the one syntactic property the CLI's manifest builder demands: every entity
// file's default export is the inline `define*({...})` call (the const-then-default form is
// invisible to it — 7.2's first live publish).

const packageRoot = fileURLToPath(new URL("..", import.meta.url));

// One list per entity kind, in the order the deleted `ALL_*` arrays carried (the model
// definition's order). The application config no longer names entities — the CLI derives them
// from the file tree — so these lists exist for the tests alone.
const OBJECT_RESULTS = [
  PATIENT,
  PROGRAM,
  PATIENT_PROGRAM,
  PROVIDER,
  CLINIC,
  DOMAIN_EVENT,
] as const;
const ROLE_RESULTS = [PRODUCER_ROLE, STAFF_ROLE, APP_ROLE] as const;
const VIEW_RESULTS = [
  PATIENT_PROGRAM_STATUS_BOARD_VIEW,
  PATIENT_PROGRAM_LIFECYCLE_BOARD_VIEW,
  DOMAIN_EVENT_LOG_VIEW,
  DOMAIN_EVENT_ORPHANS_VIEW,
] as const;

const ALL_OBJECTS = OBJECT_RESULTS.map((result) => result.config);
const ALL_ROLES = ROLE_RESULTS.map((result) => result.config);
const ALL_VIEWS = VIEW_RESULTS.map((result) => result.config);
const ALL_NAVIGATION_MENU_ITEMS = [PATIENT_PROGRAM_BOARD_NAV_ITEM.config];

// The identifiers task 6.4 minted outside uid-map.json: `uid_map_diff` rejects keys the Python
// model never asks for, so the application, role, and logic-function families carry inline
// literals until the map learns them (HANDOFF.md).
const MINTED_OUTSIDE_THE_MAP = [
  APPLICATION.config.universalIdentifier,
  ...ALL_ROLES.map((role) => role.universalIdentifier),
  PROJECT_DOMAIN_EVENT.config.universalIdentifier,
];

/** `<object>` / `<object>.<field>` / `<object>.<field>.<option>` for the hand-written model. */
const modelKeys = (): readonly string[] => {
  const keys: string[] = [];
  for (const object of ALL_OBJECTS) {
    keys.push(object.nameSingular);
    for (const field of object.fields) {
      const fieldKey = `${object.nameSingular}.${field.name}`;
      keys.push(fieldKey);
      if (field.type === FieldType.SELECT) {
        keys.push(
          ...(field.options ?? []).map(
            (option) => `${fieldKey}.${option.value}`,
          ),
        );
      }
    }
  }
  return keys.toSorted();
};

describe("the SDK accepts every definition", () => {
  it("returns success with no errors for every define* call", () => {
    // The `t.errors is not iterable` publish failure class: a definition the SDK's own
    // validation rejects would carry its refusal to the first live publish otherwise.
    for (const result of [
      APPLICATION,
      ...OBJECT_RESULTS,
      ...ROLE_RESULTS,
      ...VIEW_RESULTS,
      PATIENT_PROGRAM_BOARD_NAV_ITEM,
      PROJECT_DOMAIN_EVENT,
    ]) {
      expect(result.errors).toStrictEqual([]);
      expect(result.success).toBe(true);
    }
  });

  it("exports every entity as the inline define* call the CLI detects", () => {
    // Syntactic, because the CLI's detection is: `export default defineX({...})` inline is an
    // entity, a const re-exported as default is not. A file that drifts back builds an empty
    // manifest that publishes nothing.
    const entityFiles = [
      "src/application-config.ts",
      "src/logic-functions/project-domain-event.ts",
      "src/navigation/patient-program-board.nav.ts",
      "src/objects/clinic.object.ts",
      "src/objects/domain-event.object.ts",
      "src/objects/patient-program.object.ts",
      "src/objects/patient.object.ts",
      "src/objects/program.object.ts",
      "src/objects/provider.object.ts",
      "src/roles/app.role.ts",
      "src/roles/producer.role.ts",
      "src/roles/staff.role.ts",
      "src/views/domain-event-log.view.ts",
      "src/views/domain-event-orphans.view.ts",
      "src/views/patient-program-lifecycle-board.view.ts",
      "src/views/patient-program-status-board.view.ts",
    ];
    for (const source of entityFiles) {
      const text = readFileSync(`${packageRoot}${source}`, "utf8");
      expect(text, source).toMatch(/^export default define\w+\(\{$/m);
      expect(text, source).not.toMatch(/^export default [A-Z_]+;/m);
    }
  });

  it("declares the default role with defineApplicationRole, and only staff with it", () => {
    // The SDK's replacement for the deleted config-level `defaultRole` name: the role a
    // newly-provisioned member gets is the one declared with `defineApplicationRole`.
    for (const source of [
      "src/roles/staff.role.ts",
      "src/roles/producer.role.ts",
      "src/roles/app.role.ts",
    ]) {
      const text = readFileSync(`${packageRoot}${source}`, "utf8");
      const expected =
        source === "src/roles/staff.role.ts"
          ? /^export default defineApplicationRole\(\{$/m
          : /^export default defineRole\(\{$/m;
      expect(text, source).toMatch(expected);
    }
  });
});

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

  it("resolves every SELECT option's identifier in the map", () => {
    // The generated options carry the minted identifier twice: `universalIdentifier` for this
    // repo's artifact surface, and `id` — the SDK boundary's name for it — so the server never
    // derives an option identity. Both are checked; `id` is the one `ObjectConfig` can see.
    for (const object of ALL_OBJECTS) {
      for (const field of object.fields) {
        if (field.type !== FieldType.SELECT) continue;
        for (const option of field.options ?? []) {
          const key = `${object.nameSingular}.${field.name}.${option.value}`;
          expect(option.id, key).toBe(UID_MAP[key]);
        }
      }
    }
  });

  it("covers exactly the map's object surface — no missing key, no key the model never asks for", () => {
    // The map carries two families. This one is the object surface; the `view.` family is checked
    // below by identifier rather than by key, because a view file names its keys inside `uid()`
    // calls and re-listing them here would be the same strings typed twice.
    expect(modelKeys()).toStrictEqual(
      Object.keys(UID_MAP)
        .filter((key) => !key.startsWith("view."))
        .toSorted(),
    );
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

  it("keeps the five identifiers minted outside the map canonical, unique, and disjoint from it", () => {
    // The application, the three roles, and the logic function: entities the SDK requires an
    // identifier on, in families `uid_map_diff` would reject as orphans (HANDOFF.md proposes
    // the map learn them). Until then this is their collision check.
    const CANONICAL_UUID =
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
    const mapValues = new Set(Object.values(UID_MAP));
    for (const identifier of MINTED_OUTSIDE_THE_MAP) {
      expect(identifier).toMatch(CANONICAL_UUID);
      expect(mapValues.has(identifier), identifier).toBe(false);
    }
    expect(new Set(MINTED_OUTSIDE_THE_MAP).size).toBe(
      MINTED_OUTSIDE_THE_MAP.length,
    );
  });

  it("names a defined object and a mirrored inverse field on every relation", () => {
    const byUid = new Map(
      ALL_OBJECTS.map((object) => [object.universalIdentifier, object]),
    );
    const mirror = {
      MANY_TO_ONE: "ONE_TO_MANY",
      ONE_TO_MANY: "MANY_TO_ONE",
    } as const;

    for (const object of ALL_OBJECTS) {
      for (const field of object.fields) {
        if (field.type !== FieldType.RELATION) continue;
        const where = `${object.nameSingular}.${field.name}`;
        const target = byUid.get(
          field.relationTargetObjectMetadataUniversalIdentifier,
        );
        expect(target, `${where} targets a defined object`).toBeDefined();

        const inverse = target?.fields.find(
          (candidate) =>
            candidate.universalIdentifier ===
            field.relationTargetFieldMetadataUniversalIdentifier,
        );
        expect(inverse?.type, `${where} inverse`).toBe(FieldType.RELATION);
        if (inverse?.type !== FieldType.RELATION) continue;
        expect(
          inverse.relationTargetObjectMetadataUniversalIdentifier,
          `${where} inverse points back at the object`,
        ).toBe(object.universalIdentifier);
        expect(
          inverse.relationTargetFieldMetadataUniversalIdentifier,
          `${where} inverse points back at the field`,
        ).toBe(field.universalIdentifier);
        const relationType = field.universalSettings.relationType;
        expect(
          inverse.universalSettings.relationType,
          `${where} direction is mirrored`,
        ).toBe(mirror[relationType]);
      }
    }
  });
});

describe("SELECT options come from generated code", () => {
  it("uses the generated array itself for every SELECT field, not a copy of it", () => {
    for (const object of ALL_OBJECTS) {
      for (const field of object.fields) {
        if (field.type !== FieldType.SELECT) continue;
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
        if (field.type === FieldType.SELECT)
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
    // `application-config.ts` is exempt from the inline-UUID check alone: its identifier is one
    // of the five deliberately minted outside the map (checked above), not a drifted option UID.
    const sources = [
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
    expect(
      readFileSync(`${packageRoot}src/application-config.ts`, "utf8"),
    ).not.toMatch(/value:\s*["']/);
  });
});

describe("roles, views, and the application config", () => {
  it("grants producers write-without-read on DomainEvent and nothing else", () => {
    // Twenty has no create-without-update permission: `canUpdateObjectRecords` covers both, so
    // create-only-append is now policy plus the Snowflake mutation audit, not the permission
    // model. What the model can still say — one object, no read, no delete — it says here.
    expect(PRODUCER_ROLE.config.objectPermissions).toStrictEqual([
      {
        objectUniversalIdentifier: UID_MAP["domainEvent"],
        canReadObjectRecords: false,
        canUpdateObjectRecords: true,
        canSoftDeleteObjectRecords: false,
        canDestroyObjectRecords: false,
      },
    ]);
  });

  it("grants staff read-without-write on every status field and on DomainEvent", () => {
    const staff = STAFF_ROLE.config;

    const statusFields: [string, string][] = [];
    for (const object of ALL_OBJECTS) {
      for (const field of object.fields) {
        if (
          !field.name.startsWith("lifecycleStatus") &&
          !field.name.startsWith("qualificationStatus")
        )
          continue;
        statusFields.push([
          object.universalIdentifier,
          field.universalIdentifier,
        ]);
      }
    }
    expect(statusFields.length).toBeGreaterThan(0);

    for (const [objectUid, fieldUid] of statusFields) {
      const permission = staff.fieldPermissions?.find(
        (candidate) => candidate.fieldUniversalIdentifier === fieldUid,
      );
      expect(permission, fieldUid).toStrictEqual({
        objectUniversalIdentifier: objectUid,
        fieldUniversalIdentifier: fieldUid,
        canReadFieldValue: true,
        canUpdateFieldValue: false,
      });
    }

    const events = staff.objectPermissions?.find(
      (candidate) =>
        candidate.objectUniversalIdentifier === UID_MAP["domainEvent"],
    );
    expect(events).toStrictEqual({
      objectUniversalIdentifier: UID_MAP["domainEvent"],
      canReadObjectRecords: true,
      canUpdateObjectRecords: false,
      canSoftDeleteObjectRecords: false,
      canDestroyObjectRecords: false,
    });
  });

  it("never grants delete on any object in any role", () => {
    for (const role of ALL_ROLES) {
      expect(role.canSoftDeleteAllObjectRecords ?? false).toBe(false);
      expect(role.canDestroyAllObjectRecords ?? false).toBe(false);
      for (const permission of role.objectPermissions ?? []) {
        const where = `${role.label}: ${permission.objectUniversalIdentifier}`;
        expect(permission.canSoftDeleteObjectRecords ?? false, where).toBe(
          false,
        );
        expect(permission.canDestroyObjectRecords ?? false, where).toBe(false);
      }
    }
  });

  it("points every role permission at an object and field the model defines", () => {
    const objectUids = new Set(
      ALL_OBJECTS.map((object) => object.universalIdentifier),
    );
    for (const role of ALL_ROLES) {
      for (const permission of role.objectPermissions ?? []) {
        expect(
          objectUids.has(permission.objectUniversalIdentifier),
          `${role.label}: ${permission.objectUniversalIdentifier}`,
        ).toBe(true);
      }
      for (const permission of role.fieldPermissions ?? []) {
        const object = ALL_OBJECTS.find(
          (candidate) =>
            candidate.universalIdentifier ===
            permission.objectUniversalIdentifier,
        );
        expect(object, role.label).toBeDefined();
        expect(
          object?.fields.some(
            (field) =>
              field.universalIdentifier === permission.fieldUniversalIdentifier,
          ),
          `${role.label}: ${permission.fieldUniversalIdentifier}`,
        ).toBe(true);
      }
    }
  });

  it("points every view at an object, and every view part at a field on that object", () => {
    // Views address objects and fields by identifier, never by name (`ViewManifest`), so
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
  });

  it("uses exactly the map's view identifiers, and mints none of its own", () => {
    // The `view.` key family, checked by identifier rather than by key. Every identifier a view or
    // menu item carries has to be one the map minted, and every `view.` entry in the map has to be
    // used by something — an entry nobody uses is a UUID that will provision an orphan on deploy.
    // `fieldMetadataUniversalIdentifier` is deliberately excluded: those are object-field
    // identifiers, already covered by the object surface above.
    const used = new Set<string>();
    for (const view of ALL_VIEWS) {
      used.add(view.universalIdentifier);
      for (const part of [
        ...(view.fields ?? []),
        ...(view.filters ?? []),
        ...(view.sorts ?? []),
        ...(view.groups ?? []),
        ...(view.filterGroups ?? []),
        ...(view.fieldGroups ?? []),
      ]) {
        used.add(part.universalIdentifier);
      }
    }
    for (const item of ALL_NAVIGATION_MENU_ITEMS) {
      used.add(item.universalIdentifier);
    }

    const minted = Object.entries(UID_MAP)
      .filter(([key]) => key.startsWith("view."))
      .map(([, value]) => value);
    expect([...used].toSorted()).toStrictEqual(minted.toSorted());
  });

  it("gives the lifecycle board one column per enrollment state, in catalog order", () => {
    // The columns are derived from the generated options, so this asserts the derivation rather
    // than a hand-written list: a state ratified into the catalog is a column with no edit to the
    // view file, and a `fieldValue` that is not a catalog state cannot occur.
    const board = PATIENT_PROGRAM_LIFECYCLE_BOARD_VIEW.config;
    expect(board.groups?.map((group) => group.fieldValue)).toStrictEqual(
      PATIENT_PROGRAM_LIFECYCLE_STATUS_OPTIONS.map((option) => option.value),
    );
    expect(board.mainGroupByFieldMetadataUniversalIdentifier).toBe(
      UID_MAP["patientProgram.lifecycleStatus"],
    );
  });

  it("names the board in the sidebar, or the drag surface is URL-only", () => {
    const item = ALL_NAVIGATION_MENU_ITEMS.find(
      (candidate) =>
        candidate.viewUniversalIdentifier ===
        PATIENT_PROGRAM_LIFECYCLE_BOARD_VIEW.config.universalIdentifier,
    );
    expect(item?.type).toBe("VIEW");
  });

  it("carries the two denormalized columns a webhook delivery needs", () => {
    // A Twenty webhook carries `properties.after` — the flat entity — so a relation arrives as an
    // id, not a nested object. Without these two the ledger cannot resolve a board drag to a
    // patient and a program without reading the record back.
    const names = PATIENT_PROGRAM.config.fields.map((field) => field.name);
    expect(names).toContain("canonicalPatientId");
    expect(names).toContain("programCode");
  });

  it("carries an identity-only application config", () => {
    // The entity set is the file tree's, so the config states identity and nothing else — an
    // `objects`/`roles`/`views` member reappearing here would be a second copy of the model.
    expect(APPLICATION.config).toMatchObject({
      displayName: "PULSE",
      description:
        "Patient unified ledger of state and events — the event log and the state it projects.",
    });
    // The SDK normalizes identity-adjacent fields (`galleryImages`, `logo`) onto the config;
    // what must never reappear is a second copy of the entity set.
    for (const member of [
      "objects",
      "roles",
      "views",
      "navigationMenuItems",
      "logicFunctions",
      "defaultRole",
    ]) {
      expect(APPLICATION.config, member).not.toHaveProperty(member);
    }
  });
});
