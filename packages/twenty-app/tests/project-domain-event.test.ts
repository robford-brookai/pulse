import { describe, expect, it } from "vitest";

import {
  DOMAIN_EVENT_ENTITY_REF_SYSTEM_OPTIONS,
  DOMAIN_EVENT_ENTITY_TYPE_OPTIONS,
} from "../generated/options";
import { PROJECTION_LOOKUP } from "../generated/projection-lookup";
import {
  foreignKey,
  type CoreApiClient,
  type CoreFields,
  type CoreFilter,
  type CoreRecord,
} from "../src/logic-functions/core-api";
import PROJECT_DOMAIN_EVENT, {
  ENTITY_CROSSWALK,
  handler,
  RELATION_FIELD,
  type DomainEventRecord,
} from "../src/logic-functions/project-domain-event";
import CLINIC_OBJECT from "../../twenty-model/objects/clinic.object";
import DOMAIN_EVENT_OBJECT from "../../twenty-model/objects/domain-event.object";
import PATIENT_PROGRAM_OBJECT from "../../twenty-model/objects/patient-program.object";
import PATIENT_OBJECT from "../../twenty-model/objects/patient.object";
import PROGRAM_OBJECT from "../../twenty-model/objects/program.object";
import PROVIDER_OBJECT from "../../twenty-model/objects/provider.object";

// The `ALL_*` arrays are deleted (task 6.4: the CLI derives entities from the file tree), so
// the structural checks below walk the define* results' `.config` directly.
const ALL_OBJECTS = [
  PATIENT_OBJECT,
  PROGRAM_OBJECT,
  PATIENT_PROGRAM_OBJECT,
  PROVIDER_OBJECT,
  CLINIC_OBJECT,
  DOMAIN_EVENT_OBJECT,
].map((result) => result.config);

// Task 3.2's five spec cases, plus the two structural checks that keep the hand-written
// crosswalk from drifting off the model and the catalog.
//
// The `CoreApiClient` is the only fake on the TypeScript side (design Decision 7): no server,
// no network, no clock. Every fixture value is synthetic — ids are literal strings chosen to be
// obviously fake, and no fixture carries a name, a date of birth, or anything else that would
// be PHI if it were real.

interface FakeCall {
  readonly op: "findOne" | "create" | "update";
  readonly objectNameSingular: string;
  readonly recordId?: string;
  readonly payload: Readonly<Record<string, unknown>>;
}

interface FakeClient extends CoreApiClient {
  readonly calls: readonly FakeCall[];
  rows(objectNameSingular: string): readonly CoreRecord[];
  row(objectNameSingular: string, recordId: string): CoreRecord;
  writes(objectNameSingular: string): readonly FakeCall[];
}

/**
 * An in-memory Core API. `findOne` matches every filter entry by string equality, which is what
 * the real filter does for the crosswalk fields and foreign keys the handler filters on.
 */
const fakeClient = (
  seed: Readonly<Record<string, readonly CoreRecord[]>>,
): FakeClient => {
  const store = new Map<string, CoreRecord[]>(
    Object.entries(seed).map(([name, records]) => [name, [...records]]),
  );
  const calls: FakeCall[] = [];
  let minted = 0;

  const table = (objectNameSingular: string): CoreRecord[] => {
    const existing = store.get(objectNameSingular);
    if (existing !== undefined) return existing;
    const created: CoreRecord[] = [];
    store.set(objectNameSingular, created);
    return created;
  };

  return {
    calls,
    rows: (objectNameSingular) => [...table(objectNameSingular)],
    row: (objectNameSingular, recordId) => {
      const found = table(objectNameSingular).find(
        (candidate) => candidate.id === recordId,
      );
      if (found === undefined) {
        throw new Error(`no ${objectNameSingular} with id ${recordId}`);
      }
      return found;
    },
    writes: (objectNameSingular) =>
      calls.filter(
        (call) =>
          call.op !== "findOne" &&
          call.objectNameSingular === objectNameSingular,
      ),

    findOne: (objectNameSingular: string, filter: CoreFilter) => {
      calls.push({ op: "findOne", objectNameSingular, payload: filter });
      const match = table(objectNameSingular).find((candidate) =>
        Object.entries(filter).every(
          ([field, value]) => candidate[field] === value,
        ),
      );
      return Promise.resolve(match ?? null);
    },

    create: (objectNameSingular: string, fields: CoreFields) => {
      calls.push({ op: "create", objectNameSingular, payload: fields });
      minted += 1;
      const created: CoreRecord = {
        ...fields,
        id: `${objectNameSingular}-minted-${String(minted)}`,
      };
      table(objectNameSingular).push(created);
      return Promise.resolve(created);
    },

    update: (
      objectNameSingular: string,
      recordId: string,
      fields: CoreFields,
    ) => {
      calls.push({
        op: "update",
        objectNameSingular,
        recordId,
        payload: fields,
      });
      const records = table(objectNameSingular);
      const index = records.findIndex((candidate) => candidate.id === recordId);
      if (index === -1) {
        throw new Error(`no ${objectNameSingular} with id ${recordId}`);
      }
      const updated: CoreRecord = {
        ...records[index],
        ...fields,
        id: recordId,
      };
      records[index] = updated;
      return Promise.resolve(updated);
    },
  };
};

const PATIENT: CoreRecord = {
  id: "patient-1",
  canonicalPatientId: "spine-000001",
  sfdcId: "003XX000012345",
};
const PROGRAM: CoreRecord = { id: "program-1", code: "diabetes-mgmt" };

/** A pair row with both dimensions populated at the same instant. */
const pairRow = (asOf: string): CoreRecord => ({
  id: "pair-1",
  patientId: PATIENT.id,
  programId: PROGRAM.id,
  lifecycleStatus: "on_hold",
  lifecycleStatusAsOf: asOf,
  qualificationStatus: "open",
  qualificationStatusAsOf: asOf,
});

const patientEvent = (
  overrides: Partial<DomainEventRecord> = {},
): DomainEventRecord => ({
  id: "event-1",
  eventType: "enrollment.active",
  entityType: "patient",
  entityRefSystem: "brook",
  entityRefId: "spine-000001",
  programCode: "diabetes-mgmt",
  occurredAt: "2026-07-28T14:03:22.000Z",
  ...overrides,
});

describe("first event for a pair creates the PatientProgram row", () => {
  it("creates the pair, binds the event to it, and applies the looked-up status", async () => {
    const client = fakeClient({
      patient: [PATIENT],
      program: [PROGRAM],
      patientProgram: [],
      domainEvent: [{ id: "event-1" }],
    });

    const outcome = await handler({ record: patientEvent(), client });

    expect(outcome).toStrictEqual({
      status: "applied",
      objectNameSingular: "patientProgram",
      recordId: "patientProgram-minted-1",
      statusField: "lifecycleStatus",
      value: "active",
      asOf: "2026-07-28T14:03:22.000Z",
      createdTarget: true,
    });

    const pairs = client.rows("patientProgram");
    expect(pairs).toHaveLength(1);
    expect(pairs[0]).toMatchObject({
      patientId: "patient-1",
      programId: "program-1",
      lifecycleStatus: "active",
      lifecycleStatusAsOf: "2026-07-28T14:03:22.000Z",
    });

    // The pair row is created with relations only: the status arrives through the lookup, not
    // through the create, so a create on a non-projecting event writes no state.
    const create = client
      .writes("patientProgram")
      .find((call) => call.op === "create");
    expect(create?.payload).toStrictEqual({
      patientId: "patient-1",
      programId: "program-1",
    });

    expect(client.row("domainEvent", "event-1")).toStrictEqual({
      id: "event-1",
      patientProgramId: "patientProgram-minted-1",
    });
  });
});

describe("a late event is a no-op on state", () => {
  it("leaves both status and asOf alone when occurredAt is before the guard", async () => {
    const client = fakeClient({
      patient: [PATIENT],
      program: [PROGRAM],
      patientProgram: [pairRow("2026-07-28T14:03:22.000Z")],
      domainEvent: [{ id: "event-1" }],
    });

    const outcome = await handler({
      record: patientEvent({ occurredAt: "2026-07-01T00:00:00.000Z" }),
      client,
    });

    expect(outcome).toStrictEqual({
      status: "late",
      objectNameSingular: "patientProgram",
      recordId: "pair-1",
      statusField: "lifecycleStatus",
    });
    expect(client.row("patientProgram", "pair-1")).toStrictEqual(
      pairRow("2026-07-28T14:03:22.000Z"),
    );
    expect(client.writes("patientProgram")).toStrictEqual([]);
    // The event itself is still logged, and still bound to its pair.
    expect(client.row("domainEvent", "event-1")).toStrictEqual({
      id: "event-1",
      patientProgramId: "pair-1",
    });
  });

  it("treats an event exactly at the guard as late — the boundary is at-or-before", async () => {
    const client = fakeClient({
      patient: [PATIENT],
      program: [PROGRAM],
      patientProgram: [pairRow("2026-07-28T14:03:22.000Z")],
      domainEvent: [{ id: "event-1" }],
    });

    const outcome = await handler({
      record: patientEvent({ occurredAt: "2026-07-28T14:03:22.000Z" }),
      client,
    });

    expect(outcome.status).toBe("late");
    expect(client.writes("patientProgram")).toStrictEqual([]);
  });

  it("applies when occurredAt is after the guard, so the guard is not a blanket stop", async () => {
    const client = fakeClient({
      patient: [PATIENT],
      program: [PROGRAM],
      patientProgram: [pairRow("2026-07-01T00:00:00.000Z")],
      domainEvent: [{ id: "event-1" }],
    });

    const outcome = await handler({ record: patientEvent(), client });

    expect(outcome.status).toBe("applied");
    expect(client.row("patientProgram", "pair-1")).toMatchObject({
      lifecycleStatus: "active",
      lifecycleStatusAsOf: "2026-07-28T14:03:22.000Z",
    });
  });
});

describe("dimensions are isolated", () => {
  it("touches only the qualification pair when a qualification event is handled", async () => {
    const client = fakeClient({
      patient: [PATIENT],
      program: [PROGRAM],
      patientProgram: [pairRow("2026-07-01T00:00:00.000Z")],
      domainEvent: [{ id: "event-1" }],
    });

    const outcome = await handler({
      record: patientEvent({ eventType: "billing_episode.qualified" }),
      client,
    });

    expect(outcome).toMatchObject({
      status: "applied",
      statusField: "qualificationStatus",
      value: "qualified",
    });

    const pair = client.row("patientProgram", "pair-1");
    expect(pair.qualificationStatus).toBe("qualified");
    expect(pair.qualificationStatusAsOf).toBe("2026-07-28T14:03:22.000Z");
    expect(pair.lifecycleStatus).toBe("on_hold");
    expect(pair.lifecycleStatusAsOf).toBe("2026-07-01T00:00:00.000Z");

    // Stated as the write payload too: the update names its own dimension and nothing else.
    expect(client.writes("patientProgram")).toStrictEqual([
      {
        op: "update",
        objectNameSingular: "patientProgram",
        recordId: "pair-1",
        payload: {
          qualificationStatus: "qualified",
          qualificationStatusAsOf: "2026-07-28T14:03:22.000Z",
        },
      },
    ]);
  });

  it("reads its guard from the qualification dimension, not the lifecycle one", async () => {
    // Lifecycle is far in the future, qualification far in the past: a per-row guard would call
    // this late, a per-dimension guard applies it.
    const client = fakeClient({
      patient: [PATIENT],
      program: [PROGRAM],
      patientProgram: [
        {
          ...pairRow("2026-07-01T00:00:00.000Z"),
          lifecycleStatusAsOf: "2027-01-01T00:00:00.000Z",
        },
      ],
      domainEvent: [{ id: "event-1" }],
    });

    const outcome = await handler({
      record: patientEvent({ eventType: "billing_episode.qualified" }),
      client,
    });

    expect(outcome.status).toBe("applied");
    expect(client.row("patientProgram", "pair-1").lifecycleStatusAsOf).toBe(
      "2027-01-01T00:00:00.000Z",
    );
  });
});

describe("an unresolvable ref stops cleanly", () => {
  it("writes nothing and leaves the event's relations empty when the entity is unknown", async () => {
    const client = fakeClient({
      patient: [PATIENT],
      program: [PROGRAM],
      patientProgram: [],
      domainEvent: [{ id: "event-1" }],
    });

    const outcome = await handler({
      record: patientEvent({ entityRefId: "spine-no-such-patient" }),
      client,
    });

    expect(outcome).toStrictEqual({
      status: "unresolved",
      reason: "entity-not-found",
    });
    expect(client.calls.every((call) => call.op === "findOne")).toBe(true);
    expect(client.rows("patientProgram")).toStrictEqual([]);
    // Relations empty is what puts the event in the orphan view.
    expect(client.row("domainEvent", "event-1")).toStrictEqual({
      id: "event-1",
    });
  });

  it("stops on an unknown program code rather than inventing the program", async () => {
    const client = fakeClient({
      patient: [PATIENT],
      program: [PROGRAM],
      patientProgram: [],
      domainEvent: [{ id: "event-1" }],
    });

    const outcome = await handler({
      record: patientEvent({ programCode: "no-such-program" }),
      client,
    });

    expect(outcome).toStrictEqual({
      status: "unresolved",
      reason: "program-not-found",
    });
    expect(client.calls.every((call) => call.op === "findOne")).toBe(true);
    expect(client.rows("program")).toStrictEqual([PROGRAM]);
  });

  it("stops when the ref system names no field on that entity type", async () => {
    const client = fakeClient({
      patient: [PATIENT],
      program: [PROGRAM],
      domainEvent: [{ id: "event-1" }],
    });

    const outcome = await handler({
      record: patientEvent({ entityType: "clinic", entityRefSystem: "mrn" }),
      client,
    });

    expect(outcome).toStrictEqual({
      status: "unresolved",
      reason: "ref-system-not-registered-for-entity-type",
    });
    expect(client.calls).toStrictEqual([]);
  });
});

describe("a lookup miss is a no-op", () => {
  it("writes no state for a catalog event type the lookup has no row for", async () => {
    const client = fakeClient({
      patient: [PATIENT],
      program: [PROGRAM],
      patientProgram: [pairRow("2026-07-01T00:00:00.000Z")],
      domainEvent: [{ id: "event-1" }],
    });

    // `referral.received` is a valid picklist option with no projection row — a registry anchor.
    expect(PROJECTION_LOOKUP["referral.received"]).toBeUndefined();

    const outcome = await handler({
      record: patientEvent({ eventType: "referral.received" }),
      client,
    });

    expect(outcome).toStrictEqual({
      status: "no-lookup-row",
      eventType: "referral.received",
    });
    expect(client.row("patientProgram", "pair-1")).toStrictEqual(
      pairRow("2026-07-01T00:00:00.000Z"),
    );
    // Still bound: an anchor event belongs to its pair, not to the orphan view.
    expect(client.row("domainEvent", "event-1")).toStrictEqual({
      id: "event-1",
      patientProgramId: "pair-1",
    });
  });

  it("creates the pair row with relations only when the miss is also a first event", async () => {
    const client = fakeClient({
      patient: [PATIENT],
      program: [PROGRAM],
      patientProgram: [],
      domainEvent: [{ id: "event-1" }],
    });

    const outcome = await handler({
      record: patientEvent({ eventType: "referral.received" }),
      client,
    });

    expect(outcome.status).toBe("no-lookup-row");
    expect(client.rows("patientProgram")).toStrictEqual([
      {
        id: "patientProgram-minted-1",
        patientId: "patient-1",
        programId: "program-1",
      },
    ]);
  });
});

describe("guards the handler carries beyond the five cases", () => {
  it("refuses to apply when eventType and entityType disagree on the target object", async () => {
    const client = fakeClient({
      clinic: [{ id: "clinic-1", sfdcId: "001XX000098765" }],
      domainEvent: [{ id: "event-1" }],
    });

    const outcome = await handler({
      record: patientEvent({
        entityType: "clinic",
        entityRefSystem: "sfdc",
        entityRefId: "001XX000098765",
        eventType: "enrollment.active",
      }),
      client,
    });

    expect(outcome).toStrictEqual({
      status: "skipped",
      reason: "target-object-mismatch",
    });
    expect(client.writes("clinic")).toStrictEqual([]);
    expect(client.row("domainEvent", "event-1")).toStrictEqual({
      id: "event-1",
      clinicId: "clinic-1",
    });
  });

  it("applies nothing when occurredAt is absent, rather than disarming the guard", async () => {
    const client = fakeClient({
      patient: [PATIENT],
      program: [PROGRAM],
      patientProgram: [pairRow("2026-07-01T00:00:00.000Z")],
      domainEvent: [{ id: "event-1" }],
    });

    const outcome = await handler({
      record: patientEvent({ occurredAt: null }),
      client,
    });

    expect(outcome).toStrictEqual({
      status: "skipped",
      reason: "occurred-at-unusable",
    });
    expect(client.writes("patientProgram")).toStrictEqual([]);
  });

  it("applies to a target whose asOf has never been set", async () => {
    const client = fakeClient({
      patient: [PATIENT],
      program: [PROGRAM],
      patientProgram: [
        {
          id: "pair-1",
          patientId: PATIENT.id,
          programId: PROGRAM.id,
          lifecycleStatus: "pending_start",
          lifecycleStatusAsOf: null,
        },
      ],
      domainEvent: [{ id: "event-1" }],
    });

    const outcome = await handler({ record: patientEvent(), client });

    expect(outcome).toMatchObject({ status: "applied", createdTarget: false });
  });
});

describe("the crosswalk and the definition against the model", () => {
  it("names a real field on a real object for every (entityType, refSystem) pair", () => {
    const byName = new Map(
      ALL_OBJECTS.map((object) => [object.nameSingular, object]),
    );
    for (const [entityType, systems] of Object.entries(ENTITY_CROSSWALK)) {
      const object = byName.get(entityType);
      expect(object, entityType).toBeDefined();
      const fields = new Set(object?.fields.map((field) => field.name));
      for (const field of Object.values(systems)) {
        expect(fields.has(field), `${entityType}.${field}`).toBe(true);
      }
    }
  });

  it("draws its entity types and ref systems from the generated picklists", () => {
    const entityTypes = new Set(
      DOMAIN_EVENT_ENTITY_TYPE_OPTIONS.map((option) => option.value),
    );
    const refSystems = new Set(
      DOMAIN_EVENT_ENTITY_REF_SYSTEM_OPTIONS.map((option) => option.value),
    );

    expect(Object.keys(ENTITY_CROSSWALK).toSorted()).toStrictEqual(
      [...entityTypes].toSorted(),
    );
    for (const [entityType, systems] of Object.entries(ENTITY_CROSSWALK)) {
      for (const system of Object.keys(systems)) {
        expect(refSystems.has(system), `${entityType}: ${system}`).toBe(true);
      }
    }
  });

  it("binds every entity type to a nullable relation the DomainEvent declares", () => {
    const domainEvent = ALL_OBJECTS.find(
      (object) => object.nameSingular === "domainEvent",
    );
    for (const relationField of Object.values(RELATION_FIELD)) {
      const field = domainEvent?.fields.find(
        (candidate) => candidate.name === relationField,
      );
      expect(field?.type, relationField).toBe("RELATION");
      expect(foreignKey(relationField)).toBe(`${relationField}Id`);
    }
  });

  it("registers the projection as an entity, triggered by domainEvent.created", () => {
    // The application config no longer lists logic functions — the CLI derives entities from
    // the file tree — so what this pins is the definition itself: accepted by the SDK, named,
    // triggered by the event the projection exists for, and wired to this handler.
    expect(PROJECT_DOMAIN_EVENT.success).toBe(true);
    expect(PROJECT_DOMAIN_EVENT.config.name).toBe("project-domain-event");
    expect(
      PROJECT_DOMAIN_EVENT.config.databaseEventTriggerSettings,
    ).toStrictEqual({
      eventName: "domainEvent.created",
    });
    expect(PROJECT_DOMAIN_EVENT.config.handler).toBe(handler);
  });

  it("points every projection lookup row at an object and field the model defines", () => {
    for (const [eventType, target] of Object.entries(PROJECTION_LOOKUP)) {
      const object = ALL_OBJECTS.find(
        (candidate) => candidate.nameSingular === target.objectNameSingular,
      );
      expect(object, eventType).toBeDefined();
      const fields = new Set(object?.fields.map((field) => field.name));
      expect(fields.has(target.statusField), eventType).toBe(true);
      expect(fields.has(target.asOfField), eventType).toBe(true);
    }
  });
});
