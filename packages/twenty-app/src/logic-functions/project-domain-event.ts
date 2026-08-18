/**
 * `project-domain-event` — the platform's only real logic inside Twenty, as versioned
 * TypeScript rather than clicks in a workflow builder (`design/platform/pulse-app-scaffold.md`,
 * "Projection as a logic function").
 *
 * Trigger: a DomainEvent record is created. The steps, in the order
 * `design/platform/twenty-data-model.md` §Projection sets and the `twenty-projection-apply`
 * spec requires:
 *
 * 1. **Resolve** the entity by (`entityRefSystem`, `entityRefId`) crosswalk; a patient event
 *    additionally resolves (Patient, `programCode`) → PatientProgram, creating that row on the
 *    first event for the pair.
 * 2. **Orphan stop** — an unresolved reference leaves all three relations empty and returns.
 *    No crash, no state write: the event surfaces in `src/views/domain-event-orphans.view.ts`
 *    rather than being lost or misapplied.
 * 3. **Bind** the resolved target onto the event's relation. This happens whether or not the
 *    event type projects anything: a registry-anchor event (`referral.received`) belongs to its
 *    pair, and leaving it unbound would put it in the orphan view, falsely reporting a
 *    crosswalk gap. The relations are the only DomainEvent fields the app role may write
 *    (`src/roles/app.role.ts`) — the envelope is immutable.
 * 4. **Lookup** the event type in `generated/projection-lookup.ts`. A miss is a logged no-op,
 *    never a crash: the lookup covers the dimensions the model projects, and the catalog holds
 *    more event types than that by design.
 * 5. **Guard, per dimension** — `occurredAt` at or before the target's `<dimension>StatusAsOf`
 *    is a late event: state stays as it is, the event record stays logged. The comparison is
 *    against the `asOfField` the lookup row names and no other, which is what makes a
 *    qualification event unable to touch `lifecycleStatusAsOf`.
 * 6. **Apply** — set the status field and its matching `...AsOf` to `occurredAt`, in one write.
 *
 * Every path returns a `ProjectionOutcome` instead of throwing. The handler runs on a database
 * trigger with nobody to catch an exception, so "what happened" has to be a value: it is what
 * the function logs, and what the tests assert against.
 *
 * PHI: the outcome carries record ids, field names, and catalog values only — never a field
 * value read off a patient record. It is safe to log.
 */

import { PROJECTION_LOOKUP } from "../../generated/projection-lookup";
import { defineLogicFunction } from "twenty-sdk/define";
import { foreignKey, type CoreApiClient, type CoreRecord } from "./core-api";

/**
 * (`entityType`, `entityRefSystem`) → the field carrying that system's identifier.
 *
 * The registered systems are the envelope spec's: `brook` (the DIM_PATIENT_CONFORMED spine, and
 * the canonical patient identity Twenty never mints), `sfdc`, `mrn`, `app`. A pair absent from
 * this table is an unresolvable reference, not an error — `mrn` names no field on a Clinic, and
 * an event claiming one is an orphan to work, exactly like an id that matches no row.
 *
 * Hand-written and hand-checked: `tests/project-domain-event.test.ts` asserts every field named
 * here exists on that object and every system key is a generated `entityRefSystem` option, so
 * this table cannot drift from the model or the catalog without a red test.
 */
export const ENTITY_CROSSWALK = {
  patient: {
    brook: "canonicalPatientId",
    sfdc: "sfdcId",
    mrn: "mrn",
    app: "appUserId",
  },
  provider: { sfdc: "sfdcId" },
  clinic: { sfdc: "sfdcId" },
} as const satisfies Readonly<Record<string, Readonly<Record<string, string>>>>;

export type EntityType = keyof typeof ENTITY_CROSSWALK;

/**
 * Entity type → the DomainEvent relation that points at its projection target. A patient event
 * binds to the pair row, not to the Patient: patient state lives on PatientProgram (grain
 * decision 2026-07-28).
 */
export const RELATION_FIELD = {
  patient: "patientProgram",
  provider: "provider",
  clinic: "clinic",
} as const satisfies Readonly<Record<EntityType, string>>;

/** The projection target object for each entity type — patient events project onto the pair. */
const TARGET_OBJECT = {
  patient: "patientProgram",
  provider: "provider",
  clinic: "clinic",
} as const satisfies Readonly<Record<EntityType, string>>;

/**
 * The DomainEvent fields the handler reads. A subset of the object on purpose: the handler
 * never reads `payload` or `evidence`, so no producer-supplied blob reaches this code path.
 */
export interface DomainEventRecord {
  readonly id: string;
  readonly eventType: string;
  readonly entityType: string | null;
  readonly entityRefSystem: string | null;
  readonly entityRefId: string | null;
  readonly programCode: string | null;
  readonly occurredAt: string | null;
}

export interface ProjectDomainEventInput {
  readonly record: DomainEventRecord;
  readonly client: CoreApiClient;
}

/** Why a reference did not resolve. Named causes, because each one is a different repair. */
export type UnresolvedReason =
  | "entity-type-unknown"
  | "ref-system-not-registered-for-entity-type"
  | "ref-id-missing"
  | "entity-not-found"
  | "program-code-missing"
  | "program-not-found";

/** Why a resolved event still applied nothing, short of being late or having no lookup row. */
export type SkipReason = "occurred-at-unusable" | "target-object-mismatch";

export type ProjectionOutcome =
  | {
      readonly status: "applied";
      readonly objectNameSingular: string;
      readonly recordId: string;
      readonly statusField: string;
      readonly value: string;
      readonly asOf: string;
      readonly createdTarget: boolean;
    }
  | { readonly status: "unresolved"; readonly reason: UnresolvedReason }
  | {
      readonly status: "late";
      readonly objectNameSingular: string;
      readonly recordId: string;
      readonly statusField: string;
    }
  | { readonly status: "no-lookup-row"; readonly eventType: string }
  | { readonly status: "skipped"; readonly reason: SkipReason };

type Resolution<T> =
  | { readonly ok: true; readonly value: T }
  | { readonly ok: false; readonly reason: UnresolvedReason };

interface ResolvedTarget {
  /** The DomainEvent relation field to bind. */
  readonly relationField: string;
  readonly objectNameSingular: string;
  readonly record: CoreRecord;
  /** True when this run created the PatientProgram row — first event for the pair. */
  readonly created: boolean;
}

const isEntityType = (value: string | null): value is EntityType =>
  value !== null && Object.hasOwn(ENTITY_CROSSWALK, value);

/** Milliseconds, or `null` when the value is absent or not a parseable instant. */
const instant = (value: unknown): number | null => {
  if (typeof value !== "string") return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
};

/** (`entityRefSystem`, `entityRefId`) → the Patient, Provider, or Clinic it names. */
const resolveEntity = async (
  record: DomainEventRecord,
  client: CoreApiClient,
): Promise<Resolution<{ entityType: EntityType; record: CoreRecord }>> => {
  const { entityType, entityRefSystem, entityRefId } = record;
  if (!isEntityType(entityType)) {
    return { ok: false, reason: "entity-type-unknown" };
  }

  const crosswalk: Readonly<Record<string, string>> =
    ENTITY_CROSSWALK[entityType];
  const field =
    entityRefSystem === null ? undefined : crosswalk[entityRefSystem];
  if (field === undefined) {
    return { ok: false, reason: "ref-system-not-registered-for-entity-type" };
  }
  if (entityRefId === null || entityRefId === "") {
    return { ok: false, reason: "ref-id-missing" };
  }

  const found = await client.findOne(entityType, { [field]: entityRefId });
  if (found === null) return { ok: false, reason: "entity-not-found" };
  return { ok: true, value: { entityType, record: found } };
};

/**
 * (Patient, `programCode`) → the PatientProgram row, created on the first event for the pair.
 *
 * The Program itself is looked up, never created: the projection pairs identities that already
 * exist and invents neither (`src/roles/app.role.ts` grants it read-only on Patient and
 * Program). An unknown program code is therefore an orphan, not a new program.
 */
const resolvePatientProgram = async (
  record: DomainEventRecord,
  client: CoreApiClient,
  patient: CoreRecord,
): Promise<Resolution<{ record: CoreRecord; created: boolean }>> => {
  const code = record.programCode;
  if (code === null || code === "") {
    return { ok: false, reason: "program-code-missing" };
  }

  const program = await client.findOne("program", { code });
  if (program === null) return { ok: false, reason: "program-not-found" };

  const pairFilter = {
    [foreignKey("patient")]: patient.id,
    [foreignKey("program")]: program.id,
  };
  const existing = await client.findOne("patientProgram", pairFilter);
  if (existing !== null) {
    return { ok: true, value: { record: existing, created: false } };
  }

  // Relations only. The status pair takes its declared defaults; whether this event sets a
  // status is the lookup's business, downstream of here.
  const created = await client.create("patientProgram", pairFilter);
  return { ok: true, value: { record: created, created: true } };
};

const resolveTarget = async (
  record: DomainEventRecord,
  client: CoreApiClient,
): Promise<Resolution<ResolvedTarget>> => {
  const entity = await resolveEntity(record, client);
  if (!entity.ok) return entity;

  const { entityType } = entity.value;
  if (entityType !== "patient") {
    return {
      ok: true,
      value: {
        relationField: RELATION_FIELD[entityType],
        objectNameSingular: TARGET_OBJECT[entityType],
        record: entity.value.record,
        created: false,
      },
    };
  }

  const pair = await resolvePatientProgram(record, client, entity.value.record);
  if (!pair.ok) return pair;
  return {
    ok: true,
    value: {
      relationField: RELATION_FIELD.patient,
      objectNameSingular: TARGET_OBJECT.patient,
      record: pair.value.record,
      created: pair.value.created,
    },
  };
};

export const handler = async ({
  record,
  client,
}: ProjectDomainEventInput): Promise<ProjectionOutcome> => {
  const target = await resolveTarget(record, client);
  if (!target.ok) return { status: "unresolved", reason: target.reason };

  await client.update("domainEvent", record.id, {
    [foreignKey(target.value.relationField)]: target.value.record.id,
  });

  const lookup = PROJECTION_LOOKUP[record.eventType];
  if (lookup === undefined) {
    return { status: "no-lookup-row", eventType: record.eventType };
  }
  if (lookup.objectNameSingular !== target.value.objectNameSingular) {
    // `entityType` disagrees with the noun in `eventType` (envelope spec, field rules). Writing
    // the lookup's field onto whatever resolved is how a lifecycle status lands on a Clinic.
    return { status: "skipped", reason: "target-object-mismatch" };
  }

  const occurredAt = record.occurredAt;
  if (occurredAt === null || instant(occurredAt) === null) {
    // Without a business time there is nothing to stamp the guard with, and applying a status
    // with a null `...AsOf` would disarm LWW for that dimension permanently.
    return { status: "skipped", reason: "occurred-at-unusable" };
  }

  const asOf = instant(target.value.record[lookup.asOfField]);
  if (asOf !== null && Date.parse(occurredAt) <= asOf) {
    return {
      status: "late",
      objectNameSingular: target.value.objectNameSingular,
      recordId: target.value.record.id,
      statusField: lookup.statusField,
    };
  }

  // One write, one dimension: the status field and its own `...AsOf`, never the other pair.
  await client.update(target.value.objectNameSingular, target.value.record.id, {
    [lookup.statusField]: lookup.value,
    [lookup.asOfField]: occurredAt,
  });

  return {
    status: "applied",
    objectNameSingular: target.value.objectNameSingular,
    recordId: target.value.record.id,
    statusField: lookup.statusField,
    value: lookup.value,
    asOf: occurredAt,
    createdTarget: target.value.created,
  };
};

/**
 * The default export is the inline call: the CLI's manifest builder detects entities
 * syntactically, and the const-then-default form is invisible to it.
 */
export default defineLogicFunction({
  // Minted 2026-08-17 (task 6.4): the SDK requires an identifier on a logic function. It lives
  // here rather than in uid-map.json because `uid_map_diff` rejects any key the Python model
  // never asks for; moving it into the map is proposed in HANDOFF.md.
  universalIdentifier: "767312d9-690b-4148-8269-2117ce402a54",
  name: "project-domain-event",
  timeoutSeconds: 10,
  handler,
  databaseEventTriggerSettings: { eventName: "domainEvent.created" },
});
